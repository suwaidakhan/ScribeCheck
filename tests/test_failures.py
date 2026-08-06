"""Failure selection and diff excerpts, SPEC section 6.

This is the sheet Suwaid labels by hand, so the selection has to put the
dangerous failures in front of him rather than the most numerous ones, and the
excerpts have to show the error without him rereading a whole clip.

Nothing here fills failure_code, severity or note. Those are his.
"""

import pandas as pd
from src.failures import excerpt, mark_diff, select_failures


def scored(**overrides) -> dict:
    row = {
        "clip_id": "c1",
        "provider": "whisper",
        "accent": "yoruba",
        "tier": "A",
        "domain": "clinical",
        "wer": 0.1,
        "drug_substitution": 0,
        "dose_value_error": 0,
        "negation_lost": 0,
    }
    row.update(overrides)
    return row


class TestSelectFailures:
    def test_takes_drug_substitutions_before_anything_else(self):
        rows = [scored(clip_id=f"w{i}", wer=0.9) for i in range(10)] + [
            scored(clip_id="sub", wer=0.01, drug_substitution=1)
        ]
        selected = select_failures(pd.DataFrame(rows), n=1)
        assert list(selected["clip_id"]) == ["sub"]

    def test_takes_dose_value_errors_before_negation_flips(self):
        rows = [
            scored(clip_id="neg", negation_lost=1),
            scored(clip_id="dose", dose_value_error=1),
        ]
        selected = select_failures(pd.DataFrame(rows), n=1)
        assert list(selected["clip_id"]) == ["dose"]

    def test_takes_negation_flips_before_plain_high_wer(self):
        rows = [
            scored(clip_id="wer", wer=0.99),
            scored(clip_id="neg", wer=0.01, negation_lost=1),
        ]
        selected = select_failures(pd.DataFrame(rows), n=1)
        assert list(selected["clip_id"]) == ["neg"]

    def test_fills_the_remainder_with_the_worst_wer(self):
        rows = [
            scored(clip_id="sub", drug_substitution=1),
            scored(clip_id="bad", wer=0.8),
            scored(clip_id="ok", wer=0.05),
        ]
        selected = select_failures(pd.DataFrame(rows), n=2)
        assert list(selected["clip_id"]) == ["sub", "bad"]

    def test_returns_exactly_n_when_enough_rows_exist(self):
        rows = [scored(clip_id=f"c{i}", wer=i / 100) for i in range(200)]
        assert len(select_failures(pd.DataFrame(rows), n=100)) == 100

    def test_returns_what_exists_when_there_are_fewer_than_n(self):
        rows = [scored(clip_id=f"c{i}") for i in range(5)]
        assert len(select_failures(pd.DataFrame(rows), n=100)) == 5

    def test_never_repeats_a_clip_and_provider_pair(self):
        rows = [scored(clip_id="c1", drug_substitution=1, dose_value_error=1)]
        selected = select_failures(pd.DataFrame(rows), n=10)
        assert len(selected) == 1

    def test_spreads_across_providers_rather_than_draining_one(self):
        # SPEC section 6 asks for a spread. A sheet of 100 rows all from the
        # worst provider says nothing about whether the others are safer.
        rows = [
            scored(clip_id=f"a{i}", provider="whisper", wer=0.9) for i in range(50)
        ] + [scored(clip_id=f"b{i}", provider="gemini", wer=0.5) for i in range(50)]
        selected = select_failures(pd.DataFrame(rows), n=20)
        assert selected["provider"].nunique() == 2

    def test_spreads_across_tiers(self):
        rows = [scored(clip_id=f"a{i}", tier="A", wer=0.9) for i in range(50)] + [
            scored(clip_id=f"c{i}", tier="C", wer=0.5) for i in range(50)
        ]
        selected = select_failures(pd.DataFrame(rows), n=20)
        assert selected["tier"].nunique() == 2

    def test_is_deterministic(self):
        rows = [scored(clip_id=f"c{i}", wer=0.5) for i in range(200)]
        frame = pd.DataFrame(rows)
        assert list(select_failures(frame, n=50)["clip_id"]) == list(
            select_failures(frame, n=50)["clip_id"]
        )


class TestMarkDiff:
    def test_marks_a_word_the_hypothesis_changed(self):
        ref, hyp = mark_diff("takes metformin daily", "takes metronidazole daily")
        assert "*metformin*" in ref
        assert "*metronidazole*" in hyp

    def test_leaves_matching_words_unmarked(self):
        ref, _ = mark_diff("takes metformin daily", "takes metronidazole daily")
        assert "*takes*" not in ref
        assert "*daily*" not in ref

    def test_marks_a_deleted_word(self):
        ref, _ = mark_diff("takes metformin daily", "takes daily")
        assert "*metformin*" in ref

    def test_marks_an_inserted_word(self):
        _, hyp = mark_diff("takes daily", "takes metformin daily")
        assert "*metformin*" in hyp

    def test_identical_text_is_unmarked(self):
        ref, hyp = mark_diff("takes metformin", "takes metformin")
        assert "*" not in ref and "*" not in hyp


class TestExcerpt:
    def test_centres_on_the_marked_token(self):
        words = ["w"] * 40
        words[20] = "*target*"
        assert "*target*" in excerpt(" ".join(words), width=15)

    def test_returns_about_the_requested_width(self):
        words = ["w"] * 60
        words[30] = "*target*"
        assert len(excerpt(" ".join(words), width=15).split()) <= 17

    def test_returns_short_text_whole(self):
        assert excerpt("three short words", width=15) == "three short words"

    def test_survives_text_with_no_marked_token(self):
        words = " ".join(["w"] * 40)
        assert len(excerpt(words, width=15).split()) <= 17
