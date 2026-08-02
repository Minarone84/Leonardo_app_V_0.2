# Task 0068 — Price Interaction and Scale

## Objective

Restore the validated Old Leonardo single-price-chart interaction behavior on top
of the Light V2 viewport and Task 0067 renderer without moving data, calculation,
persistence, or task ownership into Qt widgets.

## Canonical authorities

- `HorizontalViewport`: horizontal chart-space camera and crosshair index.
- `PriceScaleState`: price-pane autoscale/manual-y presentation state.
- `ResidentOHLCVSlice`: immutable resident OHLCV truth.
- `CandlestickInteractionState`: thin local gesture adapter coordinating the two
  authorities above.
- `CandlestickChartWidget`: Qt event translation and painting only.

## Restored behavior

- left-drag horizontal panning;
- cursor-anchored wheel zoom;
- dynamic vertical/horizontal crosshair;
- visible-candle autoscale;
- optional extra visible prices in autoscale for later overlay integration;
- explicit manual price range;
- manual vertical panning;
- price-axis vertical zoom and Shift+axis pan;
- visible last-price line and axis tag;
- static candle/axis pixmap caching;
- dynamic crosshair updates through queued `QWidget.update()` without rebuilding
  the static scene.

## Architecture limits

The widget performs no filesystem access, OHLCV validation, Financial Tool
calculation, persistence, Core task management, provider communication, or
resident refill execution. It emits read-only viewport/scale changes for later
Task 0069 integration.

## Old behavior deliberately rejected

- renderer-owned dataset truth;
- mutable shared view-state dictionaries;
- `QApplication.processEvents()` progress workarounds;
- legacy `CoreBridge` and `DatasetId` dependencies;
- synchronous data or calculation work from input handlers;
- crosshair movement invalidating the static candle scene.

## Validation

Pure tests cover price-range resolution, manual pan/zoom mathematics,
horizontal gesture translation, cursor anchoring, cache identities, last-price
tagging, and explicit scale contracts. Qt smoke tests cover construction,
interaction binding, static-cache reuse, and public autoscale control when
PySide6 is available.

Final visual acceptance is required before Task 0068 closes.
