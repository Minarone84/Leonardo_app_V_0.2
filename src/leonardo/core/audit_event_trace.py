"""Read-only trace helpers for Core audit event history.

The helpers in this module expose retained or explicit `AuditEvent` values
through the shared traceability and Object Map report contracts. They read
historical event data only and do not emit audit events, mutate runtime state,
change durable logging policy, or wire Runtime Manager.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from leonardo.contracts.audit import AuditErrorPayload, AuditEvent
from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import ObjectMapProviderDescriptor, ObjectMapSection
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.traceable_object import (
    ObjectInterrogationReport,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.core.audit_log import AuditLog


AUDIT_EVENT_TRACE_PROVIDER_ID = "core.audit_event.trace"
AUDIT_EVENT_TRACE_SECTION_ID = "core.audit_events"
AUDIT_EVENT_TRACE_OWNER_DOMAIN = "core"
AUDIT_EVENT_TRACE_OWNER_COMPONENT = "AuditLog / trace helper"
AUDIT_EVENT_TRACE_HISTORY_KIND = "audit_history"
AUDIT_EVENT_TRACE_DOC = "docs/core_docs/AUDIT_FAMILY_TRACE.md"
AUDIT_EVENT_TRACE_TEST = "tests/core_test/test_audit_family_trace.py"

_TRACE_CONTRACTS = (
    "leonardo.contracts.audit.AuditEvent",
    "leonardo.contracts.audit.AuditErrorPayload",
    "leonardo.contracts.traceable_object.TraceableObjectRef",
    "leonardo.contracts.traceable_object.TraceableObjectSummary",
    "leonardo.contracts.traceable_object.TraceableRelationshipRef",
    "leonardo.contracts.object_map.ObjectMapProviderDescriptor",
    "leonardo.contracts.object_map.ObjectMapSection",
)
_TRACE_DOCS = (
    "docs/contracts_docs/AUDIT_EVENT_CONTRACTS.md",
    "docs/contracts_docs/TRACEABLE_OBJECTS.md",
    "docs/contracts_docs/OBJECT_FAMILY_LEGENDS.md",
    "docs/contracts_docs/OBJECT_RELATIONSHIPS.md",
    "docs/contracts_docs/OBJECT_MAP_PROTOCOL.md",
    AUDIT_EVENT_TRACE_DOC,
)
_TRACE_RELATIONSHIP_TYPES = ("references", "records_audit")
_DIRECT_ID_FIELDS = (
    ("session_id", "session", "SessionManager"),
    ("window_id", "window", "WindowRegistry"),
    ("action_id", "action", "ActionRegistry"),
    ("operation_id", "operation", "OperationRegistry"),
    ("task_id", "task", "TaskManager"),
    ("process_id", "process", "ProcessManager"),
    ("connection_id", "connection", "ConnectionRegistry"),
)
_PAYLOAD_OBJECT_REF_FIELD_PAIRS = (
    ("object_id", "object_kind"),
    ("target_object_id", "target_object_kind"),
)
_MAX_PREVIEW_CHARS = 160


def build_audit_event_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the read-only provider descriptor for audit event trace."""

    return ObjectMapProviderDescriptor(
        provider_id=AUDIT_EVENT_TRACE_PROVIDER_ID,
        provider_name="Core Audit Event Trace",
        owner_domain=AUDIT_EVENT_TRACE_OWNER_DOMAIN,
        owner_component=AUDIT_EVENT_TRACE_OWNER_COMPONENT,
        object_kinds=("audit_event",),
        family_ids=("audit_event",),
        relationship_types=_TRACE_RELATIONSHIP_TYPES,
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=AUDIT_EVENT_TRACE_HISTORY_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(AUDIT_EVENT_TRACE_TEST,),
        metadata={
            "event_source": "explicit AuditEvent values or AuditLog.snapshot()",
            "payload_policy": "keys, counts, and value types only",
            "error_policy": "exception type and short message preview only",
        },
        extra={
            "forbidden_behavior": (
                "audit_emission",
                "runtime_state_mutation",
                "durable_log_policy_change",
                "retention_policy_change",
                "runtime_manager_wiring",
                "object_map_service_registration",
            )
        },
    )


def audit_event_trace_ref_from_event(event: AuditEvent) -> TraceableObjectRef:
    """Build a traceable object reference for one audit event."""

    _validate_audit_event(event)
    return TraceableObjectRef(
        object_id=event.event_id,
        object_kind="audit_event",
        owner_domain=AUDIT_EVENT_TRACE_OWNER_DOMAIN,
        owner_component="AuditLog",
        label=f"{event.category.value}:{event.event_type}",
        metadata={
            "event_id": event.event_id,
            "event_type": event.event_type,
            "category": event.category.value,
            "severity": event.severity.value,
            "timestamp_utc": event.timestamp_utc,
            "correlation_id": event.correlation_id,
        },
    )


