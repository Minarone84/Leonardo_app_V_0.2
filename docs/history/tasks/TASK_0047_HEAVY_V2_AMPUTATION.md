# Task 0047 — Remove Heavy V2 Machinery and Repair Core + GUI

## Task identity

```text
Task ID: 0047
Task name: Remove Heavy V2 machinery and repair Core + GUI
Standalone or workplan task: Workplan task
Parent workplan: Leonardo Light V2 Fast-Track Reset
Execution owner: Rick
Decision entropy: MEDIUM reduced to LOW by the approved keep/delete matrix
Implementation agent: Rick-authorised direct patch
Architecture status: FROZEN FOR TASK
Durable data impact: PERSISTED SCHEMA — retain AuditEventV1 and OHLCVSidecarV1 only
```

## Objective

Delete the known Heavy V2 contract, Object Map, trace-provider and GUI metadata
bureaucracy while preserving the reusable asynchronous runtime, runtime managers,
audit persistence, theme system and GUI shells.

## Canonical authorities affected

```text
Application lifecycle: LeonardoApp
Task lifecycle: TaskManager
Process lifecycle: ProcessManager
Coarse connection state: ConnectionRegistry
Window runtime state: WindowRegistry
Application-wide actions: ActionRegistry
Historical evidence: AuditLog / AuditEventV1
Market identity: MarketId
OHLCV sidecar evidence: OHLCVSidecarV1
```

## Included scope

- delete the global contract package and Contract Registry;
- retain only `AuditEventV1`, `MarketId`, and `OHLCVSidecarV1`;
- delete Object Map, relationship/family legends and trace providers;
- delete duplicated `StateStore` authority and public runtime-state contracts;
- replace runtime records with manager-owned typed models;
- make Runtime Manager read direct snapshots;
- delete GUI metadata, TOMLs, roadmap, loaders, resolvers and override store;
- delete metadata-driven Settings Inspector and metadata test windows;
- replace metadata window values with explicit Python defaults;
- retain stable Qt object names and useful action IDs;
- preserve GUI shells and theme code;
- remove production dummy-data fixtures and start shells in honest empty states;
- delete inactive Connection metadata stubs;
- remove stale package exports, imports, tests and documentation.

## Excluded scope

- Download Data restoration;
- provider/API implementation;
- OHLCV persistence implementation beyond the retained sidecar schema;
- Financial Tools restoration;
- charts, analysis, backtesting or trading behaviour;
- a replacement Contract Registry, Object Map or GUI metadata system;
- compatibility facades for abandoned Heavy V2 internal APIs;
- new dependencies.

## Start line

```text
Branch: light-v2-reset
HEAD: a1e5f7ca8c180dd795e1008316f4815cfb98a57d
Working tree: clean
Task 0046: PASS
Governance 2.3 FINAL installed
Keep/delete matrix approved
Direct Rick implementation authorised
```

## Finish line

```text
Global contracts package absent
ContractRegistry absent
Object Map and trace providers absent
StateStore absent
GUI metadata/TOMLs/roadmap absent
Metadata Settings Inspector absent
Production dummy-data module absent
No active production imports of retired machinery
Core startup/shutdown and async task behaviour pass
Process/connection/window/action tracking pass
Audit JSONL round-trip passes
Runtime Manager uses direct snapshots
GUI shells compile and local PySide6 smoke tests exist
Governance and reset documentation are coherent
No dependency or domain restoration changes
POST package is produced for independent Task 0048 validation
```

## Validation result

Rick environment:

```text
Full available test suite: 23 passed, 1 skipped
Headless GUI-runner lifecycle tests: passed
PySide6 window smoke module: skipped because PySide6 is unavailable
Compile validation: passed
Import-resolution scan: passed
Retired-architecture scan: passed
git diff --check: passed
```

The reset reduced the active implementation to approximately:

```text
Core: 13 Python files / 1,860 lines
GUI: 26 Python files / 5,972 lines
Formal contract package: removed
Total active source: 46 Python files / 8,158 lines
```

No Download Data, provider, Financial Tools, chart, analysis, backtest, trading,
or persistence implementation was restored. Full Qt execution, multi-window
responsiveness, and visual acceptance remain Task 0048 gates in the user's
`py312_Leo` environment.

## Final status

```text
Task 0047: PASS
Code cleanup: complete
Core behavioural validation: complete
Static GUI validation: complete
Local Qt visual validation: deferred to Task 0048
Next task: 0048 — Validate and freeze the Light V2 baseline
```
