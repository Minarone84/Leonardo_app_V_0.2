from datetime import UTC, datetime
from pathlib import Path

import pytest

from leonardo.contracts.errors import ErrorReport, ErrorSeverity
from leonardo.contracts.identity import (
    ActorOrigin,
    Permission,
    SessionContext,
    UserRef,
    UserRole,
)
from leonardo.contracts.kernel import (
    ContractDescriptor,
    ContractOwner,
    ContractSchemaKind,
    ContractStatus,
)
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.runtime import AppLifecycleStatus, ServiceLifecycleStatus
from leonardo.contracts.services import ServiceDescriptor, ServiceKind
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.core.audit_log import AuditLog
from leonardo.core.contract_registry import ContractRegistry
from leonardo.core.error_router import ErrorRouter
from leonardo.core.runtime_registry_trace import (
    APP_RUNTIME_OBJECT_ID,
    RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
    build_runtime_registry_trace_provider_descriptor,
    build_runtime_registry_trace_section,
    contract_descriptor_trace_summary_from_descriptor,
    error_report_trace_summary_from_report,
    interrogate_runtime_registry_trace,
    runtime_registry_relationships_from_sources,
    service_trace_summary_from_registered_service,
    session_trace_summary_from_context,
)
from leonardo.core.service_registry import RegisteredService, ServiceRegistry
from leonardo.core.session_manager import SessionManager
from leonardo.core.state_store import StateStore


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "runtime_registry_trace.py"
_RUNTIME_MANAGER_SOURCE = _REPO_ROOT / "src" / "leonardo" / "core" / "runtime_manager.py"


def test_runtime_registry_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_runtime_registry_trace_provider_descriptor()

    assert descriptor.provider_id == RUNTIME_REGISTRY_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.object_kinds == (
        "app_runtime",
        "session",
        "service",
        "contract_descriptor",
        "error_report",
    )
    assert descriptor.family_ids == descriptor.object_kinds
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "references" in descriptor.relationship_types
    assert "described_by_contract" in descriptor.relationship_types
    assert descriptor.metadata["error_report_source"] == "explicit ErrorReport values only"


def test_app_runtime_session_service_and_contract_summaries_are_built_from_read_models() -> None:
    runtime = _runtime()
    session = _session()
    service = _register_service(runtime.service_registry, runtime.state_store)
    descriptor = _contract_descriptor()
    runtime.contract_registry.register_contract(descriptor)

    section = build_runtime_registry_trace_section(
        state_store=runtime.state_store,
        session_context=session,
        service_registry=runtime.service_registry,
        contract_registry=runtime.contract_registry,
    )
    summaries = {
        summary.object_ref.object_kind: summary
        for summary in section.summaries
        if summary.object_ref.object_kind != "contract_descriptor"
    }
    contract_summary = _summary_by_kind(section, "contract_descriptor")

    assert isinstance(section, ObjectMapSection)
    assert summaries["app_runtime"].object_ref.object_id == APP_RUNTIME_OBJECT_ID
    assert summaries["app_runtime"].metadata["status"] == "running"
    assert summaries["session"].metadata["session_id"] == session.session_id
    assert summaries["session"].metadata["actor_id"] == session.actor_id
    assert summaries["session"].permission_refs == ("runtime:view", "service:view")
    assert summaries["service"].metadata["service_id"] == service.descriptor.service_id
    assert summaries["service"].metadata["lifecycle_status"] == "running"
    assert summaries["service"].metadata["runtime_state_present"] is True
    assert summaries["service"].metadata["is_lifecycle_service"] is True
    assert contract_summary.metadata["contract_id"] == descriptor.contract_id
    assert contract_summary.metadata["version"] == descriptor.version
    assert section.metadata["app_runtime_count"] == 1
    assert section.metadata["session_count"] == 1
    assert section.metadata["service_count"] == 1
    assert section.metadata["contract_descriptor_count"] == 1
    assert section.errors == ()


