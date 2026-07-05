# OHLCV Storage Policy

This document defines the first Leonardo V2 OHLCV naming and storage policy.
It is a contract policy only. It does not implement file writing, downloader
execution, adapters, network transport, Runtime Manager controls, Data Manager
integration, or old-code import.

## Legacy Preservation Summary

The V2 policy preserves these legacy-compatible principles:

- `candles.csv` is the candle value artifact.
- `candles.meta.json` is the adjacent metadata sidecar.
- The value artifact and sidecar have separate responsibilities.
- Newly downloaded OHLCV starts with validation status `unknown`.
- Newly downloaded OHLCV starts with quality validation status
  `not_validated`.
- Accepted/loadable validation statuses are `ok` and `modified`.
- Blocked states include `unknown`, `not_validated`, `warning`, `error`,
  missing metadata, unreadable metadata, metadata mismatch, stale fingerprints,
  missing validation fingerprints, and missing value artifacts.
- `modified` means the dataset is accepted/loadable after documented source
  correction, but it is not raw exchange truth.
- OHLCV Maintenance owns validation, repair, metadata rebuild, source
  correction, and acceptance stamping.
- GUI does not parse CSV, write metadata, own validation rules, own adapter
  truth, or execute downloads directly.
- Adapter and capability layers own exchange-specific aliases, API interval
  mappings, page/request limits, range discovery, and transport specifics.

No old Leonardo source is copied or imported by this policy.

## Dataset Identity

An OHLCV dataset is uniquely identified by:

- `data_type`: `ohlcv`
- `schema_version`: `v1`
- `provider`
- `market`
- `symbol`
- `timeframe`
- `price_basis`: default `raw`

Date coverage is not part of dataset identity. Coverage belongs in metadata and
future chunk or partition inventory.

Optional identity metadata may include source/native symbol, base asset, and
quote asset. The source symbol should preserve the adapter/provider-visible
symbol even when the filesystem path uses an encoded safe segment.

## Normalization Rules

Provider and market values use lowercase ASCII-safe path segments. Unsupported
characters are encoded deterministically instead of silently stripped.

Symbols preserve their canonical/source representation in the identity model.
Filesystem paths use a separate encoded symbol segment so collision-sensitive
symbols such as `BTCUSDT`, `BTC/USDT`, `BTC:USDT`, and `BTC USDT` do not collapse
to the same path.

Timeframes use lowercase canonical tokens such as `1m`, `5m`, `1h`, and `1d`.
Date path segments, when partitioning is introduced later, use UTC compact
forms such as `YYYY`, `MM`, and optionally `DD`.

## Folder Structure

The first V2 storage policy uses a legacy-compatible relative shape:

```text
ohlcv/raw/v1/provider=<provider>/market=<market>/symbol=<symbol_slug>/timeframe=<timeframe>/candles.csv
ohlcv/raw/v1/provider=<provider>/market=<market>/symbol=<symbol_slug>/timeframe=<timeframe>/candles.meta.json
```

For Binance spot BTCUSDT 1m data, the relative dataset directory is:

```text
ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m
```

Future partition-aware storage may use:

```text
ohlcv/raw/v1/provider=<provider>/market=<market>/symbol=<symbol_slug>/timeframe=<timeframe>/data/year=<YYYY>/month=<MM>/candles.csv
ohlcv/raw/v1/provider=<provider>/market=<market>/symbol=<symbol_slug>/timeframe=<timeframe>/data/year=<YYYY>/month=<MM>/candles.meta.json
```

Partitioning is declared as a future-compatible path policy. This phase does not
write partitioned files.

## File Naming Convention

Use same-stem legacy-compatible artifacts:

- `candles.csv`
- `candles.meta.json`

The folder path carries dataset identity. File names do not repeat provider,
market, symbol, timeframe, or date coverage.

## Logical Dataset Refs

Download results should prefer logical dataset refs over absolute filesystem
paths:

```text
dataset://ohlcv/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/basis=raw
```

Refs must be deterministic, must not contain absolute paths, must not include
date coverage, must use normalized identity segments, and must include basis.

## Value Artifact And Metadata Sidecar

`candles.csv` is the candle value truth. It contains OHLCV rows only.

`candles.meta.json` is the metadata, lineage, fingerprint, quality,
validation, and loadability truth. The sidecar should eventually include:

- unique artifact identity
- data type
- schema version
- provider
- market
- symbol
- source/native symbol
- timeframe
- price basis
- CSV relative path
- metadata relative path
- first timestamp
- last timestamp
- row/candle count
- UTC display timestamps
- optional Europe/Rome display timestamps
- column metadata
- last download timestamp
- last request ID
- operation ID when operations exist
- fingerprint/checksum information
- lineage
- source correction provenance
- validation metadata
- quality metadata
- errors/warnings
- partition/chunk inventory if partitioning is introduced

Sidecars consume contract, naming, and specification metadata. They must not
invent tool behavior, compute logic, render defaults, or naming templates.

## Validation And Loadability Status

Default downloaded metadata:

- `validation.status = "unknown"`
- `quality.validation_status = "not_validated"`

Accepted/loadable validation statuses:

- `ok`
- `modified`

Blocked/not-loadable statuses:

- `unknown`
- `not_validated`
- `warning`
- `error`

Missing metadata, unreadable metadata, metadata mismatch, stale fingerprints,
missing validation fingerprints, and missing CSV are blocked by future
storage/metadata services. They are not represented as path-helper states in
this phase.

## Storage Format Strategy

The declared storage formats are:

- `csv`
- `parquet`

The default compatibility format is `csv`. The future target format is
`parquet`, but Parquet requires explicit dependency and storage-engine approval
before any writer is implemented.

This phase does not add `pyarrow`, `fastparquet`, or other dependencies. It does
not implement CSV or Parquet writing.

## Conflict Policy Semantics

Future write behavior should interpret conflict policies as:

- `skip_existing`: do not write if the target dataset or chunk exists.
- `overwrite`: atomically replace the selected dataset or chunk after validating
  new data.
- `append`: add only candles strictly after the current latest timestamp; reject
  overlaps.
- `merge`: combine existing and new rows, deduplicate by timestamp, and preserve
  sorted order.
- `repair_gaps`: detect missing expected candles and fill only missing ranges.

These meanings are documented here only. No write behavior is implemented.

## OHLCV Maintenance Semantics

OHLCV Maintenance eventually owns storage-quality maintenance:

- detect missing candles
- repair gaps
- refresh latest range
- verify continuity
- rebuild metadata
- deduplicate rows
- normalize timestamps
- validate schema
- report quality warnings
- stamp accepted validation/quality metadata
- record source correction provenance

This phase does not implement OHLCV Maintenance execution.

## Timestamp, Timezone, And Schema Policy

Legacy CSV header:

```text
ts_ms
open
high
low
close
volume
```

V2 timestamp semantics:

- UTC only.
- `ts_ms` is candle open time in milliseconds since epoch.
- Range semantics are `[start, end)`: inclusive start, exclusive end.
- Data must be sorted by `ts_ms`.
- Data must be deduplicated by `ts_ms`.
- Basic OHLCV consistency must be validated by a future validator, not by this
  naming-policy helper phase.

## Data Manager Relationship

Download Manager owns request intent and future raw output result reporting.

The OHLCV storage policy defines where raw downloaded data lands and how it is
identified.

Data Manager later owns indexing, importing, cataloging, derived datasets, and
analysis-facing access.

No Data Manager coupling is introduced in this phase.
