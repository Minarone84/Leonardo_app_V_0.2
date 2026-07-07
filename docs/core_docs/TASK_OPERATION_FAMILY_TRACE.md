# Task Operation Family Trace

`leonardo.core.task_operation_trace` exposes active Core task and operation
read models through the shared traceability and Object Map contracts.

## Scope

The helper builds read-only `TraceableObjectRef`, `TraceableObjectSummary`,
`TraceableRelationshipRef`, `ObjectMapProviderDescriptor`,
`ObjectMapSection`, and `ObjectInterrogationReport` values for the `task` and
`operation` families.

It reads existing state from:

- `TaskManager.active_tasks()`
- `OperationRegistry.active_operations()`
- `StateStore` task and operation state methods
- `RuntimeSnapshot` task and operation tuples
- explicit task and operation state tuples supplied by tests or callers

The helper does not schedule tasks, cancel tasks, submit commands, transition
operations, mutate `StateStore`, emit audit events, register Object Map
providers, wire Runtime Manager, or implement domain behavior.

## Ownership

TaskManager remains the owner of active async task lifecycle truth.
OperationRegistry remains the owner of semantic operation lifecycle truth.
StateStore remains the owner of current runtime state truth.
AuditLog remains the owner of historical event truth.
Runtime Manager remains read-only and unwired from this helper.

## Relationships

When identifiers are present, the helper emits:

- `operation -> task` via `schedules_task`
- `task -> operation` via `references`
- `operation -> action` via `references`
- `operation -> window` via `references`
- `operation -> session` via `references`

Missing optional identifiers do not create placeholder relationships.

## Validation

Focused tests live in `tests/core_test/test_task_operation_family_trace.py`.
