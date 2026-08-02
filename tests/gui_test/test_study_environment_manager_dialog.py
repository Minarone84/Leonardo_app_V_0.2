from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QProgressBar, QPushButton

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


def test_manager_owns_environment_apply_progress_and_single_cancel_request() -> None:
    QApplication.instance() or QApplication([])
    environment = StudyEnvironmentV1.from_dict(
        json.loads(FIXTURE.read_text(encoding="utf-8"))["environment"]
    )
    summary = StudyEnvironmentSummary(
        environment.environment_id,
        environment.display_name,
        environment.description,
        len(environment.entries),
        environment.created_at_utc,
        environment.updated_at_utc,
    )
    dialog = StudyEnvironmentManagerDialog(
        (summary,), (StudyEnvironmentTarget(1, "session", "Chart 1"),)
    )
    dialog.set_environment(environment)
    intent = dialog.current_compatibility_intent()
    dialog.set_compatibility(
        intent, StudyEnvironmentCompatibilityReport(environment.environment_id)
    )
    progress = dialog.findChild(
        QProgressBar, "research.environment_manager_dialog.progress.apply"
    )
    status = dialog.findChild(
        QLabel, "research.environment_manager_dialog.label.apply_status"
    )
    cancel = dialog.findChild(
        QPushButton, "research.environment_manager_dialog.button.cancel_apply"
    )
    spy = QSignalSpy(dialog.cancel_apply_requested)
    dialog.begin_apply("run_one", len(environment.entries))
    assert dialog.isVisible() is False
    assert (progress.minimum(), progress.maximum(), progress.value()) == (
        0,
        len(environment.entries),
        0,
    )
    assert status.text() == "Preparing Study Environment..."
    assert not dialog.findChild(
        QPushButton, "research.environment_manager_dialog.button.apply"
    ).isEnabled()
    dialog.reject()
    assert dialog.result() == 0
    dialog.set_apply_progress(
        "run_one", 0, "Applying Study 1 of 2: First"
    )
    assert progress.value() == 0
    assert status.text() == "Applying Study 1 of 2: First"
    dialog.set_apply_progress("run_one", 1, "Study 1 of 2 complete.")
    assert progress.value() == 1
    cancel.click()
    cancel.click()
    assert spy.count() == 1
    assert status.text() == "Study Environment cancellation requested..."
    dialog.set_apply_progress("run_one", 2, "Study 2 of 2 complete.")
    dialog.set_apply_progress("run_one", 2, "Study Environment applied.")
    assert progress.value() == 1
    assert status.text() == "Study Environment cancellation requested..."
    dialog.finish_apply("run_one", "cancellation", "Environment Apply cancelled")
    assert status.text() == "Environment Apply cancelled"
    assert dialog.findChild(
        QPushButton, "research.environment_manager_dialog.button.close"
    ).isEnabled()
    dialog.begin_apply("run_two", len(environment.entries))
    assert progress.value() == 0
    assert status.text() == "Preparing Study Environment..."
    dialog.set_apply_progress("run_two", 1, "Study 1 of 2 complete.")
    assert progress.value() == 1
    assert status.text() == "Study 1 of 2 complete."
    dialog.finish_apply("run_two", "success")
    assert status.text() == "Study Environment applied."
