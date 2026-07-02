from pathlib import Path

from leonardo.gui.metadata import (
    GuiMetadataIssueCode,
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    GuiMetadataSessionState,
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


def test_exposed_setting_resolves_from_metadata_without_override() -> None:
    document = _load_dummy_document()
    profile = GuiMetadataResolver().resolve(document)

    trace = profile.trace_for("style.font_size")

    assert "style.font_size" in _exposed_setting_paths(document)
    assert trace.source is ResolvedValueSource.METADATA_DEFAULT
    assert trace.effective_value == 14
    assert trace.default_value == 14
    assert trace.override_value is None


def test_override_one_exposed_field_traces_user_override_without_mutating_default() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 11},
    )

    profile = resolver.resolve(document, overrides)

    assert document.style.font_size == 14
    assert profile.values["style"]["font_size"] == 11
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.USER_OVERRIDE
    )
    assert resolver.explain(profile, "style.font_size").default_value == 14
    assert resolver.explain(profile, "style.font_size").override_value == 11


def test_reset_one_field_removes_override_and_restores_metadata_default() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 11},
    )

    reset = resolver.reset_field(overrides, "style.font_size")
    profile = resolver.resolve(document, reset)

    assert reset.values == {}
    assert profile.values["style"]["font_size"] == 14
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.METADATA_DEFAULT
    )


def test_reset_one_section_removes_matching_overrides_and_keeps_other_sections() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={
            "style.font_size": 11,
            "style.density": "compact",
            "geometry.width": 1000,
        },
    )

    reset = resolver.reset_section(overrides, "style")
    profile = resolver.resolve(document, reset)

    assert set(reset.values) == {"geometry.width"}
    assert profile.values["style"]["font_size"] == 14
    assert profile.values["style"]["density"] == "comfortable"
    assert profile.values["geometry"]["width"] == 1000
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.METADATA_DEFAULT
    )
    assert resolver.explain(profile, "geometry.width").source is (
        ResolvedValueSource.USER_OVERRIDE
    )


def test_reset_full_profile_removes_all_overrides() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={
            "style.font_size": 11,
            "style.density": "compact",
            "geometry.width": 1000,
            "geometry.height": 680,
        },
    )

    reset = resolver.reset_profile(overrides)
    profile = resolver.resolve(document, reset)

    assert reset.values == {}
    assert profile.values["style"]["font_size"] == 14
    assert profile.values["style"]["density"] == "comfortable"
    assert profile.values["geometry"]["width"] == 1120
    assert profile.values["geometry"]["height"] == 720


def test_stale_override_path_is_reported_and_ignored() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.missing": 9},
    )

    profile = resolver.resolve(document, overrides)

    assert profile.report.issues_by_code(GuiMetadataIssueCode.STALE_OVERRIDE_PATH)
    assert profile.values["style"]["font_size"] == 14
    assert profile.trace_for("style.missing").source is ResolvedValueSource.MISSING


def test_invalid_override_value_is_reported_and_not_made_effective() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": "banana"},
    )

    profile = resolver.resolve(document, overrides)

    assert profile.report.issues_by_code(GuiMetadataIssueCode.INVALID_OVERRIDE_VALUE)
    assert profile.values["style"]["font_size"] == 14
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.INVALID
    )
    assert resolver.explain(profile, "style.font_size").override_value == "banana"


def test_settings_exposure_marks_only_safe_user_customizable_paths() -> None:
    document = _load_dummy_document()
    exposed_paths = _exposed_setting_paths(document)

    assert "style.font_size" in exposed_paths
    assert "style.density" in exposed_paths
    assert "metadata.contract_id" not in exposed_paths
    assert "actions.dummy_metadata_test.refresh.action_id" not in exposed_paths
    assert "tables.dummy_metadata_test.results_table.table_id" not in exposed_paths


def test_session_state_remains_separate_from_user_overrides() -> None:
    document = _load_dummy_document()
    resolver = GuiMetadataResolver()
    overrides = GuiMetadataOverrideDocument(
        metadata_id=document.metadata_id,
        values={"style.font_size": 11},
    )
    session_state = GuiMetadataSessionState(
        metadata_id=document.metadata_id,
        values={"style.font_size": 13},
    )

    profile = resolver.resolve(document, overrides, session_state)

    assert profile.values["style"]["font_size"] == 13
    assert overrides.values == {"style.font_size": 11}
    assert session_state.values == {"style.font_size": 13}
    assert resolver.explain(profile, "style.font_size").source is (
        ResolvedValueSource.SESSION_STATE
    )
    assert resolver.explain(profile, "style.font_size").override_value == 11
    assert resolver.explain(profile, "style.font_size").session_value == 13


def test_forbidden_executable_field_is_rejected_for_dummy_metadata_shape(
    tmp_path: Path,
) -> None:
    text = _DUMMY_METADATA_PATH.read_text(encoding="utf-8")
    invalid_path = tmp_path / "dummy_with_forbidden_field.toml"
    invalid_path.write_text(f"{text}\n[metadata.rejected]\ncallback = \"noop\"\n", encoding="utf-8")

    result = load_metadata_document(invalid_path)

    assert result.document is None
    assert result.report.issues_by_code(
        GuiMetadataIssueCode.FORBIDDEN_EXECUTABLE_FIELD
    )


def _load_dummy_document():
    result = load_metadata_document(_DUMMY_METADATA_PATH)
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _exposed_setting_paths(document) -> set[str]:
    return {setting.path for setting in document.settings}
