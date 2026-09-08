"""Leonardo Light V2 Main Window shell."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QDialog,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.widgets import SuiteNavigationDonut
from leonardo.gui.windows.shell_widgets import apply_identity
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow
from leonardo.gui.windows.settings_dialog import LeonardoSettingsDialog


MAIN_WINDOW_ID = "main_window.window"

_MAIN_WINDOW_ACTIONS = (
    ("main_window.download_data", "Download Data"),
    ("main_window.exit", "Exit"),
    ("main_window.ohlcv_maintenance", "OHLCV Maintenance"),
    ("main_window.open_analysis_suite", "Analysis Suite"),
    ("main_window.open_data_manager_suite", "Data Manager Suite"),
    ("main_window.open_research_suite", "Research Suite"),
    ("main_window.open_runtime_manager", "Runtime Manager"),
    ("main_window.open_settings_inspector", "Settings"),
    ("main_window.open_trading_suite", "Trading Suite"),
)
RuntimeManagerWindowFactory = Callable[[], QWidget]
RuntimeSnapshotProvider = Callable[[], object]
ShellActionIntentCallback = Callable[[str], str | None]
DownloadActionIntentCallback = ShellActionIntentCallback
MainWindowCloseCallback = Callable[[], None]
SettingsDialogFactory = Callable[[QWidget], QDialog]
DisplayTimeZoneChangedCallback = Callable[[], None]
_DOWNLOAD_SHELL_ACTION_IDS = frozenset(
    (
        "main_window.download_data",
        "main_window.ohlcv_maintenance",
    )
)
_SUITE_SHELL_ACTION_IDS = frozenset(
    (
        "main_window.open_analysis_suite",
        "main_window.open_data_manager_suite",
        "main_window.open_research_suite",
        "main_window.open_trading_suite",
    )
)
_TRACKED_MAIN_WINDOW_ACTION_IDS = frozenset(
    (
        "main_window.open_runtime_manager",
        "main_window.open_settings_inspector",
    )
) | _DOWNLOAD_SHELL_ACTION_IDS | _SUITE_SHELL_ACTION_IDS
_SUITE_NAVIGATION_UTILITY_ACTIONS = (
    (
        "main_window.utility_button.runtime_manager",
        "main_window.open_runtime_manager",
    ),
    (
        "main_window.utility_button.settings",
        "main_window.open_settings_inspector",
    ),
)
_QUICK_ACTIONS = (
    (
        "main_window.quick_action.download_data",
        "Download Data",
        "main_window.download_data",
    ),
    (
        "main_window.quick_action.runtime_manager",
        "Runtime Manager",
        "main_window.open_runtime_manager",
    ),
    (
        "main_window.quick_action.settings",
        "Settings",
        "main_window.open_settings_inspector",
    ),
)


class LeonardoMainWindow(QMainWindow):
    """Minimal direct-code Leonardo Main Window shell.

    Title, action labels, geometry, and presentation defaults are explicit code.
    Runtime Manager and suite shell handoff is GUI-local through
    injected factories/callbacks. The class does not call provider, storage,
    chart, trading, or domain execution services.
    """

    def __init__(
        self,
        *,
        runtime_manager_window_factory: RuntimeManagerWindowFactory | None = None,
        runtime_snapshot_provider: RuntimeSnapshotProvider | None = None,
        action_observer: GuiActionObserver | None = None,
        on_download_data_requested: DownloadActionIntentCallback | None = None,
        on_ohlcv_maintenance_requested: DownloadActionIntentCallback | None = None,
        on_suite_shell_requested: ShellActionIntentCallback | None = None,
        on_close_requested: MainWindowCloseCallback | None = None,
        settings_dialog_factory: SettingsDialogFactory | None = None,
        on_display_time_zone_changed: DisplayTimeZoneChangedCallback | None = None,
        username: str = "admin-dev",
        version_label: str = "v0.2",
    ) -> None:
        super().__init__()
        if runtime_manager_window_factory is not None and not callable(
            runtime_manager_window_factory
        ):
            raise TypeError("runtime_manager_window_factory must be callable")
        if runtime_snapshot_provider is not None and not callable(runtime_snapshot_provider):
            raise TypeError("runtime_snapshot_provider must be callable")
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        if on_download_data_requested is not None and not callable(
            on_download_data_requested
        ):
            raise TypeError("on_download_data_requested must be callable")
        if on_ohlcv_maintenance_requested is not None and not callable(
            on_ohlcv_maintenance_requested
        ):
            raise TypeError("on_ohlcv_maintenance_requested must be callable")
        if on_suite_shell_requested is not None and not callable(on_suite_shell_requested):
            raise TypeError("on_suite_shell_requested must be callable")
        if on_close_requested is not None and not callable(on_close_requested):
            raise TypeError("on_close_requested must be callable")
        if settings_dialog_factory is not None and not callable(settings_dialog_factory):
            raise TypeError("settings_dialog_factory must be callable")
        if on_display_time_zone_changed is not None and not callable(
            on_display_time_zone_changed
        ):
            raise TypeError("on_display_time_zone_changed must be callable")
        self.close_requested_locally = False
        self._actions: dict[str, QAction] = {}
        self._menus: dict[str, QMenu] = {}
        self._placeholder_buttons: dict[str, QPushButton] = {}
        self._suite_navigation_donut: SuiteNavigationDonut | None = None
        self._last_local_action_id = ""
        self._action_observer = action_observer
        self._runtime_manager_window_factory = runtime_manager_window_factory
        self._runtime_snapshot_provider = runtime_snapshot_provider
        self._runtime_manager_window: QWidget | None = None
        self._on_download_data_requested = on_download_data_requested
        self._on_ohlcv_maintenance_requested = on_ohlcv_maintenance_requested
        self._on_suite_shell_requested = on_suite_shell_requested
        self._on_close_requested = on_close_requested
        self._settings_dialog_factory = (
            LeonardoSettingsDialog
            if settings_dialog_factory is None
            else settings_dialog_factory
        )
        self._on_display_time_zone_changed = on_display_time_zone_changed
        self._username = _string_or_fallback(username, "admin-dev")
        self._version_label = _string_or_fallback(version_label, "v0.2")
        self._central_message_label: QLabel | None = None
        self._apply_window_defaults()
        self._build_menu_bar()
        self._build_central_launcher()
        self._build_status_bar()



    @property
    def last_local_action_id(self) -> str:
        """Return the last locally handled shell action ID."""

        return self._last_local_action_id

    @property
    def runtime_manager_window(self) -> QWidget | None:
        """Return the locally retained Runtime Manager window, if created."""

        return self._runtime_manager_window


    def action_ids(self) -> tuple[str, ...]:
        """Return action IDs in deterministic order."""

        return tuple(self._actions)

    def action_labels(self) -> Mapping[str, str]:
        """Return action labels by action ID."""

        return {action_id: action.text() for action_id, action in self._actions.items()}

    def action_for_id(self, action_id: str) -> QAction:
        """Return a shell action by stable action ID."""

        try:
            return self._actions[action_id]
        except KeyError as error:
            raise KeyError(f"Unknown Main Window action: {action_id}") from error

    def menu_for_id(self, menu_id: str) -> QMenu:
        """Return a menu by stable menu identifier."""

        try:
            return self._menus[menu_id]
        except KeyError as error:
            raise KeyError(f"Unknown Main Window menu: {menu_id}") from error

    def placeholder_button_for_id(self, action_id: str) -> QPushButton:
        """Return a Suite Navigation utility button by stable action ID."""

        try:
            return self._placeholder_buttons[action_id]
        except KeyError as error:
            raise KeyError(f"Unknown Main Window utility button: {action_id}") from error

    def suite_navigation_donut(self) -> SuiteNavigationDonut:
        """Return the Main Window Suite Navigation donut widget."""

        if self._suite_navigation_donut is None:
            raise RuntimeError("Suite Navigation donut has not been constructed")
        return self._suite_navigation_donut

    def closeEvent(self, event: QCloseEvent) -> None:
        """Record that the shell close path stayed local."""

        self.close_requested_locally = True
        if self._on_close_requested is not None:
            self._on_close_requested()
        if self._runtime_manager_window is not None:
            self._runtime_manager_window.close()
        super().closeEvent(event)

    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Leonardo")
        self.setObjectName("main_window")
        self.setProperty("object_id", MAIN_WINDOW_ID)
        self.resize(1440, 900)
        self.setMinimumSize(1024, 700)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setObjectName("main_window.menu_bar")
        menu_bar.setProperty("object_id", "main_window.menu_bar")
        menu_bar.setProperty("object_type", "menu_bar")
        for action_id, label in _MAIN_WINDOW_ACTIONS:
            action = QAction(label, self)
            action.setObjectName(action_id)
            action.setProperty("object_id", action_id)
            action.setProperty("object_type", "menu_action")
            action.triggered.connect(partial(self._handle_shell_action, action_id))
            self._actions[action_id] = action

        file_menu = self._add_menu("file", "File")
        file_menu.addAction(self.action_for_id("main_window.exit"))

        connection_menu = self._add_menu("connection", "Connection")
        connection_menu.addAction(self.action_for_id("main_window.download_data"))
        connection_menu.addAction(self.action_for_id("main_window.ohlcv_maintenance"))

        research_menu = self._add_menu("research_suite", "Research Suite")
        research_menu.addAction(self.action_for_id("main_window.open_research_suite"))

        data_menu = self._add_menu("data_manager", "Data Manager")
        data_menu.addAction(self.action_for_id("main_window.open_data_manager_suite"))

        analysis_menu = self._add_menu("analysis_suite", "Analysis Suite")
        analysis_menu.addAction(self.action_for_id("main_window.open_analysis_suite"))

        trading_menu = self._add_menu("trading_suite", "Trading Suite")
        trading_menu.addAction(self.action_for_id("main_window.open_trading_suite"))

        runtime_menu = self._add_menu("runtime_manager", "Runtime Manager")
        runtime_menu.addAction(self.action_for_id("main_window.open_runtime_manager"))

        settings_menu = self._add_menu("settings", "Settings")
        settings_menu.addAction(self.action_for_id("main_window.open_settings_inspector"))

        self._add_menu("user", "User")

        username_label = QLabel(self._username, menu_bar)
        username_label.setObjectName("main_window.label.username")
        username_label.setProperty("object_id", "main_window.label.username")
        username_label.setProperty("object_type", "label")
        menu_bar.setCornerWidget(username_label, Qt.Corner.TopRightCorner)

    def _build_central_launcher(self) -> None:
        central = QWidget()
        apply_identity(
            central,
            "main_window.central",
            object_type="central_area",
        )
        layout = QVBoxLayout(central)
        apply_identity(
            layout,
            "main_window.layout.central",
            object_type="layout",
        )

        layout.addWidget(self._build_top_bar(central))
        layout.addWidget(self._build_cockpit_body(central), stretch=1)
        layout.addWidget(self._build_quick_actions(central))
        self.setCentralWidget(central)

    def _build_top_bar(self, parent: QWidget) -> QWidget:
        top_bar = QGroupBox("Command Status", parent)
        apply_identity(
            top_bar,
            "main_window.panel.top_bar",
            object_type="panel",
        )
        layout = QHBoxLayout(top_bar)
        apply_identity(
            layout,
            "main_window.layout.top_bar",
            object_type="layout",
        )

        title_label = QLabel("Leonardo V2", top_bar)
        title_label.setObjectName("main_window.label.title")
        title_label.setProperty("object_id", "main_window.label.title")
        title_label.setProperty("object_type", "label")

        shell_status = QLabel("Shell online | GUI intent only", top_bar)
        apply_identity(
            shell_status,
            "main_window.label.shell_status",
            object_type="status_label",
            display_label="Shell Status",
        )

        theme_status = QLabel("Theme: Leonardo Jarvish Cockpit", top_bar)
        apply_identity(
            theme_status,
            "main_window.label.theme_status",
            object_type="status_label",
            display_label="Active Theme",
        )

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(shell_status)
        layout.addWidget(theme_status)
        return top_bar

    def _build_cockpit_body(self, parent: QWidget) -> QWidget:
        body = QWidget(parent)
        apply_identity(
            body,
            "main_window.panel.body",
            object_type="panel",
        )
        layout = QHBoxLayout(body)
        apply_identity(
            layout,
            "main_window.layout.body",
            object_type="layout",
        )
        layout.addWidget(self._build_left_rail(body), stretch=1)
        layout.addWidget(self._build_command_core(body), stretch=3)
        layout.addWidget(self._build_right_rail(body), stretch=1)
        return body

    def _build_left_rail(self, parent: QWidget) -> QWidget:
        rail = QGroupBox("Status / Context", parent)
        apply_identity(
            rail,
            "main_window.panel.left_rail",
            object_type="panel",
        )
        layout = QVBoxLayout(rail)
        apply_identity(
            layout,
            "main_window.layout.left_rail",
            object_type="layout",
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.system_status_dummy",
                label_object_id="main_window.label.system_status_dummy",
                title="System Runtime",
                text="Runtime: available\nDomain services: not connected",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.environment_weather_dummy",
                label_object_id="main_window.label.environment_weather_dummy",
                title="Environment / Weather",
                text="Weather service: not configured",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.environment_context_dummy",
                label_object_id="main_window.label.environment_context_dummy",
                title="Environment Context",
                text="Environment context: not configured",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.visual_input_dummy",
                label_object_id="main_window.label.visual_input_dummy",
                title="Visual Input",
                text="Visual input: not configured",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.voice_control_dummy",
                label_object_id="main_window.label.voice_control_dummy",
                title="Voice Control",
                text="Voice control: not configured",
            )
        )
        layout.addStretch(1)
        return rail

    def _build_command_core(self, parent: QWidget) -> QWidget:
        core = QGroupBox("Leonardo Command Core", parent)
        apply_identity(
            core,
            "main_window.panel.command_core",
            object_type="panel",
        )
        layout = QVBoxLayout(core)
        apply_identity(
            layout,
            "main_window.layout.command_core",
            object_type="layout",
        )

        notice = QLabel(
            "Cockpit foundation only: suite buttons emit GUI intent and all "
            "unconnected panels remain read-only.",
            core,
        )
        notice.setWordWrap(True)
        apply_identity(
            notice,
            "main_window.label.cockpit_notice",
            object_type="label",
            display_label="Cockpit Notice",
        )

        placeholder = QLabel("Select a traceable shell launcher.", core)
        placeholder.setObjectName("main_window.label.placeholder")
        placeholder.setProperty("object_id", "main_window.label.placeholder")
        placeholder.setProperty("object_type", "status_label")
        self._central_message_label = placeholder

        launcher = QGroupBox("Suite Navigation", core)
        apply_identity(
            launcher,
            "main_window.panel.suite_navigation",
            object_type="suite_navigation_panel",
        )
        suite_layout = QVBoxLayout(launcher)
        apply_identity(
            suite_layout,
            "main_window.layout.suite_navigation",
            object_type="layout",
        )

        donut = SuiteNavigationDonut(parent=launcher)
        apply_identity(
            donut,
            "main_window.widget.suite_navigation_donut",
            object_type="donut_navigation",
            display_label="Suite Navigation",
            tooltip="Suite Navigation segments emit existing GUI shell intents only.",
        )
        donut.segment_activated.connect(self._handle_shell_action)
        self._suite_navigation_donut = donut
        suite_layout.addWidget(donut, stretch=1)

        utilities = QWidget(launcher)
        apply_identity(
            utilities,
            "main_window.panel.suite_navigation_utilities",
            object_type="utility_button_panel",
            display_label="Suite Navigation Utilities",
        )
        utility_layout = QHBoxLayout(utilities)
        apply_identity(
            utility_layout,
            "main_window.layout.suite_navigation_utilities",
            object_type="layout",
        )
        for object_id, action_id in _SUITE_NAVIGATION_UTILITY_ACTIONS:
            button = QPushButton(self.action_for_id(action_id).text(), utilities)
            apply_identity(
                button,
                object_id,
                object_type="button",
                action_id=action_id,
                tooltip="Suite Navigation utility action only. No domain execution is started.",
            )
            button.setMinimumHeight(42)
            button.clicked.connect(partial(self._handle_shell_action, action_id))
            self._placeholder_buttons[action_id] = button
            utility_layout.addWidget(button)
        suite_layout.addWidget(utilities)

        layout.addWidget(notice)
        layout.addWidget(placeholder)
        layout.addWidget(launcher, stretch=1)
        return core

    def _build_right_rail(self, parent: QWidget) -> QWidget:
        rail = QGroupBox("Operator Rail", parent)
        apply_identity(
            rail,
            "main_window.panel.right_rail",
            object_type="panel",
        )
        layout = QVBoxLayout(rail)
        apply_identity(
            layout,
            "main_window.layout.right_rail",
            object_type="layout",
        )

        operator_panel = QGroupBox("Operator Console", rail)
        apply_identity(
            operator_panel,
            "main_window.panel.operator_console_dummy",
            object_type="panel",
        )
        operator_layout = QVBoxLayout(operator_panel)
        apply_identity(
            operator_layout,
            "main_window.layout.operator_console_dummy",
            object_type="layout",
        )

        operator_label = QLabel("AI/operator channel is not configured", operator_panel)
        operator_label.setWordWrap(True)
        apply_identity(
            operator_label,
            "main_window.label.operator_console_dummy",
            object_type="label",
            display_label="Operator Console",
        )

        console = QTextEdit(operator_panel)
        console.setReadOnly(True)
        console.setPlainText(
            "Leonardo shell online.\n"
            "AI backend is not configured.\n"
            "No messages are persisted."
        )
        apply_identity(
            console,
            "main_window.text.operator_console_dummy",
            object_type="text_display",
            display_label="Operator Console Messages",
        )

        input_field = QLineEdit(operator_panel)
        input_field.setEnabled(False)
        input_field.setPlaceholderText("Operator input unavailable")
        apply_identity(
            input_field,
            "main_window.input.operator_console_dummy",
            object_type="input",
            display_label="Operator Console Input",
        )

        operator_layout.addWidget(operator_label)
        operator_layout.addWidget(console, stretch=1)
        operator_layout.addWidget(input_field)
        layout.addWidget(operator_panel, stretch=1)
        layout.addStretch(1)
        return rail

    def _build_quick_actions(self, parent: QWidget) -> QWidget:
        panel = QGroupBox("Quick Actions / Activity", parent)
        apply_identity(
            panel,
            "main_window.panel.quick_actions",
            object_type="panel",
        )
        layout = QHBoxLayout(panel)
        apply_identity(
            layout,
            "main_window.layout.quick_actions",
            object_type="layout",
        )

        activity = QLabel(
            "Activity: ready | optional services are not configured.",
            panel,
        )
        activity.setWordWrap(True)
        apply_identity(
            activity,
            "main_window.label.activity_log_dummy",
            object_type="status_label",
            display_label="Activity Log",
        )
        layout.addWidget(activity, stretch=1)

        for object_id, label, action_id in _QUICK_ACTIONS:
            button = QPushButton(label, panel)
            apply_identity(
                button,
                object_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="Quick action reuses an existing Main Window GUI intent.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id))
            layout.addWidget(button)
        return panel

    def _build_dummy_status_card(
        self,
        parent: QWidget,
        *,
        object_id: str,
        label_object_id: str,
        title: str,
        text: str,
    ) -> QWidget:
        card = QGroupBox(title, parent)
        apply_identity(
            card,
            object_id,
            object_type="dummy_status_card",
            display_label=title,
        )
        layout = QVBoxLayout(card)
        label = QLabel(text, card)
        label.setWordWrap(True)
        apply_identity(
            label,
            label_object_id,
            object_type="status_label",
            display_label=title,
        )
        layout.addWidget(label)
        return card

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setObjectName("main_window.status_bar")
        status_bar.setProperty("object_id", "main_window.status_bar")
        status_bar.setProperty("object_type", "status_bar")
        version = QLabel(self._version_label)
        version.setObjectName("main_window.label.version")
        version.setProperty("object_id", "main_window.label.version")
        version.setProperty("object_type", "label")
        status_bar.addPermanentWidget(version)
        self.setStatusBar(status_bar)
        status_bar.showMessage("Ready")

    def _add_menu(self, menu_id: str, label: str) -> QMenu:
        menu = self.menuBar().addMenu(label)
        object_id = f"main_window.menu.{menu_id}"
        menu.setObjectName(object_id)
        menu.setProperty("object_id", object_id)
        menu.setProperty("object_type", "menu")
        self._menus[menu_id] = menu
        return menu

    def _handle_shell_action(self, action_id: str) -> None:
        self._last_local_action_id = action_id
        if not self._record_action(action_id):
            return
        if action_id == "main_window.exit":
            self.statusBar().showMessage("Exit requested locally.")
            self.close()
            return
        if action_id == "main_window.open_settings_inspector":
            self._open_settings_inspector_window()
            return
        if action_id == "main_window.open_runtime_manager":
            self._open_runtime_manager_window()
            return
        if action_id in _DOWNLOAD_SHELL_ACTION_IDS | _SUITE_SHELL_ACTION_IDS:
            self._show_shell_action(action_id)
            return
        self.statusBar().showMessage(f"Unhandled local shell action: {action_id}")

    def _record_action(self, action_id: str) -> bool:
        if (
            self._action_observer is None
            or action_id not in _TRACKED_MAIN_WINDOW_ACTION_IDS
        ):
            return True
        decision = self._action_observer.record_action(
            action_id,
            window_id=MAIN_WINDOW_ID,
        )
        return decision.allowed

    def _show_shell_action(self, action_id: str) -> None:
        message = self._shell_message_for_action(action_id)
        if self._central_message_label is not None:
            self._central_message_label.setText(message)
        self.statusBar().showMessage(message)

    def _shell_message_for_action(self, action_id: str) -> str:
        message = self._default_placeholder_message_for_action(action_id)
        callback = self._shell_action_callback_for_id(action_id)
        if callback is None:
            return message
        callback_message = callback(action_id)
        if callback_message is None or callback_message == "":
            return message
        if not isinstance(callback_message, str):
            raise TypeError("shell action callback must return str or None")
        return callback_message

    def _default_placeholder_message_for_action(self, action_id: str) -> str:
        label = self.action_for_id(action_id).text()
        return f"{label} shell launcher selected."

    def _shell_action_callback_for_id(
        self,
        action_id: str,
    ) -> ShellActionIntentCallback | None:
        if action_id == "main_window.download_data":
            return self._on_download_data_requested
        if action_id == "main_window.ohlcv_maintenance":
            return self._on_ohlcv_maintenance_requested
        if action_id in _SUITE_SHELL_ACTION_IDS:
            return self._on_suite_shell_requested
        return None

    def _open_runtime_manager_window(self) -> None:
        created = False
        if self._runtime_manager_window is None:
            self._runtime_manager_window = self._create_runtime_manager_window()
            created = True

        self._runtime_manager_window.show()
        self._runtime_manager_window.raise_()
        self._runtime_manager_window.activateWindow()
        if created:
            self.statusBar().showMessage("Runtime Manager opened locally.")
            return
        self.statusBar().showMessage("Runtime Manager raised locally.")

    def _create_runtime_manager_window(self) -> QWidget:
        if self._runtime_manager_window_factory is not None:
            window = self._runtime_manager_window_factory()
        else:
            window = RuntimeManagerWindow(
                snapshot_provider=self._runtime_snapshot_provider,
            )
        if not isinstance(window, QWidget):
            raise TypeError("Runtime Manager window factory must return a QWidget")
        return window

    def _open_settings_inspector_window(self) -> None:
        dialog = self._settings_dialog_factory(self)
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("Settings cancelled.")
            return
        if not dialog.display_time_zone_changed:
            self.statusBar().showMessage("Settings unchanged.")
            return
        if self._on_display_time_zone_changed is not None:
            self._on_display_time_zone_changed()
        self.statusBar().showMessage("Display time zone updated.")


def _string_or_fallback(value: object, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback
