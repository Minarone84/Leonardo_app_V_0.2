# Leonardo Light V2 Core Runtime

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Status:** Current implementation reference after accepted Core patch V2 and its audit.
**Updated:** 2026-10-09. Documentation-only edition; no runtime, authority or persistence change.
**Primary implementation:** `src/leonardo/core/`, `src/leonardo/audit/event_v1.py`, and the GUI integration identified below.

## Reading this documentation

| Document | Purpose |
|---|---|
| [This entry manual](LIGHT_V2_RUNTIME.md) | Scope, vocabulary, supported behaviour, operational use and limitations |
| [Architecture and integration](CORE_ARCHITECTURE.md) | Composition, authorities, dependency direction, threads, module responsibilities and reconstruction order |
| [Complete lifecycles](CORE_LIFECYCLES.md) | Construction, execution, progress, cancellation, retention, processes, registries, failures and shutdown/retry |
| [Data and interface contracts](CORE_DATA_CONTRACTS.md) | Exact model fields, public API inventory, validation, serialization, examples and acceptance matrix |
| [Core Complete Map](Leonardo_V2_Core_Complete_Map.pdf) | Navigable visual companion to all four written manuals |

Read the entry manual, architecture, lifecycles and contracts together. Keep the map beside them as an illustrated index; it supplements the written specification. This edition describes the accepted working checkout, not merely HEAD: it includes the Core V2 shutdown/history/process corrections audited on 9 October. Earlier task records and the 16 July Core map remain historical references. Their recommendations are not implemented features or permission to change the architecture.

The reconstruction target is the current Core **inside Leonardo**. These documents specify runtime behaviour and integration; the [Research](../research_docs/RESEARCH_SUITE.md), [Data Manager](../data_manager_docs/DATA_MANAGER.md), [Connection](../connection_docs/CONNECTION_SUITE.md) and [GUI](../gui_docs/LIGHT_V2_GUI_SHELL.md) manuals retain their subject authority. Financial formulas and durable Area schemas must be reused from their owners, not invented in Core.

## 1. Purpose, scope and vocabulary

Core is the shared, domain-neutral runtime foundation of a desktop modular monolith. It gives Areas one execution path, one task lifecycle, controlled external-process ownership, runtime registries, operational logging, audit evidence, error routing and ordered shutdown.

| Concern | Owner and meaning |
|---|---|
| Application lifecycle | LeonardoApp constructs the application and owns its status and cleanup order |
| Event loop and blocking execution | CoreRunner owns one background loop and one bounded worker pool |
| Task | TaskManager owns an in-process supervised operation, its identity, status, progress and recent history |
| Process | ProcessManager owns an actual operating-system child handle; a worker thread is not a process row |
| Connection summary | ConnectionRegistry tracks coarse state; Connection Area owns provider sessions and wire semantics |
| Window record | WindowRegistry tracks a logical window identity; Qt and GUI composition own the actual widgets |
| Action | ActionRegistry holds discoverable action definitions and trigger evidence |
| Audit event | AuditLog delivers historical evidence to configured sinks; AuditEventV1 is the durable event schema |
| Error evidence | ErrorRouter turns an exception into an audit event; it does not own a second task/process status |
| Runtime view | RuntimeManagerBackend aggregates owner snapshots; the GUI presents selected fields |

Core does not validate OHLCV, choose market identity, calculate financial studies, define snapshot compatibility, save Notebooks, decide Database membership, approve trades or call provider APIs on behalf of an Area's domain logic. Each critical state family has one owner and one controlled write path. A projection or coordination flag does not create another authority.

## 2. Production composition and execution

`LeonardoApp` manually creates the shared managers, stores and Area services. The frozen `CoreContext` carries references to those existing objects into `GuiCompositionRoot`. Freezing the context prevents rebinding fields; it does not freeze the managers themselves.

```text
GUI interaction -> presenter -> Area application service
  -> shared CoreRunner -> TaskManager task identity
  -> Core-loop coroutine OR bounded-worker callable
  -> Area result / Core TaskResult -> queued GUI callback -> presentation
```

Async callables execute on the `LeonardoCore` event-loop thread. Synchronous jobs execute through its default ThreadPoolExecutor, with four workers by default and thread prefix `LeonardoWorker`. A synchronous callable returning an awaitable is invoked in the worker, then its returned awaitable is awaited on the Core loop. The worker count limits parallel execution, not queue length or task admission.

Window focus, pane resizing, chart pan/zoom and local selection remain direct GUI operations. GUI code queues callbacks to the Qt thread; Core itself has no Qt dependency. Areas attach operation/correlation/market metadata and retain publication and stale-result policy.

After DMS composition, LeonardoApp creates `AnalysisService(self.data_manager_creation_store)` then `AnalysisApplicationService(self.core_runner, self.analysis_domain)`. The required 21st context reference is `analysis_service: AnalysisApplicationService`. GUI composition injects it into the existing AnalysisSuitePresenter and fences Suite retirement by window/presenter identity.

## 3. Starting, stopping and restarting

