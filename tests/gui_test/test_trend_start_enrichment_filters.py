"""Refinement controls, immutable requests and typed outcome presentation."""
from decimal import Decimal

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from leonardo.gui.analysis.trend_start_patterns_tab import TrendStartPatternsTab, RefinementControls
from leonardo.gui.analysis.trend_start_results import StudyTableModel, duration_text, _metric_lines, _refinement_lines
from leonardo.analysis.trend_start_patterns import run_study
from tests.analysis_test.test_trend_start_patterns import counted_fixture
from tests.gui_test.test_trend_start_patterns_tab import qapp, seed_tab, select_event


@pytest.fixture
def controls(qapp):
    widget = RefinementControls()
    yield widget
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_default_empty_groups_and_explicit_zero(controls):
    assert not controls.toggle.isChecked() and controls.body.isHidden()
    assert not controls.value().active
    controls.movement.setChecked(True)
    assert not controls.value().active
    controls.movement.rows[0].minimum.setText("0")
    value = controls.value()
    assert value.active and value.basis == "completed"
    assert value.movement[0].minimum == Decimal(0)
    controls.movement.setChecked(False)
    assert not controls.value().active
    controls.reset()
    assert not controls.value().active and len(controls.movement.rows) == 1


def test_refinement_controls_fit_the_standard_window_center_pane(controls):
    controls.toggle.setChecked(True)
    controls.resize(480, 720)
    controls.show()
    QCoreApplication.processEvents()
    assert controls.minimumSizeHint().width() <= 480
    assert controls.width() == 480


def test_exact_time_conversion_and_multiple_conditions(controls):
    controls.duration.setChecked(True)
    row = controls.duration.rows[0]
    row.unit.setCurrentIndex(row.unit.findData("minutes"))
    row.minimum.setText("1.25")
    row.maximum.setText("2.5")
    second = controls.duration.add_row()
    second.field.setCurrentIndex(second.field.findData("confirmation_delay"))
    second.unit.setCurrentIndex(second.unit.findData("seconds"))
    second.maximum.setText("0.001")
    value = controls.value()
    assert len(value.duration) == 2
    assert value.duration[0].unit == "ms"
    assert value.duration[0].minimum == 75000 and value.duration[0].maximum == 150000
    assert value.duration[1].maximum == 1
    second.maximum.setText("0.0001")
    with pytest.raises(ValueError):
        controls.value()
    controls.duration.remove_row(second)
    assert len(controls.value().duration) == 1


@pytest.mark.parametrize("minimum,maximum", (("NaN", ""), ("Infinity", ""), ("abc", ""), ("3", "2")))
def test_invalid_bounds_are_not_silently_dropped(controls, minimum, maximum):
    controls.movement.setChecked(True)
    row = controls.movement.rows[0]
    row.minimum.setText(minimum)
    row.maximum.setText(maximum)
    with pytest.raises(ValueError):
        controls.value()
    controls.movement.setChecked(False)
    assert not controls.value().active


def test_basis_cohorts_overlap_and_fractional_mean_bars(controls):
    controls.preceding.setChecked(True)
    for key in ("down", "range"):
        controls.memberships[key].setCurrentIndex(1)
    value = controls.value()
    assert value.preceding.down is True and value.preceding.range is True
    assert value.preceding.up is None and not value.measurements_active
    controls.basis.setCurrentIndex(controls.basis.findData("formation"))
    assert controls.cohort.count() == 4 and controls.cohort.currentData() == "formation_recovered"
    controls.pullbacks.setChecked(True)
    row = controls.pullbacks.rows[0]
    row.field.setCurrentIndex(row.field.findData("recovered_duration"))
    row.statistic.setCurrentIndex(row.statistic.findData("mean"))
    row.minimum.setText("1.5")
    assert controls.value().pullbacks.conditions[0].minimum == Decimal("1.5")
    controls.duration.setChecked(True)
    controls.duration.rows[0].field.setCurrentIndex(1)
    controls.duration.rows[0].minimum.setText("0")
    with pytest.raises(ValueError):
        controls.value()
    assert controls.duration.rows[0].minimum.text() == "0"


