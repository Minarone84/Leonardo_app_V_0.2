# Download Data Object Map Pattern

This document records the first read-only Object Map pattern for Download Data
boundary descriptors and read models.

The pattern is implemented by
`src/leonardo/core/download_data_boundary_trace.py`. It accepts explicit
Download Data boundary inputs and emits read-only Object Map provider
descriptors, traceable object summaries, and relationship references.

## Scope

The helper covers summaries for:

- download data boundary
- download data workflow
- download data selection
- download data preflight and preflight items
- download data progress and progress items
- download data completion and completion items
- download data storage targets
- download data output references
- download data partial persistence summaries

The helper also emits reference-only links to provider capability, storage
policy, operation, task, and permission identifiers when those identifiers are
present in explicit inputs.

## Boundaries

This is read-only Object Map pattern work. Inputs are explicit descriptor and
read-model objects only. The helper does not change the Object Map service,
does not expose a Runtime Manager summary, and does not add Runtime Manager
controls.

The helper does not implement GUI behavior, downloader execution, cancellation,
adapter calls, provider clients, network/API/websocket/subscription behavior, or
storage writes. It does not integrate Data Manager, add ProviderRegistry
discovery, scan modules, or import old Leonardo code.

Download Data may use Provider/Exchange capability facts in later phases, but
it does not merge into Provider/Connection. Provider and Connection boundaries
remain separate owners of provider capability and transport facts.

Core supervises runtime workflow state. Core does not own persisted OHLCV
truth. Storage/Data owns persisted OHLCV truth.

## Storage Naming

Storage target and output summaries preserve the accepted legacy-compatible
OHLCV naming policy:

```text
data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv
data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.meta.json
artifact_id = ohlcv__candles
```

The machine identity is `symbol`. `asset` is not used as a Download Data
contract identity.

## Partial Persistence

Partial persistence summaries are diagnostic references for incomplete OHLCV
output. They do not imply accepted, loadable, validated, or clean data. Future
maintenance work must decide how partial files become accepted persisted data.

## Future AI Helper

A future AI helper may use metadata and action pathways after those boundaries
exist. It must not bypass Download Data, Provider/Connection, Storage/Data,
Object Map, Runtime Manager, or user policy boundaries. No AI helper is
implemented by this phase.

## Validation

The focused validation target is:

```text
python -m pytest tests/core_test/test_download_data_boundary_object_map_pattern.py -q -p no:cacheprovider
```
