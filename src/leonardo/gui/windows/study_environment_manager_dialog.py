"""Intent-only manager for persisted Study Environments."""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.research import (
    STUDY_DATASET_ROLES,
    StudyEnvironmentCompatibilityReport,
    StudyEnvironmentDraft,
    StudyEnvironmentSummary,
    StudyEnvironmentV1,
    StudyUserMetadata,
)
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size


@dataclass(frozen=True, slots=True)
class StudyEnvironmentTarget:
    slot_id: int
    session_id: str
    label: str
    detached: bool = False


@dataclass(frozen=True, slots=True)
class StudyEnvironmentCompatibilityIntent:
    environment_id: str
    slot_id: int
    session_id: str


@dataclass(frozen=True, slots=True)
class StudyEnvironmentApplyIntent:
    environment_id: str
    slot_id: int
    session_id: str
    mode: str


@dataclass(frozen=True, slots=True)
class StudyEnvironmentMetadataIntent:
    environment_id: str
    draft: StudyEnvironmentDraft


class StudyEnvironmentManagerDialog(QDialog):
    """Display immutable environment projections and emit user intents."""

    refresh_requested = Signal()
    environment_selected = Signal(str)
    compatibility_requested = Signal(object)
    metadata_save_requested = Signal(object)
    apply_requested = Signal(object)
    delete_requested = Signal(str)

    def __init__(
        self,
        summaries: tuple[StudyEnvironmentSummary, ...],
        targets: tuple[StudyEnvironmentTarget, ...],
        parent: QWidget | None = None,
        *,
        mode: str = "manage",
    ) -> None:
        super().__init__(parent)
        if mode not in {"load", "manage"}:
            raise ValueError("mode must be 'load' or 'manage'")
        self._mode = mode
        self.setObjectName("research.environment_manager_dialog")
        self.setWindowTitle(
            "Load Study Environment"
            if mode == "load"
            else "Manage Study Environments"
        )
        self._summaries = tuple(summaries)
        self._environment: StudyEnvironmentV1 | None = None
        self._report: StudyEnvironmentCompatibilityReport | None = None

        self._list = QListWidget(self)
        self._list.setObjectName("research.environment_manager_dialog.list.environments")
        self._name = QLineEdit(self)
        self._name.setObjectName("research.environment_manager_dialog.edit.name")
        self._description = QLineEdit(self)
        self._description.setObjectName("research.environment_manager_dialog.edit.description")
        self._table = QTableWidget(0, 6, self)
        self._table.setObjectName("research.environment_manager_dialog.table.studies")
        self._table.setHorizontalHeaderLabels(
            ("Order", "Study", "Tool", "Important", "Dataset role", "Description")
        )
        self._target = QComboBox(self)
        self._target.setObjectName("research.environment_manager_dialog.combo.target_chart")
        for target in targets:
            suffix = " (detached)" if target.detached else ""
            self._target.addItem(f"{target.label}{suffix}", target)
        self._append = QRadioButton("Append", self)
        self._append.setObjectName("research.environment_manager_dialog.radio.append")
        self._replace = QRadioButton("Replace", self)
        self._replace.setObjectName("research.environment_manager_dialog.radio.replace")
        group = QButtonGroup(self)
        group.addButton(self._append)
        group.addButton(self._replace)
        self._append.setChecked(True)
        self._compatibility = QTextEdit(self)
        self._compatibility.setObjectName("research.environment_manager_dialog.text.compatibility")
        self._compatibility.setReadOnly(True)
        self._refresh = QPushButton("Refresh", self)
        self._refresh.setObjectName("research.environment_manager_dialog.button.refresh")
        self._save = QPushButton("Save Changes", self)
        self._save.setObjectName("research.environment_manager_dialog.button.save_metadata")
        self._save.setVisible(mode == "manage")
        self._apply = QPushButton("Apply", self)
        self._apply.setObjectName("research.environment_manager_dialog.button.apply")
        self._delete = QPushButton("Delete", self)
        self._delete.setObjectName("research.environment_manager_dialog.button.delete")
        self._close = QPushButton("Close", self)
        self._close.setObjectName("research.environment_manager_dialog.button.close")

        modes = QHBoxLayout()
        modes.addWidget(self._target, 1)
        modes.addWidget(self._append)
        modes.addWidget(self._replace)
        buttons = QHBoxLayout()
        for button in (self._refresh, self._save, self._apply, self._delete, self._close):
            buttons.addWidget(button)
        details = QVBoxLayout()
        details.addWidget(QLabel("Name", self))
        details.addWidget(self._name)
        details.addWidget(QLabel("Description", self))
        details.addWidget(self._description)
        details.addWidget(self._table)
        details.addLayout(modes)
        details.addWidget(self._compatibility)
        details.addLayout(buttons)
        body = QHBoxLayout()
        body.addWidget(self._list, 13)
        body.addLayout(details, 27)
        self.setLayout(body)

        self._list.currentItemChanged.connect(self._selection_changed)
        self._target.currentIndexChanged.connect(self._request_compatibility)
        self._refresh.clicked.connect(self.refresh_requested.emit)
        self._save.clicked.connect(self._emit_metadata_save)
        self._apply.clicked.connect(self._emit_apply)
        self._delete.clicked.connect(self._confirm_delete)
        self._close.clicked.connect(self.reject)
        self._table.itemChanged.connect(self._resize_study_columns)
        self._name.setReadOnly(mode == "load")
        self._description.setReadOnly(mode == "load")
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=1 / 2,
            height_fraction=1 / 2,
        )
        self.set_summaries(self._summaries)

    @property
    def selected_environment_id(self) -> str | None:
        item = self._list.currentItem()
        value = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    @property
    def environment(self) -> StudyEnvironmentV1 | None:
        return self._environment

    def set_summaries(self, summaries: tuple[StudyEnvironmentSummary, ...]) -> None:
        selected = self.selected_environment_id
        self._summaries = tuple(summaries)
        self._list.clear()
        for summary in self._summaries:
            label = summary.display_name
            if not summary.valid:
                label = f"Invalid: {summary.environment_id} - {summary.rejection_reason}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, summary.environment_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, summary.valid)
            self._list.addItem(item)
            if summary.environment_id == selected:
                self._list.setCurrentItem(item)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        self._sync_enabled()

    def set_environment(self, environment: StudyEnvironmentV1) -> None:
        if not isinstance(environment, StudyEnvironmentV1):
            raise TypeError("environment must be StudyEnvironmentV1")
        if environment.environment_id != self.selected_environment_id:
            return
        self._environment = environment
        self._report = None
        self._name.setText(environment.display_name)
        self._description.setText(environment.description)
        self._table.setRowCount(len(environment.entries))
        for row, entry in enumerate(environment.entries):
            for column, value in enumerate(
                (str(row + 1), entry.display_name, f"{entry.kind} / {entry.tool_key}")
            ):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, column, item)
            important = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if self._mode == "manage":
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            important.setFlags(flags)
            important.setCheckState(
                Qt.CheckState.Checked if entry.user_metadata.important else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, 3, important)
            role = QComboBox(self._table)
            for value in STUDY_DATASET_ROLES:
                role.addItem(value.replace("_", " ").title(), value)
            role.setCurrentIndex(role.findData(entry.user_metadata.dataset_role))
            role.setEnabled(self._mode == "manage")
            role.currentIndexChanged.connect(self._resize_study_columns)
            self._table.setCellWidget(row, 4, role)
            description = QTableWidgetItem(entry.user_metadata.description)
            if self._mode == "load":
                description.setFlags(
                    description.flags() & ~Qt.ItemFlag.ItemIsEditable
                )
            self._table.setItem(row, 5, description)
        self._resize_study_columns()
        self._compatibility.setPlainText("Compatibility not checked")
        self._sync_enabled()
        self._request_compatibility()

    def set_compatibility(
        self,
        intent: StudyEnvironmentCompatibilityIntent,
        report: StudyEnvironmentCompatibilityReport,
    ) -> None:
        current = self.current_compatibility_intent()
        if current != intent or report.environment_id != intent.environment_id:
            return
        self._report = report
        messages = (*report.blockers, *report.warnings)
        self._compatibility.setPlainText("Compatible" if not messages else "\n".join(messages))
        self._sync_enabled()

    def current_compatibility_intent(self) -> StudyEnvironmentCompatibilityIntent | None:
        environment_id = self.selected_environment_id
        target = self._target.currentData()
        if not isinstance(environment_id, str) or not isinstance(target, StudyEnvironmentTarget):
            return None
        return StudyEnvironmentCompatibilityIntent(
            environment_id, target.slot_id, target.session_id
        )

    def metadata_intent(self) -> StudyEnvironmentMetadataIntent:
        environment = self._environment
        if environment is None or environment.environment_id != self.selected_environment_id:
            raise ValueError("select a valid loaded environment")
        entries = []
        for row, entry in enumerate(environment.entries):
            metadata = StudyUserMetadata(
                self._table.item(row, 3).checkState() == Qt.CheckState.Checked,
                self._table.cellWidget(row, 4).currentData(),
                self._table.item(row, 5).text(),
            )
            entries.append(replace(entry, user_metadata=metadata))
        draft = StudyEnvironmentDraft(
            environment_id=environment.environment_id,
            display_name=self._name.text(),
            description=self._description.text(),
            created_from=environment.created_from,
            entries=tuple(entries),
        )
        return StudyEnvironmentMetadataIntent(environment.environment_id, draft)

    def _selection_changed(self, current, _previous) -> None:
        self._environment = None
        self._report = None
        self._table.setRowCount(0)
        self._compatibility.clear()
        if current is not None:
            environment_id = current.data(Qt.ItemDataRole.UserRole)
            valid = current.data(Qt.ItemDataRole.UserRole + 1)
            summary = next(
                (item for item in self._summaries if item.environment_id == environment_id),
                None,
            )
            self._name.setText("" if summary is None else summary.display_name)
            self._description.setText("" if summary is None else summary.description)
            if valid:
                self.environment_selected.emit(environment_id)
            elif summary is not None:
                self._compatibility.setPlainText(summary.rejection_reason or "Invalid environment")
        self._sync_enabled()

    def _request_compatibility(self, *_args) -> None:
        self._report = None
        intent = self.current_compatibility_intent()
        if intent is not None and self._environment is not None:
            self._compatibility.setPlainText("Checking compatibility...")
            self.compatibility_requested.emit(intent)
        self._sync_enabled()

    def _emit_metadata_save(self) -> None:
        if self._mode != "manage":
            return
        try:
            intent = self.metadata_intent()
        except (TypeError, ValueError):
            return
        self.metadata_save_requested.emit(intent)

    def _emit_apply(self) -> None:
        intent = self.current_compatibility_intent()
        if intent is None or self._report is None or not self._report.compatible:
            return
        self.apply_requested.emit(
            StudyEnvironmentApplyIntent(
                intent.environment_id,
                intent.slot_id,
                intent.session_id,
                "replace" if self._replace.isChecked() else "append",
            )
        )

    def _confirm_delete(self) -> None:
        environment_id = self.selected_environment_id
        if environment_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Study Environment",
            "Delete only the selected Study Environment?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(environment_id)

    def _sync_enabled(self) -> None:
        item = self._list.currentItem()
        valid = bool(item is not None and item.data(Qt.ItemDataRole.UserRole + 1))
        loaded = valid and self._environment is not None
        self._name.setEnabled(loaded)
        self._description.setEnabled(loaded)
        self._table.setEnabled(loaded)
        self._save.setEnabled(loaded)
        self._delete.setEnabled(item is not None)
        self._apply.setEnabled(
            loaded and self._report is not None and self._report.compatible
        )

    def _resize_study_columns(self, *_args) -> None:
        resize_table_columns_to_contents(
            self._table,
            {4: 1.20, 5: 3.00},
        )


EnvironmentApplyIntent = StudyEnvironmentApplyIntent
EnvironmentCompatibilityIntent = StudyEnvironmentCompatibilityIntent
EnvironmentManagerDialog = StudyEnvironmentManagerDialog
EnvironmentMetadataIntent = StudyEnvironmentMetadataIntent
EnvironmentTarget = StudyEnvironmentTarget
