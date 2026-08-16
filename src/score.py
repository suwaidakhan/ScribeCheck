"""Metrics M1 through M5, SPEC section 5.

M1 through M4 are measured over the reference, never over the hypothesis. A
provider that invents a drug it was never asked to transcribe is doing
something bad, but it is not failing to transcribe a drug, and mixing the two
would let a provider improve its drug accuracy by hallucinating more drugs.

That reasoning is why the hypothesis side is reported beside M2 rather than
folded into it. `drug_accuracy` is recall over reference mentions and still
means exactly what it meant when it was published. `drug_precision` and
`drug_f1` answer the separate question of how much of what a provider wrote was
ever said, and they are the only numbers here computed over the hypothesis.
Both directions are needed: recall alone scores a silent system and a
confabulating one the same way, and silence is the safer failure.

Where SPEC leaves a judgment call, it is made once here, applied identically to
all five configurations, and recorded in docs/DECISIONS.md.

Run:  python -m src.score
"""

from __future__ import annotations

import math
import sys
from itertools import combinations

import jiwer
import pandas as pd
from rapidfuzz.distance import Levenshtein
from whisper_normalizer.english import EnglishTextNormalizer

from src import config
from src.entities import (
    find_dose_pairs,
    find_drug_mentions,
    find_negations,
    strip_spoken_punctuation,
)
from src.lexicon import load as load_lexicon

# SPEC section 5: one normalizer, applied to reference and hypothesis alike.
normalize = EnglishTextNormalizer()

# How far from a reference entity's aligned position the hypothesis is searched.
# SPEC names 5 tokens for negation (M4); the same window is used for the drug
# substitution test so both metrics mean "in roughly the same place in the
# sentence" rather than "anywhere in the clip". See DECISIONS D013.
ALIGNMENT_WINDOW = 5

# SPEC M2 allows edit distance 1 for pluralisation or minor spelling.
DRUG_EDIT_TOLERANCE = 1


def _tokens(text: str) -> list[str]:
    return text.split()


def _window(
    tokens: list[str], centre: int, radius: int = ALIGNMENT_WINDOW
) -> list[str]:
    return tokens[max(0, centre - radius) : centre + radius + 1]


def _aligned_centre(ref_index: int, ref_len: int, hyp_len: int) -> int:
    """Where a reference token at `ref_index` is expected to land in the hypothesis.

    Proportional rather than absolute, so a hypothesis that dropped or added
    words earlier in the clip does not drag every later entity out of its window.
    """
    if ref_len <= 1:
        return 0
    return round(ref_index / (ref_len - 1) * max(hyp_len - 1, 0))


def score_wer(reference: str, hypothesis: str) -> float | None:
    """M1. Word error rate. None when the reference is empty.

    An empty reference has no denominator, and jiwer returns infinity for it,
    which would poison every mean it is averaged into.
    """
    if not reference.strip():
        return None
    return jiwer.wer(reference, hypothesis)


def score_drugs(reference: str, hypothesis: str, lexicon: set[str]) -> dict:
    """M2. Per reference drug mention: correct, substitution, or deletion.

    Substitution is the class that matters. A drug dropped leaves a hole a
    reader may notice; a drug replaced by a different real drug reads as a
    complete, plausible sentence and is the failure that reaches a patient.

    `mentions`, `correct`, `substitution` and `deletion` are the recall side and
    are counted over the reference, unchanged. `hyp_mentions` and
    `false_positive` are the other direction: drug names the provider wrote
    that were never said. They are separate counts rather than adjustments to
    the first four, because a hallucinated drug is a different failure from a
    missed one and the taxonomy codes them apart.
    """
    ref_tokens = _tokens(reference)
    hyp_tokens = _tokens(hypothesis)
    mentions = find_drug_mentions(reference, lexicon)

    result = {
        "mentions": len(mentions),
        "correct": 0,
        "substitution": 0,
        "deletion": 0,
        **_count_false_positives(
            mentions, find_drug_mentions(hypothesis, lexicon), ref_tokens
        ),
    }
    if not mentions:
        return result

    for mention in mentions:
        try:
            ref_index = ref_tokens.index(mention)
        except ValueError:
            # A multi-word lexicon term does not appear as a single token.
            ref_index = 0

        if any(
            Levenshtein.distance(mention, token) <= DRUG_EDIT_TOLERANCE
            for token in hyp_tokens
        ):
            result["correct"] += 1
            continue

        centre = _aligned_centre(ref_index, len(ref_tokens), len(hyp_tokens))
        nearby = _window(hyp_tokens, centre)
        # A substitute has to be a drug the reference never asked for. Another
        # reference drug sitting nearby is not evidence that this one was
        # swapped: it is its own mention, scored on its own line, and it is
        # usually there because it was transcribed correctly.
        #
        # Without this, row 10 read as a substitution. trimethoprim was
        # destroyed into "trimethropium", a non-word, and pyrimethamine two
        # words away took the blame despite being perfect. 14 of the 19
        # substitutions in the first full run were produced this way, which put
        # Whisper's headline count at 7 when the true figure is 1.
        others = set(mentions) - {mention}
        if any(
            token in lexicon and token != mention and token not in others
            for token in nearby
        ):
            result["substitution"] += 1
        else:
            result["deletion"] += 1

    return result


