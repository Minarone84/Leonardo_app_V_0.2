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
from leonardo.data_manager import DataManagerArtifactMaterializationRequest
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.recipes import build_portable_recipe
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def _recipe(tool_key: str):
    parameters = dict(resolve_parameters(tool_key, {"period": 3}))
    return build_portable_recipe(
        tool_key=tool_key,
        kind="indicator",
        parameters=parameters,
        output_names=resolve_output_names(tool_key, parameters),
    )


def _select_collection(catalog, family: str, collection_id: str) -> None:
    catalog.select_family(family)
    for row, value in enumerate(catalog._visible_values):
        if value.collection_id == collection_id:
            catalog.table.selectRow(row)
            return
    raise AssertionError(f"Collection not found: {collection_id}")


def test_real_collection_management_create_edit_and_restart(tmp_path) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    recipes = (_recipe("sma"), _recipe("ema"))
    for recipe in recipes:
        app.portable_recipe_store.save_recipe(recipe)
    materialization = app.data_manager_domain.execute_artifact_materialization(
        app.data_manager_domain.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(
                MARKET, tuple(item.recipe_id for item in recipes)
            )
        )
    )
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
        catalog = window._catalog_workspace

        catalog.select_family("Recipes")
        catalog.create_recipe_collection_button.click()
        recipe_dialog = window.recipe_collection_dialog()
        assert recipe_dialog is not None
        recipe_dialog.select_all_button.click()
        recipe_dialog.preview_button.click()
        _settle(presenter)
        recipe_dialog.name_input.setText("Research Recipes")
        recipe_dialog.publish_button.click()
        _settle(presenter)
        recipe_collection_id = recipe_dialog.collection_id
        first_recipe_revision = recipe_dialog.expected_revision_id
        assert recipe_collection_id and first_recipe_revision

        _select_collection(catalog, "Recipe Collections", recipe_collection_id)
        _settle(presenter)
        catalog.edit_recipe_collection_button.click()
        _settle(presenter)
        recipe_dialog = window.recipe_collection_dialog()
        assert recipe_dialog is not None
        recipe_dialog.description_input.setText("Revised")
        recipe_dialog.preview_button.click()
        _settle(presenter)
        recipe_dialog.publish_button.click()
        _settle(presenter)
        second_recipe_revision = recipe_dialog.expected_revision_id
        assert second_recipe_revision not in {None, first_recipe_revision}
        assert len(
            app.data_manager_domain.list_recipe_collection_revisions(
                recipe_collection_id
            )
        ) == 2

        assert window.select_market(MARKET)
        _settle(presenter)
        catalog.select_family("Artifacts")
        catalog.create_artifact_collection_button.click()
        artifact_dialog = window.artifact_collection_dialog()
        assert artifact_dialog is not None
        artifact_dialog.select_all_button.click()
        assert set(artifact_dialog.selected_root_logical_artifact_ids()) == set(
            materialization.root_logical_artifact_ids
        )
        artifact_dialog.preview_button.click()
        _settle(presenter)
        artifact_dialog.name_input.setText("Research Artifacts")
        artifact_dialog.publish_button.click()
        _settle(presenter)
        artifact_collection_id = artifact_dialog.collection_id
        first_artifact_revision = artifact_dialog.expected_revision_id
        assert artifact_collection_id and first_artifact_revision

        catalog.dataset_scope.setCurrentIndex(1)
        _select_collection(
            catalog, "Artifact Collections", artifact_collection_id
        )
        _settle(presenter)
        catalog.edit_artifact_collection_button.click()
        artifact_dialog = window.artifact_collection_dialog()
        assert artifact_dialog is not None
        artifact_dialog.description_input.setText("Revised")
        artifact_dialog.preview_button.click()
        _settle(presenter)
        artifact_dialog.publish_button.click()
        _settle(presenter)
        second_artifact_revision = artifact_dialog.expected_revision_id
        assert second_artifact_revision not in {None, first_artifact_revision}
        assert len(
            app.data_manager_domain.list_artifact_collection_revisions(
                artifact_collection_id
            )
        ) == 2
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()

    restarted = LeonardoApp(config)
    try:
        restarted.startup()
        assert len(
            restarted.data_manager_domain.list_recipe_collection_revisions(
                recipe_collection_id
            )
        ) == 2
        assert len(
            restarted.data_manager_domain.list_artifact_collection_revisions(
                artifact_collection_id
            )
        ) == 2
        assert (
            restarted.data_manager_domain.inspect_recipe_collection(
                recipe_collection_id
            ).collection.revision_id
            == second_recipe_revision
        )
        assert (
            restarted.data_manager_domain.load_artifact_collection(
                artifact_collection_id
            ).revision_id
            == second_artifact_revision
        )
    finally:
        restarted.shutdown()
    del qapp
