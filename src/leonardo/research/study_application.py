"""Core-supervised application service for Research Study operations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from threading import Event, RLock
from uuid import uuid4

from leonardo.core.core_runner import (
    CallbackDispatcher,
    CoreRunner,
    ProgressCallback,
    ProgressReporter,
    ResultCallback,
    TaskResult,
    TaskSubmission,
)
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.studies import (
    ChartStudy,
    StudyApplyAttempt,
    StudyArtifactRequest,
    StudyEditAttempt,
    StudyExecutionRequest,
    StudySaveAttempt,
)
from leonardo.research.study_execution import ResearchStudyService


class _CancellationControl:
    """Atomically order cancellation, persistence start, and terminal cleanup."""

    def __init__(self, lock: RLock) -> None:
        self._cancelled = Event()
        self._state = "cancellable"
        self._lock = lock

    def cancellation_requested(self) -> bool:
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


class ResearchStudyApplicationService:
    """Run Study work in Core workers without mutating chart-session state."""

    def __init__(self, core_runner: CoreRunner, studies: ResearchStudyService) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        if not isinstance(studies, ResearchStudyService):
            raise TypeError("studies must be a ResearchStudyService")
        self._core_runner = core_runner
        self._studies = studies
        self._cancellations: dict[str, _CancellationControl] = {}
        self._lock = RLock()

    def submit_calculation(
        self,
        attempt: StudyApplyAttempt,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        request: StudyExecutionRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        snapshot = tuple(studies)
        cancellation = _CancellationControl(self._lock)

        def job(reporter: ProgressReporter):
            reporter.report("Resolving Research Study sources", current=0, total=2)
            prepared = self._studies.prepare_calculation(
                attempt,
                dataset,
                snapshot,
                request,
                cancellation_requested=cancellation.cancellation_requested,
            )
            reporter.report("Research Study calculation ready", current=2, total=2)
            return prepared

        return self._submit(
            job,
            task_name=f"Research Study Apply {request.tool_key}",
            operation="research_study_apply",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"study_id": attempt.study_id, "tool_key": request.tool_key},
        )

    def submit_artifact_apply(
        self,
        attempt: StudyApplyAttempt,
        dataset: HistoricalDataset,
        request: StudyArtifactRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        cancellation = _CancellationControl(self._lock)

        def job(reporter: ProgressReporter):
            reporter.report("Loading current Research artifact", current=0, total=2)
            prepared = self._studies.prepare_artifact(
                attempt,
                dataset,
                request,
                cancellation_requested=cancellation.cancellation_requested,
            )
            reporter.report("Research artifact Study ready", current=2, total=2)
            return prepared

        return self._submit(
            job,
            task_name=f"Research artifact Apply {request.tool_key}",
            operation="research_study_artifact_apply",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"study_id": attempt.study_id, "artifact_id": request.artifact_id},
        )

    def submit_edit(
        self,
        attempt: StudyEditAttempt,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        request: StudyExecutionRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        snapshot = tuple(studies)
        cancellation = _CancellationControl(self._lock)

        def job(reporter: ProgressReporter):
            reporter.report("Resolving Research Study Edit sources", current=0, total=2)
            prepared = self._studies.prepare_edit(
                attempt,
                dataset,
                snapshot,
                request,
                cancellation_requested=cancellation.cancellation_requested,
            )
            reporter.report("Research Study Edit ready", current=2, total=2)
            return prepared

        return self._submit(
            job,
            task_name=f"Research Study Edit {request.tool_key}",
            operation="research_study_edit",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"study_id": attempt.study_id, "tool_key": request.tool_key},
        )

    def submit_save(
        self,
        attempt: StudySaveAttempt,
        dataset: HistoricalDataset,
        study: ChartStudy,
        studies: Sequence[ChartStudy],
        *,
        description: str = "",
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        snapshot = tuple(studies)
        cancellation = _CancellationControl(self._lock)

        def job(reporter: ProgressReporter):
            reporter.report("Resolving durable Study lineage", current=0, total=2)
            outcome = self._studies.save_study(
                attempt,
                dataset,
                study,
                snapshot,
                description=description,
                cancellation_requested=cancellation.cancellation_requested,
                _begin_persistence=cancellation.begin_persistence,
            )
            reporter.report("Research Study save complete", current=2, total=2)
            return outcome

        return self._submit(
            job,
            task_name=f"Research Study Save {study.result.tool_key}",
            operation="research_study_save",
            cancellation=cancellation,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
            metadata={"study_id": study.study_id, "tool_key": study.result.tool_key},
        )

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            cancellation = self._cancellations.get(task_id)
        if cancellation is None or not cancellation.request_cancellation():
            return False
        return self._core_runner.cancel(task_id)

    def _submit(
        self,
        job: Callable[[ProgressReporter], object],
        *,
        task_name: str,
        operation: str,
        cancellation: _CancellationControl,
        progress_callback: ProgressCallback | None,
        result_callback: ResultCallback | None,
        callback_dispatcher: CallbackDispatcher | None,
        metadata: dict[str, object],
    ) -> TaskSubmission:
        task_id_ref: list[str] = []
        external_dispatcher = callback_dispatcher or _inline_dispatch

        def on_progress(progress) -> None:
            if progress_callback is not None:
                external_dispatcher(lambda: progress_callback(progress))

        def on_result(result: TaskResult) -> None:
            task_id = task_id_ref[0] if task_id_ref else result.task_id
            cancellation.mark_terminal()
            with self._lock:
                if self._cancellations.get(task_id) is cancellation:
                    self._cancellations.pop(task_id, None)
            if result_callback is not None:
                external_dispatcher(lambda: result_callback(result))

        submission = self._core_runner.submit_blocking_job(
            job,
            task_name=task_name,
            progress_callback=on_progress if progress_callback is not None else None,
            result_callback=on_result,
            callback_dispatcher=None,
            allow_duplicate_name=True,
            correlation_id=uuid4().hex,
            metadata={"operation": operation, **metadata},
        )
        task_id_ref.append(submission.task_id)
        with self._lock:
            if not cancellation.is_terminal():
                self._cancellations[submission.task_id] = cancellation
        return submission


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()
