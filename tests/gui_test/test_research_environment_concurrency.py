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


def test_environment_runs_are_isolated_per_chart(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, suite = _open(tmp_path)
    try:
        suite.submit_study_calculation(StudyExecutionRequest("sma", {"period": 3}))
        _wait_until(lambda: suite.session.study_count == 1)
        environment = _single_study_environment(app, suite)
        window.button_for_id("research_suite.button.open_chart").click()
        _wait_until(lambda: suite.slot_ids() == (1, 2) and suite.chart_presenter(2).viewport is not None)
        first = suite.chart_presenter(1)
        second = suite.chart_presenter(2)
        report = StudyEnvironmentCompatibilityReport(environment.environment_id)
        first.set_environment_compatibility(report)
        second.set_environment_compatibility(report)
        first.apply_environment(environment, "append")
        second.apply_environment(environment, "append")
        _wait_until(
            lambda: not first.environment_apply_active and not second.environment_apply_active
        )
        assert first.session.study_count == 2
        assert second.session.study_count == 1
    finally:
        main.close()
        app.shutdown()
