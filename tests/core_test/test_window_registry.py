import pytest

from leonardo.contracts.gui import WindowDefinition, WindowLifecycleStatus
from leonardo.core.audit_log import AuditLog
from leonardo.core.state_store import StateStore
from leonardo.core.window_registry import WindowRegistry


def _registry() -> tuple[WindowRegistry, StateStore, AuditLog]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    return WindowRegistry(state_store), state_store, audit_log


def _definition() -> WindowDefinition:
    return WindowDefinition(
        window_id="runtime-manager",
        title="Runtime Manager",
        window_type="tool",
    )


def test_window_registry_rejects_duplicate_window_definitions() -> None:
    registry, _state_store, _audit_log = _registry()
    definition = _definition()

    registry.register_window(definition)

    with pytest.raises(ValueError, match="already registered"):
        registry.register_window(definition)


def test_window_registry_records_open_focus_and_closed_state() -> None:
    registry, state_store, audit_log = _registry()
    registry.register_window(_definition())

    opened = registry.open_window("runtime-manager", owner_action_id="runtime.open")
    focused = registry.focus_window("runtime-manager")
    requested = registry.request_window_close("runtime-manager")
    closed = registry.close_window("runtime-manager")

    assert opened.status is WindowLifecycleStatus.OPEN
    assert focused.status is WindowLifecycleStatus.FOCUSED
    assert requested.status is WindowLifecycleStatus.CLOSE_REQUESTED
    assert closed.status is WindowLifecycleStatus.CLOSED
    assert state_store.windows_state() == ()
    assert state_store.runtime_snapshot().window_states == ()
    assert [event.event_type for event in audit_log.snapshot()] == [
        "gui.window.opened",
        "gui.window.focused",
        "gui.window.close_requested",
        "gui.window.closed",
    ]
