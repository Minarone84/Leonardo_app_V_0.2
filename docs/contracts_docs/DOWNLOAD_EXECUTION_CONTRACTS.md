# Download Execution Contracts

This document defines the first Leonardo V2 Download Execution planning and
read-model contracts. The contracts describe future orchestration state only.
They do not implement execution, adapters, network transport, WebSocket
transport, file output, Runtime Manager controls, GUI behavior, Data Manager
integration, dependency changes, app entry points, or old-code import.

## Ownership Model

Future real Download Data execution should be owned by Connection Suite
Download Manager services and coordinated through Core runtime primitives.
Core must not own Download Manager domain behavior and must not import concrete
provider, storage, or smoke execution implementations.

Connection Suite Download Manager services remain the owner of stored request
intent, structural preflight state, item read models, and aggregate Download
Manager summaries. They must not own GUI behavior, and GUI must not own
download planning, provider calls, or storage writes.

The future execution service should coordinate existing owners:

- Connection Suite Download Manager read models for request and item state.
- `OperationRegistry` for semantic user-visible lifecycle.
- `TaskManager` for async supervision.
- `ConnectionRegistry` for provider or client readiness visibility.
- `AuditLog` for runtime history and execution facts.
- Adapter/provider boundaries for source-specific data fetching.
- Storage/output services for write plans and later file output.

## OperationRegistry Relationship

The first safe integration point is one operation per submitted request. Item
models may reference the operation identifier for traceability, but item-level
operations should wait until queueing, retries, partial completion, and batch
semantics are explicitly designed.

OHLCV Maintenance may later use a separate maintenance workflow operation, but
that remains blocked until storage writers, metadata sidecars, validation, and
repair policies exist.

## TaskManager Relationship

The first safe execution skeleton is one parent async task per request
execution. Item work should initially be tracked inside the request task through
Download Manager item/progress read models. One task per item and future queue
workers require a later concurrency and cancellation audit.

GUI code must not call `TaskManager` directly.

## ProcessManager Policy

Historical Download Data execution should not use `ProcessManager` by default.
The first implementation should run in-process under `TaskManager` supervision.
`ProcessManager` is reserved for later explicitly external workers after a
separate process-execution audit.

## ConnectionRegistry And WebSocket Policy

`ConnectionRegistry` exposes connection identity and readiness state. It does
not own adapter execution, client handles, callbacks, or transport objects.

REST-style historical downloads may need HTTP/provider readiness rather than
WebSocket channels. WebSocket tracking is future-compatible for live or
streaming data, but it is not required for the first historical download path
unless a provider explicitly requires it.

## Adapter And Provider Boundary

Future adapters should own provider-specific responsibilities:

- supported markets and timeframes;
- source symbol normalization;
- canonical timeframe to API interval mapping;
- available range discovery;
- OHLCV page or chunk fetching;
- rate and page limit reporting;
- provider error classification.

Adapters must not own GUI behavior, Runtime Manager state, Data Manager
cataloging, or storage policy decisions.

## Layered Preflight Model

Execution preflight should evolve in layers:

1. Structural preflight.
2. Source/catalog capability preflight.
3. Connection readiness preflight.
4. Storage/output path preflight.
5. Conflict-policy preflight.
6. Execution-cost and rate-limit estimate.

`DownloadPreflightLayerResult` records the layer, status, continuation flag,
issues, and metadata for each stage.

## Progress Model

`DownloadExecutionProgress` represents request-level progress. It supports:

- current execution phase;
- total, completed, failed, skipped, and running item counts;
- current item, symbol, and timeframe;
- downloaded rows and candles;
- fetched page count;
- percent complete;
- display message;
- update timestamp;
- metadata for future throttled display or provider notes.

Progress updates should be emitted at meaningful milestones. Runtime Manager
visibility should remain read-only and should not receive every low-level
provider event.

## Output Reference Policy

Execution outputs should use logical dataset refs from the accepted OHLCV
storage policy, such as:

```text
dataset://ohlcv/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/basis=raw
```

`DownloadExecutionOutputRef` may also carry relative value and sidecar paths for
planning and read-model display:

```text
ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/candles.csv
ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/candles.meta.json
```

The default output metadata stance is:

- value artifact: `candles.csv`;
- sidecar: `candles.meta.json`;
- storage format: `csv`;
- validation status: `unknown`;
- quality validation status: `not_validated`.

Absolute paths are not part of these contracts. File writing and metadata
sidecar creation remain future storage-service work.

## Cancellation And Partial Persistence

Queued cancellation should eventually mark the request/items cancelled without
outputs.

Running cancellation should use cooperative `TaskManager` cancellation when the
execution manager is implemented. The first safe storage policy should avoid
committed partial files. Later partial persistence must be explicit and must
stamp metadata as partial, `unknown`, and `not_validated`.

## Error Taxonomy

`DownloadExecutionErrorCategory` defines the first execution error taxonomy:

- validation;
- capability;
- connection unavailable;
- rate limited;
- provider;
- storage;
- cancellation;
- partial completion;
- internal;
- unknown.

Errors are read-model facts. Recovery, retry, and user controls are future
execution-manager behavior.

## Snapshot Contract

`DownloadExecutionSnapshot` aggregates:

- plan;
- layered preflight results;
- optional estimate;
- optional progress;
- output refs;
- errors;
- metadata.

The snapshot is immutable and does not execute work.

## Explicitly Out Of Scope

This phase does not add:

- future Connection Suite execution service;
- adapter interfaces;
- downloader execution;
- storage writers;
- file output;
- TaskManager wiring;
- OperationRegistry wiring;
- ConnectionRegistry wiring;
- ProcessManager usage;
- Runtime Manager visibility or controls;
- GUI behavior;
- Data Manager integration;
- dependency changes;
- CLI, app entry, or installer behavior;
- old-code import or copy.
