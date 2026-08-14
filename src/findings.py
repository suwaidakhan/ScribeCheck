"""One record per error, which is what a human can actually label.

The metrics in `score.py` return counts, and counts turned out to be the wrong
primitive for the labelling sheet. Three things went wrong because of it, all
recorded in docs/PRD_EVAL_V2.md:

- a clip with several errors arrived as one row carrying one dropdown (W5),
- the sheet took one row per clip, so the largest error class reached it at 5
  percent coverage while three others reached 100 percent (W3),
- the excerpt centred on the first textual difference, which is usually
  capitalisation, so 15 of 100 rows hid the clinical entity being judged (W2).

A finding fixes all three. It names what was expected, what was heard instead,
and where in the reference it sits, so the sheet can take one row per error,
sample proportionally across kinds, and centre each row on its own entity.

Counts remain derivable from findings, so `score.py` keeps its published
metrics. This module adds detail; it does not replace the numbers.
"""

from __future__ import annotations

import pandas as pd
from rapidfuzz.distance import Levenshtein

from src.entities import find_dose_pairs, find_drug_mentions, find_negations

# Shared with score.py. Kept here rather than imported to avoid a cycle, and
# asserted equal in the tests so the two cannot drift apart.
ALIGNMENT_WINDOW = 5
DRUG_EDIT_TOLERANCE = 1


def _tokens(text: str) -> list[str]:
    return text.split()


def _window(
    tokens: list[str], centre: int, radius: int = ALIGNMENT_WINDOW
) -> list[str]:
    return tokens[max(0, centre - radius) : centre + radius + 1]


def _aligned_centre(ref_index: int, ref_len: int, hyp_len: int) -> int:
    if ref_len <= 1:
        return 0
    return round(ref_index / (ref_len - 1) * max(hyp_len - 1, 0))


def drug_findings(reference: str, hypothesis: str, lexicon: set[str]) -> list[dict]:
    """One finding per reference drug that did not survive.

    A drug swapped for a different real drug and a drug destroyed into a
    non-word are different failures and get different kinds, because the first
    still reads as a valid clinical sentence and the second does not.

    A surviving reference drug is never offered as the substitute for a broken
    one. That mistake produced 14 of the 19 substitutions in the first full run.
    """
    ref_tokens, hyp_tokens = _tokens(reference), _tokens(hypothesis)
    mentions = find_drug_mentions(reference, lexicon)
    others = set(mentions)

    found = []
    for mention in mentions:
        if any(
            Levenshtein.distance(mention, token) <= DRUG_EDIT_TOLERANCE
            for token in hyp_tokens
        ):
            continue

        try:
            ref_index = ref_tokens.index(mention)
        except ValueError:
            ref_index = 0

        centre = _aligned_centre(ref_index, len(ref_tokens), len(hyp_tokens))
        substitutes = [
            token
            for token in _window(hyp_tokens, centre)
            if token in lexicon and token != mention and token not in others
        ]
        found.append(
            {
                "kind": "DRUG-SUB" if substitutes else "DRUG-DEL",
                "expected": mention,
                "heard": substitutes[0] if substitutes else "",
                "ref_index": ref_index,
            }
        )
    return found


def dose_findings(reference: str, hypothesis: str) -> list[dict]:
    """One finding per reference dose that did not survive intact.

    A changed number and a changed unit are separated because they are not the
    same risk: 50 mg for 500 mg is a tenfold dosing error, while mg for mcg on
    an intact number is usually caught by whoever reads it.
    """
    ref_tokens = _tokens(reference)
    ref_doses = find_dose_pairs(reference)
    available = list(find_dose_pairs(hypothesis))

    found = []
    for value, unit in ref_doses:
        if (value, unit) in available:
            available.remove((value, unit))
            continue

        ref_index = next(
            (
                i
                for i, t in enumerate(ref_tokens)
                if t == str(value) or t == f"{value:g}"
            ),
            0,
        )
        same_unit = next((p for p in available if p[1] == unit), None)
        same_value = next((p for p in available if p[0] == value), None)

        if same_unit is not None:
            available.remove(same_unit)
            kind, heard = "DOSE-VAL", f"{same_unit[0]:g} {same_unit[1]}"
        elif same_value is not None:
            available.remove(same_value)
            kind, heard = "DOSE-UNIT", f"{same_value[0]:g} {same_value[1]}"
        else:
            kind, heard = "DOSE-MISS", ""

        found.append(
            {
                "kind": kind,
                "expected": f"{value:g} {unit}",
                "heard": heard,
                "ref_index": ref_index,
            }
        )
    return found


