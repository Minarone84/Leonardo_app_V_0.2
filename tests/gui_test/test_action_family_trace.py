from pathlib import Path

from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.gui.metadata.action_trace import (
    ACTION_TRACE_PROVIDER_ID,
    ACTION_TRACE_RUNTIME_KIND,
    action_trace_summaries_from_document,
    build_action_trace_provider_descriptor,
    build_action_trace_section,
    default_action_metadata_paths,
    interrogate_action_trace,
)
from leonardo.gui.metadata.loader import load_metadata_document


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "action_trace.py"
)
_METADATA_DIR = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "windows"
)
_MAIN_WINDOW_METADATA = _METADATA_DIR / "main_window.window.toml"
_RUNTIME_MANAGER_METADATA = _METADATA_DIR / "runtime_manager.window.toml"
_DOWNLOAD_REQUEST_BUILDER_METADATA = (
    _METADATA_DIR / "download_request_builder.window.toml"
)


def test_action_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_action_trace_provider_descriptor()

    assert descriptor.provider_id == ACTION_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "gui"
    assert descriptor.object_kinds == ("action",)
    assert descriptor.family_ids == ("action",)
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "contains_action" in descriptor.relationship_types
    assert "has_permission" in descriptor.relationship_types
    assert "triggers" in descriptor.relationship_types


def test_action_trace_summaries_are_static_without_qt_source_dependency() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "PyQt6" not in source
    assert "QtWidgets" not in source
    assert "QApplication" not in source

    section = build_action_trace_section()

    assert section.errors == ()
    assert section.summaries


def test_main_window_actions_have_trace_summaries() -> None:
    summaries = _summaries_for(_MAIN_WINDOW_METADATA)
    summary_ids = {summary.object_ref.object_id for summary in summaries}

    assert "main_window.open_runtime_manager" in summary_ids
    assert "main_window.open_settings_inspector" in summary_ids
    assert "main_window.download_data" in summary_ids
    assert "main_window.exit" in summary_ids


def test_runtime_manager_actions_have_trace_summaries() -> None:
    summaries = _summaries_for(_RUNTIME_MANAGER_METADATA)
    summary_ids = {summary.object_ref.object_id for summary in summaries}

    assert "runtime_manager.refresh_snapshot" in summary_ids
    assert "runtime_manager.close" in summary_ids
    assert "runtime_manager.export_snapshot" in summary_ids


def test_download_request_builder_actions_have_trace_summaries() -> None:
    summaries = _summaries_for(_DOWNLOAD_REQUEST_BUILDER_METADATA)
    summary_ids = {summary.object_ref.object_id for summary in summaries}

    assert "download_request_builder.submit" in summary_ids
    assert "download_request_builder.close" in summary_ids


def test_action_summary_includes_static_metadata_fields() -> None:
    section = build_action_trace_section()
    summary = _summary_by_id(section, "main_window.open_runtime_manager")

    assert summary.object_ref.object_id == "main_window.open_runtime_manager"
    assert summary.object_ref.object_kind == "action"
    assert summary.object_ref.owner_domain == "gui"
    assert summary.display_name == "Runtime Manager"
    assert summary.lifecycle_status == "defined"
    assert summary.runtime_or_persistent == ACTION_TRACE_RUNTIME_KIND
    assert summary.metadata["action_id"] == "main_window.open_runtime_manager"
    assert summary.metadata["window_id"] == "main_window.window"
    assert summary.metadata["metadata_id"] == "main_window.window"
    assert summary.metadata["action_kind"] == "menu"
    assert summary.metadata["label"] == "Runtime Manager"
    assert summary.metadata["required_permissions"] == ("runtime:view",)
    assert summary.metadata["is_placeholder"] is False
    assert summary.metadata["implementation_status"] == "defined"
    assert "window_metadata" in summary.metadata["sources"]
    assert "action_observer_definition" in summary.metadata["sources"]


def test_placeholder_action_status_is_reported_from_static_definition() -> None:
    section = build_action_trace_section()
    summary = _summary_by_id(section, "main_window.download_data")

    assert summary.metadata["is_placeholder"] is True
    assert summary.metadata["implementation_status"] == "placeholder"
    assert summary.metadata["window_id"] == "main_window.window"


def test_static_definition_only_action_has_summary_without_window_metadata() -> None:
    section = build_action_trace_section()
    summary = _summary_by_id(section, "settings_inspector.apply_changes")

    assert summary.object_ref.object_id == "settings_inspector.apply_changes"
    assert summary.metadata["metadata_id"] is None
    assert summary.metadata["metadata_ref"] is None
    assert summary.metadata["action_kind"] == "button"
    assert summary.permission_refs == ("gui_settings:manage",)


