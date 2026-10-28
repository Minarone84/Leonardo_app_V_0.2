# Connection Suite - Data and Interface Contracts

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Updated:** 2026-10-09

**Development status:** Connection Suite is still incomplete and will undergo further development. Its structure can still change significantly. This document describes the current implementation, not a frozen future design.

Read with [scope](CONNECTION_SUITE.md), [architecture](CONNECTION_ARCHITECTURE.md), [lifecycles](CONNECTION_LIFECYCLES.md) and the [map](Leonardo_V2_Connection_Suite_Complete_Map.pdf). Runtime records below are disposable unless explicitly identified as durable. Source-exact appendices describe this edition, not a frozen future API.

## 1. Identity and request validation

`MarketId(exchange, market_type, symbol, timeframe)` identifies exactly one market series. Its key joins fields with colons: `bybit:linear:BTCUSDT:1m`. Constructing MarketId checks nonempty strings; boundary callers use `canonicalize_market_id` for normalization. Exchange is trimmed/lowercase with letters, digits or underscore. Market type is canonical lowercase. Symbol is uppercased with `/`, `-`, `_`, `:`, and spaces removed; letters, digits and dots remain permitted. Canonical timeframe parsing belongs to `data/market_id.py`; fixed intervals have a duration, calendar months do not.

Download normalization requires a DownloadBatchRequest, non-negative exact integers or None for timestamps/limit (bool is not accepted as an integer), Start <= End when both exist, and at least one timeframe. Each timeframe is canonicalized, duplicates removed preserving input order. It does not independently perform the provider's supported-timeframe/instrument check; the active GUI supplies capability-derived choices.

Separate identities must not be conflated: MarketId scopes storage and locks; task UUID scopes progress/cancellation; correlation UUID links execution evidence; provider connection ID scopes coarse runtime session status; window IDs identify presentation. None is a substitute for dataset acceptance evidence.

## 2. Planning and paging algorithms

Page limit starts at a positive adapter maximum, or 500 when unknown/non-positive. A nonzero caller limit overrides it, capped by a known adapter maximum. Bybit normally yields 1,000. `max_pages=10_000` is a safety ceiling, not a target size.

If End exists, use it as end cursor and preserve an optional Start. Otherwise, local rows with no Start select `update_latest`, start at local last timestamp and find latest closed. All other cases find latest closed and use optional Start; fully automatic new history also discovers oldest. Missing latest-closed evidence falls back to server time and sets `derived_from_now`. Exact no-op condition is update_latest AND both bounds known AND effective_start >= latest_closed.

For a fixed-duration timeframe D with both bounds known, expected bars are 0 if end < start, otherwise floor((end-start)/D)+1. Expected pages are ceiling(bars/page_limit). A true no-op overrides both estimates to zero. Missing bounds or variable-duration months produce None. Estimates are not proof of provider availability or exact fetched totals.

Each page request sends the effective lower bound and current inclusive end cursor. Sort converted candles ascending, filter inclusive bounds, merge, persist. Next cursor = oldest filtered timestamp - 1. The automatic first page removes its newest candle when the provider flags it open, or when it exceeds the known latest-closed bound. The current implementation consults the provider's last candle for that flag; Bybit returns sorted rows. Custom requests retain their explicit-range semantics and do not apply this automatic exclusion.

Established breaks are negative cursor at loop entry, empty provider response, empty filtered page, or oldest timestamp reaching the known start. Existing data must be nonempty before finalization. Exhausting the for-loop without a break raises the ceiling failure before `download_complete`, preliminary validation or finalize. Reaching the lower bound on the last allowed page succeeds. An unknown lower bound cannot be declared complete merely because the ceiling was reached.

`merge_idempotent` replaces by integer timestamp in iteration order, incoming after existing, and returns ascending candles. It does not prove quality or preserve all duplicate source rows. The result's total_rows counts merged rows; fetched_rows counts filtered incoming rows across pages; downloaded_first/last describe incoming coverage. None of these alone proves every expected interval exists.

## 3. Provider and Bybit wire contract

HistoricalOHLCVProvider exposes a name, supported markets/timeframes, maximum page size, open/close, server time, oldest timestamp and historical fetch. ProviderCandle uses milliseconds, float OHLCV values and `is_closed=True` by default. The protocol is structural; adapters remain responsible for their own value semantics.

Default Bybit base is `https://api.bybit.com`; constructor testnet mode uses `https://api-testnet.bybit.com`. Server time calls `/v5/market/time`; historical candles call `/v5/market/kline`. Kline parameters are category, normalized symbol, mapped interval, limit and optional start/end. Intervals map minute/hour values to numeric minutes, day/week/month to `D`/`W`/`M`. Responses require a result mapping and list of rows with at least six numeric-convertible fields. Extra turnover fields are unused. Candles sort ascending.

If response `time` is positive, the adapter marks the newest candle open when its calculated close exceeds that time. Fixed timeframes add their duration; calendar month closes at the next calendar-month boundary. Missing/zero response time does not establish a new open flag. Downstream canonical validation remains necessary.

Oldest discovery uses server time as high bound and zero as low bound. Probe for any candle through an end timestamp using `start=0, limit=1`, then binary search until the window is at most one fixed interval (31 days for monthly discovery). Fetch the final bounded window around high using the existing maximum limit of 1,000, independent of caller-selected page size; return the first sorted row or None. This prevents reverse-ordered limited responses from losing the oldest candle. Thirty-one days is a search bracket, not a monthly candle duration.

