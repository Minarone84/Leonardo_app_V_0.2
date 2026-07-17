from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from leonardo.gui.windows.study_environment_save_dialog import StudyEnvironmentSaveDialog
from tests.research_test.test_study_execution import accepted_context, prepare


def test_environment_save_dialog_captures_slot_session_and_metadata_only(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    dataset, artifacts, _frame = accepted_context(tmp_path)
    study = prepare(
        __import__("leonardo.research", fromlist=["ResearchStudyService"]).ResearchStudyService(artifacts),
        dataset,
        "ema",
        parameters={"period": 20},
    )
    dialog = StudyEnvironmentSaveDialog(2, "session_two", (study,), ())
    dialog.findChild(QLineEdit, "research.environment_save_dialog.edit.name").setText(
        "Momentum"
    )
    intent = dialog.current_intent()
    assert (intent.slot_id, intent.session_id, intent.mode) == (2, "session_two", "create")
    assert intent.metadata_overrides[0][0] == study.study_id
