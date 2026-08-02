# Task 1019 Eight-Slot Research Workspace

Task 1019 extends the accepted single-chart Research workflow to one transient
workspace containing up to eight embedded charts. The workspace allocates the
lowest unoccupied logical slot from 1 through 8. Removing a chart does not
renumber surviving slots, while the visual grid compacts occupied charts in
logical-slot order.

`ResearchWorkspaceState` owns transient slot membership, active-slot selection,
and one independent `ChartSessionState` per occupied slot. Each chart presenter
owns that slot's dataset and resident tasks, viewport, interaction state,
Studies, presentations, panes, progress, cancellation, and stale-callback
guard. The suite presenter owns the shared accepted-dataset catalog and routes
the global Study Manager, autoscale, volume, cancel, and close controls only to
the active chart.

The adaptive layout follows the frozen one-through-eight grid plans. Scroll 4
uses vertical scrolling beyond four charts; Fit 8 fits the complete grid. Mode
changes reposition existing slot widgets and do not recreate chart sessions,
widgets, Studies, panes, viewports, or interaction state.

Chart operations may be pending concurrently. Closing one chart cancels and
disposes only that chart. Slot-local runtime identity rejects callbacks from a
removed chart and from an earlier session when a logical slot is reused. Suite
disposal cancels each remaining chart's work and disposes every chart session.

The widget package resolves its complete public widget surface lazily, so the
pure workspace layout planner remains importable without PySide6. A left-button
press on any slot surface, including current or dynamically created candle,
volume, and oscillator children, activates that slot exactly once without
consuming the child's original interaction event.

The frozen action replay removes sessions 3 and 5, reuses logical slot 3 with
session 9, and finishes with slot 3 active. Visualization-mode changes do not
change that domain state.

The first occupied chart retains the accepted Task 1017 and Task 1018 public
single-chart access through the suite presenter's active `session` and
`viewport`, and through the window's active chart and pane workspace aliases.
Task 1019 adds no persisted workspace schema and no alternate Apply, Save,
rendering, artifact, or OHLCV authority.

This task intentionally excludes detached or docked charts, chart movement,
go-to-date, Pan Anchor, cross-chart synchronization, Study Setup, Study
Environments, workspace snapshots, notebooks, annotations, collections, Data
Manager, Analysis, Backtest, realtime operation, and performance hardening.
