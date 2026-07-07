from datetime import UTC, datetime
from pathlib import Path

from leonardo.contracts.audit import (
    AuditCategory,
    AuditErrorPayload,
    AuditEvent,
    AuditSeverity,
)
from leonardo.contracts.identity import ActorOrigin
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.core.audit_event_trace import (
    AUDIT_EVENT_TRACE_HISTORY_KIND,
    AUDIT_EVENT_TRACE_PROVIDER_ID,
    audit_event_relationships_from_event,
    audit_event_trace_ref_from_event,
    audit_event_trace_summary_from_event,
    build_audit_event_trace_provider_descriptor,
    build_audit_event_trace_section,
    interrogate_audit_event_trace,
)
from leonardo.core.audit_log import AuditLog


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "audit_event_trace.py"
_RUNTIME_MANAGER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "runtime_manager.py"


def test_audit_event_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_audit_event_trace_provider_descriptor()

    assert descriptor.provider_id == AUDIT_EVENT_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.owner_component == "AuditLog / trace helper"
    assert descriptor.object_kinds == ("audit_event",)
    assert descriptor.family_ids == ("audit_event",)
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "references" in descriptor.relationship_types
    assert "records_audit" in descriptor.relationship_types
    assert descriptor.metadata["event_source"] == (
        "explicit AuditEvent values or AuditLog.snapshot()"
    )


def test_audit_event_ref_uses_stable_event_identity() -> None:
    event = _audit_event()

    ref = audit_event_trace_ref_from_event(event)

    assert ref.object_id == "event-1"
    assert ref.object_kind == "audit_event"
    assert ref.owner_domain == "core"
    assert ref.owner_component == "AuditLog"
    assert ref.label == "runtime:runtime.operation.failed"
    assert ref.metadata["event_id"] == "event-1"
    assert ref.metadata["severity"] == "error"


