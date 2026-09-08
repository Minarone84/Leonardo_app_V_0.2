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
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.recipes import PortableRecipeDependencyV1, build_portable_recipe
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _settle(presenter, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while presenter.active_task_id is not None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    QCoreApplication.processEvents()
    assert presenter.active_task_id is None


def _leaf(tool_key: str):
    parameters = dict(resolve_parameters(tool_key, {"period": 3}))
    return build_portable_recipe(
        tool_key=tool_key,
        kind="indicator" if tool_key != "rsi" else "oscillator",
        parameters=parameters,
        output_names=resolve_output_names(tool_key, parameters),
    )


def _delta(fast, slow):
    parameters = {"eps": 1e-12, "mode": "abs"}
    return build_portable_recipe(
        tool_key="delta",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names(
            "delta",
            {
                **parameters,
                "fast": "__research_fast",
                "slow": "__research_slow",
            },
        ),
        dependencies=(
            PortableRecipeDependencyV1(
                "fast", fast.recipe_id, fast.output_names[0]
            ),
            PortableRecipeDependencyV1(
                "slow", slow.recipe_id, slow.output_names[0]
            ),
        ),
    )


def _select_source(catalog, family: str, identity: str) -> None:
    catalog.select_family(family)
    for row, value in enumerate(catalog._visible_values):
        if identity in {getattr(value, "recipe_id", None), getattr(value, "collection_id", None)}:
            catalog.table.selectRow(row)
            return
    raise AssertionError(f"source not found: {identity}")


def test_real_recipe_and_collection_materialization_survive_restart(tmp_path) -> None:
    qapp = QApplication.instance() or QApplication([])
    _accepted_dataset(tmp_path / "historical_data", market=MARKET)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    fast = _leaf("sma")
    slow = _leaf("ema")
    root = _delta(fast, slow)
    for recipe in (fast, slow, root):
        app.portable_recipe_store.save_recipe(recipe)
    collection = app.data_manager_domain.create_recipe_collection(
        "Derived Research",
        "",
        (root.recipe_id,),
    ).collection
    reviewed_revision_id = collection.revision_id
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
        catalog = window._catalog_workspace

        _select_source(catalog, "Recipes", root.recipe_id)
        _settle(presenter)
        catalog.create_artifact_from_recipe_button.click()
        dialog = window.recipe_artifact_materialization_dialog()
        assert dialog is not None
        dialog.preview_button.click()
        _settle(presenter)
        plan = dialog.reviewed_plan
        assert plan is not None and not plan.blocked
        assert plan.target_market_id == MARKET
        assert len(plan.root_recipe_ids) == 1
        assert {node.role for node in plan.nodes} == {"ROOT", "SUPPORT"}
        dialog.execute_button.click()
        _settle(presenter)
        managed = app.artifact_service.list_managed_artifacts(MARKET)
        assert len(managed) == 3
        assert len(app.data_manager_domain.scan_portable_recipes().recipes) == 3
        assert "roots=1" in dialog.result_summary.text()

        _select_source(catalog, "Recipe Collections", collection.collection_id)
        _settle(presenter)
        catalog.create_artifacts_from_recipe_collection_button.click()
        dialog = window.recipe_artifact_materialization_dialog()
        assert dialog is not None
        assert dialog.source_labels["revision_id"].text() == reviewed_revision_id
        dialog.preview_button.click()
        _settle(presenter)
        plan = dialog.reviewed_plan
        assert plan is not None and not plan.blocked
        assert plan.source_recipe_collection_id == collection.collection_id
        assert plan.source_recipe_collection_revision_id == reviewed_revision_id
        dialog.create_collection_checkbox.setChecked(True)
        dialog.collection_name_input.setText("Derived Artifacts")
        dialog.execute_button.click()
        _settle(presenter)
        artifact_collection = app.data_manager_domain.list_artifact_collections()[0]
        assert artifact_collection.source_recipe_collection_id == collection.collection_id
        assert (
            artifact_collection.source_recipe_collection_revision_id
            == reviewed_revision_id
        )
        assert "Artifact Collection" in dialog.result_summary.text()

        advanced = app.data_manager_domain.update_recipe_collection(
            collection.collection_id,
            collection.display_name,
            "advanced",
            (root.recipe_id,),
            expected_revision_id=reviewed_revision_id,
        ).collection
        assert advanced.revision_id != reviewed_revision_id
        preserved = app.data_manager_domain.load_artifact_collection(
            artifact_collection.collection_id
        )
        assert preserved.source_recipe_collection_revision_id == reviewed_revision_id
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()

    restarted = LeonardoApp(config)
    try:
        restarted.startup()
        loaded = restarted.data_manager_domain.load_artifact_collection(
            artifact_collection.collection_id
        )
        assert loaded.source_recipe_collection_id == collection.collection_id
        assert loaded.source_recipe_collection_revision_id == reviewed_revision_id
        assert len(restarted.artifact_service.list_managed_artifacts(MARKET)) == 3
        for summary in restarted.artifact_service.list_managed_artifacts(MARKET):
            restarted.artifact_service.load_artifact_by_id(
                MARKET, summary.artifact_id
            )
    finally:
        restarted.shutdown()
    del qapp
