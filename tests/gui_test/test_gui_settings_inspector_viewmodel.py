import ast
import json
from pathlib import Path

from leonardo.gui.metadata import (
    GuiDisplayDefaults,
    GuiMetadataDocument,
    GuiMetadataKind,
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    GuiSettingExposure,
    GuiStyleDefaults,
    load_metadata_document,
)
from leonardo.gui.settings_inspector import (
    GuiSettingsInspectorRowSource,
    GuiSettingsInspectorViewModel,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)
_RUNTIME_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "metadata"
    / "windows"
    / "runtime_manager.window.toml"
)
_SETTINGS_INSPECTOR_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "settings_inspector.py"


def test_viewmodel_exposes_only_metadata_declared_settings(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    viewmodel = _viewmodel(document, tmp_path)

    assert viewmodel.exposed_paths() == ("style.font_size", "style.density")
    assert "geometry.width" not in viewmodel.exposed_paths()
    assert "metadata.contract_id" not in viewmodel.exposed_paths()


def test_main_window_settings_rows_include_style_settings(tmp_path: Path) -> None:
    viewmodel = _viewmodel(_load_document(_MAIN_METADATA_PATH), tmp_path)

    assert {row.path for row in viewmodel.rows} == {
        "style.font_size",
        "style.density",
    }


def test_runtime_manager_settings_rows_include_style_settings(tmp_path: Path) -> None:
    viewmodel = _viewmodel(_load_document(_RUNTIME_METADATA_PATH), tmp_path)

    assert {row.path for row in viewmodel.rows} == {
        "style.font_size",
        "style.density",
    }


def test_row_contains_required_settings_state(tmp_path: Path) -> None:
    viewmodel = _viewmodel(_load_document(_MAIN_METADATA_PATH), tmp_path)

    row = viewmodel.row_for_path("style.font_size")

    assert row.path == "style.font_size"
    assert row.label == "Font Size"
    assert row.value_type == "integer"
    assert row.description == "Default text size for the Leonardo shell."
    assert row.default_value == 14
    assert row.effective_value == 14
    assert row.override_value is None
    assert row.source is GuiSettingsInspectorRowSource.DEFAULT
    assert row.dirty is False
    assert row.diagnostics == ()


def test_persisted_override_row_is_marked_as_override_source(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={"style.font_size": 18},
        )
    )

    row = GuiSettingsInspectorViewModel(document, store).row_for_path("style.font_size")

    assert row.source is GuiSettingsInspectorRowSource.OVERRIDE
    assert row.effective_value == 18
    assert row.override_value == 18
    assert row.dirty is False


