"""Artifact Collection create and immutable-revision edit presentation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
    DataManagerProductCatalogSnapshot,
)
from leonardo.data_manager.creation_models import ArtifactCollectionSelectionPlan
from leonardo.gui.data_manager.table_presentation import (
    format_utc_datetime,
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_ARTIFACT_COLLECTION_WINDOW_ID = "data_manager.artifact_collection.window"
_ARTIFACT_COLUMNS = (
    "Select",
    "Exchange",
    "Market Type",
    "Asset",
    "Timeframe",
    "Tool",
    "Kind",
    "Rows",
    "First TS",
    "Last TS",
    "Created",
    "State",
    "Previous Artifact ID",
    "Outputs",
)
_PREVIEW_COLUMNS = (
    "Role",
    "Tool",
    "Kind",
    "Logical Artifact ID",
    "Physical Artifact ID",
    "Outputs",
)
_OUTPUT_COLUMNS = (
    "Include",
    "Tool",
    "Output",
    "Column Name",
    "Logical Artifact ID",
)
_OUTPUT_ID_ROLE = int(Qt.ItemDataRole.UserRole)


@dataclass(frozen=True, slots=True)
class _OutputMappingRow:
    included: bool
    tool_key: str
    output_name: str
    column_name: str
    logical_artifact_id: str


class DataManagerArtifactCollectionDialog(QDialog):
    """Collect Artifact roots and output mapping for a reviewed physical plan."""

    preview_requested = Signal(object, object)
    create_requested = Signal(object, str, str, object)
    edit_requested = Signal(str, object, str, str, object, object, str)
    closing = Signal()

    def __init__(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        browsing_market_id: MarketId | None = None,
        parent: QWidget | None = None,
    ) -> None:
        self._require_snapshot(snapshot)
        if browsing_market_id is not None and not isinstance(browsing_market_id, MarketId):
            raise TypeError("browsing_market_id must be a MarketId or None")
        super().__init__(parent)
        self._snapshot = snapshot
        self._artifacts = snapshot.managed_artifacts.artifacts
        self._browsing_market_id = browsing_market_id
        self._selection_market_id: MarketId | None = None
        self._fixed_market_id: MarketId | None = None
        self._selected_root_ids: tuple[str, ...] = ()
        self._reviewed_plan: ArtifactCollectionSelectionPlan | None = None
        self._equivalent_collection: ArtifactCollectionRevisionV1 | None = None
        self._prediction_ready = False
        self._preserved_output_rows: tuple[_OutputMappingRow, ...] = ()
        self._collection_id: str | None = None
        self._expected_revision_id: str | None = None
        self._busy = False
        self._populating = False
        self._workspace_splitters_initialized = False

        apply_identity(
            self,
            DATA_MANAGER_ARTIFACT_COLLECTION_WINDOW_ID,
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
        workspace = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            workspace,
            "data_manager.artifact_collection.splitter.workspace",
            object_type="splitter",
        )
        workspace.setChildrenCollapsible(False)

        left_workspace = QWidget(workspace)
        left_layout = QVBoxLayout(left_workspace)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        metadata = QGroupBox("Collection", left_workspace)
        metadata_layout = QFormLayout(metadata)
        metadata_layout.setContentsMargins(12, 24, 12, 12)
        metadata_layout.setVerticalSpacing(8)
        self.name_input = QLineEdit(metadata)
        self.name_input.setObjectName("data_manager.artifact_collection.input.name")
        self.description_input = QLineEdit(metadata)
        self.description_input.setObjectName(
            "data_manager.artifact_collection.input.description"
        )
        self.market_label = QLabel("Collection Market: None", metadata)
        self.market_label.setObjectName("data_manager.artifact_collection.label.market")
        metadata_layout.addRow("Name", self.name_input)
        metadata_layout.addRow("Description", self.description_input)
        metadata_layout.addRow(self.market_label)
        metadata_size_policy = metadata.sizePolicy()
        metadata_size_policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        metadata.setSizePolicy(metadata_size_policy)
        left_layout.addWidget(metadata)

        available = QGroupBox("Artifact roots", left_workspace)
        available_layout = QVBoxLayout(available)
        available_layout.setContentsMargins(12, 24, 12, 12)
        available_layout.setSpacing(10)
        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("Scope", available))
        self.dataset_scope = QComboBox(available)
        apply_identity(
            self.dataset_scope,
            "data_manager.artifact_collection.combo.dataset_scope",
            object_type="combo_box",
        )
        self.dataset_scope.addItem("Current Dataset", "current")
        self.dataset_scope.addItem("All", "all")
        controls.addWidget(self.dataset_scope)
        self.select_all_button = QPushButton("Select All", available)
        self.select_all_button.setObjectName(
            "data_manager.artifact_collection.action.select_all"
        )
        self.deselect_all_button = QPushButton("Deselect All", available)
        self.deselect_all_button.setObjectName(
            "data_manager.artifact_collection.action.deselect_all"
        )
        controls.addWidget(self.select_all_button)
        controls.addWidget(self.deselect_all_button)
        controls.addStretch(1)
        available_layout.addLayout(controls)
        self.artifact_table = configure_table(
            QTableWidget(available),
            object_id="data_manager.artifact_collection.table.artifacts",
            columns=_ARTIFACT_COLUMNS,
            labels=_ARTIFACT_COLUMNS,
        )
        self.artifact_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.artifact_table.itemChanged.connect(self._on_artifact_item_changed)
        available_layout.addWidget(self.artifact_table)
        available_size_policy = available.sizePolicy()
        available_size_policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        available.setSizePolicy(available_size_policy)
        left_layout.addWidget(available, 1)
        left_size_policy = left_workspace.sizePolicy()
        left_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        left_workspace.setSizePolicy(left_size_policy)
        workspace.addWidget(left_workspace)

        right_workspace = QSplitter(Qt.Orientation.Vertical, workspace)
        apply_identity(
            right_workspace,
            "data_manager.artifact_collection.splitter.right",
            object_type="splitter",
        )
        right_workspace.setChildrenCollapsible(False)

        preview = QGroupBox("Preview", right_workspace)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 24, 12, 12)
        preview_layout.setSpacing(10)
        self.preview_table = configure_table(
            QTableWidget(preview),
            object_id="data_manager.artifact_collection.table.preview",
            columns=_PREVIEW_COLUMNS,
            labels=_PREVIEW_COLUMNS,
        )
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        preview_layout.addWidget(self.preview_table)
        self.preview_summary = QLabel("Preview required.", preview)
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setObjectName(
            "data_manager.artifact_collection.label.preview_status"
        )
        preview_layout.addWidget(self.preview_summary)
        right_workspace.addWidget(preview)

        outputs = QGroupBox("Output Mapping", right_workspace)
        outputs_layout = QVBoxLayout(outputs)
        outputs_layout.setContentsMargins(12, 24, 12, 12)
        outputs_layout.setSpacing(10)
        self.output_table = configure_table(
            QTableWidget(outputs),
            object_id="data_manager.artifact_collection.table.outputs",
            columns=_OUTPUT_COLUMNS,
            labels=_OUTPUT_COLUMNS,
        )
        self.output_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.output_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.output_table.itemChanged.connect(self._on_output_item_changed)
        outputs_layout.addWidget(self.output_table)
        ordering = QHBoxLayout()
        ordering.setSpacing(10)
        self.move_up_button = QPushButton("Move Up", outputs)
        self.move_up_button.setObjectName(
            "data_manager.artifact_collection.action.move_up"
        )
        self.move_down_button = QPushButton("Move Down", outputs)
        self.move_down_button.setObjectName(
            "data_manager.artifact_collection.action.move_down"
        )
        ordering.addWidget(self.move_up_button)
        ordering.addWidget(self.move_down_button)
        ordering.addStretch(1)
        outputs_layout.addLayout(ordering)
        right_workspace.addWidget(outputs)
        right_workspace.setStretchFactor(0, 1)
        right_workspace.setStretchFactor(1, 1)
        right_size_policy = right_workspace.sizePolicy()
        right_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        right_workspace.setSizePolicy(right_size_policy)
        workspace.addWidget(right_workspace)
        workspace.setStretchFactor(0, 1)
        workspace.setStretchFactor(1, 1)
        self.workspace_splitter = workspace
        self.right_splitter = right_workspace
        self.left_workspace = left_workspace
        root.addWidget(workspace, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.preview_button = QPushButton("Preview", self)
        self.preview_button.setObjectName(
            "data_manager.artifact_collection.action.preview"
        )
        self.publish_button = QPushButton("Create Collection", self)
        self.publish_button.setObjectName(
            "data_manager.artifact_collection.action.publish"
        )
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "data_manager.artifact_collection.action.close"
        )
        actions.addWidget(self.preview_button)
        actions.addWidget(self.publish_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.dataset_scope.currentIndexChanged.connect(self._on_scope_changed)
        self.select_all_button.clicked.connect(self._select_all)
        self.deselect_all_button.clicked.connect(self._deselect_all)
        self.preview_button.clicked.connect(self._emit_preview)
        self.publish_button.clicked.connect(self._emit_publish)
        self.move_up_button.clicked.connect(lambda: self._move_output(-1))
        self.move_down_button.clicked.connect(lambda: self._move_output(1))
        self.close_button.clicked.connect(self.close)
        self.name_input.textChanged.connect(self._sync_controls)
        self.description_input.textChanged.connect(self._sync_controls)
        self.configure_create(snapshot, browsing_market_id=browsing_market_id)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._workspace_splitters_initialized:
            return
        self._workspace_splitters_initialized = True
        horizontal_extent = max(1, self.workspace_splitter.width())
        vertical_extent = max(1, self.right_splitter.height())
        self.workspace_splitter.setSizes((horizontal_extent, horizontal_extent))
        self.right_splitter.setSizes((vertical_extent, vertical_extent))

    @property
    def collection_id(self) -> str | None:
        return self._collection_id

    @property
    def expected_revision_id(self) -> str | None:
        return self._expected_revision_id

    @property
    def selection_market_id(self) -> MarketId | None:
        return self._selection_market_id

    @property
    def reviewed_plan(self) -> ArtifactCollectionSelectionPlan | None:
        return self._reviewed_plan

    def selected_root_logical_artifact_ids(self) -> tuple[str, ...]:
        return self._selected_root_ids

    def configure_create(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        browsing_market_id: MarketId | None,
    ) -> None:
        self._require_snapshot(snapshot)
        self._snapshot = snapshot
        self._artifacts = snapshot.managed_artifacts.artifacts
        self._browsing_market_id = browsing_market_id
        self._fixed_market_id = None
        self._selection_market_id = None
        self._selected_root_ids = ()
        self._collection_id = None
        self._expected_revision_id = None
        self.setWindowTitle("Create Artifact Collection")
        self.publish_button.setText("Create Collection")
        self.name_input.clear()
        self.description_input.clear()
        self.dataset_scope.setCurrentIndex(0)
        self.output_table.setRowCount(0)
        self._preserved_output_rows = ()
        self._populate_artifacts()
        self.invalidate_preview("Select one or more Artifact roots.")

    def configure_edit(
        self,
        revision: ArtifactCollectionRevisionV1,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        browsing_market_id: MarketId | None,
    ) -> None:
        if not isinstance(revision, ArtifactCollectionRevisionV1):
            raise TypeError("revision must be an ArtifactCollectionRevisionV1")
        self._require_snapshot(snapshot)
        self._snapshot = snapshot
        self._artifacts = snapshot.managed_artifacts.artifacts
        self._browsing_market_id = browsing_market_id
        self._fixed_market_id = revision.market_id
        self._selection_market_id = revision.market_id
        self._selected_root_ids = revision.root_logical_artifact_ids
        self._collection_id = revision.collection_id
        self._expected_revision_id = revision.revision_id
        self.setWindowTitle("Edit Artifact Collection")
        self.publish_button.setText("Save Revision")
        self.name_input.setText(revision.display_name)
        self.description_input.setText(revision.description)
        self.dataset_scope.setCurrentIndex(0)
        self._preserved_output_rows = ()
        self._populate_artifacts()
        self._populate_outputs_from_revision(revision)
        self.invalidate_preview("Preview the current Artifact roots before saving.")

    def set_catalog(
        self,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        browsing_market_id: MarketId | None,
    ) -> None:
        self._require_snapshot(snapshot)
        if browsing_market_id is not None and not isinstance(browsing_market_id, MarketId):
            raise TypeError("browsing_market_id must be a MarketId or None")
        previous_roots = self._selected_root_ids
        valid_ids = {
            item.logical_artifact_id
            for item in snapshot.managed_artifacts.artifacts
            if item.valid
            and (self._fixed_market_id is None or item.market_id == self._fixed_market_id)
        }
        self._selected_root_ids = tuple(
            item for item in self._selected_root_ids if item in valid_ids
        )
        self._snapshot = snapshot
        self._artifacts = snapshot.managed_artifacts.artifacts
        self._browsing_market_id = browsing_market_id
        if self._fixed_market_id is None and not self._selected_root_ids:
            self._selection_market_id = None
        self._populate_artifacts()
        if self._selected_root_ids != previous_roots:
            self._preserve_and_clear_outputs()
        self.invalidate_preview("Artifact catalog changed. Preview again.")

    def set_browsing_market(self, market_id: MarketId | None) -> None:
        if market_id is not None and not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        if market_id == self._browsing_market_id:
            return
        self._browsing_market_id = market_id
        self._populate_artifacts()
        self.invalidate_preview("Selected dataset changed. Preview again.")

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_controls()

    def set_plan(self, plan: ArtifactCollectionSelectionPlan) -> bool:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        if (
            plan.market_id != self._selection_market_id
            or plan.root_logical_artifact_ids != self._selected_root_ids
        ):
            return False
        previous = self._preserved_output_rows or self._output_rows()
        self._preserved_output_rows = ()
        self._reviewed_plan = plan
        self._equivalent_collection = None
        self._prediction_ready = False
        self._populate_preview(plan)
        self._populate_outputs_from_plan(plan, previous)
        self.preview_summary.setText(
            f"Preview ready: {len(plan.root_logical_artifact_ids)} ROOT; "
            f"{len(plan.support_logical_artifact_ids)} SUPPORT; "
            "checking Collection reuse..."
        )
        self._sync_controls()
        return True

    def set_collection_prediction(
        self,
        plan: ArtifactCollectionSelectionPlan,
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
        self._prediction_ready = True
        lines = [
            f"Preview ready: {len(plan.root_logical_artifact_ids)} ROOT; "
            f"{len(plan.support_logical_artifact_ids)} SUPPORT"
        ]
        if equivalent is None or equivalent.collection_id == self._collection_id:
            lines.append(
                "Result: UPDATE COLLECTION"
                if self._collection_id is not None
                else "Result: NEW COLLECTION"
            )
        else:
            lines.extend(
                (
                    "Result: REUSE EXISTING COLLECTION",
                    f"Existing Name: {equivalent.display_name}",
                    f"Collection ID: {equivalent.collection_id}",
                    f"Revision ID: {equivalent.revision_id}",
                )
            )
        self.preview_summary.setText("\n".join(lines))
        self._sync_controls()
        return True

    def reviewed_plan_matches(
        self,
        plan: ArtifactCollectionSelectionPlan,
    ) -> bool:
        return (
            plan is self._reviewed_plan
            and plan.market_id == self._selection_market_id
            and plan.root_logical_artifact_ids == self._selected_root_ids
        )

    def selected_outputs(self) -> tuple[ArtifactCollectionOutputV1, ...]:
        outputs: list[ArtifactCollectionOutputV1] = []
        for row in self._output_rows():
            if row.included:
                outputs.append(
                    ArtifactCollectionOutputV1(
                        row.logical_artifact_id,
                        row.output_name,
                        row.column_name,
                    )
                )
        return tuple(outputs)

    def presentation_order(self) -> tuple[str, ...]:
        return tuple(item.column_name for item in self._output_rows() if item.included)

    def settle_success(
        self,
        revision: ArtifactCollectionRevisionV1,
        *,
        outcome: str = "UPDATED",
    ) -> None:
        if outcome not in {"CREATED", "UPDATED", "REUSED_EXISTING"}:
            raise ValueError("invalid Artifact Collection outcome")
        self.configure_edit(
            revision,
            self._snapshot,
            browsing_market_id=self._browsing_market_id,
        )
        self.preview_summary.setText(
            f"Artifact Collection {outcome.replace('_', ' ').lower()} successfully.\n"
            f"Name: {revision.display_name}\n"
            f"Collection ID: {revision.collection_id}\n"
            f"Revision ID: {revision.revision_id}"
        )

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._reviewed_plan = None
        self._equivalent_collection = None
        self._prediction_ready = False
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

    def _visible_artifacts(self) -> tuple:
        if self.dataset_scope.currentData() == "all":
            return self._artifacts
        return tuple(
            item for item in self._artifacts if item.market_id == self._browsing_market_id
        )

    def _populate_artifacts(self) -> None:
        visible = self._visible_artifacts()
        self._populating = True
        blocker = QSignalBlocker(self.artifact_table)
        self.artifact_table.setRowCount(len(visible))
        for row, artifact in enumerate(visible):
            selectable = (
                artifact.valid
                and (
                    self._selection_market_id is None
                    or artifact.market_id == self._selection_market_id
                )
            )
            select_item = QTableWidgetItem("")
            select_item.setData(_OUTPUT_ID_ROLE, artifact.logical_artifact_id)
            select_item.setCheckState(
                Qt.CheckState.Checked
                if artifact.logical_artifact_id in self._selected_root_ids
                else Qt.CheckState.Unchecked
            )
            select_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                if selectable
                else Qt.ItemFlag.NoItemFlags
            )
            self.artifact_table.setItem(row, 0, select_item)
            market = artifact.market_id
            values = (
                market.exchange,
                market.market_type,
                market.symbol,
                market.timeframe,
                artifact.tool_key,
                artifact.kind,
                str(artifact.row_count),
                format_utc_timestamp_ms(artifact.first_timestamp_ms),
                format_utc_timestamp_ms(artifact.last_timestamp_ms),
                format_utc_datetime(artifact.created_at_utc),
                "valid" if artifact.valid else f"invalid: {artifact.rejection_reason}",
                artifact.previous_artifact_id or "",
                ", ".join(artifact.output_names),
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.artifact_table.setItem(row, column, item)
        del blocker
        self._populating = False
        self._sync_market_label()
        resize_data_manager_table(self.artifact_table)
        self._sync_controls()

    def _populate_preview(self, plan: ArtifactCollectionSelectionPlan) -> None:
        root_ids = set(plan.root_logical_artifact_ids)
        self.preview_table.setRowCount(len(plan.members))
        for row, member in enumerate(plan.members):
            logical_id = member.version_key.logical_artifact_id
            values = (
                "ROOT" if logical_id in root_ids else "SUPPORT",
                member.tool_key,
                member.kind,
                logical_id,
                member.version_key.artifact_id,
                ", ".join(member.output_names),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.preview_table.setItem(row, column, item)
        resize_data_manager_table(self.preview_table)

    def _populate_outputs_from_revision(
        self, revision: ArtifactCollectionRevisionV1
    ) -> None:
        selected = {
            (item.logical_artifact_id, item.output_name): item
            for item in revision.selected_outputs
        }
        order = {name: index for index, name in enumerate(revision.presentation_order)}
        rows: list[_OutputMappingRow] = []
        roots = set(revision.root_logical_artifact_ids)
        for member in revision.members:
            logical_id = member.version_key.logical_artifact_id
            if logical_id not in roots:
                continue
            for output_name in member.output_names:
                output = selected.get((logical_id, output_name))
                rows.append(
                    _OutputMappingRow(
                        output is not None,
                        member.tool_key,
                        output_name,
                        output_name if output is None else output.column_name,
                        logical_id,
                    )
                )
        rows.sort(
            key=lambda item: (
                order.get(item.column_name, len(order)),
                item.logical_artifact_id,
                item.output_name,
            )
        )
        self._set_output_rows(tuple(rows))

    def _populate_outputs_from_plan(
        self,
        plan: ArtifactCollectionSelectionPlan,
        previous: tuple[_OutputMappingRow, ...],
    ) -> None:
        previous_by_id = {
            (item.logical_artifact_id, item.output_name): item for item in previous
        }
        candidates: dict[tuple[str, str], tuple[str, str, str]] = {}
        roots = set(plan.root_logical_artifact_ids)
        for member in plan.members:
            logical_id = member.version_key.logical_artifact_id
            if logical_id not in roots:
                continue
            for output_name in member.output_names:
                candidates[(logical_id, output_name)] = (
                    member.tool_key,
                    output_name,
                    logical_id,
                )
        rows: list[_OutputMappingRow] = []
        used: set[tuple[str, str]] = set()
        for old in previous:
            key = (old.logical_artifact_id, old.output_name)
            if key in candidates:
                rows.append(old)
                used.add(key)
        for member in plan.members:
            logical_id = member.version_key.logical_artifact_id
            if logical_id not in roots:
                continue
            for output_name in member.output_names:
                key = (logical_id, output_name)
                if key in used:
                    continue
                rows.append(
                    _OutputMappingRow(
                        True,
                        member.tool_key,
                        output_name,
                        output_name,
                        logical_id,
                    )
                )
                used.add(key)
        self._set_output_rows(tuple(rows))

    def _set_output_rows(self, rows: tuple[_OutputMappingRow, ...]) -> None:
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
            include.setData(
                _OUTPUT_ID_ROLE, (row.logical_artifact_id, row.output_name)
            )
            self.output_table.setItem(row_index, 0, include)
            values = (
                row.tool_key,
                row.output_name,
                row.column_name,
                row.logical_artifact_id,
            )
            for column, value in enumerate(values, start=1):
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

    def _output_rows(self) -> tuple[_OutputMappingRow, ...]:
        rows: list[_OutputMappingRow] = []
        for row in range(self.output_table.rowCount()):
            include = self.output_table.item(row, 0)
            tool = self.output_table.item(row, 1)
            output = self.output_table.item(row, 2)
            column = self.output_table.item(row, 3)
            logical = self.output_table.item(row, 4)
            if any(
                item is None for item in (include, tool, output, column, logical)
            ):
                continue
            rows.append(
                _OutputMappingRow(
                    include.checkState() == Qt.CheckState.Checked,
                    tool.text(),
                    output.text(),
                    column.text(),
                    logical.text(),
                )
            )
        return tuple(rows)

    def _on_scope_changed(self, _index: int) -> None:
        if not self._populating:
            self._populate_artifacts()

    def _on_artifact_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() != 0:
            return
        logical_id = str(item.data(_OUTPUT_ID_ROLE) or "")
        artifact = next(
            (entry for entry in self._artifacts if entry.logical_artifact_id == logical_id),
            None,
        )
        selected = list(self._selected_root_ids)
        if item.checkState() == Qt.CheckState.Checked:
            if artifact is None or not artifact.valid:
                return
            if self._selection_market_id is None:
                self._selection_market_id = artifact.market_id
            if artifact.market_id != self._selection_market_id:
                return
            if logical_id not in selected:
                selected.append(logical_id)
        elif logical_id in selected:
            selected.remove(logical_id)
        self._selected_root_ids = tuple(selected)
        if not selected and self._fixed_market_id is None:
            self._selection_market_id = None
        self._populate_artifacts()
        self._preserve_and_clear_outputs()
        self.invalidate_preview("Root selection changed. Preview again.")

    def _select_all(self) -> None:
        selected = list(self._selected_root_ids)
        for artifact in self._visible_artifacts():
            if not artifact.valid:
                continue
            if self._selection_market_id is None:
                self._selection_market_id = artifact.market_id
            if artifact.market_id == self._selection_market_id:
                if artifact.logical_artifact_id not in selected:
                    selected.append(artifact.logical_artifact_id)
        self._selected_root_ids = tuple(selected)
        self._populate_artifacts()
        self._preserve_and_clear_outputs()
        self.invalidate_preview("Root selection changed. Preview again.")

    def _deselect_all(self) -> None:
        if not self._selected_root_ids:
            return
        self._selected_root_ids = ()
        self._selection_market_id = self._fixed_market_id
        self._populate_artifacts()
        self._preserve_and_clear_outputs()
        self.invalidate_preview("Root selection changed. Preview again.")

    def _preserve_and_clear_outputs(self) -> None:
        rows = self._output_rows()
        if rows:
            self._preserved_output_rows = rows
        self.output_table.setRowCount(0)

    def _on_output_item_changed(self, item: QTableWidgetItem) -> None:
        if not self._populating and item.column() in {0, 3}:
            self._equivalent_collection = None
            self._prediction_ready = False
            self.preview_summary.setText("Output mapping changed. Preview again.")
            self._sync_controls()

    def _move_output(self, offset: int) -> None:
        if self._busy:
            return
        row = self.output_table.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.output_table.rowCount():
            return
        rows = list(self._output_rows())
        if not rows[row].included:
            return
        rows[row], rows[target] = rows[target], rows[row]
        self._set_output_rows(tuple(rows))
        self._equivalent_collection = None
        self._prediction_ready = False
        self.preview_summary.setText("Output mapping changed. Preview again.")
        self.output_table.selectRow(target)

    def _emit_preview(self) -> None:
        if (
            not self._busy
            and self._selection_market_id is not None
            and self._selected_root_ids
        ):
            self.preview_requested.emit(
                self._selection_market_id, self._selected_root_ids
            )

    def _emit_publish(self) -> None:
        plan = self._reviewed_plan
        if plan is None or not self._publish_is_enabled():
            return
        outputs = self.selected_outputs()
        if self._collection_id is None:
            self.create_requested.emit(
                plan,
                self.name_input.text(),
                self.description_input.text(),
                outputs,
            )
        else:
            self.edit_requested.emit(
                self._collection_id,
                plan,
                self.name_input.text(),
                self.description_input.text(),
                outputs,
                self.presentation_order(),
                self._expected_revision_id or "",
            )

    def _output_mapping_is_valid(self) -> bool:
        rows = tuple(item for item in self._output_rows() if item.included)
        if not rows:
            return False
        try:
            outputs = tuple(
                ArtifactCollectionOutputV1(
                    item.logical_artifact_id,
                    item.output_name,
                    item.column_name,
                )
                for item in rows
            )
        except (TypeError, ValueError):
            return False
        columns = tuple(item.column_name for item in outputs)
        return len(columns) == len(set(columns))

    def _publish_is_enabled(self) -> bool:
        plan = self._reviewed_plan
        name = self.name_input.text()
        description = self.description_input.text()
        return (
            not self._busy
            and bool(name)
            and name == name.strip()
            and description == description.strip()
            and plan is not None
            and self.reviewed_plan_matches(plan)
            and self._prediction_ready
            and self._output_mapping_is_valid()
            and (self._collection_id is None or bool(self._expected_revision_id))
        )

    def _sync_market_label(self) -> None:
        market = self._selection_market_id
        self.market_label.setText(
            "Collection Market: None"
            if market is None
            else f"Collection Market: {market.as_key()}"
        )

    def _sync_controls(self, *_args: object) -> None:
        visible_selectable = any(
            item.valid
            and (
                self._selection_market_id is None
                or item.market_id == self._selection_market_id
            )
            for item in self._visible_artifacts()
        )
        self.artifact_table.setEnabled(not self._busy)
        self.dataset_scope.setEnabled(not self._busy)
        self.select_all_button.setEnabled(not self._busy and visible_selectable)
        self.deselect_all_button.setEnabled(
            not self._busy and bool(self._selected_root_ids)
        )
        self.preview_button.setEnabled(
            not self._busy
            and self._selection_market_id is not None
            and bool(self._selected_root_ids)
        )
        self.output_table.setEnabled(not self._busy and self._reviewed_plan is not None)
        self.move_up_button.setEnabled(not self._busy and self.output_table.rowCount() > 1)
        self.move_down_button.setEnabled(not self._busy and self.output_table.rowCount() > 1)
        self.name_input.setEnabled(not self._busy)
        self.description_input.setEnabled(not self._busy)
        self.publish_button.setEnabled(self._publish_is_enabled())
