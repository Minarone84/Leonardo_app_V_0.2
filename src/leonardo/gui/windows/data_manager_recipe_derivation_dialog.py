"""Study Environment to portable Recipe derivation presentation."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
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
    DataManagerRecipeDerivationPlan,
    DataManagerRecipePersistenceResult,
    DataManagerStudyEntryPortability,
    DataManagerStudyEnvironmentInspection,
)
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID = (
    "data_manager.recipe_derivation.window"
)
_SELECTABLE_STATUSES = {"PORTABLE", "PORTABLE_WITH_DEPENDENCIES"}
_STUDY_COLUMNS = (
    "Select",
    "Study",
    "Tool",
    "Kind",
    "Mode",
    "Status",
    "Dependencies",
    "Reason",
)
_PREVIEW_COLUMNS = (
    "Role",
    "Study",
    "Tool",
    "Kind",
    "Dependencies",
    "Result",
    "Recipe ID",
)


class DataManagerRecipeDerivationDialog(QDialog):
    """Collect explicit Recipe roots and present the canonical backend plan."""

    preview_requested = Signal(str, object)
    create_requested = Signal(str, object, bool, str, str)
    closing = Signal()

    def __init__(
        self,
        inspection: DataManagerStudyEnvironmentInspection,
        *,
        existing_recipe_ids: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(inspection, DataManagerStudyEnvironmentInspection):
            raise TypeError(
                "inspection must be a DataManagerStudyEnvironmentInspection"
            )
        super().__init__(parent)
        self._inspection = inspection
        self._entries: tuple[DataManagerStudyEntryPortability, ...] = ()
        self._existing_recipe_ids = frozenset(str(item) for item in existing_recipe_ids)
        self._reviewed_plan: DataManagerRecipeDerivationPlan | None = None
        self._busy = False
        self._populating = False

        apply_identity(
            self,
            DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID,
            object_type="window",
        )
        self.setWindowTitle("Derive Recipes")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.addWidget(self._build_environment_summary())

        studies = QGroupBox("Study roots", self)
        studies_layout = QVBoxLayout(studies)
        selection_actions = QHBoxLayout()
        self.select_all_button = QPushButton("Select All", studies)
        self.select_all_button.setObjectName(
            "data_manager.recipe_derivation.action.select_all"
        )
        self.deselect_all_button = QPushButton("Deselect All", studies)
        self.deselect_all_button.setObjectName(
            "data_manager.recipe_derivation.action.deselect_all"
        )
        selection_actions.addWidget(self.select_all_button)
        selection_actions.addWidget(self.deselect_all_button)
        selection_actions.addStretch(1)
        studies_layout.addLayout(selection_actions)
        self.study_table = configure_table(
            QTableWidget(studies),
            object_id="data_manager.recipe_derivation.table.studies",
            columns=_STUDY_COLUMNS,
            labels=_STUDY_COLUMNS,
        )
        self.study_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.study_table.itemChanged.connect(self._on_study_item_changed)
        studies_layout.addWidget(self.study_table)
        root.addWidget(studies, 1)

        preview_group = QGroupBox("Preview", self)
        preview_layout = QVBoxLayout(preview_group)
        self.preview_table = configure_table(
            QTableWidget(preview_group),
            object_id="data_manager.recipe_derivation.table.preview",
            columns=_PREVIEW_COLUMNS,
            labels=_PREVIEW_COLUMNS,
        )
        self.preview_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        preview_layout.addWidget(self.preview_table)
        self.blockers_label = QLabel("", preview_group)
        self.blockers_label.setObjectName(
            "data_manager.recipe_derivation.blockers"
        )
        self.blockers_label.setWordWrap(True)
        preview_layout.addWidget(self.blockers_label)
        root.addWidget(preview_group, 1)

        collection = QGroupBox("Recipe Collection", self)
        collection_layout = QFormLayout(collection)
        self.collection_checkbox = QCheckBox(
            "Save as Recipe Collection", collection
        )
        self.collection_checkbox.setObjectName(
            "data_manager.recipe_derivation.collection.enabled"
        )
        collection_layout.addRow(self.collection_checkbox)
        self.collection_name = QLineEdit(collection)
        self.collection_name.setObjectName(
            "data_manager.recipe_derivation.collection.name"
        )
        collection_layout.addRow("Name", self.collection_name)
        self.collection_description = QLineEdit(collection)
        self.collection_description.setObjectName(
            "data_manager.recipe_derivation.collection.description"
        )
        collection_layout.addRow("Description", self.collection_description)
        collection.setMinimumHeight(collection.sizeHint().height() + 12)
        root.addWidget(collection)

        self.status_label = QLabel("Select one or more portable Study roots.", self)
        self.status_label.setObjectName("data_manager.recipe_derivation.status")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = QPushButton("Preview", self)
        self.preview_button.setObjectName(
            "data_manager.recipe_derivation.action.preview"
        )
        self.create_button = QPushButton("Create Recipes", self)
        self.create_button.setObjectName(
            "data_manager.recipe_derivation.action.create"
        )
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "data_manager.recipe_derivation.action.close"
        )
        actions.addWidget(self.preview_button)
        actions.addWidget(self.create_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.preview_button.clicked.connect(self._emit_preview)
        self.create_button.clicked.connect(self._emit_create)
        self.close_button.clicked.connect(self.close)
        self.select_all_button.clicked.connect(self._select_all_roots)
        self.deselect_all_button.clicked.connect(self._deselect_all_roots)
        self.collection_checkbox.toggled.connect(self._sync_controls)
        self.collection_name.textChanged.connect(self._sync_controls)
        self.collection_description.textChanged.connect(self._sync_controls)

        self.set_inspection(
            inspection,
            existing_recipe_ids=self._existing_recipe_ids,
        )
        self._set_initial_size(parent)

    @property
    def environment_id(self) -> str:
        return self._inspection.environment.environment_id

    def selected_root_entry_ids(self) -> tuple[str, ...]:
        selected: list[str] = []
        for row, entry in enumerate(self._entries):
            item = self.study_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(entry.entry_id)
        return tuple(selected)

    def set_inspection(
        self,
        inspection: DataManagerStudyEnvironmentInspection,
        *,
        existing_recipe_ids: Iterable[str] = (),
    ) -> None:
        if not isinstance(inspection, DataManagerStudyEnvironmentInspection):
            raise TypeError(
                "inspection must be a DataManagerStudyEnvironmentInspection"
            )
        self._inspection = inspection
        self._entries = inspection.entries
        self._existing_recipe_ids = frozenset(
            str(item) for item in existing_recipe_ids
        )
        environment = inspection.environment
        self.environment_name.setText(environment.display_name)
        self.environment_description.setText(environment.description)
        self.environment_market.setText(
            "" if environment.origin_market_id is None else environment.origin_market_id.as_key()
        )
        self.environment_entry_count.setText(str(environment.entry_count))
        self._populate_studies()
        self.invalidate_preview("Select one or more portable Study roots.")

    def set_existing_recipe_ids(self, recipe_ids: Iterable[str]) -> None:
        self._existing_recipe_ids = frozenset(str(item) for item in recipe_ids)
        if self._reviewed_plan is not None:
            self._populate_preview(self._reviewed_plan)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()

    def set_plan(self, plan: DataManagerRecipeDerivationPlan) -> bool:
        if not isinstance(plan, DataManagerRecipeDerivationPlan):
            raise TypeError("plan must be a DataManagerRecipeDerivationPlan")
        if (
            plan.environment_id != self.environment_id
            or plan.root_entry_ids != self.selected_root_entry_ids()
        ):
            return False
        self._reviewed_plan = plan
        self._populate_preview(plan)
        if plan.blockers:
            self.status_label.setText("Recipe derivation Preview is blocked.")
        else:
            self.status_label.setText(
                f"Preview ready: {len(plan.root_entry_ids)} root; "
                f"{len(plan.support_entry_ids)} support"
            )
        self._sync_controls()
        return True

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._reviewed_plan = None
        self.preview_table.setRowCount(0)
        self.blockers_label.clear()
        self.status_label.setText(message)
        self._sync_controls()

    def settle_success(self, result: DataManagerRecipePersistenceResult) -> None:
        if not isinstance(result, DataManagerRecipePersistenceResult):
            raise TypeError("result must be a DataManagerRecipePersistenceResult")
        if result.environment_id != self.environment_id:
            return
        self._existing_recipe_ids = frozenset(
            (
                *self._existing_recipe_ids,
                *result.root_recipe_ids,
                *result.support_recipe_ids,
            )
        )
        collection = result.collection_id or "None"
        self._reviewed_plan = None
        self.preview_table.setRowCount(0)
        self.blockers_label.clear()
        self.status_label.setText(
            "Recipes created/reused successfully\n"
            f"Roots: {len(result.root_recipe_ids)}\n"
            f"Support: {len(result.support_recipe_ids)}\n"
            f"Collection: {collection}"
        )
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    def _build_environment_summary(self) -> QGroupBox:
        group = QGroupBox("Study Environment", self)
        layout = QFormLayout(group)
        self.environment_name = QLabel("", group)
        self.environment_description = QLabel("", group)
        self.environment_description.setWordWrap(True)
        self.environment_market = QLabel("", group)
        self.environment_entry_count = QLabel("", group)
        layout.addRow("Name", self.environment_name)
        layout.addRow("Description", self.environment_description)
        layout.addRow("Origin Market", self.environment_market)
        layout.addRow("Entry count", self.environment_entry_count)
        return group

    def _populate_studies(self) -> None:
        self._populating = True
        blocker = QSignalBlocker(self.study_table)
        self.study_table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            select_item = QTableWidgetItem("")
            select_item.setCheckState(Qt.CheckState.Unchecked)
            if entry.status in _SELECTABLE_STATUSES:
                select_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                )
            else:
                select_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.study_table.setItem(row, 0, select_item)
            values = (
                entry.display_name,
                entry.tool_key,
                entry.kind,
                entry.mode,
                entry.status,
                ", ".join(entry.dependency_entry_ids),
                entry.reason,
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.study_table.setItem(row, column, item)
        del blocker
        self._populating = False
        resize_data_manager_table(self.study_table)

    def _populate_preview(self, plan: DataManagerRecipeDerivationPlan) -> None:
        classifications = {
            item.entry_id: item for item in plan.entry_classifications
        }
        ordered = (*plan.root_entry_ids, *plan.support_entry_ids)
        self.preview_table.setRowCount(len(ordered))
        root_ids = set(plan.root_entry_ids)
        for row, entry_id in enumerate(ordered):
            role = "Root" if entry_id in root_ids else "Support"
            entry = classifications.get(entry_id)
            if entry is None:
                values = (role, entry_id, "", "", "", "", "")
            else:
                recipe_id = entry.recipe_id or ""
                result = (
                    "Existing"
                    if recipe_id in self._existing_recipe_ids
                    else "New"
                ) if recipe_id else ""
                values = (
                    role,
                    entry.display_name,
                    entry.tool_key,
                    entry.kind,
                    ", ".join(entry.dependency_entry_ids),
                    result,
                    recipe_id,
                )
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        self.blockers_label.setText("\n".join(plan.blockers))
        resize_data_manager_table(self.preview_table)

    def _on_study_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() != 0:
            return
        self.invalidate_preview("Root selection changed. Preview again.")

    def _select_all_roots(self) -> None:
        self._set_bulk_root_selection(select_all=True)

    def _deselect_all_roots(self) -> None:
        self._set_bulk_root_selection(select_all=False)

    def _set_bulk_root_selection(self, *, select_all: bool) -> None:
        changed = False
        blocker = QSignalBlocker(self.study_table)
        for row, entry in enumerate(self._entries):
            item = self.study_table.item(row, 0)
            if item is None:
                continue
            should_check = select_all and entry.status in _SELECTABLE_STATUSES
            desired = (
                Qt.CheckState.Checked
                if should_check
                else Qt.CheckState.Unchecked
            )
            if item.checkState() != desired:
                item.setCheckState(desired)
                changed = True
        del blocker
        if changed:
            self.invalidate_preview("Root selection changed. Preview again.")

    def _set_initial_size(self, parent: QWidget | None) -> None:
        screen = parent.screen() if parent is not None else None
        screen = screen or self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.resize(
            int(available.width() * 0.40),
            int(available.height() * 0.60),
        )

    def _emit_preview(self) -> None:
        roots = self.selected_root_entry_ids()
        if roots and not self._busy:
            self.preview_requested.emit(self.environment_id, roots)

    def _emit_create(self) -> None:
        if not self._create_is_enabled():
            return
        self.create_requested.emit(
            self.environment_id,
            self.selected_root_entry_ids(),
            self.collection_checkbox.isChecked(),
            self.collection_name.text(),
            self.collection_description.text(),
        )

    def _create_is_enabled(self) -> bool:
        plan = self._reviewed_plan
        return (
            not self._busy
            and plan is not None
            and not plan.blocked
            and plan.environment_id == self.environment_id
            and plan.root_entry_ids == self.selected_root_entry_ids()
            and self._collection_metadata_is_ready()
        )

    def _collection_metadata_is_ready(self) -> bool:
        if not self.collection_checkbox.isChecked():
            return True
        name = self.collection_name.text()
        description = self.collection_description.text()
        return (
            bool(name)
            and name == name.strip()
            and description == description.strip()
        )

    def _sync_controls(self, *_args: object) -> None:
        roots = self.selected_root_entry_ids()
        collection = self.collection_checkbox.isChecked()
        selectable = any(
            entry.status in _SELECTABLE_STATUSES for entry in self._entries
        )
        self.study_table.setEnabled(not self._busy)
        self.select_all_button.setEnabled(not self._busy and selectable)
        self.deselect_all_button.setEnabled(not self._busy and bool(roots))
        self.preview_button.setEnabled(not self._busy and bool(roots))
        self.collection_checkbox.setEnabled(not self._busy)
        self.collection_name.setEnabled(not self._busy and collection)
        self.collection_description.setEnabled(not self._busy and collection)
        self.create_button.setEnabled(self._create_is_enabled())
