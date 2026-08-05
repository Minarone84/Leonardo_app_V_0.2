from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QTabWidget

from leonardo.data_manager import (
    DataManagerCatalogSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerPortableRecipeCatalog,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionCatalog,
    DataManagerReconciliationSnapshot,
    DataManagerStudyEnvironmentCatalog,
)
from leonardo.gui.data_manager.catalogs import CATALOG_FAMILIES
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


EXPECTED_FAMILIES = (
    "Study Environments",
    "Portable Recipes",
    "Recipe Collections",
    "Managed Artifacts",
    "Artifact Collections",
    "Database Seeds",
    "Databases",
)


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


def test_catalog_workspace_exposes_seven_non_dataset_families() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        assert CATALOG_FAMILIES == EXPECTED_FAMILIES
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