def audit_event_trace_summary_from_event(event: AuditEvent) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one audit event."""

    _validate_audit_event(event)
    object_ref = audit_event_trace_ref_from_event(event)
    relationships = audit_event_relationships_from_event(event)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status="recorded",
        runtime_or_persistent=AUDIT_EVENT_TRACE_HISTORY_KIND,
        created_or_registered_at_utc=_datetime_text(event.timestamp_utc),
        updated_at_utc=_datetime_text(event.timestamp_utc),
        display_name=f"{event.category.value}:{event.event_type}",
        metadata=_audit_event_summary_metadata(event),
        relationship_refs=relationships,
        audit_refs=(event.event_id,),
        operation_refs=_optional_ref_tuple(event.operation_id),
        task_refs=_optional_ref_tuple(event.task_id),
        correlation_refs=_optional_ref_tuple(event.correlation_id),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "AuditLog historical event read model",
            "payload_policy": "Raw payload values are not included.",
            "audit_truth_policy": "AuditLog remains historical truth.",
        },
    )


def audit_event_relationships_from_event(
    event: AuditEvent,
) -> tuple[TraceableRelationshipRef, ...]:
    """Build relationship refs from explicit IDs carried by one audit event."""

    _validate_audit_event(event)
    event_ref = audit_event_trace_ref_from_event(event)
    relationships: list[TraceableRelationshipRef] = []
    for field_name, object_kind, owner_component in _DIRECT_ID_FIELDS:
        object_id = getattr(event, field_name)
        relationships.extend(
            _reference_relationship(
                event,
                event_ref,
                object_id=object_id,
                object_kind=object_kind,
                owner_component=owner_component,
                metadata_key=field_name,
                relationship_suffix=object_kind,
            )
        )
    relationships.extend(_payload_object_ref_relationships(event, event_ref))
    return _dedupe_relationships(relationships)


def build_audit_event_trace_section(
    *,
    audit_log: AuditLog | None = None,
    audit_events: Iterable[AuditEvent] | None = None,
) -> ObjectMapSection:
    """Build a read-only Object Map section for audit event history."""

    events, event_errors = _resolve_audit_events(
        audit_log=audit_log,
        audit_events=audit_events,
    )
    summaries: list[TraceableObjectSummary] = []
    errors = list(event_errors)
    for event in events:
        try:
            summaries.append(audit_event_trace_summary_from_event(event))
        except (TypeError, ValueError) as error:
            errors.append(f"Audit event trace skipped for {event!r}: {error}")

    relationships = _relationships_from_summaries(summaries)
    legends, legend_warnings = _audit_event_legends()
    return ObjectMapSection(
        section_id=AUDIT_EVENT_TRACE_SECTION_ID,
        provider_id=AUDIT_EVENT_TRACE_PROVIDER_ID,
        owner_domain=AUDIT_EVENT_TRACE_OWNER_DOMAIN,
        object_kind="audit_event",
        family_id="audit_event",
        title="Core Audit Events",
        summaries=tuple(summaries),
        relationships=relationships,
        legends=legends,
        relationship_definitions=_audit_event_relationship_definitions(),
        warnings=legend_warnings,
        errors=tuple(errors),
        metadata={
            "audit_event_count": len(events),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "event_ids": tuple(event.event_id for event in events),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": (
                "AuditLog.snapshot"
                if audit_log is not None and audit_events is None
                else "explicit_audit_events"
            ),
        },
    )


def interrogate_audit_event_trace(
    event_id: str,
    *,
    audit_log: AuditLog | None = None,
    audit_events: Iterable[AuditEvent] | None = None,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one audit event."""

    _validate_non_empty_string(event_id, "event_id")
    section = build_audit_event_trace_section(
        audit_log=audit_log,
        audit_events=audit_events,
    )
    summary = _find_summary(section.summaries, event_id)
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=event_id,
            object_kind="audit_event",
            owner_domain=AUDIT_EVENT_TRACE_OWNER_DOMAIN,
            owner_component=AUDIT_EVENT_TRACE_OWNER_COMPONENT,
        )
    )
    blockers = () if summary is not None else (f"Audit event not found: {event_id}",)
    relationships = (
        _relationships_for_summary(summary, section.relationships)
        if summary is not None
        else ()
    )
    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=object_family_legend_by_id("audit_event"),
        relationships=relationships,
        permissions=summary.permission_refs if summary is not None else (),
        audit_refs=summary.audit_refs if summary is not None else (),
        runtime_refs=(),
        docs=_TRACE_DOCS,
        tests=(AUDIT_EVENT_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": AUDIT_EVENT_TRACE_PROVIDER_ID,
            "section_id": AUDIT_EVENT_TRACE_SECTION_ID,
            "event_id": event_id,
            "object_kind": "audit_event",
            "read_only": True,
        },
    )


