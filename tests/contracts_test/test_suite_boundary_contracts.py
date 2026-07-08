from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.identity import Permission
from leonardo.contracts.suite_boundary import (
    AreaDescriptor,
    AreaKind,
    SuiteAuditPolicy,
    SuiteCachePolicy,
    SuiteCommandDescriptor,
    SuiteCommandKind,
    SuiteDescriptor,
    SuiteLifecycleStatus,
    SuiteModuleDescriptor,
    SuiteQueryDescriptor,
    SuiteQueryKind,
    SuiteRuntimePolicy,
    SuiteTaskBehavior,
)
from leonardo.contracts.traceable_object import TraceableObjectRef


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SUITE_BOUNDARY_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "suite_boundary.py"
)
_SUITE_BOUNDARY_DOC = _REPO_ROOT / "docs" / "contracts_docs" / "SUITE_BOUNDARY.md"


def test_area_descriptor_constructs_with_normalized_tuples() -> None:
    descriptor = AreaDescriptor(
        area_id="data_acquisition",
        display_name="Data Acquisition",
        description="Shared data acquisition area.",
        area_kind="workflow",
        owner_domain="data_manager",
        owner_component="DataAcquisitionBoundary",
        module_ids=["download_data"],  # type: ignore[arg-type]
        object_family_ids=("download_request", "download_preflight"),
        command_ids=("download.preview",),
        query_ids=["download.capabilities"],  # type: ignore[arg-type]
        required_permissions=(Permission.DOWNLOAD_VIEW, "download:preview"),
        audit_categories=["download.preview"],  # type: ignore[arg-type]
        docs_refs=["docs/contracts_docs/SUITE_BOUNDARY.md"],  # type: ignore[arg-type]
    )

    assert descriptor.area_kind is AreaKind.WORKFLOW
    assert descriptor.lifecycle_status is SuiteLifecycleStatus.PLANNED
    assert descriptor.module_ids == ("download_data",)
    assert descriptor.query_ids == ("download.capabilities",)
    assert descriptor.required_permissions == ("download:view", "download:preview")
    assert descriptor.audit_categories == ("download.preview",)
    assert descriptor.docs_refs == ("docs/contracts_docs/SUITE_BOUNDARY.md",)


def test_suite_descriptor_constructs_with_normalized_tuples() -> None:
    descriptor = SuiteDescriptor(
        suite_id="analysis",
        display_name="Analysis Suite",
        description="Future analysis suite boundary.",
        owner_domain="analysis",
        owner_component="AnalysisSuiteBoundary",
        lifecycle_status="planned",
        area_ids=["analysis_workspace"],  # type: ignore[arg-type]
        module_ids=("analysis_runs",),
        supported_command_ids=("analysis.run",),
        supported_query_ids=["analysis.summary"],  # type: ignore[arg-type]
        object_family_ids=("analysis_run",),
        required_permissions=(Permission.ANALYSIS_VIEW,),
    )

    assert descriptor.lifecycle_status is SuiteLifecycleStatus.PLANNED
    assert descriptor.area_ids == ("analysis_workspace",)
    assert descriptor.supported_query_ids == ("analysis.summary",)
    assert descriptor.required_permissions == ("analysis:view",)


def test_suite_module_descriptor_requires_suite_or_area_owner() -> None:
    with pytest.raises(ValueError, match="suite_id or area_id"):
        SuiteModuleDescriptor(
            module_id="download_data",
            display_name="Download Data",
            description="Future Download Data module.",
            owner_domain="download",
            owner_component="DownloadDataBoundary",
        )

    module = SuiteModuleDescriptor(
        module_id="download_data",
        area_id="data_acquisition",
        display_name="Download Data",
        description="Future Download Data module.",
        owner_domain="download",
        owner_component="DownloadDataBoundary",
        lifecycle_status="planned",
        command_ids=["download.preview"],  # type: ignore[arg-type]
        query_ids=("download.capabilities",),
        required_permissions=("download:view",),
    )

    assert module.area_id == "data_acquisition"
    assert module.suite_id is None
    assert module.command_ids == ("download.preview",)


def test_suite_command_descriptor_requires_command_id() -> None:
    with pytest.raises(ValueError, match="command_id"):
        _command(command_id="")


def test_suite_command_descriptor_requires_required_permission() -> None:
    with pytest.raises(ValueError, match="required_permission"):
        _command(required_permission="")


def test_suite_command_descriptor_does_not_execute_anything() -> None:
    descriptor = _command(
        command_kind=SuiteCommandKind.INTENT,
        creates_operation=False,
        expected_task_behavior=SuiteTaskBehavior.NONE,
        runtime_policy=SuiteRuntimePolicy.NONE,
    )

    assert descriptor.command_kind is SuiteCommandKind.INTENT
    assert descriptor.creates_operation is False
    assert not hasattr(descriptor, "execute")
    assert not hasattr(descriptor, "start")
    assert not hasattr(descriptor, "submit")


