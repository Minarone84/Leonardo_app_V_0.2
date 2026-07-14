from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

from leonardo.connection import ProviderCandle
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskResult
from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import DownloadBatchRequest
from leonardo.research import DatasetCatalogReport, HistoricalDataset


class _WorkflowProvider:
    name = "workflow"

    def __init__(self) -> None:
        self.repair_enabled = False

    def supported_markets(self) -> set[str]:
        return {"linear"}

    def supported_timeframes(self, market: str) -> set[str]:
        assert market == "linear"
        return {"1m"}

    def max_historical_ohlcv_limit(self, market: str) -> int:
        assert market == "linear"
        return 1000

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_server_time_ms(self) -> int:
        return 240_000

    async def oldest_historical_ohlcv_ts_ms(self, **_kwargs) -> int:
        return 60_000

    async def fetch_ohlcv_historical(
        self,
        *,
        symbol: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
        **_kwargs,
    ) -> tuple[ProviderCandle, ...]:
        rows = (
            ProviderCandle(60_000, 1.0, 2.0, 0.5, 1.5, 10.0),
            ProviderCandle(120_000, 1.5, 2.5, 1.0, 2.0, 12.0),
            ProviderCandle(180_000, 2.0, 3.0, 1.5, 2.5, 14.0),
        )
        if symbol == "GAPUSDT" and not self.repair_enabled:
            rows = (rows[0], rows[2])
        lower = 0 if start_ms is None else int(start_ms)
        upper = 2**63 - 1 if end_ms is None else int(end_ms)
        filtered = tuple(row for row in rows if lower <= row.ts_ms <= upper)
        if limit not in (None, 0):
            filtered = filtered[-int(limit) :]
        return filtered


def _request(symbol: str) -> DownloadBatchRequest:
    return DownloadBatchRequest(
        exchange="workflow",
        market_type="linear",
        symbol=symbol,
        timeframes=("1m",),
        start_ms=60_000,
        end_ms=180_000,
        limit=1000,
    )


def _await_submission(submit, timeout: float = 5.0) -> TaskResult:
    finished = Event()
    results: list[TaskResult] = []

    def on_result(result: TaskResult) -> None:
        results.append(result)
        finished.set()

    submit(result_callback=on_result)
    assert finished.wait(timeout), "Core task did not settle before timeout"
    assert len(results) == 1
    return results[0]


def test_composed_download_maintenance_repair_and_research_workflow(tmp_path: Path) -> None:
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    provider = _WorkflowProvider()
    app.provider_registry.register("workflow", lambda: provider)
    app.startup()
    app.start_core_runtime()

    accepted_market = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    repair_market = canonicalize_market_id("workflow", "linear", "GAPUSDT", "1m")
    try:
        download = _await_submission(
            lambda **callbacks: app.historical_download_service.submit_download(
                _request("BTCUSDT"), **callbacks
            )
        )
        assert download.status == "completed"
        assert app.ohlcv_store.read_sidecar(accepted_market).validation_status == "unknown"

        catalog_before = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_catalog(**callbacks)
        )
        assert isinstance(catalog_before.value, DatasetCatalogReport)
        assert catalog_before.value.accepted == ()

        validation = _await_submission(
            lambda **callbacks: app.ohlcv_maintenance_service.submit_validation(
                accepted_market, **callbacks
            )
        )
        assert validation.status == "completed"
        assert validation.value.accepted is True
        assert app.ohlcv_store.read_sidecar(accepted_market).validation_status == "ok"

        catalog_after = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_catalog(**callbacks)
        )
        assert [item.market_id for item in catalog_after.value.accepted] == [accepted_market]

        loaded = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_load(
                accepted_market, **callbacks
            )
        )
        assert isinstance(loaded.value, HistoricalDataset)
        assert loaded.value.row_count == 3

        gap_download = _await_submission(
            lambda **callbacks: app.historical_download_service.submit_download(
                _request("GAPUSDT"), **callbacks
            )
        )
        assert gap_download.status == "completed"
        assert app.ohlcv_store.read_sidecar(repair_market).validation_status == "unknown"

        gap_validation = _await_submission(
            lambda **callbacks: app.ohlcv_maintenance_service.submit_validation(
                repair_market, **callbacks
            )
        )
        assert gap_validation.value.report.status == "warning"
        assert gap_validation.value.accepted is False

        rejected_catalog = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_catalog(**callbacks)
        )
        assert [item.market_id for item in rejected_catalog.value.accepted] == [accepted_market]

        plan_result = _await_submission(
            lambda **callbacks: app.ohlcv_maintenance_service.submit_repair_plan(
                repair_market, **callbacks
            )
        )
        plan = plan_result.value
        assert plan.actionable is True
        assert [(item.start_ts_ms, item.end_ts_ms) for item in plan.ranges] == [
            (120_000, 120_000)
        ]

        provider.repair_enabled = True
        repair_result = _await_submission(
            lambda **callbacks: app.ohlcv_maintenance_service.submit_repair(
                plan, **callbacks
            )
        )
        assert repair_result.status == "completed"
        assert repair_result.value.outcome == "repaired_ok"
        assert repair_result.value.accepted is True

        final_sidecar = app.ohlcv_store.read_sidecar(repair_market)
        assert final_sidecar.persistence_status == "repaired"
        assert final_sidecar.validation_status == "ok"
        assert final_sidecar.lineage["repair_count"] == 1

        final_catalog = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_catalog(**callbacks)
        )
        assert [item.market_id for item in final_catalog.value.accepted] == [
            accepted_market,
            repair_market,
        ]

        repaired_dataset = _await_submission(
            lambda **callbacks: app.research_dataset_service.submit_load(
                repair_market, **callbacks
            )
        )
        assert isinstance(repaired_dataset.value, HistoricalDataset)
        assert repaired_dataset.value.row_count == 3

        operations = {
            item.metadata.get("operation") for item in app.task_manager.snapshots()
        }
        assert {
            "ohlcv_download",
            "ohlcv_validate",
            "ohlcv_repair_plan",
            "ohlcv_repair",
            "research_dataset_catalog",
            "research_dataset_load",
        } <= operations
    finally:
        app.shutdown()
