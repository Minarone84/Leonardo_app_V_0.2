# Leonardo V2 Research Suite

**Status:** Production implementation complete and accepted for freeze
**Updated:** 2026-08-02
**Data Manager acceptance:** Deferred to a separate task/conversation
**Primary implementation:** `src/leonardo/research/`,
`src/leonardo/gui/research/`, Research presenters, Financial Tools, and
Artifact services

## 1. Purpose

The Research Suite is Leonardo's interactive historical-chart and Financial
Tools workspace.

It consumes canonically accepted OHLCV datasets, calculates and presents
Financial Tools, manages transient chart Studies, persists reproducible Recipes
and full calculated Artifacts, and saves reusable Research state through Study
Environments, Workspace Snapshots, and Research Notebooks.

The production Research Suite restores the proven Old Leonardo workflow and
visual hierarchy without restoring the old architecture.

The governing path is:

```text
Research GUI intent
→ Research presenter
→ Research application service
→ Research/Financial Tools domain service
→ shared CoreRunner when work is long-running
→ canonical store when persistence is requested
→ structured result
→ queued Qt presentation
```

## 2. Current completion status

The following areas are implemented and have passed automated and native smoke
validation:

- real application composition;
- accepted-dataset catalog;
- chart creation and lifecycle;
- up to eight chart slots;
- Scroll 4 and Fit 8 layouts;
- detach and dock;
- mixed-timeframe UTC navigation;
- Pan Anchor;
- Autoscale;
- Financial Tools catalog and parameter forms;
- Study Apply, Edit, Save, style, visibility, and removal;
- price overlays, oscillator panes, volume presentation, markers, fills, and
  guides;
- Study Environments;
- Workspace Snapshots;
- Research Notebooks and annotations;
- Clear Research Suite;
- Core task integration;
- long-lived window tracking;
- restart-safe Research persistence.

The Research GUI hierarchy and primary command placement are frozen. A future
change requires a reproduced defect or an explicitly approved new task. “It
might look nicer over there” is not a defect classification, despite centuries
of interface design suggesting otherwise.

The separate Data Manager end-to-end acceptance gate is not part of this freeze
record and must be handled independently.

## 3. Canonical authorities

| Concern | Canonical authority |
|---|---|
| Market-series identity | `MarketId` |
| OHLCV persistence | `OHLCVStore` |
| OHLCV validation truth | Canonical OHLCV validator and sidecar |
| Research admission | `AcceptedDatasetCatalog` |
| Full loaded dataset truth | `HistoricalDatasetLoader` / `HistoricalDataset` |
| Resident chart candles | `ResidentSliceService` |
| Chart/session state | Research session and workspace models |
| Financial Tool definitions | Financial Tools specification catalog |
| Financial Tool calculations | Financial Tools calculation service |
| Transient Study identity and result | Research Study service/session |
| Study presentation | Research GUI presentation state |
| Recipe and Artifact persistence | `ArtifactService` |
| Study Environment persistence | `StudyEnvironmentStore` |
| Workspace Snapshot persistence | `ResearchWorkspaceSnapshotStore` |
| Notebook persistence | `ResearchNotebookStore` |
| Notebook-to-Workspace assignment | `ResearchWorkspaceNotebookLinkService` |
| Long-running task lifecycle | Core `TaskManager` through `CoreRunner` |
| Window runtime state | Core `WindowRegistry` through `GuiWindowTracker` |

The GUI owns presentation and intent. It does not calculate Financial Tools,
write Research files, validate OHLCV, or own task lifecycle.

## 4. Production composition

`LeonardoApp` constructs and retains one shared instance of each Research
application/domain service and store.

`GuiCompositionRoot` creates the restored Research Suite with those existing
services:

```text
ResearchSuiteWindow
+ RestoredResearchLifecyclePresenter
+ ResearchDatasetApplicationService
+ ResearchStudyApplicationService
+ ResearchStudySetupApplicationService
+ ResearchWorkspaceSnapshotApplicationService
+ ResearchNotebookApplicationService
```

The Research window does not construct a second CoreRunner, ArtifactService,
OHLCV loader, or persistence root.

