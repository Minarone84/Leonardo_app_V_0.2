# Download Data Boundary Contracts

`leonardo.contracts.download_data_boundary` defines the first immutable
Download Data boundary vocabulary. The contracts describe selection, selection
recap, preflight, process confirmation vocabulary, progress read models,
completion recap, output references, and partial persistence state.

This phase is contract-only. It does not implement GUI behavior, downloader
execution, adapters, provider API calls, network transport, websocket or
subscription behavior, storage writes, cancellation, Runtime Manager controls,
Object Map helpers, Data Manager integration, OHLCV Maintenance execution, app
startup changes, concrete suites, or old-code import.

## Boundary Classification

Download Data is a Core-routed workflow/module, not a top-level suite.

Download Data is not Provider/Connection. Provider/Connection may later supply
capability facts, range facts, readiness facts, and provider-specific
constraints. It must not receive Download Data ownership.

Download Data is not the storage/data layer. Core routes and supervises runtime
when execution exists, but Core does not own persisted OHLCV truth.

The storage/data layer owns persisted OHLCV truth:

- OHLCV CSV value truth;
- OHLCV metadata sidecar truth;
- file identity and path policy;
- first and last timestamp metadata;
- row counts;
- partial persistence metadata;
- accepted/loadable dataset state after validation and maintenance.

The GUI owns selection and display only. It may collect user intent and present
recaps, but it must not own provider capability truth, file persistence,
validation, runtime execution, or accepted dataset state.

## Selection Vocabulary

Selection begins empty. No default selections are invented by the contracts.

The selection draft may represent incomplete user intent:

- exchange is unset;
- market type is unset;
- symbol is unset;
- selected timeframes are empty.

The machine field name is `symbol`. GUI surfaces may label it as Asset or Asset
name, but contract fields use `symbol`.

Timeframe values are selected values only. Available timeframe options must come
from exchange/provider capability metadata, not hardcoded GUI truth.

The selection summary is a table-like recap of exchange, market type, symbol,
selected timeframes, item count, warnings, and blockers.

## Preflight Vocabulary

Preflight rows describe one selected exchange, market type, symbol, and
timeframe. The preflight mode is one of:

- `new_file`;
- `update_existing`;
- `already_current`;
- `blocked`;
- `unknown`.

Preflight may later combine local storage state, provider capability/range facts,
and workload estimates. These contracts only describe read models. They do not
read local files, call provider APIs, or write output.

Process Download confirmation is represented as boundary vocabulary only.
Execution remains future work.

## Old Leonardo Storage Naming Policy

The boundary preserves the old Leonardo OHLCV storage target shape:

```text
data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv
data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.meta.json
```

Canonical artifact identity:

```text
artifact_id = ohlcv__candles
```

Canonical file names:

```text
candles.csv
candles.meta.json
```

`DownloadDataStorageTargetRef` and `DownloadDataOutputRef` expose these paths as
relative POSIX read-model strings. They do not create directories and do not
write files.

## Progress Read Models

Progress contracts support future table-like display:

- total workflow status;
- operation and task references when later routed through Core runtime;
- per-timeframe item status;
- completed and total steps;
- downloaded bars;
- first and last timestamp facts;
- bounded message rows.

Progress messages are short read-model messages. They must not contain raw API
responses, raw payloads, handles, secrets, or large dumps.

## Final Recap Read Models

Completion contracts support final table-like recap per timeframe:

- exchange;
- market type;
- symbol;
- timeframe;
- preflight mode;
- status;
- bars downloaded;
- first and last timestamps;
- UTC display fields;
- CSV path;
- metadata sidecar path;
- persistence status;
- validation/loadable/accepted state;
- warnings and errors.

## Partial Persistence Policy

Partial persistence is explicitly not accepted clean data.

The following distinctions are mandatory:

- partial file is not an accepted dataset;
- partial file is not a validated dataset;
- partial file is not a loadable dataset;
- partial file is not clean data.

In these contracts, partial persistence is not accepted, loadable, validated, or
clean data. Put another way: partial persistence is not accepted, loadable,
validated, or clean data. Partial output exists to support later recovery or
repair workflows.

Policy sentence: partial persistence is not accepted, loadable, validated, or clean data.

OHLCV Maintenance handles later repair, validation, metadata rebuild, acceptance
stamping, and loadability decisions. Download Data may report partial output but
must not mark that output accepted or loadable.

## Metadata Safety

Contract metadata is compact and read-only. Metadata keys must not contain
credential, credentials, token, secret, password, api_key, authorization, bearer,
client, socket, payload, raw_payload, or response.

The contracts carry no raw provider handles, API response bodies, socket handles,
clients, credential material, or large provider payloads.

## Explicitly Out Of Scope

This boundary phase does not add:

- downloader execution;
- adapter or exchange API behavior;
- network calls;
- websocket or subscription work;
- storage writes;
- cancellation behavior;
- Runtime Manager controls;
- Runtime Manager summaries;
- Object Map helpers;
- Object Map service changes;
- provider registries;
- discovery or filesystem scanning;
- GUI behavior or GUI source changes;
- Data Manager integration;
- OHLCV Maintenance implementation;
- old Leonardo code import;
- app startup changes;
- concrete suite implementation.

## Validation

The contract is covered by:

```text
tests/contracts_test/test_download_data_boundary_contracts.py
```