def _count_false_positives(
    ref_mentions: list[str],
    hyp_mentions: list[str],
    ref_tokens: list[str] | None = None,
) -> dict[str, int]:
    """Hypothesis drug mentions with no reference mention to account for them.

    Matched greedily and one for one, on the same edit distance the recall side
    allows, so "metformim" for "metformin" is not counted as an invention in
    one direction while being counted correct in the other. Saying a drug once
    and writing it twice leaves the second copy unaccounted for, which is what
    the greedy pass is for.

    A substituted drug is a false positive as well as a recall miss. Both
    statements are true of it: the drug that was said is gone, and a drug that
    was never said is on the page.

    `ref_tokens` is the whole reference, not only its lexicon matches, and it is
    the guard against charging a provider for the lexicon's gaps. 10 of the 35
    false positives in the first run were this: the reference reads `propanolol`,
    which is a misspelling and therefore in no lexicon and therefore not a
    mention, so three providers that wrote `propranolol` correctly were each
    recorded as having invented a drug. `hydrocloride` was in the lexicon while
    `hydrochloride` was not, and `insulins` matched nothing, with the same
    result. A drug within the edit tolerance of something the clinician actually
    said was not invented, whatever the lexicon knows about it.
    """
    unclaimed = list(ref_mentions)
    spoken = list(ref_tokens or [])
    false_positives = 0
    for written in hyp_mentions:
        # Closest first, so a fuzzy match cannot consume the reference mention
        # that some later hypothesis token matches exactly and strand it.
        nearest = min(
            unclaimed,
            key=lambda mention: Levenshtein.distance(mention, written),
            default=None,
        )
        matched = (
            nearest is not None
            and Levenshtein.distance(nearest, written) <= DRUG_EDIT_TOLERANCE
        )
        if matched:
            unclaimed.remove(nearest)
            # Spend the spoken word too, so the fallback below cannot forgive a
            # second copy of a drug that was only said once.
            if nearest in spoken:
                spoken.remove(nearest)
            continue
        # The clinician said something within a character of this. Whether the
        # lexicon holds their spelling of it is not the provider's fault.
        #
        # Consumed one for one, exactly like the mention list above, because
        # "warfarin" said once and written twice leaves the second copy
        # unaccounted for and that is a real invention. Matching against the
        # reference without consuming would forgive every duplicate.
        said = next(
            (
                token
                for token in spoken
                if Levenshtein.distance(token, written) <= DRUG_EDIT_TOLERANCE
            ),
            None,
        )
        if said is not None:
            spoken.remove(said)
            continue
        false_positives += 1
    return {"hyp_mentions": len(hyp_mentions), "false_positive": false_positives}


def score_doses(reference: str, hypothesis: str) -> dict:
    """M3. A dose is correct only if value and unit both survive.

    Value errors and unit errors are reported apart because they are not the
    same risk: 50 mg for 500 mg is a tenfold dosing error, while mg for mcg on
    an intact value is usually caught by whoever reads it.
    """
    ref_doses = find_dose_pairs(reference)
    hyp_doses = find_dose_pairs(hypothesis)

    result = {
        "doses": len(ref_doses),
        "correct": 0,
        "value_error": 0,
        "unit_error": 0,
        "missing": 0,
    }
    available = list(hyp_doses)

    for value, unit in ref_doses:
        exact = next((pair for pair in available if pair == (value, unit)), None)
        if exact is not None:
            available.remove(exact)
            result["correct"] += 1
            continue

        same_unit = next((pair for pair in available if pair[1] == unit), None)
        if same_unit is not None:
            available.remove(same_unit)
            result["value_error"] += 1
            continue

        same_value = next((pair for pair in available if pair[0] == value), None)
        if same_value is not None:
            available.remove(same_value)
            result["unit_error"] += 1
            continue

        result["missing"] += 1

    return result


