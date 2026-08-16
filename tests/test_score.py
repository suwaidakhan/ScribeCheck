"""Metrics M1 through M4, SPEC section 5.

These are the functions the benchmark's headline claim rests on, so the cases
below are written around the failures that would be clinically dangerous rather
than around the ones that are easy to check: a drug swapped for a different real
drug, a dose value changed while its unit survives, a negation dropped.

Every function takes text that has already been through the one normalizer, per
SPEC section 5.
"""

import pandas as pd
import pytest

from src.score import (
    mcnemar,
    paired_significance,
    score_clip,
    score_doses,
    score_drugs,
    score_negations,
    score_wer,
    summarise,
)

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


class TestSubstitutionIsNotCreditedToAnotherSurvivingDrug:
    """W1. A drug mangled into a non-word is a deletion, not a substitution.

    Found by labelling row 10: `trimethoprim` became `trimethropium`, a
    non-word, and the scorer called it a substitution because `pyrimethamine`
    sat nearby, was in the lexicon, and had been transcribed perfectly. 14 of
    the 19 substitutions in the real results were produced this way.

    The distinction is the whole point of M2. A substitution is dangerous
    because the output still reads as a valid clinical sentence; a deletion
    leaves a hole a reader can notice. Conflating them overstates the danger.
    """

    LEX = {
        "aspirin",
        "warfarin",
        "pyrimethamine",
        "trimethoprim",
        "metformin",
        "metronidazole",
        "haloperidol",
        "chlorpromazine",
    }

    def test_a_mangled_drug_beside_a_surviving_drug_is_a_deletion(self):
        result = score_drugs(
            "patient takes aspirin and warfarin",
            "patient takes aspirin and wxyzzy",
            self.LEX,
        )
        assert result["deletion"] == 1
        assert result["substitution"] == 0
        assert result["correct"] == 1

    def test_the_row_10_case(self):
        # Real data. pyrimethamine survived, trimethoprim was destroyed.
        result = score_drugs(
            "drugs include pyrimethamine proguanil chlorproguanil and trimethoprim",
            "drugs include pyrimethamine proguanil chlorpropuanil and trimethropium",
            self.LEX,
        )
        assert result["substitution"] == 0, (
            "pyrimethamine survived, it is not a substitute"
        )
        assert result["deletion"] == 1
        assert result["correct"] == 1

    def test_a_genuine_substitution_is_still_caught(self):
        # The fix must not silence the real thing.
        result = score_drugs(
            "takes metformin daily", "takes metronidazole daily", self.LEX
        )
        assert result["substitution"] == 1
        assert result["deletion"] == 0

    def test_two_drugs_swapped_for_each_other_are_both_substitutions(self):
        # haloperidol and chlorpromazine are both antipsychotics and both in the
        # reference. Each is missing from where it belongs, and the other one is
        # not a valid excuse for it.
        result = score_drugs(
            "gave haloperidol then chlorpromazine",
            "gave chlorpromazine then haloperidol",
            self.LEX,
        )
        assert result["correct"] == 2, "both drugs are present, order is not the metric"

    def test_a_real_substitute_wins_over_a_surviving_reference_drug(self):
        # aspirin survived AND metronidazole appeared where warfarin should be.
        # The genuine substitute must be preferred over the innocent bystander.
        result = score_drugs(
            "takes aspirin and warfarin",
            "takes aspirin and metronidazole",
            self.LEX,
        )
        assert result["substitution"] == 1
        assert result["correct"] == 1


def _scored_row(**overrides) -> dict:
    """One per-clip scoring row, in the shape `summarise` consumes."""
    row = {
        "provider": "aai",
        "clip_id": "c1",
        "tier": "A",
        "wer": 0.2,
        "wer_spoken_punct_removed": 0.2,
        "drug_mentions": 0,
        "drug_correct": 0,
        "drug_substitution": 0,
        "drug_deletion": 0,
        "drug_hyp_mentions": 0,
        "drug_false_positive": 0,
        "doses": 0,
        "dose_correct": 0,
        "dose_value_error": 0,
        "dose_unit_error": 0,
        "dose_missing": 0,
        "negation_cues": 0,
        "negation_preserved": 0,
        "negation_lost": 0,
    }
    row.update(overrides)
    return row


