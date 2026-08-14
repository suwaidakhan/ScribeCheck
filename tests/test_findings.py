"""Individual findings, one per error, SPEC section 6 as revised.

The metrics used to return counts. Counts cannot be labelled: a clip with three
errors arrived as one row carrying one dropdown, the largest error class reached
the sheet at 5 percent coverage, and the excerpt centred on whichever difference
came first rather than on the error being judged.

So the primitive is now a finding: what was expected, what was heard instead,
and where in the reference it sits. Counts are derived from findings, and the
labelling sheet is one row per finding. See docs/PRD_EVAL_V2.md W2, W3 and W5.
"""

import pytest
from src.findings import dose_findings, drug_findings, findings_for, negation_findings

LEX = {
    "aspirin",
    "warfarin",
    "metformin",
    "metronidazole",
    "pyrimethamine",
    "trimethoprim",
    "haloperidol",
    "chlorpromazine",
}


class TestDrugFindings:
    def test_a_surviving_drug_produces_no_finding(self):
        assert drug_findings("takes aspirin", "takes aspirin", LEX) == []

    def test_a_substitution_names_both_sides(self):
        found = drug_findings("takes metformin", "takes metronidazole", LEX)
        assert len(found) == 1
        assert found[0]["kind"] == "DRUG-SUB"
        assert found[0]["expected"] == "metformin"
        assert found[0]["heard"] == "metronidazole"

    def test_a_deletion_names_the_missing_drug_and_admits_it_heard_nothing(self):
        found = drug_findings("takes metformin daily", "takes wxyzzy daily", LEX)
        assert len(found) == 1
        assert found[0]["kind"] == "DRUG-DEL"
        assert found[0]["expected"] == "metformin"
        assert found[0]["heard"] == ""

    def test_two_broken_drugs_produce_two_findings(self):
        # The whole point: one row per error, not one row per clip.
        found = drug_findings(
            "gave warfarin and metformin", "gave wxyzzy and metronidazole", LEX
        )
        assert len(found) == 2
        assert {f["expected"] for f in found} == {"warfarin", "metformin"}

    def test_a_surviving_drug_is_not_blamed_for_a_broken_one(self):
        # W1, kept as a finding-level test so the fix cannot regress silently.
        found = drug_findings(
            "includes pyrimethamine and trimethoprim",
            "includes pyrimethamine and trimethropium",
            LEX,
        )
        assert len(found) == 1
        assert found[0]["kind"] == "DRUG-DEL"
        assert found[0]["expected"] == "trimethoprim"

    def test_every_finding_carries_a_position_in_the_reference(self):
        # The excerpt centres on this, so it has to be the error's own position.
        found = drug_findings(
            "one two three four five metformin", "one two three four five wxyzzy", LEX
        )
        assert found[0]["ref_index"] == 5


class TestDoseFindings:
    def test_a_surviving_dose_produces_no_finding(self):
        assert dose_findings("take 500 mg", "take 500 mg") == []

    def test_a_changed_value_names_both(self):
        found = dose_findings("take 200 mg", "take 400 mg")
        assert found[0]["kind"] == "DOSE-VAL"
        assert "200" in found[0]["expected"]
        assert "400" in found[0]["heard"]

    def test_a_changed_unit_is_its_own_kind(self):
        found = dose_findings("take 500 mg", "take 500 mcg")
        assert found[0]["kind"] == "DOSE-UNIT"

    def test_a_missing_dose_heard_nothing(self):
        found = dose_findings("take 500 mg twice", "take it twice")
        assert found[0]["kind"] == "DOSE-MISS"
        assert found[0]["heard"] == ""

    def test_each_broken_dose_is_its_own_finding(self):
        found = dose_findings("40 mg and 10 units", "50 mg and 20 units")
        assert len(found) == 2


class TestNegationFindings:
    def test_a_surviving_negation_produces_no_finding(self):
        assert negation_findings("denies chest pain", "denies chest pain") == []

    def test_a_lost_negation_is_a_finding(self):
        found = negation_findings("patient denies chest pain", "patient has chest pain")
        assert found[0]["kind"] == "NEG-FLIP"
        assert found[0]["expected"] == "denies"

    def test_each_lost_cue_is_its_own_finding(self):
        found = negation_findings("no fever and denies cough", "fever and has cough")
        assert len(found) == 2


