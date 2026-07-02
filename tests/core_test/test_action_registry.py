import pytest

from leonardo.contracts.gui import ActionDefinition, ActionKind
from leonardo.contracts.identity import ActorOrigin
from leonardo.core.action_registry import ActionRegistry
from leonardo.core.audit_log import AuditLog
from leonardo.core.state_store import StateStore


def _registry(limit: int = 100) -> tuple[ActionRegistry, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log, recent_action_limit=limit)
    return ActionRegistry(state_store), state_store, audit_log


def _definition() -> ActionDefinition:
    return ActionDefinition(
        action_id="runtime.refresh",
        label="Refresh",
        kind=ActionKind.BUTTON,
        window_id="runtime-manager",
    )


def test_action_registry_rejects_duplicate_action_definitions() -> None:
    registry, _state_store, _audit_log = _registry()
    definition = _definition()

    registry.register_action(definition)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_action(definition)


def test_action_registry_records_trigger_audit_and_recent_state() -> None:
    registry, state_store, audit_log = _registry(limit=1)
    registry.register_action(_definition())

    first = registry.record_trigger(
        "runtime.refresh",
        window_id="runtime-manager",
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        correlation_id="corr-1",
    )
    second = registry.record_trigger("runtime.refresh", correlation_id="corr-2")

    assert first.correlation_id == "corr-1"
    assert state_store.recent_action_triggers() == (second,)
    assert [event.event_type for event in audit_log.snapshot()] == [
        "gui.action.triggered",
        "gui.action.triggered",
    ]
    assert audit_log.snapshot()[0].actor_id == "admin-dev"
