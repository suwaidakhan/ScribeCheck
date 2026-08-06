"""Metrics M1 through M4, SPEC section 5.

These are the functions the benchmark's headline claim rests on, so the cases
below are written around the failures that would be clinically dangerous rather
than around the ones that are easy to check: a drug swapped for a different real
drug, a dose value changed while its unit survives, a negation dropped.

Every function takes text that has already been through the one normalizer, per
SPEC section 5.
"""

import pytest
from src.score import score_doses, score_drugs, score_negations, score_wer

LEXICON = {
    "metformin",
    "metronidazole",
    "warfarin",
    "amoxicillin",
    "amoxapine",
    "morphine",
    "hydralazine",
    "hydroxyzine",
}


class TestWer:
    def test_identical_text_scores_zero(self):
        assert score_wer("the patient is stable", "the patient is stable") == 0.0

    def test_one_wrong_word_in_four(self):
        assert score_wer("the patient is stable", "the patient is unstable") == 0.25

    def test_a_deletion_counts(self):
        assert score_wer("the patient is stable", "the patient stable") == 0.25

    def test_an_insertion_counts(self):
        assert score_wer("the patient is stable", "the patient is very stable") == 0.25

    def test_an_empty_hypothesis_scores_one(self):
        assert score_wer("the patient is stable", "") == 1.0

    def test_an_empty_reference_is_not_scored(self):
        # Dividing by zero reference words would produce inf and poison the mean.
        assert score_wer("", "anything at all") is None


class TestDrugs:
    def test_a_surviving_drug_is_correct(self):
        result = score_drugs("takes metformin daily", "takes metformin daily", LEXICON)
        assert result["correct"] == 1
        assert result["substitution"] == 0
        assert result["deletion"] == 0

    def test_a_minor_spelling_slip_still_counts_as_correct(self):
        # SPEC M2 allows edit distance 1 for pluralisation or minor spelling.
        result = score_drugs("takes metformin", "takes metformim", LEXICON)
        assert result["correct"] == 1

    def test_a_drug_replaced_by_a_different_real_drug_is_a_substitution(self):
        # The most dangerous class: both words are real drugs, so nothing
        # downstream looks wrong.
        result = score_drugs(
            "takes metformin daily", "takes metronidazole daily", LEXICON
        )
        assert result["substitution"] == 1
        assert result["correct"] == 0

    def test_a_dropped_drug_is_a_deletion(self):
        result = score_drugs("takes metformin daily", "takes it daily", LEXICON)
        assert result["deletion"] == 1
        assert result["substitution"] == 0

    def test_a_drug_corrupted_into_a_nonword_is_a_deletion(self):
        result = score_drugs("takes metformin daily", "takes metfawmin daily", LEXICON)
        assert result["deletion"] == 1

    def test_counts_every_reference_mention(self):
        result = score_drugs(
            "warfarin and metformin", "warfarin and metronidazole", LEXICON
        )
        assert result["mentions"] == 2
        assert result["correct"] == 1
        assert result["substitution"] == 1

    def test_a_reference_with_no_drug_has_no_denominator(self):
        result = score_drugs("the patient is stable", "the patient is stable", LEXICON)
        assert result["mentions"] == 0

    def test_a_drug_the_hypothesis_invents_is_not_counted(self):
        # M2 is measured over reference mentions. An extra drug in the
        # hypothesis with no reference mention has no mention to score against.
        result = score_drugs("the patient is stable", "takes warfarin", LEXICON)
        assert result["mentions"] == 0


class TestDoses:
    def test_a_surviving_dose_is_correct(self):
        result = score_doses("take 500 mg twice", "take 500 mg twice")
        assert result["correct"] == 1
        assert result["value_error"] == 0
        assert result["unit_error"] == 0

    def test_a_changed_value_is_a_value_error(self):
        # The dangerous class: 50 mg instead of 500 mg.
        result = score_doses("take 500 mg twice", "take 50 mg twice")
        assert result["value_error"] == 1
        assert result["correct"] == 0

    def test_a_changed_unit_is_a_unit_error(self):
        result = score_doses("take 500 mg twice", "take 500 mcg twice")
        assert result["unit_error"] == 1
        assert result["value_error"] == 0

    def test_an_equivalent_unit_is_not_an_error(self):
        # SPEC M3 treats mcg and ug as equal, cc and ml as equal.
        assert score_doses("give 10 cc", "give 10 ml")["correct"] == 1

    def test_a_dose_written_out_in_words_still_matches(self):
        # The normalizer turns "five hundred" into "500", which is the whole
        # reason SPEC section 5 insists on one normalizer for both sides.
        from whisper_normalizer.english import EnglishTextNormalizer

        normalize = EnglishTextNormalizer()
        result = score_doses(
            normalize("Take 500 mg"), normalize("Take five hundred mg")
        )
        assert result["correct"] == 1

    def test_a_dropped_dose_is_missing(self):
        result = score_doses("take 500 mg twice", "take it twice")
        assert result["missing"] == 1

    def test_counts_every_reference_dose(self):
        result = score_doses(
            "40 mg daily and 10 units nightly", "40 mg daily and 20 units nightly"
        )
        assert result["doses"] == 2
        assert result["correct"] == 1
        assert result["value_error"] == 1

    def test_a_reference_with_no_dose_has_no_denominator(self):
        assert (
            score_doses("the patient is stable", "the patient is stable")["doses"] == 0
        )


class TestNegations:
    def test_a_surviving_negation_is_preserved(self):
        result = score_negations(
            "patient denies chest pain", "patient denies chest pain"
        )
        assert result["preserved"] == 1
        assert result["lost"] == 0

    def test_a_dropped_negation_is_lost(self):
        # The meaning inverts: "denies chest pain" becomes "has chest pain".
        result = score_negations("patient denies chest pain", "patient has chest pain")
        assert result["lost"] == 1
        assert result["preserved"] == 0

    def test_an_equivalent_cue_elsewhere_does_not_rescue_a_lost_one(self):
        # A negation 30 tokens away is not the same clinical statement, so the
        # window is what makes this metric mean anything.
        reference = "no fever " + "and ".join(["stable"] * 12)
        hypothesis = " ".join(["stable"] * 12) + " no cough"
        assert score_negations(reference, hypothesis)["lost"] == 1

    def test_a_cue_that_moved_slightly_still_counts(self):
        result = score_negations("there is no fever today", "there was no fever today")
        assert result["preserved"] == 1

    def test_counts_every_reference_cue(self):
        result = score_negations("no fever and denies cough", "no fever and has cough")
        assert result["cues"] == 2
        assert result["preserved"] == 1
        assert result["lost"] == 1

    def test_a_reference_with_no_cue_has_no_denominator(self):
        assert (
            score_negations("the patient is stable", "the patient is stable")["cues"]
            == 0
        )

    def test_a_negation_the_hypothesis_invents_is_not_counted(self):
        # Measured over reference cues, same as M2.
        assert score_negations("fever present", "no fever present")["cues"] == 0
