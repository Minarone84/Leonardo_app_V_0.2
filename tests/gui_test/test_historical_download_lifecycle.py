from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from leonardo.core.core_runner import TaskProgress, TaskResult, TaskSubmission
from leonardo.data import canonicalize_market_id
from leonardo.gui.presenters.historical_download_presenter import HistoricalDownloadPresenter, _success_recap
from leonardo.gui.windows.historical_download_manager_window import HistoricalDownloadManagerWindow
from leonardo.ohlcv.models import DownloadBatchResult, DownloadItemResult, DownloadPreflightItem, DownloadPreflightResult, DownloadProgressEvent


class _ControlledDownloads:
    def __init__(self):
        self.preflights = []
        self.downloads = []
        self.cancelled = []
        self.cancel_error = False
        self.cancel_result = True

    def submit_preflight(self, request, **callbacks):
        task_id = f"preflight-{len(self.preflights) + 1}"
        self.preflights.append((task_id, request, callbacks))
        return TaskSubmission(task_id, "preflight")

    def submit_download(self, request, **callbacks):
        task_id = f"download-{len(self.downloads) + 1}"
        self.downloads.append((task_id, request, callbacks))
        return TaskSubmission(task_id, "download")

    def cancel(self, task_id):
        if self.cancel_error:
            raise RuntimeError("generated cancellation failure")
        self.cancelled.append(task_id)
        return self.cancel_result


