from pathlib import Path
from threading import Event

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.research.notebook_application import (
    ResearchNotebookApplicationService,
)
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore
from leonardo.research.workspace_notebook_link import (
    ResearchWorkspaceNotebookLinkService,
)
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


def test_application_service_runs_notebook_list_through_core(tmp_path: Path) -> None:
    runner = CoreRunner(TaskManager())
    notebook_domain = ResearchNotebookService(
        ResearchNotebookStore(tmp_path / "notebooks")
    )
    link = ResearchWorkspaceNotebookLinkService(
        ResearchWorkspaceSnapshotStore(tmp_path / "snapshots"),
        notebook_domain,
    )
    application = ResearchNotebookApplicationService(
        runner,
        notebook_domain,
        link,
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


def test_delete_delegates_to_coordinated_link_and_cleans_before_callback(
    tmp_path: Path, monkeypatch
) -> None:
    runner = CoreRunner(TaskManager())
    notebook_domain = ResearchNotebookService(
        ResearchNotebookStore(tmp_path / "notebooks")
    )
    link = ResearchWorkspaceNotebookLinkService(
        ResearchWorkspaceSnapshotStore(tmp_path / "snapshots"),
        notebook_domain,
    )
    application = ResearchNotebookApplicationService(runner, notebook_domain, link)
    called = []
    completed = Event()
    summary = notebook_domain.create_notebook(
        notebook_domain.build_draft(
            notebook_id="notebook_one",
            display_name="Notebook One",
        )
    )
    expected = notebook_domain.list_notebooks()[0]

    def coordinated(notebook_id):
        called.append(notebook_id)
        return expected

    monkeypatch.setattr(link, "delete_notebook_with_reference_cleanup", coordinated)
    runner.start()
    try:
        application.submit_delete_notebook(
            summary.notebook_id,
            result_callback=lambda result: (
                assert_terminal_cleanup(application, result, expected),
                completed.set(),
            ),
        )
        assert completed.wait(3)
        assert called == ["notebook_one"]
    finally:
        runner.shutdown()


def assert_terminal_cleanup(application, result, expected):
    assert application._cancellations == {}
    assert result.status == "completed"
    assert result.value == expected
