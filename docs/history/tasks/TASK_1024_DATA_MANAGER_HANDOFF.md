# Task 1024 Data Manager Catalog and Research Handoff

Data Manager projects canonical persisted truth owned by `AcceptedDatasetCatalog`,
`HistoricalDatasetLoader`, and `ArtifactService`. It creates no competing store,
filesystem path, validation authority, or deletion path.

The suite displays accepted and rejected OHLCV catalog entries. For one selected
accepted `MarketId`, it lists recipes and artifacts, provides bounded immutable
dataset and artifact previews, validates current artifact lineage without repair,
and delegates exact confirmed artifact or unused-recipe deletion to
`ArtifactService`. Dataset deletion, database materialization, collections, batch
calculation, metadata editing, and artifact update are outside this workflow.

Research hands off only the active chart's canonical `MarketId`. Data Manager then
reloads catalog, recipe, and artifact truth from canonical persistence. No dataset,
array, DataFrame, Study, notebook, snapshot, widget, session, artifact object, or
filesystem path crosses the handoff boundary.

Every accepted Research focus starts an explicit persistence inspection, including
focus on the already selected market. Unavailable focus clears the selected market,
object catalogs, and destructive actions. Artifact preview, validation, artifact
deletion, and recipe deletion re-scan `AcceptedDatasetCatalog` immediately before
calling `ArtifactService`; rejected or missing markets make no artifact-service call.

Presentation models reject filesystem paths and live runtime objects, require text
for display fields, reject booleans in integer fields, and accept only timezone-aware
creation timestamps normalized to UTC. A successful exact deletion publishes an
immutable deleted-object identity first. The presenter removes that identity from
its current immutable snapshot and then performs a separate non-destructive market
refresh. Refresh failure does not undo or reinterpret the committed deletion.

Deletion remains cancellable while canonical market acceptance is being checked.
The application closes its cancellation gate atomically after that fresh check and
immediately before the exact `ArtifactService` delete call. Cancellation that wins
before the gate prevents a continuing worker from publishing a deletion; cancellation
after the gate is refused because canonical deletion has begun.

Rejected or missing canonical markets raise the internal
`DataManagerMarketUnavailableError`. A current inspection, preview, validation, or
pre-commit deletion that settles with this error clears stale selected market and
object actions while retaining catalog rows. Ordinary preview and lineage failures
preserve selection. A post-commit refresh failure continues to preserve and report
the already committed deletion.

`DataManagerApplicationService` runs operations through the shared `CoreRunner`.
The presenter permits one active operation, fences task and selection generations,
retains only the latest pending Research focus, and ignores results after disposal.
