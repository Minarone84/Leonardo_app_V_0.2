from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import (
    CandlestickRenderContract,
    build_candlestick_scene,
)
from leonardo.research import HorizontalViewport, ResidentOHLCVSlice


def _resident(
    count: int,
    *,
    base_index: int = 0,
    dataset_fingerprint: str = "a" * 64,
    interval_ms: int = 60_000,
) -> ResidentOHLCVSlice:
    timestamps = tuple(1_700_000_000_000 + index * interval_ms for index in range(count))
    opens = tuple(100.0 + index * 0.1 for index in range(count))
    closes = tuple(value + (0.05 if index % 2 == 0 else -0.05) for index, value in enumerate(opens))
    highs = tuple(max(open_value, close_value) + 0.2 for open_value, close_value in zip(opens, closes))
    lows = tuple(min(open_value, close_value) - 0.2 for open_value, close_value in zip(opens, closes))
    return ResidentOHLCVSlice(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint=dataset_fingerprint,
        base_index=base_index,
        end_index_exclusive=base_index + count,
        ts_ms=timestamps,
        open=opens,
        high=highs,
        low=lows,
        close=closes,
        volume=tuple(10.0 + index for index in range(count)),
        has_more_left=base_index > 0,
        has_more_right=False,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )


def _contract(
    dataset_count: int,
    resident: ResidentOHLCVSlice | None,
    *,
    visible_count: int = 100,
    start: int | None = None,
) -> CandlestickRenderContract:
    viewport = HorizontalViewport(dataset_count, visible_count=visible_count)
    if start is not None:
        viewport.set_window(start, start + visible_count)
    return CandlestickRenderContract(viewport=viewport.snapshot(), resident=resident)


def test_contract_and_scene_are_immutable() -> None:
    resident = _resident(100)
    contract = _contract(100, resident)
    scene = build_candlestick_scene(contract, width=900, height=500)

    with pytest.raises(FrozenInstanceError):
        contract.resident = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        scene.price_low = 0.0  # type: ignore[misc]


def test_scene_plans_normal_candles_price_axis_grid_and_time_axis() -> None:
    resident = _resident(100)
    scene = build_candlestick_scene(
        _contract(100, resident),
        width=900,
        height=500,
    )

    assert len(scene.candles) == 100
    assert all(not candle.compressed for candle in scene.candles)
    assert len(scene.price_ticks) == 6
    assert len(scene.horizontal_grid) == 6
    assert 2 <= len(scene.time_ticks) <= 12
    assert len(scene.vertical_grid) == len(scene.time_ticks)
    assert scene.price_low < min(resident.low)
    assert scene.price_high > max(resident.high)
    assert scene.center_message is None


def test_scene_uses_only_visible_candles_for_default_price_range() -> None:
    resident = _resident(200)
    low_values = list(resident.low)
    high_values = list(resident.high)
    low_values[0] = -1_000_000.0
    high_values[0] = 1_000_000.0
    resident = ResidentOHLCVSlice(
        market_id=resident.market_id,
        dataset_fingerprint=resident.dataset_fingerprint,
        base_index=resident.base_index,
        end_index_exclusive=resident.end_index_exclusive,
        ts_ms=resident.ts_ms,
        open=resident.open,
        high=tuple(high_values),
        low=tuple(low_values),
        close=resident.close,
        volume=resident.volume,
        has_more_left=resident.has_more_left,
        has_more_right=resident.has_more_right,
        first_timestamp_ms=resident.first_timestamp_ms,
        last_timestamp_ms=resident.last_timestamp_ms,
    )
    scene = build_candlestick_scene(
        _contract(200, resident, visible_count=50, start=150),
        width=800,
        height=400,
    )

    assert scene.price_low > 0
    assert scene.price_high < 1_000


def test_left_padding_has_explicit_no_older_data_region() -> None:
    resident = _resident(100)
    scene = build_candlestick_scene(
        _contract(100, resident, visible_count=100, start=-50),
        width=900,
        height=500,
    )

    assert scene.left_gap_rect is not None
    assert scene.left_gap_message == "No older data"
    assert scene.left_gap_rect.width == pytest.approx(scene.plot_rect.width / 2)
    assert len(scene.candles) == 50


