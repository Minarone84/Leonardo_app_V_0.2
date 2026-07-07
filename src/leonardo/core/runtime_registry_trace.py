"""Read-only trace helpers for Core runtime registry families.

The helpers in this module expose existing Core runtime, session, service,
contract, and explicit error-report read models through the shared traceability
and Object Map report contracts. They do not register Object Map providers,
wire Runtime Manager, mutate runtime state, start or stop services, route
errors, emit audit events, or call domain services.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

from leonardo.contracts.errors import ErrorReport
from leonardo.contracts.identity import Permission, SessionContext, UserRole
from leonardo.contracts.kernel import ContractDescriptor
from leonardo.contracts.object_family_legends import object_family_legend_by_id
from leonardo.contracts.object_map import ObjectMapProviderDescriptor, ObjectMapSection
from leonardo.contracts.object_relationships import (
    object_relationship_definitions_by_type,
)
from leonardo.contracts.runtime import (
    AppRuntimeState,
    RuntimeSnapshot,
    ServiceRuntimeState,
)
from leonardo.contracts.services import ServiceKind
from leonardo.contracts.traceable_object import (
    ObjectInterrogationReport,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.core.contract_registry import ContractRegistry
from leonardo.core.service_registry import RegisteredService, ServiceRegistry
from leonardo.core.session_manager import SessionManager
from leonardo.core.state_store import StateStore


RUNTIME_REGISTRY_TRACE_PROVIDER_ID = "core.runtime_registry.trace"
RUNTIME_REGISTRY_TRACE_SECTION_ID = "core.runtime_registry"
RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN = "core"
RUNTIME_REGISTRY_TRACE_OWNER_COMPONENT = (
    "StateStore / SessionManager / ServiceRegistry / ContractRegistry / "
    "ErrorRouter trace helper"
)
RUNTIME_REGISTRY_TRACE_RUNTIME_KIND = "runtime"
RUNTIME_REGISTRY_TRACE_DOC = (
    "docs/core_docs/RUNTIME_REGISTRY_FAMILY_TRACE.md"
)
RUNTIME_REGISTRY_TRACE_TEST = (
    "tests/core_test/test_runtime_registry_family_trace.py"
)

APP_RUNTIME_OBJECT_ID = "leonardo.app_runtime"
_ERROR_REPORT_WARNING = (
    "ErrorRouter exposes no retained public report listing; error_report "
    "summaries require explicit ErrorReport values."
)

_TRACE_FAMILY_IDS = (
    "app_runtime",
    "session",
    "service",
    "contract_descriptor",
    "error_report",
)
_TRACE_RELATIONSHIP_TYPES = (
    "references",
    "depends_on",
    "described_by_contract",
    "has_permission",
    "records_audit",
)
_TRACE_CONTRACTS = (
    "leonardo.contracts.runtime.AppRuntimeState",
    "leonardo.contracts.runtime.ServiceRuntimeState",
    "leonardo.contracts.identity.SessionContext",
    "leonardo.contracts.services.ServiceDescriptor",
    "leonardo.contracts.kernel.ContractDescriptor",
    "leonardo.contracts.errors.ErrorReport",
    "leonardo.contracts.traceable_object.TraceableObjectRef",
    "leonardo.contracts.traceable_object.TraceableObjectSummary",
    "leonardo.contracts.traceable_object.TraceableRelationshipRef",
    "leonardo.contracts.object_map.ObjectMapProviderDescriptor",
    "leonardo.contracts.object_map.ObjectMapSection",
)
_TRACE_DOCS = (
    "docs/contracts_docs/TRACEABLE_OBJECTS.md",
    "docs/contracts_docs/OBJECT_FAMILY_LEGENDS.md",
    "docs/contracts_docs/OBJECT_RELATIONSHIPS.md",
    "docs/contracts_docs/OBJECT_MAP_PROTOCOL.md",
    RUNTIME_REGISTRY_TRACE_DOC,
)


def build_runtime_registry_trace_provider_descriptor() -> ObjectMapProviderDescriptor:
    """Return the read-only Object Map provider descriptor for Core registry families."""

    return ObjectMapProviderDescriptor(
        provider_id=RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
        provider_name="Core Runtime Registry Trace",
        owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
        owner_component=RUNTIME_REGISTRY_TRACE_OWNER_COMPONENT,
        object_kinds=_TRACE_FAMILY_IDS,
        family_ids=_TRACE_FAMILY_IDS,
        relationship_types=_TRACE_RELATIONSHIP_TYPES,
        supports_summary_listing=True,
        supports_interrogation=True,
        supports_relationship_listing=True,
        runtime_or_persistent=RUNTIME_REGISTRY_TRACE_RUNTIME_KIND,
        read_only=True,
        mutation_forbidden=True,
        related_contracts=_TRACE_CONTRACTS,
        related_docs=_TRACE_DOCS,
        related_tests=(RUNTIME_REGISTRY_TRACE_TEST,),
        metadata={
            "app_runtime_source": "StateStore.runtime_snapshot().app_state",
            "session_source": "SessionManager.current_session",
            "service_source": "ServiceRegistry.list_services()",
            "contract_source": "ContractRegistry.list_contracts()",
            "error_report_source": "explicit ErrorReport values only",
        },
        extra={
            "forbidden_behavior": (
                "runtime_state_mutation",
                "service_lifecycle_changes",
                "session_mutation",
                "contract_registration",
                "error_routing",
                "audit_emission",
                "runtime_manager_wiring",
                "object_map_service_registration",
            ),
            "error_report_retention_policy": _ERROR_REPORT_WARNING,
        },
    )


def app_runtime_trace_ref_from_snapshot(
    snapshot_or_state: RuntimeSnapshot | AppRuntimeState,
) -> TraceableObjectRef:
    """Build a traceable object reference for the Core application runtime."""

    app_state = _app_state_from_snapshot_or_state(snapshot_or_state)
    return TraceableObjectRef(
        object_id=APP_RUNTIME_OBJECT_ID,
        object_kind="app_runtime",
        owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
        owner_component="LeonardoApp / StateStore",
        label="Leonardo application runtime",
        metadata={
            "app_id": APP_RUNTIME_OBJECT_ID,
            "status": app_state.status.value,
        },
    )


def app_runtime_trace_summary_from_snapshot(
    snapshot_or_state: RuntimeSnapshot | AppRuntimeState,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for the Core application runtime."""

    app_state = _app_state_from_snapshot_or_state(snapshot_or_state)
    object_ref = app_runtime_trace_ref_from_snapshot(app_state)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=app_state.status.value,
        runtime_or_persistent=RUNTIME_REGISTRY_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(app_state.started_at_utc),
        updated_at_utc=_datetime_text(app_state.last_updated_utc),
        display_name="Leonardo application runtime",
        metadata={
            "app_id": APP_RUNTIME_OBJECT_ID,
            "status": app_state.status.value,
            "started_at_utc": app_state.started_at_utc,
            "stopped_at_utc": app_state.stopped_at_utc,
            "last_updated_utc": app_state.last_updated_utc,
            "metadata": dict(app_state.metadata),
        },
        relationship_refs=(),
        audit_refs=(),
        source_refs=("StateStore",),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "StateStore app runtime state",
            "audit_reference_policy": "AuditLog remains historical truth",
        },
    )