class TestFindingsFor:
    """The single entry point the sheet builder uses."""

    def test_collects_every_kind_from_one_clip(self):
        found = findings_for(
            "takes metformin 500 mg and denies pain",
            "takes metronidazole 50 mg and has pain",
            LEX,
        )
        assert {f["kind"] for f in found} == {"DRUG-SUB", "DOSE-VAL", "NEG-FLIP"}

    def test_a_clean_clip_yields_nothing(self):
        assert findings_for("takes aspirin 10 mg", "takes aspirin 10 mg", LEX) == []

    def test_every_finding_is_self_describing(self):
        # A row must stand alone: the sheet shows one finding, not one clip.
        for f in findings_for(
            "takes metformin 500 mg", "takes metronidazole 50 mg", LEX
        ):
            assert set(f) >= {"kind", "expected", "heard", "ref_index"}
            assert f["kind"]
            assert f["expected"]

    def test_findings_are_ordered_by_position(self):
        found = findings_for(
            "denies pain then takes metformin", "has pain then takes wxyzzy", LEX
        )
        assert [f["ref_index"] for f in found] == sorted(f["ref_index"] for f in found)


class TestStratifiedSelection:
    """W3. The sheet has to be a sample you can compute a rate from.

    The old sheet took one row per clip and filled priority bands in order, so
    DRUG-DEL reached it at 5 percent while three classes reached 100 percent.
    Any "N percent of failures are severity 1" computed from that would describe
    a population that does not exist.

    The fix is ordinary survey practice: take a census of the rare classes,
    sample the abundant ones, and record the inclusion weight so the population
    figure can be recovered.
    """

    def frame(self, counts):
        import pandas as pd

        rows = []
        for kind, n in counts.items():
            for i in range(n):
                rows.append({"kind": kind, "clip_id": f"c{kind}{i}",
                             "provider": "whisper", "expected": "x", "heard": "y",
                             "ref_index": 0, "tier": "A", "domain": "clinical",
                             "accent": "hausa"})
        return pd.DataFrame(rows)

    def test_a_rare_class_is_taken_whole(self):
        from src.findings import select_findings

        # 5 drug substitutions exist in the whole corpus. Sampling them
        # proportionally would take one, and it is the class the project is about.
        out = select_findings(self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163}), target=100)
        assert (out.kind == "DRUG-SUB").sum() == 5

    def test_an_abundant_class_is_sampled_not_taken_whole(self):
        from src.findings import select_findings

        out = select_findings(self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163}), target=100)
        assert (out.kind == "DRUG-DEL").sum() < 163

    def test_the_sheet_hits_its_target_size(self):
        from src.findings import select_findings

        out = select_findings(
            self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163, "DOSE-MISS": 92}), target=100
        )
        assert len(out) == 100

    def test_a_census_stratum_weighs_one(self):
        from src.findings import select_findings

        out = select_findings(self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163}), target=100)
        assert (out[out.kind == "DRUG-SUB"].weight == 1.0).all()

    def test_a_sampled_stratum_weighs_more_than_one(self):
        from src.findings import select_findings

        out = select_findings(self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163}), target=100)
        assert (out[out.kind == "DRUG-DEL"].weight > 1.0).all()

    def test_weights_reconstruct_the_population(self):
        # The property that makes a rate computable: summed weights recover the
        # true totals per class, so a labelled subsample estimates the whole.
        from src.findings import select_findings

        counts = {"DRUG-SUB": 5, "DRUG-DEL": 163, "DOSE-MISS": 92, "NEG-FLIP": 38}
        out = select_findings(self.frame(counts), target=120)
        for kind, n in counts.items():
            assert round(out[out.kind == kind].weight.sum()) == n

    def test_selection_is_deterministic(self):
        from src.findings import select_findings

        f = self.frame({"DRUG-SUB": 5, "DRUG-DEL": 163})
        a = select_findings(f, target=80)
        b = select_findings(f, target=80)
        assert list(a.clip_id) == list(b.clip_id)

    def test_everything_is_taken_when_the_target_exceeds_the_population(self):
        from src.findings import select_findings

        out = select_findings(self.frame({"DRUG-SUB": 5, "DRUG-DEL": 10}), target=500)
        assert len(out) == 15
        assert (out.weight == 1.0).all()