def test_local_edit_marks_row_dirty_and_does_not_write_file(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    result = viewmodel.edit_value("style.font_size", "18")
    row = viewmodel.row_for_path("style.font_size")

    assert result.ok is True
    assert row.source is GuiSettingsInspectorRowSource.DIRTY
    assert row.dirty is True
    assert row.override_value == 18
    assert store.path_for(document.metadata_id).exists() is False


def test_save_writes_changed_only_override_json(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    viewmodel.edit_value("style.font_size", "18")
    result = viewmodel.save()
    payload = _load_payload(store.path_for(document.metadata_id))

    assert result.ok is True
    assert payload["overrides"] == {"style.font_size": 18}


def test_save_does_not_persist_defaults(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={"style.font_size": 18, "style.density": "compact"},
        )
    )
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    viewmodel.edit_value("style.font_size", "14")
    result = viewmodel.save()
    payload = _load_payload(store.path_for(document.metadata_id))

    assert result.ok is True
    assert payload["overrides"] == {"style.density": "compact"}


def test_integer_parsing_accepts_valid_integers_and_rejects_invalid_values(
    tmp_path: Path,
) -> None:
    viewmodel = _viewmodel(_load_document(_MAIN_METADATA_PATH), tmp_path)

    valid = viewmodel.edit_value("style.font_size", "19")
    invalid = viewmodel.edit_value("style.font_size", "banana")

    assert valid.ok is True
    assert valid.value == 19
    assert invalid.ok is False
    assert invalid.diagnostics[0].code == "invalid_integer"
    assert viewmodel.row_for_path("style.font_size").source is (
        GuiSettingsInspectorRowSource.INVALID
    )


def test_boolean_parsing_is_deterministic_for_synthetic_metadata(tmp_path: Path) -> None:
    document = _synthetic_document(
        settings=(
            GuiSettingExposure(
                path="display.visible",
                label="Visible",
                value_type="boolean",
            ),
        )
    )
    viewmodel = _viewmodel(document, tmp_path)

    true_result = viewmodel.edit_value("display.visible", "yes")
    false_result = viewmodel.edit_value("display.visible", "0")
    invalid_result = viewmodel.edit_value("display.visible", "maybe")

    assert true_result.ok is True
    assert true_result.value is True
    assert false_result.ok is True
    assert false_result.value is False
    assert invalid_result.ok is False
    assert invalid_result.diagnostics[0].code == "invalid_boolean"


def test_string_parsing_preserves_text(tmp_path: Path) -> None:
    viewmodel = _viewmodel(_load_document(_MAIN_METADATA_PATH), tmp_path)

    result = viewmodel.edit_value("style.density", "compact mode")

    assert result.ok is True
    assert result.value == "compact mode"
    assert viewmodel.row_for_path("style.density").override_value == "compact mode"


def test_unknown_value_type_produces_diagnostic_and_blocks_save(tmp_path: Path) -> None:
    document = _synthetic_document(
        settings=(
            GuiSettingExposure(
                path="style.density",
                label="Density",
                value_type="choice",
            ),
        )
    )
    viewmodel = _viewmodel(document, tmp_path)

    edit_result = viewmodel.edit_value("style.density", "compact")
    save_result = viewmodel.save()

    assert edit_result.ok is False
    assert edit_result.diagnostics[0].code == "unknown_value_type"
    assert save_result.ok is False
    assert save_result.diagnostics[0].code == "unknown_value_type"


def test_resolver_validation_blocks_invalid_override_value(tmp_path: Path) -> None:
    document = _synthetic_document(
        settings=(
            GuiSettingExposure(
                path="style.font_size",
                label="Font Size",
                value_type="string",
            ),
        )
    )
    viewmodel = _viewmodel(document, tmp_path)

    edit_result = viewmodel.edit_value("style.font_size", "large")
    save_result = viewmodel.save()

    assert edit_result.ok is False
    assert edit_result.diagnostics[0].code == "invalid_override_value"
    assert viewmodel.row_for_path("style.font_size").source is (
        GuiSettingsInspectorRowSource.INVALID
    )
    assert save_result.ok is False


def test_resolver_validation_blocks_stale_setting_path(tmp_path: Path) -> None:
    document = _synthetic_document(
        settings=(
            GuiSettingExposure(
                path="style.missing",
                label="Missing",
                value_type="string",
            ),
        )
    )
    viewmodel = _viewmodel(document, tmp_path)

    edit_result = viewmodel.edit_value("style.missing", "value")

    assert edit_result.ok is False
    assert edit_result.diagnostics[0].code == "stale_override_path"
    assert viewmodel.row_for_path("style.missing").source is (
        GuiSettingsInspectorRowSource.INVALID
    )


def test_reset_field_removes_only_one_override(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={"style.font_size": 18, "style.density": "compact"},
        )
    )
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    result = viewmodel.reset_field("style.font_size")
    payload = _load_payload(store.path_for(document.metadata_id))

    assert result.ok is True
    assert payload["overrides"] == {"style.density": "compact"}
    assert viewmodel.row_for_path("style.font_size").source is (
        GuiSettingsInspectorRowSource.DEFAULT
    )


def test_reset_section_removes_only_matching_section_keys(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={
                "style.font_size": 18,
                "style.density": "compact",
                "geometry.width": 1300,
            },
        )
    )
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    result = viewmodel.reset_section("style")
    loaded = store.load(document.metadata_id)

    assert result.ok is True
    assert loaded.document is not None
    assert loaded.document.values == {"geometry.width": 1300}


