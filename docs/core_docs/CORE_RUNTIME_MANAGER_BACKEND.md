# Core Runtime Manager Backend

`RuntimeManagerBackend` is the CORE-10 backend/read-model facade for the Runtime
Manager surface.

The backend aggregates current runtime truth from existing Core owners:

- `StateStore`
- `SessionManager`
- `ServiceRegistry`
- `TaskManager`
- `WindowRegistry`
- `ActionRegistry`
- `OperationRegistry`
- `AuditLog`
- `ContractRegistry`
- optional Object Map snapshot provider

`snapshot()` returns a defensive `RuntimeManagerSnapshot`. The backend reads
current app lifecycle state, current session identity, service visibility, active
tasks, open windows, recent action triggers, active operations, retained audit
events, audit sink failures, contract registry counts, and an optional compact
Object Map summary when a read-only `ObjectMapSnapshot` provider is injected.

Object Map integration is snapshot-only. Runtime Manager consumes an optional
injected callable that returns `ObjectMapSnapshot`. It does not own Object Map,
register providers, consume `ObjectMapProviderEntry`, call provider
`build_section` functions directly, read source managers for Object Map data, or
route Object Map interrogation.

Object Map diagnostics are sanitized and deduplicated before Runtime Manager
metadata is produced. Warning, error, and blocker counts represent the full
unique diagnostic totals, while the displayed diagnostic tuples are bounded and
redacted for read-only Runtime Manager display. GUI display must keep those
diagnostics read-only and must not repair, retry, execute, cancel, or control
Object Map provider output.

The backend does not own runtime state. It does not mutate `StateStore`, register
services, register windows or actions, execute actions, start or cancel tasks,
create audit files, own Object Map providers, repair Object Map output, route
Object Map interrogation, or perform lifecycle transitions.

Runtime Manager display remains read-only. Runtime Manager controls, Object Map
interrogation routing, provider repair, lifecycle control, Data Manager
behavior, Analysis Suite behavior, Trading Suite behavior, provider transport,
and old Leonardo code reuse remain outside this backend.
