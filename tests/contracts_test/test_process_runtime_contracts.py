from datetime import UTC, datetime

import pytest

from leonardo.contracts.processes import (
    ProcessExitRecord,
    ProcessKind,
    ProcessLaunchRequest,
    ProcessLifecycleStatus,
    ProcessRuntimeState,
)


def test_process_launch_request_normalizes_command_and_metadata() -> None:
    request = ProcessLaunchRequest(
        process_id="process-1",
        label="Inspect runtime",
        command=("python", "-c", "print('ok')"),
        kind=ProcessKind.UTILITY,
        cwd=".",
        env={"LEO_TEST": "1"},
        operation_id="operation-1",
        task_id="task-1",
        service_id="service-1",
        correlation_id="corr-1",
        metadata={"purpose": "test"},
    )

    assert request.command == ("python", "-c", "print('ok')")
    assert request.env["LEO_TEST"] == "1"
    assert request.metadata["purpose"] == "test"


def test_process_launch_request_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match="command"):
        ProcessLaunchRequest(
            process_id="process-1",
            label="Inspect runtime",
            command=(),
            kind=ProcessKind.UTILITY,
        )


def test_process_launch_request_rejects_string_command() -> None:
    with pytest.raises(TypeError, match="argument tokens"):
        ProcessLaunchRequest(
            process_id="process-1",
            label="Inspect runtime",
            command="python -c print('ok')",
            kind=ProcessKind.UTILITY,
        )


def test_process_runtime_state_and_exit_record_validate_terminal_status() -> None:
    now = datetime.now(UTC)
    state = ProcessRuntimeState(
        process_id="process-1",
        label="Inspect runtime",
        kind=ProcessKind.UTILITY,
        status=ProcessLifecycleStatus.RUNNING,
        command=("python", "-c", "print('ok')"),
        pid=123,
        started_at_utc=now,
        updated_at_utc=now,
    )
    exit_record = ProcessExitRecord(
        process_id="process-1",
        exit_code=0,
        status=ProcessLifecycleStatus.STOPPED,
        completed_at_utc=now,
    )

    assert state.status is ProcessLifecycleStatus.RUNNING
    assert exit_record.status.is_terminal is True


def test_process_exit_record_rejects_non_terminal_status() -> None:
    with pytest.raises(ValueError, match="terminal"):
        ProcessExitRecord(
            process_id="process-1",
            exit_code=None,
            status=ProcessLifecycleStatus.RUNNING,
            completed_at_utc=datetime.now(UTC),
        )
