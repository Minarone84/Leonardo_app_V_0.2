from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QWidget

from leonardo.connection import ProviderCandle
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from tests.gui_test.test_research_single_chart_integration import (
    _open_restored_chart,
)


class _WorkflowProvider:
    name = "workflow"

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
        lower = 0 if start_ms is None else int(start_ms)
        upper = 2**63 - 1 if end_ms is None else int(end_ms)
        filtered = tuple(row for row in rows if lower <= row.ts_ms <= upper)
        if limit not in (None, 0):
            filtered = filtered[-int(limit) :]
        return filtered


def _wait_until(predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def _select(combo: QComboBox, value: str) -> None:
    index = combo.findText(value)
    assert index >= 0, f"missing combo value: {value}"
    combo.setCurrentIndex(index)


def _top_level(qapp: QApplication, object_name: str) -> QWidget:
    for widget in qapp.topLevelWidgets():
        if widget.objectName() == object_name:
            return widget
    raise AssertionError(f"top-level widget not found: {object_name}")


def test_gui_download_validation_and_research_open_use_one_composed_workflow(
    tmp_path: Path,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.provider_registry.register("workflow", _WorkflowProvider)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    market = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    try:
        main.action_for_id("main_window.download_data").trigger()
        connection_window = composition.connection_suite_window
        assert connection_window is not None
        connection_window.button_for_id(
            "connection_suite.button.view_historical_download_manager"
        ).click()

        download_window = composition.historical_download_manager_window
        assert download_window is not None
        exchange = download_window.field_widget_for_id("exchange")
        market_type = download_window.field_widget_for_id("market_type")
        symbol = download_window.field_widget_for_id("symbol")
        start_ms = download_window.field_widget_for_id("start_ms")
        end_ms = download_window.field_widget_for_id("end_ms")
        assert isinstance(exchange, QComboBox)
        assert isinstance(market_type, QComboBox)
        assert isinstance(symbol, QLineEdit)
        assert isinstance(start_ms, QLineEdit)
        assert isinstance(end_ms, QLineEdit)
        _select(exchange, "workflow")
        _select(market_type, "linear")
        symbol.setText("BTCUSDT")
        start_ms.setText("60000")
        end_ms.setText("180000")
        download_window.timeframe_checkbox_for_value("1m").setChecked(True)
        download_window.button_for_id("start").click()

        _wait_until(
            lambda: any(
                widget.objectName() == "ohlcv_download_preflight_window"
                for widget in qapp.topLevelWidgets()
            )
        )
        preflight = _top_level(qapp, "ohlcv_download_preflight_window")
        _wait_until(
            lambda: preflight.status_text() == "Ready for confirmation"
            and preflight.button_for_id("start_download").isEnabled()
        )
        preflight.button_for_id("start_download").click()
        _wait_until(
            lambda: any(
                widget.objectName() == "ohlcv_download_task_window"
                for widget in qapp.topLevelWidgets()
            )
        )
        task_window = _top_level(qapp, "ohlcv_download_task_window")
        _wait_until(lambda: task_window.status_text() == "Completed")
        assert app.ohlcv_store.read_sidecar(market).validation_status == "unknown"

        main.action_for_id("main_window.open_research_suite").trigger()
        research_window = composition.research_suite_window
        research_presenter = composition.research_suite_presenter
        assert research_window is not None
        assert research_presenter is not None
        _wait_until(lambda: research_presenter._active_catalog_task_id is None)
        assert research_window.dataset_summaries == ()

        download_window.button_for_id("ohlcv_maintenance").click()
        maintenance_window = composition.ohlcv_maintenance_window
        maintenance_presenter = composition.ohlcv_maintenance_presenter
        assert maintenance_window is not None
        assert maintenance_presenter is not None
        _wait_until(
            lambda: maintenance_window.table_for_id("datasets").rowCount() == 1
        )
        maintenance_window.select_dataset_index(0)
        maintenance_window.button_for_id("validate").click()
        _wait_until(
            lambda: maintenance_presenter.active_task_id is None
            and app.ohlcv_store.read_sidecar(market).validation_status == "ok"
        )
        assert maintenance_window.status_text().startswith("Accepted")

        research_window.close()
        _wait_until(lambda: composition.research_suite_window is None)
        main.action_for_id("main_window.open_research_suite").trigger()
        research_window = composition.research_suite_window
        research_presenter = composition.research_suite_presenter
        assert research_window is not None
        assert research_presenter is not None
        _wait_until(
            lambda: tuple(
                summary.market_id for summary in research_window.dataset_summaries
            )
            == (market,)
        )
        slot_id = _open_restored_chart(research_window, research_presenter)
        session = research_presenter._workspace_state.session_for(slot_id)
        assert session.dataset_count == 3
        assert session.resident_count == 3

        operations = {
            item.metadata.get("operation") for item in app.task_manager.snapshots()
        }
        assert {
            "ohlcv_preflight",
            "ohlcv_download",
            "ohlcv_validate",
            "research_dataset_catalog",
            "research_dataset_load",
            "research_resident_slice",
        } <= operations
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
