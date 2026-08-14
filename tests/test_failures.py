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


class TestLabelingPageIsValid:
    """The generated page has to actually run.

    It shipped once with a JS syntax error and nothing caught it: the template
    is authored as literal HTML, and inside a non-raw Python string the `\\n`
    in `lines.join("\\n")` became a real newline, splitting a string literal
    across two lines. Every Python test still passed, because none of them
    looked at the emitted page. These do.
    """

    def _page(self, tmp_path):
        import pandas as pd
        from src import config, failures

        sheet = pd.DataFrame(
            [{
                "finding_id": 1, "clip_id": "c1", "provider": "aai", "accent": "hausa",
                "tier": "A", "domain": "clinical", "kind": "DRUG-SUB",
                "expected": "metformin", "heard": "metronidazole", "weight": 1.0,
                "ref_excerpt": "takes [[metformin]]",
                "hyp_excerpt": "takes *metronidazole*",
                "auto_flag": "DRUG-SUB candidate", "needs_listen": "",
                "failure_code": "", "severity": "", "note": "",
            }],
            columns=failures.SHEET_COLUMNS,
        )
        original = config.TAXONOMY
        config.TAXONOMY = tmp_path
        try:
            failures._write_labeling_page(sheet, pd.DataFrame())
        finally:
            config.TAXONOMY = original
        return (tmp_path / "labeling.html").read_text()

    def test_escape_sequences_survive_into_the_page(self, tmp_path):
        # The exact bug: this must be a backslash and an n, not a newline.
        page = self._page(tmp_path)
        assert r'lines.join("\n")' in page
        assert r"/\*([^*]+)\*/g" in page

    def test_the_script_parses(self, tmp_path):
        # The real check: hand it to a JS engine.
        import shutil, subprocess

        node = shutil.which("node")
        if not node:
            import pytest

            pytest.skip("node not installed")
        page = self._page(tmp_path)
        script = page.split("<script>")[1].split("</script>")[0]
        js = tmp_path / "page.js"
        js.write_text(script)
        result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_the_page_carries_its_persistence(self, tmp_path):
        # Without these the page loses everything the moment it is closed.
        page = self._page(tmp_path)
        for needed in ["localStorage", "scribecheck-labels-v1", "parseCsv",
                       "needs_listen", "finding_id"]:
            assert needed in page, f"{needed} missing from the labeling page"

    def test_transcript_text_is_escaped_before_markup(self, tmp_path):
        page = self._page(tmp_path)
        assert "markup(escapeHtml(r.ref))" in page
        assert "markup(escapeHtml(r.hyp))" in page


class TestDrugEvidence:
    """Tell the labeller which words are real drugs.

    DRUG-SUB against DRUG-DEL turns on whether the word that replaced the drug
    is itself a drug. That is a lookup with a right answer, not a judgment, and
    the lexicon already holds it. Asking a product manager to recall whether
    "glatropin" is a real medicine was a tooling gap: the code knew and did not
    say. Severity stays entirely theirs.
    """

    LEX = {"quetiapine", "humira", "ropinirole", "propranolol", "captopril"}

    def test_names_the_reference_drug(self):
        from src.failures import drug_evidence

        e = drug_evidence("quetiapine fumarate 25 mg", "glatropin humira 25 mg", self.LEX)
        assert e["expected"] == ["quetiapine"]

    def test_flags_a_real_drug_in_the_hypothesis(self):
        # humira is a real biologic, so this is a substitution, not a deletion.
        from src.failures import drug_evidence

        e = drug_evidence("quetiapine fumarate", "glatropin humira", self.LEX)
        assert "humira" in e["heard_known"]

    def test_does_not_claim_an_unknown_word_is_a_drug(self):
        from src.failures import drug_evidence

        e = drug_evidence("quetiapine fumarate", "glatropin humira", self.LEX)
        assert "glatropin" not in e["heard_known"]

    def test_reports_nothing_heard_when_the_drug_was_mangled_into_nonwords(self):
        # captopril became "cap to praline": no real drug survived.
        from src.failures import drug_evidence

        e = drug_evidence("held captopril and clonidine", "head cap to praline", self.LEX)
        assert e["expected"] == ["captopril"]
        assert e["heard_known"] == []

    def test_a_surviving_drug_is_reported_as_heard(self):
        from src.failures import drug_evidence

        e = drug_evidence("takes propranolol", "takes propranolol", self.LEX)
        assert e["heard_known"] == ["propranolol"]

    def test_a_row_with_no_drugs_reports_nothing(self):
        from src.failures import drug_evidence

        e = drug_evidence("the patient is stable", "the patient is stable", self.LEX)
        assert e["expected"] == [] and e["heard_known"] == []

    def test_the_evidence_reaches_the_page(self, tmp_path):
        # The lookup is worthless if the labeller never sees it, so check the
        # rendered page rather than the function.
        import pandas as pd
        from src import config, failures

        sheet = pd.DataFrame(
            [{
                "finding_id": 1, "clip_id": "c1", "provider": "dg-medical",
                "accent": "igbo", "tier": "A", "domain": "clinical",
                "kind": "DRUG-SUB", "expected": "quetiapine", "heard": "humira",
                "weight": 1.0,
                "ref_excerpt": "[[quetiapine]] fumarate 25 mg",
                "hyp_excerpt": "*glatropin* *humira* 25 mg",
                "auto_flag": "DRUG-SUB candidate", "needs_listen": "",
                "failure_code": "", "severity": "", "note": "",
            }],
            columns=failures.SHEET_COLUMNS,
        )
        original = config.TAXONOMY
        config.TAXONOMY = tmp_path
        try:
            failures._write_labeling_page(sheet, pd.DataFrame())
        finally:
            config.TAXONOMY = original
        page = (tmp_path / "labeling.html").read_text()

        assert "this row" in page, "the page never states which error it is asking about"
        assert "DRUG-SUB" in page and "quetiapine" in page
        assert "one error per row" in page, "the one-error-per-row rule is not stated"

    def test_the_page_tells_the_labeller_to_judge_only_this_row(self, tmp_path):
        # A line can carry six changed words belonging to six different rows.
        # Without this the labeller judges the line rather than the finding.
        from src.failures import _LABELING_TEMPLATE

        assert "Judge only the highlighted entity" in _LABELING_TEMPLATE
