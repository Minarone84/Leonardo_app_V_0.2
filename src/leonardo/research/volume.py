"""Resident volume projection for historical Research charts.

The accepted full :class:`HistoricalDataset` remains the canonical OHLCV read
model.  This module derives one immutable resident volume projection, including
Leonardo's validated 20-period rolling mean behavior, without performing I/O,
Qt work, persistence, or task lifecycle management.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from leonardo.data import MarketId
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.resident import ResidentOHLCVSlice

DEFAULT_VOLUME_MEAN_PERIOD = 20


@dataclass(frozen=True, slots=True)
class ResidentVolumeProjection:
    """Immutable resident-local volume values derived from a full dataset."""

    market_id: MarketId
    dataset_fingerprint: str
    base_index: int
    end_index_exclusive: int
    period: int
    volume: tuple[float, ...]
    moving_mean: tuple[float | None, ...]
    bullish: tuple[bool, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if not isinstance(self.dataset_fingerprint, str) or not self.dataset_fingerprint:
            raise ValueError("dataset_fingerprint must be a non-empty string")
        if type(self.base_index) is not int or self.base_index < 0:
            raise ValueError("base_index must be a non-negative integer")
        if type(self.end_index_exclusive) is not int:
            raise TypeError("end_index_exclusive must be an integer")
        if self.end_index_exclusive <= self.base_index:
            raise ValueError("end_index_exclusive must be greater than base_index")
        if type(self.period) is not int or self.period <= 0:
            raise ValueError("period must be a positive integer")
        expected = self.end_index_exclusive - self.base_index
        if len(self.volume) != expected:
            raise ValueError("volume length must match the resident range")
        if len(self.moving_mean) != expected:
            raise ValueError("moving_mean length must match the resident range")
        if len(self.bullish) != expected:
            raise ValueError("bullish length must match the resident range")
        if any(value < 0 for value in self.volume):
            raise ValueError("volume values must be non-negative")
        if any(value is not None and value < 0 for value in self.moving_mean):
            raise ValueError("moving_mean values must be non-negative or None")
        if any(type(value) is not bool for value in self.bullish):
            raise TypeError("bullish values must be booleans")

    @property
    def row_count(self) -> int:
        return self.end_index_exclusive - self.base_index

    def contains_global_index(self, global_index: int) -> bool:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        return self.base_index <= global_index < self.end_index_exclusive

    def local_index_for_global(self, global_index: int) -> int | None:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        local = global_index - self.base_index
        return local if 0 <= local < self.row_count else None


def build_resident_volume_projection(
    dataset: HistoricalDataset,
    resident: ResidentOHLCVSlice,
    *,
    period: int = DEFAULT_VOLUME_MEAN_PERIOD,
) -> ResidentVolumeProjection:
    """Build raw volume, direction, and a full-history rolling mean.

    Only the resident result is returned, but the rolling mean seeds from the
    required preceding full-dataset rows.  Therefore the first visible resident
    value remains identical to a full-dataset rolling calculation instead of
    restarting at each resident boundary.
    """

    if not isinstance(dataset, HistoricalDataset):
        raise TypeError("dataset must be a HistoricalDataset")
    if not isinstance(resident, ResidentOHLCVSlice):
        raise TypeError("resident must be a ResidentOHLCVSlice")
    if type(period) is not int or period <= 0:
        raise ValueError("period must be a positive integer")
    if resident.market_id != dataset.market_id:
        raise ValueError("resident MarketId does not match the full dataset")
    if resident.dataset_fingerprint != dataset.file_sha256:
        raise ValueError("resident fingerprint does not match the full dataset")
    if resident.end_index_exclusive > dataset.row_count:
        raise ValueError("resident range exceeds the full dataset")
    bounds = slice(resident.base_index, resident.end_index_exclusive)
    expected_columns = (
        dataset.open[bounds],
        dataset.high[bounds],
        dataset.low[bounds],
        dataset.close[bounds],
        dataset.volume[bounds],
    )
    resident_columns = (
        resident.open,
        resident.high,
        resident.low,
        resident.close,
        resident.volume,
    )
    if expected_columns != resident_columns:
        raise ValueError("resident OHLCV values do not match the full dataset")

    seed_start = max(0, resident.base_index - period + 1)
    window: deque[float] = deque()
    rolling_sum = 0.0
    moving_mean: list[float | None] = []

    for global_index in range(seed_start, resident.end_index_exclusive):
        value = float(dataset.volume[global_index])
        window.append(value)
        rolling_sum += value
        if len(window) > period:
            rolling_sum -= window.popleft()
        if global_index >= resident.base_index:
            moving_mean.append(
                rolling_sum / period if len(window) == period else None
            )

    bullish = tuple(
        close_price >= open_price
        for open_price, close_price in zip(resident.open, resident.close, strict=True)
    )
    return ResidentVolumeProjection(
        market_id=dataset.market_id,
        dataset_fingerprint=dataset.file_sha256,
        base_index=resident.base_index,
        end_index_exclusive=resident.end_index_exclusive,
        period=period,
        volume=resident.volume,
        moving_mean=tuple(moving_mean),
        bullish=bullish,
    )
