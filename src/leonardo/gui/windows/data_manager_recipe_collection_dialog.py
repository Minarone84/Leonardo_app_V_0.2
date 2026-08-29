"""Recipe Collection create and immutable-revision edit presentation."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionInspection,
)
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table
from leonardo.recipes import PortableRecipeGraphPlan


DATA_MANAGER_RECIPE_COLLECTION_WINDOW_ID = "data_manager.recipe_collection.window"
_RECIPE_COLUMNS = (
    "Select",
    "Tool",
    "Parameters",
    "Inputs",
    "Outputs",
    "State",
    "Recipe ID",
)
_PREVIEW_COLUMNS = (
    "Role",
    "Tool",
    "Parameters",
    "Inputs",
    "Outputs",
    "Recipe ID",
)


class DataManagerRecipeCollectionDialog(QDialog):
    """Collect Recipe roots and publish only a reviewed canonical closure."""

    preview_requested = Signal(object)
    create_requested = Signal(str, str, object)
    update_requested = Signal(str, str, str, object, str)
    closing = Signal()

    def __init__(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        super().__init__(parent)
        self._snapshot = snapshot
        self._recipes = snapshot.portable_recipes.recipes
        self._reviewed_plan: PortableRecipeGraphPlan | None = None
        self._collection_id: str | None = None
        self._expected_revision_id: str | None = None
        self._busy = False
        self._populating = False

        apply_identity(
            self,
            DATA_MANAGER_RECIPE_COLLECTION_WINDOW_ID,
            object_type="dialog",
        )
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        metadata = QGroupBox("Collection", self)
        metadata_layout = QFormLayout(metadata)
        self.name_input = QLineEdit(metadata)
        self.name_input.setObjectName("data_manager.recipe_collection.input.name")
        self.description_input = QLineEdit(metadata)
        self.description_input.setObjectName(
            "data_manager.recipe_collection.input.description"
        )
        metadata_layout.addRow("Name", self.name_input)
        metadata_layout.addRow("Description", self.description_input)
        root.addWidget(metadata)

        available = QGroupBox("Recipe roots", self)
        available_layout = QVBoxLayout(available)
        selection = QHBoxLayout()
        self.select_all_button = QPushButton("Select All", available)
        self.select_all_button.setObjectName(
            "data_manager.recipe_collection.action.select_all"
        )
        self.deselect_all_button = QPushButton("Deselect All", available)
        self.deselect_all_button.setObjectName(
            "data_manager.recipe_collection.action.deselect_all"
        )
        selection.addWidget(self.select_all_button)
        selection.addWidget(self.deselect_all_button)
        selection.addStretch(1)
        available_layout.addLayout(selection)
        self.recipe_table = configure_table(
            QTableWidget(available),
            object_id="data_manager.recipe_collection.table.recipes",
            columns=_RECIPE_COLUMNS,
            labels=_RECIPE_COLUMNS,
        )
        self.recipe_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.recipe_table.itemChanged.connect(self._on_recipe_item_changed)
        available_layout.addWidget(self.recipe_table)
        root.addWidget(available, 1)

        preview = QGroupBox("Preview", self)
        preview_layout = QVBoxLayout(preview)
        self.preview_table = configure_table(
            QTableWidget(preview),
            object_id="data_manager.recipe_collection.table.preview",
            columns=_PREVIEW_COLUMNS,
            labels=_PREVIEW_COLUMNS,
        )
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        preview_layout.addWidget(self.preview_table)
        self.preview_summary = QLabel("Preview required.", preview)
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setObjectName(
            "data_manager.recipe_collection.label.preview_status"
        )
        preview_layout.addWidget(self.preview_summary)
        root.addWidget(preview, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = QPushButton("Preview", self)
        self.preview_button.setObjectName(
            "data_manager.recipe_collection.action.preview"
        )
        self.publish_button = QPushButton("Create Collection", self)
        self.publish_button.setObjectName(
            "data_manager.recipe_collection.action.publish"
        )
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("data_manager.recipe_collection.action.close")
        actions.addWidget(self.preview_button)
        actions.addWidget(self.publish_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.select_all_button.clicked.connect(self._select_all)
        self.deselect_all_button.clicked.connect(self._deselect_all)
        self.preview_button.clicked.connect(self._emit_preview)
        self.publish_button.clicked.connect(self._emit_publish)
        self.close_button.clicked.connect(self.close)
        self.name_input.textChanged.connect(self._sync_controls)
        self.description_input.textChanged.connect(self._sync_controls)
        self.configure_create(snapshot)

    @property
    def collection_id(self) -> str | None:
        return self._collection_id

    @property
    def expected_revision_id(self) -> str | None:
        return self._expected_revision_id

    @property
    def reviewed_plan(self) -> PortableRecipeGraphPlan | None:
        return self._reviewed_plan

    def selected_root_recipe_ids(self) -> tuple[str, ...]:
        selected: list[str] = []
        for row, recipe in enumerate(self._recipes):
            item = self.recipe_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected.append(recipe.recipe_id)
        return tuple(selected)

    def configure_create(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        self._require_snapshot(snapshot)
        self._snapshot = snapshot
        self._recipes = snapshot.portable_recipes.recipes
        self._collection_id = None
        self._expected_revision_id = None
        self.setWindowTitle("Create Recipe Collection")
        self.publish_button.setText("Create Collection")
        self.name_input.clear()
        self.description_input.clear()
        self._populate_recipes(())
        self.invalidate_preview("Select one or more Recipe roots.")

    def configure_edit(
        self,
        inspection: DataManagerRecipeCollectionInspection,
        snapshot: DataManagerProductCatalogSnapshot,
    ) -> None:
        if not isinstance(inspection, DataManagerRecipeCollectionInspection):
            raise TypeError(
                "inspection must be a DataManagerRecipeCollectionInspection"
            )
        self._require_snapshot(snapshot)
        self._snapshot = snapshot
        self._recipes = snapshot.portable_recipes.recipes
        self._collection_id = inspection.collection.collection_id
        self._expected_revision_id = inspection.collection.revision_id
        self.setWindowTitle("Edit Recipe Collection")
        self.publish_button.setText("Save Revision")
        self.name_input.setText(inspection.collection.display_name)
        self.description_input.setText(inspection.collection.description)
        self._populate_recipes(inspection.root_recipe_ids)
        self.invalidate_preview("Preview the current Recipe roots before saving.")

    def set_catalog(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        self._require_snapshot(snapshot)
        selected = self.selected_root_recipe_ids()
        self._snapshot = snapshot
        self._recipes = snapshot.portable_recipes.recipes
        self._populate_recipes(selected)
        self.invalidate_preview("Recipe catalog changed. Preview again.")

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()

    def set_plan(self, plan: PortableRecipeGraphPlan) -> bool:
        if not isinstance(plan, PortableRecipeGraphPlan):
            raise TypeError("plan must be a PortableRecipeGraphPlan")
        if plan.root_recipe_ids != self.selected_root_recipe_ids():
            return False
        self._reviewed_plan = plan
        self._populate_preview(plan)
        self.preview_summary.setText(
            f"Preview ready: {len(plan.root_recipe_ids)} ROOT; "
            f"{len(plan.member_recipe_ids) - len(plan.root_recipe_ids)} SUPPORT"
        )
        self._sync_controls()
        return True

    def reviewed_plan_matches(self, roots: tuple[str, ...]) -> bool:
        return (
            self._reviewed_plan is not None
            and roots == self.selected_root_recipe_ids()
            and self._reviewed_plan.root_recipe_ids == roots
        )

    def settle_success(
        self,
        inspection: DataManagerRecipeCollectionInspection,
    ) -> None:
        self.configure_edit(inspection, self._snapshot)
        self.preview_summary.setText("Recipe Collection published successfully.")

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._reviewed_plan = None
        self.preview_table.setRowCount(0)
        self.preview_summary.setText(message)
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    @staticmethod
    def _require_snapshot(snapshot: object) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")

    def _populate_recipes(self, selected_ids: tuple[str, ...]) -> None:
        selected = set(selected_ids)
        self._populating = True
        blocker = QSignalBlocker(self.recipe_table)
        self.recipe_table.setRowCount(len(self._recipes))
        for row, recipe in enumerate(self._recipes):
            select_item = QTableWidgetItem("")
            select_item.setCheckState(
                Qt.CheckState.Checked
                if recipe.recipe_id in selected and recipe.valid
                else Qt.CheckState.Unchecked
            )
            select_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                if recipe.valid
                else Qt.ItemFlag.NoItemFlags
            )
            self.recipe_table.setItem(row, 0, select_item)
            values = (
                recipe.tool_key,
                ", ".join(f"{key}={value}" for key, value in recipe.parameters.items()),
                ", ".join(recipe.input_bindings),
                ", ".join(recipe.output_names),
                "valid" if recipe.valid else f"invalid: {recipe.rejection_reason}",
                recipe.recipe_id,
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.recipe_table.setItem(row, column, item)
        del blocker
        self._populating = False
        resize_data_manager_table(self.recipe_table)

    def _populate_preview(self, plan: PortableRecipeGraphPlan) -> None:
        recipes = {item.recipe_id: item for item in self._recipes}
        root_ids = set(plan.root_recipe_ids)
        self.preview_table.setRowCount(len(plan.member_recipe_ids))
        for row, recipe_id in enumerate(plan.member_recipe_ids):
            recipe = recipes.get(recipe_id)
            values = (
                "ROOT" if recipe_id in root_ids else "SUPPORT",
                "" if recipe is None else recipe.tool_key,
                "" if recipe is None else ", ".join(
                    f"{key}={value}" for key, value in recipe.parameters.items()
                ),
                "" if recipe is None else ", ".join(recipe.input_bindings),
                "" if recipe is None else ", ".join(recipe.output_names),
                recipe_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.preview_table.setItem(row, column, item)
        resize_data_manager_table(self.preview_table)

    def _on_recipe_item_changed(self, item: QTableWidgetItem) -> None:
        if not self._populating and item.column() == 0:
            self.invalidate_preview("Root selection changed. Preview again.")

    def _select_all(self) -> None:
        self._set_all(True)

    def _deselect_all(self) -> None:
        self._set_all(False)

    def _set_all(self, selected: bool) -> None:
        changed = False
        blocker = QSignalBlocker(self.recipe_table)
        for row, recipe in enumerate(self._recipes):
            if not recipe.valid:
                continue
            item = self.recipe_table.item(row, 0)
            if item is None:
                continue
            desired = Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
            if item.checkState() != desired:
                item.setCheckState(desired)
                changed = True
        del blocker
        if changed:
            self.invalidate_preview("Root selection changed. Preview again.")

    def _emit_preview(self) -> None:
        roots = self.selected_root_recipe_ids()
        if roots and not self._busy:
            self.preview_requested.emit(roots)

    def _emit_publish(self) -> None:
        roots = self.selected_root_recipe_ids()
        if not self._publish_is_enabled():
            return
        if self._collection_id is None:
            self.create_requested.emit(
                self.name_input.text(), self.description_input.text(), roots
            )
        else:
            self.update_requested.emit(
                self._collection_id,
                self.name_input.text(),
                self.description_input.text(),
                roots,
                self._expected_revision_id or "",
            )

    def _publish_is_enabled(self) -> bool:
        roots = self.selected_root_recipe_ids()
        name = self.name_input.text()
        description = self.description_input.text()
        return (
            not self._busy
            and bool(name)
            and name == name.strip()
            and description == description.strip()
            and bool(roots)
            and self.reviewed_plan_matches(roots)
            and (
                self._collection_id is None
                or bool(self._expected_revision_id)
            )
        )

    def _sync_controls(self, *_args: object) -> None:
        roots = self.selected_root_recipe_ids()
        valid_recipe = any(item.valid for item in self._recipes)
        self.recipe_table.setEnabled(not self._busy)
        self.select_all_button.setEnabled(not self._busy and valid_recipe)
        self.deselect_all_button.setEnabled(not self._busy and bool(roots))
        self.preview_button.setEnabled(not self._busy and bool(roots))
        self.name_input.setEnabled(not self._busy)
        self.description_input.setEnabled(not self._busy)
        self.publish_button.setEnabled(self._publish_is_enabled())