def test_suite_command_descriptor_requires_operations_for_runtime_backed_work() -> None:
    with pytest.raises(ValueError, match="must create operations"):
        _command(
            command_kind=SuiteCommandKind.LONG_RUNNING,
            creates_operation=False,
            expected_task_behavior=SuiteTaskBehavior.TASK_EXPECTED,
            runtime_policy=SuiteRuntimePolicy.CORE_RUNTIME_REQUIRED,
        )


def test_suite_command_descriptor_references_gui_actions_without_importing_gui() -> None:
    descriptor = _command(
        related_action_ids=["action.download.preview"],  # type: ignore[arg-type]
        object_family_ids=("download_request", "download_preflight"),
        object_refs=(
            TraceableObjectRef(
                object_id="download_request:preview",
                object_kind="download_request",
                owner_domain="download",
            ),
            {
                "object_id": "action.download.preview",
                "object_kind": "action",
                "owner_domain": "gui",
            },
        ),
    )

    assert descriptor.related_action_ids == ("action.download.preview",)
    assert descriptor.object_family_ids == ("download_request", "download_preflight")
    assert descriptor.object_refs[0].object_kind == "download_request"
    assert descriptor.object_refs[1].owner_domain == "gui"


def test_suite_query_descriptor_constructs_read_only_query_metadata() -> None:
    descriptor = SuiteQueryDescriptor(
        query_id="download.capability.summary",
        query_kind="local_read_model",
        label="Capability Summary",
        description="Read-only provider capability summary.",
        required_permission=Permission.DOWNLOAD_VIEW,
        read_model_kind="download_capability",
        area_id="data_acquisition",
        module_id="download_data",
        object_family_ids=["download_capability"],  # type: ignore[arg-type]
        cache_policy="snapshot",
        audit_policy="summary",
        allowed_callers=("gui", "runtime_manager"),
    )

    assert descriptor.query_kind is SuiteQueryKind.LOCAL_READ_MODEL
    assert descriptor.required_permission == "download:view"
    assert descriptor.cache_policy is SuiteCachePolicy.SNAPSHOT
    assert descriptor.audit_policy is SuiteAuditPolicy.SUMMARY
    assert descriptor.object_family_ids == ("download_capability",)
    assert descriptor.allowed_callers == ("gui", "runtime_manager")
    assert not hasattr(descriptor, "run")
    assert not hasattr(descriptor, "execute")


def test_suite_query_descriptor_requires_query_id() -> None:
    with pytest.raises(ValueError, match="query_id"):
        SuiteQueryDescriptor(
            query_id="",
            query_kind=SuiteQueryKind.LOCAL_READ_MODEL,
            label="Summary",
            description="Read-only summary.",
            required_permission="runtime:view",
            read_model_kind="runtime",
            area_id="core_runtime",
        )


def test_descriptor_objects_are_frozen_read_only() -> None:
    descriptor = _command()

    with pytest.raises(FrozenInstanceError):
        descriptor.command_id = "changed"  # type: ignore[misc]


def test_sequence_inputs_normalize_to_tuples() -> None:
    descriptor = _query(
        object_family_ids=["window", "action"],  # type: ignore[arg-type]
        allowed_callers=["gui"],  # type: ignore[arg-type]
        warnings=["read-only"],  # type: ignore[arg-type]
        blockers=["none"],  # type: ignore[arg-type]
    )

    assert descriptor.object_family_ids == ("window", "action")
    assert descriptor.allowed_callers == ("gui",)
    assert descriptor.warnings == ("read-only",)
    assert descriptor.blockers == ("none",)


def test_empty_required_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="area_id"):
        AreaDescriptor(
            area_id="",
            display_name="Runtime",
            description="Runtime area.",
            area_kind=AreaKind.INFRASTRUCTURE,
            owner_domain="core",
            owner_component="RuntimeBoundary",
        )
    with pytest.raises(ValueError, match="suite_id"):
        SuiteDescriptor(
            suite_id=" ",
            display_name="Research Suite",
            description="Research boundary.",
            owner_domain="research",
            owner_component="ResearchSuiteBoundary",
        )
    with pytest.raises(ValueError, match="module_id"):
        SuiteModuleDescriptor(
            module_id="",
            suite_id="research",
            display_name="Projects",
            description="Research projects.",
            owner_domain="research",
            owner_component="ResearchProjectsBoundary",
        )


def test_permission_names_remain_area_scoped_strings_not_dynamic_suite_names() -> None:
    descriptor = _command(required_permission=Permission.DOWNLOAD_SUBMIT)

    assert descriptor.required_permission == "download:submit"

    with pytest.raises(ValueError, match="established area permission"):
        _command(required_permission="suite" + ":execute")


