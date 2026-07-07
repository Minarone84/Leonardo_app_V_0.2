from pathlib import Path

import pytest

from leonardo.contracts.object_map import (
    ObjectMapProviderDescriptor,
    ObjectMapQuery,
    ObjectMapQueryReport,
    ObjectMapSection,
    ObjectMapSnapshot,
)
from leonardo.contracts.traceable_object import (
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)
from leonardo.core.audit_event_trace import (
    AUDIT_EVENT_TRACE_PROVIDER_ID,
    build_audit_event_trace_provider_descriptor,
    build_audit_event_trace_section,
)
from leonardo.core.object_map_service import (
    DEFAULT_OBJECT_MAP_SNAPSHOT_ID,
    ObjectMapProviderEntry,
    ReadOnlyObjectMapService,
)
from leonardo.core.process_connection_trace import (
    PROCESS_CONNECTION_TRACE_PROVIDER_ID,
    build_process_connection_trace_provider_descriptor,
    build_process_connection_trace_section,
)
from leonardo.core.runtime_registry_trace import (
    RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
    build_runtime_registry_trace_provider_descriptor,
    build_runtime_registry_trace_section,
)
from leonardo.core.task_operation_trace import (
    TASK_OPERATION_TRACE_PROVIDER_ID,
    build_task_operation_trace_provider_descriptor,
    build_task_operation_trace_section,
)
from leonardo.gui.metadata.action_trace import (
    ACTION_TRACE_PROVIDER_ID,
    build_action_trace_provider_descriptor,
    build_action_trace_section,
)
from leonardo.gui.metadata.window_trace import (
    WINDOW_TRACE_PROVIDER_ID,
    build_window_trace_provider_descriptor,
    build_window_trace_section,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OBJECT_MAP_SERVICE = (
    _REPO_ROOT / "src" / "leonardo" / "core" / "object_map_service.py"
)
_TEST_TIME = "2026-01-01T00:00:00+00:00"


def test_empty_service_builds_valid_snapshot_and_query_report() -> None:
    service = ReadOnlyObjectMapService()

    snapshot = service.build_snapshot(generated_at_utc=_TEST_TIME)
    report = service.query(generated_at_utc=_TEST_TIME)

    assert isinstance(snapshot, ObjectMapSnapshot)
    assert snapshot.snapshot_id == DEFAULT_OBJECT_MAP_SNAPSHOT_ID
    assert snapshot.generated_at_utc == _TEST_TIME
    assert snapshot.sections == ()
    assert snapshot.provider_descriptors == ()
    assert snapshot.metadata["provider_count"] == 0
    assert snapshot.metadata["read_only"] is True

    assert isinstance(report, ObjectMapQueryReport)
    assert report.sections == ()
    assert report.provider_descriptors == ()
    assert report.metadata["summary_count"] == 0
    assert report.errors == ()


def test_service_accepts_explicit_provider_entries_and_orders_deterministically() -> None:
    first_section = _section(
        provider_id="provider.b",
        section_id="section.b",
        summaries=(_summary("operation-1", "operation"),),
    )
    second_section = _section(
        provider_id="provider.a",
        section_id="section.a",
        summaries=(_summary("task-1", "task"),),
    )
    service = ReadOnlyObjectMapService(
        (
            _provider("provider.b", first_section, object_kinds=("operation",)),
            _provider("provider.a", second_section, object_kinds=("task",)),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc=_TEST_TIME)

    assert [descriptor.provider_id for descriptor in snapshot.provider_descriptors] == [
        "provider.a",
        "provider.b",
    ]
    assert [section.section_id for section in snapshot.sections] == [
        "section.a",
        "section.b",
    ]
    assert service.get_provider_descriptors() == snapshot.provider_descriptors
    assert service.list_sections()[0].provider_id == "provider.a"


def test_snapshot_aggregates_summaries_relationships_and_diagnostics_without_mutation() -> None:
    relationship = _relationship(
        relationship_type="schedules_task",
        source_id="operation-1",
        source_kind="operation",
        target_id="task-1",
        target_kind="task",
    )
    section = _section(
        provider_id="provider.a",
        section_id="section.a",
        summaries=(
            _summary(
                "operation-1",
                "operation",
                relationship_refs=(relationship,),
            ),
            _summary("task-1", "task"),
        ),
        relationships=(relationship,),
        warnings=("provider warning",),
        errors=("provider error",),
    )
    before = section.to_dict()

    snapshot = ReadOnlyObjectMapService(
        (_provider("provider.a", section, object_kinds=("operation", "task")),)
    ).build_snapshot(generated_at_utc=_TEST_TIME)

    assert snapshot.sections == (section,)
    assert snapshot.sections[0].summaries == section.summaries
    assert snapshot.sections[0].relationships == section.relationships
    assert "Object Map section section.a warning: provider warning" in snapshot.warnings
    assert "Object Map section section.a error: provider error" in snapshot.errors
    assert section.to_dict() == before


def test_query_filters_by_object_provider_family_kind_owner_and_relationship() -> None:
    reference_relationship = _relationship(
        relationship_type="references",
        source_id="task-1",
        source_kind="task",
        target_id="operation-1",
        target_kind="operation",
    )
    task_section = _section(
        provider_id="provider.tasks",
        section_id="section.tasks",
        owner_domain="core",
        summaries=(
            _summary(
                "task-1",
                "task",
                owner_domain="core",
                relationship_refs=(reference_relationship,),
            ),
            _summary("operation-1", "operation", owner_domain="core"),
        ),
        relationships=(reference_relationship,),
    )
    action_section = _section(
        provider_id="provider.actions",
        section_id="section.actions",
        owner_domain="gui",
        summaries=(_summary("action-1", "action", owner_domain="gui"),),
        relationships=(),
    )
    service = ReadOnlyObjectMapService(
        (
            _provider(
                "provider.tasks",
                task_section,
                object_kinds=("task", "operation"),
                family_ids=("task", "operation"),
                relationship_types=("references",),
                owner_domain="core",
            ),
            _provider(
                "provider.actions",
                action_section,
                object_kinds=("action",),
                family_ids=("action",),
                owner_domain="gui",
            ),
        )
    )

    by_object = service.query(ObjectMapQuery(object_id="task-1"))
    by_kind = service.query(ObjectMapQuery(object_kind="operation"))
    by_family = service.query(ObjectMapQuery(family_id="action"))
    by_provider = service.query(ObjectMapQuery(provider_id="provider.tasks"))
    by_owner = service.query(ObjectMapQuery(owner_domain="gui"))
    by_relationship = service.query(ObjectMapQuery(relationship_type="references"))

    assert [summary.object_ref.object_id for summary in by_object.summaries] == [
        "task-1"
    ]
    assert [summary.object_ref.object_id for summary in by_kind.summaries] == [
        "operation-1"
    ]
    assert [summary.object_ref.object_id for summary in by_family.summaries] == [
        "action-1"
    ]
    assert [section.provider_id for section in by_provider.sections] == [
        "provider.tasks"
    ]
    assert [summary.object_ref.owner_domain for summary in by_owner.summaries] == [
        "gui"
    ]
    assert [relationship.relationship_type for relationship in by_relationship.relationships] == [
        "references"
    ]


def test_query_flags_omit_selected_report_material() -> None:
    section = _section(
        provider_id="provider.a",
        section_id="section.a",
        summaries=(_summary("task-1", "task"),),
        relationships=(_relationship(),),
    )
    service = ReadOnlyObjectMapService((_provider("provider.a", section),))

    report = service.query(
        ObjectMapQuery(
            include_summaries=False,
            include_relationships=False,
            include_provider_descriptors=False,
        )
    )

    assert report.summaries == ()
    assert report.relationships == ()
    assert report.provider_descriptors == ()
    assert report.sections[0].summaries == ()
    assert report.sections[0].relationships == ()


def test_provider_failures_are_reported_without_stopping_other_sources() -> None:
    good_section = _section(provider_id="provider.good", section_id="section.good")

    def fail() -> ObjectMapSection:
        raise RuntimeError("provider unavailable")

    service = ReadOnlyObjectMapService(
        (
            _provider("provider.good", good_section),
            ObjectMapProviderEntry(
                descriptor=_descriptor("provider.failed"),
                build_section=fail,
            ),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc=_TEST_TIME)

    assert [section.section_id for section in snapshot.sections] == ["section.good"]
    assert any("provider.failed" in error for error in snapshot.errors)
    assert any("provider unavailable" in error for error in snapshot.errors)
    assert {descriptor.provider_id for descriptor in snapshot.provider_descriptors} == {
        "provider.failed",
        "provider.good",
    }


def test_provider_failure_diagnostic_is_bounded_and_has_no_traceback() -> None:
    long_secret_message = "prefix " + ("x" * 500)

    def fail() -> ObjectMapSection:
        raise RuntimeError(long_secret_message)

    snapshot = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=_descriptor("provider.failed"),
                build_section=fail,
            ),
        )
    ).build_snapshot(generated_at_utc=_TEST_TIME)

    assert len(snapshot.errors) == 1
    error = snapshot.errors[0]
    assert len(error) <= 230
    assert "RuntimeError" in error
    assert "..." in error
    assert "Traceback" not in error
    assert "x" * 200 not in error


