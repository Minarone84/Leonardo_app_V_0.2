from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.traceable_object import (
    ObjectFamilyLegend,
    ObjectInterrogationReport,
    ObjectInterrogationRequest,
    TraceableObjectRef,
    TraceableObjectSummary,
    TraceableRelationshipRef,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACEABLE_OBJECT_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "traceable_object.py"
)


def test_traceable_object_ref_validates_required_fields() -> None:
    with pytest.raises(ValueError, match="object_id"):
        TraceableObjectRef(
            object_id="",
            object_kind="window",
            owner_domain="gui",
        )
    with pytest.raises(ValueError, match="object_kind"):
        TraceableObjectRef(
            object_id="main_window",
            object_kind=" ",
            owner_domain="gui",
        )
    with pytest.raises(ValueError, match="owner_domain"):
        TraceableObjectRef(
            object_id="main_window",
            object_kind="window",
            owner_domain="",
        )


def test_traceable_object_ref_round_trips_to_and_from_dict() -> None:
    ref = TraceableObjectRef(
        object_id="main_window",
        object_kind="window",
        owner_domain="gui",
        owner_component="WindowRegistry",
        schema_version="1.0",
        label="Main Window",
        metadata={"tags": ["shell", "visible"]},
    )

    serialized = ref.to_dict()
    loaded = TraceableObjectRef.from_dict(serialized)

    assert serialized["metadata"] == {"tags": ["shell", "visible"]}
    assert loaded == ref
    assert loaded.metadata["tags"] == ("shell", "visible")
    with pytest.raises(TypeError):
        loaded.metadata["tags"] = ()  # type: ignore[index]


def test_traceable_relationship_ref_normalizes_source_and_target_refs() -> None:
    source = TraceableObjectRef(
        object_id="action.download.open",
        object_kind="action",
        owner_domain="gui",
    )
    target = {
        "object_id": "operation-1",
        "object_kind": "operation",
        "owner_domain": "core",
    }

    relationship = TraceableRelationshipRef(
        relationship_id="relationship-1",
        relationship_type="creates_operation",
        source_ref=source,
        target_ref=target,
        direction="outbound",
        operation_id="operation-1",
        metadata={"confidence": "explicit"},
    )

    assert relationship.source_ref is source
    assert isinstance(relationship.target_ref, TraceableObjectRef)
    assert relationship.target_ref.object_id == "operation-1"
    assert relationship.metadata["confidence"] == "explicit"


def test_traceable_relationship_ref_rejects_missing_type_or_invalid_refs() -> None:
    ref = TraceableObjectRef(
        object_id="main_window",
        object_kind="window",
        owner_domain="gui",
    )

    with pytest.raises(ValueError, match="relationship_type"):
        TraceableRelationshipRef(
            relationship_type="",
            source_ref=ref,
            target_ref=ref,
        )
    with pytest.raises(TypeError, match="source_ref"):
        TraceableRelationshipRef(
            relationship_type="references",
            source_ref="main_window",  # type: ignore[arg-type]
            target_ref=ref,
        )


def test_traceable_object_summary_preserves_common_envelope_fields() -> None:
    ref = TraceableObjectRef(
        object_id="task-1",
        object_kind="task",
        owner_domain="core",
    )
    relationship = TraceableRelationshipRef(
        relationship_type="depends_on",
        source_ref=ref,
        target_ref={
            "object_id": "operation-1",
            "object_kind": "operation",
            "owner_domain": "core",
        },
    )

    summary = TraceableObjectSummary(
        object_ref=ref,
        lifecycle_status="running",
        runtime_or_persistent="runtime",
        created_or_registered_at_utc="2026-07-06T12:00:00+00:00",
        updated_at_utc="2026-07-06T12:01:00+00:00",
        display_name="Task 1",
        metadata_ref="state_store.task.task-1",
        metadata={"status_source": "StateStore"},
        relationship_refs=(relationship,),
        permission_refs=("task:view",),
        audit_refs=("event-1",),
        operation_refs=("operation-1",),
        task_refs=("task-1",),
        source_refs=("CoreRuntimeBridge",),
        correlation_refs=("correlation-1",),
    )

    assert summary.object_ref is ref
    assert summary.relationship_refs == (relationship,)
    assert summary.permission_refs == ("task:view",)
    assert summary.audit_refs == ("event-1",)
    assert summary.runtime_or_persistent == "runtime"


