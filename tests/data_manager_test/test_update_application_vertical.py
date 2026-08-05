from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event
import time

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerArtifactMaterializationRequest,
    DataManagerOperationError,
)
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.recipes import build_portable_recipe

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_update_workflow import _publish_modified


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _completed(submit, *args, **kwargs):
    settled = Event()
    received: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        received.append(result)
        settled.set()

    submit(*args, **kwargs, result_callback=receive)
    assert settled.wait(10.0), submit.__name__
    assert received[0].status == "completed", received[0]
    return received[0].value


def _recipe():
    parameters = dict(resolve_parameters("sma", {"period": 3}))
    return build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters=parameters,
        output_names=resolve_output_names("sma", parameters),
    )


def test_explicit_reconciliation_stops_cooperatively_on_shutdown(
    tmp_path: Path, monkeypatch
) -> None:
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    started = Event()
    exited = Event()
    callbacks = []

    def reconcile(*, force=False, cancellation_requested=None):
        assert force is True
        assert cancellation_requested is not None
        callbacks.append(cancellation_requested)
        started.set()
        while not cancellation_requested():
            time.sleep(0.001)
        exited.set()
        raise DataManagerOperationError("Data Manager reconciliation cancelled")

    monkeypatch.setattr(
        app.data_manager_domain, "reconcile_update_status", reconcile
    )
    app.startup()
    app.start_core_runtime()
    app.data_manager_service.submit_reconcile_status(force=True)
    assert started.wait(2.0)
    app.shutdown()
    assert exited.wait(2.0)
    assert callbacks[0]() is True
    assert app.status == "stopped"
    assert not app.core_runner.is_running


def test_real_application_update_append_restart_and_rebuild(tmp_path: Path) -> None:
    historical = tmp_path / "historical_data"
    _accepted_dataset(historical, market=MARKET, rows=96)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    recipe = _recipe()
    app.portable_recipe_store.save_recipe(recipe)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    try:
        request = DataManagerArtifactMaterializationRequest(
            MARKET, (recipe.recipe_id,)
        )
        materialization = _completed(
            application.submit_execute_artifact_materialization,
            _completed(application.submit_plan_artifact_materialization, request),
        )
        collection = _completed(
            application.submit_create_artifact_collection,
            materialization,
            "SMA",
        )
        seed = _completed(
            application.submit_create_database_seed,
            MARKET,
            "Research database",
        )
        database = _completed(
            application.submit_build_database_revision,
            seed.seed_id,
            collection.collection_id,
        )
        _accepted_dataset(historical, market=MARKET, rows=104)
        stale = _completed(application.submit_reconcile_status, force=True)
        assert stale.collections[0].status == "MEMBERS_REQUIRE_UPDATE"
        artifact_result = _completed(
            application.submit_execute_artifact_collection_update,
            _completed(
                application.submit_plan_artifact_collection_update,
                collection.collection_id,
            ),
        )
        appended = _completed(
            application.submit_execute_database_append,
            _completed(
                application.submit_plan_database_update, database.database_id
            ),
        )
        assert appended.database_revision.previous_revision_id == database.revision_id
        artifact_revision_id = artifact_result.collection_revision.revision_id
    finally:
        app.shutdown()

    restarted = LeonardoApp(config)
    restarted.startup()
    restarted.start_core_runtime()
    application = restarted.data_manager_service
    try:
        current = application.latest_reconciliation_snapshot()
        assert current.collections[0].revision_id == artifact_revision_id
        assert current.collections[0].status == "CURRENT"
        assert current.databases[0].status == "CURRENT"

        _publish_modified(historical, rows=104, mutate_row=20)
        changed = _completed(application.submit_reconcile_status, force=True)
        assert changed.databases[0].status == "WAITING_FOR_ARTIFACT_UPDATE"
        _completed(
            application.submit_execute_artifact_collection_update,
            _completed(
                application.submit_plan_artifact_collection_update,
                collection.collection_id,
            ),
        )
        rebuild_plan = _completed(
            application.submit_plan_database_update, database.database_id
        )
        assert rebuild_plan.mode == "REBUILD_REQUIRED"
        rebuilt = _completed(
            application.submit_execute_database_rebuild, rebuild_plan
        )
        assert len(
            _completed(
                application.submit_list_database_revisions, database.database_id
            )
        ) == 3
        assert rebuilt.reconciliation_snapshot.databases[0].status == "CURRENT"
    finally:
        restarted.shutdown()
