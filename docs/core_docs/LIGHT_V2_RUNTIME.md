# Leonardo Light V2 Core Runtime

**Status:** Current operational specification
**Updated:** 2026-08-02
**Primary implementation:** `src/leonardo/core/` and
`src/leonardo/core/app.py`

## 1. Purpose

Core is Leonardo's shared, domain-neutral runtime foundation.

It owns application lifecycle, long-running task execution, external-process
tracking, generic runtime registries, operational logging, audit evidence,
structured error routing, runtime inspection, and ordered shutdown.

Core does not own provider wire semantics, OHLCV validation, financial
calculations, Research behavior, persistence rules, analysis algorithms,
backtesting mathematics, risk decisions, or order execution.

The governing boundary is:

```text
Area owns meaning and workflow policy
→ Core runs, tracks, reports, cancels, and shuts down the work
```

## 2. Single composition root

`LeonardoApp` is the only application composition root.

It constructs one shared instance of each application-wide runtime authority:

```text
LeonardoApp
├── AppConfig
├── operational logger
├── AuditLog
├── ErrorRouter
├── TaskManager
├── CoreRunner
├── ProcessManager
├── ConnectionRegistry
├── WindowRegistry
├── ActionRegistry
├── RuntimeManagerBackend
├── Connection Area services
├── OHLCV services and stores
├── ArtifactService
├── Research services and stores
└── Data Manager services
```

Windows and presenters receive the required services through GUI composition.
They do not construct hidden Core runtimes, stores, provider registries, or
parallel managers.

The immutable `CoreContext` exposes the application services and runtime
managers required by the GUI composition root.

## 3. Runtime execution path

The normal long-running path is:

```text
GUI intent
→ presenter/controller
→ Area application service
→ CoreRunner submission
→ TaskManager identity and lifecycle
→ coroutine on the Core loop or callable in the bounded worker pool
→ progress/result callback
→ queued GUI dispatch
→ presentation update on the Qt thread
```

Short GUI operations remain direct. Opening a window, changing visibility,
selecting a row, resizing a pane, or applying local display state does not
become a fake background task merely to make Runtime Manager look busy.

## 4. Runtime authorities

| Concern | Canonical authority | Current role |
|---|---|---|
| Application lifecycle | `LeonardoApp` | Created, starting, running, stopping, stopped, failed |
| Long-running task lifecycle | `TaskManager` | Identity, status, progress, cancellation, result history |
| Async and worker execution | `CoreRunner` | One background asyncio loop and bounded worker pool |
| External child processes | `ProcessManager` | Launch, poll, terminate, kill, shutdown |
| Coarse connection state | `ConnectionRegistry` | Connection/channel snapshots only |
| Qt window runtime state | `WindowRegistry` | Registered/open/focused/close-requested/closed |
| Discoverable actions | `ActionRegistry` | Stable action definitions and trigger evidence |
| Historical audit evidence | `AuditLog` | In-memory and optional JSONL sinks |
| Structured failure evidence | `ErrorRouter` | Converts exceptions into audit events |
| Read-only runtime view | `RuntimeManagerBackend` | Aggregates direct manager snapshots |

These authorities may cooperate. They must not create competing mutable truth.

## 5. Startup and shutdown

### 5.1 GUI startup order

`LeonardoGuiRunner` performs:

```text
construct LeonardoApp
→ LeonardoApp.startup()
→ LeonardoApp.start_core_runtime()
→ construct QApplication
→ apply the default theme
→ construct GuiCompositionRoot
→ create and show Main Window
→ enter QApplication event loop
```

`startup()` transitions application state and emits lifecycle audit evidence.
It does not itself start the background event loop.

A stopped `LeonardoApp` cannot be restarted. A fresh application composition is
required.

### 5.2 Ordered shutdown

The GUI runner first closes the Main Window, then calls `LeonardoApp.shutdown()`.

Application shutdown performs:

```text
stop accepting and cancel Core tasks
→ stop Core event loop and worker executor
→ terminate managed external processes
→ mark tracked connections disconnected
→ close still-open WindowRegistry records
→ emit application.stopped audit evidence
→ close AuditLog sinks
```

Shutdown errors set the application state to `failed` and are routed through the
shared `ErrorRouter`.