def test_traceable_object_summary_preserves_family_specific_extra() -> None:
    summary = TraceableObjectSummary(
        object_ref={
            "object_id": "download-request-1",
            "object_kind": "download_request",
            "owner_domain": "downloads",
        },
        lifecycle_status="validated",
        runtime_or_persistent="temporary",
        extra={"provider": "bybit", "symbols": ["BTCUSDT", "ETHUSDT"]},
    )

    assert summary.extra["provider"] == "bybit"
    assert summary.extra["symbols"] == ("BTCUSDT", "ETHUSDT")


def test_traceable_object_summary_round_trips_without_mutating_metadata() -> None:
    metadata = {"nested": {"owner": "StateStore"}, "labels": ["runtime"]}
    summary = TraceableObjectSummary(
        object_ref={
            "object_id": "connection-1",
            "object_kind": "connection",
            "owner_domain": "core",
        },
        lifecycle_status="connected",
        runtime_or_persistent="runtime",
        metadata=metadata,
        permission_refs=("connection:view",),
    )
    metadata["nested"] = {"owner": "changed"}
    metadata["labels"] = ["changed"]

    loaded = TraceableObjectSummary.from_dict(summary.to_dict())

    assert loaded.metadata["nested"]["owner"] == "StateStore"
    assert loaded.metadata["labels"] == ("runtime",)
    assert loaded.permission_refs == ("connection:view",)


def test_object_family_legend_validates_family_identity_and_owner_fields() -> None:
    with pytest.raises(ValueError, match="family_id"):
        _window_legend(family_id="")
    with pytest.raises(ValueError, match="object_kind"):
        _window_legend(object_kind=" ")
    with pytest.raises(ValueError, match="owner_domain"):
        _window_legend(owner_domain="")
    with pytest.raises(ValueError, match="owner_component"):
        _window_legend(owner_component="")


def test_object_family_legend_supports_flexible_family_metadata_fields() -> None:
    legend = _window_legend(
        metadata_fields=("metadata_id", "title", "geometry_policy"),
        relationships_out=("triggers", "creates_operation"),
        extra={"read_only_surface": True, "display_sections": ["summary", "actions"]},
    )
    loaded = ObjectFamilyLegend.from_dict(legend.to_dict())

    assert loaded.required_identity_fields == ("window_id",)
    assert loaded.metadata_fields == ("metadata_id", "title", "geometry_policy")
    assert loaded.relationships_out == ("triggers", "creates_operation")
    assert loaded.extra["display_sections"] == ("summary", "actions")


def test_object_interrogation_request_is_read_only_and_target_ref_based() -> None:
    request = ObjectInterrogationRequest(
        target_ref={
            "object_id": "main_window",
            "object_kind": "window",
            "owner_domain": "gui",
        },
        include_audit_refs=False,
        requester_actor_id="admin-dev",
        requester_session_id="session-admin-dev",
        metadata={"reason": "inspect"},
    )

    assert request.target_ref.object_id == "main_window"
    assert request.include_audit_refs is False
    assert request.metadata["reason"] == "inspect"
    with pytest.raises(FrozenInstanceError):
        request.include_docs = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.metadata["reason"] = "changed"  # type: ignore[index]


