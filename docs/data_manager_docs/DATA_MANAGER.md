# Leonardo V2 Data Manager Suite

**Status:** Task 1064 closed after final combined native smoke; Data Manager
completion continues through Tasks 1065-1067
**Updated:** 2026-08-17
**Primary implementation:** `src/leonardo/data_manager/`,
`src/leonardo/recipes/`, `src/leonardo/artifacts/`,
`src/leonardo/gui/data_manager/`, the Data Manager presenter, and Data Manager
windows

## 1. Purpose and current status

The Data Manager Suite is Leonardo's persisted-product inspection, creation, and
update workspace.

It connects accepted OHLCV, Research Study Environments, portable Recipes,
managed Artifacts, Artifact Collections, Database Seeds, and immutable Database
revisions without transferring domain ownership into the GUI.

The production path is:

```text
Data Manager GUI intent
→ DataManagerSuitePresenter
→ DataManagerApplicationService
→ DataManagerService / creation workflow / update workflow
→ canonical OHLCV, Recipe, Artifact, and Data Manager stores
→ CoreRunner / TaskManager for long-running work
→ immutable result or read projection
→ queued Qt presentation
```

Current implementation status:

| Area | Status |
|---|---|
| Data Manager foundation and persistence | Implemented and accepted |
| Direct Artifact creation | Implemented and accepted |
| Saved Artifact Construct source eligibility | Implemented and accepted |
| Batch Constructs | Implemented and accepted |
| Autonomous reconciliation | Implemented and accepted |
| First-open foreground warm-up | Implemented and accepted |
| Responsive and maximized Suite layout | Implemented and accepted |
| Typed Catalog and Select Dataset sorting | Implemented and accepted |
| Task 1064 | **CLOSED** after final combined native smoke |
| Task 1065 - Study Environment to Recipes | Pending |
| Task 1066 - Recipes / Recipe Collection to Artifacts + Collection lineage | Pending |
| Task 1067 - final catalog-driven integration / Data Manager closure | Pending |

Task 1064 is closed. This does not close the complete Data Manager workplan;
Tasks 1065, 1066, and 1067 remain.

## 2. Scope and ownership

Data Manager coordinates persisted research products. It does not absorb the
meaning owned by adjacent Areas.

| Concern | Canonical authority |
|---|---|
| Market-series identity | `MarketId` |
| Accepted and rejected OHLCV evidence | OHLCV Area and accepted-dataset catalog |
| Full historical dataset loading | Research historical dataset loader |
| Study Environment persistence and meaning | Research |
| Portable Recipe semantic identity | Portable Recipe models and identity functions |
| Portable Recipe persistence and Collections | `PortableRecipeStore` |
| Financial Tool definitions and calculations | Financial Tools |
| Managed Artifact identity, lineage, values, versions, and heads | `ArtifactService` |
| Database Seeds, Artifact Collections, and Databases | `DataManagerCreationStore` |
| Creation workflow policy | `DataManagerCreationWorkflow` |
| Reconciliation and update policy | `DataManagerUpdateWorkflow` |
| Data Manager read projections and coordination | `DataManagerService` |
| Long-running execution and cancellation | `DataManagerApplicationService`, `CoreRunner`, and `TaskManager` |
| Selection, layout, visibility, and display state | Data Manager GUI |
| Long-lived window lifecycle | application `WindowRegistry` through GUI tracking |

The GUI does not scan persistence roots, open stored files, construct stores,
calculate Financial Tools, decide update modes, or publish revisions directly.
It emits intent and renders immutable projections returned by the application
service.

## 3. Production composition

`LeonardoApp` constructs one shared Data Manager composition:

```text
LeonardoApp
├── AcceptedDatasetCatalog
├── HistoricalDatasetLoader
├── ArtifactService
├── StudyEnvironmentStore
├── PortableRecipeStore
├── PortableRecipeGraphPlanner
├── DataManagerCreationStore
├── DataManagerService
└── DataManagerApplicationService
```

The GUI composition root creates and retains:

```text
DataManagerSuiteWindow
↔ DataManagerSuitePresenter
→ shared DataManagerApplicationService
```

