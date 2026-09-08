from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.data_manager import DatabaseRevisionManifestV2
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter: DataManagerSuitePresenter, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def _select_first(window: DataManagerSuiteWindow, family: str) -> None:
    catalog = window._catalog_workspace
    catalog.select_family(family)
    assert catalog.table.rowCount() > 0
    catalog.table.selectRow(0)
    QCoreApplication.processEvents()


def _table_text(table) -> tuple[str, ...]:
    return tuple(
        table.item(row, column).text()
        for row in range(table.rowCount())
        for column in range(table.columnCount())
        if table.item(row, column) is not None
    )


def test_contextual_seed_only_database_vertical_and_window_lifecycle(
    tmp_path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    tracked: list[tuple[object, ...]] = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *values: tracked.append(values)
    )
    presenter = DataManagerSuitePresenter(window, app.data_manager_service)
    refreshes: list[str] = []
    original_refresh = presenter._after_write_refresh

    def counted_refresh() -> None:
        refreshes.append("refresh")
        original_refresh()

    presenter._after_write_refresh = counted_refresh
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        assert window.select_market(MARKET)
        _settle(presenter)

        catalog = window._catalog_workspace
        catalog.select_family("Database Seeds")
        assert catalog.create_database_seed_button.isEnabled()
        catalog.create_database_seed_button.click()
        seed_dialog = window.database_seed_dialog()
        assert seed_dialog is not None
        catalog.create_database_seed_button.click()
        assert window.database_seed_dialog() is seed_dialog
        assert sum(item[0] is seed_dialog for item in tracked) == 1

        seed_dialog.name_edit.setText("Vertical Seed")
        seed_dialog.preview_button.click()
        _settle(presenter)
        assert seed_dialog.reviewed_plan is not None
        seed_dialog.create_button.click()
        _settle(presenter)
        assert refreshes == ["refresh"]
        assert len(window.product_catalogs().database_seeds) == 1
        assert seed_dialog.reviewed_plan is None
        assert "created:" in seed_dialog.result_label.text()
        seed_lines = window._operation_surface.notes_text().splitlines()
        assert sum("execute_database_seed_creation" in line for line in seed_lines) == 1

        _select_first(window, "Database Seeds")
        _settle(presenter)
        seed = window.product_catalogs().database_seeds[0]
        assert seed.seed_id in _table_text(catalog.inspector)
        assert catalog.create_seed_only_database_button.isEnabled()
        catalog.create_seed_only_database_button.click()
        database_dialog = window.database_creation_dialog()
        assert database_dialog is not None
        assert database_dialog.selected_seed() is not None
        database_dialog.name_edit.setText("Vertical Database")
        database_dialog.preview_button.click()
        _settle(presenter)
        assert database_dialog.reviewed_plan is not None
        database_dialog.create_button.click()
        _settle(presenter)
        assert refreshes == ["refresh", "refresh"]
        products = window.product_catalogs()
        assert products is not None and len(products.databases) == 1
        manifest = products.databases[0].current_manifest
        assert isinstance(manifest, DatabaseRevisionManifestV2)
        assert manifest.members == manifest.collection_sources == ()
        assert products.databases[0].revision_count == 1
        database_lines = window._operation_surface.notes_text().splitlines()
        assert sum(
            "execute_seed_only_database_creation" in line
            for line in database_lines
        ) == 1

        _select_first(window, "Databases")
        _settle(presenter)
        assert manifest.database_id in _table_text(catalog.table)
        assert manifest.database_id in _table_text(catalog.inspector)
        assert manifest.revision_id in _table_text(catalog.inspector)
        assert window._catalog_workspace.history.rowCount() == 1
        assert catalog.history.item(0, 2).text() == manifest.revision_id

        database_dialog.close()
        QCoreApplication.processEvents()
        assert window.database_creation_dialog() is None
        catalog.select_family("Database Seeds")
        _select_first(window, "Database Seeds")
        catalog.create_seed_only_database_button.click()
        assert window.database_creation_dialog() is not None
        assert sum(
            item[1] == "data_manager.database_creation.window" for item in tracked
        ) == 2

        seed_dialog.close()
        QCoreApplication.processEvents()
        assert window.database_seed_dialog() is None
        catalog.create_database_seed_button.click()
        late_dialog = window.database_seed_dialog()
        assert late_dialog is not None
        late_dialog.name_edit.setText("Late Preview")
        late_dialog.preview_button.click()
        _settle(presenter)
        assert late_dialog.reviewed_plan is not None
        seed_ids_before = tuple(
            item.seed_id for item in app.data_manager_domain.list_database_seeds()
        )
        database_history_before = tuple(
            app.data_manager_domain.list_database_revisions(database_id)
            for database_id in app.data_manager_domain.list_database_ids()
        )
        _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=72)
        late_dialog.create_button.click()
        late_dialog.close()
        _settle(presenter)
        assert window.database_seed_dialog() is None
        assert tuple(
            item.seed_id for item in app.data_manager_domain.list_database_seeds()
        ) == seed_ids_before
        assert tuple(
            app.data_manager_domain.list_database_revisions(database_id)
            for database_id in app.data_manager_domain.list_database_ids()
        ) == database_history_before
    finally:
        window.close()
        QCoreApplication.processEvents()
        assert window.database_seed_dialog() is None
        assert window.database_creation_dialog() is None
        app.shutdown()
        del qapp