def session_trace_ref_from_context(session: SessionContext) -> TraceableObjectRef:
    """Build a traceable object reference for one runtime session context."""

    _validate_session_context(session)
    return TraceableObjectRef(
        object_id=session.session_id,
        object_kind="session",
        owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
        owner_component="SessionManager",
        label=session.actor.display_name,
        metadata={
            "session_id": session.session_id,
            "actor_id": session.actor_id,
            "origin": session.origin.value,
        },
    )


def session_trace_summary_from_context(session: SessionContext) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one runtime session context."""

    _validate_session_context(session)
    object_ref = session_trace_ref_from_context(session)
    permission_refs = _permission_values(session.actor.permissions)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status="active",
        runtime_or_persistent=RUNTIME_REGISTRY_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(session.started_at_utc),
        updated_at_utc=_datetime_text(session.started_at_utc),
        display_name=session.actor.display_name,
        metadata={
            "session_id": session.session_id,
            "actor_id": session.actor_id,
            "username": session.actor.username,
            "display_name": session.actor.display_name,
            "roles": _role_values(session.actor.roles),
            "permissions": permission_refs,
            "origin": session.origin.value,
            "started_at_utc": session.started_at_utc,
            "actor_is_active": session.actor.is_active,
            "metadata": dict(session.metadata),
        },
        permission_refs=permission_refs,
        audit_refs=(),
        source_refs=("SessionManager",),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "SessionManager.current_session",
            "privacy_policy": "User contact fields are not included in summaries.",
        },
    )


def service_trace_ref_from_registered_service(
    registered: RegisteredService,
    service_state: ServiceRuntimeState | None = None,
) -> TraceableObjectRef:
    """Build a traceable object reference for one registered Core service."""

    _validate_registered_service(registered)
    _validate_optional_service_state(service_state)
    descriptor = registered.descriptor
    metadata: dict[str, object] = {
        "service_id": descriptor.service_id,
        "kind": descriptor.kind.value,
        "contract_id": descriptor.contract_id,
        "contract_version": descriptor.contract_version,
    }
    if service_state is not None:
        metadata["status"] = service_state.status.value
    return TraceableObjectRef(
        object_id=descriptor.service_id,
        object_kind="service",
        owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
        owner_component="ServiceRegistry / StateStore",
        label=descriptor.display_name or descriptor.service_id,
        metadata=metadata,
    )


def service_trace_summary_from_registered_service(
    registered: RegisteredService,
    service_state: ServiceRuntimeState | None = None,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one registered Core service."""

    _validate_registered_service(registered)
    _validate_optional_service_state(service_state)
    descriptor = registered.descriptor
    object_ref = service_trace_ref_from_registered_service(registered, service_state)
    lifecycle_status = (
        service_state.status.value if service_state is not None else "registered"
    )
    relationships = _service_relationships_from_descriptor(descriptor, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=lifecycle_status,
        runtime_or_persistent=RUNTIME_REGISTRY_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(
            service_state.last_updated_utc if service_state is not None else None
        ),
        updated_at_utc=_datetime_text(
            service_state.last_updated_utc if service_state is not None else None
        ),
        display_name=descriptor.display_name or descriptor.service_id,
        metadata=_service_summary_metadata(registered, service_state),
        relationship_refs=relationships,
        audit_refs=(),
        source_refs=("ServiceRegistry", "StateStore"),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "ServiceRegistry.list_services plus StateStore service state",
        },
    )


