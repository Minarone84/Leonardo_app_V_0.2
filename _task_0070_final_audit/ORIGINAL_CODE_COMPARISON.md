# Original-Code Comparison — Task 0070

Baseline: `Leo_V2_0069_POST_20260713_2351.zip`.

Old Leonardo evidence inspected:

- `docs/DESIGN_historical_chart_v2.md`
- `gui/chart/panes/volume_pane.py`
- `gui/chart/rendering/volume_surface.py`
- `gui/chart/workspace.py`
- canonical Volume oscillator runtime

Behavior preserved:

- optional volume pane;
- shared horizontal viewport and global crosshair index;
- bullish/bearish volume bars based on candle direction;
- visible-range volume autoscale;
- 20-period rolling volume mean;
- splitter-owned pane sizing;
- resident-base/global-index alignment;
- static-scene cache with dynamic crosshair painting.

Behavior improved:

- rolling mean seeds from full accepted dataset history across resident boundaries;
- pane state is applied atomically during resident refills;
- price and volume consume one existing `HorizontalViewport` authority;
- no renderer or pane discovers mutable workspace internals;
- no broad exception swallowing;
- no GUI-owned data loading or persistence;
- no duplicate old `ChartModel`, `Crosshair`, `ChartViewport`, `DatasetId`, or `CoreBridge` implementation.

Unrelated code changed: none.
