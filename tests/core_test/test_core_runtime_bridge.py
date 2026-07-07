import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.core_runtime import (
    CoreRuntimeCommand,
    CoreRuntimeMetadata,
    CoreRuntimeProgress,
    CoreRuntimeResult,
    CoreRuntimeResultStatus,
)
from leonardo.contracts.identity import (
    ActorOrigin,
    Permission,
    SessionContext,
    UserRef,
    UserRole,
)
from leonardo.contracts.operations import OperationKind
from leonardo.core.app import LeonardoApp
from leonardo.core.audit_log import AuditLog
from leonardo.core.core_runner import CoreRunner
from leonardo.core.core_runtime_bridge import CoreRuntimeBridge
from leonardo.core.error_router import ErrorRouter
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.session_manager import (
    SessionManager,
    create_development_administrator_session,
)
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager
from leonardo.core.user_policy import UserPolicy


@dataclass(frozen=True)
class _RuntimeHarness:
    bridge: CoreRuntimeBridge
    runner: CoreRunner
    task_manager: TaskManager
    operation_registry: OperationRegistry
    state_store: StateStore
    audit_log: AuditLog
    session_manager: SessionManager
    user_policy: UserPolicy


def _runtime(
    *,
    dispatcher=None,
    session: SessionContext | None = None,
) -> _RuntimeHarness:
    audit_log = AuditLog()
    session_manager = SessionManager(
        audit_log=audit_log,
        session_context=session or create_development_administrator_session(),
    )
    user_policy = UserPolicy()
    state_store = StateStore(audit_log)
    error_router = ErrorRouter(audit_log)
    task_manager = TaskManager(
        state_store,
        error_router=error_router,
    )
    runner = CoreRunner(
        task_manager,
        error_router=error_router,
    )
    operation_registry = OperationRegistry(state_store)
    bridge = CoreRuntimeBridge(
        runner,
        operation_registry=operation_registry,
        callback_dispatcher=dispatcher,
        session_provider=session_manager,
        user_policy=user_policy,
        audit_log=audit_log,
    )
    return _RuntimeHarness(
        bridge=bridge,
        runner=runner,
        task_manager=task_manager,
        operation_registry=operation_registry,
        state_store=state_store,
        audit_log=audit_log,
        session_manager=session_manager,
        user_policy=user_policy,
    )


def _command(
    command_id: str = "command-1",
    *,
    operation_id: str | None = None,
    required_permission: Permission | str | None = None,
) -> CoreRuntimeCommand:
    required_permission_value = (
        required_permission.value
        if isinstance(required_permission, Permission)
        else required_permission
    )
    return CoreRuntimeCommand(
        command_id=command_id,
        command_type="test.command",
        metadata=CoreRuntimeMetadata(
            operation_id=operation_id,
            action_id="action-1",
            window_id="window-1",
            actor_id="actor-1",
            session_id="session-1",
            permission="test.permission",
            required_permission=required_permission_value,
            domain="core",
            suite="runtime",
            source="unit_test",
            correlation_id="correlation-1",
        ),
        payload={"value": "payload-1"},
    )


def _restricted_session(
    *,
    permissions: tuple[Permission, ...] = (),
) -> SessionContext:
    return SessionContext(
        session_id="session-restricted-user",
        actor=UserRef(
            user_id="restricted-user",
            username="Restricted User",
            roles=(UserRole.USER,),
            permissions=permissions,
        ),
        origin=ActorOrigin.HUMAN,
        started_at_utc=datetime.now(UTC),
    )


def _record_result(
    results: list[CoreRuntimeResult],
    received: Event,
):
    def record(result: CoreRuntimeResult) -> None:
        results.append(result)
        received.set()

    return record


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_core_bridge_schedules_command_through_task_manager() -> None:
    runtime = _runtime()
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(command, _progress):
        await asyncio.sleep(0)
        return {"echo": command.payload["value"]}

    try:
        runtime.bridge.start()

        submission = runtime.bridge.submit_command(
            _command(),
            handler,
            result_callback=_record_result(results, received),
        )

        assert submission.accepted is True
        assert submission.metadata.task_id == submission.task_id
        assert submission.metadata.operation_id is not None
        assert received.wait(2)
        _wait_until(lambda: runtime.task_manager.active_tasks() == ())
    finally:
        runtime.runner.shutdown()

    assert len(results) == 1
    result = results[0]
    assert result.status is CoreRuntimeResultStatus.COMPLETED
    assert result.payload["echo"] == "payload-1"
    assert result.metadata.operation_id == submission.metadata.operation_id
    assert result.metadata.task_id == submission.task_id
    assert result.metadata.correlation_id == "correlation-1"
    assert any(
        event.event_type == "task.lifecycle.started"
        and event.task_id == submission.task_id
        and event.operation_id == submission.metadata.operation_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "task.lifecycle.completed"
        and event.task_id == submission.task_id
        and event.operation_id == submission.metadata.operation_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "operation.lifecycle.running"
        and event.operation_id == submission.metadata.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "operation.lifecycle.completed"
        and event.operation_id == submission.metadata.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )


def test_core_bridge_allows_command_when_required_permission_is_granted() -> None:
    runtime = _runtime(
        session=_restricted_session(permissions=(Permission.DOWNLOAD_PREVIEW,)),
    )
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        return {"preview": "ok"}

    try:
        runtime.bridge.start()

        submission = runtime.bridge.submit_command(
            _command(
                "permitted-command-1",
                required_permission=Permission.DOWNLOAD_PREVIEW,
            ),
            handler,
            result_callback=_record_result(results, received),
        )

        assert submission.accepted is True
        assert received.wait(2)
        _wait_until(lambda: runtime.task_manager.active_tasks() == ())
    finally:
        runtime.runner.shutdown()

    assert results[0].status is CoreRuntimeResultStatus.COMPLETED
    assert results[0].payload["preview"] == "ok"
    assert submission.metadata.required_permission == "download:preview"
    assert any(
        event.event_type == "core_runtime.command.accepted"
        and event.task_id == submission.task_id
        and event.operation_id == submission.metadata.operation_id
        and event.payload["required_permission"] == "download:preview"
        for event in runtime.audit_log.snapshot()
    )


def test_core_bridge_denies_command_when_required_permission_is_missing() -> None:
    runtime = _runtime(session=_restricted_session())
    results: list[CoreRuntimeResult] = []
    received = Event()
    handler_called = False

    async def handler(_command, _progress):
        nonlocal handler_called
        handler_called = True
        return {"should_not": "run"}

    runtime.bridge.start()

    submission = runtime.bridge.submit_command(
        _command(
            "denied-command-1",
            required_permission=Permission.DOWNLOAD_EXECUTE,
        ),
        handler,
        result_callback=_record_result(results, received),
    )

    runtime.runner.shutdown()

    assert submission.accepted is False
    assert submission.task_id == "permission-denied"
    assert submission.metadata.required_permission == "download:execute"
    assert submission.metadata.denied_reason == "missing_permission"
    assert received.is_set()
    assert handler_called is False
    assert runtime.task_manager.active_tasks() == ()
    assert runtime.operation_registry.active_operations() == ()

    assert len(results) == 1
    result = results[0]
    assert result.status is CoreRuntimeResultStatus.FAILED
    assert result.task_id == "permission-denied"
    assert result.error is not None
    assert result.error.error_type == "PermissionDenied"
    assert result.error.details["required_permission"] == "download:execute"
    assert result.error.details["denied_reason"] == "missing_permission"
    assert result.metadata.denied_reason == "missing_permission"
    assert not any(
        event.event_type.startswith("task.lifecycle.")
        for event in runtime.audit_log.snapshot()
    )
    assert not any(
        event.event_type.startswith("operation.lifecycle.")
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "core_runtime.command.denied"
        and event.task_id == "permission-denied"
        and event.payload["required_permission"] == "download:execute"
        and event.payload["denied_reason"] == "missing_permission"
        for event in runtime.audit_log.snapshot()
    )


def test_core_bridge_denies_unknown_required_permission_without_task() -> None:
    runtime = _runtime(session=_restricted_session())
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        return {"should_not": "run"}

    runtime.bridge.start()

    submission = runtime.bridge.submit_command(
        _command(
            "unknown-permission-command-1",
            required_permission="download:unknown",
        ),
        handler,
        result_callback=_record_result(results, received),
    )

    runtime.runner.shutdown()

    assert submission.accepted is False
    assert submission.metadata.denied_reason == "unknown_permission"
    assert received.is_set()
    assert runtime.task_manager.active_tasks() == ()
    assert runtime.operation_registry.active_operations() == ()
    assert results[0].error is not None
    assert results[0].error.details["denied_reason"] == "unknown_permission"