def test_audit_event_summary_uses_safe_metadata_without_raw_payload() -> None:
    event = _audit_event()

    summary = audit_event_trace_summary_from_event(event)

    assert isinstance(summary, TraceableObjectSummary)
    assert summary.object_ref.object_id == "event-1"
    assert summary.object_ref.object_kind == "audit_event"
    assert summary.lifecycle_status == "recorded"
    assert summary.runtime_or_persistent == AUDIT_EVENT_TRACE_HISTORY_KIND
    assert summary.created_or_registered_at_utc == "2026-01-01T00:00:00+00:00"
    assert summary.metadata["event_id"] == "event-1"
    assert summary.metadata["timestamp_utc"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert summary.metadata["category"] == "runtime"
    assert summary.metadata["event_type"] == "runtime.operation.failed"
    assert summary.metadata["severity"] == "error"
    assert summary.metadata["actor_id"] == "admin-dev"
    assert summary.metadata["session_id"] == "session-1"
    assert summary.metadata["window_id"] == "window-1"
    assert summary.metadata["action_id"] == "action-1"
    assert summary.metadata["operation_id"] == "operation-1"
    assert summary.metadata["task_id"] == "task-1"
    assert summary.metadata["process_id"] == "process-1"
    assert summary.metadata["connection_id"] == "connection-1"
    assert summary.metadata["correlation_id"] == "corr-1"
    assert summary.operation_refs == ("operation-1",)
    assert summary.task_refs == ("task-1",)
    assert summary.correlation_refs == ("corr-1",)
    assert summary.audit_refs == ("event-1",)
    assert summary.metadata["payload_key_count"] == 7
    assert summary.metadata["payload_value_types"]["secret_token"] == "str"
    assert summary.metadata["payload_value_types"]["nested"] == "mapping"
    assert summary.metadata["payload_value_types"]["items"] == "list"
    assert summary.metadata["payload_redacted"] is True
    assert "payload" not in summary.metadata
    assert "super-secret-value" not in str(summary.metadata)
    assert "oversized-" not in str(summary.metadata)


def test_audit_event_summary_uses_small_error_preview_without_details_dump() -> None:
    event = _audit_event()

    summary = audit_event_trace_summary_from_event(event)

    assert summary.metadata["error_exception_type"] == "RuntimeError"
    assert summary.metadata["error_message_preview"].startswith("Failure ")
    assert summary.metadata["error_message_truncated"] is True
    assert len(summary.metadata["error_message_preview"]) < 170
    assert summary.metadata["error_detail_keys"] == ("secret", "stage")
    assert summary.metadata["error_detail_count"] == 2
    assert summary.metadata["error_details_redacted"] is True
    assert "secret-detail-value" not in str(summary.metadata)


def test_audit_event_relationships_use_only_explicit_ids() -> None:
    event = _audit_event()

    relationships = audit_event_relationships_from_event(event)
    relationship_ids = {relationship.relationship_id for relationship in relationships}
    targets = {
        relationship.target_ref.object_kind: relationship.target_ref.object_id
        for relationship in relationships
    }

    assert "event-1.references_session.session-1" in relationship_ids
    assert "event-1.references_window.window-1" in relationship_ids
    assert "event-1.references_action.action-1" in relationship_ids
    assert "event-1.references_operation.operation-1" in relationship_ids
    assert "event-1.references_task.task-1" in relationship_ids
    assert "event-1.references_process.process-1" in relationship_ids
    assert "event-1.references_connection.connection-1" in relationship_ids
    assert "event-1.references_payload_service.service-1" in relationship_ids
    assert targets["operation"] == "operation-1"
    assert targets["task"] == "task-1"
    assert targets["process"] == "process-1"
    assert targets["connection"] == "connection-1"
    assert targets["service"] == "service-1"


def test_missing_optional_ids_do_not_create_fake_relationships() -> None:
    event = AuditEvent(
        event_id="event-without-refs",
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        event_type="runtime.notice",
        message="Runtime notice",
        severity=AuditSeverity.INFO,
        category=AuditCategory.RUNTIME,
        payload={"object_id": "unknown-1", "object_kind": "unknown_family"},
    )

    summary = audit_event_trace_summary_from_event(event)

    assert summary.relationship_refs == ()
    assert summary.operation_refs == ()
    assert summary.task_refs == ()
    assert summary.correlation_refs == ()


def test_audit_section_reads_explicit_events_or_audit_log_snapshot() -> None:
    explicit_event = _audit_event(event_id="event-explicit")
    audit_log = AuditLog()
    audit_event = _audit_event(event_id="event-from-log")
    audit_log.emit(audit_event)

    explicit_section = build_audit_event_trace_section(
        audit_events=(explicit_event,)
    )
    audit_log_section = build_audit_event_trace_section(audit_log=audit_log)

    assert isinstance(explicit_section, ObjectMapSection)
    assert explicit_section.provider_id == AUDIT_EVENT_TRACE_PROVIDER_ID
    assert explicit_section.metadata["event_ids"] == ("event-explicit",)
    assert explicit_section.extra["source"] == "explicit_audit_events"
    assert audit_log_section.metadata["event_ids"] == ("event-from-log",)
    assert audit_log_section.extra["source"] == "AuditLog.snapshot"
    assert audit_log.snapshot() == (audit_event,)


def test_audit_section_includes_family_legend_and_relationship_definitions() -> None:
    section = build_audit_event_trace_section(audit_events=(_audit_event(),))
    family_ids = {legend.family_id for legend in section.legends}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert section.section_id == "core.audit_events"
    assert section.object_kind == "audit_event"
    assert section.family_id == "audit_event"
    assert family_ids == {"audit_event"}
    assert "references" in relationship_types
    assert "records_audit" in relationship_types
    assert section.metadata["audit_event_count"] == 1
    assert section.metadata["summary_count"] == 1
    assert section.errors == ()


def test_interrogate_audit_event_trace_returns_read_only_report() -> None:
    event = _audit_event()

    report = interrogate_audit_event_trace(
        "event-1",
        audit_events=(event,),
    )

    assert report.target_ref.object_id == "event-1"
    assert report.target_ref.object_kind == "audit_event"
    assert report.summary is not None
    assert report.family_legend is not None
    assert report.family_legend.family_id == "audit_event"
    assert report.audit_refs == ("event-1",)
    assert report.metadata["read_only"] is True
    assert report.blockers == ()
    assert any(
        relationship.target_ref.object_id == "operation-1"
        for relationship in report.relationships
    )


def test_interrogate_missing_audit_event_reports_blocker() -> None:
    report = interrogate_audit_event_trace("missing-event")

    assert report.summary is None
    assert report.target_ref.object_id == "missing-event"
    assert report.target_ref.object_kind == "audit_event"
    assert report.blockers == ("Audit event not found: missing-event",)
    assert report.errors == ()


def test_audit_trace_helpers_do_not_mutate_audit_log() -> None:
    audit_log = AuditLog()
    event = _audit_event()
    audit_log.emit(event)
    before = audit_log.snapshot()

    build_audit_event_trace_section(audit_log=audit_log)
    interrogate_audit_event_trace("event-1", audit_log=audit_log)
    after = audit_log.snapshot()

    assert after == before


def test_malformed_explicit_events_are_reported_without_mutation() -> None:
    section = build_audit_event_trace_section(audit_events=(object(),))

    assert section.summaries == ()
    assert "audit_events entries must be AuditEvent" in section.errors


def test_audit_event_trace_has_no_runtime_mutation_or_domain_wiring() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo.core.state_store",
        "from leonardo.core.task_manager",
        "from leonardo.core.operation_registry",
        "from leonardo.core.process_manager",
        "from leonardo.core.connection_registry",
        "RuntimeManagerBackend",
        "RuntimeManagerWindow",
        "class ObjectMapService",
        "class ObjectMapRegistry",
        "register_provider",
        "def discover",
        ".discover",
        "submit_command",
        ".emit(",
        "JsonlAuditSink",
        "CompositeAuditSink",
        "InMemoryAuditSink",
        "open(",
        "write(",
        "mkdir",
        "DownloadManager",
        "DownloadExecutionManager",
        "DownloadRequestBuilderWindow",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QApplication",
        "socket.",
        "requests",
        "aio" + "http",
        "web" + "sockets",
        "sub" + "process",
        "shell" + "=True",
    )

    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_remains_unwired_from_audit_event_trace() -> None:
    source = _RUNTIME_MANAGER_SOURCE.read_text(encoding="utf-8")

    assert "audit_event_trace" not in source
    assert "build_audit_event_trace_section" not in source
    assert "AUDIT_EVENT_TRACE_PROVIDER_ID" not in source


def _audit_event(event_id: str = "event-1") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        event_type="runtime.operation.failed",
        message="Runtime operation failed",
        severity=AuditSeverity.ERROR,
        category=AuditCategory.RUNTIME,
        actor_id="admin-dev",
        session_id="session-1",
        origin=ActorOrigin.DEVELOPMENT,
        window_id="window-1",
        action_id="action-1",
        operation_id="operation-1",
        task_id="task-1",
        process_id="process-1",
        connection_id="connection-1",
        correlation_id="corr-1",
        payload={
            "object_id": "service-1",
            "object_kind": "service",
            "secret_token": "super-secret-value",
            "large_blob": "oversized-" * 100,
            "nested": {"secret": "nested-secret"},
            "items": ("a", "b"),
            "status": "failed",
        },
        error=AuditErrorPayload(
            exception_type="RuntimeError",
            message="Failure " * 40,
            details={
                "stage": "runtime",
                "secret": "secret-detail-value",
            },
        ),
    )
