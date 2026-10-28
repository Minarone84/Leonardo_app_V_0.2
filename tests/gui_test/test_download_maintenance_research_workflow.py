from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QWidget

from leonardo.connection import ProviderCandle
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskProgress, TaskResult, TaskSubmission
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.presenters.historical_download_presenter import HistoricalDownloadPresenter
from leonardo.gui.windows.historical_download_manager_window import HistoricalDownloadManagerWindow
from leonardo.ohlcv import DownloadBatchRequest, DownloadBatchResult, DownloadProgressEvent
from leonardo.ohlcv.models import DownloadItemResult
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


class _NotificationDownloadService:
    def __init__(self):
        self.submissions = []
        self.cancelled = []

    def submit_download(self, request, **callbacks):
        task_id = f"download-{len(self.submissions) + 1}"
        self.submissions.append((task_id, request, callbacks))
        return TaskSubmission(task_id, "ohlcv_download")

    def cancel(self, task_id):
        self.cancelled.append(task_id)
        return True


@pytest.fixture
def download_notifications():
    qapp = QApplication.instance() or QApplication([])
    service = _NotificationDownloadService()
    connections = SimpleNamespace(
        provider_names=lambda: ("workflow",),
        supported_markets=lambda _provider: ("linear",),
        supported_timeframes=lambda _provider, _market: ("1m", "5m"),
    )
    view = HistoricalDownloadManagerWindow()
    notifications = []
    presenter = HistoricalDownloadPresenter(
        view, connections, service, on_ohlcv_evidence_changed=notifications.append
    )
    presenter._request = DownloadBatchRequest("workflow", "linear", "BTCUSDT", ("1m", "5m"))
    presenter._preflight = SimpleNamespace(can_download=True)
    presenter._start_confirmed_download()
    try:
        yield presenter, service, notifications
    finally:
        presenter._progress_timer.stop()
        presenter.task_window.close()
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def _download_event(service, kind, timeframe="1m", **details):
    task_id, _request, callbacks = service.submissions[-1]
    event = DownloadProgressEvent(kind, kind, timeframe=timeframe, details=details)
    callbacks["progress_callback"](TaskProgress(task_id, kind, details={"download_event": event}))
    return event


def _download_result(service, rows, status="completed"):
    task_id, request, callbacks = service.submissions[-1]
    items = tuple(
        DownloadItemResult(
            canonicalize_market_id(request.exchange, request.market_type, request.symbol, timeframe),
            Path("synthetic.csv"), count, count, 0 if count else None,
            0 if count else None, "ok", (),
        )
        for timeframe, count in rows
    )
    batch = DownloadBatchResult(tuple(request.timeframes), tuple(tf for tf, _count in rows), items)
    callbacks["result_callback"](TaskResult(task_id, status, batch))


def test_historical_download_notification_precedes_throttle_and_deduplicates_per_market(download_notifications):
    presenter, service, notified = download_notifications
    presenter._last_progress_render_at = time.monotonic()
    event = _download_event(service, "page_persisted", page_rows=1)
    market = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    assert notified == [market]
    assert presenter._pending_progress is event
    _download_event(service, "page_persisted", page_rows=2)
    assert notified == [market]
    _download_event(service, "page_persisted", "5m", page_rows=1)
    other = canonicalize_market_id("workflow", "linear", "BTCUSDT", "5m")
    assert notified == [market, other]
    _download_result(service, (("1m", 3), ("5m", 1)))
    assert notified == [market, other]
    presenter._start_confirmed_download()
    _download_event(service, "page_persisted", page_rows=1)
    assert notified == [market, other, market]


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_historical_download_no_persistence_does_not_notify(download_notifications, status):
    _presenter, service, notified = download_notifications
    for kind in ("preflight", "plan_ready", "item_started", "batch_progress"):
        _download_event(service, kind)
    _download_result(service, (("1m", 0), ("5m", 0)), status)
    assert notified == []


