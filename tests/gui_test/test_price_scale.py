from __future__ import annotations

import pytest

from leonardo.data import MarketId
from leonardo.gui.chart.price_scale import PriceRange, PriceScaleState, visible_price_range
from leonardo.research import HorizontalViewport, ResidentOHLCVSlice


def _resident(count: int = 100) -> ResidentOHLCVSlice:
    ts = tuple(1_700_000_000_000 + i * 60_000 for i in range(count))
    opens = tuple(100.0 + i for i in range(count))
    closes = tuple(value + 0.5 for value in opens)
    return ResidentOHLCVSlice(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint="a" * 64,
        base_index=0,
        end_index_exclusive=count,
        ts_ms=ts,
        open=opens,
        high=tuple(value + 2.0 for value in closes),
        low=tuple(value - 2.0 for value in opens),
        close=closes,
        volume=tuple(1.0 for _ in range(count)),
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=ts[0],
        last_timestamp_ms=ts[-1],
    )


def test_visible_price_range_uses_only_visible_candles_and_extra_values() -> None:
    resident = _resident(100)
    viewport = HorizontalViewport(100, visible_count=20)
    viewport.set_window(40, 60)
    price_range = visible_price_range(
        viewport.snapshot(), resident, extra_visible_prices=(50.0, 500.0)
    )
    assert price_range.low < 50.0
    assert price_range.high > 500.0


def test_autoscale_resolves_visible_range_and_manual_mode_freezes_it() -> None:
    resident = _resident(100)
    viewport = HorizontalViewport(100, visible_count=20)
    viewport.set_window(0, 20)
    state = PriceScaleState()
    automatic = state.resolve(viewport.snapshot(), resident)
    assert automatic.autoscale_enabled is True

    assert state.set_autoscale_enabled(False) is True
    frozen = state.resolve(viewport.snapshot(), resident)
    viewport.set_window(80, 100)
    moved = state.resolve(viewport.snapshot(), resident)
    assert moved.price_range == frozen.price_range


def test_manual_pan_and_zoom_match_old_pixel_behavior() -> None:
    state = PriceScaleState(autoscale_enabled=False)
    state.set_manual_range(100.0, 200.0)
    assert state.pan_by_pixels(50.0, 100.0) is True
    assert state.manual_range == PriceRange(150.0, 250.0)

    assert state.zoom_by_pixels(180.0) is True
    assert state.manual_range == PriceRange(100.0, 300.0)


def test_autoscale_rejects_manual_pan_and_zoom() -> None:
    state = PriceScaleState()
    assert state.pan_by_pixels(10.0, 100.0) is False
    assert state.zoom_by_pixels(10.0) is False


def test_price_range_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        PriceRange(1.0, 1.0)
    with pytest.raises(ValueError):
        PriceRange(float("nan"), 2.0)