def test_core_bridge_dispatches_progress_with_task_identity() -> None:
    dispatched: list[object] = []

    def dispatcher(callback) -> None:
        dispatched.append(callback)
        callback()

    runtime = _runtime(
        dispatcher=dispatcher,
    )
    progress_events: list[CoreRuntimeProgress] = []
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, progress):
        progress.report(
            "Half complete",
            current=1,
            total=2,
            percent=50,
            payload={"phase": "half"},
        )
        return {"done": True}

    try:
        runtime.bridge.start()

        submission = runtime.bridge.submit_command(
            _command(),
            handler,
            result_callback=_record_result(results, received),
            progress_callback=progress_events.append,
        )

        assert received.wait(2)
    finally:
        runtime.runner.shutdown()

    assert len(progress_events) == 1
    assert progress_events[0].task_id == submission.task_id
    assert progress_events[0].metadata.task_id == submission.task_id
    assert progress_events[0].metadata.operation_id == submission.metadata.operation_id
    assert progress_events[0].metadata.correlation_id == "correlation-1"
    assert progress_events[0].percent == 50.0
    assert progress_events[0].payload["phase"] == "half"
    assert results[0].status is CoreRuntimeResultStatus.COMPLETED
    assert results[0].metadata.operation_id == submission.metadata.operation_id
    assert results[0].metadata.correlation_id == "correlation-1"
    assert len(dispatched) == 2


def test_core_bridge_accepts_thread_safe_submission() -> None:
    runtime = _runtime()
    results: list[CoreRuntimeResult] = []
    received = Event()
    submissions = []
    errors: list[BaseException] = []

    async def handler(_command, _progress):
        await asyncio.sleep(0)
        return {"ok": True}

    def submit_from_thread() -> None:
        try:
            submissions.append(
                bridge.submit_command(
                    _command("thread-command-1"),
                    handler,
                    result_callback=_record_result(results, received),
                )
            )
        except BaseException as exc:
            errors.append(exc)

    try:
        bridge = runtime.bridge
        bridge.start()
        thread = Thread(target=submit_from_thread, name="submit-core-command")
        thread.start()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert errors == []
        assert received.wait(2)
    finally:
        runtime.runner.shutdown()

    assert submissions[0].task_id == results[0].task_id
    assert results[0].status is CoreRuntimeResultStatus.COMPLETED
    assert results[0].payload["ok"] is True


def test_core_bridge_routes_cancellation_to_task_manager() -> None:
    runtime = _runtime()
    started = Event()
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        started.set()
        await asyncio.Event().wait()

    try:
        runtime.bridge.start()
        submission = runtime.bridge.submit_command(
            _command("cancel-command-1"),
            handler,
            result_callback=_record_result(results, received),
        )
        assert started.wait(2)

        cancellation = runtime.bridge.cancel_operation(
            submission.metadata.operation_id or "",
            command_id=submission.command_id,
            reason="test cancellation",
        )

        assert cancellation.requested is True
        assert received.wait(2)
        _wait_until(lambda: runtime.task_manager.active_tasks() == ())
    finally:
        runtime.runner.shutdown()

    assert results[0].status is CoreRuntimeResultStatus.CANCELLED
    assert results[0].task_id == submission.task_id
    assert results[0].metadata.operation_id == submission.metadata.operation_id
    assert any(
        event.event_type == "task.lifecycle.cancel_requested"
        and event.task_id == submission.task_id
        and event.operation_id == submission.metadata.operation_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "task.lifecycle.cancelled"
        and event.task_id == submission.task_id
        and event.operation_id == submission.metadata.operation_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "operation.lifecycle.cancel_requested"
        and event.operation_id == submission.metadata.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "operation.lifecycle.cancelled"
        and event.operation_id == submission.metadata.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )


def test_core_runner_rejects_submission_before_start_and_closes_coroutine() -> None:
    runtime = _runtime()

    async def work() -> None:
        return None

    coroutine = work()

    with pytest.raises(RuntimeError, match="Core runner is not running"):
        runtime.runner.submit_coroutine(
            coroutine,
            command=_command(),
        )

    assert coroutine.cr_frame is None


def test_core_runner_routes_result_callback_failure_to_error_router() -> None:
    runtime = _runtime()
    received = Event()

    async def handler(_command, _progress):
        return {"ok": True}

    def failing_callback(_result: CoreRuntimeResult) -> None:
        received.set()
        raise RuntimeError("callback failed")

    try:
        runtime.bridge.start()
        runtime.bridge.submit_command(
            _command("callback-failure-command-1"),
            handler,
            result_callback=failing_callback,
        )

        assert received.wait(2)
        _wait_until(
            lambda: any(
                event.category is AuditCategory.ERROR
                and event.event_type == "error.reported"
                and event.message == "Core runtime result callback failed"
                for event in runtime.audit_log.snapshot()
            )
        )
    finally:
        runtime.runner.shutdown()


