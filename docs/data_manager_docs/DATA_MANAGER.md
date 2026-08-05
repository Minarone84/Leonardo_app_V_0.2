# Data Manager

The Data Manager Suite is Leonardo's GUI for inspecting persisted research
products and for creating or updating immutable analysis databases. It uses the
shared Core runtime for long operations and delegates all domain decisions to
the existing OHLCV, Research, Portable Recipe, Financial Tools, Artifact, and
Data Manager authorities.

## Authority Map

| Truth | Authority |
|---|---|
| Market identity | `MarketId` |
| Accepted OHLCV and source evidence | OHLCV Area |
| Study Environments | Research |
| Portable Recipes and Recipe Collections | Portable Recipe authority |
| Financial Tool definitions and calculations | Financial Tools |
| Managed Artifact identity, values, lineage, versions, and heads | `ArtifactService` |
| Seeds, Artifact Collections, and Databases | Data Manager creation authority |
| Reconciliation and update planning | Data Manager update authority |
| Background execution, progress, and cancellation | `CoreRunner` and `TaskManager` |
| Window selection and display state | GUI |

The GUI does not scan directories, open persisted files, construct stores, or
calculate financial values. It receives immutable read projections from
`DataManagerApplicationService`.

## Runtime Roots And Catalogs

Configured Leonardo runtime roots hold accepted OHLCV, Study Environments,
Portable Recipes, managed Artifacts, Artifact Collections, Database Seeds, and
Database definitions and revisions. Their configured stores remain the only
persistence authorities. Automated tests use temporary roots.

The Catalogs tab exposes eight families: OHLCV, Study Environments, Portable
Recipes, Recipe Collections, Managed Artifacts, Artifact Collections, Database
Seeds, and Databases. Invalid or rejected objects remain visible with textual
reasons. Catalog scans are bulk, Core-supervised reads and do not load full
Artifact or Database values merely to populate tables.

OHLCV rows preserve accepted and rejected dataset evidence and bounded preview.
Study Environment inspection reports every entry's portability, dependencies,
and derivable Recipe identity. Portable Recipe inspection shows canonical
parameters, bindings, dependencies, outputs, provenance, origin environments,
and origin markets. Recipe Collection, Artifact Collection, managed Artifact,
and Database inspectors retain immutable revision or version history and permit
exact historical inspection through their canonical services. Selecting a
historical row displays that exact immutable object while current inspection
remains separate. Database history uses revision manifests without loading full
values.

## Creation Workflow

Creation is an explicit nine-stage workflow:

1. Select one accepted target OHLCV.
2. Create or select a Database Seed with explicit columns and range.
3. Inspect Study Environments and select root entries.
4. Derive, persist, select, or collect portable Recipes.
5. Plan and execute the base managed Artifact DAG.
6. Plan and execute explicit batch branches.
7. Create, load, validate, or revise an Artifact Collection.
8. Validate Database readiness and inspect blockers, coverage, rows, and columns.
9. Confirm and publish the first or permitted next immutable Database revision.

No catalog's first row is selected silently. Planning never persists. Execution
requires the current unblocked plan, an exact match with the GUI context that
produced it, and one free Data Manager operation slot. A Market, Recipe,
Collection, branch, Seed, or Database context change clears stale planning or
readiness and disables execution.

Portable Recipe-library mode accepts one or more explicit canonical root IDs.
Those roots can create or update a Recipe Collection without first deriving an
Environment; Environment derivation remains an alternative source. Artifact
Collection revision editing validates each selected logical Artifact, output,
unique Database column name, and complete presentation order before submitting
the existing revision operation. Required support members remain locked.
The batch branch table obtains Financial Tool choices from the canonical
specification authority; the backend remains authoritative for compatibility,
parameters, outputs, collisions, and blockers.

## Update And Reconciliation

The Update & Reconcile tab has six stages: Source Change Review, Artifact Update
Plan, Artifact Execution, Collection Validation, Database Append or Rebuild
Preview, and Commit Database Revision.

Reconciliation reports source, Artifact, Collection, and Database currentness,
including append-only changes and historical mutation. Artifact updates remain
separate from Database updates. An append executes only an accepted `APPEND`
plan. A rebuild executes only an accepted `REBUILD_REQUIRED` plan after explicit user
confirmation. Both publish a new immutable Database revision and preserve prior
revisions. Append and rebuild controls are mode-specific and require the
selected Database to match the reviewed plan.

Artifact update completion populates Collection Validation with the exact new
Collection revision, roots, supports, selected outputs, coverage, and Database
readiness. Database update completion populates Commit Database Revision with
mode, current and previous revision identities, Collection revision, rows,
columns, coverage, and values hash. Automatic reconciliation preserves both
terminal reports.

Reconciliation runs once after the GUI is shown, once when the Suite opens,
after manual Refresh, every 60 seconds while the window is open and idle, and
after successful publications. Timer ticks skip active work and never overlap.

## Operations, Restart, And Limits

One shared operation surface displays operation name, TaskManager task ID,
state, progress, messages, structured details, terminal result, and terminal
error. Successful publication reports survive the automatic reconciliation and
catalog refresh that follows them. Cancellation is requested through the shared
application service and is reported as complete only after TaskManager settles
the task as cancelled. Publication gates may refuse late cancellation.

The Data Manager Suite is a tracked single-instance window. Closing it stops
its timer, requests cancellation of its one active operation, and closes bounded
previews. Application shutdown supervises remaining Data Manager work through
the shared Core runtime.

Seeds, portable Recipe and Recipe Collection revisions, managed Artifact
versions, Artifact Collection revisions, Database definitions, and Database
revision manifests are durable. Restart reconstructs catalogs from canonical
persistence. Exact historical revisions remain loadable and are never replaced
by current-head display state.

The supported model includes dependency-safe Artifact materialization, explicit
batch branches, immutable Collection and Database revisions, append planning,
explicit rebuild planning, structured reconciliation, bounded previews, and
exact destructive actions where the backend permits them. There is no Update
Everything command, dataset deletion, automatic repair, or silent rebuild. The
final native Windows acceptance smoke remains separate from automated
pre-smoke validation.

Database publication confirmation identifies the Database, Market, Seed,
Artifact Collection revision, rows, columns, coverage, and selected columns.
Rebuild confirmation identifies why append is unsafe and states that a new
immutable revision leaves prior revisions unchanged. Cancelling either dialog
submits no operation.
