import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from leonardo.gui.windows.main_window import (  # noqa: E402
    LeonardoMainWindow,
    load_main_window_profile,
)


def test_main_window_effective_profile_loads() -> None:
    profile = load_main_window_profile()

    assert profile.metadata_id == "main_window.window"
    assert profile.values["identity"]["title"] == "Leonardo"
    assert profile.report.has_errors is False


def test_main_window_constructs_from_metadata(qapplication: QApplication) -> None:
    profile = load_main_window_profile()
    window = LeonardoMainWindow(profile)

    assert window.profile is profile
    assert window.windowTitle() == "Leonardo"
    assert window.metadata_title == "Leonardo"
    assert window.objectName() == "main_window"
    assert window.findChild(QLabel, "main_window.title_label").text() == "Leonardo"

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_metadata_action_labels_are_present(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    assert window.action_ids() == (
        "main_window.exit",
        "main_window.open_dummy_metadata_test",
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
    )
    assert window.action_labels() == {
        "main_window.exit": "Exit",
        "main_window.open_dummy_metadata_test": "Open Dummy Metadata Test",
        "main_window.open_runtime_manager": "Open Runtime Manager",
        "main_window.open_settings_inspector": "Open Settings Inspector",
    }
    for action_id in window.action_ids():
        action = window.findChild(QAction, action_id)
        assert action is not None
        assert action.text() == window.action_labels()[action_id]

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_non_exit_actions_are_local_and_inert(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    window.action_for_id("main_window.open_dummy_metadata_test").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.open_dummy_metadata_test"
    assert window.statusBar().currentMessage() == (
        "Dummy metadata test action is local/inert."
    )
    assert window.isVisible() is False

    window.action_for_id("main_window.open_settings_inspector").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.open_settings_inspector"
    assert window.statusBar().currentMessage() == (
        "Settings inspector action is local/inert."
    )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_exit_action_closes_locally(qapplication: QApplication) -> None:
    window = LeonardoMainWindow(load_main_window_profile())
    window.show()
    qapplication.processEvents()

    window.action_for_id("main_window.exit").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.exit"
    assert window.close_requested_locally is True
    assert window.isVisible() is False

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_requires_no_app_or_core_services(qapplication: QApplication) -> None:
    window = LeonardoMainWindow()

    assert window.profile.metadata_id == "main_window.window"
    assert window.action_for_id("main_window.exit").text() == "Exit"

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_runtime_manager_action_exists_from_metadata(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    assert "main_window.open_runtime_manager" in window.action_ids()
    assert window.action_for_id("main_window.open_runtime_manager").text() == (
        "Open Runtime Manager"
    )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_can_be_destroyed_cleanly(qapplication: QApplication) -> None:
    window = LeonardoMainWindow(load_main_window_profile())
    window.show()
    qapplication.processEvents()

    window.close()
    window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
