"""Recipe and Recipe Collection managed Artifact materialization dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationRequest,
    DataManagerArtifactMaterializationResult,
    DataManagerDatasetEntry,
    DataManagerPortableRecipeEntry,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionEntry,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_RECIPE_ARTIFACT_MATERIALIZATION_WINDOW_ID = (
    "data_manager.recipe_artifact_materialization.window"
)
_PREVIEW_COLUMNS = (
    "Tool",
    "Kind",
    "Role",
    "Status",
    "Blockers",
    "Recipe ID",
    "Logical Artifact ID",
    "Current Artifact ID",
    "Previous Artifact ID",
)
_OUTPUT_COLUMNS = (
    "Include",
    "Tool",
    "Output",
    "Column Name",
    "Logical Artifact ID",
)


@dataclass(frozen=True, slots=True)
class _OutputRow:
    included: bool
    tool_key: str
    output_name: str
    column_name: str
    logical_artifact_id: str


class DataManagerRecipeArtifactMaterializationDialog(QDialog):
    """Review and execute one existing portable Recipe source on one dataset."""

    preview_requested = Signal(object)
    execute_requested = Signal(object, bool, str, str, object)
    closing = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: DataManagerProductCatalogSnapshot | None = None
        self._recipe: DataManagerPortableRecipeEntry | None = None
        self._recipe_collection: DataManagerRecipeCollectionEntry | None = None
        self._target_dataset: DataManagerDatasetEntry | None = None
        self._reviewed_plan: DataManagerArtifactMaterializationPlan | None = None
        self._equivalent_collection: ArtifactCollectionRevisionV1 | None = None
        self._collection_prediction_ready = False
        self._materialization_result: DataManagerArtifactMaterializationResult | None = None
        self._source_catalog_available = False
        self._busy = False
        self._populating = False

        apply_identity(
            self,
            DATA_MANAGER_RECIPE_ARTIFACT_MATERIALIZATION_WINDOW_ID,
            object_type="dialog",
        )
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=0.75,
            height_fraction=0.75,
        )

        root = QVBoxLayout(self)
        root.setSpacing(10)
        top_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            top_splitter,
            "data_manager.recipe_artifact_materialization.splitter.top",
            object_type="splitter",
        )
        top_splitter.setChildrenCollapsible(False)

        source = QGroupBox("Source", top_splitter)
        source_layout = QFormLayout(source)
        source_layout.setContentsMargins(12, 24, 12, 12)
        source_layout.setVerticalSpacing(8)
        self.source_labels: dict[str, QLabel] = {}
        for key, label in (
            ("source_type", "Source Type"),
            ("tool", "Tool"),
            ("parameters", "Parameters"),
            ("inputs", "Inputs"),
            ("outputs", "Outputs"),
            ("recipe_id", "Recipe ID"),
            ("name", "Name"),
            ("root_count", "Root count"),
            ("member_count", "Member count"),
            ("collection_id", "Collection ID"),
            ("revision_id", "Revision ID"),
        ):
            value = QLabel("", source)
            value.setWordWrap(True)
            value.setObjectName(
                f"data_manager.recipe_artifact_materialization.label.{key}"
            )
            self.source_labels[key] = value
            source_layout.addRow(label, value)
        self.source_status = QLabel("Source unavailable.", source)
        self.source_status.setWordWrap(True)
        self.source_status.setObjectName(
            "data_manager.recipe_artifact_materialization.label.source_status"
        )
        source_layout.addRow("State", self.source_status)
        source_size_policy = source.sizePolicy()
        source_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        source.setSizePolicy(source_size_policy)
        top_splitter.addWidget(source)

        target = QGroupBox("Target Dataset", top_splitter)
        target_layout = QFormLayout(target)
        target_layout.setContentsMargins(12, 24, 12, 12)
        target_layout.setVerticalSpacing(8)
        self.target_label = QLabel("No accepted dataset selected.", target)
        self.target_label.setWordWrap(True)
        self.target_label.setObjectName(
            "data_manager.recipe_artifact_materialization.label.target"
        )
        target_layout.addRow("MarketId", self.target_label)
        self.target_labels: dict[str, QLabel] = {}
        for key, label in (
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("asset", "Asset"),
            ("timeframe", "Timeframe"),
            ("rows", "Rows"),
            ("first_timestamp", "First timestamp"),
            ("last_timestamp", "Last timestamp"),
        ):
            value = QLabel("", target)
            value.setObjectName(
                f"data_manager.recipe_artifact_materialization.label.target_{key}"
            )
            self.target_labels[key] = value
            target_layout.addRow(label, value)
        target_size_policy = target.sizePolicy()
        target_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        target.setSizePolicy(target_size_policy)
        top_splitter.addWidget(target)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([1, 1])
        root.addWidget(top_splitter)

        bottom_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            bottom_splitter,
            "data_manager.recipe_artifact_materialization.splitter.bottom",
            object_type="splitter",
        )
        bottom_splitter.setChildrenCollapsible(False)

        preview = QGroupBox("Materialization Preview", bottom_splitter)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 24, 12, 12)
        preview_layout.setSpacing(10)
        self.preview_table = configure_table(
            QTableWidget(preview),
            object_id="data_manager.recipe_artifact_materialization.table.preview",
            columns=_PREVIEW_COLUMNS,
            labels=_PREVIEW_COLUMNS,
        )
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        preview_layout.addWidget(self.preview_table)
        self.preview_summary = QLabel("Preview required.", preview)
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setObjectName(
            "data_manager.recipe_artifact_materialization.label.preview_summary"
        )
        preview_layout.addWidget(self.preview_summary)
        preview_size_policy = preview.sizePolicy()
        preview_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        preview.setSizePolicy(preview_size_policy)
        bottom_splitter.addWidget(preview)

        collection = QGroupBox("Optional Artifact Collection", bottom_splitter)
        collection_layout = QVBoxLayout(collection)
        collection_layout.setContentsMargins(12, 24, 12, 12)
        collection_layout.setSpacing(10)
        self.create_collection_checkbox = QCheckBox(
            "Create Artifact Collection", collection
        )
        self.create_collection_checkbox.setObjectName(
            "data_manager.recipe_artifact_materialization.check.create_collection"
        )
        collection_layout.addWidget(self.create_collection_checkbox)
        metadata = QFormLayout()
        metadata.setVerticalSpacing(8)
        self.collection_name_input = QLineEdit(collection)
        self.collection_name_input.setObjectName(
            "data_manager.recipe_artifact_materialization.input.collection_name"
        )
        self.collection_description_input = QLineEdit(collection)
        self.collection_description_input.setObjectName(
            "data_manager.recipe_artifact_materialization.input.collection_description"
        )
        metadata.addRow("Collection Name", self.collection_name_input)
        metadata.addRow("Collection Description", self.collection_description_input)
        collection_layout.addLayout(metadata)
        self.output_table = configure_table(
            QTableWidget(collection),
            object_id="data_manager.recipe_artifact_materialization.table.outputs",
            columns=_OUTPUT_COLUMNS,
            labels=_OUTPUT_COLUMNS,
        )
        self.output_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.output_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        collection_layout.addWidget(self.output_table)
        order = QHBoxLayout()
        order.setSpacing(10)
        self.move_up_button = QPushButton("Move Up", collection)
        self.move_up_button.setObjectName(
            "data_manager.recipe_artifact_materialization.action.move_up"
        )
        self.move_down_button = QPushButton("Move Down", collection)
        self.move_down_button.setObjectName(
            "data_manager.recipe_artifact_materialization.action.move_down"
        )
        order.addWidget(self.move_up_button)
        order.addWidget(self.move_down_button)
        order.addStretch(1)
        collection_layout.addLayout(order)
        collection_size_policy = collection.sizePolicy()
        collection_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        collection.setSizePolicy(collection_size_policy)
        bottom_splitter.addWidget(collection)
        bottom_splitter.setStretchFactor(0, 1)
        bottom_splitter.setStretchFactor(1, 1)
        bottom_splitter.setSizes([1, 1])
        root.addWidget(bottom_splitter, 1)

        self.result_summary = QLabel("", self)
        self.result_summary.setWordWrap(True)
        self.result_summary.setObjectName(
            "data_manager.recipe_artifact_materialization.label.result_summary"
        )
        root.addWidget(self.result_summary)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.preview_button = QPushButton("Preview", self)
        self.preview_button.setObjectName(
            "data_manager.recipe_artifact_materialization.action.preview"
        )
        self.execute_button = QPushButton("Create Artifacts", self)
        self.execute_button.setObjectName(
            "data_manager.recipe_artifact_materialization.action.execute"
        )
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "data_manager.recipe_artifact_materialization.action.close"
        )
        actions.addWidget(self.preview_button)
        actions.addWidget(self.execute_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.preview_button.clicked.connect(self._emit_preview)
        self.execute_button.clicked.connect(self._emit_execute)
        self.close_button.clicked.connect(self.close)
        self.create_collection_checkbox.toggled.connect(self._sync_controls)
        self.collection_name_input.textChanged.connect(self._sync_controls)
        self.collection_description_input.textChanged.connect(self._sync_controls)
        self.output_table.itemChanged.connect(self._on_output_item_changed)
        self.move_up_button.clicked.connect(lambda: self._move_output(-1))
        self.move_down_button.clicked.connect(lambda: self._move_output(1))
        self._sync_controls()

    @property
    def target_market_id(self) -> MarketId | None:
        return None if self._target_dataset is None else self._target_dataset.market_id

    @property
    def reviewed_plan(self) -> DataManagerArtifactMaterializationPlan | None:
        return self._reviewed_plan

    def configure_recipe(
        self,
        recipe: DataManagerPortableRecipeEntry,
        snapshot: DataManagerProductCatalogSnapshot,
        target_dataset: DataManagerDatasetEntry | None,
    ) -> None:
        if not isinstance(recipe, DataManagerPortableRecipeEntry):
            raise TypeError("recipe must be a DataManagerPortableRecipeEntry")
        self._require_snapshot(snapshot)
        self._reset_configuration(snapshot, target_dataset)
        self._recipe = recipe
        self.setWindowTitle("Create Artifact from Recipe")
        self._populate_source()

    def configure_recipe_collection(
        self,
        collection: DataManagerRecipeCollectionEntry,
        snapshot: DataManagerProductCatalogSnapshot,
        target_dataset: DataManagerDatasetEntry | None,
    ) -> None:
        if not isinstance(collection, DataManagerRecipeCollectionEntry):
            raise TypeError(
                "collection must be a DataManagerRecipeCollectionEntry"
            )
        self._require_snapshot(snapshot)
        self._reset_configuration(snapshot, target_dataset)
        self._recipe_collection = collection
        self.setWindowTitle("Create Artifacts from Recipe Collection")
        self._populate_source()

    def set_target(self, target_dataset: DataManagerDatasetEntry | None) -> None:
        if target_dataset is not None and not isinstance(
            target_dataset, DataManagerDatasetEntry
        ):
            raise TypeError("target_dataset must be a DataManagerDatasetEntry or None")
        if target_dataset is not None and not target_dataset.accepted:
            target_dataset = None
        if target_dataset == self._target_dataset:
            return
        self._target_dataset = target_dataset
        self._populate_target()
        self.invalidate_preview("Selected dataset changed. Preview again.")

    def set_catalog(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        self._require_snapshot(snapshot)
        self._snapshot = snapshot
        if self._recipe is not None:
            replacement = next(
                (
                    item
                    for item in snapshot.portable_recipes.recipes
                    if item.recipe_id == self._recipe.recipe_id and item.valid
                ),
                None,
            )
            if replacement is None:
                self._source_catalog_available = False
                self.source_status.setText("Source unavailable.")
                self.invalidate_preview("Recipe source is unavailable.")
            else:
                self._recipe = replacement
                self._source_catalog_available = True
                self._populate_source()
        elif self._recipe_collection is not None:
            self._populate_source()

    def current_request(self) -> DataManagerArtifactMaterializationRequest | None:
        target_market_id = self.target_market_id
        if target_market_id is None or not self._source_available():
            return None
        if self._recipe is not None:
            return DataManagerArtifactMaterializationRequest(
                target_market_id,
                root_recipe_ids=(self._recipe.recipe_id,),
            )
        collection = self._recipe_collection
        if collection is None:
            return None
        return DataManagerArtifactMaterializationRequest(
            target_market_id,
            recipe_collection_id=collection.collection_id,
            recipe_collection_revision_id=collection.revision_id,
        )

    def set_plan(self, plan: DataManagerArtifactMaterializationPlan) -> bool:
        if not isinstance(plan, DataManagerArtifactMaterializationPlan):
            raise TypeError("plan must be a DataManagerArtifactMaterializationPlan")
        if not self._plan_matches_source(plan):
            return False
        self._reviewed_plan = plan
        self._equivalent_collection = None
        self._collection_prediction_ready = False
        self._materialization_result = None
        self.result_summary.clear()
        self._populate_preview(plan)
        self._populate_outputs(plan)
        statuses = {
            name: 0
            for name in ("NEW", "REUSE CURRENT", "ADVANCE LINEAGE", "BLOCKED")
        }
        for node in plan.nodes:
            statuses[self._node_action(node)] += 1
        source = plan.source_ohlcv
        self.preview_summary.setText(
            f"Target: {plan.target_market_id.as_key()} | "
            f"OHLCV: rows={source.row_count}, "
            f"first={format_utc_timestamp_ms(source.first_timestamp_ms)}, "
            f"last={format_utc_timestamp_ms(source.last_timestamp_ms)}, "
            f"csv={source.csv_sha256}, "
            f"sidecar={source.sidecar_sha256} | "
            f"Roots: {len(plan.root_recipe_ids)} | "
            f"Artifacts considered: {len(plan.nodes)} | "
            f"Stages: {len(plan.execution_stages)} | New: {statuses['NEW']} | "
            f"Reuse Current: {statuses['REUSE CURRENT']} | "
            f"Advance Lineage: {statuses['ADVANCE LINEAGE']} | "
            f"BLOCKED: {statuses['BLOCKED']}"
        )
        self._sync_controls()
        return True

    def set_collection_prediction(
        self,
        plan: DataManagerArtifactMaterializationPlan,
        equivalent: ArtifactCollectionRevisionV1 | None,
    ) -> bool:
        if plan is not self._reviewed_plan:
            return False
        if equivalent is not None and not isinstance(
            equivalent, ArtifactCollectionRevisionV1
        ):
            raise TypeError(
                "equivalent must be an ArtifactCollectionRevisionV1 or None"
            )
        self._equivalent_collection = equivalent
        self._collection_prediction_ready = True
        if equivalent is None:
            suffix = "Artifact Collection: NEW"
        else:
            suffix = (
                "Artifact Collection: REUSE EXISTING COLLECTION\n"
                f"Existing Name: {equivalent.display_name}\n"
                f"Collection ID: {equivalent.collection_id}\n"
                f"Revision ID: {equivalent.revision_id}"
            )
        self.preview_summary.setText(f"{self.preview_summary.text()}\n{suffix}")
        self._sync_controls()
        return True

    def reviewed_plan_matches(self, plan: DataManagerArtifactMaterializationPlan) -> bool:
        return plan is self._reviewed_plan and self._plan_matches_source(plan)

    def selected_outputs(self) -> tuple[ArtifactCollectionOutputV1, ...]:
        return tuple(
            ArtifactCollectionOutputV1(
                row.logical_artifact_id,
                row.output_name,
                row.column_name,
            )
            for row in self._output_rows()
            if row.included
        )

    def settle_materialization_success(
        self, result: DataManagerArtifactMaterializationResult
    ) -> None:
        if not isinstance(result, DataManagerArtifactMaterializationResult):
            raise TypeError(
                "result must be a DataManagerArtifactMaterializationResult"
            )
        self._materialization_result = result
        self.result_summary.setText(
            f"Artifacts complete: roots={len(result.root_logical_artifact_ids)}, "
            f"support={len(result.support_logical_artifact_ids)}, "
            f"created={len(result.created_artifact_ids)}, "
            f"reused={len(result.reused_artifact_ids)}, "
            f"advanced={len(result.advanced_logical_artifact_ids)}"
        )
        self.invalidate_preview("Execution complete. Preview again to execute again.")

    def settle_collection_success(
        self,
        revision: ArtifactCollectionRevisionV1,
        *,
        outcome: str = "CREATED",
    ) -> None:
        if not isinstance(revision, ArtifactCollectionRevisionV1):
            raise TypeError("revision must be an ArtifactCollectionRevisionV1")
        if outcome not in {"CREATED", "REUSED_EXISTING"}:
            raise ValueError("invalid Artifact Collection outcome")
        prefix = self.result_summary.text()
        self.result_summary.setText(
            f"{prefix} | Artifact Collection {outcome.replace('_', ' ').lower()}: "
            f"{revision.collection_id} | "
            f"Revision: {revision.revision_id}"
        )

    def settle_collection_failure(self, message: str) -> None:
        prefix = self.result_summary.text()
        self.result_summary.setText(
            f"{prefix} | Artifact Collection failed: {message}"
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._reviewed_plan = None
        self._equivalent_collection = None
        self._collection_prediction_ready = False
        self.preview_table.setRowCount(0)
        self.output_table.setRowCount(0)
        self.preview_summary.setText(message)
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    @staticmethod
    def _require_snapshot(snapshot: object) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")

    def _reset_configuration(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        target_dataset: DataManagerDatasetEntry | None,
    ) -> None:
        if target_dataset is not None and not isinstance(
            target_dataset, DataManagerDatasetEntry
        ):
            raise TypeError("target_dataset must be a DataManagerDatasetEntry or None")
        if target_dataset is not None and not target_dataset.accepted:
            target_dataset = None
        self._snapshot = snapshot
        self._recipe = None
        self._recipe_collection = None
        self._target_dataset = target_dataset
        self._reviewed_plan = None
        self._materialization_result = None
        self._source_catalog_available = True
        self.preview_table.setRowCount(0)
        self.output_table.setRowCount(0)
        self.preview_summary.setText("Preview required.")
        self.result_summary.clear()
        self.create_collection_checkbox.setChecked(False)
        self.collection_name_input.clear()
        self.collection_description_input.clear()
        for label in self.source_labels.values():
            label.clear()
        self._populate_target()

    def _populate_source(self) -> None:
        for label in self.source_labels.values():
            label.clear()
        recipe = self._recipe
        if recipe is not None:
            self.source_labels["source_type"].setText("Recipe")
            self.source_labels["tool"].setText(recipe.tool_key)
            self.source_labels["parameters"].setText(
                ", ".join(f"{key}={value}" for key, value in recipe.parameters.items())
            )
            self.source_labels["inputs"].setText(", ".join(recipe.input_bindings))
            self.source_labels["outputs"].setText(", ".join(recipe.output_names))
            self.source_labels["recipe_id"].setText(recipe.recipe_id)
        else:
            collection = self._recipe_collection
            if collection is not None:
                self.source_labels["source_type"].setText("Recipe Collection")
                self.source_labels["name"].setText(collection.display_name)
                self.source_labels["root_count"].setText(str(collection.root_count))
                self.source_labels["member_count"].setText(str(collection.member_count))
                self.source_labels["collection_id"].setText(collection.collection_id)
                self.source_labels["revision_id"].setText(collection.revision_id)
        self.source_status.setText(
            "Ready" if self._source_available() else "Source unavailable."
        )
        self._sync_controls()

    def _populate_target(self) -> None:
        dataset = self._target_dataset
        market = None if dataset is None else dataset.market_id
        self.target_label.setText(
            "No accepted dataset selected."
            if market is None
            else market.as_key()
        )
        values = {
            "exchange": "" if market is None else market.exchange,
            "market_type": "" if market is None else market.market_type,
            "asset": "" if market is None else market.symbol,
            "timeframe": "" if market is None else market.timeframe,
            "rows": "" if dataset is None else str(dataset.row_count),
            "first_timestamp": (
                ""
                if dataset is None
                else format_utc_timestamp_ms(dataset.first_timestamp_ms)
            ),
            "last_timestamp": (
                ""
                if dataset is None
                else format_utc_timestamp_ms(dataset.last_timestamp_ms)
            ),
        }
        for key, value in values.items():
            self.target_labels[key].setText(value)
        self._sync_controls()

    def _source_available(self) -> bool:
        return bool(
            self._source_catalog_available
            and (
                (self._recipe is not None and self._recipe.valid)
                or (
                    self._recipe_collection is not None
                    and self._recipe_collection.valid
                )
            )
        )

    def _plan_matches_source(self, plan: DataManagerArtifactMaterializationPlan) -> bool:
        if plan.target_market_id != self.target_market_id:
            return False
        if self._recipe is not None:
            return (
                plan.root_recipe_ids == (self._recipe.recipe_id,)
                and plan.source_recipe_collection_id is None
                and plan.source_recipe_collection_revision_id is None
            )
        collection = self._recipe_collection
        return bool(
            collection is not None
            and plan.source_recipe_collection_id == collection.collection_id
            and plan.source_recipe_collection_revision_id == collection.revision_id
        )

    def _populate_preview(self, plan: DataManagerArtifactMaterializationPlan) -> None:
        self.preview_table.setRowCount(len(plan.nodes))
        for row, node in enumerate(plan.nodes):
            values = (
                node.tool_key,
                node.kind,
                node.role,
                self._node_action(node),
                "; ".join(node.blockers),
                node.portable_recipe_id,
                node.logical_artifact_id,
                node.current_artifact_id or "",
                node.previous_artifact_id or "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.preview_table.setItem(row, column, item)
        resize_data_manager_table(self.preview_table)

    @staticmethod
    def _node_action(node) -> str:
        if node.status == "CREATE":
            return "NEW" if node.previous_artifact_id is None else "ADVANCE LINEAGE"
        if node.status == "REUSE_CURRENT":
            return "REUSE CURRENT"
        return "BLOCKED"

    def _populate_outputs(self, plan: DataManagerArtifactMaterializationPlan) -> None:
        snapshot = self._snapshot
        recipes = {} if snapshot is None else {
            item.recipe_id: item for item in snapshot.portable_recipes.recipes
        }
        nodes = {item.portable_recipe_id: item for item in plan.nodes}
        rows: list[_OutputRow] = []
        for recipe_id in plan.root_recipe_ids:
            recipe = recipes.get(recipe_id)
            node = nodes.get(recipe_id)
            if recipe is None or node is None:
                continue
            for output_name in recipe.output_names:
                rows.append(
                    _OutputRow(
                        True,
                        recipe.tool_key,
                        output_name,
                        output_name,
                        node.logical_artifact_id,
                    )
                )
        self._set_output_rows(tuple(rows))

    def _set_output_rows(self, rows: tuple[_OutputRow, ...]) -> None:
        self._populating = True
        blocker = QSignalBlocker(self.output_table)
        self.output_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            include = QTableWidgetItem("")
            include.setCheckState(
                Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked
            )
            include.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            self.output_table.setItem(row_index, 0, include)
            for column, value in enumerate(
                (
                    row.tool_key,
                    row.output_name,
                    row.column_name,
                    row.logical_artifact_id,
                ),
                start=1,
            ):
                item = QTableWidgetItem(value)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                    if column == 3
                    else Qt.ItemFlag.ItemIsEnabled
                )
                self.output_table.setItem(row_index, column, item)
        del blocker
        self._populating = False
        resize_data_manager_table(self.output_table)
        self._sync_controls()

    def _output_rows(self) -> tuple[_OutputRow, ...]:
        rows: list[_OutputRow] = []
        for row in range(self.output_table.rowCount()):
            items = tuple(self.output_table.item(row, column) for column in range(5))
            if any(item is None for item in items):
                continue
            include, tool, output, column, logical = items
            rows.append(
                _OutputRow(
                    include.checkState() == Qt.CheckState.Checked,
                    tool.text(),
                    output.text(),
                    column.text(),
                    logical.text(),
                )
            )
        return tuple(rows)

    def _output_mapping_is_valid(self) -> bool:
        rows = tuple(row for row in self._output_rows() if row.included)
        if not rows:
            return False
        try:
            outputs = tuple(
                ArtifactCollectionOutputV1(
                    row.logical_artifact_id,
                    row.output_name,
                    row.column_name,
                )
                for row in rows
            )
        except (TypeError, ValueError):
            return False
        columns = tuple(item.column_name for item in outputs)
        return len(columns) == len(set(columns))

    def _on_output_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._populating:
            self._equivalent_collection = None
            self._collection_prediction_ready = False
            if self.create_collection_checkbox.isChecked():
                self.preview_summary.setText("Output mapping changed. Preview again.")
        self._sync_controls()

    def _collection_is_valid(self) -> bool:
        if not self.create_collection_checkbox.isChecked():
            return True
        name = self.collection_name_input.text()
        description = self.collection_description_input.text()
        return bool(
            name
            and name == name.strip()
            and description == description.strip()
            and self._output_mapping_is_valid()
        )

    def _move_output(self, offset: int) -> None:
        if self._busy:
            return
        row = self.output_table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.output_table.rowCount():
            return
        rows = list(self._output_rows())
        rows[row], rows[target] = rows[target], rows[row]
        self._set_output_rows(tuple(rows))
        self._equivalent_collection = None
        self._collection_prediction_ready = False
        if self.create_collection_checkbox.isChecked():
            self.preview_summary.setText("Output mapping changed. Preview again.")
        self.output_table.selectRow(target)

    def _emit_preview(self) -> None:
        request = self.current_request()
        if not self._busy and request is not None:
            self.preview_requested.emit(request)

    def _emit_execute(self) -> None:
        plan = self._reviewed_plan
        if plan is None or not self._execute_is_enabled():
            return
        self.execute_requested.emit(
            plan,
            self.create_collection_checkbox.isChecked(),
            self.collection_name_input.text(),
            self.collection_description_input.text(),
            self.selected_outputs(),
        )

    def _execute_is_enabled(self) -> bool:
        plan = self._reviewed_plan
        return bool(
            not self._busy
            and plan is not None
            and not plan.blocked
            and self.reviewed_plan_matches(plan)
            and self._collection_is_valid()
            and (
                not self.create_collection_checkbox.isChecked()
                or self._collection_prediction_ready
            )
        )

    def _sync_controls(self, *_args: object) -> None:
        source_ready = self._source_available()
        target_ready = self._target_dataset is not None
        collection = self.create_collection_checkbox.isChecked()
        plan_ready = self._reviewed_plan is not None
        self.preview_button.setEnabled(
            not self._busy and source_ready and target_ready
        )
        self.execute_button.setEnabled(self._execute_is_enabled())
        self.create_collection_checkbox.setEnabled(not self._busy and plan_ready)
        self.collection_name_input.setEnabled(not self._busy and collection)
        self.collection_description_input.setEnabled(not self._busy and collection)
        self.output_table.setEnabled(not self._busy and collection and plan_ready)
        self.move_up_button.setEnabled(
            not self._busy and collection and self.output_table.rowCount() > 1
        )
        self.move_down_button.setEnabled(
            not self._busy and collection and self.output_table.rowCount() > 1
        )