def _audit_event_summary_metadata(event: AuditEvent) -> Mapping[str, object]:
    payload_summary = _payload_summary(event.payload)
    error_summary = _error_summary(event.error)
    return {
        "event_id": event.event_id,
        "schema_version": event.schema_version,
        "timestamp_utc": event.timestamp_utc,
        "severity": event.severity.value,
        "category": event.category.value,
        "event_type": event.event_type,
        "message_preview": _preview_text(event.message),
        "message_truncated": _is_truncated(event.message),
        "actor_id": event.actor_id,
        "session_id": event.session_id,
        "origin": event.origin.value if event.origin is not None else None,
        "window_id": event.window_id,
        "action_id": event.action_id,
        "operation_id": event.operation_id,
        "task_id": event.task_id,
        "process_id": event.process_id,
        "connection_id": event.connection_id,
        "correlation_id": event.correlation_id,
        "payload_keys": payload_summary["keys"],
        "payload_key_count": payload_summary["key_count"],
        "payload_value_types": payload_summary["value_types"],
        "payload_redacted": True,
        "error_exception_type": error_summary["exception_type"],
        "error_message_preview": error_summary["message_preview"],
        "error_message_truncated": error_summary["message_truncated"],
        "error_detail_keys": error_summary["detail_keys"],
        "error_detail_count": error_summary["detail_count"],
        "error_details_redacted": error_summary["details_redacted"],
    }


def _reference_relationship(
    event: AuditEvent,
    event_ref: TraceableObjectRef,
    *,
    object_id: str | None,
    object_kind: str,
    owner_component: str,
    metadata_key: str,
    relationship_suffix: str,
) -> tuple[TraceableRelationshipRef, ...]:
    if object_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=(
                f"{event.event_id}.references_{relationship_suffix}.{object_id}"
            ),
            relationship_type="references",
            source_ref=event_ref,
            target_ref=TraceableObjectRef(
                object_id=object_id,
                object_kind=object_kind,
                owner_domain=_owner_domain_for_kind(object_kind),
                owner_component=owner_component,
                metadata={metadata_key: object_id},
            ),
            direction="outbound",
            lifecycle_status="recorded",
            operation_id=event.operation_id,
            task_id=event.task_id,
            correlation_id=event.correlation_id,
            created_at_utc=_datetime_text(event.timestamp_utc),
            updated_at_utc=_datetime_text(event.timestamp_utc),
            metadata={
                "relationship_semantics": "audit_event_explicit_reference",
                metadata_key: object_id,
                "event_id": event.event_id,
            },
        ),
    )


def _payload_object_ref_relationships(
    event: AuditEvent,
    event_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    for object_id_key, object_kind_key in _PAYLOAD_OBJECT_REF_FIELD_PAIRS:
        object_id = event.payload.get(object_id_key)
        object_kind = event.payload.get(object_kind_key)
        if not isinstance(object_id, str) or not object_id.strip():
            continue
        if not isinstance(object_kind, str) or not object_kind.strip():
            continue
        if object_family_legend_by_id(object_kind) is None:
            continue
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=(
                    f"{event.event_id}.references_payload_{object_kind}."
                    f"{object_id}"
                ),
                relationship_type="references",
                source_ref=event_ref,
                target_ref=TraceableObjectRef(
                    object_id=object_id,
                    object_kind=object_kind,
                    owner_domain=_owner_domain_for_kind(object_kind),
                    owner_component="payload explicit object reference",
                    metadata={
                        "object_id_key": object_id_key,
                        "object_kind_key": object_kind_key,
                    },
                ),
                direction="outbound",
                lifecycle_status="recorded",
                operation_id=event.operation_id,
                task_id=event.task_id,
                correlation_id=event.correlation_id,
                created_at_utc=_datetime_text(event.timestamp_utc),
                updated_at_utc=_datetime_text(event.timestamp_utc),
                metadata={
                    "relationship_semantics": "audit_payload_explicit_object_ref",
                    "event_id": event.event_id,
                    "payload_object_id_key": object_id_key,
                    "payload_object_kind_key": object_kind_key,
                },
            )
        )
    return tuple(relationships)


def _resolve_audit_events(
    *,
    audit_log: AuditLog | None,
    audit_events: Iterable[AuditEvent] | None,
) -> tuple[tuple[AuditEvent, ...], tuple[str, ...]]:
    if audit_events is not None:
        return _checked_audit_events(audit_events)
    if audit_log is not None:
        if not isinstance(audit_log, AuditLog):
            return (), ("audit_log must be an AuditLog",)
        return _checked_audit_events(audit_log.snapshot())
    return (), ()


