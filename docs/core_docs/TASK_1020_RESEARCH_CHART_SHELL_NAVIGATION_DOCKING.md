# Task 1020 Research Chart Shell Navigation and Docking

Task 1020 adds transient shell placement, floating chart windows, UTC Go-to-Date
navigation, and optional horizontal Pan Anchor synchronization to the accepted
eight-slot Research workspace.

`ResearchWorkspaceState` remains the logical chart membership and session
authority. `ResearchWorkspaceShellState` independently owns transient workspace
positions and detached state. Neither placement nor Pan Anchor state is
persisted.

Detach and dock reparent the same `ResearchChartSlotWidget`. The chart presenter,
session, viewport, interaction state, pane workspace, Studies, presentation
state, and pending task callbacks remain chart-local and unchanged. Floating
windows are tracked through GUI composition using slot and session identity.

Go-to input is parsed as UTC and resolved through the chart session's canonical
nearest-timestamp authority. Navigation preserves horizontal visible count and
vertical price scale and uses the existing resident-refill path only when
required. Canonical `1d`, `1w`, and `1M` frames advertise date-only input;
intraday `1m` and `1h` frames advertise date and time. Displaying a selected
market does not enable Go-to; the chart presenter enables it only after the
dataset is accepted and its viewport exists.

Pan Anchor is off by default. When enabled, user horizontal pan is synchronized
by center timestamp to every other loaded chart, including detached charts.
Targets that are loading, empty, failed, removed, or disposed are skipped
without changing their status or task state.
Zoom, crosshair, vertical scale, Study state, splitter sizes, volume visibility,
workspace mode, and active-chart selection are not synchronized.

Direct presenter disposal closes all floating shells programmatically before
disposing chart presenters and workspace membership. Repeated disposal remains
an idempotent no-op.