def negation_findings(reference: str, hypothesis: str) -> list[dict]:
    """One finding per reference negation cue that did not survive its window.

    Position is load-bearing. "No fever, cough present" and "fever, no cough
    present" carry the same cue and opposite meanings.
    """
    ref_tokens, hyp_tokens = _tokens(reference), _tokens(hypothesis)
    found = []
    for cue, ref_index in find_negations(reference):
        centre = _aligned_centre(ref_index, len(ref_tokens), len(hyp_tokens))
        nearby = " ".join(_window(hyp_tokens, centre))
        if any(seen == cue for seen, _ in find_negations(nearby)):
            continue
        found.append(
            {"kind": "NEG-FLIP", "expected": cue, "heard": "", "ref_index": ref_index}
        )
    return found


EXCERPT_WIDTH = 15


def excerpt_around(
    reference: str, hypothesis: str, ref_index: int, width: int = EXCERPT_WIDTH
) -> tuple[str, str]:
    """Show both sides centred on the finding, with the judged entity marked.

    The old excerpt centred on the first textual difference. That is almost
    always capitalisation, so the entity being judged was frequently off screen:
    15 of 100 rows hid a drug, a dose or a negation outright, and one of them
    hid a dose doubling from 200mg to 400mg.

    Centring on the finding's own position is the fix. The judged entity is
    wrapped in double brackets so it reads differently from the ordinary diff
    marks around it, because a row that shows six changed words needs to say
    which one it is asking about.
    """
    ref_tokens, hyp_tokens = _tokens(reference), _tokens(hypothesis)
    marked_ref = list(ref_tokens)
    if 0 <= ref_index < len(marked_ref):
        marked_ref[ref_index] = f"[[{marked_ref[ref_index]}]]"

    # `half` words either side of the centre word, so the window is exactly
    # `width` tokens for an odd width and the judged entity sits in the middle.
    centre_hyp = _aligned_centre(ref_index, len(ref_tokens), len(hyp_tokens))
    half = width // 2
    return (
        " ".join(marked_ref[max(0, ref_index - half) : ref_index + half + 1]),
        " ".join(hyp_tokens[max(0, centre_hyp - half) : centre_hyp + half + 1]),
    )


def select_findings(
    all_findings: pd.DataFrame, target: int = 150, seed: int = 42
) -> pd.DataFrame:
    """Draw a labelling sheet a population rate can be computed from.

    Ordinary stratified sampling. Every kind is a stratum. A stratum small
    enough to take whole is taken whole and weighs 1. A stratum too large is
    sampled, and each row it contributes weighs the number of findings it stands
    for, so summed weights recover the true totals.

    The alternative, sampling every kind in proportion, would have taken 2 of
    the 5 drug substitutions in the entire corpus. That is the class the
    benchmark exists to measure, so it gets a census and the abundant classes
    absorb the sampling instead.

    The weight column is the point. Without it a labelled sheet supports no
    statement about the population, which is the defect recorded as W3.
    """
    if all_findings.empty:
        return all_findings.assign(weight=1.0)

    strata = {kind: group for kind, group in all_findings.groupby("kind", sort=True)}
    totals = {kind: len(group) for kind, group in strata.items()}

    # Give every stratum an equal share of the sheet, then hand back whatever a
    # small stratum cannot use so the larger ones can absorb it.
    quota = {kind: target // len(strata) for kind in strata}
    spare = target - sum(quota.values())
    for kind in sorted(strata, key=lambda k: totals[k]):
        if totals[kind] < quota[kind]:
            spare += quota[kind] - totals[kind]
            quota[kind] = totals[kind]
    for kind in sorted(strata, key=lambda k: -totals[k]):
        room = totals[kind] - quota[kind]
        take = min(room, spare)
        quota[kind] += take
        spare -= take

    picked = []
    for kind in sorted(strata):
        group = strata[kind].sort_values(["clip_id", "provider", "ref_index"])
        n = quota[kind]
        chunk = group if n >= totals[kind] else group.sample(n=n, random_state=seed)
        picked.append(
            chunk.assign(weight=totals[kind] / len(chunk) if len(chunk) else 1.0)
        )

    return pd.concat(picked).reset_index(drop=True)


def findings_for(reference: str, hypothesis: str, lexicon: set[str]) -> list[dict]:
    """Every finding in one clip, ordered by where it appears in the reference.

    Ordered because the sheet shows them in reading order and because a stable
    order makes the selection reproducible under a seed.
    """
    found = (
        drug_findings(reference, hypothesis, lexicon)
        + dose_findings(reference, hypothesis)
        + negation_findings(reference, hypothesis)
    )
    return sorted(found, key=lambda f: f["ref_index"])
