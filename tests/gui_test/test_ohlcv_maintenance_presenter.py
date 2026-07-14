from __future__ import annotations

import os
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
    MaintenanceDatasetSummary,
    MaintenanceDiscoveryReport,
    MaintenanceValidationResult,
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
        self.progress_callback = None
        self.result_callback = None
        self.dispatcher = None
        self.cancelled: list[str] = []

    def discover(self) -> MaintenanceDiscoveryReport:
        return MaintenanceDiscoveryReport(
            datasets=(
                MaintenanceDatasetSummary(
                    market_id=self.market,
                    csv_path=self.tmp_path / "candles.csv",
                    sidecar_path=self.tmp_path / "candles.meta.json",
                    csv_exists=True,
                    sidecar_exists=True,
                    persistence_status="committed",
                    validation_status=self.validation_status,
                    row_count=3,
                    source="test",
                    issues=(),
                ),
            ),
            rejected=(),
        )

    def submit_validation(self, market, **kwargs) -> TaskSubmission:
        assert market == self.market
        self.progress_callback = kwargs["progress_callback"]
        self.result_callback = kwargs["result_callback"]
        self.dispatcher = kwargs["callback_dispatcher"]
        return TaskSubmission("task-1", "OHLCV validation")

    def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return True

    def emit_progress(self) -> None:
        assert self.progress_callback is not None
        assert self.dispatcher is not None
        event = TaskProgress("task-1", "Validating", current=0, total=1)
        self.dispatcher(lambda: self.progress_callback(event))

    def emit_success(self) -> None:
        assert self.result_callback is not None
        assert self.dispatcher is not None
        self.validation_status = "ok"
        sidecar = OHLCVSidecarV1(
            market_id=self.market,
            file_sha256="a" * 64,
            row_count=3,
            first_timestamp_ms=60_000,
            last_timestamp_ms=180_000,
            source="test",
            persistence_status="committed",
            validation_status="ok",
        )
        report = CanonicalValidationReport(
            market_id=self.market,
            csv_path=self.tmp_path / "candles.csv",
            sidecar_path=self.tmp_path / "candles.meta.json",
            status="ok",
            row_count=3,
            first_timestamp_ms=60_000,
            last_timestamp_ms=180_000,
            issues=(),
            csv_evidence=None,
            sidecar_evidence=None,
            publication_allowed=True,
            publication_blockers=(),
        )
        result = MaintenanceValidationResult(
            report=report,
            sidecar=sidecar,
            sidecar_published=True,
            publication_changed=True,
        )
        task_result = TaskResult("task-1", "completed", value=result)
        self.dispatcher(lambda: self.result_callback(task_result))


def test_presenter_discovers_validates_and_refreshes(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    service = _FakeMaintenanceService(tmp_path)
    window = OhlcvMaintenanceWindow()
    presenter = OhlcvMaintenancePresenter(window, service)  # type: ignore[arg-type]
    try:
        datasets = window.table_for_id("datasets")
        assert datasets.rowCount() == 1
        assert datasets.item(0, 2).text() == "BTCUSDT"
        assert datasets.item(0, 5).text() == "unknown"
        assert window.button_for_id("validate").isEnabled()
        assert not window.button_for_id("repair").isEnabled()

        window.button_for_id("validate").click()
        assert presenter.active_task_id == "task-1"
        assert window.button_for_id("cancel").isEnabled()
        service.emit_progress()
        QCoreApplication.processEvents()
        assert window.status_text() == "Validating"

        service.emit_success()
        QCoreApplication.processEvents()
        assert presenter.active_task_id is None
        assert datasets.item(0, 5).text() == "ok"
        assert window.status_text().startswith("Accepted")
        assert window.button_for_id("validate").isEnabled()
    finally:
        window.close()
