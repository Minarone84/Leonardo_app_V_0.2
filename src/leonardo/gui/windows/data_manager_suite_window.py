"""Data Manager catalog and exact-object management window."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
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
)
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_SUITE_WINDOW_ID = "data_manager_suite.window"
_DATASET_COLUMNS = (
    "Exchange",
    "Market Type",
    "Symbol",
    "Timeframe",
    "Rows",
    "Range",
    "State",
    "Details",
)
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
        self._datasets = ()
        self._artifacts: tuple[DataManagerArtifactEntry, ...] = ()
        self._recipes: tuple[DataManagerRecipeEntry, ...] = ()
        self._selected_market: MarketId | None = None
        self._status_label: QLabel | None = None
        self._selected_market_label: QLabel | None = None
        self._selection_details: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._log_area: QTextEdit | None = None
        self._busy = False
        self._build_window()
        apply_theme_stylesheet(self, load_default_theme())
        self.load_empty_state()

    def button_for_id(self, button_id: str) -> QPushButton:
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
        self._set_selected_market_text("No accepted market selected")
        self._set_selection_details("Select an accepted dataset to inspect recipes and artifacts.")
        self.set_status("Scanning canonical persistence")
        self._sync_actions()

    def set_catalog(self, snapshot: DataManagerCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerCatalogSnapshot")
        previous = self._selected_market
        self._datasets = snapshot.datasets
        table = self._tables["data_manager.table.datasets"]
        table.blockSignals(True)
        table.setRowCount(len(self._datasets))
        for row, entry in enumerate(self._datasets):
            market = entry.market_id
            values = (
                "" if market is None else market.exchange,
                "" if market is None else market.market_type,
                "" if market is None else market.symbol,
                "" if market is None else market.timeframe,
                "" if entry.row_count is None else str(entry.row_count),
                _range_text(entry.first_timestamp_ms, entry.last_timestamp_ms),
                "accepted" if entry.accepted else "rejected",
                _dataset_details(entry),
            )
            _set_row(table, row, values)
        table.blockSignals(False)
        if previous is not None:
            self.select_market(previous, emit_selection=False)
        self._sync_actions()

    def set_market_snapshot(self, snapshot: DataManagerMarketSnapshot | None) -> None:
        if snapshot is not None and not isinstance(snapshot, DataManagerMarketSnapshot):
            raise TypeError("snapshot must be a DataManagerMarketSnapshot or None")
        self._clear_object_selection()
        self._selected_market = None if snapshot is None else snapshot.market_id
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
        for row, entry in enumerate(self._datasets):
            if entry.accepted and entry.market_id == market_id:
                table = self._tables["data_manager.table.datasets"]
                blocker = None if emit_selection else QSignalBlocker(table)
                table.selectRow(row)
                del blocker
                self._selected_market = market_id
                self._set_selected_market_text(market_id.as_key())
                self._set_selection_details("Loading recipes and artifacts...")
                self._sync_actions()
                return True
        return False

    def clear_selected_market(self, details: str) -> None:
        if not isinstance(details, str):
            raise TypeError("details must be a string")
        table = self._tables["data_manager.table.datasets"]
        blocker = QSignalBlocker(table)
        table.clearSelection()
        del blocker
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

    def set_busy(self, busy: bool, operation: str = "") -> None:
        self._busy = bool(busy)
        for table in self._tables.values():
            table.setEnabled(not self._busy)
        if self._busy:
            self.set_status(f"Operation in progress: {operation}")
        self._sync_actions()

    def set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def append_status(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)

    def set_progress(self, current: int | None, total: int | None) -> None:
        if self._progress is None:
            return
        if total is None or total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(total, current or 0)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
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
        root.addWidget(self._build_catalogs(), 1)
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
            self._buttons[object_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return panel

    def _build_catalogs(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        datasets = self._table_panel(
            splitter, "Datasets", "data_manager.table.datasets", _DATASET_COLUMNS
        )
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
        splitter.addWidget(datasets)
        splitter.addWidget(objects)
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
        if object_id == "data_manager.table.datasets":
            table.itemSelectionChanged.connect(self._on_market_selection)
        elif object_id == "data_manager.table.artifacts":
            table.itemSelectionChanged.connect(self._on_artifact_selection)
        else:
            table.itemSelectionChanged.connect(self._on_recipe_selection)
        self._tables[object_id] = table
        layout.addWidget(table)
        return panel

    def _build_status(self) -> QWidget:
        panel = QGroupBox("Activity", self)
        layout = QVBoxLayout(panel)
        progress = QProgressBar(panel)
        progress.setRange(0, 1)
        apply_identity(
            progress, "data_manager.progress.operation", object_type="progress_bar"
        )
        log = QTextEdit(panel)
        log.setReadOnly(True)
        log.setMaximumHeight(100)
        apply_identity(log, "data_manager.log.status", object_type="log")
        self._progress = progress
        self._log_area = log
        layout.addWidget(progress)
        layout.addWidget(log)
        return panel

    def _on_market_selection(self) -> None:
        index = self._selected_row("data_manager.table.datasets")
        self._clear_object_selection()
        if index is None:
            self.market_selected.emit(None)
            return
        entry = self._datasets[index]
        if not entry.accepted:
            self._selected_market = None
            self._set_selected_market_text("Rejected dataset")
            self._set_selection_details(entry.rejection_reason)
            self.market_selected.emit(None)
            self._sync_actions()
            return
        self._selected_market = entry.market_id
        self._set_selected_market_text(entry.market_id.as_key())
        self._set_selection_details("Loading recipes and artifacts...")
        self.market_selected.emit(entry.market_id)
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
            "data_manager.table.datasets": len(self._datasets),
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


def _range_text(first: int | None, last: int | None) -> str:
    return "" if first is None or last is None else f"{first} - {last}"


def _dataset_details(entry) -> str:
    if not entry.accepted:
        return f"{entry.rejection_code}: {entry.rejection_reason}"
    details = [value for value in (entry.persistence_status, entry.validation_status) if value]
    details.extend(entry.warnings)
    return " | ".join(details)