No Data Manager window or presenter creates a second Core runtime, a second
store, or hidden service objects.

## 4. Runtime roots and persisted layout

Default production roots are configured by `AppConfig`.

| Persisted truth | Default root or authority |
|---|---|
| OHLCV and managed Artifact storage | `historical_data/` through OHLCV and Artifact authorities |
| Study Environments | `study_environments/` |
| Portable Recipes and provenance | `data_manager/recipes/` and `data_manager/recipe_provenance/` |
| Recipe Collections | `data_manager/recipe_collections/` |
| Artifact Collections | `data_manager/artifact_collections/` |
| Database Seeds | `data_manager/database_seeds/` |
| Database definitions and revisions | `data_manager/databases/` |

Portable Recipe, Collection, Seed, Artifact Collection, and Database stores
validate containment, reject unsafe links, and use canonical serialized models.
Immutable identities may be reloaded only when persisted bytes agree with that
identity. A conflicting payload is an identity collision, not an invitation to
overwrite history.

Runtime folders contain application data and are not source code. They must not
be committed as project implementation files.

## 5. Persisted product model

### 5.1 OHLCV datasets

OHLCV remains owned by the OHLCV Area. Data Manager consumes catalog evidence
including:

- canonical `MarketId` when identity is valid;
- exchange, market type, symbol, and timeframe;
- accepted or rejected state;
- persistence and validation status;
- row count;
- first and last data timestamp in UTC;
- source metadata;
- warnings, rejection codes, and rejection reasons.

Rejected or invalid entries remain inspectable. They cannot become an active
Data Manager target.

### 5.2 Portable Recipes

A `PortableRecipeV1` contains the semantic calculation definition:

- canonical Financial Tool key and version;
- kind;
- canonical parameters;
- declared outputs;
- canonical OHLCV input roles;
- dependency roles, Recipe identities, and dependency outputs.

The Recipe identity is content-derived. It does not include one origin market or
one Study Environment. Origin relationships are stored separately as provenance.
Dynamic Binning is explicitly excluded from portable Recipes.

### 5.3 Recipe Collections

A Recipe Collection revision records:

- Collection identity;
- immutable revision identity;
- display name and description;
- explicit root Recipe identities;
- complete member Recipe identities;
- previous revision identity;
- creation timestamp.

A mutable head selects the current immutable revision. Historical revisions
remain loadable.

### 5.4 Managed Artifacts

A managed Artifact has two distinct identities:

- a logical Artifact identity representing the market-specific calculation role;
- an immutable Artifact version identity representing exact persisted values,
  lineage, Recipe, source evidence, and version payload.

Artifact publication creates new immutable versions and advances the logical
head. Existing versions are not edited in place.

### 5.5 Artifact Collections

An Artifact Collection revision records the exact market-specific Artifact graph
used for Database publication, including roots, required supports, selected
outputs, Database column names, presentation order, lineage, and readiness
evidence.

Required support members remain locked. User-editable output selection and
Database column ordering must still produce a complete, unique, valid revision.

### 5.6 Database Seeds and Databases

A Database Seed records the intended market, OHLCV columns, range, and creation
metadata used to define Database input.

A Database has:

- an immutable definition;
- immutable revision manifests;
- immutable revision values;
- a mutable head identifying the current revision.

Publishing an initial revision, appending, or rebuilding always creates a new
revision. Previous revisions remain available.

## 6. Data Manager Suite shell

The Data Manager Suite is a tracked single-instance window:

```text
data_manager_suite.window
```

Repeated open commands reuse and focus the existing window. Closing the Suite
stops its reconciliation scheduling, closes bounded child windows, requests
cancellation of active Data Manager work, and disposes the presenter.

The first-created Suite opens maximized with normal desktop chrome. Reopening
the same Suite preserves the user's current maximized or restored state and
geometry.

The Suite currently contains:

```text
Header and active Market summary
Actions
├── Refresh
├── Select Dataset
├── Preview Dataset
├── Preview Artifact
├── Validate Artifact
├── Create Artifact...
├── Batch Constructs...
├── Delete Artifact
└── Delete Recipe

Tabs
├── Catalogs
├── Create Database
└── Update & Reconcile

Shared operation surface
```