Closing the Research Suite disposes its lifecycle presenter, cancels active
Research tasks where applicable, closes retained secondary windows, retires the
window/presenter pair from GUI composition, and permits a fresh Research Suite
to be created later.

## 5. Main shell and command model

The Research Suite is a `QMainWindow` with:

- File menu;
- Window menu;
- Notes menu;
- same-row menu-bar quick actions;
- chart-first central workspace;
- retractable Research Activity surface;
- no permanent global dataset strip;
- no permanent right-side Studies panel;
- chart-local controls.

Primary workflows include:

```text
New Chart
Save / Load / Manage Study Environments
Save / Load / Manage Workspace Snapshots
Create / Open / Manage / Save / Load Notebooks
Pan Anchor
Scroll 4
Fit 8
Clear Research Suite
```

Menu actions and quick controls reuse the same command state so enabled,
checked, and visual status cannot drift into parallel truths.

## 6. Accepted OHLCV boundary

Research consumes only datasets listed by `AcceptedDatasetCatalog`.

A dataset is accepted only when canonical OHLCV sidecar evidence is valid and:

```text
validation_status = "ok"
```

A CSV existing on disk is not sufficient.

The accepted catalog supplies canonical `AcceptedDatasetSummary` values used by
New Chart and Workspace compatibility checks.

Research never writes or repairs OHLCV.

## 7. Dataset loading and cache behavior

`HistoricalDatasetLoader`:

- resolves the canonical accepted summary by `MarketId`;
- reads the full dataset;
- parses and validates canonical rows;
- calculates a SHA-256 file fingerprint;
- retains immutable full-dataset truth;
- caches by canonical identity and current file evidence;
- rejects non-accepted or changed datasets;
- supports explicit cache invalidation.

OHLCV Maintenance invalidates the matching Research cache after mutation.

An already-open chart does not hot-reload when its source CSV changes. The chart
continues using the immutable dataset and fingerprint with which its current
session and Studies were created. This prevents silent result and lineage
mutation.

To consume updated OHLCV, the dataset must be validated again and the chart or
Workspace must be reopened/restored.

## 8. Chart and workspace lifecycle

### 8.1 Capacity and positions

Research supports exactly eight logical chart slots.

The workspace owns:

- stable chart/session identity;
- positions 1 through 8;
- active-chart context;
- deterministic slot compaction;
- detached-position reservation;
- dock-back identity;
- no cross-chart mutable Study truth.

### 8.2 Visualization modes

#### Scroll 4

Default mode optimized for four visible chart panels with scrolling for
additional charts.

#### Fit 8

Fits up to eight charts within the available workspace using the accepted
adaptive layout.

### 8.3 Chart creation

New Chart uses accepted catalog data only:

```text
Exchange
→ Market Type
→ Asset
→ Timeframe
→ create chart in next available position
```

Dataset loading and resident-slice preparation run through Core tasks.

### 8.4 Detach and dock

Detaching moves the existing chart panel into a tracked top-level window while
reserving its logical workspace position.

Docking returns the same chart identity, dataset, viewport, panes, Studies,
styles, and local state to the reserved position.

No duplicate chart session is created.

### 8.5 Close and reuse

Closing a chart retires its presenter/session, releases its slot, compacts
remaining chart positions where required, and leaves the suite usable for new
charts.

## 9. Resident slices and refill

Financial Tools calculate against the full accepted dataset, not only the
currently visible candles.

The chart displays a resident slice projected from full dataset truth.

When navigation requires candles outside the current resident slice:

```text
requested timestamp/index
→ Core-supervised resident-slice task
→ new resident OHLCV slice
→ reproject existing full Study results
→ preserve chart identity and valid viewport state
```

Stale task results are rejected when dataset, session, or refill identity has
changed before publication.

## 10. Navigation and interaction

### 10.1 Autoscale

Autoscale state is chart-local and visibly encoded:

- enabled: green state;
- disabled: red state.

Manual price scale is preserved when Autoscale is off and is persisted in
Workspace Snapshots.

### 10.2 Go To

