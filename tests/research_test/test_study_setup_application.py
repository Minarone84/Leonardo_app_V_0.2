from __future__ import annotations

from pathlib import Path
from threading import Event

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.research import (
    ResearchStudySetupApplicationService,
    ResearchStudySetupService,
    StudyEnvironmentStore,
)

from tests.research_test.test_study_execution import accepted_context


def test_setup_application_runs_catalog_through_core_and_cleans_tasks(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    runner = CoreRunner(TaskManager())
    domain = ResearchStudySetupService(
        artifacts, StudyEnvironmentStore(tmp_path / "study_environments")
    )
    application = ResearchStudySetupApplicationService(runner, domain)
    completed = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = application.submit_catalog(
            dataset,
            (),
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(3.0)
        assert results[0].status == "completed"
        assert len(results[0].value.tools) == 26
        assert submission.task_id not in application._cancellations
    finally:
        runner.shutdown()
