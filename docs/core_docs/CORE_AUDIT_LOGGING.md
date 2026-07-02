# Core Audit Logging

Core audit logging records historical runtime events.

Included sinks:

- `InMemoryAuditSink` for bounded live inspection;
- `JsonlAuditSink` for durable local JSONL history;
- `CompositeAuditSink` for fan-out to multiple sinks.

The JSONL sink writes one serialized audit event per line using UTF-8. Parent
directories are created only when an event is written. Configuration loading does
not create directories.

Sink failures are captured as structured `AuditSinkFailure` records. A failure in
one sink does not prevent later sinks from receiving the same event, and audit
sink failures are not recursively emitted as audit events.

`AuditLog.flush()` and `AuditLog.close()` are idempotent. `LeonardoApp` closes
the audit log during shutdown.

SQLite/searchable audit storage, Runtime Manager GUI, GUI action logging, window
and action registries, and old Leonardo audit dependencies are not implemented
in this phase.
