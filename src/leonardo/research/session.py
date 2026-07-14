"""Chart-session state for accepted historical Research datasets.

This module owns the mutable state of one Research chart session.  It keeps
accepted full-dataset truth separate from disposable resident projections and
uses generation/request tokens to reject late asynchronous results.  It owns no
viewport mathematics, Qt widgets, persistence, Financial Tool calculations, or
Core task lifecycle.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.resident import ResidentOHLCVSlice


class ChartSessionDisposedError(RuntimeError):
    """Raised when new work is requested after a chart session is disposed."""


class ChartSessionStateError(RuntimeError):
    """Raised when an operation requires chart-session truth that is unavailable."""


@dataclass(frozen=True, slots=True)
class DatasetOpenAttempt:
    """Owner-local correlation token for one asynchronous dataset-open attempt."""

    session_id: str
    generation: int
    market_id: MarketId

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        _require_canonical_market(self.market_id)


@dataclass(frozen=True, slots=True)
class ResidentSliceAttempt:
    """Owner-local correlation token for one asynchronous resident-slice request."""

    session_id: str
    generation: int
    request_id: str
    market_id: MarketId
    dataset_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("request_id must be a non-empty string")
        _require_canonical_market(self.market_id)
        if not isinstance(self.dataset_fingerprint, str) or not self.dataset_fingerprint:
            raise ValueError("dataset_fingerprint must be a non-empty string")


class ChartSessionState:
    """Canonical mutable data state for one historical Research chart.

    The session retains shared references to immutable :class:`HistoricalDataset`
    and :class:`ResidentOHLCVSlice` values.  It does not duplicate full timelines,
    timestamp maps, or OHLCV arrays.  A new dataset-open generation supersedes all
    earlier dataset and slice attempts.  A new slice request supersedes the older
    slice request for the current generation.
    """

    def __init__(self, *, session_id: str | None = None) -> None:
        resolved_session_id = session_id or uuid4().hex
        if not isinstance(resolved_session_id, str) or not resolved_session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        self._session_id = resolved_session_id.strip()
        self._generation = 0
        self._selected_market_id: MarketId | None = None
        self._dataset: HistoricalDataset | None = None
        self._resident: ResidentOHLCVSlice | None = None
        self._open_attempt: DatasetOpenAttempt | None = None
        self._slice_attempt: ResidentSliceAttempt | None = None
        self._disposed = False
        self._lock = RLock()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def is_disposed(self) -> bool:
        with self._lock:
            return self._disposed

    @property
    def selected_market_id(self) -> MarketId | None:
        with self._lock:
            return self._selected_market_id

    @property
    def dataset(self) -> HistoricalDataset | None:
        with self._lock:
            return self._dataset

    @property
    def resident(self) -> ResidentOHLCVSlice | None:
        with self._lock:
            return self._resident

    @property
    def dataset_fingerprint(self) -> str | None:
        with self._lock:
            return None if self._dataset is None else self._dataset.file_sha256

    @property
    def dataset_open_pending(self) -> bool:
        with self._lock:
            return self._open_attempt is not None

    @property
    def resident_slice_pending(self) -> bool:
        with self._lock:
            return self._slice_attempt is not None

    @property
    def dataset_count(self) -> int:
        with self._lock:
            return 0 if self._dataset is None else self._dataset.row_count

    @property
    def resident_count(self) -> int:
        with self._lock:
            return 0 if self._resident is None else self._resident.row_count

    def begin_dataset_open(self, market_id: MarketId) -> DatasetOpenAttempt:
        """Begin a new dataset generation and release all previous data truth."""

        market = _require_canonical_market(market_id)
        with self._lock:
            self._ensure_active_locked()
            self._generation += 1
            attempt = DatasetOpenAttempt(
                session_id=self._session_id,
                generation=self._generation,
                market_id=market,
            )
            self._selected_market_id = market
            self._dataset = None
            self._resident = None
            self._open_attempt = attempt
            self._slice_attempt = None
            return attempt

    def accept_dataset_open(
        self,
        attempt: DatasetOpenAttempt,
        dataset: HistoricalDataset,
    ) -> bool:
        """Publish a current accepted dataset; return ``False`` for a stale result."""

        _validate_open_attempt(attempt)
        if not isinstance(dataset, HistoricalDataset):
            raise TypeError("dataset must be a HistoricalDataset")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._open_attempt:
                return False
            if dataset.market_id != attempt.market_id:
                raise ValueError("dataset MarketId does not match the open attempt")
            if self._selected_market_id != attempt.market_id:
                return False
            self._dataset = dataset
            self._resident = None
            self._open_attempt = None
            self._slice_attempt = None
            return True

    def settle_dataset_open_failure(self, attempt: DatasetOpenAttempt) -> bool:
        """Settle the current open failure without accepting any dataset truth."""

        _validate_open_attempt(attempt)
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._open_attempt:
                return False
            self._open_attempt = None
            self._dataset = None
            self._resident = None
            self._slice_attempt = None
            return True

    def begin_resident_slice_request(self) -> ResidentSliceAttempt:
        """Create the latest resident-slice request for the accepted dataset."""

        with self._lock:
            self._ensure_active_locked()
            dataset = self._require_dataset_locked()
            attempt = ResidentSliceAttempt(
                session_id=self._session_id,
                generation=self._generation,
                request_id=uuid4().hex,
                market_id=dataset.market_id,
                dataset_fingerprint=dataset.file_sha256,
            )
            self._slice_attempt = attempt
            return attempt

    def accept_resident_slice(
        self,
        attempt: ResidentSliceAttempt,
        resident: ResidentOHLCVSlice,
    ) -> bool:
        """Publish the current resident result; return ``False`` when it is stale."""

        _validate_slice_attempt(attempt)
        if not isinstance(resident, ResidentOHLCVSlice):
            raise TypeError("resident must be a ResidentOHLCVSlice")
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._slice_attempt:
                return False
            dataset = self._require_dataset_locked()
            self._validate_current_slice_locked(attempt, resident, dataset)
            self._resident = resident
            self._slice_attempt = None
            return True

    def settle_resident_slice_failure(self, attempt: ResidentSliceAttempt) -> bool:
        """Settle the current resident request without replacing resident truth."""

        _validate_slice_attempt(attempt)
        with self._lock:
            self._require_attempt_session_locked(attempt.session_id)
            if self._disposed or attempt != self._slice_attempt:
                return False
            self._slice_attempt = None
            return True

    def exact_global_index_for_timestamp(self, timestamp_ms: int) -> int | None:
        if type(timestamp_ms) is not int:
            raise TypeError("timestamp_ms must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            position = bisect.bisect_left(timestamps, timestamp_ms)
            if position < len(timestamps) and timestamps[position] == timestamp_ms:
                return position
            return None

    def nearest_global_index_for_timestamp(self, timestamp_ms: int) -> int:
        """Return the nearest candle index, preferring the earlier candle on ties."""

        if type(timestamp_ms) is not int:
            raise TypeError("timestamp_ms must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            position = bisect.bisect_left(timestamps, timestamp_ms)
            if position <= 0:
                return 0
            if position >= len(timestamps):
                return len(timestamps) - 1
            previous = position - 1
            if abs(timestamps[previous] - timestamp_ms) <= abs(
                timestamps[position] - timestamp_ms
            ):
                return previous
            return position

    def timestamp_for_global_index(self, global_index: int) -> int | None:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        with self._lock:
            timestamps = self._require_dataset_locked().ts_ms
            if 0 <= global_index < len(timestamps):
                return timestamps[global_index]
            return None

    def resident_index_for_global(self, global_index: int) -> int | None:
        if type(global_index) is not int:
            raise TypeError("global_index must be an integer")
        with self._lock:
            resident = self._require_resident_locked()
            if not resident.contains_global_index(global_index):
                return None
            return global_index - resident.base_index

    def global_index_for_resident(self, resident_index: int) -> int:
        if type(resident_index) is not int:
            raise TypeError("resident_index must be an integer")
        with self._lock:
            resident = self._require_resident_locked()
            if not 0 <= resident_index < resident.row_count:
                raise IndexError("resident_index is outside the resident slice")
            return resident.base_index + resident_index

    def dispose(self) -> bool:
        """Seal the session, invalidate attempts, and release dataset references."""

        with self._lock:
            if self._disposed:
                return False
            self._disposed = True
            self._generation += 1
            self._selected_market_id = None
            self._dataset = None
            self._resident = None
            self._open_attempt = None
            self._slice_attempt = None
            return True

    def _validate_current_slice_locked(
        self,
        attempt: ResidentSliceAttempt,
        resident: ResidentOHLCVSlice,
        dataset: HistoricalDataset,
    ) -> None:
        if attempt.generation != self._generation:
            raise ValueError("resident attempt generation does not match the session")
        if attempt.market_id != dataset.market_id:
            raise ValueError("resident attempt MarketId does not match the active dataset")
        if attempt.dataset_fingerprint != dataset.file_sha256:
            raise ValueError("resident attempt fingerprint does not match the active dataset")
        if resident.market_id != dataset.market_id:
            raise ValueError("resident MarketId does not match the active dataset")
        if resident.dataset_fingerprint != dataset.file_sha256:
            raise ValueError("resident fingerprint does not match the active dataset")
        if resident.end_index_exclusive > dataset.row_count:
            raise ValueError("resident range exceeds the active dataset")
        start = resident.base_index
        end = resident.end_index_exclusive
        expected_columns = (
            dataset.ts_ms[start:end],
            dataset.open[start:end],
            dataset.high[start:end],
            dataset.low[start:end],
            dataset.close[start:end],
            dataset.volume[start:end],
        )
        resident_columns = (
            resident.ts_ms,
            resident.open,
            resident.high,
            resident.low,
            resident.close,
            resident.volume,
        )
        if resident_columns != expected_columns:
            raise ValueError("resident OHLCV values do not match the active dataset range")

    def _ensure_active_locked(self) -> None:
        if self._disposed:
            raise ChartSessionDisposedError("chart session is disposed")

    def _require_dataset_locked(self) -> HistoricalDataset:
        self._ensure_active_locked()
        if self._dataset is None:
            raise ChartSessionStateError("chart session has no accepted dataset")
        return self._dataset

    def _require_resident_locked(self) -> ResidentOHLCVSlice:
        self._ensure_active_locked()
        if self._resident is None:
            raise ChartSessionStateError("chart session has no resident slice")
        return self._resident

    def _require_attempt_session_locked(self, session_id: str) -> None:
        if session_id != self._session_id:
            raise ValueError("attempt belongs to a different chart session")


def _validate_open_attempt(attempt: DatasetOpenAttempt) -> None:
    if not isinstance(attempt, DatasetOpenAttempt):
        raise TypeError("attempt must be a DatasetOpenAttempt")


def _validate_slice_attempt(attempt: ResidentSliceAttempt) -> None:
    if not isinstance(attempt, ResidentSliceAttempt):
        raise TypeError("attempt must be a ResidentSliceAttempt")


def _require_canonical_market(market_id: MarketId) -> MarketId:
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
