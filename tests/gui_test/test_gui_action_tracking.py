import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from leonardo.core.app import LeonardoApp  # noqa: E402
from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import GuiMetadataOverrideStore  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOW_SOURCES = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "runtime_manager_window.py",
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "gui"
    / "windows"
    / "settings_inspector_window.py",
)


def test_composition_registers_first_gui_action_definitions(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()

    registered_action_ids = {
        definition.action_id for definition in app.action_registry.list_actions()
    }

    assert {
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
        "settings_inspector.save",
        "settings_inspector.apply_changes",
        "runtime_manager.refresh_snapshot",
        "runtime_manager.close",
    } <= registered_action_ids

    _dispose(qapplication, window)
    app.shutdown()


def test_main_window_tracked_actions_are_recorded(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(app.context, track_windows=False, override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    records = app.action_registry.recent_triggers()
    action_ids = _recent_action_ids(app)
    runtime_record = _last_record(app, "main_window.open_runtime_manager")
    settings_record = _last_record(app, "main_window.open_settings_inspector")

    assert "main_window.open_runtime_manager" in action_ids
    assert "main_window.open_settings_inspector" in action_ids
    assert runtime_record.window_id == "main_window.window"
    assert settings_record.window_id == "main_window.window"
    assert all(record.actor_id == "admin-dev" for record in records)
    assert all(record.session_id == "session-admin-dev" for record in records)

    _dispose(
        qapplication,
        window,
        window.runtime_manager_window,
        window.settings_inspector_window,
    )
    app.shutdown()


def test_settings_inspector_save_and_apply_actions_are_recorded_without_semantic_change(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    app = LeonardoApp()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(app.context, track_windows=False, override_store=store)
    window = root.create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()
    dialog = window.settings_inspector_window
    assert isinstance(dialog, SettingsInspectorWindow)

    assert dialog.set_editor_value("style.font_size", "18") is True
    dialog.findChild(QPushButton, "settings_inspector.save").click()
    qapplication.processEvents()

    loaded = store.load("main_window.window")
    assert loaded.document is not None
    assert loaded.document.values == {"style.font_size": 18}
    assert window.font().pointSize() == 14
    assert dict(_last_record(app, "settings_inspector.save").metadata) == {
        "target_metadata_id": "main_window.window",
    }

    assert dialog.set_editor_value("style.font_size", "19") is True
    dialog.findChild(QPushButton, "settings_inspector.apply_changes").click()
    qapplication.processEvents()

    loaded = store.load("main_window.window")
    assert loaded.document is not None
    assert loaded.document.values == {"style.font_size": 19}
    assert window.font().pointSize() == 19
    assert _recent_action_ids(app)[-1] == "settings_inspector.apply_changes"
    assert _recent_action_ids(app).count("settings_inspector.save") == 1
    assert _recent_action_ids(app).count("settings_inspector.apply_changes") == 1

    _dispose(qapplication, window, dialog)
    app.shutdown()


def test_runtime_manager_refresh_and_close_actions_are_recorded_and_visible(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    root = GuiCompositionRoot(app.context, track_windows=False)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window
    assert isinstance(runtime_window, RuntimeManagerWindow)

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    actions_table = runtime_window.table_for_id("runtime_manager.actions_table")
    visible_action_ids = {
        actions_table.item(row, 0).text() for row in range(actions_table.rowCount())
    }

    assert "runtime_manager.refresh_snapshot" in visible_action_ids
    assert _recent_action_ids(app)[-1] == "runtime_manager.refresh_snapshot"
    assert runtime_window.refresh_called is True

    runtime_window.action_button_for_id("runtime_manager.close").click()
    qapplication.processEvents()

    assert _recent_action_ids(app)[-1] == "runtime_manager.close"
    assert runtime_window.close_requested_locally is True
    assert runtime_window.isVisible() is False

    _dispose(qapplication, window, runtime_window)
    app.shutdown()


def test_action_tracking_keeps_qt_windows_free_of_core_concrete_imports() -> None:
    for path in _WINDOW_SOURCES:
        source = path.read_text(encoding="utf-8")

        assert "leonardo.core" not in source
        assert "LeonardoApp" not in source
        assert "ActionRegistry" not in source
        assert "WindowRegistry" not in source
        assert "OperationRegistry" not in source


def _recent_action_ids(app: LeonardoApp) -> tuple[str, ...]:
    return tuple(record.action_id for record in app.action_registry.recent_triggers())


def _last_record(app: LeonardoApp, action_id: str):
    for record in reversed(app.action_registry.recent_triggers()):
        if record.action_id == action_id:
            return record
    raise AssertionError(f"Missing action trigger record: {action_id}")


def _dispose(qapplication: QApplication, *widgets: QWidget | None) -> None:
    for widget in widgets:
        if widget is not None:
            widget.close()
            widget.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
