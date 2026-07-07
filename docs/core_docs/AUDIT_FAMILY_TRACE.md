# Audit Family Trace

`leonardo.core.audit_event_trace` exposes Core audit history as read-only
traceable object summaries and Object Map sections for the `audit_event`
family.

## Scope

The helper builds read-only `TraceableObjectRef`, `TraceableObjectSummary`,
`TraceableRelationshipRef`, `ObjectMapProviderDescriptor`,
`ObjectMapSection`, and `ObjectInterrogationReport` values.

It reads existing event data from:

- explicit `AuditEvent` values supplied by tests or callers;
- `AuditLog.snapshot()` when an `AuditLog` instance is supplied.

The helper does not emit audit events, mutate `AuditLog`, mutate current
runtime state, change durable logging policy, change retention policy, wire
Runtime Manager, register Object Map providers, or implement domain behavior.

## Sensitive Fields

Payload values are not copied into summaries. The helper records payload keys,
top-level key count, and top-level value types only. Error details are treated
the same way. Event and error messages are exposed only as bounded previews.

## Relationships

When explicit identifiers are present, the helper emits `references`
relationships from the audit event to:

- session;
- window;
- action;
- operation;
- task;
- process;
- connection.

The helper may also create a relationship for an explicit payload
`object_id`/`object_kind` pair when the object kind is already a known object
family. It does not parse free-form text or raw payload bodies to infer object
relationships.

## Validation

Focused tests live in `tests/core_test/test_audit_family_trace.py`.