def test_previous_family_follows_explicit_direction(controls):
    families = ("UP/TPTP/0,2,1,3", "DOWN/PTPT/3,1,2,0")
    controls.set_previous_families(families)
    controls.preceding.setChecked(True)
    controls.previous_direction.setCurrentIndex(controls.previous_direction.findData("UP"))
    assert controls.previous_family.count() == 2
    controls.previous_family.setCurrentIndex(1)
    assert controls.value().preceding.previous_family == families[0]
    controls.previous_direction.setCurrentIndex(controls.previous_direction.findData("NONE"))
    assert not controls.previous_family.isEnabled()
    assert controls.value().preceding.previous_family is None


def test_non_start_incompatibility_clear_and_missing_enrichment(qapp, tmp_path):
    parent, catalogue, ts, req = counted_fixture(tmp_path)
    tab = TrendStartPatternsTab()
    try:
        seed_tab(tab, parent, catalogue)
        select_event(tab, family=req.family)
        tab.comparison.setCurrentIndex(tab.comparison.findData("non_start"))
        assert tab.run_button.isEnabled()
        tab.refinement.movement.setChecked(True)
        tab.refinement.movement.rows[0].minimum.setText("0")
        assert tab.comparison.currentData() == "non_start" and not tab.run_button.isEnabled()
        assert "non-start" in tab.context.text().lower()
        tab.comparison.setCurrentIndex(tab.comparison.findData("other_families"))
        assert tab.family.currentData() == req.family
        assert "0" in tab.family.currentText()
        study = run_study(parent, catalogue, tab.request(), ts)
        tab.results.set_result(study)
        events = study.frame("events")
        assert not events.empty and not events.refinement_eligible.any()
        assert not study.frame("refinement_funnel").empty
        request = tab.request()
        tab.refinement.clear_button.click()
        assert not tab.request().refinement.active
        assert request.refinement.active and tab._run_key == catalogue.run_key
        assert tab.family.currentData() == req.family and tab.results._result is None
        tab.set_execution_state(connected=True, busy=True)
        assert not tab.refinement.isEnabled()
        tab.clear_source()
        assert not tab.refinement.value().active
    finally:
        tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_durations_never_render_as_calendar_dates(qapp):
    import pandas as pd
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
    model = StudyTableModel()
    model.set_frame(pd.DataFrame({"elapsed_ms": [90000], "confirmation_delay_ms": [2000], "anchor_ms": [1700000000000]}))
    old = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        durations = []
        for zone in ("UTC", "Europe/Rome", "America/New_York"):
            qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, zone)
            durations.append(tuple(model.data(model.index(0, column)) for column in (0, 1)))
        assert durations[0] == durations[1] == durations[2]
        assert durations[0] == (duration_text(90000), duration_text(2000))
        assert "1970" not in str(durations)
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, old)


def test_nested_recovered_duration_has_units_but_support_is_a_count():
    lines = _metric_lines({"recovered_duration_ms": {"mean": 30000.0, "maximum": 60000, "eligible_count": 2}})
    assert lines == ["recovered duration ms · mean: 30 s", "recovered duration ms · maximum: 1 min",
                     "recovered duration ms · eligible count: 2"]


@pytest.mark.parametrize("mirror", (False, True))
def test_readable_saved_outcome_keeps_sign_units_and_support(tmp_path, mirror):
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture, ENDED, movement, first_event
    from tests.analysis_test.test_trend_start_catalogue import study_request
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, ENDED, mirror=mirror)
    event = first_event(catalogue)
    request = study_request(parent, catalogue, kind="P" if mirror else "T", family=event["family"], refinement=movement())
    study = run_study(parent, catalogue, request, axis)
    lines = _refinement_lines(study.evidence(event["event_id"])["refinement"], request)
    text = "\n".join(lines)
    assert "Included after refinement" in text and "SAVED OUTCOME · ended" in text
    assert ("Signed endpoint movement: -" in text) == mirror
    assert "Structural duration:" in text and " min" in text
    assert "Total recovered duration:" in text and "supported members:" in text
    assert "\"pullback_id\"" not in text


