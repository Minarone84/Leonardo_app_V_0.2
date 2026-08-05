"""Data Manager catalog and exact-object management window."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerMarketSnapshot,
    DataManagerRecipeEntry,
    DataManagerProductCatalogSnapshot,
)
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.data_manager import (
    DataManagerCatalogWorkspace,
    DataManagerCreationWorkspace,
    DataManagerOperationSurface,
    DataManagerUpdateWorkspace,
)
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.data_manager_dataset_selector_dialog import (
    DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
    DataManagerDatasetSelectorDialog,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table
from leonardo.financial_tools import CONSTRUCT_SPECS


DATA_MANAGER_SUITE_WINDOW_ID = "data_manager_suite.window"
_ARTIFACT_COLUMNS = (
    "Artifact",
    "Tool",
    "Kind",
    "Outputs",
    "Rows",
    "Current",
    "State",
)
_RECIPE_COLUMNS = ("Recipe", "Tool", "Kind", "Outputs", "Name", "Created", "State")


class DataManagerSuiteWindow(QWidget):
    """Display immutable Data Manager projections and emit user intent."""

    refresh_requested = Signal()
    market_selected = Signal(object)
    artifact_selected = Signal(object)
    recipe_selected = Signal(object)
    preview_dataset_requested = Signal()
    preview_artifact_requested = Signal()
    validate_artifact_requested = Signal()
    delete_artifact_requested = Signal()
    delete_recipe_requested = Signal()
    closing = Signal()
    creation_action_requested = Signal(str, object)
    update_action_requested = Signal(str, object)
    catalog_row_selected = Signal(str, object)
    catalog_history_selected = Signal(str, str, object)
    creation_cancel_requested = Signal()

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        floating_window_tracker: Callable[[QWidget, str, str, str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        if floating_window_tracker is not None and not callable(floating_window_tracker):
            raise TypeError("floating_window_tracker must be callable or None")
        self._action_observer = action_observer
        self._floating_window_tracker = floating_window_tracker
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._datasets = ()
        self._artifacts: tuple[DataManagerArtifactEntry, ...] = ()
        self._recipes: tuple[DataManagerRecipeEntry, ...] = ()
        self._selected_market: MarketId | None = None
        self._status_label: QLabel | None = None
        self._selected_market_label: QLabel | None = None
        self._selection_details: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._log_area: QTextEdit | None = None
        self._creation_controls: dict[str, QWidget] = {}
        self._creation_stage_list: QListWidget | None = None
        self._creation_stack: QStackedWidget | None = None
        self._creation_summary: QLabel | None = None
        self._cancel_button: QPushButton | None = None
        self._catalog_workspace: DataManagerCatalogWorkspace | None = None
        self._dataset_selector_dialog: DataManagerDatasetSelectorDialog | None = None
        self._creation_workspace: DataManagerCreationWorkspace | None = None
        self._update_workspace: DataManagerUpdateWorkspace | None = None
        self._operation_surface: DataManagerOperationSurface | None = None
        self._busy = False
        self._build_window()
        apply_theme_stylesheet(self, load_default_theme())
        self.load_empty_state()

    def button_for_id(self, button_id: str) -> QPushButton:
        if button_id == "data_manager.button.cancel_operation" and self._cancel_button is not None:
            return self._cancel_button
        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Data Manager button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Data Manager table: {table_id}") from error

    def status_text(self) -> str:
        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        return "" if self._log_area is None else self._log_area.toPlainText()

    def selected_market_id(self) -> MarketId | None:
        return self._selected_market

    def selected_artifact(self) -> DataManagerArtifactEntry | None:
        index = self._selected_row("data_manager.table.artifacts")
        return None if index is None else self._artifacts[index]

    def selected_recipe(self) -> DataManagerRecipeEntry | None:
        index = self._selected_row("data_manager.table.recipes")
        return None if index is None else self._recipes[index]

    def load_empty_state(self) -> None:
        self._datasets = ()
        self._artifacts = ()
        self._recipes = ()
        self._selected_market = None
        for table in self._tables.values():
            table.setRowCount(0)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_catalog(DataManagerCatalogSnapshot(()))
            self._dataset_selector_dialog.set_current_market(None)
        self._set_selected_market_text("No accepted market selected")
        self._set_selection_details("Select an accepted dataset to inspect recipes and artifacts.")
        self.set_status("Scanning canonical persistence")
        self._sync_actions()

    def set_catalog(self, snapshot: DataManagerCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerCatalogSnapshot")
        self._datasets = snapshot.datasets
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_catalog(snapshot)
        self._sync_actions()

    def set_market_snapshot(self, snapshot: DataManagerMarketSnapshot | None) -> None:
        if snapshot is not None and not isinstance(snapshot, DataManagerMarketSnapshot):
            raise TypeError("snapshot must be a DataManagerMarketSnapshot or None")
        self._clear_object_selection()
        self._selected_market = None if snapshot is None else snapshot.market_id
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_current_market(self._selected_market)
        self._artifacts = () if snapshot is None else snapshot.artifacts
        self._recipes = () if snapshot is None else snapshot.recipes
        self._populate_artifacts()
        self._populate_recipes()
        if snapshot is None:
            self._set_selected_market_text("No accepted market selected")
            self._set_selection_details(
                "Select an accepted dataset to inspect recipes and artifacts."
            )
        else:
            self._set_selected_market_text(snapshot.market_id.as_key())
            self._set_selection_details(
                f"{len(snapshot.artifacts)} artifact(s), {len(snapshot.recipes)} recipe(s)"
            )
        self._sync_actions()

    def select_market(
        self, market_id: MarketId, *, emit_selection: bool = True
    ) -> bool:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        accepted = next(
            (
                entry
                for entry in self._datasets
                if entry.accepted and entry.market_id == market_id
            ),
            None,
        )
        if accepted is None:
            return False
        self._selected_market = market_id
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_current_market(market_id)
        self._set_selected_market_text(market_id.as_key())
        self._set_selection_details("Loading recipes and artifacts...")
        self._sync_actions()
        if emit_selection:
            self.market_selected.emit(market_id)
        return True

    def clear_selected_market(self, details: str) -> None:
        if not isinstance(details, str):
            raise TypeError("details must be a string")
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_current_market(None)
            self._dataset_selector_dialog.clear_selection()
        self.set_market_snapshot(None)
        self._set_selection_details(details)

    def update_artifact_validation(
        self, validation: DataManagerArtifactValidation
    ) -> None:
        for index, artifact in enumerate(self._artifacts):
            if (
                artifact.market_id == validation.market_id
                and artifact.kind == validation.kind
                and artifact.tool_key == validation.tool_key
                and artifact.artifact_id == validation.artifact_id
            ):
                values = list(self._artifacts)
                values[index] = DataManagerArtifactEntry(
                    market_id=artifact.market_id,
                    artifact_id=artifact.artifact_id,
                    recipe_id=artifact.recipe_id,
                    tool_key=artifact.tool_key,
                    kind=artifact.kind,
                    output_names=artifact.output_names,
                    row_count=artifact.row_count,
                    first_timestamp_ms=artifact.first_timestamp_ms,
                    last_timestamp_ms=artifact.last_timestamp_ms,
                    created_at_utc=artifact.created_at_utc,
                    valid=artifact.valid,
                    rejection_reason=artifact.rejection_reason,
                    current_status=validation.status,
                    current_reason=validation.reason,
                )
                self._artifacts = tuple(values)
                self._populate_artifacts()
                self._tables["data_manager.table.artifacts"].selectRow(index)
                return

    def set_busy(
        self, busy: bool, operation: str = "", *, preserve_operation: bool = False
    ) -> None:
        self._busy = bool(busy)
        for table in self._tables.values():
            table.setEnabled(not self._busy)
        if self._catalog_workspace is not None:
            self._catalog_workspace.setEnabled(not self._busy)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_busy(self._busy)
        if self._creation_workspace is not None:
            self._creation_workspace.set_busy(self._busy)
        if self._update_workspace is not None:
            self._update_workspace.set_busy(self._busy)
        if self._busy:
            self.set_status(f"Operation in progress: {operation}")
            if self._operation_surface is not None and not preserve_operation:
                self._operation_surface.begin(operation)
        self._sync_actions()

    def set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def append_status(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)

    def set_progress(
        self, current: int | None, total: int | None, message: str = ""
    ) -> None:
        if self._progress is None:
            return
        if total is None or total <= 0:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, total)
            self._progress.setValue(max(0, min(total, current or 0)))
        if self._operation_surface is not None:
            self._operation_surface.set_progress(current, total, message)

    def set_operation_task(self, task_id: str) -> None:
        if self._operation_surface is not None:
            self._operation_surface.set_task_id(task_id)

    def settle_operation(
        self,
        state: str,
        message: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if self._operation_surface is not None:
            self._operation_surface.settle(state, message, details)

    def set_product_catalogs(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_snapshot(snapshot)
        self.set_catalog(snapshot.catalog)
        self.set_creation_catalogs(
            portable_recipes=tuple(
                (item.recipe_id, f"{item.tool_key} - {', '.join(item.output_names)}")
                for item in snapshot.portable_recipes.recipes
                if item.valid
            ),
            seeds=tuple(
                (item.seed_id, item.display_name) for item in snapshot.database_seeds
            ),
            collections=tuple(
                (item.collection_id, item.display_name)
                for item in snapshot.artifact_collections
            ),
            databases=tuple(
                (item.definition.database_id, item.definition.display_name)
                for item in snapshot.databases
            ),
            environments=tuple(
                (item.environment_id, item.display_name)
                for item in snapshot.study_environments.environments
                if item.valid
            ),
            recipe_collections=tuple(
                (item.collection_id, item.display_name)
                for item in snapshot.recipe_collections.collections
                if item.valid
            ),
        )
        if self._update_workspace is not None:
            self._update_workspace.set_snapshot(snapshot)

    def set_catalog_inspection(
        self,
        fields: tuple[tuple[str, object], ...],
        history: tuple[tuple[str, str, str], ...] = (),
    ) -> None:
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_inspection(fields, history)

    def set_catalog_history(
        self, logical_identity: str, values: tuple[object, ...]
    ) -> None:
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_history_items(logical_identity, values)

    def set_historical_catalog_inspection(self, value: object) -> None:
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_historical_inspection(value)

    def set_update_artifact_plan(self, plan: object) -> None:
        if self._update_workspace is not None:
            self._update_workspace.set_artifact_plan(plan)

    def clear_update_artifact_plan(self) -> None:
        if self._update_workspace is not None:
            self._update_workspace.clear_artifact_plan()

    def set_update_database_plan(self, plan: object) -> None:
        if self._update_workspace is not None:
            self._update_workspace.set_database_plan(plan)

    def clear_update_database_plan(self) -> None:
        if self._update_workspace is not None:
            self._update_workspace.clear_database_plan()

    def set_artifact_update_result(self, result: object) -> None:
        if self._update_workspace is not None:
            self._update_workspace.set_artifact_update_result(result)

    def set_database_update_result(self, result: object) -> None:
        if self._update_workspace is not None:
            self._update_workspace.set_database_update_result(result)

    def set_creation_base_plan_ready(self, ready: bool) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_base_plan_ready(ready)

    def set_creation_batch_plan_ready(self, ready: bool) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_batch_plan_ready(ready)

    def set_creation_readiness_ready(self, ready: bool) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_database_readiness_ready(ready)

    def invalidate_creation_plans(self) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.invalidate_all_plans()

    def set_creation_environment_rows(
        self, rows: tuple[tuple[str, ...], ...]
    ) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_environment_rows(rows)

    def set_creation_recipe_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_recipe_rows(rows)

    def set_creation_plan_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_plan_rows(rows)

    def set_creation_readiness_rows(
        self, rows: tuple[tuple[str, ...], ...]
    ) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_readiness_rows(rows)

    def set_creation_build_report(
        self, rows: tuple[tuple[str, ...], ...]
    ) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_build_report(rows)

    def set_creation_collection_rows(
        self, rows: tuple[tuple[str, ...], ...]
    ) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_collection_rows(rows)

    def confirm_database_seed_deletion(self, seed_id: str) -> bool:
        return QMessageBox.question(
            self,
            "Delete Database Seed",
            f"Delete exactly one unreferenced Database Seed?\n\n{seed_id}",
        ) == QMessageBox.StandardButton.Yes

    def confirm_database_publication(
        self,
        *,
        database_identity: str,
        market_id: MarketId,
        seed_id: str,
        collection_id: str,
        collection_revision_id: str,
        row_count: int,
        column_count: int,
        coverage: str,
        selected_columns: tuple[str, ...],
    ) -> bool:
        message = (
            f"Database: {database_identity}\n"
            f"MarketId: {market_id.as_key()}\n"
            f"Seed: {seed_id}\n"
            f"Artifact Collection: {collection_id} / {collection_revision_id}\n"
            f"Rows: {row_count}\nColumns: {column_count}\n"
            f"Coverage: {coverage}\n"
            f"Selected columns: {', '.join(selected_columns)}\n\n"
            "This publishes a new immutable Database revision."
        )
        return QMessageBox.question(
            self, "Publish Database Revision", message
        ) == QMessageBox.StandardButton.Yes

    def confirm_database_rebuild(self, plan: object) -> bool:
        source_change = getattr(plan, "source_change", None)
        plan_status = str(getattr(plan, "status", "") or "unavailable")
        source_status = str(
            getattr(source_change, "status", "") or "unavailable"
        )
        source_reason = str(
            getattr(source_change, "reason", "") or "not provided"
        )
        message = (
            f"Database: {getattr(plan, 'database_id', '')}\n"
            f"Current revision: {getattr(plan, 'database_revision_id', '')}\n"
            f"Database plan status: {plan_status}\n"
            f"Source-change status: {source_status}\n"
            f"Reason append is unsafe: {source_reason}\n"
            f"Target Artifact Collection revision: "
            f"{getattr(plan, 'collection_revision_id', '')}\n\n"
            "This publishes a new immutable Database revision. "
            "Previous revisions remain unchanged."
        )
        return QMessageBox.question(
            self, "Rebuild Database Revision", message
        ) == QMessageBox.StandardButton.Yes

    def creation_text(self, object_id: str) -> str:
        if self._creation_workspace is not None:
            return self._creation_workspace.value(object_id)
        control = self._creation_controls.get(object_id)
        if isinstance(control, QLineEdit):
            return control.text().strip()
        if isinstance(control, QComboBox):
            data = control.currentData()
            return "" if data is None else str(data)
        raise KeyError(f"Unknown Data Manager creation control: {object_id}")

    def set_creation_summary(self, message: str) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.summary.setText(message)
        if self._creation_summary is not None:
            self._creation_summary.setText(message)

    def set_creation_catalogs(
        self,
        *,
        portable_recipes: tuple[tuple[str, str], ...],
        seeds: tuple[tuple[str, str], ...],
        collections: tuple[tuple[str, str], ...],
        databases: tuple[tuple[str, str], ...],
        environments: tuple[tuple[str, str], ...] = (),
        recipe_collections: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.set_catalogs(
                portable_recipes=portable_recipes,
                seeds=seeds,
                collections=collections,
                databases=databases,
                environments=environments,
                recipe_collections=recipe_collections,
            )
            self._sync_actions()
            return
        values = {
            "data_manager.combo.portable_recipe": portable_recipes,
            "data_manager.combo.seed": seeds,
            "data_manager.combo.artifact_collection": collections,
            "data_manager.combo.database": databases,
        }
        for object_id, entries in values.items():
            combo = self._creation_controls.get(object_id)
            if not isinstance(combo, QComboBox):
                continue
            current = combo.currentData()
            blocker = QSignalBlocker(combo)
            combo.clear()
            for identity, label in entries:
                combo.addItem(label, identity)
            if current is not None:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            del blocker
        self._sync_actions()

    def select_creation_stage(self, index: int) -> None:
        if self._creation_workspace is not None:
            self._creation_workspace.select_stage(index)
            return
        if self._creation_stage_list is None or not 0 <= index < self._creation_stage_list.count():
            raise ValueError("creation stage index is invalid")
        self._creation_stage_list.setCurrentRow(index)

    def creation_stage(self) -> int:
        return -1 if self._creation_stage_list is None else self._creation_stage_list.currentRow()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.close()
        self.closing.emit()
        super().closeEvent(event)

    def _build_window(self) -> None:
        self.setWindowTitle("Data Manager Suite")
        self.setObjectName("data_manager_suite_window")
        self.setProperty("object_id", DATA_MANAGER_SUITE_WINDOW_ID)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1280, 820)
        root = QVBoxLayout(self)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        tabs = QTabWidget(self)
        apply_identity(tabs, "data_manager.tabs.workspace", object_type="tab_widget")
        tabs.addTab(self._build_catalogs(), "Catalogs")
        tabs.addTab(self._build_creation_workflow(), "Create Database")
        tabs.addTab(self._build_update_workflow(), "Update & Reconcile")
        root.addWidget(tabs, 1)
        root.addWidget(self._build_status())

    def _build_header(self) -> QWidget:
        panel = QGroupBox("Data Manager Suite", self)
        layout = QHBoxLayout(panel)
        selected = QLabel(panel)
        apply_identity(
            selected, "data_manager.label.selected_market", object_type="label"
        )
        details = QLabel(panel)
        details.setWordWrap(True)
        apply_identity(
            details, "data_manager.label.selection_details", object_type="label"
        )
        status = QLabel(panel)
        apply_identity(status, "data_manager.label.status", object_type="status_label")
        self._selected_market_label = selected
        self._selection_details = details
        self._status_label = status
        layout.addWidget(selected)
        layout.addWidget(details, 1)
        layout.addWidget(status)
        return panel

    def _build_toolbar(self) -> QWidget:
        panel = QGroupBox("Actions", self)
        layout = QHBoxLayout(panel)
        actions = (
            ("data_manager.button.refresh", "Refresh", self.refresh_requested.emit),
            (
                "data_manager.button.select_dataset",
                "Select Dataset",
                self._show_dataset_selector,
            ),
            (
                "data_manager.button.preview_dataset",
                "Preview Dataset",
                self.preview_dataset_requested.emit,
            ),
            (
                "data_manager.button.preview_artifact",
                "Preview Artifact",
                self.preview_artifact_requested.emit,
            ),
            (
                "data_manager.button.validate_artifact",
                "Validate Artifact",
                self.validate_artifact_requested.emit,
            ),
            (
                "data_manager.button.delete_artifact",
                "Delete Artifact",
                self._confirm_delete_artifact,
            ),
            (
                "data_manager.button.delete_recipe",
                "Delete Recipe",
                self._confirm_delete_recipe,
            ),
        )
        for object_id, label, callback in actions:
            button = QPushButton(label, panel)
            apply_identity(
                button,
                object_id,
                object_type="button",
                display_label=label,
                action_id=object_id,
            )
            button.clicked.connect(partial(self._invoke_action, object_id, callback))
            if object_id == "data_manager.button.cancel_operation":
                self._cancel_button = button
            else:
                self._buttons[object_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return panel

    def _build_catalogs(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        workspace = DataManagerCatalogWorkspace(splitter)
        workspace.row_selected.connect(self.catalog_row_selected.emit)
        workspace.history_selected.connect(self.catalog_history_selected.emit)
        self._catalog_workspace = workspace
        splitter.addWidget(workspace)
        objects = QSplitter(Qt.Orientation.Horizontal, splitter)
        objects.addWidget(
            self._table_panel(
                objects, "Artifacts", "data_manager.table.artifacts", _ARTIFACT_COLUMNS
            )
        )
        objects.addWidget(
            self._table_panel(
                objects, "Recipes", "data_manager.table.recipes", _RECIPE_COLUMNS
            )
        )
        splitter.addWidget(objects)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return splitter

    def _table_panel(
        self, parent: QWidget, title: str, object_id: str, columns: tuple[str, ...]
    ) -> QWidget:
        panel = QGroupBox(title, parent)
        layout = QVBoxLayout(panel)
        table = configure_table(
            QTableWidget(panel), object_id=object_id, columns=columns, labels=columns
        )
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if object_id == "data_manager.table.artifacts":
            table.itemSelectionChanged.connect(self._on_artifact_selection)
        else:
            table.itemSelectionChanged.connect(self._on_recipe_selection)
        self._tables[object_id] = table
        layout.addWidget(table)
        return panel

    def _build_status(self) -> QWidget:
        surface = DataManagerOperationSurface(self)
        surface.cancel_requested.connect(self.creation_cancel_requested.emit)
        self._operation_surface = surface
        self._progress = surface.progress
        self._log_area = surface.log
        self._cancel_button = surface.cancel_button
        return surface

    def _build_creation_workflow(self) -> QWidget:
        workspace = DataManagerCreationWorkspace(self)
        workspace.action_requested.connect(self.creation_action_requested.emit)
        self._creation_workspace = workspace
        self._creation_controls = workspace.controls
        self._creation_stage_list = workspace.stage_list
        self._creation_stack = workspace.stack
        self._creation_summary = workspace.summary
        self._buttons.update(workspace.buttons)
        return workspace

    def _build_update_workflow(self) -> QWidget:
        workspace = DataManagerUpdateWorkspace(self)
        workspace.action_requested.connect(self.update_action_requested.emit)
        self._update_workspace = workspace
        self._buttons.update(workspace.buttons)
        return workspace

    def _build_creation_workflow_legacy(self) -> QWidget:
        panel = QWidget(self)
        layout = QHBoxLayout(panel)
        stages = QListWidget(panel)
        apply_identity(stages, "data_manager.list.creation_stages", object_type="list")
        for title in (
            "1. Target OHLCV",
            "2. Database Seed",
            "3. Study Environments",
            "4. Recipes",
            "5. Base Artifacts",
            "6. Batch Artifacts",
            "7. Artifact Collection",
            "8. Database Review",
            "9. Build Database",
        ):
            stages.addItem(title)
        stages.setFixedWidth(210)
        stack = QStackedWidget(panel)
        apply_identity(stack, "data_manager.stack.creation", object_type="stack")
        self._creation_stage_list = stages
        self._creation_stack = stack
        stages.currentRowChanged.connect(stack.setCurrentIndex)
        stack.addWidget(self._creation_page(
            "Target OHLCV",
            "Use the accepted dataset selected in the catalog.",
            (("data_manager.button.creation.use_target", "Use Selected Dataset", "use_target"),),
        ))
        stack.addWidget(self._seed_page())
        stack.addWidget(self._creation_page(
            "Study Environments",
            "Reload canonical Study Environments and portability evidence.",
            (("data_manager.button.creation.refresh_foundations", "Refresh Foundations", "refresh_foundations"),),
        ))
        stack.addWidget(self._recipe_page())
        stack.addWidget(self._creation_page(
            "Base Artifacts",
            "Materialize the accepted portable Recipe DAG through the shared runtime.",
            (("data_manager.button.creation.materialize_base", "Materialize Base Artifacts", "materialize_base"),),
        ))
        stack.addWidget(self._batch_page())
        stack.addWidget(self._collection_page())
        stack.addWidget(self._creation_page(
            "Database Review",
            "Validate exact source evidence, dependency membership, outputs, coverage, and columns.",
            (("data_manager.button.creation.review", "Validate Readiness", "review"),),
        ))
        stack.addWidget(self._creation_page(
            "Build Database",
            "Publish the first immutable Database revision and exact materialized snapshot.",
            (
                ("data_manager.button.creation.build", "Build Database Revision", "build"),
                ("data_manager.button.creation.reload", "Reload Durable Creation State", "reload_creation"),
            ),
        ))
        summary = QLabel("Select an accepted Target OHLCV to begin.", panel)
        summary.setWordWrap(True)
        apply_identity(summary, "data_manager.label.creation_summary", object_type="status_label")
        self._creation_summary = summary
        right = QVBoxLayout()
        right.addWidget(stack, 1)
        right.addWidget(summary)
        layout.addWidget(stages)
        layout.addLayout(right, 1)
        stages.setCurrentRow(0)
        return panel

    def _seed_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        title = QLabel("Database Seed", page)
        apply_identity(title, "data_manager.label.creation.seed", object_type="label")
        layout.addWidget(title)
        form = QFormLayout()
        existing = QComboBox(page)
        apply_identity(existing, "data_manager.combo.seed", object_type="combo_box")
        self._creation_controls["data_manager.combo.seed"] = existing
        name = QLineEdit(page)
        name.setPlaceholderText("Database name")
        apply_identity(name, "data_manager.input.seed_name", object_type="line_edit")
        description = QLineEdit(page)
        description.setPlaceholderText("Description")
        apply_identity(description, "data_manager.input.seed_description", object_type="line_edit")
        self._creation_controls["data_manager.input.seed_name"] = name
        self._creation_controls["data_manager.input.seed_description"] = description
        form.addRow("Existing Seeds", existing)
        form.addRow("Name", name)
        form.addRow("Description", description)
        layout.addLayout(form)
        layout.addWidget(self._creation_button(
            page, "data_manager.button.creation.create_seed", "Create Database Seed", "create_seed"
        ))
        layout.addStretch(1)
        return page

    def _recipe_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        recipes = QComboBox(page)
        apply_identity(recipes, "data_manager.combo.portable_recipe", object_type="combo_box")
        self._creation_controls["data_manager.combo.portable_recipe"] = recipes
        form = QFormLayout()
        form.addRow("Portable Recipe", recipes)
        layout.addLayout(form)
        layout.addWidget(self._creation_button(
            page, "data_manager.button.creation.plan_base", "Plan Selected Recipe", "plan_base"
        ))
        layout.addStretch(1)
        return page

    def _collection_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        collections = QComboBox(page)
        apply_identity(
            collections, "data_manager.combo.artifact_collection", object_type="combo_box"
        )
        self._creation_controls["data_manager.combo.artifact_collection"] = collections
        databases = QComboBox(page)
        apply_identity(databases, "data_manager.combo.database", object_type="combo_box")
        self._creation_controls["data_manager.combo.database"] = databases
        form = QFormLayout()
        form.addRow("Artifact Collection", collections)
        form.addRow("Existing Database", databases)
        layout.addLayout(form)
        layout.addWidget(self._creation_button(
            page, "data_manager.button.creation.create_collection", "Create Artifact Collection", "create_collection"
        ))
        layout.addStretch(1)
        return page

    def _batch_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        form = QFormLayout()
        tools = QComboBox(page)
        for key, specification in CONSTRUCT_SPECS.items():
            tools.addItem(specification.title, key)
        apply_identity(tools, "data_manager.combo.batch_tool", object_type="combo_box")
        self._creation_controls["data_manager.combo.batch_tool"] = tools
        form.addRow("Derived tool", tools)
        layout.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(self._creation_button(
            page, "data_manager.button.creation.plan_batch", "Plan Batch Branch", "plan_batch"
        ))
        row.addWidget(self._creation_button(
            page, "data_manager.button.creation.execute_batch", "Execute Batch Branch", "execute_batch"
        ))
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _creation_page(
        self,
        title: str,
        detail: str,
        actions: tuple[tuple[str, str, str], ...],
    ) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        heading = QLabel(title, page)
        heading.setStyleSheet("font-weight: 600;")
        detail_label = QLabel(detail, page)
        detail_label.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(detail_label)
        for object_id, label, action in actions:
            layout.addWidget(self._creation_button(page, object_id, label, action))
        layout.addStretch(1)
        return page

    def _creation_button(
        self, parent: QWidget, object_id: str, label: str, action: str
    ) -> QPushButton:
        button = QPushButton(label, parent)
        apply_identity(
            button, object_id, object_type="button", display_label=label,
            action_id=object_id,
        )
        button.clicked.connect(
            partial(self._invoke_action, object_id, lambda: self._emit_creation(action))
        )
        self._buttons[object_id] = button
        return button

    def _emit_creation(self, action: str) -> None:
        payload = {
            "seed_name": self.creation_text("data_manager.input.seed_name"),
            "seed_description": self.creation_text("data_manager.input.seed_description"),
            "batch_tool": self.creation_text("data_manager.combo.batch_tool"),
            "portable_recipe_id": self.creation_text("data_manager.combo.portable_recipe"),
            "seed_id": self.creation_text("data_manager.combo.seed"),
            "collection_id": self.creation_text("data_manager.combo.artifact_collection"),
            "database_id": self.creation_text("data_manager.combo.database"),
        }
        self.creation_action_requested.emit(action, payload)

    def dataset_selector_dialog(self) -> DataManagerDatasetSelectorDialog | None:
        return self._dataset_selector_dialog

    def _show_dataset_selector(self) -> None:
        dialog = self._ensure_dataset_selector()
        dialog.prepare_for_market(self._selected_market)
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _ensure_dataset_selector(self) -> DataManagerDatasetSelectorDialog:
        dialog = self._dataset_selector_dialog
        if dialog is not None:
            return dialog
        dialog = DataManagerDatasetSelectorDialog(
            action_observer=self._action_observer,
            parent=self,
        )
        dialog.set_catalog(DataManagerCatalogSnapshot(tuple(self._datasets)))
        dialog.set_current_market(self._selected_market)
        dialog.refresh_requested.connect(self.refresh_requested.emit)
        dialog.market_selected.connect(self._on_dataset_selector_selected)
        self._dataset_selector_dialog = dialog
        if self._floating_window_tracker is not None:
            self._floating_window_tracker(
                dialog,
                DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
                dialog.windowTitle(),
                "dialog",
            )
        return dialog

    def _on_dataset_selector_selected(self, market_id: object) -> None:
        if not isinstance(market_id, MarketId):
            return
        self._selected_market = market_id
        self._set_selected_market_text(market_id.as_key())
        self._set_selection_details("Loading recipes and artifacts...")
        self.market_selected.emit(market_id)
        self._sync_actions()

    def _on_artifact_selection(self) -> None:
        artifact = self.selected_artifact()
        self.artifact_selected.emit(artifact)
        self._set_selection_details(
            "No artifact selected"
            if artifact is None
            else artifact.rejection_reason
            if not artifact.valid
            else f"Artifact {artifact.artifact_id}"
        )
        self._sync_actions()

    def _on_recipe_selection(self) -> None:
        recipe = self.selected_recipe()
        self.recipe_selected.emit(recipe)
        self._set_selection_details(
            "No recipe selected"
            if recipe is None
            else recipe.rejection_reason
            if not recipe.valid
            else f"Recipe {recipe.recipe_id}"
        )
        self._sync_actions()

    def _clear_object_selection(self) -> None:
        for object_id in ("data_manager.table.artifacts", "data_manager.table.recipes"):
            self._tables[object_id].clearSelection()
        self._artifacts = ()
        self._recipes = ()
        self._populate_artifacts()
        self._populate_recipes()
        self.artifact_selected.emit(None)
        self.recipe_selected.emit(None)

    def _populate_artifacts(self) -> None:
        table = self._tables["data_manager.table.artifacts"]
        table.setRowCount(len(self._artifacts))
        for row, item in enumerate(self._artifacts):
            _set_row(
                table,
                row,
                (
                    item.artifact_id,
                    item.tool_key,
                    item.kind,
                    ", ".join(item.output_names),
                    str(item.row_count),
                    item.current_status,
                    "valid" if item.valid else f"invalid: {item.rejection_reason}",
                ),
            )

    def _populate_recipes(self) -> None:
        table = self._tables["data_manager.table.recipes"]
        table.setRowCount(len(self._recipes))
        for row, item in enumerate(self._recipes):
            _set_row(
                table,
                row,
                (
                    item.recipe_id,
                    item.tool_key,
                    item.kind,
                    ", ".join(item.output_names),
                    item.display_name,
                    "" if item.created_at_utc is None else item.created_at_utc.isoformat(),
                    "valid" if item.valid else f"invalid: {item.rejection_reason}",
                ),
            )

    def _sync_actions(self) -> None:
        if not self._buttons:
            return
        artifact = self.selected_artifact()
        recipe = self.selected_recipe()
        self._buttons["data_manager.button.refresh"].setEnabled(not self._busy)
        self._buttons["data_manager.button.select_dataset"].setEnabled(not self._busy)
        self._buttons["data_manager.button.preview_dataset"].setEnabled(
            not self._busy and self._selected_market is not None
        )
        for object_id in (
            "data_manager.button.preview_artifact",
            "data_manager.button.validate_artifact",
            "data_manager.button.delete_artifact",
        ):
            self._buttons[object_id].setEnabled(
                not self._busy and artifact is not None and artifact.valid
            )
        self._buttons["data_manager.button.delete_recipe"].setEnabled(
            not self._busy and recipe is not None and recipe.valid
        )
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(self._busy)
        target = self._selected_market is not None
        self._buttons["data_manager.button.creation.use_target"].setEnabled(
            not self._busy and target
        )
        for object_id in (
            "data_manager.button.creation.create_seed",
            "data_manager.button.creation.plan_base",
            "data_manager.button.creation.plan_batch",
        ):
            self._buttons[object_id].setEnabled(not self._busy and target)

    def _confirm_delete_artifact(self) -> None:
        artifact = self.selected_artifact()
        if artifact is None or not artifact.valid:
            return
        if QMessageBox.question(
            self,
            "Delete Artifact",
            f"Delete exactly artifact {artifact.artifact_id}?",
        ) == QMessageBox.StandardButton.Yes:
            self.delete_artifact_requested.emit()

    def _confirm_delete_recipe(self) -> None:
        recipe = self.selected_recipe()
        if recipe is None or not recipe.valid:
            return
        if QMessageBox.question(
            self,
            "Delete Recipe",
            f"Delete exactly unused recipe {recipe.recipe_id}?",
        ) == QMessageBox.StandardButton.Yes:
            self.delete_recipe_requested.emit()

    def _invoke_action(self, action_id: str, callback) -> None:
        if self._action_observer is not None:
            decision = self._action_observer.record_action(
                action_id, window_id=DATA_MANAGER_SUITE_WINDOW_ID
            )
            if not decision.allowed:
                return
        callback()

    def _selected_row(self, object_id: str) -> int | None:
        rows = self._tables[object_id].selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        limit = {
            "data_manager.table.artifacts": len(self._artifacts),
            "data_manager.table.recipes": len(self._recipes),
        }[object_id]
        return row if 0 <= row < limit else None

    def _set_selected_market_text(self, text: str) -> None:
        if self._selected_market_label is not None:
            self._selected_market_label.setText(text)

    def _set_selection_details(self, text: str) -> None:
        if self._selection_details is not None:
            self._selection_details.setText(text)


def _set_row(table: QTableWidget, row: int, values: tuple[str, ...]) -> None:
    from PySide6.QtWidgets import QTableWidgetItem

    for column, value in enumerate(values):
        table.setItem(row, column, QTableWidgetItem(value))
