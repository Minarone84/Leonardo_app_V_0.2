"""Core-supervised application wrapper for Research Notebooks."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock
from uuid import uuid4

from leonardo.core.core_runner import CallbackDispatcher, CoreRunner, TaskResult, TaskSubmission
from leonardo.research.notebook import ResearchNotebookDraft
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.workspace_notebook_link import (
    ResearchWorkspaceNotebookLinkService,
)


class _DeleteCancellationControl:
    """Atomically order cancellation and coordinated Notebook deletion."""

    def __init__(self, lock: RLock) -> None:
        self._cancelled = Event()
        self._state = "cancellable"
        self._lock = lock

    def is_set(self) -> bool:
        return self._cancelled.is_set()

    def request_cancellation(self) -> bool:
        with self._lock:
            if self._state != "cancellable":
                return False
            self._cancelled.set()
            return True

    def begin_persistence(self) -> bool:
        with self._lock:
            if self._state != "cancellable" or self._cancelled.is_set():
                return False
            self._state = "persistence_started"
            return True

    def mark_terminal(self) -> None:
        with self._lock:
            self._state = "terminal"

    def is_terminal(self) -> bool:
        with self._lock:
            return self._state == "terminal"


class ResearchNotebookApplicationService:
    """Run Research Notebook persistence through the shared CoreRunner."""

    def __init__(
        self,
        core_runner: CoreRunner,
        service: ResearchNotebookService,
        notebook_link: ResearchWorkspaceNotebookLinkService,
    ) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be CoreRunner")
        if not isinstance(service, ResearchNotebookService):
            raise TypeError("service must be ResearchNotebookService")
        if not isinstance(notebook_link, ResearchWorkspaceNotebookLinkService):
            raise TypeError(
                "notebook_link must be ResearchWorkspaceNotebookLinkService"
            )
        self._core_runner = core_runner
        self._service = service
        self._notebook_link = notebook_link
        self._cancellations: dict[str, Event | _DeleteCancellationControl] = {}
        self._lock = RLock()

    def build_draft(self, **values) -> ResearchNotebookDraft:
        return self._service.build_draft(**values)

    def project_annotations(self, notebook, market_id):
        return self._service.project_annotations(notebook, market_id)

    def submit_list_notebooks(self, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple(
                reporter, "Listing Research Notebooks", self._service.list_notebooks
            ),
            "Research Notebook list",
            "research.notebook.list",
            **callbacks,
        )

    def submit_load_notebook(self, notebook_id: str, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple(
                reporter,
                "Loading Research Notebook",
                lambda: self._service.load_notebook(notebook_id),
            ),
            "Research Notebook load",
            "research.notebook.load",
            **callbacks,
        )

    def submit_create_notebook(self, draft: ResearchNotebookDraft, **callbacks):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Creating Research Notebook",
                lambda: self._service.create_notebook(draft),
            ),
            "Research Notebook create",
            "research.notebook.create",
            **callbacks,
        )

    def submit_update_notebook(
        self, notebook_id: str, draft: ResearchNotebookDraft, **callbacks
    ):
        return self._submit(
            lambda reporter, cancelled: self._publishing(
                reporter,
                cancelled,
                "Updating Research Notebook",
                lambda: self._service.update_notebook(notebook_id, draft),
            ),
            "Research Notebook update",
            "research.notebook.update",
            **callbacks,
        )

    def submit_delete_notebook(self, notebook_id: str, **callbacks):
        cancellation = _DeleteCancellationControl(self._lock)
        return self._submit_delete(
            notebook_id,
            cancellation,
            **callbacks,
        )

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be non-empty text")
        with self._lock:
            cancellation = self._cancellations.get(task_id)
        if cancellation is None:
            return False
        if isinstance(cancellation, _DeleteCancellationControl):
            if not cancellation.request_cancellation():
                return False
        else:
            if cancellation.is_set():
                return False
            cancellation.set()
        return self._core_runner.cancel(task_id)

    def _submit_delete(
        self,
        notebook_id: str,
        cancellation: _DeleteCancellationControl,
        *,
        progress_callback=None,
        result_callback=None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        completed = Event()
        task_ref: list[str] = []
        dispatcher = callback_dispatcher or _inline_dispatch

        def job(reporter):
            reporter.report("Deleting Research Notebook", current=0, total=1)
            if not cancellation.begin_persistence():
                from leonardo.research.studies import StudyOperationCancelled

                raise StudyOperationCancelled(
                    "Deleting Research Notebook cancelled before publication"
                )
            value = self._notebook_link.delete_notebook_with_reference_cleanup(
                notebook_id
            )
            reporter.report(
                "Deleting Research Notebook complete",
                current=1,
                total=1,
            )
            return value

        def on_progress(progress) -> None:
            if progress_callback is not None:
                dispatcher(lambda: progress_callback(progress))

        def on_result(result: TaskResult) -> None:
            completed.set()
            task_id = task_ref[0] if task_ref else result.task_id
            cancellation.mark_terminal()
            with self._lock:
                if self._cancellations.get(task_id) is cancellation:
                    self._cancellations.pop(task_id, None)
            if result_callback is not None:
                dispatcher(lambda: result_callback(result))

        submission = self._core_runner.submit_blocking_job(
            job,
            task_name="Research Notebook delete",
            progress_callback=on_progress if progress_callback is not None else None,
            result_callback=on_result,
            callback_dispatcher=None,
            allow_duplicate_name=True,
            correlation_id=uuid4().hex,
            metadata={"operation": "research.notebook.delete"},
        )
        task_ref.append(submission.task_id)
        with self._lock:
            if not completed.is_set() and not cancellation.is_terminal():
                self._cancellations[submission.task_id] = cancellation
        return submission

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
