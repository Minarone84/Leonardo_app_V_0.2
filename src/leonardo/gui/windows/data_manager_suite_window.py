"""Data Manager catalog and exact-object management window."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

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
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionRevisionV1,
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerManagedArtifactEntry,
    DataManagerPortableRecipeEntry,
    DataManagerRecipeEntry,
    DataManagerRecipeCollectionEntry,
    DataManagerProductCatalogSnapshot,
    DataManagerStudyEnvironmentInspection,
)
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactCatalog
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.data_manager import (
    DataManagerCatalogWorkspace,
    DataManagerCreationWorkspace,
    DataManagerOperationSurface,
    DataManagerUpdateWorkspace,
)
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    data_manager_dataset_details,
    data_manager_dataset_row,
    resize_data_manager_table,
)
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.data_manager_dataset_selector_dialog import (
    DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
    DataManagerDatasetSelectorDialog,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table
from leonardo.financial_tools import CONSTRUCT_SPECS

if TYPE_CHECKING:
    from leonardo.gui.windows.data_manager_artifact_creation_dialog import (
        DataManagerArtifactCreationDialog,
    )
    from leonardo.gui.windows.data_manager_construct_batch_dialog import (
        DataManagerConstructBatchDialog,
    )
    from leonardo.gui.windows.data_manager_recipe_derivation_dialog import (
        DataManagerRecipeDerivationDialog,
    )
    from leonardo.gui.windows.data_manager_recipe_collection_dialog import (
        DataManagerRecipeCollectionDialog,
    )
    from leonardo.gui.windows.data_manager_artifact_collection_dialog import (
        DataManagerArtifactCollectionDialog,
    )


DATA_MANAGER_SUITE_WINDOW_ID = "data_manager_suite.window"

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
    create_artifact_requested = Signal()
    calculate_artifact_requested = Signal(object)
    batch_constructs_requested = Signal()
    batch_construct_preview_requested = Signal(object)
    batch_construct_execute_requested = Signal()
    derive_recipes_requested = Signal(object)
    recipe_derivation_preview_requested = Signal(str, object)
    recipe_derivation_create_requested = Signal(str, object, bool, str, str)
    catalog_delete_recipe_requested = Signal(object)
    catalog_delete_artifact_requested = Signal(object)
    catalog_delete_recipe_collection_requested = Signal(object)
    catalog_delete_artifact_collection_requested = Signal(object)
    create_recipe_collection_requested = Signal()
    edit_recipe_collection_requested = Signal(object)
    create_artifact_collection_requested = Signal()
    edit_artifact_collection_requested = Signal(object)
    recipe_collection_preview_requested = Signal(object)
    recipe_collection_create_requested = Signal(str, str, object)
    recipe_collection_update_requested = Signal(str, str, str, object, str)
    artifact_collection_preview_requested = Signal(object, object)
    artifact_collection_create_requested = Signal(object, str, str, object)
    artifact_collection_edit_requested = Signal(
        str, object, str, str, object, object, str
    )

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
        self._selected_dataset_entry: DataManagerDatasetEntry | None = None
        self._selected_dataset_table: QTableWidget | None = None
        self._progress: QProgressBar | None = None
        self._creation_controls: dict[str, QWidget] = {}
        self._creation_stage_list: QListWidget | None = None
        self._creation_stack: QStackedWidget | None = None
        self._creation_summary: QLabel | None = None
        self._cancel_button: QPushButton | None = None
        self._catalog_workspace: DataManagerCatalogWorkspace | None = None
        self._dataset_selector_dialog: DataManagerDatasetSelectorDialog | None = None
        self._artifact_creation_dialog: DataManagerArtifactCreationDialog | None = None
        self._construct_batch_dialog: DataManagerConstructBatchDialog | None = None
        self._recipe_derivation_dialog: (
            DataManagerRecipeDerivationDialog | None
        ) = None
        self._recipe_collection_dialog: (
            DataManagerRecipeCollectionDialog | None
        ) = None
        self._artifact_collection_dialog: (
            DataManagerArtifactCollectionDialog | None
        ) = None
        self._product_catalogs: DataManagerProductCatalogSnapshot | None = None
        self._existing_recipe_ids: tuple[str, ...] = ()
        self._creation_workspace: DataManagerCreationWorkspace | None = None
        self._update_workspace: DataManagerUpdateWorkspace | None = None
        self._operation_surface: DataManagerOperationSurface | None = None
        self._workspace_tabs: QTabWidget | None = None
        self._body_panel: QWidget | None = None
        self._upper_panel: QWidget | None = None
        self._catalog_details_panel: QWidget | None = None
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
        return (
            ""
            if self._operation_surface is None
            else self._operation_surface.status_text()
        )

    def status_log_text(self) -> str:
        return (
            ""
            if self._operation_surface is None
            else self._operation_surface.notes_text()
        )

    def selected_market_id(self) -> MarketId | None:
        return self._selected_market

    def selected_artifact(self) -> DataManagerArtifactEntry | None:
        if "data_manager.table.artifacts" not in self._tables:
            return None
        index = self._selected_row("data_manager.table.artifacts")
        return None if index is None else self._artifacts[index]

    def selected_recipe(self) -> DataManagerRecipeEntry | None:
        if "data_manager.table.recipes" not in self._tables:
            return None
        index = self._selected_row("data_manager.table.recipes")
        return None if index is None else self._recipes[index]

    def load_empty_state(self) -> None:
        self._datasets = ()
        self._artifacts = ()
        self._recipes = ()
        self._selected_market = None
        self._selected_dataset_entry = None
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_selected_market(None)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_browsing_market(None)
        self._invalidate_artifact_creation_target()
        for table in self._tables.values():
            table.setRowCount(0)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_catalog(DataManagerCatalogSnapshot(()))
            self._dataset_selector_dialog.set_current_market(None)
        self._populate_selected_dataset()
        self._set_selection_details("Select an accepted dataset to preview data or create a Database.")
        self.set_status("Scanning canonical persistence")
        self._sync_actions()

    def set_catalog(self, snapshot: DataManagerCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerCatalogSnapshot")
        self._datasets = snapshot.datasets
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_catalog(snapshot)
        self._refresh_selected_dataset_from_catalog()
        self._sync_actions()

    def set_market_snapshot(self, snapshot: DataManagerMarketSnapshot | None) -> None:
        if snapshot is not None and not isinstance(snapshot, DataManagerMarketSnapshot):
            raise TypeError("snapshot must be a DataManagerMarketSnapshot or None")
        next_market = None if snapshot is None else snapshot.market_id
        if next_market != self._selected_market:
            self._invalidate_artifact_creation_target()
        self._clear_object_selection()
        self._selected_market = None if snapshot is None else snapshot.market_id
        self._selected_dataset_entry = None if snapshot is None else snapshot.dataset
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_selected_market(self._selected_market)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_current_market(self._selected_market)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_browsing_market(
                self._selected_market
            )
        self._artifacts = () if snapshot is None else snapshot.artifacts
        self._recipes = () if snapshot is None else snapshot.recipes
        self._populate_artifacts()
        self._populate_recipes()
        self._populate_selected_dataset()
        if snapshot is None:
            self._set_selection_details(
                "Select an accepted dataset to preview data or create a Database."
            )
        else:
            self._set_selection_details(
                "Accepted dataset ready for preview and Database workflows."
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
        if market_id != self._selected_market:
            self._invalidate_artifact_creation_target()
        self._selected_market = market_id
        self._selected_dataset_entry = accepted
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_selected_market(market_id)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_browsing_market(market_id)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_current_market(market_id)
        self._populate_selected_dataset()
        self._set_selection_details("Loading accepted dataset...")
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
        self._invalidate_artifact_creation_target()
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
                table = self._tables.get("data_manager.table.artifacts")
                if table is not None:
                    table.selectRow(index)
                return

    def set_busy(
        self, busy: bool, operation: str = "", *, preserve_operation: bool = False
    ) -> None:
        self._busy = bool(busy)
        for table in self._tables.values():
            table.setEnabled(not self._busy)
        if self._catalog_workspace is not None:
            self._catalog_workspace.setEnabled(not self._busy)
            self._catalog_workspace.set_collection_actions_enabled(not self._busy)
        if self._dataset_selector_dialog is not None:
            self._dataset_selector_dialog.set_busy(self._busy)
        if self._artifact_creation_dialog is not None:
            self._artifact_creation_dialog.set_busy(self._busy)
        if self._construct_batch_dialog is not None:
            self._construct_batch_dialog.set_busy(self._busy)
        if self._recipe_derivation_dialog is not None:
            self._recipe_derivation_dialog.set_busy(self._busy)
        if self._recipe_collection_dialog is not None:
            self._recipe_collection_dialog.set_busy(self._busy)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_busy(self._busy)
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
        if self._operation_surface is not None:
            self._operation_surface.set_status(message)

    def append_status(self, message: str) -> None:
        if self._operation_surface is not None:
            self._operation_surface.append(message)

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
        self._product_catalogs = snapshot
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_selected_market(self._selected_market)
            self._catalog_workspace.set_snapshot(snapshot)
            self._catalog_workspace.set_collection_actions_enabled(not self._busy)
        self._existing_recipe_ids = tuple(
            item.recipe_id
            for item in snapshot.portable_recipes.recipes
            if item.valid
        )
        if self._recipe_derivation_dialog is not None:
            self._recipe_derivation_dialog.set_existing_recipe_ids(
                self._existing_recipe_ids
            )
        if self._recipe_collection_dialog is not None:
            self._recipe_collection_dialog.set_catalog(snapshot)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_catalog(
                snapshot,
                browsing_market_id=self._selected_market,
            )
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
        if self._artifact_creation_dialog is not None:
            self._artifact_creation_dialog.close()
        if self._construct_batch_dialog is not None:
            self._construct_batch_dialog.close()
        if self._recipe_derivation_dialog is not None:
            self._recipe_derivation_dialog.close()
        if self._recipe_collection_dialog is not None:
            self._recipe_collection_dialog.close()
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.close()
        self.closing.emit()
        super().closeEvent(event)

    def _build_window(self) -> None:
        self.setWindowTitle("Data Manager Suite")
        self.setObjectName("data_manager_suite_window")
        self.setProperty("object_id", DATA_MANAGER_SUITE_WINDOW_ID)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1280, 820)
        root = QVBoxLayout(self)
        root.addWidget(self._build_top_strip())

        body = QWidget(self)
        apply_identity(body, "data_manager.panel.body", object_type="panel")
        body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        upper = QWidget(body)
        apply_identity(upper, "data_manager.panel.upper", object_type="panel")
        upper.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        upper_layout = QHBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget(upper)
        apply_identity(tabs, "data_manager.tabs.workspace", object_type="tab_widget")
        tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        tabs.addTab(self._build_catalogs(), "Catalogs")
        tabs.addTab(self._build_creation_workflow(), "Create Database")
        tabs.addTab(self._build_update_workflow(), "Update & Reconcile")

        operation = self._build_status()
        operation.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        upper_layout.addWidget(tabs)
        upper_layout.addWidget(operation)
        upper_layout.setStretch(0, 3)
        upper_layout.setStretch(1, 1)

        details = QWidget(body)
        apply_identity(
            details,
            "data_manager.panel.catalog_details",
            object_type="panel",
        )
        details.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        details_layout = QHBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.addWidget(self._catalog_workspace.inspector_panel())
        details_layout.addWidget(self._catalog_workspace.history_panel())
        details_layout.setStretch(0, 1)
        details_layout.setStretch(1, 1)

        body_layout.addWidget(upper)
        body_layout.addWidget(details)
        body_layout.setStretch(0, 7)
        body_layout.setStretch(1, 3)
        root.addWidget(body, 1)

        self._workspace_tabs = tabs
        self._body_panel = body
        self._upper_panel = upper
        self._catalog_details_panel = details
        tabs.currentChanged.connect(self._on_workspace_tab_changed)
        self._on_workspace_tab_changed(tabs.currentIndex())

    def _build_top_strip(self) -> QWidget:
        strip = QWidget(self)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        actions = self._build_toolbar()
        selected_dataset = self._build_selected_dataset()
        layout.addWidget(actions)
        layout.addWidget(selected_dataset, 1)
        layout.setStretch(0, 0)
        layout.setStretch(1, 1)
        return strip

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

    def _build_selected_dataset(self) -> QWidget:
        panel = QGroupBox("Selected Dataset", self)
        apply_identity(
            panel,
            "data_manager.selected_dataset.group",
            object_type="group_box",
        )
        layout = QVBoxLayout(panel)
        table = configure_table(
            QTableWidget(panel),
            object_id="data_manager.selected_dataset.table",
            columns=DATA_MANAGER_DATASET_COLUMNS,
            labels=DATA_MANAGER_DATASET_COLUMNS,
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._selected_dataset_table = table
        layout.addWidget(table)
        self._populate_selected_dataset()
        return panel

    def _build_catalogs(self) -> QWidget:
        workspace = DataManagerCatalogWorkspace(self)
        workspace.row_selected.connect(self.catalog_row_selected.emit)
        workspace.history_selected.connect(self.catalog_history_selected.emit)
        workspace.create_artifact_requested.connect(
            self.create_artifact_requested.emit
        )
        workspace.batch_constructs_requested.connect(
            self.batch_constructs_requested.emit
        )
        workspace.derive_recipes_requested.connect(
            self.derive_recipes_requested.emit
        )
        workspace.create_recipe_collection_requested.connect(
            self.create_recipe_collection_requested.emit
        )
        workspace.edit_recipe_collection_requested.connect(
            self.edit_recipe_collection_requested.emit
        )
        workspace.create_artifact_collection_requested.connect(
            self.create_artifact_collection_requested.emit
        )
        workspace.edit_artifact_collection_requested.connect(
            self.edit_artifact_collection_requested.emit
        )
        workspace.delete_recipe_requested.connect(
            self._confirm_catalog_recipe_deletion
        )
        workspace.delete_artifact_requested.connect(
            self._confirm_catalog_artifact_deletion
        )
        workspace.delete_recipe_collection_requested.connect(
            self._confirm_catalog_recipe_collection_deletion
        )
        workspace.delete_artifact_collection_requested.connect(
            self._confirm_catalog_artifact_collection_deletion
        )
        workspace.family_changed.connect(lambda _family: self._sync_actions())
        self._catalog_workspace = workspace
        return workspace

    def _on_workspace_tab_changed(self, index: int) -> None:
        if self._catalog_details_panel is not None:
            self._catalog_details_panel.setVisible(index == 0)

    def _build_status(self) -> QWidget:
        surface = DataManagerOperationSurface(self)
        surface.cancel_requested.connect(self.creation_cancel_requested.emit)
        self._operation_surface = surface
        self._progress = surface.progress
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

    def artifact_creation_dialog(self) -> DataManagerArtifactCreationDialog | None:
        return self._artifact_creation_dialog

    def construct_batch_dialog(self) -> DataManagerConstructBatchDialog | None:
        return self._construct_batch_dialog

    def recipe_derivation_dialog(
        self,
    ) -> DataManagerRecipeDerivationDialog | None:
        return self._recipe_derivation_dialog

    def recipe_collection_dialog(
        self,
    ) -> DataManagerRecipeCollectionDialog | None:
        return self._recipe_collection_dialog

    def artifact_collection_dialog(
        self,
    ) -> DataManagerArtifactCollectionDialog | None:
        return self._artifact_collection_dialog

    def show_recipe_collection_dialog(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        inspection: object | None = None,
    ) -> None:
        from leonardo.data_manager import DataManagerRecipeCollectionInspection
        from leonardo.gui.windows.data_manager_recipe_collection_dialog import (
            DATA_MANAGER_RECIPE_COLLECTION_WINDOW_ID,
            DataManagerRecipeCollectionDialog,
        )

        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        if inspection is not None and not isinstance(
            inspection, DataManagerRecipeCollectionInspection
        ):
            raise TypeError(
                "inspection must be a DataManagerRecipeCollectionInspection or None"
            )
        dialog = self._recipe_collection_dialog
        created = dialog is None
        if dialog is None:
            dialog = DataManagerRecipeCollectionDialog(snapshot, self)
            dialog.preview_requested.connect(
                self.recipe_collection_preview_requested.emit
            )
            dialog.create_requested.connect(
                self.recipe_collection_create_requested.emit
            )
            dialog.update_requested.connect(
                self.recipe_collection_update_requested.emit
            )
            dialog.closing.connect(self._release_recipe_collection_dialog)
            self._recipe_collection_dialog = dialog
        if inspection is None:
            dialog.configure_create(snapshot)
        else:
            dialog.configure_edit(inspection, snapshot)
        if created and self._floating_window_tracker is not None:
            self._floating_window_tracker(
                dialog,
                DATA_MANAGER_RECIPE_COLLECTION_WINDOW_ID,
                "Recipe Collection",
                "dialog",
            )
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_artifact_collection_dialog(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        revision: ArtifactCollectionRevisionV1 | None = None,
    ) -> None:
        from leonardo.gui.windows.data_manager_artifact_collection_dialog import (
            DATA_MANAGER_ARTIFACT_COLLECTION_WINDOW_ID,
            DataManagerArtifactCollectionDialog,
        )

        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        if revision is not None and not isinstance(
            revision, ArtifactCollectionRevisionV1
        ):
            raise TypeError(
                "revision must be an ArtifactCollectionRevisionV1 or None"
            )
        dialog = self._artifact_collection_dialog
        created = dialog is None
        if dialog is None:
            dialog = DataManagerArtifactCollectionDialog(
                snapshot,
                browsing_market_id=self._selected_market,
                parent=self,
            )
            dialog.preview_requested.connect(
                self.artifact_collection_preview_requested.emit
            )
            dialog.create_requested.connect(
                self.artifact_collection_create_requested.emit
            )
            dialog.edit_requested.connect(
                self.artifact_collection_edit_requested.emit
            )
            dialog.closing.connect(self._release_artifact_collection_dialog)
            self._artifact_collection_dialog = dialog
        if revision is None:
            dialog.configure_create(
                snapshot,
                browsing_market_id=self._selected_market,
            )
        else:
            dialog.configure_edit(
                revision,
                snapshot,
                browsing_market_id=self._selected_market,
            )
        if created and self._floating_window_tracker is not None:
            self._floating_window_tracker(
                dialog,
                DATA_MANAGER_ARTIFACT_COLLECTION_WINDOW_ID,
                "Artifact Collection",
                "dialog",
            )
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _release_recipe_collection_dialog(self) -> None:
        self._recipe_collection_dialog = None

    def _release_artifact_collection_dialog(self) -> None:
        self._artifact_collection_dialog = None

    def show_recipe_derivation_dialog(
        self, inspection: DataManagerStudyEnvironmentInspection
    ) -> None:
        from leonardo.gui.windows.data_manager_recipe_derivation_dialog import (
            DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID,
            DataManagerRecipeDerivationDialog,
        )

        if not isinstance(inspection, DataManagerStudyEnvironmentInspection):
            raise TypeError(
                "inspection must be a DataManagerStudyEnvironmentInspection"
            )
        dialog = self._recipe_derivation_dialog
        if dialog is None:
            dialog = DataManagerRecipeDerivationDialog(
                inspection,
                existing_recipe_ids=self._existing_recipe_ids,
                parent=self,
            )
            dialog.preview_requested.connect(
                self.recipe_derivation_preview_requested.emit
            )
            dialog.create_requested.connect(
                self.recipe_derivation_create_requested.emit
            )
            dialog.closing.connect(self._release_recipe_derivation_dialog)
            self._recipe_derivation_dialog = dialog
            if self._floating_window_tracker is not None:
                self._floating_window_tracker(
                    dialog,
                    DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID,
                    dialog.windowTitle(),
                    "dialog",
                )
        else:
            dialog.set_inspection(
                inspection,
                existing_recipe_ids=self._existing_recipe_ids,
            )
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _release_recipe_derivation_dialog(self) -> None:
        self._recipe_derivation_dialog = None

    def show_artifact_creation_dialog(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        *,
        preserve_configuration: bool = False,
    ) -> None:
        from leonardo.gui.windows.data_manager_artifact_creation_dialog import (
            DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID,
            DataManagerArtifactCreationDialog,
        )

        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        dialog = self._artifact_creation_dialog
        if dialog is None:
            dialog = DataManagerArtifactCreationDialog(catalog, self)
            dialog.calculate_requested.connect(
                self.calculate_artifact_requested.emit
            )
            self._artifact_creation_dialog = dialog
            if self._floating_window_tracker is not None:
                self._floating_window_tracker(
                    dialog,
                    DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID,
                    dialog.windowTitle(),
                    "dialog",
                )
        else:
            dialog.set_catalog(
                catalog,
                preserve_configuration=preserve_configuration,
            )
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_construct_batch_dialog(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        *,
        collections: tuple[tuple[str, str], ...] = (),
        preserve_configuration: bool = False,
    ) -> None:
        from leonardo.gui.windows.data_manager_construct_batch_dialog import (
            DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID,
            DataManagerConstructBatchDialog,
        )

        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        dialog = self._construct_batch_dialog
        if dialog is None:
            dialog = DataManagerConstructBatchDialog(
                catalog, collections=collections, parent=self
            )
            dialog.preview_requested.connect(
                self.batch_construct_preview_requested.emit
            )
            dialog.execute_requested.connect(
                self.batch_construct_execute_requested.emit
            )
            self._construct_batch_dialog = dialog
            if self._floating_window_tracker is not None:
                self._floating_window_tracker(
                    dialog,
                    DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID,
                    dialog.windowTitle(),
                    "dialog",
                )
        else:
            dialog.set_catalog(
                catalog,
                collections=collections,
                preserve_configuration=preserve_configuration,
            )
        dialog.set_busy(self._busy)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
        if market_id != self._selected_market:
            self._invalidate_artifact_creation_target()
        self._selected_market = market_id
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_selected_market(market_id)
        if self._artifact_collection_dialog is not None:
            self._artifact_collection_dialog.set_browsing_market(market_id)
        self._selected_dataset_entry = next(
            (
                entry
                for entry in self._datasets
                if entry.accepted and entry.market_id == market_id
            ),
            None,
        )
        self._populate_selected_dataset()
        self._set_selection_details("Loading accepted dataset...")
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
            table = self._tables.get(object_id)
            if table is not None:
                table.clearSelection()
        self._artifacts = ()
        self._recipes = ()
        self._populate_artifacts()
        self._populate_recipes()
        self.artifact_selected.emit(None)
        self.recipe_selected.emit(None)

    def _populate_artifacts(self) -> None:
        table = self._tables.get("data_manager.table.artifacts")
        if table is None:
            return
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
        table = self._tables.get("data_manager.table.recipes")
        if table is None:
            return
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
        self._buttons["data_manager.button.refresh"].setEnabled(not self._busy)
        self._buttons["data_manager.button.select_dataset"].setEnabled(not self._busy)
        self._buttons["data_manager.button.preview_dataset"].setEnabled(
            not self._busy and self._selected_market is not None
        )
        if self._catalog_workspace is not None:
            self._catalog_workspace.set_create_artifact_enabled(
                not self._busy and self._selected_market is not None
            )
            self._catalog_workspace.set_derive_recipes_enabled(not self._busy)
            self._catalog_workspace.set_deletion_actions_enabled(not self._busy)
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

    def _invalidate_artifact_creation_target(self) -> None:
        if self._artifact_creation_dialog is not None:
            self._artifact_creation_dialog.invalidate_target()
        if self._construct_batch_dialog is not None:
            self._construct_batch_dialog.invalidate_target()

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

    def _confirm_catalog_recipe_deletion(self, value: object) -> None:
        if not isinstance(value, DataManagerPortableRecipeEntry) or not value.valid:
            return
        message = (
            f"Recipe ID: {value.recipe_id}\n"
            f"Tool: {value.tool_key}\n\n"
            "This deletes the global Recipe and its provenance.\n"
            "No dependent object will be deleted.\n"
            "Deletion is refused if the Recipe is still referenced."
        )
        if QMessageBox.question(
            self, "Delete Recipe", message
        ) == QMessageBox.StandardButton.Yes:
            self.catalog_delete_recipe_requested.emit(value)

    def _confirm_catalog_recipe_collection_deletion(self, value: object) -> None:
        if not isinstance(value, DataManagerRecipeCollectionEntry) or not value.valid:
            return
        message = (
            f"Collection name: {value.display_name}\n"
            f"Collection ID: {value.collection_id}\n\n"
            "This deletes the Collection and all of its revisions.\n"
            "Member Recipes are not deleted.\n"
            "Deletion is refused if an Artifact Collection references it."
        )
        if QMessageBox.question(
            self, "Delete Recipe Collection", message
        ) == QMessageBox.StandardButton.Yes:
            self.catalog_delete_recipe_collection_requested.emit(value)

    def _confirm_catalog_artifact_deletion(self, value: object) -> None:
        if not isinstance(value, DataManagerManagedArtifactEntry) or not value.valid:
            return
        message = (
            f"Logical Artifact ID: {value.logical_artifact_id}\n"
            f"Tool: {value.tool_key}\n"
            f"Market: {value.market_id.as_key()}\n\n"
            "This deletes the complete managed Artifact and all of its versions.\n"
            "Its Recipe and other Artifacts are not deleted.\n"
            "Deletion is refused if any surviving object references it."
        )
        if QMessageBox.question(
            self, "Delete Artifact", message
        ) == QMessageBox.StandardButton.Yes:
            self.catalog_delete_artifact_requested.emit(value)

    def _confirm_catalog_artifact_collection_deletion(self, value: object) -> None:
        if (
            not isinstance(value, ArtifactCollectionRevisionV1)
            or value.validation_state != "valid"
        ):
            return
        message = (
            f"Collection name: {value.display_name}\n"
            f"Collection ID: {value.collection_id}\n"
            f"Market: {value.market_id.as_key()}\n\n"
            "This deletes the Collection and all revisions.\n"
            "Member Artifacts are not deleted.\n"
            "Deletion is refused if a Database revision references it."
        )
        if QMessageBox.question(
            self, "Delete Artifact Collection", message
        ) == QMessageBox.StandardButton.Yes:
            self.catalog_delete_artifact_collection_requested.emit(value)

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

    def _set_selection_details(self, text: str) -> None:
        if self._operation_surface is not None:
            self._operation_surface.set_context(text)

    def _refresh_selected_dataset_from_catalog(self) -> None:
        self._selected_dataset_entry = next(
            (
                entry
                for entry in self._datasets
                if entry.accepted and entry.market_id == self._selected_market
            ),
            None,
        )
        self._populate_selected_dataset()

    def _populate_selected_dataset(self) -> None:
        table = self._selected_dataset_table
        if table is None:
            return
        entry = self._selected_dataset_entry
        blocker = QSignalBlocker(table)
        table.setRowCount(0 if entry is None else 1)
        if entry is not None:
            details = data_manager_dataset_details(entry)
            for column, value in enumerate(data_manager_dataset_row(entry)):
                item = QTableWidgetItem(value)
                item.setToolTip(details)
                table.setItem(0, column, item)
        del blocker
        resize_data_manager_table(table)
        row_height = (
            table.rowHeight(0)
            if table.rowCount()
            else table.verticalHeader().defaultSectionSize()
        )
        table.setFixedHeight(
            table.horizontalHeader().height()
            + row_height
            + table.horizontalScrollBar().sizeHint().height()
            + (table.frameWidth() * 2)
            + 4
        )


def _set_row(table: QTableWidget, row: int, values: tuple[str, ...]) -> None:
    for column, value in enumerate(values):
        table.setItem(row, column, QTableWidgetItem(value))
