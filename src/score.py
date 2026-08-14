"""Metrics M1 through M5, SPEC section 5.

Every metric is measured over reference mentions, never hypothesis mentions.
A provider that invents a drug it was never asked to transcribe is doing
something bad, but it is not failing to transcribe a drug, and mixing the two
would let a provider improve its drug accuracy by hallucinating more drugs.

Where SPEC leaves a judgment call, it is made once here, applied identically to
all five configurations, and recorded in docs/DECISIONS.md.

Run:  python -m src.score
"""

from __future__ import annotations

import sys

import jiwer
import pandas as pd
from rapidfuzz.distance import Levenshtein
from whisper_normalizer.english import EnglishTextNormalizer

from src import config
from src.entities import find_dose_pairs, find_drug_mentions, find_negations
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
    """
    ref_tokens = _tokens(reference)
    hyp_tokens = _tokens(hypothesis)
    mentions = find_drug_mentions(reference, lexicon)

    result = {"mentions": len(mentions), "correct": 0, "substitution": 0, "deletion": 0}
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
    """Every metric for one clip and one provider, on normalized text."""
    ref = normalize(str(reference))
    hyp = normalize(str(hypothesis))
    drugs = score_drugs(ref, hyp, lexicon)
    doses = score_doses(ref, hyp)
    negations = score_negations(ref, hyp)
    return {
        "wer": score_wer(ref, hyp),
        "drug_mentions": drugs["mentions"],
        "drug_correct": drugs["correct"],
        "drug_substitution": drugs["substitution"],
        "drug_deletion": drugs["deletion"],
        "doses": doses["doses"],
        "dose_correct": doses["correct"],
        "dose_value_error": doses["value_error"],
        "dose_unit_error": doses["unit_error"],
        "dose_missing": doses["missing"],
        "negation_cues": negations["cues"],
        "negation_preserved": negations["preserved"],
        "negation_lost": negations["lost"],
    }


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
        row["drug_mentions"] = int(group["drug_mentions"].sum())
        row["drug_accuracy"] = _ratio(
            group["drug_correct"].sum(), group["drug_mentions"].sum()
        )
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
