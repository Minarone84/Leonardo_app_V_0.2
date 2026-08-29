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
from leonardo.gui.data_manager.update import UPDATE_STAGES, DataManagerUpdateWorkspace
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
        if presenter.active_task_id is None:
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


def _inspector_fields(window) -> dict[str, str]:
    table = window._catalog_workspace.inspector
    return {
        table.item(row, 0).text(): table.item(row, 1).text()
        for row in range(table.rowCount())
    }


def test_update_workspace_exposes_six_explicit_decision_stages() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    workspace = DataManagerUpdateWorkspace()
    try:
        assert tuple(
            workspace.stage_list.item(index).text()
            for index in range(workspace.stage_list.count())
        ) == UPDATE_STAGES
        assert "data_manager.update.button.append_database" in workspace.buttons
        assert "data_manager.update.button.rebuild_database" in workspace.buttons
        assert all("everything" not in button.text().casefold() for button in workspace.buttons.values())
        for object_id in (
            "data_manager.update.button.execute_artifacts",
            "data_manager.update.button.append_database",
            "data_manager.update.button.rebuild_database",
        ):
            assert not workspace.buttons[object_id].isEnabled()
    finally:
        workspace.close()


def test_update_plans_render_structured_nodes_and_commit_evidence() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    workspace = DataManagerUpdateWorkspace()
    try:
        strategy = SimpleNamespace(value="OVERLAP_RECALCULATION")
        node = SimpleNamespace(
            portable_recipe_id="a" * 64,
            logical_artifact_id="b" * 64,
            tool_key="sma",
            role="ROOT",
            action="CREATE",
            update_strategy=strategy,
            context_rows=20,
            revisable_tail_rows=5,
            blockers=(),
        )
        workspace.set_artifact_plan(SimpleNamespace(nodes=(node,)))
        workspace.set_database_plan(SimpleNamespace(
            database_id="db_" + "1" * 32,
            mode="APPEND",
            status="READY",
            collection_revision_id="c" * 64,
            column_names=("close", "sma_20"),
            execution_stages=(("append",),),
            blockers=(),
        ))
        assert workspace.artifact_plan_table.rowCount() == 1
        assert workspace.artifact_plan_table.item(0, 3).text() == "OVERLAP_RECALCULATION"
        assert workspace.database_plan_table.item(0, 0).text() == "APPEND"
    finally:
        workspace.close()


def test_update_execution_buttons_require_matching_plan_identity_and_mode() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    workspace = DataManagerUpdateWorkspace()
    try:
        workspace.collection_combo.addItem("First", "ac_first")
        workspace.collection_combo.addItem("Second", "ac_second")
        workspace.collection_combo.setCurrentIndex(0)
        workspace.database_combo.addItem("First", "db_first")
        workspace.database_combo.addItem("Second", "db_second")
        workspace.database_combo.setCurrentIndex(0)
        node = SimpleNamespace(
            portable_recipe_id="a" * 64,
            logical_artifact_id="b" * 64,
            tool_key="sma",
            role="ROOT",
            action="CREATE",
            update_strategy=SimpleNamespace(value="APPEND_ONLY"),
            context_rows=0,
            revisable_tail_rows=0,
            blockers=(),
        )
        blocked_node = SimpleNamespace(
            **{
                **node.__dict__,
                "blockers": ("dependency is stale",),
            }
        )
        workspace.set_artifact_plan(
            SimpleNamespace(
                collection_id="ac_first",
                nodes=(blocked_node,),
                blockers=("dependency is stale",),
                blocked=True,
            )
        )
        assert not workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()
        workspace.set_busy(True)
        workspace.set_busy(False)
        assert not workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()

        workspace.set_artifact_plan(
            SimpleNamespace(
                collection_id="ac_first",
                nodes=(node,),
                blockers=(),
                blocked=False,
            )
        )
        append = SimpleNamespace(
            database_id="db_first",
            mode="APPEND",
            status="READY",
            collection_revision_id="c" * 64,
            column_names=("close",),
            execution_stages=(("append",),),
            blockers=(),
            blocked=False,
        )
        workspace.set_database_plan(append)
        assert workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()
        assert workspace.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        assert not workspace.buttons[
            "data_manager.update.button.rebuild_database"
        ].isEnabled()

        workspace.set_busy(True)
        workspace.set_busy(False)
        assert workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()
        assert workspace.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()

        workspace.collection_combo.setCurrentIndex(1)
        assert not workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()
        workspace.collection_combo.setCurrentIndex(0)
        assert workspace.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()

        workspace.database_combo.setCurrentIndex(1)
        assert not workspace.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        workspace.database_combo.setCurrentIndex(0)
        rebuild = SimpleNamespace(**{
            **append.__dict__,
            "mode": "REBUILD_REQUIRED",
        })
        workspace.set_database_plan(rebuild)
        assert not workspace.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        assert workspace.buttons[
            "data_manager.update.button.rebuild_database"
        ].isEnabled()
    finally:
        workspace.close()


def test_real_gui_update_append_restart_and_explicit_rebuild(tmp_path) -> None:
    qapp = QApplication.instance() or QApplication([])
    historical = tmp_path / "historical_data"
    _accepted_dataset(historical, market=MARKET, rows=96)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    parameters = dict(resolve_parameters("sma", {"period": 3}))
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters=parameters,
        output_names=resolve_output_names("sma", parameters),
    )
    app.portable_recipe_store.save_recipe(recipe)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    request = DataManagerArtifactMaterializationRequest(MARKET, (recipe.recipe_id,))
    materialization = _completed(
        application.submit_execute_artifact_materialization,
        _completed(application.submit_plan_artifact_materialization, request),
    )
    collection = _completed(
        application.submit_create_artifact_collection, materialization, "SMA"
    )
    other_collection = _completed(
        application.submit_create_artifact_collection,
        materialization,
        "SMA Secondary",
    )
    seed = _completed(application.submit_create_database_seed, MARKET, "Research DB")
    database = _completed(
        application.submit_build_database_revision,
        seed.seed_id,
        collection.collection_id,
    )
    other_database = _completed(
        application.submit_build_database_revision,
        seed.seed_id,
        other_collection.collection_id,
        display_name="Secondary DB",
    )
    _composition, main, window, presenter = _open_data_manager(app)
    try:
        window.confirm_database_rebuild = lambda _plan: True
        _accepted_dataset(historical, market=MARKET, rows=104)
        window.button_for_id("data_manager.button.refresh").click()
        _settle(presenter)
        assert presenter._product_catalogs.latest_reconciliation.collections[0].status == "MEMBERS_REQUIRE_UPDATE"

        update = window._update_workspace
        update.collection_combo.setCurrentIndex(
            update.collection_combo.findData(collection.collection_id)
        )
        update.buttons["data_manager.update.button.plan_artifacts"].click()
        _settle(presenter)
        assert presenter._artifact_update_plan is not None
        update.collection_combo.setCurrentIndex(
            update.collection_combo.findData(other_collection.collection_id)
        )
        assert presenter._artifact_update_plan is None
        assert not update.buttons[
            "data_manager.update.button.execute_artifacts"
        ].isEnabled()
        update.buttons["data_manager.update.button.execute_artifacts"].click()
        assert presenter.active_task_id is None
        update.collection_combo.setCurrentIndex(
            update.collection_combo.findData(collection.collection_id)
        )
        update.buttons["data_manager.update.button.plan_artifacts"].click()
        _settle(presenter)
        update.buttons["data_manager.update.button.execute_artifacts"].click()
        _settle(presenter)
        validation = update.collection_validation_table
        assert validation.item(0, 6).text() == collection.collection_id
        assert validation.item(0, 7).text()
        assert validation.item(0, 8).text()
        assert validation.item(0, 1).text()

        update.database_combo.setCurrentIndex(
            update.database_combo.findData(database.database_id)
        )
        update.buttons["data_manager.update.button.plan_database"].click()
        _settle(presenter)
        assert presenter._database_update_plan.mode == "APPEND"
        assert update.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        assert not update.buttons[
            "data_manager.update.button.rebuild_database"
        ].isEnabled()
        update.database_combo.setCurrentIndex(
            update.database_combo.findData(other_database.database_id)
        )
        assert presenter._database_update_plan is None
        assert not update.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        update.database_combo.setCurrentIndex(
            update.database_combo.findData(database.database_id)
        )
        update.buttons["data_manager.update.button.plan_database"].click()
        _settle(presenter)
        update.buttons["data_manager.update.button.append_database"].click()
        _settle(presenter)
        commit = update.commit_report
        commit_values = {
            commit.item(row, 0).text(): commit.item(row, 1).text()
            for row in range(commit.rowCount())
        }
        assert commit_values["mode"] == "APPEND"
        assert commit_values["database_id"] == database.database_id
        assert commit_values["previous_revision_id"] == database.revision_id
        assert commit_values["values_hash"]
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()

    restarted = LeonardoApp(config)
    restarted.startup()
    restarted.start_core_runtime()
    _composition, main, window, presenter = _open_data_manager(restarted)
    try:
        window.confirm_database_rebuild = lambda _plan: True
        assert window.select_market(MARKET)
        _settle(presenter)
        revisions = restarted.data_manager_domain.list_database_revisions(
            database.database_id
        )
        assert len(revisions) == 2
        _publish_modified(historical, rows=104, mutate_row=20)
        window.button_for_id("data_manager.button.refresh").click()
        _settle(presenter)

        update = window._update_workspace
        update.collection_combo.setCurrentIndex(
            update.collection_combo.findData(collection.collection_id)
        )
        update.buttons["data_manager.update.button.plan_artifacts"].click()
        _settle(presenter)
        update.buttons["data_manager.update.button.execute_artifacts"].click()
        _settle(presenter)

        update.database_combo.setCurrentIndex(
            update.database_combo.findData(database.database_id)
        )
        update.buttons["data_manager.update.button.plan_database"].click()
        _settle(presenter)
        assert presenter._database_update_plan.mode == "REBUILD_REQUIRED"
        assert not update.buttons[
            "data_manager.update.button.append_database"
        ].isEnabled()
        assert update.buttons[
            "data_manager.update.button.rebuild_database"
        ].isEnabled()
        update.confirm_rebuild.setChecked(True)
        window.confirm_database_rebuild = lambda _plan: False
        update.buttons["data_manager.update.button.rebuild_database"].click()
        assert presenter.active_task_id is None
        assert len(
            restarted.data_manager_domain.list_database_revisions(
                database.database_id
            )
        ) == 2
        window.confirm_database_rebuild = lambda _plan: True
        update.buttons["data_manager.update.button.rebuild_database"].click()
        _settle(presenter)
        assert len(
            restarted.data_manager_domain.list_database_revisions(database.database_id)
        ) == 3
        commit_values = {
            update.commit_report.item(row, 0).text(): update.commit_report.item(
                row, 1
            ).text()
            for row in range(update.commit_report.rowCount())
        }
        assert commit_values["mode"] == "REBUILD_REQUIRED"
        assert commit_values["database_id"] == database.database_id

        for family, identity, field_name in (
            ("Artifact Collections", collection.collection_id, "revision_id"),
            ("Databases", database.database_id, "revision_id"),
        ):
            catalog = window._catalog_workspace
            catalog.select_family(family)
            _select_catalog_identity(catalog, identity)
            _settle(presenter)
            assert catalog.history.rowCount() >= 3
            first_revision = catalog.history.item(0, 2).text()
            last_revision = catalog.history.item(
                catalog.history.rowCount() - 1, 2
            ).text()
            catalog.history.selectRow(0)
            assert _inspector_fields(window)[field_name] == first_revision
            catalog.history.selectRow(catalog.history.rowCount() - 1)
            assert _inspector_fields(window)[field_name] == last_revision
    finally:
        main.close()
        QCoreApplication.processEvents()
        restarted.shutdown()
    del qapp
