from __future__ import annotations

import os
import time
from dataclasses import replace
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QCheckBox
from shiboken6 import isValid

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_seed_only_database_application import (
    _completed,
    _create_seed_only_database,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter: DataManagerSuitePresenter, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def _select_database(window: DataManagerSuiteWindow) -> None:
    catalog = window._catalog_workspace
    catalog.select_family("Databases")
    assert catalog.table.rowCount() == 1
    catalog.table.selectRow(0)
    QCoreApplication.processEvents()


def _first_check(dialog) -> QCheckBox:
    checkbox = dialog.source_table.cellWidget(0, 0)
    assert isinstance(checkbox, QCheckBox)
    return checkbox


def test_database_content_presenter_vertical_refresh_history_and_lifecycle(
    tmp_path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    _seed, database = _create_seed_only_database(application, "Vertical Content")
    sma = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("sma", {"period": 3}),
    )
    ema = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("ema", {"period": 4}),
    )
    collection = app.data_manager_domain.create_artifact_collection(
        ema, "Collection Content"
    )
    tracked: list[tuple[object, ...]] = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *values: tracked.append(values)
    )
    presenter = DataManagerSuitePresenter(window, application)
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
        _select_database(window)
        _settle(presenter)
        catalog = window._catalog_workspace
        assert catalog.add_database_artifacts_button.isEnabled()
        catalog.add_database_artifacts_button.click()
        dialog = window.database_content_dialog()
        assert dialog is not None and dialog.mode == "artifacts"
        catalog.add_database_artifacts_button.click()
        assert window.database_content_dialog() is dialog
        assert sum(item[0] is dialog for item in tracked) == 1

        root = sma.root_logical_artifact_ids[0]
        row = next(
            index for index, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == root
        )
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan is not None
        dialog.add_button.click()
        _settle(presenter)
        assert refreshes == ["refresh"]
        assert "execute_database_content_addition" in window._operation_surface.notes_text()

        _select_database(window)
        current = window.product_catalogs().databases[0].current_manifest
        assert current is not None and current.revision_id != database.revision_id
        assert catalog.history.rowCount() == 2
        inspector_text = " ".join(
            catalog.inspector.item(row, column).text()
            for row in range(catalog.inspector.rowCount())
            for column in range(catalog.inspector.columnCount())
            if catalog.inspector.item(row, column) is not None
        )
        assert current.revision_id in inspector_text

        catalog.add_database_collection_button.click()
        assert window.database_content_dialog() is dialog
        assert dialog.mode == "collection"
        collection_row = next(
            index for index, value in enumerate(dialog._source_values)
            if value.collection_id == collection.collection_id
        )
        collection_check = dialog.source_table.cellWidget(collection_row, 0)
        assert isinstance(collection_check, QCheckBox)
        collection_check.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan.source_collection.revision_id == collection.revision_id
        dialog.add_button.click()
        _settle(presenter)
        assert refreshes == ["refresh", "refresh"]
        latest = window.product_catalogs().databases[0].current_manifest
        assert latest is not None
        assert latest.collection_sources[-1].revision_id == collection.revision_id
        assert catalog.history.rowCount() == 3

        dialog.close()
        QCoreApplication.processEvents()
        assert window.database_content_dialog() is None
    finally:
        window.close()
        QCoreApplication.processEvents()
        assert window.database_content_dialog() is None
        app.shutdown()
        del qapp


def test_database_content_review_is_invalidated_by_authoritative_head_change(
    tmp_path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    _seed, database = _create_seed_only_database(application, "Context Change")
    sma = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("sma", {"period": 3}),
    )
    ema = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("ema", {"period": 4}),
    )
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.add_database_artifacts_button.click()
        dialog = window.database_content_dialog()
        assert dialog is not None
        root = sma.root_logical_artifact_ids[0]
        row = next(
            index
            for index, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == root
        )
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan is not None
        assert dialog.add_button.isEnabled()

        competing = app.data_manager_domain.plan_database_artifact_addition(
            database.database_id, ema.root_logical_artifact_ids
        )
        published = app.data_manager_domain.execute_database_content_addition(
            competing
        )
        assert published is not None
        app.data_manager_domain.reconcile_update_status(force=True)
        snapshot = app.data_manager_domain.scan_product_catalogs()
        refreshed_database = next(
            item
            for item in snapshot.databases
            if item.definition.database_id == database.database_id
        )
        dialog.set_context(refreshed_database, snapshot, mode=dialog.mode)

        assert window.database_content_dialog() is dialog
        assert dialog.reviewed_plan is None
        assert not dialog.add_button.isEnabled()
    finally:
        window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp


def test_late_preview_result_does_not_reopen_closed_content_dialog(
    tmp_path,
    monkeypatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    _seed, _database = _create_seed_only_database(application, "Late Preview")
    result = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("sma", {"period": 3}),
    )
    entered = Event()
    release = Event()
    original_plan = app.data_manager_domain.plan_database_artifact_addition

    def delayed_plan(*args, **kwargs):
        entered.set()
        assert release.wait(10.0)
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(
        app.data_manager_domain,
        "plan_database_artifact_addition",
        delayed_plan,
    )
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.add_database_artifacts_button.click()
        dialog = window.database_content_dialog()
        assert dialog is not None
        root = result.root_logical_artifact_ids[0]
        row = next(
            index
            for index, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == root
        )
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        assert entered.wait(10.0)
        dialog.close()
        QCoreApplication.processEvents()
        assert window.database_content_dialog() is None

        release.set()
        _settle(presenter)
        assert window.database_content_dialog() is None
        assert not dialog.isVisible()
    finally:
        release.set()
        window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp


def test_suite_close_releases_content_dialog_and_rejects_late_preview(
    tmp_path,
    monkeypatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    _seed, _database = _create_seed_only_database(application, "Suite Close")
    result = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("sma", {"period": 3}),
    )
    entered = Event()
    release = Event()
    original_plan = app.data_manager_domain.plan_database_artifact_addition

    def delayed_plan(*args, **kwargs):
        entered.set()
        assert release.wait(10.0)
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(
        app.data_manager_domain,
        "plan_database_artifact_addition",
        delayed_plan,
    )
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.add_database_artifacts_button.click()
        dialog = window.database_content_dialog()
        assert dialog is not None
        root = result.root_logical_artifact_ids[0]
        row = next(
            index
            for index, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == root
        )
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        assert entered.wait(10.0)

        window.close()
        QCoreApplication.processEvents()
        assert presenter.is_disposed
        assert not isValid(dialog)
        release.set()
        deadline = time.monotonic() + 10.0
        while app.task_manager.active_tasks() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        QCoreApplication.processEvents()
        assert not app.task_manager.active_tasks()
        assert not isValid(window)
    finally:
        release.set()
        if isValid(window):
            window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp
