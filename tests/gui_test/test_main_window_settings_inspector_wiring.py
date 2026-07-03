import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import GuiMetadataOverrideStore  # noqa: E402
from leonardo.gui.windows.main_window import (  # noqa: E402
    LeonardoMainWindow,
    load_main_window_profile,
)
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_WINDOW_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py"
_RUNTIME_MANAGER_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "runtime_manager_window.py"
)
_CORE_ROOT = _REPO_ROOT / "src" / "leonardo" / "core"


class FakeSettingsDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.raise_calls = 0
        self.activate_calls = 0

    def raise_(self) -> None:
        self.raise_calls += 1
        super().raise_()

    def activateWindow(self) -> None:
        self.activate_calls += 1
        super().activateWindow()


class FakeRuntimeManager:
    def snapshot(self) -> dict[str, object]:
        return {"health": "ok", "sections": (), "recent_audit_events": ()}


class FakeCoreContext:
    def __init__(self) -> None:
        self.runtime_manager = FakeRuntimeManager()


def test_main_window_accepts_injected_settings_inspector_factory(
    qapplication: QApplication,
) -> None:
    created: list[FakeSettingsDialog] = []

    def factory() -> FakeSettingsDialog:
        dialog = FakeSettingsDialog()
        created.append(dialog)
        return dialog

    window = LeonardoMainWindow(
        load_main_window_profile(),
        settings_inspector_factory=factory,
    )

    assert window.settings_inspector_window is None
    assert window.action_for_id("main_window.open_settings_inspector").text() == (
        "Open Settings Inspector"
    )

    _dispose(qapplication, window, *created)


def test_settings_action_calls_factory_and_shows_dialog(
    qapplication: QApplication,
) -> None:
    created: list[FakeSettingsDialog] = []

    def factory() -> FakeSettingsDialog:
        dialog = FakeSettingsDialog()
        created.append(dialog)
        return dialog

    window = LeonardoMainWindow(
        load_main_window_profile(),
        settings_inspector_factory=factory,
    )

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert len(created) == 1
    assert window.settings_inspector_window is created[0]
    assert created[0].isVisible() is True
    assert created[0].raise_calls == 1
    assert created[0].activate_calls == 1
    assert window.statusBar().currentMessage() == "Settings inspector opened locally."

    _dispose(qapplication, window, *created)


def test_settings_action_reuses_retained_dialog(
    qapplication: QApplication,
) -> None:
    created: list[FakeSettingsDialog] = []

    def factory() -> FakeSettingsDialog:
        dialog = FakeSettingsDialog()
        created.append(dialog)
        return dialog

    window = LeonardoMainWindow(
        load_main_window_profile(),
        settings_inspector_factory=factory,
    )

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()
    created[0].close()
    qapplication.processEvents()
    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert len(created) == 1
    assert window.settings_inspector_window is created[0]
    assert created[0].isVisible() is True
    assert created[0].raise_calls == 2
    assert created[0].activate_calls == 2
    assert window.statusBar().currentMessage() == "Settings inspector raised locally."

    _dispose(qapplication, window, *created)


def test_settings_action_remains_inert_without_factory(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert window.settings_inspector_window is None
    assert window.statusBar().currentMessage() == (
        "Settings inspector action is local/inert."
    )

    _dispose(qapplication, window)


def test_composition_wires_real_settings_inspector_when_override_store_is_injected(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(
        FakeCoreContext(),
        track_windows=False,
        override_store=store,
    )
    window = root.create_main_window()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert isinstance(window.settings_inspector_window, SettingsInspectorWindow)
    assert window.settings_inspector_window.viewmodel.metadata_id == "main_window.window"
    assert store.path_for("main_window.window").exists() is False

    _dispose(qapplication, window, window.settings_inspector_window)


def test_main_window_does_not_own_settings_metadata_or_store_logic() -> None:
    source = _MAIN_WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "SettingsInspectorWindow" not in source
    assert "GuiSettingsInspectorViewModel" not in source
    assert "GuiMetadataOverrideStore" not in source
    assert "json.load" not in source
    assert "json.dump" not in source
    assert "read_text" not in source
    assert "write_text" not in source
    assert "settings_inspector.window.toml" not in source


def test_runtime_manager_remains_unwired_to_settings_inspector() -> None:
    source = _RUNTIME_MANAGER_SOURCE.read_text(encoding="utf-8")

    assert "SettingsInspectorWindow" not in source
    assert "GuiSettingsInspectorViewModel" not in source
    assert "open_settings_inspector" not in source


def test_core_remains_free_of_settings_inspector_ownership() -> None:
    forbidden = ("SettingsInspectorWindow", "GuiSettingsInspectorViewModel")
    for path in _CORE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in source


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
