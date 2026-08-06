"""End to end: injected errors in, headline table out.

No provider key exists during the overnight build, so the scoring path cannot
be proven on real transcripts. It can be proven on transcripts whose errors are
known exactly, which is what this does: it plants one drug substitution, one
dose value error, one unit error and one dropped negation into otherwise
perfect hypotheses, then asserts the headline table reports those and nothing
else.

This is the test that says the pipeline is safe to point at 2,000 paid API
calls. If it passes and the real numbers still come out wrong, the fault is in
the provider responses or the manifest, not in the metrics.
"""

import pandas as pd
import pytest

from src.failures import mark_diff, select_failures
from src.score import score_clip, summarise

LEXICON = {"metformin", "metronidazole", "warfarin", "amoxicillin"}

# Ten clips. Six transcribe perfectly, four carry one known error each.
CASES = [
    # (clip_id, tier, reference, hypothesis, what was broken)
    ("clean1", "A", "the patient takes metformin 500 mg daily", None, "none"),
    ("clean2", "A", "denies chest pain and shortness of breath", None, "none"),
    ("clean3", "A", "give 10 ml of the suspension", None, "none"),
    ("clean4", "B", "the patient takes warfarin 5 mg nightly", None, "none"),
    ("clean5", "B", "no fever and no cough on examination", None, "none"),
    ("clean6", "C", "amoxicillin 250 mg three times daily", None, "none"),
    (
        "drugsub",
        "C",
        "the patient takes metformin 500 mg daily",
        "the patient takes metronidazole 500 mg daily",
        "drug substitution",
    ),
    (
        "doseval",
        "C",
        "the patient takes warfarin 5 mg nightly",
        "the patient takes warfarin 50 mg nightly",
        "dose value error",
    ),
    (
        "doseunit",
        "B",
        "give 10 ml of the suspension",
        "give 10 mg of the suspension",
        "dose unit error",
    ),
    (
        "negdrop",
        "A",
        "denies chest pain and shortness of breath",
        "reports chest pain and shortness of breath",
        "negation dropped",
    ),
]


