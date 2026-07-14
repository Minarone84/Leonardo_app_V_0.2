from __future__ import annotations

from pathlib import Path

import pytest

from leonardo.data import MarketId
from leonardo.gui.chart.volume_scene import VolumeRenderContract, build_volume_scene
from leonardo.research import (
    HistoricalDataset,
    HorizontalViewport,
    ResidentOHLCVSlice,
    build_resident_volume_projection,
)


def _inputs(count: int = 100):
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(count))
    opens = tuple(100.0 + index * 0.1 for index in range(count))
    closes = tuple(value + (0.05 if index % 2 == 0 else -0.05) for index, value in enumerate(opens))
    dataset = HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256="a" * 64,
        row_count=count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=opens,
        high=tuple(max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)),
        low=tuple(min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)),
        close=closes,
        volume=tuple(float(100 + index) for index in range(count)),
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
    projection = build_resident_volume_projection(dataset, resident, period=20)
    viewport = HorizontalViewport(count, visible_count=40)
    return resident, projection, viewport


def test_volume_scene_draws_visible_bars_mean_and_axis() -> None:
    resident, projection, viewport = _inputs()
    viewport.set_window(40, 80)
    scene = build_volume_scene(
        VolumeRenderContract(viewport.snapshot(), resident, projection),
        width=800,
        height=180,
    )

    assert len(scene.bars) == 40
    assert scene.bars[0].global_index == 40
    assert scene.bars[-1].global_index == 79
    assert scene.moving_mean[0].global_index == 40
    assert len(scene.axis_ticks) == 5
    assert scene.last_volume_tag is not None
    assert scene.center_message is None


def test_volume_scene_respects_chart_padding() -> None:
    resident, projection, viewport = _inputs()
    viewport.set_window(-20, 20)
    scene = build_volume_scene(
        VolumeRenderContract(viewport.snapshot(), resident, projection),
        width=600,
        height=160,
    )

    assert len(scene.bars) == 20
    assert scene.bars[0].global_index == 0


def test_crosshair_does_not_change_static_volume_cache_identity() -> None:
    resident, projection, viewport = _inputs()
    first = VolumeRenderContract(viewport.snapshot(), resident, projection)
    viewport.set_crosshair(50)
    second = VolumeRenderContract(viewport.snapshot(), resident, projection)

    assert first.cache_identity() == second.cache_identity()


def test_volume_contract_rejects_partial_payload() -> None:
    resident, _projection, viewport = _inputs()

    with pytest.raises(ValueError, match="both"):
        VolumeRenderContract(viewport.snapshot(), resident, None)
