import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.research.notebook import ResearchNotebookAnnotationSettingsV1
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore
from leonardo.research.workspace_notebook_link import (
    ResearchWorkspaceNotebookLinkService,
)
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotV1,
)
from leonardo.research.workspace_snapshot_application import (
    ResearchWorkspaceSnapshotApplicationService,
)
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore


def test_application_service_uses_shared_core_runner_and_task_prefix():
    source = Path("src/leonardo/research/workspace_snapshot_application.py").read_text(
        encoding="utf-8"
    )
    assert "CoreRunner" in source
    assert "research.workspace_snapshot." in source
    assert "ThreadPoolExecutor" not in source


def _application_system(tmp_path):
    ticks = iter(
        datetime(2026, 7, 21, 10, tzinfo=timezone.utc) + timedelta(minutes=index)
        for index in range(20)
    )
    snapshots = ResearchWorkspaceSnapshotStore(
        tmp_path / "snapshots", clock=lambda: next(ticks)
    )
    notebooks = ResearchNotebookService(
        ResearchNotebookStore(
            tmp_path / "notebooks", clock=lambda: next(ticks)
        )
    )
    source = ResearchWorkspaceSnapshotV1.from_dict(
        json.loads(
            Path(
                "tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json"
            ).read_text(encoding="utf-8")
        )["snapshot"]
    )
    snapshot = snapshots.create(
        ResearchWorkspaceSnapshotDraft(
            snapshot_id="snapshot_one",
            display_name="Snapshot One",
            description="",
            workspace=source.workspace,
            charts=source.charts,
        )
    )
    notebook = notebooks.create_notebook(
        notebooks.build_draft(
            notebook_id="notebook_one",
            display_name="Notebook One",
            annotation_settings=ResearchNotebookAnnotationSettingsV1(),
        )
    )
    link = ResearchWorkspaceNotebookLinkService(snapshots, notebooks)
    runner = CoreRunner(TaskManager())
    application = object.__new__(ResearchWorkspaceSnapshotApplicationService)
    application._core_runner = runner
    application._service = object()
    application._notebook_link = link
    application._cancellations = {}
    from threading import RLock

    application._lock = RLock()
    return runner, application, snapshot, notebook


def test_assign_and_unassign_use_core_and_exact_operations(tmp_path):
    runner, application, snapshot, notebook = _application_system(tmp_path)
    results: list[TaskResult] = []
    completed = Event()
    runner.start()
    try:
        assignment = application.submit_assign_notebook(
            snapshot.snapshot_id,
            notebook.notebook_id,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(3)
        assert results[-1].status == "completed"
        assert results[-1].value.notebook_id == notebook.notebook_id
        assert application._cancellations == {}
        assert (
            runner._task_manager.get_snapshot(assignment.task_id).metadata[
                "operation"
            ]
            == "research.workspace_snapshot.notebook_assign"
        )

        completed.clear()
        unassignment = application.submit_unassign_notebook(
            snapshot.snapshot_id,
            notebook.notebook_id,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(3)
        assert results[-1].status == "completed"
        assert results[-1].value.notebook_id is None
        assert application._cancellations == {}
        assert (
            runner._task_manager.get_snapshot(unassignment.task_id).metadata[
                "operation"
            ]
            == "research.workspace_snapshot.notebook_unassign"
        )
    finally:
        runner.shutdown()
