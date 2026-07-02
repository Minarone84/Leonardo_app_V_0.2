from pathlib import Path

from leonardo.gui.metadata import (
    GuiMetadataIssueCode,
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    GuiMetadataSessionState,
    ResolvedValueSource,
    load_metadata_document,
)


_VALID_METADATA_TOML = """
metadata_id = "dummy_metadata_test.window"
kind = "window"
schema_version = "1"
title = "Dummy Metadata Test"
label = "Dummy"

[geometry]
width = 900
height = 600

[display]
visible = true
enabled = true
theme = "system"

[style]
font_size = 14
density = "comfortable"

[[actions]]
action_id = "dummy.refresh"
label = "Refresh"

[[regions]]
region_id = "main"
label = "Main"

[[widgets]]
widget_id = "refresh_button"
region_id = "main"
label = "Refresh"
widget_type = "button"

[[tables]]
table_id = "summary"
label = "Summary"

[[tables.columns]]
column_id = "name"
label = "Name"
visible = true
width = 140

[[reports]]
report_id = "status"
label = "Status"

[[reports.sections]]
section_id = "overview"
label = "Overview"
visible = true

[[settings]]
path = "style.font_size"
label = "Font size"
value_type = "integer"

[[settings]]
path = "tables.summary.columns.name.visible"
label = "Show name column"
value_type = "boolean"
"""


def test_toml_metadata_loading_creates_document(tmp_path: Path) -> None:
    path = _write_metadata(tmp_path, _VALID_METADATA_TOML)

    result = load_metadata_document(path)

    assert result.report.has_errors is False
    assert result.document is not None
    assert result.document.metadata_id == "dummy_metadata_test.window"
    assert result.document.kind.value == "window"
    assert result.document.settings[0].path == "style.font_size"


def test_duplicate_id_validation_reports_structured_issue(tmp_path: Path) -> None:
    text = _VALID_METADATA_TOML + """
[[regions]]
region_id = "main"
label = "Duplicate Main"
"""

    result = load_metadata_document(_write_metadata(tmp_path, text))

    assert result.document is None
    assert result.report.issues_by_code(GuiMetadataIssueCode.DUPLICATE_ID)


def test_forbidden_executable_metadata_field_is_reported(tmp_path: Path) -> None:
    text = _VALID_METADATA_TOML + """
[metadata]
callback = "run_something"
"""

    result = load_metadata_document(_write_metadata(tmp_path, text))

    assert result.document is None
    assert result.report.issues_by_code(
        GuiMetadataIssueCode.FORBIDDEN_EXECUTABLE_FIELD
    )


def test_invalid_setting_exposure_path_is_reported(tmp_path: Path) -> None:
    text = _VALID_METADATA_TOML + """
[[settings]]
path = "actions.dummy.refresh.label"
label = "Invalid"
value_type = "string"
"""

    result = load_metadata_document(_write_metadata(tmp_path, text))

    assert result.document is None
    assert result.report.issues_by_code(
        GuiMetadataIssueCode.INVALID_SETTING_EXPOSURE_PATH
    )


def test_source_override_merge_effective_trace_and_reset(tmp_path: Path) -> None:
    document = _load_valid_document(tmp_path)
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={
            "style.font_size": 10,
            "display.visible": False,
            "geometry.width": 1200,
        },
    )

    profile = resolver.resolve(document, overrides)

    assert profile.values["style"]["font_size"] == 10
    assert profile.values["display"]["visible"] is False
    assert profile.values["geometry"]["width"] == 1200
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.USER_OVERRIDE
    )
    assert resolver.explain(profile, "style.font_size").default_value == 14

    field_reset = resolver.reset_field(overrides, "style.font_size")
    assert "style.font_size" not in field_reset.values
    assert resolver.resolve(document, field_reset).values["style"]["font_size"] == 14

    section_reset = resolver.reset_section(overrides, "style")
    assert "style.font_size" not in section_reset.values
    assert "geometry.width" in section_reset.values

    full_reset = resolver.reset_profile(overrides)
    assert full_reset.values == {}
    assert resolver.resolve(document, full_reset).values["geometry"]["width"] == 900


def test_stale_override_path_and_invalid_override_are_reported(tmp_path: Path) -> None:
    document = _load_valid_document(tmp_path)
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={
            "style.missing": 10,
            "style.font_size": "large",
        },
    )

    profile = resolver.resolve(document, overrides)

    assert profile.values["style"]["font_size"] == 14
    assert profile.report.issues_by_code(GuiMetadataIssueCode.STALE_OVERRIDE_PATH)
    assert profile.report.issues_by_code(GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE)
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.INVALID
    )
    assert resolver.explain(profile, "style.font_size").override_value == "large"


def test_session_state_overlays_preferences_without_mutating_overrides(tmp_path: Path) -> None:
    document = _load_valid_document(tmp_path)
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 10},
    )
    session_state = GuiMetadataSessionState(
        metadata_id=document.metadata_id,
        values={"style.font_size": 16},
    )

    profile = resolver.resolve(document, overrides, session_state)

    assert profile.values["style"]["font_size"] == 16
    assert overrides.values == {"style.font_size": 10}
    assert session_state.values == {"style.font_size": 16}
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.SESSION_STATE
    )
    assert resolver.explain(profile, "style.font_size").override_value == 10
    assert resolver.explain(profile, "style.font_size").session_value == 16


def _load_valid_document(tmp_path: Path):
    result = load_metadata_document(_write_metadata(tmp_path, _VALID_METADATA_TOML))
    assert result.document is not None
    return result.document


def _write_metadata(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "metadata.toml"
    path.write_text(text, encoding="utf-8")
    return path