The single-instance chart-local Go To dialog supports:

- typed UTC date/time;
- calendar selection;
- time selector.

Navigation uses canonical timestamp centering and resident refill when needed.
Repeated use focuses/reuses the same dialog for that chart.

### 10.3 Pan Anchor

Pan Anchor synchronizes user-originated horizontal navigation across ready
charts by UTC timestamp.

It does not treat programmatic initial load, Workspace restore, or other
non-user navigation as a new synchronization source.

Pan Anchor starts OFF, is visibly red while off, and green while on.

### 10.4 Crosshair

The accepted crosshair presentation includes:

- UTC time tag on the price pane when no oscillator exists;
- UTC time tag on the bottom time-axis-owning oscillator when oscillators exist;
- right-axis price value tag;
- volume value tag;
- no static-pixmap rebuild for dynamic crosshair movement.

## 11. Research Financial Tools catalog

The global Financial Tools catalog contains 26 tools:

```text
10 indicators
7 oscillators
9 constructs
```

Research exposes 25.

### Indicators

```text
sma
ema
tema
hma
kama
bb
hck
strategy
peaks_troughs
universal_trend_classifier
```

### Oscillators

```text
rsi
arsi
tdirsi
smi
mfi
obv
volume
```

### Research Constructs

```text
derivative
angle
braids
braid_instability
delta
trap_area
percent_span_angle
angle_momentum
```

### Dynamic Binning exclusion

`dynamic_binning` remains globally registered as a deterministic, nonvisual
Financial Tool for future Analysis use.

It is excluded from:

- Research Financial Tools catalog;
- Research calculation drafts;
- saved-Artifact application in Research;
- Study Environments;
- Research presentation and compact labels.

Legacy Environment files containing Dynamic Binning may be parsed for honest
compatibility reporting, but application is blocked and the persisted file is
not silently rewritten.

## 12. Study source model

A Study input may come from:

- canonical OHLCV columns;
- another in-session Study output;
- a persisted Artifact output.

Source roles and output names are validated against the Financial Tool
specification.

Structural identity remains exact:

- tool key;
- Study ID;
- source roles;
- output names;
- dependencies;
- lineage;
- ordering.

Timestamp alignment and `MarketId` are used for persisted Artifact sources.
Positional row matching is not treated as durable lineage.

## 13. Apply, Edit, and Save semantics

These operations are intentionally distinct.

### 13.1 Apply

```text
full accepted OHLCV
→ calculate Financial Tool
→ create transient ChartStudy
→ store full result in the chart session
→ project to resident candles
→ render
```

Apply does not persist a Recipe or Artifact.

### 13.2 Edit

Edit recalculates an existing in-session Study with changed editable parameters.

The Edit dialog:

- displays only editable parameters for the selected Study;
- does not expose a second tool selector;
- enables confirmation only after a legitimate value changes;
- preserves Study identity and presentation state where valid;
- does not auto-save.

### 13.3 Save

Save persists the existing full Study result through `ArtifactService`:

```text
Chart Study full result
→ canonical Recipe
→ calculated Artifact
→ durable OHLCV/source lineage
→ saved link returned to the in-session Study
```

The calculation form does not expose the retired direct-save behavior. Save is a
Study lifecycle operation.

Persistence is fenced against OHLCV changes before and during publication.

## 14. Recipe and Artifact persistence

Artifacts and Recipes are stored beneath the canonical market root in
`historical_data/`:

```text
historical_data/
└── <exchange>/<market_type>/<symbol>/<timeframe>/
    ├── recipes/<kind>/<tool_key>/<recipe_id>.json
    └── artifacts/<kind>/<tool_key>/<artifact_id>/
        ├── values.csv
        ├── artifact.meta.json
        └── analysis.json        optional
```

Identifiers are deterministic lowercase SHA-256 values derived from canonical
identity payloads.

A saved Artifact records:

- canonical Recipe;
- `MarketId`;
- tool kind and key;
- resolved parameters and bindings;
- output names;
- source OHLCV fingerprint;
- source Artifact references;
- row count and timestamp coverage;
- values hash;
- optional analysis payload hash;
- creation time.

