from __future__ import annotations

from pathlib import Path

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.research import (
    HistoricalDataset,
    HorizontalViewport,
    ResidentOHLCVSlice,
    build_resident_volume_projection,
)
from tools.research_gui_dev_fixtures import build_primary_chart_fixture


def _state_and_projection():
    count = 100
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(count))
    opens = tuple(100.0 + index for index in range(count))
    closes = tuple(value + 0.5 for value in opens)
    dataset = HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256="a" * 64,
        row_count=count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=opens,
        high=tuple(value + 2.0 for value in closes),
        low=tuple(value - 2.0 for value in opens),
        close=closes,
        volume=tuple(float(index + 10) for index in range(count)),
    )
    resident = ResidentOHLCVSlice(
        market_id=market,
        dataset_fingerprint=dataset.file_sha256,
        base_index=0,
        end_index_exclusive=count,
        ts_ms=dataset.ts_ms,
        open=dataset.open,
        high=dataset.high,
        low=dataset.low,
        close=dataset.close,
        volume=dataset.volume,
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=dataset.first_timestamp_ms,
        last_timestamp_ms=dataset.last_timestamp_ms,
    )
    state = CandlestickInteractionState(HorizontalViewport(count), resident)
    return state, build_resident_volume_projection(dataset, resident)


def test_workspace_owns_optional_volume_pane_and_shared_state() -> None:
    app = QApplication.instance() or QApplication([])
    state, projection = _state_and_projection()
    workspace = ChartPaneWorkspaceWidget()
    workspace.set_interaction_state(state)
    workspace.set_volume_projection(projection)

    assert workspace.volume_visible is False
    assert workspace.price_chart.interaction_state is state
    assert workspace.volume_chart.render_contract is not None
    assert workspace.set_volume_visible(True) is True
    assert workspace.volume_visible is True
    assert workspace.volume_chart.isHidden() is False
    assert workspace.set_volume_visible(True) is False
    initial_sizes = workspace.pane_sizes()
    assert initial_sizes[0] > initial_sizes[1] > 0
    assert workspace.set_volume_visible(False) is True
    assert workspace.set_volume_visible(True) is True
    assert workspace.pane_sizes()[1] > 0
    workspace.close()
    app.processEvents()


def _visible_sizes(workspace: ChartPaneWorkspaceWidget) -> tuple[int, ...]:
    return tuple(
        size
        for index, size in enumerate(workspace._splitter.sizes())
        if not workspace._splitter.widget(index).isHidden()
    )


def _normalized_boundaries(workspace: ChartPaneWorkspaceWidget) -> tuple[int, ...]:
    sizes = _visible_sizes(workspace)
    total = sum(sizes)
    cumulative = 0
    boundaries: list[int] = []
    for size in sizes[:-1]:
        cumulative += size
        boundaries.append(round(cumulative * 1000 / total))
    return tuple(boundaries)


def _on_anchor(boundary: int) -> bool:
    return abs(boundary - round(boundary / 10) * 10) <= 1


def _show_workspace(
    app: QApplication, height: int
) -> ChartPaneWorkspaceWidget:
    state, projection = _state_and_projection()
    workspace = ChartPaneWorkspaceWidget()
    workspace.set_interaction_state(state)
    workspace.set_volume_projection(projection)
    workspace.set_volume_visible(True)
    workspace.resize(800, height)
    workspace.show()
    app.processEvents()
    return workspace


def test_user_splitter_drag_snaps_reproducibly_without_recursive_emission() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = _show_workspace(app, 700)
    try:
        splitter = workspace._splitter
        assert splitter.handle(1).isVisible()
        assert not splitter.childrenCollapsible()
        emitted = QSignalSpy(splitter.splitterMoved)
        total = sum(_visible_sizes(workspace))

        splitter.moveSplitter(round(total * 0.633), 1)
        app.processEvents()
        first_sizes = _visible_sizes(workspace)
        first_boundaries = _normalized_boundaries(workspace)
        assert all(_on_anchor(boundary) for boundary in first_boundaries)
        assert all(
            size >= splitter.widget(index).minimumHeight()
            for index, size in enumerate(splitter.sizes())
            if not splitter.widget(index).isHidden()
        )

        splitter.moveSplitter(round(total * 0.633), 1)
        app.processEvents()
        assert _visible_sizes(workspace) == first_sizes
        assert _normalized_boundaries(workspace) == first_boundaries
        assert emitted.count() == 2
    finally:
        workspace.close()
        app.processEvents()


def test_normalized_splitter_anchors_are_height_independent_and_chart_local() -> None:
    app = QApplication.instance() or QApplication([])
    first = _show_workspace(app, 650)
    second = _show_workspace(app, 950)
    try:
        second_before = _normalized_boundaries(second)
        for workspace in (first, second):
            workspace._splitter.moveSplitter(
                round(workspace._splitter.height() * 0.65), 1
            )
            app.processEvents()
        assert _normalized_boundaries(first)[0] == pytest.approx(650, abs=1)
        assert _normalized_boundaries(second)[0] == pytest.approx(650, abs=1)

        first._splitter.moveSplitter(round(first._splitter.height() * 0.72), 1)
        app.processEvents()
        assert _normalized_boundaries(first)[0] == pytest.approx(720, abs=1)
        assert _normalized_boundaries(second)[0] == pytest.approx(650, abs=1)
        assert second_before != _normalized_boundaries(first)
    finally:
        first.close()
        second.close()
        app.processEvents()


def test_visible_topology_changes_remain_anchored_and_exclude_hidden_panes() -> None:
    app = QApplication.instance() or QApplication([])
    fixture = build_primary_chart_fixture()
    workspace = ChartPaneWorkspaceWidget()
    workspace.set_interaction_state(fixture.interaction_state)
    workspace.set_volume_visible(True)
    workspace.resize(900, 900)
    workspace.show()
    app.processEvents()
    try:
        workspace.apply_study_state(
            fixture.study_projections[2:], fixture.study_presentations[2:]
        )
        app.processEvents()
        assert all(
            _on_anchor(boundary)
            for boundary in _normalized_boundaries(workspace)
        )

        workspace.set_volume_visible(False)
        app.processEvents()
        assert workspace._splitter.sizes()[1] == 0
        assert all(
            _on_anchor(boundary)
            for boundary in _normalized_boundaries(workspace)
        )

        workspace.apply_study_state(
            fixture.study_projections[2:3], fixture.study_presentations[2:3]
        )
        app.processEvents()
        assert workspace.oscillator_widget("dev-volume") is None
        assert all(
            _on_anchor(boundary)
            for boundary in _normalized_boundaries(workspace)
        )
    finally:
        workspace.close()
        app.processEvents()
