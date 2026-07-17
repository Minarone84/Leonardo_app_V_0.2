"""Core-supervised application service for Study Setup and Environment work."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
from leonardo.research.studies import ChartStudy, StudyUserMetadata
from leonardo.research.study_presentation import StudyPresentation
from leonardo.research.study_environment import StudyEnvironmentDraft, StudyEnvironmentV1
from leonardo.research.study_setup_service import ResearchStudySetupService


class ResearchStudySetupApplicationService:
    """Run setup and environment operations through the existing CoreRunner."""

    def __init__(self, core_runner: CoreRunner, service: ResearchStudySetupService) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        if not isinstance(service, ResearchStudySetupService):
            raise TypeError("service must be ResearchStudySetupService")
        self._core_runner = core_runner
        self._service = service
        self._cancellations: dict[str, Event] = {}
        self._lock = RLock()

    def submit_catalog(self, dataset: HistoricalDataset, studies: Sequence[ChartStudy], **callbacks):
        snapshot = tuple(studies)
        return self._submit(
            lambda reporter, cancelled: self._catalog_job(
                reporter, cancelled, dataset, snapshot
            ),
            task_name="Research Study Setup catalog",
            operation="research.study_setup.catalog",
            **callbacks,
        )

    def submit_list_environments(self, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple_job(
                reporter, "Listing Study Environments", self._service.list_environments
            ),
            task_name="Research Study Environment list",
            operation="research.study_setup.environment_list",
            **callbacks,
        )

    def submit_load_environment(self, environment_id: str, **callbacks):
        return self._submit(
            lambda reporter, _cancelled: self._simple_job(
                reporter,
                "Loading Study Environment",
                lambda: self._service.load_environment(environment_id),
            ),
            task_name="Research Study Environment load",
            operation="research.study_setup.environment_load",
            **callbacks,
        )

    def submit_create_environment(self, draft: StudyEnvironmentDraft, **callbacks):
        return self._submit(
            lambda reporter, cancelled: self._publishing_job(
                reporter,
                cancelled,
                "Creating Study Environment",
                lambda: self._service.create_environment(draft),
            ),
            task_name="Research Study Environment create",
            operation="research.study_setup.environment_create",
            **callbacks,
        )

    def submit_save_chart_environment(
        self,
        dataset: HistoricalDataset,
        studies: Sequence[ChartStudy],
        presentations: Sequence[StudyPresentation],
        *,
        display_name: str,
        description: str = "",
        environment_id: str | None = None,
        metadata_overrides: Mapping[str, StudyUserMetadata] | None = None,
        **callbacks,
    ):
        study_snapshot = tuple(studies)
        presentation_snapshot = tuple(presentations)
        overrides = dict(metadata_overrides or {})
        return self._submit(
            lambda reporter, cancelled: self._save_chart_job(
                reporter,
                cancelled,
                dataset,
                study_snapshot,
                presentation_snapshot,
                display_name,
                description,
                environment_id,
                overrides,
            ),
            task_name="Research Study Environment save",
            operation="research.study_setup.environment_save",
            **callbacks,
        )

    def submit_update_environment(
        self, environment_id: str, draft: StudyEnvironmentDraft, **callbacks
    ):
        return self._submit(
            lambda reporter, cancelled: self._publishing_job(
                reporter,
                cancelled,
                "Updating Study Environment",
                lambda: self._service.update_environment(environment_id, draft),
            ),
            task_name="Research Study Environment update",
            operation="research.study_setup.environment_update",
            **callbacks,
        )

    def submit_delete_environment(self, environment_id: str, **callbacks):
        return self._submit(
            lambda reporter, cancelled: self._publishing_job(
                reporter,
                cancelled,
                "Deleting Study Environment",
                lambda: self._service.delete_environment(environment_id),
            ),
            task_name="Research Study Environment delete",
            operation="research.study_setup.environment_delete",
            **callbacks,
        )

    def submit_compatibility(
        self,
        environment: StudyEnvironmentV1,
        dataset: HistoricalDataset,
        **callbacks,
    ):
        return self._submit(
            lambda reporter, cancelled: self._compatibility_job(
                reporter, cancelled, environment, dataset
            ),
            task_name="Research Study Environment compatibility",
            operation="research.study_setup.compatibility",
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
        job: Callable[[ProgressReporter, Event], object],
        *,
        task_name: str,
        operation: str,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
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

    def _catalog_job(self, reporter, cancelled, dataset, studies):
        reporter.report("Building Study Setup catalog", current=0, total=1)
        value = self._service.build_catalog(
            dataset, studies, cancellation_requested=cancelled.is_set
        )
        reporter.report("Study Setup catalog ready", current=1, total=1)
        return value

    def _compatibility_job(self, reporter, cancelled, environment, dataset):
        reporter.report("Checking Study Environment compatibility", current=0, total=1)
        value = self._service.compatibility(
            environment, dataset, cancellation_requested=cancelled.is_set
        )
        reporter.report("Study Environment compatibility ready", current=1, total=1)
        return value

    def _save_chart_job(
        self,
        reporter,
        cancelled,
        dataset,
        studies,
        presentations,
        display_name,
        description,
        environment_id,
        metadata_overrides,
    ):
        reporter.report("Building Study Environment", current=0, total=2)
        draft = self._service.build_environment(
            dataset,
            studies,
            presentations,
            display_name=display_name,
            description=description,
            environment_id=environment_id,
            metadata_overrides=metadata_overrides,
        )
        if cancelled.is_set():
            from leonardo.research.studies import StudyOperationCancelled

            raise StudyOperationCancelled("Study Environment save cancelled before publication")
        reporter.report("Publishing Study Environment", current=1, total=2)
        if environment_id is None:
            value = self._service.create_environment(draft)
        else:
            value = self._service.update_environment(environment_id, draft)
        reporter.report("Study Environment saved", current=2, total=2)
        return value

    @staticmethod
    def _simple_job(reporter, message, callback):
        reporter.report(message, current=0, total=1)
        value = callback()
        reporter.report(f"{message} complete", current=1, total=1)
        return value

    @staticmethod
    def _publishing_job(reporter, cancelled, message, callback):
        reporter.report(message, current=0, total=1)
        if cancelled.is_set():
            from leonardo.research.studies import StudyOperationCancelled

            raise StudyOperationCancelled(f"{message} cancelled before publication")
        value = callback()
        reporter.report(f"{message} complete", current=1, total=1)
        return value


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()