@pytest.mark.parametrize("mirror", (False, True))
@pytest.mark.parametrize("basis", ("completed", "formation", "observed"))
def test_event_time_boundaries_follow_basis_and_refresh_timezone(qapp, tmp_path, basis, mirror):
    from leonardo.gui.analysis.trend_start_results import TrendStartResults
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY, format_display_timestamp_ms
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture, ENDED, STANDARD, movement, first_event
    from tests.analysis_test.test_trend_start_catalogue import study_request
    parent, catalogue, axis, analysis, _ = enriched_fixture(
        tmp_path, STANDARD if basis == "observed" else ENDED, mirror=mirror)
    event = first_event(catalogue)
    request = study_request(parent, catalogue, kind="P" if mirror else "T", family=event["family"],
                            refinement=movement(basis))
    study = run_study(parent, catalogue, request, axis)
    metrics = next(e for e in analysis["utc_episode_metrics"]["episodes"]
                   if e["episode_id"] == event["witnesses"][0]["episode"]["episode_id"])
    formation, episode = metrics["formation_metrics"], metrics["episode_metrics"]
    structural = formation if basis == "formation" else episode[
        "final_structural" if basis == "completed" else "observed_structural"]
    limits = {
        "Start (S)": formation["movement"]["start"]["ts_ms"],
        "Formation end (F)": formation["interval_limit"]["ts_ms"],
        "Structural endpoint (E)": structural["movement"]["endpoint"]["ts_ms"],
        "Observation limit (O)": (formation["interval_limit"] if basis == "formation"
                                  else episode["observation_limit"])["ts_ms"],
    }
    if basis == "formation":
        assert len({limits[name] for name in limits if name != "Start (S)"}) == 1
    elif basis == "completed":
        assert limits["Observation limit (O)"] > limits["Structural endpoint (E)"]
    else:
        assert limits["Structural endpoint (E)"] > limits["Formation end (F)"]
        assert episode["status"] == "open"
    widget = TrendStartResults()
    old_zone = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    try:
        widget.set_result(study)
        widget.events.table.selectRow(0)
        evidence = widget.evidence_text.toPlainText()
        durations, displayed = [], []
        for zone in ("UTC", "Europe/Rome", "America/New_York"):
            qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, zone)
            widget.refresh_display_time()
            text = widget.metric_detail.toPlainText()
            for label, instant in limits.items():
                assert f"{label}: {format_display_timestamp_ms(instant, zone_name=zone)}" in text
            assert ("Frozen formation: E and O coincide with F." in text) == (basis == "formation")
            assert f"Confirmed: {format_display_timestamp_ms(formation['confirmed_at_ms'], zone_name=zone)}" in widget.event_detail.text()
            assert widget.evidence_text.toPlainText() == evidence
            displayed.append(tuple(line for line in text.splitlines() if line.startswith(tuple(limits))))
            durations.append(tuple(line for line in text.splitlines() if line.startswith(
                ("Structural duration:", "Endpoint extension:", "Observed elapsed:", "Formation confirmation delay:",
                 "Spacing:", "Total recovered duration:"))))
        assert len(set(displayed)) == 3
        assert durations[0] == durations[1] == durations[2]
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, old_zone)
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_missing_time_boundaries_are_explicit_without_reconstructing_them(tmp_path):
    from copy import deepcopy
    from tests.analysis_test.test_trend_start_enrichment import enriched_fixture, ENDED, movement, first_event
    from tests.analysis_test.test_trend_start_catalogue import study_request
    parent, catalogue, axis, _, _ = enriched_fixture(tmp_path, ENDED)
    event = first_event(catalogue)
    request = study_request(parent, catalogue, family=event["family"], refinement=movement())
    detail = deepcopy(run_study(parent, catalogue, request, axis).evidence(event["event_id"])["refinement"])
    measured = detail["projection"]["measurements"]
    measured["structural"]["movement"]["endpoint"]["ts_ms"] = None
    measured["observation_limit"]["ts_ms"] = None
    text = "\n".join(_refinement_lines(detail, request))
    assert "Structural endpoint (E): Unavailable" in text
    assert "Observation limit (O): Unavailable" in text
    assert measured["structural"]["duration"]["ms"] is not None
    for projection, resolution in (({}, "resolved"), (None, "ambiguous_saved_measurements"),
                                   (None, "measurement_unavailable")):
        # Context-only and unresolved views must never borrow a raw witness's times.
        detail["projection"], detail["resolution"] = projection, resolution
        lines = _refinement_lines(detail, request)
        assert not any(line.startswith(("Start (S):", "Formation end (F):", "Structural endpoint (E):",
                                       "Observation limit (O):")) for line in lines)
