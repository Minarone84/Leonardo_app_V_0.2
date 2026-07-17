from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidget, QPushButton

from leonardo.gui.windows.study_environment_manager_dialog import (
    StudyEnvironmentManagerDialog,
    StudyEnvironmentTarget,
)
from leonardo.research import (
    StudyEnvironmentCompatibilityReport,
    StudyEnvironmentSummary,
    StudyEnvironmentV1,
)


FIXTURE = Path(__file__).parent / "fixtures" / "task_1021_study_setup_environment_input.json"


def test_manager_lists_invalid_rows_and_enables_apply_only_after_compatibility() -> None:
    QApplication.instance() or QApplication([])
    environment = StudyEnvironmentV1.from_dict(
        json.loads(FIXTURE.read_text(encoding="utf-8"))["environment"]
    )
    valid = StudyEnvironmentSummary(
        environment.environment_id,
        environment.display_name,
        environment.description,
        len(environment.entries),
        environment.created_at_utc,
        environment.updated_at_utc,
    )
    invalid = StudyEnvironmentSummary(
        "env_invalid", "env_invalid", "", 0, None, None, False, "bad JSON"
    )
    dialog = StudyEnvironmentManagerDialog(
        (valid, invalid), (StudyEnvironmentTarget(2, "session_two", "Chart 2", True),)
    )
    assert dialog.findChild(QListWidget, "research.environment_manager_dialog.list.environments").count() == 2
    dialog.set_environment(environment)
    intent = dialog.current_compatibility_intent()
    dialog.set_compatibility(
        intent, StudyEnvironmentCompatibilityReport(environment.environment_id)
    )
    assert dialog.findChild(QPushButton, "research.environment_manager_dialog.button.apply").isEnabled()
