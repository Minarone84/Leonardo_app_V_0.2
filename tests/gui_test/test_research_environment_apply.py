from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.research import StudyEnvironmentCompatibilityReport, StudyExecutionRequest
from tests.gui_test.test_research_single_chart_integration import _wait_until
from tests.gui_test.test_research_study_presenter import _open


def _single_study_environment(app, presenter):
    dataset = presenter.session.dataset
    draft = app.research_study_setup_domain.build_environment(
        dataset,
        presenter.session.studies,
        presenter.session.study_presentations(),
        display_name="EMA Environment",
    )
    return app.research_study_setup_domain.create_environment(draft)


def test_environment_append_and_replace_use_sequential_task_1017_apply(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    app, main, _window, suite = _open(tmp_path)
    try:
        suite.submit_study_calculation(StudyExecutionRequest("ema", {"period": 20}))
        _wait_until(lambda: suite.session.study_count == 1)
        environment = _single_study_environment(app, suite)
        chart = suite.chart_presenter(1)
        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(environment, "append")
        _wait_until(lambda: not chart.environment_apply_active)
        assert suite.session.study_count == 2
        assert suite.session.studies[-1].user_metadata == environment.entries[0].user_metadata

        chart.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        chart.apply_environment(environment, "replace")
        _wait_until(lambda: not chart.environment_apply_active)
        assert suite.session.study_count == 1
        assert suite.session.studies[0].result.output_names == environment.entries[0].expected_output_names
    finally:
        main.close()
        app.shutdown()
