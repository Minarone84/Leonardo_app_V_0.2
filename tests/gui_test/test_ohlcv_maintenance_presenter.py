from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskProgress, TaskResult, TaskSubmission
from leonardo.data import canonicalize_market_id
from leonardo.gui.presenters import OhlcvMaintenancePresenter
from leonardo.gui.windows import OhlcvMaintenanceWindow
from leonardo.ohlcv import (
    CanonicalValidationReport,
    DatasetDeletionEvidence,
    DatasetDeletionResult,
    MaintenanceDatasetSummary,
    MaintenanceDeletionPlan,
    MaintenanceDeletionResult,
    MaintenanceDiscoveryReport,
    MaintenanceRepairPlan,
    MaintenanceRepairRange,
    MaintenanceRepairRangeResult,
    MaintenanceRepairResult,
    MaintenanceSidecarReconstructionPlan,
    MaintenanceSidecarReconstructionResult,
    MaintenanceValidationResult,
    FileEvidence,
    SidecarReconstructionResult,
    StoredFileEvidence,
    ValidationIssue,
)
from leonardo.storage import OHLCVSidecarV1


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeMaintenanceService:
    def __init__(self, tmp_path: Path) -> None:
        self.market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
        self.tmp_path = tmp_path
        self.validation_status = "unknown"
        self.persistence_status = "committed"
        self.evidence_state = "complete"
        self.sidecar_exists = True
        self.deleted = False
        self.callbacks: dict[str, tuple[object, object, object]] = {}
        self.cancelled: list[str] = []

    def discover(self) -> MaintenanceDiscoveryReport:
        datasets = () if self.deleted else (
            MaintenanceDatasetSummary(
                market_id=self.market,
                csv_path=self.tmp_path / "candles.csv",
                sidecar_path=self.tmp_path / "candles.meta.json",
                csv_exists=True,
                sidecar_exists=self.sidecar_exists,
                persistence_status=self.persistence_status,
                validation_status=self.validation_status,
                row_count=3,
                source="test",
                evidence_state=self.evidence_state,
                issues=(),
                first_timestamp_ms=60_000,
                last_timestamp_ms=180_000,
                csv_size_bytes=256,
                csv_modified_time_ns=123_456_789,
                file_sha256="a" * 64,
                sidecar_schema_version="1.0",
                sidecar_created_at_utc=datetime(2026, 7, 14, 10, 0, tzinfo=UTC),
                sidecar_updated_at_utc=datetime(2026, 7, 14, 11, 0, tzinfo=UTC),
                sidecar_warnings=("provider retry observed",),
                validator_id="canonical_ohlcv_v1",
                validation_error_count=0,
                validation_warning_count=1,
            ),
        )
        return MaintenanceDiscoveryReport(datasets=datasets, rejected=())

    def submit_deletion_plan(self, market, **kwargs) -> TaskSubmission:
        assert market == self.market
        self.callbacks["task-delete-plan"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-delete-plan", "OHLCV deletion plan")

    def submit_deletion(self, plan, **kwargs) -> TaskSubmission:
        assert plan.market_id == self.market
        self.callbacks["task-delete"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-delete", "OHLCV deletion")

    def submit_validation(self, market, **kwargs) -> TaskSubmission:
        assert market == self.market
        self.callbacks["task-validation"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-validation", "OHLCV validation")

    def submit_sidecar_reconstruction_plan(self, market, **kwargs) -> TaskSubmission:
        assert market == self.market
        self.callbacks["task-sidecar-plan"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-sidecar-plan", "OHLCV sidecar reconstruction plan")

    def submit_sidecar_reconstruction(self, plan, **kwargs) -> TaskSubmission:
        assert plan.market_id == self.market
        self.callbacks["task-sidecar-reconstruct"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-sidecar-reconstruct", "OHLCV sidecar reconstruction")

    def submit_repair_plan(self, market, **kwargs) -> TaskSubmission:
        assert market == self.market
        self.callbacks["task-plan"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-plan", "OHLCV repair plan")

    def submit_repair(self, plan, **kwargs) -> TaskSubmission:
        assert plan.market_id == self.market
        self.callbacks["task-repair"] = (
            kwargs["progress_callback"],
            kwargs["result_callback"],
            kwargs["callback_dispatcher"],
        )
        return TaskSubmission("task-repair", "OHLCV repair")

    def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return True

    def emit_deletion_plan(self) -> MaintenanceDeletionPlan:
        _, result_callback, dispatcher = self.callbacks["task-delete-plan"]
        csv_path = self.tmp_path / "candles.csv"
        sidecar_path = self.tmp_path / "candles.meta.json"
        plan = MaintenanceDeletionPlan(
            market_id=self.market,
            evidence=DatasetDeletionEvidence(
                market_id=self.market,
                dataset_dir=self.tmp_path,
                csv=StoredFileEvidence(csv_path, 10, 20, "a" * 64),
                sidecar=StoredFileEvidence(sidecar_path, 11, 21, "b" * 64),
            ),
            message="Delete the reviewed dataset.",
        )
        dispatcher(
            lambda: result_callback(
                TaskResult("task-delete-plan", "completed", value=plan)
            )
        )
        return plan

    def emit_deletion_success(self, plan: MaintenanceDeletionPlan) -> None:
        _, result_callback, dispatcher = self.callbacks["task-delete"]
        self.deleted = True
        store_result = DatasetDeletionResult(
            market_id=self.market,
            dataset_dir=self.tmp_path,
            csv_path=self.tmp_path / "candles.csv",
            sidecar_path=self.tmp_path / "candles.meta.json",
            csv_deleted=True,
            sidecar_deleted=True,
            removed_directories=(self.tmp_path,),
            cleanup_warnings=(),
        )
        result = MaintenanceDeletionResult(
            plan=plan,
            store_result=store_result,
            cache_invalidated=True,
        )
        dispatcher(
            lambda: result_callback(TaskResult("task-delete", "completed", value=result))
        )

    def emit_progress(self, task_id: str, message: str) -> None:
        progress, _, dispatcher = self.callbacks[task_id]
        event = TaskProgress(task_id, message, current=0, total=1)
        dispatcher(lambda: progress(event))

    def emit_validation_success(self, *, publication_changed: bool = True) -> None:
        _, result_callback, dispatcher = self.callbacks["task-validation"]
        self.validation_status = "ok"
        result = _validation_result(self.tmp_path, self.market, persistence="committed")
        if not publication_changed:
            result = MaintenanceValidationResult(
                report=result.report,
                sidecar=result.sidecar,
                sidecar_published=True,
                publication_changed=False,
            )
        dispatcher(
            lambda: result_callback(
                TaskResult("task-validation", "completed", value=result)
            )
        )

    def emit_sidecar_reconstruction_plan(self) -> MaintenanceSidecarReconstructionPlan:
        _, result_callback, dispatcher = self.callbacks["task-sidecar-plan"]
        report = CanonicalValidationReport(
            market_id=self.market,
            csv_path=self.tmp_path / "candles.csv",
            sidecar_path=self.tmp_path / "candles.meta.json",
            status="error",
            row_count=3,
            first_timestamp_ms=60_000,
            last_timestamp_ms=180_000,
            issues=(),
            csv_evidence=FileEvidence(
                path=self.tmp_path / "candles.csv",
                size_bytes=10,
                modified_time_ns=20,
                sha256="a" * 64,
            ),
            sidecar_evidence=None,
            publication_allowed=False,
            publication_blockers=("sidecar_missing",),
        )
        plan = MaintenanceSidecarReconstructionPlan(
            market_id=self.market,
            validation_report=report,
            evidence_state="sidecar_missing",
            actionable=True,
            message="Sidecar reconstruction is available.",
            warnings=(),
            csv_evidence=report.csv_evidence,
            sidecar_evidence=None,
        )
        dispatcher(
            lambda: result_callback(
                TaskResult("task-sidecar-plan", "completed", value=plan)
            )
        )
        return plan

    def emit_sidecar_reconstruction_success(
        self,
        plan: MaintenanceSidecarReconstructionPlan,
    ) -> None:
        _, result_callback, dispatcher = self.callbacks["task-sidecar-reconstruct"]
        self.sidecar_exists = True
        self.evidence_state = "complete"
        self.validation_status = "ok"
        validation = _validation_result(self.tmp_path, self.market, persistence="committed")
        result = MaintenanceSidecarReconstructionResult(
            plan=plan,
            store_result=SidecarReconstructionResult(
                market_id=self.market,
                sidecar=validation.sidecar,
                replaced_existing=False,
            ),
            validation=validation,
            cache_invalidated=True,
        )
        dispatcher(
            lambda: result_callback(
                TaskResult("task-sidecar-reconstruct", "completed", value=result)
            )
        )

    def emit_plan(self) -> MaintenanceRepairPlan:
        _, result_callback, dispatcher = self.callbacks["task-plan"]
        report = _report(self.tmp_path, self.market, status="warning")
        plan = MaintenanceRepairPlan(
            market_id=self.market,
            validation_report=report,
            actionable=True,
            message="1 provider-redownload range is available.",
            ranges=(
                MaintenanceRepairRange(
                    start_ts_ms=120_000,
                    end_ts_ms=120_000,
                    reason="missing interval",
                    issue_codes=("timeframe_gap",),
                    coverage_anchor_ts_ms=(120_000,),
                    estimated_bars=1,
                ),
            ),
            warnings=(),
            csv_evidence=None,
            sidecar_evidence=None,
        )
        dispatcher(lambda: result_callback(TaskResult("task-plan", "completed", value=plan)))
        return plan

    def emit_repair_success(self, plan: MaintenanceRepairPlan) -> None:
        _, result_callback, dispatcher = self.callbacks["task-repair"]
        self.validation_status = "ok"
        self.persistence_status = "repaired"
        validation = _validation_result(self.tmp_path, self.market, persistence="repaired")
        repair = MaintenanceRepairResult(
            plan=plan,
            outcome="repaired_ok",
            range_results=(
                MaintenanceRepairRangeResult(
                    repair_range=plan.ranges[0],
                    fetched_rows=1,
                    downloaded_first_ts_ms=120_000,
                    downloaded_last_ts_ms=120_000,
                    total_rows_after=3,
                    file_path=self.tmp_path / "candles.csv",
                ),
            ),
            validation=validation,
            repaired_sidecar=validation.sidecar,
            warnings=(),
        )
        dispatcher(
            lambda: result_callback(TaskResult("task-repair", "completed", value=repair))
        )


    def emit_repair_source_invalid(self, plan: MaintenanceRepairPlan) -> None:
        _, result_callback, dispatcher = self.callbacks["task-repair"]
        self.validation_status = "error"
        self.persistence_status = "repaired"
        sidecar = OHLCVSidecarV1(
            market_id=self.market,
            file_sha256="a" * 64,
            row_count=3,
            first_timestamp_ms=60_000,
            last_timestamp_ms=180_000,
            source="test",
            persistence_status="repaired",
            validation_status="error",
        )
        report = CanonicalValidationReport(
            market_id=self.market,
            csv_path=self.tmp_path / "candles.csv",
            sidecar_path=self.tmp_path / "candles.meta.json",
            status="error",
            row_count=3,
            first_timestamp_ms=60_000,
            last_timestamp_ms=180_000,
            issues=(
                ValidationIssue(
                    "error",
                    "open_outside_range",
                    "open is outside [low, high]",
                    row_number=3,
                    column="open",
                    timestamp_ms=120_000,
                ),
            ),
            csv_evidence=None,
            sidecar_evidence=None,
            publication_allowed=True,
            publication_blockers=(),
        )
        validation = MaintenanceValidationResult(
            report=report,
            sidecar=sidecar,
            sidecar_published=True,
            publication_changed=True,
        )
        repair = MaintenanceRepairResult(
            plan=plan,
            outcome="source_invalid",
            range_results=(
                MaintenanceRepairRangeResult(
                    repair_range=plan.ranges[0],
                    fetched_rows=1,
                    downloaded_first_ts_ms=120_000,
                    downloaded_last_ts_ms=120_000,
                    total_rows_after=3,
                    file_path=self.tmp_path / "candles.csv",
                ),
            ),
            validation=validation,
            repaired_sidecar=sidecar,
            warnings=("No local correction was applied.",),
            source_invalid=True,
            source_invalid_anchors=(120_000,),
        )
        dispatcher(
            lambda: result_callback(TaskResult("task-repair", "completed", value=repair))
        )


def _report(tmp_path: Path, market, *, status: str) -> CanonicalValidationReport:
    return CanonicalValidationReport(
        market_id=market,
        csv_path=tmp_path / "candles.csv",
        sidecar_path=tmp_path / "candles.meta.json",
        status=status,
        row_count=3,
        first_timestamp_ms=60_000,
        last_timestamp_ms=180_000,
        issues=(),
        csv_evidence=None,
        sidecar_evidence=None,
        publication_allowed=True,
        publication_blockers=(),
    )


def _validation_result(tmp_path: Path, market, *, persistence: str) -> MaintenanceValidationResult:
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256="a" * 64,
        row_count=3,
        first_timestamp_ms=60_000,
        last_timestamp_ms=180_000,
        source="test",
        persistence_status=persistence,
        validation_status="ok",
    )
    return MaintenanceValidationResult(
        report=_report(tmp_path, market, status="ok"),
        sidecar=sidecar,
        sidecar_published=True,
        publication_changed=True,
    )


def test_presenter_discovers_validates_and_refreshes(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    try:
        datasets = window.table_for_id("datasets")
        assert datasets.rowCount() == 1
        assert datasets.item(0, 2).text() == "BTCUSDT"
        assert datasets.item(0, 5).text() == "unknown"
        assert window.button_for_id("validate").isEnabled()
        assert window.button_for_id("plan_repair").isEnabled()
        assert window.button_for_id("delete").isEnabled()
        assert not window.button_for_id("execute_repair").isEnabled()

        evidence = window.table_for_id("evidence")
        evidence_values = {
            evidence.item(row, 0).text(): evidence.item(row, 1).text()
            for row in range(evidence.rowCount())
        }
        assert evidence_values["First timestamp UTC"] == "1970-01-01T00:01:00+00:00"
        assert evidence_values["Last timestamp UTC"] == "1970-01-01T00:03:00+00:00"
        assert evidence_values["CSV size"] == "256 bytes"
        assert evidence_values["CSV SHA-256"] == "a" * 64
        assert evidence_values["Sidecar schema"] == "1.0"
        assert evidence_values["Canonical validator"] == "canonical_ohlcv_v1"
        assert evidence_values["Validation counts"] == "errors=0; warnings=1"
        assert evidence_values["Sidecar warnings"] == "provider retry observed"

        window.button_for_id("validate").click()
        assert presenter.active_task_id == "task-validation"
        assert window.button_for_id("cancel").isEnabled()
        service.emit_progress("task-validation", "Validating")
        QCoreApplication.processEvents()
        assert window.status_text() == "Validating"

        service.emit_validation_success()
        QCoreApplication.processEvents()
        assert presenter.active_task_id is None
        assert datasets.item(0, 5).text() == "ok"
        assert window.status_text().startswith("Accepted")
        assert window.button_for_id("validate").isEnabled()
        assert notifications == [service.market]
    finally:
        window.close()


def test_presenter_plans_confirms_executes_and_refreshes_repair(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    monkeypatch.setattr(window, "confirm_repair", lambda _summary: True)
    try:
        window.button_for_id("plan_repair").click()
        assert presenter.active_task_id == "task-plan"
        plan = service.emit_plan()
        QCoreApplication.processEvents()
        assert notifications == []

        assert presenter.repair_plan == plan
        assert window.table_for_id("repair").rowCount() == 1
        assert window.button_for_id("execute_repair").isEnabled()

        window.button_for_id("execute_repair").click()
        assert presenter.active_task_id == "task-repair"
        service.emit_repair_success(plan)
        QCoreApplication.processEvents()

        datasets = window.table_for_id("datasets")
        assert presenter.active_task_id is None
        assert datasets.item(0, 4).text() == "repaired"
        assert datasets.item(0, 5).text() == "ok"
        assert window.status_text().startswith("Repair accepted")
        assert not window.button_for_id("execute_repair").isEnabled()
        assert notifications == [service.market]
    finally:
        window.close()


def test_presenter_reports_source_invalid_provider_repair(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    monkeypatch.setattr(window, "confirm_repair", lambda _summary: True)
    try:
        window.button_for_id("plan_repair").click()
        plan = service.emit_plan()
        QCoreApplication.processEvents()

        window.button_for_id("execute_repair").click()
        service.emit_repair_source_invalid(plan)
        QCoreApplication.processEvents()

        datasets = window.table_for_id("datasets")
        assert presenter.active_task_id is None
        assert datasets.item(0, 4).text() == "repaired"
        assert datasets.item(0, 5).text() == "error"
        assert window.status_text().startswith("Provider source remains invalid")
        assert "anchors=120000" in window.status_text()
        assert "no local correction applied" in window.status_text()
        assert not window.button_for_id("execute_repair").isEnabled()
        assert notifications == [service.market]
    finally:
        window.close()


def test_presenter_confirms_deletes_and_removes_dataset_row(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    monkeypatch.setattr(window, "confirm_deletion", lambda **_kwargs: True)
    try:
        assert window.button_for_id("delete").isEnabled()
        window.button_for_id("delete").click()
        assert presenter.active_task_id == "task-delete-plan"

        plan = service.emit_deletion_plan()
        QCoreApplication.processEvents()
        assert presenter.active_task_id == "task-delete"
        assert not window.button_for_id("cancel").isEnabled()

        service.emit_deletion_success(plan)
        QCoreApplication.processEvents()
        assert presenter.active_task_id is None
        assert window.table_for_id("datasets").rowCount() == 0
        assert window.status_text().startswith("Deleted")
        assert not window.button_for_id("delete").isEnabled()
        assert notifications == [service.market]
    finally:
        window.close()


def test_presenter_confirms_reconstructs_sidecar_and_refreshes(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    service.evidence_state = "sidecar_missing"
    service.sidecar_exists = False
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    monkeypatch.setattr(
        window,
        "confirm_sidecar_reconstruction",
        lambda **_kwargs: True,
    )
    try:
        assert window.button_for_id("reconstruct_sidecar").isEnabled()
        window.button_for_id("reconstruct_sidecar").click()
        assert presenter.active_task_id == "task-sidecar-plan"

        plan = service.emit_sidecar_reconstruction_plan()
        QCoreApplication.processEvents()
        assert presenter.active_task_id == "task-sidecar-reconstruct"
        assert not window.button_for_id("cancel").isEnabled()

        service.emit_sidecar_reconstruction_success(plan)
        QCoreApplication.processEvents()

        datasets = window.table_for_id("datasets")
        assert presenter.active_task_id is None
        assert datasets.item(0, 5).text() == "ok"
        evidence = window.table_for_id("evidence")
        evidence_values = {
            evidence.item(row, 0).text(): evidence.item(row, 1).text()
            for row in range(evidence.rowCount())
        }
        assert evidence_values["Evidence state"] == "complete"
        assert window.status_text().startswith("Sidecar created and accepted")
        assert not window.button_for_id("reconstruct_sidecar").isEnabled()
        assert notifications == [service.market]
    finally:
        window.close()


def test_presenter_does_not_notify_for_unchanged_failed_or_cancelled_validation(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    notifications = []
    presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        window,
        service,
        on_canonical_ohlcv_evidence_changed=notifications.append,
    )
    try:
        window.button_for_id("validate").click()
        service.emit_validation_success(publication_changed=False)
        QCoreApplication.processEvents()

        for status in ("failed", "cancelled"):
            window.button_for_id("validate").click()
            _, result_callback, dispatcher = service.callbacks["task-validation"]
            dispatcher(
                lambda status=status: result_callback(
                    TaskResult("task-validation", status, error_message=status)
                )
            )
            QCoreApplication.processEvents()

        assert notifications == []
    finally:
        window.close()
