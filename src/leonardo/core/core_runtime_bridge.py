"""Core-facing runtime bridge for command submission and callback delivery."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import replace
from threading import Lock

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.contracts.core_runtime import (
    CoreRuntimeCancellationRequest,
    CoreRuntimeCancellationResult,
    CoreRuntimeCommand,
    CoreRuntimeError,
    CoreRuntimeMetadata,
    CoreRuntimeProgress,
    CoreRuntimeResult,
    CoreRuntimeResultStatus,
    CoreRuntimeSubmission,
)
from leonardo.contracts.identity import SessionContext
from leonardo.contracts.operations import OperationKind
from leonardo.core.audit_log import AuditLog
from leonardo.core.core_runner import CoreRunner
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.user_policy import UserPolicy


CoreRuntimeCallbackDispatcher = Callable[[Callable[[], None]], None]
CoreRuntimeResultCallback = Callable[[CoreRuntimeResult], None]
CoreRuntimeProgressCallback = Callable[[CoreRuntimeProgress], None]
CoreRuntimeCommandHandler = Callable[
    [CoreRuntimeCommand, "CoreRuntimeProgressReporter"],
    object,
]
_DENIED_TASK_ID = "permission-denied"


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


class _TaskIdRef:
    """Mutable task identifier reference populated after TaskManager scheduling."""

    def __init__(self) -> None:
        self.task_id: str | None = None

    def set(self, task_id: str) -> None:
        self.task_id = task_id


class _CommandRef:
    """Mutable command reference updated after operation metadata preparation."""

    def __init__(self, command: CoreRuntimeCommand) -> None:
        self.command = command

    def set(self, command: CoreRuntimeCommand) -> None:
        self.command = command


class CoreRuntimeProgressReporter:
    """
    Emit progress contracts for a bridge-submitted command.

    The reporter is passed to command handlers by `CoreRuntimeBridge`. It
    constructs immutable progress contracts and delivers them through the
    configured callback dispatcher without owning GUI widgets or domain state.
    """

    def __init__(
        self,
        command_ref: _CommandRef,
        task_id_ref: _TaskIdRef,
        dispatcher: CoreRuntimeCallbackDispatcher,
        progress_callback: CoreRuntimeProgressCallback | None,
    ) -> None:
        self._command_ref = command_ref
        self._task_id_ref = task_id_ref
        self._dispatcher = dispatcher
        self._progress_callback = progress_callback

    def report(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        percent: float | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> CoreRuntimeProgress:
        """
        Build and dispatch a progress event for the active Core task.

        Raises
        ------
        RuntimeError
            Raised when progress is emitted before TaskManager has assigned a
            stable task identifier.
        """

        task_id = self._task_id_ref.task_id
        if task_id is None:
            raise RuntimeError("Core runtime progress requires a task identifier")
        command = self._command_ref.command
        progress = CoreRuntimeProgress(
            command_id=command.command_id,
            task_id=task_id,
            message=message,
            metadata=command.metadata.with_task_id(task_id),
            current=current,
            total=total,
            percent=percent,
            payload=payload or {},
        )
        if self._progress_callback is not None:
            self._dispatcher(lambda: self._progress_callback(progress))
        return progress


class CoreRuntimeBridge:
    """
    Submit GUI-facing command intent into the Core runtime runner.

    The bridge owns no domain behavior. Callers provide a command contract and
    a handler callable. The bridge wraps that handler for CoreRunner scheduling,
    attaches progress reporting, and dispatches terminal results through the
    configured callback dispatcher.
    """

    def __init__(
        self,
        runner: CoreRunner,
        *,
        operation_registry: OperationRegistry | None = None,
        callback_dispatcher: CoreRuntimeCallbackDispatcher | None = None,
        session_provider: object | None = None,
        user_policy: UserPolicy | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        if not isinstance(runner, CoreRunner):
            raise TypeError("runner must be CoreRunner")
        if operation_registry is not None and not isinstance(
            operation_registry,
            OperationRegistry,
        ):
            raise TypeError("operation_registry must be OperationRegistry or None")
        if callback_dispatcher is not None and not callable(callback_dispatcher):
            raise TypeError("callback_dispatcher must be callable or None")
        if session_provider is not None and not hasattr(
            session_provider,
            "current_session",
        ):
            raise TypeError("session_provider must expose current_session or be None")
        if user_policy is not None and not isinstance(user_policy, UserPolicy):
            raise TypeError("user_policy must be UserPolicy or None")
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be AuditLog or None")
        self._runner = runner
        self._operation_registry = operation_registry
        self._callback_dispatcher = callback_dispatcher or _inline_dispatch
        self._session_provider = session_provider
        self._user_policy = user_policy
        self._audit_log = audit_log
        self._lock = Lock()
        self._accepting_submissions = True

    @property
    def runner(self) -> CoreRunner:
        """Return the owned Core runner boundary."""

        return self._runner

    @property
    def is_accepting_submissions(self) -> bool:
        """Return whether command submissions are accepted by the bridge."""

        return self._accepting_submissions

    def start(self) -> None:
        """Start the underlying Core runner."""

        self._runner.start()
        with self._lock:
            self._accepting_submissions = True

    def stop_accepting_submissions(self) -> None:
        """Prevent new bridge command submissions during shutdown."""

        with self._lock:
            self._accepting_submissions = False

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Stop the underlying Core runner."""

        self.stop_accepting_submissions()
        self._runner.shutdown(timeout=timeout)

    def submit_command(
        self,
        command: CoreRuntimeCommand,
        handler: CoreRuntimeCommandHandler,
        *,
        result_callback: CoreRuntimeResultCallback | None = None,
        progress_callback: CoreRuntimeProgressCallback | None = None,
        task_name: str | None = None,
        operation_kind: OperationKind = OperationKind.USER_WORKFLOW,
        operation_label: str | None = None,
    ) -> CoreRuntimeSubmission:
        """
        Submit a command handler to CoreRunner without interpreting the command.

        The handler may be synchronous or asynchronous. Returned mappings become
        result payloads through CoreRunner. Other return values are wrapped under
        the generic ``value`` payload key by CoreRunner.
        """

        if not isinstance(command, CoreRuntimeCommand):
            raise TypeError("command must be CoreRuntimeCommand")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if result_callback is not None and not callable(result_callback):
            raise TypeError("result_callback must be callable or None")
        if progress_callback is not None and not callable(progress_callback):
            raise TypeError("progress_callback must be callable or None")
        if not isinstance(operation_kind, OperationKind):
            raise TypeError("operation_kind must be an OperationKind")
        if operation_label is not None:
            if not isinstance(operation_label, str):
                raise TypeError("operation_label must be a string or None")
            if not operation_label.strip():
                raise ValueError("operation_label must be a non-empty string or None")
        with self._lock:
            if not self._accepting_submissions:
                raise RuntimeError("Core runtime bridge is not accepting submissions")

        denied_submission = self._deny_unauthorized_command(command, result_callback)
        if denied_submission is not None:
            return denied_submission

        command_ref = _CommandRef(command)
        task_id_ref = _TaskIdRef()
        progress_reporter = CoreRuntimeProgressReporter(
            command_ref,
            task_id_ref,
            self._callback_dispatcher,
            progress_callback,
        )

        async def invoke_handler() -> object:
            value = handler(command_ref.command, progress_reporter)
            if inspect.isawaitable(value):
                return await value
            return value

        def prepare_command(original: CoreRuntimeCommand) -> CoreRuntimeCommand:
            prepared = self._prepare_operation_command(
                original,
                operation_kind=operation_kind,
                operation_label=operation_label,
            )
            command_ref.set(prepared)
            return prepared

        def record_task_id(task_id: str) -> None:
            task_id_ref.set(task_id)
            self._mark_operation_running(command_ref.command, task_id)
            self._emit_command_accepted(command_ref.command, task_id)

        return self._runner.submit_coroutine(
            invoke_handler(),
            command=command,
            task_name=task_name,
            prepare_command=prepare_command,
            result_callback=self._dispatch_result(result_callback),
            task_id_callback=record_task_id,
        )

    def cancel(
        self,
        request: CoreRuntimeCancellationRequest,
    ) -> CoreRuntimeCancellationResult:
        """Route cancellation to the underlying Core runner."""

        return self._runner.cancel(request)

    def cancel_operation(
        self,
        operation_id: str,
        *,
        command_id: str | None = None,
        reason: str = "",
    ) -> CoreRuntimeCancellationResult:
        """Route cancellation by semantic operation identifier to its task."""

        if self._operation_registry is None:
            raise RuntimeError("operation cancellation requires an OperationRegistry")
        operation = self._operation_registry.get_operation(operation_id)
        if operation is None:
            raise KeyError(f"Operation is not active: {operation_id}")
        if operation.task_id is None:
            raise ValueError(f"Operation has no task to cancel: {operation_id}")

        self._operation_registry.request_cancel(operation.operation_id)
        return self.cancel(
            CoreRuntimeCancellationRequest(
                task_id=operation.task_id,
                command_id=command_id,
                reason=reason,
                metadata=CoreRuntimeMetadata(
                    operation_id=operation.operation_id,
                    task_id=operation.task_id,
                    action_id=operation.action_id,
                    window_id=operation.window_id,
                    actor_id=operation.actor_id,
                    session_id=operation.session_id,
                    correlation_id=operation.correlation_id,
                    extra=dict(operation.metadata),
                ),
            )
        )

    def _deny_unauthorized_command(
        self,
        command: CoreRuntimeCommand,
        result_callback: CoreRuntimeResultCallback | None,
    ) -> CoreRuntimeSubmission | None:
        required_permission = command.metadata.required_permission
        if required_permission is None:
            return None

        reason = self._authorization_denial_reason(required_permission)
        if not reason:
            return None

        denied_metadata = command.metadata.with_denial(
            required_permission=required_permission,
            denied_reason=reason,
        )
        error = CoreRuntimeError(
            error_type="PermissionDenied",
            message=f"Command requires permission: {required_permission}",
            details={
                "command_id": command.command_id,
                "command_type": command.command_type,
                "required_permission": required_permission,
                "denied_reason": reason,
                "action_id": command.metadata.action_id,
                "window_id": command.metadata.window_id,
                "actor_id": command.metadata.actor_id,
                "session_id": command.metadata.session_id,
                "operation_id": command.metadata.operation_id,
                "correlation_id": command.metadata.correlation_id,
            },
        )
        result = CoreRuntimeResult(
            command_id=command.command_id,
            task_id=_DENIED_TASK_ID,
            status=CoreRuntimeResultStatus.FAILED,
            metadata=denied_metadata.with_task_id(_DENIED_TASK_ID),
            error=error,
        )
        self._emit_command_denied(command, result, reason)
        if result_callback is not None:
            self._callback_dispatcher(lambda: result_callback(result))
        return CoreRuntimeSubmission(
            command_id=command.command_id,
            task_id=_DENIED_TASK_ID,
            accepted=False,
            metadata=result.metadata,
        )

    def _authorization_denial_reason(self, required_permission: str) -> str:
        if self._user_policy is None:
            return "missing_user_policy"
        if self._session_provider is None:
            return "missing_session"
        session = self._current_session()
        if session is None:
            return "missing_session"
        actor = session.actor
        if actor is None:
            return "missing_actor"
        try:
            permission = self._user_policy.normalize_permission(required_permission)
        except ValueError:
            return "unknown_permission"
        if not self._user_policy.has_permission(actor, permission):
            return "missing_permission"
        return ""

    def _current_session(self) -> SessionContext | None:
        if self._session_provider is None:
            return None
        session = self._session_provider.current_session
        if session is None:
            return None
        if not isinstance(session, SessionContext):
            raise TypeError("current_session must be SessionContext or None")
        return session

    def _emit_command_denied(
        self,
        command: CoreRuntimeCommand,
        result: CoreRuntimeResult,
        reason: str,
    ) -> None:
        if self._audit_log is None:
            return
        session = self._current_session()
        self._audit_log.emit(
            AuditEvent(
                event_type="core_runtime.command.denied",
                message=f"Core runtime command denied: {command.command_type}",
                severity=AuditSeverity.WARNING,
                category=AuditCategory.RUNTIME,
                actor_id=command.metadata.actor_id
                or _optional_string(getattr(session, "actor_id", None)),
                session_id=command.metadata.session_id
                or _optional_string(getattr(session, "session_id", None)),
                origin=getattr(session, "origin", None),
                window_id=command.metadata.window_id,
                action_id=command.metadata.action_id,
                operation_id=command.metadata.operation_id,
                task_id=result.task_id,
                correlation_id=command.metadata.correlation_id,
                payload={
                    "command_id": command.command_id,
                    "command_type": command.command_type,
                    "required_permission": result.metadata.required_permission,
                    "denied_reason": reason,
                    "domain": command.metadata.domain,
                    "suite": command.metadata.suite,
                    "source": command.metadata.source,
                    "extra_keys": sorted(command.metadata.extra.keys()),
                },
            )
        )

    def _emit_command_accepted(
        self,
        command: CoreRuntimeCommand,
        task_id: str,
    ) -> None:
        if self._audit_log is None:
            return
        session = self._current_session()
        self._audit_log.emit(
            AuditEvent(
                event_type="core_runtime.command.accepted",
                message=f"Core runtime command accepted: {command.command_type}",
                severity=AuditSeverity.INFO,
                category=AuditCategory.RUNTIME,
                actor_id=command.metadata.actor_id
                or _optional_string(getattr(session, "actor_id", None)),
                session_id=command.metadata.session_id
                or _optional_string(getattr(session, "session_id", None)),
                origin=getattr(session, "origin", None),
                window_id=command.metadata.window_id,
                action_id=command.metadata.action_id,
                operation_id=command.metadata.operation_id,
                task_id=task_id,
                correlation_id=command.metadata.correlation_id,
                payload={
                    "command_id": command.command_id,
                    "command_type": command.command_type,
                    "required_permission": command.metadata.required_permission,
                    "domain": command.metadata.domain,
                    "suite": command.metadata.suite,
                    "source": command.metadata.source,
                    "extra_keys": sorted(command.metadata.extra.keys()),
                },
            )
        )

    def _dispatch_result(
        self,
        result_callback: CoreRuntimeResultCallback | None,
    ) -> CoreRuntimeResultCallback:

        def dispatch(result: CoreRuntimeResult) -> None:
            self._mark_operation_terminal(result)
            if result_callback is not None:
                self._callback_dispatcher(lambda: result_callback(result))

        return dispatch

    def _prepare_operation_command(
        self,
        command: CoreRuntimeCommand,
        *,
        operation_kind: OperationKind,
        operation_label: str | None,
    ) -> CoreRuntimeCommand:
        if self._operation_registry is None:
            return command
        operation_id = command.metadata.operation_id
        if operation_id is not None:
            if self._operation_registry.get_operation(operation_id) is None:
                raise KeyError(f"Operation is not active: {operation_id}")
            return command

        operation = self._operation_registry.request_operation(
            operation_kind=operation_kind,
            label=operation_label or command.command_type,
            actor_id=command.metadata.actor_id,
            session_id=command.metadata.session_id,
            window_id=command.metadata.window_id,
            action_id=command.metadata.action_id,
            correlation_id=command.metadata.correlation_id,
            metadata={
                "command_id": command.command_id,
                "command_type": command.command_type,
                "permission": command.metadata.permission,
                "required_permission": command.metadata.required_permission,
                "domain": command.metadata.domain,
                "suite": command.metadata.suite,
                "source": command.metadata.source,
                "schema_version": command.metadata.schema_version,
                "extra": dict(command.metadata.extra),
            },
        )
        return replace(
            command,
            metadata=command.metadata.with_operation_id(operation.operation_id),
        )

    def _mark_operation_running(
        self,
        command: CoreRuntimeCommand,
        task_id: str,
    ) -> None:
        if self._operation_registry is None:
            return
        operation_id = command.metadata.operation_id
        if operation_id is None:
            return
        self._operation_registry.mark_running(operation_id, task_id=task_id)

    def _mark_operation_terminal(self, result: CoreRuntimeResult) -> None:
        if self._operation_registry is None:
            return
        operation_id = result.metadata.operation_id
        if operation_id is None:
            return

        if result.status is CoreRuntimeResultStatus.COMPLETED:
            self._operation_registry.mark_completed(operation_id)
            return
        if result.status is CoreRuntimeResultStatus.CANCELLED:
            self._operation_registry.mark_cancelled(operation_id)
            return
        if result.status is CoreRuntimeResultStatus.FAILED:
            error_message = (
                result.error.message if result.error is not None else "Command failed"
            )
            self._operation_registry.mark_failed(operation_id, error_message)
