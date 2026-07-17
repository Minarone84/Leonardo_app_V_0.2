from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.research import StudyEnvironmentCompatibilityReport, StudyExecutionRequest
from tests.gui_test.test_research_environment_apply import _single_study_environment
from tests.gui_test.test_research_single_chart_integration import _wait_until
from tests.gui_test.test_research_study_presenter import _open


def test_saved_environment_applies_to_detached_target_without_shell_state_persistence(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, suite = _open(tmp_path)
    try:
        suite.submit_study_calculation(StudyExecutionRequest("rsi", {"period": 14}))
        _wait_until(lambda: suite.session.study_count == 1)
        environment = _single_study_environment(app, suite)
        window.button_for_id("research_suite.button.open_chart").click()
        _wait_until(lambda: suite.slot_ids() == (1, 2) and suite.chart_presenter(2).viewport is not None)
        suite.detach_slot(2)
        target = suite.chart_presenter(2)
        target.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        target.apply_environment(environment, "append")
        _wait_until(lambda: not target.environment_apply_active)
        assert target.session.study_count == 1
        assert window.is_chart_detached(2)
        encoded = environment.canonical_json_bytes().decode("utf-8")
        assert "detached" not in encoded and "workspace_position" not in encoded
    finally:
        main.close()
        app.shutdown()