def _merged_row(**overrides) -> dict:
    """The transcription-side row `summarise` needs for the M5 cost columns."""
    row = {
        "provider": "aai",
        "audio_seconds": 3600.0,
        "cost_usd": 1.0,
        "latency_ms": 500,
    }
    row.update(overrides)
    return row


class TestDualWer:
    """W9. Spoken punctuation is a formatting convention, not a recognition error.

    112 of the 400 clips have a speaker voicing "comma" or "open bracket" and
    the providers write the word. AssemblyAI turns it into a character the
    normalizer strips; Deepgram writes it out and takes an insertion error on
    the same audio. One number cannot describe both, so both are reported and
    the gap between them is the finding.
    """

    def test_score_clip_reports_both_wers(self):
        result = score_clip("the patient is stable", "the patient is stable", LEXICON)
        assert result["wer"] == 0.0
        assert result["wer_spoken_punct_removed"] == 0.0

    def test_a_voiced_comma_costs_the_as_scored_wer_and_not_the_other(self):
        # The provider heard exactly what was said. Only the convention differs.
        result = score_clip("no fever no cough", "no fever comma no cough", LEXICON)
        assert result["wer"] == 0.25
        assert result["wer_spoken_punct_removed"] == 0.0

    def test_a_multi_word_punctuation_phrase_is_removed_whole(self):
        result = score_clip(
            "22 units at bedtime",
            "open bracket 22 close bracket units at bedtime",
            LEXICON,
        )
        assert result["wer"] > 0
        assert result["wer_spoken_punct_removed"] == 0.0

    def test_a_real_error_survives_both(self):
        # Removing punctuation must not launder a genuine substitution.
        result = score_clip(
            "takes metformin daily", "takes metronidazole daily", LEXICON
        )
        assert result["wer"] == result["wer_spoken_punct_removed"] == 1 / 3

    def test_a_reference_that_is_only_punctuation_has_no_stripped_denominator(self):
        # An empty stripped reference has no denominator, same rule as M1.
        result = score_clip("comma", "comma", LEXICON)
        assert result["wer"] == 0.0
        assert result["wer_spoken_punct_removed"] is None

    def test_summarise_carries_both_and_the_share_between_them(self):
        per_clip = pd.DataFrame(
            [
                _scored_row(
                    provider="dg-general", wer=0.4, wer_spoken_punct_removed=0.3
                ),
                _scored_row(
                    provider="dg-general", wer=0.2, wer_spoken_punct_removed=0.1
                ),
            ]
        )
        merged = pd.DataFrame([_merged_row(provider="dg-general")])
        row = summarise(per_clip, merged).iloc[0]
        assert row["wer"] == pytest.approx(0.3)
        assert row["wer_spoken_punct_removed"] == pytest.approx(0.2)
        # A third of this provider's measured error is transcribed punctuation.
        assert row["wer_spoken_punct_share"] == pytest.approx(1 / 3)


