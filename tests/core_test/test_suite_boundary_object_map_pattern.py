from pathlib import Path

from leonardo.contracts.identity import Permission
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.suite_boundary import (
    AreaDescriptor,
    AreaKind,
    SuiteCommandDescriptor,
    SuiteCommandKind,
    SuiteDescriptor,
    SuiteModuleDescriptor,
    SuiteQueryDescriptor,
    SuiteQueryKind,
    SuiteRuntimePolicy,
    SuiteTaskBehavior,
)
from leonardo.core.object_map_service import (
    ObjectMapProviderEntry,
    ReadOnlyObjectMapService,
)
from leonardo.core.suite_boundary_trace import (
    AREA_OBJECT_KIND,
    SUITE_BOUNDARY_TRACE_PROVIDER_ID,
    SUITE_COMMAND_OBJECT_KIND,
    SUITE_MODULE_OBJECT_KIND,
    SUITE_OBJECT_KIND,
    SUITE_QUERY_OBJECT_KIND,
    area_trace_ref_from_descriptor,
    area_trace_summary_from_descriptor,
    build_suite_boundary_trace_provider_descriptor,
    build_suite_boundary_trace_section,
    suite_boundary_relationships_from_descriptors,
    suite_command_trace_ref_from_descriptor,
    suite_command_trace_summary_from_descriptor,
    suite_module_trace_ref_from_descriptor,
    suite_module_trace_summary_from_descriptor,
    suite_query_trace_ref_from_descriptor,
    suite_query_trace_summary_from_descriptor,
    suite_trace_ref_from_descriptor,
    suite_trace_summary_from_descriptor,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_HELPER = _REPO_ROOT / "src" / "leonardo" / "core" / "suite_boundary_trace.py"


def test_provider_descriptor_is_read_only_and_mutation_forbidden() -> None:
    descriptor = build_suite_boundary_trace_provider_descriptor()

    assert descriptor.provider_id == SUITE_BOUNDARY_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.owner_component == "SuiteBoundaryTrace"
    assert descriptor.object_kinds == (
        "area",
        "suite",
        "suite_module",
        "suite_command",
        "suite_query",
    )
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.supports_interrogation is False
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True


def test_area_descriptor_converts_to_ref_and_summary() -> None:
    area = _area()

    ref = area_trace_ref_from_descriptor(area)
    summary = area_trace_summary_from_descriptor(area)

    assert ref.object_id == "data_acquisition"
    assert ref.object_kind == AREA_OBJECT_KIND
    assert ref.owner_domain == "data_manager"
    assert ref.owner_component == "DataAcquisitionBoundary"
    assert ref.label == "Data Acquisition"
    assert summary.object_ref == ref
    assert summary.lifecycle_status == "planned"
    assert summary.runtime_or_persistent == "static_metadata"
    assert summary.metadata["area_kind"] == "workflow"
    assert summary.metadata["module_ids"] == ("download_data",)
    assert summary.permission_refs == ("download:view",)


def test_suite_descriptor_converts_to_ref_and_summary() -> None:
    suite = _suite()

    ref = suite_trace_ref_from_descriptor(suite)
    summary = suite_trace_summary_from_descriptor(suite)

    assert ref.object_id == "data_manager"
    assert ref.object_kind == SUITE_OBJECT_KIND
    assert ref.owner_domain == "data_manager"
    assert summary.metadata["area_ids"] == ("data_acquisition",)
    assert summary.metadata["supported_command_ids"] == ("download.preview",)
    assert summary.permission_refs == ("data_manager:view",)


def test_module_descriptor_converts_to_ref_and_summary() -> None:
    module = _module()

    ref = suite_module_trace_ref_from_descriptor(module)
    summary = suite_module_trace_summary_from_descriptor(module)

    assert ref.object_id == "download_data"
    assert ref.object_kind == SUITE_MODULE_OBJECT_KIND
    assert ref.owner_component == "DownloadDataBoundary"
    assert summary.metadata["suite_id"] == "data_manager"
    assert summary.metadata["area_id"] == "data_acquisition"
    assert summary.metadata["command_ids"] == ("download.preview",)


def test_command_descriptor_converts_to_ref_and_summary() -> None:
    area = _area()
    suite = _suite()
    module = _module()
    command = _command()

    ref = suite_command_trace_ref_from_descriptor(
        command,
        areas=(area,),
        suites=(suite,),
        modules=(module,),
    )
    summary = suite_command_trace_summary_from_descriptor(
        command,
        areas=(area,),
        suites=(suite,),
        modules=(module,),
    )

    assert ref.object_id == "download.preview"
    assert ref.object_kind == SUITE_COMMAND_OBJECT_KIND
    assert ref.owner_domain == "download"
    assert ref.owner_component == "DownloadDataBoundary"
    assert summary.metadata["command_kind"] == "long_running"
    assert summary.metadata["required_permission"] == "download:preview"
    assert summary.metadata["related_action_ids"] == ("action.download.preview",)
    assert summary.permission_refs == ("download:preview",)


def test_query_descriptor_converts_to_ref_and_summary() -> None:
    area = _area()
    suite = _suite()
    module = _module()
    query = _query()

    ref = suite_query_trace_ref_from_descriptor(
        query,
        areas=(area,),
        suites=(suite,),
        modules=(module,),
    )
    summary = suite_query_trace_summary_from_descriptor(
        query,
        areas=(area,),
        suites=(suite,),
        modules=(module,),
    )

    assert ref.object_id == "download.capability.summary"
    assert ref.object_kind == SUITE_QUERY_OBJECT_KIND
    assert ref.owner_domain == "download"
    assert summary.metadata["query_kind"] == "local_read_model"
    assert summary.metadata["read_model_kind"] == "download_capability"
    assert summary.metadata["cache_policy"] == "snapshot"
    assert summary.metadata["audit_policy"] == "summary"


def test_relationships_include_permissions_and_declared_descriptor_links() -> None:
    relationships = suite_boundary_relationships_from_descriptors(
        areas=(_area(),),
        suites=(_suite(),),
        modules=(_module(),),
        commands=(_command(),),
        queries=(_query(),),
    )
    pairs = {
        (
            relationship.relationship_type,
            relationship.source_ref.object_kind,
            relationship.source_ref.object_id,
            relationship.target_ref.object_kind,
            relationship.target_ref.object_id,
        )
        for relationship in relationships
    }

    assert (
        "references",
        "suite",
        "data_manager",
        "area",
        "data_acquisition",
    ) in pairs
    assert (
        "references",
        "suite",
        "data_manager",
        "suite_module",
        "download_data",
    ) in pairs
    assert (
        "references",
        "suite",
        "data_manager",
        "suite_command",
        "download.preview",
    ) in pairs
    assert (
        "references",
        "suite",
        "data_manager",
        "suite_query",
        "download.capability.summary",
    ) in pairs
    assert (
        "references",
        "suite_module",
        "download_data",
        "suite_command",
        "download.preview",
    ) in pairs
    assert (
        "references",
        "suite_module",
        "download_data",
        "suite_query",
        "download.capability.summary",
    ) in pairs
    assert (
        "references",
        "suite_command",
        "download.preview",
        "action",
        "action.download.preview",
    ) in pairs
    assert (
        "has_permission",
        "suite_command",
        "download.preview",
        "permission",
        "download:preview",
    ) in pairs
    assert (
        "has_permission",
        "suite_query",
        "download.capability.summary",
        "permission",
        "download:view",
    ) in pairs


def test_missing_optional_ids_do_not_create_fake_relationships() -> None:
    command = SuiteCommandDescriptor(
        command_id="download.preview",
        command_kind=SuiteCommandKind.LONG_RUNNING,
        label="Preview Download",
        description="Preview Download Data.",
        required_permission=Permission.DOWNLOAD_PREVIEW,
        area_id="missing_area",
        module_id="missing_module",
        creates_operation=True,
        expected_task_behavior=SuiteTaskBehavior.TASK_EXPECTED,
        runtime_policy=SuiteRuntimePolicy.CORE_RUNTIME_REQUIRED,
        audit_category="download.preview",
    )

    relationships = suite_boundary_relationships_from_descriptors(commands=(command,))

    assert all(
        relationship.target_ref.object_id not in {"missing_area", "missing_module"}
        for relationship in relationships
    )
    assert any(
        relationship.relationship_type == "has_permission"
        and relationship.target_ref.object_id == "download:preview"
        for relationship in relationships
    )


def test_download_data_can_appear_as_workflow_module_metadata_not_suite() -> None:
    section = build_suite_boundary_trace_section(
        areas=(_area(area_id="download_data", suite_id=None),),
        modules=(_module(suite_id=None),),
        commands=(_command(suite_id=None),),
        queries=(_query(suite_id=None),),
    )

    area_summary = _summary_by_id(section, "download_data")
    module_summary = _summary_by_id(section, "download_data", kind="suite_module")

    assert area_summary.metadata["area_kind"] == "workflow"
    assert area_summary.metadata["suite_id"] is None
    assert module_summary.metadata["suite_id"] is None
    assert module_summary.metadata["area_id"] == "download_data"


def test_provider_connection_can_appear_as_infrastructure_capability_not_suite() -> None:
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

    section = build_suite_boundary_trace_section(areas=(provider_area,))
    summary = _summary_by_id(section, "provider_connection")

    assert summary.metadata["area_kind"] == "infrastructure"
    assert summary.object_ref.object_kind == "area"
    assert summary.object_ref.owner_domain == "connection"


def test_object_map_section_aggregates_explicit_descriptor_inputs() -> None:
    section = build_suite_boundary_trace_section(
        areas=(_area(),),
        suites=(_suite(),),
        modules=(_module(),),
        commands=(_command(),),
        queries=(_query(),),
    )

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "core.suite_boundary"
    assert section.provider_id == SUITE_BOUNDARY_TRACE_PROVIDER_ID
    assert section.owner_domain == "core"
    assert section.metadata["area_count"] == 1
    assert section.metadata["suite_count"] == 1
    assert section.metadata["module_count"] == 1
    assert section.metadata["command_count"] == 1
    assert section.metadata["query_count"] == 1
    assert len(section.summaries) == 5
    assert section.relationships
    assert section.relationship_definitions
    assert any("Formal ObjectFamilyLegend" in warning for warning in section.warnings)


def test_object_map_section_reports_missing_declared_references_without_faking_targets() -> None:
    area = _area(module_ids=("missing_module",), command_ids=("missing_command",))

    section = build_suite_boundary_trace_section(areas=(area,))

    assert any("missing module_ids entry: missing_module" in warning for warning in section.warnings)
    assert any("missing command_ids entry: missing_command" in warning for warning in section.warnings)
    assert all(
        relationship.target_ref.object_id not in {"missing_module", "missing_command"}
        for relationship in section.relationships
    )


def test_object_map_section_is_compatible_with_read_only_object_map_service() -> None:
    provider_descriptor = build_suite_boundary_trace_provider_descriptor()
    service = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=provider_descriptor,
                build_section=lambda: build_suite_boundary_trace_section(
                    areas=(_area(),),
                    suites=(_suite(),),
                    modules=(_module(),),
                    commands=(_command(),),
                    queries=(_query(),),
                ),
            ),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc="2026-01-01T00:00:00+00:00")
    report = service.query()

    assert snapshot.provider_descriptors == (provider_descriptor,)
    assert snapshot.sections[0].provider_id == provider_descriptor.provider_id
    assert snapshot.metadata["summary_count"] == 5
    assert report.summaries
    assert any(
        summary.object_ref.object_kind == "suite_command"
        for summary in report.summaries
    )


