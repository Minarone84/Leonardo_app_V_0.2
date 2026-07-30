"""Core-supervised application wrapper for Research Workspace Snapshots."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock
from uuid import uuid4

from leonardo.core.core_runner import CallbackDispatcher, CoreRunner, TaskResult, TaskSubmission
from leonardo.research.workspace_snapshot import (
    ResearchWorkspaceSnapshotDraft,
    ResearchWorkspaceSnapshotV1,
    WorkspaceSnapshotCapture,
)
from leonardo.research.workspace_snapshot_service import ResearchWorkspaceSnapshotService
from leonardo.research.workspace_notebook_link import (
    ResearchWorkspaceNotebookLinkService,
)


class ResearchWorkspaceSnapshotApplicationService:
    """Run snapshot persistence and preflight through the shared CoreRunner."""

    def __init__(
        self,
        core_runner: CoreRunner,
        service: ResearchWorkspaceSnapshotService,
        notebook_link: ResearchWorkspaceNotebookLinkService,
    ) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be CoreRunner")
        if not isinstance(service, ResearchWorkspaceSnapshotService):
            raise TypeError("service must be ResearchWorkspaceSnapshotService")
        if not isinstance(notebook_link, ResearchWorkspaceNotebookLinkService):
            raise TypeError(
                "notebook_link must be ResearchWorkspaceNotebookLinkService"
            )
        self._core_runner = core_runner
        self._service = service
        self._notebook_link = notebook_link
        self._cancellations: dict[str, Event] = {}
        self._lock = RLock()

    def build_draft(
        self,
        capture: WorkspaceSnapshotCapture,
        *,
        display_name: str,
        description: str = "",
        snapshot_id: str | None = None,
    ) -> ResearchWorkspaceSnapshotDraft:
        return self._service.build_draft(
            capture,
            display_name=display_name,
            description=description,
            snapshot_id=snapshot_id,
        )

    def submit_list_snapshots(self, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple(
                reporter, "Listing Workspace Snapshots", self._service.list_snapshots
            ),
            "Research Workspace Snapshot list",
            "research.workspace_snapshot.list",
            **callbacks,
        )

    def submit_load_snapshot(self, snapshot_id: str, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple(
                reporter,
                "Loading Workspace Snapshot",
                lambda: self._service.load_snapshot(snapshot_id),
            ),
            "Research Workspace Snapshot load",
            "research.workspace_snapshot.load",
            **callbacks,
        )

    def submit_create_snapshot(self, draft: ResearchWorkspaceSnapshotDraft, **callbacks):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Creating Workspace Snapshot",
                lambda: self._service.create_snapshot(draft),
            ),
            "Research Workspace Snapshot create",
            "research.workspace_snapshot.create",
            **callbacks,
        )

    def submit_update_snapshot(
        self, snapshot_id: str, draft: ResearchWorkspaceSnapshotDraft, **callbacks
    ):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Updating Workspace Snapshot",
                lambda: self._service.update_snapshot(snapshot_id, draft),
            ),
            "Research Workspace Snapshot update",
            "research.workspace_snapshot.update",
            **callbacks,
        )

    def submit_delete_snapshot(self, snapshot_id: str, **callbacks):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Deleting Workspace Snapshot",
                lambda: self._service.delete_snapshot(snapshot_id),
            ),
            "Research Workspace Snapshot delete",
            "research.workspace_snapshot.delete",
            **callbacks,
        )

    def submit_assign_notebook(
        self,
        snapshot_id: str,
        notebook_id: str,
        **callbacks,
    ):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Assigning Workspace Snapshot Notebook",
                lambda: self._notebook_link.assign_notebook(
                    snapshot_id,
                    notebook_id,
                ),
            ),
            "Research Workspace Snapshot Notebook assign",
            "research.workspace_snapshot.notebook_assign",
            **callbacks,
        )

    def submit_unassign_notebook(
        self,
        snapshot_id: str,
        notebook_id: str,
        **callbacks,
    ):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Unassigning Workspace Snapshot Notebook",
                lambda: self._notebook_link.unassign_notebook(
                    snapshot_id,
                    notebook_id,
                ),
            ),
            "Research Workspace Snapshot Notebook unassign",
            "research.workspace_snapshot.notebook_unassign",
            **callbacks,
        )

    def submit_preflight(
        self,
        snapshot: ResearchWorkspaceSnapshotV1,
        mode: str,
        current_workspace: object,
        **callbacks,
    ):
        return self._submit(
            lambda reporter, cancelled: self._preflight(
                reporter, cancelled, snapshot, mode, current_workspace
            ),
            "Research Workspace Snapshot preflight",
            "research.workspace_snapshot.preflight",
            **callbacks,
        )

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be non-empty text")
        with self._lock:
            cancellation = self._cancellations.get(task_id)
        if cancellation is None or cancellation.is_set():
            return False
        cancellation.set()
        return self._core_runner.cancel(task_id)

    def _submit(
        self,
        job,
        task_name: str,
        operation: str,
        *,
        progress_callback=None,
        result_callback=None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        cancelled = Event()
        completed = Event()
        task_ref: list[str] = []
        dispatcher = callback_dispatcher or _inline_dispatch

        def on_progress(progress) -> None:
            if progress_callback is not None:
                dispatcher(lambda: progress_callback(progress))

        def on_result(result: TaskResult) -> None:
            completed.set()
            task_id = task_ref[0] if task_ref else result.task_id
            with self._lock:
                self._cancellations.pop(task_id, None)
            if result_callback is not None:
                dispatcher(lambda: result_callback(result))

        submission = self._core_runner.submit_blocking_job(
            lambda reporter: job(reporter, cancelled),
            task_name=task_name,
            progress_callback=on_progress if progress_callback is not None else None,
            result_callback=on_result,
            callback_dispatcher=None,
            allow_duplicate_name=True,
            correlation_id=uuid4().hex,
            metadata={"operation": operation},
        )
        task_ref.append(submission.task_id)
        with self._lock:
            if not completed.is_set():
                self._cancellations[submission.task_id] = cancelled
        return submission

    def _preflight(self, reporter, cancelled, snapshot, mode, current_workspace):
        reporter.report("Checking Workspace Snapshot compatibility", current=0, total=1)
        value = self._service.preflight(
            snapshot,
            mode,
            current_workspace,
            cancellation_requested=cancelled.is_set,
        )
        reporter.report("Workspace Snapshot compatibility ready", current=1, total=1)
        return value

    @staticmethod
    def _simple(reporter, message: str, callback):
        reporter.report(message, current=0, total=1)
        value = callback()
        reporter.report(f"{message} complete", current=1, total=1)
        return value

    @staticmethod
    def _publishing(reporter, cancelled, message: str, callback):
        reporter.report(message, current=0, total=1)
        if cancelled.is_set():
            from leonardo.research.studies import StudyOperationCancelled

            raise StudyOperationCancelled(f"{message} cancelled before publication")
        value = callback()
        reporter.report(f"{message} complete", current=1, total=1)
        return value


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()