@pytest.fixture
def workflow(tmp_path):
    qapp = QApplication.instance() or QApplication([])
    view = HistoricalDownloadManagerWindow()
    service = _ControlledDownloads()
    notifications = []
    connections = SimpleNamespace(provider_names=lambda: ("workflow",), supported_markets=lambda _p: ("linear",), supported_timeframes=lambda _p, _m: ("1m",))
    presenter = HistoricalDownloadPresenter(view, connections, service, on_ohlcv_evidence_changed=notifications.append)
    view.show()

    def request(symbol="BTCUSDT"):
        view.field_widget_for_id("exchange").setCurrentText("workflow")
        view.field_widget_for_id("market_type").setCurrentText("linear")
        view.field_widget_for_id("symbol").setText(symbol)
        view.timeframe_checkbox_for_value("1m").setChecked(True)
        view.button_for_id("start").click()

    def ready():
        task_id, req, callbacks = service.preflights[-1]
        market = canonicalize_market_id(req.exchange, req.market_type, req.symbol, "1m")
        item = DownloadPreflightItem(market, "new_download", tmp_path/"candles.csv", False, False, False, None, None, 0, (), 60_000, 180_000, 60_000, 180_000, 3, 2, 2, False, True)
        report = DownloadPreflightResult(req.exchange, req.market_type, req.symbol, tuple(req.timeframes), (item,))
        callbacks["callback_dispatcher"](lambda: callbacks["result_callback"](TaskResult(task_id, "completed", report)))
        qapp.processEvents()
        assert presenter.preflight_window.button_for_id("start_download").isEnabled()

    def start(symbol="BTCUSDT"):
        request(symbol)
        ready()
        presenter.preflight_window.button_for_id("start_download").click()
        qapp.processEvents()

    def result(index, status="cancelled"):
        task_id, _req, callbacks = service.downloads[index]
        callbacks["callback_dispatcher"](lambda: callbacks["result_callback"](TaskResult(task_id, status)))
        qapp.processEvents()

    try:
        yield SimpleNamespace(qapp=qapp, view=view, presenter=presenter, service=service, notifications=notifications, request=request, ready=ready, start=start, result=result)
    finally:
        presenter._progress_timer.stop()
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(view, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert not isValid(view)


@pytest.mark.parametrize("reopen", [False, True])
def test_active_download_survives_repeated_request_and_manager_reopen(workflow, reopen):
    w = workflow
    w.start()
    original_request = w.presenter._active_download_request
    w.presenter.task_window.hide()
    if reopen:
        w.view.close()
        w.view.show()
    w.request("ETHUSDT")
    assert len(w.service.preflights) == 1
    assert len(w.service.downloads) == 1
    assert w.presenter.active_task_id == "download-1"
    assert w.presenter._active_download_request is original_request
    assert w.presenter.task_window.isVisible()
    assert w.presenter.task_window.button_for_id("stop").isEnabled()
    w.presenter.task_window.button_for_id("stop").click()
    assert w.service.cancelled == ["download-1"]


def test_confirmation_double_click_does_not_submit_second_download(workflow):
    w = workflow
    w.start()
    w.presenter.preflight_window.button_for_id("start_download").click()
    assert len(w.service.downloads) == 1
    assert w.presenter.active_task_id == "download-1"


def test_old_callbacks_cannot_change_new_download_or_notifications(workflow):
    w = workflow
    w.start()
    first_id, _, callbacks = w.service.downloads[0]
    w.result(0)
    assert w.presenter.active_task_id is None
    w.start("ETHUSDT")
    before = (w.presenter.active_task_id, w.presenter._active_download_request, w.presenter.task_window.status_text(), w.presenter.task_window.progress_log().toPlainText(), w.presenter.task_window.final_recap().toPlainText())
    for kind in ("page_persisted", "item_cancelled", "page_retrying"):
        event = DownloadProgressEvent(kind, "late old-job progress", "1m", 1, 2)
        callbacks["callback_dispatcher"](lambda event=event: callbacks["progress_callback"](TaskProgress(first_id, event.message, details={"download_event": event})))
    callbacks["callback_dispatcher"](lambda: callbacks["progress_callback"](TaskProgress(first_id, "late unstructured progress")))
    callbacks["callback_dispatcher"](lambda: callbacks["result_callback"](TaskResult(first_id, "failed", error_message="old failure")))
    w.qapp.processEvents()
    after = (w.presenter.active_task_id, w.presenter._active_download_request, w.presenter.task_window.status_text(), w.presenter.task_window.progress_log().toPlainText(), w.presenter.task_window.final_recap().toPlainText())
    assert after == before
    assert not w.presenter._progress_timer.isActive()
    assert w.presenter._last_cancel_event is None
    assert w.notifications == []
    assert w.presenter.task_window.button_for_id("stop").isEnabled()


def test_matching_callbacks_notify_and_settle_once(workflow):
    w = workflow
    w.start()
    task_id, request, callbacks = w.service.downloads[0]
    for index in range(2):
        event = DownloadProgressEvent("page_persisted", f"page {index}", "1m", index + 1, 2)
        callbacks["progress_callback"](TaskProgress(task_id, event.message, details={"download_event": event}))
    market = canonicalize_market_id(request.exchange, request.market_type, request.symbol, "1m")
    assert w.notifications == [market]
    assert w.presenter._progress_timer.isActive()
    w.result(0)
    assert not w.presenter._progress_timer.isActive()
    assert w.presenter.active_task_id is None
    assert w.presenter._pending_progress is None
    assert not w.presenter.task_window.button_for_id("stop").isEnabled()
    before = w.view.status_log().toPlainText()
    w.result(0)
    assert w.view.status_log().toPlainText() == before


def test_preflight_close_cancels_only_preflight_and_ignores_late_result(workflow):
    w = workflow
    w.request()
    w.presenter.preflight_window.close()
    assert w.service.cancelled == ["preflight-1"]
    task_id, _, callbacks = w.service.preflights[0]
    callbacks["callback_dispatcher"](lambda: callbacks["result_callback"](TaskResult(task_id, "failed", error_message="late preflight")))
    w.qapp.processEvents()
    assert w.presenter._request is None and w.presenter._preflight is None
    assert w.service.downloads == []


@pytest.mark.parametrize("error", [False, True])
def test_stop_race_and_failure_preserve_current_identity(workflow, error):
    w = workflow
    w.start()
    w.service.cancel_error = error
    w.service.cancel_result = False
    w.presenter.task_window.button_for_id("stop").click()
    assert w.presenter.active_task_id == "download-1"
    assert w.presenter.task_window.button_for_id("stop").isEnabled() is error
    w.result(0)
    assert w.presenter.active_task_id is None


def test_noop_recap_is_distinct_from_mutation_and_legacy_result_construction():
    market = canonicalize_market_id("workflow", "linear", "BTCUSDT", "1m")
    old = DownloadItemResult(market, Path("generated.csv"), 3, 2, 60_000, 120_000, "ok", ())
    assert old.up_to_date is False
    unchanged = replace(old, market_id=canonicalize_market_id("workflow", "linear", "BTCUSDT", "5m"), fetched_rows=0, downloaded_first_ts_ms=None, downloaded_last_ts_ms=None, up_to_date=True)
    recap = _success_recap(DownloadBatchResult(("1m", "5m"), ("1m", "5m"), (old, unchanged)))
    mutated, noop = recap.split("5m:")
    assert "Canonical validation: unknown" in mutated
    assert "evidence unchanged" in noop
    assert "Canonical validation: unknown" not in noop
    assert "accepted" not in noop.lower()