def _checked_audit_events(
    values: Iterable[AuditEvent],
) -> tuple[tuple[AuditEvent, ...], tuple[str, ...]]:
    events: list[AuditEvent] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, AuditEvent):
            errors.append("audit_events entries must be AuditEvent")
            continue
        events.append(value)
    return tuple(events), tuple(errors)


def _relationships_from_summaries(
    summaries: Iterable[TraceableObjectSummary],
) -> tuple[TraceableRelationshipRef, ...]:
    return _dedupe_relationships(
        relationship
        for summary in summaries
        for relationship in summary.relationship_refs
    )


def _relationships_for_summary(
    summary: TraceableObjectSummary,
    relationships: Iterable[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    event_id = summary.object_ref.object_id
    return tuple(
        relationship
        for relationship in relationships
        if relationship.source_ref.object_id == event_id
        or relationship.target_ref.object_id == event_id
    )


def _audit_event_legends() -> tuple[tuple[object, ...], tuple[str, ...]]:
    legend = object_family_legend_by_id("audit_event")
    if legend is None:
        return (), ("Missing object family legend for audit_event",)
    return (legend,), ()


def _audit_event_relationship_definitions() -> tuple[object, ...]:
    definitions: list[object] = []
    for relationship_type in _TRACE_RELATIONSHIP_TYPES:
        definitions.extend(object_relationship_definitions_by_type(relationship_type))
    return tuple(definitions)


def _dedupe_relationships(
    relationships: Iterable[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    records: dict[str, TraceableRelationshipRef] = {}
    for relationship in relationships:
        relationship_id = relationship.relationship_id or (
            f"{relationship.source_ref.object_id}."
            f"{relationship.relationship_type}."
            f"{relationship.target_ref.object_id}"
        )
        records.setdefault(relationship_id, relationship)
    return tuple(records[key] for key in sorted(records))


def _find_summary(
    summaries: tuple[TraceableObjectSummary, ...],
    event_id: str,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        if summary.object_ref.object_id == event_id:
            return summary
        if summary.metadata.get("event_id") == event_id:
            return summary
    return None


def _payload_summary(payload: Mapping[str, object]) -> Mapping[str, object]:
    keys = tuple(sorted(payload))
    return {
        "keys": keys,
        "key_count": len(keys),
        "value_types": {
            key: _json_type_name(payload[key])
            for key in keys
        },
    }


def _error_summary(error: AuditErrorPayload | None) -> Mapping[str, object]:
    if error is None:
        return {
            "exception_type": None,
            "message_preview": None,
            "message_truncated": False,
            "detail_keys": (),
            "detail_count": 0,
            "details_redacted": False,
        }
    detail_keys = tuple(sorted(error.details))
    return {
        "exception_type": error.exception_type,
        "message_preview": _preview_optional_text(error.message),
        "message_truncated": _is_truncated(error.message or ""),
        "detail_keys": detail_keys,
        "detail_count": len(detail_keys),
        "details_redacted": bool(detail_keys),
    }


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, tuple | list):
        return "list"
    return type(value).__name__


def _preview_text(value: str) -> str:
    if len(value) <= _MAX_PREVIEW_CHARS:
        return value
    return f"{value[:_MAX_PREVIEW_CHARS]}..."


def _preview_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _preview_text(value)


def _is_truncated(value: str) -> bool:
    return len(value) > _MAX_PREVIEW_CHARS


def _owner_domain_for_kind(object_kind: str) -> str:
    if object_kind in {"connection", "websocket_channel"}:
        return "core.connection"
    if object_kind in {"window"}:
        return "gui"
    if object_kind in {"action"}:
        return "gui.core"
    return AUDIT_EVENT_TRACE_OWNER_DOMAIN


def _optional_ref_tuple(value: str | None) -> tuple[str, ...]:
    return (value,) if value is not None else ()


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_audit_event(value: AuditEvent) -> None:
    if not isinstance(value, AuditEvent):
        raise TypeError("event must be an AuditEvent")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "AUDIT_EVENT_TRACE_HISTORY_KIND",
    "AUDIT_EVENT_TRACE_OWNER_COMPONENT",
    "AUDIT_EVENT_TRACE_OWNER_DOMAIN",
    "AUDIT_EVENT_TRACE_PROVIDER_ID",
    "AUDIT_EVENT_TRACE_SECTION_ID",
    "audit_event_relationships_from_event",
    "audit_event_trace_ref_from_event",
    "audit_event_trace_summary_from_event",
    "build_audit_event_trace_provider_descriptor",
    "build_audit_event_trace_section",
    "interrogate_audit_event_trace",
]
