"""Service-free Research Notebook manager dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from leonardo.research.notebook import ResearchNotebookSummary
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size


@dataclass(frozen=True, slots=True)
class ResearchNotebookSnapshotAssignment:
    """GUI-only projection of a Workspace Snapshot notebook reference."""

    snapshot_id: str
    snapshot_display_name: str
    notebook_id: str | None

    def __post_init__(self) -> None:
        for value, name in (
            (self.snapshot_id, "snapshot_id"),
            (self.snapshot_display_name, "snapshot_display_name"),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be canonical non-empty text")
        if self.notebook_id is not None and (
            not isinstance(self.notebook_id, str)
            or not self.notebook_id
            or self.notebook_id != self.notebook_id.strip()
        ):
            raise ValueError("notebook_id must be None or canonical non-empty text")


class ResearchNotebookManagerDialog(QDialog):
    """Display notebook summaries and emit immutable selection intent."""

    refresh_requested = Signal()
    open_requested = Signal(str)
    delete_requested = Signal(str)
    assign_requested = Signal(str, str)
    unassign_requested = Signal(str, str)

    def __init__(
        self,
        summaries: tuple[ResearchNotebookSummary, ...] = (),
        parent=None,
        *,
        assignments: tuple[ResearchNotebookSnapshotAssignment, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research.notebook_manager_dialog")
        self.setWindowTitle("Research Notebooks")
        self._summaries: tuple[ResearchNotebookSummary, ...] = ()
        self._assignments: tuple[ResearchNotebookSnapshotAssignment, ...] = ()
        self._list = QListWidget(self)
        self._list.setObjectName(
            "research.notebook_manager_dialog.list.notebooks"
        )
        self._name = QLineEdit(self)
        self._name.setObjectName("research.notebook_manager_dialog.edit.name")
        self._name.setReadOnly(True)
        self._description = QLineEdit(self)
        self._description.setObjectName(
            "research.notebook_manager_dialog.edit.description"
        )
        self._description.setReadOnly(True)
        self._pages = QTableWidget(0, 4, self)
        self._pages.setObjectName(
            "research.notebook_manager_dialog.table.pages"
        )
        self._pages.setHorizontalHeaderLabels(
            ("Exchange", "Market Type", "Asset", "Timeframe")
        )
        self._assignment_table = QTableWidget(0, 2, self)
        self._assignment_table.setObjectName(
            "research.notebook_manager_dialog.table.assignments"
        )
        self._assignment_table.setHorizontalHeaderLabels(
            ("Workspace", "Assigned Notebook")
        )
        self._validation = QLabel("", self)
        self._validation.setObjectName(
            "research.notebook_manager_dialog.label.validation"
        )
        self._refresh = QPushButton("Refresh", self)
        self._refresh.setObjectName(
            "research.notebook_manager_dialog.button.refresh"
        )
        self._open = QPushButton("Open", self)
        self._open.setObjectName(
            "research.notebook_manager_dialog.button.open"
        )
        self._delete = QPushButton("Delete", self)
        self._delete.setObjectName(
            "research.notebook_manager_dialog.button.delete"
        )
        self._assign = QPushButton("Assign...", self)
        self._assign.setObjectName(
            "research.notebook_manager_dialog.button.assign"
        )
        self._unassign = QPushButton("Unassign...", self)
        self._unassign.setObjectName(
            "research.notebook_manager_dialog.button.unassign"
        )
        self._close = QPushButton("Close", self)
        self._close.setObjectName(
            "research.notebook_manager_dialog.button.close"
        )
        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        actions = QHBoxLayout()
        actions.addWidget(self._validation, stretch=1)
        actions.addWidget(self._refresh)
        actions.addWidget(self._open)
        actions.addWidget(self._assign)
        actions.addWidget(self._unassign)
        actions.addWidget(self._delete)
        actions.addWidget(self._close)
        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(form)
        layout.addWidget(self._pages)
        layout.addWidget(self._assignment_table)
        layout.addLayout(actions)
        self._list.currentRowChanged.connect(self._selection_changed)
        self._assignment_table.currentCellChanged.connect(
            lambda *_args: self._sync_assignment_buttons()
        )
        self._refresh.clicked.connect(self.refresh_requested.emit)
        self._open.clicked.connect(self._emit_open)
        self._assign.clicked.connect(self._emit_assign)
        self._unassign.clicked.connect(self._emit_unassign)
        self._delete.clicked.connect(self._confirm_delete)
        self._close.clicked.connect(self.close)
        apply_initial_window_size(self, parent=parent)
        self.set_assignments(assignments)
        self.set_summaries(summaries)

    @property
    def summaries(self) -> tuple[ResearchNotebookSummary, ...]:
        return self._summaries

    @property
    def assignments(self) -> tuple[ResearchNotebookSnapshotAssignment, ...]:
        return self._assignments

    def set_summaries(
        self, summaries: tuple[ResearchNotebookSummary, ...]
    ) -> None:
        selected_id = None
        selected = self._selected()
        if selected is not None:
            selected_id = selected.notebook_id
        values = tuple(summaries)
        if not all(isinstance(item, ResearchNotebookSummary) for item in values):
            raise TypeError("summaries must contain ResearchNotebookSummary values")
        self._summaries = values
        self._list.clear()
        for summary in values:
            label = summary.display_name or summary.notebook_id
            if not summary.valid:
                label = f"{label} (invalid)"
            item = QListWidgetItem(label)
            item.setData(256, summary.notebook_id)
            self._list.addItem(item)
        selected_row = next(
            (
                index
                for index, summary in enumerate(values)
                if summary.notebook_id == selected_id
            ),
            0 if values else -1,
        )
        if selected_row >= 0:
            self._list.setCurrentRow(selected_row)
        else:
            self._selection_changed(-1)
        self._rebuild_assignment_table()
        resize_table_columns_to_contents(self._pages)

    def set_assignments(
        self,
        assignments: tuple[ResearchNotebookSnapshotAssignment, ...],
    ) -> None:
        values = tuple(assignments)
        if not all(
            isinstance(item, ResearchNotebookSnapshotAssignment) for item in values
        ):
            raise TypeError(
                "assignments must contain ResearchNotebookSnapshotAssignment values"
            )
        self._assignments = values
        self._rebuild_assignment_table()

    def _selected(self) -> ResearchNotebookSummary | None:
        row = self._list.currentRow()
        return self._summaries[row] if 0 <= row < len(self._summaries) else None

    def _selection_changed(self, _row: int) -> None:
        summary = self._selected()
        if summary is None:
            self._name.clear()
            self._description.clear()
            self._pages.setRowCount(0)
            self._validation.clear()
            self._open.setEnabled(False)
            self._delete.setEnabled(False)
            self._sync_assignment_buttons()
            return
        self._name.setText(summary.display_name)
        self._description.setText(summary.description)
        self._pages.setRowCount(len(summary.page_market_ids))
        for row, market in enumerate(summary.page_market_ids):
            for column, value in enumerate(
                (
                    market.exchange,
                    market.market_type,
                    market.symbol,
                    market.timeframe,
                )
            ):
                self._pages.setItem(row, column, QTableWidgetItem(value))
        self._validation.setText(
            summary.rejection_reason
            or (
                f"{summary.page_count} page(s) | {summary.note_count} note(s) | "
                f"{summary.potential_trade_count} trade(s) | "
                f"{summary.point_of_interest_count} POI(s)"
            )
        )
        self._open.setEnabled(summary.valid)
        self._delete.setEnabled(True)
        self._sync_assignment_buttons()
        resize_table_columns_to_contents(self._assignment_table)

    def _rebuild_assignment_table(self) -> None:
        selected_snapshot_id = self._selected_snapshot_id()
        notebook_names = {
            summary.notebook_id: summary.display_name for summary in self._summaries
        }
        self._assignment_table.setRowCount(len(self._assignments))
        selected_row = -1
        for row, assignment in enumerate(self._assignments):
            snapshot_item = QTableWidgetItem(assignment.snapshot_display_name)
            snapshot_item.setData(Qt.ItemDataRole.UserRole, assignment.snapshot_id)
            self._assignment_table.setItem(row, 0, snapshot_item)
            assigned_name = (
                "Unassigned"
                if assignment.notebook_id is None
                else notebook_names.get(assignment.notebook_id, assignment.notebook_id)
            )
            self._assignment_table.setItem(row, 1, QTableWidgetItem(assigned_name))
            if assignment.snapshot_id == selected_snapshot_id:
                selected_row = row
        if selected_row >= 0:
            self._assignment_table.setCurrentCell(selected_row, 0)
        elif self._assignments:
            self._assignment_table.setCurrentCell(0, 0)
        self._sync_assignment_buttons()

    def _selected_snapshot_id(self) -> str | None:
        row = self._assignment_table.currentRow()
        if not 0 <= row < len(self._assignments):
            return None
        item = self._assignment_table.item(row, 0)
        value = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _selected_assignment(
        self,
    ) -> ResearchNotebookSnapshotAssignment | None:
        snapshot_id = self._selected_snapshot_id()
        return next(
            (
                assignment
                for assignment in self._assignments
                if assignment.snapshot_id == snapshot_id
            ),
            None,
        )

    def _sync_assignment_buttons(self) -> None:
        summary = self._selected()
        assignment = self._selected_assignment()
        valid = summary is not None and summary.valid and assignment is not None
        self._assign.setEnabled(
            valid and assignment.notebook_id != summary.notebook_id
        )
        self._unassign.setEnabled(
            valid and assignment.notebook_id == summary.notebook_id
        )

    def _emit_assign(self) -> None:
        summary = self._selected()
        assignment = self._selected_assignment()
        if (
            summary is not None
            and summary.valid
            and assignment is not None
            and assignment.notebook_id != summary.notebook_id
        ):
            self.assign_requested.emit(summary.notebook_id, assignment.snapshot_id)

    def _emit_unassign(self) -> None:
        summary = self._selected()
        assignment = self._selected_assignment()
        if (
            summary is not None
            and summary.valid
            and assignment is not None
            and assignment.notebook_id == summary.notebook_id
        ):
            self.unassign_requested.emit(summary.notebook_id, assignment.snapshot_id)

    def _emit_open(self) -> None:
        summary = self._selected()
        if summary is not None and summary.valid:
            self.open_requested.emit(summary.notebook_id)

    def _confirm_delete(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        assigned_snapshots = tuple(
            assignment.snapshot_display_name
            for assignment in self._assignments
            if assignment.notebook_id == summary.notebook_id
        )
        message = f"Delete {summary.display_name or summary.notebook_id}?"
        if assigned_snapshots:
            listed = "\n".join(f"- {name}" for name in assigned_snapshots)
            message += (
                "\n\nThis notebook is assigned to:\n"
                f"{listed}\n\nDeleting it also requires removing those "
                "Workspace references."
            )
        if QMessageBox.question(
            self,
            "Delete Research Notebook",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes:
            self.delete_requested.emit(summary.notebook_id)
