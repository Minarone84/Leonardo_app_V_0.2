import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QToolBar  # noqa: E402

from leonardo.gui.metadata import (  # noqa: E402
    GuiMetadataOverrideDocument,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.windows.main_window import (  # noqa: E402
    LeonardoMainWindow,
    _MAIN_WINDOW_METADATA_PATH,
    load_main_window_profile,
)
from leonardo.gui.windows.runtime_manager_window import (  # noqa: E402
    load_runtime_manager_profile,
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
    assert window.findChild(QLabel, "main_window.username_label").text() == "admin-dev"
    assert window.findChild(QLabel, "main_window.version_label").text() == "v0.2"

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_accepts_injected_display_labels(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(
        load_main_window_profile(),
        username="operator-1",
        version_label="v9.9",
    )

    assert window.findChild(QLabel, "main_window.username_label").text() == "operator-1"
    assert window.findChild(QLabel, "main_window.version_label").text() == "v9.9"

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_metadata_action_labels_are_present(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    assert window.action_ids() == (
        "main_window.download_data",
        "main_window.exit",
        "main_window.ohlcv_maintenance",
        "main_window.open_analysis_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_dummy_metadata_test",
        "main_window.open_research_suite",
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
        "main_window.open_trading_suite",
    )
    assert window.action_labels() == {
        "main_window.download_data": "Download Data",
        "main_window.exit": "Exit",
        "main_window.ohlcv_maintenance": "OHLCV Maintenance",
        "main_window.open_analysis_suite": "Analysis Suite",
        "main_window.open_data_manager_suite": "Data Manager Suite",
        "main_window.open_dummy_metadata_test": "Open Dummy Metadata Test",
        "main_window.open_research_suite": "Research Suite",
        "main_window.open_runtime_manager": "Runtime Manager",
        "main_window.open_settings_inspector": "Settings",
        "main_window.open_trading_suite": "Trading Suite",
    }
    for action_id in window.action_ids():
        action = window.findChild(QAction, action_id)
        assert action is not None
        assert action.text() == window.action_labels()[action_id]

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_menu_layout_has_expected_sections(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    file_menu = window.findChild(QMenu, "main_window.menu.file")
    download_menu = window.findChild(QMenu, "main_window.menu.download_manager")
    connections_menu = window.findChild(QMenu, "main_window.menu.connections")
    user_menu = window.findChild(QMenu, "main_window.menu.user")

    assert file_menu is not None
    assert download_menu is not None
    assert connections_menu is not None
    assert user_menu is not None
    assert [action.text() for action in file_menu.actions() if action.text()] == [
        "Runtime Manager",
        "Settings",
        "Exit",
    ]
    assert [action.text() for action in download_menu.actions()] == [
        "Download Data",
        "OHLCV Maintenance",
    ]
    assert connections_menu.actions() == []
    assert user_menu.actions() == []
    assert window.findChild(QToolBar, "main_window.toolbar") is None
    assert window.findChildren(QToolBar) == []

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_central_placeholder_buttons_exist(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    expected = {
        "main_window.open_trading_suite": "Trading Suite",
        "main_window.open_research_suite": "Research Suite",
        "main_window.open_data_manager_suite": "Data Manager Suite",
        "main_window.open_analysis_suite": "Analysis Suite",
    }
    for action_id, label in expected.items():
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.text() == label
        assert button.minimumHeight() >= 96

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


def test_main_window_placeholder_actions_update_status_without_windows(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.download_data"
    assert window.statusBar().currentMessage() == (
        "Download Data placeholder selected."
    )
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Download Data placeholder selected."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.placeholder_button_for_id("main_window.open_trading_suite").click()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.open_trading_suite"
    assert window.statusBar().currentMessage() == (
        "Trading Suite placeholder selected."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

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
        "Runtime Manager"
    )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_live_apply_updates_font_without_rebuilding_shell(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())
    action = window.action_for_id("main_window.open_settings_inspector")
    object_name = window.objectName()
    title = window.windowTitle()
    labels = window.action_labels()

    window.apply_effective_profile(
        _main_window_profile_with_overrides(
            {
                "style.font_size": 18,
                "style.density": "compact",
            }
        )
    )

    assert window.font().pointSize() == 18
    assert window.objectName() == object_name
    assert window.windowTitle() == title
    assert window.action_for_id("main_window.open_settings_inspector") is action
    assert window.action_labels() == labels

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_live_apply_rejects_non_main_window_profile(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    with pytest.raises(ValueError, match="main_window.window"):
        window.apply_effective_profile(load_runtime_manager_profile())

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


def _main_window_profile_with_overrides(
    values: dict[str, object],
):
    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)
    assert result.document is not None
    assert result.report.has_errors is False
    return GuiMetadataResolver().resolve(
        result.document,
        GuiMetadataOverrideDocument(
            metadata_id=result.document.metadata_id,
            values=values,
        ),
    )


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
