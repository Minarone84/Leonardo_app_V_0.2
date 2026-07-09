import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextEdit,
    QToolBar,
)

from leonardo.gui.action_observer import GuiActionDecision  # noqa: E402
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
from leonardo.gui.widgets import SuiteNavigationDonut  # noqa: E402
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
    assert window.findChild(QLabel, "main_window.title_label").text() == "Leonardo V2"
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
    connection_menu = window.findChild(QMenu, "main_window.menu.connection")
    research_menu = window.findChild(QMenu, "main_window.menu.research_suite")
    data_menu = window.findChild(QMenu, "main_window.menu.data_manager")
    analysis_menu = window.findChild(QMenu, "main_window.menu.analysis_suite")
    trading_menu = window.findChild(QMenu, "main_window.menu.trading_suite")
    runtime_menu = window.findChild(QMenu, "main_window.menu.runtime_manager")
    settings_menu = window.findChild(QMenu, "main_window.menu.settings")
    user_menu = window.findChild(QMenu, "main_window.menu.user")

    assert file_menu is not None
    assert connection_menu is not None
    assert research_menu is not None
    assert data_menu is not None
    assert analysis_menu is not None
    assert trading_menu is not None
    assert runtime_menu is not None
    assert settings_menu is not None
    assert user_menu is not None
    assert [action.text() for action in file_menu.actions() if action.text()] == ["Exit"]
    assert [action.text() for action in connection_menu.actions()] == [
        "Download Data",
        "OHLCV Maintenance",
    ]
    assert [action.text() for action in research_menu.actions()] == ["Research Suite"]
    assert [action.text() for action in data_menu.actions()] == ["Data Manager Suite"]
    assert [action.text() for action in analysis_menu.actions()] == ["Analysis Suite"]
    assert [action.text() for action in trading_menu.actions()] == ["Trading Suite"]
    assert [action.text() for action in runtime_menu.actions()] == ["Runtime Manager"]
    assert [action.text() for action in settings_menu.actions()] == ["Settings"]
    assert user_menu.actions() == []
    assert window.findChild(QToolBar, "main_window.toolbar") is None
    assert window.findChildren(QToolBar) == []

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_suite_navigation_donut_and_utilities_exist(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    donut = window.suite_navigation_donut()
    assert window.findChild(SuiteNavigationDonut, "main_window.widget.suite_navigation_donut") is donut
    assert donut.property("object_id") == "main_window.widget.suite_navigation_donut"
    assert donut.property("parent_object_id") == "main_window.panel.suite_navigation"
    assert donut.segment_count() == 5
    assert {
        segment.object_id: (segment.label, segment.action_id)
        for segment in donut.segments()
    } == {
        "main_window.donut.segment.connection_suite": (
            "Connection Suite",
            "main_window.download_data",
        ),
        "main_window.donut.segment.research_suite": (
            "Research Suite",
            "main_window.open_research_suite",
        ),
        "main_window.donut.segment.data_manager": (
            "Data Manager Suite",
            "main_window.open_data_manager_suite",
        ),
        "main_window.donut.segment.analysis_suite": (
            "Analysis Suite",
            "main_window.open_analysis_suite",
        ),
        "main_window.donut.segment.trading_suite": (
            "Trading Suite",
            "main_window.open_trading_suite",
        ),
    }

    expected_utilities = {
        "main_window.open_runtime_manager": (
            "main_window.utility_button.runtime_manager",
            "Runtime Manager",
        ),
        "main_window.open_settings_inspector": (
            "main_window.utility_button.settings",
            "Settings",
        ),
    }
    for action_id, (button_id, label) in expected_utilities.items():
        button = window.placeholder_button_for_id(action_id)
        assert window.findChild(QPushButton, button_id) is button
        assert button.text() == label
        assert button.property("action_id") == action_id
        assert button.property("parent_object_id") == (
            "main_window.panel.suite_navigation_utilities"
        )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_cockpit_dummy_panels_are_traceable_and_inert(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    expected_labels = {
        "main_window.label.shell_status": "GUI intent only",
        "main_window.label.theme_status": "Jarvish Cockpit",
        "main_window.label.system_status_dummy": "Domain execution: disabled",
        "main_window.label.environment_weather_dummy": "Network calls: none",
        "main_window.label.environment_context_dummy": "Location permission: not requested",
        "main_window.label.visual_input_dummy": "Camera feed: offline",
        "main_window.label.voice_control_dummy": "Microphone: not requested",
        "main_window.label.cockpit_notice": "dummy/read-only",
        "main_window.label.operator_console_dummy": "AI/operator channel placeholder",
        "main_window.label.activity_log_dummy": "dummy-only",
    }
    for object_id, expected_text in expected_labels.items():
        label = window.findChild(QLabel, object_id)
        assert label is not None, object_id
        assert label.property("object_id") == object_id
        assert expected_text in label.text()

    console = window.findChild(QTextEdit, "main_window.text.operator_console_dummy")
    input_field = window.findChild(QLineEdit, "main_window.input.operator_console_dummy")
    assert console is not None
    assert console.isReadOnly() is True
    assert "AI backend offline / placeholder" in console.toPlainText()
    assert input_field is not None
    assert input_field.isEnabled() is False
    assert input_field.placeholderText() == "Dummy operator input (inactive)"

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_quick_actions_reuse_existing_action_ids(
    qapplication: QApplication,
) -> None:
    window = LeonardoMainWindow(load_main_window_profile())

    expected = {
        "main_window.quick_action.download_data": "main_window.download_data",
        "main_window.quick_action.runtime_manager": "main_window.open_runtime_manager",
        "main_window.quick_action.settings": "main_window.open_settings_inspector",
    }
    for button_id, action_id in expected.items():
        button = window.findChild(QPushButton, button_id)
        assert button is not None, button_id
        assert button.property("object_id") == button_id
        assert button.property("action_id") == action_id

    window.findChild(QPushButton, "main_window.quick_action.download_data").click()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.download_data"
    assert window.statusBar().currentMessage() == (
        "Download Data shell launcher selected."
    )

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
        "Download Data shell launcher selected."
    )
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Download Data shell launcher selected."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.ohlcv_maintenance"
    assert window.statusBar().currentMessage() == (
        "OHLCV Maintenance shell launcher selected."
    )
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "OHLCV Maintenance shell launcher selected."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.suite_navigation_donut().segment_activated.emit(
        "main_window.open_trading_suite"
    )
    qapplication.processEvents()

    assert window.last_local_action_id == "main_window.open_trading_suite"
    assert window.statusBar().currentMessage() == (
        "Trading Suite shell launcher selected."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_download_callbacks_display_returned_messages(
    qapplication: QApplication,
) -> None:
    download_calls: list[str] = []
    maintenance_calls: list[str] = []
    window = LeonardoMainWindow(
        load_main_window_profile(),
        on_download_data_requested=lambda action_id: (
            download_calls.append(action_id) or "Download intent callback received."
        ),
        on_ohlcv_maintenance_requested=lambda action_id: (
            maintenance_calls.append(action_id)
            or "OHLCV maintenance intent callback received."
        ),
    )

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert download_calls == ["main_window.download_data"]
    assert window.statusBar().currentMessage() == "Download intent callback received."
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Download intent callback received."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()

    assert maintenance_calls == ["main_window.ohlcv_maintenance"]
    assert window.statusBar().currentMessage() == (
        "OHLCV maintenance intent callback received."
    )
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "OHLCV maintenance intent callback received."
    )
    assert window.runtime_manager_window is None
    assert window.settings_inspector_window is None

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_download_callback_none_preserves_default_message(
    qapplication: QApplication,
) -> None:
    calls: list[str] = []
    window = LeonardoMainWindow(
        load_main_window_profile(),
        on_download_data_requested=lambda action_id: calls.append(action_id) or None,
    )

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert calls == ["main_window.download_data"]
    assert window.statusBar().currentMessage() == (
        "Download Data shell launcher selected."
    )
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Download Data shell launcher selected."
    )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_suite_callback_display_returned_message(
    qapplication: QApplication,
) -> None:
    calls: list[str] = []
    window = LeonardoMainWindow(
        load_main_window_profile(),
        on_suite_shell_requested=lambda action_id: (
            calls.append(action_id) or "Research Suite shell opened."
        ),
    )

    window.action_for_id("main_window.open_research_suite").trigger()
    qapplication.processEvents()

    assert calls == ["main_window.open_research_suite"]
    assert window.statusBar().currentMessage() == "Research Suite shell opened."
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Research Suite shell opened."
    )

    window.deleteLater()
    qapplication.processEvents()


def test_main_window_download_callback_is_not_called_when_action_denied(
    qapplication: QApplication,
) -> None:
    callback_calls: list[str] = []
    observer = _DenyingActionObserver()
    window = LeonardoMainWindow(
        load_main_window_profile(),
        action_observer=observer,
        on_download_data_requested=lambda action_id: (
            callback_calls.append(action_id) or "should not display"
        ),
    )

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert observer.action_ids == ["main_window.download_data"]
    assert callback_calls == []
    assert window.last_local_action_id == "main_window.download_data"
    assert window.statusBar().currentMessage() == "Ready"
    assert window.findChild(QLabel, "main_window.placeholder_label").text() == (
        "Select a traceable shell launcher."
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


class _DenyingActionObserver:
    def __init__(self) -> None:
        self.action_ids: list[str] = []

    def record_action(
        self,
        action_id: str,
        *,
        window_id: str | None = None,
        metadata: object = None,
    ) -> GuiActionDecision:
        self.action_ids.append(action_id)
        return GuiActionDecision(
            action_id=action_id,
            allowed=False,
            reason="denied_for_test",
        )


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
