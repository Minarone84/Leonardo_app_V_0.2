# Task 1008 — Controlled OHLCV Dataset Deletion

## Task identity

```text
Task ID: 1008
Task name: Controlled OHLCV Dataset Deletion
Parent workplan: OHLCV Maintenance completion follow-up
Implementation owner: Rick-authorised direct implementation
Baseline: main @ 802e754
```

## Objective

Allow the user to permanently delete one selected canonical OHLCV dataset through
Maintenance without giving the GUI direct filesystem authority or allowing a stale
confirmation to delete replacement data.

## Accepted workflow

```text
select one discovered dataset
→ prepare exact stable CSV and sidecar evidence
→ show exact paths in an explicit destructive confirmation
→ acquire the shared per-MarketId OHLCV operation lock
→ verify the reviewed evidence is still current
→ stage and remove only candles.csv and candles.meta.json
→ remove only empty canonical parent directories
→ invalidate the matching Research loader cache entry
→ audit the destructive result
→ refresh Maintenance discovery
```

## Canonical authorities

- `OHLCVStore` owns exact physical deletion and canonical path cleanup.
- `OHLCVMaintenanceService` owns deletion planning, result semantics, and audit intent.
- `OHLCVDatasetOperationLocks` serializes download, repair, and deletion for one `MarketId`.
- `HistoricalDatasetLoader` owns its read-only Research cache and serializes invalidation with active loads.
- The presenter coordinates confirmation and result display.
- The GUI owns no filesystem, cache, or deletion logic.

## Safety rules

- Deletion requires an existing canonical `candles.csv`.
- A missing sidecar is allowed; no sidecar is invented.
- Exact size, modification time, and SHA-256 evidence are captured before confirmation.
- Any CSV or sidecar change after planning rejects the deletion as stale.
- The Store stages reviewed files before cleanup and restores already staged files if
  staging the pair fails.
- Unrelated files in the dataset directory are never deleted.
- Empty directories are removed only inside the canonical historical root.
- Once confirmed deletion mutation starts, GUI cancellation is disabled and late Core
  cancellation cannot falsely report a cancelled task while filesystem mutation continues.

## Explicit non-goals

- batch deletion;
- deletion of orphan sidecars without a CSV;
- automatic deletion based on validation status;
- cascade deletion of artifacts, recipes, databases, studies, or workspaces;
- active Research session disposal;
- sidecar reconstruction;
- source correction;
- remote push or pull-request integration.

## Validation

Automated coverage includes:

- exact reviewed file deletion;
- stale CSV rejection;
- optional missing sidecar;
- preservation of unrelated directory content;
- audit evidence;
- Research cache invalidation, active-load serialization, and catalog exclusion;
- honest completion when cancellation arrives after mutation starts;
- one shared operation-lock authority in the composition root;
- presenter confirmation and post-delete discovery refresh;
- static GUI shell boundary checks;
- existing validation, repair, download, and Research workflow regression coverage.

Manual smoke command:

```powershell
python tools/dev_launch_ohlcv_deletion.py
```
