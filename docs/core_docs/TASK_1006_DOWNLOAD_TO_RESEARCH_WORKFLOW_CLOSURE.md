# Task 1006 — Download-to-Maintenance-to-Research Workflow Closure

## Objective

Close the OHLCV Download-to-Acceptance workplan by proving the complete composed
workflow through the current Light V2 authorities and user-facing GUI shells.

```text
Historical Download
→ canonical CSV and sidecar persisted with validation_status="unknown"
→ OHLCV Maintenance discovery
→ canonical validation or explicit provider-backed repair
→ store-owned final validation evidence
→ Research catalog admission only when validation_status="ok"
→ full historical dataset load and chart preparation
```

## Scope

Task 1006 adds closure evidence only:

- a composed non-GUI vertical test using the real `LeonardoApp` composition;
- accepted and rejected Research-admission transitions;
- explicit repair-to-acceptance proof through the shared downloader lock;
- a composed Qt workflow test covering the actual Download, Maintenance and
  Research presenters/windows;
- a deterministic temporary-data visual smoke launcher;
- final workplan documentation.

No production service, validator, store, persisted schema, provider adapter,
Research implementation or GUI workflow required modification.

## Canonical-authority result

| Concern | Confirmed authority |
|---|---|
| Provider access and redownload | Connection / `HistoricalDownloadService` |
| Persisted CSV and sidecar writes | `OHLCVStore` |
| Final OHLCV quality truth | `CanonicalOHLCVValidator` |
| Maintenance orchestration | `OHLCVMaintenanceService` and application service |
| Long-running lifecycle | shared Core `TaskManager` / `CoreRunner` |
| Research admission | read-only `AcceptedDatasetCatalog` |
| Research loading | `HistoricalDatasetLoader` |
| User intent and presentation | existing GUI presenters and windows |

The closure tests do not create a second write path or validation authority.

## Proven happy path

1. Historical Download persists a complete dataset as `committed/unknown`.
2. Research catalog refuses it before canonical validation.
3. Maintenance validates it and publishes `validation_status="ok"` atomically.
4. Research catalog admits it.
5. Research loads the full dataset through the shared Core runtime.
6. The composed GUI reaches `Chart ready` through the real windows and
   presenters.

## Proven rejection and repair path

1. Historical Download persists a dataset containing a cadence gap.
2. Maintenance publishes a warning result, not false acceptance.
3. Research continues to exclude the dataset.
4. Maintenance creates an exact read-only repair plan.
5. The provider redownload supplies the reviewed missing range under the
   downloader dataset lock.
6. Store-owned repair persistence records provenance and resets validation.
7. Canonical post-repair validation publishes `repaired/ok`.
8. Research admits and loads the repaired dataset.

## Visual smoke

`tools/dev_launch_ohlcv_acceptance_workflow.py` launches the real composed GUI
with a deterministic local provider and a temporary historical-data directory.
It exercises:

- Historical Download request, preflight and execution;
- dedicated OHLCV Maintenance discovery and validation;
- Research catalog refresh and chart opening;
- shared task/runtime observability;
- no mutation of the user's real `historical_data`.

All smoke data is deleted when the launcher exits.

## Workplan closure

Tasks 1003–1006 now provide:

- canonical final validation;
- controlled validation-evidence publication;
- dedicated Maintenance GUI and presenter;
- explicit reviewed repair;
- end-to-end Download → Maintenance → Research proof;
- deterministic automated and user-visible acceptance evidence.

The OHLCV Download-to-Acceptance Completion Workplan is closed when the Task
1006 automated suite and temporary-data visual smoke pass on the active
repository.
