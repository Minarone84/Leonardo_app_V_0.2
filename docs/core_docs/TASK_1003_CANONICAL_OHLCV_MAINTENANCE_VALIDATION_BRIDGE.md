# Task 1003: Canonical OHLCV Maintenance Validation Bridge

## Task identity

```text
Task ID: 1003
Task name: Canonical OHLCV Maintenance Validation Bridge
Implementation agent: Rick-authorised direct implementation
Parent workplan: OHLCV Download-to-Acceptance Completion Workplan
Decision entropy: Frozen for task
Baseline: main at 900b87e
```

## Objective

Complete the missing logical bridge between persisted Historical Download output
and Research admission without adding GUI validation logic or repair behaviour.

```text
Download persists CSV and sidecar with validation_status="unknown"
→ OHLCV Maintenance discovers the dataset
→ canonical read-only validation runs
→ OHLCVStore publishes final sidecar evidence atomically
→ Research admits only current validation_status="ok" evidence
```

## Included scope

- canonical OHLCV final validator and typed report models;
- canonical dataset discovery for Maintenance;
- fixed-timeframe and calendar-month cadence validation;
- strict schema, timestamp, numeric, OHLC and volume checks;
- sidecar identity, persistence, row-count, timestamp and fingerprint checks;
- file-stability checks before and after validation;
- optimistic concurrency before sidecar publication;
- store-owned atomic validation-evidence write path;
- deterministic and idempotent revalidation;
- shared Core blocking-task application boundary;
- audit events for publication, refusal and publication failure;
- Download-to-Maintenance-to-Research vertical validation.

## Excluded scope

- OHLCV Maintenance GUI and presenter;
- repair, deletion or source correction;
- provider or Historical Download behaviour changes;
- Research production changes;
- a new persisted schema version;
- Heavy V2 contracts, registries or metadata systems.

## Canonical authorities

| Truth or state | Authority |
|---|---|
| Market-series identity | `MarketId` |
| Physical CSV and sidecar writes | `OHLCVStore` |
| Final OHLCV quality truth | `CanonicalOHLCVValidator` |
| Discovery and validation orchestration | `OHLCVMaintenanceService` |
| Long-running task lifecycle | `TaskManager` through `CoreRunner` |
| Durable validation evidence | existing `OHLCVSidecarV1` |
| Research admission | existing read-only `AcceptedDatasetCatalog` |

## Validation policy

Canonical status is derived as follows:

```text
one or more errors   → error
no errors, warnings  → warning
no findings          → ok
```

Research continues to accept only `ok`.

A warning such as a cadence gap therefore remains visible but is not promoted to
Research acceptance. Month continuity is checked through calendar-month
progression rather than a fixed millisecond duration.

## Controlled publication

The validator never writes files. It returns stable CSV and sidecar evidence.
The Maintenance service may request publication only when:

- both files remained stable throughout validation;
- sidecar identity matches the canonical storage path;
- persistence is `committed` or `repaired`;
- sidecar SHA-256, row count, timestamps and file fingerprint match the CSV;
- no evidence-publication blocker exists.

`OHLCVStore.publish_validation` rechecks both fingerprints under its write lock
before atomically replacing the sidecar. Repeating the same unchanged validation
is a no-op and does not rewrite the sidecar.

## Old-code classification

### Preserved as behaviour

- dataset discovery;
- structured issue codes and severities;
- row, column and timestamp context;
- schema, numeric, OHLC, volume, timestamp and gap checks;
- explicit accepted, warning and rejected outcomes.

### Improved

- canonical `MarketId` identity;
- current `OHLCVSidecarV1` evidence;
- SHA-256 and stable-file verification;
- optimistic concurrency;
- one store-owned sidecar publication path;
- shared Core execution;
- deterministic and idempotent revalidation.

### Rejected

- old Maintenance god service;
- `CoreBridge` ownership;
- GUI filesystem traversal or validation;
- automatic repair;
- duplicate dataset identities;
- contract registries, Object Maps and metadata bureaucracy.

## Finish line

Task 1003 is complete when focused and full tests prove that:

- valid downloaded data moves from `unknown` to `ok`;
- Research admits it only after publication;
- invalid and warning datasets remain excluded;
- stale, partial, missing, contradictory or changing evidence is never blessed;
- CSV bytes are never modified by validation;
- sidecar publication is atomic and idempotent;
- the complete test suite remains green;
- no Research or GUI production file changes are present.
