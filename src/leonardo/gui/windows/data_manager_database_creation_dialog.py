"""Seed-only Database creation form and reviewed-plan presentation."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import (
    DataManagerProductCatalogSnapshot,
    DatabaseSeedV1,
    SeedOnlyDatabaseCreationPlan,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DATABASE_CREATION_WINDOW_ID = "data_manager.database_creation.window"
_OBJECT_PREFIX = "data_manager.database_creation"
_SEED_COLUMNS = (
    "Select", "Name", "Exchange", "Market Type", "Asset", "Timeframe", "Columns",
    "Range Start", "Range End",
)


class DataManagerDatabaseCreationDialog(QDialog):
    """Collect Seed-only Database intent and display canonical readiness."""

    preview_requested = Signal(object)
    create_requested = Signal(object)
    closing = Signal()

    def __init__(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        selected_seed: DatabaseSeedV1 | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        super().__init__(parent)
        self._snapshot = snapshot
        self._seeds: tuple[DatabaseSeedV1, ...] = ()
        self._plan: SeedOnlyDatabaseCreationPlan | None = None
        self._busy = False
        self._checked_seed_ids: set[str] = set()
        self._seed_checks: list[QCheckBox] = []
        self._populating = False
        apply_identity(
            self, DATA_MANAGER_DATABASE_CREATION_WINDOW_ID, object_type="window"
        )
        self.setWindowTitle("Create Database")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        seed_group = QGroupBox("Database Seed", self)
        seed_layout = QVBoxLayout(seed_group)
        seed_layout.setContentsMargins(12, 24, 12, 12)
        seed_layout.setSpacing(8)
        self.seed_table = configure_table(
            QTableWidget(seed_group),
            object_id=f"{_OBJECT_PREFIX}.input.seed",
            columns=_SEED_COLUMNS,
            labels=_SEED_COLUMNS,
        )
        self.seed_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.seed_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        seed_layout.addWidget(self.seed_table)
        root.addWidget(seed_group)

        metadata = QGroupBox("Database metadata", self)
        metadata_layout = QFormLayout(metadata)
        metadata_layout.setContentsMargins(12, 24, 12, 12)
        metadata_layout.setVerticalSpacing(8)
        self.name_edit = QLineEdit(metadata)
        self.description_edit = QLineEdit(metadata)
        for widget, suffix in (
            (self.name_edit, "name"),
            (self.description_edit, "description"),
        ):
            apply_identity(
                widget,
                f"{_OBJECT_PREFIX}.input.{suffix}",
                object_type="line_edit",
            )
        metadata_layout.addRow("Name", self.name_edit)
        metadata_layout.addRow("Description", self.description_edit)
        root.addWidget(metadata)

        preview = QGroupBox("Readiness Preview", self)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 24, 12, 12)
        preview_layout.setSpacing(8)
        self.preview_table = configure_table(
            QTableWidget(preview),
            object_id=f"{_OBJECT_PREFIX}.table.preview",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        preview_layout.addWidget(self.preview_table, 1)
        root.addWidget(preview, 1)

        self.result_label = QLabel("Select a Seed and preview.", self)
        self.result_label.setWordWrap(True)
        apply_identity(
            self.result_label,
            f"{_OBJECT_PREFIX}.label.result",
            object_type="label",
        )
        root.addWidget(self.result_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = self._button("Preview", "preview")
        self.create_button = self._button("Create Database", "create")
        self.close_button = self._button("Close", "close")
        actions.addWidget(self.preview_button)
        actions.addWidget(self.create_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.name_edit.textChanged.connect(self._form_changed)
        self.description_edit.textChanged.connect(self._form_changed)
        self.preview_button.clicked.connect(self._emit_preview)
        self.create_button.clicked.connect(self._emit_create)
        self.close_button.clicked.connect(self.close)
        self.set_catalog(snapshot, selected_seed=selected_seed)
        apply_initial_window_size(
            self, parent=parent, width_fraction=0.50, height_fraction=0.60
        )

    @property
    def reviewed_plan(self) -> SeedOnlyDatabaseCreationPlan | None:
        return self._plan

    @property
    def context_key(self) -> tuple[object, ...]:
        return tuple(seed.seed_id for seed in self._seeds)

    def selected_seed(self) -> DatabaseSeedV1 | None:
        if len(self._checked_seed_ids) != 1:
            return None
        selected_seed_id = next(iter(self._checked_seed_ids))
        return next(
            (
                seed
                for seed in self._seeds
                if seed.seed_id == selected_seed_id
            ),
            None,
        )

    def set_catalog(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        selected_seed: DatabaseSeedV1 | None = None,
    ) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        current_ids = set(self._checked_seed_ids)
        self._snapshot = snapshot
        self._seeds = snapshot.database_seeds
        available_ids = {seed.seed_id for seed in self._seeds}
        self._checked_seed_ids = (
            {selected_seed.seed_id}
            if selected_seed is not None
            else current_ids & available_ids
        )
        self._seed_checks = []
        self._populating = True
        self.seed_table.blockSignals(True)
        self.seed_table.setRowCount(len(self._seeds))
        for row, seed in enumerate(self._seeds):
            market = seed.market_id
            values = (
                seed.display_name,
                market.exchange,
                market.market_type,
                market.symbol,
                market.timeframe,
                ", ".join(seed.selected_ohlcv_columns),
                format_utc_timestamp_ms(seed.selected_range_start_ms),
                format_utc_timestamp_ms(seed.selected_range_end_ms),
            )
            checkbox = QCheckBox(self.seed_table)
            checkbox.setChecked(seed.seed_id in self._checked_seed_ids)
            checkbox.setStyleSheet(
                "QCheckBox::indicator { width: 16px; height: 16px; }"
                "QCheckBox::indicator:unchecked {"
                " border: 1px solid #8C98A8; background: #20252D; }"
                "QCheckBox::indicator:checked {"
                " border: 1px solid #D4D9E1; background: #7C8796; }"
            )
            checkbox.stateChanged.connect(
                lambda state, identity=seed.seed_id: self._seed_toggled(
                    identity, state
                )
            )
            self._seed_checks.append(checkbox)
            self.seed_table.setCellWidget(row, 0, checkbox)
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setData(Qt.ItemDataRole.UserRole, seed.seed_id)
                self.seed_table.setItem(row, column, item)
        self.seed_table.blockSignals(False)
        self._populating = False
        resize_data_manager_table(self.seed_table)
        self.invalidate_preview("Seed context changed; preview again.")

    def _seed_toggled(self, seed_id: str, state: int) -> None:
        if self._populating:
            return
        checked = state == Qt.CheckState.Checked.value
        if checked:
            self._checked_seed_ids.add(seed_id)
        else:
            self._checked_seed_ids.discard(seed_id)
        self._form_changed()

    def form_values(self) -> dict[str, object]:
        seed = self.selected_seed()
        return {
            "seed_id": None if seed is None else seed.seed_id,
            "display_name": self.name_edit.text(),
            "description": self.description_edit.text(),
        }

    def set_plan(self, plan: SeedOnlyDatabaseCreationPlan) -> None:
        if not isinstance(plan, SeedOnlyDatabaseCreationPlan):
            raise TypeError("plan must be a SeedOnlyDatabaseCreationPlan")
        seed = next(
            (item for item in self._seeds if item.seed_id == plan.seed_id), None
        )
        if seed is None:
            raise ValueError("plan Seed is not present in the current catalog")
        self._plan = plan
        market = seed.market_id
        self._set_preview_rows((
            ("Seed name", seed.display_name),
            ("Exchange", market.exchange),
            ("Market Type", market.market_type),
            ("Asset", market.symbol),
            ("Timeframe", market.timeframe),
            ("Base columns", ", ".join(plan.column_names)),
            ("Range Start", format_utc_timestamp_ms(plan.first_timestamp_ms)),
            ("Range End", format_utc_timestamp_ms(plan.last_timestamp_ms)),
            ("Row count", str(plan.row_count)),
            ("Column count", str(len(plan.column_names))),
            ("Artifact outputs", "0"),
        ))
        self.result_label.setText("Seed-only Database preview ready.")
        self._sync_controls()

    def consume_plan(self) -> SeedOnlyDatabaseCreationPlan | None:
        plan = self._plan
        self._plan = None
        self._sync_controls()
        return plan

    def set_result(self, message: str) -> None:
        self.result_label.setText(str(message))

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._plan = None
        self.preview_table.setRowCount(0)
        self.result_label.setText(message)
        self._sync_controls()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for widget in (self.seed_table, self.name_edit, self.description_edit):
            widget.setEnabled(not self._busy)
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    def _form_changed(self, *_args) -> None:
        self.invalidate_preview("Form changed; preview again.")

    def _form_valid(self) -> bool:
        name = self.name_edit.text()
        description = self.description_edit.text()
        return bool(
            self.selected_seed() is not None
            and name
            and name == name.strip()
            and description == description.strip()
        )

    def _sync_controls(self) -> None:
        self.preview_button.setEnabled(not self._busy and self._form_valid())
        self.create_button.setEnabled(not self._busy and self._plan is not None)
        self.close_button.setEnabled(True)

    def _emit_preview(self) -> None:
        if not self._busy and self._form_valid():
            self.invalidate_preview("Planning Seed-only Database...")
            self.preview_requested.emit(self.form_values())

    def _emit_create(self) -> None:
        if not self._busy and self._plan is not None:
            self.create_requested.emit(self._plan)

    def _button(self, label: str, suffix: str) -> QPushButton:
        button = QPushButton(label, self)
        apply_identity(
            button,
            f"{_OBJECT_PREFIX}.button.{suffix}",
            object_type="button",
            display_label=label,
            action_id=f"{_OBJECT_PREFIX}.button.{suffix}",
        )
        return button

    def _set_preview_rows(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.preview_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        resize_data_manager_table(self.preview_table)
