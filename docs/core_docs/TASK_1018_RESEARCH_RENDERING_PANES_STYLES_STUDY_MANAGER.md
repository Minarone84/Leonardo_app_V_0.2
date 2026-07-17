# Task 1018 Research Rendering, Panes, Styles and Study Manager

## Scope

Task 1018 renders accepted Task 1017 Studies in the Research chart. It adds
chart-local presentation state, price overlays, one pane per oscillator Study,
the embedded Study Manager, and a local style dialog. It does not add Study
setup, source selection, style persistence, pane persistence, or calculation
semantics.

## Authorities

`ChartSessionState` owns the ordered Study and presentation state for one chart
session. `StudyPresentationRegistry` owns visibility and style revisions. Task
1017 remains the authority for Apply, Save, durable lineage, and dependency-aware
removal. Task 1014 remains the authority for renderable outputs, style-driver
outputs, pane roles, oscillator bounds, and guide levels.

Only `ResidentStudyProjection` values enter scene planning. Full Financial Tool
calculation frames do not enter GUI widgets. Styles are chart-local and never
enter recipes or artifacts.

## Rendering

Price scene planning is pure. Visible finite overlay values participate in
autoscale, while manual price ranges remain unchanged. Fills are painted before
candles; lines and markers are painted after candles and before the crosshair.
Non-finite values break line and fill strips. Conditional style-driver changes
split line and fill strips at a shared boundary point so every adjacent finite
interval remains drawable without rendering the driver as a signal. Visible
fill boundaries participate once in autoscale even when their line styles are
hidden.

Oscillator scene planning is also pure. Fixed Task 1014 bounds and guides are
used where declared; other oscillators autoscale finite visible values. Empty
data uses `0.0..1.0`, and flat ranges expand. Each visible oscillator Study owns
`oscillator:<study_id>`. The eight Task 1014 oscillator-pane constructs use
strict canonical output signatures, automatic finite visible-value bounds, and
no guides; native oscillator fixed bounds and guide policies remain unchanged.

## Pane And Manager Lifecycle

`ChartPaneWorkspaceWidget` is the sole pane owner. Price is permanent, volume
remains optional, oscillator pane order follows Study order, hidden oscillator
Studies retain their presentation and widget identity, and removed Studies lose
their exact pane. Nonvisual Studies remain visible in the manager without a
pane.

`StudyManagerWidget` receives immutable manager entries and emits only user
intent signals. `StudyStyleDialog` receives one immutable presentation and emits
an immutable patch. Style Apply and Reset mutate only session presentation state
and trigger redraws; they do not calculate or persist. Reset emits only its
reset intent and closes the dialog so stale controls cannot reapply pre-reset
values.

## Composition

`LeonardoApp` constructs one `ArtifactService`, one `ResearchStudyService`, and
one `ResearchStudyApplicationService` from the canonical historical root and
the shared `CoreRunner`. GUI composition injects the dataset and Study
application services into `ResearchSuitePresenter`. The presenter uses Task 1017
begin, submit, accept, and settle flows, then publishes session projections,
presentations, and manager entries to the window.

## Preserved Exclusions

Task 1018 does not implement Financial Tool forms, artifact browsing, Study
Environments, workspace snapshots, detached panes, collections, Data Manager,
Analysis, Backtesting, realtime operation, or any direct GUI filesystem access.
