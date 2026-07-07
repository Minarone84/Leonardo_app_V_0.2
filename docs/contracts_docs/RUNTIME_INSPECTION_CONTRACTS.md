# Runtime Inspection Contracts

Runtime inspection contracts define read models for Runtime Manager backend
snapshots. They are importable contracts under `src/leonardo/contracts/` and use
only the Python standard library.

`RuntimeManagerSnapshot` is an aggregate read model. It includes the generated
timestamp, derived health, app lifecycle status, current session/user identity,
section summaries, recent audit event previews, audit sink failure previews, and
contract registry counts.

`RuntimeSectionSummary` represents one backend section with a status, count, and
bounded metadata. Section metadata is intended for inspection surfaces and must
remain presentation-neutral.

`ProviderRuntimeSummary` is a compact provider-boundary read model supplied by
future app composition or provider owners. It reports provider availability,
capability/session/subscription/message-trace counts, object-map section counts,
bounded diagnostics, and last activity metadata. It is frozen and rejects
sensitive metadata keys such as credentials, tokens, secrets, passwords, API
keys, raw client/socket references, raw payloads, and raw responses at every
metadata nesting level. Provider metadata values must remain JSON-compatible:
null, booleans, integers, finite floats, strings, lists or tuples of safe
values, and string-keyed mappings of safe values.

`RuntimeHealthStatus` is derived from section statuses. Failed app state maps to
an error section. Audit sink failures and visible failed or cancellation-requested
runtime work degrade the relevant section.

`AuditEventPreview` and `AuditSinkFailurePreview` provide bounded readback from
`AuditLog` without exposing sink ownership or persistence behavior.

These contracts do not define GUI widgets, Qt/PySide objects, command execution,
provider registries, provider discovery, adapter/client/network/websocket
execution, subscription execution, task control, ProcessManager behavior, or
connection/websocket tracking ownership.
