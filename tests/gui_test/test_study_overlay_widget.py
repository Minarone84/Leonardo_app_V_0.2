from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.study_scene import PriceStudyBundle
from leonardo.research import (
    HorizontalViewport,
    ResidentOHLCVSlice,
    ResidentStudyProjection,
    StudyFillStyle,
    StudyLineStyle,
    StudyPresentation,
)


def _state() -> CandlestickInteractionState:
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    count = 30
    resident = ResidentOHLCVSlice(
        market, "a" * 64, 0, count, tuple(range(count)),
        tuple(100.0 for _ in range(count)),
        tuple(110.0 for _ in range(count)),
        tuple(90.0 for _ in range(count)),
        tuple(100.0 for _ in range(count)),
        tuple(10.0 for _ in range(count)),
        False, False, 0, count - 1,
    )
    return CandlestickInteractionState(
        HorizontalViewport(count, visible_count=count, left_padding=0, right_padding=0),
        resident,
    )


def _bundle(value: float = 500.0, *, revision: int = 0) -> PriceStudyBundle:
    projection = ResidentStudyProjection(
        "sma", MarketId("bybit", "linear", "BTCUSDT", "1m"), "a" * 64,
        "price", 0, 30, tuple(range(30)), {"sma_3": (value,) * 30}, {},
    )
    presentation = StudyPresentation(
        "sma", True, "price", {"sma_3": StudyLineStyle("sma_3", "#F59E0B")}, {}, revision,
    )
    return PriceStudyBundle((projection,), (presentation,))


def _hidden_boundary_fill_bundle() -> PriceStudyBundle:
    projection = ResidentStudyProjection(
        "bb",
        MarketId("bybit", "linear", "BTCUSDT", "1m"),
        "a" * 64,
        "price",
        0,
        30,
        tuple(range(30)),
        {"upper": (220.0,) * 30, "lower": (180.0,) * 30},
        {},
    )
    presentation = StudyPresentation(
        "bb",
        True,
        "price",
        {
            "upper": StudyLineStyle("upper", "#60A5FA", visible=False),
            "lower": StudyLineStyle("lower", "#60A5FA", visible=False),
        },
        {"band": StudyFillStyle("band", "upper", "lower", "#60A5FA")},
    )
    return PriceStudyBundle((projection,), (presentation,))


def test_overlay_values_autoscale_paint_and_clear_without_recalculation() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CandlestickChartWidget()
    state = _state()
    try:
        widget.resize(800, 420)
        widget.set_interaction_state(state)
        widget.set_study_bundle(_bundle())
        widget.show()
        app.processEvents()
        assert widget.render_contract is not None
        assert widget.render_contract.price_scale.price_range.high > 500.0
        assert not widget.grab().isNull()
        assert widget.study_scene is not None
        assert widget.study_scene.line_strips

        assert widget.set_autoscale_enabled(False) is True
        manual = widget.render_contract.price_scale.price_range
        widget.set_study_bundle(_bundle(900.0, revision=1))
        assert widget.render_contract.price_scale.price_range == manual

        widget.clear_studies()
        assert not widget.study_bundle.projections
        assert widget.study_scene is None
    finally:
        widget.close()


def test_visible_fill_hidden_boundary_lines_still_autoscale() -> None:
    app = QApplication.instance() or QApplication([])
    widget = CandlestickChartWidget()
    try:
        widget.resize(800, 420)
        widget.set_interaction_state(_state())
        widget.set_study_bundle(_hidden_boundary_fill_bundle())
        widget.show()
        app.processEvents()

        assert widget.render_contract is not None
        assert widget.render_contract.price_scale.price_range.high > 220.0
        assert widget.study_scene is not None
        assert widget.study_scene.fills
        assert widget.study_scene.line_strips == ()
    finally:
        widget.close()
