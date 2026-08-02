# Task 0070 PATCH — Splitter Initialization

## Problem

On Windows with PySide6, an unshown `QSplitter` may report equal placeholder
sizes such as `(13, 13)` even after `setSizes((720, 220))`. Task 0070 treated
those provisional values as authoritative pane state. The existing GUI test
correctly rejected the loss of the intended price-dominant proportions.

## Correction

`ChartPaneWorkspaceWidget` now:

- returns the cached visible-pane proportions until the workspace has visible
  geometry;
- does not persist provisional splitter values while the workspace is hidden;
- reapplies the cached proportions after the widget is shown;
- records user splitter movement only while the workspace and volume pane are
  visible.

The existing failing test remains unchanged. No GUI workflow, Research data,
Core, OHLCV, persistence, Financial Tool, or Download Data behavior changed.
