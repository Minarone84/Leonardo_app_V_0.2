"""R05: real widget event geometry, without a post-event manual refresh."""
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.oscillator_widget import OscillatorStudyWidget
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.research import (
    HorizontalViewport, ResidentOHLCVSlice, ResidentStudyProjection,
    StudyLineStyle, StudyPresentation,
)


def _receipt(request, value):
    root = os.environ.get("R02_OBSERVATIONS")
    if root:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
        (path / (key + ".json")).write_text(
            json.dumps({"node": request.node.nodeid, **value}, indent=2) + "\n",
            encoding="utf-8",
        )


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _fixture(study_id="r05"):
    count = 32
    timestamps = tuple(1_700_000_000_000 + i * 60_000 for i in range(count))
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    resident = ResidentOHLCVSlice(
        market, "a" * 64, 0, count, timestamps,
        (100.0,) * count, (102.0,) * count, (99.0,) * count,
        (101.0,) * count, (1.0,) * count, False, False, timestamps[0], timestamps[-1],
    )
    state = CandlestickInteractionState(
        HorizontalViewport(count, visible_count=20, left_padding=0, right_padding=0),
        resident,
    )
    values = [10.0, 50.0, 90.0, 50.0] * 8
    values[23] = float("nan")
    values[24] = 0.0
    projection = ResidentStudyProjection(
        study_id, market, "a" * 64, "oscillator", 0, count, timestamps,
        {"rsi_3": tuple(values)}, {},
    )
    presentation = StudyPresentation(
        study_id, True, "oscillator:" + study_id,
        {"rsi_3": StudyLineStyle("rsi_3", "#A855F7")}, {}, tool_key="rsi",
    )
    return state, projection, presentation


def _bound(app):
    state, projection, presentation = _fixture()
    widget = OscillatorStudyWidget("r05")
    widget.resize(540, 220)
    widget.show()
    app.processEvents()
    widget.set_interaction_state(state)
    widget.set_study_state(projection, presentation)
    return widget, state, projection, presentation


def _destroy(app, widget):
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _geometry(widget):
    scene = widget.scene_plan
    assert scene is not None
    rect = scene.plot_rect
    assert (rect.x, rect.y, rect.width, rect.height) == (
        2.0, 4.0, max(1.0, widget.width() - 66.0),
        max(1.0, widget.height() - 4.0 - (24.0 if widget.time_axis_visible else 4.0)),
    )
    return {"widget": [widget.width(), widget.height()], "axis": widget.time_axis_visible,
            "plot": asdict(rect)}


@pytest.mark.parametrize("size,axis", [((900, 380), False), ((300, 130), False),
                                               ((900, 380), True), ((300, 130), True)])
def test_resize_rebuilds_scene(app, request, size, axis):
    widget, state, projection, presentation = _bound(app)
    try:
        widget.set_time_axis_visible(axis)
        before = state.viewport.snapshot()
        old_scene = widget.scene_plan
        widget.resize(*size)
        app.processEvents()
        observed = {"size": list(size), "scene": asdict(widget.scene_plan.plot_rect),
                    "viewport": asdict(state.viewport.snapshot())}
        _receipt(request, observed)
        _geometry(widget)
        assert widget.scene_plan is not old_scene
        assert state.viewport.snapshot() == before
        assert widget.projection is projection and widget.presentation is presentation
    finally:
        _destroy(app, widget)


def test_axis_off_on_off_and_same_bool_noop(app, request):
    widget, state, projection, presentation = _bound(app)
    try:
        before = state.viewport.snapshot()
        scenes = []
        for visible in (False, True, False):
            widget.set_time_axis_visible(visible)
            app.processEvents()
            scenes.append(_geometry(widget))
            scene = widget.scene_plan
            widget.set_time_axis_visible(visible)
            assert widget.scene_plan is scene
        with pytest.raises(TypeError, match="boolean"):
            widget.set_time_axis_visible(1)
        assert state.viewport.snapshot() == before
        assert widget.projection is projection and widget.presentation is presentation
        _receipt(request, {"scenes": scenes, "same_bool_noop": True})
    finally:
        _destroy(app, widget)


def test_source_alignment_missing_zero_and_threshold_segments(app, request):
    widget, state, projection, presentation = _bound(app)
    try:
        before = state.viewport.snapshot()
        assert before.visible_count == 20
        source = projection.render_series["rsi_3"]
        widget.resize(850, 320)
        widget.set_time_axis_visible(True)
        app.processEvents()
        scene = widget.scene_plan
        _geometry(widget)
        points = [point for strip in scene.line_strips for point in strip.points]
        integral = {int(p.global_index): p.value for p in points if float(p.global_index).is_integer()}
        expected = {i: source[i] for i in range(before.start_index, before.end_index_exclusive)
                    if math.isfinite(source[i])}
        assert integral == expected
        assert 23 not in integral and integral[24] == 0.0
        fractions = [p for p in points if not float(p.global_index).is_integer()]
        assert fractions  # Threshold crossings are interpolated, not extra input rows.
        for point in points:
            assert point.x == pytest.approx(scene.plot_rect.x +
                (point.global_index - before.start_index + 0.5) /
                before.visible_count * scene.plot_rect.width)
            assert point.y == pytest.approx(scene.plot_rect.y +
                (scene.axis_high - point.value) /
                (scene.axis_high - scene.axis_low) * scene.plot_rect.height)
        for point in fractions:
            left = math.floor(point.global_index)
            fraction = point.global_index - left
            assert point.value == pytest.approx(source[left] + fraction * (source[left + 1] - source[left]))
        assert all(t.timestamp_ms == projection.ts_ms[t.global_index] for t in scene.time_ticks)
        assert scene.guides and scene.axis_low == 0.0 and scene.axis_high == 100.0
        assert state.viewport.snapshot() == before
        assert math.isnan(source[23]) and source[24] == 0.0
        assert widget.presentation is presentation and widget.projection is projection
        _receipt(request, {"geometry": _geometry(widget), "viewport": asdict(before),
            "source_indices": sorted(integral), "unique_source_count": len(integral),
            "render_point_count_including_shared_endpoints": len(points),
            "fractional_points": [asdict(p) for p in fractions],
            "ticks": [asdict(t) for t in scene.time_ticks]})
    finally:
        _destroy(app, widget)


