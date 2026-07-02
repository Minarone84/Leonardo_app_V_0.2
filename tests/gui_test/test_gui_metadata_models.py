from types import MappingProxyType

import pytest

from leonardo.gui.metadata import (
    FORBIDDEN_EXECUTABLE_FIELD_NAMES,
    GuiActionReference,
    GuiGeometryDefaults,
    GuiMetadataDocument,
    GuiMetadataIssue,
    GuiMetadataIssueCode,
    GuiMetadataKind,
    GuiMetadataOverrideDocument,
    GuiMetadataReport,
    GuiMetadataSessionState,
    GuiRegionReference,
    GuiSettingExposure,
    GuiStyleDefaults,
    GuiTableColumnDescriptor,
    GuiTableDescriptor,
    GuiWidgetReference,
)


def test_metadata_model_creation_captures_declarative_profile_parts() -> None:
    document = GuiMetadataDocument(
        metadata_id="dummy_metadata_test.window",
        kind=GuiMetadataKind.WINDOW,
        schema_version="1",
        title="Dummy Metadata Test",
        geometry=GuiGeometryDefaults(width=900, height=600),
        style=GuiStyleDefaults(font_size=14),
        actions=(GuiActionReference(action_id="dummy.refresh", label="Refresh"),),
        regions=(GuiRegionReference(region_id="main", label="Main"),),
        widgets=(
            GuiWidgetReference(
                widget_id="refresh_button",
                region_id="main",
                label="Refresh",
                widget_type="button",
            ),
        ),
        tables=(
            GuiTableDescriptor(
                table_id="summary",
                label="Summary",
                columns=(
                    GuiTableColumnDescriptor(
                        column_id="name",
                        label="Name",
                        width=140,
                    ),
                ),
            ),
        ),
        settings=(
            GuiSettingExposure(
                path="style.font_size",
                label="Font size",
                value_type="integer",
            ),
        ),
    )

    profile = document.to_profile_mapping()

    assert profile["identity"]["metadata_id"] == "dummy_metadata_test.window"
    assert profile["style"]["font_size"] == 14
    assert profile["actions"]["dummy.refresh"]["label"] == "Refresh"
    assert profile["tables"]["summary"]["columns"]["name"]["width"] == 140


def test_override_and_session_state_are_separate_changed_only_models() -> None:
    override = GuiMetadataOverrideDocument(
        metadata_id="dummy_metadata_test.window",
        values={"style.font_size": 10},
    )
    session_state = GuiMetadataSessionState(
        metadata_id="dummy_metadata_test.window",
        values={"geometry.width": 1200},
    )

    assert override.changed_paths == ("style.font_size",)
    assert "geometry.width" not in override.values
    assert session_state.values["geometry.width"] == 1200


def test_model_mappings_are_defensive_copies() -> None:
    values = {"style.font_size": 10}
    override = GuiMetadataOverrideDocument(
        metadata_id="dummy_metadata_test.window",
        values=values,
    )
    values["style.font_size"] = 8

    assert isinstance(override.values, MappingProxyType)
    assert override.values["style.font_size"] == 10
    with pytest.raises(TypeError):
        override.values["style.font_size"] = 12


def test_report_supports_issue_filtering() -> None:
    issue = GuiMetadataIssue(
        code=GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE,
        path="style.font_size",
        message="Invalid value",
    )
    report = GuiMetadataReport((issue,))

    assert report.has_errors is True
    assert report.issues_by_code(GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE) == (issue,)


def test_forbidden_executable_field_names_are_declared() -> None:
    assert "callback" in FORBIDDEN_EXECUTABLE_FIELD_NAMES
    assert "handler" in FORBIDDEN_EXECUTABLE_FIELD_NAMES
    assert "lambda" in FORBIDDEN_EXECUTABLE_FIELD_NAMES
    assert "code" in FORBIDDEN_EXECUTABLE_FIELD_NAMES