| Policy | Current values and meaning |
|---|---|
| Adapter timeout | aiohttp total request timeout defaults to 30 seconds |
| Adapter pacing | Async lock serializes requests per adapter; minimum 0.20 seconds between starts |
| Adapter attempts | At most 4 for retryable wire failures |
| Rate limit | HTTP 429 or Bybit code 10006; use reset timestamp with 0.05-second cushion when usable, capped at 10 seconds; fallback grows from 1 second by attempt |
| Other HTTP retry | 408, 425 and >=500; transport/client/timeout/OSError are retryable |
| Other API errors | Nonzero parsed retCode is permanent unless rate-limited; parsing/row-shape response errors are typed failures |
| JSON failure | Malformed JSON is retried for successful/retryable HTTP statuses; permanent HTTP failures are not retried |
| Downloader page timeout | 30-second `wait_for` around each fetch call |
| Downloader attempts | Up to 3, with 1-second times attempt linear backoff; typed permanent or already-exhausted provider errors stop outer retry |

The adapter's normal retry sleeps use attempt-based seconds bounded by 10. Reset headers also delay later requests when remaining capacity is exhausted. Limits apply per adapter instance, not a global provider account throttle. Cancellation propagates through sleeps and network awaits. Planning calls use adapter behavior but are not all wrapped in the downloader's page-specific outer retry loop. A timeout of that outer wrapper can precede an adapter-exhausted error; do not claim there is a single four-attempt global request budget.

HistoricalProviderRequestError carries provider, operation, retryable, attempts_exhausted, optional HTTP status and code. The downloader includes these in page retry/failure events and eventually raises RuntimeError on terminal fetch failure. No credentials are required or managed by this public REST adapter.

## 4. Persistence and validation contract

```text
<historical_root>/<exchange>/<market_type>/<symbol>/<timeframe_segment>/ohlcv/
    candles.csv
    candles.meta.json
```

Month uses storage segment `1mo` for canonical `1M`; minute uses `1m`, keeping identities distinct on case-insensitive filesystems. The CSV has exactly `ts_ms,open,high,low,close,volume`, UTF-8, an integer timestamp and float OHLCV values. Store writes via csv.writer, flush/fsync, then same-directory temporary-file replacement. Sidecar JSON uses indent 2, sorted keys, finite JSON values and a trailing newline; its replacement has five attempts only for Windows errors 5/32, sleeping 0.05 seconds between retries. CSV replacement does not have that same retry loop.

Each file replacement is atomic. CSV then sidecar is not a joint filesystem transaction. Failure can leave unmatched evidence, which trusted consumers must reject. Temporary files are removed on a failed write where possible; this is not automatic canonical recovery.

OHLCVSidecarV1 serializes schema_version `1.0`, market_id as four fields, file_sha256, row_count, first_timestamp_ms, last_timestamp_ms, source, persistence_status, validation_status, warnings, lineage, created_at_utc and updated_at_utc. Datetimes serialize ISO-8601 and normalize to UTC. SHA is 64 hexadecimal characters normalized lowercase. Row count is a non-negative exact int; nonempty data requires both ordered bounds, empty data requires neither. Timestamps are integer or None. Updated time cannot predate created time. Lineage must be JSON-safe and finite.

Persistence states are partial/committed/repaired; validation states are unknown/ok/warning/error. Store page write and normal finalize set validation unknown and capture CSV SHA, size and mtime. Existing created_at is retained when the prior sidecar can be read. Normal writes replace lineage from the supplied operation plus file evidence; do not promise preservation of arbitrary prior lineage on mutation. The true up-to-date branch bypasses this entire write/finalize path and preserves bytes, mtimes and evidence.

Preliminary checks read the file, require finite OHLCV values, low <= high, open/close within the low/high interval and volume >= 0, test strictly increasing timestamps, flag fixed-interval gaps, and give variable months a warning rather than checking fixed continuity. These checks do not invent a positive-price constraint.

Canonical validation additionally checks exact ordered columns, duplicate/missing/unexpected headers, row width, parseability, non-negative integer timestamps, duplicate/out-of-order timestamps, CSV/sidecar identity/count/range/hash and file stability. Fixed-interval deltas must equal the timeframe duration; month continuity adds calendar months (preserving end-of-month when the source is its month's last day, otherwise clamping the day to the destination month's length). Continuity gaps are warnings. Non-finite numbers, negative volume and invalid OHLC relationships are errors. Status is error if any error exists, otherwise warning if any warning exists, otherwise ok. Quality status and publication eligibility remain independent: a warning/error report may be publishable, but publication does not mean acceptance.

Canonical publication compares expected size, mtime and SHA for both files, requires matching MarketId, final persistence and matching sidecar CSV SHA, then publishes the report and `lineage.canonical_validation` (validator, status, issue_codes, error_count, warning_count). Identical publication is a no-op. Unsafe evidence or concurrent change blocks publication rather than blessing stale rows.

Research strict catalog admission requires canonical path/identity, both readable files, supported sidecar, final persistence, validation ok, positive row count, declared time range, stable CSV stat while hashing and CSV SHA equal to sidecar evidence. Metadata-only discovery deliberately omits payload hashing; it is not identical to strict trusted-use verification. Research/DMS documentation specifies their own loader and operation-scoped checks.

If the monthly successor conversion raises OverflowError or ValueError, canonical validation records an error issue `timestamp_out_of_range` at the current row/`ts_ms`, with the unrepresentable successor reason. Valid calendar-month/end-of-month/leap-year behavior is unchanged. Input timestamps are not clamped; this bounded conversion handling does not add arbitrary-date support or bypass publication eligibility.

## 5. Events, task metadata and UI contracts