Artifact-backed Studies are not silently recalculated when OHLCV changes.
Current source lineage must match. Stale Artifact lineage is a blocker.

## 15. What happens after OHLCV is updated

The correct lifecycle is:

```text
update/download/repair OHLCV
→ sidecar validation status becomes non-accepted until validated
→ run canonical OHLCV validation
→ updated dataset re-enters AcceptedDatasetCatalog
→ reopen chart or reload Workspace
```

### Already-open chart

It remains on its original immutable dataset and Study results. No silent
hot-reload occurs.

### Calculation-mode Study on Workspace reload

Workspace restore loads the latest accepted dataset for the stored `MarketId`,
then reapplies the embedded Study Environment. Calculation-mode Studies are
therefore recalculated from updated OHLCV.

### Artifact-mode Study on Workspace reload

The persisted Artifact remains tied to its original OHLCV fingerprint. If that
fingerprint no longer matches the current accepted dataset, compatibility or
application blocks it as stale. Workspace restore does not forge new Artifact
lineage.

This is deliberate. Recalculating/replacing persisted Artifacts belongs to the
Artifact/Data Manager lifecycle.

## 16. Presentation and styles

### 16.1 Study presentation

Research supports chart-local presentation state including, where semantically
valid:

- line visibility;
- line color, width, and style;
- per-signal styling;
- fill styling;
- conditional line/fill behavior;
- oscillator guides and thresholds;
- marker style;
- semantic presets;
- custom colors;
- reset to accepted defaults.

Price Study overlay rows expose compact values and actions such as visibility,
style, edit, and removal.

Oscillator panes expose their own title, values, style/edit/removal, and pane
ordering controls.

### 16.2 Specialized accepted behavior

- HCK states are exactly `red`, `silver`, and `green`.
- HCK line/fill behavior follows its accepted conditional fast/slow logic.
- Peaks & Troughs markers use accepted triangle direction, colors, labels, and
  pixel offsets.
- Universal Trend Classifier consumes exact Peaks & Troughs dependency roles.
- Braid and Braid Instability require fast, mid, and slow sources.
- Trap Area permits an optional mid source.
- oscillators with thresholds expose editable threshold values;
- RSI and related guide levels persist and render;
- Volume uses the accepted oscillator-style pane/presentation family.

### 16.3 General window appearance

Research Studies are style-editable.

The Research windows themselves currently inherit the application-wide static
default theme. There is no completed user-facing Appearance Settings workflow
for changing generic Research window backgrounds, menus, tables, buttons, or
fonts at runtime.

This is an application-wide appearance limitation, not a missing Study feature.

## 17. Numerical precision policy

Continuous numerical comparisons use the default practical policy:

```text
absolute tolerance: 0.00005
relative tolerance: 0
```

Full internal calculation and storage precision is preserved. Results are not
rounded merely to make tests pass.

The following remain exact:

- NaN placement;
- booleans;
- categorical states;
- parameter identities;
- tool and Study identities;
- source bindings;
- lineage;
- ordering;
- lifecycle behavior;
- persisted schema structure.

A narrower or wider tolerance may be used only when an individual analysis has
a documented technical reason.

## 18. Study Environments

A Study Environment is a versioned persisted collection of Study definitions
and presentation state.

It stores:

- canonical tool/mode identity;
- display name and description;
- parameters;
- source bindings;
- Artifact links when applicable;
- expected outputs;
- user metadata;
- visibility;
- line, fill, and guide styles;
- entry dependency identity.

Files are stored atomically under:

```text
study_environments/
```

Implemented lifecycle:

```text
Create
Update
Load
Manage
Delete
Compatibility check
Apply with rollback
```

Create names must be unique. Update selects an existing Environment and uses
its canonical name. Switching back to Create clears the name and keeps Save
disabled until a new valid name is entered.

### Dependency ordering

Environment application uses generic dependency ordering derived from source
identity.

It does not hard-code a preferred tool sequence.

For example:

```text
Peaks & Troughs
→ Universal Trend Classifier
```

