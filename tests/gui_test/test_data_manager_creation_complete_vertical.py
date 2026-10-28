from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView

from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot
from tests.gui_test.test_data_manager_database_dialogs import _seed, _database_plan


def test_contextual_creation_requires_review_and_invalidates_changed_intent() -> None:
    app = QApplication.instance() or QApplication([])
    window = DataManagerSuiteWindow()
    seed = _seed()
    snapshot = replace(empty_product_snapshot(), database_seeds=(seed,))
    creations = []
    window.seed_only_database_create_requested.connect(creations.append)
    try:
        assert window._creation_workspace is None
        window.show_database_creation_dialog(snapshot, selected_seed=seed)
        dialog = window.database_creation_dialog()
        dialog.name_edit.setText("Base Database")
        assert dialog.preview_button.isEnabled()
        assert not dialog.create_button.isEnabled()
        plan = _database_plan(seed)
        dialog.set_plan(plan)
        assert dialog.create_button.isEnabled()
        assert dialog.preview_table.rowCount() > 0
        assert dialog.preview_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        dialog.set_busy(True)
        assert not dialog.create_button.isEnabled()
        dialog.set_busy(False)
        assert dialog.create_button.isEnabled()
        dialog.create_button.click()
        assert len(creations) == 1
        dialog.name_edit.setText("Changed Database")
        assert dialog.reviewed_plan is None
        assert not dialog.create_button.isEnabled()
    finally:
        window.close()
