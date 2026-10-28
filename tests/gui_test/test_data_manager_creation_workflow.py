from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from leonardo.data_manager import DataManagerCatalogSnapshot
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot
from tests.gui_test.test_data_manager_database_dialogs import _dataset, _seed


def test_catalog_creation_routes_replace_permanent_workspace() -> None:
    app = QApplication.instance() or QApplication([])
    window = DataManagerSuiteWindow()
    try:
        assert tuple(window._workspace_tabs.tabText(i) for i in range(
            window._workspace_tabs.count())) == ("Catalogs", "Update & Reconcile")
        assert window._creation_workspace is None
        seed = _seed()
        snapshot = replace(empty_product_snapshot(), database_seeds=(seed,))
        window.set_product_catalogs(snapshot)
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(),)))
        assert window.select_market(seed.market_id, emit_selection=False)
        catalog = window._catalog_workspace
        catalog.select_family("Database Seeds")
        catalog.table.selectRow(0)
        observed = []
        window.create_seed_only_database_requested.connect(observed.append)
        assert catalog.create_database_seed_button.isEnabled()
        assert catalog.create_seed_only_database_button.isEnabled()
        catalog.create_seed_only_database_button.click()
        assert observed == [seed]
        window.set_busy(True, "create_database")
        assert not catalog.create_database_seed_button.isEnabled()
        assert not catalog.create_seed_only_database_button.isEnabled()
        window.set_busy(False)
        assert catalog.create_seed_only_database_button.isEnabled()
    finally:
        window.close()


def test_contextual_creation_dialog_emits_reviewed_intent() -> None:
    app = QApplication.instance() or QApplication([])
    window = DataManagerSuiteWindow()
    seed = _seed()
    snapshot = replace(empty_product_snapshot(), database_seeds=(seed,))
    previews = []
    window.seed_only_database_preview_requested.connect(previews.append)
    try:
        window.show_database_creation_dialog(snapshot, selected_seed=seed)
        dialog = window.database_creation_dialog()
        assert dialog.selected_seed() == seed
        assert not dialog.create_button.isEnabled()
        dialog.name_edit.setText("Context Database")
        dialog.preview_button.click()
        assert len(previews) == 1
        assert previews[0]["seed_id"] == seed.seed_id
        assert previews[0]["display_name"] == "Context Database"
        assert window.database_creation_dialog() is dialog
    finally:
        window.close()