The standard GUI path constructs LeonardoApp, calls `startup()`, starts Core, creates or reuses QApplication, applies the theme, creates/shows Main Window, schedules one post-show reconciliation and enters the Qt event loop. `startup()` alone does not start Core. The GUI runner closes Main Window and attempts application shutdown in its finalization path.

`LeonardoApp.shutdown()` requests pending DMS cancellation, then pending Analysis cancellation, shuts down Core, terminates managed processes, updates connection tracking, closes remaining window records and emits `application.stopped`. Audit sinks close in `finally`. A failure stops the remaining ordered steps, sets status `failed`, routes the exception and re-raises. A later successful cleanup preserves an earlier failed application status. A normally stopped app requires a new LeonardoApp instance for startup.

CoreRunner's own completed lifecycle can be explicitly restarted through its existing API. During shutdown it rejects new submissions and start attempts. Repeated shutdown calls reuse the same cancellation future and stop request. A timeout can leave the worker drain running; retry may time out again. After actual loop closure and thread exit, retry retires only that completed lifecycle and permits application cleanup to continue. Defaults remain five seconds per existing wait; this is not a newly imposed whole-application deadline.

`stop_core_runtime()` uses that same DMS -> Analysis -> Core order but does not run whole-app process/tracking/audit cleanup. Exceptions propagate; the whole-app failed-state and retry qualifications above are unchanged.

## 4. Submission, progress and results

| Entry point | Input and progress support |
|---|---|
| `submit_job` | Callable receiving ProgressReporter; async on loop, sync in pool; supports progress and result callbacks |
| `submit_blocking_job` | Synchronous callable receiving ProgressReporter; rejects async functions; supports both callbacks |
| `submit_coroutine` | Already-created coroutine; supports result callback, but **has no progress_callback parameter** |

Submission returns `TaskSubmission(task_id, task_name)` after task registration, not after completion. Results use `TaskResult`: `completed` with value, `failed` with error type/message, or `cancelled`. Task IDs are generated UUID hex strings. Names normalize by stripping surrounding whitespace in TaskManager; duplicate active names are rejected unless explicitly permitted. A submission's echoed task name need not be the normalized snapshot name.

ProgressReporter updates TaskManager before dispatching an optional TaskProgress notification. `current` and `total` are integers or None; Core does not infer percentages, require non-negative values, enforce monotonic progress or clamp current to total. Area/UI policy supplies that meaning. The default dispatcher is inline: progress from a blocking callable occurs on its worker thread, and terminal delivery occurs on the Core loop. GUI callers must provide the established queued dispatcher.

Synchronous runner submission/cancel methods wait for loop work and are intended for outside-loop callers. They are not async methods to call synchronously from a Core-loop callback. Use TaskManager on its owning loop for direct async internals; do not create another runtime to work around this boundary.

CoreRunner calls the existing `normalize_task_name` before allocating its private execution coroutine. Public callable/coroutine and runtime-admission checks keep their precedence. TaskManager still normalizes its stored name; the returned TaskSubmission echoes the supplied name. This does not promise TaskManager cleanup of arbitrary caller-owned objects; submit_coroutine rejection and active-duplicate cleanup retain their separate ownership.

## 5. Cancellation and retention

Task statuses are `running`, `cancel_requested`, `completed`, `cancelled`, `failed`; the first two are active. Cancellation requests `asyncio.Task.cancel()`. A coroutine can catch cancellation and still complete. Cancelling an awaiter around an executing Python worker cannot forcibly stop the worker. Area cancellation events/checks and publication fences remain necessary for persistence-sensitive work.

Default history cap: 500. Trim oldest eligible terminal records on creation and completion, scanning past active records. At a settled point, retained count is at most `max(500, active_count)` for the default configuration. Active-only overflow is allowed. Established waiters and terminal-delivery tasks retain their task reference; a new lookup after eviction may return no snapshot or raise the existing unknown-task KeyError, depending on the API. Eviction removes runtime history, never saved Research/DMS objects or audit events.

## 6. Processes and operational registries

ProcessManager launches argument sequences without a shell, optionally with a cwd and an environment overlay. Explicit IDs are reserved before external launch; overlapping duplicates are rejected before a second launcher executes. Different IDs remain independent. Failed launch releases its reservation. Polling detects exit and emits one terminal event. Shutdown requests termination, polls until its timeout, escalates remaining handles to kill and allows an additional `min(timeout, 1 second)` wait. There is no new global launch-versus-shutdown admission protocol.

Connection summaries and websocket-channel counters are generic. Current historical Bybit integration uses REST summaries, not a production websocket workflow. `shutdown_tracking()` changes summaries, not sockets, and preserves already failed/disconnected records. Provider resource closure belongs to the Connection Area.

Window tracking uses IDs rather than display titles as identity. Show opens; activation/focus records focus. Ordinary close-event tracking is used only where appropriate. Guarded main/Research windows set `close_on_event=False`; their accepted-close signal records closure. Cancelled dirty-change prompts leave windows and registry state open. Closing a record does not delete its Qt object, saved objects or historical record.

