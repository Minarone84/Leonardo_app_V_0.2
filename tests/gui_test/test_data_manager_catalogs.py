from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTabWidget,
)

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionRevisionV1,
    DataManagerArtifactCurrentness,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerManagedArtifactEntry,
    DataManagerManagedArtifactCatalog,
    DataManagerPortableRecipeEntry,
    DataManagerPortableRecipeCatalog,
    DataManagerProductCatalogSnapshot,
    DataManagerCollectionCurrentness,
    DataManagerDatabaseCatalogEntry,
    DataManagerDatabaseCurrentness,
    DataManagerRecipeCollectionEntry,
    DataManagerRecipeCollectionCatalog,
    DataManagerReconciliationSnapshot,
    DataManagerStudyEnvironmentCatalog,
    DataManagerStudyEnvironmentEntry,
    DatabaseDefinitionV1,
)
from leonardo.gui.data_manager.catalogs import CATALOG_FAMILIES, _COLUMNS
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


EXPECTED_FAMILIES = (
    "Study Environments",
    "Recipes",
    "Recipe Collections",
    "Artifacts",
    "Artifact Collections",
    "Database Seeds",
    "Databases",
)

MARKET_A = MarketId("bybit", "linear", "BTCUSDT", "1h")
MARKET_B = MarketId("bybit", "linear", "ETHUSDT", "4h")
TIMESTAMP_MS = 1786297337123


def empty_product_snapshot() -> DataManagerProductCatalogSnapshot:
    return DataManagerProductCatalogSnapshot(
        DataManagerCatalogSnapshot(()),
        DataManagerStudyEnvironmentCatalog(()),
        DataManagerPortableRecipeCatalog(()),
        DataManagerRecipeCollectionCatalog(()),
        DataManagerManagedArtifactCatalog(()),
        (),
        (),
        (),
        DataManagerReconciliationSnapshot(
            datetime(2026, 8, 4, tzinfo=UTC), (), (), (), (), (), "0" * 64
        ),
    )


def _artifact_collection(
    market: MarketId, *, collection_id: str, revision_id: str, name: str
) -> ArtifactCollectionRevisionV1:
    value = object.__new__(ArtifactCollectionRevisionV1)
    attributes = {
        "collection_id": collection_id,
        "revision_id": revision_id,
        "display_name": name,
        "description": "",
        "market_id": market,
        "root_logical_artifact_ids": ("d" * 64,),
        "support_logical_artifact_ids": (),
        "members": (object(),),
        "dependency_edges": (),
        "selected_outputs": (object(),),
        "presentation_order": ("value",),
        "source_portable_recipe_ids": ("a" * 64,),
        "source_recipe_collection_id": None,
        "source_recipe_collection_revision_id": None,
        "source_ohlcv": OHLCVSourceFingerprintV1(
            market,
            "1" * 64,
            "2" * 64,
            1,
            TIMESTAMP_MS,
            TIMESTAMP_MS,
            "committed",
            "ok",
            "1.0",
        ),
        "first_timestamp_ms": TIMESTAMP_MS,
        "last_timestamp_ms": TIMESTAMP_MS,
        "database_ready": True,
        "validation_state": "valid",
        "previous_revision_id": None,
        "created_at_utc": datetime.fromtimestamp(TIMESTAMP_MS / 1000, tz=UTC),
        "revised_at_utc": datetime.fromtimestamp(TIMESTAMP_MS / 1000, tz=UTC),
        "schema_version": "1.0",
        "object_type": "artifact_collection_revision",
    }
    for name, item in attributes.items():
        object.__setattr__(value, name, item)
    return value


def associated_product_snapshot() -> DataManagerProductCatalogSnapshot:
    associated_id = "a" * 64
    unassociated_id = "b" * 64
    associated = DataManagerPortableRecipeEntry(
        associated_id, "sma", "1.0", "indicator", {"period": 20},
        ("sma_20",), ("source=OHLCV.close",), 0, 1,
        (MARKET_A,), (), (), 1,
    )
    unassociated = DataManagerPortableRecipeEntry(
        unassociated_id, "rsi", "1.0", "oscillator", {"period": 14},
        ("rsi_14",), ("source=OHLCV.close",), 0, 1, (), (), (), 0,
    )
    artifact = DataManagerManagedArtifactEntry(
        "c" * 64, associated_id, MARKET_B, "d" * 64, None, "sma",
        "indicator", ("sma_20",), 1, TIMESTAMP_MS, TIMESTAMP_MS,
        datetime.fromtimestamp(TIMESTAMP_MS / 1000, tz=UTC),
    )
    associated_collection = DataManagerRecipeCollectionEntry(
        "collection_associated", "e" * 64, "Associated", "", 2, 2,
        (associated_id, unassociated_id), 0, 1,
        datetime(2026, 8, 9, tzinfo=UTC),
        datetime.fromtimestamp(TIMESTAMP_MS / 1000, tz=UTC),
    )
    unassociated_collection = DataManagerRecipeCollectionEntry(
        "collection_unassociated", "f" * 64, "Unassociated", "", 1, 1,
        (unassociated_id,), 0, 1, datetime(2026, 8, 9, tzinfo=UTC),
        datetime.fromtimestamp(TIMESTAMP_MS / 1000, tz=UTC),
    )
    return DataManagerProductCatalogSnapshot(
        DataManagerCatalogSnapshot(()),
        DataManagerStudyEnvironmentCatalog(()),
        DataManagerPortableRecipeCatalog((associated, unassociated)),
        DataManagerRecipeCollectionCatalog(
            (associated_collection, unassociated_collection)
        ),
        DataManagerManagedArtifactCatalog((artifact,)),
        (
            _artifact_collection(
                MARKET_A,
                collection_id="artifact_collection_a",
                revision_id="1" * 64,
                name="A Collection",
            ),
            _artifact_collection(
                MARKET_B,
                collection_id="artifact_collection_b",
                revision_id="2" * 64,
                name="B Collection",
            ),
        ),
        (),
        (),
        DataManagerReconciliationSnapshot(
            datetime(2026, 8, 9, tzinfo=UTC),
            (),
            (
                DataManagerArtifactCurrentness(
                    "c" * 64, "d" * 64, associated_id, MARKET_B, "CURRENT",
                    False, TIMESTAMP_MS, TIMESTAMP_MS, 0, (), (),
                ),
            ),
            (
                DataManagerCollectionCurrentness(
                    "artifact_collection_b", "2" * 64, MARKET_B, "CURRENT",
                    TIMESTAMP_MS, TIMESTAMP_MS, 0, 0, True, (),
                ),
            ),
            (),
            (),
            "0" * 64,
        ),
    )


