import asyncio

import pytest

from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.runtime import TaskLifecycleStatus
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager


def _manager() -> tuple[TaskManager, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    manager = TaskManager(
        state_store,
        error_router=ErrorRouter(audit_log),
    )
    return manager, state_store, audit_log


def test_task_manager_creates_and_completes_supervised_task() -> None:
    async def scenario() -> None:
        manager, state_store, audit_log = _manager()

        async def work() -> str:
            return "done"

        task_id = manager.create_task(work(), task_name="complete-task")
        assert manager.active_tasks()[0].status is TaskLifecycleStatus.RUNNING

        assert await manager.wait_task(task_id) == "done"

        assert manager.active_tasks() == ()
        assert state_store.runtime_snapshot().task_states == ()
        assert any(
            event.event_type == "task.lifecycle.completed"
            and event.task_id == task_id
            for event in audit_log.snapshot()
        )

    asyncio.run(scenario())


def test_task_manager_routes_failed_task_and_removes_active_state() -> None:
    async def scenario() -> None:
        manager, _state_store, audit_log = _manager()

        async def fail() -> None:
            raise ValueError("task failed")

        task_id = manager.create_task(
            fail(),
            task_name="failing-task",
            correlation_id="corr-1",
        )

        with pytest.raises(ValueError, match="task failed"):
            await manager.wait_task(task_id)

        assert manager.active_tasks() == ()
        assert any(
            event.event_type == "task.lifecycle.failed"
            and event.task_id == task_id
            for event in audit_log.snapshot()
        )
        assert any(
            event.category is AuditCategory.ERROR
            and event.event_type == "error.reported"
            and event.correlation_id == "corr-1"
            for event in audit_log.snapshot()
        )

    asyncio.run(scenario())


def test_task_manager_cancels_task_and_keeps_terminal_audit() -> None:
    async def scenario() -> None:
        manager, _state_store, audit_log = _manager()
        ready = asyncio.Event()

        async def wait_forever() -> None:
            ready.set()
            await asyncio.Event().wait()

        task_id = manager.create_task(wait_forever(), task_name="cancel-task")
        await ready.wait()

        assert manager.cancel_task(task_id) is True
        with pytest.raises(asyncio.CancelledError):
            await manager.wait_task(task_id)

        assert manager.active_tasks() == ()
        assert any(
            event.event_type == "task.lifecycle.cancel_requested"
            and event.task_id == task_id
            for event in audit_log.snapshot()
        )
        assert any(
            event.event_type == "task.lifecycle.cancelled"
            and event.task_id == task_id
            for event in audit_log.snapshot()
        )

    asyncio.run(scenario())


def test_task_manager_rejects_duplicate_active_task_names_and_closes_coroutine() -> None:
    async def scenario() -> None:
        manager, _state_store, _audit_log = _manager()
        release = asyncio.Event()

        async def wait_for_release() -> None:
            await release.wait()

        first_task_id = manager.create_task(
            wait_for_release(),
            task_name="duplicate-name",
        )
        rejected = wait_for_release()

        with pytest.raises(ValueError, match="already active"):
            manager.create_task(rejected, task_name="duplicate-name")

        assert rejected.cr_frame is None
        release.set()
        await manager.wait_task(first_task_id)

    asyncio.run(scenario())


def test_task_manager_cancel_all_cancels_active_tasks() -> None:
    async def scenario() -> None:
        manager, _state_store, audit_log = _manager()
        ready_count = 0
        ready = asyncio.Event()

        async def wait_forever() -> None:
            nonlocal ready_count
            ready_count += 1
            if ready_count == 2:
                ready.set()
            await asyncio.Event().wait()

        manager.create_task(
            wait_forever(),
            task_name="cancel-all-task",
            allow_duplicate_name=True,
        )
        manager.create_task(
            wait_forever(),
            task_name="cancel-all-task",
            allow_duplicate_name=True,
        )
        await ready.wait()

        await manager.cancel_all()

        assert manager.active_tasks() == ()
        assert sum(
            1
            for event in audit_log.snapshot()
            if event.event_type == "task.lifecycle.cancelled"
        ) == 2

    asyncio.run(scenario())
