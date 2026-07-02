from datetime import UTC, datetime

import pytest

from leonardo.contracts.audit import (
    AuditCategory,
    AuditErrorPayload,
    AuditEvent,
    AuditSeverity,
)
from leonardo.contracts.connections import (
    ConnectionDirection,
    ConnectionKind,
    ConnectionLifecycleStatus,
    ConnectionProtocol,
    ConnectionRuntimeState,
    WebSocketChannelRuntimeState,
)
from leonardo.contracts.errors import ErrorReport, ErrorSeverity
from leonardo.contracts.identity import (
    ActorOrigin,
    Permission,
    SessionContext,
    UserRef,
    UserRole,
)
from leonardo.contracts.runtime import (
    AppLifecycleStatus,
    AppRuntimeState,
    RuntimeSnapshot,
    ServiceLifecycleStatus,
    ServiceRuntimeState,
)
from leonardo.contracts.services import ServiceDescriptor, ServiceKind


def test_user_ref_and_session_context_model_development_administrator() -> None:
    user = UserRef(
        user_id="admin-dev",
        username="Administrator",
        first_name="Administrator",
        roles=(UserRole.ADMINISTRATOR,),
        permissions=(Permission.RUNTIME_MANAGE,),
    )
    session = SessionContext(
        session_id="session-admin-dev",
        actor=user,
        origin=ActorOrigin.DEVELOPMENT,
        started_at_utc=datetime.now(UTC),
    )

    assert session.actor_id == "admin-dev"
    assert session.actor.display_name == "Administrator"
    assert session.origin is ActorOrigin.DEVELOPMENT


def test_audit_event_normalizes_json_safe_payload() -> None:
    event = AuditEvent(
        event_type="runtime.test",
        message="Runtime test event",
        severity=AuditSeverity.INFO,
        category=AuditCategory.RUNTIME,
        payload={
            "status": AppLifecycleStatus.RUNNING,
            "items": ["a", "b"],
        },
        error=AuditErrorPayload(message="none"),
    )

    assert event.payload["status"] == "running"
    assert event.payload["items"] == ("a", "b")
    assert event.error is not None


def test_audit_event_rejects_unsupported_payload_values() -> None:
    with pytest.raises(TypeError, match="Unsupported JSON payload"):
        AuditEvent(
            event_type="runtime.test",
            message="Runtime test event",
            severity=AuditSeverity.INFO,
            category=AuditCategory.RUNTIME,
            payload={"bad": object()},
        )


def test_runtime_snapshot_contains_current_app_and_service_state() -> None:
    app_state = AppRuntimeState(status=AppLifecycleStatus.RUNNING)
    service_state = ServiceRuntimeState(
        service_id="audit-log",
        status=ServiceLifecycleStatus.RUNNING,
    )
    now = datetime.now(UTC)
    connection_state = ConnectionRuntimeState(
        connection_id="connection-1",
        label="Runtime feed",
        kind=ConnectionKind.EXTERNAL_SERVICE,
        protocol=ConnectionProtocol.WEBSOCKET,
        direction=ConnectionDirection.OUTBOUND,
        status=ConnectionLifecycleStatus.CONNECTED,
        registered_at_utc=now,
        updated_at_utc=now,
    )
    channel_state = WebSocketChannelRuntimeState(
        channel_id="channel-1",
        connection_id="connection-1",
        label="Runtime channel",
        status=ConnectionLifecycleStatus.CONNECTED,
        registered_at_utc=now,
        updated_at_utc=now,
    )
    snapshot = RuntimeSnapshot(
        app_state=app_state,
        service_states=(service_state,),
        connection_states=(connection_state,),
        websocket_channel_states=(channel_state,),
    )

    assert snapshot.app_state.status is AppLifecycleStatus.RUNNING
    assert snapshot.service_states == (service_state,)
    assert snapshot.connection_states == (connection_state,)
    assert snapshot.websocket_channel_states == (channel_state,)


def test_service_descriptor_rejects_duplicate_dependencies() -> None:
    with pytest.raises(ValueError, match="Duplicate dependency"):
        ServiceDescriptor(
            service_id="runtime",
            kind=ServiceKind.LIFECYCLE,
            dependencies=("audit", "audit"),
        )


def test_error_report_keeps_structured_context() -> None:
    report = ErrorReport(
        message="Failure",
        severity=ErrorSeverity.ERROR,
        context={"component": "runtime"},
    )

    assert report.context["component"] == "runtime"