| Event kind | Meaning / relevant details |
|---|---|
| batch_started | Requested timeframe tuple and zero overall progress |
| item_started | Current timeframe and one-based timeframe_index |
| plan_ready | Mode, planned_start_ms/end_ms, expected_pages, page_limit, up_to_date |
| page_retrying / page_failed | Page/attempt/error, estimates and typed provider error details when available |
| page_persisted | Page, page_rows, total_rows, path, expected_pages, progress_ratio; sent after settled successful write |
| preliminary_validation_completed | Status/issues/row_count; no-op carries up_to_date, mutation path reports validation_status unknown |
| source_evidence_changed | Changed or uncertain CSV/sidecar witnesses on exit, including failure; details contain market_id, timeframe and changed_files with before/after evidence |
| item_completed | Path, total_rows, fetched_rows, preliminary validation status |
| batch_progress | Completed timeframe tuple and overall progress |
| item_cancelled | Actual page/row counts, persisted/downloaded ranges, partial_persistence, download_complete, persistence_status and path where pages were written |
| batch_cancelled | Completed and remaining timeframe tuples; cancellation is re-raised |
| batch_failed | Error type/message; completed prefix also retained in audit |
| batch_completed | All completed timeframes; DownloadBatchResult follows |

Optional counters are None when unknown. The presenter computes bounded percentages when current/total are meaningful; these are display values, not persisted completeness. Download events are wrapped in `TaskProgress.details["download_event"]`. Domain batch results exist on normal success; failure/cancellation use Core terminal status and event/audit evidence.

Operation metadata: `ohlcv_preflight`, `ohlcv_download`, `ohlcv_validate`, `ohlcv_deletion_plan`, `ohlcv_delete`, `ohlcv_sidecar_reconstruction_plan`, `ohlcv_sidecar_reconstruct`, `ohlcv_repair_plan`, `ohlcv_repair`. Maintenance metadata includes MarketId; plans/results carry reviewed file evidence as shown in the inventory.

Only matching active task IDs can mutate the download UI. Two entry guards prevent replacing an active download. The Qt dispatcher queues callbacks. The retained request resolves event timeframe to MarketId after form closure/reset. Stop is cancellation intent; closing either manager or task display is not equivalent to deleting a dataset. Store sidecars, not cancellation recap wording, determine validation state.

## 6. Observable verification matrix

Paths in this table are relative to `tests/`. Generated providers and temporary roots are required for isolated validation; do not point destructive/recovery tests at real saved data.

| Contract | Existing verification |
|---|---|
| Factory registration, capabilities, scoped sessions and runtime states | `connection_test/test_provider_registry.py` |
| Bybit wire parsing, paging limits, retries, cancellation, oldest discovery including fixed/monthly small-page cases | `connection_test/test_bybit_historical_provider.py` |
| Normalization, preflight/planning, merge, no-op evidence, cancellation fences, page ceiling and repair range execution | `ohlcv_test/test_download_vertical.py` |
| Download/preliminary versus canonical acceptance | `ohlcv_test/test_download_acceptance_workflow.py` |
| Store/sidecar format and evidence | `ohlcv_test/test_store_and_sidecar.py` |
| Canonical validation, publication, repair/reconstruction/deletion and limits | `ohlcv_test/test_maintenance_validation.py`, `test_maintenance_repair.py`, `test_maintenance_sidecar_reconstruction.py`, `test_maintenance_deletion.py`, `test_maintenance_performance.py` |
| Production GUI wiring | `gui_test/test_historical_download_wiring_static.py` |
| Active identity, close/reopen, late progress/results, cancellation and retained request | `gui_test/test_historical_download_lifecycle.py` |
| Composed Connection/Maintenance/Research/DMS behavior | `gui_test/test_download_maintenance_research_workflow.py` |
| Maintenance presenter operations and cleanup | `gui_test/test_ohlcv_maintenance_presenter.py` |

The independent correction audit adds mixed-batch/no-op, zero-fetch custom control, stale callback, sparse/monthly discovery and explicit retry-after-ceiling probes in its external evidence directory. Those are evidence for the current candidate, not additional product modules. Prior results and their limits are summarized in suite section 8.

## 7. Source-exact model field inventory

The tables below are extracted from this candidate's annotated dataclass declarations. Required means no declared default. Type annotations do not add validation beyond each owner's implementation. Derived properties are listed separately. All models are runtime/evidence objects except OHLCVSidecarV1, whose serialized contract is specified above. Maintenance uses the same OHLCV owners; including its boundary records does not make it a Connection-owned subsystem.

### ProviderCandle

Source: `src/leonardo/connection/provider.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `ts_ms` | `int` | `(required)` |
| `open` | `float` | `(required)` |
| `high` | `float` | `(required)` |
| `low` | `float` | `(required)` |
| `close` | `float` | `(required)` |
| `volume` | `float` | `(required)` |
| `is_closed` | `bool` | `True` |

### DownloadBatchRequest

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `exchange` | `str` | `(required)` |
| `market_type` | `str` | `(required)` |
| `symbol` | `str` | `(required)` |
| `timeframes` | `Sequence[str]` | `(required)` |
| `start_ms` | `int \| None` | `None` |
| `end_ms` | `int \| None` | `None` |
| `limit` | `int \| None` | `None` |

### DownloadPlan

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `mode` | `str` | `(required)` |
| `effective_start_ms` | `int \| None` | `(required)` |
| `end_cursor_ms` | `int \| None` | `(required)` |
| `planned_end_ms` | `int \| None` | `(required)` |
| `latest_closed_ts_ms` | `int \| None` | `(required)` |
| `oldest_available_ts_ms` | `int \| None` | `(required)` |
| `page_limit` | `int` | `(required)` |
| `max_pages` | `int` | `(required)` |
| `expected_bars` | `int \| None` | `(required)` |
| `expected_pages` | `int \| None` | `(required)` |
| `determinate_progress` | `bool` | `(required)` |
| `up_to_date` | `bool` | `False` |
| `reason` | `str \| None` | `None` |
| `derived_from_now` | `bool` | `False` |

### DownloadPreflightItem

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `mode` | `str` | `(required)` |
| `path` | `Path` | `(required)` |
| `local_csv_exists` | `bool` | `(required)` |
| `local_metadata_exists` | `bool` | `(required)` |
| `local_metadata_valid` | `bool` | `(required)` |
| `local_first_ts_ms` | `int \| None` | `(required)` |
| `local_last_ts_ms` | `int \| None` | `(required)` |
| `local_row_count` | `int` | `(required)` |
| `local_state_issues` | `tuple[str, ...]` | `(required)` |
| `exchange_oldest_ts_ms` | `int \| None` | `(required)` |
| `exchange_youngest_ts_ms` | `int \| None` | `(required)` |
| `planned_start_ms` | `int \| None` | `(required)` |
| `planned_end_ms` | `int \| None` | `(required)` |
| `expected_bars` | `int \| None` | `(required)` |
| `expected_pages` | `int \| None` | `(required)` |
| `page_limit` | `int` | `(required)` |
| `up_to_date` | `bool` | `(required)` |
| `can_download` | `bool` | `(required)` |
| `reason` | `str \| None` | `None` |

### DownloadPreflightResult

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `exchange` | `str` | `(required)` |
| `market_type` | `str` | `(required)` |
| `symbol` | `str` | `(required)` |
| `timeframes` | `tuple[str, ...]` | `(required)` |
| `items` | `tuple[DownloadPreflightItem, ...]` | `(required)` |

Derived properties: `can_download`.

### DownloadProgressEvent

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `kind` | `str` | `(required)` |
| `message` | `str` | `(required)` |
| `timeframe` | `str \| None` | `None` |
| `current` | `int \| None` | `None` |
| `total` | `int \| None` | `None` |
| `overall_current` | `int \| None` | `None` |
| `overall_total` | `int \| None` | `None` |
| `details` | `Mapping[str, object]` | `field(default_factory=dict)` |

### DownloadItemResult

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `file_path` | `Path` | `(required)` |
| `total_rows` | `int` | `(required)` |
| `fetched_rows` | `int` | `(required)` |
| `downloaded_first_ts_ms` | `int \| None` | `(required)` |
| `downloaded_last_ts_ms` | `int \| None` | `(required)` |
| `preliminary_validation_status` | `str` | `(required)` |
| `preliminary_validation_issues` | `tuple[str, ...]` | `(required)` |
| `up_to_date` | `bool` | `False` |

### DownloadBatchResult

Source: `src/leonardo/ohlcv/models.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `requested_timeframes` | `tuple[str, ...]` | `(required)` |
| `completed_timeframes` | `tuple[str, ...]` | `(required)` |
| `results` | `tuple[DownloadItemResult, ...]` | `(required)` |

### Candle

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `ts_ms` | `int` | `(required)` |
| `open` | `float` | `(required)` |
| `high` | `float` | `(required)` |
| `low` | `float` | `(required)` |
| `close` | `float` | `(required)` |
| `volume` | `float` | `(required)` |

### DatasetInspection

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `csv_path` | `Path` | `(required)` |
| `sidecar_path` | `Path` | `(required)` |
| `csv_exists` | `bool` | `(required)` |
| `metadata_exists` | `bool` | `(required)` |
| `metadata_valid` | `bool` | `(required)` |
| `first_ts_ms` | `int \| None` | `(required)` |
| `last_ts_ms` | `int \| None` | `(required)` |
| `row_count` | `int` | `(required)` |
| `source` | `str` | `(required)` |
| `issues` | `tuple[str, ...]` | `(required)` |

### ValidationPublicationResult

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `sidecar` | `OHLCVSidecarV1` | `(required)` |
| `changed` | `bool` | `(required)` |

### StoredFileEvidence

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `path` | `Path` | `(required)` |
| `size_bytes` | `int` | `(required)` |
| `modified_time_ns` | `int` | `(required)` |
| `sha256` | `str` | `(required)` |

### DatasetDeletionEvidence

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `dataset_dir` | `Path` | `(required)` |
| `csv` | `StoredFileEvidence` | `(required)` |
| `sidecar` | `StoredFileEvidence \| None` | `(required)` |

### DatasetDeletionResult

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `dataset_dir` | `Path` | `(required)` |
| `csv_path` | `Path` | `(required)` |
| `sidecar_path` | `Path` | `(required)` |
| `csv_deleted` | `bool` | `(required)` |
| `sidecar_deleted` | `bool` | `(required)` |
| `removed_directories` | `tuple[Path, ...]` | `(required)` |
| `cleanup_warnings` | `tuple[str, ...]` | `(required)` |

### SidecarReconstructionResult

Source: `src/leonardo/ohlcv/store.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `sidecar` | `OHLCVSidecarV1` | `(required)` |
| `replaced_existing` | `bool` | `(required)` |

### ValidationIssue

Source: `src/leonardo/ohlcv/validation.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `severity` | `str` | `(required)` |
| `code` | `str` | `(required)` |
| `message` | `str` | `(required)` |
| `row_number` | `int \| None` | `None` |
| `column` | `str \| None` | `None` |
| `timestamp_ms` | `int \| None` | `None` |

