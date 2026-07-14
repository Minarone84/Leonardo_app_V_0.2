# Task 0070 — Pane Workspace and Volume

## Status

Implementation complete. Local PySide6 visual acceptance is required before final closure.

## Objective

Restore the validated Old Leonardo single-chart pane behavior for one price pane
and one optional base-volume pane without restoring legacy ownership machinery.

## Preserved behavior

- One workspace owns pane lifecycle and splitter sizing.
- Price and volume consume the same horizontal viewport.
- Price and volume consume the same global crosshair index.
- Volume bars use candle direction for bullish/bearish presentation.
- Volume has an always-visible-range autoscale.
- Volume includes the validated 20-period rolling mean.
- The rolling mean is seeded from full dataset history before the resident slice.
- Price and volume resident state changes are applied coherently.
- Volume is optional and hidden by default.

## Architecture

```text
HistoricalDataset                      canonical accepted full OHLCV
    ↓
build_resident_volume_projection       Research-derived resident projection
    ↓
ChartPaneWorkspaceWidget               pane lifecycle and splitter authority
    ├── CandlestickChartWidget         price presentation and price interaction
    └── VolumeChartWidget              volume presentation and shared-x interaction
```

Canonical authorities remain:

- `HistoricalDataset`: accepted full OHLCV read truth.
- `ChartSessionState`: selected dataset and resident slice truth.
- `HorizontalViewport`: shared horizontal camera and crosshair index.
- `PriceScaleState`: price-pane vertical state.
- `ChartPaneWorkspaceWidget`: pane visibility, ordering, and splitter state.
- `TaskManager`: long-running operation lifecycle.

The GUI does not read files, calculate Financial Tools, own validation, or write
persistence. The small resident volume projection is a deterministic Research
domain derivation. Task 0073 must reuse this rolling-mean implementation for the
canonical Volume oscillator rather than create a second formula.

## Rejected old behavior and architecture

- Strict NSRR doctrine.
- Old `ChartModel`, `ChartViewport`, `Crosshair`, and `CoreBridge` types.
- Pane discovery through shared mutable internals.
- Renderer-owned pane lifecycle.
- GUI-thread filesystem work.
- Duplicate Volume formulas.
- Contract registries and GUI metadata mirrors.
- Broad exception swallowing.

## Files

### Added

- `src/leonardo/research/volume.py`
- `src/leonardo/gui/chart/volume_scene.py`
- `src/leonardo/gui/chart/volume_widget.py`
- `src/leonardo/gui/chart/pane_workspace.py`
- `tests/research_test/test_volume_projection.py`
- `tests/gui_test/test_volume_scene.py`
- `tests/gui_test/test_pane_workspace.py`

### Updated

- `src/leonardo/research/__init__.py`
- `src/leonardo/gui/chart/__init__.py`
- `src/leonardo/gui/chart/candlestick_widget.py`
- `src/leonardo/gui/windows/research_suite_window.py`
- `src/leonardo/gui/presenters/research_presenter.py`
- `tests/gui_test/test_research_single_chart_integration.py`
- `tests/gui_test/test_research_single_chart_static.py`
- `tools/dev_launch_research_chart.py`

## Explicit non-goals

- Oscillator studies.
- Financial Tool specifications.
- Study manager or style editor.
- Multiple chart sessions.
- Detach/dock or Pan Anchor.
- Study Environment, Workspace Snapshot, or Notebook persistence.
- Data Manager artifact integration.
- OHLCV writes, validation, repair, or download changes.

## Visual acceptance

Run:

```powershell
python tools/dev_launch_research_chart.py
```

Confirm:

1. The accepted dataset loads and the price chart remains unchanged.
2. The Volume pane appears automatically in the developer smoke launcher.
3. Bullish and bearish volume bars match candle direction.
4. The cyan 20-period mean line is visible after warm-up.
5. Price and volume stay horizontally aligned while panning and zooming.
6. Crosshair vertical position is shared between panes.
7. Panning or zooming from the volume pane updates the price pane.
8. The splitter resizes both panes cleanly.
9. `Show Volume` / `Hide Volume` preserves the chart session.
10. Resident refill does not reset volume visibility or alignment.


## Autoscale integration correction

The integrated Research chart toolbar exposes the existing price-scale authority
through a local `Disable Autoscale` / `Enable Autoscale` button. The control only
changes chart presentation state; it does not enter the global ActionRegistry or
own price calculations. Manual vertical pan and price-axis zoom are available only
while autoscale is disabled.
