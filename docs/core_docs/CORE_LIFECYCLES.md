# Core workflows and complete lifecycles

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Verified:** 2026-10-09 after Core V2 audit. Read with [scope](LIGHT_V2_RUNTIME.md), [architecture](CORE_ARCHITECTURE.md), [contracts](CORE_DATA_CONTRACTS.md) and the [map](Leonardo_V2_Core_Complete_Map.pdf).

## 1. Configuration and construction

`load_default_config(root)` resolves the supplied root, or current working directory when omitted, without creating directories. It returns frozen AppConfig/RuntimePaths/AuditConfig values. LeonardoApp builds the graph described in architecture and starts with status `created`. Its CoreRunner has no loop/thread, is not accepting, and has no pending shutdown future/stop request. Service construction is distinct from application startup, Core runtime startup and Qt event-loop entry.

All runtime records are initially in memory. Optional JSONL audit storage opens on first emission, not on config construction. Existing Area stores and files are not copied into a Core-owned database.

## 2. Application startup and GUI execution

1. `startup()` returns the same context immediately if already `running`; it rejects a normally `stopped` instance.
2. Otherwise set `starting`; log and emit `application.starting`.
3. Set `running`; emit `application.started`; return the existing context. No worker thread is started by this method.
4. If an exception escapes, set `failed`, route the startup exception and re-raise. This is sequential code, not an all-or-nothing transaction over previous audit writes.
5. `start_core_runtime()` requires app status `running`, invokes runner.start and returns context.
6. GUI runner obtains QApplication, applies theme, composes Main Window, shows it, schedules the one-shot DMS reconciliation and enters QApplication.exec.

The application method explicitly refuses `stopped`; it does not implement a general transition guard for every other state. In particular, failed-state policy must not be inferred from the happy-path diagram. Do not use a fresh `startup()` call to conceal a shutdown failure. The accepted recovery path is explicit cleanup retry, preserving failed status.

If GUI creation or event-loop execution raises, the GUI runner still tries window close and application shutdown. A shutdown exception is raised chained from the earlier primary error, or from a close error if that is the available predecessor. A close error is re-raised after successful shutdown when there was no primary error. The runner does not swallow shutdown failures or synthesize successful acceptance of a refused dirty transition.

## 3. CoreRunner startup and admission

From a fully stopped runner, clear per-lifecycle shutdown state, create one daemon `LeonardoCore` thread and wait up to five seconds for its startup event. The thread creates an asyncio loop, attaches one default executor (four workers unless explicitly configured), installs that loop, publishes loop/executor references and signals ready before run_forever. Admission opens after the ready handshake.

A second normal start is idempotent. During an in-progress shutdown, start raises `Core runner is shutting down`; after a thread exits with an unclosed loop, it raises `Core event loop cleanup did not complete`. Explicit later restart after complete cleanup works. No general concurrent-start feature is specified. `is_running` checks the live thread and loop reference; it can remain true during drain. `is_accepting_submissions` combines that with admission state.

## 4. Submission and execution

Preconditions: valid callable/coroutine, a running loop, and open admission. `submit_blocking_job` rejects coroutine functions; `submit_coroutine` requires an actual coroutine object. Rejected submit_coroutine wrappers close their supplied coroutine through the helper on exception. CoreRunner invokes `normalize_task_name` before creating its private execution wrapper, after the existing public input/admission checks. TaskManager rejects non-coroutines and invalid/empty names; duplicate active names close the supplied coroutine before rejecting. Generic caller-object cleanup is not promised. TaskSubmission retains the supplied name while the manager stores its canonical trimmed name.

1. External caller submits `_schedule_job` to the Core loop with `run_coroutine_threadsafe` and waits up to five seconds for its registration result.
2. Build a shared task-ID reference and ProgressReporter bound to TaskManager and callback dispatcher.
3. Create the execution coroutine. Async job executes on the loop; blocking/synchronous job runs via `asyncio.to_thread`. If its value is awaitable, await that value.
4. TaskManager creates UUID identity and asyncio task, stores its running record with metadata/correlation and appends creation order. Trim eligible terminal history; emit `task.submitted`; register its terminal callback.
5. Publish task ID to the reporter, create a separate terminal-result delivery coroutine and return TaskSubmission.
6. Terminal delivery establishes a wait on the manager's task. A returned value maps to completed, CancelledError to cancelled, other Exception to failed with type/message. Dispatch one TaskResult if a result callback was supplied.