def test_core_bridge_preserves_existing_operation_identity_and_records_task_id() -> None:
    runtime = _runtime()
    operation = runtime.operation_registry.request_operation(
        operation_kind=OperationKind.SYSTEM_WORKFLOW,
        label="Existing operation",
        correlation_id="correlation-1",
    )
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(command, _progress):
        return {"operation_id": command.metadata.operation_id}

    try:
        runtime.bridge.start()
        submission = runtime.bridge.submit_command(
            _command("existing-operation-command-1", operation_id=operation.operation_id),
            handler,
            result_callback=_record_result(results, received),
        )

        assert submission.metadata.operation_id == operation.operation_id
        assert received.wait(2)
    finally:
        runtime.runner.shutdown()

    assert results[0].payload["operation_id"] == operation.operation_id
    assert any(
        event.event_type == "operation.lifecycle.running"
        and event.operation_id == operation.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )
    assert any(
        event.event_type == "operation.lifecycle.completed"
        and event.operation_id == operation.operation_id
        and event.task_id == submission.task_id
        for event in runtime.audit_log.snapshot()
    )


def test_core_bridge_marks_operation_failed_when_task_fails() -> None:
    runtime = _runtime()
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        raise ValueError("planned failure")

    try:
        runtime.bridge.start()
        submission = runtime.bridge.submit_command(
            _command("failed-command-1"),
            handler,
            result_callback=_record_result(results, received),
        )

        assert received.wait(2)
        _wait_until(lambda: runtime.task_manager.active_tasks() == ())
    finally:
        runtime.runner.shutdown()

    result = results[0]
    assert result.status is CoreRuntimeResultStatus.FAILED
    assert result.error is not None
    assert result.error.message == "planned failure"
    assert result.error.details["operation_id"] == submission.metadata.operation_id
    assert result.error.details["task_id"] == submission.task_id
    assert result.error.details["correlation_id"] == "correlation-1"
    assert any(
        event.event_type == "operation.lifecycle.failed"
        and event.operation_id == submission.metadata.operation_id
        and event.task_id == submission.task_id
        and event.payload["error_message"] == "planned failure"
        for event in runtime.audit_log.snapshot()
    )


def test_core_bridge_rejects_unknown_operation_identity() -> None:
    runtime = _runtime()

    async def handler(_command, _progress):
        return None

    try:
        runtime.bridge.start()
        with pytest.raises(KeyError, match="Operation is not active"):
            runtime.bridge.submit_command(
                _command("unknown-operation-command-1", operation_id="missing"),
                handler,
            )
    finally:
        runtime.runner.shutdown()


def test_runtime_manager_snapshot_reads_operation_task_relationship_without_control() -> None:
    app = LeonardoApp()
    started = Event()
    results: list[CoreRuntimeResult] = []
    received = Event()

    async def handler(_command, _progress):
        started.set()
        await asyncio.Event().wait()

    try:
        context = app.startup()
        context.core_runtime_bridge.start()
        submission = context.core_runtime_bridge.submit_command(
            _command("runtime-manager-relationship-command-1"),
            handler,
            result_callback=_record_result(results, received),
        )
        assert started.wait(2)

        before_tasks = app.task_manager.active_tasks()
        snapshot = app.runtime_manager.snapshot()

        assert app.task_manager.active_tasks() == before_tasks
        assert snapshot.tasks_summary.metadata["task_ids"] == (submission.task_id,)
        assert snapshot.tasks_summary.metadata["operation_ids"] == (
            submission.metadata.operation_id,
        )
        assert snapshot.operations_summary.metadata["operation_ids"] == (
            submission.metadata.operation_id,
        )
        assert snapshot.operations_summary.metadata["task_ids"] == (
            submission.task_id,
        )

        cancellation = context.core_runtime_bridge.cancel_operation(
            submission.metadata.operation_id or "",
            command_id=submission.command_id,
            reason="test cleanup",
        )

        assert cancellation.requested is True
        assert received.wait(2)
    finally:
        app.shutdown()

    assert results[0].status is CoreRuntimeResultStatus.CANCELLED


def test_leonardo_app_exposes_core_runtime_bridge_and_stops_started_runner() -> None:
    app = LeonardoApp()

    try:
        context = app.startup()

        assert context.core_runner is app.core_runner
        assert context.core_runtime_bridge is app.core_runtime_bridge
        assert context.core_runtime_bridge.runner is app.core_runner
        assert app.core_runner.is_running is False
        assert app.contract_registry.get_contract(
            "leonardo.core_runtime.command",
            "1.0",
        ) is not None

        context.core_runtime_bridge.start()
        assert app.core_runner.is_running is True
    finally:
        app.shutdown()

    assert app.core_runner.is_running is False
