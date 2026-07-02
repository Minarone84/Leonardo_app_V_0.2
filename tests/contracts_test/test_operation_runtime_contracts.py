from datetime import UTC, datetime

import pytest

from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.operations import (
    OperationBlocker,
    OperationKind,
    OperationLifecycleStatus,
    OperationResult,
    OperationRuntimeState,
    OperationWarning,
)


def test_operation_runtime_state_tracks_active_workflow_identity() -> None:
    now = datetime.now(UTC)
    state = OperationRuntimeState(
        operation_id="operation-1",
        operation_kind=OperationKind.USER_WORKFLOW,
        status=OperationLifecycleStatus.RUNNING,
        label="Open runtime manager",
        requested_at_utc=now,
        updated_at_utc=now,
        started_at_utc=now,
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        window_id="runtime-manager",
        action_id="runtime.open",
        correlation_id="corr-1",
        warnings=(OperationWarning(code="slow", message="May take time"),),
    )

    assert state.is_terminal is False
    assert state.operation_kind is OperationKind.USER_WORKFLOW
    assert state.warnings[0].code == "slow"


def test_operation_blocked_state_is_terminal() -> None:
    now = datetime.now(UTC)
    state = OperationRuntimeState(
        operation_id="operation-1",
        operation_kind=OperationKind.USER_WORKFLOW,
        status=OperationLifecycleStatus.BLOCKED,
        label="Open runtime manager",
        requested_at_utc=now,
        updated_at_utc=now,
        completed_at_utc=now,
        blockers=(OperationBlocker(code="missing_permission", message="Denied"),),
    )

    assert state.is_terminal is True
    assert state.blockers[0].message == "Denied"


def test_operation_result_requires_terminal_status() -> None:
    with pytest.raises(ValueError, match="terminal"):
        OperationResult(
            operation_id="operation-1",
            status=OperationLifecycleStatus.RUNNING,
            completed_at_utc=datetime.now(UTC),
        )