def test_historical_download_completed_result_notifies_only_unreported_fetched_rows(download_notifications):
    _presenter, service, notified = download_notifications
    _download_result(service, (("1m", 2), ("5m", 0)))
    assert notified == [canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")]


def test_historical_download_partial_persistence_notifies_before_cancellation(download_notifications):
    presenter, service, notified = download_notifications
    _download_event(service, "page_persisted", page_rows=1)
    assert len(notified) == 1
    presenter.task_window.button_for_id("stop").click()
    assert service.cancelled == [service.submissions[-1][0]]
    _download_event(service, "item_cancelled", pages_written=1, rows_written=1)
    _download_result(service, (), "cancelled")
    assert len(notified) == 1
    assert presenter.task_window.status_text() == "Cancelled"


def test_historical_download_notification_uses_confirmed_request_after_manager_closes(download_notifications):
    presenter, service, notified = download_notifications
    presenter._on_manager_closed()
    assert presenter._request is None
    _download_event(service, "page_persisted", page_rows=1)
    assert notified == [canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")]


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


class _UpdatingWorkflowProvider(_WorkflowProvider):
    def __init__(self):
        self.now_ms = 240_000

    async def get_server_time_ms(self):
        return self.now_ms

    async def fetch_ohlcv_historical(self, *, start_ms=None, end_ms=None, limit=None, **_kwargs):
        rows = tuple(
            ProviderCandle(index * 60_000, 1.0, 2.0, 0.5, 1.5, 10.0)
            for index in range(1, 6)
        )
        lower = 0 if start_ms is None else start_ms
        upper = self.now_ms - 60_000 if end_ms is None else min(end_ms, self.now_ms - 60_000)
        filtered = tuple(row for row in rows if lower <= row.ts_ms <= upper)
        return filtered[-limit:] if limit else filtered


def _prepare_workflow_download(composition, *, symbol="BTCUSDT", start="", end="", limit=""):
    window = composition.historical_download_manager_window
    _select(window.field_widget_for_id("exchange"), "workflow")
    _select(window.field_widget_for_id("market_type"), "linear")
    window.field_widget_for_id("symbol").setText(symbol)
    window.field_widget_for_id("start_ms").setText(start)
    window.field_widget_for_id("end_ms").setText(end)
    window.field_widget_for_id("limit").setText(limit)
    window.timeframe_checkbox_for_value("1m").setChecked(True)
    window.button_for_id("start").click()
    presenter = composition._historical_download_presenter
    _wait_until(lambda: presenter.preflight_window.status_text() == "Ready for confirmation")
    assert presenter.preflight_window.button_for_id("start_download").isEnabled()
    return presenter


@pytest.mark.parametrize("scenario", ["selected_update", "other_update", "up_to_date"])
def test_historical_download_real_first_persistence_reaches_open_data_manager(
    tmp_path: Path, monkeypatch, scenario,
):
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    provider = _UpdatingWorkflowProvider()
    app.provider_registry.register("workflow", lambda: provider)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    market = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    try:
        main.action_for_id("main_window.download_data").trigger()
        composition.connection_suite_window.button_for_id(
            "connection_suite.button.view_historical_download_manager"
        ).click()
        download = _prepare_workflow_download(composition, start="60000", end="180000")

        def download_completed():
            status = download.task_window.status_text()
            assert status not in {"Failed", "Cancelled"}, download.task_window.final_recap().toPlainText()
            return status == "Completed"

        download.preflight_window.button_for_id("start_download").click()
        _wait_until(download_completed)
        assert len(app.ohlcv_store.read(market)) == 3
        assert composition.data_manager_suite_window is None
        assert download._on_ohlcv_evidence_changed.__self__ is composition
        assert download._on_ohlcv_evidence_changed.__func__ is GuiCompositionRoot._notify_data_manager_ohlcv_change

        composition.historical_download_manager_window.button_for_id("ohlcv_maintenance").click()
        maintenance = composition.ohlcv_maintenance_window
        maintenance_presenter = composition.ohlcv_maintenance_presenter
        assert maintenance_presenter._on_canonical_ohlcv_validation_accepted.__self__ is composition
        assert maintenance_presenter._on_canonical_ohlcv_validation_accepted.__func__ is GuiCompositionRoot._notify_data_manager_ohlcv_validation_accepted
        _wait_until(lambda: maintenance.table_for_id("datasets").rowCount() == 1)
        maintenance.select_dataset_index(0)
        maintenance.button_for_id("validate").click()
        _wait_until(lambda: maintenance_presenter.active_task_id is None
                    and app.ohlcv_store.read_sidecar(market).validation_status == "ok")
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        data = composition.data_manager_suite_window
        data_presenter = composition.data_manager_suite_presenter
        _wait_until(lambda: data_presenter._initial_warmup_complete)
        data.button_for_id("data_manager.button.select_dataset").click()
        selector = data.dataset_selector_dialog()
        selector._table.cellWidget(0, 0).findChild(QCheckBox).click()
        selector.button_for_id("data_manager.dataset_selector.button.select").click()
        _wait_until(lambda: data_presenter._active_task_id is None)
        assert data_presenter.selected_market_id == market
        assert data.accepted_target_dataset().accepted
        assert data.button_for_id("data_manager.button.preview_dataset").isEnabled()
        data._catalog_workspace.select_family("Artifacts")
        data._catalog_workspace.create_artifact_button.click()
        _wait_until(lambda: data_presenter._active_task_id is None
                    and data.artifact_creation_dialog() is not None)
        child = data.artifact_creation_dialog()
        assert child.isVisible()
        data._show_dataset_selector()
        assert selector.isVisible()
        original_progress = download._on_task_progress
        persisted_callbacks = []

        def observe_progress(progress):
            original_progress(progress)
            event = (progress.details or {}).get("download_event")
            if isinstance(event, DownloadProgressEvent) and event.kind == "page_persisted":
                persisted_callbacks.append({
                    "suspended": data.dataset_context_suspended,
                    "child_visible": child.isVisible(),
                    "selected_rows": data._selected_dataset_table.rowCount(),
                    "table_running": data._selected_dataset_attention_animation.state() == QAbstractAnimation.State.Running,
                    "status_running": data._operation_surface._attention_animation.state() == QAbstractAnimation.State.Running,
                    "download_still_active": download.active_task_id == progress.task_id,
                    "committed_rows": event.details["total_rows"],
                })

        monkeypatch.setattr(download, "_on_task_progress", observe_progress)
        symbol = "ETHUSDT" if scenario == "other_update" else "BTCUSDT"
        changed_market = canonicalize_market_id("workflow", "linear", symbol, "1m")
        before_csv = app.ohlcv_store.csv_path(market).read_bytes()
        before_sidecar = app.ohlcv_store.sidecar_path(market).read_bytes()
        before_mtimes = (
            app.ohlcv_store.csv_path(market).stat().st_mtime_ns,
            app.ohlcv_store.sidecar_path(market).stat().st_mtime_ns,
        )
        provider.now_ms = 240_000 if scenario == "up_to_date" else 360_000
        _prepare_workflow_download(composition, symbol=symbol, limit="1")
        assert not data.dataset_context_suspended
        assert child.isVisible()
        download.preflight_window.button_for_id("start_download").click()
        _wait_until(download_completed)
        if scenario == "up_to_date":
            assert persisted_callbacks == []
            assert download._notified_ohlcv_markets == set()
            assert not data.dataset_context_suspended
            assert app.ohlcv_store.csv_path(market).read_bytes() == before_csv
            assert app.ohlcv_store.sidecar_path(market).read_bytes() == before_sidecar
            assert (
                app.ohlcv_store.csv_path(market).stat().st_mtime_ns,
                app.ohlcv_store.sidecar_path(market).stat().st_mtime_ns,
            ) == before_mtimes
            assert app.ohlcv_store.read_sidecar(market).validation_status == "ok"
            assert any(item.market_id == market for item in app.accepted_dataset_catalog.list_accepted())
        else:
            assert len(persisted_callbacks) >= 2
            first = persisted_callbacks[0]
            assert first["download_still_active"]
            assert first["committed_rows"] > 0
            assert len(app.ohlcv_store.read(changed_market)) == persisted_callbacks[-1]["committed_rows"]
            assert download._notified_ohlcv_markets == {changed_market}
            if scenario == "selected_update":
                assert first["committed_rows"] > 3
                assert first["suspended"]
                assert not first["child_visible"]
                assert first["selected_rows"] == 1
                assert first["table_running"] and first["status_running"]
                assert data.dataset_context_suspended
                assert not selector.isVisible()
                assert not data._catalog_workspace.create_artifact_button.isEnabled()
                assert data.button_for_id("data_manager.button.refresh").isEnabled()
                assert data.button_for_id("data_manager.button.select_dataset").isEnabled()
                assert app.ohlcv_store.csv_path(market).read_bytes() != before_csv
            else:
                assert not first["suspended"]
                assert first["child_visible"]
                assert not first["table_running"] and not first["status_running"]
                assert data_presenter.selected_market_id == market
                assert not data.dataset_context_suspended
                assert app.ohlcv_store.csv_path(market).read_bytes() == before_csv
        assert composition.data_manager_suite_window is data
        assert composition.data_manager_suite_presenter is data_presenter
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        main.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


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
