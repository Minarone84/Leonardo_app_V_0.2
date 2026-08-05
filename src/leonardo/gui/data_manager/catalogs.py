"""Read-only Data Manager product catalog workspace."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import DataManagerProductCatalogSnapshot
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


CATALOG_FAMILIES = (
    "Study Environments",
    "Portable Recipes",
    "Recipe Collections",
    "Managed Artifacts",
    "Artifact Collections",
    "Database Seeds",
    "Databases",
)

_COLUMNS = {
    "Study Environments": (
        "Name", "Origin Market", "Entries", "Portable",
        "Portable with Dependencies", "Market Bound", "Unsupported", "Invalid",
        "Updated", "State",
    ),
    "Portable Recipes": (
        "Recipe ID", "Tool", "Version", "Kind", "Parameters", "Outputs",
        "OHLCV Inputs", "Dependencies", "Origin Markets", "Provenance Count", "State",
    ),
    "Recipe Collections": (
        "Collection", "Current Revision", "Name", "Roots", "Members",
        "Dependency Edges", "Execution Stages", "Updated", "State",
    ),
    "Managed Artifacts": (
        "Logical ID", "Current Artifact ID", "Market", "Tool", "Kind", "Outputs",
        "Rows", "Coverage", "Previous", "Created", "Currentness", "State",
    ),
    "Artifact Collections": (
        "Collection", "Revision", "Name", "Market", "Roots", "Supports", "Members",
        "Selected Outputs", "Coverage", "Database Ready", "Currentness", "State",
    ),
    "Database Seeds": (
        "Seed", "Name", "Market", "Columns", "Selected Range", "Rows", "Coverage",
        "Created", "Validation", "Usage", "State",
    ),
    "Databases": (
        "Database", "Current Revision", "Name", "Market", "Seed", "Collection Revision",
        "Rows", "Columns", "Coverage", "Currentness", "Update Mode", "Revisions", "State",
    ),
}


class DataManagerCatalogWorkspace(QWidget):
    """Display all persisted Data Manager product families without loading values."""

    family_changed = Signal(str)
    row_selected = Signal(str, object)
    history_selected = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_identity(self, "data_manager.catalogs.workspace", object_type="workspace")
        self._snapshot: DataManagerProductCatalogSnapshot | None = None
        self._all_rows: tuple[tuple[tuple[str, ...], object], ...] = ()
        self._visible_values: tuple[object, ...] = ()
        self._history_values: tuple[object, ...] = ()
        self._current_logical_identity = ""

        self.family_list = QListWidget(self)
        apply_identity(
            self.family_list,
            "data_manager.catalogs.list.families",
            object_type="list",
        )
        self.family_list.addItems(CATALOG_FAMILIES)
        self.family_list.setFixedWidth(190)

        self.table = configure_table(
            QTableWidget(self),
            object_id="data_manager.catalogs.table.family",
            columns=_COLUMNS["Study Environments"],
            labels=_COLUMNS["Study Environments"],
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self.inspector = configure_table(
            QTableWidget(self),
            object_id="data_manager.catalogs.table.inspector",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.history = configure_table(
            QTableWidget(self),
            object_id="data_manager.catalogs.table.history",
            columns=("Revision", "Created", "State"),
            labels=("Revision", "Created", "State"),
        )
        self.history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history.itemSelectionChanged.connect(self._on_history_selection)
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Inspector", right))
        right_layout.addWidget(self.inspector, 1)
        right_layout.addWidget(QLabel("Revision History", right))
        right_layout.addWidget(self.history, 1)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.addWidget(self.table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.family_list)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)

        self.family_list.currentTextChanged.connect(self._on_family_changed)
        self.family_list.setCurrentRow(0)

    @property
    def current_family(self) -> str:
        return (
            self.family_list.currentItem().text()
            if self.family_list.currentItem()
            else "Study Environments"
        )

    def set_snapshot(self, snapshot: DataManagerProductCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        self._snapshot = snapshot
        self._load_family()

    def set_inspection(
        self,
        fields: Iterable[tuple[str, object]],
        history: Iterable[tuple[str, str, str]] = (),
    ) -> None:
        field_rows = tuple((str(name), str(value)) for name, value in fields)
        history_rows = tuple(tuple(str(value) for value in row) for row in history)
        _set_rows(self.inspector, field_rows)
        _set_rows(self.history, history_rows)
        self._history_values = ()

    def set_history_items(
        self,
        logical_identity: str,
        values: Iterable[object],
    ) -> None:
        items = tuple(values)
        self._current_logical_identity = str(logical_identity)
        self._history_values = items
        _set_rows(
            self.history,
            tuple(
                (
                    _revision_identity(item),
                    str(getattr(item, "created_at_utc", "")),
                    "current" if index == len(items) - 1 else "superseded",
                )
                for index, item in enumerate(items)
            ),
        )

    def set_historical_inspection(self, value: object) -> None:
        _set_rows(self.inspector, _inspection_fields(value))

    def select_family(self, family: str) -> None:
        values = [self.family_list.item(index).text() for index in range(self.family_list.count())]
        if family not in values:
            raise ValueError(f"unknown Data Manager catalog family: {family}")
        self.family_list.setCurrentRow(values.index(family))

    def _on_family_changed(self, family: str) -> None:
        if not family:
            return
        self._load_family()
        self.family_changed.emit(family)

    def _load_family(self) -> None:
        family = self.current_family
        columns = _COLUMNS[family]
        blocker = QSignalBlocker(self.table)
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(0)
        del blocker
        self.inspector.setRowCount(0)
        self.history.setRowCount(0)
        self._history_values = ()
        self._current_logical_identity = ""
        self._all_rows = self._rows_for_family(family)
        self._populate()

    def _populate(self) -> None:
        visible = self._all_rows
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(visible))
        for row_index, (values, _value) in enumerate(visible):
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        del blocker
        self._visible_values = tuple(value for _row, value in visible)

    def _on_selection(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.row_selected.emit(self.current_family, None)
            return
        row = indexes[0].row()
        value = self._visible_values[row] if 0 <= row < len(self._visible_values) else None
        if value is not None:
            self._current_logical_identity = _logical_identity(
                self.current_family, value
            )
            self._history_values = ()
            self.history.setRowCount(0)
            self.set_inspection(_inspection_fields(value))
        self.row_selected.emit(self.current_family, value)

    def _on_history_selection(self) -> None:
        indexes = self.history.selectionModel().selectedRows()
        if not indexes:
            return
        row = indexes[0].row()
        if not 0 <= row < len(self._history_values):
            return
        value = self._history_values[row]
        _set_rows(self.inspector, _inspection_fields(value))
        self.history_selected.emit(
            self.current_family,
            self._current_logical_identity,
            value,
        )

    def _rows_for_family(self, family: str) -> tuple[tuple[tuple[str, ...], object], ...]:
        snapshot = self._snapshot
        if snapshot is None:
            return ()
        if family == "Study Environments":
            return tuple((_environment_row(item), item) for item in snapshot.study_environments.environments)
        if family == "Portable Recipes":
            return tuple((_recipe_row(item), item) for item in snapshot.portable_recipes.recipes)
        if family == "Recipe Collections":
            return tuple((_recipe_collection_row(item), item) for item in snapshot.recipe_collections.collections)
        if family == "Managed Artifacts":
            currentness = {
                item.logical_artifact_id: item
                for item in snapshot.latest_reconciliation.artifacts
            }
            return tuple(
                (_managed_artifact_row(item, currentness.get(item.logical_artifact_id)), item)
                for item in snapshot.managed_artifacts.artifacts
            )
        if family == "Artifact Collections":
            currentness = {
                item.collection_id: item
                for item in snapshot.latest_reconciliation.collections
            }
            return tuple(
                (_artifact_collection_row(item, currentness.get(item.collection_id)), item)
                for item in snapshot.artifact_collections
            )
        if family == "Database Seeds":
            usage = {item.definition.seed_id for item in snapshot.databases}
            return tuple((_seed_row(item, item.seed_id in usage), item) for item in snapshot.database_seeds)
        return tuple((_database_row(item), item) for item in snapshot.databases)


def _market(value) -> str:
    return "" if value is None else value.as_key()


def _coverage(first: int | None, last: int | None) -> str:
    return "" if first is None or last is None else f"{first} - {last}"


def _state(valid: bool, reason: str = "") -> str:
    return "valid" if valid else f"invalid: {reason}"


def _environment_row(item) -> tuple[str, ...]:
    return (
        item.display_name, _market(item.origin_market_id), str(item.entry_count),
        str(item.portable_count), str(item.portable_with_dependencies_count),
        str(item.market_bound_count), str(item.unsupported_count), str(item.invalid_count),
        "" if item.updated_at_utc is None else item.updated_at_utc.isoformat(),
        _state(item.valid, item.rejection_reason),
    )


def _recipe_row(item) -> tuple[str, ...]:
    return (
        item.recipe_id, item.tool_key, item.tool_version, item.kind,
        ", ".join(f"{key}={value}" for key, value in item.parameters.items()),
        ", ".join(item.output_names), str(item.ohlcv_input_count),
        str(item.dependency_count), ", ".join(_market(value) for value in item.origin_market_ids),
        str(item.provenance_count), _state(item.valid, item.rejection_reason),
    )


def _recipe_collection_row(item) -> tuple[str, ...]:
    return (
        item.collection_id, item.revision_id, item.display_name, str(item.root_count),
        str(item.member_count), str(item.dependency_edge_count), str(item.execution_stage_count),
        "" if item.updated_at_utc is None else item.updated_at_utc.isoformat(),
        _state(item.valid, item.rejection_reason),
    )


def _managed_artifact_row(item, currentness) -> tuple[str, ...]:
    return (
        item.logical_artifact_id, item.artifact_id, _market(item.market_id), item.tool_key,
        item.kind, ", ".join(item.output_names), str(item.row_count),
        _coverage(item.first_timestamp_ms, item.last_timestamp_ms),
        item.previous_artifact_id or "", "" if item.created_at_utc is None else item.created_at_utc.isoformat(),
        "unknown" if currentness is None else currentness.status,
        _state(item.valid, item.rejection_reason),
    )


def _artifact_collection_row(item, currentness) -> tuple[str, ...]:
    return (
        item.collection_id, item.revision_id, item.display_name, _market(item.market_id),
        str(len(item.root_logical_artifact_ids)), str(len(item.support_logical_artifact_ids)),
        str(len(item.members)), str(len(item.selected_outputs)),
        _coverage(item.first_timestamp_ms, item.last_timestamp_ms),
        "yes" if item.database_ready else "no",
        item.validation_state if currentness is None else currentness.status,
        item.validation_state,
    )


def _seed_row(item, in_use: bool) -> tuple[str, ...]:
    return (
        item.seed_id, item.display_name, _market(item.market_id),
        ", ".join(item.selected_ohlcv_columns),
        _coverage(item.selected_range_start_ms, item.selected_range_end_ms),
        str(item.source_row_count), _coverage(item.first_timestamp_ms, item.last_timestamp_ms),
        item.created_at_utc.isoformat(), "valid", "in use" if in_use else "unused", "valid",
    )


def _database_row(item) -> tuple[str, ...]:
    definition = item.definition
    manifest = item.current_manifest
    currentness = item.currentness
    return (
        definition.database_id,
        "" if manifest is None else manifest.revision_id,
        definition.display_name,
        _market(definition.market_id),
        definition.seed_id,
        "" if manifest is None else manifest.collection_revision_id,
        "" if manifest is None else str(manifest.row_count),
        "" if manifest is None else str(manifest.column_count),
        "" if manifest is None else _coverage(manifest.first_timestamp_ms, manifest.last_timestamp_ms),
        "unknown" if currentness is None else currentness.status,
        "CURRENT" if currentness is None or currentness.status == "CURRENT" else "REVIEW",
        str(item.revision_count),
        _state(item.valid, item.rejection_reason),
    )


def _inspection_fields(value: object) -> tuple[tuple[str, str], ...]:
    fields = getattr(value, "__dataclass_fields__", {})
    return tuple((name, str(getattr(value, name))) for name in fields)


def _logical_identity(family: str, value: object) -> str:
    if family in {"Recipe Collections", "Artifact Collections"}:
        return str(getattr(value, "collection_id", ""))
    if family == "Managed Artifacts":
        return str(getattr(value, "logical_artifact_id", ""))
    if family == "Databases":
        definition = getattr(value, "definition", None)
        return str(getattr(definition, "database_id", ""))
    return ""


def _revision_identity(value: object) -> str:
    return str(
        getattr(value, "revision_id", None)
        or getattr(value, "artifact_id", "")
    )


def _set_rows(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row_index, column, QTableWidgetItem(value))
