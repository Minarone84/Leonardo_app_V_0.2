"""Owner-local models for the historical OHLCV download workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from leonardo.data import MarketId


@dataclass(frozen=True, slots=True)
class DownloadBatchRequest:
    exchange: str
    market_type: str
    symbol: str
    timeframes: Sequence[str]
    start_ms: int | None = None
    end_ms: int | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    mode: str
    effective_start_ms: int | None
    end_cursor_ms: int | None
    planned_end_ms: int | None
    latest_closed_ts_ms: int | None
    oldest_available_ts_ms: int | None
    page_limit: int
    max_pages: int
    expected_bars: int | None
    expected_pages: int | None
    determinate_progress: bool
    up_to_date: bool = False
    reason: str | None = None
    derived_from_now: bool = False


@dataclass(frozen=True, slots=True)
class DownloadPreflightItem:
    market_id: MarketId
    mode: str
    path: Path
    local_csv_exists: bool
    local_metadata_exists: bool
    local_metadata_valid: bool
    local_first_ts_ms: int | None
    local_last_ts_ms: int | None
    local_row_count: int
    local_state_issues: tuple[str, ...]
    exchange_oldest_ts_ms: int | None
    exchange_youngest_ts_ms: int | None
    planned_start_ms: int | None
    planned_end_ms: int | None
    expected_bars: int | None
    expected_pages: int | None
    page_limit: int
    up_to_date: bool
    can_download: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadPreflightResult:
    exchange: str
    market_type: str
    symbol: str
    timeframes: tuple[str, ...]
    items: tuple[DownloadPreflightItem, ...]

    @property
    def can_download(self) -> bool:
        return bool(self.items) and all(item.can_download for item in self.items)


@dataclass(frozen=True, slots=True)
class DownloadProgressEvent:
    kind: str
    message: str
    timeframe: str | None = None
    current: int | None = None
    total: int | None = None
    overall_current: int | None = None
    overall_total: int | None = None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DownloadItemResult:
    market_id: MarketId
    file_path: Path
    total_rows: int
    fetched_rows: int
    downloaded_first_ts_ms: int | None
    downloaded_last_ts_ms: int | None
    preliminary_validation_status: str
    preliminary_validation_issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownloadBatchResult:
    requested_timeframes: tuple[str, ...]
    completed_timeframes: tuple[str, ...]
    results: tuple[DownloadItemResult, ...]
