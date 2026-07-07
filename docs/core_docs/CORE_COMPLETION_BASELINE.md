# Core Completion Baseline

This document summarizes the accepted Leonardo V2 Core foundation state before
commit and tag preparation.

## Completed Core Foundation

The Core foundation is explicit, inspectable, traceable, permission-gated,
auditable, cancellable, and read-only inspectable.

Runtime ownership is:

- `LeonardoApp` constructs and exposes Core runtime components.
- `LeonardoApp.startup()` prepares Core state and contracts only.
- `LeonardoApp.start_core_runtime()` is the explicit app-level async runtime
  start boundary.
- `LeonardoApp.stop_core_runtime()` and `LeonardoApp.shutdown()` stop runtime
  safely and remain safe when runtime was never started.
- `CoreRuntimeBridge` owns command, query, result, progress, and cancellation
  submission.
- `CoreRunner` owns the persistent async loop.
- `TaskManager` owns task lifecycle.
- `OperationRegistry` owns semantic operation lifecycle.
- `StateStore` owns current runtime truth.
- `AuditLog` owns historical event truth.

Command submission before runtime start is blocked with
`RuntimeError: Core runner is not running` and creates no task or operation.
Command submission after explicit runtime start is supported.

Suites, windows, Runtime Manager, Object Map providers, adapters, provider
clients, and domain services must not start the Core runtime independently. A
future GUI app runner may call `start_core_runtime()` once at the top-level app
boundary.

## Runtime Inspection And Object Map

`RuntimeManagerBackend` remains read-only. It aggregates existing Core owner
read models and exposes compact snapshots for Runtime Manager display. It does
not execute actions, cancel tasks, repair state, start runtime, register Object
Map providers, or mutate source managers.

Runtime Manager may display compact Object Map status through
`object_map_summary` when an app-level boundary injects an `ObjectMapSnapshot`
provider. Diagnostics are sanitized, deduplicated, counted as full unique
totals, and displayed as bounded tuples.

`ReadOnlyObjectMapService` aggregates explicit `ObjectMapProviderEntry` values.
It has no global provider registry, no import-time registration, no filesystem
or module scanning, no source-manager direct reads, no command execution, and no
mutation behavior. Provider failures are bounded and redacted without blocking
healthy providers. Duplicate section and object IDs are reported.

## Trace Providers

Read-only trace providers now exist for:

- task and operation families;
- app runtime, session, service, contract descriptor, and explicit error report
  families;
- process, connection, and websocket channel families;
- audit event family;
- static GUI window family;
- static GUI action family.

Trace providers emit summaries and relationships only from existing owner read
models, explicit caller inputs, or static metadata. They do not register
providers globally, mutate source owners, execute commands, wire Runtime
Manager, or add domain behavior.

## Domain Boundaries

The completed Core baseline does not implement Research Suite, Data Manager
Suite, Analysis Suite, Trading Suite, provider/client/network transport,
WebSocket transport behavior, old-code import, or future Download Data
execution. Accepted download contracts and read models remain Core-visible
facts only; they are not provider execution or storage behavior.

## Validation State

The Core completion correction pass validated:

- app runtime foundation and Core Runtime Bridge tests passed;
- Runtime Manager backend and Object Map safety tests passed;
- Core trace provider tests passed;
- focused Runtime Manager GUI, window trace, action trace, and GUI action
  tracking tests passed;
- contracts tests passed;
- combined core and contracts tests passed;
- full GUI tests passed after the stale Runtime Manager row-count assertion was
  corrected;
- `git diff --check` passed with CRLF conversion warnings only.

No final Core completion commit or tag has been created in this phase.

## Next Phase

The next phase is `LEO-V2-CORE-COMPLETION-COMMIT-001`.

Major area design and implementation must wait until the Core completion
baseline is committed and tagged.