## 6. CoreRunner

`CoreRunner` owns:

- one daemon thread named `LeonardoCore`;
- one asyncio event loop in that thread;
- one bounded default `ThreadPoolExecutor`;
- four worker threads by default;
- task submission, callback delivery, cancellation, and terminal results.

### 6.1 Submission types

#### `submit_job`

Accepts either an async callable or a synchronous callable.

- async callables execute on the Core event loop;
- synchronous callables execute in the shared worker pool.

#### `submit_blocking_job`

Explicitly declares a synchronous blocking boundary and always executes the
callable in the worker pool.

#### `submit_coroutine`

Accepts an already-created coroutine object and wraps it as a supervised task.

All submission paths support:

- stable task name;
- optional progress callback;
- optional result callback;
- callback dispatcher;
- duplicate-name policy;
- correlation ID;
- structured metadata.

### 6.2 GUI callback boundary

Core never mutates Qt widgets.

GUI presenters pass a dispatcher that queues progress and result callbacks back
to the Qt thread. Non-GUI callers may use inline dispatch.

### 6.3 Worker cancellation limitation

Python cannot forcibly terminate a callable already running in a worker thread.
Cancelling a Leonardo task cancels its asyncio awaiter and produces an honest
`cancelled` task result, but the underlying callable may continue until it
returns.

Blocking operations requiring prompt interruption must cooperate through their
own cancellation event/checks. Research dataset parsing, validation, and
persistence-sensitive workflows use explicit cancellation fences where needed.

Core shutdown waits for the default worker executor to settle. It does not
pretend unfinished worker code vanished because the UI stopped displaying it.

## 7. TaskManager

`TaskManager` owns canonical task identity and lifecycle.

### 7.1 Task snapshot

Each task records:

```text
task_id
task_name
status
created_at_utc
started_at_utc
finished_at_utc
progress_current
progress_total
progress_message
correlation_id
error_message
metadata
```

### 7.2 Statuses

```text
running
cancel_requested
completed
cancelled
failed
```

`running` and `cancel_requested` are active statuses.

### 7.3 Duplicate names

By default, a second active task with the same normalized name is rejected.
Application services may explicitly allow duplicate names when independent
chart, dataset, or item operations legitimately share a descriptive task name.

### 7.4 Audit and errors

Task submission, cancellation request, completion, cancellation, and failure
emit structured audit events.

Failed task exceptions are also passed to `ErrorRouter`, preserving task and
correlation identity.

### 7.5 History

TaskManager retains active and recent terminal task records. The default history
limit is 500. Active tasks are never trimmed to satisfy that limit.

## 8. ProcessManager

`ProcessManager` is the canonical owner for real operating-system child
processes.

It supports:

- launch from an argument tuple;
- optional working directory and environment overlay;
- PID and exit-code tracking;
- polling;
- graceful termination;
- forced termination after shutdown timeout;
- structured audit and error evidence.

Process statuses include:

```text
running
terminate_requested
completed
failed
terminated
```

Research calculations, historical downloads, OHLCV validation, and other
in-process jobs are **tasks**, not processes. They therefore appear under Tasks
in Runtime Manager and correctly do not create ProcessManager rows.

## 9. ConnectionRegistry

`ConnectionRegistry` owns coarse operational connection summaries, not provider
semantics.

A connection record includes:

- connection ID and label;
- status;
- kind, protocol, and direction;
- last heartbeat;
- last error;
- metadata.

Supported status transitions include:

```text
registered
connecting
connected
degraded
disconnect_requested
disconnected
failed
```

The registry also supports generic websocket-channel counters and timestamps.
The current Bybit historical workflow uses a REST connection record; no
production websocket channel is currently registered by the Connection Area.

Detailed API behavior, retry classification, authentication, subscriptions, and
wire semantics remain owned by Connection provider adapters.

## 10. WindowRegistry and GUI tracking

`WindowRegistry` owns runtime state records without owning Qt objects.

A tracked window moves through:

```text
registered
open
close_requested
closed
```

It records opening, focus, and closing timestamps.

`GuiWindowTracker` bridges Qt events to the registry:

- Show → open;
- WindowActivate/FocusIn → focus;
- Close → close requested and closed.

