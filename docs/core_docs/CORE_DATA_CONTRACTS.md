# Core data and interface contracts

**Targeted revision: 2026-10-28 (R07).** Reconciles accepted R01-R06 and current source. Earlier edition dates and validation counts below remain historical; R08 integrated and R09 native acceptance are separate, not performed by this documentation revision.

**Verified:** 2026-10-09, accepted Core V2 candidate. Read with [scope](LIGHT_V2_RUNTIME.md), [architecture](CORE_ARCHITECTURE.md), [lifecycles](CORE_LIFECYCLES.md) and the [map](Leonardo_V2_Core_Complete_Map.pdf).

## 1. Contract classification and inventory

AuditEventV1 is the durable schema written by current Leonardo and read later. CoreContext, config, ActionDefinition, submissions/progress/results, manager snapshots and private records are internal/runtime models. Dataclasses and type annotations do not automatically create persisted/public compatibility contracts. Frozen means fields cannot be rebound normally; nested dict payloads are not universally deeply immutable.

Appendices list every annotated dataclass field from all 13 `core/*.py` files plus `audit/event_v1.py`: 22 models, including 17 non-private and 5 private implementation records. They also list 111 source-declared callable/property/constructor signatures, including protocol methods and the explicitly listed private `_TaskIdRef` constructor. Generated dataclass constructors are represented by the field tables, not counted as separate signatures. Private record inventory explains implementation; it is not an additional API commitment. The inventory is generated from AST and mechanically compared with the audited source.

## 2. Configuration and reference bundle

`load_default_config(root=None)` resolves supplied root or cwd without creating directories. App name is `Leonardo Light V2`, environment `development`, actor `local-user`, development_mode true. RuntimePaths: repo_root plus runs, historical_data, tmp, study_environments, workspace_snapshots, research_notebooks and data_manager below it. Audit defaults: enabled true, memory_max_events 1000, jsonl_enabled false; the loader supplies `runs/audit.jsonl` as jsonl_path even though file output is off.

Constructing frozen config dataclasses is not a full config validation engine. Sink construction checks a positive exact integer memory cap; enabled JSONL with no path is rejected by app composition. Audit disabled selects an in-memory sink. CoreContext has 21 required references and contains no serialized manager state. The complete field list below is authoritative for this edition.

## 3. Execution boundary and validation

| Surface | Enforced behaviour / default |
|---|---|
| CoreRunner constructor | TaskManager instance; positive exact int worker count, default 4 |
| TaskManager constructor | Positive exact int history cap, default 500; non-empty actor; checks supplied router/audit/logger types |
| Task name | String, trimmed; blank rejected; active duplicate rejected unless allowed |
| Submitted job | Callable; submit_blocking_job excludes coroutine functions; submit_coroutine requires inspect.iscoroutine |
| TaskManager coroutine | Actual coroutine object on a running loop; not a general Future/awaitable adapter |
| Task ID | uuid4().hex at registration; task snapshot lookup returns None when absent; wait raises KeyError |
| Progress | message string; current/total exact int or None (bool rejected); no range/monotonic/percentage contract |
| Shutdown timeout | Positive int/float (bool rejected), default 5.0; existing per-wait semantics |
| Result | TaskResult has completed/value, failed/error_type/error_message, or cancelled; not automatically serialized |
| Dispatch | Callable receiving zero-argument callback; default inline; GUI supplies queued dispatch |

Progress details are copied into TaskProgress only. Metadata is copied into task records and snapshots; nested values do not become immutable. Correlation IDs are passed through as supplied; Core does not interpret market IDs embedded in metadata. A failed job's task.failed evidence and ErrorRouter's error.reported are distinct events.

Callable type aliases complete the method inventory:

| Alias | Required shape |
|---|---|
| ProgressCallback | Callable taking TaskProgress and returning None |
| ResultCallback | Callable taking TaskResult and returning None |
| JobCallable | Callable taking ProgressReporter and returning an object or Awaitable of object |
| BlockingJobCallable | Callable taking ProgressReporter and returning object |
| CallbackDispatcher | Callable taking a zero-argument, None-returning callback and returning None |
| CoroutineObject | Coroutine[Any, Any, object] accepted by the coroutine helper |

`submit_coroutine` intentionally has no progress_callback argument. Public signatures below settle differences between submission methods. Return annotations do not constitute automatic runtime validation of arbitrary job return values. Synchronous runner waits are outside-loop interfaces; invoking them from a Core-loop callback can block the loop they need.

CoreRunner uses `normalize_task_name` before allocating its private `execute()` coroutine. Existing public validation/admission precedence remains: invalid callables/coroutines and closed runtime checks are not displaced by the private check. TaskSubmission echoes the caller name; TaskManager stores the normalized name. Rejected submit_coroutine caller cleanup and duplicate-name cleanup remain distinct from generic TaskManager ownership.

