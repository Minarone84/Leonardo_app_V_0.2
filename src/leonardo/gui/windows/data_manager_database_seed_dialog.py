"""Database Seed creation form and reviewed-plan presentation."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
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
    DataManagerDatasetEntry,
    DatabaseSeedCreationPlan,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DATABASE_SEED_WINDOW_ID = "data_manager.database_seed.window"
_OBJECT_PREFIX = "data_manager.database_seed"
_COLUMNS = ("open", "high", "low", "close", "volume")


class DataManagerDatabaseSeedDialog(QDialog):
    """Collect Seed intent and display an authoritative creation plan."""

    preview_requested = Signal(object)
    create_requested = Signal(object)
    closing = Signal()

    def __init__(
        self,
        dataset: DataManagerDatasetEntry,
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(dataset, DataManagerDatasetEntry) or not dataset.accepted:
            raise TypeError("dataset must be an accepted DataManagerDatasetEntry")
        super().__init__(parent)
        self._dataset = dataset
        self._plan: DatabaseSeedCreationPlan | None = None
        self._busy = False
        self._populating = False
        apply_identity(self, DATA_MANAGER_DATABASE_SEED_WINDOW_ID, object_type="window")
        self.setWindowTitle("Create Database Seed")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.addWidget(self._build_dataset_group())
        root.addWidget(self._build_metadata_group())
        root.addWidget(self._build_columns_group())
        root.addWidget(self._build_range_group())

        preview = QGroupBox("Preview", self)
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

        self.result_label = QLabel("Enter Seed details and preview.", self)
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
        self.create_button = self._button("Create Seed", "create")
        self.close_button = self._button("Close", "close")
        actions.addWidget(self.preview_button)
        actions.addWidget(self.create_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.preview_button.clicked.connect(self._emit_preview)
        self.create_button.clicked.connect(self._emit_create)
        self.close_button.clicked.connect(self.close)
        self.name_edit.textChanged.connect(self._form_changed)
        self.description_edit.textChanged.connect(self._form_changed)
        self.range_start.dateTimeChanged.connect(self._form_changed)
        self.range_end.dateTimeChanged.connect(self._form_changed)
        for checkbox in self.column_checks.values():
            checkbox.toggled.connect(self._form_changed)
        self.set_dataset(dataset)
        apply_initial_window_size(
            self, parent=parent, width_fraction=0.50, height_fraction=0.65
        )

    @property
    def context_key(self) -> tuple[object, ...]:
        return (
            self._dataset.market_id,
            self._dataset.first_timestamp_ms,
            self._dataset.last_timestamp_ms,
            self._dataset.row_count,
        )

    @property
    def reviewed_plan(self) -> DatabaseSeedCreationPlan | None:
        return self._plan

    def set_dataset(self, dataset: DataManagerDatasetEntry) -> None:
        if not isinstance(dataset, DataManagerDatasetEntry) or not dataset.accepted:
            raise TypeError("dataset must be an accepted DataManagerDatasetEntry")
        self._dataset = dataset
        market = dataset.market_id
        if market is None:
            raise ValueError("accepted dataset requires MarketId")
        self._populating = True
        values = (
            ("Exchange", market.exchange),
            ("Market Type", market.market_type),
            ("Asset", market.symbol),
            ("Timeframe", market.timeframe),
            ("First TS", format_utc_timestamp_ms(dataset.first_timestamp_ms)),
            ("Last TS", format_utc_timestamp_ms(dataset.last_timestamp_ms)),
            ("Rows", str(dataset.row_count)),
        )
        for label, widget in self.dataset_fields.items():
            widget.setText(dict(values)[label])
        self.range_start.setDateTime(_utc_datetime(dataset.first_timestamp_ms))
        self.range_end.setDateTime(_utc_datetime(dataset.last_timestamp_ms))
        self._populating = False
        self.invalidate_preview("Dataset context changed; preview again.")

    def form_values(self) -> dict[str, object]:
        return {
            "market_id": self._dataset.market_id,
            "display_name": self.name_edit.text(),
            "description": self.description_edit.text(),
            "selected_ohlcv_columns": tuple(
                column
                for column in _COLUMNS
                if self.column_checks[column].isChecked()
            ),
            "selected_range_start_ms": self.range_start.dateTime().toMSecsSinceEpoch(),
            "selected_range_end_ms": self.range_end.dateTime().toMSecsSinceEpoch(),
        }

    def set_plan(self, plan: DatabaseSeedCreationPlan) -> None:
        if not isinstance(plan, DatabaseSeedCreationPlan):
            raise TypeError("plan must be a DatabaseSeedCreationPlan")
        self._plan = plan
        seed = plan.seed
        self._set_preview_rows((
            ("Seed ID", seed.seed_id),
            ("Name", seed.display_name),
            ("Market", seed.market_id.as_key()),
            ("Columns", ", ".join(seed.selected_ohlcv_columns)),
            ("Range Start", format_utc_timestamp_ms(seed.selected_range_start_ms)),
            ("Range End", format_utc_timestamp_ms(seed.selected_range_end_ms)),
            ("Rows Available", str(seed.source_row_count)),
        ))
        self.result_label.setText("Database Seed preview ready.")
        self._sync_controls()

    def consume_plan(self) -> DatabaseSeedCreationPlan | None:
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
        for widget in (
            self.name_edit,
            self.description_edit,
            self.range_start,
            self.range_end,
            *self.column_checks.values(),
        ):
            widget.setEnabled(not self._busy)
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    def _build_dataset_group(self) -> QGroupBox:
        group = QGroupBox("Dataset", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(12, 24, 12, 12)
        layout.setVerticalSpacing(8)
        self.dataset_fields: dict[str, QLineEdit] = {}
        for label, suffix in (
            ("Exchange", "exchange"),
            ("Market Type", "market_type"),
            ("Asset", "asset"),
            ("Timeframe", "timeframe"),
            ("First TS", "first_timestamp"),
            ("Last TS", "last_timestamp"),
            ("Rows", "rows"),
        ):
            field = QLineEdit(group)
            field.setReadOnly(True)
            apply_identity(
                field,
                f"{_OBJECT_PREFIX}.input.{suffix}",
                object_type="line_edit",
            )
            layout.addRow(label, field)
            self.dataset_fields[label] = field
        return group

    def _build_metadata_group(self) -> QGroupBox:
        group = QGroupBox("Seed metadata", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(12, 24, 12, 12)
        layout.setVerticalSpacing(8)
        self.name_edit = QLineEdit(group)
        self.description_edit = QLineEdit(group)
        for widget, suffix in (
            (self.name_edit, "name"),
            (self.description_edit, "description"),
        ):
            apply_identity(
                widget,
                f"{_OBJECT_PREFIX}.input.{suffix}",
                object_type="line_edit",
            )
        layout.addRow("Name", self.name_edit)
        layout.addRow("Description", self.description_edit)
        return group

    def _build_columns_group(self) -> QGroupBox:
        group = QGroupBox("OHLCV columns", self)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(12, 24, 12, 12)
        layout.setSpacing(8)
        self.column_checks: dict[str, QCheckBox] = {}
        for column in _COLUMNS:
            checkbox = QCheckBox(column.title(), group)
            checkbox.setChecked(True)
            apply_identity(
                checkbox,
                f"{_OBJECT_PREFIX}.input.{column}",
                object_type="check_box",
            )
            layout.addWidget(checkbox)
            self.column_checks[column] = checkbox
        layout.addStretch(1)
        return group

    def _build_range_group(self) -> QGroupBox:
        group = QGroupBox("UTC range", self)
        layout = QFormLayout(group)
        layout.setContentsMargins(12, 24, 12, 12)
        layout.setVerticalSpacing(8)
        self.range_start = QDateTimeEdit(group)
        self.range_end = QDateTimeEdit(group)
        for widget, suffix in (
            (self.range_start, "range_start"),
            (self.range_end, "range_end"),
        ):
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss.zzz")
            widget.setTimeSpec(Qt.TimeSpec.UTC)
            apply_identity(
                widget,
                f"{_OBJECT_PREFIX}.input.{suffix}",
                object_type="date_time_edit",
            )
        layout.addRow("Start UTC", self.range_start)
        layout.addRow("End UTC", self.range_end)
        return group

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

    def _form_changed(self, *_args) -> None:
        if not self._populating:
            self.invalidate_preview("Form changed; preview again.")

    def _form_valid(self) -> bool:
        name = self.name_edit.text()
        description = self.description_edit.text()
        return bool(
            name
            and name == name.strip()
            and description == description.strip()
            and any(item.isChecked() for item in self.column_checks.values())
            and self.range_start.dateTime().toMSecsSinceEpoch()
            <= self.range_end.dateTime().toMSecsSinceEpoch()
        )

    def _sync_controls(self) -> None:
        self.preview_button.setEnabled(not self._busy and self._form_valid())
        self.create_button.setEnabled(not self._busy and self._plan is not None)
        self.close_button.setEnabled(True)

    def _emit_preview(self) -> None:
        if not self._busy and self._form_valid():
            self.invalidate_preview("Planning Database Seed...")
            self.preview_requested.emit(self.form_values())

    def _emit_create(self) -> None:
        if not self._busy and self._plan is not None:
            self.create_requested.emit(self._plan)

    def _set_preview_rows(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.preview_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        resize_data_manager_table(self.preview_table)


def _utc_datetime(value: int | None) -> QDateTime:
    if type(value) is not int:
        raise ValueError("accepted dataset timestamp is unavailable")
    return QDateTime.fromMSecsSinceEpoch(value, Qt.TimeSpec.UTC)
