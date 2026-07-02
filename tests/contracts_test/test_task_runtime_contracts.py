from datetime import UTC, datetime

import pytest

from leonardo.contracts.runtime import (
    AppLifecycleStatus,
    AppRuntimeState,
    RuntimeSnapshot,
    ServiceRuntimeState,
    TaskLifecycleStatus,
    TaskRuntimeState,
)


def test_task_runtime_state_tracks_task_identity_and_status() -> None:
    now = datetime.now(UTC)
    state = TaskRuntimeState(
        task_id="task-1",
        task_name="Load runtime snapshot",
        status=TaskLifecycleStatus.RUNNING,
        started_at_utc=now,
        updated_at_utc=now,
        operation_id="operation-1",
        service_id="runtime",
        correlation_id="correlation-1",
        metadata={"source": "test"},
    )

    assert state.task_id == "task-1"
    assert state.status is TaskLifecycleStatus.RUNNING
    assert state.metadata["source"] == "test"


def test_task_runtime_state_rejects_empty_task_identity() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="task_id"):
        TaskRuntimeState(
            task_id="",
            task_name="Runtime task",
            status=TaskLifecycleStatus.RUNNING,
            started_at_utc=now,
            updated_at_utc=now,
        )


def test_runtime_snapshot_includes_task_states() -> None:
    now = datetime.now(UTC)
    task_state = TaskRuntimeState(
        task_id="task-1",
        task_name="Runtime task",
        status=TaskLifecycleStatus.RUNNING,
        started_at_utc=now,
        updated_at_utc=now,
    )
    snapshot = RuntimeSnapshot(
        app_state=AppRuntimeState(status=AppLifecycleStatus.RUNNING),
        service_states=(ServiceRuntimeState(service_id="state-store"),),
        task_states=(task_state,),
    )

    assert snapshot.task_states == (task_state,)
    assert isinstance(snapshot.task_states, tuple)
