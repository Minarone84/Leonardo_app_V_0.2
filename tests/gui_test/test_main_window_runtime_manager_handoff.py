import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from leonardo.gui.windows.main_window import (  # noqa: E402
    LeonardoMainWindow,
    load_main_window_profile,
)
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_WINDOW_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "gui" / "windows" / "main_window.py"
)


class FakeRuntimeManagerWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.close_requested_locally = False
        self.read_only = True
        self.setObjectName("fake_runtime_manager_window")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.close_requested_locally = True
        super().closeEvent(event)


class FakeRuntimeManagerFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.window = FakeRuntimeManagerWindow()

    def __call__(self) -> QWidget:
        self.calls += 1
        return self.window


class FakeSnapshotProvider:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> dict[str, object]:
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


def test_main_window_constructs_without_core(qapplication: QApplication) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    assert window.profile.metadata_id == "main_window.window"
    assert window.runtime_manager_window is None

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_action_exists_in_metadata_actions(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    assert "main_window.open_runtime_manager" in window.action_ids()
    assert window.action_for_id("main_window.open_runtime_manager").text() == (
        "Runtime Manager"
    )

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_action_calls_gui_local_factory(
    qapplication: QApplication,
) -> None:
    factory = FakeRuntimeManagerFactory()
    window = LeonardoMainWindow(
        load_main_window_profile(),
        runtime_manager_window_factory=factory,
    )

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()

    assert factory.calls == 1
    assert window.runtime_manager_window is factory.window
    assert factory.window.isVisible() is True
    assert window.statusBar().currentMessage() == "Runtime Manager opened locally."

    factory.window.close()
    window.deleteLater()
    factory.window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_window_reference_is_retained_and_reused(
    qapplication: QApplication,
) -> None:
    factory = FakeRuntimeManagerFactory()
    window = LeonardoMainWindow(
        load_main_window_profile(),
        runtime_manager_window_factory=factory,
    )

    window.action_for_id("main_window.open_runtime_manager").trigger()
    first_runtime_window = window.runtime_manager_window
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()

    assert factory.calls == 1
    assert first_runtime_window is factory.window
    assert window.runtime_manager_window is first_runtime_window
    assert window.statusBar().currentMessage() == "Runtime Manager raised locally."

    factory.window.close()
    window.deleteLater()
    factory.window.deleteLater()
    qapplication.processEvents()


def test_handoff_requires_no_app_or_runtime_backend() -> None:
    source = _MAIN_WINDOW_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoApp" not in source
    assert "RuntimeManagerBackend" not in source
    assert "StateStore" not in source
    assert "WindowRegistry" not in source
    assert "ActionRegistry" not in source
    assert "OperationRegistry" not in source


def test_runtime_manager_view_remains_read_only_through_handoff(
    qapplication: QApplication,
) -> None:
    provider = FakeSnapshotProvider()
    window = LeonardoMainWindow(
        load_main_window_profile(),
        runtime_snapshot_provider=provider,
    )

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert runtime_window.refresh_called is False
    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert provider.calls == 1
    assert runtime_window.refresh_called is True
    assert runtime_window.last_rendered_snapshot_summary["service_rows"] == 1

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_main_window_destroys_cleanly_with_runtime_manager_child(
    qapplication: QApplication,
) -> None:
    factory = FakeRuntimeManagerFactory()
    window = LeonardoMainWindow(
        load_main_window_profile(),
        runtime_manager_window_factory=factory,
    )
    window.show()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()

    window.close()
    window.deleteLater()
    factory.window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True
    assert factory.window.close_requested_locally is True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
