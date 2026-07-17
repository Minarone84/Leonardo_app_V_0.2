from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QSpinBox

from leonardo.gui.windows.study_setup_dialog import StudySetupDialog
from leonardo.research import (
    ResearchStudySetupService,
    StudyEnvironmentStore,
    StudyExecutionRequest,
)
from tests.research_test.test_study_execution import accepted_context


def test_setup_dialog_projects_canonical_spec_and_builds_existing_request(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    catalog = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "env")
    ).build_catalog(dataset, ())
    dialog = StudySetupDialog(catalog)
    tools = dialog.findChild(QListWidget, "research.study_setup_dialog.list.tools")
    assert tools.count() == 26
    for row in range(tools.count()):
        if tools.item(row).text() == "EMA":
            tools.setCurrentRow(row)
            break
    period = dialog.findChild(QSpinBox, "research.study_setup_dialog.parameter.period")
    period.setValue(20)
    request = dialog.current_request()
    assert isinstance(request, StudyExecutionRequest)
    assert request.tool_key == "ema"
    assert request.parameters["period"] == 20