def test_service_summary_links_contract_and_dependencies_without_fake_links() -> None:
    runtime = _runtime()
    service = _register_service(runtime.service_registry, runtime.state_store)
    state = runtime.state_store.runtime_snapshot().service_states[0]

    summary = service_trace_summary_from_registered_service(service, state)
    relationship_ids = {
        relationship.relationship_id for relationship in summary.relationship_refs
    }
    relationship_types = {
        relationship.relationship_type for relationship in summary.relationship_refs
    }

    assert isinstance(summary, TraceableObjectSummary)
    assert "described_by_contract" in relationship_types
    assert "depends_on" in relationship_types
    assert (
        "runtime-service.described_by_contract."
        "leonardo.runtime.service_state@1.0"
    ) in relationship_ids
    assert "runtime-service.depends_on.dependency-service" in relationship_ids

    service_without_links = RegisteredService(
        descriptor=ServiceDescriptor(
            service_id="unlinked-service",
            kind=ServiceKind.CAPABILITY,
        ),
        service_object=object(),
    )

    assert service_trace_summary_from_registered_service(
        service_without_links
    ).relationship_refs == ()


def test_session_summary_uses_public_identity_without_contact_fields() -> None:
    session = _session()

    summary = session_trace_summary_from_context(session)

    assert summary.object_ref.object_id == "session-1"
    assert summary.object_ref.object_kind == "session"
    assert summary.display_name == "Ada Lovelace"
    assert summary.metadata["roles"] == ("administrator",)
    assert summary.metadata["permissions"] == ("runtime:view", "service:view")
    assert "email" not in summary.metadata
    assert "phone" not in summary.metadata


def test_contract_descriptor_summary_uses_registry_descriptor_fields() -> None:
    descriptor = _contract_descriptor()

    summary = contract_descriptor_trace_summary_from_descriptor(descriptor)

    assert summary.object_ref.object_id == "leonardo.runtime.service_state@1.0"
    assert summary.object_ref.object_kind == "contract_descriptor"
    assert summary.lifecycle_status == "active"
    assert summary.runtime_or_persistent == "static_metadata"
    assert summary.metadata["owner"] == "runtime"
    assert summary.metadata["schema_kind"] == "field_set"
    assert summary.metadata["required_fields"] == ("service_id", "status")
    assert summary.metadata["known_fields"] == (
        "service_id",
        "status",
        "message",
    )


def test_explicit_error_report_summary_redacts_context_and_links_safe_refs() -> None:
    report = _error_report()

    summary = error_report_trace_summary_from_report(report)
    targets = {
        relationship.target_ref.object_kind: relationship.target_ref.object_id
        for relationship in summary.relationship_refs
    }

    assert summary.object_ref.object_id == "error-1"
    assert summary.object_ref.object_kind == "error_report"
    assert summary.lifecycle_status == "reported"
    assert summary.metadata["severity"] == "error"
    assert summary.metadata["context_keys"] == ("action_id", "operation_id", "task_id")
    assert summary.metadata["context_redacted"] is True
    assert "context" not in summary.metadata
    assert targets["session"] == "session-1"
    assert targets["operation"] == "operation-1"
    assert targets["task"] == "task-1"
    assert targets["action"] == "main_window.download_data"
    assert summary.operation_refs == ("operation-1",)
    assert summary.task_refs == ("task-1",)
    assert summary.correlation_refs == ("corr-1",)


def test_error_reports_require_explicit_reports_because_error_router_has_no_read_api() -> None:
    runtime = _runtime()
    router = ErrorRouter(runtime.audit_log)

    section = build_runtime_registry_trace_section(state_store=runtime.state_store)

    assert not hasattr(router, "list_reports")
    assert not hasattr(router, "reports")
    assert section.metadata["error_report_count"] == 0
    assert any("explicit ErrorReport values" in warning for warning in section.warnings)


def test_runtime_registry_relationships_include_app_and_service_relationships() -> None:
    runtime = _runtime()
    session = _session()
    service = _register_service(runtime.service_registry, runtime.state_store)
    descriptor = _contract_descriptor()

    relationships = runtime_registry_relationships_from_sources(
        runtime_snapshot=runtime.state_store.runtime_snapshot(),
        session_context=session,
        registered_services=(service,),
        contract_descriptors=(descriptor,),
        error_reports=(_error_report(),),
    )
    relationship_ids = {relationship.relationship_id for relationship in relationships}
    relationship_types = {relationship.relationship_type for relationship in relationships}

    assert "references" in relationship_types
    assert "described_by_contract" in relationship_types
    assert "depends_on" in relationship_types
    assert f"{APP_RUNTIME_OBJECT_ID}.references_session.session-1" in relationship_ids
    assert (
        f"{APP_RUNTIME_OBJECT_ID}.references_service.runtime-service"
        in relationship_ids
    )
    assert (
        "runtime-service.described_by_contract."
        "leonardo.runtime.service_state@1.0"
    ) in relationship_ids
    assert "runtime-service.depends_on.dependency-service" in relationship_ids
    assert "error-1.references_operation.operation-1" in relationship_ids