is ordered because UTC depends on the newly created Peaks & Troughs entry.
Missing dependencies and cycles are explicit blockers.

Multi-entry application reports progress by accepted entry count, supports
cancellation, rejects late progress after cancellation, rolls back partial
application, and permits retry.

## 19. Workspace Snapshots

A Workspace Snapshot is a versioned persisted representation of Research
workspace state.

It stores:

- display name and description;
- visualization mode;
- Pan Anchor state;
- active chart reference;
- chart positions;
- detached/docked state;
- `MarketId` per chart;
- viewport center and visible count;
- Autoscale/manual price scale;
- volume visibility;
- pane sizes;
- embedded Study Environment per chart;
- optional Notebook assignment.

Files are stored atomically under:

```text
workspace_snapshots/
```

Implemented lifecycle:

```text
Create
Update
Load
Manage
Delete
Compatibility preflight
Notebook assign/unassign
```

Update uses an existing Snapshot selector, keeps the canonical name read-only,
and allows description changes.

### Restore

Workspace restore performs compatibility preflight before replacing live state.
It then restores charts sequentially, loads current accepted datasets, applies
the embedded Study Environment, restores chart/pane/navigation state, restores
Notebook assignment, and closes stale administrative/chart-local secondary
windows after successful replacement.

A failed restore preserves a visible terminal failure state and uses rollback
where required. It does not silently leave a half-replaced workspace.

## 20. Research Notebooks

Research Notebooks are versioned persisted objects stored under:

```text
research_notebooks/
```

A Notebook contains:

- display name and description;
- annotation settings;
- pages keyed by canonical `MarketId`;
- timestamped notes;
- Potential Trades;
- Points of Interest.

Annotations are projected into charts as Notebook presentation. They are not
Studies, Financial Tool outputs, or Artifacts.

Implemented lifecycle:

```text
Create
Open
Save
Save As
Load
Manage
Delete
Assign to Workspace
Unassign from Workspace
Go to annotation timestamp
```

Only one Notebook may be assigned to a Workspace Snapshot at a time.

Dirty Notebook transitions use Save / Discard / Cancel decisions. Cancel aborts
the requested transition or Clear operation without partial teardown.

Deleting a Notebook coordinates cleanup of Workspace references under one
persistence fence.

## 21. Clear Research Suite

Clear Research Suite is an in-session reset. It does not delete persisted data.

After confirmation it:

- closes docked and detached charts;
- closes retained secondary Research windows;
- clears current Workspace identity;
- clears Notebook assignment;
- resets Pan Anchor OFF;
- restores Scroll 4;
- leaves the main Research Suite open;
- permits creation of new charts.

Cancelling the confirmation changes nothing.

A dirty Notebook Cancel decision aborts the entire Clear operation before
partial teardown.

## 22. Core task integration

All long-running and persistence Research operations share the application
`CoreRunner` and canonical `TaskManager`.

### Dataset operations

```text
research_dataset_catalog
research_dataset_load
research_resident_slice
```

### Study operations

```text
research_study_apply
research_study_artifact_apply
research_study_edit
research_study_save
```

### Study Environment operations

```text
research.study_setup.catalog
research.study_setup.environment_list
research.study_setup.environment_load
research.study_setup.environment_create
research.study_setup.environment_save
research.study_setup.environment_update
research.study_setup.environment_delete
research.study_setup.compatibility
```

### Workspace Snapshot operations

```text
research.workspace_snapshot.list
research.workspace_snapshot.load
research.workspace_snapshot.create
research.workspace_snapshot.update
research.workspace_snapshot.delete
research.workspace_snapshot.preflight
research.workspace_snapshot.notebook_assign
research.workspace_snapshot.notebook_unassign
```

### Notebook operations

```text
research.notebook.list
research.notebook.load
research.notebook.create
research.notebook.update
research.notebook.delete
```

Runtime Manager receives task IDs, names, progress, cancellation, status,
errors, correlation IDs, and operation metadata directly from TaskManager.

Fast GUI interactions such as pan, zoom, style mutation, pane resize,
visibility, focus, and detach/dock are correctly not represented as background
tasks.