def sortable_artifact_snapshot() -> DataManagerProductCatalogSnapshot:
    snapshot = associated_product_snapshot()
    artifacts = (
        DataManagerManagedArtifactEntry(
            "a" * 64, "1" * 64, MARKET_B, "4" * 64, None, "sma",
            "indicator", ("sma_20",), 100, 7_200_000, 7_200_000,
            datetime.fromtimestamp(7_200, tz=UTC),
        ),
        DataManagerManagedArtifactEntry(
            "b" * 64, "2" * 64, MARKET_B, "5" * 64, None, "ema",
            "indicator", ("ema_20",), 2, 0, 0,
            datetime.fromtimestamp(0, tz=UTC),
        ),
        DataManagerManagedArtifactEntry(
            "c" * 64, "3" * 64, MARKET_B, "6" * 64, None, "rsi",
            "oscillator", ("rsi_14",), 10, 3_600_000, 3_600_000,
            datetime.fromtimestamp(3_600, tz=UTC),
        ),
    )
    return replace(
        snapshot,
        managed_artifacts=DataManagerManagedArtifactCatalog(artifacts),
    )


def _database_entry(
    currentness: DataManagerDatabaseCurrentness | None,
) -> DataManagerDatabaseCatalogEntry:
    definition = DatabaseDefinitionV1(
        "db_" + "1" * 32,
        "Research Database",
        "",
        MARKET_B,
        "seed_" + "2" * 32,
        datetime(2026, 8, 9, tzinfo=UTC),
    )
    return DataManagerDatabaseCatalogEntry(definition, None, 1, currentness)


def _environment(
    environment_id: str,
    display_name: str,
    *,
    valid: bool = True,
) -> DataManagerStudyEnvironmentEntry:
    return DataManagerStudyEnvironmentEntry(
        environment_id,
        display_name,
        "",
        MARKET_A,
        1,
        1,
        0,
        0,
        0,
        0,
        datetime(2026, 8, 17, tzinfo=UTC),
        datetime(2026, 8, 17, tzinfo=UTC),
        valid,
        "invalid Environment" if not valid else "",
    )


def _environment_snapshot(
    *environments: DataManagerStudyEnvironmentEntry,
) -> DataManagerProductCatalogSnapshot:
    return replace(
        empty_product_snapshot(),
        study_environments=DataManagerStudyEnvironmentCatalog(environments),
    )


def _column(workspace, label: str) -> int:
    return next(
        column
        for column in range(workspace.table.columnCount())
        if workspace.table.horizontalHeaderItem(column).text() == label
    )


def _column_values(workspace, label: str) -> tuple[str, ...]:
    column = _column(workspace, label)
    return tuple(
        workspace.table.item(row, column).text()
        for row in range(workspace.table.rowCount())
    )


def _click_header(workspace, label: str) -> None:
    workspace.table.horizontalHeader().sectionClicked.emit(
        _column(workspace, label)
    )
    QCoreApplication.processEvents()


def test_catalog_workspace_exposes_seven_non_dataset_families() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        assert CATALOG_FAMILIES == EXPECTED_FAMILIES
        assert "Portable Recipes" not in CATALOG_FAMILIES
        assert "Managed Artifacts" not in CATALOG_FAMILIES
        assert tuple(
            window._catalog_workspace.family_list.item(index).text()
            for index in range(window._catalog_workspace.family_list.count())
        ) == EXPECTED_FAMILIES
        window.set_product_catalogs(empty_product_snapshot())
        for family in CATALOG_FAMILIES:
            window._catalog_workspace.select_family(family)
            assert window._catalog_workspace.current_family == family
            assert window._catalog_workspace.table.columnCount() > 0
    finally:
        window.close()


