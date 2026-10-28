from __future__ import annotations

import os
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.data_manager import DataManagerArtifactMaterializationRequest
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.data_manager.update import DataManagerUpdateWorkspace
from leonardo.recipes import build_portable_recipe

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_update_application_vertical import _completed
from tests.data_manager_test.test_update_workflow import _publish_modified


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    idle_passes = 0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if presenter.active_task_id is None and presenter._background_refresh_task_id is None:
            idle_passes += 1
            if idle_passes >= 3:
                return
        else:
            idle_passes = 0
        time.sleep(0.005)
    raise AssertionError("Data Manager GUI operation did not settle")


def _open_data_manager(app: LeonardoApp):
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    main.show()
    main.action_for_id("main_window.open_data_manager_suite").trigger()
    QCoreApplication.processEvents()
    window = composition.data_manager_suite_window
    presenter = composition.data_manager_suite_presenter
    assert window is not None and presenter is not None
    _settle(presenter)
    return composition, main, window, presenter


def _select_catalog_identity(catalog, identity: str) -> None:
    identity_label = {
        "Artifact Collections": "Collection ID",
        "Databases": "Database ID",
    }[catalog.current_family]
    identity_column = next(
        column
        for column in range(catalog.table.columnCount())
        if catalog.table.horizontalHeaderItem(column).text() == identity_label
    )
    for row in range(catalog.table.rowCount()):
        if catalog.table.item(row, identity_column).text() == identity:
            catalog.table.selectRow(row)
            return
    raise AssertionError(f"Catalog identity not found: {identity}")


PREFIX = "data_manager.update.button."


def _click(workspace, suffix, presenter):
    assert workspace.buttons[PREFIX + suffix].isEnabled(), suffix
    workspace.buttons[PREFIX + suffix].click()
    _settle(presenter)


def _database_row(workspace, database_id):
    for row in range(workspace.database_candidates.rowCount()):
        if workspace.database_candidates.item(row, 7).text() == database_id:
            workspace.database_candidates.selectRow(row)
            return
    raise AssertionError(database_id)


def test_two_tabs_candidates_multiselect_review_invalidation_and_lock(tmp_path):
    from tests.data_manager_test.test_update_workflow import _domain, _materialize, _sma, _append
    qapp = QApplication.instance() or QApplication([])
    service, _, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma(3), _sma(9))
    service.reconcile_update_status(force=True)
    workspace = DataManagerUpdateWorkspace()
    try:
        workspace.set_market(MARKET)
        workspace.set_snapshot(service.scan_product_catalogs())
        assert [workspace.tabs.tabText(i) for i in range(workspace.tabs.count())] == ["Artifacts", "Databases"]
        assert not hasattr(workspace, "collection_combo")
        assert not hasattr(workspace, "stage_list")
        assert workspace.artifact_candidates.rowCount() == 0
        assert workspace.database_candidates.rowCount() == 0
        _append(historical)
        service.reconcile_update_status(force=True)
        workspace.set_snapshot(service.scan_product_catalogs())
        assert workspace.artifact_candidates.rowCount() == 2
        workspace.buttons[PREFIX + "select_all"].click()
        roots = workspace.selected_roots()
        assert set(roots) == set(materialization.root_logical_artifact_ids)
        plan = service.plan_artifact_update(MARKET, roots)
        workspace.set_artifact_plan(plan)
        assert workspace.buttons[PREFIX + "execute_artifacts"].isEnabled()
        for action in ("REUSE_CURRENT", "UPDATE", "RECREATE", "BLOCKED"):
            node = replace(plan.nodes[0], action=action, reasons=("Exact reviewed evidence",))
            workspace.set_artifact_plan(replace(plan, nodes=(node,)))
            assert workspace.artifact_plan_table.item(0, 2).text() == action
            assert workspace.buttons[PREFIX + "execute_artifacts"].isEnabled() == (action != "BLOCKED")
        workspace.set_artifact_plan(plan)
        workspace._checks[roots[0]].setChecked(False)
        assert workspace._artifact_plan is None
        assert not workspace.buttons[PREFIX + "execute_artifacts"].isEnabled()
        workspace.buttons[PREFIX + "select_all"].click()
        workspace.set_artifact_plan(plan)
        workspace.set_busy(True)
        assert not any(b.isEnabled() for b in workspace.buttons.values())
        assert workspace.tabs.isEnabled()
        workspace.set_busy(False)
        assert workspace.buttons[PREFIX + "execute_artifacts"].isEnabled()
        workspace.buttons[PREFIX + "deselect_all"].click()
        assert not workspace.selected_roots()
        assert workspace._artifact_plan is None
        workspace.set_market(MarketId("bybit", "linear", "ETHUSDT", "1m"))
        assert workspace.artifact_candidates.rowCount() == 0
    finally:
        workspace.close()
    del qapp


def test_real_gui_root_update_waiting_database_append_restart_without_rebuild(tmp_path):
    from tests.data_manager_test.test_update_application_vertical import _recipe
    from tests.data_manager_test.test_update_workflow import _persistent_bytes
    qapp = QApplication.instance() or QApplication([])
    historical = tmp_path / "historical_data"
    _accepted_dataset(historical, market=MARKET, rows=96)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    recipe = _recipe()
    app.portable_recipe_store.save_recipe(recipe)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    materialization = _completed(
        application.submit_execute_artifact_materialization,
        _completed(application.submit_plan_artifact_materialization,
                   DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,))),
    )
    collection = _completed(application.submit_create_artifact_collection, materialization, "SMA")
    seed = _completed(application.submit_create_database_seed, MARKET, "Research DB")
    database = _completed(application.submit_build_database_revision, seed.seed_id, collection.collection_id)
    root = materialization.root_logical_artifact_ids[0]
    before_open = _persistent_bytes(tmp_path)
    _, main, window, presenter = _open_data_manager(app)
    try:
        assert window.select_market(MARKET)
        _settle(presenter)
        for family in ("Study Environments", "Recipes", "Recipe Collections", "Artifacts",
                       "Artifact Collections", "Database Seeds", "Databases"):
            window._catalog_workspace.select_family(family)
            if window._catalog_workspace.table.rowCount():
                window._catalog_workspace.table.selectRow(0)
                _settle(presenter)
        assert _persistent_bytes(tmp_path) == before_open
        assert [window._workspace_tabs.tabText(i) for i in range(window._workspace_tabs.count())] == ["Catalogs", "Update & Reconcile"]
        update = window._update_workspace
        assert update.artifact_candidates.rowCount() == 0
        assert update.database_candidates.rowCount() == 0
        _accepted_dataset(historical, market=MARKET, rows=104)
        before_review = _persistent_bytes(tmp_path)
        window.button_for_id("data_manager.button.refresh").click()
        _settle(presenter)
        assert update.artifact_candidates.rowCount() == 1
        _database_row(update, database.database_id)
        assert update.database_candidates.item(0, 2).text() == "valid"
        assert update.database_candidates.item(0, 3).text() == "WAITING FOR ARTIFACTS"
        _click(update, "plan_database", presenter)
        assert presenter._database_update_plan.status == "WAITING_FOR_ARTIFACT_UPDATE"
        assert presenter._database_update_plan.prerequisite_nodes[0].action == "UPDATE"
        assert not update.buttons[PREFIX + "append_database"].isEnabled()
        update._checks[root].setChecked(True)
        _click(update, "plan_artifacts", presenter)
        assert presenter._artifact_update_plan is not None
        assert _persistent_bytes(tmp_path) == before_review
        window.enter_dataset_evidence_changed_state(MARKET, "OHLCV evidence changed")
        assert not update.buttons[PREFIX + "execute_artifacts"].isEnabled()
        window.clear_dataset_evidence_changed_state()
        _click(update, "execute_artifacts", presenter)
        assert update.artifact_candidates.rowCount() == 0
        assert update.artifact_report.item(0, 1).text() == "1"
        assert presenter._database_update_plan is None
        assert update.database_candidates.rowCount() == 1
        _database_row(update, database.database_id)
        assert update.database_candidates.item(0, 2).text() == "valid"
        assert update.database_candidates.item(0, 3).text() == "APPEND READY"
        before_database_preview = _persistent_bytes(tmp_path)
        _click(update, "plan_database", presenter)
        assert presenter._database_update_plan.mode == "APPEND"
        assert _persistent_bytes(tmp_path) == before_database_preview
        _click(update, "append_database", presenter)
        assert update.database_candidates.rowCount() == 0
        assert update.commit_report.item(0, 1).text() == "APPEND"
        assert len(app.data_manager_domain.list_database_revisions(database.database_id)) == 2
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()

    restarted = LeonardoApp(config)
    restarted.startup()
    restarted.start_core_runtime()
    _, main, window, presenter = _open_data_manager(restarted)
    try:
        assert window.select_market(MARKET)
        _settle(presenter)
        assert len(restarted.data_manager_domain.list_database_revisions(database.database_id)) == 2
        _publish_modified(historical, rows=104, mutate_row=20)
        window.button_for_id("data_manager.button.refresh").click()
        _settle(presenter)
        update = window._update_workspace
        update._checks[root].setChecked(True)
        _click(update, "plan_artifacts", presenter)
        _click(update, "execute_artifacts", presenter)
        assert update.database_candidates.rowCount() == 0
        assert not hasattr(update, "confirm_rebuild")
        assert "data_manager.update.button.rebuild_database" not in update.buttons
        assert len(restarted.data_manager_domain.list_database_revisions(database.database_id)) == 2
        catalog = window._catalog_workspace
        catalog.select_family("Databases")
        headings = tuple(
            catalog.table.horizontalHeaderItem(index).text()
            for index in range(catalog.table.columnCount())
        )
        state_column = headings.index("State")
        readiness_column = headings.index("Update Readiness")
        revisions_column = headings.index("Revisions")
        assert catalog.table.item(0, state_column).text() == "valid"
        assert catalog.table.item(0, readiness_column).text() == "CURRENT"
        assert catalog.table.item(0, revisions_column).text() == "2"
    finally:
        main.close()
        QCoreApplication.processEvents()
        restarted.shutdown()
    del qapp