## 4. Registry and process rules

| Owner | Validation, identity and ordering |
|---|---|
| ProcessManager | Nonempty command with nonempty string parts; nonempty label stripped for record; explicit ID or UUID; published/in-flight duplicate rejected. No reusable ID after terminal record remains registered. snapshots preserve dictionary insertion order and poll. |
| ConnectionRegistry | Nonempty connection ID/label; duplicate rejected; kind/protocol/direction strings are descriptive values, not enum enforcement. Lists sorted by ID. Mark methods assign known statuses without a strict predecessor graph. |
| Channels | Existing parent connection, unique channel ID; positive exact integer increments; last-message UTC time. Registration does not repeat connection-style nonempty-text validation for channel ID/label. |
| WindowRegistry | Nonempty ID/title; identical title/type re-registration returns existing record; conflicting registration raises. Sorted IDs; focus requires open; open_windows includes close_requested. |
| ActionDefinition/Registry | Nonempty ID/label; callable handler or None; copied metadata. Exact duplicate definition allowed; conflicting ID rejected. Definitions sorted; latest 500 triggers in insertion order. |

Public snapshot dataclasses do not validate every field in `__post_init__`; their owner constructs meaningful values. Source's current validation must not be silently strengthened in a reconstruction. Window/process/connection/action records have no generic delete or unregister operation. ProcessLauncher and ManagedProcessHandle are structural protocols: launcher receives command/cwd/env; handle exposes pid, poll, terminate and kill. Default launcher uses subprocess.Popen with argument tuple, inherited environment unless an overlay is supplied, and no shell=True.

## 5. AuditEventV1 durable representation

All 17 fields are listed in the model appendix. Required construction input is event_type and message. Defaults include UUID hex event_id, schema_version `1.0`, UTC timestamp, severity `info`, category `runtime`, empty details and None optional identities/errors.

Constructor validates nonempty strings for event_id/schema_version/event_type/message/severity/category and a timezone-aware datetime timestamp; it normalizes timestamp to UTC. It does **not** restrict severity/category to enumerations or reject every non-`1.0` nonempty version string. Optional text type checking happens on from_dict; constructor annotations alone are not an equal validation guarantee.

Details must be a Mapping; keys become strings. Accepted values: None, str/int/bool, finite float, aware datetime normalized to UTC ISO text, Enum converted through its value, nested mappings, and non-string/non-bytes sequences normalized recursively to tuples. Unsupported objects, bytes, naive datetimes and non-finite floats reject. `to_dict` renders tuple sequences as JSON lists and timestamp as ISO text; optional None fields are retained.

`from_dict` requires a mapping, ISO timestamp string, required nonempty text fields and mapping details; optional text must be string or None. A trailing Z is accepted and normalized via +00:00. Extra mapping keys are ignored by construction rather than retained. No implicit migration or strict schema-version negotiation is implemented.

JSONL sink writes one `json.dumps(event.to_dict(), sort_keys=True)` line per event with immediate flush. Reading skips blank lines and validates every event. Core provides no JSONL rotation, archive compression, invalid-line skipping or automatic repair. The optional audit file is evidence, not a source for rebuilding live task/process ownership.

Core event vocabulary is explicit: `application.starting`, `application.started`, `application.stopped`; `task.submitted`, `task.cancel_requested`, `task.completed`, `task.cancelled`, `task.failed`; `process.started`, `process.termination_requested`, `process.completed`, `process.failed`, `process.terminated`; `action.triggered`; and `error.reported`. Lifecycle categories are lifecycle/runtime/action/error as constructed by their owners. This is current usage, not a schema-enforced closed enum. ConnectionRegistry and WindowRegistry themselves update records without emitting a parallel event for every status change. Errors may add error.reported without introducing a second terminal task/process state.

## 6. RuntimeSnapshot projection and visible UI

Backend uses dataclasses.asdict for tasks, processes, connections, channels, windows and sink failures; datetime objects remain Python datetimes in those projections. It uses AuditEventV1.to_dict for recent_events. RuntimeSnapshot as a whole is therefore not an automatically JSON-ready persisted schema.

Action projection is exactly action_id, label, window_id, risk_level, confirmation_required; handler, audit_enabled and arbitrary definition metadata are not included. The six GUI tables select:

| Tab | Visible columns |
|---|---|
| Tasks | task_id, task_name, status, progress_message |
| Processes | process_id, label, status, pid |
| Connections | connection_id, label, status, protocol |
| Windows | window_id, title, status, window_type |
| Actions | action_id, label, window_id, risk_level |
| Audit | timestamp_utc, severity, event_type, message |

