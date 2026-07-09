import ast
import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget, QWidget  # noqa: E402

from leonardo.gui.action_observer import GuiActionDecision  # noqa: E402
from leonardo.gui.metadata import (  # noqa: E402
    GuiMetadataOverrideDocument,
    GuiMetadataOverrideStore,
    load_metadata_document,
)
from leonardo.gui.settings_inspector import GuiSettingsInspectorViewModel  # noqa: E402
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
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
_WINDOW_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "settings_inspector_window.py"
)
_SETTINGS_BUTTON_ACTION_IDS = (
    "settings_inspector.save",
    "settings_inspector.apply_changes",
    "settings_inspector.reset_field",
    "settings_inspector.reset_section",
    "settings_inspector.reset_profile",
    "settings_inspector.close",
)


def test_dialog_constructs_with_injected_viewmodel(qapplication: QApplication, tmp_path: Path) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.viewmodel is viewmodel
    assert window.objectName() == "settings_inspector_window"
    assert window.property("object_id") == "settings_inspector.window"
    assert window.property("theme_id") == "leonardo_jarvish_cockpit"
    assert window.findChild(QLabel, "settings_inspector.label.title") is not None
    assert window.findChild(QLabel, "settings_inspector.label.source_status") is not None
    assert window.findChild(QLabel, "settings_inspector.label.theme_status") is not None
    assert window.findChild(QTableWidget, "settings_inspector.settings_table") is not None
    assert window.findChild(QPushButton, "settings_inspector.save") is not None
    assert window.findChild(QPushButton, "settings_inspector.apply_changes") is not None
    assert window.findChild(QPushButton, "settings_inspector.reset_field") is not None
    assert window.findChild(QPushButton, "settings_inspector.reset_section") is not None
    assert window.findChild(QPushButton, "settings_inspector.reset_profile") is not None
    assert window.findChild(QPushButton, "settings_inspector.close") is not None

    _dispose(qapplication, window)


def test_dialog_uses_jarvish_utility_panel_structure(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.findChild(QLabel, "settings_inspector.label.theme_status").text() == (
        "Theme: Leonardo Jarvish Cockpit"
    )
    assert window.findChild(QLabel, "settings_inspector.label.source_status").text() == (
        "Profile: main_window.window"
    )
    for object_id in (
        "settings_inspector.panel.header",
        "settings_inspector.panel.settings",
        "settings_inspector.panel.editor",
        "settings_inspector.panel.controls",
        "settings_inspector.panel.diagnostics",
        "settings_inspector.label.value",
    ):
        assert window.findChild(QWidget, object_id) is not None

    assert window.settings_table.property("parent_object_id") == (
        "settings_inspector.panel.settings"
    )
    assert window.value_editor.property("parent_object_id") == (
        "settings_inspector.panel.editor"
    )
    assert window.diagnostics_view.property("parent_object_id") == (
        "settings_inspector.panel.diagnostics"
    )
    for action_id in _SETTINGS_BUTTON_ACTION_IDS:
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.property("action_id") == action_id

    _dispose(qapplication, window)


def test_dialog_clickable_buttons_have_stable_object_and_action_ids(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    for action_id in _SETTINGS_BUTTON_ACTION_IDS:
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.property("object_id") == action_id
        assert button.property("object_type") == "button"
        assert button.property("action_id") == action_id
        assert button.property("parent_object_id") == "settings_inspector.panel.controls"

    _dispose(qapplication, window)


def test_dialog_lists_metadata_declared_rows(qapplication: QApplication, tmp_path: Path) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.exposed_setting_paths() == ("style.font_size", "style.density")
    assert window.settings_table.rowCount() == 2
    assert window.row_snapshot("style.font_size")["label"] == "Font Size"
    assert window.row_snapshot("style.font_size")["value_type"] == "integer"
    assert window.row_snapshot("style.font_size")["effective_value"] == "14"
    assert window.row_snapshot("style.density")["value_type"] == "string"

    _dispose(qapplication, window)


def test_dialog_does_not_write_files_during_construction(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)

    window = SettingsInspectorWindow(viewmodel)

    assert store.path_for(viewmodel.metadata_id).exists() is False

    _dispose(qapplication, window)


def test_editing_field_marks_row_dirty_without_saving_file(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.set_editor_value("style.font_size", "18") is True
    row = window.row_snapshot("style.font_size")

    assert row["source"] == "dirty"
    assert row["dirty"] == "yes"
    assert row["override_value"] == "18"
    assert store.path_for(viewmodel.metadata_id).exists() is False

    _dispose(qapplication, window)


def test_save_writes_changed_only_override_through_viewmodel(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.set_editor_value("style.font_size", "18") is True
    assert window.save_settings() is True
    payload = _load_payload(store.path_for(viewmodel.metadata_id))

    assert payload["overrides"] == {"style.font_size": 18}
    assert window.row_snapshot("style.font_size")["source"] == "override"
    assert window.row_snapshot("style.font_size")["dirty"] == "no"

    _dispose(qapplication, window)


def test_apply_changes_saves_and_calls_injected_callback(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    applied: list[tuple[str, object]] = []
    window = SettingsInspectorWindow(
        viewmodel,
        on_apply=lambda metadata_id, profile: applied.append((metadata_id, profile)),
    )

    assert window.set_editor_value("style.font_size", "18") is True
    window.findChild(QPushButton, "settings_inspector.apply_changes").click()
    qapplication.processEvents()
    payload = _load_payload(store.path_for(viewmodel.metadata_id))

    assert payload["overrides"] == {"style.font_size": 18}
    assert len(applied) == 1
    assert applied[0][0] == "main_window.window"
    assert applied[0][1].metadata_id == "main_window.window"
    assert applied[0][1].values["style"]["font_size"] == 18

    _dispose(qapplication, window)


def test_apply_changes_does_not_call_callback_on_invalid_edit(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    applied: list[tuple[str, object]] = []
    window = SettingsInspectorWindow(
        viewmodel,
        on_apply=lambda metadata_id, profile: applied.append((metadata_id, profile)),
    )

    assert window.set_editor_value("style.font_size", "banana") is False
    assert window.apply_changes() is False

    assert applied == []
    assert store.path_for(viewmodel.metadata_id).exists() is False

    _dispose(qapplication, window)


def test_apply_changes_surfaces_callback_errors(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    failure = RuntimeError("apply failed")
    calls = 0

    def callback(_metadata_id: str, _profile: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure

    window = SettingsInspectorWindow(viewmodel, on_apply=callback)

    assert window.set_editor_value("style.font_size", "18") is True
    with pytest.raises(RuntimeError) as exc_info:
        window.apply_changes()

    assert exc_info.value is failure

    _dispose(qapplication, window)


def test_save_persists_without_applying_immediately(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    applied: list[tuple[str, object]] = []
    window = SettingsInspectorWindow(
        viewmodel,
        on_apply=lambda metadata_id, profile: applied.append((metadata_id, profile)),
    )

    assert window.set_editor_value("style.font_size", "18") is True
    assert window.save_settings() is True
    payload = _load_payload(store.path_for(viewmodel.metadata_id))

    assert payload["overrides"] == {"style.font_size": 18}
    assert applied == []

    _dispose(qapplication, window)


def test_close_applies_saved_but_unapplied_change_once(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    applied: list[tuple[str, object]] = []
    window = SettingsInspectorWindow(
        viewmodel,
        on_apply=lambda metadata_id, profile: applied.append((metadata_id, profile)),
    )

    assert window.set_editor_value("style.font_size", "18") is True
    assert window.save_settings() is True
    assert applied == []

    window.close()
    qapplication.processEvents()
    window.close()
    qapplication.processEvents()

    assert len(applied) == 1
    assert applied[0][0] == "main_window.window"
    assert applied[0][1].values["style"]["font_size"] == 18

    window.deleteLater()
    qapplication.processEvents()


def test_close_with_dirty_unsaved_edit_does_not_save_or_apply(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    applied: list[tuple[str, object]] = []
    window = SettingsInspectorWindow(
        viewmodel,
        on_apply=lambda metadata_id, profile: applied.append((metadata_id, profile)),
    )

    assert window.set_editor_value("style.font_size", "18") is True
    window.close()
    qapplication.processEvents()

    assert applied == []
    assert store.path_for(viewmodel.metadata_id).exists() is False

    window.deleteLater()
    qapplication.processEvents()


def test_invalid_integer_input_shows_diagnostics_and_does_not_save(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.set_editor_value("style.font_size", "banana") is False
    assert "invalid_integer" in window.diagnostics_text()
    assert window.save_settings() is False

    assert store.path_for(viewmodel.metadata_id).exists() is False

    _dispose(qapplication, window)


def test_reset_field_removes_one_override_and_refreshes_display(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(
        tmp_path,
        overrides={"style.font_size": 18, "style.density": "compact"},
    )
    window = SettingsInspectorWindow(viewmodel)

    window.select_setting("style.font_size")
    assert window.reset_selected_field() is True
    payload = _load_payload(store.path_for(viewmodel.metadata_id))

    assert payload["overrides"] == {"style.density": "compact"}
    assert window.row_snapshot("style.font_size")["source"] == "default"
    assert window.row_snapshot("style.font_size")["effective_value"] == "14"
    assert window.row_snapshot("style.density")["source"] == "override"

    _dispose(qapplication, window)


def test_reset_section_removes_matching_section_only(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(
        tmp_path,
        overrides={
            "style.font_size": 18,
            "style.density": "compact",
            "geometry.width": 1300,
        },
    )
    window = SettingsInspectorWindow(viewmodel)

    window.select_setting("style.font_size")
    assert window.reset_selected_section() is True
    loaded = store.load(viewmodel.metadata_id)

    assert loaded.document is not None
    assert loaded.document.values == {"geometry.width": 1300}
    assert window.row_snapshot("style.font_size")["source"] == "default"
    assert window.row_snapshot("style.density")["source"] == "default"

    _dispose(qapplication, window)


def test_reset_profile_deletes_override_file_and_refreshes_display(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, store = _viewmodel(tmp_path, overrides={"style.font_size": 18})
    path = store.path_for(viewmodel.metadata_id)
    window = SettingsInspectorWindow(viewmodel)

    assert path.exists() is True
    assert window.reset_profile() is True

    assert path.exists() is False
    assert window.row_snapshot("style.font_size")["source"] == "default"
    assert window.row_snapshot("style.font_size")["effective_value"] == "14"

    _dispose(qapplication, window)


@pytest.mark.parametrize(
    ("action_id", "selected_path"),
    (
        ("settings_inspector.reset_field", "style.font_size"),
        ("settings_inspector.reset_section", "style.font_size"),
        ("settings_inspector.reset_profile", None),
    ),
)
def test_reset_button_actions_obey_blocked_action_observer(
    qapplication: QApplication,
    tmp_path: Path,
    action_id: str,
    selected_path: str | None,
) -> None:
    viewmodel, store = _viewmodel(
        tmp_path,
        overrides={
            "style.font_size": 18,
            "style.density": "compact",
            "geometry.width": 1300,
        },
    )
    observer = _RecordingActionObserver(blocked_action_ids={action_id})
    window = SettingsInspectorWindow(viewmodel, action_observer=observer)
    path = store.path_for(viewmodel.metadata_id)
    before = _load_payload(path)

    if selected_path is not None:
        window.select_setting(selected_path)
    window.findChild(QPushButton, action_id).click()
    qapplication.processEvents()

    assert observer.records == (
        (action_id, {"target_metadata_id": "main_window.window"}),
    )
    assert _load_payload(path) == before

    _dispose(qapplication, window)


def test_close_button_action_obeys_blocked_action_observer(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    viewmodel, _store = _viewmodel(tmp_path)
    observer = _RecordingActionObserver(
        blocked_action_ids={"settings_inspector.close"}
    )
    window = SettingsInspectorWindow(viewmodel, action_observer=observer)
    window.show()
    qapplication.processEvents()

    window.findChild(QPushButton, "settings_inspector.close").click()
    qapplication.processEvents()

    assert observer.records == (
        (
            "settings_inspector.close",
            {"target_metadata_id": "main_window.window"},
        ),
    )
    assert window.isVisible() is True

    _dispose(qapplication, window)


def test_corrupt_override_diagnostics_are_displayed_without_crash(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    document = _load_document()
    store.root.mkdir(parents=True)
    store.path_for(document.metadata_id).write_text("{not json", encoding="utf-8")
    viewmodel = GuiSettingsInspectorViewModel(document, store)

    window = SettingsInspectorWindow(viewmodel)

    assert "corrupt_json" in window.diagnostics_text()
    assert window.row_snapshot("style.font_size")["source"] == "default"

    _dispose(qapplication, window)


def test_dialog_has_no_core_dependency() -> None:
    imported_modules = _imported_modules(_WINDOW_SOURCE)

    assert all(not module.startswith("leonardo.core") for module in imported_modules)


def test_dialog_does_not_instantiate_application_startup() -> None:
    source = _WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "Leonardo" + "App" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source


def test_dialog_does_not_require_main_window_wiring() -> None:
    source = _WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "main_window" not in source
    assert "LeonardoMainWindow" not in source


def test_dialog_does_not_require_runtime_manager_wiring() -> None:
    source = _WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "runtime_manager" not in source
    assert "RuntimeManagerWindow" not in source


def test_dialog_does_not_mutate_source_toml(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    before = _MAIN_METADATA_PATH.read_text(encoding="utf-8")
    viewmodel, _store = _viewmodel(tmp_path)
    window = SettingsInspectorWindow(viewmodel)

    assert window.set_editor_value("style.font_size", "18") is True
    assert window.save_settings() is True
    assert window.reset_profile() is True

    assert _MAIN_METADATA_PATH.read_text(encoding="utf-8") == before

    _dispose(qapplication, window)


def test_dialog_uses_viewmodel_without_resolver_or_store_logic() -> None:
    source = _WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "GuiSettingsInspectorViewModel" in source
    assert "GuiMetadataResolver" not in source
    assert "GuiMetadataOverrideStore" not in source
    assert "GuiMetadataOverrideDocument" not in source
    assert "load_metadata_document" not in source


def _load_document():
    result = load_metadata_document(_MAIN_METADATA_PATH)
    assert result.document is not None
    assert result.report.has_errors is False
    return result.document


def _viewmodel(
    tmp_path: Path,
    *,
    overrides: dict[str, object] | None = None,
) -> tuple[GuiSettingsInspectorViewModel, GuiMetadataOverrideStore]:
    document = _load_document()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    if overrides is not None:
        result = store.save(
            GuiMetadataOverrideDocument(
                metadata_id=document.metadata_id,
                values=overrides,
            )
        )
        assert result.ok is True
    return GuiSettingsInspectorViewModel(document, store), store


def _load_payload(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.append(node.module)
    return tuple(imported_modules)


def _dispose(qapplication: QApplication, *windows: SettingsInspectorWindow) -> None:
    for window in windows:
        window.close()
        window.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()


class _RecordingActionObserver:
    def __init__(self, *, blocked_action_ids: set[str] | None = None) -> None:
        self._blocked_action_ids = blocked_action_ids or set()
        self.records: tuple[tuple[str, dict[str, object]], ...] = ()

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> GuiActionDecision:
        del window_id
        record = (action_id, dict(metadata or {}))
        self.records = (*self.records, record)
        return GuiActionDecision(
            action_id=action_id,
            allowed=action_id not in self._blocked_action_ids,
        )
