from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QSignalSpy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from leonardo.data import MarketId
from leonardo.gui.windows.research_notebook_manager_dialog import (
    ResearchNotebookManagerDialog,
    ResearchNotebookSnapshotAssignment,
)
from leonardo.research.notebook import ResearchNotebookSummary


def _summary(valid: bool) -> ResearchNotebookSummary:
    return ResearchNotebookSummary(
        notebook_id="notebook_one" if valid else "Invalid Name",
        display_name="Valid" if valid else "Invalid",
        description="description",
        created_at_utc=None,
        updated_at_utc=None,
        page_count=1 if valid else 0,
        note_count=0,
        potential_trade_count=0,
        point_of_interest_count=0,
        page_market_ids=(
            (MarketId("bybit", "linear", "BTCUSDT", "1h"),) if valid else ()
        ),
        valid=valid,
        rejection_reason=None if valid else "invalid JSON",
        path=Path("notebook.json"),
    )


def _valid_summary(notebook_id: str, display_name: str) -> ResearchNotebookSummary:
    return ResearchNotebookSummary(
        notebook_id=notebook_id,
        display_name=display_name,
        description="description",
        created_at_utc=None,
        updated_at_utc=None,
        page_count=1,
        note_count=0,
        potential_trade_count=0,
        point_of_interest_count=0,
        page_market_ids=(MarketId("bybit", "linear", "BTCUSDT", "1h"),),
        valid=True,
        rejection_reason=None,
        path=Path("notebook.json"),
    )


def _set_checked(
    dialog: ResearchNotebookManagerDialog, row: int, checked: bool = True
) -> None:
    dialog._list.item(row).setCheckState(
        Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    )


def test_manager_valid_and_invalid_selection_enablement() -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(True), _summary(False)))
    notebook_list = dialog.findChild(
        QListWidget, "research.notebook_manager_dialog.list.notebooks"
    )
    instruction = dialog.findChild(
        QLabel, "research.notebook_manager_dialog.label.selection_instruction"
    )
    open_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.open"
    )
    delete_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.delete"
    )
    assert instruction.text() == "Select one Notebook"
    assert notebook_list.selectionMode() == QAbstractItemView.NoSelection
    assert notebook_list.currentRow() == -1
    assert all(
        notebook_list.item(row).checkState() == Qt.CheckState.Unchecked
        for row in range(notebook_list.count())
    )
    assert dialog._name.text() == ""
    assert dialog._description.text() == ""
    assert dialog._pages.rowCount() == 0
    assert dialog._selected_notebook.text() == ""
    assert dialog._target_workspace.text() == ""
    assert dialog._current_assignment.text() == ""
    assert not open_button.isEnabled()
    assert not delete_button.isEnabled()
    assert not dialog._assignment_action.isEnabled()
    assert dialog._create.isEnabled()

    _set_checked(dialog, 0)
    assert dialog._name.text() == "Valid"
    assert dialog._description.text() == "description"
    assert dialog._pages.rowCount() == 1
    assert open_button.isEnabled()
    assert delete_button.isEnabled()

    _set_checked(dialog, 1)
    assert dialog._name.text() == ""
    assert dialog._description.text() == ""
    assert dialog._pages.rowCount() == 0
    assert dialog._selected_notebook.text() == ""
    assert dialog._target_workspace.text() == ""
    assert dialog._current_assignment.text() == ""
    assert not open_button.isEnabled()
    assert not delete_button.isEnabled()
    assert not dialog._assignment_action.isEnabled()

    _set_checked(dialog, 1, False)
    assert dialog._name.text() == "Valid"
    assert open_button.isEnabled()
    assert delete_button.isEnabled()

    _set_checked(dialog, 0, False)
    _set_checked(dialog, 1)
    assert dialog._validation.text() == "invalid JSON"
    assert not open_button.isEnabled()
    assert delete_button.isEnabled()
    assert not dialog._assignment_action.isEnabled()


