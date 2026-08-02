# Leonardo V2 Connection Suite and Historical Data Workflow

**Status:** Current operational specification
**Updated:** 2026-08-02
**Primary implementation:** `src/leonardo/connection/`,
`src/leonardo/ohlcv/`, and the related GUI presenters/windows

## 1. Purpose and current status

The Connection Area owns external provider capability and wire behavior.

The current production capability is deliberately narrow:

```text
Bybit public historical REST
→ historical OHLCV preflight and download
→ canonical OHLCV persistence
→ OHLCV validation and maintenance
→ accepted historical datasets for Research
```

The historical workflow is implemented and Core-supervised.

The top-level `ConnectionSuiteWindow` is still an honest presentation shell. Its
provider, websocket, and download-overview tables are not connected to live
backend projections. The real user workflow is exposed through:

```text
Connection Suite
→ Historical Download Manager

Main Window or Download Manager
→ OHLCV Maintenance
```

This distinction is intentional and must remain visible in documentation. The
existence of a dashboard-shaped window does not magically summon account APIs,
websockets, or a trading gateway from the void.

## 2. Area ownership

| Concern | Canonical authority |
|---|---|
| Provider factory registration | `ProviderRegistry` |
| Provider capabilities and wire behavior | Provider adapter |
| Provider session coordination | `ConnectionApplicationService` |
| Coarse runtime connection status | Core `ConnectionRegistry` |
| Historical download planning/execution | `HistoricalDownloadService` |
| Task submission/progress/cancellation | `HistoricalDownloadApplicationService` + Core |
| OHLCV persistence | `OHLCVStore` |
| Dataset mutation exclusion | `OHLCVDatasetOperationLocks` |
| Canonical OHLCV validation | `CanonicalOHLCVValidator` / maintenance service |
| Research admission | `AcceptedDatasetCatalog` |
| GUI state and presentation | GUI windows and presenters |

Connection owns provider semantics. Core only tracks generic connection state.
OHLCV owns historical persistence and validation truth.

## 3. Current architecture

```text
Historical Download Manager
→ HistoricalDownloadPresenter
→ ConnectionApplicationService       capability queries / provider sessions
→ HistoricalDownloadApplicationService
→ CoreRunner / TaskManager
→ HistoricalDownloadService
→ BybitHistoricalProvider
→ OHLCVStore
→ preliminary validation and sidecar evidence
```

For maintenance:

```text
OHLCV Maintenance Window
→ OhlcvMaintenancePresenter
→ OHLCVMaintenanceApplicationService
→ CoreRunner / TaskManager
→ OHLCVMaintenanceService
→ OHLCVStore + canonical validator
→ AcceptedDatasetCatalog / Research cache invalidation
```

No GUI window calls provider methods, writes files, or owns download planning.

## 4. Provider registry

`ProviderRegistry` stores factories rather than live provider instances.

Properties:

- provider names are canonical lowercase strings;
- duplicate provider registration is rejected;
- each `create()` call returns a fresh provider adapter;
- returned objects must satisfy the owner-local
  `HistoricalOHLCVProvider` protocol;
- capability queries may instantiate an adapter but do not open a network
  session.

The default registry currently contains one provider:

```text
bybit
```

## 5. Historical provider boundary

`HistoricalOHLCVProvider` defines the current Connection-to-OHLCV boundary:

```text
name
supported_markets()
supported_timeframes(market)
max_historical_ohlcv_limit(market)
open()
close()
get_server_time_ms()
oldest_historical_ohlcv_ts_ms(...)
fetch_ohlcv_historical(...)
```

Provider candles are normalized into:

```text
timestamp milliseconds
open
high
low
close
volume
closed/open state
```

Provider adapters own exchange-specific normalization, endpoint selection,
request parameters, response parsing, rate limits, retry classification, and
wire errors.

## 6. Bybit historical adapter

### 6.1 Endpoint and scope

The current default adapter uses Bybit v5 public REST endpoints. Mainnet is the
default; a testnet base URL can be selected when constructing the adapter.

Implemented markets:

```text
spot
linear
inverse
```

Options are deliberately rejected by the standard kline adapter.

Implemented timeframes:

```text
1m  3m  5m  15m  30m
1h  2h  4h  6h   12h
1d  1w  1M
```

`60m` is accepted as an input alias and normalized to `1h`.

Maximum page limit:

```text
1000 candles
```

### 6.2 Session and pacing

The adapter owns one `aiohttp.ClientSession` per provider instance.

Requests are serialized through an async lock and paced with a minimum interval
of 0.20 seconds.

### 6.3 Retry behavior

The Bybit adapter performs at most four attempts for retryable transport,
server, and rate-limit failures.

It uses Bybit rate-limit reset headers when available and bounds rate-limit
sleep to ten seconds.

Permanent API errors are not retried.