class TestDrugPrecision:
    """W11. Recall alone rewards a provider for inventing drugs.

    M2 stays measured over reference mentions, for the reason in the module
    docstring: a hallucinated drug is not a failure to transcribe a drug.
    Precision is the second direction, reported beside it rather than folded
    into it, so neither number can hide the other.
    """

    def test_the_recall_counts_are_untouched(self):
        # M2 is published. Adding a direction must not move the existing one.
        result = score_drugs("takes metformin daily", "takes metformin daily", LEXICON)
        assert result["mentions"] == 1
        assert result["correct"] == 1
        assert result["substitution"] == 0
        assert result["deletion"] == 0

    def test_an_invented_drug_is_a_false_positive(self):
        # The case the metric was blind to: nothing in the reference to score
        # against, so recall never notices.
        result = score_drugs("the patient is stable", "takes warfarin", LEXICON)
        assert result["mentions"] == 0
        assert result["hyp_mentions"] == 1
        assert result["false_positive"] == 1

    def test_a_surviving_drug_is_not_a_false_positive(self):
        result = score_drugs("takes metformin daily", "takes metformin daily", LEXICON)
        assert result["hyp_mentions"] == 1
        assert result["false_positive"] == 0

    def test_a_minor_spelling_slip_is_not_a_false_positive(self):
        # Same edit-distance tolerance as the recall side, or the two
        # directions would disagree about the same word.
        result = score_drugs("takes metformin", "takes metformim", LEXICON)
        assert result["correct"] == 1
        assert result["false_positive"] == 0

    def test_a_substitution_is_a_false_positive_as_well_as_a_recall_miss(self):
        # metronidazole was never said. It is a miss in one direction and an
        # invention in the other, and it is both at once.
        result = score_drugs(
            "takes metformin daily", "takes metronidazole daily", LEXICON
        )
        assert result["substitution"] == 1
        assert result["false_positive"] == 1

    def test_an_extra_copy_of_a_real_drug_is_a_false_positive(self):
        # Said once, written twice. The second mention has nothing to match.
        result = score_drugs("takes warfarin", "takes warfarin and warfarin", LEXICON)
        assert result["hyp_mentions"] == 2
        assert result["false_positive"] == 1

    def test_a_hypothesis_with_no_drug_has_no_precision_denominator(self):
        result = score_drugs("takes metformin", "takes it", LEXICON)
        assert result["hyp_mentions"] == 0
        assert result["false_positive"] == 0

    def test_summarise_reports_precision_and_f1_beside_recall(self):
        per_clip = pd.DataFrame(
            [
                _scored_row(
                    provider="gemini",
                    drug_mentions=4,
                    drug_correct=2,
                    drug_hyp_mentions=4,
                    drug_false_positive=2,
                )
            ]
        )
        merged = pd.DataFrame([_merged_row(provider="gemini")])
        row = summarise(per_clip, merged).iloc[0]
        assert row["drug_accuracy"] == pytest.approx(0.5), "recall, unrenamed"
        assert row["drug_precision"] == pytest.approx(0.5)
        assert row["drug_f1"] == pytest.approx(0.5)
        assert row["drug_false_positives"] == 2

    def test_precision_is_undefined_rather_than_zero_when_no_drug_was_output(self):
        per_clip = pd.DataFrame([_scored_row(provider="whisper")])
        merged = pd.DataFrame([_merged_row(provider="whisper")])
        row = summarise(per_clip, merged).iloc[0]
        assert row["drug_precision"] is None
        assert row["drug_f1"] is None


class TestMcnemar:
    """W13. The headline gap is reported as a raw difference and nothing else."""

    def test_symmetric_disagreement_is_not_significant(self):
        result = mcnemar(10, 10)
        assert result["statistic"] == pytest.approx(0.0)
        assert result["p_value"] == pytest.approx(1.0)

    def test_no_disagreement_at_all_gives_p_one(self):
        result = mcnemar(0, 0)
        assert result["discordant"] == 0
        assert result["p_value"] == pytest.approx(1.0)

    def test_a_one_sided_disagreement_is_significant(self):
        result = mcnemar(20, 5)
        assert result["p_value"] < 0.01

    def test_small_samples_use_the_exact_binomial(self):
        # 2 against 8 is 2 * P(X <= 2 | n=10, p=0.5) = 112/1024.
        result = mcnemar(2, 8)
        assert result["test"] == "exact"
        assert result["p_value"] == pytest.approx(0.109375)

    def test_large_samples_use_chi_square_with_continuity_correction(self):
        # (|20 - 5| - 1)^2 / 25 = 7.84, one degree of freedom.
        result = mcnemar(20, 5)
        assert result["test"] == "chi2"
        assert result["statistic"] == pytest.approx(7.84)
        assert result["p_value"] == pytest.approx(0.005110, rel=1e-3)

    def test_the_test_is_symmetric_in_its_arguments(self):
        assert mcnemar(20, 5)["p_value"] == pytest.approx(mcnemar(5, 20)["p_value"])


