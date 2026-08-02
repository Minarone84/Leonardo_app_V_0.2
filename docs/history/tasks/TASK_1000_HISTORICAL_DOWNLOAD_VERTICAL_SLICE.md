# Task 1000: Historical Download Vertical Slice

## Task identity

```text
Task ID: 1000
Task name: Historical Download Vertical Slice
Implementation agent: Rick-authorised direct implementation
Parent workplan: Market Access and Historical Ingestion
Decision entropy: Frozen for task
Baseline: Task 0048 Light V2 reset package
```

## Objective

Adapt the proven old Leonardo Historical Download Manager workflow into the
Light V2 architecture and the existing GUI shells without modifying Research
Suite implementation files.

## Included scope

- explicit Core boundary for blocking work;
- provider factory registry and Bybit historical REST adapter;
- current Bybit standard-kline capability limited to spot, linear and inverse;
- provider-owned market and timeframe capabilities;
- canonical market identity normalization;
- non-mutating preflight;
- new, update-latest, custom-range and up-to-date planning modes;
- fixed-timeframe workload estimates and indeterminate month estimates;
- sequential multi-timeframe execution;
- backward cursor pagination, retry and cursor-stall protection;
- provider-derived latest-closed-candle planning and open-candle filtering, including month candles;
- atomic CSV replacement and recoverable sidecar writes;
- page-level partial persistence;
- strict `OHLCVSidecarV1` admission;
- preliminary OHLCV checks that leave canonical validation `unknown`;
- exact cancellation reporting for no-write, partial and committed persistence states;
- thin Qt presenter and queued callback dispatch;
- 250 ms GUI-only progress coalescing;
- wiring of the existing manager, preflight and task shells.

## Excluded scope

- OHLCV Maintenance acceptance and repair;
- dataset loading for Research Suite;
- real-time websockets;
- credential management;
- live or paper trading;
- deletion of unused GUI widgets;
- Research Suite source changes;
- Git commits, merges or branch writes.

## Canonical authorities

| Truth or state | Authority |
|---|---|
| Application composition | `LeonardoApp` |
| Task lifecycle | `TaskManager` |
| Blocking execution boundary | `CoreRunner` |
| Provider semantics | Connection Area adapter |
| Coarse connection state | `ConnectionRegistry` |
| Market identity | `MarketId` canonicalization policy |
| Physical OHLCV writes | `OHLCVStore` |
| Durable metadata | `OHLCVSidecarV1` |
| Canonical OHLCV acceptance | Future OHLCV Maintenance validator |
| GUI presentation state | Existing Qt shells and presenter |

## Old-code classification

### Reused as behavior

- field normalization and provider capability flow;
- checkbox timeframe selection;
- read-only preflight;
- sequential batch execution;
- backward paging and overlap merge;
- preliminary checks;
- partial persistence and cancellation facts;
- progress coalescing and final recap behavior.

### Adapted

- old exchange registry to a local Connection Area provider registry;
- old downloader to `HistoricalDownloadService`;
- old CSV store to `OHLCVStore` plus `OHLCVSidecarV1`;
- audit-event polling to queued task callbacks;
- old window orchestration to a thin presenter.

### Rejected

- `CoreBridge` as the workflow owner;
- audit history as a GUI message bus;
- GUI-owned storage or provider logic;
- Heavy V2 contracts, registries and metadata mirrors;
- automatic acceptance after download;
- obsolete Bybit options support on the standard `/v5/market/kline` endpoint.
- default page limit of 200 in the new shell.

## User workflow

```text
Select provider, market, symbol, bounds and timeframes
→ validate and normalize fields
→ submit non-mutating preflight
→ review work plan and blockers
→ explicitly confirm
→ submit Core task
→ execute timeframes sequentially
→ persist each page atomically
→ report progress and cancellation honestly
→ run preliminary checks
→ leave canonical validation unknown
→ display final recap
```

## Finish line

Task 1000 is implementation-complete when automated validation passes, no
Research Suite source file changes are present, generated caches are excluded,
and the package contains a merge guide and independent evidence.

GUI visual acceptance remains required on a workstation with PySide6.