def test_collection_actions_are_contextual_exact_and_busy_fenced() -> None:
    window = DataManagerSuiteWindow()
    workspace = window._catalog_workspace
    snapshot = associated_product_snapshot()
    recipe_create: list[bool] = []
    recipe_edit: list[object] = []
    artifact_create: list[bool] = []
    artifact_edit: list[object] = []
    workspace.create_recipe_collection_requested.connect(
        lambda: recipe_create.append(True)
    )
    workspace.edit_recipe_collection_requested.connect(recipe_edit.append)
    workspace.create_artifact_collection_requested.connect(
        lambda: artifact_create.append(True)
    )
    workspace.edit_artifact_collection_requested.connect(artifact_edit.append)
    try:
        workspace.set_snapshot(snapshot)
        actions = {
            "Recipes": workspace.create_recipe_collection_button,
            "Recipe Collections": workspace.edit_recipe_collection_button,
            "Artifacts": workspace.create_artifact_collection_button,
            "Artifact Collections": workspace.edit_artifact_collection_button,
        }
        assert {
            family: button.objectName() for family, button in actions.items()
        } == {
            "Recipes": "data_manager.catalogs.action.create_recipe_collection",
            "Recipe Collections": "data_manager.catalogs.action.edit_recipe_collection",
            "Artifacts": "data_manager.catalogs.action.create_artifact_collection",
            "Artifact Collections": "data_manager.catalogs.action.edit_artifact_collection",
        }

        workspace.select_family("Recipes")
        assert workspace.create_recipe_collection_button.isEnabled()
        workspace.create_recipe_collection_button.click()
        assert recipe_create == [True]

        workspace.select_family("Recipe Collections")
        assert not workspace.edit_recipe_collection_button.isEnabled()
        workspace.table.selectRow(0)
        assert workspace.edit_recipe_collection_button.isEnabled()
        workspace.edit_recipe_collection_button.click()
        assert recipe_edit == [workspace._visible_values[0]]

        workspace.select_family("Artifacts")
        assert workspace.create_artifact_collection_button.isEnabled()
        workspace.create_artifact_collection_button.click()
        assert artifact_create == [True]

        workspace.dataset_scope.setCurrentIndex(1)
        workspace.select_family("Artifact Collections")
        assert not workspace.edit_artifact_collection_button.isEnabled()
        workspace.table.selectRow(0)
        assert workspace.edit_artifact_collection_button.isEnabled()
        workspace.edit_artifact_collection_button.click()
        assert artifact_edit == [workspace._visible_values[0]]

        workspace.set_collection_actions_enabled(False)
        assert all(not button.isEnabled() for button in actions.values())
    finally:
        window.close()


def test_recipe_materialization_actions_require_exact_source_and_dataset() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    workspace = window._catalog_workspace
    snapshot = associated_product_snapshot()
    recipe_values: list[object] = []
    collection_values: list[object] = []
    workspace.create_artifact_from_recipe_requested.connect(recipe_values.append)
    workspace.create_artifacts_from_recipe_collection_requested.connect(
        collection_values.append
    )
    try:
        workspace.set_snapshot(snapshot)
        window.set_catalog(
            DataManagerCatalogSnapshot(
                (DataManagerDatasetEntry(MARKET_A, True, 1, 0, 0),)
            )
        )
        assert workspace.create_artifact_from_recipe_button.objectName() == (
            "data_manager.catalogs.action.create_artifact_from_recipe"
        )
        assert (
            workspace.create_artifacts_from_recipe_collection_button.objectName()
            == "data_manager.catalogs.action.create_artifacts_from_recipe_collection"
        )

        workspace.select_family("Recipes")
        assert not workspace.create_artifact_from_recipe_button.isHidden()
        assert not workspace.create_artifact_from_recipe_button.isEnabled()
        assert not workspace.create_artifact_from_recipe_button.isEnabled()
        assert window.select_market(MARKET_A, emit_selection=False)
        assert not workspace.create_artifact_from_recipe_button.isEnabled()
        workspace.table.selectRow(0)
        assert workspace.create_artifact_from_recipe_button.isEnabled()
        recipe = workspace._visible_values[0]
        workspace.create_artifact_from_recipe_button.click()
        assert recipe_values == [recipe]

        workspace.select_family("Recipe Collections")
        assert not workspace.create_artifacts_from_recipe_collection_button.isHidden()
        assert not workspace.create_artifacts_from_recipe_collection_button.isEnabled()
        workspace.table.selectRow(0)
        collection = workspace._visible_values[0]
        assert workspace.create_artifacts_from_recipe_collection_button.isEnabled()
        workspace.create_artifacts_from_recipe_collection_button.click()
        assert collection_values == [collection]

        workspace.set_materialization_actions_enabled(False)
        assert not workspace.create_artifacts_from_recipe_collection_button.isEnabled()
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_from_recipe_button.isHidden()
        assert workspace.create_artifacts_from_recipe_collection_button.isHidden()
    finally:
        window.close()


def test_main_catalog_workspace_has_no_dataset_filters_or_ohlcv_family() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        assert "OHLCV" not in CATALOG_FAMILIES
        for key in ("exchange", "market_type", "symbol", "timeframe", "text"):
            assert window.findChild(
                QObject,
                f"data_manager.catalogs.filter.{key}",
            ) is None
        assert window.findChild(QObject, "data_manager.table.datasets") is None
    finally:
        window.close()


def test_data_manager_top_level_tabs_and_catalog_ids_are_stable() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        tabs = window.findChild(QTabWidget, "data_manager.tabs.workspace")
        assert tabs is not None
        assert tuple(
            tabs.tabText(index) for index in range(tabs.count())
        ) == ("Catalogs", "Create Database", "Update & Reconcile")
        assert window._catalog_workspace.objectName() == "data_manager.catalogs.workspace"
        assert (
            window._catalog_workspace.table.objectName()
            == "data_manager.catalogs.table.family"
        )
    finally:
        window.close()


