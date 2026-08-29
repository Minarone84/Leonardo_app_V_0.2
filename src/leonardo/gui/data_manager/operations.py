"""Shared Data Manager operation-state presentation."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


class DataManagerOperationSurface(QGroupBox):
    """Keep one visible operation report until explicitly replaced or cleared."""

    cancel_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Operation", parent)
        apply_identity(self, "data_manager.operation.surface", object_type="group_box")
        self._name = QLabel("None", self)
        self._task_id = QLabel("", self)
        self._state = QLabel("idle", self)
        self._context = QLabel("", self)
        self._status = QLabel("", self)
        self._message = QLabel("", self)
        self._notes = QLabel("", self)
        self._context.setWordWrap(True)
        self._status.setWordWrap(True)
        self._message.setWordWrap(True)
        self._notes.setWordWrap(True)
        self._notes.setTextInteractionFlags(
            self._notes.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._notes.hide()
        for widget, object_id in (
            (self._name, "data_manager.operation.name"),
            (self._task_id, "data_manager.operation.task_id"),
            (self._state, "data_manager.operation.state"),
            (self._context, "data_manager.operation.context"),
            (self._status, "data_manager.operation.status"),
            (self._message, "data_manager.operation.message"),
            (self._notes, "data_manager.operation.notes"),
        ):
            apply_identity(widget, object_id, object_type="label")

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 1)
        apply_identity(
            self.progress,
            "data_manager.operation.progress",
            object_type="progress_bar",
        )
        self.details = configure_table(
            QTableWidget(self),
            object_id="data_manager.operation.details",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.details.setMaximumHeight(130)

        self.cancel_button = QPushButton("Cancel", self)
        apply_identity(
            self.cancel_button,
            "data_manager.button.cancel_operation",
            object_type="button",
            action_id="data_manager.button.cancel_operation",
        )
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.clear_button = QPushButton("Clear", self)
        apply_identity(
            self.clear_button,
            "data_manager.operation.button.clear",
            object_type="button",
            action_id="data_manager.operation.button.clear",
        )
        self.clear_button.clicked.connect(self.clear)

        form = QFormLayout()
        form.addRow("Operation", self._name)
        form.addRow("Task ID", self._task_id)
        form.addRow("State", self._state)
        form.addRow("Context", self._context)
        form.addRow("Status", self._status)
        form.addRow("Message", self._message)
        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.details)
        layout.addWidget(self._notes)
        layout.addLayout(buttons)
        self.cancel_button.setEnabled(False)

    @property
    def state(self) -> str:
        return self._state.text()

    def set_context(self, message: str) -> None:
        self._context.setText(message)

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def context_text(self) -> str:
        return self._context.text()

    def status_text(self) -> str:
        return self._status.text()

    def notes_text(self) -> str:
        return self._notes.text()

    def begin(self, operation: str) -> None:
        self._name.setText(operation)
        self._task_id.clear()
        self._state.setText("running")
        self._message.setText("Operation submitted")
        self.progress.setRange(0, 0)
        self.details.setRowCount(0)
        self.cancel_button.setEnabled(True)

    def set_task_id(self, task_id: str) -> None:
        self._task_id.setText(task_id)

    def set_progress(
        self, current: int | None, total: int | None, message: str = ""
    ) -> None:
        if total is None or total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(max(0, min(total, current or 0)))
        if message:
            self._message.setText(message)

    def settle(
        self,
        state: str,
        message: str,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._state.setText(state)
        self._message.setText(message)
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if state == "completed" else 0)
        self.cancel_button.setEnabled(False)
        self.details.setRowCount(len(details))
        for row, (name, value) in enumerate(details):
            self.details.setItem(row, 0, QTableWidgetItem(name))
            self.details.setItem(row, 1, QTableWidgetItem(value))
        resize_data_manager_table(self.details)

    def append(self, message: str) -> None:
        current = self._notes.text()
        self._notes.setText(f"{current}\n{message}" if current else message)
        self._notes.setVisible(bool(self._notes.text()))

    def clear(self) -> None:
        self._name.setText("None")
        self._task_id.clear()
        self._state.setText("idle")
        self._message.clear()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.details.setRowCount(0)
        self._notes.clear()
        self._notes.hide()
        self.cancel_button.setEnabled(False)
        self.clear_requested.emit()