def test_section_includes_target_legends_and_relationship_definitions() -> None:
    runtime = _runtime()
    _register_service(runtime.service_registry, runtime.state_store)
    runtime.contract_registry.register_contract(_contract_descriptor())

    section = build_runtime_registry_trace_section(
        state_store=runtime.state_store,
        session_context=_session(),
        service_registry=runtime.service_registry,
        contract_registry=runtime.contract_registry,
        error_reports=(_error_report(),),
    )
    family_ids = {legend.family_id for legend in section.legends}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert family_ids == {
        "app_runtime",
        "session",
        "service",
        "contract_descriptor",
        "error_report",
    }
    assert {"references", "depends_on", "described_by_contract"}.issubset(
        relationship_types
    )
    assert "has_permission" in relationship_types
    assert "records_audit" in relationship_types
    assert section.metadata["summary_count"] == 5
    assert section.metadata["relationship_count"] >= 5
    assert section.errors == ()


def test_interrogate_runtime_registry_trace_returns_read_only_reports() -> None:
    runtime = _runtime()
    service = _register_service(runtime.service_registry, runtime.state_store)
    runtime.contract_registry.register_contract(_contract_descriptor())

    service_report = interrogate_runtime_registry_trace(
        service.descriptor.service_id,
        object_kind="service",
        state_store=runtime.state_store,
        session_context=_session(),
        service_registry=runtime.service_registry,
        contract_registry=runtime.contract_registry,
    )
    app_report = interrogate_runtime_registry_trace(
        APP_RUNTIME_OBJECT_ID,
        object_kind="app_runtime",
        state_store=runtime.state_store,
        service_registry=runtime.service_registry,
    )

    assert service_report.summary is not None
    assert service_report.target_ref.object_kind == "service"
    assert service_report.family_legend is not None
    assert service_report.family_legend.family_id == "service"
    assert service_report.metadata["read_only"] is True
    assert service_report.blockers == ()
    assert any(
        relationship.relationship_type == "described_by_contract"
        for relationship in service_report.relationships
    )
    assert app_report.summary is not None
    assert app_report.target_ref.object_kind == "app_runtime"
    assert any(
        relationship.target_ref.object_id == service.descriptor.service_id
        for relationship in app_report.relationships
    )


def test_interrogate_missing_runtime_registry_object_reports_blocker() -> None:
    report = interrogate_runtime_registry_trace(
        "missing-service",
        object_kind="service",
    )

    assert report.summary is None
    assert report.target_ref.object_id == "missing-service"
    assert report.target_ref.object_kind == "service"
    assert report.blockers == ("Runtime registry object not found: missing-service",)
    assert report.errors == ()


def test_trace_helpers_do_not_mutate_state_registries_session_or_audit_log() -> None:
    runtime = _runtime()
    session = _session()
    service = _register_service(runtime.service_registry, runtime.state_store)
    descriptor = _contract_descriptor()
    runtime.contract_registry.register_contract(descriptor)
    before = (
        runtime.state_store.get_app_state(),
        runtime.state_store.runtime_snapshot().service_states,
        runtime.service_registry.list_services(),
        runtime.contract_registry.list_contracts(),
        session,
        runtime.audit_log.snapshot(),
    )

    build_runtime_registry_trace_section(
        state_store=runtime.state_store,
        session_context=session,
        service_registry=runtime.service_registry,
        contract_registry=runtime.contract_registry,
        error_reports=(_error_report(),),
    )
    interrogate_runtime_registry_trace(
        service.descriptor.service_id,
        object_kind="service",
        state_store=runtime.state_store,
        session_context=session,
        service_registry=runtime.service_registry,
        contract_registry=runtime.contract_registry,
        error_reports=(_error_report(),),
    )
    after = (
        runtime.state_store.get_app_state(),
        runtime.state_store.runtime_snapshot().service_states,
        runtime.service_registry.list_services(),
        runtime.contract_registry.list_contracts(),
        session,
        runtime.audit_log.snapshot(),
    )

    assert after == before