def test_catalog_detail_panels_and_content_are_independently_responsive() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        workspace = window._catalog_workspace
        inspector_panel = workspace.inspector_panel()
        history_panel = workspace.history_panel()
        splitter = workspace.findChild(
            QSplitter, "data_manager.catalogs.splitter.content"
        )

        assert isinstance(inspector_panel, QGroupBox)
        assert inspector_panel.title() == "Inspector"
        assert isinstance(history_panel, QGroupBox)
        assert history_panel.title() == "Revision History"
        assert inspector_panel.findChildren(QTableWidget) == [workspace.inspector]
        assert history_panel.findChildren(QTableWidget) == [workspace.history]
        assert workspace.inspector.objectName() == (
            "data_manager.catalogs.table.inspector"
        )
        assert workspace.history.objectName() == (
            "data_manager.catalogs.table.history"
        )
        assert workspace.family_list.minimumWidth() == 150
        assert workspace.family_list.maximumWidth() > 150
        assert workspace.family_list.sizePolicy().horizontalPolicy() == (
            QSizePolicy.Policy.Preferred
        )
        assert workspace.family_list.sizePolicy().verticalPolicy() == (
            QSizePolicy.Policy.Expanding
        )
        assert workspace.table.sizePolicy().horizontalPolicy() == (
            QSizePolicy.Policy.Expanding
        )
        assert workspace.table.sizePolicy().verticalPolicy() == (
            QSizePolicy.Policy.Expanding
        )
        assert splitter is workspace.content_splitter
        assert splitter.count() == 2
        assert splitter.widget(0) is workspace.family_list
        assert splitter.widget(1) is workspace.table.parentWidget()

        snapshot = associated_product_snapshot()
        workspace.set_snapshot(snapshot)
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifacts")
        workspace.table.selectRow(0)
        assert workspace.inspector.rowCount() > 0
        historical = snapshot.managed_artifacts.artifacts[0]
        selected = []
        workspace.history_selected.connect(lambda *args: selected.append(args))
        workspace.set_history_items("logical", (historical,))
        workspace.history.selectRow(0)
        assert selected[-1][1:] == ("logical", historical)
        assert workspace.inspector.rowCount() > 0
    finally:
        window.close()


def test_create_artifact_action_is_contextual_and_externally_controlled() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    emitted: list[None] = []
    batches: list[None] = []
    try:
        workspace = window._catalog_workspace
        workspace.create_artifact_requested.connect(lambda: emitted.append(None))
        workspace.batch_constructs_requested.connect(lambda: batches.append(None))
        button = workspace.create_artifact_button
        batch_button = workspace.batch_constructs_button
        assert button.objectName() == "data_manager.catalogs.action.create_artifact"
        center_layout = button.parentWidget().layout()
        assert center_layout.itemAt(1).layout().indexOf(button) == 0
        assert center_layout.itemAt(2).widget() is workspace.table

        for family in CATALOG_FAMILIES:
            workspace.select_family(family)
            workspace.set_create_artifact_enabled(True)
            assert button.isVisibleTo(workspace) is (family == "Artifacts")
            assert button.isEnabled() is (family == "Artifacts")
            assert batch_button.isVisibleTo(workspace) is (family == "Artifacts")
            assert batch_button.isEnabled() is (family == "Artifacts")

        workspace.select_family("Artifacts")
        workspace.set_create_artifact_enabled(True)
        button.click()
        batch_button.click()
        assert emitted == [None]
        assert batches == [None]
        workspace.set_create_artifact_enabled(False)
        assert not button.isEnabled()
    finally:
        window.close()


def test_catalog_delete_actions_are_contextual_valid_exact_and_sort_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        workspace = window._catalog_workspace
        snapshot = associated_product_snapshot()
        window.set_product_catalogs(snapshot)
        workspace.set_selected_market(MARKET_B)
        workspace.dataset_scope.setCurrentIndex(
            workspace.dataset_scope.findData("all")
        )
        workspace.set_deletion_actions_enabled(True)
        actions = {
            "Recipes": (
                workspace.delete_recipe_button,
                workspace.delete_recipe_requested,
            ),
            "Recipe Collections": (
                workspace.delete_recipe_collection_button,
                workspace.delete_recipe_collection_requested,
            ),
            "Artifacts": (
                workspace.delete_artifact_button,
                workspace.delete_artifact_requested,
            ),
            "Artifact Collections": (
                workspace.delete_artifact_collection_button,
                workspace.delete_artifact_collection_requested,
            ),
        }
        expected_ids = {
            "Recipes": "data_manager.catalogs.action.delete_recipe",
            "Recipe Collections": "data_manager.catalogs.action.delete_recipe_collection",
            "Artifacts": "data_manager.catalogs.action.delete_artifact",
            "Artifact Collections": "data_manager.catalogs.action.delete_artifact_collection",
        }
        for family in CATALOG_FAMILIES:
            workspace.select_family(family)
            visible = {
                name: button.isVisibleTo(workspace)
                for name, (button, _signal) in actions.items()
            }
            assert visible == {
                name: name == family for name in actions
            }
            if family not in actions:
                continue
            button, signal = actions[family]
            assert button.objectName() == expected_ids[family]
            assert not button.isEnabled()
            selected = workspace._visible_values[-1]
            workspace.table.selectRow(len(workspace._visible_values) - 1)
            assert button.isEnabled()
            emitted: list[object] = []
            signal.connect(emitted.append)
            workspace._on_sort_column(0)
            assert workspace._selected_value() is selected
            button.click()
            assert emitted == [selected]
            workspace.set_deletion_actions_enabled(False)
            assert not button.isEnabled()
            workspace.set_deletion_actions_enabled(True)

        invalid_recipe = replace(
            snapshot.portable_recipes.recipes[0],
            valid=False,
            rejection_reason="invalid",
        )
        invalid_snapshot = replace(
            snapshot,
            portable_recipes=DataManagerPortableRecipeCatalog((invalid_recipe,)),
        )
        window.set_product_catalogs(invalid_snapshot)
        workspace.select_family("Recipes")
        workspace.table.selectRow(0)
        assert not workspace.delete_recipe_button.isEnabled()
    finally:
        window.close()


