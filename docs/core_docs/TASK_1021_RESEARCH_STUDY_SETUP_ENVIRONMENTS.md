# Task 1021 Research Study Setup and Environments

Task 1021 adds chart-local Study setup and reusable Study Environments without
changing the calculation, artifact, rendering, workspace, or chart-shell
authorities established by Tasks 1014 through 1020.

## Authorities

Task 1014 `FinancialToolSpec` values are the only authority for the 26 setup
forms, parameter types, bounds, choices, source-family compatibility, and output
metadata. The setup GUI projects those immutable specifications and creates an
existing `StudyExecutionRequest` or `StudyArtifactRequest`.

Task 1017 remains the only runtime that calculates a Study or applies a saved
artifact. Study Environment application submits one Task 1017 request at a time;
it does not calculate, load artifacts, or publish Studies independently.

`ResearchStudySetupService` is the sole owner of Study Environment construction,
compatibility checks, and persistence coordination. `StudyEnvironmentStore` owns
the exact atomic JSON file operations. GUI widgets and dialogs receive immutable
projections and emit intents only.

## Semantic Metadata and Setup Intent

Every newly accepted `ChartStudy` retains its exact immutable setup request and
one `StudyUserMetadata` value. The metadata consists of `important`,
`dataset_role`, and `description`. It is semantic only and does not alter
calculation identity, artifact lineage, rendering identity, pane selection,
visibility, or dependency validation.

## Study Setup

The catalog contains all 26 canonical Financial Tools, the five canonical OHLCV
columns, analysis-usable outputs from current chart-local Studies, current saved
artifact outputs for the active `MarketId`, and explicit disabled rejection rows
for invalid or stale artifacts. Other-market artifacts are not exposed.
Saved Artifact source rows keep analysis-usable outputs selectable and show
non-analysis outputs plus stale or invalid artifacts as disabled rows with a
reason. Direct saved-artifact Apply remains unchanged.

Source roles follow the frozen Task 1021 schema. Ordinary tools have no explicit
source rows. Derivative and Angle use `source`; Delta uses `fast` and `slow`;
Braids, Braid Instability, and Trap Area use `fast`, optional `mid`, and `slow`;
the multi-source constructs use contiguous `source_1` through `source_n`; and UTC
uses either no source or the exact peak/trough pair.

## Study Environment Schema

`StudyEnvironmentV1` is a canonical immutable JSON schema. It persists only:

- ordered setup intent;
- environment-local topological dependencies;
- direct saved-artifact identities;
- expected output names;
- semantic Study metadata;
- Study visibility and line/fill styles.

It does not persist computed values, DataFrames, Study IDs, chart sessions,
generations, pane IDs, presentation revisions, chart slots, workspace positions,
detached state, viewport state, renderer state, or caches. Canonical JSON is
sorted, compact UTF-8 with no NaN. `content_hash` is the lowercase SHA-256 of the
full payload excluding the hash field.

Pure calculation and environment-local dependency entries may be checked
against another accepted market. Any direct artifact entry or artifact source is
bound to the environment's originating `MarketId` and must remain current and
valid for the exact target dataset.

## Persistence

The default environment directory is `<runtime-root>/study_environments` and is
not created by configuration. The store creates it on first write. One canonical
JSON file is written per environment. Create and update use a temporary file,
flush, filesystem sync, and atomic replacement. Display names are unique
case-insensitively. Invalid files remain visible as invalid summaries, while
load rejects them. Create, load, and update require canonical IDs. Delete may
also accept the exact raw stem of one listed invalid direct-child JSON file.
Delete targets only that exact environment file. Symlink, junction, traversal,
absolute, external, and path-escape targets are rejected.

## Apply and Rollback

One environment Apply run may be active per chart. Different charts may run
independently. Each run captures the target slot, session, generation, existing
Study IDs, environment ID, and a run ID. Environment-local entry IDs are mapped
only to newly accepted chart-local Study IDs. Every entry is submitted through
Task 1017 in topological order, then its exact metadata, visibility, and styles
are published.

Append retains old and new Studies. Replace retains all old Studies until every
new entry has succeeded, then removes the captured old Studies in reverse
dependency order. Failure or cancellation removes only the new Studies created
by that run in reverse order. A removed chart, reused slot, stale session, stale
task, or stale run cannot publish a result. Detach, dock, chart position, Go-to,
and Pan Anchor do not alter the run identity.

## Exclusions

Task 1021 adds no Workspace Snapshot, chart-shell persistence, notebook,
annotation, POI/PT marker, recipe export, collection, Data Manager, Analysis,
Backtest, realtime, cross-chart Study sharing, new Financial Tool, calculation
change, or dependency. Those remain outside this task and Tasks 1022 through
1025 retain their assigned scope.
