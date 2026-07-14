"""Immutable full-dataset loading for accepted historical OHLCV Research data."""

from __future__ import annotations

import csv
import hashlib
import math
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research.catalog import (
    AcceptedDatasetCatalog,
    AcceptedDatasetSummary,
    DatasetRejection,
)

_CSV_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")
LoadProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]


class DatasetNotAcceptedError(PermissionError):
    """Raised when Research cannot obtain current accepted dataset evidence."""


class HistoricalDatasetLoadError(ValueError):
    """Raised when accepted persisted evidence and parsed OHLCV bytes disagree."""


class HistoricalDatasetLoadCancelled(RuntimeError):
    """Raised cooperatively before a loaded dataset is published to the cache."""


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    """Immutable full OHLCV dataset shared read-only between Research sessions."""

    market_id: MarketId
    csv_path: Path
    file_sha256: str
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    ts_ms: tuple[int, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if type(self.row_count) is not int or self.row_count <= 0:
            raise ValueError("row_count must be a positive integer")
        columns = (self.ts_ms, self.open, self.high, self.low, self.close, self.volume)
        if any(len(column) != self.row_count for column in columns):
            raise ValueError("all OHLCV columns must match row_count")
        if self.ts_ms[0] != self.first_timestamp_ms:
            raise ValueError("first_timestamp_ms must match the first timestamp")
        if self.ts_ms[-1] != self.last_timestamp_ms:
            raise ValueError("last_timestamp_ms must match the last timestamp")


class HistoricalDatasetLoader:
    """Load accepted OHLCV CSV bytes into one bounded shared immutable cache."""

    def __init__(
        self,
        catalog: AcceptedDatasetCatalog,
        *,
        max_cache_entries: int = 4,
        progress_interval_rows: int = 10_000,
    ) -> None:
        if not isinstance(catalog, AcceptedDatasetCatalog):
            raise TypeError("catalog must be an AcceptedDatasetCatalog")
        if type(max_cache_entries) is not int or max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be a positive integer")
        if type(progress_interval_rows) is not int or progress_interval_rows <= 0:
            raise ValueError("progress_interval_rows must be a positive integer")
        self._catalog = catalog
        self._max_cache_entries = max_cache_entries
        self._progress_interval_rows = progress_interval_rows
        self._cache: OrderedDict[MarketId, HistoricalDataset] = OrderedDict()
        self._dataset_locks: dict[MarketId, Lock] = {}
        self._lock = RLock()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def load(
        self,
        market_id: MarketId,
        *,
        progress: LoadProgressCallback | None = None,
        cancellation_requested: CancellationCheck | None = None,
    ) -> HistoricalDataset:
        market = _canonical_market(market_id)
        cancel_check = cancellation_requested or _never_cancelled
        _raise_if_cancelled(cancel_check)
        dataset_lock = self._lock_for(market)
        with dataset_lock:
            _raise_if_cancelled(cancel_check)
            summary = self._require_accepted(market)
            _raise_if_cancelled(cancel_check)
            cached = self._get_cached(summary)
            if cached is not None:
                if progress is not None:
                    progress(cached.row_count, cached.row_count)
                _raise_if_cancelled(cancel_check)
                return cached
            loaded = self._parse(
                summary,
                progress=progress,
                cancellation_requested=cancel_check,
            )
            _raise_if_cancelled(cancel_check)
            self._publish_cache(loaded)
            return loaded

    def invalidate(self, market_id: MarketId) -> bool:
        market = _canonical_market(market_id)
        dataset_lock = self._lock_for(market)
        with dataset_lock:
            with self._lock:
                return self._cache.pop(market, None) is not None

    def clear_cache(self) -> int:
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def _require_accepted(self, market: MarketId) -> AcceptedDatasetSummary:
        result = self._catalog.inspect_market(market)
        if isinstance(result, DatasetRejection):
            raise DatasetNotAcceptedError(
                f"Research dataset {market.as_key()} is not accepted: "
                f"{result.code}: {result.reason}"
            )
        return result

    def _lock_for(self, market: MarketId) -> Lock:
        with self._lock:
            lock = self._dataset_locks.get(market)
            if lock is None:
                lock = Lock()
                self._dataset_locks[market] = lock
            return lock

    def _get_cached(self, summary: AcceptedDatasetSummary) -> HistoricalDataset | None:
        with self._lock:
            cached = self._cache.get(summary.market_id)
            if cached is None:
                return None
            evidence_matches = (
                cached.file_sha256 == summary.file_sha256
                and cached.row_count == summary.row_count
                and cached.first_timestamp_ms == summary.first_timestamp_ms
                and cached.last_timestamp_ms == summary.last_timestamp_ms
                and cached.csv_path == summary.csv_path
            )
            if not evidence_matches:
                self._cache.pop(summary.market_id, None)
                return None
            self._cache.move_to_end(summary.market_id)
            return cached

    def _publish_cache(self, dataset: HistoricalDataset) -> None:
        with self._lock:
            self._cache[dataset.market_id] = dataset
            self._cache.move_to_end(dataset.market_id)
            while len(self._cache) > self._max_cache_entries:
                self._cache.popitem(last=False)

    def _parse(
        self,
        summary: AcceptedDatasetSummary,
        *,
        progress: LoadProgressCallback | None,
        cancellation_requested: CancellationCheck,
    ) -> HistoricalDataset:
        csv_before = _stat_fingerprint(summary.csv_path)
        sidecar_before = _stat_fingerprint(summary.sidecar_path)
        digest = hashlib.sha256()
        timestamps: list[int] = []
        opens: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        closes: list[float] = []
        volumes: list[float] = []

        try:
            with summary.csv_path.open("rb") as raw_handle:
                reader = csv.DictReader(_decoded_lines(raw_handle, digest))
                if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
                    raise HistoricalDatasetLoadError(
                        f"invalid OHLCV CSV columns: {reader.fieldnames!r}; "
                        f"expected={_CSV_COLUMNS!r}"
                    )
                previous_timestamp: int | None = None
                for line_number, row in enumerate(reader, start=2):
                    _raise_if_cancelled(cancellation_requested)
                    candle = _parse_row(row, line_number)
                    if previous_timestamp is not None and candle[0] <= previous_timestamp:
                        kind = "duplicate" if candle[0] == previous_timestamp else "out-of-order"
                        raise HistoricalDatasetLoadError(
                            f"{kind} timestamp at line {line_number}: {candle[0]} "
                            f"after {previous_timestamp}"
                        )
                    previous_timestamp = candle[0]
                    timestamps.append(candle[0])
                    opens.append(candle[1])
                    highs.append(candle[2])
                    lows.append(candle[3])
                    closes.append(candle[4])
                    volumes.append(candle[5])
                    current = len(timestamps)
                    if progress is not None and (
                        current == summary.row_count
                        or current % self._progress_interval_rows == 0
                    ):
                        progress(current, summary.row_count)
        except UnicodeDecodeError as error:
            raise HistoricalDatasetLoadError("candles.csv is not valid UTF-8") from error
        except OSError as error:
            raise HistoricalDatasetLoadError(
                f"candles.csv could not be read: {type(error).__name__}: {error}"
            ) from error

        _raise_if_cancelled(cancellation_requested)
        csv_after = _stat_fingerprint(summary.csv_path)
        sidecar_after = _stat_fingerprint(summary.sidecar_path)
        if csv_before != csv_after:
            raise HistoricalDatasetLoadError("candles.csv changed while Research was loading it")
        if sidecar_before != sidecar_after:
            raise HistoricalDatasetLoadError(
                "candles.meta.json changed while Research was loading the dataset"
            )
        file_sha256 = digest.hexdigest()
        if file_sha256 != summary.file_sha256:
            raise HistoricalDatasetLoadError(
                "candles.csv bytes do not match the accepted sidecar SHA-256"
            )
        if len(timestamps) != summary.row_count:
            raise HistoricalDatasetLoadError(
                f"CSV row count {len(timestamps)} does not match accepted sidecar "
                f"row_count {summary.row_count}"
            )
        if not timestamps:
            raise HistoricalDatasetLoadError("accepted OHLCV dataset is empty")
        if timestamps[0] != summary.first_timestamp_ms:
            raise HistoricalDatasetLoadError(
                "first CSV timestamp does not match accepted sidecar evidence"
            )
        if timestamps[-1] != summary.last_timestamp_ms:
            raise HistoricalDatasetLoadError(
                "last CSV timestamp does not match accepted sidecar evidence"
            )
        _raise_if_cancelled(cancellation_requested)
        return HistoricalDataset(
            market_id=summary.market_id,
            csv_path=summary.csv_path,
            file_sha256=file_sha256,
            row_count=len(timestamps),
            first_timestamp_ms=timestamps[0],
            last_timestamp_ms=timestamps[-1],
            ts_ms=tuple(timestamps),
            open=tuple(opens),
            high=tuple(highs),
            low=tuple(lows),
            close=tuple(closes),
            volume=tuple(volumes),
        )


def _decoded_lines(raw_handle, digest) -> Iterator[str]:
    for raw_line in raw_handle:
        digest.update(raw_line)
        yield raw_line.decode("utf-8")


def _parse_row(
    row: dict[str | None, str | list[str] | None],
    line_number: int,
) -> tuple[int, float, float, float, float, float]:
    if None in row:
        raise HistoricalDatasetLoadError(f"unexpected extra CSV columns at line {line_number}")
    try:
        timestamp = int(_required_cell(row, "ts_ms", line_number))
        open_value = float(_required_cell(row, "open", line_number))
        high_value = float(_required_cell(row, "high", line_number))
        low_value = float(_required_cell(row, "low", line_number))
        close_value = float(_required_cell(row, "close", line_number))
        volume_value = float(_required_cell(row, "volume", line_number))
    except ValueError as error:
        raise HistoricalDatasetLoadError(f"invalid OHLCV value at line {line_number}") from error
    numeric = (open_value, high_value, low_value, close_value, volume_value)
    if not all(math.isfinite(value) for value in numeric):
        raise HistoricalDatasetLoadError(f"non-finite OHLCV value at line {line_number}")
    if high_value < low_value:
        raise HistoricalDatasetLoadError(f"high is below low at line {line_number}")
    if high_value < max(open_value, close_value):
        raise HistoricalDatasetLoadError(
            f"high is below open or close at line {line_number}"
        )
    if low_value > min(open_value, close_value):
        raise HistoricalDatasetLoadError(
            f"low is above open or close at line {line_number}"
        )
    if volume_value < 0:
        raise HistoricalDatasetLoadError(f"volume is negative at line {line_number}")
    return timestamp, open_value, high_value, low_value, close_value, volume_value


def _required_cell(
    row: dict[str | None, str | list[str] | None],
    name: str,
    line_number: int,
) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDatasetLoadError(
            f"missing {name!r} value at line {line_number}"
        )
    return value.strip()


def _stat_fingerprint(path: Path) -> tuple[int, int, int]:
    try:
        stat = path.stat()
    except OSError as error:
        raise HistoricalDatasetLoadError(
            f"required dataset file could not be inspected: {path}: "
            f"{type(error).__name__}: {error}"
        ) from error
    return stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0)


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
    return canonical


def _raise_if_cancelled(check: CancellationCheck) -> None:
    if check():
        raise HistoricalDatasetLoadCancelled("historical dataset load was cancelled")


def _never_cancelled() -> bool:
    return False
