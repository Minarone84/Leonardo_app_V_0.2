"""Application-wide discoverable action registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock

from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import AuditLog


@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    label: str
    handler: Callable[..., object] | None = None
    window_id: str | None = None
    risk_level: str = "normal"
    confirmation_required: bool = False
    audit_enabled: bool = True
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not self.action_id.strip():
            raise ValueError("action_id must be a non-empty string")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be a non-empty string")
        if self.handler is not None and not callable(self.handler):
            raise TypeError("handler must be callable or None")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ActionTrigger:
    action_id: str
    triggered_at_utc: datetime
    actor_id: str
    window_id: str | None
    correlation_id: str | None
    metadata: dict[str, object]


class ActionRegistry:
    def __init__(self, audit_log: AuditLog, *, actor_id: str = "local-user") -> None:
        if not isinstance(audit_log, AuditLog):
            raise TypeError("audit_log must be an AuditLog")
        self._audit_log = audit_log
        self._actor_id = actor_id
        self._definitions: dict[str, ActionDefinition] = {}
        self._triggers: list[ActionTrigger] = []
        self._lock = RLock()

    def register_action(
        self,
        definition: ActionDefinition | None = None,
        *,
        action_id: str | None = None,
        label: str | None = None,
        handler: Callable[..., object] | None = None,
        window_id: str | None = None,
        risk_level: str = "normal",
        confirmation_required: bool = False,
        audit_enabled: bool = True,
        metadata: dict[str, object] | None = None,
    ) -> ActionDefinition:
        resolved = definition or ActionDefinition(
            action_id=action_id or "",
            label=label or action_id or "",
            handler=handler,
            window_id=window_id,
            risk_level=risk_level,
            confirmation_required=confirmation_required,
            audit_enabled=audit_enabled,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            existing = self._definitions.get(resolved.action_id)
            if existing is not None:
                if existing == resolved:
                    return existing
                raise ValueError(f"Action already registered: {resolved.action_id}")
            self._definitions[resolved.action_id] = resolved
        return resolved

    def get_action_definition(self, action_id: str) -> ActionDefinition | None:
        with self._lock:
            return self._definitions.get(action_id)

    def list_actions(self) -> tuple[ActionDefinition, ...]:
        with self._lock:
            return tuple(self._definitions[key] for key in sorted(self._definitions))

    def record_trigger(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        actor_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ActionTrigger:
        definition = self._require(action_id)
        record = ActionTrigger(
            action_id=action_id,
            triggered_at_utc=datetime.now(UTC),
            actor_id=actor_id or self._actor_id,
            window_id=window_id or definition.window_id,
            correlation_id=correlation_id,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._triggers.append(record)
            if len(self._triggers) > 500:
                del self._triggers[:-500]
        if definition.audit_enabled:
            self._audit_log.emit(
                AuditEventV1(
                    event_type="action.triggered",
                    category="action",
                    message=f"Action triggered: {definition.label}",
                    actor_id=record.actor_id,
                    action_id=action_id,
                    window_id=record.window_id,
                    correlation_id=correlation_id,
                    details=record.metadata,
                )
            )
        return record

    def invoke(
        self,
        action_id: str,
        *args: object,
        actor_id: str | None = None,
        window_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, object] | None = None,
        **kwargs: object,
    ) -> object:
        definition = self._require(action_id)
        self.record_trigger(
            action_id,
            actor_id=actor_id,
            window_id=window_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
        if definition.handler is None:
            return None
        return definition.handler(*args, **kwargs)

    def recent_triggers(self) -> tuple[ActionTrigger, ...]:
        with self._lock:
            return tuple(self._triggers)

    def _require(self, action_id: str) -> ActionDefinition:
        with self._lock:
            definition = self._definitions.get(action_id)
        if definition is None:
            raise KeyError(f"Action is not registered: {action_id}")
        return definition
