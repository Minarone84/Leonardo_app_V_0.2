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
_DUMMY_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "dummy_metadata_test.window.toml"
)


def test_dummy_window_metadata_loads_and_validates() -> None:
    result = load_metadata_document(_DUMMY_METADATA_PATH)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == "dummy_metadata_test.window"
    assert result.document.kind.value == "window"
    assert result.document.title == "Dummy Metadata Test Window"
    assert result.document.metadata["contract_id"] == "dummy_metadata_test.window"
    assert result.document.metadata["logical_kind"] == "test_window"
    assert result.document.metadata["owner_area"] == "gui_metadata_test"


def test_dummy_window_metadata_resolves_effective_profile() -> None:
    document = _load_dummy_document()
    profile = GuiMetadataResolver().resolve(document)

    assert profile.report.has_errors is False
    assert profile.metadata_id == "dummy_metadata_test.window"
    assert profile.values["identity"]["title"] == "Dummy Metadata Test Window"
    assert profile.values["geometry"]["width"] == 1120
    assert profile.values["style"]["font_size"] == 14
    assert profile.trace_for("style.font_size").source is (
        ResolvedValueSource.METADATA_DEFAULT
    )


def test_dummy_window_metadata_contains_required_actions_regions_and_widgets() -> None:
    document = _load_dummy_document()

    assert {
        "dummy_metadata_test.refresh",
        "dummy_metadata_test.apply_mock",
        "dummy_metadata_test.reset_mock",
        "dummy_metadata_test.open_settings",
        "dummy_metadata_test.close",
    }.issubset({action.action_id for action in document.actions})
    assert {
        "header",
        "toolbar",
        "body",
        "left_panel",
        "right_panel",
        "footer",
        "status_area",
    }.issubset({region.region_id for region in document.regions})
    assert {
        "dummy_metadata_test.title_label",
        "dummy_metadata_test.status_label",
        "dummy_metadata_test.enabled_checkbox",
        "dummy_metadata_test.name_input",
        "dummy_metadata_test.mode_combo",
        "dummy_metadata_test.notes_text",
        "dummy_metadata_test.report_view",
        "dummy_metadata_test.diagnostics_view",
    }.issubset({widget.widget_id for widget in document.widgets})


def test_dummy_window_metadata_contains_required_table_and_columns() -> None:
    document = _load_dummy_document()
    profile = GuiMetadataResolver().resolve(document)
    tables = {table.table_id: table for table in document.tables}

    assert "dummy_metadata_test.results_table" in tables
    assert {"item", "status", "value", "details"} == {
        column.column_id
        for column in tables["dummy_metadata_test.results_table"].columns
    }
    assert (
        profile.values["tables"]["dummy_metadata_test.results_table"]["columns"]["status"][
            "width"
        ]
        == 120
    )


def test_dummy_window_metadata_contains_required_report_and_sections() -> None:
    document = _load_dummy_document()
    profile = GuiMetadataResolver().resolve(document)
    reports = {report.report_id: report for report in document.reports}

    assert "dummy_metadata_test.structured_report" in reports
    assert {"summary", "warnings", "results", "diagnostics"} == {
        section.section_id
        for section in reports["dummy_metadata_test.structured_report"].sections
    }
    assert (
        profile.values["reports"]["dummy_metadata_test.structured_report"]["sections"][
            "diagnostics"
        ]["visible"]
        is True
    )


def test_dummy_window_metadata_settings_are_safe_profile_paths() -> None:
    document = _load_dummy_document()
    profile = GuiMetadataResolver().resolve(document)
    setting_paths = {setting.path for setting in document.settings}

    assert {"style.font_size", "style.density", "geometry.width", "geometry.height"} == (
        setting_paths
    )
    for path in setting_paths:
        assert profile.trace_for(path).source is ResolvedValueSource.METADATA_DEFAULT


def test_dummy_window_metadata_override_merge_and_reset() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 11},
    )

    overridden = resolver.resolve(document, overrides)
    reset = resolver.reset_field(overrides, "style.font_size")
    restored = resolver.resolve(document, reset)

    assert overridden.values["style"]["font_size"] == 11
    assert resolver.explain(overridden, "style.font_size").source is (
        ResolvedValueSource.USER_OVERRIDE
    )
    assert "style.font_size" not in reset.values
    assert restored.values["style"]["font_size"] == 14


def test_dummy_window_metadata_has_no_executable_metadata_fields() -> None:
    with _DUMMY_METADATA_PATH.open("rb") as source_file:
        raw_data = tomllib.load(source_file)

    assert _forbidden_keys_in(raw_data) == set()


def test_dummy_window_metadata_loads_with_metadata_package_only() -> None:
    result = load_metadata_document(_DUMMY_METADATA_PATH)

    assert result.document is not None
    assert result.report.has_errors is False


def _load_dummy_document():
    result = load_metadata_document(_DUMMY_METADATA_PATH)
    assert result.document is not None
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
