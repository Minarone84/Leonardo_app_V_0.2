# Task 0064 — Resident Slice Service

## Status

Implemented and independently validated.

## Objective

Derive immutable, bounded resident OHLCV windows from the accepted full
`HistoricalDataset` without adding GUI, persistence, validation, or Core task
responsibilities.

## Canonical authorities

- `MarketId` remains the shared market-series identity.
- `HistoricalDataset` remains the canonical accepted full Research read model.
- `ResidentSliceService` owns only disposable resident-window derivation and its
  local cache.
- OHLCV persistence and validation remain outside Research.

## Preserved Old Leonardo behavior

- Resident size is `visible_max + buffer_left + buffer_right`.
- The default policy is 2,000 visible bars plus 1,500 bars on each side.
- Slices expand at dataset edges to retain the target size when possible.
- Timestamp lookup uses the nearest candle and prefers the earlier candle on a
  tie.
- Resident payloads expose a global `base_index` and left/right availability.

## Improvements

- Tuple-backed immutable payloads.
- Canonical `MarketId`; no legacy `DatasetId`.
- Cache keys include the accepted CSV SHA-256 fingerprint.
- Older slices for the same market are removed automatically when a new
  fingerprint is observed.
- Deterministic argument validation and explicit cache invalidation.
- No request-envelope identity, GUI state, filesystem access, or async runtime
  plumbing in the resident domain service.

## Explicit non-goals

- Chart session state.
- Viewport mathematics.
- Qt rendering.
- Core task submission.
- Financial Tool calculations.
- OHLCV writes, validation, or repair.