def test_derive_recipes_action_requires_one_valid_explicit_environment() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    emitted: list[object] = []
    try:
        workspace = window._catalog_workspace
        first = _environment("environment_b", "B Environment")
        second = _environment("environment_a", "A Environment")
        invalid = _environment("environment_invalid", "Invalid", valid=False)
        workspace.derive_recipes_requested.connect(emitted.append)
        window.set_product_catalogs(_environment_snapshot(first, second, invalid))
        workspace.select_family("Study Environments")

        button = workspace.derive_recipes_button
        assert button.objectName() == "data_manager.catalogs.action.derive_recipes"
        assert button.isVisibleTo(workspace)
        assert not button.isEnabled()
        assert window.selected_market_id() is None

        invalid_row = workspace._visible_values.index(invalid)
        workspace.table.selectRow(invalid_row)
        assert not button.isEnabled()

        selected_row = workspace._visible_values.index(first)
        workspace.table.selectRow(selected_row)
        assert button.isEnabled()
        assert window.selected_market_id() is None
        window.set_busy(True, "inspect")
        assert not button.isEnabled()
        window.set_busy(False)
        assert button.isEnabled()
        button.click()
        assert emitted == [first]

        _click_header(workspace, "Name")
        assert workspace._selected_value() is first
        assert button.isEnabled()
        button.click()
        assert emitted == [first, first]

        for family in CATALOG_FAMILIES:
            workspace.select_family(family)
            assert button.isVisibleTo(workspace) is (
                family == "Study Environments"
            )
        workspace.select_family("Artifacts")
        assert workspace.create_artifact_button.isVisibleTo(workspace)
        assert workspace.batch_constructs_button.isVisibleTo(workspace)
    finally:
        window.close()


def test_recipe_and_collection_catalogs_are_global_and_not_market_duplicated() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    snapshot = associated_product_snapshot()
    try:
        workspace = window._catalog_workspace
        window.set_product_catalogs(snapshot)
        workspace.set_selected_market(MARKET_A)
        combo = window.findChild(
            QComboBox, "data_manager.catalogs.combo.dataset_scope"
        )
        assert combo is workspace.dataset_scope
        assert combo.currentData() == "current"

        workspace.select_family("Recipes")
        assert workspace.scope_panel.isHidden()
        assert workspace.table.rowCount() == 2
        assert _column_values(workspace, "Recipe ID") == (
            "a" * 64,
            "b" * 64,
        )
        associated_row = _column_values(workspace, "Recipe ID").index("a" * 64)
        assert workspace.table.item(
            associated_row, _column(workspace, "Inputs")
        ).text() == "source=OHLCV.close"
        combo.setCurrentIndex(combo.findData("all"))
        assert workspace.table.rowCount() == 2
        workspace.set_selected_market(MARKET_B)
        assert workspace.table.rowCount() == 2
        workspace.set_selected_market(None)
        assert workspace.table.rowCount() == 2

        workspace.select_family("Recipe Collections")
        assert workspace.scope_panel.isHidden()
        assert workspace.table.rowCount() == 2
        workspace.set_selected_market(MARKET_B)
        assert workspace.table.rowCount() == 2
        workspace.set_selected_market(None)
        assert workspace.table.rowCount() == 2
        combo.setCurrentIndex(combo.findData("all"))
        assert workspace.table.rowCount() == 2
    finally:
        window.close()


def test_recipe_catalog_resolves_dependency_inputs_without_changing_row_identity() -> None:
    app = QApplication.instance() or QApplication([])
    del app

    def recipe(
        recipe_id: str,
        tool_key: str,
        parameters: dict[str, object],
        output_names: tuple[str, ...],
        input_bindings: tuple[str, ...],
    ) -> DataManagerPortableRecipeEntry:
        dependency_count = sum("=Recipe[" in item for item in input_bindings)
        return DataManagerPortableRecipeEntry(
            recipe_id,
            tool_key,
            "1.0",
            "construct" if dependency_count else "indicator",
            parameters,
            output_names,
            input_bindings,
            dependency_count,
            len(input_bindings) - dependency_count,
            (),
            (),
            (),
            0,
        )

    sma_id = "1" * 64
    ema_id = "2" * 64
    rsi_id = "3" * 64
    missing_id = "f" * 64
    recipes = (
        recipe(sma_id, "sma", {"period": 20}, ("sma",), ("source=OHLCV.close",)),
        recipe(ema_id, "ema", {"period": 30}, ("ema",), ("source=OHLCV.close",)),
        recipe(rsi_id, "rsi", {"period": 14}, ("rsi",), ("source=OHLCV.close",)),
        recipe(
            "4" * 64,
            "derivative",
            {"period": 1},
            ("derivative",),
            (f"source=Recipe[{sma_id}].sma",),
        ),
        recipe(
            "5" * 64,
            "derivative",
            {"period": 1},
            ("derivative",),
            (f"source=Recipe[{ema_id}].ema",),
        ),
        recipe(
            "6" * 64,
            "delta",
            {},
            ("delta",),
            (
                f"minuend=Recipe[{sma_id}].sma",
                f"subtrahend=Recipe[{ema_id}].ema",
            ),
        ),
        recipe(
            "7" * 64,
            "delta",
            {},
            ("delta",),
            (
                f"minuend=Recipe[{ema_id}].ema",
                f"subtrahend=Recipe[{sma_id}].sma",
            ),
        ),
        recipe(
            "8" * 64,
            "angle_momentum",
            {"period": 5},
            ("angle_momentum",),
            (f"source=Recipe[{rsi_id}].rsi",),
        ),
        recipe(
            "9" * 64,
            "angle_momentum",
            {"period": 5},
            ("angle_momentum",),
            (f"source=Recipe[{sma_id}].sma",),
        ),
        recipe(
            "a" * 64,
            "derivative",
            {"period": 1},
            ("derivative",),
            (f"source=Recipe[{missing_id}].value",),
        ),
    )
    snapshot = replace(
        empty_product_snapshot(),
        portable_recipes=DataManagerPortableRecipeCatalog(recipes),
    )
    window = DataManagerSuiteWindow()
    try:
        workspace = window._catalog_workspace
        window.set_product_catalogs(snapshot)
        workspace.select_family("Recipes")
        recipe_ids = _column_values(workspace, "Recipe ID")
        inputs = dict(
            zip(recipe_ids, _column_values(workspace, "Inputs"), strict=True)
        )

        assert len(recipe_ids) == len(recipes) == len(set(recipe_ids))
        assert inputs[sma_id] == "source=OHLCV.close"
        assert inputs["4" * 64] == "source=sma(period=20).sma"
        assert inputs["5" * 64] == "source=ema(period=30).ema"
        assert inputs["4" * 64] != inputs["5" * 64]
        assert inputs["6" * 64] == (
            "minuend=sma(period=20).sma, subtrahend=ema(period=30).ema"
        )
        assert inputs["7" * 64] == (
            "minuend=ema(period=30).ema, subtrahend=sma(period=20).sma"
        )
        assert inputs["6" * 64] != inputs["7" * 64]
        assert inputs["8" * 64] == "source=rsi(period=14).rsi"
        assert inputs["9" * 64] == "source=sma(period=20).sma"
        assert inputs["8" * 64] != inputs["9" * 64]
        assert inputs["a" * 64] == f"source=Recipe[{missing_id}].value"
        assert _COLUMNS["Recipes"] == (
            "Tool", "Inputs", "Parameters", "Outputs", "State", "Recipe ID",
        )
    finally:
        window.close()


