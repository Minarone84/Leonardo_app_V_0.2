from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from leonardo.core.audit_log import AuditLog, InMemoryAuditSink
from leonardo.core.core_runner import CoreRunner
from leonardo.core.task_manager import TaskManager
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import (
    Candle,
    CanonicalOHLCVValidator,
    MaintenanceSidecarReconstructionResult,
    OHLCVDatasetOperationLocks,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader


def _market():
    return canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")


def _candles() -> tuple[Candle, ...]:
    return (
        Candle(60_000, 1, 2, 0.5, 1.5, 10),
        Candle(120_000, 1.5, 2.5, 1, 2, 12),
        Candle(180_000, 2, 3, 1.5, 2.5, 14),
    )


def _write(store: OHLCVStore, *, persistence_status: str = "committed") -> None:
    store.write(
        _market(),
        _candles(),
        source="test_provider",
        persistence_status=persistence_status,
    )


def _maintenance(store: OHLCVStore, sink: InMemoryAuditSink | None = None):
    return OHLCVMaintenanceService(
        store,
        CanonicalOHLCVValidator(),
        audit_log=AuditLog(sink or InMemoryAuditSink()),
        actor_id="tester",
    )


def test_missing_sidecar_reconstruction_returns_to_canonical_validation(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.sidecar_path(_market()).unlink()
    sink = InMemoryAuditSink()
    maintenance = _maintenance(store, sink)

    plan = maintenance.plan_sidecar_reconstruction(
        _market(),
        correlation_id="reconstruct-correlation",
    )

    assert plan.actionable is True
    assert plan.evidence_state == "sidecar_missing"
    assert plan.sidecar_evidence is None
    assert plan.proposed_source == "maintenance_reconstruction"
    assert plan.proposed_persistence_status == "committed"
    assert plan.proposed_validation_status == "unknown"

    store_result = maintenance.reconstruct_sidecar(
        plan,
        correlation_id="reconstruct-correlation",
    )
    reconstructed = store_result.sidecar

    assert store_result.replaced_existing is False
    assert reconstructed.source == "maintenance_reconstruction"
    assert reconstructed.persistence_status == "committed"
    assert reconstructed.validation_status == "unknown"
    assert reconstructed.lineage["sidecar_reconstruction"]["reason"] == "sidecar_missing"
    assert store.read(_market()) == list(_candles())

    validation = maintenance.validate(
        _market(),
        correlation_id="reconstruct-correlation",
    )

    assert validation.accepted is True
    assert validation.sidecar is not None
    assert validation.sidecar.validation_status == "ok"
    assert [event.event_type for event in sink.snapshot()] == [
        "ohlcv.sidecar_reconstruction_planned",
        "ohlcv.sidecar_reconstructed",
        "ohlcv.validation_published",
    ]


def test_invalid_sidecar_is_replaced_without_preserving_invented_provenance(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.sidecar_path(_market()).write_text("{broken", encoding="utf-8")
    maintenance = _maintenance(store)

    plan = maintenance.plan_sidecar_reconstruction(_market())
    assert plan.actionable is True
    assert plan.evidence_state == "sidecar_invalid"
    assert plan.sidecar_evidence is not None

    result = maintenance.reconstruct_sidecar(plan)

    assert result.replaced_existing is True
    assert result.sidecar.source == "maintenance_reconstruction"
    assert result.sidecar.lineage["sidecar_reconstruction"]["replaced_existing"] is True
    assert (
        result.sidecar.lineage["sidecar_reconstruction"]["replaced_sidecar_sha256"]
        == plan.sidecar_evidence.sha256
    )


def test_stale_sidecar_is_reconstructed_for_the_current_csv(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    with store.csv_path(_market()).open("a", encoding="utf-8", newline="") as handle:
        handle.write("240000,2.5,3.5,2,3,16\n")
    maintenance = _maintenance(store)

    plan = maintenance.plan_sidecar_reconstruction(_market())

    assert plan.actionable is True
    assert plan.evidence_state == "sidecar_stale"
    assert "sidecar_hash_stale" in plan.validation_report.issue_codes

    result = maintenance.reconstruct_sidecar(plan)
    validation = maintenance.validate(_market())

    assert result.sidecar.row_count == 4
    assert result.sidecar.last_timestamp_ms == 240_000
    assert validation.accepted is True


def test_reconstruction_rejects_stale_plan_and_preserves_new_sidecar(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.sidecar_path(_market()).unlink()
    maintenance = _maintenance(store)
    plan = maintenance.plan_sidecar_reconstruction(_market())
    replacement = store.finalize(_market(), source="replacement")

    with pytest.raises(ValueError, match="candles.meta.json changed"):
        maintenance.reconstruct_sidecar(plan)

    assert store.read_sidecar(_market()) == replacement


def test_partial_persistence_is_inspect_only_and_cannot_be_promoted(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store, persistence_status="partial")
    maintenance = _maintenance(store)

    report = maintenance.discover()
    plan = maintenance.plan_sidecar_reconstruction(_market())

    assert report.datasets[0].evidence_state == "partial_persistence"
    assert plan.evidence_state == "partial_persistence"
    assert plan.actionable is False
    assert "cannot be promoted" in " ".join(plan.warnings)


def test_orphan_sidecar_is_classified_but_remains_inspect_only(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.csv_path(_market()).unlink()
    maintenance = _maintenance(store)

    report = maintenance.discover()
    plan = maintenance.plan_sidecar_reconstruction(_market())

    assert len(report.datasets) == 1
    assert report.datasets[0].evidence_state == "orphan_sidecar"
    assert report.datasets[0].csv_exists is False
    assert plan.evidence_state == "orphan_sidecar"
    assert plan.actionable is False


def test_malformed_csv_blocks_sidecar_reconstruction(tmp_path: Path) -> None:
    store = OHLCVStore(tmp_path)
    directory = store.dataset_dir(_market())
    directory.mkdir(parents=True)
    store.csv_path(_market()).write_text(
        "ts_ms,open,high,low,close\n60000,1,2,0.5,1.5\n",
        encoding="utf-8",
    )
    maintenance = _maintenance(store)

    plan = maintenance.plan_sidecar_reconstruction(_market())

    assert plan.evidence_state == "sidecar_missing"
    assert plan.actionable is False
    assert "missing_column" in plan.validation_report.issue_codes
    assert "CSV structure is not safe" in " ".join(plan.warnings)


def test_noncanonical_storage_files_are_reported_without_moving_them(tmp_path: Path) -> None:
    wrong = tmp_path / "bybit" / "linear" / "BTCUSDT" / "1m" / "wrong"
    wrong.mkdir(parents=True)
    csv_path = wrong / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n60000,1,2,0.5,1.5,10\n",
        encoding="utf-8",
    )
    maintenance = _maintenance(OHLCVStore(tmp_path))

    report = maintenance.discover()

    assert report.datasets == ()
    assert len(report.rejected) == 1
    assert report.rejected[0].code == "storage_layout_invalid"
    assert csv_path.is_file()


def test_application_reconstruction_invalidates_cache_and_returns_structured_result(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    maintenance = _maintenance(store)
    assert maintenance.validate(_market()).accepted is True
    catalog = AcceptedDatasetCatalog(tmp_path)
    loader = HistoricalDatasetLoader(catalog)
    assert loader.load(_market()).row_count == 3
    store.sidecar_path(_market()).unlink()
    plan = maintenance.plan_sidecar_reconstruction(_market())

    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner,
        maintenance,
        operation_locks=OHLCVDatasetOperationLocks(),
        cache_invalidator=loader.invalidate,
    )
    completed = Event()
    results = []

    runner.start()
    try:
        application.submit_sidecar_reconstruction(
            plan,
            result_callback=lambda result: (results.append(result), completed.set()),
        )
        assert completed.wait(4.0)
    finally:
        runner.shutdown()

    task_result = results[0]
    assert task_result.status == "completed"
    assert isinstance(task_result.value, MaintenanceSidecarReconstructionResult)
    assert task_result.value.accepted is True
    assert task_result.value.cache_invalidated is True
    assert loader.cache_size == 0
    assert catalog.list_accepted()[0].market_id == _market()


def test_confirmed_reconstruction_finishes_honestly_if_cancelled_after_start(
    tmp_path: Path,
) -> None:
    store = OHLCVStore(tmp_path)
    _write(store)
    store.sidecar_path(_market()).unlink()
    maintenance = _maintenance(store)
    plan = maintenance.plan_sidecar_reconstruction(_market())
    original_reconstruct = maintenance.reconstruct_sidecar
    started = Event()
    release = Event()

    def slow_reconstruct(reconstruction_plan, *, correlation_id=None):
        started.set()
        assert release.wait(4.0)
        return original_reconstruct(
            reconstruction_plan,
            correlation_id=correlation_id,
        )

    maintenance.reconstruct_sidecar = slow_reconstruct  # type: ignore[method-assign]
    runner = CoreRunner(TaskManager())
    application = OHLCVMaintenanceApplicationService(
        runner,
        maintenance,
        operation_locks=OHLCVDatasetOperationLocks(),
    )
    completed = Event()
    results = []

    runner.start()
    try:
        submission = application.submit_sidecar_reconstruction(
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
    assert isinstance(results[0].value, MaintenanceSidecarReconstructionResult)
    assert results[0].value.accepted is True
    assert store.sidecar_path(_market()).is_file()
