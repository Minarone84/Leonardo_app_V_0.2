from __future__ import annotations

from pathlib import Path

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

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
