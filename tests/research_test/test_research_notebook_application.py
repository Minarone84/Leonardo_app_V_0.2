from pathlib import Path
from threading import Event

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.research.notebook_application import (
    ResearchNotebookApplicationService,
)
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore


def test_application_service_runs_notebook_list_through_core(tmp_path: Path) -> None:
    runner = CoreRunner(TaskManager())
    application = ResearchNotebookApplicationService(
        runner,
        ResearchNotebookService(ResearchNotebookStore(tmp_path / "notebooks")),
    )
    completed = Event()
    results: list[TaskResult] = []
    runner.start()
    try:
        submission = application.submit_list_notebooks(
            result_callback=lambda result: (results.append(result), completed.set())
        )
        assert completed.wait(3.0)
        assert results[0].status == "completed"
        assert results[0].value == ()
        assert submission.task_id not in application._cancellations
    finally:
        runner.shutdown()


def test_application_service_uses_shared_runner_and_task_prefix():
    source = Path("src/leonardo/research/notebook_application.py").read_text(
        encoding="utf-8"
    )
    assert "CoreRunner" in source
    assert "research.notebook." in source
    assert "ThreadPoolExecutor" not in source