Backend websocket_channels and audit_sink_failures have no dedicated tabs. Snapshot reads are sequential; ProcessManager.snapshots polls and may transition a record and emit terminal audit. There is no globally atomic or side-effect-free snapshot promise.

## 7. Executable examples

These examples are validated against this edition using disposable objects and temporary paths. They are illustrations of current interfaces, not new app composition or production persistence conventions.

### 7.1 A result delivered without a Qt dependency

```python
from threading import Event
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager

runner = CoreRunner(TaskManager())
received, ready = [], Event()
runner.start()
try:
    submission = runner.submit_blocking_job(
        lambda reporter: 42,
        task_name="documentation.example",
        result_callback=lambda result: (received.append(result), ready.set()),
    )
    assert ready.wait(5)
    assert received[0].task_id == submission.task_id
    assert received[0].status == "completed" and received[0].value == 42
finally:
    runner.shutdown()
```

### 7.2 Durable event round-trip in an isolated directory

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, datetime
from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import JsonlAuditSink

event = AuditEventV1(
    event_id="documentation-event", event_type="task.completed",
    message="Generated example", timestamp_utc=datetime(2026, 10, 9, tzinfo=UTC),
    task_id="generated-task", details={"rows": 3, "labels": ["a", "b"]},
)
assert AuditEventV1.from_dict(event.to_dict()) == event
with TemporaryDirectory(prefix="leonardo_docs_") as folder:
    sink = JsonlAuditSink(Path(folder) / "audit.jsonl")
    sink.emit(event)
    sink.close()
    assert sink.snapshot() == (event,)
```

### 7.3 Reopen a logical window without replacing saved objects

```python
from leonardo.core.window_registry import WindowRegistry

windows = WindowRegistry()
windows.register_window("docs.window", title="Generated example")
opened = windows.open_window("docs.window")
windows.request_window_close("docs.window")
windows.close_window("docs.window")
reopened = windows.open_window("docs.window")
assert reopened.status == "open" and reopened.closed_at_utc is None
assert reopened.opened_at_utc == opened.opened_at_utc
```

This registry example does not create/close a Qt widget. In production, accepted-close tracking coordinates the actual widget lifecycle.

## 8. Verification matrix

| Contract | Principal repository evidence |
|---|---|
| Application composition, progress/cancel/failure, audit, registries | `tests/core_test/test_light_core.py` |
| Async versus blocking job placement and responsiveness | `tests/core_test/test_blocking_work_boundary.py` |
| No retired heavy runtime authority revived | `tests/core_test/test_architecture_reset.py` |
| Direct manager RuntimeSnapshot aggregation | `tests/core_test/test_runtime_snapshot.py` |
| Shared shutdown retry, retention and process identity fix | `tests/core_test/test_core_audit_regressions.py` |
| Durable schema validation | `tests/schema_test/test_surviving_schemas.py` |
| GUI startup/finalization and snapshot presentation | `tests/gui_test/test_gui_runner.py`, `test_light_gui.py`, `test_light_gui_static.py` |
| Window identity and guarded acceptance | `test_database_content_window_identity.py`, `test_research_composed_transition_guards.py` in `tests/gui_test/` |
| Area service disposal and reconciliation | `test_research_gui_service_shutdown.py`, `test_data_manager_reconciliation_lifecycle.py` in `tests/gui_test/` |

Required controls include default 500-cap/620 completed tasks behind an active record, active-only overflow, completed/failed/cancelled waiter delivery, repeated shutdown during and after drain, rejected admission while draining, normal explicit restart, duplicate process reservation and failure release. The accepted V2 audit also tested old-lifecycle retirement after new restart and queued progress/results after eviction. Existing broad/native results are summarized in the entry manual; documentation verification is recorded separately under the canonical Task Packages root.

The 2026-10-28 reconciliation statically checks accepted R06 source, the 21 CoreContext fields and existing API inventory. R01-R06 acceptance receipts retain their original product-test provenance. No product tests, native checks or example execution are repeated by R07; R08/R09 remain pending.

## 9. Source-exact model inventory

Tables below preserve annotation/default spelling from source. `(required)` means no field default. Factories such as `dict`, UTC-now and uuid4 execute per instance. Private records are labelled implementation-only. Frozen decorators describe the dataclass, not a deep immutable or durable contract.

### ActionDefinition

Source: `src/leonardo/core/action_registry.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `action_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `handler` | `Callable[..., object] \| None` | `None` |
| `window_id` | `str \| None` | `None` |
| `risk_level` | `str` | `'normal'` |
| `confirmation_required` | `bool` | `False` |
| `audit_enabled` | `bool` | `True` |
| `metadata` | `dict[str, object]` | `field(default_factory=dict)` |

### ActionTrigger

Source: `src/leonardo/core/action_registry.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `action_id` | `str` | `(required)` |
| `triggered_at_utc` | `datetime` | `(required)` |
| `actor_id` | `str` | `(required)` |
| `window_id` | `str \| None` | `(required)` |
| `correlation_id` | `str \| None` | `(required)` |
| `metadata` | `dict[str, object]` | `(required)` |

