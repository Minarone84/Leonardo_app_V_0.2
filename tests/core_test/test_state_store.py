import pytest

from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.runtime import AppLifecycleStatus, ServiceLifecycleStatus
from leonardo.core.audit_log import AuditLog
from leonardo.core.state_store import StateStore


def test_state_store_tracks_app_transitions_and_audits_changes() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)

    state_store.set_app_lifecycle_status(AppLifecycleStatus.STARTING)
    state_store.set_app_lifecycle_status(AppLifecycleStatus.RUNNING)

    assert state_store.get_app_status() is AppLifecycleStatus.RUNNING
    assert state_store.get_app_state().started_at_utc is not None
    assert [event.category for event in audit_log.snapshot()] == [
        AuditCategory.STATE,
        AuditCategory.STATE,
    ]


def test_state_store_tracks_service_state_and_snapshot_is_defensive() -> None:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)

    state_store.register_service_runtime_state("audit-log")
    state_store.set_service_lifecycle_status(
        "audit-log",
        ServiceLifecycleStatus.RUNNING,
    )
    snapshot = state_store.runtime_snapshot()

    assert snapshot.service_states[0].service_id == "audit-log"
    assert snapshot.service_states[0].status is ServiceLifecycleStatus.RUNNING
    assert isinstance(snapshot.service_states, tuple)


def test_state_store_rejects_unknown_service_transition() -> None:
    state_store = StateStore(AuditLog())

    with pytest.raises(KeyError, match="not registered"):
        state_store.set_service_lifecycle_status(
            "missing",
            ServiceLifecycleStatus.RUNNING,
        )
