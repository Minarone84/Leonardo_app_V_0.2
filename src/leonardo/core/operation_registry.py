"""Operation lifecycle registry for Leonardo V2 Core."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.operations import (
    OperationBlocker,
    OperationKind,
    OperationLifecycleStatus,
    OperationRuntimeState,
    OperationWarning,
)
from leonardo.core.state_store import StateStore


class OperationRegistry:
    """
    Track semantic operation lifecycle state.

    The registry does not execute business logic, run tasks, own GUI actions, or
    manage OS processes.
    """

    def __init__(self, state_store: StateStore) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        self._state_store = state_store

    def request_operation(
        self,
        *,
        operation_kind: OperationKind,
        label: str,
        actor_id: str | None = None,
        session_id: str | None = None,
        origin: ActorOrigin | None = None,
        window_id: str | None = None,
        action_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OperationRuntimeState:
        """Create a requested operation state."""

        now = datetime.now(UTC)
        state = OperationRuntimeState(
            operation_id=uuid4().hex,
            operation_kind=operation_kind,
            status=OperationLifecycleStatus.REQUESTED,
            label=label,
            requested_at_utc=now,
            updated_at_utc=now,
            actor_id=actor_id,
            session_id=session_id,
            origin=origin,
            window_id=window_id,
            action_id=action_id,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        return self._state_store.operation_state_changed(
            state,
            event_type="operation.lifecycle.requested",
            message=f"Operation requested: {state.label}",
        )

    def mark_preflight(self, operation_id: str) -> OperationRuntimeState:
        """Mark an active operation as in preflight."""

        return self._transition(
            operation_id,
            OperationLifecycleStatus.PREFLIGHT,
            "operation.lifecycle.preflight",
        )

    def mark_confirmed(self, operation_id: str) -> OperationRuntimeState:
        """Mark an active operation as confirmed."""

        return self._transition(
            operation_id,
            OperationLifecycleStatus.CONFIRMED,
            "operation.lifecycle.confirmed",
        )

    def mark_running(
        self,
        operation_id: str,
        *,
        task_id: str | None = None,
    ) -> OperationRuntimeState:
        """Mark an active operation as running."""

        previous = self._require_state(operation_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=OperationLifecycleStatus.RUNNING,
            updated_at_utc=now,
            started_at_utc=previous.started_at_utc or now,
            task_id=task_id or previous.task_id,
        )
        return self._state_store.operation_state_changed(
            state,
            event_type="operation.lifecycle.running",
            message=f"Operation running: {state.label}",
        )

    def mark_blocked(
        self,
        operation_id: str,
        blockers: tuple[OperationBlocker, ...],
        *,
        warnings: tuple[OperationWarning, ...] = (),
    ) -> OperationRuntimeState:
        """Mark an operation as blocked and remove active runtime state."""

        previous = self._require_state(operation_id)
        state = replace(
            previous,
            status=OperationLifecycleStatus.BLOCKED,
            updated_at_utc=datetime.now(UTC),
            completed_at_utc=datetime.now(UTC),
            blockers=blockers,
            warnings=warnings,
        )
        return self._state_store.operation_state_changed(
            state,
            event_type="operation.lifecycle.blocked",
            message=f"Operation blocked: {state.label}",
            failed=True,
        )

    def mark_completed(self, operation_id: str) -> OperationRuntimeState:
        """Mark an operation as completed and remove active runtime state."""

        return self._terminal_transition(
            operation_id,
            OperationLifecycleStatus.COMPLETED,
            "operation.lifecycle.completed",
        )

    def mark_failed(
        self,
        operation_id: str,
        error_message: str,
    ) -> OperationRuntimeState:
        """Mark an operation as failed and remove active runtime state."""

        return self._terminal_transition(
            operation_id,
            OperationLifecycleStatus.FAILED,
            "operation.lifecycle.failed",
            error_message=error_message,
            failed=True,
        )

    def request_cancel(self, operation_id: str) -> OperationRuntimeState:
        """Mark an active operation as cancellation-requested."""

        return self._transition(
            operation_id,
            OperationLifecycleStatus.CANCEL_REQUESTED,
            "operation.lifecycle.cancel_requested",
        )

    def mark_cancelled(self, operation_id: str) -> OperationRuntimeState:
        """Mark an operation as cancelled and remove active runtime state."""

        return self._terminal_transition(
            operation_id,
            OperationLifecycleStatus.CANCELLED,
            "operation.lifecycle.cancelled",
        )

    def active_operations(self) -> tuple[OperationRuntimeState, ...]:
        """Return active operation runtime states."""

        return self._state_store.operations_state()

    def _transition(
        self,
        operation_id: str,
        status: OperationLifecycleStatus,
        event_type: str,
    ) -> OperationRuntimeState:
        previous = self._require_state(operation_id)
        state = replace(
            previous,
            status=status,
            updated_at_utc=datetime.now(UTC),
        )
        return self._state_store.operation_state_changed(
            state,
            event_type=event_type,
            message=f"Operation status changed to {status.value}: {state.label}",
        )

    def _terminal_transition(
        self,
        operation_id: str,
        status: OperationLifecycleStatus,
        event_type: str,
        *,
        error_message: str | None = None,
        failed: bool = False,
    ) -> OperationRuntimeState:
        previous = self._require_state(operation_id)
        now = datetime.now(UTC)
        state = replace(
            previous,
            status=status,
            updated_at_utc=now,
            completed_at_utc=now,
            error_message=error_message,
        )
        return self._state_store.operation_state_changed(
            state,
            event_type=event_type,
            message=f"Operation status changed to {status.value}: {state.label}",
            failed=failed,
        )

    def _require_state(self, operation_id: str) -> OperationRuntimeState:
        for state in self._state_store.operations_state():
            if state.operation_id == operation_id:
                return state
        raise KeyError(f"Operation is not active: {operation_id}")
