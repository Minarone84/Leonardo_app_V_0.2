"""Read-only Duplicate Maintenance scan results."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager.models import (
    DuplicateMaintenancePurgeResult,
    DuplicateMaintenanceScanResult,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_datetime,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DUPLICATE_MAINTENANCE_RESULTS_WINDOW_ID = (
    "data_manager.duplicate_maintenance.results.dialog"
)
_RESULT_COLUMNS = (
    "Status",
    "Canonical",
    "Duplicate",
    "Reason",
    "Dependency / Blocker",
)
_RECIPE_RESULT_COLUMNS = (
    "Status",
    "Canonical Recipe ID",
    "Duplicate Recipe ID",
    "Tool",
    "Parameters",
    "Reason",
    "Dependency / Blocker",
)


class DataManagerDuplicateMaintenanceResultsDialog(QDialog):
    """Present duplicate classifications and one explicit purge action."""

    closing = Signal()
    purge_requested = Signal(object)

    def __init__(
        self,
        result: DuplicateMaintenanceScanResult | DuplicateMaintenancePurgeResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._closing_emitted = False
        self._labels: dict[str, QLabel] = {}
        apply_identity(
            self,
            DATA_MANAGER_DUPLICATE_MAINTENANCE_RESULTS_WINDOW_ID,
            object_type="dialog",
        )
        self.setWindowTitle("Duplicate Maintenance Results")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=0.7,
            height_fraction=0.65,
        )

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._form_labels: dict[str, QWidget] = {}
        for key, label in (
            ("domain", "Domain"),
            ("scope", "Scope"),
            ("timestamp", "Scan timestamp"),
            ("objects", "Objects scanned"),
            ("groups", "Duplicate groups"),
            ("duplicates", "Duplicate objects"),
            ("safe", "Safe to purge"),
            ("blocked", "Blocked"),
            ("invalid", "Invalid / skipped"),
            ("review", "Review required"),
            ("historical", "Historical versions excluded"),
            ("candidates", "Candidates"),
            ("purged", "Purged"),
            ("skipped", "Skipped stale"),
            ("failed", "Failed"),
            ("winners", "Canonical winners retained"),
        ):
            value = QLabel(self)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            apply_identity(
                value,
                f"data_manager.duplicate_maintenance.results.label.{key}",
                object_type="label",
            )
            self._labels[key] = value
            form.addRow(f"{label}:", value)
            self._form_labels[key] = form.labelForField(value)
        root.addLayout(form)

        self.empty_label = QLabel("No semantic duplicates found.", self)
        apply_identity(
            self.empty_label,
            "data_manager.duplicate_maintenance.results.label.empty",
            object_type="status_label",
        )
        root.addWidget(self.empty_label)
        self.table = configure_table(
            QTableWidget(self),
            object_id="data_manager.duplicate_maintenance.results.table",
            columns=_RESULT_COLUMNS,
            labels=_RESULT_COLUMNS,
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.purge_button = QPushButton("Purge Safe Duplicates...", self)
        apply_identity(
            self.purge_button,
            "data_manager.duplicate_maintenance.results.button.purge",
            object_type="button",
            display_label="Purge Safe Duplicates...",
            action_id="data_manager.duplicate_maintenance.results.button.purge",
        )
        self.purge_button.clicked.connect(
            lambda: self.purge_requested.emit(self._result)
        )
        actions.addWidget(self.purge_button)
        self.close_button = QPushButton("Close", self)
        apply_identity(
            self.close_button,
            "data_manager.duplicate_maintenance.results.button.close",
            object_type="button",
            display_label="Close",
            action_id="data_manager.duplicate_maintenance.results.button.close",
        )
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        self.set_result(result)

    @property
    def result(
        self,
    ) -> DuplicateMaintenanceScanResult | DuplicateMaintenancePurgeResult:
        return self._result

    def label_text(self, key: str) -> str:
        return self._labels[key].text()

    def set_result(
        self,
        result: DuplicateMaintenanceScanResult | DuplicateMaintenancePurgeResult,
    ) -> None:
        if not isinstance(
            result, (DuplicateMaintenanceScanResult, DuplicateMaintenancePurgeResult)
        ):
            raise TypeError("result must be a duplicate maintenance result")
        self._result = result
        if isinstance(result, DuplicateMaintenancePurgeResult):
            self._set_purge_result(result)
            return
        self.setWindowTitle("Duplicate Maintenance Results")
        values = {
            "domain": result.preflight.domain.display_name,
            "scope": result.preflight.scope_label,
            "timestamp": format_utc_datetime(result.scanned_at_utc),
            "objects": str(result.objects_scanned),
            "groups": str(len(result.groups)),
            "duplicates": str(result.duplicate_objects),
            "safe": str(result.safe_to_purge),
            "blocked": str(result.blocked),
            "invalid": str(result.invalid_skipped),
            "review": str(result.review_required),
            "historical": str(result.historical_versions_excluded),
        }
        self._set_visible_fields(
            {
                "domain",
                "scope",
                "timestamp",
                "objects",
                "groups",
                "duplicates",
                "safe",
                "blocked",
                "invalid",
                "review",
                "historical",
            }
        )
        for key, value in values.items():
            self._labels[key].setText(value)
        historical = self._labels["historical"]
        historical.setVisible(result.preflight.domain.key == "artifacts")
        form_label = self.layout().itemAt(0).layout().labelForField(historical)
        if form_label is not None:
            form_label.setVisible(result.preflight.domain.key == "artifacts")

        recipe_result = result.preflight.domain.key == "recipes"
        self._set_result_columns(recipe_result)
        if recipe_result:
            rows = [
                (
                    candidate.classification,
                    group.canonical_id,
                    candidate.object_id,
                    group.tool_key,
                    group.parameters_label,
                    f"{group.semantic_reason}: {candidate.reason}",
                    ", ".join(candidate.blockers),
                )
                for group in result.groups
                for candidate in group.duplicates
            ]
            rows.extend(
                (
                    candidate.classification,
                    "",
                    candidate.object_id,
                    "",
                    "",
                    candidate.reason,
                    "",
                )
                for candidate in result.invalid_candidates
            )
        else:
            rows = [
                (
                    candidate.classification,
                    group.canonical_id or "Not established",
                    candidate.object_id,
                    f"{group.semantic_reason}: {candidate.reason}",
                    ", ".join(candidate.blockers),
                )
                for group in result.groups
                for candidate in group.duplicates
            ]
            rows.extend(
                (
                    candidate.classification,
                    "",
                    candidate.object_id,
                    candidate.reason,
                    "",
                )
                for candidate in result.invalid_candidates
            )
        self.table.setRowCount(len(rows))
        for row, values_row in enumerate(rows):
            for column, value in enumerate(values_row):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.empty_label.setVisible(not result.groups)
        self.empty_label.setText("No semantic duplicates found.")
        self.table.setVisible(bool(rows))
        self.purge_button.setVisible(True)
        self.purge_button.setEnabled(result.safe_to_purge > 0)
        resize_data_manager_table(self.table)

    def _set_purge_result(self, result: DuplicateMaintenancePurgeResult) -> None:
        self.setWindowTitle("Duplicate Maintenance Complete")
        self._set_visible_fields(
            {
                "domain",
                "scope",
                "candidates",
                "purged",
                "blocked",
                "skipped",
                "failed",
                "winners",
            }
        )
        values = {
            "domain": result.scan.preflight.domain.display_name,
            "scope": result.scan.preflight.scope_label,
            "candidates": str(result.candidates_requested),
            "purged": str(result.purged),
            "blocked": str(result.blocked_during_revalidation),
            "skipped": str(result.skipped_stale),
            "failed": str(result.failed),
            "winners": str(result.canonical_winners_retained),
        }
        for key, value in values.items():
            self._labels[key].setText(value)
        recipe_result = result.scan.preflight.domain.key == "recipes"
        self._set_result_columns(recipe_result)
        if recipe_result:
            groups = {
                candidate.object_id: group
                for group in result.scan.groups
                for candidate in group.duplicates
            }
            rows = tuple(
                (
                    item.result,
                    item.winner_id,
                    item.candidate_id,
                    groups[item.candidate_id].tool_key,
                    groups[item.candidate_id].parameters_label,
                    item.reason,
                    "",
                )
                for item in result.details
            )
        else:
            rows = tuple(
                (
                    item.result,
                    item.winner_id,
                    item.candidate_id,
                    item.reason,
                    "",
                )
                for item in result.details
            )
        self.table.setRowCount(len(rows))
        for row, values_row in enumerate(rows):
            for column, value in enumerate(values_row):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.empty_label.setText("No duplicate objects were deleted.")
        self.empty_label.setVisible(result.purged == 0)
        self.table.setVisible(bool(rows))
        self.purge_button.setEnabled(False)
        self.purge_button.setVisible(False)
        resize_data_manager_table(self.table)

    def _set_result_columns(self, recipe_result: bool) -> None:
        columns = _RECIPE_RESULT_COLUMNS if recipe_result else _RESULT_COLUMNS
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

    def _set_visible_fields(self, visible: set[str]) -> None:
        for key, label in self._labels.items():
            show = key in visible
            label.setVisible(show)
            self._form_labels[key].setVisible(show)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._closing_emitted:
            self._closing_emitted = True
            self.closing.emit()
        super().closeEvent(event)
