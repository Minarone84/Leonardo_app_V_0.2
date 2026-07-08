from pathlib import Path

from leonardo.contracts.object_map import ObjectMapSection
from leonardo.contracts.traceable_object import TraceableObjectSummary
from leonardo.gui.metadata.loader import load_metadata_document
from leonardo.gui.metadata.window_trace import (
    WINDOW_TRACE_PROVIDER_ID,
    WINDOW_TRACE_RUNTIME_KIND,
    build_window_trace_provider_descriptor,
    build_window_trace_section,
    default_window_metadata_paths,
    interrogate_window_trace,
    window_trace_summary_from_document,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "window_trace.py"
)
_METADATA_DIR = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "metadata" / "windows"
)
_MAIN_WINDOW_METADATA = _METADATA_DIR / "main_window.window.toml"
_RUNTIME_MANAGER_METADATA = _METADATA_DIR / "runtime_manager.window.toml"
_HISTORICAL_DOWNLOAD_MANAGER_METADATA = (
    _METADATA_DIR / "historical_download_manager.window.toml"
)


def test_window_trace_provider_descriptor_is_read_only() -> None:
    descriptor = build_window_trace_provider_descriptor()

    assert descriptor.provider_id == WINDOW_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "gui"
    assert descriptor.object_kinds == ("window",)
    assert descriptor.family_ids == ("window",)
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_interrogation is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert "contains_action" in descriptor.relationship_types


def test_window_trace_summaries_are_metadata_only_without_qt_source_dependency() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")

    assert "PySide6" not in source
    assert "PyQt6" not in source
    assert "QtWidgets" not in source
    assert "QApplication" not in source

    section = build_window_trace_section()

    assert section.errors == ()
    assert section.summaries


def test_main_window_summary_has_stable_trace_identity() -> None:
    summary = _summary_for(_MAIN_WINDOW_METADATA)

    assert summary.object_ref.object_id == "main_window.window"
    assert summary.object_ref.object_kind == "window"
    assert summary.object_ref.owner_domain == "gui"
    assert summary.display_name == "Leonardo"
    assert summary.lifecycle_status == "defined"
    assert summary.runtime_or_persistent == WINDOW_TRACE_RUNTIME_KIND


def test_runtime_manager_window_summary_is_available() -> None:
    summary = _summary_for(_RUNTIME_MANAGER_METADATA)

    assert summary.object_ref.object_id == "runtime_manager.window"
    assert summary.metadata["metadata_id"] == "runtime_manager.window"
    assert summary.metadata["owner_area"] == "gui"
    assert summary.metadata["object_name"] == "runtime_manager_window"


def test_historical_download_manager_window_summary_is_available() -> None:
    summary = _summary_for(_HISTORICAL_DOWNLOAD_MANAGER_METADATA)

    assert summary.object_ref.object_id == "historical_download_manager.window"
    assert summary.metadata["metadata_id"] == "historical_download_manager.window"
    assert summary.metadata["owner_area"] == "gui"
    assert summary.metadata["object_name"] == "historical_download_manager_window"


def test_window_summaries_include_static_metadata_fields() -> None:
    summary = _summary_for(_MAIN_WINDOW_METADATA)

    assert summary.metadata["metadata_id"] == "main_window.window"
    assert summary.metadata["window_id"] == "main_window.window"
    assert summary.metadata["object_name"] == "main_window"
    assert summary.metadata["title"] == "Leonardo"
    assert summary.metadata["label"] == "Leonardo"
    assert summary.metadata["owner_area"] == "gui"
    assert summary.metadata["instance_policy"] == "singleton"
    assert summary.metadata["settings_present"] is True
    assert "main_window.open_runtime_manager" in summary.metadata["action_ids"]


def test_all_gui_window_metadata_files_are_gui_owned() -> None:
    paths = tuple(sorted(_METADATA_DIR.glob("*.window.toml")))

    assert paths
    for path in paths:
        result = load_metadata_document(path)
        assert result.document is not None
        assert result.report.has_errors is False
        assert result.document.metadata["owner_area"] == "gui"


def test_window_summaries_include_static_window_action_relationships() -> None:
    summary = _summary_for(_MAIN_WINDOW_METADATA)
    relationships = {
        relationship.target_ref.object_id: relationship
        for relationship in summary.relationship_refs
    }

    assert "main_window.open_runtime_manager" in relationships
    relationship = relationships["main_window.open_runtime_manager"]
    assert relationship.relationship_type == "contains_action"
    assert relationship.source_ref.object_id == "main_window.window"
    assert relationship.target_ref.object_kind == "action"
    assert relationship.lifecycle_status == "defined"


def test_window_object_map_section_includes_summaries_and_legend() -> None:
    section = build_window_trace_section()
    summary_ids = {summary.object_ref.object_id for summary in section.summaries}
    relationship_types = {
        definition.relationship_type
        for definition in section.relationship_definitions
    }

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "gui.windows"
    assert section.provider_id == WINDOW_TRACE_PROVIDER_ID
    assert section.owner_domain == "gui"
    assert section.object_kind == "window"
    assert section.family_id == "window"
    assert "main_window.window" in summary_ids
    assert "runtime_manager.window" in summary_ids
    assert "historical_download_manager.window" in summary_ids
    assert section.legends[0].family_id == "window"
    assert "contains_action" in relationship_types
    assert "opens_window" in relationship_types


def test_malformed_metadata_is_reported_without_mutation(tmp_path: Path) -> None:
    malformed = tmp_path / "broken.window.toml"
    malformed.write_text(
        'metadata_id = "broken.window"\nkind = "window"\ntitle = "Broken"\n',
        encoding="utf-8",
    )

    section = build_window_trace_section(metadata_paths=(malformed,))

    assert section.summaries == ()
    assert section.errors
    assert "Missing required metadata field: schema_version" in section.errors[0]
    assert malformed.read_text(encoding="utf-8") == (
        'metadata_id = "broken.window"\nkind = "window"\ntitle = "Broken"\n'
    )


def test_interrogate_window_trace_returns_read_only_report() -> None:
    report = interrogate_window_trace("main_window.window")

    assert report.target_ref.object_id == "main_window.window"
    assert isinstance(report.summary, TraceableObjectSummary)
    assert report.family_legend is not None
    assert report.family_legend.family_id == "window"
    assert any(
        relationship.target_ref.object_id == "main_window.open_runtime_manager"
        for relationship in report.relationships
    )
    assert report.blockers == ()
    assert report.metadata["read_only"] is True


def test_window_trace_has_no_runtime_manager_or_object_map_wiring() -> None:
    source = _TRACE_SOURCE.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "RuntimeManagerWindow",
        "GuiCompositionRoot",
        "WindowRegistry",
        "ActionRegistry",
        "GuiActionObserver",
        "TRACKED_GUI_ACTION_DEFINITIONS",
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


def test_default_window_metadata_paths_are_static_and_existing() -> None:
    paths = default_window_metadata_paths()

    assert _MAIN_WINDOW_METADATA in paths
    assert _RUNTIME_MANAGER_METADATA in paths
    assert _HISTORICAL_DOWNLOAD_MANAGER_METADATA in paths
    assert all(path.exists() for path in paths)


def _summary_for(path: Path) -> TraceableObjectSummary:
    result = load_metadata_document(path)
    assert result.document is not None
    assert result.report.has_errors is False
    return window_trace_summary_from_document(result.document, metadata_path=path)
