import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.gui.composition import GuiCompositionRoot  # noqa: E402
from leonardo.gui.metadata import GuiMetadataOverrideStore  # noqa: E402
from leonardo.gui.settings_profiles import (  # noqa: E402
    MAIN_WINDOW_SETTINGS_PROFILE_ID,
    RUNTIME_MANAGER_SETTINGS_PROFILE_ID,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import (  # noqa: E402
    RUNTIME_MANAGER_METADATA_ID,
    RuntimeManagerWindow,
)
from leonardo.gui.windows.settings_inspector_window import (  # noqa: E402
    SettingsInspectorWindow,
)


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "health": "ok",
            "sections": (
                {
                    "section_id": "services",
                    "status": "ok",
                    "count": 1,
                    "message": "1 service visible",
                    "metadata": {"service_ids": ("runtime-service",)},
                },
            ),
            "recent_audit_events": (),
        }


class FakeCoreContext:
    def __init__(self) -> None:
        self.runtime_manager = FakeRuntimeManager()


def test_gui_composition_smoke_opens_runtime_manager_and_settings_inspector(
    qapplication: QApplication,
    tmp_path: Path,
) -> None:
    context = FakeCoreContext()
    store = GuiMetadataOverrideStore(tmp_path / "overrides")
    root = GuiCompositionRoot(
        context,
        track_windows=False,
        override_store=store,
    )

    window = root.create_main_window()
    assert isinstance(window, LeonardoMainWindow)
    assert root.window_trackers == {}
    assert QApplication.instance() is qapplication

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.profile.metadata_id == RUNTIME_MANAGER_METADATA_ID
    assert runtime_window.refresh_called is False
    assert context.runtime_manager.calls == 0
    assert "runtime_manager.open_settings" not in runtime_window.action_labels()
    assert "runtime_manager.settings" not in runtime_window.action_labels()

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()
    settings_window = window.settings_inspector_window

    assert isinstance(settings_window, SettingsInspectorWindow)
    assert settings_window.viewmodel.metadata_id == MAIN_WINDOW_SETTINGS_PROFILE_ID
    assert settings_window.viewmodel.metadata_id != RUNTIME_MANAGER_SETTINGS_PROFILE_ID
    assert store.path_for(MAIN_WINDOW_SETTINGS_PROFILE_ID).exists() is False
    assert store.path_for(RUNTIME_MANAGER_SETTINGS_PROFILE_ID).exists() is False
    assert runtime_window is not settings_window
    assert context.runtime_manager.calls == 0

    _dispose(qapplication, window, runtime_window, settings_window)


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
