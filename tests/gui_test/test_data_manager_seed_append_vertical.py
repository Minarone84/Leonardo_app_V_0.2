from __future__ import annotations

from dataclasses import replace
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.data_manager_test.test_update_workflow import MARKET, _append
from tests.data_manager_test.test_nan_snapshot_updates import _tree
from tests.data_manager_test.test_seed_append_workflow import _seed_tree
from tests.gui_test.test_data_manager_seed_database_vertical import _settle, _select_first, _table_text


def _settle_all(presenter):
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if presenter.active_task_id is None and presenter._background_refresh_task_id is None:
            QCoreApplication.processEvents()
            return
        time.sleep(0.005)
    assert presenter.active_task_id is None and presenter._background_refresh_task_id is None


@pytest.mark.parametrize("answer", ("yes", "no", "stale", "generation"))
def test_real_selected_seed_append_vertical(tmp_path, monkeypatch, answer):
    qapp = QApplication.instance() or QApplication([])
    historical = tmp_path / "historical_data"
    _append(historical, rows=96)
    app = LeonardoApp(replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False)))
    app.startup()
    app.start_core_runtime()
    window = DataManagerSuiteWindow(floating_window_tracker=lambda *_: None)
    presenter = DataManagerSuitePresenter(window, app.data_manager_service)
    domain = app.data_manager_domain
    seed = domain.create_database_seed(MARKET, "Vertical append")
    database = domain.execute_seed_only_database_creation(domain.plan_seed_only_database_creation(seed.seed_id, "Frozen Database"))
    before = _seed_tree(domain)
    databases = _tree(domain.creation_store.root_dir / "databases")
    _append(historical, rows=104)
    confirmations = []
    statuses = []
    original_status = window.set_status
    def record_status(message):
        statuses.append(message)
        original_status(message)
    window.set_status = record_status
    def question(parent, title, text, buttons, default):
        assert parent is window and title == "Append Database Seed"
        assert default == QMessageBox.StandardButton.No
        assert buttons == QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        for token in (seed.display_name, seed.seed_id, "Previous rows: 96", "Added rows: 8", "Resulting rows: 104", "Existing rows and existing Databases remain unchanged."):
            assert token in text
        assert _seed_tree(domain) == before  # Preview and confirmation did not publish.
        confirmations.append(text)
        if answer == "stale": _append(historical, rows=105)
        if answer == "generation": presenter._catalog_generation += 1
        return QMessageBox.StandardButton.No if answer == "no" else QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    try:
        window.show()
        presenter.refresh()
        _settle_all(presenter)
        catalog = window._catalog_workspace
        catalog.dataset_scope.setCurrentIndex(catalog.dataset_scope.findData("all"))
        _select_first(window, "Database Seeds")
        _settle(presenter)
        button = catalog.append_database_seed_button
        assert button.objectName() == "data_manager.catalogs.action.append_database_seed"
        assert button.property("action_id") == "data_manager.catalogs.action.append_database_seed"
        assert window._selected_market is None  # The Seed owns its market.
        assert button.isEnabled() and button.isVisible()
        assert all("Range" not in catalog.table.horizontalHeaderItem(i).text() for i in range(catalog.table.columnCount()))
        catalog.table.clearSelection()
        QCoreApplication.processEvents()
        assert not button.isEnabled()
        catalog.table.selectRow(0)
        _settle(presenter)
        window.set_busy(True)
        assert not button.isEnabled()
        window.set_busy(False)
        window.enter_dataset_evidence_changed_state(MARKET, "Test context suspended")
        assert not button.isEnabled()
        window.clear_dataset_evidence_changed_state()
        assert button.isEnabled()
        source = _tree(historical)
        button.click()
        _settle_all(presenter)
        assert len(confirmations) == 1
        if answer == "yes":
            assert domain.load_database_seed(seed.seed_id).row_count == 104
            assert window.product_catalogs().database_seeds[0].row_count == 104
            assert "Database Seed append completed" in statuses
            _select_first(window, "Database Seeds")
            _settle(presenter)
            assert "104" in _table_text(catalog.table)
            unchanged = _seed_tree(domain)
            button.click()
            _settle_all(presenter)
            assert "Database Seed is already current" in statuses
            assert len(confirmations) == 1 and _seed_tree(domain) == unchanged
        else:
            assert _seed_tree(domain) == before
            if answer == "no": assert "Database Seed append cancelled" in statuses
            if answer == "stale": assert "stale" in window._operation_surface.notes_text().lower()
        assert _tree(domain.creation_store.root_dir / "databases") == databases
        assert domain.load_database_revision(database.database_id).manifest == database
        if answer != "stale": assert _tree(historical) == source
        catalog.select_family("Databases")
        assert not button.isVisible()
    finally:
        window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp
