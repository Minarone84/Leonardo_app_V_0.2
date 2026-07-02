from datetime import UTC, datetime

from leonardo.contracts.audit import (
    AuditCategory,
    AuditErrorPayload,
    AuditEvent,
    AuditSeverity,
)
from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.runtime import AppLifecycleStatus


def test_audit_event_to_dict_from_dict_round_trip_preserves_fields() -> None:
    event = AuditEvent(
        event_id="event-1",
        schema_version="1.0",
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        severity=AuditSeverity.ERROR,
        category=AuditCategory.ERROR,
        event_type="runtime.error",
        message="Runtime error",
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        window_id="window-1",
        action_id="action-1",
        operation_id="operation-1",
        task_id="task-1",
        process_id="process-1",
        connection_id="connection-1",
        correlation_id="correlation-1",
        payload={
            "status": AppLifecycleStatus.FAILED,
            "nested": {"unknown_key": "kept"},
            "items": ("a", "b"),
        },
        error=AuditErrorPayload(
            exception_type="RuntimeError",
            message="Failure",
            details={"detail_key": "detail"},
        ),
    )

    serialized = event.to_dict()
    loaded = AuditEvent.from_dict(serialized)

    assert loaded.to_dict() == serialized
    assert loaded.origin is ActorOrigin.DEVELOPMENT
    assert loaded.payload["nested"]["unknown_key"] == "kept"
    assert loaded.error is not None
    assert loaded.error.details["detail_key"] == "detail"


def test_audit_event_serialization_normalizes_json_safe_payload_values() -> None:
    event = AuditEvent(
        event_type="runtime.state",
        message="Runtime state changed",
        severity=AuditSeverity.INFO,
        category=AuditCategory.RUNTIME,
        payload={
            "status": AppLifecycleStatus.RUNNING,
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
            "items": ["a", "b"],
        },
    )

    serialized = event.to_dict()

    assert serialized["payload"]["status"] == "running"
    assert serialized["payload"]["timestamp"] == "2026-01-01T00:00:00+00:00"
    assert serialized["payload"]["items"] == ["a", "b"]
