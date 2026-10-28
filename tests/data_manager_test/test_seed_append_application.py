from __future__ import annotations

from dataclasses import replace
from threading import Event

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config

from tests.data_manager_test.test_seed_only_database_application import _application, _completed
from tests.data_manager_test.test_seed_append_workflow import _seed_tree
from tests.data_manager_test.test_nan_snapshot_updates import _tree
from tests.data_manager_test.test_update_workflow import MARKET, _append


def test_real_core_preview_execute_restart_without_cascade(tmp_path):
    app, application = _application(tmp_path)
    historical = tmp_path / "historical_data"
    try:
        _append(historical, rows=96)
        seed = _completed(application.submit_create_database_seed, MARKET, "Core Seed")
        database = _completed(application.submit_execute_seed_only_database_creation,
                              _completed(application.submit_plan_seed_only_database_creation, seed.seed_id, "Old Core Database"))
        databases = _tree(app.data_manager_domain.creation_store.root_dir / "databases")
        _append(historical, rows=104)
        before = _tree(historical)
        seed_before = _seed_tree(app.data_manager_domain)
        plan = _completed(application.submit_plan_database_seed_append, seed.seed_id)
        assert plan.previous_row_count == 96 and plan.appended_row_count == 8
        assert _seed_tree(app.data_manager_domain) == seed_before
        result = _completed(application.submit_execute_database_seed_append, plan)
        assert result == plan.seed and result.row_count == 104
        assert result.seed_id == seed.seed_id and result.created_at_utc == seed.created_at_utc
        assert _tree(historical) == before
        assert _tree(app.data_manager_domain.creation_store.root_dir / "databases") == databases
        assert _completed(application.submit_load_database_revision, database.database_id).manifest == database
        unchanged = _seed_tree(app.data_manager_domain)
        current = _completed(application.submit_plan_database_seed_append, seed.seed_id)
        assert current.appended_row_count == 0
        assert _completed(application.submit_execute_database_seed_append, current) == result
        assert _seed_tree(app.data_manager_domain) == unchanged
    finally:
        app.shutdown()
    restarted = LeonardoApp(replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False)))
    restarted.startup()
    restarted.start_core_runtime()
    try:
        assert _completed(restarted.data_manager_service.submit_load_database_seed, seed.seed_id) == result
        assert restarted.data_manager_domain.creation_store.load_seed_values(seed.seed_id) == plan.values_csv
        assert _completed(restarted.data_manager_service.submit_load_database_revision, database.database_id).manifest == database
        assert _tree(historical) == before
    finally:
        restarted.shutdown()


def test_real_core_cancel_before_publication_fence(tmp_path, monkeypatch):
    app, application = _application(tmp_path)
    entered, release, settled = Event(), Event(), Event()
    try:
        historical = tmp_path / "historical_data"
        _append(historical, rows=96)
        seed = _completed(application.submit_create_database_seed, MARKET, "Cancelled append")
        _append(historical, rows=104)
        plan = _completed(application.submit_plan_database_seed_append, seed.seed_id)
        before = _seed_tree(app.data_manager_domain)
        source = _tree(historical)
        original = app.data_manager_domain.execute_database_seed_append
        def delayed(plan, **options):
            entered.set()
            assert release.wait(10.0)
            return original(plan, **options)
        monkeypatch.setattr(app.data_manager_domain, "execute_database_seed_append", delayed)
        results = []
        submission = application.submit_execute_database_seed_append(
            plan, result_callback=lambda result: (results.append(result), settled.set()),
        )
        assert entered.wait(10.0)
        assert application.cancel(submission.task_id)
        release.set()
        assert settled.wait(10.0)
        assert results[0].status in {"cancelled", "failed"}
        assert _seed_tree(app.data_manager_domain) == before
        assert _tree(historical) == source
        assert app.data_manager_domain.load_database_seed(seed.seed_id) == seed
    finally:
        release.set()
        app.shutdown()
