from dataclasses import replace
import json
import pandas as pd
import pytest

from leonardo.analysis.trend_start_patterns import run_study
from leonardo.gui.analysis.trend_start_results import StudyTable
from tests.gui_test.test_trend_start_patterns_tab import qapp
from tests.gui_test.test_pre_event_pattern_controls import configured_tab, dispose
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture, find_rule, TOLERANT


def test_pre_event_paging_ledger_views_and_detached_detail(qapp, tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, planted=TOLERANT, radius=1)
    study = run_study(parent, catalogue, req, axis)
    tab = configured_tab(parent, catalogue, req)
    try:
        tab.results.set_result(study)
        result = tab.results
        assert result.patterns.model.page_size == 50
        table = result.patterns
        assert table.model.rowCount() == min(50, len(table.model.frame))
        if table.model.page_count > 1:
            table.next.click(); table.table.selectRow(0)
            assert table.current_row() == table.model.frame.iloc[50].to_dict()
        row = find_rule(study, ("P03", "P07"))
        result._pattern_selected(study.frame("patterns").query("pattern_id == @row.pattern_id").iloc[0].to_dict())
        assert "P02, P03, P04" in result.pattern_detail.toPlainText()
        ledger = study.pattern_matches(row.pattern_id)
        result.show_matches(ledger, cohort="target", condition=row.condition)
        assert len(result.events.model.frame) == 4
        result.set_busy(True)
        assert not result.patterns.isEnabled() and not result.pattern_kind.isEnabled()
        assert not result.ranked.isEnabled()
        result.set_busy(False)
        assert result.patterns.isEnabled() and result.pattern_kind.isEnabled()
        result.pattern_detail.setPlainText("Unrelated stale condition")
        result.show_matches(ledger, cohort="target", condition=row.condition)
        result.show_matches(ledger, cohort="target", condition=row.condition)
        detail = result.pattern_detail.toPlainText()
        assert detail.startswith(row.condition) and "Unrelated stale condition" not in detail
        assert detail.count("SIMPLER CONDITIONS") == 1
        result.events.table.selectRow(0)
        assert result.event_detail.text() and not result.window.model.frame.empty
        result.occurrence_kind.setCurrentIndex(result.occurrence_kind.findData("exact_match"))
        assert result.events.model.frame.empty
        assert result.event_detail.text() == "" and result.window.model.frame.empty
        assert result.metric_detail.toPlainText() == result.evidence_text.toPlainText() == ""
        result.occurrence_kind.setCurrentIndex(result.occurrence_kind.findData("added_by_tolerance"))
        assert len(result.events.model.frame) == 4
        assert "same assessable rows" in result.pattern_detail.toPlainText()
        result.events.table.selectRow(0)
        assert set(result.window.model.frame.use) == {"mined history", "inspection only"}
        assert "Confirmed:" in result.event_detail.text()
        assert not result.assignments.model.frame.empty
        result._pattern_selected(None)
        assert result.pattern_detail.toPlainText() == ""
    finally:
        dispose(tab)


