from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.gui.data_manager.reconciliation import (
    DataManagerReconciliationCoordinator,
    schedule_post_show_reconciliation,
)


def test_window_reconciliation_runs_on_open_skips_busy_and_stops() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    calls: list[str] = []
    busy = [False]
    coordinator = DataManagerReconciliationCoordinator(
        refresh_when_opened=lambda: calls.append("open"),
        refresh_on_timer=lambda: calls.append("timer"),
        is_busy=lambda: busy[0],
    )
    coordinator.start()
    assert calls == ["open"]
    assert coordinator.active
    coordinator._on_timeout()
    busy[0] = True
    coordinator._on_timeout()
    assert calls == ["open", "timer"]
    coordinator.stop()
    assert not coordinator.active


def test_post_show_reconciliation_is_forced_once_per_service() -> None:
    app = QApplication.instance() or QApplication([])
    calls: list[bool] = []
    service = SimpleNamespace(
        submit_reconcile_status=lambda *, force: calls.append(force)
    )
    context = SimpleNamespace(data_manager_service=service)
    assert schedule_post_show_reconciliation(context)
    assert not schedule_post_show_reconciliation(context)
    QCoreApplication.processEvents()
    assert calls == [True]
    del app