### PreliminaryValidationReport

Source: `src/leonardo/ohlcv/validation.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `status` | `str` | `(required)` |
| `row_count` | `int` | `(required)` |
| `issues` | `tuple[ValidationIssue, ...]` | `(required)` |

Derived properties: `messages`.

### FileEvidence

Source: `src/leonardo/ohlcv/validation.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `path` | `Path` | `(required)` |
| `size_bytes` | `int` | `(required)` |
| `modified_time_ns` | `int` | `(required)` |
| `sha256` | `str` | `(required)` |

### CanonicalValidationReport

Source: `src/leonardo/ohlcv/validation.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `csv_path` | `Path` | `(required)` |
| `sidecar_path` | `Path` | `(required)` |
| `status` | `str` | `(required)` |
| `row_count` | `int` | `(required)` |
| `first_timestamp_ms` | `int \| None` | `(required)` |
| `last_timestamp_ms` | `int \| None` | `(required)` |
| `issues` | `tuple[ValidationIssue, ...]` | `(required)` |
| `csv_evidence` | `FileEvidence \| None` | `(required)` |
| `sidecar_evidence` | `FileEvidence \| None` | `(required)` |
| `publication_allowed` | `bool` | `(required)` |
| `publication_blockers` | `tuple[str, ...]` | `(required)` |

Derived properties: `error_count`, `warning_count`, `issue_codes`, `warning_messages`, `messages`.

### MaintenanceDatasetSummary

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `csv_path` | `Path` | `(required)` |
| `sidecar_path` | `Path` | `(required)` |
| `csv_exists` | `bool` | `(required)` |
| `sidecar_exists` | `bool` | `(required)` |
| `persistence_status` | `str` | `(required)` |
| `validation_status` | `str` | `(required)` |
| `row_count` | `int` | `(required)` |
| `source` | `str` | `(required)` |
| `evidence_state` | `str` | `(required)` |
| `issues` | `tuple[str, ...]` | `(required)` |
| `first_timestamp_ms` | `int \| None` | `None` |
| `last_timestamp_ms` | `int \| None` | `None` |
| `csv_size_bytes` | `int \| None` | `None` |
| `csv_modified_time_ns` | `int \| None` | `None` |
| `file_sha256` | `str` | `''` |
| `sidecar_schema_version` | `str` | `''` |
| `sidecar_created_at_utc` | `datetime \| None` | `None` |
| `sidecar_updated_at_utc` | `datetime \| None` | `None` |
| `sidecar_warnings` | `tuple[str, ...]` | `()` |
| `validator_id` | `str` | `''` |
| `validation_error_count` | `int \| None` | `None` |
| `validation_warning_count` | `int \| None` | `None` |

### MaintenanceDiscoveryRejection

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `dataset_dir` | `Path` | `(required)` |
| `code` | `str` | `(required)` |
| `reason` | `str` | `(required)` |

### MaintenanceDiscoveryReport

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `datasets` | `tuple[MaintenanceDatasetSummary, ...]` | `(required)` |
| `rejected` | `tuple[MaintenanceDiscoveryRejection, ...]` | `(required)` |

### MaintenanceValidationResult

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `report` | `CanonicalValidationReport` | `(required)` |
| `sidecar` | `OHLCVSidecarV1 \| None` | `(required)` |
| `sidecar_published` | `bool` | `(required)` |
| `publication_changed` | `bool` | `(required)` |
| `publication_error` | `str \| None` | `None` |

Derived properties: `accepted`.

### MaintenanceDeletionPlan

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `evidence` | `DatasetDeletionEvidence` | `(required)` |
| `message` | `str` | `(required)` |

### MaintenanceDeletionResult

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `plan` | `MaintenanceDeletionPlan` | `(required)` |
| `store_result` | `DatasetDeletionResult` | `(required)` |
| `cache_invalidated` | `bool` | `False` |

Derived properties: `completed`.

### MaintenanceSidecarReconstructionPlan

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `validation_report` | `CanonicalValidationReport` | `(required)` |
| `evidence_state` | `str` | `(required)` |
| `actionable` | `bool` | `(required)` |
| `message` | `str` | `(required)` |
| `warnings` | `tuple[str, ...]` | `(required)` |
| `csv_evidence` | `FileEvidence \| None` | `(required)` |
| `sidecar_evidence` | `FileEvidence \| None` | `(required)` |
| `proposed_source` | `str` | `'maintenance_reconstruction'` |
| `proposed_persistence_status` | `str` | `'committed'` |
| `proposed_validation_status` | `str` | `'unknown'` |

### MaintenanceSidecarReconstructionResult

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `plan` | `MaintenanceSidecarReconstructionPlan` | `(required)` |
| `store_result` | `SidecarReconstructionResult` | `(required)` |
| `validation` | `MaintenanceValidationResult` | `(required)` |
| `cache_invalidated` | `bool` | `False` |

Derived properties: `accepted`.

### MaintenanceRepairRange

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `start_ts_ms` | `int` | `(required)` |
| `end_ts_ms` | `int` | `(required)` |
| `reason` | `str` | `(required)` |
| `issue_codes` | `tuple[str, ...]` | `(required)` |
| `coverage_anchor_ts_ms` | `tuple[int, ...]` | `(required)` |
| `estimated_bars` | `int \| None` | `(required)` |

### MaintenanceRepairPlan

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `validation_report` | `CanonicalValidationReport` | `(required)` |
| `actionable` | `bool` | `(required)` |
| `message` | `str` | `(required)` |
| `ranges` | `tuple[MaintenanceRepairRange, ...]` | `(required)` |
| `warnings` | `tuple[str, ...]` | `(required)` |
| `csv_evidence` | `FileEvidence \| None` | `(required)` |
| `sidecar_evidence` | `FileEvidence \| None` | `(required)` |

### MaintenanceRepairRangeResult

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `repair_range` | `MaintenanceRepairRange` | `(required)` |
| `fetched_rows` | `int` | `(required)` |
| `downloaded_first_ts_ms` | `int \| None` | `(required)` |
| `downloaded_last_ts_ms` | `int \| None` | `(required)` |
| `total_rows_after` | `int` | `(required)` |
| `file_path` | `Path` | `(required)` |

### MaintenanceRepairResult

Source: `src/leonardo/ohlcv/maintenance.py`. dataclass(frozen=True, slots=True).

| Field | Type | Default |
|---|---|---|
| `plan` | `MaintenanceRepairPlan` | `(required)` |
| `outcome` | `str` | `(required)` |
| `range_results` | `tuple[MaintenanceRepairRangeResult, ...]` | `(required)` |
| `validation` | `MaintenanceValidationResult` | `(required)` |
| `repaired_sidecar` | `OHLCVSidecarV1` | `(required)` |
| `warnings` | `tuple[str, ...]` | `(required)` |
| `source_invalid` | `bool` | `False` |
| `source_invalid_anchors` | `tuple[int, ...]` | `()` |

Derived properties: `accepted`.

### OHLCVSidecarV1

Source: `src/leonardo/storage/sidecar_v1.py`. dataclass(frozen=True).

| Field | Type | Default |
|---|---|---|
| `market_id` | `MarketId` | `(required)` |
| `file_sha256` | `str` | `(required)` |
| `row_count` | `int` | `(required)` |
| `first_timestamp_ms` | `int \| None` | `(required)` |
| `last_timestamp_ms` | `int \| None` | `(required)` |
| `source` | `str` | `(required)` |
| `persistence_status` | `str` | `(required)` |
| `validation_status` | `str` | `'unknown'` |
| `warnings` | `tuple[str, ...]` | `()` |
| `lineage` | `Mapping[str, object]` | `field(default_factory=dict)` |
| `created_at_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `updated_at_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `schema_version` | `str` | `'1.0'` |

## 8. Source-exact public interface inventory

Signatures include constructors and public properties; `self` is shown as in source, not supplied by the caller. Private helpers are explained by the algorithms above. Mutation interfaces below belong to OHLCV owners and are not permissions for GUI code to bypass the application boundary.


### src/leonardo/connection/provider.py

```python
HistoricalProviderRequestError.__init__(self, message: str, *, provider: str, operation: str, retryable: bool, attempts_exhausted: bool=False, status: int | None=None, code: int | str | None=None) -> None

