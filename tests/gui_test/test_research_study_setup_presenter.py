from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QSpinBox

from tests.gui_test.test_research_multi_chart_presenter import _composed, _open_chart
from tests.gui_test.test_research_single_chart_integration import _wait_until


def test_suite_add_study_routes_dialog_result_to_captured_chart(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        first_slot = _open_chart(window, lifecycle)
        second_slot = _open_chart(window, lifecycle)
        first = lifecycle._chart_presenters[first_slot]
        second = lifecycle._chart_presenters[second_slot]
        panel = window.workspace.chart_panel_for_slot(first_slot)
        panel.financial_tools_button.click()
        _wait_until(lambda: first_slot in lifecycle._financial_tools_dialogs)
        dialog = lifecycle._financial_tools_dialogs[first_slot]
        tools = dialog.findChild(
            QListWidget, "research_restoration.financial_tools.tools"
        )
        for row in range(tools.count()):
            if tools.item(row).text() == "EMA":
                tools.setCurrentRow(row)
                break
        dialog.findChild(
            QSpinBox, "research_restoration.financial_tools.parameter.period"
        ).setValue(20)
        window.workspace.set_active_slot(second_slot)
        dialog.apply_button.click()
        _wait_until(lambda: first.session.study_count == 1)
        assert first.session.studies[0].setup_request.parameters["period"] == 20
        assert second.session.study_count == 0
    finally:
        main.close()
        app.shutdown()
