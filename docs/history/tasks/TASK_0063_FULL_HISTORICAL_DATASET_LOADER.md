# Task 0063: Full Historical Dataset Loader

## Task identity

```text
Task ID: 0063
Task name: Full Historical Dataset Loader
Parent workplan: Leonardo Light V2 Research Suite Rebuild
Execution owner: Rick
Architecture status: Frozen for task
Decision entropy: Low
```

## Objective

Load one canonically accepted historical OHLCV dataset into a shared immutable
Research read model without filesystem work on the GUI thread.

## Canonical authorities

| Truth | Authority |
|---|---|
| Market identity | `MarketId` and canonicalization policy |
| OHLCV physical paths and writes | `OHLCVStore` |
| Dataset acceptance | `AcceptedDatasetCatalog` projecting canonical sidecar evidence |
| Full Research dataset read model and cache | `HistoricalDatasetLoader` |
| Long-running task lifecycle | `TaskManager` through `CoreRunner` |

The loader does not validate or repair OHLCV canonically. It defensively verifies
that parsed bytes still match the already accepted sidecar and refuses any
inconsistency.

## Included scope

- strict canonical `MarketId` input;
- exact OHLCV CSV header and numeric parsing;
- finite numeric values;
- strictly increasing unique timestamps;
- OHLC range consistency and non-negative volume;
- sidecar row-count and time-range verification;
- SHA-256 verification while parsing;
- CSV and sidecar change detection during loading;
- immutable tuple-backed full-dataset model;
- bounded shared dataset cache;
- per-dataset load serialization;
- cooperative cancellation before cache publication;
- Core worker execution, progress, result and cancellation;
- composition through `LeonardoApp`.

## Excluded scope

- resident slicing;
- chart sessions and viewport state;
- Qt chart rendering;
- dataset validation, repair or acceptance mutation;
- Financial Tool calculations;
- Research GUI changes.

## Old-code comparison

Preserved behavior:

- complete OHLCV is loaded for later full-dataset calculations;
- accepted dataset evidence is rechecked before loading;
- timestamps remain canonical chart alignment truth;
- loaded data may be shared between chart sessions.

Improved behavior:

- no legacy `DatasetId`;
- no pandas/DataFrame construction during base loading;
- no partially unsorted or duplicate timestamps;
- no shallow mutable column lists;
- no cache return that bypasses current acceptance evidence;
- loading runs in the bounded Core worker pool;
- cancellation prevents cache publication.

Deferred to Task 0064:

- resident slice derivation and resident cache.
