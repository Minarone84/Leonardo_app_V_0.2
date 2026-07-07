import pytest

from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.operations import (
    OperationBlocker,
    OperationKind,
    OperationLifecycleStatus,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.state_store import StateStore


def _registry() -> tuple[OperationRegistry, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    return OperationRegistry(state_store), state_store, audit_log


def test_operation_registry_tracks_requested_running_and_completed_lifecycle() -> None:
    registry, state_store, audit_log = _registry()

    requested = registry.request_operation(
        operation_kind=OperationKind.USER_WORKFLOW,
        label="Open runtime manager",
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        window_id="runtime-manager",
        action_id="runtime.open",
        correlation_id="corr-1",
    )
    running = registry.mark_running(requested.operation_id, task_id="task-1")
    active = registry.get_operation(requested.operation_id)
    completed = registry.mark_completed(requested.operation_id)

    assert requested.status is OperationLifecycleStatus.REQUESTED
    assert running.status is OperationLifecycleStatus.RUNNING
    assert running.task_id == "task-1"
    assert active == running
    assert completed.status is OperationLifecycleStatus.COMPLETED
    assert completed.task_id == "task-1"
    assert completed.is_terminal is True
    assert registry.get_operation(requested.operation_id) is None
    assert state_store.operations_state() == ()
    assert [event.event_type for event in audit_log.snapshot()] == [
        "operation.lifecycle.requested",
        "operation.lifecycle.running",
        "operation.lifecycle.completed",
    ]
    assert any(
        event.event_type == "operation.lifecycle.running"
        and event.payload["task_id"] == "task-1"
        and event.payload["correlation_id"] == "corr-1"
        for event in audit_log.snapshot()
    )


def test_operation_registry_removes_blocked_failed_and_cancelled_terminal_states() -> None:
    registry, state_store, audit_log = _registry()

    blocked = registry.request_operation(
        operation_kind=OperationKind.USER_WORKFLOW,
        label="Blocked operation",
    )
    blocked_terminal = registry.mark_blocked(
        blocked.operation_id,
        (OperationBlocker(code="blocked", message="Blocked"),),
    )

    failed = registry.request_operation(
        operation_kind=OperationKind.SERVICE_WORKFLOW,
        label="Failed operation",
    )
    failed_terminal = registry.mark_failed(failed.operation_id, "Failure")

    cancelled = registry.request_operation(
        operation_kind=OperationKind.SYSTEM_WORKFLOW,
        label="Cancelled operation",
    )
    registry.request_cancel(cancelled.operation_id)
    cancelled_terminal = registry.mark_cancelled(cancelled.operation_id)

    assert blocked_terminal.status is OperationLifecycleStatus.BLOCKED
    assert failed_terminal.status is OperationLifecycleStatus.FAILED
    assert cancelled_terminal.status is OperationLifecycleStatus.CANCELLED
    assert state_store.operations_state() == ()
    assert any(
        event.event_type == "operation.lifecycle.failed"
        and event.payload["error_message"] == "Failure"
        for event in audit_log.snapshot()
    )


def test_operation_registry_rejects_unknown_operation_transition() -> None:
    registry, _state_store, _audit_log = _registry()

    with pytest.raises(KeyError, match="not active"):
        registry.mark_running("missing")