### CoreContext

Source: `src/leonardo/core/app.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `config` | `AppConfig` | `(required)` |
| `logger` | `logging.Logger` | `(required)` |
| `audit_log` | `AuditLog` | `(required)` |
| `error_router` | `ErrorRouter` | `(required)` |
| `task_manager` | `TaskManager` | `(required)` |
| `core_runner` | `CoreRunner` | `(required)` |
| `process_manager` | `ProcessManager` | `(required)` |
| `connection_registry` | `ConnectionRegistry` | `(required)` |
| `window_registry` | `WindowRegistry` | `(required)` |
| `action_registry` | `ActionRegistry` | `(required)` |
| `runtime_manager` | `RuntimeManagerBackend` | `(required)` |
| `connection_service` | `ConnectionApplicationService` | `(required)` |
| `historical_download_service` | `HistoricalDownloadApplicationService` | `(required)` |
| `ohlcv_maintenance_service` | `OHLCVMaintenanceApplicationService` | `(required)` |
| `research_dataset_service` | `ResearchDatasetApplicationService` | `(required)` |
| `research_study_service` | `ResearchStudyApplicationService` | `(required)` |
| `research_study_setup_service` | `ResearchStudySetupApplicationService` | `(required)` |
| `research_workspace_snapshot_service` | `ResearchWorkspaceSnapshotApplicationService` | `(required)` |
| `research_notebook_service` | `ResearchNotebookApplicationService` | `(required)` |
| `data_manager_service` | `DataManagerApplicationService` | `(required)` |
| `analysis_service` | `AnalysisApplicationService` | `(required)` |

### AuditSinkFailure

Source: `src/leonardo/core/audit_log.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `sink_name` | `str` | `(required)` |
| `operation` | `str` | `(required)` |
| `error_type` | `str` | `(required)` |
| `message` | `str` | `(required)` |

### RuntimePaths

Source: `src/leonardo/core/config.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `repo_root` | `Path` | `(required)` |
| `runs_dir` | `Path` | `(required)` |
| `historical_data_dir` | `Path` | `(required)` |
| `tmp_dir` | `Path` | `(required)` |
| `study_environments_dir` | `Path` | `(required)` |
| `workspace_snapshots_dir` | `Path` | `(required)` |
| `research_notebooks_dir` | `Path` | `(required)` |
| `data_manager_dir` | `Path` | `(required)` |

### AuditConfig

Source: `src/leonardo/core/config.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `enabled` | `bool` | `True` |
| `memory_max_events` | `int` | `1000` |
| `jsonl_enabled` | `bool` | `False` |
| `jsonl_path` | `Path \| None` | `None` |

### AppConfig

Source: `src/leonardo/core/config.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `app_name` | `str` | `(required)` |
| `environment` | `str` | `(required)` |
| `paths` | `RuntimePaths` | `(required)` |
| `audit` | `AuditConfig` | `(required)` |
| `actor_id` | `str` | `'local-user'` |
| `development_mode` | `bool` | `True` |

### ConnectionSnapshot

Source: `src/leonardo/core/connection_registry.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `connection_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `status` | `str` | `(required)` |
| `kind` | `str` | `(required)` |
| `protocol` | `str` | `(required)` |
| `direction` | `str` | `(required)` |
| `last_heartbeat_utc` | `datetime \| None` | `(required)` |
| `last_error_message` | `str \| None` | `(required)` |
| `metadata` | `dict[str, object]` | `(required)` |

### ChannelSnapshot

Source: `src/leonardo/core/connection_registry.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `channel_id` | `str` | `(required)` |
| `connection_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `received_count` | `int` | `(required)` |
| `sent_count` | `int` | `(required)` |
| `error_count` | `int` | `(required)` |
| `last_message_at_utc` | `datetime \| None` | `(required)` |

### _ConnectionRecord

Source: `src/leonardo/core/connection_registry.py`. Private implementation record. Decorators: `dataclass`.

| Field | Type | Default |
|---|---|---|
| `connection_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `kind` | `str` | `(required)` |
| `protocol` | `str` | `(required)` |
| `direction` | `str` | `(required)` |
| `status` | `str` | `'registered'` |
| `last_heartbeat_utc` | `datetime \| None` | `None` |
| `last_error_message` | `str \| None` | `None` |
| `metadata` | `dict[str, object]` | `field(default_factory=dict)` |

### _ChannelRecord

Source: `src/leonardo/core/connection_registry.py`. Private implementation record. Decorators: `dataclass`.

| Field | Type | Default |
|---|---|---|
| `channel_id` | `str` | `(required)` |
| `connection_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `received_count` | `int` | `0` |
| `sent_count` | `int` | `0` |
| `error_count` | `int` | `0` |
| `last_message_at_utc` | `datetime \| None` | `None` |

### TaskSubmission

Source: `src/leonardo/core/core_runner.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `task_id` | `str` | `(required)` |
| `task_name` | `str` | `(required)` |

### TaskProgress

Source: `src/leonardo/core/core_runner.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `task_id` | `str` | `(required)` |
| `message` | `str` | `(required)` |
| `current` | `int \| None` | `None` |
| `total` | `int \| None` | `None` |
| `details` | `Mapping[str, object] \| None` | `None` |

### TaskResult

Source: `src/leonardo/core/core_runner.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `task_id` | `str` | `(required)` |
| `status` | `str` | `(required)` |
| `value` | `object \| None` | `None` |
| `error_type` | `str \| None` | `None` |
| `error_message` | `str \| None` | `None` |

### ProcessSnapshot

Source: `src/leonardo/core/process_manager.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `process_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `command` | `tuple[str, ...]` | `(required)` |
| `status` | `str` | `(required)` |
| `pid` | `int \| None` | `(required)` |
| `exit_code` | `int \| None` | `(required)` |
| `started_at_utc` | `datetime` | `(required)` |
| `finished_at_utc` | `datetime \| None` | `(required)` |
| `error_message` | `str \| None` | `(required)` |

### _ProcessRecord

Source: `src/leonardo/core/process_manager.py`. Private implementation record. Decorators: `dataclass`.

| Field | Type | Default |
|---|---|---|
| `process_id` | `str` | `(required)` |
| `label` | `str` | `(required)` |
| `command` | `tuple[str, ...]` | `(required)` |
| `handle` | `ManagedProcessHandle` | `(required)` |
| `status` | `str` | `'running'` |
| `pid` | `int \| None` | `None` |
| `exit_code` | `int \| None` | `None` |
| `started_at_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `finished_at_utc` | `datetime \| None` | `None` |
| `error_message` | `str \| None` | `None` |
| `terminal_event_emitted` | `bool` | `False` |

### RuntimeSnapshot

Source: `src/leonardo/core/runtime_manager.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `generated_at_utc` | `datetime` | `(required)` |
| `app_status` | `str` | `(required)` |
| `actor_id` | `str` | `(required)` |
| `tasks` | `tuple[dict[str, object], ...]` | `(required)` |
| `processes` | `tuple[dict[str, object], ...]` | `(required)` |
| `connections` | `tuple[dict[str, object], ...]` | `(required)` |
| `websocket_channels` | `tuple[dict[str, object], ...]` | `(required)` |
| `windows` | `tuple[dict[str, object], ...]` | `(required)` |
| `actions` | `tuple[dict[str, object], ...]` | `(required)` |
| `recent_events` | `tuple[dict[str, object], ...]` | `(required)` |
| `audit_sink_failures` | `tuple[dict[str, object], ...]` | `(required)` |

### TaskSnapshot

Source: `src/leonardo/core/task_manager.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `task_id` | `str` | `(required)` |
| `task_name` | `str` | `(required)` |
| `status` | `str` | `(required)` |
| `created_at_utc` | `datetime` | `(required)` |
| `started_at_utc` | `datetime \| None` | `(required)` |
| `finished_at_utc` | `datetime \| None` | `(required)` |
| `progress_current` | `int \| None` | `(required)` |
| `progress_total` | `int \| None` | `(required)` |
| `progress_message` | `str` | `(required)` |
| `correlation_id` | `str \| None` | `(required)` |
| `error_message` | `str \| None` | `(required)` |
| `metadata` | `dict[str, object]` | `(required)` |

### _TaskRecord

Source: `src/leonardo/core/task_manager.py`. Private implementation record. Decorators: `dataclass`.

| Field | Type | Default |
|---|---|---|
| `task_id` | `str` | `(required)` |
| `task_name` | `str` | `(required)` |
| `asyncio_task` | `asyncio.Task[object]` | `(required)` |
| `status` | `str` | `'running'` |
| `created_at_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `started_at_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `finished_at_utc` | `datetime \| None` | `None` |
| `progress_current` | `int \| None` | `None` |
| `progress_total` | `int \| None` | `None` |
| `progress_message` | `str` | `''` |
| `correlation_id` | `str \| None` | `None` |
| `error_message` | `str \| None` | `None` |
| `metadata` | `dict[str, object]` | `field(default_factory=dict)` |

### WindowSnapshot

Source: `src/leonardo/core/window_registry.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `window_id` | `str` | `(required)` |
| `title` | `str` | `(required)` |
| `window_type` | `str` | `(required)` |
| `status` | `str` | `(required)` |
| `opened_at_utc` | `datetime \| None` | `(required)` |
| `focused_at_utc` | `datetime \| None` | `(required)` |
| `closed_at_utc` | `datetime \| None` | `(required)` |
| `metadata` | `dict[str, object]` | `(required)` |

