from collections.abc import Mapping
from pathlib import Path
import tomllib

from leonardo.gui.metadata import (
    FORBIDDEN_EXECUTABLE_FIELD_NAMES,
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    ResolvedValueSource,
    load_metadata_document,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_WINDOW_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)


def test_main_window_metadata_loads_and_validates() -> None:
    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == "main_window.window"
    assert result.document.kind.value == "window"
    assert result.document.title == "Leonardo"


def test_main_window_metadata_resolves_effective_profile() -> None:
    document = _load_main_window_document()
    profile = GuiMetadataResolver().resolve(document)

    assert profile.report.has_errors is False
    assert profile.metadata_id == "main_window.window"
    assert profile.values["identity"]["title"] == "Leonardo"
    assert profile.values["geometry"]["width"] == 1440
    assert profile.values["style"]["font_size"] == 14


def test_main_window_identity_is_discoverable() -> None:
    document = _load_main_window_document()

    assert document.metadata["contract_id"] == "main_window.window"
    assert document.metadata["logical_kind"] == "main_application_shell"
    assert document.metadata["owner_area"] == "shell"
    assert document.metadata["instance_policy"] == "singleton"
    assert document.metadata["geometry_policy"]["start_mode"] == "maximized"


def test_main_window_required_shell_regions_exist() -> None:
    document = _load_main_window_document()

    assert {
        "menu_bar",
        "central",
        "status_bar",
        "user_display",
        "version_display",
    } == {
        region.region_id
        for region in document.regions
    }


def test_main_window_required_shell_actions_exist() -> None:
    document = _load_main_window_document()

    assert {
        "main_window.download_data",
        "main_window.open_dummy_metadata_test",
        "main_window.ohlcv_maintenance",
        "main_window.open_analysis_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_research_suite",
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
        "main_window.open_trading_suite",
        "main_window.exit",
    } == {action.action_id for action in document.actions}


def test_main_window_metadata_documents_download_launch_surfaces() -> None:
    document = _load_main_window_document()
    launch_surfaces = document.metadata["launch_surfaces"]
    download_data = launch_surfaces["download_data"]
    ohlcv_maintenance = launch_surfaces["ohlcv_maintenance"]

    assert document.metadata["menu_bar"]["present"] is True
    assert "Download Manager" in document.metadata["menu_bar"]["menus"]
    assert download_data["action_id"] == "main_window.download_data"
    assert download_data["target_window_id"] == "download_request_builder.window"
    assert download_data["target_workflow_id"] == "download_data"
    assert download_data["boundary_id"] == "download_data_boundary"
    assert download_data["permission_ref"] == "download:view"
    assert download_data["implementation_status"] == "opens_existing_builder_shell"
    assert ohlcv_maintenance["action_id"] == "main_window.ohlcv_maintenance"
    assert ohlcv_maintenance["target_window_id"] == "download_request_builder.window"
    assert ohlcv_maintenance["target_workflow_id"] == "ohlcv_maintenance"
    assert ohlcv_maintenance["related_boundary_id"] == "download_data_boundary"
    assert ohlcv_maintenance["implementation_status"] == "deferred_shell_entry"


def test_main_window_metadata_is_inspectable_without_ai_helper_behavior() -> None:
    document = _load_main_window_document()
    inspection = document.metadata["ai_inspection"]

    assert inspection["inspectable"] is True
    assert "normal GUI action observation" in inspection["allowed_path"]
    assert "Future AI helper work" in inspection["notes"][0]
    assert document.metadata["documentation"]["docs_refs"]
    assert document.metadata["documentation"]["test_refs"]


def test_main_window_settings_exposure_contains_only_safe_paths() -> None:
    document = _load_main_window_document()
    profile = GuiMetadataResolver().resolve(document)
    setting_paths = {setting.path for setting in document.settings}

    assert setting_paths == {"style.font_size", "style.density"}
    for path in setting_paths:
        assert profile.trace_for(path).source is ResolvedValueSource.METADATA_DEFAULT
    assert "metadata.contract_id" not in setting_paths
    assert "actions.main_window.exit.action_id" not in setting_paths
    assert "identity.schema_version" not in setting_paths


def test_main_window_override_merge_and_reset_for_exposed_setting() -> None:
    document = _load_main_window_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 12},
    )

    overridden = resolver.resolve(document, overrides)
    reset = resolver.reset_field(overrides, "style.font_size")
    restored = resolver.resolve(document, reset)

    assert overridden.values["style"]["font_size"] == 12
    assert resolver.explain(overridden, "style.font_size").source is (
        ResolvedValueSource.USER_OVERRIDE
    )
    assert "style.font_size" not in reset.values
    assert restored.values["style"]["font_size"] == 14
    assert resolver.explain(restored, "style.font_size").source is (
        ResolvedValueSource.METADATA_DEFAULT
    )


def test_main_window_metadata_has_no_executable_metadata_fields() -> None:
    with _MAIN_WINDOW_METADATA_PATH.open("rb") as source_file:
        raw_data = tomllib.load(source_file)

    assert _forbidden_keys_in(raw_data) == set()


def test_main_window_metadata_loading_requires_no_qt_imports() -> None:
    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)

    assert result.document is not None
    assert result.report.has_errors is False


def _load_main_window_document():
    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _forbidden_keys_in(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in FORBIDDEN_EXECUTABLE_FIELD_NAMES:
                found.add(key_text)
            found.update(_forbidden_keys_in(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys_in(item))
    return found