def score_negations(reference: str, hypothesis: str) -> dict:
    """M4. Does each reference negation cue survive near where it belongs?

    Position is load-bearing. "No fever, cough present" and "fever, no cough
    present" carry the same cue and opposite meanings, so presence alone would
    score the second as a success.
    """
    ref_tokens = _tokens(reference)
    hyp_tokens = _tokens(hypothesis)
    cues = find_negations(reference)

    result = {"cues": len(cues), "preserved": 0, "lost": 0}
    for cue, ref_index in cues:
        centre = _aligned_centre(ref_index, len(ref_tokens), len(hyp_tokens))
        nearby = " ".join(_window(hyp_tokens, centre))
        if any(found == cue for found, _ in find_negations(nearby)):
            result["preserved"] += 1
        else:
            result["lost"] += 1
    return result


def score_clip(reference: str, hypothesis: str, lexicon: set[str]) -> dict:
    """Every metric for one clip and one provider, on normalized text.

    Two word error rates, W9. `wer` is what the providers were charged for,
    every word they wrote against every word in the reference. Speakers in this
    dataset read the punctuation aloud, and vendors disagree about what to do
    with it: AssemblyAI writes a comma character, which the normalizer strips,
    while Deepgram writes the word "comma" and takes an insertion error for it.
    `wer_spoken_punct_removed` takes those words off both sides, so it compares
    recognition without the formatting convention.

    Neither one is the true number. Measured on this sample, the gap is 18 to
    30 percent of the error of every provider except AssemblyAI, whose gap is
    zero because it emits characters instead of words. That is the finding: WER
    is sensitive to a vendor formatting choice that has nothing to do with what
    the model heard.

    Entity metrics are computed on the as-scored text, because no punctuation
    word is a drug, a unit, a number or a negation cue, so stripping cannot
    move them.
    """
    ref = normalize(str(reference))
    hyp = normalize(str(hypothesis))
    drugs = score_drugs(ref, hyp, lexicon)
    doses = score_doses(ref, hyp)
    negations = score_negations(ref, hyp)
    return {
        "wer": score_wer(ref, hyp),
        "wer_spoken_punct_removed": score_wer(
            strip_spoken_punctuation(ref), strip_spoken_punctuation(hyp)
        ),
        "drug_mentions": drugs["mentions"],
        "drug_correct": drugs["correct"],
        "drug_substitution": drugs["substitution"],
        "drug_deletion": drugs["deletion"],
        "drug_hyp_mentions": drugs["hyp_mentions"],
        "drug_false_positive": drugs["false_positive"],
        "doses": doses["doses"],
        "dose_correct": doses["correct"],
        "dose_value_error": doses["value_error"],
        "dose_unit_error": doses["unit_error"],
        "dose_missing": doses["missing"],
        "negation_cues": negations["cues"],
        "negation_preserved": negations["preserved"],
        "negation_lost": negations["lost"],
    }


# Below this many disagreements the chi-square approximation is unreliable and
# the exact binomial is used instead. The conventional threshold.
MCNEMAR_EXACT_BELOW = 25

# A clip counts as a success for a metric when every reference entity of that
# kind survived it. The denominator is the first column: a clip with no drug
# mention cannot succeed or fail at drugs, so it is not a pair.
#
# The dose rule matches the published `dose_value_accuracy`, where a surviving
# value with the wrong unit still counts. Two definitions of a correct dose in
# one repo is how a headline and its significance test start disagreeing.
PAIRED_METRICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "drug": ("drug_mentions", ("drug_correct",)),
    "dose": ("doses", ("dose_correct", "dose_unit_error")),
    "negation": ("negation_cues", ("negation_preserved",)),
}


