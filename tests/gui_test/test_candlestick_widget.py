from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import CandlestickRenderContract
from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.research import HorizontalViewport, ResidentOHLCVSlice


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _contract() -> CandlestickRenderContract:
    count = 100
    timestamps = tuple(1_700_000_000_000 + index * 60_000 for index in range(count))
    opens = tuple(100.0 + index * 0.1 for index in range(count))
    closes = tuple(value + 0.05 for value in opens)
    resident = ResidentOHLCVSlice(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint="a" * 64,
        base_index=0,
        end_index_exclusive=count,
        ts_ms=timestamps,
        open=opens,
        high=tuple(value + 0.25 for value in closes),
        low=tuple(value - 0.25 for value in opens),
        close=closes,
        volume=tuple(10.0 for _ in range(count)),
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    return CandlestickRenderContract(
        viewport=HorizontalViewport(count, visible_count=100).snapshot(),
        resident=resident,
    )


def test_widget_constructs_renders_and_reuses_static_scene(qapp: QApplication) -> None:
    widget = CandlestickChartWidget()
    try:
        assert widget.objectName() == "research.chart.candlestick"
        widget.resize(900, 500)
        widget.set_render_contract(_contract())
        widget.show()
        QCoreApplication.processEvents()
        pixmap = widget.grab()
        assert not pixmap.isNull()
        assert widget.static_rebuild_count == 1

        widget.update()
        QCoreApplication.processEvents()
        assert widget.static_rebuild_count == 1
    finally:
        widget.close()


def test_crosshair_update_does_not_rebuild_static_pixmap(qapp: QApplication) -> None:
    from leonardo.gui.chart.interaction import CandlestickInteractionState

    base = _contract()
    viewport = HorizontalViewport(base.viewport.dataset_count, visible_count=100)
    state = CandlestickInteractionState(viewport, base.resident)
    widget = CandlestickChartWidget()
    try:
        widget.resize(900, 500)
        widget.set_interaction_state(state)
        widget.show()
        QCoreApplication.processEvents()
        widget.grab()
        initial = widget.static_rebuild_count

        state.move_crosshair(0.5)
        widget.set_render_contract(state.render_contract())
        widget.update()
        QCoreApplication.processEvents()
        widget.grab()
        assert widget.static_rebuild_count == initial
    finally:
        widget.close()


def test_public_autoscale_control_updates_interaction_contract(qapp: QApplication) -> None:
    from leonardo.gui.chart.interaction import CandlestickInteractionState

    base = _contract()
    state = CandlestickInteractionState(
        HorizontalViewport(base.viewport.dataset_count, visible_count=100),
        base.resident,
    )
    widget = CandlestickChartWidget()
    try:
        widget.set_interaction_state(state)
        assert widget.autoscale_enabled is True
        assert widget.set_autoscale_enabled(False) is True
        assert widget.autoscale_enabled is False
        assert widget.render_contract is not None
        assert widget.render_contract.price_scale is not None
        assert widget.render_contract.price_scale.autoscale_enabled is False
    finally:
        widget.close()
