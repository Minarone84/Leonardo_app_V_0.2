# Task 0066 — Horizontal Viewport Mathematics

## Status

Implemented and validated.

## Objective

Restore the proven Old Leonardo horizontal chart-camera behavior as pure Research
domain mathematics, without PySide6, rendering, resident ownership, persistence,
or Core task responsibilities.

## Canonical authorities

- The accepted Research dataset/session owns dataset truth and timestamp lookup.
- `HorizontalViewport` owns only horizontal chart-space camera state.
- `ChartSessionState` continues to own full/resident data references.
- A future Qt adapter will own gestures, signals, and repaint scheduling.

## Preserved Old Leonardo behavior

- Fixed empty chart space before and after real dataset rows.
- Latest real candle aligned to the right data edge on initial placement.
- Boundary-clamped horizontal panning.
- Cursor-anchored zoom without automatic snapping to the latest candle.
- Minimum and maximum visible-bar policies.
- Explicit chart-space crosshair index.
- Mapping between normalized screen position and discrete chart slots.
- Dataset-interest mapping when the camera is partly or entirely in padding.
- Resident-refill decisions near resident-data boundaries.

## Frozen policy

```text
left chart padding:       1,000 slots
right chart padding:      1,000 slots
minimum visible bars:        20
initial visible bars:        500
maximum visible bars:      2,000
resident refill threshold:   250 bars
```

## Improvements

- No Qt dependency in camera mathematics.
- State-changing methods return whether observable state changed; later GUI code
  decides whether to emit signals or repaint.
- Timestamp centering delegates timestamp-to-index resolution to the chart
  session instead of duplicating timeline authority.
- Crosshair state is domain-bounded.
- Dataset-interest and refill decisions are explicit immutable values/enums.
- Invalid inputs fail clearly rather than being silently coerced.

## Explicit non-goals

- Mouse or wheel event handling.
- Candlestick, axis, grid, or crosshair rendering.
- Price autoscale or manual y-axis state.
- Resident-slice calculation or publication.
- Qt signals.
- Dataset loading, persistence, Financial Tools, or studies.
