"""Intent-only dialog for creating or updating a Study Environment."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.research import (
    STUDY_DATASET_ROLES,
    ChartStudy,
    StudyEnvironmentSummary,
    StudyUserMetadata,
)


@dataclass(frozen=True, slots=True)
class StudyEnvironmentSaveIntent:
    slot_id: int
    session_id: str
    mode: str
    environment_id: str | None
    display_name: str
    description: str
    metadata_overrides: tuple[tuple[str, StudyUserMetadata], ...]


class StudyEnvironmentSaveDialog(QDialog):
    """Edit only environment metadata over a captured chart snapshot."""

    save_requested = Signal(object)

    def __init__(
        self,
        slot_id: int,
        session_id: str,
        studies: tuple[ChartStudy, ...],
        summaries: tuple[StudyEnvironmentSummary, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if type(slot_id) is not int or slot_id <= 0:
            raise ValueError("slot_id must be positive")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be text")
        self.setObjectName("research.environment_save_dialog")
        self.setWindowTitle("Save Study Environment")
        self._slot_id = slot_id
        self._session_id = session_id
        self._studies = tuple(studies)
        self._summaries = tuple(summaries)
        self._intent: StudyEnvironmentSaveIntent | None = None

        self._create = QRadioButton("Create", self)
        self._create.setObjectName("research.environment_save_dialog.radio.create")
        self._update = QRadioButton("Update", self)
        self._update.setObjectName("research.environment_save_dialog.radio.update")
        group = QButtonGroup(self)
        group.addButton(self._create)
        group.addButton(self._update)
        self._create.setChecked(True)
        self._existing = QComboBox(self)
        self._existing.setObjectName("research.environment_save_dialog.combo.existing")
        for summary in self._summaries:
            if summary.valid:
                self._existing.addItem(summary.display_name, summary.environment_id)
        self._name = QLineEdit(self)
        self._name.setObjectName("research.environment_save_dialog.edit.name")
        self._description = QLineEdit(self)
        self._description.setObjectName("research.environment_save_dialog.edit.description")
        self._table = QTableWidget(len(self._studies), 7, self)
        self._table.setObjectName("research.environment_save_dialog.table.studies")
        self._table.setHorizontalHeaderLabels(
            ("Order", "Display name", "Kind / tool", "Parameters", "Important", "Dataset role", "Description")
        )
        self._populate_studies()
        self._validation = QLabel(self)
        self._validation.setObjectName("research.environment_save_dialog.label.validation")
        self._save = QPushButton("Save", self)
        self._save.setObjectName("research.environment_save_dialog.button.save")
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setObjectName("research.environment_save_dialog.button.cancel")

        modes = QHBoxLayout()
        modes.addWidget(self._create)
        modes.addWidget(self._update)
        modes.addWidget(self._existing, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._save)
        buttons.addWidget(self._cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(modes)
        layout.addWidget(self._name)
        layout.addWidget(self._description)
        layout.addWidget(self._table)
        layout.addWidget(self._validation)
        layout.addLayout(buttons)

        self._create.toggled.connect(self._sync_mode)
        self._update.toggled.connect(self._sync_mode)
        self._existing.currentIndexChanged.connect(self._existing_changed)
        self._name.textChanged.connect(self._validate)
        self._description.textChanged.connect(self._validate)
        self._table.itemChanged.connect(self._validate)
        self._save.clicked.connect(self._emit_save)
        self._cancel.clicked.connect(self.reject)
        self._sync_mode()

    @property
    def result_intent(self) -> StudyEnvironmentSaveIntent | None:
        return self._intent

    def current_intent(self) -> StudyEnvironmentSaveIntent:
        mode = "update" if self._update.isChecked() else "create"
        environment_id = self._existing.currentData() if mode == "update" else None
        name = self._name.text()
        if not name or name != name.strip():
            raise ValueError("environment name must be canonical non-empty text")
        if mode == "create" and any(
            summary.valid and summary.display_name.casefold() == name.casefold()
            for summary in self._summaries
        ):
            raise ValueError("environment name already exists")
        if mode == "update" and not isinstance(environment_id, str):
            raise ValueError("select a valid environment to update")
        overrides = []
        for row, study in enumerate(self._studies):
            important = self._table.item(row, 4).checkState() == Qt.CheckState.Checked
            role = self._table.cellWidget(row, 5).currentData()
            description = self._table.item(row, 6).text()
            overrides.append(
                (
                    study.study_id,
                    StudyUserMetadata(important, role, description),
                )
            )
        return StudyEnvironmentSaveIntent(
            self._slot_id,
            self._session_id,
            mode,
            environment_id,
            name,
            self._description.text(),
            tuple(overrides),
        )

    def _populate_studies(self) -> None:
        self._table.blockSignals(True)
        for row, study in enumerate(self._studies):
            readonly = (
                str(row + 1),
                study.display_name,
                f"{study.result.kind} / {study.result.tool_key}",
                repr(dict(study.setup_request.parameters))
                if hasattr(study.setup_request, "parameters")
                else "{}",
            )
            for column, value in enumerate(readonly):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, column, item)
            important = QTableWidgetItem()
            important.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            important.setCheckState(
                Qt.CheckState.Checked if study.user_metadata.important else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, 4, important)
            role = QComboBox(self._table)
            for value in STUDY_DATASET_ROLES:
                role.addItem(value.replace("_", " ").title(), value)
            role.setCurrentIndex(role.findData(study.user_metadata.dataset_role))
            role.currentIndexChanged.connect(self._validate)
            self._table.setCellWidget(row, 5, role)
            self._table.setItem(row, 6, QTableWidgetItem(study.user_metadata.description))
        self._table.blockSignals(False)

    def _sync_mode(self, *_args) -> None:
        self._existing.setEnabled(self._update.isChecked())
        if self._update.isChecked():
            self._existing_changed()
        self._validate()

    def _existing_changed(self, *_args) -> None:
        if not self._update.isChecked():
            return
        environment_id = self._existing.currentData()
        summary = next(
            (item for item in self._summaries if item.environment_id == environment_id),
            None,
        )
        if summary is not None:
            self._name.setText(summary.display_name)
            self._description.setText(summary.description)

    def _validate(self, *_args) -> None:
        try:
            self.current_intent()
        except (TypeError, ValueError) as error:
            self._validation.setText(str(error))
            self._save.setEnabled(False)
        else:
            self._validation.setText("Ready")
            self._save.setEnabled(True)

    def _emit_save(self) -> None:
        try:
            intent = self.current_intent()
        except (TypeError, ValueError):
            self._validate()
            return
        self._intent = intent
        self.save_requested.emit(intent)
        self.accept()


EnvironmentSaveDialog = StudyEnvironmentSaveDialog
EnvironmentSaveIntent = StudyEnvironmentSaveIntent