def test_reset_profile_deletes_override_file(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.save(
        GuiMetadataOverrideDocument(
            metadata_id=document.metadata_id,
            values={"style.font_size": 18},
        )
    )
    path = store.path_for(document.metadata_id)
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    result = viewmodel.reset_profile()

    assert result.ok is True
    assert path.exists() is False
    assert viewmodel.row_for_path("style.font_size").source is (
        GuiSettingsInspectorRowSource.DEFAULT
    )


def test_corrupt_override_diagnostics_are_exposed_with_default_rows(
    tmp_path: Path,
) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    store.root.mkdir(parents=True)
    store.path_for(document.metadata_id).write_text("{not json", encoding="utf-8")

    viewmodel = GuiSettingsInspectorViewModel(document, store)
    row = viewmodel.row_for_path("style.font_size")

    assert viewmodel.diagnostics[0].code == "corrupt_json"
    assert row.default_value == 14
    assert row.effective_value == 14
    assert row.source is GuiSettingsInspectorRowSource.DEFAULT


def test_session_state_is_not_exposed_or_persisted(tmp_path: Path) -> None:
    document = _load_document(_MAIN_METADATA_PATH)
    store = _store(tmp_path)
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    viewmodel.edit_value("style.font_size", "18")
    result = viewmodel.save()
    payload = _load_payload(store.path_for(document.metadata_id))

    assert result.ok is True
    assert all("session" not in path for path in viewmodel.exposed_paths())
    assert "session" not in payload
    assert "session_state" not in payload


def test_source_metadata_toml_is_not_mutated(tmp_path: Path) -> None:
    before = _MAIN_METADATA_PATH.read_text(encoding="utf-8")
    document = _load_document(_MAIN_METADATA_PATH)
    viewmodel = _viewmodel(document, tmp_path)

    viewmodel.edit_value("style.font_size", "18")
    viewmodel.save()
    viewmodel.reset_profile()

    assert _MAIN_METADATA_PATH.read_text(encoding="utf-8") == before


def test_viewmodel_requires_no_qt_core_or_window_imports() -> None:
    tree = ast.parse(_SETTINGS_INSPECTOR_SOURCE.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)

    assert all(not module.startswith("PySide") for module in imported_modules)
    assert all(not module.startswith("PyQt") for module in imported_modules)
    assert all(not module.startswith("leonardo.core") for module in imported_modules)
    assert all(not module.startswith("leonardo.gui.windows") for module in imported_modules)


def test_viewmodel_does_not_instantiate_application_startup() -> None:
    source = _SETTINGS_INSPECTOR_SOURCE.read_text(encoding="utf-8")

    assert "Leonardo" + "App" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source


def test_viewmodel_does_not_require_qapplication() -> None:
    source = _SETTINGS_INSPECTOR_SOURCE.read_text(encoding="utf-8")

    assert "QApplication" not in source


def test_no_main_window_or_runtime_manager_wiring_is_added() -> None:
    source = _SETTINGS_INSPECTOR_SOURCE.read_text(encoding="utf-8")

    assert "main_window" not in source
    assert "runtime_manager" not in source


def _load_document(path: Path) -> GuiMetadataDocument:
    result = load_metadata_document(path)
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _store(tmp_path: Path) -> GuiMetadataOverrideStore:
    return GuiMetadataOverrideStore(tmp_path / "overrides")


def _viewmodel(
    document: GuiMetadataDocument,
    tmp_path: Path,
) -> GuiSettingsInspectorViewModel:
    return GuiSettingsInspectorViewModel(document, _store(tmp_path))


def _load_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _synthetic_document(
    *,
    settings: tuple[GuiSettingExposure, ...],
) -> GuiMetadataDocument:
    return GuiMetadataDocument(
        metadata_id="synthetic_settings.window",
        kind=GuiMetadataKind.WINDOW,
        schema_version="1",
        title="Synthetic Settings",
        display=GuiDisplayDefaults(visible=True, enabled=True, theme="system"),
        style=GuiStyleDefaults(font_size=14, density="comfortable"),
        settings=settings,
    )