def test_object_interrogation_report_carries_read_only_trace_sections() -> None:
    target_ref = TraceableObjectRef(
        object_id="main_window",
        object_kind="window",
        owner_domain="gui",
    )
    summary = TraceableObjectSummary(
        object_ref=target_ref,
        lifecycle_status="visible",
        runtime_or_persistent="hybrid",
    )
    legend = _window_legend()
    relationship = TraceableRelationshipRef(
        relationship_type="triggers",
        source_ref=target_ref,
        target_ref={
            "object_id": "action.runtime_manager.open",
            "object_kind": "action",
            "owner_domain": "gui",
        },
    )

    report = ObjectInterrogationReport(
        target_ref=target_ref,
        summary=summary,
        family_legend=legend,
        relationships=(relationship,),
        permissions=("runtime:view",),
        audit_refs=("event-1",),
        runtime_refs=("window.main_window",),
        docs=("docs/contracts_docs/TRACEABLE_OBJECTS.md",),
        tests=("tests/contracts_test/test_traceable_object_contracts.py",),
        warnings=("No Object Map provider is implemented yet.",),
        blockers=("Domain family legends are not registered yet.",),
        errors=("example-error-ref",),
        metadata={"read_only": True},
    )
    loaded = ObjectInterrogationReport.from_dict(report.to_dict())

    assert loaded.summary is not None
    assert loaded.family_legend is not None
    assert loaded.relationships == (relationship,)
    assert loaded.permissions == ("runtime:view",)
    assert loaded.docs == ("docs/contracts_docs/TRACEABLE_OBJECTS.md",)
    assert loaded.tests == ("tests/contracts_test/test_traceable_object_contracts.py",)
    assert loaded.warnings == ("No Object Map provider is implemented yet.",)
    assert loaded.blockers == ("Domain family legends are not registered yet.",)
    assert loaded.errors == ("example-error-ref",)


def test_traceable_object_contracts_are_generic_and_have_no_domain_execution() -> None:
    source = _TRACEABLE_OBJECT_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "ObjectMapProvider",
        "RuntimeManagerBackend",
        "DownloadManager",
        "TaskManager",
        "OperationRegistry",
        "ConnectionRegistry",
        "StateStore",
        "AuditLog(",
        "QApplication",
        "QtWidgets",
    )

    for token in blocked_tokens:
        assert token not in source


def test_traceable_object_contract_imports_no_core_or_gui() -> None:
    source = _TRACEABLE_OBJECT_CONTRACT.read_text(encoding="utf-8")
    blocked_imports = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "from leonardo." + "gui",
        "import leonardo." + "gui",
    )

    for blocked_import in blocked_imports:
        assert blocked_import not in source


def test_traceable_object_contract_has_no_runtime_io_or_dependency_imports() -> None:
    source = _TRACEABLE_OBJECT_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    for token in blocked_tokens:
        assert token not in source


def _window_legend(
    *,
    family_id: str = "gui.window",
    object_kind: str = "window",
    owner_domain: str = "gui",
    owner_component: str = "WindowRegistry",
    metadata_fields: tuple[str, ...] = (),
    relationships_out: tuple[str, ...] = (),
    extra: dict[str, object] | None = None,
) -> ObjectFamilyLegend:
    return ObjectFamilyLegend(
        family_id=family_id,
        object_kind=object_kind,
        owner_domain=owner_domain,
        owner_component=owner_component,
        mutation_owner="GUI composition and WindowRegistry",
        read_provider="RuntimeManagerBackend and future Object Map",
        runtime_or_persistent="hybrid",
        truth_source="GUI metadata plus StateStore window runtime state",
        required_identity_fields=("window_id",),
        optional_identity_fields=("metadata_id",),
        metadata_fields=metadata_fields,
        lifecycle_statuses=("registered", "visible", "closed"),
        allowed_actions=("inspect",),
        permission_refs=("runtime:view",),
        audit_event_types=("gui.window.registered", "gui.window.closed"),
        relationships_in=("references",),
        relationships_out=relationships_out,
        related_contracts=("leonardo.gui.window_definition",),
        related_docs=("docs/contracts_docs/TRACEABLE_OBJECTS.md",),
        related_tests=("tests/contracts_test/test_traceable_object_contracts.py",),
        extra=extra or {},
    )
