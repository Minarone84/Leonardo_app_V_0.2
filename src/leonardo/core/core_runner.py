"""Persistent Core asyncio runner boundary for Leonardo V2."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from collections.abc import Callable, Mapping
from threading import Event, Lock, Thread, current_thread

from leonardo.contracts.core_runtime import (
    CoreRuntimeCancellationRequest,
    CoreRuntimeCancellationResult,
    CoreRuntimeCommand,
    CoreRuntimeError,
    CoreRuntimeMetadata,
    CoreRuntimeResult,
    CoreRuntimeResultStatus,
    CoreRuntimeSubmission,
)
from leonardo.contracts.errors import ErrorSeverity
from leonardo.core.async_runtime import (
    CoroutineObject,
    close_coroutine_if_needed,
    is_coroutine_object,
    normalize_task_name,
)
from leonardo.core.error_router import ErrorRouter
from leonardo.core.task_manager import TaskManager


CoreRuntimeResultCallback = Callable[[CoreRuntimeResult], None]
CoreRuntimeTaskIdCallback = Callable[[str], None]
CoreRuntimeCommandPrepareCallback = Callable[[CoreRuntimeCommand], CoreRuntimeCommand]


class _TaskIdRef:
    """Mutable task identifier reference used before a supervised task starts."""

    def __init__(self) -> None:
        self.task_id: str | None = None

    def set(self, task_id: str) -> None:
        self.task_id = task_id


class CoreRunner:
    """
    Own a persistent Core asyncio event loop and TaskManager scheduling boundary.

    The runner accepts already-constructed coroutine objects from Core-facing
    bridge code, schedules them through `TaskManager` on a background event
    loop, and reports terminal results through immutable runtime contracts. It
    does not implement command semantics, domain logic, GUI behavior, adapter
    calls, persistence, or operation ownership.
    """

    def __init__(
        self,
        task_manager: TaskManager,
        *,
        error_router: ErrorRouter | None = None,
        thread_name: str = "LeonardoCoreRunner",
    ) -> None:
        if not isinstance(task_manager, TaskManager):
            raise TypeError("task_manager must be a TaskManager")
        if error_router is not None and not isinstance(error_router, ErrorRouter):
            raise TypeError("error_router must be an ErrorRouter or None")
        normalized_thread_name = normalize_task_name(thread_name)
        self._task_manager = task_manager
        self._error_router = error_router
        self._thread_name = normalized_thread_name
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None
        self._accepting_submissions = False
        self._shutdown_drain_timeout = 5.0

    @property
    def is_running(self) -> bool:
        """Return whether the Core event loop thread is running."""

        loop = self._loop
        thread = self._thread
        return loop is not None and loop.is_running() and thread is not None and thread.is_alive()

    @property
    def is_accepting_submissions(self) -> bool:
        """Return whether new coroutine submissions are accepted."""

        return self._accepting_submissions

    def start(self) -> None:
        """Start the persistent Core event loop thread. Startup is idempotent."""

        with self._lock:
            if self.is_running:
                return

            loop = asyncio.new_event_loop()
            ready = Event()
            failed: list[BaseException] = []
            thread = Thread(
                target=self._run_loop,
                args=(loop, ready, failed),
                name=self._thread_name,
            )
            thread.start()
            ready.wait()
            if failed:
                loop.close()
                raise RuntimeError("Core runner event loop failed to start") from failed[0]
            self._loop = loop
            self._thread = thread
            self._accepting_submissions = True

    def submit_coroutine(
        self,
        coroutine: CoroutineObject,
        *,
        command: CoreRuntimeCommand,
        task_name: str | None = None,
        prepare_command: CoreRuntimeCommandPrepareCallback | None = None,
        result_callback: CoreRuntimeResultCallback | None = None,
        task_id_callback: CoreRuntimeTaskIdCallback | None = None,
    ) -> CoreRuntimeSubmission:
        """
        Schedule a coroutine through TaskManager from any caller thread.

        Rejected coroutine objects are closed before an exception is raised so
        callers do not leak unawaited coroutine state.
        """

        if not isinstance(command, CoreRuntimeCommand):
            close_coroutine_if_needed(coroutine)
            raise TypeError("command must be CoreRuntimeCommand")
        if not is_coroutine_object(coroutine):
            raise TypeError("coroutine must be a coroutine object")
        if prepare_command is not None and not callable(prepare_command):
            close_coroutine_if_needed(coroutine)
            raise TypeError("prepare_command must be callable or None")
        if result_callback is not None and not callable(result_callback):
            close_coroutine_if_needed(coroutine)
            raise TypeError("result_callback must be callable or None")
        if task_id_callback is not None and not callable(task_id_callback):
            close_coroutine_if_needed(coroutine)
            raise TypeError("task_id_callback must be callable or None")
        normalized_task_name = normalize_task_name(task_name or command.command_type)
        with self._lock:
            loop = self._require_running_loop(coroutine)
            if not self._accepting_submissions:
                close_coroutine_if_needed(coroutine)
                raise RuntimeError("Core runner is not accepting submissions")
            future = asyncio.run_coroutine_threadsafe(
                self._schedule_submission(
                    coroutine,
                    command=command,
                    task_name=normalized_task_name,
                    prepare_command=prepare_command,
                    result_callback=result_callback,
                    task_id_callback=task_id_callback,
                ),
                loop,
            )
        return future.result()

    def cancel(
        self,
        request: CoreRuntimeCancellationRequest,
    ) -> CoreRuntimeCancellationResult:
        """Route cancellation to TaskManager on the Core event loop."""

        if not isinstance(request, CoreRuntimeCancellationRequest):
            raise TypeError("request must be CoreRuntimeCancellationRequest")
        loop = self._require_running_loop(None)
        future = asyncio.run_coroutine_threadsafe(
            self._cancel_on_loop(request),
            loop,
        )
        return future.result()

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Cancel active Core tasks and stop the event loop. Shutdown is idempotent."""

        if type(timeout) not in (float, int) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        with self._lock:
            self._accepting_submissions = False
            self._shutdown_drain_timeout = float(timeout)
            loop = self._loop
            thread = self._thread
        if loop is None or thread is None:
            return
        if current_thread() is thread:
            raise RuntimeError("CoreRunner.shutdown cannot run from runner thread")

        shutdown_error: BaseException | None = None
        if loop.is_running():
            cancel_future = asyncio.run_coroutine_threadsafe(
                self._task_manager.cancel_all(),
                loop,
            )
            try:
                cancel_future.result(timeout=timeout)
            except FutureTimeoutError as exc:
                shutdown_error = RuntimeError(
                    "Core runner task settlement timed out"
                )
                self._route_shutdown_exception(
                    shutdown_error,
                    context={
                        "timeout_s": float(timeout),
                        "phase": "task_settlement",
                    },
                )
            except Exception as exc:
                shutdown_error = exc
                self._route_shutdown_exception(
                    exc,
                    context={
                        "timeout_s": float(timeout),
                        "phase": "task_settlement",
                    },
                )
            finally:
                loop.call_soon_threadsafe(loop.stop)

        thread.join(timeout=timeout)
        if thread.is_alive():
            shutdown_error = RuntimeError("Core runner event loop did not stop")
            self._route_shutdown_exception(
                shutdown_error,
                context={
                    "timeout_s": float(timeout),
                    "phase": "loop_stop",
                },
            )

        if not thread.is_alive():
            with self._lock:
                self._loop = None
                self._thread = None
        if shutdown_error is not None:
            raise shutdown_error

    def _require_running_loop(
        self,
        rejected_coroutine: object | None,
    ) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or not self.is_running:
            close_coroutine_if_needed(rejected_coroutine)
            raise RuntimeError("Core runner is not running")
        return loop

    async def _schedule_submission(
        self,
        coroutine: CoroutineObject,
        *,
        command: CoreRuntimeCommand,
        task_name: str,
        prepare_command: CoreRuntimeCommandPrepareCallback | None,
        result_callback: CoreRuntimeResultCallback | None,
        task_id_callback: CoreRuntimeTaskIdCallback | None,
    ) -> CoreRuntimeSubmission:
        task_id_ref = _TaskIdRef()
        try:
            prepared_command = command
            if prepare_command is not None:
                prepared_command = prepare_command(command)
                if not isinstance(prepared_command, CoreRuntimeCommand):
                    raise TypeError("prepare_command must return CoreRuntimeCommand")
            task_id = self._task_manager.create_task(
                self._execute_task(
                    coroutine,
                    command=prepared_command,
                    task_id_ref=task_id_ref,
                    result_callback=result_callback,
                ),
                task_name=task_name,
                operation_id=prepared_command.metadata.operation_id,
                correlation_id=prepared_command.metadata.correlation_id,
                metadata=_task_metadata(prepared_command),
            )
        except Exception:
            close_coroutine_if_needed(coroutine)
            raise
        task_id_ref.set(task_id)
        metadata = prepared_command.metadata.with_task_id(task_id)
        if task_id_callback is not None:
            task_id_callback(task_id)
        return CoreRuntimeSubmission(
            command_id=prepared_command.command_id,
            task_id=task_id,
            accepted=True,
            metadata=metadata,
        )

    async def _execute_task(
        self,
        coroutine: CoroutineObject,
        *,
        command: CoreRuntimeCommand,
        task_id_ref: _TaskIdRef,
        result_callback: CoreRuntimeResultCallback | None,
    ) -> object:
        task_id = task_id_ref.task_id
        if task_id is None:
            close_coroutine_if_needed(coroutine)
            raise RuntimeError("Core runtime task identity was not assigned")
        metadata = command.metadata.with_task_id(task_id)
        try:
            payload_value = await coroutine
        except asyncio.CancelledError:
            result = CoreRuntimeResult(
                command_id=command.command_id,
                task_id=task_id,
                status=CoreRuntimeResultStatus.CANCELLED,
                metadata=metadata,
            )
            self._deliver_result(result_callback, result)
            raise
        except Exception as exc:
            result = CoreRuntimeResult(
                command_id=command.command_id,
                task_id=task_id,
                status=CoreRuntimeResultStatus.FAILED,
                metadata=metadata,
                error=CoreRuntimeError(
                    error_type=type(exc).__name__,
                    message=str(exc) or type(exc).__name__,
                    details={
                        "command_id": command.command_id,
                        "task_id": task_id,
                        "operation_id": metadata.operation_id,
                        "correlation_id": metadata.correlation_id,
                    },
                ),
            )
            self._deliver_result(result_callback, result)
            raise
        else:
            result = CoreRuntimeResult(
                command_id=command.command_id,
                task_id=task_id,
                status=CoreRuntimeResultStatus.COMPLETED,
                metadata=metadata,
                payload=_payload_from_value(payload_value),
            )
            self._deliver_result(result_callback, result)
            return payload_value

    async def _cancel_on_loop(
        self,
        request: CoreRuntimeCancellationRequest,
    ) -> CoreRuntimeCancellationResult:
        requested = self._task_manager.cancel_task(request.task_id)
        message = (
            "Task cancellation requested."
            if requested
            else "Task was not active; cancellation was not requested."
        )
        return CoreRuntimeCancellationResult(
            task_id=request.task_id,
            requested=requested,
            message=message,
            metadata=request.metadata.with_task_id(request.task_id),
        )

    def _deliver_result(
        self,
        result_callback: CoreRuntimeResultCallback | None,
        result: CoreRuntimeResult,
    ) -> None:
        if result_callback is None:
            return
        try:
            result_callback(result)
        except Exception as exc:
            if self._error_router is not None:
                self._error_router.route_exception(
                    exc,
                    message="Core runtime result callback failed",
                    severity=ErrorSeverity.ERROR,
                    correlation_id=result.metadata.correlation_id,
                    context={
                        "command_id": result.command_id,
                        "task_id": result.task_id,
                    },
                )

    def _route_shutdown_exception(
        self,
        exception: BaseException,
        *,
        context: Mapping[str, object],
    ) -> None:
        if self._error_router is None:
            return
        self._error_router.route_exception(
            exception,
            message="Core runner shutdown failed",
            severity=ErrorSeverity.ERROR,
            context=context,
        )

    def _run_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        ready: Event,
        failed: list[BaseException],
    ) -> None:
        try:
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            if pending:
                for task in pending:
                    task.cancel()
                _done, unsettled = loop.run_until_complete(
                    asyncio.wait(
                        pending,
                        timeout=self._shutdown_drain_timeout,
                    )
                )
                if unsettled and self._error_router is not None:
                    self._error_router.route_error(
                        "Core runner pending tasks did not settle before loop close",
                        severity=ErrorSeverity.ERROR,
                        context={
                            "pending_task_count": len(unsettled),
                            "timeout_s": self._shutdown_drain_timeout,
                        },
                    )
                loop.run_until_complete(
                    asyncio.gather(
                        *(task for task in pending if task.done()),
                        return_exceptions=True,
                    )
                )
        except BaseException as exc:
            failed.append(exc)
            ready.set()
        finally:
            loop.close()


def _task_metadata(command: CoreRuntimeCommand) -> dict[str, object]:
    metadata = command.metadata
    return {
        "command_id": command.command_id,
        "command_type": command.command_type,
        "schema_version": metadata.schema_version,
        "action_id": metadata.action_id,
        "window_id": metadata.window_id,
        "actor_id": metadata.actor_id,
        "session_id": metadata.session_id,
        "permission": metadata.permission,
        "domain": metadata.domain,
        "suite": metadata.suite,
        "source": metadata.source,
        "correlation_id": metadata.correlation_id,
        "extra": dict(metadata.extra),
    }


def _payload_from_value(value: object) -> Mapping[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}
