"""Controlled process supervision for Leonardo V2 Core."""

from __future__ import annotations

import os
import subprocess
from typing import Protocol

from leonardo.contracts.errors import ErrorSeverity
from leonardo.contracts.processes import (
    ProcessLaunchRequest,
    ProcessRuntimeState,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter
from leonardo.core.state_store import StateStore


class ManagedProcessHandle(Protocol):
    """Minimal handle required for supervised process lifecycle control."""

    pid: int | None

    def poll(self) -> int | None:
        """Return the exit code when the process has completed."""

    def terminate(self) -> None:
        """Request graceful process termination."""

    def kill(self) -> None:
        """Force process termination."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process completion."""


class ProcessLauncher(Protocol):
    """Boundary used by ProcessManager to start processes."""

    def start(self, request: ProcessLaunchRequest) -> ManagedProcessHandle:
        """Start a process for an explicit launch request."""


class SubprocessLauncher:
    """Standard-library process launcher used outside tests."""

    def start(self, request: ProcessLaunchRequest) -> ManagedProcessHandle:
        """Start a process through ``subprocess.Popen``."""

        env = None
        if request.env:
            env = dict(os.environ)
            env.update(request.env)
        return subprocess.Popen(
            list(request.command),
            cwd=request.cwd,
            env=env,
        )


class ProcessManager:
    """
    Supervise explicitly launched operating-system processes.

    The manager owns only process lifecycle supervision. It does not register
    domain processes, execute actions, own TaskManager behavior, or start
    processes during application startup.
    """

    def __init__(
        self,
        state_store: StateStore,
        audit_log: AuditLog,
        *,
        launcher: ProcessLauncher | None = None,
        error_router: ErrorRouter | None = None,
    ) -> None:
        if not isinstance(state_store, StateStore):
            raise TypeError("state_store must be a StateStore")
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if error_router is not None and not isinstance(error_router, ErrorRouter):
            raise TypeError("error_router must be an ErrorRouter")
        self._state_store = state_store
        self._audit_log = audit_log
        self._launcher = launcher if launcher is not None else SubprocessLauncher()
        self._error_router = error_router
        self._handles: dict[str, ManagedProcessHandle] = {}

    def launch_process(
        self,
        request: ProcessLaunchRequest,
    ) -> ProcessRuntimeState:
        """
        Start a process from an explicit launch request.

        The process command is executed through the configured launcher boundary.
        Duplicate active process identifiers are rejected.
        """

        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("request must be a ProcessLaunchRequest")
        if self._is_active_process_id(request.process_id):
            raise ValueError(f"Process is already active: {request.process_id}")

        self._state_store.process_starting(request)
        try:
            handle = self._launcher.start(request)
        except Exception as exc:
            self._state_store.process_failed(
                request.process_id,
                error_message=str(exc) or type(exc).__name__,
            )
            self._route_exception(
                exc,
                message=f"Process launch failed: {request.label}",
                correlation_id=request.correlation_id,
                context={"process_id": request.process_id},
            )
            raise

        self._handles[request.process_id] = handle
        return self._state_store.process_running(
            request.process_id,
            pid=handle.pid,
        )

    def active_processes(self) -> tuple[ProcessRuntimeState, ...]:
        """Return defensive active process runtime state snapshots."""

        return self._state_store.processes_state()

    def poll_process(self, process_id: str) -> ProcessRuntimeState:
        """Refresh one active process from its handle status."""

        handle = self._require_handle(process_id)
        try:
            exit_code = handle.poll()
        except Exception as exc:
            state = self._current_state(process_id)
            terminal = self._state_store.process_failed(
                process_id,
                error_message=str(exc) or type(exc).__name__,
            )
            self._handles.pop(process_id, None)
            self._route_exception(
                exc,
                message=f"Process poll failed: {state.label}",
                correlation_id=state.correlation_id,
                context={"process_id": process_id},
            )
            return terminal

        if exit_code is None:
            return self._current_state(process_id)

        self._handles.pop(process_id, None)
        if exit_code == 0:
            return self._state_store.process_stopped(
                process_id,
                exit_code=exit_code,
            )
        return self._state_store.process_failed(
            process_id,
            exit_code=exit_code,
            error_message=f"Process exited with code {exit_code}",
        )

    def refresh_process(self, process_id: str) -> ProcessRuntimeState:
        """Alias for ``poll_process``."""

        return self.poll_process(process_id)

    def stop_process(self, process_id: str) -> ProcessRuntimeState:
        """Request graceful termination for one active process."""

        handle = self._require_handle(process_id)
        state = self._state_store.process_stop_requested(process_id)
        try:
            handle.terminate()
        except Exception as exc:
            terminal = self._state_store.process_failed(
                process_id,
                error_message=str(exc) or type(exc).__name__,
            )
            self._handles.pop(process_id, None)
            self._route_exception(
                exc,
                message=f"Process stop failed: {state.label}",
                correlation_id=state.correlation_id,
                context={"process_id": process_id},
            )
            return terminal
        return state

    def kill_process(self, process_id: str) -> ProcessRuntimeState:
        """Force termination for one active process."""

        handle = self._require_handle(process_id)
        state = self._current_state(process_id)
        try:
            handle.kill()
            exit_code = handle.wait(timeout=1.0)
        except Exception as exc:
            self._route_exception(
                exc,
                message=f"Process kill failed: {state.label}",
                correlation_id=state.correlation_id,
                context={"process_id": process_id},
            )
            raise

        self._handles.pop(process_id, None)
        return self._state_store.process_killed(
            process_id,
            exit_code=exit_code,
            error_message="Process killed",
        )

    def stop_all(self) -> tuple[ProcessRuntimeState, ...]:
        """Request graceful termination for all active process handles."""

        states: list[ProcessRuntimeState] = []
        for process_id in tuple(sorted(self._handles)):
            states.append(self.stop_process(process_id))
        return tuple(states)

    def _is_active_process_id(self, process_id: str) -> bool:
        if process_id in self._handles:
            return True
        return any(
            state.process_id == process_id
            for state in self._state_store.processes_state()
        )

    def _require_handle(self, process_id: str) -> ManagedProcessHandle:
        handle = self._handles.get(process_id)
        if handle is None:
            raise KeyError(f"Process is not active: {process_id}")
        return handle

    def _current_state(self, process_id: str) -> ProcessRuntimeState:
        for state in self._state_store.processes_state():
            if state.process_id == process_id:
                return state
        raise KeyError(f"Process runtime state is not active: {process_id}")

    def _route_exception(
        self,
        exception: Exception,
        *,
        message: str,
        correlation_id: str | None,
        context: dict[str, object],
    ) -> None:
        if self._error_router is None:
            return
        self._error_router.route_exception(
            exception,
            message=message,
            severity=ErrorSeverity.ERROR,
            correlation_id=correlation_id,
            context=context,
        )