### _WindowRecord

Source: `src/leonardo/core/window_registry.py`. Private implementation record. Decorators: `dataclass`.

| Field | Type | Default |
|---|---|---|
| `window_id` | `str` | `(required)` |
| `title` | `str` | `(required)` |
| `window_type` | `str` | `(required)` |
| `status` | `str` | `'registered'` |
| `opened_at_utc` | `datetime \| None` | `None` |
| `focused_at_utc` | `datetime \| None` | `None` |
| `closed_at_utc` | `datetime \| None` | `None` |
| `metadata` | `dict[str, object]` | `field(default_factory=dict)` |

### AuditEventV1

Source: `src/leonardo/audit/event_v1.py`. Decorators: `dataclass(frozen=True)`.

| Field | Type | Default |
|---|---|---|
| `event_type` | `str` | `(required)` |
| `message` | `str` | `(required)` |
| `severity` | `str` | `'info'` |
| `category` | `str` | `'runtime'` |
| `event_id` | `str` | `field(default_factory=lambda: uuid4().hex)` |
| `schema_version` | `str` | `'1.0'` |
| `timestamp_utc` | `datetime` | `field(default_factory=lambda: datetime.now(UTC))` |
| `actor_id` | `str \| None` | `None` |
| `window_id` | `str \| None` | `None` |
| `action_id` | `str \| None` | `None` |
| `task_id` | `str \| None` | `None` |
| `process_id` | `str \| None` | `None` |
| `connection_id` | `str \| None` | `None` |
| `correlation_id` | `str \| None` | `None` |
| `details` | `Mapping[str, object]` | `field(default_factory=dict)` |
| `error_type` | `str \| None` | `None` |
| `error_message` | `str \| None` | `None` |

## 10. Source-exact public interface inventory

The following signatures include constructors and properties. `self` is shown to match source; callers do not supply it. Protocol ellipses represent structural ports. An annotation is not an extra runtime validator. All operation/failure meanings are defined in the preceding sections and lifecycle manual.

### src/leonardo/core/action_registry.py

```python
ActionRegistry.__init__(self, audit_log: AuditLog, *, actor_id: str='local-user') -> None

ActionRegistry.register_action(self, definition: ActionDefinition | None=None, *, action_id: str | None=None, label: str | None=None, handler: Callable[..., object] | None=None, window_id: str | None=None, risk_level: str='normal', confirmation_required: bool=False, audit_enabled: bool=True, metadata: dict[str, object] | None=None) -> ActionDefinition

ActionRegistry.get_action_definition(self, action_id: str) -> ActionDefinition | None

ActionRegistry.list_actions(self) -> tuple[ActionDefinition, ...]

ActionRegistry.record_trigger(self, action_id: str, *, window_id: str | None=None, actor_id: str | None=None, correlation_id: str | None=None, metadata: dict[str, object] | None=None) -> ActionTrigger

ActionRegistry.invoke(self, action_id: str, *args: object, actor_id: str | None=None, window_id: str | None=None, correlation_id: str | None=None, metadata: dict[str, object] | None=None, **kwargs: object) -> object

ActionRegistry.recent_triggers(self) -> tuple[ActionTrigger, ...]

```

### src/leonardo/core/app.py

```python
LeonardoApp.__init__(self, config: AppConfig | None=None) -> None

@property
LeonardoApp.context(self) -> CoreContext

@property
LeonardoApp.status(self) -> str

LeonardoApp.startup(self) -> CoreContext

LeonardoApp.start_core_runtime(self) -> CoreContext

LeonardoApp.stop_core_runtime(self, *, timeout: float=5.0) -> None

LeonardoApp.shutdown(self, *, timeout: float=5.0, reason: str='Application shutdown requested') -> None

```

### src/leonardo/core/async_runtime.py

```python
utc_now() -> datetime

normalize_task_name(task_name: str) -> str

is_coroutine_object(value: object) -> bool

close_coroutine_if_needed(value: object) -> None

```

### src/leonardo/core/audit_log.py