def test_interrogation_is_future_not_implemented() -> None:
    section = build_suite_boundary_trace_section(areas=(_area(),))

    assert section.extra["interrogation"] == "future"


def test_no_mutable_registry_scanning_runtime_manager_or_concrete_behavior() -> None:
    source = _TRACE_HELPER.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "gui",
        "import leonardo." + "gui",
        "PySide6",
        "Task" + "Manager",
        "Operation" + "Registry",
        "State" + "Store",
        "Audit" + "Log",
        "Runtime" + "Manager",
        "CoreRuntime" + "Bridge",
        "Core" + "Runner",
        "Suite" + "Registry",
        "register" + "_suite",
        "dis" + "cover(",
        "pkg" + "util",
        "import" + "lib",
        "os." + "walk",
        "Path." + "rglob",
        "glo" + "bals" + "()",
        "Research" + "Suite",
        "Data" + "ManagerSuite",
        "Analysis" + "Suite",
        "Trading" + "Suite",
        "Download" + "Manager",
        "sub" + "process",
        "soc" + "ket.",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "shell" + "=True",
    )

    for token in blocked_tokens:
        assert token not in source


def _area(
    *,
    area_id: str = "data_acquisition",
    suite_id: str | None = "data_manager",
    module_ids: tuple[str, ...] = ("download_data",),
    command_ids: tuple[str, ...] = ("download.preview",),
    query_ids: tuple[str, ...] = ("download.capability.summary",),
) -> AreaDescriptor:
    return AreaDescriptor(
        area_id=area_id,
        display_name="Data Acquisition" if area_id != "download_data" else "Download Data",
        description="Future data acquisition workflow boundary.",
        area_kind=AreaKind.WORKFLOW,
        owner_domain="data_manager" if area_id != "download_data" else "download",
        owner_component="DataAcquisitionBoundary",
        suite_id=suite_id,
        module_ids=module_ids,
        command_ids=command_ids,
        query_ids=query_ids,
        object_family_ids=("download_request", "download_capability"),
        required_permissions=(Permission.DOWNLOAD_VIEW,),
        audit_categories=("download.preview",),
        docs_refs=("docs/contracts_docs/SUITE_BOUNDARY.md",),
        test_refs=("tests/core_test/test_suite_boundary_object_map_pattern.py",),
    )


