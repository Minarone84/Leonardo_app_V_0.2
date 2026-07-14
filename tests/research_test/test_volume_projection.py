from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.data import MarketId
from leonardo.research import (
    HistoricalDataset,
    ResidentOHLCVSlice,
    build_resident_volume_projection,
)


def _dataset(count: int = 30, *, fingerprint: str = "a" * 64) -> HistoricalDataset:
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(count))
    opens = tuple(100.0 + index for index in range(count))
    closes = tuple(value + (1.0 if index % 2 == 0 else -1.0) for index, value in enumerate(opens))
    return HistoricalDataset(
        market_id=market,
        csv_path=Path("candles.csv"),
        file_sha256=fingerprint,
        row_count=count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=opens,
        high=tuple(max(o, c) + 1.0 for o, c in zip(opens, closes, strict=True)),
        low=tuple(min(o, c) - 1.0 for o, c in zip(opens, closes, strict=True)),
        close=closes,
        volume=tuple(float(index + 1) for index in range(count)),
    )


def _resident(dataset: HistoricalDataset, start: int, end: int) -> ResidentOHLCVSlice:
    return ResidentOHLCVSlice(
        market_id=dataset.market_id,
        dataset_fingerprint=dataset.file_sha256,
        base_index=start,
        end_index_exclusive=end,
        ts_ms=dataset.ts_ms[start:end],
        open=dataset.open[start:end],
        high=dataset.high[start:end],
        low=dataset.low[start:end],
        close=dataset.close[start:end],
        volume=dataset.volume[start:end],
        has_more_left=start > 0,
        has_more_right=end < dataset.row_count,
        first_timestamp_ms=dataset.ts_ms[start],
        last_timestamp_ms=dataset.ts_ms[end - 1],
    )


def test_volume_projection_uses_full_history_for_resident_mean() -> None:
    dataset = _dataset()
    resident = _resident(dataset, 10, 20)

    projection = build_resident_volume_projection(dataset, resident, period=5)

    assert projection.volume is resident.volume
    assert projection.moving_mean[0] == pytest.approx(sum(dataset.volume[6:11]) / 5)
    assert projection.moving_mean[-1] == pytest.approx(sum(dataset.volume[15:20]) / 5)
    assert projection.bullish == tuple(
        close >= open_price
        for open_price, close in zip(resident.open, resident.close, strict=True)
    )


def test_volume_projection_preserves_warmup_none_values() -> None:
    dataset = _dataset(10)
    resident = _resident(dataset, 0, 6)

    projection = build_resident_volume_projection(dataset, resident, period=4)

    assert projection.moving_mean[:3] == (None, None, None)
    assert projection.moving_mean[3] == pytest.approx(2.5)


def test_volume_projection_is_deeply_immutable() -> None:
    projection = build_resident_volume_projection(_dataset(), _resident(_dataset(), 0, 10))

    with pytest.raises(FrozenInstanceError):
        projection.period = 5  # type: ignore[misc]
    with pytest.raises(TypeError):
        projection.volume[0] = 2.0  # type: ignore[index]


def test_volume_projection_rejects_mismatched_resident_evidence() -> None:
    dataset = _dataset()
    other = _dataset(fingerprint="b" * 64)
    resident = _resident(other, 0, 10)

    with pytest.raises(ValueError, match="fingerprint"):
        build_resident_volume_projection(dataset, resident)


def test_volume_projection_rejects_invalid_period() -> None:
    dataset = _dataset()
    resident = _resident(dataset, 0, 10)

    with pytest.raises(ValueError, match="period"):
        build_resident_volume_projection(dataset, resident, period=0)
