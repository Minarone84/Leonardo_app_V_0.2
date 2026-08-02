from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QRectF
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import (
    CandlestickRenderContract,
    _format_price,
    build_candlestick_scene,
)
from leonardo.gui.chart.candlestick_widget import (
    CandlestickChartWidget,
    _time_tag_plan,
)
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


def test_dynamic_crosshair_time_and_price_tags_are_exact_and_cache_independent(
    qapp: QApplication,
) -> None:
    from leonardo.gui.chart.interaction import CandlestickInteractionState

    base = _contract()
    state = CandlestickInteractionState(
        HorizontalViewport(base.viewport.dataset_count, visible_count=100),
        base.resident,
    )
    widget = CandlestickChartWidget()
    try:
        widget.resize(900, 500)
        widget.set_interaction_state(state)
        assert widget._dynamic_crosshair_tags() == ()
        widget.show()
        QCoreApplication.processEvents()
        widget.grab()
        initial_rebuilds = widget.static_rebuild_count

        state.viewport.set_crosshair(0)
        widget.refresh_from_shared_state(refresh_price_scale=False)
        widget._crosshair_y = widget._plot_rect().center().y()
        tags = widget._dynamic_crosshair_tags()
        assert len(tags) == 2
        value_tag, time_tag = tags
        assert time_tag.text == "14 Nov 2023 22:13"
        assert (time_tag.background, time_tag.background_opacity) == (
            "#E1E1E1",
            1.0,
        )
        assert time_tag.text_color == "#000000"
        assert time_tag.corner_radius == 4.0

        contract = widget.render_contract
        assert contract is not None and contract.price_scale is not None
        price_range = contract.price_scale.price_range
        assert value_tag.text == _format_price(price_range.midpoint, price_range.span)
        assert (value_tag.background, value_tag.background_opacity) == (
            "#FFA500",
            0.5,
        )
        assert value_tag.text_color == "#000000"
        axis = widget._price_axis_rect()
        assert axis.left() <= value_tag.left
        assert value_tag.left + value_tag.width <= axis.right()
        assert axis.top() <= value_tag.top
        assert value_tag.top + value_tag.height <= axis.bottom()

        first_dynamic_text = time_tag.text
        state.viewport.set_crosshair(99)
        widget.refresh_from_shared_state(refresh_price_scale=False)
        later_tags = widget._dynamic_crosshair_tags()
        assert later_tags[-1].text != first_dynamic_text
        widget.update()
        QCoreApplication.processEvents()
        widget.grab()
        assert widget.static_rebuild_count == initial_rebuilds
    finally:
        widget.close()


def test_dynamic_price_tag_preserves_overlapping_static_last_price_tag(
    qapp: QApplication,
) -> None:
    from leonardo.gui.chart.interaction import CandlestickInteractionState

    base = _contract()
    state = CandlestickInteractionState(
        HorizontalViewport(base.viewport.dataset_count, visible_count=100),
        base.resident,
    )
    widget = CandlestickChartWidget()
    try:
        widget.resize(900, 500)
        widget.set_interaction_state(state)
        widget.show()
        QCoreApplication.processEvents()
        widget.grab()
        initial_rebuilds = widget.static_rebuild_count
        state.viewport.set_crosshair(99)
        widget.refresh_from_shared_state(refresh_price_scale=False)

        contract = widget.render_contract
        assert contract is not None and contract.price_scale is not None
        scene = build_candlestick_scene(
            contract,
            width=widget.width(),
            height=widget.height(),
        )
        assert scene.last_price_tag is not None
        static_rect = QRectF(
            scene.plot_rect.right + 2,
            scene.last_price_tag.y - 9,
            max(1.0, scene.price_axis_rect.width - 4),
            18,
        )

        widget._crosshair_y = scene.last_price_tag.y
        overlapping_tags = widget._dynamic_crosshair_tags()
        assert widget._plot_rect().contains(
            widget._plot_rect().center().x(), widget._crosshair_y
        )
        assert not any(tag.background == "#FFA500" for tag in overlapping_tags)
        assert any(tag.background == "#E1E1E1" for tag in overlapping_tags)
        assert widget.static_rebuild_count == initial_rebuilds

        widget._crosshair_y = static_rect.bottom() + 30.0
        separated_tags = widget._dynamic_crosshair_tags()
        value_tag = next(tag for tag in separated_tags if tag.background == "#FFA500")
        price_range = contract.price_scale.price_range
        fraction = (
            widget._crosshair_y - widget._plot_rect().top()
        ) / widget._plot_rect().height()
        expected_value = price_range.high - fraction * price_range.span
        assert value_tag.text == _format_price(expected_value, price_range.span)
        assert widget.static_rebuild_count == initial_rebuilds

        widget._crosshair_y = static_rect.bottom() + value_tag.height / 2.0
        edge_tags = widget._dynamic_crosshair_tags()
        edge_tag = next(tag for tag in edge_tags if tag.background == "#FFA500")
        assert edge_tag.rect.top() == pytest.approx(static_rect.bottom())
        assert widget.static_rebuild_count == initial_rebuilds
    finally:
        widget.close()


def test_time_tag_geometry_clamps_to_both_plot_edges(qapp: QApplication) -> None:
    del qapp
    bounds = QRectF(10.0, 100.0, 200.0, 24.0)
    left = _time_tag_plan(1_700_000_000_000, -100.0, bounds)
    right = _time_tag_plan(1_700_000_000_000, 500.0, bounds)
    assert left.left == bounds.left()
    assert right.left + right.width == bounds.right()


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