def test_provider_failure_diagnostic_redacts_sensitive_values() -> None:
    sensitive_message = (
        "password=hunter2 token=tok-123 "
        "api_key=api-456 authorization: Bearer auth-789 "
        "credential=cred-000 secret=secret-111 passwd=pass-222"
    )

    def fail() -> ObjectMapSection:
        raise RuntimeError(sensitive_message)

    snapshot = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=_descriptor("provider.failed"),
                build_section=fail,
            ),
        )
    ).build_snapshot(generated_at_utc=_TEST_TIME)

    error = snapshot.errors[0]
    assert "[redacted]" in error
    for sensitive_value in (
        "hunter2",
        "tok-123",
        "api-456",
        "auth-789",
        "cred-000",
        "secret-111",
        "pass-222",
    ):
        assert sensitive_value not in error


def test_query_with_no_matching_object_returns_valid_empty_report() -> None:
    section = _section(
        provider_id="provider.a",
        section_id="section.a",
        summaries=(_summary("task-1", "task"),),
    )
    service = ReadOnlyObjectMapService((_provider("provider.a", section),))

    report = service.query(
        ObjectMapQuery(
            object_id="missing-object",
            include_provider_descriptors=False,
        )
    )

    assert isinstance(report, ObjectMapQueryReport)
    assert report.sections == ()
    assert report.summaries == ()
    assert report.relationships == ()
    assert report.provider_descriptors == ()
    assert report.errors == ()