The responsive body uses these canonical stretch relationships:

```text
Workspace : Operation = 3 : 1
upper : bottom = 7 : 3
Inspector : Revision History = 1 : 1
```

The Inspector and Revision History form one full-width bottom strip. Major
panels and tables expand with the Suite; no old fixed right rail is retained.

The shared operation surface displays the operation name, TaskManager identity,
state, progress, messages, structured details, terminal result, terminal error,
and cancellation availability. It is the only live Data Manager progress,
task-state, cancellation, and operation authority.

## 7. Active OHLCV dataset selection

### 7.1 Dedicated selector

The complete OHLCV catalog and OHLCV-specific filters are confined to the
tracked selector window:

```text
data_manager.dataset_selector.window
```

The selector is created once per Data Manager Suite instance. Repeated open
commands reuse and focus it. Closing the Data Manager Suite closes the selector.

The search-help dialog is a bounded modal child of the selector. It is reused by
the selector and closes with it; it does not own an independent application
runtime or store.

### 7.2 Dataset table

The selectable dataset table displays:

```text
Exchange
Market Type
Symbol
Timeframe
Status
Persistence
Validation
Rows
First Data UTC
Last Data UTC
Details
```

Timestamps are rendered in human-readable UTC. Columns are sized from their
headers and visible contents. Horizontal scrolling is used when the complete
content exceeds the viewport.

Accepted and rejected entries remain visible. `Select` is enabled only when the
chosen row is accepted and has a valid canonical `MarketId`.

No row is silently selected when the selector first opens without an active
market.

The full multi-row table supports user-triggered typed sorting for text,
numbers, and canonical UTC values. Sorting is presentation-only, keeps blank
values after populated values in either direction, and preserves the selected
`MarketId`. The one-row Active Dataset table is not sortable.

### 7.3 Cascading dropdown filters

The four dropdowns form a strict left-to-right chain:

```text
Exchange
→ Market Type constrained by Exchange
→ Symbol constrained by Exchange + Market Type
→ Timeframe constrained by Exchange + Market Type + Symbol
```

Each menu contains `All` plus only values that exist for the selected upstream
combination. When an upstream value changes:

- valid downstream selections are preserved;
- invalid downstream selections reset to `All`;
- the visible dataset table is rebuilt after the chain is consistent.

The controls use content-derived minimum widths and expand proportionally across
the selector. A narrow value such as `1h` does not force a tiny Timeframe field.

### 7.4 Global All reset

The selector's `All` button:

- resets Exchange, Market Type, Symbol, and Timeframe to `All`;
- clears both text-search fields;
- restores the complete dataset catalog;
- preserves the active-dataset highlight when possible.

### 7.5 Text search

Two labelled text fields supplement the dropdown chain.

`Dataset ID / State` searches:

- complete or partial canonical `MarketId`;
- accepted or rejected state;
- persistence status;
- validation status.

`Source / Warning / Reason` searches:

- source metadata;
- warning text;
- rejection code;
- rejection reason.

Searches are case-insensitive and accept partial text. Both fields combine with
one another and with the dropdown filters using `AND`. They filter only the
visible catalog and never modify data.

The `?` button opens `Dataset Search Help`, which provides one example for each
field and a legend built from terms actually present in the current catalog.

### 7.6 Active Dataset table

When an active market exists, a one-row `Active Dataset` table appears above the
selectable catalog. It uses the same columns and formatting as the catalog but
is read-only and non-selectable.

When no active dataset exists, the label and table are hidden completely. No
placeholder rectangle or explanatory empty-state text is retained.

### 7.7 Selection and Research handoff

Selecting an accepted dataset:

```text
selector MarketId
→ existing Data Manager market_selected signal
→ presenter market inspection
→ selected Market summary
→ selected-market Recipe and Artifact projections
→ creation target synchronization
```

Research handoff carries only the canonical `MarketId`. Data Manager reloads its
own persisted truth, focuses that market, and highlights the same row when the
selector opens.

Changing the active market invalidates stale creation or update context. The GUI
does not submit execution using a plan prepared for another market.