class TestExcerptCentresOnTheFinding:
    """W2. The row must show the error it is asking about.

    The old excerpt centred on the first textual difference, which is usually
    capitalisation, so the clinical entity being judged was often off screen.
    Row 15 hid 200mg becoming 400mg. Row 12 looked clean while multivitamin had
    become emotivitamin at the end of the clip.
    """

    def test_centres_on_a_late_error_not_an_early_diff(self):
        from src.findings import excerpt_around

        ref = "The following medication change was made ADDED folate thiamine and a multivitamin"
        hyp = "the following medication change was made added folate thiamine and emotivitamin"
        # The finding sits at the last token, far past the capitalisation diff.
        shown_ref, shown_hyp = excerpt_around(ref, hyp, ref_index=len(ref.split()) - 1)
        assert "multivitamin" in shown_ref
        assert "emotivitamin" in shown_hyp

    def test_the_early_diff_alone_does_not_drag_the_window(self):
        from src.findings import excerpt_around

        ref = "The " + " ".join(["filler"] * 30) + " metformin"
        hyp = "the " + " ".join(["filler"] * 30) + " wxyzzy"
        shown_ref, _ = excerpt_around(ref, hyp, ref_index=len(ref.split()) - 1)
        assert "metformin" in shown_ref

    def test_marks_the_finding_distinctly_from_ordinary_diffs(self):
        from src.findings import excerpt_around

        shown_ref, _ = excerpt_around(
            "takes metformin daily", "takes wxyzzy daily", ref_index=1
        )
        assert "[[metformin]]" in shown_ref, "the judged entity needs its own marker"

    def test_short_text_is_shown_whole(self):
        from src.findings import excerpt_around

        shown_ref, shown_hyp = excerpt_around("takes metformin", "takes wxyzzy", 1)
        assert "takes" in shown_ref and "takes" in shown_hyp

    def test_a_dose_finding_shows_both_numbers(self):
        from src.findings import excerpt_around

        ref = " ".join(["w"] * 20) + " ibuprofen 200 mg and 10 mg"
        hyp = " ".join(["w"] * 20) + " ibuprofen 400 mg and 10 mg"
        shown_ref, shown_hyp = excerpt_around(ref, hyp, ref_index=21)
        assert "200" in shown_ref
        assert "400" in shown_hyp


class TestEveryFindingKindHasACode:
    """The dropdown must be able to express what the detector produces.

    Found in a browser: labelling a DOSE-MISS row silently did nothing. A
    select rejects a value that is not one of its options, so the row never
    completed and the progress counter sat one behind. 92 of the 328 findings
    are DOSE-MISS and the taxonomy had no code for them.
    """

    KINDS = {"DRUG-SUB", "DRUG-DEL", "DOSE-VAL", "DOSE-UNIT", "DOSE-MISS", "NEG-FLIP"}

    def test_every_kind_the_detector_emits_is_a_selectable_code(self):
        from src.failures import CODE_DEFINITIONS

        codes = {code for code, _ in CODE_DEFINITIONS}
        assert self.KINDS <= codes, f"no code for: {self.KINDS - codes}"

    def test_the_judgment_codes_beyond_the_detector_survive(self):
        # The human can see things the detector cannot, and must keep saying so.
        from src.failures import CODE_DEFINITIONS

        codes = {code for code, _ in CODE_DEFINITIONS}
        assert {"TERM-CORRUPT", "PHON-ACCENT", "BENIGN", "NO-ERROR"} <= codes

    def test_the_real_corpus_emits_no_kind_without_a_code(self):
        import pandas as pd
        from src.failures import CODE_DEFINITIONS

        path = "results/all_findings.csv"
        try:
            emitted = set(pd.read_csv(path)["kind"])
        except FileNotFoundError:
            import pytest

            pytest.skip(f"{path} not built yet")
        assert emitted <= {code for code, _ in CODE_DEFINITIONS}