Failures are exposed through `HistoricalProviderRequestError` with:

```text
provider
operation
retryable
attempts_exhausted
HTTP status, when available
provider error code, when available
```

This prevents the outer downloader from blindly retrying a permanent error or
replaying a request after the provider adapter has already exhausted its own
bounded policy.

Cancellation during provider retry sleep propagates normally.

### 6.4 Candle closure

The adapter marks candles as closed or open using timeframe boundaries and
server-time evidence. The current monthly candle is therefore not treated as a
completed historical candle merely because an API returned a row for it.

## 7. ConnectionApplicationService

The application service provides:

- provider names;
- supported markets;
- supported timeframes in canonical order;
- async provider-session context management.

### 7.1 Capability queries

Capability queries use adapter-owned static knowledge and do not open network
sessions.

### 7.2 Provider sessions

A session:

```text
creates a fresh provider adapter
→ ensures a coarse ConnectionRegistry record exists
→ marks connecting
→ opens the provider
→ marks connected
→ yields the provider
→ closes the provider
→ marks disconnected when the last active session closes
```

The canonical runtime connection ID is currently:

```text
connection.bybit.historical_rest
```

Nested or concurrent sessions for the same provider are reference-counted. The
connection remains `connected` until the final active session closes.

If one of several concurrent sessions fails, the coarse state becomes
`degraded`. If the only session fails, it becomes `failed`.

The runtime record is a summary only. It does not own request planning, retry
rules, or provider credentials.

## 8. Historical Download Manager

The Historical Download Manager is the real GUI entry point for current
Connection functionality.

It supports:

- provider selection;
- market type selection;
- canonical symbol input;
- one or more timeframes;
- optional start timestamp;
- optional end timestamp;
- optional page limit;
- select-all and clear-timeframe controls;
- preflight review;
- download confirmation;
- task progress and cancellation;
- result recap;
- navigation to OHLCV Maintenance.

The window owns only fields, validation-friendly presentation state, buttons,
tables, and status text.

`HistoricalDownloadPresenter` owns GUI workflow coordination and dispatches Core
callbacks back to Qt.

## 9. Download preflight

Preflight runs as a Core task with operation metadata:

```text
ohlcv_preflight
```

For every selected timeframe it inspects:

- canonical `MarketId`;
- current CSV and metadata paths;
- whether CSV and metadata exist;
- sidecar validity;
- local row count and timestamp range;
- local state issues;
- exchange oldest/youngest available timestamps;
- planned start and end;
- expected bars and pages;
- provider page limit;
- whether the dataset is already current;
- whether execution is safe.

A new download without an explicit range requires the provider to resolve the
oldest available timestamp. If that lower bound cannot be established,
preflight blocks execution rather than inventing a convenient historical start.

## 10. Download planning modes

The planner currently produces three user-relevant modes:

### `new_download`

Used when no local rows exist and the user did not provide a custom boundary.
The downloader attempts to discover the oldest available provider timestamp and
runs forward to the latest closed candle.

### `update_latest`

Used when local rows exist and no explicit range is provided. The last local
timestamp becomes the starting point and the provider's latest closed candle
becomes the target.

If the local dataset is already current, the plan reports `up_to_date` with zero
expected bars/pages.

### `custom_range`

Used when the user provides a start, end, or both.

The requested limit is capped by the provider's maximum page limit.

## 11. Download execution

Download execution runs as a Core task with operation metadata:

```text
ohlcv_download
```

For a multi-timeframe batch, timeframes are processed under one provider
session. Each target dataset uses its own canonical `MarketId` and operation
lock.

Execution provides:

- batch and timeframe progress;
- page progress;
- bounded request timeout;
- downloader-level retry only when the provider error remains retryable and its
  adapter-level attempts are not already exhausted;
- cancellation;
- idempotent merge with existing candles;
- canonical sort/deduplication;
- preliminary validation;
- atomic OHLCV/sidecar persistence through `OHLCVStore`;
- audit evidence with correlation identity.

Downloader constants currently include:

```text
30 second request timeout
3 outer downloader attempts
1 second linear retry backoff
10,000 page safety ceiling
```

Provider-level retry happens inside the Bybit adapter. The outer downloader does
not multiply retries after an adapter reports `attempts_exhausted=True`.

## 12. Cancellation semantics

Historical provider calls and download orchestration are asynchronous and
respond to normal task cancellation.

Completed timeframes remain reported in the cancellation recap; unfinished
ones remain explicit.

Persistence-sensitive maintenance operations use additional cancellation fences
so cancellation cannot publish a half-completed canonical mutation.

## 13. OHLCV persistence and Research acceptance

A successful download writes canonical OHLCV data and sidecar evidence, then
reports a **preliminary** validation result.

Research does not accept a dataset merely because a CSV exists.