Research launches no child operating-system processes, so ProcessManager is
correctly unused.

Composite operations such as Workspace restore appear as their real individual
load/apply tasks. There is currently no parent-child umbrella task hierarchy.

## 23. Window tracking and single-instance behavior

The production Research Suite and long-lived top-level secondary windows are
registered through `GuiWindowTracker` and Core `WindowRegistry`.

Tracked identities include:

```text
research_suite.window
research_restoration.new_chart_dialog
research_restoration.financial_tools.<slot>
research_restoration.study_edit.<slot>.<study_id>
research_restoration.studies_manager.<slot>
research_restoration.study_style.<slot>.<study_id>
research_restoration.go_to.<slot>
research.environment_save.<slot>
research.environment_manager.<active-slot-or-0>
research.workspace_snapshot_save
research.workspace_snapshot_manager
research.workspace_snapshot_preflight
research.notebook_manager
research.notebook_editor
research_restoration.detached_chart.<slot>
```

The registry records registered, open, focused, close-requested, and closed
state with timestamps.

Logical secondary windows are single-instance per required function/context.
Repeated actions focus or reuse the retained window instead of creating
uncontrolled duplicates.

Short-lived `QMessageBox` confirmation prompts are not separate durable runtime
windows.

## 24. Runtime data safety

The following are permanent user-data roots:

```text
historical_data/
study_environments/
workspace_snapshots/
research_notebooks/
```

Testing, packaging, Clear Research Suite, and Workspace replacement must not
clean, recreate, normalize, or delete these roots.

Tests use `tmp_path`, temporary directories, or injected stores.

## 25. Current deferred or separate work

The following are not Research freeze defects:

- final Data Manager GUI/user acceptance;
- application-wide Appearance Settings editor;
- parent-child grouping for composite Runtime Manager tasks;
- live OHLCV hot-reload into an already-open chart;
- Dynamic Binning in Research;
- Analysis/Trading workflows;
- arbitrary Research GUI redesign after visual freeze.

The Data Manager shares canonical Artifact and OHLCV services, but its complete
user lifecycle is documented and accepted separately.

## 26. Primary source map

Domain and application services:

```text
src/leonardo/research/application.py
src/leonardo/research/catalog.py
src/leonardo/research/dataset.py
src/leonardo/research/resident.py
src/leonardo/research/session.py
src/leonardo/research/workspace.py
src/leonardo/research/studies.py
src/leonardo/research/study_execution.py
src/leonardo/research/study_application.py
src/leonardo/research/study_setup.py
src/leonardo/research/study_setup_service.py
src/leonardo/research/study_setup_application.py
src/leonardo/research/study_environment.py
src/leonardo/research/study_environment_store.py
src/leonardo/research/workspace_snapshot.py
src/leonardo/research/workspace_snapshot_service.py
src/leonardo/research/workspace_snapshot_application.py
src/leonardo/research/workspace_snapshot_store.py
src/leonardo/research/notebook.py
src/leonardo/research/notebook_service.py
src/leonardo/research/notebook_application.py
src/leonardo/research/notebook_store.py
```

Financial and persistence authorities:

```text
src/leonardo/financial_tools/
src/leonardo/artifacts/
src/leonardo/ohlcv/
```

GUI:

```text
src/leonardo/gui/research/
src/leonardo/gui/presenters/research_chart_presenter.py
src/leonardo/gui/chart/
src/leonardo/gui/windows/study_environment_*.py
src/leonardo/gui/windows/workspace_snapshot_*.py
src/leonardo/gui/windows/research_notebook_*.py
src/leonardo/gui/composition.py
```

Primary tests:

```text
tests/research_test/
tests/gui_test/test_research_*.py
tests/gui_test/test_candlestick_widget.py
tests/gui_test/test_oscillator_study_scene.py
tests/gui_test/test_pane_workspace.py
tests/gui_test/test_study_scene.py
tests/gui_test/test_study_environment_*.py
tests/gui_test/test_workspace_snapshot_*.py
tests/gui_test/test_research_notebook_*.py
```
