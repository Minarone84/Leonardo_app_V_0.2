"""Explicit Artifact-root and Database update review workspace."""
from __future__ import annotations

from functools import partial
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from leonardo.data_manager import DataManagerProductCatalogSnapshot
from leonardo.gui.data_manager.catalogs import (
    _ARTIFACT_CURRENTNESS,
    _database_update_details,
    _database_update_readiness,
    _state,
)
from leonardo.gui.data_manager.table_presentation import format_utc_timestamp_ms, resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


# Retained package export; the workspace no longer has staged pages.
UPDATE_STAGES = ()


class DataManagerUpdateWorkspace(QWidget):
    action_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_identity(self, "data_manager.update.workspace", object_type="workspace")
        self.buttons = {}
        self._busy = False
        self._market = None
        self._snapshot = None
        self._artifact_plan = None
        self._database_plan = None
        self._checks = {}
        self._database_ids = ()
        self.tabs = QTabWidget(self)
        apply_identity(self.tabs, "data_manager.update.tabs", object_type="tabs")
        artifacts, layout = self._page()
        self.artifact_candidates = self._table("artifact_candidates", (
            "Select", "Tool", "Kind", "Artifact through", "OHLCV through",
            "Currentness", "Reason", "Logical Artifact ID",
        ))
        layout.addWidget(self.artifact_candidates, 1)
        layout.addLayout(self._buttons(artifacts, (
            ("select_all", "Select All", "select_all"),
            ("deselect_all", "Deselect All", "deselect_all"),
            ("plan_artifacts", "Preview Update", "plan_artifact_update"),
        )))
        self.artifact_plan_table = self._table("artifact_plan", (
            "Tool", "Kind/Role", "Action", "Reason", "Strategy", "Context",
            "Revisable Tail", "Dependencies", "Logical Artifact ID",
        ))
        layout.addWidget(self.artifact_plan_table, 1)
        layout.addLayout(self._buttons(artifacts, (
            ("execute_artifacts", "Execute Reviewed Update", "execute_artifact_update"),
        )))
        self.artifact_report = self._table("artifact_report", ("Field", "Value"))
        layout.addWidget(self.artifact_report)
        self.tabs.addTab(artifacts, "Artifacts")
        databases, layout = self._page()
        self.database_candidates = self._table("database_candidates", (
            "Name", "Current Revision", "Snapshot State", "Update Readiness",
            "Update Details", "Snapshot Through", "OHLCV Through", "Database ID",
        ))
        layout.addWidget(self.database_candidates, 1)
        layout.addLayout(self._buttons(databases, (
            ("plan_database", "Preview Update", "plan_database_update"),
        )))
        self.database_plan_table = self._table("database_plan", ("Field", "Value"))
        layout.addWidget(self.database_plan_table, 1)
        layout.addLayout(self._buttons(databases, (
            ("append_database", "Append Database Revision", "execute_database_append"),
        )))
        self.commit_report = self._table("commit_report", ("Field", "Value"))
        layout.addWidget(self.commit_report)
        self.tabs.addTab(databases, "Databases")
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        self.database_candidates.itemSelectionChanged.connect(self._database_selection_changed)
        self._sync_gating()

    def selected_roots(self):
        return tuple(sorted(key for key, check in self._checks.items() if check.isChecked()))

    def selected_database_id(self):
        row = self.database_candidates.currentRow()
        return self._database_ids[row] if 0 <= row < len(self._database_ids) else None

    def set_market(self, market):
        if self._market == market:
            return
        self._market = market
        self.clear_artifact_plan()
        self.clear_database_plan()
        if self._snapshot is not None:
            self.set_snapshot(self._snapshot)

    def set_busy(self, busy):
        self._busy = bool(busy)
        self._sync_gating()

    def set_snapshot(self, snapshot):
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        self._snapshot = snapshot
        selected = set(self.selected_roots())
        database_id = self.selected_database_id()
        statuses = {item.logical_artifact_id: item for item in snapshot.latest_reconciliation.artifacts
                    if item.market_id == self._market}
        candidates = []
        for artifact in snapshot.managed_artifacts.artifacts:
            state = statuses.get(artifact.logical_artifact_id)
            if artifact.market_id != self._market or not artifact.valid or state is None:
                continue
            if _ARTIFACT_CURRENTNESS[state.status] != "UPDATE AVAILABLE":
                continue
            candidates.append((artifact, state))
        self._checks = {}
        _set_rows(self.artifact_candidates, tuple(
            ("", artifact.tool_key, artifact.kind, format_utc_timestamp_ms(state.artifact_through_ms),
             format_utc_timestamp_ms(state.ohlcv_through_ms), "UPDATE AVAILABLE",
             " | ".join(state.reasons), artifact.logical_artifact_id)
            for artifact, state in candidates
        ))
        for row, (artifact, _) in enumerate(candidates):
            check = QCheckBox(self.artifact_candidates)
            check.setChecked(artifact.logical_artifact_id in selected)
            check.toggled.connect(self._artifact_selection_changed)
            self._checks[artifact.logical_artifact_id] = check
            self.artifact_candidates.setCellWidget(row, 0, check)
        databases = tuple(
            item
            for item in snapshot.databases
            if item.current_manifest is not None
            and item.current_manifest.market_id == self._market
            and item.currentness is not None
            and item.valid
            and _database_update_readiness(item.currentness) != "CURRENT"
        )
        blocker = QSignalBlocker(self.database_candidates)
        self._database_ids = tuple(item.definition.database_id for item in databases)
        _set_rows(self.database_candidates, tuple(
            (
                item.definition.display_name,
                item.current_manifest.revision_id,
                _state(item.valid, item.rejection_reason),
                _database_update_readiness(item.currentness),
                _database_update_details(item.currentness),
                format_utc_timestamp_ms(item.currentness.snapshot_through_ms),
                format_utc_timestamp_ms(item.currentness.ohlcv_through_ms),
                item.definition.database_id,
            )
            for item in databases
        ))
        if database_id in self._database_ids:
            self.database_candidates.selectRow(self._database_ids.index(database_id))
        else:
            self.database_candidates.clearSelection()
            self.database_candidates.setCurrentCell(-1, -1)
        del blocker
        if self._artifact_plan is not None:
            heads = {item.logical_artifact_id: item.artifact_id for item in snapshot.managed_artifacts.artifacts if item.valid}
            source = next((item.current_source for item in snapshot.latest_reconciliation.source_changes
                           if item.market_id == self._market), None)
            if (self.selected_roots() != self._artifact_plan.root_logical_artifact_ids
                    or any(heads.get(n.logical_artifact_id) != n.current_artifact_id
                           for n in self._artifact_plan.nodes)
                    or (source is not None and source != self._artifact_plan.source_ohlcv)):
                self.clear_artifact_plan()
        if self._database_plan is not None:
            current = next(
                (item for item in databases if item.definition.database_id == self._database_plan.database_id),
                None,
            )
            if (
                current is None
                or current.current_manifest.revision_id != self._database_plan.database_revision_id
                or current.currentness.status != self._database_plan.status
            ):
                self.clear_database_plan()
        self._sync_gating()

    def set_artifact_plan(self, plan):
        self._artifact_plan = plan
        _set_rows(self.artifact_plan_table, tuple(
            (item.tool_key, f"{item.kind} / {item.role}", item.action,
             " | ".join((*item.reasons, *item.blockers)), item.update_strategy.value,
             str(item.context_rows), str(item.revisable_tail_rows),
             ", ".join(item.dependency_logical_artifact_ids), item.logical_artifact_id)
            for item in plan.nodes
        ) + tuple(("", "", "BLOCKED", reason, "", "", "", "", "") for reason in plan.blockers))
        self._sync_gating()

    def clear_artifact_plan(self):
        self._artifact_plan = None
        self.artifact_plan_table.setRowCount(0)
        self._sync_gating()

    def set_database_plan(self, plan):
        self._database_plan = plan
        change = plan.source_change
        prerequisites = tuple(
            f"{node.tool_key} [{node.action}]: "
            + " | ".join((*node.reasons, *node.blockers))
            for node in plan.prerequisite_nodes
        )
        _set_rows(self.database_plan_table, (
            ("Database", plan.database_id),
            ("Current Revision", plan.database_revision_id),
            ("Update Readiness", _database_update_readiness(plan)),
            ("Execution Mode", plan.mode),
            ("Source Evidence", change.status),
            ("Source Detail", change.reason),
            ("Old Through", format_utc_timestamp_ms(change.previous_through_ms)),
            ("Prospective Through", format_utc_timestamp_ms(change.current_through_ms)),
            ("Row Impact", str(change.missing_row_count)),
            ("Columns", ", ".join(plan.column_names)),
            (
                "Required Artifact Heads",
                ", ".join(f"{key}: {value}" for key, value in plan.starting_artifact_heads),
            ),
            ("Artifact Prerequisites", " || ".join(prerequisites)),
            ("Blockers", " | ".join(plan.blockers)),
        ))
        self._sync_gating()

    def clear_database_plan(self):
        self._database_plan = None
        self.database_plan_table.setRowCount(0)
        self._sync_gating()

    def set_artifact_update_result(self, result):
        _set_rows(self.artifact_report, (
            ("Updated", str(len(result.updated_logical_artifact_ids))),
            ("Recovered managed heads (RECREATE)", str(len(result.recovered_logical_artifact_ids))),
            ("Reused", str(len(result.reused_logical_artifact_ids))),
            ("Failed", "0"),
            (
                "Advanced logical Artifact IDs",
                ", ".join(result.materialization.advanced_logical_artifact_ids),
            ),
        ))

    def set_database_update_result(self, result):
        revision = result.database_revision
        _set_rows(self.commit_report, (
            ("Mode", result.mode), ("Database", revision.database_id),
            ("New Revision", revision.revision_id), ("Previous Revision", revision.previous_revision_id or ""),
            ("Rows", str(revision.row_count)), ("Columns", str(revision.column_count)),
            ("Through", format_utc_timestamp_ms(revision.last_timestamp_ms)),
        ))

    def _artifact_selection_changed(self):
        self.clear_artifact_plan()
        self.action_requested.emit("context_changed", self._payload("artifact"))

    def _database_selection_changed(self):
        self.clear_database_plan()
        self.action_requested.emit("context_changed", self._payload("database"))

    def _payload(self, scope=""):
        return {
            "scope": scope,
            "market_id": self._market,
            "root_logical_artifact_ids": self.selected_roots(),
            "database_id": self.selected_database_id(),
        }

    def _emit(self, action):
        if self._busy:
            return
        if action in {"select_all", "deselect_all"}:
            for check in self._checks.values():
                check.setChecked(action == "select_all")
            return
        self.action_requested.emit(action, self._payload())

    def _sync_gating(self, *_):
        if not self.buttons:
            return
        for button in self.buttons.values():
            button.setEnabled(not self._busy)
        for check in self._checks.values():
            check.setEnabled(not self._busy)
        roots = self.selected_roots()
        plan = self._artifact_plan
        self.buttons["data_manager.update.button.plan_artifacts"].setEnabled(not self._busy and bool(roots))
        self.buttons["data_manager.update.button.execute_artifacts"].setEnabled(
            not self._busy and plan is not None and not plan.blocked
            and plan.market_id == self._market and plan.root_logical_artifact_ids == roots)
        database = self._database_plan
        matched = (database is not None and not database.blockers
                   and database.database_id == self.selected_database_id())
        self.buttons["data_manager.update.button.plan_database"].setEnabled(
            not self._busy and self.selected_database_id() is not None)
        self.buttons["data_manager.update.button.append_database"].setEnabled(
            not self._busy and matched and database.mode == "APPEND"
        )

    def _table(self, suffix, columns):
        return configure_table(QTableWidget(self), object_id=f"data_manager.update.table.{suffix}",
                               columns=columns, labels=columns)

    def _page(self):
        page = QWidget(self)
        return page, QVBoxLayout(page)

    def _buttons(self, parent, actions):
        layout = QHBoxLayout()
        for suffix, label, action in actions:
            identity = f"data_manager.update.button.{suffix}"
            button = QPushButton(label, parent)
            apply_identity(button, identity, object_type="button", action_id=identity)
            button.clicked.connect(partial(self._emit, action))
            self.buttons[identity] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return layout


def _set_rows(table, rows):
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, column, item)
    table.setSortingEnabled(sorting)
    resize_data_manager_table(table)