def test_scoped_artifact_families_use_exact_market_and_scope_visibility() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        workspace = window._catalog_workspace
        window.set_product_catalogs(associated_product_snapshot())
        workspace.set_selected_market(MARKET_A)
        combo = workspace.dataset_scope
        for family in CATALOG_FAMILIES:
            workspace.select_family(family)
            assert workspace.scope_panel.isVisibleTo(workspace) is (
                family in {"Artifacts", "Artifact Collections"}
            )

        workspace.select_family("Artifacts")
        assert workspace.table.rowCount() == 0
        workspace.set_selected_market(MARKET_B)
        assert workspace.table.rowCount() == 1
        combo.setCurrentIndex(combo.findData("all"))
        assert workspace.table.rowCount() == 1

        workspace.select_family("Artifact Collections")
        assert workspace.table.rowCount() == 2
        combo.setCurrentIndex(combo.findData("current"))
        assert workspace.table.rowCount() == 1
        assert workspace.table.item(0, 2).text() == MARKET_B.symbol
    finally:
        window.close()


def test_product_catalog_column_schemas_are_exact_and_artifact_outputs_are_last() -> None:
    assert _COLUMNS["Recipes"] == (
        "Tool", "Inputs", "Parameters", "Outputs", "State", "Recipe ID",
    )
    assert _COLUMNS["Recipe Collections"] == (
        "Name", "Roots", "Members", "Dependency Edges", "Execution Stages",
        "Updated", "State", "Collection ID", "Current Revision ID",
    )
    assert _COLUMNS["Artifacts"] == (
        "Exchange", "Market Type", "Asset", "Timeframe", "Tool", "Kind",
        "Rows", "First TS", "Last TS", "Created", "State", "Currentness",
        "Previous Artifact ID", "Outputs",
    )
    assert "Logical ID" not in _COLUMNS["Artifacts"]
    assert "Current Artifact ID" not in _COLUMNS["Artifacts"]
    assert _COLUMNS["Artifacts"][-1] == "Outputs"
    assert _COLUMNS["Artifact Collections"][-2:] == (
        "Collection ID", "Revision ID"
    )
    for family in ("Artifacts", "Artifact Collections"):
        columns = _COLUMNS[family]
        assert columns[:4] == ("Exchange", "Market Type", "Asset", "Timeframe")
        assert "Market" not in columns
        assert "Coverage" not in columns
        assert "Currentness" in columns
        assert "Origin Markets" not in columns


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        ("CURRENT", "CURRENT"),
        ("APPEND_AVAILABLE", "UPDATE AVAILABLE"),
        ("HISTORICAL_SOURCE_CHANGED", "UPDATE AVAILABLE"),
        ("BLOCKED_BY_DEPENDENCY", "BLOCKED"),
        ("INVALID", "INVALID"),
        (None, "VERIFYING"),
    ),
)
def test_artifact_currentness_uses_reconciliation_projection(
    status: str | None,
    expected: str,
) -> None:
    window = DataManagerSuiteWindow()
    try:
        snapshot = associated_product_snapshot()
        row = snapshot.latest_reconciliation.artifacts[0]
        reconciliation = replace(
            snapshot.latest_reconciliation,
            artifacts=(
                ()
                if status is None
                else (replace(row, status=status, reasons=("artifact reason",)),)
            ),
        )
        window.set_product_catalogs(
            replace(snapshot, latest_reconciliation=reconciliation)
        )
        workspace = window._catalog_workspace
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifacts")

        assert _column_values(workspace, "State") == ("valid",)
        assert _column_values(workspace, "Currentness") == (expected,)
        workspace.table.selectRow(0)
        inspector = {
            workspace.inspector.item(index, 0).text(): workspace.inspector.item(
                index, 1
            ).text()
            for index in range(workspace.inspector.rowCount())
        }
        if status is not None:
            assert inspector["currentness.status"] == status
            assert "artifact reason" in inspector["currentness.reasons"]
    finally:
        window.close()


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        ("CURRENT", "CURRENT"),
        ("MEMBERS_REQUIRE_UPDATE", "UPDATE AVAILABLE"),
        ("PARTIALLY_ALIGNED", "UPDATE AVAILABLE"),
        ("BLOCKED_BY_DEPENDENCY", "BLOCKED"),
        ("SOURCE_INVALID", "INVALID"),
        (None, "VERIFYING"),
    ),
)
def test_artifact_collection_currentness_uses_reconciliation_projection(
    status: str | None,
    expected: str,
) -> None:
    window = DataManagerSuiteWindow()
    try:
        snapshot = associated_product_snapshot()
        row = snapshot.latest_reconciliation.collections[0]
        reconciliation = replace(
            snapshot.latest_reconciliation,
            collections=(
                ()
                if status is None
                else (replace(row, status=status, reasons=("collection reason",)),)
            ),
        )
        window.set_product_catalogs(
            replace(snapshot, latest_reconciliation=reconciliation)
        )
        workspace = window._catalog_workspace
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifact Collections")

        assert _column_values(workspace, "State") == ("valid",)
        assert _column_values(workspace, "Currentness") == (expected,)
        workspace.table.selectRow(0)
        inspector = {
            workspace.inspector.item(index, 0).text(): workspace.inspector.item(
                index, 1
            ).text()
            for index in range(workspace.inspector.rowCount())
        }
        if status is not None:
            assert inspector["currentness.status"] == status
            assert "collection reason" in inspector["currentness.reasons"]
    finally:
        window.close()


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        ("CURRENT", "CURRENT"),
        ("UPDATE_AVAILABLE", "UPDATE AVAILABLE"),
        ("REBUILD_REQUIRED", "UPDATE AVAILABLE"),
        ("WAITING_FOR_ARTIFACT_UPDATE", "BLOCKED"),
        ("SOURCE_INVALID", "INVALID"),
        (None, "VERIFYING"),
    ),
)
def test_database_currentness_uses_reconciliation_projection(
    status: str | None,
    expected: str,
) -> None:
    window = DataManagerSuiteWindow()
    try:
        snapshot = associated_product_snapshot()
        currentness = (
            None
            if status is None
            else DataManagerDatabaseCurrentness(
                "db_" + "1" * 32,
                "3" * 64,
                MARKET_B,
                status,
                TIMESTAMP_MS,
                TIMESTAMP_MS,
                TIMESTAMP_MS,
                0,
                True,
                ("database reason",),
            )
        )
        reconciliation = replace(
            snapshot.latest_reconciliation,
            databases=() if currentness is None else (currentness,),
        )
        window.set_product_catalogs(
            replace(
                snapshot,
                databases=(_database_entry(currentness),),
                latest_reconciliation=reconciliation,
            )
        )
        workspace = window._catalog_workspace
        workspace.select_family("Databases")

        assert _column_values(workspace, "State") == ("valid",)
        assert _column_values(workspace, "Currentness") == (expected,)
        workspace.table.selectRow(0)
        inspector = {
            workspace.inspector.item(index, 0).text(): workspace.inspector.item(
                index, 1
            ).text()
            for index in range(workspace.inspector.rowCount())
        }
        if status is not None:
            assert inspector["currentness.status"] == status
            assert "database reason" in inspector["currentness.reasons"]
    finally:
        window.close()