```python
AuditSink.emit(self, event: AuditEventV1) -> AuditEventV1

AuditSink.snapshot(self) -> tuple[AuditEventV1, ...]

AuditSink.flush(self) -> None

AuditSink.close(self) -> None

InMemoryAuditSink.__init__(self, max_events: int=1000) -> None

@property
InMemoryAuditSink.max_events(self) -> int

InMemoryAuditSink.emit(self, event: AuditEventV1) -> AuditEventV1

InMemoryAuditSink.snapshot(self) -> tuple[AuditEventV1, ...]

InMemoryAuditSink.flush(self) -> None

InMemoryAuditSink.close(self) -> None

JsonlAuditSink.__init__(self, path: Path | str) -> None

@property
JsonlAuditSink.path(self) -> Path

JsonlAuditSink.emit(self, event: AuditEventV1) -> AuditEventV1

JsonlAuditSink.snapshot(self) -> tuple[AuditEventV1, ...]

JsonlAuditSink.flush(self) -> None

JsonlAuditSink.close(self) -> None

CompositeAuditSink.__init__(self, sinks: tuple[AuditSink, ...]) -> None

CompositeAuditSink.emit(self, event: AuditEventV1) -> AuditEventV1

CompositeAuditSink.snapshot(self) -> tuple[AuditEventV1, ...]

CompositeAuditSink.flush(self) -> None

CompositeAuditSink.close(self) -> None

CompositeAuditSink.sink_failures(self) -> tuple[AuditSinkFailure, ...]

AuditLog.__init__(self, sink: AuditSink) -> None

AuditLog.emit(self, event: AuditEventV1) -> AuditEventV1

AuditLog.snapshot(self) -> tuple[AuditEventV1, ...]

AuditLog.flush(self) -> None

AuditLog.close(self) -> None

AuditLog.sink_failures(self) -> tuple[AuditSinkFailure, ...]

```

### src/leonardo/core/config.py

```python
load_default_config(repo_root: Path | str | None=None) -> AppConfig

```

### src/leonardo/core/connection_registry.py

```python
ConnectionRegistry.__init__(self) -> None

ConnectionRegistry.register_connection(self, connection_id: str, *, label: str, kind: str='external_service', protocol: str='unknown', direction: str='outbound', metadata: dict[str, object] | None=None) -> ConnectionSnapshot

ConnectionRegistry.register_websocket_channel(self, channel_id: str, *, connection_id: str, label: str) -> ChannelSnapshot

ConnectionRegistry.mark_connecting(self, connection_id: str) -> ConnectionSnapshot

ConnectionRegistry.mark_connected(self, connection_id: str) -> ConnectionSnapshot

ConnectionRegistry.mark_degraded(self, connection_id: str, *, error: str) -> ConnectionSnapshot

ConnectionRegistry.mark_disconnect_requested(self, connection_id: str) -> ConnectionSnapshot

ConnectionRegistry.mark_disconnected(self, connection_id: str) -> ConnectionSnapshot

ConnectionRegistry.mark_failed(self, connection_id: str, *, error: str) -> ConnectionSnapshot

ConnectionRegistry.record_heartbeat(self, connection_id: str, *, timestamp_utc: datetime | None=None) -> ConnectionSnapshot

ConnectionRegistry.record_channel_received(self, channel_id: str, *, count: int=1) -> ChannelSnapshot

ConnectionRegistry.record_channel_sent(self, channel_id: str, *, count: int=1) -> ChannelSnapshot

ConnectionRegistry.record_channel_error(self, channel_id: str, *, count: int=1) -> ChannelSnapshot

ConnectionRegistry.connection_states(self) -> tuple[ConnectionSnapshot, ...]

ConnectionRegistry.websocket_channel_states(self) -> tuple[ChannelSnapshot, ...]

ConnectionRegistry.shutdown_tracking(self) -> tuple[ConnectionSnapshot, ...]

```

### src/leonardo/core/core_runner.py

```python
ProgressReporter.__init__(self, task_manager: TaskManager, task_id_ref: '_TaskIdRef', callback: ProgressCallback | None, dispatcher: CallbackDispatcher) -> None

ProgressReporter.report(self, message: str, *, current: int | None=None, total: int | None=None, details: Mapping[str, object] | None=None) -> None

_TaskIdRef.__init__(self) -> None

CoreRunner.__init__(self, task_manager: TaskManager, *, max_worker_threads: int=4) -> None

@property
CoreRunner.is_running(self) -> bool

@property
CoreRunner.is_accepting_submissions(self) -> bool

CoreRunner.start(self) -> None

CoreRunner.submit_job(self, job: JobCallable, *, task_name: str, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None, allow_duplicate_name: bool=False, correlation_id: str | None=None, metadata: dict[str, object] | None=None) -> TaskSubmission

CoreRunner.submit_blocking_job(self, job: BlockingJobCallable, *, task_name: str, progress_callback: ProgressCallback | None=None, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None, allow_duplicate_name: bool=False, correlation_id: str | None=None, metadata: dict[str, object] | None=None) -> TaskSubmission

CoreRunner.submit_coroutine(self, coroutine: Awaitable[object], *, task_name: str, result_callback: ResultCallback | None=None, callback_dispatcher: CallbackDispatcher | None=None, allow_duplicate_name: bool=False, correlation_id: str | None=None, metadata: dict[str, object] | None=None) -> TaskSubmission

CoreRunner.cancel(self, task_id: str, *, timeout: float=5.0) -> bool

CoreRunner.stop_accepting_submissions(self) -> None

CoreRunner.shutdown(self, *, timeout: float=5.0) -> None

```