@property
HistoricalOHLCVProvider.name(self) -> str

HistoricalOHLCVProvider.supported_markets(self) -> Set[str]

HistoricalOHLCVProvider.supported_timeframes(self, market: str) -> Set[str]

HistoricalOHLCVProvider.max_historical_ohlcv_limit(self, market: str) -> int | None

async HistoricalOHLCVProvider.open(self) -> None

async HistoricalOHLCVProvider.close(self) -> None

async HistoricalOHLCVProvider.get_server_time_ms(self) -> int

async HistoricalOHLCVProvider.oldest_historical_ohlcv_ts_ms(self, *, market: str, symbol: str, timeframe: str, limit: int | None=None) -> int | None

async HistoricalOHLCVProvider.fetch_ohlcv_historical(self, *, market: str, symbol: str, timeframe: str, start_ms: int | None=None, end_ms: int | None=None, limit: int | None=None) -> Sequence[ProviderCandle]
```

### src/leonardo/connection/registry.py

```python
ProviderRegistry.__init__(self) -> None

ProviderRegistry.register(self, name: str, factory: ProviderFactory) -> None

ProviderRegistry.names(self) -> tuple[str, ...]

ProviderRegistry.create(self, name: str) -> HistoricalOHLCVProvider

build_default_provider_registry() -> ProviderRegistry
```

### src/leonardo/connection/service.py

```python
ConnectionApplicationService.__init__(self, providers: ProviderRegistry, runtime: ConnectionRegistry) -> None

ConnectionApplicationService.provider_names(self) -> tuple[str, ...]

ConnectionApplicationService.supported_markets(self, provider_name: str) -> tuple[str, ...]

ConnectionApplicationService.supported_timeframes(self, provider_name: str, market: str) -> tuple[str, ...]

@asynccontextmanager
async ConnectionApplicationService.provider_session(self, provider_name: str) -> AsyncIterator[HistoricalOHLCVProvider]
```

### src/leonardo/connection/bybit.py

```python
BybitHistoricalProvider.__init__(self, *, testnet: bool=False, request_timeout_seconds: float=30.0) -> None

@property
BybitHistoricalProvider.name(self) -> str

async BybitHistoricalProvider.open(self) -> None

async BybitHistoricalProvider.close(self) -> None

BybitHistoricalProvider.supported_markets(self) -> Set[str]

BybitHistoricalProvider.supported_timeframes(self, market: str) -> Set[str]

BybitHistoricalProvider.max_historical_ohlcv_limit(self, market: str) -> int

async BybitHistoricalProvider.get_server_time_ms(self) -> int

async BybitHistoricalProvider.fetch_ohlcv_historical(self, *, market: str, symbol: str, timeframe: str, start_ms: int | None=None, end_ms: int | None=None, limit: int | None=None) -> Sequence[ProviderCandle]