Long-lived top-level application, suite, workflow, manager, editor, detached
chart, and Research dialog windows are tracked. Short-lived framework message
boxes are not individual durable runtime windows.

Closed records remain available as historical runtime state. Reopening a
single-instance logical window uses the same canonical identity.

## 11. ActionRegistry

`ActionRegistry` is used for operations requiring application-wide discovery,
shared invocation, shortcuts, audit, automation, or future AI access.

An action definition may contain:

- stable action ID;
- label;
- optional handler;
- owning window ID;
- risk level;
- confirmation-required metadata;
- audit policy;
- additional metadata.

The registry records trigger evidence and may invoke a registered handler. It
does not replace Area-owned business validation or persistence authority.

Local presentation actions do not require registration.

## 12. Logging, audit, and error routing

### 12.1 Operational logging

Leonardo uses the standard-library `leonardo` logger for diagnostics, lifecycle,
task, process, and failure messages.

### 12.2 AuditLog

Audit evidence is separate from mutable runtime state.

The default configuration uses an in-memory sink with a maximum of 1000 events.
An optional JSONL sink may be enabled at:

```text
runs/audit.jsonl
```

Audit sink failures are recorded and exposed through Runtime Manager rather than
silently corrupting the primary operation.

### 12.3 ErrorRouter

`ErrorRouter` converts exceptions into `AuditEventV1` evidence containing, where
available:

- task ID;
- process ID;
- connection ID;
- correlation ID;
- error type and message;
- structured context.

It does not become a second error-state owner for tasks or processes.

## 13. Runtime Manager

`RuntimeManagerBackend` creates a read-only point-in-time snapshot directly from
the canonical managers.

A snapshot contains:

```text
generated_at_utc
application status
actor ID
tasks
processes
connections
websocket channels
windows
actions
recent audit events
audit sink failures
```

Runtime Manager rows are disposable projections. Runtime Manager does not
mutate the underlying task, process, connection, window, action, or audit state.

## 14. Current Area integration

### Connection and OHLCV

- Historical preflight and download are Core tasks.
- OHLCV validation, deletion, sidecar reconstruction, and repair are Core tasks.
- Provider sessions update ConnectionRegistry.
- Dataset mutation uses canonical OHLCV stores and per-MarketId operation locks.

### Research

All Research application services share the same CoreRunner:

```text
ResearchDatasetApplicationService
ResearchStudyApplicationService
ResearchStudySetupApplicationService
ResearchWorkspaceSnapshotApplicationService
ResearchNotebookApplicationService
```

Research catalog scans, dataset loads, resident slices, Study operations,
Environment operations, Workspace operations, and Notebook persistence appear
as TaskManager rows.

Chart pan, zoom, local style changes, pane layout, and window focus remain direct
GUI operations.

### Data Manager

Data Manager application operations also use the shared CoreRunner and canonical
OHLCV/Artifact authorities. Its final user acceptance is tracked separately
from the Research Suite freeze.

## 15. Current limitations and deliberate non-features

- There is no parent-child aggregate task model. Composite workflows appear as
  their actual individual tasks.
- Worker threads cannot be forcibly killed; cooperative cancellation is required.
- ProcessManager is available but current Research and historical-download
  workflows do not launch child processes.
- ConnectionRegistry supports websocket summaries, but the current Connection
  Area has no production websocket workflow.
- Action risk and confirmation metadata do not replace Area service checks.
- Core is not a financial or provider decision engine.

## 16. Primary source map

```text
src/leonardo/core/app.py
src/leonardo/core/core_runner.py
src/leonardo/core/task_manager.py
src/leonardo/core/process_manager.py
src/leonardo/core/connection_registry.py
src/leonardo/core/window_registry.py
src/leonardo/core/action_registry.py
src/leonardo/core/audit_log.py
src/leonardo/core/error_router.py
src/leonardo/core/runtime_manager.py
src/leonardo/gui/runner.py
src/leonardo/gui/window_tracking.py
src/leonardo/gui/composition.py
```

Primary tests:

```text
tests/core_test/
tests/gui_test/test_gui_runner.py
tests/core_test/test_architecture_reset.py
tests/core_test/test_blocking_work_boundary.py
tests/core_test/test_light_core.py
tests/core_test/test_runtime_snapshot.py
```