def test_unbound_cleared_hidden_and_initial_geometry_control(app):
    widget = OscillatorStudyWidget("r05")
    try:
        widget.show()
        widget.resize(700, 250)
        widget.set_time_axis_visible(True)
        app.processEvents()
        assert widget.scene_plan is None
        state, projection, presentation = _fixture()
        widget.set_interaction_state(state)
        assert widget.scene_plan is None
        widget.set_study_state(projection, presentation)
        _geometry(widget)
        widget.set_study_state(projection, replace(presentation, visible=False))
        widget.resize(400, 150)
        app.processEvents()
        assert widget.scene_plan.line_strips == ()
        widget.clear_interaction_state()
        widget.set_time_axis_visible(False)
        widget.resize(300, 120)
        app.processEvents()
        assert widget.scene_plan is None
    finally:
        _destroy(app, widget)


def test_workspace_topology_resize_pan_zoom_crosshair(app, request):
    state, first, first_style = _fixture("first")
    _, second, second_style = _fixture("second")
    workspace = ChartPaneWorkspaceWidget()
    try:
        workspace.resize(850, 800)
        workspace.set_interaction_state(state)
        workspace.apply_study_state((first, second), (first_style, second_style))
        workspace.show()
        app.processEvents()
        upper = workspace.oscillator_widget("first")
        lower = workspace.oscillator_widget("second")
        assert not upper.time_axis_visible and lower.time_axis_visible
        receipts = []
        for size in ((1100, 950), (700, 650)):
            workspace.resize(*size)
            app.processEvents()
            receipts.append([_geometry(upper), _geometry(lower)])
        changed, crossed = [], []
        workspace.viewportChanged.connect(changed.append)
        workspace.crosshairChanged.connect(crossed.append)
        plot = lower._plot_rect()
        pos = plot.center()
        start = state.viewport.snapshot()
        app.sendEvent(lower, QMouseEvent(QEvent.Type.MouseButtonPress, pos,
            lower.mapToGlobal(pos.toPoint()), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        app.sendEvent(lower, QMouseEvent(QEvent.Type.MouseMove, pos + QPointF(80, 0),
            lower.mapToGlobal((pos + QPointF(80, 0)).toPoint()), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        app.sendEvent(lower, QMouseEvent(QEvent.Type.MouseButtonRelease, pos + QPointF(80, 0),
            lower.mapToGlobal((pos + QPointF(80, 0)).toPoint()), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        assert changed and state.viewport.snapshot().start_index != start.start_index
        app.sendEvent(lower, QWheelEvent(pos, lower.mapToGlobal(pos.toPoint()),
            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
        assert state.viewport.snapshot().visible_count > start.visible_count
        app.sendEvent(lower, QMouseEvent(QEvent.Type.MouseMove, pos,
            lower.mapToGlobal(pos.toPoint()), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        assert crossed and state.viewport.snapshot().crosshair_index is not None
        assert upper._interaction is state and lower._interaction is state
        assert upper.scene_plan.line_strips[0].points[0].global_index == lower.scene_plan.line_strips[0].points[0].global_index
        workspace.apply_study_state((first, second), (first_style, replace(second_style, visible=False)))
        app.processEvents()
        assert upper.time_axis_visible and not lower.time_axis_visible
        _geometry(upper)
        _receipt(request, {"resize_scenes": receipts, "viewport_signal_count": len(changed),
            "crosshair_signal_count": len(crossed), "final_viewport": asdict(state.viewport.snapshot()),
            "topology": list(workspace.study_pane_ids())})
    finally:
        _destroy(app, workspace)


def test_repaint_stays_in_rendering_authority(app, request):
    widget, _, _, _ = _bound(app)
    calls = set()
    prior = sys.getprofile()
    def observe(frame, event, _arg):
        if event == "call":
            path = frame.f_code.co_filename.replace("\\", "/")
            if "/leonardo/" in path:
                calls.add((path.split("/leonardo/", 1)[1], frame.f_code.co_name))
    try:
        sys.setprofile(observe)
        widget.resize(880, 330)
        widget.set_time_axis_visible(True)
        app.processEvents()
        image = widget.grab()
        assert not image.isNull()
    finally:
        sys.setprofile(prior)
        _destroy(app, widget)
    forbidden = [(path, name) for path, name in calls if
        path.startswith(("artifacts/", "ohlcv/", "storage/", "recipes/")) or
        "store" in path or path.endswith("study_execution.py") or
        (path.startswith("financial_tools/") and name.startswith(("calculate", "compute", "execute")))]
    _receipt(request, {"observed_product_calls": sorted(calls), "forbidden_calls": forbidden})
    assert forbidden == []
