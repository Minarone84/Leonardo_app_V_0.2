"""GUI-only Data Manager Suite shell with honest empty presentation state."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import (
    apply_identity,
    configure_table,
    populate_table,
)


DATA_MANAGER_SUITE_WINDOW_ID = "data_manager_suite.window"
_DATASET_COLUMNS = ("dataset_id", "market", "rows", "status")
_ARTIFACT_COLUMNS = ("artifact_id", "kind", "source", "status")
_RECIPE_COLUMNS = ("recipe_id", "kind", "status")
_OVERVIEW_COLUMNS = ("surface", "state", "details")
_STORAGE_COLUMNS = ("component", "state", "details")
_IMPORT_EXPORT_COLUMNS = ("control", "state", "details")
_QUEUE_COLUMNS = ("item", "progress", "state")


class DataManagerSuiteWindow(QWidget):
    """Data Manager Suite shell awaiting application services."""

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._log_area: QTextEdit | None = None
        self._build_progress = QProgressBar(self)

        self._apply_window_defaults()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_shell()
        self.load_empty_state()


    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Data Manager Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Data Manager Suite table: {table_id}") from error

    def status_text(self) -> str:
        """Return the shell status label text."""

        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        """Return the local status log text."""

        return "" if self._log_area is None else self._log_area.toPlainText()

    def load_empty_state(self) -> None:
        """Reset Data Manager presentation without synthetic catalog data."""

        for table in self._tables.values():
            table.setRowCount(0)
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText("Data Manager workflow messages will appear here.")
        self._set_status("Data Manager services are not connected")


    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Data Manager Suite")
        self.setObjectName("data_manager_suite_window")
        self.setProperty("object_id", DATA_MANAGER_SUITE_WINDOW_ID)
        self.resize(1280, 820)
        font = self.font()
        font.setPointSize(14)
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(
            root,
            "data_manager.layout.root",
            object_type="layout",
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_overview_panel())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_processing_queue_panel())
        root.addWidget(self._build_status_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Data Manager Suite", self)
        apply_identity(
            header,
            "data_manager.panel.header",
            object_type="panel",
        )
        layout = QHBoxLayout(header)
        apply_identity(
            layout,
            "data_manager.layout.header",
            object_type="layout",
        )
        title = QLabel("Data Manager Suite", header)
        apply_identity(
            title,
            "data_manager.label.title",
            object_type="label",
        )
        status = QLabel("Services not connected", header)
        apply_identity(
            status,
            "data_manager.label.status",
            object_type="status_label",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_overview_panel(self) -> QWidget:
        panel = QGroupBox("Data Manager Overview", self)
        apply_identity(
            panel,
            "data_manager.panel.overview",
            object_type="panel",
        )
        layout = QGridLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.overview",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.overview_dummy",
            columns=_OVERVIEW_COLUMNS,
            labels=("Surface", "State", "Details"),
        )
        notice = QLabel(
            "Shell-only: no imports, exports, storage, materialization, recipes, "
            "artifacts, or database workflows execute here.",
            panel,
        )
        apply_identity(
            notice,
            "data_manager.label.boundary_notice",
            object_type="label",
        )
        self._tables["data_manager.table.overview_dummy"] = table
        layout.addWidget(table, 0, 0)
        layout.addWidget(notice, 0, 1)
        return panel

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_identity(
            toolbar,
            "data_manager.toolbar.main",
            object_type="toolbar",
        )
        layout = QHBoxLayout(toolbar)
        apply_identity(
            layout,
            "data_manager.layout.toolbar",
            object_type="layout",
        )
        for button_id, label, action_id, action in (
            (
                "data_manager.button.refresh",
                "Refresh",
                "data_manager.action.refresh",
                self.load_empty_state,
            ),
            (
                "data_manager.button.preview_dummy_dataset",
                "Preview Dataset",
                "data_manager.action.preview_dummy_dataset",
                partial(self._local_action, "data_manager.action.preview_dummy_dataset"),
            ),
            (
                "data_manager.button.preview_dummy_artifact",
                "Preview Artifact",
                "data_manager.action.preview_dummy_artifact",
                partial(self._local_action, "data_manager.action.preview_dummy_artifact"),
            ),
            (
                "data_manager.button.preview_dummy_recipe",
                "Preview Recipe",
                "data_manager.action.preview_dummy_recipe",
                partial(self._local_action, "data_manager.action.preview_dummy_recipe"),
            ),
            (
                "data_manager.button.plan_dummy_database",
                "Plan Database",
                "data_manager.action.plan_dummy_database",
                partial(self._local_action, "data_manager.action.plan_dummy_database"),
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_identity(
                button,
                button_id,
                object_type="button",
                display_label=label,
                action_id=action_id,
                tooltip="GUI shell action only. No storage or materialization.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id, action))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            splitter,
            "data_manager.splitter.catalogs",
            object_type="splitter",
        )
        splitter.addWidget(self._build_dataset_panel())
        splitter.addWidget(self._build_artifact_recipe_panel())
        splitter.addWidget(self._build_database_panel())
        return splitter

    def _build_dataset_panel(self) -> QWidget:
        panel = QGroupBox("Dataset Catalog", self)
        apply_identity(
            panel,
            "data_manager.panel.dataset_catalog_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.dataset_catalog_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.dataset_catalog_dummy",
            columns=_DATASET_COLUMNS,
            labels=("Dataset", "Market", "Rows", "Status"),
        )
        self._tables["data_manager.table.dataset_catalog_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_artifact_recipe_panel(self) -> QWidget:
        panel = QGroupBox("Artifacts / Recipes", self)
        apply_identity(
            panel,
            "data_manager.panel.artifact_recipe_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.artifact_recipe_dummy",
            object_type="layout",
        )
        artifact_panel = QGroupBox("Artifact Catalog", panel)
        apply_identity(
            artifact_panel,
            "data_manager.panel.artifact_catalog_dummy",
            object_type="panel",
        )
        artifact_layout = QVBoxLayout(artifact_panel)
        artifact_table = configure_table(
            QTableWidget(artifact_panel),
            object_id="data_manager.table.artifact_catalog_dummy",
            columns=_ARTIFACT_COLUMNS,
            labels=("Artifact", "Kind", "Source", "Status"),
        )
        artifact_layout.addWidget(artifact_table)
        recipe_panel = QGroupBox("Recipe / Collection Placeholder", panel)
        apply_identity(
            recipe_panel,
            "data_manager.panel.recipe_catalog_dummy",
            object_type="panel",
        )
        recipe_layout = QVBoxLayout(recipe_panel)
        recipe_table = configure_table(
            QTableWidget(recipe_panel),
            object_id="data_manager.table.recipe_catalog_dummy",
            columns=_RECIPE_COLUMNS,
            labels=("Recipe", "Kind", "Status"),
        )
        recipe_layout.addWidget(recipe_table)
        self._tables["data_manager.table.artifact_catalog_dummy"] = artifact_table
        self._tables["data_manager.table.recipe_catalog_dummy"] = recipe_table
        layout.addWidget(artifact_panel)
        layout.addWidget(recipe_panel)
        return panel

    def _build_database_panel(self) -> QWidget:
        panel = QGroupBox("Database Build", self)
        apply_identity(
            panel,
            "data_manager.panel.database_build_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.database_build_dummy",
            object_type="layout",
        )
        storage_table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.storage_readiness_dummy",
            columns=_STORAGE_COLUMNS,
            labels=("Component", "State", "Details"),
        )
        import_export_table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.import_export_controls_dummy",
            columns=_IMPORT_EXPORT_COLUMNS,
            labels=("Control", "State", "Details"),
        )
        label = QLabel("Analysis Database build placeholder", panel)
        apply_identity(
            label,
            "data_manager.label.database_build_dummy",
            object_type="label",
        )
        apply_identity(
            self._build_progress,
            "data_manager.progress.database_build_dummy",
            object_type="progress_bar",
        )
        self._build_progress.setRange(0, 100)
        self._build_progress.setEnabled(False)
        self._tables["data_manager.table.storage_readiness_dummy"] = storage_table
        self._tables["data_manager.table.import_export_controls_dummy"] = (
            import_export_table
        )
        layout.addWidget(storage_table)
        layout.addWidget(import_export_table)
        layout.addWidget(label)
        layout.addWidget(self._build_progress)
        layout.addStretch(1)
        return panel

    def _build_processing_queue_panel(self) -> QWidget:
        panel = QGroupBox("Materialization / Processing Queue", self)
        apply_identity(
            panel,
            "data_manager.panel.processing_queue_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.processing_queue_dummy",
            object_type="layout",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.processing_queue_dummy",
            columns=_QUEUE_COLUMNS,
            labels=("Item", "Progress", "State"),
        )
        self._tables["data_manager.table.processing_queue_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("Metadata / Status", self)
        apply_identity(
            panel,
            "data_manager.panel.metadata_status_dummy",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        apply_identity(
            layout,
            "data_manager.layout.metadata_status_dummy",
            object_type="layout",
        )
        log = QTextEdit(panel)
        apply_identity(
            log,
            "data_manager.text.metadata_status_dummy",
            object_type="text_area",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only unavailable behavior.")
        self._append_log(f"{action_id}: no Data Manager backend ran.")

    def _handle_shell_action(
        self,
        action_id: str,
        handler: Callable[[], None],
    ) -> None:
        if not self._record_action(action_id):
            return
        handler()

    def _record_action(self, action_id: str) -> bool:
        if self._action_observer is None:
            return True
        decision = self._action_observer.record_action(
            action_id,
            window_id=DATA_MANAGER_SUITE_WINDOW_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)
