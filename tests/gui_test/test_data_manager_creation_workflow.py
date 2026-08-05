from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.data_manager import DataManagerCatalogSnapshot, DataManagerDatasetEntry
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def test_nine_stage_creation_workspace_and_enabled_state_truth() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        assert window._creation_stage_list.count() == 9
        assert window.creation_stage() == 0
        assert not window.button_for_id(
            "data_manager.button.creation.use_target"
        ).isEnabled()

        window.set_catalog(
            DataManagerCatalogSnapshot(
                (DataManagerDatasetEntry(MARKET, True, 8, 1, 8),)
            )
        )
        window.select_market(MARKET, emit_selection=False)
        assert window.button_for_id(
            "data_manager.button.creation.use_target"
        ).isEnabled()

        window.set_busy(True, "build_database_revision")
        assert window.button_for_id("data_manager.button.cancel_operation").isEnabled()
        assert not window.button_for_id(
            "data_manager.button.creation.build"
        ).isEnabled()
        window.set_busy(False)
        assert not window.button_for_id("data_manager.button.cancel_operation").isEnabled()
    finally:
        window.close()


def test_creation_catalogs_and_intent_payload_are_canonical_gui_state() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    observed: list[tuple[str, dict[str, str]]] = []
    window.creation_action_requested.connect(
        lambda action, payload: observed.append((action, payload))
    )
    try:
        window.set_creation_catalogs(
            portable_recipes=(("a" * 64, "sma — sma_20"),),
            seeds=(("seed_" + "1" * 32, "Research DB"),),
            collections=(("ac_" + "2" * 32, "Features"),),
            databases=(("db_" + "3" * 32, "Research DB"),),
        )
        window._creation_controls["data_manager.input.seed_name"].setText(
            "Research DB"
        )
        for object_id in (
            "data_manager.combo.portable_recipe",
            "data_manager.combo.seed",
            "data_manager.combo.artifact_collection",
            "data_manager.combo.database",
        ):
            assert window._creation_controls[object_id].currentData() is None
            window._creation_controls[object_id].setCurrentIndex(1)
        window.button_for_id("data_manager.button.creation.refresh_foundations").click()

        assert observed[-1][0] == "refresh_foundations"
        assert observed[-1][1]["portable_recipe_id"] == "a" * 64
        assert observed[-1][1]["seed_id"] == "seed_" + "1" * 32
        assert observed[-1][1]["collection_id"] == "ac_" + "2" * 32
        assert observed[-1][1]["database_id"] == "db_" + "3" * 32
        assert observed[-1][1]["seed_name"] == "Research DB"
        window._creation_controls[
            "data_manager.creation.input.recipe_root_ids"
        ].setText(f"{'b' * 64}, {'c' * 64}")
        window.button_for_id("data_manager.button.creation.plan_base").click()
        assert observed[-1][1]["portable_recipe_ids"] == (
            "b" * 64,
            "c" * 64,
        )
    finally:
        window.close()
