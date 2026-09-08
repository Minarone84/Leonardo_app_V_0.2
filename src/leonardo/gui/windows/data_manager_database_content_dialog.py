"""Database content-management window for persisted Artifact outputs."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import (
    DataManagerDatabaseCatalogEntry,
    DataManagerProductCatalogSnapshot,
    DatabaseContentAdditionPlan,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID = "data_manager.database_content.window"
_CHECKBOX_STYLE = """
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { border: 1px solid #8B949E; background: #0D1117; }
QCheckBox::indicator:checked { border: 1px solid #58A6FF; background: #1F6FEB; }
QCheckBox::indicator:disabled { border: 1px solid #484F58; background: #21262D; }
"""


class DataManagerDatabaseContentDialog(QDialog):
    """Preview and publish immutable additions to one current Database."""

    preview_requested = Signal(str, str, object)
    add_requested = Signal(object)
    closing = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._database: DataManagerDatabaseCatalogEntry | None = None
        self._snapshot: DataManagerProductCatalogSnapshot | None = None
        self._mode = "artifacts"
        self._plan: DatabaseContentAdditionPlan | None = None
        self._busy = False
        self._source_values: list[object] = []
        self._source_checks: list[QCheckBox] = []

        self.setWindowTitle("Add Database Content")
        self.setObjectName("data_manager_database_content_dialog")
        self.setProperty("object_id", DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID)
        self.setWindowModality(Qt.WindowModality.NonModal)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(available.width(), max(760, int(available.width() * 0.60))),
                min(available.height(), max(600, int(available.height() * 0.70))),
            )

        root = QVBoxLayout(self)
        self.summary_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.summary",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.summary_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        root.addWidget(self.summary_table)

        self.source_label = QLabel("Artifact Selection", self)
        apply_identity(
            self.source_label,
            "data_manager.database_content.label.source",
            object_type="label",
        )
        root.addWidget(self.source_label)
        self.source_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.sources",
            columns=("Select", "Artifact", "Tool", "Outputs", "Status"),
            labels=("Select", "Artifact", "Tool", "Outputs", "Status"),
        )
        self.source_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        root.addWidget(self.source_table, 1)

        root.addWidget(QLabel("Preview", self))
        self.preview_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.preview",
            columns=("Status", "Artifact", "Output", "Database Column", "Origin"),
            labels=("Status", "Artifact", "Output", "Database Column", "Origin"),
        )
        self.preview_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        root.addWidget(self.preview_table, 1)

        self.preview_summary = QLabel("Preview required.", self)
        apply_identity(
            self.preview_summary,
            "data_manager.database_content.label.preview_summary",
            object_type="label",
        )
        self.preview_summary.setWordWrap(True)
        root.addWidget(self.preview_summary)

        buttons = QHBoxLayout()
        self.preview_button = self._button("Preview", "preview")
        self.add_button = self._button("Add to Database", "add")
        self.close_button = self._button("Close", "close")
        self.preview_button.clicked.connect(self._emit_preview)
        self.add_button.clicked.connect(self._emit_add)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.preview_button)
        buttons.addStretch(1)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)
        self._sync_controls()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def reviewed_plan(self) -> DatabaseContentAdditionPlan | None:
        return self._plan

    @property
    def context_key(self) -> tuple[object, ...]:
        manifest = None if self._database is None else self._database.current_manifest
        return (
            None if self._database is None else self._database.definition.database_id,
            None if manifest is None else manifest.revision_id,
            self._mode,
            self.selected_source_ids(),
        )

    def set_context(
        self,
        database: DataManagerDatabaseCatalogEntry,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        mode: str,
    ) -> None:
        if not isinstance(database, DataManagerDatabaseCatalogEntry):
            raise TypeError("database must be a DataManagerDatabaseCatalogEntry")
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        if mode not in {"artifacts", "collection"}:
            raise ValueError("mode must be artifacts or collection")
        self._database = database
        self._snapshot = snapshot
        self._mode = mode
        self.setWindowTitle(
            "Add Artifacts to Database"
            if mode == "artifacts"
            else "Add Artifact Collection to Database"
        )
        self._populate_summary()
        self._populate_sources()
        self.invalidate_preview("Preview required.")

    def selected_source_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for checkbox, value in zip(
            self._source_checks, self._source_values, strict=True
        ):
            if not checkbox.isEnabled() or not checkbox.isChecked():
                continue
            if self._mode == "artifacts":
                values.append(value.logical_artifact_id)
            else:
                values.append(value.collection_id)
        return tuple(values)

    def set_plan(self, plan: DatabaseContentAdditionPlan) -> None:
        if not isinstance(plan, DatabaseContentAdditionPlan):
            raise TypeError("plan must be a DatabaseContentAdditionPlan")
        if not self._plan_matches_context(plan):
            raise ValueError("plan does not match current Database content context")
        self._plan = plan
        self.preview_table.setRowCount(len(plan.output_preview_rows))
        for row, item in enumerate(plan.output_preview_rows):
            values = (
                "BLOCKED" if item.status == "BLOCKED_COLLISION" else item.status.replace("_", " "),
                item.artifact_id,
                item.output_name,
                item.column_name,
                item.origin,
            )
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        added_count = sum(
            item.status == "ADD" for item in plan.output_preview_rows
        )
        included_count = sum(
            item.status == "ALREADY_INCLUDED" for item in plan.output_preview_rows
        )
        collision_count = sum(
            item.status == "BLOCKED_COLLISION" for item in plan.output_preview_rows
        )
        proposed_columns = tuple(plan.old_columns) + tuple(plan.new_columns)
        summary = "\n".join(
            (
                f"Current schema: {', '.join(plan.old_columns)}",
                f"Proposed schema: {', '.join(proposed_columns)}",
                f"Current row count: {plan.old_row_count}",
                f"Proposed row count: {plan.new_row_count}",
                "Coverage: "
                f"{format_utc_timestamp_ms(plan.first_timestamp_ms)} to "
                f"{format_utc_timestamp_ms(plan.last_timestamp_ms)}",
                f"Leading warmup exclusions: {plan.leading_warmup_exclusions}",
                "Interior / later missing rows: "
                f"{plan.non_leading_missing_rows}",
                f"Added output count: {added_count}",
                f"Already included count: {included_count}",
                f"Collision count: {collision_count}",
            )
        )
        if plan.requires_v1_transition:
            summary += (
                "\n\nThis Database currently uses the legacy V1 "
                "collection-following revision format. Confirming this content "
                "change will create a new V2 revision whose content membership "
                "is owned by the Database. Existing V1 revisions and history "
                "will remain unchanged."
            )
        if plan.blockers:
            summary += " Blocked: " + "; ".join(plan.blockers)
        self.preview_summary.setText(summary)
        resize_data_manager_table(self.preview_table)
        self._sync_controls()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.source_table.setEnabled(not self._busy)
        self._sync_controls()

    def publication_succeeded(
        self,
        database: DataManagerDatabaseCatalogEntry,
        snapshot: DataManagerProductCatalogSnapshot,
    ) -> None:
        mode = self._mode
        self.set_context(database, snapshot, mode=mode)
        self.preview_summary.setText(
            "Database content revision published. Preview again for another addition."
        )

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._plan = None
        self.preview_table.setRowCount(0)
        self.preview_summary.setText(str(message))
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    def _populate_summary(self) -> None:
        database = self._database
        manifest = None if database is None else database.current_manifest
        if database is None or manifest is None:
            rows = (("State", "Current Database revision unavailable"),)
        else:
            market = database.definition.market_id
            rows = (
                ("Database Name", database.definition.display_name),
                ("Database ID", database.definition.database_id),
                ("Exchange", market.exchange),
                ("Market Type", market.market_type),
                ("Asset", market.symbol),
                ("Timeframe", market.timeframe),
                ("Current Revision", manifest.revision_id),
                ("Current Rows", str(manifest.row_count)),
                ("Current Columns", str(manifest.column_count)),
            )
        self.summary_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.summary_table.setItem(row, column, QTableWidgetItem(value))
        resize_data_manager_table(self.summary_table)

    def _populate_sources(self) -> None:
        database = self._database
        snapshot = self._snapshot
        self._source_values = []
        self._source_checks = []
        self.source_table.setRowCount(0)
        if database is None or snapshot is None or database.current_manifest is None:
            return
        market = database.definition.market_id
        source = database.current_manifest.source_ohlcv
        database_current = (
            database.currentness is not None
            and database.currentness.status == "CURRENT"
        )
        if self._mode == "artifacts":
            values = tuple(
                item
                for item in snapshot.managed_artifacts.artifacts
                if item.market_id == market
            )
            columns = ("Select", "Artifact", "Tool", "Outputs", "Status")
            self.source_label.setText("Artifact Selection")
        else:
            values = tuple(
                item
                for item in snapshot.artifact_collections
                if item.market_id == market
            )
            columns = ("Select", "Collection", "Revision", "Outputs", "Status")
            self.source_label.setText("Artifact Collection Selection")
        self.source_table.setColumnCount(len(columns))
        self.source_table.setHorizontalHeaderLabels(columns)
        self.source_table.setRowCount(len(values))
        self._source_values = list(values)
        for row, value in enumerate(values):
            if self._mode == "artifacts":
                currentness = next(
                    (
                        item
                        for item in snapshot.latest_reconciliation.artifacts
                        if item.logical_artifact_id == value.logical_artifact_id
                        and item.artifact_id == value.artifact_id
                        and item.market_id == value.market_id
                    ),
                    None,
                )
                selectable = (
                    database_current
                    and value.valid
                    and currentness is not None
                    and currentness.status == "CURRENT"
                )
                if not database_current:
                    status = "Database update required"
                elif not value.valid:
                    status = value.rejection_reason
                elif selectable:
                    status = "Current"
                else:
                    status = "Stale or source-incompatible"
                texts = (
                    value.logical_artifact_id,
                    value.tool_key,
                    ", ".join(value.output_names),
                    status,
                )
            else:
                selectable = (
                    database_current
                    and value.validation_state == "valid"
                    and value.source_ohlcv == source
                )
                if not database_current:
                    status = "Database update required"
                elif selectable:
                    status = "Current"
                else:
                    status = "Stale, invalid, or source-incompatible"
                texts = (
                    value.collection_id,
                    value.revision_id,
                    ", ".join(value.presentation_order),
                    status,
                )
            checkbox = QCheckBox(self.source_table)
            checkbox.setStyleSheet(_CHECKBOX_STYLE)
            checkbox.setEnabled(selectable)
            checkbox.stateChanged.connect(
                lambda state, current=checkbox: self._source_toggled(current, state)
            )
            self._source_checks.append(checkbox)
            self.source_table.setCellWidget(row, 0, checkbox)
            for column, text in enumerate(texts, start=1):
                self.source_table.setItem(row, column, QTableWidgetItem(str(text)))
        resize_data_manager_table(self.source_table)

    def _source_toggled(self, checkbox: QCheckBox, state: int) -> None:
        if not checkbox.isEnabled() and checkbox.isChecked():
            checkbox.setChecked(False)
            return
        self.invalidate_preview("Source selection changed; Preview again.")

    def _emit_preview(self) -> None:
        database = self._database
        selected = self.selected_source_ids()
        if (
            not self._busy
            and database is not None
            and database.current_manifest is not None
            and selected
            and (self._mode == "artifacts" or len(selected) == 1)
        ):
            self.invalidate_preview("Planning Database content...")
            self.preview_requested.emit(
                self._mode, database.definition.database_id, selected
            )

    def _emit_add(self) -> None:
        if not self._busy and self._plan is not None:
            self.add_requested.emit(self._plan)

    def _sync_controls(self) -> None:
        selected = self.selected_source_ids()
        selectable = bool(selected) and (
            self._mode == "artifacts" or len(selected) == 1
        )
        self.preview_button.setEnabled(not self._busy and selectable)
        self.add_button.setEnabled(
            not self._busy
            and self._plan is not None
            and self._plan_matches_context(self._plan)
            and not self._plan.blocked
            and self._plan.has_additions
        )
        self.close_button.setEnabled(True)

    def _plan_matches_context(self, plan: DatabaseContentAdditionPlan) -> bool:
        database = self._database
        manifest = None if database is None else database.current_manifest
        if database is None or manifest is None:
            return False
        if (
            plan.database_id != database.definition.database_id
            or plan.starting_revision_id != manifest.revision_id
            or plan.market_id != database.definition.market_id
            or plan.source_ohlcv != manifest.source_ohlcv
            or plan.source_kind != self._mode
        ):
            return False
        selected = self.selected_source_ids()
        if self._mode == "artifacts":
            return plan.selected_root_logical_artifact_ids == selected
        return (
            plan.source_collection is not None
            and (plan.source_collection.collection_id,) == selected
        )

    def _button(self, label: str, suffix: str) -> QPushButton:
        button = QPushButton(label, self)
        apply_identity(
            button,
            f"data_manager.database_content.button.{suffix}",
            object_type="button",
            display_label=label,
            action_id=f"data_manager.database_content.button.{suffix}",
        )
        return button
