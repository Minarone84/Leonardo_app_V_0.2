# Task 0067 — Base Candlestick Renderer

## Status

Implemented. Automated non-Qt validation passes. The Qt smoke test is included
and runs when PySide6 is available; final visual acceptance remains a user gate.

## Objective

Restore the proven Old Leonardo static historical price chart as a clean Light
V2 GUI component without restoring old controller, CoreBridge, mutable chart
model, study, or interaction responsibilities.

## Canonical authorities

- Accepted OHLCV truth remains owned by the existing OHLCV authority.
- `ChartSessionState` owns the accepted full and resident data references.
- `HorizontalViewport` owns horizontal camera state.
- The pure scene planner derives disposable geometry.
- `CandlestickChartWidget` owns only Qt painting and static pixmap caching.

## Preserved behavior

- Custom `QWidget` and `QPainter` rendering.
- Resident-local candle drawing in global chart coordinates.
- Historical and future empty chart padding.
- Explicit `No older data` presentation.
- Candlestick wicks and open/close bodies.
- High-density aggregation by horizontal pixel bucket:
  - first open;
  - maximum high;
  - minimum low;
  - last close.
- Price grid and right-side price axis.
- Timestamp-based bottom axis.
- HiDPI-aware static `QPixmap` caching.
- Honest empty state when no accepted data exists.

## Improvements

- Pure geometry planning has no PySide6 dependency and is fully unit tested.
- Renderer inputs are immutable `CandlestickRenderContract` values.
- The widget cannot load files, calculate Financial Tools, mutate the viewport,
  or own canonical OHLCV state.
- Cache identity uses accepted dataset fingerprint and viewport state.
- Default price range is derived from visible candles only.
- Price formatting adapts to the visible price span.

## Explicit non-goals

- Mouse and wheel interaction.
- Crosshair rendering.
- User-selectable autoscale/manual-y state.
- Volume and oscillator panes.
- Study overlays, fills, markers, or Financial Tools.
- Research Suite application-service wiring.
- Dataset selection or resident refill submission.