def test_incomplete_and_ordinary_states_are_explicit(qapp, tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    tab = configured_tab(parent, catalogue, req)
    try:
        limited = run_study(parent, catalogue, replace(req, pre_event=replace(req.pre_event, candidate_limit=2)), axis)
        tab.results.set_result(limited)
        assert "INCOMPLETE SEARCH" in tab.results.pattern_note.text()
        ordinary = run_study(parent, catalogue, replace(req, comparison="non_start"), axis)
        tab.results.set_result(ordinary)
        row = ordinary.frame("patterns").iloc[0]
        ledger = ordinary.pattern_matches(row.pattern_id, "comparison")
        tab.results.show_matches(ledger, cohort="comparison", condition=row.condition)
        tab.results.occurrence_kind.setCurrentIndex(tab.results.occurrence_kind.findData("all"))
        tab.results.events.table.selectRow(0)
        assert "Ordinary timestamp" in tab.results.event_detail.text()
        assert tab.results.metric_detail.toPlainText() == ""
        assert "SAVED OUTCOME" not in tab.results.evidence_text.toPlainText()
    finally:
        dispose(tab)


@pytest.mark.parametrize("chronological", (False, True))
def test_equivalent_centers_show_backend_exact_counts_for_both_cohorts(qapp, tmp_path, chronological):
    from tests.financial_tools_test.test_utc_classification import CASES
    sequences = (CASES[1], CASES[2])*4 if chronological else None
    parent, catalogue, axis, req, *_ = planted_fixture(
        tmp_path, planted=TOLERANT, radius=1, positive_bins=2, sequences=sequences)
    if chronological:
        req = replace(req, min_matches=1, pre_event=replace(req.pre_event, chronological=True, split_ms=axis[88]))
    study = run_study(parent, catalogue, req, axis)
    row = find_rule(study, ("P01", "P01"))
    tab = configured_tab(parent, catalogue, req)
    try:
        result = tab.results
        result.set_result(study)
        result._pattern_selected(row._asdict())
        text = result.pattern_detail.toPlainText()
        assert "Equivalent centers for this allowed set: P01, P02" in text
        assert "representative center P01" in text
        assert "exact occurrence views use the representative centers" in text
        for cohort in ("target", "comparison", "target"):
            ledger = study.pattern_matches(row.pattern_id, cohort)
            detail = json.loads(ledger.attrs["pattern_detail"])
            if not chronological:
                alternative = next(a for a in detail["exact_center_aliases"] if a["centers"] == ["P01", "P02"])
                assert alternative["exact_matched"] == 4 and alternative["comparison_exact_matched"] == 1
            else:
                assert any(a["later_exact_matched"] for a in detail["exact_center_aliases"])
                assert any(a["later_comparison_exact_matched"] for a in detail["exact_center_aliases"])
            result.show_matches(ledger, cohort=cohort, condition=row.condition)
            text = result.pattern_detail.toPlainText()
            assert text.count("EXACT CENTER INTERPRETATIONS") == 1
            assert text.count("SIMPLER CONDITIONS") == 1
            for alias in detail["exact_center_aliases"]:
                label = " AND ".join(f"{t['column']}[{t['offset']}]={center}"
                    for t, center in zip(detail["conditions"], alias["centers"], strict=True))
                block = text.split(label, 1)[1].split("\n\n", 1)[0]
                assert f"Discovery exact: target {alias['exact_matched']}; comparison {alias['comparison_exact_matched']}" in block
                if chronological:
                    assert f"Later exact: target {alias['later_exact_matched']}; comparison {alias['later_comparison_exact_matched']}" in block
            assert "delta[-4]=P01 AND volume_change[-1]=P01 (representative)" in text
        result._pattern_selected(None)
        assert result.pattern_detail.toPlainText() == ""
    finally:
        dispose(tab)


@pytest.mark.parametrize("sign", (1, -1))
def test_single_bin_tolerance_discloses_no_effect_and_respects_exact_override(qapp, tmp_path, sign):
    from leonardo.analysis.pre_event_patterns import terms_for_column
    from leonardo.analysis.service import AnalysisService
    from tests.analysis_test.test_analysis_service import make_database, request
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path/"study", radius=1)
    store, manifest, _ = make_database(tmp_path/"one_bin", {"delta": [sign*v for v in range(1, 21)]+[0.]})
    column = AnalysisService(store).run(request(manifest, "delta", positive_bins=1, negative_bins=1, minimum=1)).columns[0]
    terms = terms_for_column(column, "delta", (-1,), 1)
    term = next(t for t in terms if t.center != "Zero")
    zero = next(t for t in terms if t.center == "Zero")
    tab = configured_tab(parent, catalogue, req)
    try:
        result = tab.results
        study = run_study(parent, catalogue, req, axis)
        result.set_result(study)
        result._describe_pattern([term.to_dict()], "Single-bin example")
        assert "Tolerance has no effect: this sign has one bin." in result.pattern_detail.toPlainText()
        result._describe_pattern([zero.to_dict()], "Exact zero")
        assert "this sign has one bin" not in result.pattern_detail.toPlainText()
        exact = replace(study, request=replace(req, pre_event=replace(req.pre_event, overrides=(("delta", 0),))))
        result.set_result(exact)
        result._describe_pattern([term.to_dict()], "Exact override")
        assert "Tolerance has no effect" not in result.pattern_detail.toPlainText()
    finally:
        dispose(tab)