def _suite() -> SuiteDescriptor:
    return SuiteDescriptor(
        suite_id="data_manager",
        display_name="Data Manager Suite",
        description="Future Data Manager Suite boundary.",
        owner_domain="data_manager",
        owner_component="DataManagerBoundary",
        area_ids=("data_acquisition",),
        module_ids=("download_data",),
        supported_command_ids=("download.preview",),
        supported_query_ids=("download.capability.summary",),
        object_family_ids=("download_request", "download_capability"),
        required_permissions=(Permission.DATA_MANAGER_VIEW,),
        audit_categories=("download.preview",),
    )


def _module(*, suite_id: str | None = "data_manager") -> SuiteModuleDescriptor:
    return SuiteModuleDescriptor(
        module_id="download_data",
        suite_id=suite_id,
        area_id="data_acquisition" if suite_id is not None else "download_data",
        display_name="Download Data",
        description="Future Download Data workflow module.",
        owner_domain="download",
        owner_component="DownloadDataBoundary",
        object_family_ids=("download_request", "download_capability"),
        command_ids=("download.preview",),
        query_ids=("download.capability.summary",),
        required_permissions=(Permission.DOWNLOAD_VIEW,),
        audit_categories=("download.preview",),
        object_map_section_id="download.data",
    )


def _command(*, suite_id: str | None = "data_manager") -> SuiteCommandDescriptor:
    return SuiteCommandDescriptor(
        command_id="download.preview",
        suite_id=suite_id,
        area_id="data_acquisition" if suite_id is not None else "download_data",
        module_id="download_data",
        command_kind=SuiteCommandKind.LONG_RUNNING,
        label="Preview Download",
        description="Future Download Data preview command.",
        required_permission=Permission.DOWNLOAD_PREVIEW,
        creates_operation=True,
        expected_task_behavior=SuiteTaskBehavior.TASK_EXPECTED,
        cancellable=True,
        audit_category="download.preview",
        runtime_policy=SuiteRuntimePolicy.CORE_RUNTIME_REQUIRED,
        input_schema_ref="leonardo.download.preview.input",
        result_schema_ref="leonardo.download.preview.result",
        progress_schema_ref="leonardo.download.preview.progress",
        related_action_ids=("action.download.preview",),
        object_family_ids=("download_request", "download_capability"),
        allowed_callers=("gui",),
        docs_refs=("docs/contracts_docs/SUITE_BOUNDARY.md",),
        test_refs=("tests/core_test/test_suite_boundary_object_map_pattern.py",),
    )


def _query(*, suite_id: str | None = "data_manager") -> SuiteQueryDescriptor:
    return SuiteQueryDescriptor(
        query_id="download.capability.summary",
        suite_id=suite_id,
        area_id="data_acquisition" if suite_id is not None else "download_data",
        module_id="download_data",
        query_kind=SuiteQueryKind.LOCAL_READ_MODEL,
        label="Download Capability Summary",
        description="Future Download capability read model.",
        required_permission=Permission.DOWNLOAD_VIEW,
        read_model_kind="download_capability",
        object_family_ids=("download_capability",),
        cache_policy="snapshot",
        audit_policy="summary",
        allowed_callers=("gui", "object_map"),
        docs_refs=("docs/contracts_docs/SUITE_BOUNDARY.md",),
        test_refs=("tests/core_test/test_suite_boundary_object_map_pattern.py",),
    )


def _summary_by_id(
    section: ObjectMapSection,
    object_id: str,
    *,
    kind: str = "area",
):
    matches = tuple(
        summary
        for summary in section.summaries
        if summary.object_ref.object_id == object_id
        and summary.object_ref.object_kind == kind
    )
    assert len(matches) == 1
    return matches[0]