## 8. Catalogs tab

The main Catalogs workspace now exposes seven non-OHLCV product families:

```text
Study Environments
Recipes
Recipe Collections
Artifacts
Artifact Collections
Database Seeds
Databases
```

OHLCV is intentionally absent from this family list because complete dataset
browsing and selection live in the dedicated selector described in section 7.
The backend product snapshot still includes OHLCV catalog evidence.

The Catalogs workspace contains:

- family navigation;
- one family-specific table;
- current-object inspection;
- immutable revision or version history where supported.

Invalid or rejected products remain visible with textual reasons. Selecting a
historical row loads that exact immutable object through its canonical service;
it does not replace persisted head state.

The central family table supports typed presentation-only sorting through
`sort_data_manager_rows(...)`. Text is case-insensitive, numbers use numeric
order, and canonical UTC values use chronological order. Blank values stay
after populated values in both directions. Sort state is retained per family,
and row-to-domain identity moves with the displayed projection so selection,
Inspector content, and revision history remain associated with the same object.
Inspector and Revision History are not sortable through this behavior.

### 8.1 Direct Artifact creation

`Create Artifact...` starts from the selected accepted OHLCV dataset:

```text
selected accepted OHLCV
→ Create Artifact
→ canonical Financial Tool configuration
→ global Recipe create/reuse
→ managed Artifact materialization
→ immutable/current publication
→ catalog refresh
```

There is no Research-style Apply step. `Calculate Artifact` means calculation
plus durable publication or reuse. Recipe identity is global and does not
include `MarketId`; managed Artifact identity is specific to the market and
accepted source fingerprint. Direct creation does not automatically create an
Artifact Collection.

Construct saved-source eligibility is defined by
`src/leonardo/financial_tools/construct_input_eligibility.json`. Eligible
numeric outputs from saved Artifacts may feed Constructs through that canonical
authority and the canonical saved-Artifact source catalogue. Dynamic Binning
remains excluded from Financial Tools Constructs and is not a Data Manager
Construct.

### 8.2 Batch Constructs

`Batch Constructs...` provides these scopes:

```text
Selected Signals
All Indicators
All Oscillators
All Constructs
```

Automatic family scopes use saved Artifact outputs only. The accepted lifecycle
is:

```text
select sources and Construct configuration
→ Preview
→ reviewed BatchArtifactPlan
→ Execute
→ terminal report
```

Preview displays `Source(s)`, `Construct`, `Parameters`, `Inputs`, and `Result`.
Result values include `New` and `Reuse Current`.

The only raw current-dataset inputs are `Open`, `High`, `Low`, and `Close`,
bound to the selected accepted OHLCV dataset and its exact fingerprint. Raw
Volume is prohibited. Volume becomes eligible only through the normal saved
Artifact route after a Volume Artifact exists. Raw OHLC inputs create no fake
Artifact identity or lineage: Recipe bindings may reference canonical OHLCV
inputs, while only saved Artifact dependencies become Artifact lineage
dependencies.

The Suite Operation surface remains the only live progress, task-state,
cancellation, and operation authority. Batch owns no second progress lifecycle.
Its local terminal report includes reviewed-plan-derived counts such as branches
completed, `New`, and `Reuse Current`; that report closes independently while
the Batch window remains open. Successful execution invalidates Preview, so a
new Preview is required before another Execute.

## 9. Creation workflow

The Create Database tab is an explicit nine-stage workspace:

1. **Target OHLCV**
2. **Database Seed**
3. **Study Environments**
4. **Recipes**
5. **Base Artifacts**
6. **Batch Artifacts**
7. **Artifact Collection**
8. **Database Review**
9. **Build Database**

### 9.1 Target OHLCV

Creation begins only from the current accepted active market. Selecting a market
in the selector does not itself publish or calculate anything.

### 9.2 Database Seed

The user may select an existing Seed or create a new Seed with explicit columns,
range, display name, and description. Seed validation remains a domain
responsibility.

### 9.3 Study Environment and Recipe sources

Recipe roots may come from:

- explicit Study Environment entry derivation;
- one direct portable Recipe;
- one Recipe Collection revision;
- multiple explicit portable Recipe root identities.

Environment derivation is an optional source, not a mandatory gateway to the
portable Recipe library.

### 9.4 Planning and execution

Planning is read-only. It returns dependency order, reuse decisions, create or
update decisions, compatibility evidence, and blockers.

Execution requires:

- the current plan;
- no blockers;
- the same market and selected source context that produced the plan;
- no active conflicting Data Manager operation.

A context change clears stale plan readiness and disables execution.

### 9.5 Base and batch Artifacts

Base materialization follows the complete dependency-safe Recipe graph.
Dependencies are published before their dependents.

Batch branches are explicit. The GUI obtains available Financial Tool choices
from the canonical specification authority. The backend validates parameters,
source compatibility, output collisions, dependency roles, and blockers.

There is no implicit `Update Everything` or automatic addition of arbitrary
branches.

### 9.6 Artifact Collection revision

The user explicitly chooses logical Artifacts and outputs, assigns unique
Database column names, and provides complete presentation order. Required
support members remain present and locked.

Creating or revising the Collection publishes a new immutable Collection
revision.

### 9.7 Database review and publication

Readiness review reports blockers, selected columns, row count, coverage, source
identity, Seed identity, Collection revision, and publication mode.

Publication requires explicit confirmation. Cancelling the confirmation submits
no operation.

## 10. Managed Artifact materialization

Artifact materialization resolves one portable Recipe graph for one canonical
market.

The workflow:

```text
portable Recipe roots
→ complete dependency graph
→ target OHLCV and dependency source resolution
→ calculation in dependency order
→ validation of outputs and lineage
→ prepared immutable Artifact versions
→ atomic graph publication
→ logical Artifact head updates
```

Internal calculation precision is preserved. Data Manager does not round
persisted values merely for display convenience.

A failed or cancelled graph publication does not intentionally expose a partial
new head set. Existing immutable versions remain available.

## 11. Update and reconciliation

The Update & Reconcile tab contains six stages:

1. **Source Change Review**
2. **Artifact Update Plan**
3. **Artifact Execution**
4. **Collection Validation**
5. **Database Append or Rebuild Preview**
6. **Commit Database Revision**

### 11.1 Reconciliation

Reconciliation creates a read-only snapshot covering:

- OHLCV source changes;
- managed Artifact currentness;
- Artifact Collection currentness;
- Database currentness;
- bounded failures and reasons;
- an evidence signature.

Source-change statuses include unchanged, append-only, historical mutation,
truncation, invalid source, and identity mismatch conditions.

Reconciliation never updates Artifacts or Databases by itself.

### 11.2 Artifact updates

Artifact updates remain separate from Database updates.

A reviewed Artifact Collection update plan contains:

- exact starting Collection revision;
- current Artifact heads;
- source evidence;
- dependency-safe execution stages;
- node actions such as reuse, update, or blocked;
- context and revisable-tail requirements;
- blockers.

The Artifact execute button is enabled only for the current, unblocked plan whose
Collection matches the current GUI selection. Busy-state changes or a different
selection must not make a blocked or stale plan executable.

Successful execution publishes new immutable Artifact versions and a new
Artifact Collection revision. Old Artifact and Collection revisions remain
available.

### 11.3 Database planning

A Database update plan has one mode:

```text
CURRENT
APPEND
REBUILD_REQUIRED
BLOCKED
```

`APPEND` is permitted only when accepted source and Collection evidence preserve
the exact existing Database prefix and compatible schema.

Rebuild may be required by historical mutation, truncation, source identity
mismatch, Collection change, schema change, or prefix mismatch. The plan must
report the actual cause; the GUI must not replace it with one generic invented
reason.

### 11.4 Append and rebuild

Append executes only a matching accepted `APPEND` plan.

Rebuild executes only a matching accepted `REBUILD_REQUIRED` plan after explicit
confirmation. The confirmation identifies the current Database revision, actual
plan status, available source-change status and reason, target Collection
revision, and the fact that publication creates a new immutable revision while
preserving prior revisions.