def contract_descriptor_trace_ref_from_descriptor(
    descriptor: ContractDescriptor,
) -> TraceableObjectRef:
    """Build a traceable object reference for one registered contract descriptor."""

    _validate_contract_descriptor(descriptor)
    return TraceableObjectRef(
        object_id=_contract_object_id(descriptor.contract_id, descriptor.version),
        object_kind="contract_descriptor",
        owner_domain="core.contracts",
        owner_component="ContractRegistry",
        label=f"{descriptor.contract_id} {descriptor.version}",
        metadata={
            "contract_id": descriptor.contract_id,
            "version": descriptor.version,
            "owner": descriptor.owner.value,
            "status": descriptor.status.value,
        },
    )


def contract_descriptor_trace_summary_from_descriptor(
    descriptor: ContractDescriptor,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one registered contract descriptor."""

    _validate_contract_descriptor(descriptor)
    object_ref = contract_descriptor_trace_ref_from_descriptor(descriptor)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status=descriptor.status.value,
        runtime_or_persistent="static_metadata",
        display_name=f"{descriptor.contract_id} {descriptor.version}",
        metadata={
            "contract_id": descriptor.contract_id,
            "version": descriptor.version,
            "owner": descriptor.owner.value,
            "status": descriptor.status.value,
            "schema_kind": descriptor.schema_kind.value,
            "required_fields": descriptor.required_fields,
            "optional_fields": descriptor.optional_fields,
            "known_fields": descriptor.known_fields,
            "description": descriptor.description,
        },
        relationship_refs=(),
        audit_refs=(),
        source_refs=("ContractRegistry",),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "ContractRegistry.list_contracts",
        },
    )


def error_report_trace_ref_from_report(report: ErrorReport) -> TraceableObjectRef:
    """Build a traceable object reference for one explicit error report."""

    _validate_error_report(report)
    return TraceableObjectRef(
        object_id=report.error_id,
        object_kind="error_report",
        owner_domain="core.errors",
        owner_component="ErrorRouter",
        label=report.message,
        metadata={
            "error_id": report.error_id,
            "severity": report.severity.value,
            "session_id": report.session_id,
            "correlation_id": report.correlation_id,
        },
    )


def error_report_trace_summary_from_report(
    report: ErrorReport,
) -> TraceableObjectSummary:
    """Build a read-only traceable summary for one explicit error report."""

    _validate_error_report(report)
    object_ref = error_report_trace_ref_from_report(report)
    relationships = _error_report_relationships_from_report(report, object_ref)
    return TraceableObjectSummary(
        object_ref=object_ref,
        lifecycle_status="reported",
        runtime_or_persistent=RUNTIME_REGISTRY_TRACE_RUNTIME_KIND,
        created_or_registered_at_utc=_datetime_text(report.timestamp_utc),
        updated_at_utc=_datetime_text(report.timestamp_utc),
        display_name=report.message,
        metadata={
            "error_id": report.error_id,
            "message": report.message,
            "severity": report.severity.value,
            "timestamp_utc": report.timestamp_utc,
            "exception_type": report.exception_type,
            "exception_message": report.exception_message,
            "session_id": report.session_id,
            "correlation_id": report.correlation_id,
            "context_keys": tuple(sorted(report.context)),
            "context_redacted": True,
        },
        relationship_refs=relationships,
        audit_refs=(),
        operation_refs=_context_string_tuple(report.context, "operation_id"),
        task_refs=_context_string_tuple(report.context, "task_id"),
        correlation_refs=_optional_ref_tuple(report.correlation_id),
        source_refs=("ErrorReport",),
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "explicit ErrorReport values",
            "error_router_retention_policy": _ERROR_REPORT_WARNING,
        },
    )


def runtime_registry_relationships_from_sources(
    *,
    runtime_snapshot: RuntimeSnapshot | None = None,
    app_state: AppRuntimeState | None = None,
    session_context: SessionContext | None = None,
    registered_services: Iterable[RegisteredService] = (),
    service_states: Iterable[ServiceRuntimeState] = (),
    contract_descriptors: Iterable[ContractDescriptor] = (),
    error_reports: Iterable[ErrorReport] = (),
) -> tuple[TraceableRelationshipRef, ...]:
    """Build read-only relationship refs from explicit runtime registry sources."""

    summaries: list[TraceableObjectSummary] = []
    resolved_app_state = app_state
    resolved_service_states = tuple(service_states)
    if runtime_snapshot is not None:
        _validate_runtime_snapshot(runtime_snapshot)
        resolved_app_state = resolved_app_state or runtime_snapshot.app_state
        if not resolved_service_states:
            resolved_service_states = runtime_snapshot.service_states
    if resolved_app_state is not None:
        summaries.append(app_runtime_trace_summary_from_snapshot(resolved_app_state))
    if session_context is not None:
        summaries.append(session_trace_summary_from_context(session_context))
    service_state_by_id = _service_state_by_id(resolved_service_states)
    for registered in _normalize_registered_services(registered_services):
        summaries.append(
            service_trace_summary_from_registered_service(
                registered,
                service_state_by_id.get(registered.descriptor.service_id),
            )
        )
    for descriptor in _normalize_contract_descriptors(contract_descriptors):
        summaries.append(contract_descriptor_trace_summary_from_descriptor(descriptor))
    for report in _normalize_error_reports(error_reports):
        summaries.append(error_report_trace_summary_from_report(report))

    return _relationships_from_summaries(summaries)


def build_runtime_registry_trace_section(
    *,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    session_manager: SessionManager | None = None,
    session_context: SessionContext | None = None,
    service_registry: ServiceRegistry | None = None,
    registered_services: Iterable[RegisteredService] | None = None,
    service_states: Iterable[ServiceRuntimeState] | None = None,
    contract_registry: ContractRegistry | None = None,
    contract_descriptors: Iterable[ContractDescriptor] | None = None,
    error_reports: Iterable[ErrorReport] | None = None,
) -> ObjectMapSection:
    """Build a read-only Object Map section for Core runtime registry families."""

    snapshot, snapshot_errors = _resolve_runtime_snapshot(
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
    )
    app_summary, app_errors = _resolve_app_summary(snapshot)
    session_summary, session_errors = _resolve_session_summary(
        session_manager=session_manager,
        session_context=session_context,
    )
    service_summaries, service_errors = _resolve_service_summaries(
        service_registry=service_registry,
        registered_services=registered_services,
        service_states=service_states,
        runtime_snapshot=snapshot,
    )
    contract_summaries, contract_errors = _resolve_contract_summaries(
        contract_registry=contract_registry,
        contract_descriptors=contract_descriptors,
    )
    error_summaries, error_errors = _resolve_error_summaries(error_reports)

    summaries = tuple(
        summary
        for summary in (
            app_summary,
            session_summary,
            *service_summaries,
            *contract_summaries,
            *error_summaries,
        )
        if summary is not None
    )
    relationships = _relationships_from_summaries(summaries)
    legends, legend_warnings = _runtime_registry_legends()
    warnings = [*legend_warnings, _ERROR_REPORT_WARNING]
    errors = (
        *snapshot_errors,
        *app_errors,
        *session_errors,
        *service_errors,
        *contract_errors,
        *error_errors,
    )

    return ObjectMapSection(
        section_id=RUNTIME_REGISTRY_TRACE_SECTION_ID,
        provider_id=RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
        owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
        object_kind=None,
        family_id=None,
        title="Core Runtime Registry",
        summaries=summaries,
        relationships=relationships,
        legends=legends,
        relationship_definitions=_runtime_registry_relationship_definitions(),
        warnings=tuple(warnings),
        errors=tuple(errors),
        metadata={
            "app_runtime_count": _summary_count(summaries, "app_runtime"),
            "session_count": _summary_count(summaries, "session"),
            "service_count": _summary_count(summaries, "service"),
            "contract_descriptor_count": _summary_count(
                summaries,
                "contract_descriptor",
            ),
            "error_report_count": _summary_count(summaries, "error_report"),
            "summary_count": len(summaries),
            "relationship_count": len(relationships),
            "object_kinds": tuple(
                sorted({summary.object_ref.object_kind for summary in summaries})
            ),
        },
        extra={
            "read_only": True,
            "mutation_forbidden": True,
            "source": "runtime_registry_read_models",
        },
    )


def interrogate_runtime_registry_trace(
    object_id: str,
    *,
    object_kind: str | None = None,
    state_store: StateStore | None = None,
    runtime_snapshot: RuntimeSnapshot | None = None,
    session_manager: SessionManager | None = None,
    session_context: SessionContext | None = None,
    service_registry: ServiceRegistry | None = None,
    registered_services: Iterable[RegisteredService] | None = None,
    service_states: Iterable[ServiceRuntimeState] | None = None,
    contract_registry: ContractRegistry | None = None,
    contract_descriptors: Iterable[ContractDescriptor] | None = None,
    error_reports: Iterable[ErrorReport] | None = None,
) -> ObjectInterrogationReport:
    """Return a read-only interrogation report for one runtime registry object."""

    _validate_non_empty_string(object_id, "object_id")
    if object_kind is not None and object_kind not in _TRACE_FAMILY_IDS:
        allowed = ", ".join(_TRACE_FAMILY_IDS)
        raise ValueError(f"object_kind must be one of: {allowed}")

    section = build_runtime_registry_trace_section(
        state_store=state_store,
        runtime_snapshot=runtime_snapshot,
        session_manager=session_manager,
        session_context=session_context,
        service_registry=service_registry,
        registered_services=registered_services,
        service_states=service_states,
        contract_registry=contract_registry,
        contract_descriptors=contract_descriptors,
        error_reports=error_reports,
    )
    summary = _find_summary(section.summaries, object_id, object_kind=object_kind)
    inferred_kind = object_kind or _kind_from_summary(summary) or "runtime_registry"
    target_ref = (
        summary.object_ref
        if summary is not None
        else TraceableObjectRef(
            object_id=object_id,
            object_kind=inferred_kind,
            owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
            owner_component=RUNTIME_REGISTRY_TRACE_OWNER_COMPONENT,
        )
    )
    blockers = (
        ()
        if summary is not None
        else (f"Runtime registry object not found: {object_id}",)
    )
    relationships = (
        _relationships_for_summary(summary, section.relationships)
        if summary is not None
        else ()
    )
    return ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=_legend_for_kind(target_ref.object_kind),
        relationships=relationships,
        permissions=summary.permission_refs if summary is not None else (),
        audit_refs=summary.audit_refs if summary is not None else (),
        runtime_refs=(object_id,),
        docs=_TRACE_DOCS,
        tests=(RUNTIME_REGISTRY_TRACE_TEST,),
        warnings=section.warnings,
        blockers=(*blockers, *section.blockers),
        errors=section.errors,
        metadata={
            "provider_id": RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
            "section_id": RUNTIME_REGISTRY_TRACE_SECTION_ID,
            "object_id": object_id,
            "object_kind": target_ref.object_kind,
            "read_only": True,
        },
    )


def _service_relationships_from_descriptor(
    descriptor: object,
    service_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    contract_id = getattr(descriptor, "contract_id", None)
    contract_version = getattr(descriptor, "contract_version", None)
    service_id = getattr(descriptor, "service_id", None)
    if isinstance(contract_id, str) and isinstance(contract_version, str):
        contract_ref = TraceableObjectRef(
            object_id=_contract_object_id(contract_id, contract_version),
            object_kind="contract_descriptor",
            owner_domain="core.contracts",
            owner_component="ContractRegistry",
            label=f"{contract_id} {contract_version}",
            metadata={
                "contract_id": contract_id,
                "version": contract_version,
            },
        )
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=(
                    f"{service_id}.described_by_contract."
                    f"{contract_ref.object_id}"
                ),
                relationship_type="described_by_contract",
                source_ref=service_ref,
                target_ref=contract_ref,
                direction="outbound",
                lifecycle_status="registered",
                metadata={
                    "service_id": service_id,
                    "contract_id": contract_id,
                    "contract_version": contract_version,
                },
            )
        )
    dependencies = getattr(descriptor, "dependencies", ())
    for dependency_id in dependencies:
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=f"{service_id}.depends_on.{dependency_id}",
                relationship_type="depends_on",
                source_ref=service_ref,
                target_ref=TraceableObjectRef(
                    object_id=dependency_id,
                    object_kind="service",
                    owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
                    owner_component="ServiceRegistry",
                    metadata={"service_id": dependency_id},
                ),
                direction="outbound",
                lifecycle_status="registered",
                metadata={
                    "service_id": service_id,
                    "dependency_service_id": dependency_id,
                },
            )
        )
    return tuple(relationships)


def _error_report_relationships_from_report(
    report: ErrorReport,
    report_ref: TraceableObjectRef,
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    relationships.extend(
        _reference_relationship(
            report_ref,
            object_id=report.session_id,
            object_kind="session",
            owner_domain=RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN,
            owner_component="SessionManager",
            metadata_key="session_id",
            relationship_suffix="session",
            correlation_id=report.correlation_id,
        )
    )
    for key, object_kind, owner_component in (
        ("operation_id", "operation", "OperationRegistry"),
        ("task_id", "task", "TaskManager"),
        ("action_id", "action", "ActionRegistry"),
        ("window_id", "window", "WindowRegistry"),
    ):
        relationships.extend(
            _reference_relationship(
                report_ref,
                object_id=_context_string(report.context, key),
                object_kind=object_kind,
                owner_domain=(
                    RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN
                    if object_kind in {"operation", "task"}
                    else "gui"
                ),
                owner_component=owner_component,
                metadata_key=key,
                relationship_suffix=object_kind,
                correlation_id=report.correlation_id,
            )
        )
    return tuple(relationships)


def _reference_relationship(
    source_ref: TraceableObjectRef,
    *,
    object_id: str | None,
    object_kind: str,
    owner_domain: str,
    owner_component: str,
    metadata_key: str,
    relationship_suffix: str,
    correlation_id: str | None,
) -> tuple[TraceableRelationshipRef, ...]:
    if object_id is None:
        return ()
    return (
        TraceableRelationshipRef(
            relationship_id=(
                f"{source_ref.object_id}.references_{relationship_suffix}."
                f"{object_id}"
            ),
            relationship_type="references",
            source_ref=source_ref,
            target_ref=TraceableObjectRef(
                object_id=object_id,
                object_kind=object_kind,
                owner_domain=owner_domain,
                owner_component=owner_component,
                metadata={metadata_key: object_id},
            ),
            direction="outbound",
            lifecycle_status="reported",
            correlation_id=correlation_id,
            metadata={
                "relationship_semantics": "error_report_context_reference",
                metadata_key: object_id,
            },
        ),
    )


def _resolve_runtime_snapshot(
    *,
    state_store: StateStore | None,
    runtime_snapshot: RuntimeSnapshot | None,
) -> tuple[RuntimeSnapshot | None, tuple[str, ...]]:
    if runtime_snapshot is not None:
        if not isinstance(runtime_snapshot, RuntimeSnapshot):
            return None, ("runtime_snapshot must be a RuntimeSnapshot",)
        return runtime_snapshot, ()
    if state_store is not None:
        if not isinstance(state_store, StateStore):
            return None, ("state_store must be a StateStore",)
        return state_store.runtime_snapshot(), ()
    return None, ()


def _resolve_app_summary(
    snapshot: RuntimeSnapshot | None,
) -> tuple[TraceableObjectSummary | None, tuple[str, ...]]:
    if snapshot is None:
        return None, ()
    return app_runtime_trace_summary_from_snapshot(snapshot), ()


def _resolve_session_summary(
    *,
    session_manager: SessionManager | None,
    session_context: SessionContext | None,
) -> tuple[TraceableObjectSummary | None, tuple[str, ...]]:
    if session_context is not None:
        if not isinstance(session_context, SessionContext):
            return None, ("session_context must be a SessionContext",)
        return session_trace_summary_from_context(session_context), ()
    if session_manager is not None:
        if not isinstance(session_manager, SessionManager):
            return None, ("session_manager must be a SessionManager",)
        return session_trace_summary_from_context(session_manager.current_session), ()
    return None, ()


def _resolve_service_summaries(
    *,
    service_registry: ServiceRegistry | None,
    registered_services: Iterable[RegisteredService] | None,
    service_states: Iterable[ServiceRuntimeState] | None,
    runtime_snapshot: RuntimeSnapshot | None,
) -> tuple[tuple[TraceableObjectSummary, ...], tuple[str, ...]]:
    services, service_errors = _resolve_registered_services(
        service_registry=service_registry,
        registered_services=registered_services,
    )
    states, state_errors = _resolve_service_states(
        service_states=service_states,
        runtime_snapshot=runtime_snapshot,
    )
    service_state_by_id = _service_state_by_id(states)
    summaries: list[TraceableObjectSummary] = []
    errors = [*service_errors, *state_errors]
    for registered in services:
        try:
            summaries.append(
                service_trace_summary_from_registered_service(
                    registered,
                    service_state_by_id.get(registered.descriptor.service_id),
                )
            )
        except (TypeError, ValueError) as error:
            errors.append(f"Service trace skipped for {registered!r}: {error}")
    return tuple(summaries), tuple(errors)


def _resolve_registered_services(
    *,
    service_registry: ServiceRegistry | None,
    registered_services: Iterable[RegisteredService] | None,
) -> tuple[tuple[RegisteredService, ...], tuple[str, ...]]:
    if registered_services is not None:
        return _checked_registered_services(registered_services)
    if service_registry is not None:
        if not isinstance(service_registry, ServiceRegistry):
            return (), ("service_registry must be a ServiceRegistry",)
        return _checked_registered_services(service_registry.list_services())
    return (), ()


def _resolve_service_states(
    *,
    service_states: Iterable[ServiceRuntimeState] | None,
    runtime_snapshot: RuntimeSnapshot | None,
) -> tuple[tuple[ServiceRuntimeState, ...], tuple[str, ...]]:
    if service_states is not None:
        return _checked_service_states(service_states)
    if runtime_snapshot is not None:
        return _checked_service_states(runtime_snapshot.service_states)
    return (), ()


def _resolve_contract_summaries(
    *,
    contract_registry: ContractRegistry | None,
    contract_descriptors: Iterable[ContractDescriptor] | None,
) -> tuple[tuple[TraceableObjectSummary, ...], tuple[str, ...]]:
    descriptors, errors = _resolve_contract_descriptors(
        contract_registry=contract_registry,
        contract_descriptors=contract_descriptors,
    )
    summaries: list[TraceableObjectSummary] = []
    for descriptor in descriptors:
        try:
            summaries.append(contract_descriptor_trace_summary_from_descriptor(descriptor))
        except (TypeError, ValueError) as error:
            errors = (*errors, f"Contract trace skipped for {descriptor!r}: {error}")
    return tuple(summaries), errors


def _resolve_contract_descriptors(
    *,
    contract_registry: ContractRegistry | None,
    contract_descriptors: Iterable[ContractDescriptor] | None,
) -> tuple[tuple[ContractDescriptor, ...], tuple[str, ...]]:
    if contract_descriptors is not None:
        return _checked_contract_descriptors(contract_descriptors)
    if contract_registry is not None:
        if not isinstance(contract_registry, ContractRegistry):
            return (), ("contract_registry must be a ContractRegistry",)
        return _checked_contract_descriptors(
            registered.descriptor for registered in contract_registry.list_contracts()
        )
    return (), ()


def _resolve_error_summaries(
    error_reports: Iterable[ErrorReport] | None,
) -> tuple[tuple[TraceableObjectSummary, ...], tuple[str, ...]]:
    if error_reports is None:
        return (), ()
    reports, errors = _checked_error_reports(error_reports)
    summaries: list[TraceableObjectSummary] = []
    for report in reports:
        try:
            summaries.append(error_report_trace_summary_from_report(report))
        except (TypeError, ValueError) as error:
            errors = (*errors, f"Error report trace skipped for {report!r}: {error}")
    return tuple(summaries), errors


def _service_summary_metadata(
    registered: RegisteredService,
    service_state: ServiceRuntimeState | None,
) -> Mapping[str, object]:
    descriptor = registered.descriptor
    return {
        "service_id": descriptor.service_id,
        "kind": descriptor.kind.value,
        "display_name": descriptor.display_name,
        "description": descriptor.description,
        "contract_id": descriptor.contract_id,
        "contract_version": descriptor.contract_version,
        "dependencies": descriptor.dependencies,
        "lifecycle_status": (
            service_state.status.value if service_state is not None else "registered"
        ),
        "runtime_state_present": service_state is not None,
        "message": service_state.message if service_state is not None else "",
        "last_updated_utc": (
            service_state.last_updated_utc if service_state is not None else None
        ),
        "metadata": dict(service_state.metadata) if service_state is not None else {},
        "is_lifecycle_service": descriptor.kind is ServiceKind.LIFECYCLE,
        "is_capability_provider": descriptor.kind is ServiceKind.CAPABILITY,
    }


def _relationships_from_summaries(
    summaries: Iterable[TraceableObjectSummary],
) -> tuple[TraceableRelationshipRef, ...]:
    summaries_tuple = tuple(summaries)
    relationships: list[TraceableRelationshipRef] = [
        relationship
        for summary in summaries_tuple
        for relationship in summary.relationship_refs
    ]
    app_summary = _first_summary(summaries_tuple, "app_runtime")
    if app_summary is not None:
        relationships.extend(_app_relationships_from_summaries(app_summary, summaries_tuple))
    return _dedupe_relationships(relationships)


def _relationships_for_summary(
    summary: TraceableObjectSummary,
    relationships: Iterable[TraceableRelationshipRef],
) -> tuple[TraceableRelationshipRef, ...]:
    object_id = summary.object_ref.object_id
    object_kind = summary.object_ref.object_kind
    return tuple(
        relationship
        for relationship in relationships
        if (
            relationship.source_ref.object_id == object_id
            and relationship.source_ref.object_kind == object_kind
        )
        or (
            relationship.target_ref.object_id == object_id
            and relationship.target_ref.object_kind == object_kind
        )
    )


def _app_relationships_from_summaries(
    app_summary: TraceableObjectSummary,
    summaries: tuple[TraceableObjectSummary, ...],
) -> tuple[TraceableRelationshipRef, ...]:
    relationships: list[TraceableRelationshipRef] = []
    for summary in summaries:
        if summary.object_ref.object_kind not in {"session", "service"}:
            continue
        relationships.append(
            TraceableRelationshipRef(
                relationship_id=(
                    f"{APP_RUNTIME_OBJECT_ID}.references_"
                    f"{summary.object_ref.object_kind}.{summary.object_ref.object_id}"
                ),
                relationship_type="references",
                source_ref=app_summary.object_ref,
                target_ref=summary.object_ref,
                direction="outbound",
                lifecycle_status=app_summary.lifecycle_status,
                metadata={
                    "relationship_semantics": "app_runtime_current_reference",
                    "target_kind": summary.object_ref.object_kind,
                    "target_id": summary.object_ref.object_id,
                },
            )
        )
    return tuple(relationships)


def _checked_registered_services(
    values: Iterable[RegisteredService],
) -> tuple[tuple[RegisteredService, ...], tuple[str, ...]]:
    services: list[RegisteredService] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, RegisteredService):
            errors.append("registered_services entries must be RegisteredService")
            continue
        services.append(value)
    return tuple(services), tuple(errors)


def _checked_service_states(
    values: Iterable[ServiceRuntimeState],
) -> tuple[tuple[ServiceRuntimeState, ...], tuple[str, ...]]:
    states: list[ServiceRuntimeState] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ServiceRuntimeState):
            errors.append("service_states entries must be ServiceRuntimeState")
            continue
        states.append(value)
    return tuple(states), tuple(errors)


def _checked_contract_descriptors(
    values: Iterable[ContractDescriptor],
) -> tuple[tuple[ContractDescriptor, ...], tuple[str, ...]]:
    descriptors: list[ContractDescriptor] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ContractDescriptor):
            errors.append("contract_descriptors entries must be ContractDescriptor")
            continue
        descriptors.append(value)
    return tuple(descriptors), tuple(errors)


def _checked_error_reports(
    values: Iterable[ErrorReport],
) -> tuple[tuple[ErrorReport, ...], tuple[str, ...]]:
    reports: list[ErrorReport] = []
    errors: list[str] = []
    for value in tuple(values):
        if not isinstance(value, ErrorReport):
            errors.append("error_reports entries must be ErrorReport")
            continue
        reports.append(value)
    return tuple(reports), tuple(errors)


def _normalize_registered_services(
    values: Iterable[RegisteredService],
) -> tuple[RegisteredService, ...]:
    services, errors = _checked_registered_services(values)
    if errors:
        raise TypeError(errors[0])
    return services


def _normalize_contract_descriptors(
    values: Iterable[ContractDescriptor],
) -> tuple[ContractDescriptor, ...]:
    descriptors, errors = _checked_contract_descriptors(values)
    if errors:
        raise TypeError(errors[0])
    return descriptors


def _normalize_error_reports(values: Iterable[ErrorReport]) -> tuple[ErrorReport, ...]:
    reports, errors = _checked_error_reports(values)
    if errors:
        raise TypeError(errors[0])
    return reports


def _service_state_by_id(
    values: Iterable[ServiceRuntimeState],
) -> dict[str, ServiceRuntimeState]:
    states, errors = _checked_service_states(values)
    if errors:
        raise TypeError(errors[0])
    return {state.service_id: state for state in states}


def _runtime_registry_legends() -> tuple[tuple[object, ...], tuple[str, ...]]:
    warnings: list[str] = []
    legends = []
    for family_id in _TRACE_FAMILY_IDS:
        legend = object_family_legend_by_id(family_id)
        if legend is None:
            warnings.append(f"Missing object family legend for {family_id}")
            continue
        legends.append(legend)
    return tuple(legends), tuple(warnings)


def _runtime_registry_relationship_definitions() -> tuple[object, ...]:
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
    object_id: str,
    *,
    object_kind: str | None,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        if object_kind is not None and summary.object_ref.object_kind != object_kind:
            continue
        if object_id == summary.object_ref.object_id:
            return summary
        for key in ("session_id", "service_id", "contract_id", "error_id", "app_id"):
            if object_id == summary.metadata.get(key):
                return summary
        if summary.object_ref.object_kind == "contract_descriptor":
            contract_id = summary.metadata.get("contract_id")
            version = summary.metadata.get("version")
            if isinstance(contract_id, str) and isinstance(version, str):
                if object_id == _contract_object_id(contract_id, version):
                    return summary
    return None


def _first_summary(
    summaries: tuple[TraceableObjectSummary, ...],
    object_kind: str,
) -> TraceableObjectSummary | None:
    for summary in summaries:
        if summary.object_ref.object_kind == object_kind:
            return summary
    return None


def _kind_from_summary(summary: TraceableObjectSummary | None) -> str | None:
    if summary is None:
        return None
    return summary.object_ref.object_kind


def _legend_for_kind(object_kind: str) -> object | None:
    if object_kind in _TRACE_FAMILY_IDS:
        return object_family_legend_by_id(object_kind)
    return None


def _summary_count(
    summaries: tuple[TraceableObjectSummary, ...],
    object_kind: str,
) -> int:
    return sum(1 for summary in summaries if summary.object_ref.object_kind == object_kind)


def _app_state_from_snapshot_or_state(
    value: RuntimeSnapshot | AppRuntimeState,
) -> AppRuntimeState:
    if isinstance(value, RuntimeSnapshot):
        return value.app_state
    if isinstance(value, AppRuntimeState):
        return value
    raise TypeError("snapshot_or_state must be a RuntimeSnapshot or AppRuntimeState")


def _contract_object_id(contract_id: str, version: str) -> str:
    return f"{contract_id}@{version}"


def _context_string(context: Mapping[str, object], key: str) -> str | None:
    value = context.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _context_string_tuple(context: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = _context_string(context, key)
    return (value,) if value is not None else ()


def _optional_ref_tuple(value: str | None) -> tuple[str, ...]:
    return (value,) if value is not None else ()


def _role_values(values: tuple[UserRole, ...]) -> tuple[str, ...]:
    return tuple(value.value for value in values)


def _permission_values(values: tuple[Permission, ...]) -> tuple[str, ...]:
    return tuple(value.value for value in values)


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _validate_runtime_snapshot(value: RuntimeSnapshot) -> None:
    if not isinstance(value, RuntimeSnapshot):
        raise TypeError("runtime_snapshot must be a RuntimeSnapshot")


def _validate_session_context(value: SessionContext) -> None:
    if not isinstance(value, SessionContext):
        raise TypeError("session must be a SessionContext")


def _validate_registered_service(value: RegisteredService) -> None:
    if not isinstance(value, RegisteredService):
        raise TypeError("registered must be a RegisteredService")


def _validate_optional_service_state(value: ServiceRuntimeState | None) -> None:
    if value is not None and not isinstance(value, ServiceRuntimeState):
        raise TypeError("service_state must be a ServiceRuntimeState or None")


def _validate_contract_descriptor(value: ContractDescriptor) -> None:
    if not isinstance(value, ContractDescriptor):
        raise TypeError("descriptor must be a ContractDescriptor")


def _validate_error_report(value: ErrorReport) -> None:
    if not isinstance(value, ErrorReport):
        raise TypeError("report must be an ErrorReport")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


__all__ = [
    "APP_RUNTIME_OBJECT_ID",
    "RUNTIME_REGISTRY_TRACE_OWNER_COMPONENT",
    "RUNTIME_REGISTRY_TRACE_OWNER_DOMAIN",
    "RUNTIME_REGISTRY_TRACE_PROVIDER_ID",
    "RUNTIME_REGISTRY_TRACE_RUNTIME_KIND",
    "RUNTIME_REGISTRY_TRACE_SECTION_ID",
    "app_runtime_trace_ref_from_snapshot",
    "app_runtime_trace_summary_from_snapshot",
    "build_runtime_registry_trace_provider_descriptor",
    "build_runtime_registry_trace_section",
    "contract_descriptor_trace_ref_from_descriptor",
    "contract_descriptor_trace_summary_from_descriptor",
    "error_report_trace_ref_from_report",
    "error_report_trace_summary_from_report",
    "interrogate_runtime_registry_trace",
    "runtime_registry_relationships_from_sources",
    "service_trace_ref_from_registered_service",
    "service_trace_summary_from_registered_service",
    "session_trace_ref_from_context",
    "session_trace_summary_from_context",
]