def test_download_data_can_be_workflow_module_without_becoming_suite() -> None:
    area = AreaDescriptor(
        area_id="download_data",
        display_name="Download Data",
        description="Future Download Data workflow.",
        area_kind=AreaKind.WORKFLOW,
        owner_domain="download",
        owner_component="DownloadDataBoundary",
        module_ids=("download_data",),
        required_permissions=("download:view", "download:submit"),
    )
    module = SuiteModuleDescriptor(
        module_id="download_data",
        area_id=area.area_id,
        display_name="Download Data",
        description="Future workflow module under a data acquisition area.",
        owner_domain="download",
        owner_component="DownloadDataBoundary",
    )

    assert area.area_kind is AreaKind.WORKFLOW
    assert module.suite_id is None
    assert module.area_id == "download_data"


def test_provider_connection_can_be_infrastructure_capability_area_not_suite() -> None:
    provider_area = AreaDescriptor(
        area_id="provider_connection",
        display_name="Provider Connection",
        description="Shared provider and connection capability boundary.",
        area_kind=AreaKind.INFRASTRUCTURE,
        owner_domain="connection",
        owner_component="ProviderConnectionBoundary",
        object_family_ids=("connection", "provider_session"),
        required_permissions=(Permission.CONNECTION_VIEW,),
    )
    capability_area = AreaDescriptor(
        area_id="provider_capability",
        display_name="Provider Capability",
        description="Static provider capability boundary.",
        area_kind="capability",
        owner_domain="connection",
        owner_component="ProviderCapabilityBoundary",
    )

    assert provider_area.area_kind is AreaKind.INFRASTRUCTURE
    assert capability_area.area_kind is AreaKind.CAPABILITY
    assert provider_area.suite_id is None


def test_suite_boundary_contracts_do_not_import_core_gui_or_concrete_suites() -> None:
    source = _SUITE_BOUNDARY_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "from leonardo." + "gui",
        "import leonardo." + "gui",
        "PySide6",
        "PyQt6",
        "QtWidgets",
        "QtCore",
        "QtGui",
        "ResearchSuite(",
        "DataManagerSuite(",
        "AnalysisSuite(",
        "TradingSuite(",
        "Task" + "Manager",
        "Operation" + "Registry",
        "State" + "Store",
        "Audit" + "Log",
        "Runtime" + "Manager",
        "ReadOnly" + "ObjectMapService",
        "CoreRuntime" + "Bridge",
        "Core" + "Runner",
        "Download" + "Manager(",
        "DownloadExecution" + "Manager(",
        "sub" + "process",
        "soc" + "ket.",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "shell" + "=True",
    )

    for token in blocked_tokens:
        assert token not in source


def test_suite_boundary_docs_explain_ownership_and_forbidden_behavior() -> None:
    doc = _SUITE_BOUNDARY_DOC.read_text(encoding="utf-8")

    assert "area is the generic architecture term" in doc
    assert "Download Data is a workflow/module under the Download Manager area" in doc
    assert "Provider/Connection is shared infrastructure" in doc
    assert "No mutable SuiteRegistry exists in this phase" in doc
    assert "Suite Object Map provider patterns are read-only" in doc
    assert "Runtime Manager suite summaries are read-only" in doc


def _command(
    *,
    command_id: str = "download.preview",
    command_kind: SuiteCommandKind | str = SuiteCommandKind.LONG_RUNNING,
    required_permission: Permission | str = Permission.DOWNLOAD_PREVIEW,
    creates_operation: bool = True,
    expected_task_behavior: SuiteTaskBehavior | str = SuiteTaskBehavior.TASK_EXPECTED,
    runtime_policy: SuiteRuntimePolicy | str = SuiteRuntimePolicy.CORE_RUNTIME_REQUIRED,
    related_action_ids=(),
    object_family_ids=(),
    object_refs=(),
) -> SuiteCommandDescriptor:
    return SuiteCommandDescriptor(
        command_id=command_id,
        command_kind=command_kind,
        label="Preview Download",
        description="Future Download Data preview command capability.",
        required_permission=required_permission,
        area_id="data_acquisition",
        module_id="download_data",
        creates_operation=creates_operation,
        expected_task_behavior=expected_task_behavior,
        cancellable=True,
        audit_category="download.preview",
        runtime_policy=runtime_policy,
        related_action_ids=related_action_ids,
        object_family_ids=object_family_ids,
        object_refs=object_refs,
        allowed_callers=("gui",),
        docs_refs=("docs/contracts_docs/SUITE_BOUNDARY.md",),
        test_refs=("tests/contracts_test/test_suite_boundary_contracts.py",),
    )


def _query(
    *,
    object_family_ids=(),
    allowed_callers=(),
    warnings=(),
    blockers=(),
) -> SuiteQueryDescriptor:
    return SuiteQueryDescriptor(
        query_id="runtime.window.summary",
        query_kind=SuiteQueryKind.LOCAL_READ_MODEL,
        label="Window Summary",
        description="Read-only window summary query descriptor.",
        required_permission="runtime:view",
        read_model_kind="window_runtime_summary",
        area_id="core_runtime",
        object_family_ids=object_family_ids,
        allowed_callers=allowed_callers,
        warnings=warnings,
        blockers=blockers,
    )
