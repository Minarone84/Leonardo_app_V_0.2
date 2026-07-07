# Core Runtime Bridge

`CoreRuntimeBridge` and `CoreRunner` define the first Leonardo V2 Core async
runtime boundary.

## Ownership

Core owns the runner, task scheduling, runtime task state, cancellation routing,
audit/error reporting, operation-task correlation, and immutable
command/result/progress contracts.

GUI-facing callers may submit intent through the bridge, but GUI code does not
own execution, task lifecycle, domain validation, storage, adapters, networking,
or runtime state mutation.

Runtime Manager remains read-only. It observes task, operation, audit, and
runtime state through snapshots; it does not execute or cancel work.

## Flow

The supported foundation flow is:

```text
GUI-facing intent
-> CoreRuntimeBridge
-> OperationRegistry operation identity
-> CoreRunner persistent asyncio loop
-> TaskManager supervised task
-> StateStore and AuditLog task state
-> dispatcher-delivered result/progress callback
```

The bridge accepts caller-provided command handlers. It does not interpret
command payloads and does not implement domain behavior.

## Permission Gate

`CoreRuntimeMetadata.required_permission` may carry one canonical permission
value from `leonardo.contracts.identity.Permission`. When present,
`CoreRuntimeBridge` asks Core `UserPolicy` to authorize the current
`SessionManager` actor before submitting to `CoreRunner`.

Allowed commands proceed to operation and task creation. Denied commands return
a rejected `CoreRuntimeSubmission`, dispatch a failed `CoreRuntimeResult` with
`PermissionDenied` error metadata, and emit `core_runtime.command.denied` when
an `AuditLog` is configured. Denied commands do not create TaskManager tasks or
OperationRegistry operations.

The legacy metadata field `permission` remains traceability metadata. It is not
used as an authorization requirement; callers must use `required_permission` for
Core-owned command gating.

## Operation And Task Correlation

When an app-owned `OperationRegistry` is available, command submission either
preserves an existing `operation_id` from command metadata or creates a neutral
operation record from command metadata. The bridge marks the operation running
with the TaskManager-assigned `task_id` after scheduling succeeds.

Terminal Core runtime results mark the associated operation completed, failed,
or cancelled. Cancellation may be routed by operation identity when the active
operation has an associated task. TaskManager remains the owner of task
lifecycle, and OperationRegistry remains the owner of semantic operation
lifecycle.

Runtime Manager observes the relationship through read-only snapshots. It does
not execute, cancel, or mutate operations or tasks.

## Contracts

The runtime bridge contracts live in `leonardo.contracts.core_runtime`:

- `CoreRuntimeMetadata`
- `CoreRuntimeCommand`
- `CoreRuntimeQuery`
- `CoreRuntimeProgress`
- `CoreRuntimeResult`
- `CoreRuntimeError`
- `CoreRuntimeSubmission`
- `CoreRuntimeCancellationRequest`
- `CoreRuntimeCancellationResult`

Metadata carries operation, task, action, window, actor, session, permission,
domain, suite, source, correlation, and schema identity so future workflows can
remain traceable without making the bridge a domain owner.

## Lifecycle

`CoreRunner.start()` creates the persistent Core event loop. Submissions are
rejected until the runner is running.

`CoreRuntimeBridge.shutdown()` stops accepting new submissions before delegating
to the runner. `CoreRunner.shutdown()` cancels active TaskManager tasks, waits
for settlement using an explicit timeout, reports shutdown failures through the
Core error router, and stops the event loop. `LeonardoApp.shutdown()` calls
bridge shutdown idempotently when the app owns the runner.

Application shutdown follows a narrow Core-owned sequence:

```text
stop bridge submissions
-> cancel and settle Core runtime tasks
-> request ProcessManager stop for active process handles
-> mark tracked connections disconnected
-> mark lifecycle service runtime states stopped
-> emit final app lifecycle facts
-> close AuditLog
```

Connection shutdown remains tracking-only. The registry marks connection and
channel runtime state; it does not own provider clients or transports.

Capability providers registered as lookup objects are not lifecycle-managed
services. Only services registered with lifecycle kind and runtime state
participate in service shutdown state transitions.

## Non-Goals

This boundary does not add Download Manager execution, adapters, WebSocket or
provider clients, storage writers, Data Manager behavior, Analysis Suite
behavior, trading behavior, GUI layout changes, or Runtime Manager controller
behavior.
