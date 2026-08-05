"""Explicit Data Manager update and reconciliation workspace."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import DataManagerProductCatalogSnapshot
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


UPDATE_STAGES = (
    "1. Source Change Review",
    "2. Artifact Update Plan",
    "3. Artifact Execution",
    "4. Collection Validation",
    "5. Database Append or Rebuild Preview",
    "6. Commit Database Revision",
)


class DataManagerUpdateWorkspace(QWidget):
    """Present explicit update decisions and complete reconciliation evidence."""

    action_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_identity(self, "data_manager.update.workspace", object_type="workspace")
        self.buttons: dict[str, QPushButton] = {}
        self._busy = False
        self._artifact_plan_collection_id: str | None = None
        self._artifact_plan_executable = False
        self._database_plan_database_id: str | None = None
        self._database_plan_mode: str | None = None
        self._artifact_result_active = False
        self.stage_list = QListWidget(self)
        self.stage_list.addItems(UPDATE_STAGES)
        self.stage_list.setFixedWidth(260)
        apply_identity(self.stage_list, "data_manager.update.list.stages", object_type="list")
        self.stack = QStackedWidget(self)
        apply_identity(self.stack, "data_manager.update.stack.stages", object_type="stack")
        self.stage_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.collection_combo = QComboBox(self)
        self.database_combo = QComboBox(self)
        apply_identity(self.collection_combo, "data_manager.update.combo.collection", object_type="combo_box")
        apply_identity(self.database_combo, "data_manager.update.combo.database", object_type="combo_box")
        self.confirm_rebuild = QCheckBox("I confirm full Database rebuild", self)
        apply_identity(self.confirm_rebuild, "data_manager.update.check.rebuild_confirmed", object_type="check_box")

        self.reconciliation_tables = {
            "sources": self._table("sources", ("Market", "Status", "Previous Through", "Current Through", "Missing Rows", "Reason")),
            "artifacts": self._table("artifacts", ("Logical Artifact", "Market", "Status", "Artifact Through", "OHLCV Through", "Missing Rows", "Reasons")),
            "collections": self._table("collections", ("Collection", "Market", "Status", "Aligned Through", "OHLCV Through", "Stale", "Blocked", "Database Ready", "Reasons")),
            "databases": self._table("databases", ("Database", "Market", "Status", "Snapshot Through", "OHLCV Through", "Collection Through", "Missing Rows", "Prefix", "Reasons")),
            "failures": self._table("failures", ("Failure",)),
        }
        source_page, source_layout = self._page("Source Change Review")
        source_tabs = QTabWidget(source_page)
        for key, label in (
            ("sources", "Sources"),
            ("artifacts", "Artifacts"),
            ("collections", "Collections"),
            ("databases", "Databases"),
            ("failures", "Failures"),
        ):
            source_tabs.addTab(self.reconciliation_tables[key], label)
        source_layout.addWidget(source_tabs, 1)
        source_layout.addLayout(self._buttons(source_page, (
            ("data_manager.update.button.refresh", "Refresh Reconciliation", "refresh_reconciliation"),
        )))
        self.stack.addWidget(source_page)

        artifact_plan_page, artifact_plan_layout = self._page("Artifact Update Plan")
        form = QFormLayout()
        form.addRow("Artifact Collection", self.collection_combo)
        artifact_plan_layout.addLayout(form)
        self.artifact_plan_table = self._table(
            "artifact_plan",
            ("Recipe", "Logical Artifact", "Tool", "Role", "Action", "Strategy", "Context", "Revisable Tail", "Blockers"),
        )
        artifact_plan_layout.addWidget(self.artifact_plan_table, 1)
        artifact_plan_layout.addLayout(self._buttons(artifact_plan_page, (
            ("data_manager.update.button.plan_artifacts", "Plan Artifact Update", "plan_artifact_update"),
        )))
        self.stack.addWidget(artifact_plan_page)

        artifact_execute_page, artifact_execute_layout = self._page("Artifact Execution")
        artifact_execute_layout.addWidget(QLabel("Execute only the reviewed immutable Artifact update plan.", artifact_execute_page))
        artifact_execute_layout.addLayout(self._buttons(artifact_execute_page, (
            ("data_manager.update.button.execute_artifacts", "Execute Artifact Update", "execute_artifact_update"),
        )))
        artifact_execute_layout.addStretch(1)
        self.stack.addWidget(artifact_execute_page)

        collection_page, collection_layout = self._page("Collection Validation")
        self.collection_validation_table = self._table(
            "collection_validation",
            (
                "Collection", "Revision", "State", "Roots", "Supports",
                "Selected Outputs", "Coverage", "Database Ready", "Reasons",
            ),
        )
        collection_layout.addWidget(self.collection_validation_table, 1)
        collection_layout.addLayout(self._buttons(collection_page, (
            ("data_manager.update.button.validate_collection", "Refresh Collection Validation", "refresh_reconciliation"),
        )))
        self.stack.addWidget(collection_page)

        database_plan_page, database_plan_layout = self._page("Database Append or Rebuild Preview")
        database_form = QFormLayout()
        database_form.addRow("Database", self.database_combo)
        database_plan_layout.addLayout(database_form)
        self.database_plan_table = self._table(
            "database_plan",
            ("Database", "Mode", "Status", "Collection Revision", "Columns", "Stages", "Blockers"),
        )
        database_plan_layout.addWidget(self.database_plan_table, 1)
        database_plan_layout.addLayout(self._buttons(database_plan_page, (
            ("data_manager.update.button.plan_database", "Plan Database Update", "plan_database_update"),
        )))
        self.stack.addWidget(database_plan_page)

        commit_page, commit_layout = self._page("Commit Database Revision")
        commit_layout.addWidget(self.confirm_rebuild)
        commit_layout.addLayout(self._buttons(commit_page, (
            ("data_manager.update.button.append_database", "Append Database Revision", "execute_database_append"),
            ("data_manager.update.button.rebuild_database", "Rebuild Database Revision", "execute_database_rebuild"),
        )))
        self.commit_report = self._table("commit_report", ("Field", "Value"))
        commit_layout.addWidget(self.commit_report, 1)
        self.stack.addWidget(commit_page)

        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(self.stage_list)
        layout.addLayout(right, 1)
        self.stage_list.setCurrentRow(0)
        self.collection_combo.currentIndexChanged.connect(
            lambda _index: self._selection_changed("artifact")
        )
        self.database_combo.currentIndexChanged.connect(
            lambda _index: self._selection_changed("database")
        )
        self._sync_gating()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.stage_list.setEnabled(not self._busy)
        self._sync_gating()

    def set_snapshot(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        _set_combo(
            self.collection_combo,
            tuple((item.collection_id, item.display_name) for item in snapshot.artifact_collections),
        )
        _set_combo(
            self.database_combo,
            tuple((item.definition.database_id, item.definition.display_name) for item in snapshot.databases),
        )
        reconciliation = snapshot.latest_reconciliation
        _set_rows(self.reconciliation_tables["sources"], tuple(
            (
                item.market_id.as_key(), item.status, str(item.previous_through_ms or ""),
                str(item.current_through_ms or ""), str(item.missing_row_count), item.reason,
            )
            for item in reconciliation.source_changes
        ))
        _set_rows(self.reconciliation_tables["artifacts"], tuple(
            (
                item.logical_artifact_id, item.market_id.as_key(), item.status,
                str(item.artifact_through_ms or ""), str(item.ohlcv_through_ms or ""),
                str(item.missing_row_count), " | ".join(item.reasons),
            )
            for item in reconciliation.artifacts
        ))
        collection_rows = tuple(
            (
                item.collection_id, item.market_id.as_key(), item.status,
                str(item.aligned_through_ms or ""), str(item.ohlcv_through_ms or ""),
                str(item.stale_member_count), str(item.blocked_member_count),
                "yes" if item.database_ready else "no", " | ".join(item.reasons),
            )
            for item in reconciliation.collections
        )
        _set_rows(self.reconciliation_tables["collections"], collection_rows)
        if not self._artifact_result_active:
            _set_rows(self.collection_validation_table, tuple(
                (row[0], "", row[2], "", "", "", row[3], row[7], row[8])
                for row in collection_rows
            ))
        _set_rows(self.reconciliation_tables["databases"], tuple(
            (
                item.database_id, item.market_id.as_key(), item.status,
                str(item.snapshot_through_ms or ""), str(item.ohlcv_through_ms or ""),
                str(item.collection_through_ms or ""), str(item.missing_row_count),
                "valid" if item.prefix_integrity else "mismatch", " | ".join(item.reasons),
            )
            for item in reconciliation.databases
        ))
        _set_rows(
            self.reconciliation_tables["failures"],
            tuple((value,) for value in reconciliation.failures),
        )

    def set_artifact_plan(self, plan) -> None:
        _set_rows(self.artifact_plan_table, tuple(
            (
                item.portable_recipe_id, item.logical_artifact_id, item.tool_key,
                item.role, item.action, item.update_strategy.value,
                str(item.context_rows), str(item.revisable_tail_rows),
                " | ".join(item.blockers),
            )
            for item in plan.nodes
        ))
        self._artifact_plan_collection_id = str(
            getattr(plan, "collection_id", None)
            or self.collection_combo.currentData()
            or ""
        ) or None
        plan_blockers = tuple(getattr(plan, "blockers", ()) or ())
        node_blocked = any(
            bool(tuple(getattr(item, "blockers", ()) or ()))
            for item in getattr(plan, "nodes", ())
        )
        self._artifact_plan_executable = not bool(
            getattr(plan, "blocked", False)
            or plan_blockers
            or node_blocked
        )
        self._sync_gating()

    def set_database_plan(self, plan) -> None:
        _set_rows(self.database_plan_table, ((
            plan.database_id, plan.mode, plan.status, plan.collection_revision_id,
            ", ".join(plan.column_names), str(len(plan.execution_stages)),
            " | ".join(plan.blockers),
        ),))
        self._database_plan_database_id = plan.database_id
        blocked = bool(getattr(plan, "blocked", plan.blockers))
        self._database_plan_mode = None if blocked else plan.mode
        self._sync_gating()

    def clear_artifact_plan(self) -> None:
        self._artifact_plan_collection_id = None
        self._artifact_plan_executable = False
        self.artifact_plan_table.setRowCount(0)
        self._sync_gating()

    def clear_database_plan(self) -> None:
        self._database_plan_database_id = None
        self._database_plan_mode = None
        self.database_plan_table.setRowCount(0)
        self._sync_gating()

    def set_artifact_update_result(self, result) -> None:
        revision = result.collection_revision
        self._artifact_result_active = True
        _set_rows(self.collection_validation_table, ((
            revision.collection_id,
            revision.revision_id,
            revision.validation_state,
            ", ".join(revision.root_logical_artifact_ids),
            ", ".join(revision.support_logical_artifact_ids),
            ", ".join(
                f"{item.logical_artifact_id}:{item.output_name}->{item.column_name}"
                for item in revision.selected_outputs
            ),
            f"{revision.first_timestamp_ms} - {revision.last_timestamp_ms}",
            "yes" if revision.database_ready else "no",
            "",
        ),))

    def set_database_update_result(self, result) -> None:
        revision = result.database_revision
        _set_rows(self.commit_report, tuple(
            (name, value)
            for name, value in (
                ("mode", result.mode),
                ("database_id", revision.database_id),
                ("new_revision_id", revision.revision_id),
                ("previous_revision_id", revision.previous_revision_id or ""),
                ("collection_revision_id", revision.collection_revision_id),
                ("rows", str(revision.row_count)),
                ("columns", str(revision.column_count)),
                (
                    "coverage",
                    f"{revision.first_timestamp_ms} - {revision.last_timestamp_ms}",
                ),
                ("values_hash", revision.values_sha256),
            )
        ))

    def _emit(self, action: str) -> None:
        self.action_requested.emit(
            action,
            {
                "collection_id": self.collection_combo.currentData(),
                "database_id": self.database_combo.currentData(),
                "rebuild_confirmed": self.confirm_rebuild.isChecked(),
            },
        )

    def _selection_changed(self, scope: str) -> None:
        self._sync_gating()
        self.action_requested.emit(
            "context_changed",
            {
                "scope": scope,
                "collection_id": self.collection_combo.currentData(),
                "database_id": self.database_combo.currentData(),
            },
        )

    def _sync_gating(self) -> None:
        for button in self.buttons.values():
            button.setEnabled(not self._busy)
        artifact_matches = (
            self._artifact_plan_executable
            and self._artifact_plan_collection_id is not None
            and self.collection_combo.currentData() == self._artifact_plan_collection_id
        )
        database_matches = (
            self._database_plan_database_id is not None
            and self.database_combo.currentData() == self._database_plan_database_id
        )
        self.buttons["data_manager.update.button.execute_artifacts"].setEnabled(
            not self._busy and artifact_matches
        )
        self.buttons["data_manager.update.button.append_database"].setEnabled(
            not self._busy and database_matches and self._database_plan_mode == "APPEND"
        )
        self.buttons["data_manager.update.button.rebuild_database"].setEnabled(
            not self._busy
            and database_matches
            and self._database_plan_mode == "REBUILD_REQUIRED"
        )

    def _table(self, suffix: str, columns: tuple[str, ...]) -> QTableWidget:
        return configure_table(
            QTableWidget(self),
            object_id=f"data_manager.update.table.{suffix}",
            columns=columns,
            labels=columns,
        )

    def _page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        heading = QLabel(title, page)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        return page, layout

    def _buttons(self, parent: QWidget, actions) -> QHBoxLayout:
        layout = QHBoxLayout()
        for object_id, label, action in actions:
            button = QPushButton(label, parent)
            apply_identity(
                button,
                object_id,
                object_type="button",
                display_label=label,
                action_id=object_id,
            )
            button.clicked.connect(partial(self._emit, action))
            self.buttons[object_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return layout


def _set_combo(combo: QComboBox, values: tuple[tuple[str, str], ...]) -> None:
    current = combo.currentData()
    blocker = QSignalBlocker(combo)
    combo.clear()
    combo.addItem("Select explicitly", None)
    for identity, label in values:
        combo.addItem(label, identity)
    if current is not None:
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
    del blocker


def _set_rows(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