def test_empty_contract_uses_honest_empty_state() -> None:
    scene = build_candlestick_scene(
        _contract(0, None, visible_count=100),
        width=640,
        height=360,
    )

    assert scene.candles == ()
    assert scene.center_message == "No accepted OHLCV data"
    assert scene.price_low == 0.0
    assert scene.price_high == 1.0


def test_high_density_candles_are_aggregated_by_horizontal_pixel() -> None:
    resident = _resident(2_000)
    scene = build_candlestick_scene(
        _contract(2_000, resident, visible_count=2_000),
        width=240,
        height=400,
    )

    assert len(scene.candles) <= int(scene.plot_rect.width) + 1
    assert len(scene.candles) < resident.row_count
    assert all(candle.compressed for candle in scene.candles)
    assert scene.candles[0].first_global_index == 0
    assert scene.candles[-1].last_global_index == 1_999


def test_compressed_bucket_preserves_first_open_extremes_and_last_close() -> None:
    resident = _resident(2_000)
    scene = build_candlestick_scene(
        _contract(2_000, resident, visible_count=2_000),
        width=240,
        height=400,
    )
    first = scene.candles[0]
    start = first.first_global_index
    end = first.last_global_index + 1

    assert first.open_price == resident.open[start]
    assert first.close_price == resident.close[end - 1]
    assert first.high_price == max(resident.high[start:end])
    assert first.low_price == min(resident.low[start:end])


def test_scene_rejects_resident_beyond_dataset_truth() -> None:
    resident = _resident(100)
    viewport = HorizontalViewport(50).snapshot()

    with pytest.raises(ValueError, match="exceeds"):
        CandlestickRenderContract(viewport=viewport, resident=resident)


def test_render_cache_identity_changes_for_viewport_or_dataset_fingerprint() -> None:
    resident = _resident(100)
    first = _contract(100, resident)
    viewport = HorizontalViewport(100, visible_count=100)
    viewport.pan_left(10)
    moved = CandlestickRenderContract(viewport.snapshot(), resident)
    changed_resident = _resident(100, dataset_fingerprint="b" * 64)
    changed = _contract(100, changed_resident)

    assert first.cache_identity() != moved.cache_identity()
    assert first.cache_identity() != changed.cache_identity()


def test_explicit_manual_price_scale_controls_scene_and_last_price_tag() -> None:
    from leonardo.gui.chart.price_scale import PriceRange, PriceScaleSnapshot

    resident = _resident(100)
    viewport = HorizontalViewport(100, visible_count=100).snapshot()
    contract = CandlestickRenderContract(
        viewport=viewport,
        resident=resident,
        price_scale=PriceScaleSnapshot(False, PriceRange(50.0, 250.0)),
    )
    scene = build_candlestick_scene(contract, width=900, height=500)

    assert scene.price_low == 50.0
    assert scene.price_high == 250.0
    assert scene.last_price_tag is not None
    assert scene.last_price_tag.price == resident.close[-1]
    assert scene.last_price_tag.label


def test_price_scale_changes_static_cache_identity_but_crosshair_does_not() -> None:
    from leonardo.gui.chart.price_scale import PriceRange, PriceScaleSnapshot

    resident = _resident(100)
    viewport = HorizontalViewport(100, visible_count=100)
    first = CandlestickRenderContract(
        viewport.snapshot(),
        resident,
        PriceScaleSnapshot(True, PriceRange(90.0, 120.0)),
    )
    viewport.set_crosshair(50)
    crosshair = CandlestickRenderContract(
        viewport.snapshot(),
        resident,
        PriceScaleSnapshot(True, PriceRange(90.0, 120.0)),
    )
    scale = CandlestickRenderContract(
        viewport.snapshot(),
        resident,
        PriceScaleSnapshot(False, PriceRange(80.0, 130.0)),
    )

    assert first.cache_identity() == crosshair.cache_identity()
    assert first.cache_identity() != scale.cache_identity()
