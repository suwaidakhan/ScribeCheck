"""Entity extraction: drugs, dosages, negations.

These run on normalized text (lowercase, no punctuation, number-words already
converted to digits by the Whisper normalizer), because that is the only form
SPEC section 5 lets any metric see.
"""

import pytest
from src.entities import (
    canonical_unit,
    find_dose_pairs,
    find_drug_mentions,
    find_negations,
    has_entity,
)

LEXICON = {
    "amoxicillin",
    "metformin",
    "warfarin",
    "lisinopril",
    "paracetamol",
    "insulin",
}


class TestDrugMentions:
    def test_finds_a_single_drug(self):
        assert find_drug_mentions("patient takes metformin daily", LEXICON) == [
            "metformin"
        ]

    def test_finds_several_and_keeps_transcript_order(self):
        found = find_drug_mentions("started on warfarin then amoxicillin", LEXICON)
        assert found == ["warfarin", "amoxicillin"]

    def test_returns_empty_when_no_drug_present(self):
        assert find_drug_mentions("blood pressure was normal today", LEXICON) == []

    def test_matches_whole_tokens_only(self):
        # "insulin" must not be found inside "insulinoma", a different clinical word.
        assert find_drug_mentions("history of insulinoma", LEXICON) == []

    def test_repeated_mention_is_reported_twice(self):
        # M2 accuracy is per reference mention, so the denominator counts repeats.
        found = find_drug_mentions(
            "metformin in the morning and metformin at night", LEXICON
        )
        assert found == ["metformin", "metformin"]


class TestDosePairs:
    def test_extracts_value_and_unit(self):
        assert find_dose_pairs("take 500 mg twice") == [(500.0, "mg")]

    def test_handles_unit_joined_to_the_number(self):
        assert find_dose_pairs("take 500mg twice") == [(500.0, "mg")]

    def test_extracts_decimal_values(self):
        assert find_dose_pairs("give 2.5 ml now") == [(2.5, "ml")]

    def test_finds_several_pairs(self):
        assert find_dose_pairs("40 mg daily and 10 units nightly") == [
            (40.0, "mg"),
            (10.0, "units"),
        ]

    def test_ignores_a_number_with_no_unit_after_it(self):
        assert find_dose_pairs("the patient is 45 years old and stable") == []

    def test_unit_must_directly_follow_the_number(self):
        # One intervening token is allowed for things like "500 of mg"? No.
        # SPEC says number-plus-unit pairs, so anything further away is not a dose.
        assert find_dose_pairs("500 patients received mg doses") == []

    def test_compound_units_survive(self):
        assert find_dose_pairs("glucose 120 mg/dl") == [(120.0, "mg/dl")]

    def test_multiword_unit_is_captured(self):
        assert find_dose_pairs("3 times daily") == [(3.0, "times daily")]


class TestUnitCanonicalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("mcg", "mcg"),
            ("µg", "mcg"),
            ("ug", "mcg"),
            ("cc", "ml"),
            ("ml", "ml"),
            ("milligrams", "mg"),
            ("mg", "mg"),
        ],
    )
    def test_equivalent_units_collapse(self, raw, expected):
        assert canonical_unit(raw) == expected

    def test_mcg_and_ug_are_the_same_dose(self):
        assert find_dose_pairs("50 mcg") == find_dose_pairs("50 ug")

    def test_cc_and_ml_are_the_same_dose(self):
        assert find_dose_pairs("10 cc") == find_dose_pairs("10 ml")


class TestNegations:
    def test_finds_a_single_word_cue(self):
        assert find_negations("patient denies chest pain") == [("denies", 1)]

    def test_finds_a_multiword_cue(self):
        assert find_negations("negative for diabetes") == [("negative for", 0)]

    def test_returns_position_so_the_window_check_can_use_it(self):
        assert find_negations("there is no fever today") == [("no", 2)]

    def test_finds_several(self):
        found = find_negations("no fever and denies cough")
        assert [cue for cue, _ in found] == ["no", "denies"]

    def test_returns_empty_when_none_present(self):
        assert find_negations("fever and cough present") == []

    def test_does_not_match_a_cue_inside_a_longer_word(self):
        # "not" must not fire on "notable", "never" must not fire on "nevertheless".
        assert find_negations("a notable finding nevertheless") == []


class TestHasEntity:
    def test_true_when_a_drug_is_present(self):
        assert has_entity("takes warfarin", LEXICON) is True

    def test_true_when_a_dose_is_present(self):
        assert has_entity("give 500 mg", LEXICON) is True

    def test_true_when_a_negation_is_present(self):
        assert has_entity("denies pain", LEXICON) is True

    def test_false_when_nothing_safety_relevant_is_present(self):
        assert has_entity("the weather is warm today", LEXICON) is False


class TestSpokenPunctuationIsNotContent:
    """W9, promoted out of Phase B because it corrupts collapse classification.

    112 of 400 clips have a speaker voicing punctuation aloud, "comma" and
    "open bracket", and the providers transcribe those words literally. They are
    not content and they are not errors, but they count as inserted words, so
    they inflate WER.

    That was a reporting problem until WER became a classifier. 38 of 118
    transcripts labelled ASR-COLLAPSE are not collapses at all: a Rituxan line
    scored 1.62 against 0.38 once the punctuation words came out, and the clip
    that started this, `14 glargine sig 22 units at bedtime` against `nicaragine
    sig twenty two open bracket twenty two close bracket units at bedtime`,
    scored 1.14. Left in, a real drug deletion would have been buried inside a
    collapse row instead of being labelled.
    """

    def test_removes_a_spoken_comma(self):
        from src.entities import strip_spoken_punctuation

        assert strip_spoken_punctuation("no fever comma no cough") == "no fever no cough"

    def test_removes_bracket_words(self):
        from src.entities import strip_spoken_punctuation

        assert (
            strip_spoken_punctuation("22 open bracket 22 close bracket units")
            == "22 22 units"
        )

    def test_keeps_a_drug_that_contains_a_punctuation_word(self):
        from src.entities import strip_spoken_punctuation

        # "periodic" starts with "period". Word boundaries, not substrings.
        assert "periodic" in strip_spoken_punctuation("periodic acid given")

    def test_keeps_ordinary_clinical_use_of_the_word_colon(self):
        # The anatomical colon is a body part, and this is the known cost of
        # the rule. Recorded rather than solved: distinguishing "colon" the
        # organ from "colon" the punctuation needs context this does not have.
        from src.entities import strip_spoken_punctuation

        assert strip_spoken_punctuation("the colon was inflamed") == "the was inflamed"

    def test_leaves_clean_text_alone(self):
        from src.entities import strip_spoken_punctuation

        assert strip_spoken_punctuation("takes warfarin daily") == "takes warfarin daily"
