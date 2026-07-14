# Task 1004 — OHLCV Maintenance GUI and Presenter Integration

## Objective

Expose the canonical Task 1003 Maintenance validation bridge through a dedicated
Qt window and presenter without moving validation, persistence, discovery, or
Core task authority into GUI code.

## Implemented workflow

```text
Main Window or Historical Download Manager
→ OHLCV Maintenance window
→ presenter requests canonical discovery
→ user selects a persisted dataset
→ presenter submits validation through OHLCVMaintenanceApplicationService
→ Core reports progress and terminal result
→ presenter renders evidence and structured findings
→ dataset status refreshes from canonical persisted evidence
```

## Authority boundaries

- `OHLCVMaintenanceService` remains the discovery and validation orchestrator.
- `CanonicalOHLCVValidator` remains the final quality authority.
- `OHLCVStore` remains the only sidecar publication authority.
- `CoreRunner` and `TaskManager` retain asynchronous lifecycle authority.
- The presenter translates intent and results only.
- The window stores presentation state only.
- Repair remains disabled and out of scope until Task 1005.

## User-visible behaviour

The dedicated window provides:

- persisted dataset discovery;
- canonical identity and current status columns;
- selected storage-evidence details;
- canonical validation findings;
- refresh, validate and cancel controls;
- validation progress and terminal status;
- disabled repair control with an explicit future-work explanation.

The existing Main Window action now opens this dedicated window. The Historical
Download Manager Maintenance button opens the same window and no longer displays
a placeholder message.

## Exclusions

Task 1004 does not implement:

- repair planning or execution;
- CSV mutation;
- sidecar editing in GUI code;
- provider access;
- Research mutation;
- batch validation;
- deletion or metadata rebuilding.
