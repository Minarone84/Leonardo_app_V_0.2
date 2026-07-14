from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from leonardo.core.app import LeonardoApp
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import (
    Candle,
    CanonicalOHLCVValidator,
    MaintenanceDeletionResult,
    OHLCVDatasetOperationLocks,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader


def _market():
    return canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")


def _write(store: OHLCVStore) -> None:
    store.write(
        _market(),
        (
            Candle(60_000, 1, 2, 0.5, 1.5, 10),
            Candle(120_000, 1.5, 2.5, 1, 2, 12),
            Candle(180_000, 2, 3, 1.5, 2.5, 14),
        ),
        source="test",
        persistence_status="committed",
    )


def _maintenance(store: OHLCVStore, sink: InMemoryAuditSink | None = None):
    actual_sink = sink or InMemoryAuditSink()
    return OHLCVMaintenanceService(
        store,
        CanonicalOHLCVValidator(),
        audit_log=AuditLog(actual_sink),
        actor_id="tester",
    )


def test_controlled_deletion_removes_exact_reviewed_files_and_audits(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    sink = InMemoryAuditSink()
    maintenance = _maintenance(store, sink)

    plan = maintenance.plan_deletion(_market(), correlation_id="delete-correlation")

    assert plan.evidence.csv.path == store.csv_path(_market())
    assert plan.evidence.csv.sha256 == store.read_sidecar(_market()).file_sha256
    assert plan.evidence.sidecar is not None
    assert store.csv_path(_market()).is_file()
    assert store.sidecar_path(_market()).is_file()

    result = maintenance.delete_dataset(plan, correlation_id="delete-correlation")

    assert result.completed is True
    assert result.store_result.csv_deleted is True
    assert result.store_result.sidecar_deleted is True
    assert not store.csv_path(_market()).exists()
    assert not store.sidecar_path(_market()).exists()
    assert not store.dataset_dir(_market()).exists()
    assert result.store_result.cleanup_warnings == ()
    assert [event.event_type for event in sink.snapshot()] == [
        "ohlcv.deletion_planned",
        "ohlcv.dataset_deleted",
    ]
    assert sink.snapshot()[-1].correlation_id == "delete-correlation"


def test_deletion_plan_rejects_replaced_csv_and_preserves_dataset(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    maintenance = _maintenance(store)
    plan = maintenance.plan_deletion(_market())
    store.csv_path(_market()).write_text(
        store.csv_path(_market()).read_text(encoding="utf-8")
        + "240000,2.5,3.5,2,3,16\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stale because candles.csv changed"):
        maintenance.delete_dataset(plan)

    assert store.csv_path(_market()).is_file()
    assert store.sidecar_path(_market()).is_file()


def test_deletion_leaves_unrelated_dataset_directory_content_untouched(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    marker = store.dataset_dir(_market()) / "operator-notes.txt"
    marker.write_text("keep", encoding="utf-8")
    maintenance = _maintenance(store)
    plan = maintenance.plan_deletion(_market())

    result = maintenance.delete_dataset(plan)

    assert result.completed is True
    assert marker.read_text(encoding="utf-8") == "keep"
    assert store.dataset_dir(_market()).is_dir()
    assert result.store_result.removed_directories == ()


def test_deletion_supports_missing_sidecar_without_inventing_evidence(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.sidecar_path(_market()).unlink()
    maintenance = _maintenance(store)

    plan = maintenance.plan_deletion(_market())
    result = maintenance.delete_dataset(plan)

    assert plan.evidence.sidecar is None
    assert result.completed is True
    assert result.store_result.sidecar_deleted is True
    assert not store.csv_path(_market()).exists()


def test_application_deletion_invalidates_research_cache_and_catalog(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    maintenance = _maintenance(store)
    validated = maintenance.validate(_market())
    assert validated.accepted is True
    catalog = AcceptedDatasetCatalog(tmp_path)
    loader = HistoricalDatasetLoader(catalog)
    assert loader.load(_market()).row_count == 3
    assert loader.cache_size == 1

    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner,
        maintenance,
        operation_locks=OHLCVDatasetOperationLocks(),
        cache_invalidator=loader.invalidate,
    )
    plan = maintenance.plan_deletion(_market())
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_deletion(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    task_result = results[0]
    assert task_result.status == "completed"
    assert isinstance(task_result.value, MaintenanceDeletionResult)
    assert task_result.value.completed is True
    assert task_result.value.cache_invalidated is True
    assert loader.cache_size == 0
    assert catalog.list_accepted() == ()


def test_composition_shares_one_operation_lock_authority(tmp_path: Path) -> None:
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)

    assert app.historical_download_domain._operation_locks is app.ohlcv_operation_locks
    assert app.ohlcv_maintenance_service._operation_locks is app.ohlcv_operation_locks


def test_confirmed_deletion_finishes_honestly_if_cancellation_arrives_after_start(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    maintenance = _maintenance(store)
    original_delete = maintenance.delete_dataset
    started = Event()
    release = Event()

    def slow_delete(plan, *, correlation_id=None):
        started.set()
        assert release.wait(4.0)
        return original_delete(plan, correlation_id=correlation_id)

    maintenance.delete_dataset = slow_delete  # type: ignore[method-assign]
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner,
        maintenance,
        operation_locks=OHLCVDatasetOperationLocks(),
    )
    plan = maintenance.plan_deletion(_market())
    completed = Event()
    results = []

    runner.start()
    try:
        submission = application.submit_deletion(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert started.wait(4.0)
        assert application.cancel(submission.task_id) is True
        release.set()
        assert completed.wait(4.0)
    finally:
        release.set()
        runner.shutdown()

    assert results[0].status == "completed"
    assert isinstance(results[0].value, MaintenanceDeletionResult)
    assert results[0].value.completed is True
    assert not store.csv_path(_market()).exists()