def mcnemar(a_only: int, b_only: int) -> dict:
    """McNemar's paired test on two counts of disagreement.

    `a_only` is the number of clips the first provider got right and the second
    got wrong, `b_only` the reverse. Clips both got right and clips both got
    wrong carry no information about which is better and are not used, which is
    the whole point of a paired test.

    Exact binomial below `MCNEMAR_EXACT_BELOW` disagreements, chi-square with
    Edwards' continuity correction above it. No scipy: the chi-square survival
    function with one degree of freedom is erfc(sqrt(x / 2)), and the binomial
    tail is a sum of math.comb terms, so both are stdlib.

    What this does NOT account for: the 400 clips come from 247 speakers and 99
    of those contribute more than one clip, so the pairs are not independent
    draws. The test assumes they are. The p-value is therefore optimistic, and
    a speaker-blocked bootstrap is the correct fix. That is W12, and it is not
    done here. Read any p-value below as an upper bound on the evidence, not a
    measurement of it.
    """
    discordant = a_only + b_only
    # Edwards' correction, floored at zero so a perfectly symmetric split gives
    # a statistic of 0 rather than a small positive number.
    statistic = (
        max(abs(a_only - b_only) - 1, 0) ** 2 / discordant if discordant else 0.0
    )

    if discordant < MCNEMAR_EXACT_BELOW:
        smaller = min(a_only, b_only)
        tail = sum(math.comb(discordant, k) for k in range(smaller + 1))
        p_value = min(1.0, 2 * tail / 2**discordant)
        test = "exact"
    else:
        p_value = math.erfc(math.sqrt(statistic / 2))
        test = "chi2"

    return {
        "a_only": a_only,
        "b_only": b_only,
        "discordant": discordant,
        "statistic": statistic,
        "p_value": p_value,
        "test": test,
    }


def paired_significance(per_clip: pd.DataFrame, metric: str = "drug") -> pd.DataFrame:
    """McNemar's test for every provider pair, on per-clip outcomes.

    The same 400 clips went to all five providers, so a difference between two
    of them is matched-pairs data and the unpaired comparison the writeup
    currently makes throws that away.

    The unit of pairing is the clip, not the entity mention, because the clip
    is what `per_clip_scores.csv` records. A clip with four drug mentions counts
    once, and it counts as a success only if all four survived. That is a
    stricter outcome than per-mention accuracy and it is not the same quantity
    as `drug_accuracy`; the p-value says whether one provider beats another on
    clips, and the headline percentage stays the mention-level number.

    Independence is assumed and is not true. See `mcnemar`.
    """
    if metric not in PAIRED_METRICS:
        raise ValueError(
            f"{metric!r} has no binary per-clip outcome. McNemar's test needs "
            f"paired binary data; choose one of {sorted(PAIRED_METRICS)}. WER is "
            "continuous and dichotomising it would invent a threshold nobody "
            "chose."
        )

    denominator, survived = PAIRED_METRICS[metric]
    frame = per_clip[per_clip[denominator] > 0]
    outcomes = {
        provider: (
            group.set_index("clip_id")[list(survived)].sum(axis=1)
            == group.set_index("clip_id")[denominator]
        )
        for provider, group in frame.groupby("provider")
    }

    rows = []
    for first, second in combinations(sorted(outcomes), 2):
        a, b = outcomes[first].align(outcomes[second], join="inner")
        result = mcnemar(int((a & ~b).sum()), int((b & ~a).sum()))
        rows.append(
            {
                "metric": metric,
                "provider_a": first,
                "provider_b": second,
                "n_pairs": int(len(a)),
                "a_clips_correct": int(a.sum()),
                "b_clips_correct": int(b.sum()),
                **result,
            }
        )
    return pd.DataFrame(rows)


def load_cached_transcripts() -> pd.DataFrame:
    """Every cached provider response, as one row per clip and provider."""
    import json

    rows = []
    for provider_dir in sorted(config.CACHE.glob("*")):
        if not provider_dir.is_dir() or provider_dir.name.startswith("_"):
            continue
        for path in sorted(provider_dir.glob("*.json")):
            rows.append(json.loads(path.read_text()))
    return pd.DataFrame(rows)


def build() -> pd.DataFrame:
    """Score every cached transcript against the manifest and write results/."""
    lexicon = load_lexicon()
    manifest = pd.read_csv(config.MANIFEST)
    cached = load_cached_transcripts()

    if cached.empty:
        raise SystemExit(
            "No cached transcripts in data/cache/. Run `python -m src.transcribe` "
            "first, which needs the four API keys in .env."
        )

    merged = cached.merge(
        manifest[["clip_id", "accent", "tier", "domain", "duration", "transcript"]],
        on="clip_id",
        how="inner",
    )
    print(
        f"Scoring {len(merged)} transcripts across {merged['provider'].nunique()} providers."
    )

    scores = pd.DataFrame(
        [
            score_clip(row["transcript"], row["text"], lexicon)
            for _, row in merged.iterrows()
        ]
    )
    per_clip = pd.concat(
        [
            merged[["clip_id", "provider", "accent", "tier", "domain", "duration"]],
            scores,
        ],
        axis=1,
    )

    config.RESULTS.mkdir(parents=True, exist_ok=True)
    per_clip.to_csv(config.RESULTS / "per_clip_scores.csv", index=False)

    headline = summarise(per_clip, merged)
    headline.to_csv(config.RESULTS / "headline.csv", index=False)
    summarise(per_clip, merged, by="tier").to_csv(
        config.RESULTS / "by_tier.csv", index=False
    )
    summarise(per_clip, merged, by="domain").to_csv(
        config.RESULTS / "by_domain.csv", index=False
    )
    summarise(per_clip, merged, by="accent").to_csv(
        config.RESULTS / "by_accent.csv", index=False
    )
    pd.concat(
        [paired_significance(per_clip, metric=metric) for metric in PAIRED_METRICS]
    ).to_csv(config.RESULTS / "significance.csv", index=False)

    print(headline.to_string(index=False))
    print(f"\nWrote {config.RESULTS}/headline.csv and the breakdowns.")
    return headline


