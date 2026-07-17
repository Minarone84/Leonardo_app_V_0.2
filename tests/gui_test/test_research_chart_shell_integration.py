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
    app, main, window, presenter = _composed(tmp_path)
    try:
        slots = [_open_chart(window, presenter) for _ in range(4)]
        presenter.move_slot(4, 2)
        presenter.detach_slot(4)
        assert presenter.shell_state.attached_slot_ids() == (1, 3, 2)
        assert presenter.shell_state.detached_slot_ids() == (4,)
        presenter.dock_slot(4)
        presenter.open_go_to(3)
        dialog = next(iter(window._go_to_dialogs))
        presenter.set_active_slot(1)
        field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
        field.setText("2024-01-01")
        dialog.findChild(object, "research.go_to_dialog.button.go").click()
        assert presenter.active_slot_id == 1
        presenter.detach_slot(2)
        old_session = presenter.session_for(2)
        window.floating_chart_window(2).close()
        qapp.processEvents()
        assert old_session.is_disposed
        assert presenter.slot_ids() == (1, 3, 4)
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
