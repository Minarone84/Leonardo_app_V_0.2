"""Canonical task lifecycle owner for Leonardo Light V2."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from leonardo.audit import AuditEventV1
from leonardo.core.async_runtime import (
    CoroutineObject,
    close_coroutine_if_needed,
    is_coroutine_object,
    normalize_task_name,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    task_name: str
    status: str
    created_at_utc: datetime
    started_at_utc: datetime | None
    finished_at_utc: datetime | None
    progress_current: int | None
    progress_total: int | None
    progress_message: str
    correlation_id: str | None
    error_message: str | None
    metadata: dict[str, object]


@dataclass
class _TaskRecord:
    task_id: str
    task_name: str
    asyncio_task: asyncio.Task[object]
    status: str = "running"
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at_utc: datetime | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    progress_message: str = ""
    correlation_id: str | None = None
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class TaskManager:
    """Own active and recent task state. Business logic remains outside Core."""

    def __init__(
        self,
        *,
        error_router: ErrorRouter | None = None,
        audit_log: AuditLog | None = None,
        actor_id: str = "local-user",
        logger: logging.Logger | None = None,
        history_limit: int = 500,
    ) -> None:
        if error_router is not None and not isinstance(error_router, ErrorRouter):
            raise TypeError("error_router must be an ErrorRouter")
        if audit_log is not None and not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id must be a non-empty string")
        if logger is not None and not isinstance(logger, logging.Logger):
            raise TypeError("logger must be a logging.Logger")
        if type(history_limit) is not int or history_limit <= 0:
            raise ValueError("history_limit must be a positive integer")
        self._error_router = error_router
        self._audit_log = audit_log
        self._actor_id = actor_id.strip()
        self._logger = logger or logging.getLogger("leonardo")
        self._history_limit = history_limit
        self._records: dict[str, _TaskRecord] = {}
        self._order: list[str] = []
        self._lock = RLock()

    def create_task(
        self,
        coroutine: CoroutineObject,
        *,
        task_name: str,
        allow_duplicate_name: bool = False,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        normalized = normalize_task_name(task_name)
        if not is_coroutine_object(coroutine):
            raise TypeError("coroutine must be a coroutine object")
        with self._lock:
            if not allow_duplicate_name and any(
                record.task_name == normalized and record.status in _ACTIVE_STATUSES
                for record in self._records.values()
            ):
                close_coroutine_if_needed(coroutine)
                raise ValueError(f"Task name is already active: {normalized}")

        loop = asyncio.get_running_loop()
        task_id = uuid4().hex
        async_task = loop.create_task(coroutine, name=f"{normalized}:{task_id}")
        record = _TaskRecord(
            task_id=task_id,
            task_name=normalized,
            asyncio_task=async_task,
            correlation_id=correlation_id,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[task_id] = record
            self._order.append(task_id)
            self._trim_history_locked()
        self._emit_audit(
            AuditEventV1(
                event_type="task.submitted",
                category="runtime",
                message=f"Task submitted: {normalized}",
                actor_id=self._actor_id,
                task_id=task_id,
                correlation_id=correlation_id,
                details={"task_name": normalized},
            )
        )
        self._logger.info("Task submitted: %s [%s]", normalized, task_id)
        async_task.add_done_callback(
            lambda completed: self._on_task_done(task_id, completed)
        )
        return task_id

    async def wait_task(self, task_id: str) -> object:
        record = self._require_record(task_id)
        return await record.asyncio_task

    def update_progress(
        self,
        task_id: str,
        *,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> TaskSnapshot:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if current is not None and type(current) is not int:
            raise TypeError("current must be an integer or None")
        if total is not None and type(total) is not int:
            raise TypeError("total must be an integer or None")
        with self._lock:
            record = self._require_record_locked(task_id)
            record.progress_message = message
            record.progress_current = current
            record.progress_total = total
            return _snapshot(record)

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            record = self._records.get(task_id)
            if record is None or record.status not in _ACTIVE_STATUSES:
                return False
            record.status = "cancel_requested"
            task = record.asyncio_task
            task_name = record.task_name
            correlation_id = record.correlation_id
        cancelled = task.cancel()
        if cancelled:
            self._emit_audit(
                AuditEventV1(
                    event_type="task.cancel_requested",
                    category="runtime",
                    message=f"Task cancellation requested: {task_name}",
                    actor_id=self._actor_id,
                    task_id=task_id,
                    correlation_id=correlation_id,
                    details={"task_name": task_name},
                )
            )
            self._logger.info("Task cancellation requested: %s [%s]", task_name, task_id)
        return cancelled

    async def cancel_all(self) -> None:
        with self._lock:
            active = [
                record
                for record in self._records.values()
                if record.status in _ACTIVE_STATUSES
            ]
        for record in active:
            self.cancel_task(record.task_id)
        if active:
            await asyncio.gather(
                *(record.asyncio_task for record in active),
                return_exceptions=True,
            )

    def active_tasks(self) -> tuple[TaskSnapshot, ...]:
        with self._lock:
            return tuple(
                _snapshot(self._records[task_id])
                for task_id in self._order
                if task_id in self._records
                and self._records[task_id].status in _ACTIVE_STATUSES
            )

    def snapshots(self) -> tuple[TaskSnapshot, ...]:
        with self._lock:
            return tuple(
                _snapshot(self._records[task_id])
                for task_id in self._order
                if task_id in self._records
            )

    def get_snapshot(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            record = self._records.get(task_id)
            return _snapshot(record) if record is not None else None

    def _require_record(self, task_id: str) -> _TaskRecord:
        with self._lock:
            return self._require_record_locked(task_id)

    def _require_record_locked(self, task_id: str) -> _TaskRecord:
        record = self._records.get(task_id)
        if record is None:
            raise KeyError(f"Unknown task: {task_id}")
        return record

    def _on_task_done(self, task_id: str, completed: asyncio.Task[object]) -> None:
        exception: BaseException | None = None
        with self._lock:
            record = self._records.get(task_id)
            if record is None:
                return
            record.finished_at_utc = datetime.now(UTC)
            if completed.cancelled():
                record.status = "cancelled"
                event_type = "task.cancelled"
                message = f"Task cancelled: {record.task_name}"
                severity = "info"
            else:
                exception = completed.exception()
                if exception is None:
                    record.status = "completed"
                    event_type = "task.completed"
                    message = f"Task completed: {record.task_name}"
                    severity = "info"
                else:
                    record.status = "failed"
                    record.error_message = str(exception)
                    event_type = "task.failed"
                    message = f"Task failed: {record.task_name}"
                    severity = "error"
            correlation_id = record.correlation_id
            task_name = record.task_name

        self._emit_audit(
            AuditEventV1(
                event_type=event_type,
                category="runtime",
                severity=severity,
                message=message,
                actor_id=self._actor_id,
                task_id=task_id,
                correlation_id=correlation_id,
                details={"task_name": task_name},
                error_type=type(exception).__name__ if exception is not None else None,
                error_message=str(exception) if exception is not None else None,
            )
        )
        if exception is None:
            self._logger.info("%s [%s]", message, task_id)
            return
        self._logger.error("%s [%s]: %s", message, task_id, exception)
        if self._error_router is not None and isinstance(exception, Exception):
            self._error_router.route_exception(
                exception,
                message=message,
                task_id=task_id,
                correlation_id=correlation_id,
                context={"task_name": task_name},
            )

    def _emit_audit(self, event: AuditEventV1) -> None:
        if self._audit_log is None:
            return
        try:
            self._audit_log.emit(event)
        except Exception:
            self._logger.exception(
                "Task audit emission failed: %s [%s]",
                event.event_type,
                event.task_id,
            )

    def _trim_history_locked(self) -> None:
        while len(self._order) > self._history_limit:
            oldest = self._order[0]
            record = self._records.get(oldest)
            if record is not None and record.status in _ACTIVE_STATUSES:
                break
            self._order.pop(0)
            self._records.pop(oldest, None)


_ACTIVE_STATUSES = frozenset({"running", "cancel_requested"})


def _snapshot(record: _TaskRecord) -> TaskSnapshot:
    return TaskSnapshot(
        task_id=record.task_id,
        task_name=record.task_name,
        status=record.status,
        created_at_utc=record.created_at_utc,
        started_at_utc=record.started_at_utc,
        finished_at_utc=record.finished_at_utc,
        progress_current=record.progress_current,
        progress_total=record.progress_total,
        progress_message=record.progress_message,
        correlation_id=record.correlation_id,
        error_message=record.error_message,
        metadata=dict(record.metadata),
    )
