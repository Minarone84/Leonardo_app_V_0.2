"""Read-only Data Manager product catalog workspace."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
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
    ArtifactCollectionRevisionV1,
    DataManagerManagedArtifactEntry,
    DataManagerPortableRecipeEntry,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionEntry,
    DataManagerStudyEnvironmentEntry,
    DataManagerDatabaseCatalogEntry,
    DatabaseSeedV1,
    database_collection_references,
)
from leonardo.gui.data_manager.table_presentation import (
    DataManagerSortKind,
    format_data_manager_value,
    format_utc_datetime,
    format_utc_timestamp_ms,
    resize_data_manager_table,
    sort_data_manager_rows,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


CATALOG_FAMILIES = (
    "Study Environments",
    "Recipes",
    "Recipe Collections",
    "Artifacts",
    "Artifact Collections",
    "Database Seeds",
    "Databases",
)

_SCOPED_FAMILIES = {
    "Artifacts",
    "Artifact Collections",
}

_COLUMNS = {
    "Study Environments": (
        "Name", "Origin Market", "Entries", "Portable",
        "Portable with Dependencies", "Market Bound", "Unsupported", "Invalid",
        "Updated", "State",
    ),
    "Recipes": (
        "Tool", "Inputs", "Parameters", "Outputs", "State", "Recipe ID",
    ),
    "Recipe Collections": (
        "Name", "Roots", "Members", "Dependency Edges", "Execution Stages",
        "Updated", "State", "Collection ID", "Current Revision ID",
    ),
    "Artifacts": (
        "Exchange", "Market Type", "Asset", "Timeframe", "Tool", "Kind",
        "Rows", "First TS", "Last TS", "Created", "State", "Currentness",
        "Previous Artifact ID", "Outputs",
    ),
    "Artifact Collections": (
        "Exchange", "Market Type", "Asset", "Timeframe", "Name", "Roots",
        "Supports", "Members", "Selected Outputs", "First TS", "Last TS",
        "Database Ready", "State", "Currentness", "Collection ID", "Revision ID",
    ),
    "Database Seeds": (
        "Name", "Market", "Columns", "Range Start", "Range End", "Rows",
        "First TS", "Last TS", "Created", "Validation", "Usage", "State",
        "Seed ID",
    ),
    "Databases": (
        "Name", "Market", "Rows", "Columns", "First TS", "Last TS",
        "Currentness", "Update Mode", "Revisions", "State", "Seed ID",
        "Collection Revision ID", "Database ID", "Current Revision ID",
    ),
}

_NUMBER_COLUMNS = {
    "Study Environments": {
        "Entries", "Portable", "Portable with Dependencies", "Market Bound",
        "Unsupported", "Invalid",
    },
    "Recipes": set(),
    "Recipe Collections": {
        "Roots", "Members", "Dependency Edges", "Execution Stages",
    },
    "Artifacts": {"Rows"},
    "Artifact Collections": {"Roots", "Supports", "Members", "Selected Outputs"},
    "Database Seeds": {"Rows"},
    "Databases": {"Rows", "Columns", "Revisions"},
}

_UTC_COLUMNS = {
    "Study Environments": {"Updated"},
    "Recipe Collections": {"Updated"},
    "Artifacts": {"First TS", "Last TS", "Created"},
    "Artifact Collections": {"First TS", "Last TS"},
    "Database Seeds": {
        "Range Start", "Range End", "First TS", "Last TS", "Created",
    },
    "Databases": {"First TS", "Last TS"},
}

_RECIPE_DEPENDENCY_BINDING = re.compile(
    r"^(?P<role>[^=]+)=Recipe\[(?P<recipe_id>[0-9a-f]{64})\]\."
    r"(?P<output>.+)$"
)


class DataManagerCatalogWorkspace(QWidget):
    """Display all persisted Data Manager product families without loading values."""

    family_changed = Signal(str)
    row_selected = Signal(str, object)
    history_selected = Signal(str, str, object)
    create_artifact_requested = Signal()
    batch_constructs_requested = Signal()
    derive_recipes_requested = Signal(object)
    create_recipe_collection_requested = Signal()
    edit_recipe_collection_requested = Signal(object)
    create_artifact_from_recipe_requested = Signal(object)
    create_artifacts_from_recipe_collection_requested = Signal(object)
    create_artifact_collection_requested = Signal()
    edit_artifact_collection_requested = Signal(object)
    inspect_recipe_collection_requested = Signal(object)
    inspect_artifact_collection_requested = Signal(object)
    delete_recipe_requested = Signal(object)
    delete_artifact_requested = Signal(object)
    delete_recipe_collection_requested = Signal(object)
    delete_artifact_collection_requested = Signal(object)
    create_database_seed_requested = Signal()
    create_seed_only_database_requested = Signal(object)
    add_database_artifacts_requested = Signal(object)
    add_database_collection_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_identity(self, "data_manager.catalogs.workspace", object_type="workspace")
        self._snapshot: DataManagerProductCatalogSnapshot | None = None
        self._all_rows: tuple[tuple[tuple[str, ...], object], ...] = ()
        self._visible_values: tuple[object, ...] = ()
        self._history_values: tuple[object, ...] = ()
        self._current_logical_identity = ""
        self._create_artifact_enabled = False
        self._derive_recipes_enabled = False
        self._collection_actions_enabled = True
        self._materialization_actions_enabled = False
        self._deletion_actions_enabled = False
        self._create_database_seed_enabled = False
        self._create_seed_only_database_enabled = False
        self._database_content_actions_enabled = False
        self._selected_market: MarketId | None = None
        self._sort_states: dict[str, tuple[int, bool]] = {}

        self.family_list = QListWidget(self)
        apply_identity(
            self.family_list,
            "data_manager.catalogs.list.families",
            object_type="list",
        )
        self.family_list.addItems(CATALOG_FAMILIES)
        self.family_list.setMinimumWidth(150)
        self.family_list.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        self.table = configure_table(
            QTableWidget(self),
            object_id="data_manager.catalogs.table.family",
            columns=_COLUMNS["Study Environments"],
            labels=_COLUMNS["Study Environments"],
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.horizontalHeader().sectionClicked.connect(
            self._on_sort_column
        )
        self.table.itemSelectionChanged.connect(self._on_selection)

        self._inspector_panel = QGroupBox("Inspector", self)
        apply_identity(
            self._inspector_panel,
            "data_manager.catalogs.panel.inspector",
            object_type="group_box",
        )
        inspector_layout = QVBoxLayout(self._inspector_panel)
        self.inspector = configure_table(
            QTableWidget(self._inspector_panel),
            object_id="data_manager.catalogs.table.inspector",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.inspector.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        inspector_layout.addWidget(self.inspector)

        self._history_panel = QGroupBox("Revision History", self)
        apply_identity(
            self._history_panel,
            "data_manager.catalogs.panel.history",
            object_type="group_box",
        )
        history_layout = QVBoxLayout(self._history_panel)
        self.history = configure_table(
            QTableWidget(self._history_panel),
            object_id="data_manager.catalogs.table.history",
            columns=("Created", "State", "Revision ID"),
            labels=("Created", "State", "Revision ID"),
        )
        self.history.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history.itemSelectionChanged.connect(self._on_history_selection)
        history_layout.addWidget(self.history)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.scope_panel = QWidget(center)
        scope_layout = QHBoxLayout(self.scope_panel)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.addWidget(QLabel("Scope", self.scope_panel))
        self.dataset_scope = QComboBox(self.scope_panel)
        apply_identity(
            self.dataset_scope,
            "data_manager.catalogs.combo.dataset_scope",
            object_type="combo_box",
        )
        self.dataset_scope.addItem("Current Dataset", "current")
        self.dataset_scope.addItem("All Datasets", "all")
        self.dataset_scope.currentIndexChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self.dataset_scope)
        scope_layout.addStretch(1)
        center_layout.addWidget(self.scope_panel)
        action_row = QHBoxLayout()
        self.create_artifact_button = QPushButton("Create Artifact...", center)
        apply_identity(
            self.create_artifact_button,
            "data_manager.catalogs.action.create_artifact",
            object_type="button",
            display_label="Create Artifact...",
            action_id="data_manager.catalogs.action.create_artifact",
        )
        self.create_artifact_button.clicked.connect(
            self.create_artifact_requested.emit
        )
        action_row.addWidget(self.create_artifact_button)
        self.batch_constructs_button = QPushButton("Batch Constructs...", center)
        apply_identity(
            self.batch_constructs_button,
            "data_manager.catalogs.action.batch_constructs",
            object_type="button",
            display_label="Batch Constructs...",
            action_id="data_manager.catalogs.action.batch_constructs",
        )
        self.batch_constructs_button.clicked.connect(
            self.batch_constructs_requested.emit
        )
        action_row.addWidget(self.batch_constructs_button)
        self.derive_recipes_button = QPushButton("Derive Recipes...", center)
        apply_identity(
            self.derive_recipes_button,
            "data_manager.catalogs.action.derive_recipes",
            object_type="button",
            display_label="Derive Recipes...",
            action_id="data_manager.catalogs.action.derive_recipes",
        )
        self.derive_recipes_button.clicked.connect(self._emit_derive_recipes)
        action_row.addWidget(self.derive_recipes_button)
        self.create_recipe_collection_button = QPushButton(
            "Create Collection...", center
        )
        apply_identity(
            self.create_recipe_collection_button,
            "data_manager.catalogs.action.create_recipe_collection",
            object_type="button",
            display_label="Create Collection...",
            action_id="data_manager.catalogs.action.create_recipe_collection",
        )
        self.create_recipe_collection_button.clicked.connect(
            self._emit_create_recipe_collection
        )
        action_row.addWidget(self.create_recipe_collection_button)
        self.edit_recipe_collection_button = QPushButton(
            "Edit Collection...", center
        )
        apply_identity(
            self.edit_recipe_collection_button,
            "data_manager.catalogs.action.edit_recipe_collection",
            object_type="button",
            display_label="Edit Collection...",
            action_id="data_manager.catalogs.action.edit_recipe_collection",
        )
        self.edit_recipe_collection_button.clicked.connect(
            self._emit_edit_recipe_collection
        )
        action_row.addWidget(self.edit_recipe_collection_button)
        self.create_artifact_from_recipe_button = QPushButton(
            "Create Artifact...", center
        )
        apply_identity(
            self.create_artifact_from_recipe_button,
            "data_manager.catalogs.action.create_artifact_from_recipe",
            object_type="button",
            display_label="Create Artifact...",
            action_id="data_manager.catalogs.action.create_artifact_from_recipe",
        )
        self.create_artifact_from_recipe_button.clicked.connect(
            self._emit_create_artifact_from_recipe
        )
        action_row.addWidget(self.create_artifact_from_recipe_button)
        self.create_artifacts_from_recipe_collection_button = QPushButton(
            "Create Artifacts...", center
        )
        apply_identity(
            self.create_artifacts_from_recipe_collection_button,
            "data_manager.catalogs.action.create_artifacts_from_recipe_collection",
            object_type="button",
            display_label="Create Artifacts...",
            action_id=(
                "data_manager.catalogs.action."
                "create_artifacts_from_recipe_collection"
            ),
        )
        self.create_artifacts_from_recipe_collection_button.clicked.connect(
            self._emit_create_artifacts_from_recipe_collection
        )
        action_row.addWidget(self.create_artifacts_from_recipe_collection_button)
        self.create_artifact_collection_button = QPushButton(
            "Create Collection...", center
        )
        apply_identity(
            self.create_artifact_collection_button,
            "data_manager.catalogs.action.create_artifact_collection",
            object_type="button",
            display_label="Create Collection...",
            action_id="data_manager.catalogs.action.create_artifact_collection",
        )
        self.create_artifact_collection_button.clicked.connect(
            self._emit_create_artifact_collection
        )
        action_row.addWidget(self.create_artifact_collection_button)
        self.edit_artifact_collection_button = QPushButton(
            "Edit Collection...", center
        )
        apply_identity(
            self.edit_artifact_collection_button,
            "data_manager.catalogs.action.edit_artifact_collection",
            object_type="button",
            display_label="Edit Collection...",
            action_id="data_manager.catalogs.action.edit_artifact_collection",
        )
        self.edit_artifact_collection_button.clicked.connect(
            self._emit_edit_artifact_collection
        )
        action_row.addWidget(self.edit_artifact_collection_button)
        self.inspect_collection_button = QPushButton(
            "Inspect Collection...", center
        )
        apply_identity(
            self.inspect_collection_button,
            "data_manager.catalogs.action.inspect_collection",
            object_type="button",
            display_label="Inspect Collection...",
            action_id="data_manager.catalogs.action.inspect_collection",
        )
        self.inspect_collection_button.clicked.connect(
            self._emit_inspect_collection
        )
        action_row.addWidget(self.inspect_collection_button)
        self.delete_recipe_button = self._deletion_button(
            "Delete Recipe",
            "data_manager.catalogs.action.delete_recipe",
            self._emit_delete_recipe,
            center,
        )
        action_row.addWidget(self.delete_recipe_button)
        self.delete_artifact_button = self._deletion_button(
            "Delete Artifact",
            "data_manager.catalogs.action.delete_artifact",
            self._emit_delete_artifact,
            center,
        )
        action_row.addWidget(self.delete_artifact_button)
        self.delete_recipe_collection_button = self._deletion_button(
            "Delete Recipe Collection",
            "data_manager.catalogs.action.delete_recipe_collection",
            self._emit_delete_recipe_collection,
            center,
        )
        action_row.addWidget(self.delete_recipe_collection_button)
        self.delete_artifact_collection_button = self._deletion_button(
            "Delete Artifact Collection",
            "data_manager.catalogs.action.delete_artifact_collection",
            self._emit_delete_artifact_collection,
            center,
        )
        action_row.addWidget(self.delete_artifact_collection_button)
        self.create_database_seed_button = QPushButton("Create Seed...", center)
        apply_identity(
            self.create_database_seed_button,
            "data_manager.catalogs.action.create_database_seed",
            object_type="button",
            display_label="Create Seed...",
            action_id="data_manager.catalogs.action.create_database_seed",
        )
        self.create_database_seed_button.clicked.connect(
            self._emit_create_database_seed
        )
        action_row.addWidget(self.create_database_seed_button)
        self.create_seed_only_database_button = QPushButton(
            "Create Database...", center
        )
        apply_identity(
            self.create_seed_only_database_button,
            "data_manager.catalogs.action.create_seed_only_database",
            object_type="button",
            display_label="Create Database...",
            action_id="data_manager.catalogs.action.create_seed_only_database",
        )
        self.create_seed_only_database_button.clicked.connect(
            self._emit_create_seed_only_database
        )
        action_row.addWidget(self.create_seed_only_database_button)
        self.add_database_artifacts_button = QPushButton(
            "Add Artifact(s)...", center
        )
        apply_identity(
            self.add_database_artifacts_button,
            "data_manager.catalogs.action.add_database_artifacts",
            object_type="button",
            display_label="Add Artifact(s)...",
            action_id="data_manager.catalogs.action.add_database_artifacts",
        )
        self.add_database_artifacts_button.clicked.connect(
            self._emit_add_database_artifacts
        )
        action_row.addWidget(self.add_database_artifacts_button)
        self.add_database_collection_button = QPushButton(
            "Add Artifact Collection...", center
        )
        apply_identity(
            self.add_database_collection_button,
            "data_manager.catalogs.action.add_database_collection",
            object_type="button",
            display_label="Add Artifact Collection...",
            action_id="data_manager.catalogs.action.add_database_collection",
        )
        self.add_database_collection_button.clicked.connect(
            self._emit_add_database_collection
        )
        action_row.addWidget(self.add_database_collection_button)
        action_row.addStretch(1)
        center_layout.addLayout(action_row)
        center_layout.addWidget(self.table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_identity(
            splitter,
            "data_manager.catalogs.splitter.content",
            object_type="splitter",
        )
        splitter.addWidget(self.family_list)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.content_splitter = splitter
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)

        self.family_list.currentTextChanged.connect(self._on_family_changed)
        self.family_list.setCurrentRow(0)

    def inspector_panel(self) -> QWidget:
        """Return the catalog-owned Inspector panel for Suite placement."""
        return self._inspector_panel

    def history_panel(self) -> QWidget:
        """Return the catalog-owned Revision History panel for Suite placement."""
        return self._history_panel

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

    def set_selected_market(self, market_id: MarketId | None) -> None:
        if market_id is not None and not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        if market_id == self._selected_market:
            return
        self._selected_market = market_id
        blocker = QSignalBlocker(self.dataset_scope)
        self.dataset_scope.setCurrentIndex(
            self.dataset_scope.findData("current")
        )
        del blocker
        self._load_family()

    def set_create_artifact_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._create_artifact_enabled = enabled
        self.create_artifact_button.setEnabled(
            enabled and self.current_family == "Artifacts"
        )
        self.batch_constructs_button.setEnabled(
            enabled and self.current_family == "Artifacts"
        )

    def set_derive_recipes_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._derive_recipes_enabled = enabled
        self._sync_context_actions()

    def set_deletion_actions_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._deletion_actions_enabled = enabled
        self._sync_context_actions()

    def set_collection_actions_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._collection_actions_enabled = enabled
        self._sync_context_actions()

    def set_materialization_actions_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._materialization_actions_enabled = enabled
        self._sync_context_actions()

    def set_database_creation_actions_enabled(
        self, *, create_seed: bool, create_database: bool
    ) -> None:
        if type(create_seed) is not bool or type(create_database) is not bool:
            raise TypeError("Database creation action states must be booleans")
        self._create_database_seed_enabled = create_seed
        self._create_seed_only_database_enabled = create_database
        self._sync_context_actions()

    def set_database_content_actions_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("Database content action state must be a boolean")
        self._database_content_actions_enabled = enabled
        self._sync_context_actions()

    def set_inspection(
        self,
        fields: Iterable[tuple[str, object]],
        history: Iterable[tuple[str, str, str]] = (),
    ) -> None:
        field_rows = tuple(
            (str(name), format_data_manager_value(str(name), value))
            for name, value in fields
        )
        field_rows += self._currentness_inspection_fields()
        history_rows = tuple(
            (
                _history_datetime(row[1]),
                str(row[2]),
                str(row[0]),
            )
            for row in history
        )
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
                    _history_datetime(getattr(item, "created_at_utc", None)),
                    "current" if index == len(items) - 1 else "superseded",
                    _revision_identity(item),
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

    def _on_scope_changed(self, _index: int) -> None:
        if self.current_family in _SCOPED_FAMILIES:
            self._load_family()

    def _load_family(self) -> None:
        family = self.current_family
        selected_value = self._selected_value()
        self.create_artifact_button.setVisible(family == "Artifacts")
        self.batch_constructs_button.setVisible(family == "Artifacts")
        self.derive_recipes_button.setVisible(family == "Study Environments")
        self.create_recipe_collection_button.setVisible(family == "Recipes")
        self.edit_recipe_collection_button.setVisible(
            family == "Recipe Collections"
        )
        self.create_artifact_from_recipe_button.setVisible(family == "Recipes")
        self.create_artifacts_from_recipe_collection_button.setVisible(
            family == "Recipe Collections"
        )
        self.create_artifact_collection_button.setVisible(family == "Artifacts")
        self.edit_artifact_collection_button.setVisible(
            family == "Artifact Collections"
        )
        self.inspect_collection_button.setVisible(
            family in {"Recipe Collections", "Artifact Collections"}
        )
        self.delete_recipe_button.setVisible(family == "Recipes")
        self.delete_artifact_button.setVisible(family == "Artifacts")
        self.delete_recipe_collection_button.setVisible(
            family == "Recipe Collections"
        )
        self.delete_artifact_collection_button.setVisible(
            family == "Artifact Collections"
        )
        self.create_database_seed_button.setVisible(family == "Database Seeds")
        self.create_seed_only_database_button.setVisible(
            family in {"Database Seeds", "Databases"}
        )
        self.add_database_artifacts_button.setVisible(family == "Databases")
        self.add_database_collection_button.setVisible(family == "Databases")
        self.create_artifact_button.setEnabled(
            self._create_artifact_enabled and family == "Artifacts"
        )
        self.batch_constructs_button.setEnabled(
            self._create_artifact_enabled and family == "Artifacts"
        )
        self.scope_panel.setVisible(family in _SCOPED_FAMILIES)
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
        self._apply_sort_indicator()
        self._populate(selected_value=selected_value)
        self._sync_context_actions()

    def _populate(self, *, selected_value: object | None = None) -> None:
        if selected_value is None:
            selected_value = self._selected_value()
        visible = self._all_rows
        sort_state = self._sort_states.get(self.current_family)
        if sort_state is not None:
            column, descending = sort_state
            visible = sort_data_manager_rows(
                visible,
                column=column,
                kind=self._sort_kind(column),
                descending=descending,
            )
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(visible))
        self.table.clearSelection()
        for row_index, (values, _value) in enumerate(visible):
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        self._visible_values = tuple(value for _row, value in visible)
        del blocker
        if selected_value is not None:
            for row, value in enumerate(self._visible_values):
                if _same_catalog_value(self.current_family, value, selected_value):
                    self.table.selectRow(row)
                    break
        resize_data_manager_table(self.table)

    def _on_sort_column(self, column: int) -> None:
        previous = self._sort_states.get(self.current_family)
        descending = previous is not None and previous == (column, False)
        self._sort_states[self.current_family] = (column, descending)
        self._apply_sort_indicator()
        self._populate()

    def _sort_kind(self, column: int) -> DataManagerSortKind:
        label = _COLUMNS[self.current_family][column]
        if label in _NUMBER_COLUMNS.get(self.current_family, set()):
            return "number"
        if label in _UTC_COLUMNS.get(self.current_family, set()):
            return "utc"
        return "text"

    def _apply_sort_indicator(self) -> None:
        header = self.table.horizontalHeader()
        state = self._sort_states.get(self.current_family)
        header.setSortIndicatorShown(state is not None)
        if state is not None:
            column, descending = state
            header.setSortIndicator(
                column,
                Qt.SortOrder.DescendingOrder
                if descending
                else Qt.SortOrder.AscendingOrder,
            )

    def _selected_value(self) -> object | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._visible_values):
            return self._visible_values[row]
        return None

    def _on_selection(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self._sync_context_actions()
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
        self._sync_context_actions()
        self.row_selected.emit(self.current_family, value)

    def _emit_derive_recipes(self) -> None:
        value = self._selected_value()
        if (
            self.current_family == "Study Environments"
            and isinstance(value, DataManagerStudyEnvironmentEntry)
            and value.valid
            and self._derive_recipes_enabled
        ):
            self.derive_recipes_requested.emit(value)

    def _emit_delete_recipe(self) -> None:
        self._emit_deletion("Recipes", self.delete_recipe_requested)

    def _emit_delete_artifact(self) -> None:
        self._emit_deletion("Artifacts", self.delete_artifact_requested)

    def _emit_create_recipe_collection(self) -> None:
        snapshot = self._snapshot
        if (
            self._collection_actions_enabled
            and self.current_family == "Recipes"
            and snapshot is not None
            and any(item.valid for item in snapshot.portable_recipes.recipes)
        ):
            self.create_recipe_collection_requested.emit()

    def _emit_edit_recipe_collection(self) -> None:
        value = self._selected_value()
        if (
            self._collection_actions_enabled
            and self.current_family == "Recipe Collections"
            and isinstance(value, DataManagerRecipeCollectionEntry)
            and value.valid
        ):
            self.edit_recipe_collection_requested.emit(value)

    def _emit_create_artifact_from_recipe(self) -> None:
        value = self._selected_value()
        if (
            self._materialization_actions_enabled
            and self.current_family == "Recipes"
            and isinstance(value, DataManagerPortableRecipeEntry)
            and value.valid
        ):
            self.create_artifact_from_recipe_requested.emit(value)

    def _emit_create_artifacts_from_recipe_collection(self) -> None:
        value = self._selected_value()
        if (
            self._materialization_actions_enabled
            and self.current_family == "Recipe Collections"
            and isinstance(value, DataManagerRecipeCollectionEntry)
            and value.valid
        ):
            self.create_artifacts_from_recipe_collection_requested.emit(value)

    def _emit_create_artifact_collection(self) -> None:
        snapshot = self._snapshot
        if (
            self._collection_actions_enabled
            and self.current_family == "Artifacts"
            and snapshot is not None
            and any(item.valid for item in snapshot.managed_artifacts.artifacts)
        ):
            self.create_artifact_collection_requested.emit()

    def _emit_edit_artifact_collection(self) -> None:
        value = self._selected_value()
        if (
            self._collection_actions_enabled
            and self.current_family == "Artifact Collections"
            and isinstance(value, ArtifactCollectionRevisionV1)
            and value.validation_state == "valid"
        ):
            self.edit_artifact_collection_requested.emit(value)

    def _emit_inspect_collection(self) -> None:
        value = self._selected_value()
        if not self._collection_actions_enabled:
            return
        if (
            self.current_family == "Recipe Collections"
            and isinstance(value, DataManagerRecipeCollectionEntry)
            and value.valid
        ):
            self.inspect_recipe_collection_requested.emit(value)
        elif (
            self.current_family == "Artifact Collections"
            and isinstance(value, ArtifactCollectionRevisionV1)
            and value.validation_state == "valid"
        ):
            self.inspect_artifact_collection_requested.emit(value)

    def _emit_delete_recipe_collection(self) -> None:
        self._emit_deletion(
            "Recipe Collections", self.delete_recipe_collection_requested
        )

    def _emit_delete_artifact_collection(self) -> None:
        self._emit_deletion(
            "Artifact Collections", self.delete_artifact_collection_requested
        )

    def _emit_create_database_seed(self) -> None:
        if (
            self.current_family == "Database Seeds"
            and self._create_database_seed_enabled
        ):
            self.create_database_seed_requested.emit()

    def _emit_create_seed_only_database(self) -> None:
        if not (
            self.current_family in {"Database Seeds", "Databases"}
            and self._create_seed_only_database_enabled
        ):
            return
        value = self._selected_value()
        selected_seed = value if isinstance(value, DatabaseSeedV1) else None
        self.create_seed_only_database_requested.emit(selected_seed)

    def _emit_add_database_artifacts(self) -> None:
        value = self._selected_value()
        if (
            self._database_content_actions_enabled
            and self.current_family == "Databases"
            and isinstance(value, DataManagerDatabaseCatalogEntry)
        ):
            self.add_database_artifacts_requested.emit(value)

    def _emit_add_database_collection(self) -> None:
        value = self._selected_value()
        if (
            self._database_content_actions_enabled
            and self.current_family == "Databases"
            and isinstance(value, DataManagerDatabaseCatalogEntry)
        ):
            self.add_database_collection_requested.emit(value)

    def _emit_deletion(self, family: str, signal: object) -> None:
        value = self._selected_value()
        if (
            self._deletion_actions_enabled
            and self.current_family == family
            and _valid_deletion_target(family, value)
        ):
            signal.emit(value)

    def _sync_context_actions(self) -> None:
        value = self._selected_value()
        snapshot = self._snapshot
        self.create_recipe_collection_button.setEnabled(
            self._collection_actions_enabled
            and self.current_family == "Recipes"
            and snapshot is not None
            and any(item.valid for item in snapshot.portable_recipes.recipes)
        )
        self.edit_recipe_collection_button.setEnabled(
            self._collection_actions_enabled
            and self.current_family == "Recipe Collections"
            and isinstance(value, DataManagerRecipeCollectionEntry)
            and value.valid
        )
        self.create_artifact_from_recipe_button.setEnabled(
            self._materialization_actions_enabled
            and self.current_family == "Recipes"
            and isinstance(value, DataManagerPortableRecipeEntry)
            and value.valid
        )
        self.create_artifacts_from_recipe_collection_button.setEnabled(
            self._materialization_actions_enabled
            and self.current_family == "Recipe Collections"
            and isinstance(value, DataManagerRecipeCollectionEntry)
            and value.valid
        )
        self.create_artifact_collection_button.setEnabled(
            self._collection_actions_enabled
            and self.current_family == "Artifacts"
            and snapshot is not None
            and any(item.valid for item in snapshot.managed_artifacts.artifacts)
        )
        self.edit_artifact_collection_button.setEnabled(
            self._collection_actions_enabled
            and self.current_family == "Artifact Collections"
            and isinstance(value, ArtifactCollectionRevisionV1)
            and value.validation_state == "valid"
        )
        self.inspect_collection_button.setEnabled(
            self._collection_actions_enabled
            and (
                (
                    self.current_family == "Recipe Collections"
                    and isinstance(value, DataManagerRecipeCollectionEntry)
                    and value.valid
                )
                or (
                    self.current_family == "Artifact Collections"
                    and isinstance(value, ArtifactCollectionRevisionV1)
                    and value.validation_state == "valid"
                )
            )
        )
        self.derive_recipes_button.setEnabled(
            self._derive_recipes_enabled
            and self.current_family == "Study Environments"
            and isinstance(value, DataManagerStudyEnvironmentEntry)
            and value.valid
        )
        enabled_family = (
            self.current_family
            if self._deletion_actions_enabled
            and _valid_deletion_target(self.current_family, value)
            else ""
        )
        self.delete_recipe_button.setEnabled(enabled_family == "Recipes")
        self.delete_artifact_button.setEnabled(enabled_family == "Artifacts")
        self.delete_recipe_collection_button.setEnabled(
            enabled_family == "Recipe Collections"
        )
        self.delete_artifact_collection_button.setEnabled(
            enabled_family == "Artifact Collections"
        )
        self.create_database_seed_button.setEnabled(
            self._create_database_seed_enabled
            and self.current_family == "Database Seeds"
        )
        self.create_seed_only_database_button.setEnabled(
            self._create_seed_only_database_enabled
            and self.current_family in {"Database Seeds", "Databases"}
        )
        database_content_enabled = (
            self._database_content_actions_enabled
            and self.current_family == "Databases"
            and isinstance(value, DataManagerDatabaseCatalogEntry)
        )
        self.add_database_artifacts_button.setEnabled(database_content_enabled)
        self.add_database_collection_button.setEnabled(database_content_enabled)

    @staticmethod
    def _deletion_button(
        label: str,
        object_id: str,
        callback: object,
        parent: QWidget,
    ) -> QPushButton:
        button = QPushButton(label, parent)
        apply_identity(
            button,
            object_id,
            object_type="button",
            display_label=label,
            action_id=object_id,
        )
        button.clicked.connect(callback)
        return button

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
        if family == "Recipes":
            recipes_by_id = {
                item.recipe_id: item for item in snapshot.portable_recipes.recipes
            }
            return tuple(
                (_recipe_row(item, recipes_by_id), item)
                for item in snapshot.portable_recipes.recipes
            )
        if family == "Recipe Collections":
            return tuple(
                (_recipe_collection_row(item), item)
                for item in snapshot.recipe_collections.collections
            )
        if family == "Artifacts":
            return tuple(
                (
                    _managed_artifact_row(
                        item,
                        _artifact_currentness(snapshot, item.logical_artifact_id),
                    ),
                    item,
                )
                for item in snapshot.managed_artifacts.artifacts
                if self._market_is_visible(item.market_id)
            )
        if family == "Artifact Collections":
            return tuple(
                (
                    _artifact_collection_row(
                        item,
                        _collection_currentness(snapshot, item.collection_id),
                    ),
                    item,
                )
                for item in snapshot.artifact_collections
                if self._market_is_visible(item.market_id)
            )
        if family == "Database Seeds":
            usage = {item.definition.seed_id for item in snapshot.databases}
            return tuple((_seed_row(item, item.seed_id in usage), item) for item in snapshot.database_seeds)
        return tuple((_database_row(item), item) for item in snapshot.databases)

    def _market_is_visible(self, market_id: MarketId) -> bool:
        return (
            self.dataset_scope.currentData() == "all"
            or market_id == self._selected_market
        )

    def _currentness_inspection_fields(self) -> tuple[tuple[str, str], ...]:
        snapshot = self._snapshot
        if snapshot is None or not self._current_logical_identity:
            return ()
        candidates: Iterable[object]
        if self.current_family == "Artifacts":
            candidates = snapshot.latest_reconciliation.artifacts
            identity_name = "logical_artifact_id"
        elif self.current_family == "Artifact Collections":
            candidates = snapshot.latest_reconciliation.collections
            identity_name = "collection_id"
        elif self.current_family == "Databases":
            candidates = snapshot.latest_reconciliation.databases
            identity_name = "database_id"
        else:
            return ()
        currentness = next(
            (
                item
                for item in candidates
                if str(getattr(item, identity_name, ""))
                == self._current_logical_identity
            ),
            None,
        )
        if currentness is None:
            return ()
        return tuple(
            (
                f"currentness.{name}",
                format_data_manager_value(name, getattr(currentness, name)),
            )
            for name in getattr(currentness, "__dataclass_fields__", {})
        )


def _market(value) -> str:
    return "" if value is None else value.as_key()


def _market_columns(value: MarketId | None) -> tuple[str, str, str, str]:
    if value is None:
        return "", "", "", ""
    return value.exchange, value.market_type, value.symbol, value.timeframe


def _state(valid: bool, reason: str = "") -> str:
    return "valid" if valid else f"invalid: {reason}"


def _environment_row(item) -> tuple[str, ...]:
    return (
        item.display_name, _market(item.origin_market_id), str(item.entry_count),
        str(item.portable_count), str(item.portable_with_dependencies_count),
        str(item.market_bound_count), str(item.unsupported_count), str(item.invalid_count),
        format_utc_datetime(item.updated_at_utc),
        _state(item.valid, item.rejection_reason),
    )


def _recipe_parameters(parameters: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={value}" for key, value in parameters.items())


def _recipe_input_binding(
    value: str,
    recipes_by_id: Mapping[str, DataManagerPortableRecipeEntry],
) -> str:
    match = _RECIPE_DEPENDENCY_BINDING.fullmatch(value)
    if match is None:
        return value
    dependency = recipes_by_id.get(match.group("recipe_id"))
    if dependency is None or not dependency.tool_key:
        return value
    parameters = _recipe_parameters(dependency.parameters)
    label = (
        f"{dependency.tool_key}({parameters})"
        if parameters
        else dependency.tool_key
    )
    return f"{match.group('role')}={label}.{match.group('output')}"


def _recipe_row(
    item: DataManagerPortableRecipeEntry,
    recipes_by_id: Mapping[str, DataManagerPortableRecipeEntry],
) -> tuple[str, ...]:
    return (
        item.tool_key,
        ", ".join(
            _recipe_input_binding(value, recipes_by_id)
            for value in item.input_bindings
        ),
        _recipe_parameters(item.parameters),
        ", ".join(item.output_names),
        _state(item.valid, item.rejection_reason), item.recipe_id,
    )


def _valid_deletion_target(family: str, value: object) -> bool:
    if family == "Recipes":
        return isinstance(value, DataManagerPortableRecipeEntry) and value.valid
    if family == "Recipe Collections":
        return isinstance(value, DataManagerRecipeCollectionEntry) and value.valid
    if family == "Artifacts":
        return isinstance(value, DataManagerManagedArtifactEntry) and value.valid
    if family == "Artifact Collections":
        return (
            isinstance(value, ArtifactCollectionRevisionV1)
            and value.validation_state == "valid"
        )
    return False


def _recipe_collection_row(item) -> tuple[str, ...]:
    return (
        item.display_name, str(item.root_count),
        str(item.member_count), str(item.dependency_edge_count), str(item.execution_stage_count),
        format_utc_datetime(item.updated_at_utc),
        _state(item.valid, item.rejection_reason), item.collection_id, item.revision_id,
    )


def _managed_artifact_row(item, currentness: str) -> tuple[str, ...]:
    return (
        *_market_columns(item.market_id), item.tool_key, item.kind,
        str(item.row_count),
        format_utc_timestamp_ms(item.first_timestamp_ms),
        format_utc_timestamp_ms(item.last_timestamp_ms),
        format_utc_datetime(item.created_at_utc),
        _state(item.valid, item.rejection_reason),
        currentness,
        item.previous_artifact_id or "", ", ".join(item.output_names),
    )


def _artifact_collection_row(item, currentness: str) -> tuple[str, ...]:
    return (
        *_market_columns(item.market_id), item.display_name,
        str(len(item.root_logical_artifact_ids)), str(len(item.support_logical_artifact_ids)),
        str(len(item.members)), str(len(item.selected_outputs)),
        format_utc_timestamp_ms(item.first_timestamp_ms),
        format_utc_timestamp_ms(item.last_timestamp_ms),
        "yes" if item.database_ready else "no",
        item.validation_state,
        currentness,
        item.collection_id, item.revision_id,
    )


def _seed_row(item, in_use: bool) -> tuple[str, ...]:
    return (
        item.display_name, _market(item.market_id),
        ", ".join(item.selected_ohlcv_columns),
        format_utc_timestamp_ms(item.selected_range_start_ms),
        format_utc_timestamp_ms(item.selected_range_end_ms),
        str(item.source_row_count),
        format_utc_timestamp_ms(item.first_timestamp_ms),
        format_utc_timestamp_ms(item.last_timestamp_ms),
        format_utc_datetime(item.created_at_utc), "valid",
        "in use" if in_use else "unused", "valid", item.seed_id,
    )


def _database_row(item) -> tuple[str, ...]:
    definition = item.definition
    manifest = item.current_manifest
    currentness = item.currentness
    return (
        definition.display_name,
        _market(definition.market_id),
        "" if manifest is None else str(manifest.row_count),
        "" if manifest is None else str(manifest.column_count),
        "" if manifest is None else format_utc_timestamp_ms(manifest.first_timestamp_ms),
        "" if manifest is None else format_utc_timestamp_ms(manifest.last_timestamp_ms),
        _database_currentness(currentness),
        "CURRENT" if currentness is None or currentness.status == "CURRENT" else "REVIEW",
        str(item.revision_count),
        _state(item.valid, item.rejection_reason),
        definition.seed_id,
        (
            ""
            if manifest is None
            else ", ".join(
                reference.revision_id
                for reference in database_collection_references(manifest)
            )
        ),
        definition.database_id,
        "" if manifest is None else manifest.revision_id,
    )


_ARTIFACT_CURRENTNESS = {
    "CURRENT": "CURRENT",
    "APPEND_AVAILABLE": "UPDATE AVAILABLE",
    "HISTORICAL_SOURCE_CHANGED": "UPDATE AVAILABLE",
    "REBUILD_REQUIRED": "UPDATE AVAILABLE",
    "RECIPE_CHANGED": "UPDATE AVAILABLE",
    "BLOCKED_BY_DEPENDENCY": "BLOCKED",
    "INVALID": "INVALID",
}

_COLLECTION_CURRENTNESS = {
    "CURRENT": "CURRENT",
    "DATABASE_READY": "CURRENT",
    "MEMBERS_REQUIRE_UPDATE": "UPDATE AVAILABLE",
    "PARTIALLY_ALIGNED": "UPDATE AVAILABLE",
    "REBUILD_REQUIRED": "UPDATE AVAILABLE",
    "NOT_DATABASE_READY": "UPDATE AVAILABLE",
    "BLOCKED_BY_DEPENDENCY": "BLOCKED",
    "SOURCE_INVALID": "INVALID",
}

_DATABASE_CURRENTNESS = {
    "CURRENT": "CURRENT",
    "UPDATE_AVAILABLE": "UPDATE AVAILABLE",
    "REBUILD_REQUIRED": "UPDATE AVAILABLE",
    "COLLECTION_CHANGED": "UPDATE AVAILABLE",
    "SCHEMA_CHANGED": "UPDATE AVAILABLE",
    "PREFIX_MISMATCH": "UPDATE AVAILABLE",
    "WAITING_FOR_ARTIFACT_UPDATE": "BLOCKED",
    "SOURCE_INVALID": "INVALID",
}


def _artifact_currentness(
    snapshot: DataManagerProductCatalogSnapshot,
    logical_artifact_id: str,
) -> str:
    row = next(
        (
            item
            for item in snapshot.latest_reconciliation.artifacts
            if item.logical_artifact_id == logical_artifact_id
        ),
        None,
    )
    return "VERIFYING" if row is None else _ARTIFACT_CURRENTNESS[row.status]


def _collection_currentness(
    snapshot: DataManagerProductCatalogSnapshot,
    collection_id: str,
) -> str:
    row = next(
        (
            item
            for item in snapshot.latest_reconciliation.collections
            if item.collection_id == collection_id
        ),
        None,
    )
    return "VERIFYING" if row is None else _COLLECTION_CURRENTNESS[row.status]


def _database_currentness(currentness: object | None) -> str:
    if currentness is None:
        return "VERIFYING"
    return _DATABASE_CURRENTNESS[str(getattr(currentness, "status"))]


def _inspection_fields(value: object) -> tuple[tuple[str, str], ...]:
    fields = getattr(value, "__dataclass_fields__", {})
    return tuple(
        (name, format_data_manager_value(name, getattr(value, name)))
        for name in fields
    )


def _logical_identity(family: str, value: object) -> str:
    if family == "Study Environments":
        return str(getattr(value, "environment_id", ""))
    if family in {"Recipe Collections", "Artifact Collections"}:
        return str(getattr(value, "collection_id", ""))
    if family == "Artifacts":
        return str(getattr(value, "logical_artifact_id", ""))
    if family == "Databases":
        definition = getattr(value, "definition", None)
        return str(getattr(definition, "database_id", ""))
    return ""


def _same_catalog_value(family: str, left: object, right: object) -> bool:
    left_identity = _logical_identity(family, left)
    right_identity = _logical_identity(family, right)
    if left_identity or right_identity:
        return bool(left_identity) and left_identity == right_identity
    return left == right


def _revision_identity(value: object) -> str:
    return str(
        getattr(value, "revision_id", None)
        or getattr(value, "artifact_id", "")
    )


def _history_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return format_utc_datetime(value)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return format_utc_datetime(parsed)
    return str(value or "")


def _set_rows(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row_index, column, QTableWidgetItem(value))
    resize_data_manager_table(table)
