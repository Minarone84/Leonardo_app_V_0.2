from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLineEdit

from tests.gui_test.test_research_multi_chart_presenter import _composed, _open_chart


def test_composed_position_detach_go_to_dock_and_close_flow(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        slots = [_open_chart(window, lifecycle) for _ in range(4)]
        assert slots == [1, 2, 3, 4]
        panel_4 = window.workspace.chart_panel_for_slot(4)
        panel_4.position_combo.setCurrentText("2")
        assert window.workspace.attached_slot_ids() == (1, 4, 3, 2)
        panel_4.detach_button.click()
        assert window.workspace.attached_slot_ids() == (1, 3, 2)
        assert window.workspace.detached_slot_ids() == (4,)
        panel_4.detach_button.click()
        panel_3 = window.workspace.chart_panel_for_slot(3)
        panel_3.go_to_button.click()
        dialog = lifecycle._go_to_dialogs[3]
        window.workspace.set_active_slot(1)
        field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
        field.setText("2024-01-01 00:00")
        dialog.findChild(object, "research.go_to_dialog.button.go").click()
        assert window.workspace.active_slot_id == 1
        panel_2 = window.workspace.chart_panel_for_slot(2)
        panel_2.detach_button.click()
        old_session = lifecycle._workspace_state.session_for(2)
        window.workspace.detached_window(2).close()
        qapp.processEvents()
        assert window.workspace.detached_window(2) is None
        assert window.workspace.attached_slot_ids() == (1, 4, 3, 2)
        assert not old_session.is_disposed
        panel_2.close_button.click()
        qapp.processEvents()
        assert old_session.is_disposed
        assert window.workspace.slot_ids() == (1, 3, 4)
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
