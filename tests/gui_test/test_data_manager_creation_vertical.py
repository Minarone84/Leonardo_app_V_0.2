from __future__ import annotations

import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.gui.composition import GuiCompositionRoot
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset

MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter, timeout=10.0):
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def test_real_catalog_database_creation_survives_restart(tmp_path):
    app_qt = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    saved = None
    for restarting in (False, True):
        app = LeonardoApp(config)
        app.startup()
        app.start_core_runtime()
        composition = GuiCompositionRoot(app.context)
        main = composition.create_main_window()
        try:
            main.action_for_id("main_window.open_data_manager_suite").trigger()
            QCoreApplication.processEvents()
            window = composition.data_manager_suite_window
            presenter = composition.data_manager_suite_presenter
            assert window is not None and presenter is not None
            _settle(presenter)
            assert window.select_market(MARKET)
            _settle(presenter)
            assert tuple(window._workspace_tabs.tabText(i) for i in range(
                window._workspace_tabs.count())) == ("Catalogs", "Update & Reconcile")
            catalog = window._catalog_workspace
            if not restarting:
                catalog.select_family("Database Seeds")
                catalog.create_database_seed_button.click()
                seed_dialog = window.database_seed_dialog()
                seed_dialog.name_edit.setText("Persistent Seed")
                seed_dialog.preview_button.click()
                _settle(presenter)
                assert seed_dialog.reviewed_plan is not None
                seed_dialog.create_button.click()
                _settle(presenter)
                catalog.select_family("Database Seeds")
                catalog.table.selectRow(0)
                _settle(presenter)
                seed = window.product_catalogs().database_seeds[0]
                catalog.create_seed_only_database_button.click()
                dialog = window.database_creation_dialog()
                assert dialog is not None and dialog.selected_seed() == seed
                dialog.name_edit.setText("Persistent Database")
                dialog.preview_button.click()
                _settle(presenter)
                assert dialog.reviewed_plan is not None
                dialog.create_button.click()
                _settle(presenter)
                products = window.product_catalogs()
                assert len(products.databases) == 1
                manifest = products.databases[0].current_manifest
                assert manifest.members == manifest.collection_sources == ()
                saved = (seed, manifest)
            else:
                seed, manifest = saved
                assert app.data_manager_domain.load_database_seed(seed.seed_id) == seed
                assert app.data_manager_domain.load_database_revision(
                    manifest.database_id, manifest.revision_id).manifest == manifest
                catalog.select_family("Databases")
                assert catalog.table.rowCount() == 1
                catalog.table.selectRow(0)
                _settle(presenter)
                assert catalog.history.rowCount() == 1
                catalog.history.selectRow(0)
                _settle(presenter)
                fields = {catalog.inspector.item(i, 0).text():
                          catalog.inspector.item(i, 1).text()
                          for i in range(catalog.inspector.rowCount())}
                assert fields["database_id"] == manifest.database_id
        finally:
            main.close()
            QCoreApplication.processEvents()
            app.shutdown()
