"""Failure selection and diff excerpts, SPEC section 6.

This is the sheet Suwaid labels by hand, so the selection has to put the
dangerous failures in front of him rather than the most numerous ones, and the
excerpts have to show the error without him rereading a whole clip.

Nothing here fills failure_code, severity or note. Those are his.
"""

import json

import pandas as pd

from src.failures import excerpt, mark_diff, select_failures


def sheet_row(**overrides) -> dict:
    """One pre-filled sheet row, the shape `build` writes."""
    row = {
        "finding_id": 1,
        "source": "detector",
        "clip_id": "c1",
        "provider": "aai",
        "accent": "hausa",
        "tier": "A",
        "domain": "clinical",
        "kind": "DRUG-SUB",
        "expected": "metformin",
        "heard": "metronidazole",
        "weight": 1.0,
        "ref_excerpt": "takes [[metformin]] daily",
        "hyp_excerpt": "takes *metronidazole* daily",
        "auto_flag": "DRUG-SUB candidate",
        "needs_listen": "",
        "failure_code": "",
        "severity": "",
        "note": "",
    }
    row.update(overrides)
    return row


def write_page(tmp_path, rows, texts=None) -> str:
    """Generate labeling.html from these rows and hand back the HTML."""
    from src import config, failures

    sheet = pd.DataFrame(rows, columns=failures.SHEET_COLUMNS)
    original = config.TAXONOMY
    config.TAXONOMY = tmp_path
    try:
        failures._write_labeling_page(sheet, texts)
    finally:
        config.TAXONOMY = original
    return (tmp_path / "labeling.html").read_text()


def embedded(page: str, name: str):
    """Read a JSON constant back out of the generated page."""
    marker = f"const {name} = "
    start = page.index(marker) + len(marker)
    value, _ = json.JSONDecoder().raw_decode(page[start:])
    return value


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
        return write_page(tmp_path, [sheet_row()])

    def test_escape_sequences_survive_into_the_page(self, tmp_path):
        # The exact bug: this must be a backslash and an n, not a newline.
        page = self._page(tmp_path)
        assert r'lines.join("\n")' in page
        assert r"/\*([^*]+)\*/g" in page

    def test_the_script_parses(self, tmp_path):
        # The real check: hand it to a JS engine.
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            import pytest

            pytest.skip("node not installed")
        page = self._page(tmp_path)
        script = page.split("<script>")[1].split("</script>")[0]
        js = tmp_path / "page.js"
        js.write_text(script)
        result = subprocess.run(
            [node, "--check", str(js)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_the_page_carries_its_persistence(self, tmp_path):
        # Without these the page loses everything the moment it is closed.
        page = self._page(tmp_path)
        for needed in [
            "localStorage",
            "scribecheck-labels-v2",
            "parseCsv",
            "needs_listen",
            "finding_id",
        ]:
            assert needed in page, f"{needed} missing from the labeling page"

    def test_transcript_text_is_escaped_before_markup(self, tmp_path):
        page = self._page(tmp_path)
        assert "markup(escapeHtml(c.ref))" in page
        assert "markup(escapeHtml(c.hyp))" in page


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

        e = drug_evidence(
            "quetiapine fumarate 25 mg", "glatropin humira 25 mg", self.LEX
        )
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

        e = drug_evidence(
            "held captopril and clonidine", "head cap to praline", self.LEX
        )
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
        write_page(
            tmp_path,
            [
                sheet_row(
                    provider="dg-medical",
                    accent="igbo",
                    expected="quetiapine",
                    heard="humira",
                    ref_excerpt="[[quetiapine]] fumarate 25 mg",
                    hyp_excerpt="*glatropin* *humira* 25 mg",
                )
            ],
        )
        page = (tmp_path / "labeling.html").read_text()

        assert "DRUG-SUB" in page and "quetiapine" in page
        assert "Judge only the highlighted entity" in page, (
            "the page never says which of the errors on the card it is asking about"
        )
        # The judged drug arrives wrapped as [[quetiapine]], which is in no
        # lexicon, so the line that separates DRUG-SUB from DRUG-DEL used to
        # come back blank on exactly the rows it exists for.
        finding = embedded(page, "CARDS")[0]["findings"][0]
        assert finding["expected_drugs"] == ["quetiapine"]
        assert finding["heard_drugs"] == ["humira"]

    def test_the_page_tells_the_labeller_to_judge_only_this_row(self, tmp_path):
        # A line can carry six changed words belonging to six different rows.
        # Without this the labeller judges the line rather than the finding.
        from src.failures import _LABELING_TEMPLATE

        assert "Judge only the highlighted entity" in _LABELING_TEMPLATE


class TestCodeDefinitions:
    """A finding kind with no code to land on is an unanswerable question.

    PRD W16: a transcript that produced nothing usable was being labelled once
    per lost entity, and none of the ten codes described "the transcription
    failed". `findings.py` now emits one ASR-COLLAPSE finding for it.
    """

    def test_asr_collapse_is_a_code(self):
        from src.failures import CODE_DEFINITIONS

        assert "ASR-COLLAPSE" in dict(CODE_DEFINITIONS)

    def test_asr_collapse_says_it_is_not_an_entity_error(self):
        from src.failures import CODE_DEFINITIONS

        assert "not an entity-level error" in dict(CODE_DEFINITIONS)["ASR-COLLAPSE"]

    def test_every_kind_the_detector_emits_has_a_code(self):
        from src.failures import CODE_DEFINITIONS

        codes = {code for code, _ in CODE_DEFINITIONS}
        for kind in [
            "DRUG-SUB",
            "DRUG-DEL",
            "DOSE-VAL",
            "DOSE-UNIT",
            "DOSE-MISS",
            "NEG-FLIP",
            "ASR-COLLAPSE",
        ]:
            assert kind in codes, f"{kind} findings have no code to land on"


class TestSheetCarriesSource:
    """Detector findings and human-found ones have to be told apart.

    The errors Suwaid finds that the detector missed are the measured
    false-negative rate, which is worth more than the sheet itself. They only
    carry that meaning if the export says which rows came from where.
    """

    def test_the_sheet_has_a_source_column(self):
        from src.failures import SHEET_COLUMNS

        assert "source" in SHEET_COLUMNS

    def test_generated_rows_are_marked_as_the_detectors(self, tmp_path):
        cards = embedded(write_page(tmp_path, [sheet_row()]), "CARDS")
        assert cards[0]["findings"][0]["source"] == "detector"


class TestGroupedByClipAndProvider:
    """One card per transcript, every finding on it listed beneath.

    Clip 8132758125fa0e31 produced 10 of the 150 rows on its own, scattered as
    rows 1, 7, 10, 12, 19, 24, 25, 59, 83 and 88. The labeller read the same
    reference ten times. PRD W5 and W16.
    """

    THREE = [
        sheet_row(finding_id=1, kind="DOSE-MISS", expected="0.035 mg", heard=""),
        sheet_row(finding_id=2, kind="DRUG-DEL", expected="glargine", heard=""),
        sheet_row(finding_id=3, clip_id="c2", kind="NEG-FLIP", expected="no"),
    ]

    def test_findings_on_one_transcript_share_a_card(self, tmp_path):
        cards = embedded(write_page(tmp_path, self.THREE), "CARDS")
        assert len(cards) == 2
        assert [len(c["findings"]) for c in cards] == [2, 1]

    def test_the_same_clip_on_another_provider_is_its_own_card(self, tmp_path):
        rows = [sheet_row(finding_id=1), sheet_row(finding_id=2, provider="gemini")]
        cards = embedded(write_page(tmp_path, rows), "CARDS")
        assert len(cards) == 2

    def test_the_card_carries_the_transcript_once(self, tmp_path):
        cards = embedded(write_page(tmp_path, self.THREE), "CARDS")
        assert cards[0]["ref"] and cards[0]["hyp"]
        # The text belongs to the card, not repeated onto every finding.
        assert "ref" not in cards[0]["findings"][0]

    def test_the_full_transcript_is_shown_when_it_is_available(self, tmp_path):
        texts = {("aai", "c1"): ("takes metformin daily at noon", "takes metro daily")}
        cards = embedded(write_page(tmp_path, [sheet_row()], texts), "CARDS")
        assert cards[0]["ref"] == "takes metformin daily at noon"
        assert cards[0]["hyp"] == "takes metro daily"

    def test_the_page_prints_reference_and_heard_once_per_card(self):
        from src.failures import _LABELING_TEMPLATE

        assert _LABELING_TEMPLATE.count(">reference") == 1
        assert _LABELING_TEMPLATE.count(">heard") == 1

    def test_each_finding_keeps_its_own_controls(self):
        from src.failures import _LABELING_TEMPLATE

        for field in ["failure_code", "severity", "note", "needs_listen"]:
            assert f'data-field="{field}"' in _LABELING_TEMPLATE


class TestHumanFoundErrors:
    """An error the detector missed must be recordable.

    The case that blocked labelling: reference "14 glargine sig 22 units at
    bedtime", heard "nicaragine sig 22 open bracket 22 close bracket unit at
    bedtime". The drug was mangled into a non-word and got no row, while the
    only row offered was a false dose error. MQM annotators select spans
    freely rather than confirming a machine's guesses.
    """

    def test_the_card_offers_an_add_control(self):
        from src.failures import _LABELING_TEMPLATE

        assert "add-human" in _LABELING_TEMPLATE
        assert "Add an error I found" in _LABELING_TEMPLATE

    def test_the_control_takes_free_text_for_both_sides(self):
        from src.failures import _LABELING_TEMPLATE

        assert 'data-field="expected"' in _LABELING_TEMPLATE
        assert 'data-field="heard"' in _LABELING_TEMPLATE

    def test_a_card_with_no_findings_still_gets_the_control(self, tmp_path):
        # Not gated on the detector. The whole point of the control is the
        # errors the detector did not find, so a card it said nothing about
        # must still be labellable.
        html = run_page(
            tmp_path,
            [sheet_row()],
            'out(cardHtml({ clip_id: "c9", provider: "aai", accent: "igbo",'
            '  tier: "A", domain: "clinical", ref: "r", hyp: "h",'
            "  findings: [] }, 0));",
        )
        assert "add-human" in html
        assert "Add an error I found" in html

    def test_the_added_error_carries_its_own_code_and_severity(self, tmp_path):
        html = run_page(
            tmp_path,
            [sheet_row()],
            'out(humanHtml("c1|aai", { id: "h1", expected: "", heard: "" }));',
        )
        for field in ["expected", "heard", "failure_code", "severity", "note"]:
            assert f'data-field="{field}"' in html
        assert 'value="DRUG-DEL"' in html and 'value="S1"' in html

    def test_human_findings_persist_alongside_the_labels(self, tmp_path):
        saved = run_page(
            tmp_path,
            [sheet_row()],
            'human["c1|aai"] = [{ id: "h1", expected: "glargine",'
            '  heard: "nicaragine", failure_code: "DRUG-DEL", severity: "S1" }];'
            'state["k"] = { failure_code: "NO-ERROR" };'
            "save(); out(stored());",
        )
        assert json.loads(saved)["human"]["c1|aai"][0]["expected"] == "glargine"
        assert json.loads(saved)["labels"]["k"]["failure_code"] == "NO-ERROR"


def run_page(tmp_path, rows, harness: str, texts=None) -> str:
    """Run the real page script in node and return what the harness printed.

    Every defect found in this file was invisible to the Python tests, because
    they checked the code that builds the page rather than the page. This runs
    the emitted JavaScript against a stub DOM, so a broken renderer or a
    shifted export column fails here rather than in Suwaid's browser.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not installed")

    page = write_page(tmp_path, rows, texts)
    script = page.split("<script>")[1].split("</script>")[0]
    stub = """
const store = {};
const node = () => ({ textContent: "", innerHTML: "", value: "", checked: false,
  type: "", dataset: {}, classList: { add() {}, remove() {} },
  addEventListener() {}, click() {}, scrollIntoView() {} });
const nodes = {};
globalThis.document = {
  getElementById: (id) => (nodes[id] = nodes[id] || node()),
  querySelectorAll: () => [],
  createElement: () => node(),
};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; },
};
globalThis.alert = () => {};
globalThis.confirm = () => true;
globalThis.URL = { createObjectURL: () => "blob:", revokeObjectURL: () => {} };
globalThis.Blob = class { constructor(parts) { this.parts = parts; } };
const stored = () => store["scribecheck-labels-v2"];
const out = (v) => console.log(typeof v === "string" ? v : JSON.stringify(v));
"""
    js = tmp_path / "harness.mjs"
    js.write_text(stub + script + "\n" + harness + "\n")
    result = subprocess.run([node, str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestExportColumnsStayAligned:
    """The header and the values are one list, checked by running the export.

    They were two hand-maintained lists once, they drifted, and every exported
    column shifted. No Python test noticed, because the export lives in JS.
    """

    def test_the_header_has_a_value_for_every_column(self, tmp_path):
        lines = run_page(
            tmp_path,
            [sheet_row(), sheet_row(finding_id=2, kind="DOSE-MISS", expected="5 mg")],
            'human["c1|aai"] = [{ id: "h1", expected: "glargine",'
            '  heard: "nicaragine" }];'
            'out(exportLines().join("\\n"));',
        ).splitlines()
        header = lines[0].split(",")
        assert len(lines) == 4, "two detector findings and one human row expected"
        for line in lines[1:]:
            assert len(_csv_fields(line)) == len(header)

    def test_the_exported_columns_are_the_csv_columns(self, tmp_path):
        from src.failures import SHEET_COLUMNS

        header = json.loads(run_page(tmp_path, [sheet_row()], "out(HEADER);"))
        assert header == SHEET_COLUMNS

    def test_a_detector_row_says_it_came_from_the_detector(self, tmp_path):
        lines = run_page(
            tmp_path,
            [sheet_row()],
            'state[CARDS[0].findings[0].key] = { failure_code: "DRUG-SUB",'
            '  severity: "S1", note: "n", needs_listen: true };'
            'out(exportLines().join("\\n"));',
        ).splitlines()
        row = dict(zip(lines[0].split(","), _csv_fields(lines[1])))
        assert row["source"] == "detector"
        assert row["failure_code"] == "DRUG-SUB" and row["severity"] == "S1"
        assert row["needs_listen"] == "yes"

    def test_a_human_row_says_it_came_from_a_human(self, tmp_path):
        lines = run_page(
            tmp_path,
            [sheet_row()],
            'human["c1|aai"] = [{ id: "h1", expected: "glargine",'
            '  heard: "nicaragine", failure_code: "DRUG-DEL", severity: "S1",'
            '  note: "detector missed it", needs_listen: false }];'
            'out(exportLines().join("\\n"));',
        ).splitlines()
        assert len(lines) == 3, "the human row did not reach the export"
        row = dict(zip(lines[0].split(","), _csv_fields(lines[2])))
        assert row["source"] == "human"
        assert row["expected"] == "glargine" and row["heard"] == "nicaragine"
        assert row["failure_code"] == "DRUG-DEL"
        assert row["clip_id"] == "c1" and row["provider"] == "aai"
        # It has no judged entity, so the card text goes out without the
        # numbered marks, which point at findings that are not this row.
        assert "[[" not in row["ref_excerpt"] and "*" not in row["ref_excerpt"]

    def test_an_untouched_human_row_is_not_exported(self, tmp_path):
        lines = run_page(
            tmp_path,
            [sheet_row()],
            'human["c1|aai"] = [{ id: "h1", expected: "", heard: "" }];'
            'out(exportLines().join("\\n"));',
        ).splitlines()
        assert len(lines) == 2


def _csv_fields(line: str) -> list[str]:
    """Split one exported line the way a CSV reader would."""
    import csv

    return next(csv.reader([line]))