Registration timeout and task completion timeout are different concepts. A synchronous submission wait is not a cancellation API; documentation does not promise rollback of work merely because its caller stopped waiting. Result delivery is not a persisted queue, retry service or acknowledgement protocol. Callback/dispatcher failures are not automatically retried, and must not be treated as a second failure status for an already completed task.

## 5. Progress and terminal bookkeeping

ProgressReporter requires the task identity to have been populated. It calls `update_progress`, then sends a copied-details TaskProgress through the dispatcher if one was supplied. TaskManager records message/current/total and returns a snapshot. Reporter details are notification data; they are not an additional field in TaskSnapshot. Core does not validate progress ranges or infer percentage.

Task completion callback records finish time and sets `completed`, `failed` or `cancelled`. It captures task name/correlation/error data, trims eligible history under the same manager lock, then emits the terminal event. Failure also routes an `error.reported` event for an Exception, so task.failed and error.reported are separate evidence roles, not duplicate task completion. Result delivery uses the existing waiter even if history is evicted. Cancellation is not routed as a financial/domain failure.

ResearchDatasetApplicationService performs terminal map cleanup even if the GUI dispatcher delays or discards delivery. It sets its finished event, removes the actual task identity under its RLock, then dispatches outward result once after releasing that lock. Progress also uses the original outward dispatcher. The finished flag prevents a terminal entry being inserted after an early result; active cancellation and GUI-owner-thread delivery remain unchanged.

## 6. Cancellation and worker survival

`CoreRunner.cancel(id)` schedules TaskManager cancellation on the loop and waits up to its timeout (default five seconds). Unknown or terminal IDs return false. For an active record, TaskManager sets `cancel_requested` and calls asyncio task.cancel; it emits request evidence when cancellation is accepted. A coroutine that suppresses CancelledError may return a value and become completed. Cancellation is a request, not an immutable terminal outcome.

`cancel_all()` snapshots active records, requests each cancellation and gathers those tasks with `return_exceptions=True`. It does not kill threads. For an executing blocking job, the asyncio awaiter may become cancelled while the worker still runs. Area-owned events/checks must prevent unwanted continued work or publication. DMS publication gates may reject a late cancel after the destructive/publication boundary. Core preserves these contracts; it does not introduce universal rollback.

Closing a Research/DMS/Analysis view is also not equivalent to global Core shutdown. Presenters/services stop relevant admission, request appropriate cancellations and ignore late callbacks. Other windows may still use the shared runner. Saved data ownership and surviving references remain in the Area manuals.

## 7. Task history and lookup

Order is registration order. On creation and terminal completion, scan from the oldest entry: skip active records, remove eligible terminal entries, stop when at the configured bound or when all remaining records are active. Default cap 500 is retention, not concurrency admission. If active_count exceeds the cap, every active record remains.

An established waiter holds its asyncio task through completion/exception/cancellation. A new `wait_task` after eviction raises KeyError; `get_snapshot` returns None. Completed history, task-name availability and audit history are separate concerns. No history eviction deletes an Artifact, Notebook, Workspace Snapshot, Database, file or audit event. There is no task-history reload after a new app instance.

## 8. External processes

### Launch

Validate non-empty string command parts and non-empty label. Resolve explicit ID or UUID. Under ProcessManager's existing lock, reject an ID in either published records or in-flight reservations, then reserve it. Run the external launcher outside the lock with optional cwd and environment overlay. On launch exception, log/route/re-raise; finally release the reservation. On success, build/publish the handle record before releasing reservation, emit one process.started and return ID. No second process can launch with that reserved ID while the first is held. Different IDs remain concurrent.

### Poll and terminal state

Get the owned handle and poll it outside the record lock. None means still running. An exit code sets finished timestamp and terminal state: zero -> completed, nonzero -> failed, or terminated if termination had been requested. Store exit code and failure text. The terminal_event_emitted flag makes repeated poll/snapshot calls emit at most one terminal event for that record. Failed exit is process.failed evidence with ProcessExitError details; this path does not additionally call ErrorRouter.

### Terminate and shutdown

`terminate` returns false for missing/non-active IDs; otherwise set terminate_requested, call handle.terminate or handle.kill outside lock, and emit process.termination_requested. If the handle method raises, restore previous status, record the error, route and re-raise. Shutdown terminates current active handles, polls every at most 0.05 seconds until timeout, kills remaining active handles, then waits up to `min(timeout, 1.0)` seconds. If any remain, raise TimeoutError naming them.

