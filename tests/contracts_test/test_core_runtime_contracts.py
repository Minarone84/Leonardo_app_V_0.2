import pytest

from leonardo.contracts.core_runtime import (
    CoreRuntimeCancellationRequest,
    CoreRuntimeCancellationResult,
    CoreRuntimeCommand,
    CoreRuntimeError,
    CoreRuntimeMetadata,
    CoreRuntimeProgress,
    CoreRuntimeQuery,
    CoreRuntimeResult,
    CoreRuntimeResultStatus,
    CoreRuntimeSubmission,
)


def test_core_runtime_metadata_carries_traceability_fields_and_is_immutable() -> None:
    metadata = CoreRuntimeMetadata(
        operation_id="operation-1",
        task_id="task-1",
        action_id="action-1",
        window_id="window-1",
        actor_id="actor-1",
        session_id="session-1",
        permission="download.preview",
        required_permission="download:preview",
        denied_reason="missing_permission",
        domain="downloads",
        suite="data",
        source="main_window",
        correlation_id="correlation-1",
        extra={"symbol": "BTCUSDT"},
    )

    assert metadata.schema_version == "1.0"
    assert metadata.operation_id == "operation-1"
    assert metadata.task_id == "task-1"
    assert metadata.action_id == "action-1"
    assert metadata.window_id == "window-1"
    assert metadata.actor_id == "actor-1"
    assert metadata.session_id == "session-1"
    assert metadata.permission == "download.preview"
    assert metadata.required_permission == "download:preview"
    assert metadata.denied_reason == "missing_permission"
    assert metadata.domain == "downloads"
    assert metadata.suite == "data"
    assert metadata.source == "main_window"
    assert metadata.correlation_id == "correlation-1"
    assert metadata.extra["symbol"] == "BTCUSDT"
    assert metadata.with_operation_id("operation-2").operation_id == "operation-2"
    assert metadata.with_task_id("task-2").task_id == "task-2"
    denied = metadata.with_denial(
        required_permission="download:execute",
        denied_reason="missing_permission",
    )
    assert denied.required_permission == "download:execute"
    assert denied.denied_reason == "missing_permission"

    with pytest.raises(TypeError):
        metadata.extra["symbol"] = "ETHUSDT"  # type: ignore[index]


def test_core_runtime_command_and_query_payloads_are_read_only() -> None:
    command = CoreRuntimeCommand(
        command_id="command-1",
        command_type="download.preview",
        payload={"symbol": "BTCUSDT"},
    )
    query = CoreRuntimeQuery(
        query_id="query-1",
        query_type="runtime.snapshot",
        payload={"window_id": "runtime_manager"},
    )

    assert command.payload["symbol"] == "BTCUSDT"
    assert query.payload["window_id"] == "runtime_manager"

    with pytest.raises(TypeError):
        command.payload["symbol"] = "ETHUSDT"  # type: ignore[index]
    with pytest.raises(TypeError):
        query.payload["window_id"] = "main_window"  # type: ignore[index]


def test_core_runtime_progress_validates_identity_counts_and_percent() -> None:
    progress = CoreRuntimeProgress(
        command_id="command-1",
        task_id="task-1",
        message="Half complete",
        metadata=CoreRuntimeMetadata(task_id="task-1"),
        current=1,
        total=2,
        percent=50,
        payload={"phase": "preview"},
    )

    assert progress.percent == 50.0
    assert progress.payload["phase"] == "preview"

    with pytest.raises(ValueError, match="percent must be between 0 and 100"):
        CoreRuntimeProgress(
            command_id="command-1",
            task_id="task-1",
            message="Invalid",
            metadata=CoreRuntimeMetadata(),
            percent=101,
        )
    with pytest.raises(ValueError, match="current must be a non-negative integer"):
        CoreRuntimeProgress(
            command_id="command-1",
            task_id="task-1",
            message="Invalid",
            metadata=CoreRuntimeMetadata(),
            current=-1,
        )


def test_core_runtime_result_requires_error_for_failed_status() -> None:
    error = CoreRuntimeError(
        error_type="RuntimeError",
        message="command failed",
        details={"reason": "boom"},
    )
    result = CoreRuntimeResult(
        command_id="command-1",
        task_id="task-1",
        status=CoreRuntimeResultStatus.FAILED,
        metadata=CoreRuntimeMetadata(task_id="task-1"),
        error=error,
    )

    assert result.error is error
    assert result.error.details["reason"] == "boom"

    with pytest.raises(ValueError, match="failed results must include an error"):
        CoreRuntimeResult(
            command_id="command-1",
            task_id="task-1",
            status=CoreRuntimeResultStatus.FAILED,
            metadata=CoreRuntimeMetadata(task_id="task-1"),
        )


def test_core_runtime_submission_and_cancellation_contracts_validate_identity() -> None:
    metadata = CoreRuntimeMetadata(task_id="task-1")
    submission = CoreRuntimeSubmission(
        command_id="command-1",
        task_id="task-1",
        accepted=True,
        metadata=metadata,
    )
    request = CoreRuntimeCancellationRequest(
        task_id="task-1",
        command_id="command-1",
        reason="user requested",
        metadata=metadata,
    )
    result = CoreRuntimeCancellationResult(
        task_id="task-1",
        requested=True,
        message="Task cancellation requested.",
        metadata=metadata,
    )

    assert submission.accepted is True
    assert request.reason == "user requested"
    assert result.requested is True

    with pytest.raises(ValueError, match="task_id must be a non-empty string"):
        CoreRuntimeCancellationRequest(task_id="")