def test_duplicate_section_and_object_ids_are_reported_without_dropping_output() -> None:
    first_section = _section(
        provider_id="provider.a",
        section_id="duplicate-section",
        summaries=(_summary("duplicate-object", "task"),),
    )
    second_section = _section(
        provider_id="provider.b",
        section_id="duplicate-section",
        summaries=(_summary("duplicate-object", "operation"),),
    )

    snapshot = ReadOnlyObjectMapService(
        (
            _provider("provider.a", first_section),
            _provider("provider.b", second_section, object_kinds=("operation",)),
        )
    ).build_snapshot(generated_at_utc=_TEST_TIME)

    assert len(snapshot.sections) == 2
    assert any("duplicate-section" in warning for warning in snapshot.warnings)
    assert any("duplicate-object" in warning for warning in snapshot.warnings)


def test_provider_id_must_be_unique_and_section_provider_must_match_descriptor() -> None:
    section = _section(provider_id="provider.a", section_id="section.a")

    with pytest.raises(ValueError, match="Duplicate Object Map provider_id"):
        ReadOnlyObjectMapService(
            (
                _provider("provider.a", section),
                _provider("provider.a", section),
            )
        )

    mismatched = ReadOnlyObjectMapService(
        (_provider("provider.b", section),)
    ).build_snapshot(generated_at_utc=_TEST_TIME)
    assert mismatched.sections == ()
    assert any("emitted section section.a" in error for error in mismatched.errors)


def test_existing_trace_sections_can_be_consumed_through_explicit_sources() -> None:
    service = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=build_task_operation_trace_provider_descriptor(),
                build_section=lambda: build_task_operation_trace_section(
                    task_states=(),
                    operation_states=(),
                ),
            ),
            ObjectMapProviderEntry(
                descriptor=build_runtime_registry_trace_provider_descriptor(),
                build_section=lambda: build_runtime_registry_trace_section(
                    registered_services=(),
                    service_states=(),
                    contract_descriptors=(),
                    error_reports=(),
                ),
            ),
            ObjectMapProviderEntry(
                descriptor=build_process_connection_trace_provider_descriptor(),
                build_section=lambda: build_process_connection_trace_section(
                    process_states=(),
                    connection_states=(),
                    websocket_channel_states=(),
                    connection_definitions=(),
                    websocket_channel_definitions=(),
                ),
            ),
            ObjectMapProviderEntry(
                descriptor=build_audit_event_trace_provider_descriptor(),
                build_section=lambda: build_audit_event_trace_section(audit_events=()),
            ),
            ObjectMapProviderEntry(
                descriptor=build_window_trace_provider_descriptor(),
                build_section=build_window_trace_section,
            ),
            ObjectMapProviderEntry(
                descriptor=build_action_trace_provider_descriptor(),
                build_section=build_action_trace_section,
            ),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc=_TEST_TIME)

    assert {
        descriptor.provider_id for descriptor in snapshot.provider_descriptors
    } == {
        ACTION_TRACE_PROVIDER_ID,
        AUDIT_EVENT_TRACE_PROVIDER_ID,
        PROCESS_CONNECTION_TRACE_PROVIDER_ID,
        RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
        TASK_OPERATION_TRACE_PROVIDER_ID,
        WINDOW_TRACE_PROVIDER_ID,
    }
    assert {section.provider_id for section in snapshot.sections} == {
        ACTION_TRACE_PROVIDER_ID,
        AUDIT_EVENT_TRACE_PROVIDER_ID,
        PROCESS_CONNECTION_TRACE_PROVIDER_ID,
        RUNTIME_REGISTRY_TRACE_PROVIDER_ID,
        TASK_OPERATION_TRACE_PROVIDER_ID,
        WINDOW_TRACE_PROVIDER_ID,
    }


