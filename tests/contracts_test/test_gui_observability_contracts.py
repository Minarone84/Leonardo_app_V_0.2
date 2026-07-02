from datetime import UTC, datetime

import pytest

from leonardo.contracts.gui import (
    ActionDefinition,
    ActionKind,
    ActionTriggerRecord,
    WindowDefinition,
    WindowLifecycleStatus,
    WindowRuntimeState,
)
from leonardo.contracts.identity import ActorOrigin, Permission


def test_window_definition_and_runtime_state_capture_identity_only() -> None:
    definition = WindowDefinition(
        window_id="runtime-manager",
        title="Runtime Manager",
        window_type="tool",
        required_permissions=(Permission.RUNTIME_VIEW,),
    )
    now = datetime.now(UTC)
    state = WindowRuntimeState(
        window_id=definition.window_id,
        title=definition.title,
        window_type=definition.window_type,
        status=WindowLifecycleStatus.OPEN,
        opened_at_utc=now,
        updated_at_utc=now,
    )

    assert definition.window_id == "runtime-manager"
    assert state.status is WindowLifecycleStatus.OPEN


def test_window_definition_rejects_duplicate_permissions() -> None:
    with pytest.raises(ValueError, match="Duplicate required permission"):
        WindowDefinition(
            window_id="runtime-manager",
            title="Runtime Manager",
            window_type="tool",
            required_permissions=(Permission.RUNTIME_VIEW, Permission.RUNTIME_VIEW),
        )


def test_action_definition_flags_and_trigger_record() -> None:
    definition = ActionDefinition(
        action_id="runtime.refresh",
        label="Refresh",
        kind=ActionKind.BUTTON,
        window_id="runtime-manager",
        is_destructive=False,
        requires_confirmation=False,
        is_placeholder=True,
        required_permissions=(Permission.RUNTIME_VIEW,),
    )
    trigger = ActionTriggerRecord(
        action_id=definition.action_id,
        window_id=definition.window_id,
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        triggered_at_utc=datetime.now(UTC),
        correlation_id="corr-1",
    )

    assert definition.is_placeholder is True
    assert trigger.action_id == "runtime.refresh"
    assert trigger.origin is ActorOrigin.DEVELOPMENT
