from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from leonardo.gui.data_manager.creation import CREATION_STAGES
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


def test_complete_creation_workspace_requires_explicit_state_across_nine_stages() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        workspace = window._creation_workspace
        assert tuple(
            workspace.stage_list.item(index).text()
            for index in range(workspace.stage_list.count())
        ) == CREATION_STAGES
        required = (
            "data_manager.button.creation.use_target",
            "data_manager.button.creation.create_seed",
            "data_manager.creation.button.plan_derivation",
            "data_manager.creation.button.create_recipe_collection",
            "data_manager.button.creation.materialize_base",
            "data_manager.button.creation.execute_batch",
            "data_manager.creation.button.validate_collection",
            "data_manager.button.creation.review",
            "data_manager.button.creation.build",
        )
        assert all(window.button_for_id(object_id) is not None for object_id in required)
        for object_id in (
            "data_manager.button.creation.materialize_base",
            "data_manager.button.creation.execute_batch",
            "data_manager.button.creation.build",
        ):
            assert not window.button_for_id(object_id).isEnabled()
        window.set_creation_catalogs(
            portable_recipes=(("a" * 64, "SMA"),),
            seeds=(("seed_" + "1" * 32, "Seed"),),
            collections=(("ac_" + "2" * 32, "Collection"),),
            databases=(("db_" + "3" * 32, "Database"),),
        )
        for object_id in (
            "data_manager.combo.portable_recipe",
            "data_manager.combo.seed",
            "data_manager.combo.artifact_collection",
            "data_manager.combo.database",
        ):
            assert workspace.controls[object_id].currentData() is None

        workspace.set_base_plan_ready(True)
        workspace.set_batch_plan_ready(True)
        workspace.set_database_readiness_ready(True)
        assert window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).isEnabled()
        assert window.button_for_id(
            "data_manager.button.creation.execute_batch"
        ).isEnabled()
        assert not window.button_for_id(
            "data_manager.button.creation.build"
        ).isEnabled()
        workspace.controls[
            "data_manager.creation.check.build_confirmed"
        ].setChecked(True)
        assert window.button_for_id("data_manager.button.creation.build").isEnabled()

        workspace.set_busy(True)
        assert not window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).isEnabled()
        workspace.set_busy(False)
        assert window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).isEnabled()

        workspace.controls[
            "data_manager.creation.input.recipe_root_ids"
        ].setText("b" * 64)
        assert not window.button_for_id(
            "data_manager.button.creation.materialize_base"
        ).isEnabled()

        workspace.set_collection_rows((
            (
                "a" * 64,
                "sma_20",
                "sma_20",
                "1",
                "support",
                "yes",
            ),
        ))
        for column in range(workspace.collection_table.columnCount()):
            assert not (
                workspace.collection_table.item(0, column).flags()
                & Qt.ItemFlag.ItemIsEditable
            )
    finally:
        window.close()