Artifact updates never mutate old Database revisions. Database updates never
trigger hidden Artifact updates.

## 12. Initialization and reconciliation lifecycle

### 12.1 Deterministic first-open warm-up

A newly created Suite performs one foreground initialization sequence:

```text
open Data Manager
→ Suite appears
→ Loading Data Manager
→ foreground reconcile_status(force=False)
→ foreground product catalog scan
→ catalogs applied
→ warm-up complete
→ evidence baseline established
→ normal silent background reconciliation
```

The first product catalog scan follows successful initial reconciliation.
Warm-up completes only after valid product catalogs are applied. The existing
Suite Operation surface presents this foreground work without invented progress
percentages. A failed warm-up stays visible and manually retryable; Refresh
retries foreground initialization with `force=True`.

### 12.2 Post-warm-up background reconciliation

After successful warm-up, reconciliation is autonomous, asynchronous,
non-blocking, and independent of foreground Operation ownership. It uses the
shared Core runtime and creates no second executor, thread pool, task registry,
or GUI progress authority.

Unchanged evidence avoids unnecessary scans and GUI churn. Changed evidence
drives the required market and catalog refresh. Late-result fencing,
coalescing, and pending `MarketId` catch-up prevent stale or duplicate results
from replacing current state. Successful publication may trigger background
synchronization while its foreground terminal report remains visible.

## 13. Operations and cancellation

All long-running Data Manager work uses the shared Core runtime.

Representative TaskManager operation identities include:

```text
data_manager.scan_product_catalogs
data_manager.inspect_study_environment
data_manager.inspect_portable_recipe
data_manager.list_recipe_collection_revisions
data_manager.scan_managed_artifacts
data_manager.reconcile_status
data_manager.plan_artifact_collection_update
data_manager.execute_artifact_collection_update
data_manager.plan_database_update
data_manager.execute_database_append
data_manager.execute_database_rebuild
```

Only one Data Manager operation slot is exposed through the Suite. While busy,
conflicting actions and selector mutation controls are disabled.

Cancellation is cooperative. The application service requests cancellation and
reports cancellation as complete only after TaskManager settles the task.
Publication gates may reject a late cancellation after the operation has entered
its non-interruptible publication boundary.

## 14. Window lifecycle and tracking

Long-lived Data Manager windows are registered through the shared application
window tracker.

| Window | Identity | Lifecycle |
|---|---|---|
| Data Manager Suite | `data_manager_suite.window` | Single instance, reused and focused |
| Select OHLCV Dataset | `data_manager.dataset_selector.window` | One per Suite, reused and closed with Suite |

Bounded previews and confirmation dialogs are child windows. The Dataset Search
Help dialog is a reusable modal child of the selector and cannot outlive it.

Closing the Suite:

- stops its background reconciliation scheduling;
- closes the dataset selector and bounded previews;
- requests cancellation of active Data Manager work;
- disposes the presenter;
- leaves final application shutdown authority with `LeonardoApp` and Core.

## 15. Restart and historical inspection

Restart reconstructs current catalogs from canonical persistence.

Durable state includes:

- portable Recipes and provenance;
- Recipe Collection revisions and heads;
- managed Artifact versions and heads;
- Database Seeds;
- Artifact Collection revisions and heads;
- Database definitions, revision manifests, values, and heads.

Exact historical Recipe Collection, managed Artifact, Artifact Collection, and
Database revisions remain loadable. Selecting a historical row is an inspection
operation only; it does not move the persisted head.

## 16. Destructive actions and confirmations

Destructive actions remain explicit and backend-gated.

Current GUI actions include Artifact and Recipe deletion where the canonical
service permits deletion. Referenced or in-use objects may be refused by the
backend.

There is no dataset deletion from Data Manager, no automatic repair, no silent
rebuild, and no command that updates every product indiscriminately.

Database publication and rebuild use explicit confirmation. Cancelling a
confirmation submits no operation.

## 17. Completion and workplan position

Task 1064 is **CLOSED** after the final combined native smoke.

Remaining Data Manager work is limited here to the accepted task identities:

```text
1065 - Study Environment → Recipes
1066 - Recipes / Recipe Collection → Artifacts + Collection lineage
1067 - final catalog-driven integration / Data Manager closure
```

This document does not define or anticipate detailed semantics for Tasks
1065-1067. The Data Manager Area is not yet closed.

## 18. Validation and acceptance

Automated validation covers:

- domain models and stores;
- portable Recipe identity and graph planning;
- managed Artifact publication;
- creation and update workflows;
- GUI architecture boundaries;
- Data Manager presenter behavior;
- window tracking;
- stale-plan gating;
- operation reports;
- dataset selector filtering, sizing, active-row behavior, search help, and
  typed sorting;
- Direct Artifact creation and global Recipe reuse;
- Batch Construct planning, execution, and terminal reporting;
- deterministic first-open warm-up and autonomous background reconciliation;
- responsive Suite layout and central Catalog typed sorting.

Task 1064's final combined native smoke passed. Future Data Manager functional
acceptance continues through Tasks 1065, 1066, and 1067. The current smoke
authority is
[`LIGHT_V2_APPLICATION_SMOKE.md`](../gui_docs/LIGHT_V2_APPLICATION_SMOKE.md).

## 19. Primary source map

### Domain and application

```text
src/leonardo/data_manager/models.py
src/leonardo/data_manager/service.py
src/leonardo/data_manager/application.py
src/leonardo/data_manager/artifact_materialization.py
src/leonardo/data_manager/direct_artifact.py
src/leonardo/data_manager/construct_sources.py
src/leonardo/data_manager/construct_batch.py
src/leonardo/data_manager/creation_models.py
src/leonardo/data_manager/creation_store.py
src/leonardo/data_manager/creation_service.py
src/leonardo/data_manager/update_models.py
src/leonardo/data_manager/update_service.py
```

### Portable Recipes and Artifacts

```text
src/leonardo/recipes/identity.py
src/leonardo/recipes/models.py
src/leonardo/recipes/planner.py
src/leonardo/recipes/store.py
src/leonardo/financial_tools/construct_input_eligibility.json
src/leonardo/artifacts/identity.py
src/leonardo/artifacts/models.py
src/leonardo/artifacts/service.py
```

### GUI and composition

```text
src/leonardo/gui/presenters/data_manager_presenter.py
src/leonardo/gui/windows/data_manager_suite_window.py
src/leonardo/gui/windows/data_manager_dataset_selector_dialog.py
src/leonardo/gui/windows/data_manager_preview_dialog.py
src/leonardo/gui/windows/data_manager_artifact_creation_dialog.py
src/leonardo/gui/windows/data_manager_construct_batch_dialog.py
src/leonardo/gui/data_manager/catalogs.py
src/leonardo/gui/data_manager/table_presentation.py
src/leonardo/gui/data_manager/creation.py
src/leonardo/gui/data_manager/update.py
src/leonardo/gui/data_manager/operations.py
src/leonardo/gui/data_manager/reconciliation.py
src/leonardo/gui/composition.py
src/leonardo/core/app.py
src/leonardo/core/config.py
```

### Principal tests

```text
tests/data_manager_test/
tests/data_manager_test/test_direct_artifact_creation.py
tests/data_manager_test/test_construct_source_catalog.py
tests/data_manager_test/test_construct_batch.py
tests/recipes_test/
tests/artifacts_test/test_managed_artifact_versions.py
tests/gui_test/test_data_manager_catalogs.py
tests/gui_test/test_data_manager_creation_complete_vertical.py
tests/gui_test/test_data_manager_update_complete_vertical.py
tests/gui_test/test_data_manager_reconciliation_lifecycle.py
tests/gui_test/test_data_manager_revision_history.py
tests/gui_test/test_data_manager_operation_reports.py
tests/gui_test/test_data_manager_dataset_selector_dialog.py
tests/gui_test/test_data_manager_artifact_creation_dialog.py
tests/gui_test/test_data_manager_construct_batch_dialog.py
tests/gui_test/test_data_manager_table_presentation.py
tests/gui_test/test_data_manager_suite_window.py
tests/gui_test/test_data_manager_integration.py
tests/gui_test/test_data_manager_static.py
```
