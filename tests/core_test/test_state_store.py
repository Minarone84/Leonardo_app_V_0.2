import pytest

from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.gui import (
    ActionTriggerRecord,
    WindowDefinition,
    WindowLifecycleStatus,
)
from leonardo.contracts.operations import (
    OperationKind,
    OperationLifecycleStatus,
    OperationRuntimeState,
)
from leonardo.contracts.runtime import (
    AppLifecycleStatus,
    ServiceLifecycleStatus,
    TaskLifecycleStatus,
)
from datetime import UTC, datetime
from leonardo.core.audit_log import AuditLog
from leonardo.core.state_store import StateStore


def test_state_store_tracks_app_transitions_and_audits_changes() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)

    state_store.set_app_lifecycle_status(AppLifecycleStatus.STARTING)
    state_store.set_app_lifecycle_status(AppLifecycleStatus.RUNNING)

    assert state_store.get_app_status() is AppLifecycleStatus.RUNNING
    assert state_store.get_app_state().started_at_utc is not None
    assert [event.category for event in audit_log.snapshot()] == [
        AuditCategory.STATE,
        AuditCategory.STATE,
    ]


def test_state_store_tracks_service_state_and_snapshot_is_defensive() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)

    state_store.register_service_runtime_state("audit-log")
    state_store.set_service_lifecycle_status(
        "audit-log",
        ServiceLifecycleStatus.RUNNING,
    )
    snapshot = state_store.runtime_snapshot()

    assert snapshot.service_states[0].service_id == "audit-log"
    assert snapshot.service_states[0].status is ServiceLifecycleStatus.RUNNING
    assert isinstance(snapshot.service_states, tuple)


def test_state_store_rejects_unknown_service_transition() -> None:
    state_store = StateStore(AuditLog())

    with pytest.raises(KeyError, match="not registered"):
        state_store.set_service_lifecycle_status(
            "missing",
            ServiceLifecycleStatus.RUNNING,
        )


def test_state_store_tracks_active_tasks_and_removes_terminal_tasks() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)

    state_store.task_started(
        task_id="task-1",
        task_name="Runtime task",
        correlation_id="corr-1",
    )

    snapshot = state_store.runtime_snapshot()
    assert snapshot.task_states[0].status is TaskLifecycleStatus.RUNNING

    state_store.task_completed("task-1")

    assert state_store.tasks_state() == ()
    assert state_store.runtime_snapshot().task_states == ()
    assert any(
        event.event_type == "task.lifecycle.completed"
        and event.task_id == "task-1"
        and event.correlation_id == "corr-1"
        for event in audit_log.snapshot()
    )


def test_state_store_tracks_windows_actions_and_operations() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log, recent_action_limit=1)
    window_definition = WindowDefinition(
        window_id="runtime-manager",
        title="Runtime Manager",
        window_type="tool",
    )

    state_store.window_opened(window_definition)
    state_store.window_focused("runtime-manager")
    action_record = ActionTriggerRecord(
        action_id="runtime.refresh",
        triggered_at_utc=datetime.now(UTC),
    )
    state_store.action_triggered(action_record)

    now = datetime.now(UTC)
    operation = OperationRuntimeState(
        operation_id="operation-1",
        operation_kind=OperationKind.USER_WORKFLOW,
        status=OperationLifecycleStatus.RUNNING,
        label="Runtime workflow",
        requested_at_utc=now,
        updated_at_utc=now,
    )
    state_store.operation_state_changed(
        operation,
        event_type="operation.lifecycle.running",
    )

    snapshot = state_store.runtime_snapshot()
    assert snapshot.window_states[0].status is WindowLifecycleStatus.FOCUSED
    assert snapshot.recent_action_triggers == (action_record,)
    assert snapshot.operation_states == (operation,)

    completed = OperationRuntimeState(
        operation_id="operation-1",
        operation_kind=OperationKind.USER_WORKFLOW,
        status=OperationLifecycleStatus.COMPLETED,
        label="Runtime workflow",
        requested_at_utc=now,
        updated_at_utc=now,
        completed_at_utc=now,
    )
    state_store.operation_state_changed(
        completed,
        event_type="operation.lifecycle.completed",
    )
    state_store.window_closed("runtime-manager")

    assert state_store.operations_state() == ()
    assert state_store.windows_state() == ()
