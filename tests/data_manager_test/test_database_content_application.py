from __future__ import annotations

from pathlib import Path
from threading import Event

from leonardo.core.app import LeonardoApp
from leonardo.core.core_runner import TaskResult

from tests.data_manager_test.test_creation_workflow import (
    _advance_same_source,
    _leaf,
    _materialize,
)
from tests.data_manager_test.test_seed_only_database_application import (
    _application,
    _completed,
    _create_seed_only_database,
    _settled,
)


def test_database_content_plan_execute_and_restart_use_core(tmp_path: Path) -> None:
    app, application = _application(tmp_path)
    try:
        _seed, database = _create_seed_only_database(application, "Content")
        result = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        plan = _completed(
            application.submit_plan_database_artifact_addition,
            database.database_id,
            result.root_logical_artifact_ids,
        )
        published = _completed(
            application.submit_execute_database_content_addition, plan
        )
        assert published.previous_revision_id == database.revision_id
        assert len(app.task_manager.snapshots()) >= 2
    finally:
        app.shutdown()

    restarted = LeonardoApp(app.config)
    restarted.startup()
    restarted.start_core_runtime()
    try:
        loaded = _completed(
            restarted.data_manager_service.submit_load_database_revision,
            database.database_id,
        )
        assert loaded.manifest == published
    finally:
        restarted.shutdown()


def test_collection_plan_and_failed_execution_settle_once(tmp_path: Path) -> None:
    app, application = _application(tmp_path)
    try:
        _seed, database = _create_seed_only_database(application, "Collection")
        result = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        collection = app.data_manager_domain.create_artifact_collection(
            result, "Features"
        )
        plan = _completed(
            application.submit_plan_database_collection_addition,
            database.database_id,
            collection.collection_id,
        )
        published = _completed(
            application.submit_execute_database_content_addition, plan
        )
        assert published.collection_sources[0].revision_id == collection.revision_id

        _submission, failed = _settled(
            application.submit_execute_database_content_addition, plan
        )
        assert failed.status == "failed"
        assert len(app.data_manager_domain.list_database_revisions(database.database_id)) == 2
    finally:
        app.shutdown()


def test_content_cancellation_settles_without_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, application = _application(tmp_path)
    entered = Event()
    release = Event()
    try:
        _seed, database = _create_seed_only_database(application, "Cancelled")
        result = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        plan = _completed(
            application.submit_plan_database_artifact_addition,
            database.database_id,
            result.root_logical_artifact_ids,
        )
        original = app.data_manager_domain.execute_database_content_addition

        def delayed(current_plan, **options):
            entered.set()
            assert release.wait(10.0)
            return original(current_plan, **options)

        monkeypatch.setattr(
            app.data_manager_domain,
            "execute_database_content_addition",
            delayed,
        )
        settled = Event()
        received: list[TaskResult] = []
        submission = application.submit_execute_database_content_addition(
            plan,
            result_callback=lambda result: (received.append(result), settled.set()),
        )
        assert entered.wait(10.0)
        assert application.cancel(submission.task_id)
        release.set()
        assert settled.wait(10.0)
        assert received[0].status in {"cancelled", "failed"}
        assert len(app.data_manager_domain.list_database_revisions(database.database_id)) == 1
    finally:
        release.set()
        app.shutdown()


def test_stale_reviewed_plan_fails_once_through_core_without_publication(
    tmp_path: Path,
) -> None:
    app, application = _application(tmp_path)
    try:
        _seed, database = _create_seed_only_database(application, "Stale")
        result = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        logical_id = result.root_logical_artifact_ids[0]
        plan = _completed(
            application.submit_plan_database_artifact_addition,
            database.database_id,
            (logical_id,),
        )
        _advance_same_source(
            app.data_manager_domain,
            app.data_manager_domain._artifacts,
            logical_id,
        )
        before_task_ids = {
            item.task_id for item in app.task_manager.snapshots()
        }

        submission, settled = _settled(
            application.submit_execute_database_content_addition,
            plan,
        )

        assert settled.task_id == submission.task_id
        assert settled.status == "failed"
        assert "changed after Preview" in (settled.error_message or "")
        new_tasks = tuple(
            item
            for item in app.task_manager.snapshots()
            if item.task_id not in before_task_ids
        )
        assert len(new_tasks) == 1
        assert new_tasks[0].task_id == submission.task_id
        assert new_tasks[0].status == "failed"
        assert len(
            app.data_manager_domain.list_database_revisions(database.database_id)
        ) == 1
    finally:
        app.shutdown()
