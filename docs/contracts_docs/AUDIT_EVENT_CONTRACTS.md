# Audit Event Contracts

Audit events are structured historical records. Runtime state remains current
truth and is represented by runtime state contracts.

`AuditEvent.to_dict()` returns a JSON-safe mapping containing the full audit
event field set:

- identity and schema fields;
- UTC timestamp;
- severity and category values;
- event type and message;
- actor, session, origin, window, action, operation, task, process, connection,
  and correlation identifiers;
- normalized payload;
- optional structured error payload.

`AuditEvent.from_dict(...)` restores an event from the serialized mapping.
Unknown payload keys and error detail keys are preserved.

Payload values are normalized with standard-library types only. Supported values
include strings, booleans, integers, finite floats, `None`, datetimes, enums,
lists, tuples, and nested mappings with string keys.

The contract does not add GUI action/window contracts, runtime search storage,
SQLite storage, or old Leonardo dependencies.
