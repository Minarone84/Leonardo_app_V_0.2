"""Core-supervised asyncio task manager for Leonardo V2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from leonardo.contracts.errors import ErrorSeverity
from leonardo.contracts.runtime import TaskRuntimeState
from leonardo.core.async_runtime import (
    CoroutineObject,
    close_coroutine_if_needed,
    is_coroutine_object,
    normalize_task_name,
)
from leonardo.core.error_router import ErrorRouter
from leonardo.core.state_store import StateStore


@dataclass(frozen=True)
class _ManagedTask:
    task_id: str
    task_name: str
    asyncio_task: asyncio.Task[object]
    operation_id: str | None
    service_id: str | None
    correlation_id: str | None


class TaskManager:
    """
    Supervise Core-managed asyncio tasks on the currently running event loop.

    The manager owns task supervision only. It does not implement operation
    lifecycle, OS process management, GUI worker ownership, or business logic.
    """

    def __init__(
        self,
        state_store: StateStore,
        *,
        error_router: ErrorRouter | None = None,
    ) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        if error_router is not None and not isinstance(error_router, ErrorRouter):
            raise TypeError("error_router must be an ErrorRouter")
        self._state_store = state_store
        self._error_router = error_router
        self._tasks: dict[str, _ManagedTask] = {}

    def create_task(
        self,
        coroutine: CoroutineObject,
        *,
        task_name: str,
        allow_duplicate_name: bool = False,
        operation_id: str | None = None,
        service_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        """
        Create a supervised task on the currently running event loop.

        Duplicate active task names are rejected by default. Rejected coroutine
        objects are closed before the exception is raised.
        """

        normalized_name = normalize_task_name(task_name)
        if not allow_duplicate_name and self._has_active_task_name(normalized_name):
            close_coroutine_if_needed(coroutine)
            raise ValueError(f"Task name is already active: {normalized_name}")
        if not is_coroutine_object(coroutine):
            raise TypeError("coroutine must be a coroutine object")

        loop = asyncio.get_running_loop()
        task_id = uuid4().hex
        self._state_store.task_started(
            task_id=task_id,
            task_name=normalized_name,
            operation_id=operation_id,
            service_id=service_id,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        asyncio_task = loop.create_task(
            coroutine,
            name=f"{normalized_name}:{task_id}",
        )
        managed = _ManagedTask(
            task_id=task_id,
            task_name=normalized_name,
            asyncio_task=asyncio_task,
            operation_id=operation_id,
            service_id=service_id,
            correlation_id=correlation_id,
        )
        self._tasks[task_id] = managed
        asyncio_task.add_done_callback(
            lambda completed_task: self._on_task_done(task_id, completed_task)
        )
        return task_id

    async def wait_task(self, task_id: str) -> object:
        """Await an active task by task identifier."""

        managed = self._tasks.get(task_id)
        if managed is None:
            raise KeyError(f"Task is not active: {task_id}")
        return await managed.asyncio_task

    def cancel_task(self, task_id: str) -> bool:
        """Request cancellation for an active task."""

        managed = self._tasks.get(task_id)
        if managed is None or managed.asyncio_task.done():
            return False
        self._state_store.task_cancel_requested(task_id)
        return managed.asyncio_task.cancel()

    async def cancel_all(self) -> None:
        """Request cancellation for all active tasks and wait for settlement."""

        active_tasks = [
            managed.asyncio_task
            for managed in tuple(self._tasks.values())
            if not managed.asyncio_task.done()
        ]
        for managed in tuple(self._tasks.values()):
            if not managed.asyncio_task.done():
                self.cancel_task(managed.task_id)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)

    def active_tasks(self) -> tuple[TaskRuntimeState, ...]:
        """Return defensive active task runtime state snapshots."""

        return self._state_store.tasks_state()

    def _has_active_task_name(self, task_name: str) -> bool:
        return any(managed.task_name == task_name for managed in self._tasks.values())

    def _on_task_done(
        self,
        task_id: str,
        completed_task: asyncio.Task[object],
    ) -> None:
        managed = self._tasks.get(task_id)
        if managed is None:
            return

        if completed_task.cancelled():
            self._state_store.task_cancelled(task_id)
            del self._tasks[task_id]
            return

        exception = completed_task.exception()
        if exception is not None:
            self._state_store.task_failed(task_id, str(exception))
            if self._error_router is not None:
                self._error_router.route_exception(
                    exception,
                    message=f"Task failed: {managed.task_name}",
                    severity=ErrorSeverity.ERROR,
                    correlation_id=managed.correlation_id,
                    context={
                        "task_id": task_id,
                        "task_name": managed.task_name,
                        "operation_id": managed.operation_id,
                        "service_id": managed.service_id,
                    },
                )
            del self._tasks[task_id]
            return

        self._state_store.task_completed(task_id)
        del self._tasks[task_id]
