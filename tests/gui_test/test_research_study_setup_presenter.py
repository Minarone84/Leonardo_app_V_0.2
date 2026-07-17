from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QSpinBox

from leonardo.gui.windows.study_setup_dialog import StudySetupDialog
from tests.gui_test.test_research_single_chart_integration import _wait_until
from tests.gui_test.test_research_study_presenter import _open


def test_suite_add_study_routes_dialog_result_to_captured_chart(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open(tmp_path)
    try:
        window.button_for_id("research_suite.button.add_study").click()
        _wait_until(lambda: bool(window.findChildren(StudySetupDialog)))
        dialog = window.findChildren(StudySetupDialog)[0]
        tools = dialog.findChild(QListWidget, "research.study_setup_dialog.list.tools")
        for row in range(tools.count()):
            if tools.item(row).text() == "EMA":
                tools.setCurrentRow(row)
                break
        dialog.findChild(QSpinBox, "research.study_setup_dialog.parameter.period").setValue(20)
        dialog.findChild(
            __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton,
            "research.study_setup_dialog.button.apply",
        ).click()
        _wait_until(lambda: presenter.session.study_count == 1)
        assert presenter.session.studies[0].setup_request.parameters["period"] == 20
    finally:
        main.close()
        app.shutdown()
