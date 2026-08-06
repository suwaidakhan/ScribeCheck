"""Safety-relevant entity extraction: drug names, dosages, negations.

Every function here takes text that has already been through the single
normalizer from SPEC section 5, so it can assume lowercase, no punctuation
beyond the slash in compound units, and number-words already turned into
digits. Nothing here normalizes on its own, because two normalizers is how a
benchmark starts comparing reference and hypothesis on different terms.

Used by sample.py to annotate the manifest and by score.py to compute M2, M3
and M4 against the same definitions.
"""

from __future__ import annotations

import re

# SPEC section 5, M3. Order matters: the longest surface form has to be tried
# first so "mg/dl" is never read as "mg", and "times daily" never as a bare
# number followed by nothing.
DOSE_UNITS: tuple[str, ...] = (
    "times daily",
    "mg/dl",
    "ml/hr",
    "milligrams",
    "milligram",
    "micrograms",
    "microgram",
    "millilitres",
    "millilitre",
    "milliliters",
    "milliliter",
    "kilograms",
    "kilogram",
    "grams",
    "gram",
    "litres",
    "litre",
    "liters",
    "liter",
    "tablets",
    "tablet",
    "capsules",
    "capsule",
    "drops",
    "drop",
    "puffs",
    "puff",
    "units",
    "unit",
    "hours",
    "hour",
    "days",
    "day",
    "percent",
    "mmol",
    "meq",
    "mcg",
    "mg",
    "kg",
    "ml",
    "cc",
    "iu",
    "ug",
    "µg",
    "g",
    "l",
)

# Units that mean the same dose. SPEC section 5 names mcg/µg and cc/ml; the
# spelled-out forms come with them because the normalizer leaves "milligrams"
# alone while turning "five hundred" into "500", so both surfaces appear.
UNIT_ALIASES: dict[str, str] = {
    "µg": "mcg",
    "ug": "mcg",
    "micrograms": "mcg",
    "microgram": "mcg",
    "cc": "ml",
    "millilitres": "ml",
    "millilitre": "ml",
    "milliliters": "ml",
    "milliliter": "ml",
    "milligrams": "mg",
    "milligram": "mg",
    "kilograms": "kg",
    "kilogram": "kg",
    "grams": "g",
    "gram": "g",
    "litres": "l",
    "litre": "l",
    "liters": "l",
    "liter": "l",
    "tablet": "tablets",
    "capsule": "capsules",
    "drop": "drops",
    "puff": "puffs",
    "unit": "units",
    "hour": "hours",
    "day": "days",
}

# SPEC section 5, M4. Longest first for the same reason as the units.
NEGATION_CUES: tuple[str, ...] = (
    "negative for",
    "denies",
    "denied",
    "without",
    "never",
    "not",
    "no",
)

_UNIT_PATTERN = "|".join(re.escape(u) for u in DOSE_UNITS)
_DOSE_RE = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})(?![\w/])")

_CUE_PATTERN = "|".join(re.escape(c) for c in NEGATION_CUES)
_NEGATION_RE = re.compile(rf"(?<!\w)({_CUE_PATTERN})(?!\w)")

_TOKEN_RE = re.compile(r"[\w/.]+")


def canonical_unit(unit: str) -> str:
    """Collapse a unit surface form onto the one this benchmark scores against.

    "µg", "ug" and "micrograms" are all "mcg"; "cc" is "ml". A dose is only
    correct if value and unit both survive, so two spellings of the same unit
    must not count as a unit error.
    """
    return UNIT_ALIASES.get(unit, unit)


def find_drug_mentions(text: str, lexicon: set[str]) -> list[str]:
    """Every lexicon hit in `text`, in the order it appears, repeats included.

    Repeats are kept because M2 accuracy is measured per reference mention, so
    a transcript naming the same drug twice contributes two chances to get it
    wrong. Matching is whole-token, so "insulin" does not fire on "insulinoma".
    """
    if not lexicon:
        return []
    return [tok for tok in _TOKEN_RE.findall(text) if tok in lexicon]


def find_dose_pairs(text: str) -> list[tuple[float, str]]:
    """Number-and-unit pairs, as (value, canonical unit).

    The unit has to come directly after the number. "500 patients received mg
    doses" holds a number and a unit but no dose, and counting it as one would
    inflate the M3 denominator with things no clinician would call a dosage.
    """
    return [
        (float(value), canonical_unit(unit)) for value, unit in _DOSE_RE.findall(text)
    ]


def find_negations(text: str) -> list[tuple[str, int]]:
    """Negation cues as (cue, token index).

    The index is what M4 needs: SPEC asks whether the cue survives within a
    five-token window of its aligned context, which is a question about
    position, not just presence.
    """
    starts = [m.start() for m in _TOKEN_RE.finditer(text)]
    found: list[tuple[str, int]] = []
    for match in _NEGATION_RE.finditer(text):
        # Bisect by hand rather than importing bisect for one call site.
        index = sum(1 for s in starts if s < match.start())
        found.append((match.group(1), index))
    return found


def has_entity(text: str, lexicon: set[str]) -> bool:
    """True if the text carries anything the benchmark treats as safety relevant.

    This is the predicate SPEC section 3 uses for entity oversampling: at least
    55 percent of the 400 clips must contain a drug, a dose, or a negation.
    """
    return bool(
        find_drug_mentions(text, lexicon)
        or find_dose_pairs(text)
        or find_negations(text)
    )
