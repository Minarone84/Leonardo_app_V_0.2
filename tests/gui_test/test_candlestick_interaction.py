from __future__ import annotations

from leonardo.data import MarketId
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.research import HorizontalViewport, ResidentOHLCVSlice


def _resident(count: int = 1_000) -> ResidentOHLCVSlice:
    ts = tuple(1_700_000_000_000 + i * 60_000 for i in range(count))
    opens = tuple(100.0 + i * 0.1 for i in range(count))
    closes = tuple(value + 0.05 for value in opens)
    return ResidentOHLCVSlice(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint="a" * 64,
        base_index=0,
        end_index_exclusive=count,
        ts_ms=ts,
        open=opens,
        high=tuple(value + 0.2 for value in closes),
        low=tuple(value - 0.2 for value in opens),
        close=closes,
        volume=tuple(1.0 for _ in range(count)),
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=ts[0],
        last_timestamp_ms=ts[-1],
    )


def test_horizontal_pixel_pan_preserves_old_drag_direction() -> None:
    viewport = HorizontalViewport(1_000, visible_count=100)
    viewport.set_window(400, 500)
    state = CandlestickInteractionState(viewport, _resident())
    assert state.pan_horizontal_pixels(100.0, 1_000.0) is True
    assert viewport.start_index == 390
    assert state.pan_horizontal_pixels(-100.0, 1_000.0) is True
    assert viewport.start_index == 400


def test_horizontal_zoom_is_cursor_anchored() -> None:
    viewport = HorizontalViewport(1_000, visible_count=100)
    viewport.set_window(400, 500)
    state = CandlestickInteractionState(viewport, _resident())
    anchor_before = viewport.global_index_at_relative(0.25)
    assert state.zoom_horizontal(120, 0.25) is True
    anchor_after = viewport.global_index_at_relative(0.25)
    assert abs(anchor_after - anchor_before) <= 1


def test_crosshair_changes_do_not_change_static_contract_identity() -> None:
    viewport = HorizontalViewport(1_000, visible_count=100)
    viewport.set_window(400, 500)
    state = CandlestickInteractionState(viewport, _resident())
    first = state.render_contract()
    assert state.move_crosshair(0.5) is True
    second = state.render_contract()
    assert second.viewport.crosshair_index is not None
    assert first.cache_identity() == second.cache_identity()


def test_manual_price_pan_and_zoom_are_explicit() -> None:
    viewport = HorizontalViewport(1_000, visible_count=100)
    state = CandlestickInteractionState(viewport, _resident())
    assert state.set_autoscale_enabled(False) is True
    before = state.price_scale_snapshot().price_range
    assert state.pan_price_pixels(50.0, 500.0) is True
    panned = state.price_scale_snapshot().price_range
    assert panned.low > before.low
    assert state.zoom_price_pixels(180.0) is True
    zoomed = state.price_scale_snapshot().price_range
    assert zoomed.span > panned.span


def test_render_contract_contains_explicit_price_scale() -> None:
    state = CandlestickInteractionState(
        HorizontalViewport(1_000, visible_count=100), _resident()
    )
    contract = state.render_contract()
    assert contract.price_scale is not None
    assert contract.price_scale.autoscale_enabled is True