Records remain available for the manager lifetime; no unregister/delete API or persisted process restore exists. The launch reservation solves overlapping duplicate admission. It is not a general lockout of all new launches during shutdown, which remains outside the approved correction.

## 9. Connection and channel summaries

Register a non-empty connection ID/label once; duplicate IDs raise. Initial state is registered. Public mark methods assign connecting, connected, degraded, disconnect_requested, disconnected or failed. These methods are not a strict state-transition graph: they do not enforce a mandatory predecessor. Mark connected clears prior error; marking disconnected does not automatically erase an old error. Heartbeat normalizes an aware datetime to UTC, or uses current UTC.

Register a websocket channel against an existing connection and unique channel ID. Counter updates require a positive exact int, increment the chosen receive/send/error field and set last-message time. Core does not interpret messages or subscriptions. Connection/channel listings are sorted by identity. Shutdown tracking marks all except already disconnected/failed connections disconnected; it neither removes channel counters nor closes network resources. These records are in memory only; there is no unregister or automatic persistence.

## 10. Windows, accepted closure and reopening

WindowRegistry registers a supplied ID/title/type and copied metadata. Re-registration of the same ID with identical title/type returns the existing record; conflicting title/type raises. A metadata-only change in this call does not replace the existing record. Open sets status open, retains first opened timestamp and clears closed timestamp. Focus requires open and updates focus time. Request-close sets close_requested; close sets closed and a timestamp. Open-window queries include close_requested records.

GuiWindowTracker is parented to the widget and installs an event filter. Show opens; WindowActivate/FocusIn attempts focus. Ordinary close-event tracking records request/closed when close_on_event is true. Main Window and active Research use guarded closure: tracking waits for their accepted closed signal, so Cancel/failed-save leaves both visible window and registry open. Registry closure itself does not close/delete a QWidget. Hide is not a close event in this adapter.

Closed logical records remain inspectable. Reopening the same logical window uses the same accepted identity, clears closed_at and preserves the original opened_at. Distinct editor modes retain distinct IDs; title alone is not identity. Removing a chart from a workspace, deleting a Notebook and closing a window are different Area/UI operations with different surviving references; the registry does not implement any of those persistence decisions.

## 11. Discoverable actions

Register an ActionDefinition or construct one from arguments. Exact duplicate definition is idempotent; conflicting definition for an existing ID raises. Lookup returns None if absent; invoke/record of unknown ID raises KeyError. List definitions sorted by ID.

`record_trigger` chooses caller actor/window overrides or definition/registry defaults, records time/correlation/copied metadata, keeps latest 500 triggers and emits action.triggered when audit_enabled. `invoke` records the trigger before calling the optional handler; no handler returns None. Handler runs synchronously on the caller thread. A trigger is not proof the handler completed successfully. The registry does not catch/retry handler exceptions or enforce confirmation/risk metadata. No unregister, reload or task conversion is implied.

## 12. Audit storage, errors and failure visibility

InMemoryAuditSink validates event type, appends to a bounded deque (default 1000), and returns events in insertion order. flush/close are no-ops. JsonlAuditSink lazily creates the parent directory, opens append UTF-8, writes sorted-key JSON plus newline and flushes every event. snapshot reads nonblank lines through AuditEventV1.from_dict; malformed data can raise. close releases its handle; a later emit reopens it in append mode. No rotation, compression or migration engine is supplied.

CompositeAuditSink attempts each sink per operation and accumulates AuditSinkFailure records. Emit succeeds with at least one successful delivery, otherwise raises RuntimeError. Snapshot returns the first non-empty successful sink result, not all histories merged; failing/empty sinks allow trying the next. Flush and close attempt every sink and record errors without aborting the remaining sink calls. Default JSONL composition orders JSONL then memory. AuditLog delegates; `sink_failures` is empty for a sink without that capability. Memory/JSONL directly wrapped without Composite may propagate sink exceptions.

TaskManager and ProcessManager protect their ordinary `_emit_audit` boundaries with logging on exception. ErrorRouter, ActionRegistry and app lifecycle emission have their actual propagation semantics; there is no blanket guarantee that every audit failure is harmless. ErrorRouter builds error.reported with identities/context/error type and message and calls AuditLog.emit. It owns evidence formatting, not retries, dialogs or runtime recovery.