def test_manager_new_notebook_is_always_available_and_emits_once() -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(False),))
    button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.new"
    )
    emitted = QSignalSpy(dialog.create_requested)

    assert button.isEnabled()
    command_layout = dialog.layout().itemAt(dialog.layout().count() - 1).layout()
    assert tuple(
        item.widget().text()
        for index in range(command_layout.count())
        if (item := command_layout.itemAt(index)).widget() is not None
        and isinstance(item.widget(), QPushButton)
    ) == (
        "Refresh",
        "New Notebook",
        "Open",
        "Assign Notebook",
        "Delete",
        "Close",
    )
    button.click()

    assert emitted.count() == 1


def test_manager_disables_mutation_controls_while_notebook_work_is_busy() -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(True),))
    _set_checked(dialog, 0)

    dialog.set_busy(True)

    assert not dialog._refresh.isEnabled()
    assert not dialog._create.isEnabled()
    assert not dialog._open.isEnabled()
    assert not dialog._delete.isEnabled()
    assert not dialog._assignment_action.isEnabled()
    assert dialog._close.isEnabled()

    dialog.set_busy(False)

    assert dialog._refresh.isEnabled()
    assert dialog._create.isEnabled()
    assert dialog._open.isEnabled()
    assert dialog._delete.isEnabled()


def test_manager_user_refresh_clears_checked_notebook_selection() -> None:
    QApplication.instance() or QApplication([])
    first = _valid_summary("notebook_one", "Notebook One")
    second = _valid_summary("notebook_two", "Notebook Two")
    dialog = ResearchNotebookManagerDialog((first, second))
    emitted = QSignalSpy(dialog.refresh_requested)
    _set_checked(dialog, 0)
    dialog.set_summaries((second, first))
    assert dialog._selected().notebook_id == "notebook_one"

    dialog._refresh.click()

    assert emitted.count() == 1
    assert dialog._checked_notebook_ids() == ()
    assert dialog._list.currentRow() == -1
    assert dialog._name.text() == ""
    assert dialog._description.text() == ""
    assert dialog._pages.rowCount() == 0
    assert dialog._selected_notebook.text() == ""
    assert not dialog._open.isEnabled()
    assert not dialog._delete.isEnabled()
    assert not dialog._assignment_action.isEnabled()


def test_manager_assignment_table_and_explicit_context() -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog(
        (_valid_summary("notebook_one", "Notebook One"),),
        assignments=(
            ResearchNotebookSnapshotAssignment(
                "workspace_one", "Workspace One", None
            ),
        ),
    )
    table = dialog.findChild(
        QTableWidget, "research.notebook_manager_dialog.table.assignments"
    )
    action = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.assignment_action"
    )
    selected = dialog.findChild(
        QLineEdit,
        "research.notebook_manager_dialog.assignment.selected_notebook",
    )
    target = dialog.findChild(
        QLineEdit,
        "research.notebook_manager_dialog.assignment.target_workspace",
    )
    current = dialog.findChild(
        QLineEdit,
        "research.notebook_manager_dialog.assignment.current_assignment",
    )

    assert table.columnCount() == 2
    assert tuple(table.horizontalHeaderItem(column).text() for column in range(2)) == (
        "Workspace Snapshot",
        "Current Notebook",
    )
    assert table.selectionBehavior() == QAbstractItemView.SelectRows
    assert table.selectionMode() == QAbstractItemView.SingleSelection
    assert table.editTriggers() == QAbstractItemView.NoEditTriggers
    assert table.verticalHeader().isHidden()
    assert table.currentRow() == -1
    assert table.item(0, 0).data(Qt.UserRole) == "workspace_one"
    assert table.item(0, 1).data(Qt.UserRole) == "workspace_one"
    assert selected.text() == ""
    assert target.text() == ""
    assert current.text() == ""
    assert action.text() == "Assign Notebook"
    assert not action.isEnabled()

    _set_checked(dialog, 0)
    assert selected.text() == "Notebook One"
    table.setCurrentCell(0, 0)
    assert target.text() == "Workspace One"
    assert current.text() == "Unassigned"
    assert action.text() == "Assign Notebook"
    assert action.isEnabled()