ActionRegistry may record a trigger or invoke a handler. Risk/confirmation fields are metadata, not an automatic authorization engine. Local presentation controls do not need fake registered tasks or actions.

## 7. Audit, errors and Runtime Manager

The default application uses standard-library `leonardo` logging plus an in-memory audit sink retaining 1,000 events. JSONL is opt-in; its default configured destination is `runs/audit.jsonl`. Loading config creates no directories. JsonlAuditSink opens lazily and flushes each appended event. `AuditConfig.enabled=False` selects an in-memory sink; it does not mean that every audit call becomes a no-op.

CompositeAuditSink tries each sink and records sink failures. Emission succeeds if at least one accepts the event; all-failed emission raises. Snapshot returns the first non-empty successful sink snapshot, not a merge. In default JSONL mode the composite orders JSONL before memory. ErrorRouter emits `error.reported` and returns the event; it does not retry business work or show dialogs itself.

Runtime Manager has six tabs: Tasks, Processes, Connections, Windows, Actions, Audit; its controls are Refresh and Close. Backend snapshots additionally contain websocket channel summaries and audit-sink failures, which do not have separate visible tabs. Backend reads are taken sequentially, not as one atomic global transaction. Process snapshots poll through ProcessManager and can therefore update its terminal state and emit audit. The GUI has no task/process mutation controls; that does not make process polling side-effect-free.

## 8. Integration with current Areas

| Area | Shared runtime use | Meaning and persistence retained outside Core |
|---|---|---|
| Historical Download / Maintenance | Preflight, downloads, validation, repair, deletion and sidecar operations as tasks | Provider retries, canonical OHLCV validation/store, market locks and cache invalidation |
| Research | Catalogs, dataset loads, resident slices, studies, Study Environments, Workspace Snapshots and Notebook operations | Chart/session ownership, compatibility, dependencies, edits, assignments, dirty decisions and stores |
| Data Manager | Catalog, creation, reconciliation, update and explicit publication tasks | Recipes/Artifacts/Collections/Seeds/Database policy, source-currentness, cancellation/publication fences |
| Analysis | Saved-database binning, trend-start patterns, pinned evaluation, inspection and sensitivity | Frozen analysis inputs/rules, session identities and retrospective evidence; no predictive-validity guarantee |

DMS startup schedules one `QTimer.singleShot(0, ...)` forced reconciliation after main-window show. The open coordinator is one-shot, not a recurring 60-second timer. First Suite open performs foreground reconciliation then catalog warm-up. Later explicit/event-driven synchronization and evidence-based refresh retain DMS ownership and preserve foreground terminal reports. Suite disposal fences late results; both application shutdown routes call DMS then Analysis `cancel_all_pending()` before stopping Core. `execute_database_rebuild` remains a retained refusal/compatibility surface under current DMS policy, not a supported rebuild workflow.

Research dataset terminal bookkeeping runs before outward queued GUI delivery and outside-GUI cleanup does not depend on a surviving presenter. Its outward progress/result callbacks retain the existing Qt dispatcher; no additional task authority is introduced.

## 9. Supported limits and verification

There is no task hierarchy, priority scheduler, persistent task queue, durable task-result cache, generic resource-lifecycle plugin framework, automatic retry policy, forced worker kill or financial decision engine in Core. Process and window records persist for the manager lifetime; recent task, trigger and in-memory audit histories are bounded independently. Frozen runtime dataclasses are not deeply immutable serialization contracts.

Historical October 9 code evidence: Core V2 audit passed on 2026-10-09; 42 fresh audit checks passed, including six external probes. The unchanged candidate's broader evidence is 2,845 tests passed/seven Windows symbolic-link privilege skips, 161 focused/integration passes and 10 native Windows smoke checks. These are code-audit results, not fresh tests claimed by this documentation edition or independent human visual acceptance. Documentation checks separately validate source inventories, examples, links, PDF layout and preservation.

## 10. Source and reconstruction navigation

Start with `core/config.py`, `core/app.py` and `core/core_runner.py`; follow `task_manager.py`, `process_manager.py`, the registries, `audit_log.py`, `error_router.py` and `runtime_manager.py`. Durable event authority is `audit/event_v1.py`. GUI bridges are `gui/runner.py`, `gui/composition.py`, `gui/window_tracking.py`, `gui/action_observer.py`, `gui/windows/runtime_manager_window.py` and Area presenters. `core/async_runtime.py` contains small validation/coroutine helpers; its historical module comment does not defer the already implemented CoreRunner.

The [architecture](CORE_ARCHITECTURE.md) supplies construction and dependency order; [lifecycles](CORE_LIFECYCLES.md) specifies sequencing and failures; [contracts](CORE_DATA_CONTRACTS.md) provides exact fields/APIs and executable examples. Preserve the root [architecture guideline](../../LEONARDO_LIGHT_V2_ARCHITECTURE_GUIDELINE.md) and [AGENTS.md](../../AGENTS.md) when implementing against this reference.
