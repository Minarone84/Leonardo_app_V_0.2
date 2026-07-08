"""GUI-only Data Manager Suite shell with deterministic dummy data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

from leonardo.gui.dummy_data import (
    data_manager_artifact_rows,
    data_manager_dataset_rows,
    data_manager_recipe_rows,
)
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.windows.traceable_shell_widgets import (
    apply_trace,
    configure_table,
    populate_table,
)


DATA_MANAGER_SUITE_METADATA_ID = "data_manager_suite.window"
_DATA_MANAGER_SUITE_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "data_manager_suite.window.toml"
)
_DATASET_COLUMNS = ("dataset_id", "market", "rows", "status")
_ARTIFACT_COLUMNS = ("artifact_id", "kind", "source", "status")
_RECIPE_COLUMNS = ("recipe_id", "kind", "status")


def load_data_manager_suite_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Data Manager Suite shell metadata profile."""

    result = load_metadata_document(_DATA_MANAGER_SUITE_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Data Manager Suite metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class DataManagerSuiteWindow(QWidget):
    """Shell-only Data Manager Suite window using local dummy display data."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._profile = profile if profile is not None else load_data_manager_suite_profile()
        if self._profile.metadata_id != DATA_MANAGER_SUITE_METADATA_ID:
            raise ValueError("profile must describe data_manager_suite.window")
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

        self._apply_profile_metadata()
        self._build_shell()
        self.load_dummy_catalogs()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

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

    def load_dummy_catalogs(self) -> None:
        """Render deterministic dummy catalogs into local tables."""

        populate_table(
            self._tables["data_manager.table.dataset_catalog_dummy"],
            _DATASET_COLUMNS,
            data_manager_dataset_rows(),
        )
        populate_table(
            self._tables["data_manager.table.artifact_catalog_dummy"],
            _ARTIFACT_COLUMNS,
            data_manager_artifact_rows(),
        )
        populate_table(
            self._tables["data_manager.table.recipe_catalog_dummy"],
            _RECIPE_COLUMNS,
            data_manager_recipe_rows(),
        )
        self._build_progress.setValue(0)
        self._set_status("DUMMY catalogs loaded: no storage/materialization ran.")
        self._append_log("Loaded dummy Data Manager catalogs from in-memory fixtures.")

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")
        self.setWindowTitle(_string_value(identity, "title", "Data Manager Suite"))
        self.setObjectName(_string_value(metadata, "object_name", "data_manager_suite_window"))
        self.setProperty(
            "object_id",
            _string_value(metadata, "window_id", DATA_MANAGER_SUITE_METADATA_ID),
        )
        self.resize(_int_value(geometry, "width", 1280), _int_value(geometry, "height", 820))
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_trace(
            root,
            "data_manager.layout.root",
            object_type="layout",
            parent_object_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_status_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Data Manager Suite Shell", self)
        apply_trace(
            header,
            "data_manager.panel.header",
            object_type="panel",
            parent_object_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(header)
        apply_trace(
            layout,
            "data_manager.layout.header",
            object_type="layout",
            parent_object_id="data_manager.panel.header",
        )
        title = QLabel("Data Manager Suite", header)
        apply_trace(
            title,
            "data_manager.label.title",
            object_type="label",
            parent_object_id="data_manager.panel.header",
        )
        status = QLabel("DUMMY shell only", header)
        apply_trace(
            status,
            "data_manager.label.status",
            object_type="status_label",
            parent_object_id="data_manager.panel.header",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_trace(
            toolbar,
            "data_manager.toolbar.main",
            object_type="toolbar",
            parent_object_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(toolbar)
        apply_trace(
            layout,
            "data_manager.layout.toolbar",
            object_type="layout",
            parent_object_id="data_manager.toolbar.main",
        )
        for button_id, label, action_id, action in (
            (
                "data_manager.button.load_dummy_catalogs",
                "Load Dummy Catalogs",
                "data_manager.action.load_dummy_catalogs",
                self.load_dummy_catalogs,
            ),
            (
                "data_manager.button.preview_dummy_dataset",
                "Preview Dummy Dataset",
                "data_manager.action.preview_dummy_dataset",
                partial(self._local_action, "data_manager.action.preview_dummy_dataset"),
            ),
            (
                "data_manager.button.preview_dummy_artifact",
                "Preview Dummy Artifact",
                "data_manager.action.preview_dummy_artifact",
                partial(self._local_action, "data_manager.action.preview_dummy_artifact"),
            ),
            (
                "data_manager.button.preview_dummy_recipe",
                "Preview Dummy Recipe",
                "data_manager.action.preview_dummy_recipe",
                partial(self._local_action, "data_manager.action.preview_dummy_recipe"),
            ),
            (
                "data_manager.button.plan_dummy_database",
                "Plan Dummy Database",
                "data_manager.action.plan_dummy_database",
                partial(self._local_action, "data_manager.action.plan_dummy_database"),
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_trace(
                button,
                button_id,
                object_type="button",
                display_label=label,
                parent_object_id="data_manager.toolbar.main",
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
        apply_trace(
            splitter,
            "data_manager.splitter.catalogs",
            object_type="splitter",
            parent_object_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        splitter.addWidget(self._build_dataset_panel())
        splitter.addWidget(self._build_artifact_recipe_panel())
        splitter.addWidget(self._build_database_panel())
        return splitter

    def _build_dataset_panel(self) -> QWidget:
        panel = QGroupBox("Dataset Catalog Dummy", self)
        apply_trace(
            panel,
            "data_manager.panel.dataset_catalog_dummy",
            object_type="panel",
            parent_object_id="data_manager.splitter.catalogs",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "data_manager.layout.dataset_catalog_dummy",
            object_type="layout",
            parent_object_id="data_manager.panel.dataset_catalog_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.dataset_catalog_dummy",
            columns=_DATASET_COLUMNS,
            labels=("Dataset", "Market", "Rows", "Status"),
            parent_object_id="data_manager.panel.dataset_catalog_dummy",
        )
        self._tables["data_manager.table.dataset_catalog_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_artifact_recipe_panel(self) -> QWidget:
        panel = QGroupBox("Artifacts / Recipes Dummy", self)
        apply_trace(
            panel,
            "data_manager.panel.artifact_recipe_dummy",
            object_type="panel",
            parent_object_id="data_manager.splitter.catalogs",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "data_manager.layout.artifact_recipe_dummy",
            object_type="layout",
            parent_object_id="data_manager.panel.artifact_recipe_dummy",
        )
        artifact_table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.artifact_catalog_dummy",
            columns=_ARTIFACT_COLUMNS,
            labels=("Artifact", "Kind", "Source", "Status"),
            parent_object_id="data_manager.panel.artifact_recipe_dummy",
        )
        recipe_table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.table.recipe_catalog_dummy",
            columns=_RECIPE_COLUMNS,
            labels=("Recipe", "Kind", "Status"),
            parent_object_id="data_manager.panel.artifact_recipe_dummy",
        )
        self._tables["data_manager.table.artifact_catalog_dummy"] = artifact_table
        self._tables["data_manager.table.recipe_catalog_dummy"] = recipe_table
        layout.addWidget(artifact_table)
        layout.addWidget(recipe_table)
        return panel

    def _build_database_panel(self) -> QWidget:
        panel = QGroupBox("Database Build Dummy", self)
        apply_trace(
            panel,
            "data_manager.panel.database_build_dummy",
            object_type="panel",
            parent_object_id="data_manager.splitter.catalogs",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "data_manager.layout.database_build_dummy",
            object_type="layout",
            parent_object_id="data_manager.panel.database_build_dummy",
        )
        label = QLabel("Analysis Database build placeholder", panel)
        apply_trace(
            label,
            "data_manager.label.database_build_dummy",
            object_type="label",
            parent_object_id="data_manager.panel.database_build_dummy",
        )
        apply_trace(
            self._build_progress,
            "data_manager.progress.database_build_dummy",
            object_type="progress_bar",
            parent_object_id="data_manager.panel.database_build_dummy",
        )
        self._build_progress.setRange(0, 100)
        self._build_progress.setEnabled(False)
        layout.addWidget(label)
        layout.addWidget(self._build_progress)
        layout.addStretch(1)
        return panel

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("Metadata / Status Dummy", self)
        apply_trace(
            panel,
            "data_manager.panel.metadata_status_dummy",
            object_type="panel",
            parent_object_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "data_manager.layout.metadata_status_dummy",
            object_type="layout",
            parent_object_id="data_manager.panel.metadata_status_dummy",
        )
        log = QTextEdit(panel)
        apply_trace(
            log,
            "data_manager.text.metadata_status_dummy",
            object_type="text_area",
            parent_object_id="data_manager.panel.metadata_status_dummy",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only dummy behavior.")
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
            window_id=DATA_MANAGER_SUITE_METADATA_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)


def _mapping_at(values: object, key: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        return {}
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: object, key: str, fallback: str) -> str:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, str) and value else fallback


def _int_value(values: object, key: str, fallback: int) -> int:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback
