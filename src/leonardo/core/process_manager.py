"""Controlled external-process lifecycle owner for Leonardo Light V2."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import uuid4

from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter


class ManagedProcessHandle(Protocol):
    pid: int | None

    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


class ProcessLauncher(Protocol):
    def __call__(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path | None,
        env: dict[str, str] | None,
    ) -> ManagedProcessHandle: ...


@dataclass(frozen=True)
class ProcessSnapshot:
    process_id: str
    label: str
    command: tuple[str, ...]
    status: str
    pid: int | None
    exit_code: int | None
    started_at_utc: datetime
    finished_at_utc: datetime | None
    error_message: str | None


@dataclass
class _ProcessRecord:
    process_id: str
    label: str
    command: tuple[str, ...]
    handle: ManagedProcessHandle
    status: str = "running"
    pid: int | None = None
    exit_code: int | None = None
    started_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at_utc: datetime | None = None
    error_message: str | None = None
    terminal_event_emitted: bool = False


class ProcessManager:
    def __init__(
        self,
        audit_log: AuditLog,
        *,
        error_router: ErrorRouter | None = None,
        launcher: ProcessLauncher | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if logger is not None and not isinstance(logger, logging.Logger):
            raise TypeError("logger must be a logging.Logger")
        self._audit_log = audit_log
        self._error_router = error_router
        self._launcher = launcher or _default_launcher
        self._logger = logger or logging.getLogger("leonardo")
        self._records: dict[str, _ProcessRecord] = {}
        self._lock = RLock()

    def launch(
        self,
        command: tuple[str, ...] | list[str],
        *,
        label: str,
        process_id: str | None = None,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        normalized = tuple(command)
        if not normalized or any(not isinstance(part, str) or not part for part in normalized):
            raise ValueError("command must contain non-empty strings")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        identity = process_id or uuid4().hex
        with self._lock:
            if identity in self._records:
                raise ValueError(f"Process already registered: {identity}")
        try:
            handle = self._launcher(
                normalized,
                cwd=Path(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
            )
        except Exception as exc:
            self._logger.exception("Process launch failed: %s [%s]", label, identity)
            if self._error_router is not None:
                self._error_router.route_exception(
                    exc,
                    message=f"Process launch failed: {label}",
                    process_id=identity,
                    context={"command": normalized},
                )
            raise
        record = _ProcessRecord(
            process_id=identity,
            label=label.strip(),
            command=normalized,
            handle=handle,
            pid=handle.pid,
        )
        with self._lock:
            self._records[identity] = record
        self._emit_audit(
            AuditEventV1(
                event_type="process.started",
                category="runtime",
                message=f"Process started: {record.label}",
                process_id=identity,
                details={"command": normalized, "pid": record.pid},
            )
        )
        self._logger.info("Process started: %s [%s]", record.label, identity)
        return identity

    def poll(self, process_id: str) -> ProcessSnapshot:
        with self._lock:
            record = self._require_locked(process_id)
            handle = record.handle
        exit_code = handle.poll()
        event: AuditEventV1 | None = None
        if exit_code is not None:
            with self._lock:
                record = self._require_locked(process_id)
                if record.status not in {"completed", "failed", "terminated"}:
                    termination_requested = record.status == "terminate_requested"
                    if termination_requested:
                        record.status = "terminated"
                    else:
                        record.status = "completed" if exit_code == 0 else "failed"
                    record.exit_code = int(exit_code)
                    record.finished_at_utc = datetime.now(UTC)
                    if record.status == "failed":
                        record.error_message = f"Process exited with code {exit_code}"
                if not record.terminal_event_emitted:
                    record.terminal_event_emitted = True
                    event_type = f"process.{record.status}"
                    event = AuditEventV1(
                        event_type=event_type,
                        category="runtime",
                        severity="error" if record.status == "failed" else "info",
                        message=f"Process {record.status}: {record.label}",
                        process_id=record.process_id,
                        details={
                            "command": record.command,
                            "pid": record.pid,
                            "exit_code": record.exit_code,
                        },
                        error_type="ProcessExitError" if record.status == "failed" else None,
                        error_message=record.error_message,
                    )
                snapshot = _snapshot(record)
            if event is not None:
                self._emit_audit(event)
                log_method = (
                    self._logger.error
                    if snapshot.status == "failed"
                    else self._logger.info
                )
                log_method(
                    "Process %s: %s [%s], exit=%s",
                    snapshot.status,
                    snapshot.label,
                    snapshot.process_id,
                    snapshot.exit_code,
                )
            return snapshot
        return self.get_snapshot(process_id)

    def terminate(self, process_id: str, *, force: bool = False) -> bool:
        with self._lock:
            record = self._records.get(process_id)
            if record is None or record.status not in {"running", "terminate_requested"}:
                return False
            previous_status = record.status
            record.status = "terminate_requested"
            handle = record.handle
            label = record.label
        try:
            if force:
                handle.kill()
            else:
                handle.terminate()
        except Exception as exc:
            with self._lock:
                record = self._records.get(process_id)
                if record is not None:
                    record.status = previous_status
                    record.error_message = str(exc)
            self._logger.exception("Process termination failed: %s [%s]", label, process_id)
            if self._error_router is not None:
                self._error_router.route_exception(
                    exc,
                    message=f"Process termination failed: {label}",
                    process_id=process_id,
                    context={"force": force},
                )
            raise
        self._emit_audit(
            AuditEventV1(
                event_type="process.termination_requested",
                category="runtime",
                message=f"Process termination requested: {label}",
                process_id=process_id,
                details={"force": force},
            )
        )
        self._logger.info(
            "Process termination requested: %s [%s], force=%s",
            label,
            process_id,
            force,
        )
        return True

    def active_processes(self) -> tuple[ProcessSnapshot, ...]:
        with self._lock:
            identities = tuple(self._records)
        snapshots = tuple(self.poll(identity) for identity in identities)
        return tuple(
            item
            for item in snapshots
            if item.status in {"running", "terminate_requested"}
        )

    def snapshots(self) -> tuple[ProcessSnapshot, ...]:
        with self._lock:
            identities = tuple(self._records)
        return tuple(self.poll(identity) for identity in identities)

    def get_snapshot(self, process_id: str) -> ProcessSnapshot:
        with self._lock:
            return _snapshot(self._require_locked(process_id))

    def shutdown(self, *, timeout: float = 5.0) -> None:
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        active = self.active_processes()
        for snapshot in active:
            self.terminate(snapshot.process_id)
        if self._wait_for_exit(float(timeout)):
            return
        for snapshot in self.active_processes():
            self.terminate(snapshot.process_id, force=True)
        force_timeout = min(float(timeout), 1.0)
        if not self._wait_for_exit(force_timeout):
            remaining = ", ".join(
                item.process_id for item in self.active_processes()
            )
            raise TimeoutError(
                f"Managed processes did not stop within timeout: {remaining}"
            )

    def _wait_for_exit(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if not self.active_processes():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def _emit_audit(self, event: AuditEventV1) -> None:
        try:
            self._audit_log.emit(event)
        except Exception:
            self._logger.exception(
                "Process audit emission failed: %s [%s]",
                event.event_type,
                event.process_id,
            )

    def _require_locked(self, process_id: str) -> _ProcessRecord:
        record = self._records.get(process_id)
        if record is None:
            raise KeyError(f"Unknown process: {process_id}")
        return record


def _snapshot(record: _ProcessRecord) -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id=record.process_id,
        label=record.label,
        command=record.command,
        status=record.status,
        pid=record.pid,
        exit_code=record.exit_code,
        started_at_utc=record.started_at_utc,
        finished_at_utc=record.finished_at_utc,
        error_message=record.error_message,
    )


def _default_launcher(
    command: tuple[str, ...],
    *,
    cwd: Path | None,
    env: dict[str, str] | None,
) -> ManagedProcessHandle:
    merged_env = None if env is None else {**os.environ, **env}
    return subprocess.Popen(command, cwd=cwd, env=merged_env)  # noqa: S603
