"""Read-only Recipe and Artifact Collection inspection presentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.artifacts import ArtifactMetadataV1
from leonardo.data_manager import (
    ArtifactCollectionRevisionV1,
    ArtifactCollectionValidation,
    DataManagerPortableRecipeEntry,
    DataManagerRecipeCollectionInspection,
)
from leonardo.gui.data_manager.table_presentation import (
    format_utc_datetime,
    format_utc_timestamp_ms,
    resize_data_manager_table,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_COLLECTION_INSPECTION_WINDOW_ID = (
    "data_manager.collection_inspection.dialog"
)
_RECIPE_MEMBER_COLUMNS = (
    "Role",
    "Stage",
    "Tool",
    "Kind",
    "Parameters",
    "Inputs",
    "Outputs",
    "Recipe ID",
)
_ARTIFACT_MEMBER_COLUMNS = (
    "Role",
    "Tool",
    "Kind",
    "Parameters",
    "Bindings",
    "Source Artifacts",
    "Outputs",
    "Rows",
    "First TS",
    "Last TS",
    "Logical Artifact ID",
    "Artifact ID",
)
_OUTPUT_COLUMNS = ("Order", "Output", "Column", "Logical Artifact ID")


class DataManagerCollectionInspectionDialog(QDialog):
    """Project one exact Collection revision without mutation controls."""

    closing = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._closing_emitted = False
        apply_identity(
            self,
            DATA_MANAGER_COLLECTION_INSPECTION_WINDOW_ID,
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

        self.collection_group = QGroupBox("Collection", self)
        apply_identity(
            self.collection_group,
            "data_manager.collection_inspection.group.collection",
            object_type="group",
        )
        collection_layout = QVBoxLayout(self.collection_group)
        collection_layout.setContentsMargins(12, 24, 12, 12)
        collection_layout.setSpacing(10)
        self.metadata_table = configure_table(
            QTableWidget(self.collection_group),
            object_id="data_manager.collection_inspection.table.metadata",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.metadata_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        collection_layout.addWidget(self.metadata_table)
        root.addWidget(self.collection_group)

        self.members_group = QGroupBox("Members", self)
        apply_identity(
            self.members_group,
            "data_manager.collection_inspection.group.members",
            object_type="group",
        )
        members_layout = QVBoxLayout(self.members_group)
        members_layout.setContentsMargins(12, 24, 12, 12)
        members_layout.setSpacing(10)
        self.members_table = configure_table(
            QTableWidget(self.members_group),
            object_id="data_manager.collection_inspection.table.members",
            columns=_RECIPE_MEMBER_COLUMNS,
            labels=_RECIPE_MEMBER_COLUMNS,
        )
        self.members_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        members_layout.addWidget(self.members_table)
        root.addWidget(self.members_group, 1)

        self.outputs_group = QGroupBox("Selected Outputs", self)
        apply_identity(
            self.outputs_group,
            "data_manager.collection_inspection.group.outputs",
            object_type="group",
        )
        outputs_layout = QVBoxLayout(self.outputs_group)
        outputs_layout.setContentsMargins(12, 24, 12, 12)
        outputs_layout.setSpacing(10)
        self.outputs_table = configure_table(
            QTableWidget(self.outputs_group),
            object_id="data_manager.collection_inspection.table.outputs",
            columns=_OUTPUT_COLUMNS,
            labels=_OUTPUT_COLUMNS,
        )
        self.outputs_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        outputs_layout.addWidget(self.outputs_table)
        root.addWidget(self.outputs_group, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.close_button = QPushButton("Close", self)
        apply_identity(
            self.close_button,
            "data_manager.collection_inspection.button.close",
            object_type="button",
            display_label="Close",
        )
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

    def configure_recipe_collection(
        self,
        inspection: DataManagerRecipeCollectionInspection,
        recipe_entries: Sequence[DataManagerPortableRecipeEntry],
    ) -> None:
        if not isinstance(inspection, DataManagerRecipeCollectionInspection):
            raise TypeError(
                "inspection must be a DataManagerRecipeCollectionInspection"
            )
        entries = tuple(recipe_entries)
        if not all(isinstance(item, DataManagerPortableRecipeEntry) for item in entries):
            raise TypeError(
                "recipe_entries must contain DataManagerPortableRecipeEntry values"
            )
        if tuple(item.recipe_id for item in entries) != inspection.member_recipe_ids:
            raise ValueError("recipe_entries must exactly match Collection members")

        collection = inspection.collection
        self.setWindowTitle("Recipe Collection Inspection")
        _set_rows(
            self.metadata_table,
            (
                ("Type", "Recipe Collection"),
                ("Name", collection.display_name),
                ("Description", collection.description),
                ("Collection ID", collection.collection_id),
                ("Revision ID", collection.revision_id),
                ("Created", format_utc_datetime(collection.created_at_utc)),
                ("Updated", format_utc_datetime(collection.updated_at_utc)),
                ("Root count", collection.root_count),
                ("Member count", collection.member_count),
                ("Dependency edges", collection.dependency_edge_count),
                ("Execution stages", collection.execution_stage_count),
            ),
        )
        roots = set(inspection.root_recipe_ids)
        stage_by_id = {
            recipe_id: stage
            for stage, recipe_ids in enumerate(inspection.execution_stages, start=1)
            for recipe_id in recipe_ids
        }
        ordered = sorted(
            entries,
            key=lambda item: (
                stage_by_id[item.recipe_id],
                0 if item.recipe_id in roots else 1,
                item.tool_key,
                item.recipe_id,
            ),
        )
        _configure_columns(self.members_table, _RECIPE_MEMBER_COLUMNS)
        _set_rows(
            self.members_table,
            tuple(
                (
                    "ROOT" if item.recipe_id in roots else "SUPPORT",
                    stage_by_id[item.recipe_id],
                    item.tool_key,
                    item.kind,
                    _mapping_text(item.parameters),
                    ", ".join(item.input_bindings),
                    ", ".join(item.output_names),
                    item.recipe_id,
                )
                for item in ordered
            ),
        )
        self.outputs_table.setRowCount(0)
        self.outputs_group.setVisible(False)

    def configure_artifact_collection(
        self,
        revision: ArtifactCollectionRevisionV1,
        validation: ArtifactCollectionValidation,
        metadata_values: Sequence[ArtifactMetadataV1],
    ) -> None:
        if not isinstance(revision, ArtifactCollectionRevisionV1):
            raise TypeError("revision must be an ArtifactCollectionRevisionV1")
        if not isinstance(validation, ArtifactCollectionValidation):
            raise TypeError("validation must be an ArtifactCollectionValidation")
        metadata = tuple(metadata_values)
        if not all(isinstance(item, ArtifactMetadataV1) for item in metadata):
            raise TypeError("metadata must contain ArtifactMetadataV1 values")
        metadata_by_id = {item.artifact_id: item for item in metadata}
        if len(metadata_by_id) != len(revision.members):
            raise ValueError("metadata must exactly match Collection members")

        market = revision.market_id
        self.setWindowTitle("Artifact Collection Inspection")
        validation_text = "valid" if validation.valid else "invalid"
        if validation.blockers:
            validation_text = f"{validation_text}: {', '.join(validation.blockers)}"
        _set_rows(
            self.metadata_table,
            (
                ("Type", "Artifact Collection"),
                ("Name", revision.display_name),
                ("Description", revision.description),
                ("Exchange", market.exchange),
                ("Market Type", market.market_type),
                ("Asset", market.symbol),
                ("Timeframe", market.timeframe),
                ("Collection ID", revision.collection_id),
                ("Revision ID", revision.revision_id),
                ("Created", format_utc_datetime(revision.created_at_utc)),
                ("Revised", format_utc_datetime(revision.revised_at_utc)),
                ("Root count", len(revision.root_logical_artifact_ids)),
                ("Support count", len(revision.support_logical_artifact_ids)),
                ("Member count", len(revision.members)),
                ("Selected output count", len(revision.selected_outputs)),
                ("First Timestamp", format_utc_timestamp_ms(revision.first_timestamp_ms)),
                ("Last Timestamp", format_utc_timestamp_ms(revision.last_timestamp_ms)),
                ("Validation", validation_text),
                ("Database Ready", "yes" if validation.database_ready else "no"),
                (
                    "Source Recipe Collection ID",
                    revision.source_recipe_collection_id or "",
                ),
                (
                    "Source Recipe Collection Revision ID",
                    revision.source_recipe_collection_revision_id or "",
                ),
            ),
        )

        roots = set(revision.root_logical_artifact_ids)
        supports = set(revision.support_logical_artifact_ids)
        ordered_members = tuple(
            member
            for role_ids in (roots, supports)
            for member in revision.members
            if member.version_key.logical_artifact_id in role_ids
        )
        _configure_columns(self.members_table, _ARTIFACT_MEMBER_COLUMNS)
        _set_rows(
            self.members_table,
            tuple(
                _artifact_member_row(member, metadata_by_id, roots)
                for member in ordered_members
            ),
        )

        outputs_by_column = {
            item.column_name: item for item in revision.selected_outputs
        }
        _set_rows(
            self.outputs_table,
            tuple(
                (
                    order,
                    outputs_by_column[column].output_name,
                    column,
                    outputs_by_column[column].logical_artifact_id,
                )
                for order, column in enumerate(revision.presentation_order, start=1)
            ),
        )
        self.outputs_group.setVisible(True)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._closing_emitted:
            self._closing_emitted = True
            self.closing.emit()
        super().closeEvent(event)


def _configure_columns(table: QTableWidget, columns: tuple[str, ...]) -> None:
    table.clear()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setProperty("column_ids", columns)


def _set_rows(
    table: QTableWidget,
    rows: Sequence[Sequence[object]],
) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row_index, column_index, item)
    resize_data_manager_table(table)


def _mapping_text(value: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _artifact_member_row(member, metadata_by_id, roots) -> tuple[object, ...]:
    metadata = metadata_by_id.get(member.version_key.artifact_id)
    if metadata is None:
        raise ValueError("metadata must exactly match Collection members")
    recipe = metadata.recipe
    sources = ", ".join(
        f"{item.role}=Artifact[{item.artifact_id}].{item.output_name}"
        for item in recipe.source_artifacts
    )
    return (
        "ROOT" if member.version_key.logical_artifact_id in roots else "SUPPORT",
        recipe.tool_key,
        recipe.kind,
        _mapping_text(recipe.parameters),
        _mapping_text(recipe.bindings),
        sources,
        ", ".join(recipe.output_names),
        metadata.row_count,
        format_utc_timestamp_ms(metadata.first_timestamp_ms),
        format_utc_timestamp_ms(metadata.last_timestamp_ms),
        member.version_key.logical_artifact_id,
        metadata.artifact_id,
    )