### src/leonardo/core/error_router.py

```python
ErrorRouter.__init__(self, audit_log: AuditLog, *, actor_id: str='local-user') -> None

ErrorRouter.route_exception(self, exc: Exception, *, message: str, category: str='error', severity: str='error', task_id: str | None=None, process_id: str | None=None, connection_id: str | None=None, correlation_id: str | None=None, context: Mapping[str, object] | None=None) -> AuditEventV1

```

### src/leonardo/core/process_manager.py

```python
ManagedProcessHandle.poll(self) -> int | None

ManagedProcessHandle.terminate(self) -> None

ManagedProcessHandle.kill(self) -> None

ProcessLauncher.__call__(self, command: tuple[str, ...], *, cwd: Path | None, env: dict[str, str] | None) -> ManagedProcessHandle

ProcessManager.__init__(self, audit_log: AuditLog, *, error_router: ErrorRouter | None=None, launcher: ProcessLauncher | None=None, logger: logging.Logger | None=None) -> None

ProcessManager.launch(self, command: tuple[str, ...] | list[str], *, label: str, process_id: str | None=None, cwd: Path | str | None=None, env: dict[str, str] | None=None) -> str

ProcessManager.poll(self, process_id: str) -> ProcessSnapshot

ProcessManager.terminate(self, process_id: str, *, force: bool=False) -> bool

ProcessManager.active_processes(self) -> tuple[ProcessSnapshot, ...]

ProcessManager.snapshots(self) -> tuple[ProcessSnapshot, ...]

ProcessManager.get_snapshot(self, process_id: str) -> ProcessSnapshot

ProcessManager.shutdown(self, *, timeout: float=5.0) -> None

```

### src/leonardo/core/runtime_manager.py

```python
RuntimeManagerBackend.__init__(self, *, app_status_provider: Callable[[], str], actor_id: str, task_manager: TaskManager, process_manager: ProcessManager, connection_registry: ConnectionRegistry, window_registry: WindowRegistry, action_registry: ActionRegistry, audit_log: AuditLog) -> None

RuntimeManagerBackend.snapshot(self) -> RuntimeSnapshot

```

### src/leonardo/core/task_manager.py

```python
TaskManager.__init__(self, *, error_router: ErrorRouter | None=None, audit_log: AuditLog | None=None, actor_id: str='local-user', logger: logging.Logger | None=None, history_limit: int=500) -> None

TaskManager.create_task(self, coroutine: CoroutineObject, *, task_name: str, allow_duplicate_name: bool=False, correlation_id: str | None=None, metadata: dict[str, object] | None=None) -> str

async TaskManager.wait_task(self, task_id: str) -> object

TaskManager.update_progress(self, task_id: str, *, message: str, current: int | None=None, total: int | None=None) -> TaskSnapshot

TaskManager.cancel_task(self, task_id: str) -> bool

async TaskManager.cancel_all(self) -> None

TaskManager.active_tasks(self) -> tuple[TaskSnapshot, ...]

TaskManager.snapshots(self) -> tuple[TaskSnapshot, ...]

TaskManager.get_snapshot(self, task_id: str) -> TaskSnapshot | None

```

### src/leonardo/core/window_registry.py

```python
WindowRegistry.__init__(self) -> None

WindowRegistry.register_window(self, window_id: str, *, title: str, window_type: str='window', metadata: dict[str, object] | None=None) -> WindowSnapshot

WindowRegistry.open_window(self, window_id: str) -> WindowSnapshot

WindowRegistry.focus_window(self, window_id: str) -> WindowSnapshot

WindowRegistry.request_window_close(self, window_id: str) -> WindowSnapshot

WindowRegistry.close_window(self, window_id: str) -> WindowSnapshot

WindowRegistry.list_windows(self) -> tuple[WindowSnapshot, ...]

WindowRegistry.open_windows(self) -> tuple[WindowSnapshot, ...]

```

### src/leonardo/audit/event_v1.py

```python
AuditEventV1.to_dict(self) -> dict[str, object]

@classmethod
AuditEventV1.from_dict(cls, data: Mapping[str, object]) -> 'AuditEventV1'

```