def test_action_summaries_include_relationships_to_declaring_windows() -> None:
    section = build_action_trace_section()
    summary = _summary_by_id(section, "main_window.open_runtime_manager")
    relationships = {
        relationship.target_ref.object_id: relationship
        for relationship in summary.relationship_refs
        if relationship.relationship_type == "contains_action"
    }

    assert "main_window.window" in relationships
    relationship = relationships["main_window.window"]
    assert relationship.source_ref.object_id == "main_window.open_runtime_manager"
    assert relationship.target_ref.object_kind == "window"
    assert relationship.direction == "inbound"
    assert relationship.lifecycle_status == "defined"


def test_action_summaries_include_permission_refs_and_relationships() -> None:
    section = build_action_trace_section()
    summary = _summary_by_id(section, "main_window.open_settings_inspector")
    relationships = {
        relationship.target_ref.object_id: relationship
        for relationship in summary.relationship_refs
        if relationship.relationship_type == "has_permission"
    }

    assert summary.permission_refs == ("gui_settings:manage",)
    assert "gui_settings:manage" in relationships
    relationship = relationships["gui_settings:manage"]
    assert relationship.source_ref.object_id == "main_window.open_settings_inspector"
    assert relationship.target_ref.object_kind == "permission"
    assert relationship.target_ref.owner_domain == "core.policy"


def test_action_object_map_section_includes_summaries_legend_and_relationship_defs() -> None:
    section = build_action_trace_section()
    summary_ids = {summary.object_ref.object_id for summary in section.summaries}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "gui.actions"
    assert section.provider_id == ACTION_TRACE_PROVIDER_ID
    assert section.owner_domain == "gui"
    assert section.object_kind == "action"
    assert section.family_id == "action"
    assert "main_window.open_runtime_manager" in summary_ids
    assert "runtime_manager.refresh_snapshot" in summary_ids
    assert "download_request_builder.submit" in summary_ids
    assert section.legends[0].family_id == "action"
    assert "contains_action" in relationship_types
    assert "has_permission" in relationship_types
    assert "triggers" in relationship_types
    assert "creates_operation" not in relationship_types


def test_malformed_action_metadata_is_reported_without_mutation(tmp_path: Path) -> None:
    malformed = tmp_path / "broken.window.toml"
    malformed.write_text(
        'metadata_id = "broken.window"\nkind = "window"\ntitle = "Broken"\n',
        encoding="utf-8",
    )

    section = build_action_trace_section(metadata_paths=(malformed,), definitions=())

    assert section.summaries == ()
    assert section.errors
    assert "Missing required metadata field: schema_version" in section.errors[0]
    assert malformed.read_text(encoding="utf-8") == (
        'metadata_id = "broken.window"\nkind = "window"\ntitle = "Broken"\n'
    )


def test_interrogate_action_trace_returns_read_only_report() -> None:
    report = interrogate_action_trace("main_window.open_runtime_manager")

    assert report.target_ref.object_id == "main_window.open_runtime_manager"
    assert isinstance(report.summary, TraceableObjectSummary)
    assert report.family_legend is not None
    assert report.family_legend.family_id == "action"
    assert "runtime:view" in report.permissions
    assert any(
        relationship.target_ref.object_id == "main_window.window"
        for relationship in report.relationships
    )
    assert report.blockers == ()
    assert report.metadata["read_only"] is True


def test_interrogate_missing_action_reports_blocker_without_failure() -> None:
    report = interrogate_action_trace("missing.action")

    assert report.summary is None
    assert report.target_ref.object_id == "missing.action"
    assert report.blockers == ("Action metadata not found: missing.action",)
    assert report.errors == ()


def test_action_trace_has_no_runtime_or_execution_wiring() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "RuntimeManagerWindow",
        "GuiCompositionRoot",
        "WindowRegistry",
        "ActionRegistry(",
        "build_gui_action_observer",
        "CoreGuiActionObserver(",
        "record_action(",
        "class ObjectMapService",
        "class ObjectMapRegistry",
        "register_provider",
        "def discover",
        ".discover",
        "discover(",
        "DownloadManager(",
        "DownloadExecutionManager(",
        "DownloadRequestBuilderWindow",
        "QWidget",
        "show(",
        "exec(",
        "exec_",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
    )

    for token in blocked_tokens:
        assert token not in source


def test_default_action_metadata_paths_are_static_and_existing() -> None:
    paths = default_action_metadata_paths()

    assert _MAIN_WINDOW_METADATA in paths
    assert _RUNTIME_MANAGER_METADATA in paths
    assert _DOWNLOAD_REQUEST_BUILDER_METADATA in paths
    assert all(path.exists() for path in paths)


def _summaries_for(path: Path) -> tuple[TraceableObjectSummary, ...]:
    result = load_metadata_document(path)
    assert result.document is not None
    assert result.report.has_errors is False
    return action_trace_summaries_from_document(result.document, metadata_path=path)


def _summary_by_id(
    section: ObjectMapSection,
    action_id: str,
) -> TraceableObjectSummary:
    for summary in section.summaries:
        if summary.object_ref.object_id == action_id:
            return summary
    raise AssertionError(f"Missing action trace summary: {action_id}")