AuditEventV1 is the durable contract. Runtime histories are disposable. Default audit is memory-only even though a JSONL destination is present in config. `enabled=False` selects memory, not an absent audit authority.

## 13. Runtime Manager inspection

Refresh asks RuntimeManagerBackend for generated time, app status/actor, task/process/connection/channel/window/action snapshots and audit events/failures. Task and registry snapshots are projections. Process snapshot construction invokes polling and can record a newly observed exit plus its terminal audit. Recent events are then read later in the same sequential backend construction. There is no atomic all-manager snapshot lock.

The visible six tabs contain selected columns. Backend websocket_channels and audit_sink_failures remain available to callers but are not rendered in dedicated tabs. GUI Refresh and Close are presentation controls; the window has no built-in task cancellation or process termination buttons. GUI claims of being read-only describe its controls, not the absence of owner-side poll updates.

## 14. Ordered whole-application shutdown and retry

| Stage | Success | Failure / retained state |
|---|---|---|
| App entry | If stopped, return; otherwise preserve prior-failed flag, set stopping unless already failed | Invalid timeout rejects before work |
| DMS cancellation | Ask Area gates to cancel eligible pending tasks | Error aborts later ordered steps; app failure is routed |
| Analysis cancellation | Ask the existing Analysis service to cancel pending work after DMS | Error aborts Core shutdown and later steps; app failure is routed |
| Core cancellation | Close admission; create/reuse one cancellation future and wait | Timeout leaves same future for retry; no second cancellation pass |
| Core stop request | Request loop.stop once for matching live lifecycle | Retry observes existing request rather than interrupting final drain |
| Core loop finalization | Cancel/gather remaining tasks, shut async generators, drain default executor, close loop | Executing workers remain cooperative; incomplete loop cleanup is not reported as success |
| Join and retirement | Wait for thread; verify loop closed; clear references only if they still name this lifecycle | Thread still alive -> TimeoutError; unclosed loop -> RuntimeError; another explicit lifecycle is not cleared |
| Process shutdown | Termination/poll/escalation as section 8 | Error leaves later connection/window/audit steps pending |
| Tracking cleanup | Mark connection summaries and remaining window records closed | Does not delete data or close provider sockets by itself |
| App completion | Emit application.stopped; set stopped only when not preserving earlier failed status | Exception sets failed, routes and re-raises |
| Audit finalization | Close sinks in finally, including failure paths | Sink-specific/composite semantics from section 12 apply |

The timeout parameter remains the existing duration for individual waits, not an aggregate deadline. A worker-drain timeout does not mean the loop was abandoned. Retry while it drains can time out again; retry after real finalization continues cleanup without closed-loop submission. A failed application stays failed even when that cleanup later succeeds. A fresh application instance is the ordinary new-session boundary.

The separate `stop_core_runtime(timeout=...)` route calls DMS cancellation, Analysis cancellation, then `core_runner.shutdown(timeout=timeout)`. It propagates failure but does not execute the whole-app process, connection, window, app-status or audit-finalization stages. Both routes preserve sequential non-atomic cleanup, cooperative workers and existing timeout/retry behavior.

## 15. Survival and deletion matrix

| Object/state | Close/cancel/end effect | Survives / persistence |
|---|---|---|
| Task record | Terminal then eligible for bounded eviction | Established waiters/results and audit delivery survive; no disk task record |
| Blocking callable | Awaiter may cancel first | Worker continues until it returns/cooperates; executor drain waits |
| Process record/handle | Owner terminates/polls; terminal record retained | Record lasts manager lifetime, OS process does not have a Core reload contract |
| Connection/channel | Tracking shutdown changes summaries | In-memory records/counters retained; actual provider resources are separate |
| Window | Accepted GUI close and registry close are coordinated | Registry history retained; saved Area objects unaffected |
| Action / triggers | Invocation records evidence; bounded triggers | Definitions retained, latest 500 triggers; no durable registry |
| Audit | Sink close flush/release semantics | Optional JSONL file survives app; memory ring lasts sink instance |
| CoreContext / services | References live with app composition | Not a persisted schema; no automatic resource graph reconstruction from it |
| Research/DMS saved objects | Governed by their explicit operations | Neither Core history eviction nor runtime-window closure deletes them |

Analysis Suite retirement disposes only the matching presenter/session and clears its GUI composition references. Its shared Analysis application service, creation store and Core runtime remain app-owned; Suite closure does not delete saved databases.
