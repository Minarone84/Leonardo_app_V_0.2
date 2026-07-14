# Leonardo Light V2 Runtime

`LeonardoApp` is the single composition root.

Core owns generic application lifecycle and long-running execution:

- `CoreRunner`: background asyncio event loop;
- `TaskManager`: canonical task lifecycle;
- `ProcessManager`: external process lifecycle;
- `ConnectionRegistry`: coarse operational connection summaries;
- `WindowRegistry`: window runtime state;
- `ActionRegistry`: application-wide discoverable actions where justified;
- standard-library `leonardo` logger: operational diagnostics;
- `AuditLog`: historical evidence;
- `RuntimeManagerBackend`: read-only aggregation of direct manager snapshots.

Core does not define provider, OHLCV, financial, research, analysis, backtest or
trading semantics.

Current runtime state lives with the manager that owns it. Runtime Manager rows
are disposable read models. Audit history is persisted separately.


Task and process lifecycle transitions emit structured audit events while their
managers retain canonical mutable state. Managed-process shutdown first requests
termination, then escalates to forced termination only when the timeout expires.

## Blocking work boundary

`CoreRunner` owns a bounded worker pool in addition to the background asyncio
loop. Coroutine jobs execute on the Core loop. Synchronous jobs submitted
through `submit_job` are routed to the worker pool, and callers may use
`submit_blocking_job` to state that boundary explicitly.

Python cannot forcibly stop a callable that is already executing in a worker
thread. Cancellation therefore cancels the Leonardo task and its awaiter; a
blocking operation that needs prompt interruption must cooperate explicitly.
Core shutdown waits for the default worker executor to settle and reports a
timeout instead of pretending that unfinished work disappeared.

Historical OHLCV file reads, writes, hashing and preliminary validation run in
that worker boundary. Provider network operations remain asynchronous.