async BybitHistoricalProvider.oldest_historical_ohlcv_ts_ms(self, *, market: str, symbol: str, timeframe: str, limit: int | None=None) -> int | None
```

### src/leonardo/ohlcv/download_service.py

```python
HistoricalDownloadService.__init__(self, connection_service: ConnectionApplicationService, store: OHLCVStore, audit_log: AuditLog, *, actor_id: str, operation_locks: OHLCVDatasetOperationLocks | None=None) -> None

@property
HistoricalDownloadService.store(self) -> OHLCVStore

@property
HistoricalDownloadService.operation_locks(self) -> OHLCVDatasetOperationLocks

async HistoricalDownloadService.preflight_batch(self, request: DownloadBatchRequest) -> DownloadPreflightResult

async HistoricalDownloadService.run_batch(self, request: DownloadBatchRequest, *, progress: ProgressSink | None=None, correlation_id: str | None=None) -> DownloadBatchResult

async HistoricalDownloadService.run_repair_batches(self, requests: Sequence[DownloadBatchRequest], *, before_first_write: Callable[[], None], progress: ProgressSink | None=None, correlation_id: str | None=None) -> tuple[DownloadBatchResult, ...]

normalize_batch_request(request: DownloadBatchRequest) -> DownloadBatchRequest
```

### src/leonardo/ohlcv/application.py

```python
HistoricalDownloadApplicationService.__init__(self, core_runner: CoreRunner, downloader: HistoricalDownloadService) -> None

