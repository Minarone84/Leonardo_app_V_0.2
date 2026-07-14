# Task 0065 — Chart Session State

## Status

Implemented and validated.

## Objective

Provide one canonical mutable data-state owner for a historical Research chart
without introducing viewport, Qt, persistence, Financial Tool, or Core task
responsibilities.

## Canonical authorities

- `MarketId` remains the canonical market-series identity.
- `HistoricalDataset` remains accepted immutable full-dataset read truth.
- `ResidentOHLCVSlice` remains disposable immutable resident truth.
- `ChartSessionState` owns only one chart's selected dataset generation,
  accepted dataset reference, current resident reference, result-correlation
  attempts, and coordinate translation.

## Preserved Old Leonardo behavior

- New dataset opens invalidate older open and resident results.
- A latest slice-request identity rejects late resident results.
- Full timeline lookup supports exact and nearest timestamps, preferring the
  earlier candle on ties.
- Global dataset indexes and resident-local indexes remain separate.
- Disposal prevents late asynchronous results from mutating a closed chart.

## Improvements

- Uses canonical `MarketId`; no legacy `DatasetId`.
- Shares immutable dataset and resident objects instead of copying timelines,
  timestamp maps, candles, or OHLCV columns into every chart session.
- Explicit immutable correlation tokens replace loosely coordinated controller
  fields.
- Current failures settle only their matching attempt.
- Session disposal releases all full-dataset and resident references.
- No pandas DataFrame cache is owned by the chart session.

## Explicit non-goals

- Horizontal viewport mathematics.
- Qt rendering and interaction.
- Dataset loading or resident-slice calculation.
- Core task submission or cancellation.
- Financial Tool calculations or study projections.
- Research persistence.
