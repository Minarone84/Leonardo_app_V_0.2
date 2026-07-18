"""Core-supervised application service for Data Manager operations."""

from __future__ import annotations

from collections.abc import Callable
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
from leonardo.data import MarketId

from .service import DataManagerService


class _CancellationGate:
    def __init__(self) -> None:
        self._cancelled = Event()
        self._destructive_started = False
        self._lock = RLock()

    def request_cancel(self) -> bool:
        with self._lock:
            if self._destructive_started:
                return False
            self._cancelled.set()
            return True

    def begin_destructive(self) -> None:
        with self._lock:
            if self._cancelled.is_set():
                raise RuntimeError("Data Manager operation cancelled before deletion")
            self._destructive_started = True

    def raise_if_cancelled(self, stage: str) -> None:
        if self._cancelled.is_set():
            raise RuntimeError(f"Data Manager operation cancelled before {stage}")

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class DataManagerApplicationService:
    """Run one Data Manager operation through the shared CoreRunner."""

    def __init__(self, core_runner: CoreRunner, service: DataManagerService) -> None:
        if not isinstance(core_runner, CoreRunner):
            raise TypeError("core_runner must be a CoreRunner")
        if not isinstance(service, DataManagerService):
            raise TypeError("service must be a DataManagerService")
        self._runner = core_runner
        self._service = service
        self._cancellations: dict[str, _CancellationGate] = {}
        self._lock = RLock()

    def submit_scan_catalog(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._submit(
            operation="data_manager.scan_catalog",
            task_name="Data Manager catalog scan",
            start_message="Scanning canonical dataset catalog",
            completed_message="Data Manager catalog ready",
            work=lambda _reporter, _gate: self._service.scan_catalog(),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_inspect_market(
        self,
        market_id: MarketId,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.inspect_market",
            task_name=f"Data Manager market inspection {market_id.as_key()}",
            start_message=f"Inspecting {market_id.as_key()}",
            completed_message="Market inspection ready",
            work=lambda _reporter, _gate: self._service.inspect_market(market_id),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_preview_dataset(
        self,
        market_id: MarketId,
        limit: int = 200,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        def work(reporter: ProgressReporter, gate: _CancellationGate):
            def on_progress(current: int, total: int) -> None:
                if not gate.is_cancelled():
                    reporter.report(
                        f"Loading dataset preview {current}/{total}",
                        current=current,
                        total=total,
                    )

            return self._service._preview_dataset(
                market_id,
                limit=limit,
                progress=on_progress,
                cancellation_requested=gate.is_cancelled,
            )

        return self._market_submit(
            market_id,
            operation="data_manager.preview_dataset",
            task_name=f"Data Manager dataset preview {market_id.as_key()}",
            start_message=f"Preparing dataset preview for {market_id.as_key()}",
            completed_message="Dataset preview ready",
            work=work,
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_preview_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        limit: int = 200,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.preview_artifact",
            task_name=f"Data Manager artifact preview {artifact_id}",
            start_message=f"Preparing artifact preview {artifact_id}",
            completed_message="Artifact preview ready",
            work=lambda _reporter, _gate: self._service.preview_artifact(
                market_id, kind, tool_key, artifact_id, limit=limit
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_validate_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.validate_artifact",
            task_name=f"Data Manager artifact validation {artifact_id}",
            start_message=f"Validating artifact {artifact_id}",
            completed_message="Artifact validation ready",
            work=lambda _reporter, _gate: self._service.validate_artifact_current(
                market_id, kind, tool_key, artifact_id
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.delete_artifact",
            task_name=f"Data Manager artifact deletion {artifact_id}",
            start_message=f"Deleting exact artifact {artifact_id}",
            completed_message="Artifact deleted",
            work=lambda _reporter, gate: self._service._delete_artifact(
                market_id,
                kind,
                tool_key,
                artifact_id,
                before_delete=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def submit_delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
        callback_dispatcher: CallbackDispatcher | None = None,
    ) -> TaskSubmission:
        return self._market_submit(
            market_id,
            operation="data_manager.delete_recipe",
            task_name=f"Data Manager recipe deletion {recipe_id}",
            start_message=f"Deleting exact recipe {recipe_id}",
            completed_message="Recipe deleted",
            work=lambda _reporter, gate: self._service._delete_recipe(
                market_id,
                kind,
                tool_key,
                recipe_id,
                before_delete=gate.begin_destructive,
            ),
            progress_callback=progress_callback,
            result_callback=result_callback,
            callback_dispatcher=callback_dispatcher,
        )

    def cancel(self, task_id: str) -> bool:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        with self._lock:
            gate = self._cancellations.get(task_id)
        if gate is None or not gate.request_cancel():
            return False
        return self._runner.cancel(task_id)

    def _market_submit(self, market_id: MarketId, **values) -> TaskSubmission:
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        metadata = dict(values.pop("metadata", {}))
        metadata["market_id"] = market_id.as_key()
        return self._submit(metadata=metadata, **values)

    def _submit(
        self,
        *,
        operation: str,
        task_name: str,
        start_message: str,
        completed_message: str,
        work: Callable[[ProgressReporter, _CancellationGate], object],
        progress_callback: ProgressCallback | None,
        result_callback: ResultCallback | None,
        callback_dispatcher: CallbackDispatcher | None,
        destructive: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> TaskSubmission:
        gate = _CancellationGate()
        finished = Event()
        task_ref: list[str] = []

        def job(reporter: ProgressReporter):
            gate.raise_if_cancelled("execution")
            reporter.report(start_message, current=0, total=None)
            if destructive:
                gate.begin_destructive()
            value = work(reporter, gate)
            if not destructive:
                gate.raise_if_cancelled("publication")
            reporter.report(completed_message, current=1, total=1)
            return value

        def on_result(result: TaskResult) -> None:
            finished.set()
            task_id = task_ref[0] if task_ref else result.task_id
            with self._lock:
                self._cancellations.pop(task_id, None)
            if result_callback is not None:
                result_callback(result)

        submission = self._runner.submit_blocking_job(
            job,
            task_name=task_name,
            progress_callback=progress_callback,
            result_callback=on_result,
            callback_dispatcher=callback_dispatcher,
            allow_duplicate_name=True,
            correlation_id=uuid4().hex,
            metadata={"operation": operation, **dict(metadata or {})},
        )
        task_ref.append(submission.task_id)
        with self._lock:
            if not finished.is_set():
                self._cancellations[submission.task_id] = gate
        return submission
