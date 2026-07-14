"""Immutable resident OHLCV slicing for Research chart sessions.

The full accepted :class:`HistoricalDataset` remains the canonical read model.
This module derives bounded, disposable resident windows for chart rendering.
It performs no filesystem access, validation mutation, GUI work, or task
management.
"""

from __future__ import annotations

import bisect
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research.dataset import HistoricalDataset

DEFAULT_VISIBLE_MAX = 2_000
DEFAULT_BUFFER_LEFT = 1_500
DEFAULT_BUFFER_RIGHT = 1_500
DEFAULT_RESIDENT_TARGET = (
    DEFAULT_VISIBLE_MAX + DEFAULT_BUFFER_LEFT + DEFAULT_BUFFER_RIGHT
)

_CacheKey = tuple[MarketId, str, int, int]


@dataclass(frozen=True, slots=True)
class ResidentOHLCVSlice:
    """Immutable resident projection of one full historical dataset."""

    market_id: MarketId
    dataset_fingerprint: str
    base_index: int
    end_index_exclusive: int
    ts_ms: tuple[int, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    has_more_left: bool
    has_more_right: bool
    first_timestamp_ms: int
    last_timestamp_ms: int

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

        columns = (self.ts_ms, self.open, self.high, self.low, self.close, self.volume)
        expected_size = self.end_index_exclusive - self.base_index
        if any(len(column) != expected_size for column in columns):
            raise ValueError("all resident OHLCV columns must match the resident range")
        if self.ts_ms[0] != self.first_timestamp_ms:
            raise ValueError("first_timestamp_ms must match the first resident timestamp")
        if self.ts_ms[-1] != self.last_timestamp_ms:
            raise ValueError("last_timestamp_ms must match the last resident timestamp")

    @property
    def row_count(self) -> int:
        return self.end_index_exclusive - self.base_index

    @property
    def last_global_index(self) -> int:
        return self.end_index_exclusive - 1

    def contains_global_index(self, global_index: int) -> bool:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        return self.base_index <= global_index < self.end_index_exclusive


class ResidentSliceService:
    """Derive edge-aware resident windows from immutable full datasets.

    Cache entries are disposable projections keyed by canonical ``MarketId``,
    dataset SHA-256 fingerprint, and resident range. When a new fingerprint for
    the same market is observed, all slices derived from older bytes are
    discarded before the new slice is returned.
    """

    def __init__(self, *, max_cache_entries: int = 128) -> None:
        if type(max_cache_entries) is not int or max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be a positive integer")
        self._max_cache_entries = max_cache_entries
        self._cache: OrderedDict[_CacheKey, ResidentOHLCVSlice] = OrderedDict()
        self._lock = RLock()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def slice_around_index(
        self,
        dataset: HistoricalDataset,
        center_index: int,
        *,
        visible_max: int = DEFAULT_VISIBLE_MAX,
        buffer_left: int = DEFAULT_BUFFER_LEFT,
        buffer_right: int = DEFAULT_BUFFER_RIGHT,
    ) -> ResidentOHLCVSlice:
        """Return an edge-aware resident slice centered near a global index.

        Out-of-range center indexes are clamped to the nearest real dataset row.
        This allows the later chart camera to map empty left/right padding to the
        first or last real dataset window without creating invalid slice state.
        """

        _validate_dataset(dataset)
        if type(center_index) is not int:
            raise TypeError("center_index must be an integer")
        visible, left, right = _validated_window_sizes(
            visible_max,
            buffer_left,
            buffer_right,
        )
        clamped_center = min(max(center_index, 0), dataset.row_count - 1)
        start, end = _resident_bounds(
            dataset.row_count,
            clamped_center,
            visible,
            left,
            right,
        )
        return self._slice(dataset, start, end)

    def slice_around_timestamp(
        self,
        dataset: HistoricalDataset,
        center_timestamp_ms: int,
        *,
        visible_max: int = DEFAULT_VISIBLE_MAX,
        buffer_left: int = DEFAULT_BUFFER_LEFT,
        buffer_right: int = DEFAULT_BUFFER_RIGHT,
    ) -> ResidentOHLCVSlice:
        """Return a resident slice centered on the nearest canonical timestamp.

        When the requested timestamp is exactly between two candles, the earlier
        candle is selected. Timestamps outside the dataset clamp to the first or
        last candle.
        """

        _validate_dataset(dataset)
        if type(center_timestamp_ms) is not int:
            raise TypeError("center_timestamp_ms must be an integer")
        center_index = _nearest_timestamp_index(dataset.ts_ms, center_timestamp_ms)
        return self.slice_around_index(
            dataset,
            center_index,
            visible_max=visible_max,
            buffer_left=buffer_left,
            buffer_right=buffer_right,
        )

    def invalidate_dataset(self, market_id: MarketId) -> int:
        """Remove all cached resident projections for one canonical market."""

        market = _canonical_market(market_id)
        with self._lock:
            keys = [key for key in self._cache if key[0] == market]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def clear_cache(self) -> int:
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def _slice(
        self,
        dataset: HistoricalDataset,
        start: int,
        end: int,
    ) -> ResidentOHLCVSlice:
        key: _CacheKey = (
            dataset.market_id,
            dataset.file_sha256,
            start,
            end,
        )
        with self._lock:
            self._drop_stale_fingerprints_locked(dataset)
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        payload = ResidentOHLCVSlice(
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

        with self._lock:
            self._drop_stale_fingerprints_locked(dataset)
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
            self._cache[key] = payload
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_cache_entries:
                self._cache.popitem(last=False)
        return payload

    def _drop_stale_fingerprints_locked(self, dataset: HistoricalDataset) -> None:
        stale = [
            key
            for key in self._cache
            if key[0] == dataset.market_id and key[1] != dataset.file_sha256
        ]
        for key in stale:
            self._cache.pop(key, None)


def _resident_bounds(
    row_count: int,
    center_index: int,
    visible_max: int,
    buffer_left: int,
    buffer_right: int,
) -> tuple[int, int]:
    resident_left = buffer_left + visible_max // 2
    resident_right = buffer_right + (visible_max - visible_max // 2)
    start = center_index - resident_left
    end = center_index + resident_right

    if start < 0:
        deficit = -start
        start = 0
        end = min(row_count, end + deficit)
    if end > row_count:
        deficit = end - row_count
        end = row_count
        start = max(0, start - deficit)

    if start >= end:
        raise RuntimeError("resident range calculation produced an empty slice")
    return start, end


def _nearest_timestamp_index(timestamps: tuple[int, ...], target: int) -> int:
    insertion = bisect.bisect_left(timestamps, target)
    if insertion <= 0:
        return 0
    if insertion >= len(timestamps):
        return len(timestamps) - 1
    previous = insertion - 1
    if abs(timestamps[previous] - target) <= abs(timestamps[insertion] - target):
        return previous
    return insertion


def _validated_window_sizes(
    visible_max: int,
    buffer_left: int,
    buffer_right: int,
) -> tuple[int, int, int]:
    if type(visible_max) is not int or visible_max <= 0:
        raise ValueError("visible_max must be a positive integer")
    if type(buffer_left) is not int or buffer_left < 0:
        raise ValueError("buffer_left must be a non-negative integer")
    if type(buffer_right) is not int or buffer_right < 0:
        raise ValueError("buffer_right must be a non-negative integer")
    return visible_max, buffer_left, buffer_right


def _validate_dataset(dataset: HistoricalDataset) -> None:
    if not isinstance(dataset, HistoricalDataset):
        raise TypeError("dataset must be a HistoricalDataset")


def _canonical_market(market_id: MarketId) -> MarketId:
    if not isinstance(market_id, MarketId):
        raise TypeError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )
    if canonical != market_id:
        raise ValueError(f"market_id must already be canonical: {canonical!r}")
    return market_id
