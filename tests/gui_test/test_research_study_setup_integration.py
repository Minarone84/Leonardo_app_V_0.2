from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.research import StudyEnvironmentCompatibilityReport, StudyExecutionRequest
from tests.gui_test.test_research_environment_apply import _single_study_environment
from tests.gui_test.test_research_multi_chart_presenter import _composed, _open_chart
from tests.gui_test.test_research_single_chart_integration import _wait_until


def test_saved_environment_applies_to_detached_target_without_shell_state_persistence(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, lifecycle = _composed(tmp_path)
    try:
        source_slot = _open_chart(window, lifecycle)
        target_slot = _open_chart(window, lifecycle)
        source = lifecycle._chart_presenters[source_slot]
        target = lifecycle._chart_presenters[target_slot]
        source.submit_study_calculation(
            StudyExecutionRequest("rsi", {"period": 14})
        )
        _wait_until(lambda: source.session.study_count == 1)
        environment = _single_study_environment(app, source)
        window.workspace.detach_chart(target_slot)
        target.set_environment_compatibility(
            StudyEnvironmentCompatibilityReport(environment.environment_id)
        )
        target.apply_environment(environment, "append")
        _wait_until(lambda: not target.environment_apply_active)
        assert target.session.study_count == 1
        assert window.workspace.detached_slot_ids() == (target_slot,)
        encoded = environment.canonical_json_bytes().decode("utf-8")
        assert "detached" not in encoded and "workspace_position" not in encoded
    finally:
        main.close()
        app.shutdown()