def test_catalog_created_updated_and_coverage_timestamps_use_display_time() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    expected = "2026-08-09 19:42:17 CEST (+02:00)"
    try:
        workspace = window._catalog_workspace
        window.set_product_catalogs(associated_product_snapshot())
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifacts")
        headings = {
            workspace.table.horizontalHeaderItem(column).text(): column
            for column in range(workspace.table.columnCount())
        }
        for label in ("First TS", "Last TS", "Created"):
            assert workspace.table.item(0, headings[label]).text() == expected
        workspace.table.selectRow(0)
        inspector = {
            workspace.inspector.item(row, 0).text(): workspace.inspector.item(
                row, 1
            ).text()
            for row in range(workspace.inspector.rowCount())
        }
        assert inspector["currentness.status"] == "CURRENT"
        assert inspector["currentness.artifact_through_ms"] == expected
        assert inspector["logical_artifact_id"] == "c" * 64
        assert inspector["artifact_id"] == "d" * 64

        workspace.select_family("Recipe Collections")
        headings = {
            workspace.table.horizontalHeaderItem(column).text(): column
            for column in range(workspace.table.columnCount())
        }
        assert workspace.table.item(0, headings["Updated"]).text() == expected
    finally:
        window.close()


def test_catalog_header_typed_sorting_and_per_family_state() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        workspace = window._catalog_workspace
        workspace.set_snapshot(sortable_artifact_snapshot())
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifacts")
        header = workspace.table.horizontalHeader()

        assert header.sectionsClickable()
        assert not header.isSortIndicatorShown()
        assert _column_values(workspace, "Rows") == ("2", "100", "10")

        _click_header(workspace, "Tool")
        assert _column_values(workspace, "Tool") == ("ema", "rsi", "sma")
        assert header.sortIndicatorSection() == _column(workspace, "Tool")
        assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        _click_header(workspace, "Tool")
        assert _column_values(workspace, "Tool") == ("sma", "rsi", "ema")
        assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

        _click_header(workspace, "Rows")
        assert _column_values(workspace, "Rows") == ("2", "10", "100")
        _click_header(workspace, "First TS")
        assert _column_values(workspace, "First TS") == (
            "1970-01-01 01:00:00 CET (+01:00)",
            "1970-01-01 02:00:00 CET (+01:00)",
            "1970-01-01 03:00:00 CET (+01:00)",
        )
        _click_header(workspace, "First TS")
        assert _column_values(workspace, "First TS") == (
            "1970-01-01 03:00:00 CET (+01:00)",
            "1970-01-01 02:00:00 CET (+01:00)",
            "1970-01-01 01:00:00 CET (+01:00)",
        )

        workspace.set_snapshot(associated_product_snapshot())
        workspace.select_family("Recipes")
        assert not header.isSortIndicatorShown()
        associated_row = _column_values(workspace, "Recipe ID").index("a" * 64)
        workspace.table.selectRow(associated_row)
        _click_header(workspace, "Tool")
        assert _column_values(workspace, "Tool") == ("rsi", "sma")
        assert workspace._selected_value().recipe_id == "a" * 64
        assert header.sortIndicatorSection() == _column(workspace, "Tool")

        workspace.select_family("Recipe Collections")
        _click_header(workspace, "Roots")
        assert _column_values(workspace, "Roots") == ("1", "2")
        workspace.select_family("Artifacts")
        assert header.isSortIndicatorShown()
        assert header.sortIndicatorSection() == _column(workspace, "First TS")
        assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

        assert not workspace.inspector.isSortingEnabled()
        assert not workspace.inspector.horizontalHeader().isSortIndicatorShown()
        assert not workspace.history.isSortingEnabled()
        assert not workspace.history.horizontalHeader().isSortIndicatorShown()
    finally:
        window.close()