HistoricalDownloadApplicationService.submit_preflight(self, request: DownloadBatchRequest, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

HistoricalDownloadApplicationService.submit_download(self, request: DownloadBatchRequest, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

HistoricalDownloadApplicationService.cancel(self, task_id: str) -> bool

OHLCVMaintenanceApplicationService.__init__(self, core_runner: CoreRunner, maintenance: OHLCVMaintenanceService, downloader: HistoricalDownloadService | None=None, *, operation_locks: OHLCVDatasetOperationLocks | None=None, cache_invalidator: Callable[[MarketId], bool] | None=None) -> None

OHLCVMaintenanceApplicationService.discover(self) -> MaintenanceDiscoveryReport

OHLCVMaintenanceApplicationService.submit_deletion_plan(self, market: MarketId, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_deletion(self, plan: MaintenanceDeletionPlan, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_validation(self, market: MarketId, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_sidecar_reconstruction_plan(self, market: MarketId, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_sidecar_reconstruction(self, plan: MaintenanceSidecarReconstructionPlan, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_repair_plan(self, market: MarketId, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.submit_repair(self, plan: MaintenanceRepairPlan, *, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None) -> TaskSubmission

OHLCVMaintenanceApplicationService.cancel(self, task_id: str) -> bool
```

### src/leonardo/ohlcv/operation_locks.py

```python
OHLCVDatasetOperationLocks.__init__(self) -> None

@asynccontextmanager
async OHLCVDatasetOperationLocks.acquire(self, market: MarketId) -> AsyncIterator[None]
```

### src/leonardo/ohlcv/store.py

```python
OHLCVStore.__init__(self, root: Path) -> None

@property
OHLCVStore.root(self) -> Path

OHLCVStore.dataset_dir(self, market: MarketId) -> Path

OHLCVStore.csv_path(self, market: MarketId) -> Path

OHLCVStore.sidecar_path(self, market: MarketId) -> Path

OHLCVStore.inspect(self, market: MarketId) -> DatasetInspection

OHLCVStore.read(self, market: MarketId) -> list[Candle]

OHLCVStore.write(self, market: MarketId, candles: Iterable[Candle], *, source: str, persistence_status: str, warnings: Iterable[str]=(), lineage: dict[str, object] | None=None) -> OHLCVSidecarV1

OHLCVStore.finalize(self, market: MarketId, *, source: str, warnings: Iterable[str]=(), lineage: dict[str, object] | None=None) -> OHLCVSidecarV1

OHLCVStore.mark_repaired(self, market: MarketId, *, repair_record: dict[str, object]) -> OHLCVSidecarV1

OHLCVStore.capture_deletion_evidence(self, market: MarketId) -> DatasetDeletionEvidence

OHLCVStore.delete_dataset(self, evidence: DatasetDeletionEvidence) -> DatasetDeletionResult

OHLCVStore.reconstruct_sidecar(self, market: MarketId, *, expected_csv_size: int, expected_csv_mtime_ns: int, expected_csv_sha256: str, expected_sidecar_size: int | None, expected_sidecar_mtime_ns: int | None, expected_sidecar_sha256: str | None, reconstruction_reason: str) -> SidecarReconstructionResult

OHLCVStore.publish_validation(self, market: MarketId, *, expected_csv_size: int, expected_csv_mtime_ns: int, expected_csv_sha256: str, expected_sidecar_size: int, expected_sidecar_mtime_ns: int, expected_sidecar_sha256: str, status: str, row_count: int, first_timestamp_ms: int | None, last_timestamp_ms: int | None, warnings: Iterable[str], issue_codes: Iterable[str], error_count: int, warning_count: int, validator: str) -> ValidationPublicationResult

OHLCVStore.read_sidecar(self, market: MarketId) -> OHLCVSidecarV1

merge_idempotent(existing: Iterable[Candle], incoming: Iterable[Candle]) -> list[Candle]
```

### src/leonardo/ohlcv/validation.py

```python
@property
PreliminaryValidationReport.messages(self) -> tuple[str, ...]

@property
CanonicalValidationReport.error_count(self) -> int

@property
CanonicalValidationReport.warning_count(self) -> int

@property
CanonicalValidationReport.issue_codes(self) -> tuple[str, ...]

@property
CanonicalValidationReport.warning_messages(self) -> tuple[str, ...]

@property
CanonicalValidationReport.messages(self) -> tuple[str, ...]

PreliminaryOHLCVValidator.validate(self, store: OHLCVStore, market: MarketId) -> PreliminaryValidationReport

CanonicalOHLCVValidator.validate(self, store: OHLCVStore, market: MarketId, *, cancel_requested: Callable[[], bool] | None=None, progress_callback: Callable[[int, int | None], None] | None=None, progress_interval_rows: int=_DEFAULT_PROGRESS_INTERVAL_ROWS) -> CanonicalValidationReport
```

### src/leonardo/ohlcv/maintenance.py

```python
@property
MaintenanceValidationResult.accepted(self) -> bool

@property
MaintenanceDeletionResult.completed(self) -> bool

@property
MaintenanceSidecarReconstructionResult.accepted(self) -> bool

@property
MaintenanceRepairResult.accepted(self) -> bool

OHLCVMaintenanceService.__init__(self, store: OHLCVStore, validator: CanonicalOHLCVValidator, *, audit_log: AuditLog | None=None, actor_id: str | None=None) -> None

OHLCVMaintenanceService.discover(self) -> MaintenanceDiscoveryReport

OHLCVMaintenanceService.validate(self, market: MarketId, *, correlation_id: str | None=None, cancel_requested: Callable[[], bool] | None=None, progress_callback: Callable[[int, int | None], None] | None=None) -> MaintenanceValidationResult

OHLCVMaintenanceService.plan_deletion(self, market: MarketId, *, correlation_id: str | None=None) -> MaintenanceDeletionPlan

OHLCVMaintenanceService.delete_dataset(self, plan: MaintenanceDeletionPlan, *, correlation_id: str | None=None) -> MaintenanceDeletionResult

OHLCVMaintenanceService.plan_sidecar_reconstruction(self, market: MarketId, *, correlation_id: str | None=None) -> MaintenanceSidecarReconstructionPlan

OHLCVMaintenanceService.reconstruct_sidecar(self, plan: MaintenanceSidecarReconstructionPlan, *, correlation_id: str | None=None) -> SidecarReconstructionResult

OHLCVMaintenanceService.plan_repair(self, market: MarketId, *, correlation_id: str | None=None) -> MaintenanceRepairPlan

OHLCVMaintenanceService.assert_repair_plan_current(self, plan: MaintenanceRepairPlan) -> None

OHLCVMaintenanceService.mark_repair_completed(self, plan: MaintenanceRepairPlan, range_results: tuple[MaintenanceRepairRangeResult, ...], *, correlation_id: str | None=None) -> OHLCVSidecarV1

OHLCVMaintenanceService.build_repair_result(self, plan: MaintenanceRepairPlan, range_results: tuple[MaintenanceRepairRangeResult, ...], repaired_sidecar: OHLCVSidecarV1, validation: MaintenanceValidationResult, *, correlation_id: str | None=None) -> MaintenanceRepairResult

repair_range_result(repair_range: MaintenanceRepairRange, download_result: DownloadItemResult) -> MaintenanceRepairRangeResult
```

## 9. Executable generated-data example

This example uses three generated 1-minute rows, no exchange call and a separate historical root. It exercises the current Store, Maintenance validator, strict accepted catalog and sidecar serializer, not an invented format. Runtime UTC times and filesystem mtime are illustrative captured values, not portable constants.

The request `BYBIT / LINEAR / btc/usdt / (1m, 1m)` normalizes to `bybit / linear / BTCUSDT / (1m,)`. The generated CSV is:

```csv
ts_ms,open,high,low,close,volume
0,100.0,102.0,99.0,101.0,10.0
60000,100.0,102.0,99.0,101.0,10.0
120000,100.0,102.0,99.0,101.0,10.0
```

The page-write state `partial/unknown` is rejected by the accepted catalog. Finalization changes it to `committed/unknown`, still rejected. Canonical Maintenance validation publishes `committed/ok`; the catalog then accepts it without changing CSV bytes. A second identical validation is accepted with `publication_changed=False` and preserves exact sidecar bytes/mtime.

Complete resulting sidecar (source is explicitly a generated fixture):

```json
{
  "created_at_utc": "2026-10-09T16:38:18.309239+00:00",
  "file_sha256": "ac198f32688b4bece65682f95d66e0b0b688d42c187863d6bd2a3d5d952e4526",
  "first_timestamp_ms": 0,
  "last_timestamp_ms": 120000,
  "lineage": {
    "canonical_validation": {
      "error_count": 0,
      "issue_codes": [],
      "status": "ok",
      "validator": "canonical_ohlcv_v1",
      "warning_count": 0
    },
    "file_mtime_ns": 1791563898307240700,
    "file_size": 136
  },
  "market_id": {
    "exchange": "bybit",
    "market_type": "linear",
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  },
  "persistence_status": "committed",
  "row_count": 3,
  "schema_version": "1.0",
  "source": "documentation_fixture",
  "updated_at_utc": "2026-10-09T16:38:18.331631+00:00",
  "validation_status": "ok",
  "warnings": []
}
```

The example's source, output and checks are retained in `20261009_Connection_Documentation/verify_example.py`, `generated_example/` and `EXAMPLE_VALIDATION.json` under the canonical external evidence directory. It is one offline documentation example, not a new full-suite or native acceptance run.
