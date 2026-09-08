from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, current_thread
import time

from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.research import (
    ResearchStudyApplicationService,
    ResearchStudyService,
    StudyExecutionRequest,
    StudySaveAttempt,
)

from tests.research_test.test_study_execution import (
    accepted_context,
    apply_attempt,
    prepare,
    research_service,
)


def _save_attempt(study) -> StudySaveAttempt:
    return StudySaveAttempt(
        session_id=study.session_id,
        generation=study.generation,
        request_id="save-" + study.study_id,
        study_id=study.study_id,
        market_id=study.market_id,
        dataset_fingerprint=study.dataset_fingerprint,
    )


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_application_runs_calculation_in_core_worker_and_cleans_bookkeeping(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    runner = CoreRunner(TaskManager())
    application = ResearchStudyApplicationService(runner, domain)
    completed = Event()
    results: list[TaskResult] = []
    worker_names: list[str] = []
    real = __import__(
        "leonardo.research.study_execution", fromlist=["calculate_financial_tool"]
    ).calculate_financial_tool

    def recording(*args, **kwargs):
        worker_names.append(current_thread().name)
        return real(*args, **kwargs)

    monkeypatch.setattr("leonardo.research.study_execution.calculate_financial_tool", recording)
    runner.start()
    try:
        application.submit_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("sma", {"period": 3}),
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(3.0)
        assert results[0].status == "completed"
        assert worker_names[0].startswith("LeonardoWorker")
        assert application._cancellations == {}
    finally:
        runner.shutdown()


def test_application_cancellation_prevents_result_publication(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    runner = CoreRunner(TaskManager())
    application = ResearchStudyApplicationService(runner, domain)
    started = Event()
    release = Event()
    completed = Event()
    results: list[TaskResult] = []
    real = __import__(
        "leonardo.research.study_execution", fromlist=["calculate_financial_tool"]
    ).calculate_financial_tool

    def delayed(*args, **kwargs):
        started.set()
        release.wait(3.0)
        return real(*args, **kwargs)

    monkeypatch.setattr("leonardo.research.study_execution.calculate_financial_tool", delayed)
    runner.start()
    try:
        submission = application.submit_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("sma", {"period": 3}),
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert started.wait(2.0)
        assert application.cancel(submission.task_id)
        release.set()
        assert completed.wait(3.0)
        assert results[0].status == "cancelled"
        assert application._cancellations == {}
        assert artifacts.list_artifacts(dataset.market_id) == ()
    finally:
        release.set()
        runner.shutdown()


def test_cancel_before_persistence_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    study = prepare(domain, dataset, "sma", parameters={"period": 3})
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = ResearchStudyApplicationService(runner, domain)
    resolving = Event()
    release = Event()
    worker_settled = Event()
    result_ready = Event()
    results: list[TaskResult] = []
    real = domain._durable_source_refs

    def delayed(*args, **kwargs):
        resolving.set()
        release.wait(3.0)
        try:
            return real(*args, **kwargs)
        finally:
            worker_settled.set()

    monkeypatch.setattr(domain, "_durable_source_refs", delayed)
    runner.start()
    try:
        submission = application.submit_save(
            _save_attempt(study),
            dataset,
            study,
            (study,),
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert resolving.wait(2.0)
        assert application.cancel(submission.task_id) is True
        release.set()
        assert worker_settled.wait(2.0)
        assert result_ready.wait(3.0)
        assert results[0].status == "cancelled"
        assert artifacts.list_artifacts(dataset.market_id) == ()
        assert artifacts.list_recipes(dataset.market_id) == ()
    finally:
        release.set()
        runner.shutdown()


def test_cancel_after_persistence_start_returns_false_and_completes(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    study = prepare(domain, dataset, "sma", parameters={"period": 3})
    runner = CoreRunner(TaskManager())
    application = ResearchStudyApplicationService(runner, domain)
    persistence_started = Event()
    release = Event()
    result_ready = Event()
    results: list[TaskResult] = []
    real = artifacts.save_calculation

    def delayed(*args, **kwargs):
        persistence_started.set()
        release.wait(3.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(artifacts, "save_calculation", delayed)
    runner.start()
    try:
        submission = application.submit_save(
            _save_attempt(study),
            dataset,
            study,
            (study,),
            result_callback=lambda result: (results.append(result), result_ready.set()),
        )
        assert persistence_started.wait(2.0)
        assert application.cancel(submission.task_id) is False
        release.set()
        assert result_ready.wait(3.0)
        assert results[0].status == "completed"
        assert len(artifacts.list_artifacts(dataset.market_id)) == 1
        assert application._cancellations == {}
    finally:
        release.set()
        runner.shutdown()


def test_delayed_result_dispatcher_does_not_delay_terminal_cleanup(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = ResearchStudyApplicationService(runner, domain)
    queued: list[Callable[[], None]] = []
    delivered: list[TaskResult] = []
    runner.start()
    try:
        submission = application.submit_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("sma", {"period": 3}),
            result_callback=delivered.append,
            callback_dispatcher=queued.append,
        )
        assert _wait_until(
            lambda: manager.get_snapshot(submission.task_id).status == "completed"
        )
        assert _wait_until(lambda: application._cancellations == {})
        assert delivered == []
        for callback in tuple(queued):
            callback()
        assert len(delivered) == 1
        assert delivered[0].status == "completed"
    finally:
        runner.shutdown()


def test_failure_and_cancellation_cleanup_precede_external_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    domain = research_service(tmp_path, artifacts)
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = ResearchStudyApplicationService(runner, domain)
    queued: list[Callable[[], None]] = []

    def failing(*_args, **_kwargs):
        raise RuntimeError("expected failure")

    monkeypatch.setattr("leonardo.research.study_execution.calculate_financial_tool", failing)
    runner.start()
    try:
        failed = application.submit_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("sma", {"period": 3}),
            result_callback=lambda _result: None,
            callback_dispatcher=queued.append,
        )
        assert _wait_until(lambda: manager.get_snapshot(failed.task_id).status == "failed")
        assert _wait_until(lambda: application._cancellations == {})
        assert len(queued) == 1
        queued.clear()

        started = Event()
        release = Event()

        def delayed_failure(*_args, **_kwargs):
            started.set()
            release.wait(3.0)
            raise RuntimeError("cancelled worker")

        monkeypatch.setattr(
            "leonardo.research.study_execution.calculate_financial_tool", delayed_failure
        )
        cancelled = application.submit_calculation(
            apply_attempt(dataset),
            dataset,
            (),
            StudyExecutionRequest("sma", {"period": 3}),
            result_callback=lambda _result: None,
            callback_dispatcher=queued.append,
        )
        assert started.wait(2.0)
        assert application.cancel(cancelled.task_id) is True
        release.set()
        assert _wait_until(
            lambda: manager.get_snapshot(cancelled.task_id).status == "cancelled"
        )
        assert _wait_until(lambda: application._cancellations == {})
        assert len(queued) == 1
    finally:
        runner.shutdown()
