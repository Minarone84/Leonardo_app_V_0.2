# Core Runtime Manager Backend

`RuntimeManagerBackend` is the CORE-10 backend/read-model facade for the future
Runtime Manager surface.

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

`snapshot()` returns a defensive `RuntimeManagerSnapshot`. The backend reads
current app lifecycle state, current session identity, service visibility, active
tasks, open windows, recent action triggers, active operations, retained audit
events, audit sink failures, and contract registry counts.

The backend does not own runtime state. It does not mutate `StateStore`, register
services, register windows or actions, execute actions, start or cancel tasks,
create audit files, or perform lifecycle transitions.

This phase does not implement the Runtime Manager GUI. It also does not
implement ProcessManager behavior, connection/websocket tracking, Qt/PySide
integration, Data Manager behavior, financial tools, workspace/chart behavior,
or old Leonardo code reuse.
