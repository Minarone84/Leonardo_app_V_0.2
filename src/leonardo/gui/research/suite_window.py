"""Production-target shell for the restored Research Suite GUI."""

from __future__ import annotations

from collections.abc import Iterable
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.research.workspace_widget import ResearchWorkspaceWidget
from leonardo.research.catalog import AcceptedDatasetSummary


class ResearchSuiteWindow(QMainWindow):
    """Menu-driven restored Research Suite window."""

    new_chart_requested = Signal()
    closed = Signal()
    save_study_environment_requested = Signal()
    load_study_environment_requested = Signal()
    manage_study_environments_requested = Signal()
    save_workspace_snapshot_requested = Signal()
    load_workspace_snapshot_requested = Signal()
    manage_workspace_snapshots_requested = Signal()
    open_notebook_requested = Signal()
    notebook_manager_requested = Signal()
    clear_research_suite_requested = Signal()

    def __init__(
        self,
        dataset_summaries: Iterable[AcceptedDatasetSummary] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research_restoration.window")
        self.setWindowTitle("Leonardo - Research Suite")
        self.resize(1400, 900)

        self._dataset_summaries: tuple[AcceptedDatasetSummary, ...] = ()
        self._actions: dict[str, QAction] = {}
        self._quick_buttons: dict[str, QToolButton] = {}

        self.workspace = ResearchWorkspaceWidget(self)
        self.setCentralWidget(self.workspace)

        self._build_activity_surface()
        self._build_menus()
        self._build_menu_bar_corner_widget()
        self.set_dataset_summaries(dataset_summaries)
        self.set_study_environment_actions_state(False, False, False)
        self.set_workspace_snapshot_actions_state(False, False, False)
        self.set_notebook_actions_state(False)
        self.set_assigned_notebook_state(None)

    @property
    def dataset_summaries(self) -> tuple[AcceptedDatasetSummary, ...]:
        return self._dataset_summaries

    @property
    def activity_expanded(self) -> bool:
        return self._activity_body.isHidden() is False

    def action_for_text(self, text: str) -> QAction:
        return self._actions[text]

    def quick_button_for_action(self, text: str) -> QToolButton:
        return self._quick_buttons[text]

    def set_dataset_summaries(
        self, summaries: Iterable[AcceptedDatasetSummary]
    ) -> None:
        snapshot = tuple(summaries)
        if not all(isinstance(item, AcceptedDatasetSummary) for item in snapshot):
            raise TypeError(
                "summaries must contain AcceptedDatasetSummary values"
            )
        self._dataset_summaries = snapshot

    def set_catalog_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._actions["New Chart..."].setEnabled(not busy)

    def append_activity(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._append_activity(message)

    def set_assigned_notebook_state(
        self, notebook_display_name: str | None
    ) -> None:
        if notebook_display_name is not None:
            if (
                not isinstance(notebook_display_name, str)
                or not notebook_display_name
                or notebook_display_name != notebook_display_name.strip()
            ):
                raise ValueError(
                    "notebook_display_name must be None or canonical non-empty text"
                )
        action = self._actions["Open Assigned Notebook"]
        if notebook_display_name is None:
            message = "No notebook assigned to the current workspace."
            action.setEnabled(False)
        else:
            message = f"Open assigned notebook: {notebook_display_name}"
            action.setEnabled(True)
        action.setToolTip(message)
        action.setStatusTip(message)

    def set_study_environment_actions_state(
        self,
        save_enabled: bool,
        load_enabled: bool,
        manage_enabled: bool,
    ) -> None:
        for value in (save_enabled, load_enabled, manage_enabled):
            if type(value) is not bool:
                raise TypeError("Study Environment action states must be boolean")
        self._actions["Save Study Environment..."].setEnabled(save_enabled)
        self._actions["Load Study Environment..."].setEnabled(load_enabled)
        self._actions["Manage Study Environments..."].setEnabled(manage_enabled)

    def set_workspace_snapshot_actions_state(
        self,
        save_enabled: bool,
        load_enabled: bool,
        manage_enabled: bool,
    ) -> None:
        for value in (save_enabled, load_enabled, manage_enabled):
            if type(value) is not bool:
                raise TypeError("Workspace Snapshot action states must be boolean")
        self._actions["Save Workspace..."].setEnabled(save_enabled)
        self._actions["Load Workspace..."].setEnabled(load_enabled)
        self._actions["Manage Workspaces..."].setEnabled(manage_enabled)

    def set_notebook_actions_state(
        self,
        manager_enabled: bool,
    ) -> None:
        if type(manager_enabled) is not bool:
            raise TypeError("Research Notebook action state must be boolean")
        self._actions["Notebook Manager..."].setEnabled(manager_enabled)

    def set_clear_research_suite_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("Clear Research Suite action state must be boolean")
        self._actions["Clear Research Suite"].setEnabled(enabled)

    def set_pan_anchor_visual_state(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("Pan Anchor visual state must be boolean")
        button = self._quick_buttons["Pan Anchor"]
        if enabled:
            background = "#86EFAC"
            tooltip = (
                "Pan Anchor is on. Horizontal user panning keeps ready charts "
                "aligned by UTC timestamp."
            )
            accessible_name = "Pan Anchor on"
        else:
            background = "#FCA5A5"
            tooltip = "Pan Anchor is off. Charts may be panned independently."
            accessible_name = "Pan Anchor off"
        button.setStyleSheet(
            "QToolButton {"
            f" background-color: {background}; color: #111827;"
            "}"
        )
        button.setToolTip(tooltip)
        button.setStatusTip(tooltip)
        button.setAccessibleName(accessible_name)
        action = self._actions["Pan Anchor"]
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)

    def set_workspace_view_mode(self, label: str) -> None:
        if label not in {"Scroll 4", "Fit 8"}:
            raise ValueError("workspace view mode must be Scroll 4 or Fit 8")
        self._actions[label].setChecked(True)
        self._set_view_mode(label)

    def reset_activity(self, message: str) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("activity reset message must be non-empty text")
        self._activity_log.clear()
        self._set_activity_expanded(False)
        self._append_activity(message)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setObjectName("research_restoration.menu_bar")

        file_menu = menu_bar.addMenu("File")
        file_menu.setObjectName("research_restoration.menu.file")
        self.file_menu = file_menu
        new_chart_action = self._add_shell_action(file_menu, "New Chart...")
        new_chart_action.triggered.connect(
            lambda _checked=False: self.new_chart_requested.emit()
        )
        file_menu.addSeparator()
        save_environment_action = self._add_shell_action(
            file_menu, "Save Study Environment..."
        )
        save_environment_action.triggered.connect(
            lambda _checked=False: self.save_study_environment_requested.emit()
        )
        load_environment_action = self._add_shell_action(
            file_menu, "Load Study Environment..."
        )
        load_environment_action.triggered.connect(
            lambda _checked=False: self.load_study_environment_requested.emit()
        )
        manage_environments_action = self._add_shell_action(
            file_menu, "Manage Study Environments..."
        )
        manage_environments_action.triggered.connect(
            lambda _checked=False: self.manage_study_environments_requested.emit()
        )
        file_menu.addSeparator()
        save_snapshot_action = self._add_shell_action(
            file_menu, "Save Workspace..."
        )
        save_snapshot_action.triggered.connect(
            lambda _checked=False: self.save_workspace_snapshot_requested.emit()
        )
        load_snapshot_action = self._add_shell_action(
            file_menu, "Load Workspace..."
        )
        load_snapshot_action.triggered.connect(
            lambda _checked=False: self.load_workspace_snapshot_requested.emit()
        )
        manage_snapshots_action = self._add_shell_action(
            file_menu, "Manage Workspaces..."
        )
        manage_snapshots_action.triggered.connect(
            lambda _checked=False: self.manage_workspace_snapshots_requested.emit()
        )
        file_menu.addSeparator()
        clear_suite_action = self._add_shell_action(
            file_menu, "Clear Research Suite", log_request=False
        )
        clear_tooltip = (
            "Close all Research charts and secondary windows and reset the "
            "Research Suite. Persisted data is not deleted."
        )
        clear_suite_action.setToolTip(clear_tooltip)
        clear_suite_action.setStatusTip(clear_tooltip)
        clear_suite_action.triggered.connect(
            lambda _checked=False: self.clear_research_suite_requested.emit()
        )
        file_menu.addSeparator()
        close_action = QAction("Close", self)
        close_action.setObjectName("research_restoration.action.close")
        close_action.triggered.connect(self.close)
        self._actions[close_action.text()] = close_action
        file_menu.addAction(close_action)

        window_menu = menu_bar.addMenu("Window")
        window_menu.setObjectName("research_restoration.menu.window")
        self.window_menu = window_menu
        self._add_shell_action(window_menu, "Pan Anchor", checkable=True)
        window_menu.addSeparator()

        view_group = QActionGroup(self)
        view_group.setObjectName("research_restoration.action_group.view_mode")
        view_group.setExclusive(True)
        scroll_action = self._add_shell_action(
            window_menu, "Scroll 4", checkable=True
        )
        fit_action = self._add_shell_action(window_menu, "Fit 8", checkable=True)
        view_group.addAction(scroll_action)
        view_group.addAction(fit_action)
        scroll_action.setChecked(True)
        scroll_action.triggered.connect(
            lambda checked: checked and self._set_view_mode("Scroll 4")
        )
        fit_action.triggered.connect(
            lambda checked: checked and self._set_view_mode("Fit 8")
        )
        self._view_mode_group = view_group

        notes_menu = menu_bar.addMenu("Notes")
        notes_menu.setObjectName("research_restoration.menu.notes")
        self.notes_menu = notes_menu
        open_notebook_action = self._add_shell_action(
            notes_menu, "Open Assigned Notebook"
        )
        open_notebook_action.triggered.connect(
            lambda _checked=False: self.open_notebook_requested.emit()
        )
        notebook_manager_action = self._add_shell_action(
            notes_menu, "Notebook Manager..."
        )
        notebook_manager_action.triggered.connect(
            lambda _checked=False: self.notebook_manager_requested.emit()
        )

    def _add_shell_action(
        self,
        menu,
        text: str,
        *,
        checkable: bool = False,
        log_request: bool = True,
    ) -> QAction:
        action = QAction(text, self)
        action.setObjectName(
            "research_restoration.action."
            + text.lower().replace("...", "").replace(" ", "_")
        )
        action.setCheckable(checkable)
        if log_request:
            action.triggered.connect(
                lambda _checked=False, action_text=text: self._append_activity(
                    f"{action_text} requested"
                )
            )
        self._actions[text] = action
        menu.addAction(action)
        return action

    def _build_menu_bar_corner_widget(self) -> None:
        corner = QWidget(self.menuBar())
        corner.setObjectName("research_restoration.menu_bar.quick_actions")
        layout = QHBoxLayout(corner)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(4)

        quick_actions = (
            ("Open Assigned Notebook", "Notebook"),
            ("Save Study Environment...", "Save Environment"),
            ("Load Study Environment...", "Load Environment"),
            ("Save Workspace...", "Save Workspace"),
            ("Load Workspace...", "Load Workspace"),
            ("Clear Research Suite", "Clear Research Suite"),
            ("Pan Anchor", "Pan Anchor"),
        )
        for action_text, label in quick_actions:
            button = QToolButton(corner)
            button.setObjectName(
                "research_restoration.quick."
                + action_text.lower().replace("...", "").replace(" ", "_")
            )
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setDefaultAction(self._actions[action_text])
            button.setText(label)
            layout.addWidget(button)
            self._quick_buttons[action_text] = button

        clear_button = self._quick_buttons["Clear Research Suite"]
        clear_button.setToolTip(
            "Close all Research charts and secondary windows and reset the "
            "Research Suite. Persisted data is not deleted."
        )
        self.set_pan_anchor_visual_state(False)

        view_label = QLabel("View: Scroll 4", corner)
        view_label.setObjectName("research_restoration.label.view_mode")
        layout.addWidget(view_label)
        self._view_mode_label = view_label
        self._menu_bar_corner_widget = corner
        self.menuBar().setCornerWidget(corner, Qt.Corner.TopRightCorner)

    def _set_view_mode(self, label: str) -> None:
        self._view_mode_label.setText(f"View: {label}")

    def _build_activity_surface(self) -> None:
        dock = QDockWidget(self)
        dock.setObjectName("research_restoration.activity")
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        header = QWidget(dock)
        header.setObjectName("research_restoration.activity.header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(4)
        toggle = QToolButton(header)
        toggle.setObjectName("research_restoration.activity.toggle")
        toggle.setText("Research Activity")
        toggle.setCheckable(True)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header_layout.addWidget(toggle)
        header_layout.addStretch(1)
        dock.setTitleBarWidget(header)

        body = QWidget(dock)
        body.setObjectName("research_restoration.activity.body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(4, 2, 4, 4)
        body_layout.setSpacing(2)
        activity_log = QTextEdit(body)
        activity_log.setObjectName("research_restoration.activity.log")
        activity_log.setReadOnly(True)
        body_layout.addWidget(activity_log)
        dock.setWidget(body)

        toggle.toggled.connect(self._set_activity_expanded)
        self._activity_dock = dock
        self._activity_header = header
        self._activity_toggle = toggle
        self._activity_body = body
        self._activity_log = activity_log
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self._set_activity_expanded(False)

    def _set_activity_expanded(self, expanded: bool) -> None:
        self._activity_body.setVisible(expanded)
        self._activity_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        if self._activity_toggle.isChecked() != expanded:
            self._activity_toggle.setChecked(expanded)
        if expanded:
            self._activity_dock.setMaximumHeight(220)
        else:
            self._activity_dock.setMaximumHeight(self._activity_header.sizeHint().height())

    def _append_activity(self, message: str) -> None:
        self._activity_log.append(message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.closed.emit()
        super().closeEvent(event)
