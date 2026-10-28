"""Selection semantics, detached presentation, paging and display-time identity."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import pandas as pd
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab
from leonardo.gui.analysis.trend_start_results import StudyTable
from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_trend_start_patterns import counted_fixture

_APP = None


@pytest.fixture(scope="module")
def qapp():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def seed_tab(tab, parent, catalogue):
    tab.set_source(parent.entry, catalogue.run_key, tuple((c.request.source, c.request.measurement,
        c.profile.profile_id if c.profile else None) for c in parent.columns))
    tab.set_catalogue(catalogue)
    tab.set_execution_state(connected=True, busy=False)


def select_event(tab, kind="T", family=None):
    tab.utc.setCurrentIndex(1)
    tab.event.setCurrentIndex(tab.event.findData(kind))
    tab.family.setCurrentIndex(tab.family.findData(family))
    for i in range(tab.columns.count()):
        tab.columns.item(i).setCheckState(Qt.CheckState.Checked)


@pytest.mark.parametrize("mirror", (False, True))
def test_context_selection_separates_directions_and_reuses_parent(qapp, tmp_path, mirror):
    parent, catalogue, ts, req = counted_fixture(tmp_path, mirror=mirror)
    tab = TrendStartPatternsTab()
    try:
        assert not tab.run_button.isEnabled() and not tab.load_button.isEnabled()
        seed_tab(tab, parent, catalogue)
        assert tab.utc.currentData() is None and not tab.run_button.isEnabled()
        select_event(tab, req.event_kind, req.family)
        assert tab.run_button.isEnabled()
        assert all(str(tab.family.itemData(i)).startswith(req.trend_direction+"/") for i in range(2, tab.family.count()))
        request = tab.request()
        assert request.reference == parent.entry.reference and request.run_key == catalogue.run_key
        assert request.event_kind == req.event_kind and request.role_label in tab.context.text()
        tab.results.set_result(run_study(parent, catalogue, request, ts))
        assert tab.results._result is not None
        tab.event.setCurrentIndex(tab.event.findData("T" if mirror else "P"))
        assert tab.family.currentIndex() == 0 and tab.results._result is None and not tab.run_button.isEnabled()
        assert tab._run_key == catalogue.run_key
        tab.set_execution_state(connected=False, busy=False)
        assert not tab.load_button.isEnabled()
    finally:
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_timezone_preserves_integer_dates_result_and_request(qapp, tmp_path):
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
    parent, catalogue, ts, req = counted_fixture(tmp_path)
    tab = TrendStartPatternsTab()
    old = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        seed_tab(tab, parent, catalogue)
        select_event(tab, family=req.family)
        request = tab.request()
        study = run_study(parent, catalogue, request, ts)
        tab.results.set_result(study)
        for zone in ("UTC", "Europe/Rome", "America/New_York"):
            qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, zone)
            tab.refresh_display_time()
            assert tab.request() == request
            assert tab.results._result is study and zone in tab.date_zone.text()
            from leonardo.gui.display_time import format_display_timestamp_ms
            assert format_display_timestamp_ms(request.start_ms) in tab.results.context.text()
        tab.before.setValue(0)
        assert tab.request().sequence_lengths == ()
        assert tab.results._result is None
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, old)
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_family_zero_support_missing_metadata_and_column_limit(qapp, tmp_path):
    parent, catalogue, ts, req = counted_fixture(tmp_path)
    tab = TrendStartPatternsTab()
    try:
        seed_tab(tab, parent, catalogue)
        select_event(tab, family=req.family)
        tab.origin.setCurrentIndex(tab.origin.findData("direct_reversal"))
        assert tab.family.currentData() == req.family and "0 matching" in tab.family.currentText()
        study = run_study(parent, catalogue, tab.request(), ts)
        tab.results.set_result(study)
        assert tab.results.events.model.frame.empty and "No assessable" in tab.results.pattern_note.text()
        tab.set_source(parent.entry, catalogue.run_key, tuple((f"c{i}", "value", None) for i in range(9)))
        tab.set_catalogue(catalogue)
        tab.origin.setCurrentIndex(0)
        select_event(tab, family=req.family)
        assert not tab.run_button.isEnabled() and "1 to 8" in tab.context.text()
        empty = replace(catalogue, _json='{"status":"legacy_unavailable","instances":[]}')
        tab.set_catalogue(empty)
        assert not tab.run_button.isEnabled() and "No copied UTC" in tab.utc_details.text()
    finally:
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_every_paged_row_and_matching_event_evidence_is_accessible(qapp, tmp_path):
    table = StudyTable("paging")
    tab = TrendStartPatternsTab()
    try:
        table.set_frame(pd.DataFrame({"value": range(1001)}))
        assert table.model.rowCount() == 500
        table.next.click()
        table.table.selectRow(0)
        assert table.current_row()["value"] == 500
        table.page.setValue(3)
        assert table.model.rowCount() == 1
        assert table.model.data(table.model.index(0, 0)) == "1000"
        parent, catalogue, ts, req = counted_fixture(tmp_path, missing=True)
        study = run_study(parent, catalogue, req, ts)
        tab.results.set_result(study)
        result = tab.results
        result.events.table.selectRow(0)
        assert len(result.window.model.frame) == 4
        assert '"formation"' in result.evidence_text.toPlainText()
        assert '"continuations"' in result.evidence_text.toPlainText()
        assert "Confirmed:" in result.event_detail.text() and "Starting swing available:" in result.event_detail.text()
        assert list(result.window.model.frame.columns[:4]) == ["offset", "column", "ts_ms", "raw_value"]
        result.patterns.table.selectRow(0)
        calls = []
        result.matches_requested.connect(lambda *args: calls.append(args))
        result.target_matches.click()
        assert len(calls) == 1 and calls[0][1] == "target"
        matches = study.pattern_matches(*calls[0])
        result.show_matches(matches, cohort="target", condition="fixture")
        assert result.views.currentIndex() == 3 and len(result.events.model.frame) == len(matches)
        assert result.frequency.model.heat_columns
        assert "not prediction" in result.pattern_note.text()
        result.clear()
        assert result.event_note.text() == "Select an event to inspect its actual observations and evidence."
        assert not result.event_detail.text() and not result.context.toolTip()
        assert all(w.objectName().startswith("analysis_suite.patterns.") for w in
            (tab.utc, tab.event, tab.family, tab.run_button, result.views, result.events.table))
    finally:
        table.deleteLater()
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