Canonical Research admission requires the dataset sidecar to carry:

```text
validation_status = "ok"
```

The user flow is therefore:

```text
download or update OHLCV
→ run canonical validation in OHLCV Maintenance
→ dataset appears in the accepted Research catalog
```

Updating a dataset changes its fingerprint and invalidates prior Research cache
evidence. The OHLCV maintenance application service calls
`HistoricalDatasetLoader.invalidate()` after accepted mutation operations.

## 14. OHLCV Maintenance boundary

OHLCV Maintenance is not provider wire logic. It is an OHLCV Area workflow that
uses the same Core and store authorities.

Implemented operations:

```text
discovery
validation
deletion plan
delete
sidecar reconstruction plan
sidecar reconstruction
repair plan
repair
```

Corresponding task metadata includes:

```text
ohlcv_validate
ohlcv_deletion_plan
ohlcv_delete
ohlcv_sidecar_reconstruction_plan
ohlcv_sidecar_reconstruct
ohlcv_repair_plan
ohlcv_repair
```

Dataset mutation is serialized by `OHLCVDatasetOperationLocks` so download,
repair, delete, or reconstruction cannot independently write the same
`MarketId` at the same time.

## 15. Runtime and audit integration

### TaskManager

Preflight, download, validation, repair, reconstruction, and deletion appear as
Tasks in Runtime Manager with progress, terminal status, errors, correlation
identity, and operation metadata.

### ConnectionRegistry

Provider sessions create/update the coarse historical REST connection row.

### ProcessManager

No child operating-system process is launched. Historical work therefore does
not create ProcessManager rows.

### WindowRegistry

The following long-lived windows are tracked by GUI composition:

```text
connection_suite.home.window
historical_download_manager.window
ohlcv_maintenance.window
```

Preflight and task windows are owned by the retained Historical Download
presenter. They are workflow dialogs rather than separate provider authorities.

### Audit

Download batch start, completion, cancellation, and failure emit structured
audit evidence. Store and maintenance operations also preserve their own
canonical audit details.

## 16. Top-level Connection Suite shell

`ConnectionSuiteWindow` currently provides:

- stable window and widget IDs;
- provider/account/API table shell;
- websocket/connection table shell;
- historical-download overview shell;
- activity log;
- Refresh and Clear Log presentation actions;
- an action that opens Historical Download Manager through GUI composition.

It currently does **not**:

- bind live `ConnectionRegistry` rows into its tables;
- show real provider account state;
- manage credentials;
- establish persistent connections;
- subscribe to websocket channels;
- show live download task summaries;
- perform provider or OHLCV work directly.

Its empty-state text is therefore honest and should remain so until a bounded
Connection dashboard task wires real read models.

## 17. Not implemented

The current Connection Area does not implement:

- exchange credentials or private account APIs;
- provider account management;
- websocket market-data subscriptions;
- persistent live connection management;
- order or trading gateways;
- reconnect policy for live feeds;
- multiple production providers beyond Bybit historical REST;
- live binding of the Connection Suite dashboard tables;
- provider-specific GUI business logic.

These are future vertical workflows, not hidden capabilities implied by empty
widgets.

## 18. Primary source map

```text
src/leonardo/connection/provider.py
src/leonardo/connection/registry.py
src/leonardo/connection/service.py
src/leonardo/connection/bybit.py
src/leonardo/ohlcv/models.py
src/leonardo/ohlcv/download_service.py
src/leonardo/ohlcv/application.py
src/leonardo/ohlcv/store.py
src/leonardo/ohlcv/maintenance.py
src/leonardo/ohlcv/validation.py
src/leonardo/ohlcv/operation_locks.py
src/leonardo/gui/windows/connection_suite_window.py
src/leonardo/gui/windows/historical_download_manager_window.py
src/leonardo/gui/presenters/historical_download_presenter.py
src/leonardo/gui/windows/ohlcv_maintenance_window.py
src/leonardo/gui/presenters/ohlcv_maintenance_presenter.py
src/leonardo/gui/composition.py
```

Primary tests:

```text
tests/connection_test/test_provider_registry.py
tests/connection_test/test_bybit_historical_provider.py
tests/ohlcv_test/test_download_vertical.py
tests/ohlcv_test/test_download_acceptance_workflow.py
tests/ohlcv_test/test_store_and_sidecar.py
tests/ohlcv_test/test_maintenance_validation.py
tests/ohlcv_test/test_maintenance_repair.py
tests/ohlcv_test/test_maintenance_sidecar_reconstruction.py
tests/ohlcv_test/test_maintenance_deletion.py
tests/ohlcv_test/test_maintenance_performance.py
tests/gui_test/test_historical_download_wiring_static.py
tests/gui_test/test_download_maintenance_research_workflow.py
tests/gui_test/test_ohlcv_maintenance_presenter.py
```
