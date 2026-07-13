"""Read-only aggregation of authoritative runtime snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Callable

from leonardo.core.action_registry import ActionRegistry
from leonardo.core.audit_log import AuditLog
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.process_manager import ProcessManager
from leonardo.core.task_manager import TaskManager
from leonardo.core.window_registry import WindowRegistry


@dataclass(frozen=True)
class RuntimeSnapshot:
    generated_at_utc: datetime
    app_status: str
    actor_id: str
    tasks: tuple[dict[str, object], ...]
    processes: tuple[dict[str, object], ...]
    connections: tuple[dict[str, object], ...]
    websocket_channels: tuple[dict[str, object], ...]
    windows: tuple[dict[str, object], ...]
    actions: tuple[dict[str, object], ...]
    recent_events: tuple[dict[str, object], ...]
    audit_sink_failures: tuple[dict[str, object], ...]


class RuntimeManagerBackend:
    def __init__(
        self,
        *,
        app_status_provider: Callable[[], str],
        actor_id: str,
        task_manager: TaskManager,
        process_manager: ProcessManager,
        connection_registry: ConnectionRegistry,
        window_registry: WindowRegistry,
        action_registry: ActionRegistry,
        audit_log: AuditLog,
    ) -> None:
        self._app_status_provider = app_status_provider
        self._actor_id = actor_id
        self._task_manager = task_manager
        self._process_manager = process_manager
        self._connection_registry = connection_registry
        self._window_registry = window_registry
        self._action_registry = action_registry
        self._audit_log = audit_log

    def snapshot(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            generated_at_utc=datetime.now(UTC),
            app_status=self._app_status_provider(),
            actor_id=self._actor_id,
            tasks=tuple(asdict(item) for item in self._task_manager.snapshots()),
            processes=tuple(asdict(item) for item in self._process_manager.snapshots()),
            connections=tuple(asdict(item) for item in self._connection_registry.connection_states()),
            websocket_channels=tuple(asdict(item) for item in self._connection_registry.websocket_channel_states()),
            windows=tuple(asdict(item) for item in self._window_registry.list_windows()),
            actions=tuple(
                {
                    "action_id": item.action_id,
                    "label": item.label,
                    "window_id": item.window_id,
                    "risk_level": item.risk_level,
                    "confirmation_required": item.confirmation_required,
                }
                for item in self._action_registry.list_actions()
            ),
            recent_events=tuple(event.to_dict() for event in self._audit_log.snapshot()),
            audit_sink_failures=tuple(asdict(item) for item in self._audit_log.sink_failures()),
        )
