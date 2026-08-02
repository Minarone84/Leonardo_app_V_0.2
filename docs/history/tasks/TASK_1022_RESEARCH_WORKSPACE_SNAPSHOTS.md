# Task 1022 Research Workspace Snapshots

Research Workspace Snapshots are versioned, canonical descriptions used to reconstruct a Research workspace through the existing dataset and Study application services. They do not serialize live Qt widgets, chart sessions, tasks, calculated arrays, DataFrames, crosshair state, window geometry, notebooks, or annotations.

## Authority

`ResearchWorkspaceSnapshotService` owns snapshot construction, canonical serialization, content hashing, persistence delegation, compatibility preflight, and append position planning. `ResearchWorkspaceSnapshotStore` is the only snapshot filesystem writer. `ResearchWorkspaceSnapshotApplicationService` submits persistence and preflight operations through the shared `CoreRunner`.

The suite presenter owns current workspace capture and live restore coordination. Dataset loading continues through `ResearchDatasetApplicationService`. Study reconstruction continues through embedded Task 1021 `StudyEnvironmentV1` values and the existing Study Environment Apply coordinator.

## Persisted State

Schema version `1.0` persists one to eight chart descriptions with canonical MarketIds, workspace positions, detached state, viewport center timestamp and visible count, autoscale or exact manual price bounds, volume visibility, pane sizes, and an optional embedded Study Environment. Logical slot IDs and session IDs are regenerated during restore.

Snapshot JSON uses UTF-8, sorted keys, compact separators, no non-finite values, and one final newline. The content hash is the lowercase SHA-256 of the canonical payload excluding `content_hash`.

## Restore Policy

Preflight validates capacity, accepted datasets, dataset loading, embedded Study Environment compatibility, artifact currency, pane references, and target workspace idleness before mutation.

Append preserves existing charts. Requested positions are retained when free and otherwise remapped to the lowest free position. Failure or cancellation removes only charts added by that restore run.

Append also captures the exact pre-run active slot and session, workspace mode, and Pan Anchor state. Failure or cancellation restores those values after removing added charts. An active identity is restored only when its original slot still owns the same session.

Replace captures an immutable in-memory rollback snapshot before clearing current charts. A target failure clears partial target charts and reconstructs the prior workspace. The rollback snapshot is never persisted. A rollback failure is reported as a degraded restore state.

Restore order per chart is dataset, embedded environment, viewport, price scale, volume, pane sizes, and detached shell state. Snapshot mode, Pan Anchor, and active chart are applied after all charts complete. Run, workspace generation, slot, session, and task identities reject stale callbacks.

Chart creation during restore is transactional across workspace membership, shell placement, chart widget construction, presenter publication, and signal wiring. A failure removes every partial layer before append rollback or replace reconstruction continues. Callbacks from prior runs are ignored; a callback for the current chart in the current run fails and settles the restore when its target is missing or its session has been replaced.

## GUI Boundary

The Save, Manager, and Preflight dialogs own only immutable display state and intents. They do not access the filesystem, snapshot store, dataset loader, ArtifactService, Core, or calculation functions. Valid and invalid snapshot deletion requires an explicit confirmation before one delete intent is emitted.

One restore run may exist per Research Suite. While it is active, the suite fences user chart creation, removal, movement, detach/dock, floating-window close, active selection, chart-view mutation, Study mutation, and Study Environment mutation. The Cancel action remains enabled. Coordinator-owned creation, view restoration, detach, activation, rollback, and finalization use private internal paths and remain operational.

Task 1022 does not add notebook, annotation, Data Manager, Analysis, Backtest, realtime, window-geometry, recipe-export, or collection behavior.
