"""Persistent asyncio runtime for long-running Leonardo work."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Any

from leonardo.core.async_runtime import close_coroutine_if_needed
from leonardo.core.task_manager import TaskManager

ProgressCallback = Callable[["TaskProgress"], None]
ResultCallback = Callable[["TaskResult"], None]
JobCallable = Callable[["ProgressReporter"], Awaitable[object] | object]
CallbackDispatcher = Callable[[Callable[[], None]], None]


@dataclass(frozen=True)
class TaskSubmission:
    task_id: str
    task_name: str


@dataclass(frozen=True)
class TaskProgress:
    task_id: str
    message: str
    current: int | None = None
    total: int | None = None
    details: Mapping[str, object] | None = None


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: str
    value: object | None = None
    error_type: str | None = None
    error_message: str | None = None


class ProgressReporter:
    def __init__(
        self,
        task_manager: TaskManager,
        task_id_ref: "_TaskIdRef",
        callback: ProgressCallback | None,
        dispatcher: CallbackDispatcher,
    ) -> None:
        self._task_manager = task_manager
        self._task_id_ref = task_id_ref
        self._callback = callback
        self._dispatcher = dispatcher

    def report(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        task_id = self._task_id_ref.value
        if task_id is None:
            raise RuntimeError("Task identity is not available yet")
        self._task_manager.update_progress(
            task_id,
            message=message,
            current=current,
            total=total,
        )
        if self._callback is not None:
            event = TaskProgress(
                task_id=task_id,
                message=message,
                current=current,
                total=total,
                details=dict(details or {}),
            )
            self._dispatcher(lambda: self._callback(event))


class _TaskIdRef:
    def __init__(self) -> None:
        self.value: str | None = None


class CoreRunner:
    """Own one background asyncio event loop and supervised task submission."""

    def __init__(self, task_manager: TaskManager) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        self._task_manager = task_manager
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None
        self._started = Event()
        self._lock = Lock()
        self._accepting = False

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and self._loop is not None)

    @property
    def is_accepting_submissions(self) -> bool:
        return self.is_running and self._accepting

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                self._accepting = True
                return
            self._started.clear()
            self._thread = Thread(target=self._run_loop, name="LeonardoCore", daemon=True)
            self._thread.start()
        if not self._started.wait(5.0):
            raise RuntimeError("Core event loop failed to start")
        self._accepting = True

    def submit_job(
        self,
        job: JobCallable,
        *,
        task_name: str,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
        allow_duplicate_name: bool = False,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TaskSubmission:
        if not callable(job):
            raise TypeError("job must be callable")
        loop = self._require_loop()
        if not self._accepting:
            raise RuntimeError("Core runner is not accepting submissions")
        dispatcher = callback_dispatcher or _inline_dispatch
        submitted: ConcurrentFuture[str] = asyncio.run_coroutine_threadsafe(
            self._schedule_job(
                job,
                task_name=task_name,
                progress_callback=progress_callback,
                result_callback=result_callback,
                callback_dispatcher=dispatcher,
                allow_duplicate_name=allow_duplicate_name,
                correlation_id=correlation_id,
                metadata=metadata,
            ),
            loop,
        )
        return TaskSubmission(task_id=submitted.result(timeout=5.0), task_name=task_name)

    def submit_coroutine(
        self,
        coroutine: Awaitable[object],
        *,
        task_name: str,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
        allow_duplicate_name: bool = False,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> TaskSubmission:
        if not inspect.iscoroutine(coroutine):
            raise TypeError("coroutine must be a coroutine object")

        async def job(_reporter: ProgressReporter) -> object:
            return await coroutine

        try:
            return self.submit_job(
                job,
                task_name=task_name,
                result_callback=result_callback,
                callback_dispatcher=callback_dispatcher,
                allow_duplicate_name=allow_duplicate_name,
                correlation_id=correlation_id,
                metadata=metadata,
            )
        except Exception:
            close_coroutine_if_needed(coroutine)
            raise

    def cancel(self, task_id: str, *, timeout: float = 5.0) -> bool:
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(self._cancel(task_id), loop)
        return bool(future.result(timeout=timeout))

    def stop_accepting_submissions(self) -> None:
        self._accepting = False

    def shutdown(self, *, timeout: float = 5.0) -> None:
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        with self._lock:
            loop = self._loop
            thread = self._thread
            if loop is None or thread is None:
                self._accepting = False
                return
            self._accepting = False
        future = asyncio.run_coroutine_threadsafe(self._task_manager.cancel_all(), loop)
        future.result(timeout=float(timeout))
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=float(timeout))
        if thread.is_alive():
            raise TimeoutError("Core event loop did not stop within timeout")
        with self._lock:
            self._loop = None
            self._thread = None
            self._started.clear()

    async def _schedule_job(
        self,
        job: JobCallable,
        *,
        task_name: str,
        progress_callback: ProgressCallback | None,
        result_callback: ResultCallback | None,
        callback_dispatcher: CallbackDispatcher,
        allow_duplicate_name: bool,
        correlation_id: str | None,
        metadata: dict[str, object] | None,
    ) -> str:
        task_id_ref = _TaskIdRef()
        reporter = ProgressReporter(
            self._task_manager,
            task_id_ref,
            progress_callback,
            callback_dispatcher,
        )

        async def execute() -> object:
            value = job(reporter)
            return await value if inspect.isawaitable(value) else value

        task_id = self._task_manager.create_task(
            execute(),
            task_name=task_name,
            allow_duplicate_name=allow_duplicate_name,
            correlation_id=correlation_id,
            metadata=metadata,
        )
        task_id_ref.value = task_id
        asyncio.create_task(
            self._deliver_terminal_result(
                task_id,
                result_callback=result_callback,
                dispatcher=callback_dispatcher,
            )
        )
        return task_id

    async def _deliver_terminal_result(
        self,
        task_id: str,
        *,
        result_callback: ResultCallback | None,
        dispatcher: CallbackDispatcher,
    ) -> None:
        try:
            value = await self._task_manager.wait_task(task_id)
        except asyncio.CancelledError:
            result = TaskResult(task_id=task_id, status="cancelled")
        except Exception as exc:
            result = TaskResult(
                task_id=task_id,
                status="failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        else:
            result = TaskResult(task_id=task_id, status="completed", value=value)
        if result_callback is not None:
            dispatcher(lambda: result_callback(result))

    async def _cancel(self, task_id: str) -> bool:
        return self._task_manager.cancel_task(task_id)

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or not self.is_running:
            raise RuntimeError("Core runner is not running")
        return loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        self._started.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()