def test_malformed_explicit_sources_are_reported_without_mutation() -> None:
    section = build_runtime_registry_trace_section(
        registered_services=(object(),),
        service_states=(object(),),
        contract_descriptors=(object(),),
        error_reports=(object(),),
    )

    assert section.summaries == ()
    assert "registered_services entries must be RegisteredService" in section.errors
    assert "service_states entries must be ServiceRuntimeState" in section.errors
    assert "contract_descriptors entries must be ContractDescriptor" in section.errors
    assert "error_reports entries must be ErrorReport" in section.errors


def test_runtime_registry_trace_has_no_lifecycle_wiring_or_domain_behavior() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "CoreRunner",
        "CoreRuntimeBridge",
        "RuntimeManagerBackend",
        "RuntimeManagerWindow",
        "class ObjectMapService",
        "class ObjectMapRegistry",
        "register_provider",
        "def discover",
        ".discover",
        "submit_command",
        "set_app_lifecycle_status",
        "set_service_lifecycle_status",
        "register_service_runtime_state",
        "route_exception(",
        "route_error(",
        ".emit(",
        "DownloadManager",
        "DownloadExecutionManager",
        "DownloadRequestBuilderWindow",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QApplication",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "sub" + "process",
        "shell" + "=True",
        "requests",
        "aio" + "http",
        "web" + "sockets",
    )

    for token in blocked_tokens:
        assert token not in source


def test_runtime_manager_remains_unwired_from_runtime_registry_trace() -> None:
    source = _RUNTIME_MANAGER_SOURCE.read_text(encoding="utf-8")

    assert "runtime_registry_trace" not in source
    assert "build_runtime_registry_trace_section" not in source
    assert "RUNTIME_REGISTRY_TRACE_PROVIDER_ID" not in source


def _summary_by_kind(section: ObjectMapSection, object_kind: str) -> TraceableObjectSummary:
    for summary in section.summaries:
        if summary.object_ref.object_kind == object_kind:
            return summary
    raise AssertionError(f"Missing summary kind: {object_kind}")


class _Runtime:
    def __init__(self) -> None:
        self.audit_log = AuditLog()
        self.state_store = StateStore(self.audit_log)
        self.session_manager = SessionManager(
            audit_log=self.audit_log,
            session_context=_session(),
        )
        self.service_registry = ServiceRegistry()
        self.contract_registry = ContractRegistry()
        self.state_store.set_app_lifecycle_status(AppLifecycleStatus.RUNNING)


def _runtime() -> _Runtime:
    return _Runtime()


def _session() -> SessionContext:
    return SessionContext(
        session_id="session-1",
        actor=UserRef(
            user_id="admin-1",
            username="ada",
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.test",
            phone="555-0000",
            roles=(UserRole.ADMINISTRATOR,),
            permissions=(Permission.RUNTIME_VIEW, Permission.SERVICE_VIEW),
        ),
        origin=ActorOrigin.DEVELOPMENT,
        started_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _register_service(
    service_registry: ServiceRegistry,
    state_store: StateStore,
) -> RegisteredService:
    registered = service_registry.register_service(
        ServiceDescriptor(
            service_id="runtime-service",
            kind=ServiceKind.LIFECYCLE,
            display_name="Runtime Service",
            description="Runtime lifecycle service",
            contract_id="leonardo.runtime.service_state",
            contract_version="1.0",
            dependencies=("dependency-service",),
        ),
        object(),
    )
    state_store.register_service_runtime_state(
        registered.descriptor.service_id,
        status=ServiceLifecycleStatus.RUNNING,
        message="running",
    )
    return registered


def _contract_descriptor() -> ContractDescriptor:
    return ContractDescriptor(
        contract_id="leonardo.runtime.service_state",
        version="1.0",
        owner=ContractOwner.RUNTIME,
        status=ContractStatus.ACTIVE,
        schema_kind=ContractSchemaKind.FIELD_SET,
        required_fields=("service_id", "status"),
        optional_fields=("message",),
        description="Service runtime state contract",
    )


def _error_report() -> ErrorReport:
    return ErrorReport(
        error_id="error-1",
        message="Operation failed",
        severity=ErrorSeverity.ERROR,
        timestamp_utc=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        exception_type="RuntimeError",
        exception_message="failure",
        session_id="session-1",
        correlation_id="corr-1",
        context={
            "operation_id": "operation-1",
            "task_id": "task-1",
            "action_id": "main_window.download_data",
        },
    )
