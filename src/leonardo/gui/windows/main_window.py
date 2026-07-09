"""Minimal Main Window shell that consumes GUI metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.windows.traceable_shell_widgets import apply_trace
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow


MAIN_WINDOW_METADATA_ID = "main_window.window"
_MAIN_WINDOW_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "main_window.window.toml"
)
RuntimeManagerWindowFactory = Callable[[], QWidget]
RuntimeSnapshotProvider = Callable[[], object]
SettingsInspectorFactory = Callable[[], QWidget]
ShellActionIntentCallback = Callable[[str], str | None]
DownloadActionIntentCallback = ShellActionIntentCallback
MainWindowCloseCallback = Callable[[], None]
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
_LAUNCHER_BUTTON_ACTION_IDS = (
    "main_window.download_data",
    "main_window.open_research_suite",
    "main_window.open_data_manager_suite",
    "main_window.open_analysis_suite",
    "main_window.open_trading_suite",
    "main_window.open_runtime_manager",
    "main_window.open_settings_inspector",
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


def load_main_window_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Main Window shell metadata profile."""

    result = load_metadata_document(_MAIN_WINDOW_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Main Window metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class LeonardoMainWindow(QMainWindow):
    """Minimal metadata-driven Leonardo Main Window shell.

    The shell consumes metadata for title, action labels, and basic presentation
    defaults. Runtime Manager and suite shell handoff is GUI-local through
    injected factories/callbacks. The class does not call provider, storage,
    chart, trading, or domain execution services.
    """

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        runtime_manager_window_factory: RuntimeManagerWindowFactory | None = None,
        runtime_snapshot_provider: RuntimeSnapshotProvider | None = None,
        settings_inspector_factory: SettingsInspectorFactory | None = None,
        action_observer: GuiActionObserver | None = None,
        on_download_data_requested: DownloadActionIntentCallback | None = None,
        on_ohlcv_maintenance_requested: DownloadActionIntentCallback | None = None,
        on_suite_shell_requested: ShellActionIntentCallback | None = None,
        on_close_requested: MainWindowCloseCallback | None = None,
        username: str = "admin-dev",
        version_label: str = "v0.2",
    ) -> None:
        super().__init__()
        self._profile = profile if profile is not None else load_main_window_profile()
        if self._profile.metadata_id != MAIN_WINDOW_METADATA_ID:
            raise ValueError("profile must describe main_window.window")
        if runtime_manager_window_factory is not None and not callable(
            runtime_manager_window_factory
        ):
            raise TypeError("runtime_manager_window_factory must be callable")
        if runtime_snapshot_provider is not None and not callable(runtime_snapshot_provider):
            raise TypeError("runtime_snapshot_provider must be callable")
        if settings_inspector_factory is not None and not callable(
            settings_inspector_factory
        ):
            raise TypeError("settings_inspector_factory must be callable")
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
        self.close_requested_locally = False
        self._actions: dict[str, QAction] = {}
        self._menus: dict[str, QMenu] = {}
        self._placeholder_buttons: dict[str, QPushButton] = {}
        self._last_local_action_id = ""
        self._action_observer = action_observer
        self._runtime_manager_window_factory = runtime_manager_window_factory
        self._runtime_snapshot_provider = runtime_snapshot_provider
        self._runtime_manager_window: QWidget | None = None
        self._settings_inspector_factory = settings_inspector_factory
        self._settings_inspector_window: QWidget | None = None
        self._on_download_data_requested = on_download_data_requested
        self._on_ohlcv_maintenance_requested = on_ohlcv_maintenance_requested
        self._on_suite_shell_requested = on_suite_shell_requested
        self._on_close_requested = on_close_requested
        self._username = _string_or_fallback(username, "admin-dev")
        self._version_label = _string_or_fallback(version_label, "v0.2")
        self._central_message_label: QLabel | None = None
        self._apply_profile_metadata()
        self._build_menu_bar()
        self._build_central_launcher()
        self._build_status_bar()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

    @property
    def metadata_title(self) -> str:
        """Return the metadata-derived shell title."""

        identity = _mapping_at(self._profile.values, "identity")
        return _string_value(identity, "title", "Leonardo")

    @property
    def last_local_action_id(self) -> str:
        """Return the last locally handled shell action ID."""

        return self._last_local_action_id

    @property
    def runtime_manager_window(self) -> QWidget | None:
        """Return the locally retained Runtime Manager window, if created."""

        return self._runtime_manager_window

    @property
    def settings_inspector_window(self) -> QWidget | None:
        """Return the locally retained Settings Inspector dialog, if created."""

        return self._settings_inspector_window

    def action_ids(self) -> tuple[str, ...]:
        """Return metadata action IDs in deterministic order."""

        return tuple(self._actions)

    def action_labels(self) -> Mapping[str, str]:
        """Return metadata action labels by action ID."""

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
        """Return a central launcher button by stable action ID."""

        try:
            return self._placeholder_buttons[action_id]
        except KeyError as error:
            raise KeyError(f"Unknown Main Window launcher button: {action_id}") from error

    def apply_effective_profile(self, profile: EffectiveGuiMetadataProfile) -> None:
        """
        Apply safe live visual settings from a Main Window effective profile.

        The method intentionally limits live updates to visual fields that can
        be changed without rebuilding the shell, rewiring actions, changing
        stable object names, or mutating Core state.
        """

        if not isinstance(profile, EffectiveGuiMetadataProfile):
            raise TypeError("profile must be an EffectiveGuiMetadataProfile")
        if profile.metadata_id != MAIN_WINDOW_METADATA_ID:
            raise ValueError("profile must describe main_window.window")
        self._profile = profile
        self._apply_visual_profile_metadata()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Record that the shell close path stayed local."""

        self.close_requested_locally = True
        if self._on_close_requested is not None:
            self._on_close_requested()
        if self._runtime_manager_window is not None:
            self._runtime_manager_window.close()
        if self._settings_inspector_window is not None:
            self._settings_inspector_window.close()
        super().closeEvent(event)

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")

        self.setWindowTitle(self.metadata_title)
        self.setObjectName(_string_value(metadata, "object_name", "main_window"))
        self.setProperty(
            "object_id",
            _string_value(metadata, "window_id", MAIN_WINDOW_METADATA_ID),
        )
        self.resize(
            _int_value(geometry, "width", 1440),
            _int_value(geometry, "height", 900),
        )

        self._apply_visual_profile_metadata()

    def _apply_visual_profile_metadata(self) -> None:
        style = _mapping_at(self._profile.values, "style")
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setObjectName("main_window.menu_bar")
        menu_bar.setProperty("object_id", "main_window.menu_bar")
        menu_bar.setProperty("object_type", "menu_bar")
        menu_bar.setProperty("parent_object_id", MAIN_WINDOW_METADATA_ID)
        for action_id, action_metadata in _sorted_metadata_items(
            _mapping_at(self._profile.values, "actions")
        ):
            action = QAction(_string_value(action_metadata, "label", action_id), self)
            action.setObjectName(action_id)
            action.setProperty("object_id", action_id)
            action.setProperty("object_type", "menu_action")
            action.setProperty("parent_object_id", "main_window.menu_bar")
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
        username_label.setObjectName("main_window.username_label")
        username_label.setProperty("object_id", "main_window.label.username")
        username_label.setProperty("object_type", "label")
        username_label.setProperty("parent_object_id", "main_window.menu_bar")
        menu_bar.setCornerWidget(username_label, Qt.Corner.TopRightCorner)

    def _build_central_launcher(self) -> None:
        central = QWidget()
        apply_trace(
            central,
            "main_window.central",
            object_type="central_area",
            parent_object_id=MAIN_WINDOW_METADATA_ID,
        )
        layout = QVBoxLayout(central)
        apply_trace(
            layout,
            "main_window.layout.central",
            object_type="layout",
            parent_object_id="main_window.central",
        )

        layout.addWidget(self._build_top_bar(central))
        layout.addWidget(self._build_cockpit_body(central), stretch=1)
        layout.addWidget(self._build_quick_actions(central))
        self.setCentralWidget(central)

    def _build_top_bar(self, parent: QWidget) -> QWidget:
        top_bar = QGroupBox("Command Status", parent)
        apply_trace(
            top_bar,
            "main_window.panel.top_bar",
            object_type="panel",
            parent_object_id="main_window.central",
        )
        layout = QHBoxLayout(top_bar)
        apply_trace(
            layout,
            "main_window.layout.top_bar",
            object_type="layout",
            parent_object_id="main_window.panel.top_bar",
        )

        title_label = QLabel("Leonardo V2", top_bar)
        title_label.setObjectName("main_window.title_label")
        title_label.setProperty("object_id", "main_window.label.title")
        title_label.setProperty("object_type", "label")
        title_label.setProperty("parent_object_id", "main_window.panel.top_bar")

        shell_status = QLabel("Shell online | GUI intent only", top_bar)
        apply_trace(
            shell_status,
            "main_window.label.shell_status",
            object_type="status_label",
            display_label="Shell Status",
            parent_object_id="main_window.panel.top_bar",
        )

        theme_status = QLabel("Theme: Leonardo Jarvish Cockpit", top_bar)
        apply_trace(
            theme_status,
            "main_window.label.theme_status",
            object_type="status_label",
            display_label="Active Theme",
            parent_object_id="main_window.panel.top_bar",
        )

        layout.addWidget(title_label)
        layout.addStretch(1)
        layout.addWidget(shell_status)
        layout.addWidget(theme_status)
        return top_bar

    def _build_cockpit_body(self, parent: QWidget) -> QWidget:
        body = QWidget(parent)
        apply_trace(
            body,
            "main_window.panel.body",
            object_type="panel",
            parent_object_id="main_window.central",
        )
        layout = QHBoxLayout(body)
        apply_trace(
            layout,
            "main_window.layout.body",
            object_type="layout",
            parent_object_id="main_window.panel.body",
        )
        layout.addWidget(self._build_left_rail(body), stretch=1)
        layout.addWidget(self._build_command_core(body), stretch=3)
        layout.addWidget(self._build_right_rail(body), stretch=1)
        return body

    def _build_left_rail(self, parent: QWidget) -> QWidget:
        rail = QGroupBox("Status / Context", parent)
        apply_trace(
            rail,
            "main_window.panel.left_rail",
            object_type="panel",
            parent_object_id="main_window.panel.body",
        )
        layout = QVBoxLayout(rail)
        apply_trace(
            layout,
            "main_window.layout.left_rail",
            object_type="layout",
            parent_object_id="main_window.panel.left_rail",
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.system_status_dummy",
                label_object_id="main_window.label.system_status_dummy",
                title="System Runtime",
                text="Runtime shell: online\nCore bridge: composition-owned\nDomain execution: disabled",
                parent_object_id="main_window.panel.left_rail",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.environment_weather_dummy",
                label_object_id="main_window.label.environment_weather_dummy",
                title="Environment / Weather",
                text="Weather: dummy offline\nExternal APIs: disabled\nNetwork calls: none",
                parent_object_id="main_window.panel.left_rail",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.environment_context_dummy",
                label_object_id="main_window.label.environment_context_dummy",
                title="Environment Context",
                text="City context: placeholder\nLocation permission: not requested\nPersistence: none",
                parent_object_id="main_window.panel.left_rail",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.visual_input_dummy",
                label_object_id="main_window.label.visual_input_dummy",
                title="Visual Input",
                text="Camera feed: offline\nDevice access: not requested\nImages: not captured",
                parent_object_id="main_window.panel.left_rail",
            )
        )
        layout.addWidget(
            self._build_dummy_status_card(
                rail,
                object_id="main_window.panel.voice_control_dummy",
                label_object_id="main_window.label.voice_control_dummy",
                title="Voice Control",
                text="Voice: offline\nMicrophone: not requested\nSpeech services: disabled",
                parent_object_id="main_window.panel.left_rail",
            )
        )
        layout.addStretch(1)
        return rail

    def _build_command_core(self, parent: QWidget) -> QWidget:
        core = QGroupBox("Leonardo Command Core", parent)
        apply_trace(
            core,
            "main_window.panel.command_core",
            object_type="panel",
            parent_object_id="main_window.panel.body",
        )
        layout = QVBoxLayout(core)
        apply_trace(
            layout,
            "main_window.layout.command_core",
            object_type="layout",
            parent_object_id="main_window.panel.command_core",
        )

        notice = QLabel(
            "Cockpit foundation only: suite buttons emit GUI intent and all "
            "future panels remain dummy/read-only.",
            core,
        )
        notice.setWordWrap(True)
        apply_trace(
            notice,
            "main_window.label.cockpit_notice",
            object_type="label",
            display_label="Cockpit Notice",
            parent_object_id="main_window.panel.command_core",
        )

        placeholder = QLabel("Select a traceable shell launcher.", core)
        placeholder.setObjectName("main_window.placeholder_label")
        placeholder.setProperty("object_id", "main_window.label.placeholder")
        placeholder.setProperty("object_type", "status_label")
        placeholder.setProperty(
            "parent_object_id",
            "main_window.panel.command_core",
        )
        self._central_message_label = placeholder

        launcher = QGroupBox("Suite Navigation", core)
        apply_trace(
            launcher,
            "main_window.panel.launcher",
            object_type="launcher_panel",
            parent_object_id="main_window.panel.command_core",
        )
        button_grid = QGridLayout(launcher)
        apply_trace(
            button_grid,
            "main_window.layout.launcher_grid",
            object_type="layout",
            parent_object_id="main_window.panel.launcher",
        )
        for index, action_id in enumerate(_LAUNCHER_BUTTON_ACTION_IDS):
            object_id = _launcher_button_object_id(action_id)
            button = QPushButton(self.action_for_id(action_id).text(), launcher)
            apply_trace(
                button,
                object_id,
                object_type="button",
                parent_object_id="main_window.panel.launcher",
                action_id=action_id,
                tooltip="GUI shell action only. No domain execution is started.",
            )
            button.setMinimumHeight(80)
            button.clicked.connect(partial(self._handle_shell_action, action_id))
            self._placeholder_buttons[action_id] = button
            button_grid.addWidget(button, index // 2, index % 2)

        layout.addWidget(notice)
        layout.addWidget(placeholder)
        layout.addWidget(launcher, stretch=1)
        return core

    def _build_right_rail(self, parent: QWidget) -> QWidget:
        rail = QGroupBox("Operator Rail", parent)
        apply_trace(
            rail,
            "main_window.panel.right_rail",
            object_type="panel",
            parent_object_id="main_window.panel.body",
        )
        layout = QVBoxLayout(rail)
        apply_trace(
            layout,
            "main_window.layout.right_rail",
            object_type="layout",
            parent_object_id="main_window.panel.right_rail",
        )

        operator_panel = QGroupBox("Operator Console", rail)
        apply_trace(
            operator_panel,
            "main_window.panel.operator_console_dummy",
            object_type="panel",
            parent_object_id="main_window.panel.right_rail",
        )
        operator_layout = QVBoxLayout(operator_panel)
        apply_trace(
            operator_layout,
            "main_window.layout.operator_console_dummy",
            object_type="layout",
            parent_object_id="main_window.panel.operator_console_dummy",
        )

        operator_label = QLabel("AI/operator channel placeholder", operator_panel)
        operator_label.setWordWrap(True)
        apply_trace(
            operator_label,
            "main_window.label.operator_console_dummy",
            object_type="label",
            display_label="Operator Console",
            parent_object_id="main_window.panel.operator_console_dummy",
        )

        console = QTextEdit(operator_panel)
        console.setReadOnly(True)
        console.setPlainText(
            "Leonardo shell online.\n"
            "AI backend offline / placeholder.\n"
            "No messages are persisted."
        )
        apply_trace(
            console,
            "main_window.text.operator_console_dummy",
            object_type="text_display",
            display_label="Operator Console Messages",
            parent_object_id="main_window.panel.operator_console_dummy",
        )

        input_field = QLineEdit(operator_panel)
        input_field.setEnabled(False)
        input_field.setPlaceholderText("Dummy operator input (inactive)")
        apply_trace(
            input_field,
            "main_window.input.operator_console_dummy",
            object_type="input",
            display_label="Operator Console Input",
            parent_object_id="main_window.panel.operator_console_dummy",
        )

        operator_layout.addWidget(operator_label)
        operator_layout.addWidget(console, stretch=1)
        operator_layout.addWidget(input_field)
        layout.addWidget(operator_panel, stretch=1)
        layout.addStretch(1)
        return rail

    def _build_quick_actions(self, parent: QWidget) -> QWidget:
        panel = QGroupBox("Quick Actions / Activity", parent)
        apply_trace(
            panel,
            "main_window.panel.quick_actions",
            object_type="panel",
            parent_object_id="main_window.central",
        )
        layout = QHBoxLayout(panel)
        apply_trace(
            layout,
            "main_window.layout.quick_actions",
            object_type="layout",
            parent_object_id="main_window.panel.quick_actions",
        )

        activity = QLabel(
            "Activity: ready | weather/camera/voice/operator panels are dummy-only.",
            panel,
        )
        activity.setWordWrap(True)
        apply_trace(
            activity,
            "main_window.label.activity_log_dummy",
            object_type="status_label",
            display_label="Activity Log",
            parent_object_id="main_window.panel.quick_actions",
        )
        layout.addWidget(activity, stretch=1)

        for object_id, label, action_id in _QUICK_ACTIONS:
            button = QPushButton(label, panel)
            apply_trace(
                button,
                object_id,
                object_type="button",
                display_label=label,
                parent_object_id="main_window.panel.quick_actions",
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
        parent_object_id: str,
    ) -> QWidget:
        card = QGroupBox(title, parent)
        apply_trace(
            card,
            object_id,
            object_type="dummy_status_card",
            display_label=title,
            parent_object_id=parent_object_id,
        )
        layout = QVBoxLayout(card)
        label = QLabel(text, card)
        label.setWordWrap(True)
        apply_trace(
            label,
            label_object_id,
            object_type="status_label",
            display_label=title,
            parent_object_id=object_id,
        )
        layout.addWidget(label)
        return card

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar()
        status_bar.setObjectName("main_window.status_bar")
        status_bar.setProperty("object_id", "main_window.status_bar")
        status_bar.setProperty("object_type", "status_bar")
        status_bar.setProperty("parent_object_id", MAIN_WINDOW_METADATA_ID)
        version = QLabel(self._version_label)
        version.setObjectName("main_window.version_label")
        version.setProperty("object_id", "main_window.label.version")
        version.setProperty("object_type", "label")
        version.setProperty("parent_object_id", "main_window.status_bar")
        status_bar.addPermanentWidget(version)
        self.setStatusBar(status_bar)
        status_bar.showMessage("Ready")

    def _add_menu(self, menu_id: str, label: str) -> QMenu:
        menu = self.menuBar().addMenu(label)
        object_id = f"main_window.menu.{menu_id}"
        menu.setObjectName(object_id)
        menu.setProperty("object_id", object_id)
        menu.setProperty("object_type", "menu")
        menu.setProperty("parent_object_id", "main_window.menu_bar")
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
        if action_id == "main_window.open_dummy_metadata_test":
            self.statusBar().showMessage("Dummy metadata test action is local/inert.")
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
            window_id=MAIN_WINDOW_METADATA_ID,
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
        if self._settings_inspector_factory is None:
            self.statusBar().showMessage("Settings inspector action is local/inert.")
            return

        created = False
        if self._settings_inspector_window is None:
            self._settings_inspector_window = self._create_settings_inspector_window()
            created = True

        self._settings_inspector_window.show()
        self._settings_inspector_window.raise_()
        self._settings_inspector_window.activateWindow()
        if created:
            self.statusBar().showMessage("Settings inspector opened locally.")
            return
        self.statusBar().showMessage("Settings inspector raised locally.")

    def _create_settings_inspector_window(self) -> QWidget:
        if self._settings_inspector_factory is None:
            raise RuntimeError("settings_inspector_factory is not configured")
        window = self._settings_inspector_factory()
        if not isinstance(window, QWidget):
            raise TypeError("Settings Inspector factory must return a QWidget")
        return window


def _launcher_button_object_id(action_id: str) -> str:
    suffix = action_id.removeprefix("main_window.")
    return f"main_window.button.{suffix}"


def _mapping_at(values: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: Mapping[str, object], key: str, fallback: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _string_or_fallback(value: object, fallback: str) -> str:
    if isinstance(value, str) and value:
        return value
    return fallback


def _int_value(values: Mapping[str, object], key: str, fallback: int) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _sorted_metadata_items(
    values: Mapping[str, object],
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    return tuple(
        (key, item)
        for key, item in sorted(values.items(), key=lambda entry: entry[0])
        if isinstance(key, str) and isinstance(item, Mapping)
    )
