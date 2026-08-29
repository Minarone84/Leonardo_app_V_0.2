from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import MarketId
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.recipes import build_portable_recipe

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def _inspector_fields(window) -> dict[str, str]:
    table = window._catalog_workspace.inspector
    return {
        table.item(row, 0).text(): table.item(row, 1).text()
        for row in range(table.rowCount())
    }


def _select_catalog_identity(catalog, identity: str) -> None:
    if catalog.current_family == "Artifacts":
        for row, value in enumerate(catalog._visible_values):
            if value.logical_artifact_id == identity:
                catalog.table.selectRow(row)
                return
        raise AssertionError(f"Catalog identity not found: {identity}")
    identity_label = {
        "Recipe Collections": "Collection ID",
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


def test_real_gui_creation_workflow_survives_restart(tmp_path) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET)
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
    second_parameters = dict(resolve_parameters("bb", {}))
    second_recipe = build_portable_recipe(
        tool_key="bb",
        kind="indicator",
        parameters=second_parameters,
        output_names=resolve_output_names("bb", second_parameters),
    )
    app.portable_recipe_store.save_recipe(second_recipe)
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
        window.confirm_database_publication = lambda **_details: True
        _settle(presenter)

        assert window.select_market(MARKET), (
            window.status_text(), window.status_log_text(), window._datasets
        )
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.use_target").click()
        window.button_for_id("data_manager.button.creation.refresh_foundations").click()
        _settle(presenter)
        recipe_combo = window._creation_controls["data_manager.combo.portable_recipe"]
        assert recipe_combo.currentData() is None
        recipe_combo.setCurrentIndex(recipe_combo.findData(recipe.recipe_id))
        window._creation_controls[
            "data_manager.creation.input.recipe_root_ids"
        ].setText(f"{recipe.recipe_id}, {second_recipe.recipe_id}")
        window._creation_controls[
            "data_manager.creation.input.recipe_collection_name"
        ].setText("Research roots")
        window.button_for_id(
            "data_manager.creation.button.create_recipe_collection"
        ).click()
        _settle(presenter)
        _settle(presenter)
        recipe_collection_combo = window._creation_controls[
            "data_manager.creation.combo.recipe_collection"
        ]
        assert recipe_collection_combo.count() == 2
        recipe_collection_combo.setCurrentIndex(1)
        recipe_collection_id = recipe_collection_combo.currentData()
        initial_recipe_collection_revision = next(
            item.revision_id
            for item in presenter._product_catalogs.recipe_collections.collections
            if item.collection_id == recipe_collection_id
        )
        window._creation_controls[
            "data_manager.creation.input.recipe_collection_name"
        ].setText("Research roots revised")
        window.button_for_id(
            "data_manager.creation.button.update_recipe_collection"
        ).click()
        _settle(presenter)
        _settle(presenter)
        revised_recipe_collection_revision = next(
            item.revision_id
            for item in presenter._product_catalogs.recipe_collections.collections
            if item.collection_id == recipe_collection_id
        )
        assert revised_recipe_collection_revision != initial_recipe_collection_revision
        recipe_mode = window._creation_controls[
            "data_manager.creation.combo.recipe_mode"
        ]
        recipe_mode.setCurrentIndex(recipe_mode.findData("collection"))

        window._creation_controls["data_manager.input.seed_name"].setText("Native Smoke DB")
        window.button_for_id("data_manager.button.creation.create_seed").click()
        _settle(presenter)
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.plan_base").click()
        _settle(presenter)
        assert presenter._base_plan is not None
        recipe_mode.setCurrentIndex(recipe_mode.findData("direct"))
        assert presenter._base_plan is None
        assert not window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).isEnabled()
        window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).click()
        assert presenter.active_task_id is None
        recipe_mode.setCurrentIndex(recipe_mode.findData("collection"))
        window.button_for_id("data_manager.button.creation.plan_base").click()
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.materialize_base").click()
        _settle(presenter)
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.create_collection").click()
        _settle(presenter)
        _settle(presenter)

        base = presenter._base_materialization
        collection = presenter._creation_collection
        assert base is not None and collection is not None
        assert set(presenter._base_plan.root_recipe_ids) == {
            recipe.recipe_id,
            second_recipe.recipe_id,
        }
        collection_combo = window._creation_controls[
            "data_manager.combo.artifact_collection"
        ]
        collection_combo.setCurrentIndex(
            collection_combo.findData(collection.collection_id)
        )
        window.button_for_id(
            "data_manager.creation.button.load_collection"
        ).click()
        _settle(presenter)
        collection_table = window._creation_workspace.collection_table
        assert collection_table.rowCount() >= 4
        original_revision_id = presenter._creation_collection.revision_id
        collection_table.item(0, 1).setText("duplicate_column")
        collection_table.item(1, 1).setText("duplicate_column")
        window.button_for_id(
            "data_manager.creation.button.revise_collection"
        ).click()
        assert presenter.active_task_id is None
        assert "unique" in window._creation_workspace.summary.text()
        rows_by_logical: dict[str, list[int]] = {}
        for row in range(collection_table.rowCount()):
            rows_by_logical.setdefault(
                collection_table.item(row, 5).text(), []
            ).append(row)
        multi_rows = next(rows for rows in rows_by_logical.values() if len(rows) > 1)
        keep_row, remove_row = multi_rows[0], multi_rows[-1]
        original_output = collection_table.item(keep_row, 0).text()
        replacement_output = collection_table.item(remove_row, 0).text()
        collection_table.removeRow(remove_row)
        collection_table.item(keep_row, 0).setText(replacement_output)
        for row in range(collection_table.rowCount()):
            collection_table.item(row, 1).setText(f"feature_{row + 1}")
            collection_table.item(row, 2).setText(
                str(collection_table.rowCount() - row)
            )
        window.button_for_id(
            "data_manager.creation.button.revise_collection"
        ).click()
        _settle(presenter)
        _settle(presenter)
        collection = presenter._creation_collection
        assert collection.revision_id != original_revision_id
        assert collection.presentation_order[0] == f"feature_{collection_table.rowCount()}"
        selected_output_names = {
            item.output_name for item in collection.selected_outputs
        }
        assert replacement_output in selected_output_names
        assert original_output not in selected_output_names
        source = base.managed_artifacts[0]
        source_output = source.output_names[0]
        batch = window._creation_workspace.batch_table
        for column, value in enumerate((
            source_output,
            "derivative",
            '{"order": 1}',
            ",".join(resolve_output_names(
                "derivative", {"order": 1, "source": source_output}
            )),
            source.logical_artifact_id,
        )):
            batch.setItem(0, column, QTableWidgetItem(value))
        destination = window._creation_controls[
            "data_manager.creation.combo.batch_destination"
        ]
        destination.setCurrentIndex(destination.findData("existing_collection"))
        collection_combo.setCurrentIndex(
            collection_combo.findData(collection.collection_id)
        )
        window.button_for_id("data_manager.button.creation.plan_batch").click()
        _settle(presenter)
        batch.item(0, 2).setText('{"order": 2}')
        batch.item(0, 3).setText(
            ",".join(
                resolve_output_names(
                    "derivative", {"order": 2, "source": source_output}
                )
            )
        )
        assert presenter._batch_plan is None
        assert not window.button_for_id(
            "data_manager.button.creation.execute_batch"
        ).isEnabled()
        window.button_for_id("data_manager.button.creation.execute_batch").click()
        assert presenter.active_task_id is None
        window.button_for_id("data_manager.button.creation.plan_batch").click()
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.execute_batch").click()
        _settle(presenter)
        _settle(presenter)
        window.button_for_id("data_manager.button.creation.review").click()
        _settle(presenter)
        readiness = window._creation_workspace.readiness_table
        readiness_values = {
            readiness.item(row, 0).text(): readiness.item(row, 1).text()
            for row in range(readiness.rowCount())
        }
        assert "Coverage" not in readiness_values
        assert readiness_values["First TS"].endswith(" UTC")
        assert readiness_values["Last TS"].endswith(" UTC")
        revision_input = window._creation_controls[
            "data_manager.creation.input.collection_revision"
        ]
        revision_input.setText("stale revision")
        assert presenter._database_readiness is None
        assert not window.button_for_id(
            "data_manager.button.creation.build"
        ).isEnabled()
        revision_input.clear()
        window.button_for_id("data_manager.button.creation.review").click()
        _settle(presenter)
        window._creation_controls[
            "data_manager.creation.check.build_confirmed"
        ].setChecked(True)
        publication_evidence: list[dict[str, object]] = []

        def reject_publication(**details) -> bool:
            publication_evidence.append(details)
            return False

        window.confirm_database_publication = reject_publication
        window.button_for_id("data_manager.button.creation.build").click()
        assert presenter.active_task_id is None
        assert not app.data_manager_domain.list_database_ids()
        assert publication_evidence[-1]["market_id"] == MARKET
        assert publication_evidence[-1]["seed_id"] == presenter._creation_seed.seed_id
        assert publication_evidence[-1]["collection_revision_id"] == (
            presenter._creation_collection.revision_id
        )
        assert publication_evidence[-1]["row_count"] > 0
        assert publication_evidence[-1]["column_count"] > 0
        assert publication_evidence[-1]["selected_columns"]
        window.confirm_database_publication = lambda **_details: True
        window.button_for_id("data_manager.button.creation.build").click()
        _settle(presenter)
        _settle(presenter)

        assert app.data_manager_domain.list_database_seeds()
        collections = app.data_manager_domain.list_artifact_collections()
        databases = app.data_manager_domain.list_database_ids()
        assert collections and databases
        exact = app.data_manager_domain.load_database_revision(databases[0])
        seed_id = app.data_manager_domain.list_database_seeds()[0].seed_id
        collection_id = collections[0].collection_id
        database_id = exact.manifest.database_id
        revision_id = exact.manifest.revision_id
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()

    restarted = LeonardoApp(config)
    restarted.startup()
    restarted.start_core_runtime()
    composition = GuiCompositionRoot(restarted.context)
    main = composition.create_main_window()
    try:
        assert restarted.data_manager_domain.load_database_seed(seed_id).seed_id == seed_id
        assert restarted.data_manager_domain.load_artifact_collection(collection_id).collection_id == collection_id
        assert restarted.data_manager_domain.load_database_revision(
            database_id, revision_id
        ).manifest.revision_id == revision_id
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        QCoreApplication.processEvents()
        window = composition.data_manager_suite_window
        presenter = composition.data_manager_suite_presenter
        assert window is not None and presenter is not None
        _settle(presenter)
        assert window.select_market(MARKET)
        _settle(presenter)
        for family, expected_identity, field_name in (
            ("Recipe Collections", recipe_collection_id, "collection_id"),
            ("Artifacts", source.logical_artifact_id, "logical_artifact_id"),
            ("Artifact Collections", collection_id, "collection_id"),
            ("Databases", database_id, "database_id"),
        ):
            catalog = window._catalog_workspace
            catalog.select_family(family)
            _select_catalog_identity(catalog, expected_identity)
            _settle(presenter)
            assert catalog.history.rowCount() >= 1
            catalog.history.selectRow(0)
            assert _inspector_fields(window)[field_name] == expected_identity
    finally:
        main.close()
        QCoreApplication.processEvents()
        restarted.shutdown()
    del qapp