def test_catalog_sort_preserves_artifact_selection_inspector_scope_and_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    selected: list[object] = []
    try:
        workspace = window._catalog_workspace
        snapshot = sortable_artifact_snapshot()
        workspace.row_selected.connect(
            lambda _family, value: selected.append(value)
        )
        workspace.set_snapshot(snapshot)
        workspace.set_selected_market(MARKET_B)
        workspace.select_family("Artifacts")
        workspace.table.selectRow(2)
        selected_artifact = workspace._visible_values[2]
        assert selected_artifact.logical_artifact_id == "c" * 64

        _click_header(workspace, "Rows")
        assert workspace._selected_value() is selected_artifact
        assert selected[-1] is selected_artifact
        inspection = {
            workspace.inspector.item(row, 0).text(): workspace.inspector.item(
                row, 1
            ).text()
            for row in range(workspace.inspector.rowCount())
        }
        assert inspection["logical_artifact_id"] == "c" * 64

        workspace.dataset_scope.setCurrentIndex(
            workspace.dataset_scope.findData("all")
        )
        assert _column_values(workspace, "Rows") == ("2", "10", "100")
        assert workspace._selected_value().logical_artifact_id == "c" * 64

        refreshed = replace(
            snapshot,
            managed_artifacts=DataManagerManagedArtifactCatalog(
                tuple(reversed(snapshot.managed_artifacts.artifacts))
            ),
        )
        workspace.set_snapshot(refreshed)
        assert _column_values(workspace, "Rows") == ("2", "10", "100")
        assert workspace._selected_value().logical_artifact_id == "c" * 64
    finally:
        window.close()


def test_collection_inspection_action_is_contextual_exact_and_busy_fenced() -> None:
    window = DataManagerSuiteWindow()
    snapshot = associated_product_snapshot()
    recipe_emitted: list[object] = []
    artifact_emitted: list[object] = []
    try:
        workspace = window._catalog_workspace
        workspace.inspect_recipe_collection_requested.connect(
            recipe_emitted.append
        )
        workspace.inspect_artifact_collection_requested.connect(
            artifact_emitted.append
        )
        window.set_product_catalogs(snapshot)
        button = workspace.inspect_collection_button
        assert button.objectName() == (
            "data_manager.catalogs.action.inspect_collection"
        )

        for family in CATALOG_FAMILIES:
            workspace.select_family(family)
            assert button.isVisibleTo(workspace) is (
                family in {"Recipe Collections", "Artifact Collections"}
            )

        workspace.select_family("Recipe Collections")
        assert not button.isEnabled()
        recipe = workspace._visible_values[0]
        workspace.table.selectRow(0)
        assert button.isEnabled()
        button.click()
        assert recipe_emitted == [recipe]
        assert artifact_emitted == []

        workspace.set_collection_actions_enabled(False)
        assert not button.isEnabled()
        workspace.set_collection_actions_enabled(True)
        assert button.isEnabled()

        workspace.dataset_scope.setCurrentIndex(
            workspace.dataset_scope.findData("all")
        )
        workspace.select_family("Artifact Collections")
        artifact = workspace._visible_values[0]
        workspace.table.selectRow(0)
        assert button.isEnabled()
        button.click()
        assert artifact_emitted == [artifact]

        invalid = _artifact_collection(
            MARKET_A,
            collection_id="artifact_collection_invalid",
            revision_id="3" * 64,
            name="Invalid",
        )
        object.__setattr__(invalid, "validation_state", "invalid")
        window.set_product_catalogs(
            replace(snapshot, artifact_collections=(invalid,))
        )
        workspace.select_family("Artifact Collections")
        workspace.table.selectRow(0)
        assert not button.isEnabled()
    finally:
        window.close()