def summarise(
    per_clip: pd.DataFrame, merged: pd.DataFrame, by: str | None = None
) -> pd.DataFrame:
    """Aggregate per-clip scores into the SPEC section 5 headline shape.

    Entity accuracies are ratios of summed counts, not means of per-clip
    ratios. A clip with one drug mention and a clip with four must not carry
    the same weight, which is what averaging per-clip accuracy would do.
    """
    keys = ["provider"] + ([by] if by else [])
    rows = []
    for values, group in per_clip.groupby(keys, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        row = dict(zip(keys, values))
        row["clips"] = len(group)
        row["wer"] = group["wer"].mean()
        row["wer_spoken_punct_removed"] = group["wer_spoken_punct_removed"].mean()
        # What share of this provider's measured error was punctuation it was
        # told to write. Deepgram runs with smart_format off, deliberately, to
        # protect dosage scoring, and pays for it here.
        row["wer_spoken_punct_share"] = _ratio(
            row["wer"] - row["wer_spoken_punct_removed"], row["wer"]
        )
        row["drug_mentions"] = int(group["drug_mentions"].sum())
        row["drug_accuracy"] = _ratio(
            group["drug_correct"].sum(), group["drug_mentions"].sum()
        )
        # W11. Recall over reference mentions is `drug_accuracy` and is
        # unchanged. Precision is over what the provider wrote, so a provider
        # that invents drug names is finally charged for it somewhere.
        row["drug_hyp_mentions"] = int(group["drug_hyp_mentions"].sum())
        row["drug_false_positives"] = int(group["drug_false_positive"].sum())
        row["drug_precision"] = _ratio(
            group["drug_hyp_mentions"].sum() - group["drug_false_positive"].sum(),
            group["drug_hyp_mentions"].sum(),
        )
        row["drug_f1"] = _harmonic_mean(row["drug_precision"], row["drug_accuracy"])
        row["drug_substitutions"] = int(group["drug_substitution"].sum())
        row["doses"] = int(group["doses"].sum())
        row["dose_value_accuracy"] = _ratio(
            group["dose_correct"].sum() + group["dose_unit_error"].sum(),
            group["doses"].sum(),
        )
        row["dose_value_errors"] = int(group["dose_value_error"].sum())
        row["dose_unit_errors"] = int(group["dose_unit_error"].sum())
        row["negation_cues"] = int(group["negation_cues"].sum())
        row["negation_preservation"] = _ratio(
            group["negation_preserved"].sum(), group["negation_cues"].sum()
        )
        rows.append(row)

    summary = pd.DataFrame(rows)
    if not by:
        summary = summary.merge(_cost_per_hour(merged), on="provider", how="left")
    return summary.sort_values(keys).reset_index(drop=True)


def _ratio(numerator, denominator) -> float | None:
    """None rather than 0 when there is nothing to divide by.

    A provider with no drug mentions to get wrong has an undefined accuracy,
    not a perfect one and not a zero.
    """
    return float(numerator) / float(denominator) if denominator else None


def _harmonic_mean(precision: float | None, recall: float | None) -> float | None:
    """F1, or None when either side has no denominator to be measured on.

    A provider with nothing to be precise about does not have an F1 of zero, it
    has no F1, same rule as `_ratio`.
    """
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _cost_per_hour(merged: pd.DataFrame) -> pd.DataFrame:
    """M5. Cost per audio hour and median latency, beside the quality columns."""
    rows = []
    for provider, group in merged.groupby("provider"):
        hours = group["audio_seconds"].sum() / 3600
        rows.append(
            {
                "provider": provider,
                "cost_per_audio_hour": group["cost_usd"].sum() / hours
                if hours
                else None,
                "median_latency_ms": group["latency_ms"].median(),
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    build()
    sys.exit(0)