@pytest.fixture
def per_clip():
    """Score every case exactly as src.score.build would."""
    rows = []
    for clip_id, tier, reference, hypothesis, _ in CASES:
        scores = score_clip(reference, hypothesis or reference, LEXICON)
        rows.append(
            {
                "clip_id": clip_id,
                "provider": "testprov",
                "accent": "yoruba",
                "tier": tier,
                "domain": "clinical",
                "duration": 10.0,
                **scores,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def merged():
    """The cost and latency side, shaped as the cache merge produces it."""
    return pd.DataFrame(
        {
            "provider": ["testprov"] * len(CASES),
            "audio_seconds": [10.0] * len(CASES),
            "cost_usd": [0.001] * len(CASES),
            "latency_ms": [500] * len(CASES),
        }
    )


class TestInjectedErrorsAreReported:
    def test_finds_exactly_one_drug_substitution(self, per_clip):
        assert per_clip["drug_substitution"].sum() == 1
        assert (
            per_clip.loc[per_clip["clip_id"] == "drugsub", "drug_substitution"].iloc[0]
            == 1
        )

    def test_finds_exactly_one_dose_value_error(self, per_clip):
        assert per_clip["dose_value_error"].sum() == 1
        assert (
            per_clip.loc[per_clip["clip_id"] == "doseval", "dose_value_error"].iloc[0]
            == 1
        )

    def test_finds_exactly_one_dose_unit_error(self, per_clip):
        assert per_clip["dose_unit_error"].sum() == 1

    def test_finds_exactly_one_lost_negation(self, per_clip):
        assert per_clip["negation_lost"].sum() == 1
        assert (
            per_clip.loc[per_clip["clip_id"] == "negdrop", "negation_lost"].iloc[0] == 1
        )

    def test_the_six_clean_clips_score_zero_wer(self, per_clip):
        clean = per_clip[per_clip["clip_id"].str.startswith("clean")]
        assert (clean["wer"] == 0.0).all()

    def test_no_error_is_invented_on_a_clean_clip(self, per_clip):
        clean = per_clip[per_clip["clip_id"].str.startswith("clean")]
        for column in [
            "drug_substitution",
            "drug_deletion",
            "dose_value_error",
            "dose_unit_error",
            "negation_lost",
        ]:
            assert clean[column].sum() == 0, f"{column} fired on a clean clip"


class TestHeadlineTable:
    def test_has_one_row_per_provider(self, per_clip, merged):
        assert len(summarise(per_clip, merged)) == 1

    def test_carries_every_spec_headline_column(self, per_clip, merged):
        headline = summarise(per_clip, merged)
        for column in [
            "wer",
            "drug_accuracy",
            "drug_substitutions",
            "dose_value_accuracy",
            "negation_preservation",
            "cost_per_audio_hour",
        ]:
            assert column in headline.columns

    def test_wer_stays_between_zero_and_one(self, per_clip, merged):
        wer = summarise(per_clip, merged)["wer"].iloc[0]
        assert 0.0 <= wer <= 1.0

    def test_drug_accuracy_matches_the_injected_error(self, per_clip, merged):
        # 5 reference drug mentions across the cases, 1 substituted.
        headline = summarise(per_clip, merged)
        assert headline["drug_mentions"].iloc[0] == 5
        assert headline["drug_accuracy"].iloc[0] == pytest.approx(4 / 5)
        assert headline["drug_substitutions"].iloc[0] == 1

    def test_dose_value_accuracy_counts_a_unit_error_as_value_intact(
        self, per_clip, merged
    ):
        # 8 reference doses across the ten clips: one each in clean1, clean3,
        # clean4, drugsub, doseval and doseunit, and two in clean6, where the
        # normalizer turns "three times daily" into a (3, times daily) pair
        # alongside the 250 mg. One value error, one unit error. The unit error
        # kept its value, so value accuracy is 7 of 8.
        headline = summarise(per_clip, merged)
        assert headline["doses"].iloc[0] == 8
        assert headline["dose_value_accuracy"].iloc[0] == pytest.approx(7 / 8)

    def test_negation_preservation_matches_the_injected_drop(self, per_clip, merged):
        headline = summarise(per_clip, merged)
        # 5 cues: 1 in clean2, 2 in clean5, 1 in negdrop, 1 in the negdrop ref pair.
        assert headline["negation_cues"].iloc[0] >= 4
        assert headline["negation_preservation"].iloc[0] < 1.0

    def test_reports_cost_per_audio_hour(self, per_clip, merged):
        # 10 clips of 10 seconds is 100 seconds; 0.01 USD over 100/3600 hours.
        headline = summarise(per_clip, merged)
        assert headline["cost_per_audio_hour"].iloc[0] == pytest.approx(0.36, rel=0.01)

    def test_a_tier_breakdown_splits_the_same_totals(self, per_clip, merged):
        by_tier = summarise(per_clip, merged, by="tier")
        assert set(by_tier["tier"]) == {"A", "B", "C"}
        assert by_tier["drug_substitutions"].sum() == 1

    def test_rerunning_reproduces_identical_numbers(self, per_clip, merged):
        # SPEC prompt 04 sanity check: scoring is deterministic.
        first = summarise(per_clip, merged)
        second = summarise(per_clip, merged)
        pd.testing.assert_frame_equal(first, second)


class TestFailureSheetFromRealScores:
    def test_puts_the_drug_substitution_first(self, per_clip):
        selected = select_failures(per_clip, n=4)
        assert selected.iloc[0]["clip_id"] == "drugsub"

    def test_selects_all_four_injected_failures_before_clean_clips(self, per_clip):
        selected = select_failures(per_clip, n=4)
        assert set(selected["clip_id"]) == {"drugsub", "doseval", "doseunit", "negdrop"}

    def test_the_excerpt_marks_both_sides_of_the_substitution(self):
        ref, hyp = mark_diff(
            "the patient takes metformin 500 mg daily",
            "the patient takes metronidazole 500 mg daily",
        )
        assert "*metformin*" in ref
        assert "*metronidazole*" in hyp

    def test_leaves_the_judgment_columns_empty(self, per_clip):
        # The three columns that are Suwaid's must never arrive pre-filled.
        selected = select_failures(per_clip, n=4)
        assert (
            "failure_code" not in selected.columns
            or selected["failure_code"].eq("").all()
        )