def test_service_module_does_not_wire_runtime_manager_or_scan_or_import_sources() -> None:
    source = _OBJECT_MAP_SERVICE.read_text(encoding="utf-8")

    blocked_tokens = (
        "from leonardo.core.task_manager",
        "from leonardo.core.operation_registry",
        "from leonardo.core.state_store",
        "from leonardo.core.audit_log",
        "from leonardo.core.process_manager",
        "from leonardo.core.connection_registry",
        "from leonardo.gui",
        "RuntimeManagerBackend(",
        "CoreRuntimeBridge(",
        "CoreRunner(",
        "DownloadManager(",
        "DownloadExecutionManager(",
        "def discover",
        ".discover",
        "discover(",
        "register_provider",
        "importlib",
        "os.walk",
        ".glob(",
        ".rglob(",
        "QApplication",
        "subprocess",
        "shell=True",
        "requests",
        "aiohttp",
        "websockets",
        "socket.",
    )
    for token in blocked_tokens:
        assert token not in source


def _provider(
    provider_id: str,
    section: ObjectMapSection,
    *,
    object_kinds: tuple[str, ...] = ("task",),
    family_ids: tuple[str, ...] = ("task",),
    relationship_types: tuple[str, ...] = ("references",),
    owner_domain: str = "core",
) -> ObjectMapProviderEntry:
    return ObjectMapProviderEntry(
        descriptor=_descriptor(
            provider_id,
            object_kinds=object_kinds,
            family_ids=family_ids,
            relationship_types=relationship_types,
            owner_domain=owner_domain,
        ),
        build_section=lambda: section,
    )


def _descriptor(
    provider_id: str,
    *,
    object_kinds: tuple[str, ...] = ("task",),
    family_ids: tuple[str, ...] = ("task",),
    relationship_types: tuple[str, ...] = ("references",),
    owner_domain: str = "core",
) -> ObjectMapProviderDescriptor:
    return ObjectMapProviderDescriptor(
        provider_id=provider_id,
        provider_name=provider_id,
        owner_domain=owner_domain,
        owner_component="test provider",
        object_kinds=object_kinds,
        family_ids=family_ids,
        relationship_types=relationship_types,
        related_docs=("docs/contracts_docs/OBJECT_MAP_PROTOCOL.md",),
        related_tests=("tests/core_test/test_object_map_readonly_service.py",),
    )


def _section(
    *,
    provider_id: str = "provider.a",
    section_id: str = "section.a",
    owner_domain: str = "core",
    summaries: tuple[TraceableObjectSummary, ...] | None = None,
    relationships: tuple[TraceableRelationshipRef, ...] = (),
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> ObjectMapSection:
    resolved_summaries = summaries or (_summary("task-1", "task"),)
    resolved_relationships = relationships or tuple(
        relationship
        for summary in resolved_summaries
        for relationship in summary.relationship_refs
    )
    return ObjectMapSection(
        section_id=section_id,
        provider_id=provider_id,
        owner_domain=owner_domain,
        object_kind=None,
        family_id=None,
        title=section_id,
        summaries=resolved_summaries,
        relationships=resolved_relationships,
        warnings=warnings,
        errors=errors,
        metadata={"section_id": section_id},
        extra={"read_only": True, "mutation_forbidden": True},
    )


def _summary(
    object_id: str,
    object_kind: str,
    *,
    owner_domain: str = "core",
    relationship_refs: tuple[TraceableRelationshipRef, ...] = (),
) -> TraceableObjectSummary:
    return TraceableObjectSummary(
        object_ref=TraceableObjectRef(
            object_id=object_id,
            object_kind=object_kind,
            owner_domain=owner_domain,
            owner_component="test owner",
            label=object_id,
            metadata={"family_id": object_kind},
        ),
        lifecycle_status="active",
        runtime_or_persistent="runtime",
        display_name=object_id,
        metadata={"family_id": object_kind},
        relationship_refs=relationship_refs,
        extra={"read_only": True, "mutation_forbidden": True},
    )


def _relationship(
    *,
    relationship_type: str = "references",
    source_id: str = "task-1",
    source_kind: str = "task",
    target_id: str = "operation-1",
    target_kind: str = "operation",
) -> TraceableRelationshipRef:
    return TraceableRelationshipRef(
        relationship_id=f"{source_id}.{relationship_type}.{target_id}",
        relationship_type=relationship_type,
        source_ref=TraceableObjectRef(
            object_id=source_id,
            object_kind=source_kind,
            owner_domain="core",
            owner_component="test source",
        ),
        target_ref=TraceableObjectRef(
            object_id=target_id,
            object_kind=target_kind,
            owner_domain="core",
            owner_component="test target",
        ),
        lifecycle_status="active",
    )