class TestPairedSignificance:
    """The same 400 clips go to every provider, which is matched-pairs data.

    What the test does not carry is stated in the docstring of the function
    itself: 99 speakers contribute more than one clip, so the clips are not
    independent draws and the p-value is optimistic. That is W12.
    """

    def _frame(self) -> pd.DataFrame:
        # Four clips with one drug mention each. `a` gets all four, `b` gets one.
        rows = []
        for i in range(4):
            rows.append(
                _scored_row(
                    provider="a", clip_id=f"c{i}", drug_mentions=1, drug_correct=1
                )
            )
            rows.append(
                _scored_row(
                    provider="b",
                    clip_id=f"c{i}",
                    drug_mentions=1,
                    drug_correct=1 if i == 0 else 0,
                    drug_deletion=0 if i == 0 else 1,
                )
            )
        return pd.DataFrame(rows)

    def test_it_counts_the_discordant_clips(self):
        result = paired_significance(self._frame(), metric="drug")
        row = result.iloc[0]
        assert row["provider_a"] == "a" and row["provider_b"] == "b"
        assert row["n_pairs"] == 4
        assert row["a_only"] == 3
        assert row["b_only"] == 0

    def test_a_clip_with_no_denominator_is_not_a_pair(self):
        frame = pd.concat(
            [
                self._frame(),
                pd.DataFrame(
                    [
                        _scored_row(provider="a", clip_id="empty"),
                        _scored_row(provider="b", clip_id="empty"),
                    ]
                ),
            ]
        )
        assert paired_significance(frame, metric="drug").iloc[0]["n_pairs"] == 4

    def test_every_provider_pair_appears_once(self):
        frame = pd.concat(
            [
                self._frame(),
                pd.DataFrame(
                    [
                        _scored_row(
                            provider="c",
                            clip_id=f"c{i}",
                            drug_mentions=1,
                            drug_correct=1,
                        )
                        for i in range(4)
                    ]
                ),
            ]
        )
        result = paired_significance(frame, metric="drug")
        assert len(result) == 3
        assert set(zip(result["provider_a"], result["provider_b"])) == {
            ("a", "b"),
            ("a", "c"),
            ("b", "c"),
        }

    def test_negation_and_dose_are_pairable_too(self):
        frame = pd.DataFrame(
            [
                _scored_row(
                    provider="a", clip_id="c1", negation_cues=1, negation_preserved=1
                ),
                _scored_row(
                    provider="b", clip_id="c1", negation_cues=1, negation_preserved=0
                ),
            ]
        )
        assert paired_significance(frame, metric="negation").iloc[0]["a_only"] == 1

    def test_wer_is_refused_because_it_is_not_a_binary_outcome(self):
        # McNemar needs a paired binary outcome. Dichotomising a continuous WER
        # to force it through the test would invent a threshold nobody chose.
        with pytest.raises(ValueError, match="binary"):
            paired_significance(self._frame(), metric="wer")


class TestAnInventedDrugMustNotBeTheLexiconsGap:
    """W11 follow-up. 10 of 35 false positives were the lexicon, not the system.

    Found by checking what the precision denominator was actually made of.
    Three cases, all of them charging a provider for being right:

    - The reference is misspelled `propanolol`, which is in no lexicon, so it is
      not a reference mention. Three providers wrote `propranolol` correctly and
      all three were recorded as having invented a drug.
    - `hydrocloride` reached the lexicon as a misspelling while `hydrochloride`
      did not, so writing the correct spelling counted as invention. Twice.
    - `insulins` is not a lexicon term, so a provider writing `insulin` invented
      one.

    A hallucination is a drug name with nothing like it in the reference. That is
    the thing worth reporting, and it is what this now measures.
    """

    LEX = {"propranolol", "insulin", "morphine", "warfarin"}

    def test_a_drug_the_reference_misspelled_is_not_invented(self):
        from src.score import score_drugs

        result = score_drugs("propanolol 20 mg tid", "propranolol 20 mg tid", self.LEX)
        assert result["false_positive"] == 0

    def test_a_plural_in_the_reference_is_not_invented(self):
        from src.score import score_drugs

        result = score_drugs(
            "short acting insulins at meals", "short acting insulin at meals", self.LEX
        )
        assert result["false_positive"] == 0

    def test_a_genuine_hallucination_is_still_counted(self):
        from src.score import score_drugs

        # "more follicles" became "morphine calls". Nothing in the reference is
        # anything like "morphine", so the provider put a drug on the page that
        # the clinician never said.
        result = score_drugs(
            "preventing more follicles from developing",
            "preventing morphine calls from developing",
            self.LEX,
        )
        assert result["false_positive"] == 1

    def test_an_unrelated_invented_drug_is_still_counted(self):
        from src.score import score_drugs

        result = score_drugs("the patient is stable", "takes warfarin", self.LEX)
        assert result["false_positive"] == 1
