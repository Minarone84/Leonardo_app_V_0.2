from PySide6.QtCore import QCoreApplication, QEvent, Qt
from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab
from leonardo.analysis.trend_start_patterns import run_study
from tests.gui_test.test_trend_start_patterns_tab import qapp, seed_tab, select_event
from tests.analysis_test.test_pre_event_pattern_matching import planted_fixture


def configured_tab(parent, catalogue, request):
    tab = TrendStartPatternsTab()
    seed_tab(tab, parent, catalogue)
    select_event(tab, request.event_kind, request.family)
    tab.mode.setCurrentIndex(tab.mode.findData("pre_event"))
    tab.min_target.setValue(1); tab.min_comparison.setValue(1); tab.min_matches.setValue(2)
    tab.pre_event_controls.max_terms.setValue(2)
    return tab


def dispose(widget):
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_new_controls_and_post_inspection_filters_invalidate_only_study(qapp, tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    tab = configured_tab(parent, catalogue, req)
    try:
        assert tab.run_button.isEnabled() and not tab.before.isEnabled()
        assert tab.request().pre_event.offsets == (-6, -5, -4, -3, -2, -1)
        result = run_study(parent, catalogue, tab.request(), axis)
        tab.results.set_result(result)
        assert tab.results._result is result
        tab.refinement.movement.setChecked(True)
        tab.refinement.basis.setCurrentIndex(tab.refinement.basis.findData("formation"))
        tab.refinement.movement.rows[0].minimum.setText("1000")
        assert tab.results._result is None
        assert tab._run_key == catalogue.run_key and tab._catalogue is catalogue
        filtered = run_study(parent, catalogue, tab.request(), axis)
        assert filtered.frame("patterns").empty
        tab.refinement.movement.setChecked(False)
        tab.pre_event_controls.lead.setValue(3)
        assert tab.request().pre_event.offsets == (-8, -7, -6, -5, -4, -3)
        assert "After-event window: inspection only" in tab.context.text()
        tab.set_execution_state(connected=True, busy=True)
        assert not tab.pre_event_controls.isEnabled() and not tab.run_button.isEnabled()
    finally:
        dispose(tab)


def test_comparison_incompatibility_keeps_filter_choices_and_legacy_mode(qapp, tmp_path):
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path)
    tab = configured_tab(parent, catalogue, req)
    try:
        tab.pre_event_controls.comparison.setCurrentIndex(1)
        assert not tab.run_button.isEnabled() and "completed-trend" in tab.context.text()
        tab.refinement.movement.setChecked(True)
        tab.refinement.movement.rows[0].minimum.setText("1")
        assert tab.run_button.isEnabled()
        tab.pre_event_controls.comparison.setCurrentIndex(2)
        assert "outcome bounds apply to targets only" in tab.refinement.note.text()
        assert "requires filters off" not in tab.refinement.note.text()
        tab.refinement.preceding.setChecked(True)
        tab.refinement.memberships["down"].setCurrentIndex(tab.refinement.memberships["down"].findData(True))
        assert not tab.run_button.isEnabled() and tab.refinement.preceding.isChecked()
        assert "preceding-context" in tab.context.text()
        tab.mode.setCurrentIndex(0)
        assert tab.request().pre_event is None and tab.request().comparison == "other_families"
        assert tab.before.isEnabled()
        assert "requires filters off" in tab.refinement.note.text()
    finally:
        dispose(tab)


def test_tolerance_overrides_exact_only_modes_and_split_timezone(qapp, tmp_path):
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
    parent, catalogue, axis, req, *_ = planted_fixture(tmp_path, measurement="value")
    tab = configured_tab(parent, catalogue, req)
    old = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        tab.pre_event_controls.tolerance.setCurrentIndex(1)
        spec = tab.request().pre_event
        assert all(spec.radius(name) == 0 for name in req.columns)
        assert all(not combo.isEnabled() for combo in tab.pre_event_controls._columns.values())
        tab.pre_event_controls.chronological.setChecked(True)
        tab.pre_event_controls.custom_split.setChecked(True)
        original = tab.request()
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, "America/New_York")
        tab.refresh_display_time()
        assert tab.request() == original
        tab.columns.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert "Primary combinations disabled" in tab.context.text()
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, old)
        dispose(tab)