def test_manager_assign_replace_and_unassign_actions(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    first = _valid_summary("notebook_one", "Notebook One")
    second = _valid_summary("notebook_two", "Notebook Two")
    dialog = ResearchNotebookManagerDialog(
        (first, second),
        assignments=(
            ResearchNotebookSnapshotAssignment(
                "workspace_one", "Workspace One", None
            ),
        ),
    )
    table = dialog._assignment_table
    action = dialog._assignment_action
    assigned = QSignalSpy(dialog.assign_requested)
    unassigned = QSignalSpy(dialog.unassign_requested)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unassigned Workspace must not require confirmation")
        ),
    )
    _set_checked(dialog, 0)
    table.setCurrentCell(0, 0)
    action.click()
    assert assigned.count() == 1
    assert assigned.at(0) == ["notebook_one", "workspace_one"]

    dialog.set_assignments(
        (
            ResearchNotebookSnapshotAssignment(
                "workspace_one", "Workspace One", "notebook_two"
            ),
        )
    )
    assert action.text() == "Replace Assignment"
    messages: list[tuple[str, str]] = []
    answers = iter((QMessageBox.No, QMessageBox.Yes))

    def confirm_replace(_parent, title, message, *_args):
        messages.append((title, message))
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", confirm_replace)
    action.click()
    action.click()
    assert assigned.count() == 2
    assert assigned.at(1) == ["notebook_one", "workspace_one"]
    assert messages[0][0] == "Replace Notebook Assignment"
    assert all(
        text in messages[0][1]
        for text in ("Workspace One", "Notebook Two", "Notebook One")
    )

    dialog.set_assignments(
        (
            ResearchNotebookSnapshotAssignment(
                "workspace_one", "Workspace One", "notebook_one"
            ),
        )
    )
    assert action.text() == "Unassign Notebook"
    messages.clear()
    answers = iter((QMessageBox.No, QMessageBox.Yes))
    action.click()
    action.click()
    assert unassigned.count() == 1
    assert unassigned.at(0) == ["notebook_one", "workspace_one"]
    assert messages[0][0] == "Unassign Notebook"
    assert "Notebook One" in messages[0][1]
    assert "Workspace One" in messages[0][1]


def test_manager_assignment_refresh_preserves_or_clears_explicit_target() -> None:
    QApplication.instance() or QApplication([])
    first = ResearchNotebookSnapshotAssignment(
        "workspace_one", "Workspace One", None
    )
    second = ResearchNotebookSnapshotAssignment(
        "workspace_two", "Workspace Two", None
    )
    dialog = ResearchNotebookManagerDialog(
        (_valid_summary("notebook_one", "Notebook One"),),
        assignments=(first, second),
    )
    dialog._assignment_table.setCurrentCell(1, 0)

    dialog.set_assignments((second, first))
    assert dialog._selected_snapshot_id() == "workspace_two"

    dialog.set_assignments((first,))
    assert dialog._assignment_table.currentRow() == -1
    assert dialog._selected_snapshot_id() is None
    assert not dialog._assignment_action.isEnabled()


def test_manager_delete_requires_explicit_confirmation(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    dialog = ResearchNotebookManagerDialog((_summary(True),))
    emitted: list[str] = []
    dialog.delete_requested.connect(emitted.append)
    delete_button = dialog.findChild(
        QPushButton, "research.notebook_manager_dialog.button.delete"
    )
    answers = iter((QMessageBox.No, QMessageBox.Yes))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )

    _set_checked(dialog, 0)
    delete_button.click()
    delete_button.click()

    assert emitted == ["notebook_one"]
