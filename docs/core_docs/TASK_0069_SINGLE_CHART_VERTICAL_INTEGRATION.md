# Task 0069 — Single-Chart Vertical Integration

## Objective

Connect the accepted historical Research data foundation and the validated
candlestick chart engine into one production GUI workflow.

## User workflow

```text
Open Research Suite
→ scan accepted OHLCV datasets
→ select MarketId
→ load the immutable full dataset through Core
→ prepare an initial resident slice through Core
→ display the interactive candlestick chart
→ pan/zoom/crosshair/manual-y
→ refill resident data near slice edges
→ cancel or close safely
```

## Canonical authorities

- `MarketId`: canonical market identity.
- OHLCV Area and `OHLCVSidecarV1`: persistence and accepted-data evidence.
- `HistoricalDatasetLoader`: immutable complete dataset truth.
- `ResidentSliceService`: disposable resident projections.
- `ChartSessionState`: one chart's selected dataset and resident truth.
- `HorizontalViewport`: horizontal camera state.
- `PriceScaleState`: vertical price presentation state.
- `TaskManager`: background task lifecycle.
- Research window: dataset selection, status, progress, and chart presentation.

## Architecture

The GUI never reads CSV or sidecar files, validates datasets, slices candles, or
owns task lifecycle. `ResearchSuitePresenter` translates GUI intent and correlates
Core results with `ChartSessionState`. The application service submits catalog,
full-load, and resident-slice jobs to the existing Core worker pool. Results return
through a queued Qt dispatcher.

## Preserved old behavior

- Accepted datasets only.
- Latest-candle initial camera placement.
- Full dataset retained independently of resident render data.
- Resident refills driven by viewport proximity.
- Stale dataset and slice results rejected.
- Existing pan, zoom, crosshair, autoscale, manual-y, and chart-padding behavior.

## Explicit non-goals

- Volume or oscillator panes.
- Financial Tools and studies.
- Multi-chart workspace.
- Study Environments, snapshots, or notebooks.
- OHLCV download, validation mutation, or repair.
- Data Manager artifact persistence.

## Visual validation

Run:

```powershell
python tools/dev_launch_research_chart.py
```

Confirm dataset selection, loading status, chart display, panning, zooming,
crosshair, manual-y interaction, resident refills, cancellation, close, and clean
application shutdown.
