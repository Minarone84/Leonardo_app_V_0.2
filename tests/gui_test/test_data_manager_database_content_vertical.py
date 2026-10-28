from __future__ import annotations

import os
import time
from dataclasses import replace
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox
from shiboken6 import isValid

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_seed_only_database_application import (
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
    catalog.dataset_scope.setCurrentIndex(catalog.dataset_scope.findData("all"))
    catalog.select_family("Databases")
    assert catalog.table.rowCount() == 1
    catalog.table.selectRow(0)
    QCoreApplication.processEvents()


def _artifact_row(dialog, logical_artifact_id: str) -> int:
    return next(
        index
        for index, value in enumerate(dialog._source_values)
        if value.logical_artifact_id == logical_artifact_id
    )


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
        _leaf("sma", {"period": 1}),
    )
    ema = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("ema", {"period": 1}),
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
        assert catalog.edit_database_artifacts_button.isEnabled()
        catalog.edit_database_artifacts_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None and dialog.mode == "artifacts"
        assert dialog.baseline_plan is not None

        catalog.edit_database_artifacts_button.click()
        _settle(presenter)
        assert window.database_content_dialog() is dialog
        assert sum(item[0] is dialog for item in tracked) == 1

        root = sma.root_logical_artifact_ids[0]
        row = _artifact_row(dialog, root)
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan is not None
        dialog.apply_button.click()
        _settle(presenter)
        assert refreshes == ["refresh"]
        assert window.database_content_dialog() is None
        assert "execute_database_content_edit" in window._operation_surface.notes_text()

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

        catalog.edit_database_collections_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None and dialog.mode == "collections"
        collection_row = next(
            index
            for index, value in enumerate(dialog._source_values)
            if value.collection_id == collection.collection_id
            and value.revision_id == collection.revision_id
        )
        collection_check = dialog.source_table.cellWidget(collection_row, 0)
        assert isinstance(collection_check, QCheckBox)
        collection_check.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan.collection_additions[0].revision_id == (
            collection.revision_id
        )
        dialog.apply_button.click()
        _settle(presenter)
        assert refreshes == ["refresh", "refresh"]
        assert window.database_content_dialog() is None
        latest = window.product_catalogs().databases[0].current_manifest
        assert latest is not None
        assert latest.collection_sources[-1].revision_id == collection.revision_id
        assert catalog.history.rowCount() == 3
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
        _leaf("sma", {"period": 1}),
    )
    ema = _materialize(
        app.data_manager_domain,
        app.data_manager_domain._portable_recipes,
        _leaf("ema", {"period": 1}),
    )
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.edit_database_artifacts_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None
        row = _artifact_row(dialog, sma.root_logical_artifact_ids[0])
        checkbox = dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan is not None
        assert dialog.apply_button.isEnabled()

        competing = app.data_manager_domain.plan_database_artifact_addition(
            database.database_id, ema.root_logical_artifact_ids
        )
        published = app.data_manager_domain.execute_database_content_edit(competing)
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
        assert dialog.baseline_plan is None
        assert dialog.reviewed_plan is None
        assert not dialog.apply_button.isEnabled()
        assert not dialog.preview_button.isEnabled()
    finally:
        window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp


def test_catalog_seed_and_database_delete_controls_use_existing_lifecycle(
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
    seed, database = _create_seed_only_database(application, "Delete Controls")
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        catalog = window._catalog_workspace
        catalog.dataset_scope.setCurrentIndex(catalog.dataset_scope.findData("all"))

        catalog.select_family("Database Seeds")
        assert catalog.table.rowCount() == 1
        catalog.table.selectRow(0)
        assert catalog.delete_database_seed_button.isEnabled()
        catalog.delete_database_seed_button.click()
        _settle(presenter)
        assert all(item.seed_id != seed.seed_id for item in window.product_catalogs().database_seeds)
        assert any(
            item.definition.database_id == database.database_id
            for item in window.product_catalogs().databases
        )

        catalog.select_family("Databases")
        assert catalog.table.rowCount() == 1
        catalog.table.selectRow(0)
        _settle(presenter)
        assert catalog.delete_database_button.isEnabled()
        catalog.delete_database_button.click()
        _settle(presenter)
        assert not window.product_catalogs().databases
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
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    entered = Event()
    release = Event()
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.edit_database_artifacts_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None

        original_plan = app.data_manager_domain.plan_database_content_edit

        def delayed_plan(*args, **kwargs):
            if any(kwargs.values()):
                entered.set()
                assert release.wait(10.0)
            return original_plan(*args, **kwargs)

        monkeypatch.setattr(
            app.data_manager_domain,
            "plan_database_content_edit",
            delayed_plan,
        )
        row = _artifact_row(dialog, result.root_logical_artifact_ids[0])
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
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, application)
    entered = Event()
    release = Event()
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        window._catalog_workspace.edit_database_artifacts_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None

        original_plan = app.data_manager_domain.plan_database_content_edit

        def delayed_plan(*args, **kwargs):
            if any(kwargs.values()):
                entered.set()
                assert release.wait(10.0)
            return original_plan(*args, **kwargs)

        monkeypatch.setattr(
            app.data_manager_domain,
            "plan_database_content_edit",
            delayed_plan,
        )
        row = _artifact_row(dialog, result.root_logical_artifact_ids[0])
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



def test_a2_all_datasets_legacy_edit_without_selected_or_existing_ohlcv(tmp_path):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    service = app.data_manager_domain
    original, collection, roots, before = _a2_snapshot(service, service._portable_recipes)
    extra = _materialize(service, service._portable_recipes, _leaf("ema", {"period": 5})).root_logical_artifact_ids[0]
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    store = service._artifacts._ohlcv_store
    store.csv_path(MARKET).unlink()
    store.sidecar_path(MARKET).unlink()
    service.invalidate_source(MARKET)
    window = DataManagerSuiteWindow()
    presenter = DataManagerSuitePresenter(window, app.data_manager_service)
    try:
        window.show()
        presenter.refresh()
        _settle(presenter)
        catalog = window._catalog_workspace
        catalog.set_selected_market(None)
        catalog.dataset_scope.setCurrentIndex(catalog.dataset_scope.findData("all"))
        catalog.select_family("Databases")
        row = next(i for i, value in enumerate(catalog._visible_values)
                   if value.definition.database_id == original.database_id)
        catalog.table.selectRow(row)
        QCoreApplication.processEvents()
        _settle(presenter)
        assert catalog.edit_database_artifacts_button.isEnabled()
        catalog.edit_database_artifacts_button.click()
        _settle(presenter)
        dialog = window.database_content_dialog()
        assert dialog is not None and dialog.baseline_plan is not None
        included = next(i for i, value in enumerate(dialog._source_values) if value.was_selected)
        removed = dialog._source_values[included].output.column_name
        dialog.source_table.cellWidget(included, 0).setChecked(False)
        dialog.source_table.cellWidget(_artifact_row(dialog, extra), 0).setChecked(True)
        dialog.preview_button.click()
        _settle(presenter)
        assert dialog.reviewed_plan is not None and not dialog.reviewed_plan.blocked
        assert dialog.reviewed_plan.remove_columns == (removed,)
        dialog.apply_button.click()
        _settle(presenter)
        assert window.database_content_dialog() is None
        edited = service.load_database_revision(original.database_id).manifest
        assert edited.schema_version == "5.0"
        assert "ema_5" in edited.column_mapping and removed not in edited.column_mapping
        assert service.load_database_revision(original.database_id, original.revision_id).values_csv == before
        assert service.plan_database_update(original.database_id).blocked
    finally:
        window.close()
        QCoreApplication.processEvents()
        app.shutdown()
        del qapp
