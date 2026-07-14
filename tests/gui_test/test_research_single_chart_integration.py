from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.ohlcv import OHLCVStore
from leonardo.storage import OHLCVSidecarV1


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def _write_accepted_dataset(root: Path, rows: int = 800) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = OHLCVStore(root)
    directory = store.dataset_dir(market)
    directory.mkdir(parents=True, exist_ok=True)
    path = store.csv_path(market)
    lines = ["ts_ms,open,high,low,close,volume\n"]
    price = 100.0
    for index in range(rows):
        timestamp = (index + 1) * 60_000
        open_price = price
        close_price = price + (0.5 if index % 2 == 0 else -0.25)
        high = max(open_price, close_price) + 1.0
        low = min(open_price, close_price) - 1.0
        lines.append(
            f"{timestamp},{open_price},{high},{low},{close_price},{1000 + index}\n"
        )
        price = close_price
    path.write_text("".join(lines), encoding="utf-8", newline="")
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        row_count=rows,
        first_timestamp_ms=60_000,
        last_timestamp_ms=rows * 60_000,
        source="task0069-test",
        persistence_status="committed",
        validation_status="ok",
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_composed_research_window_opens_accepted_dataset(tmp_path: Path) -> None:
    qapp = QApplication.instance() or QApplication([])
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    _write_accepted_dataset(config.paths.historical_data_dir)
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    try:
        main.action_for_id("main_window.open_research_suite").trigger()
        window = composition.research_suite_window
        presenter = composition.research_suite_presenter
        assert window is not None
        assert presenter is not None
        _wait_until(lambda: window.selected_market_id() is not None)
        window.button_for_id("research_suite.button.open_chart").click()
        _wait_until(lambda: window.status_text() == "Chart ready")
        assert presenter.session.dataset_count == 800
        assert presenter.session.resident_count == 800
        assert window.chart_widget.interaction_state is not None
        autoscale_button = window.button_for_id(
            "research_suite.button.toggle_autoscale"
        )
        assert autoscale_button.isEnabled() is True
        assert window.chart_widget.autoscale_enabled is True
        autoscale_button.click()
        assert window.chart_widget.autoscale_enabled is False
        assert autoscale_button.text() == "Enable Autoscale"
        autoscale_button.click()
        assert window.chart_widget.autoscale_enabled is True
        assert autoscale_button.text() == "Disable Autoscale"
        volume_button = window.button_for_id("research_suite.button.toggle_volume")
        assert volume_button.isEnabled() is True
        volume_button.click()
        assert window.volume_visible is True
        assert window.chart_workspace.volume_chart.projection is not None
        assert (
            window.chart_workspace.volume_chart.interaction_state
            is window.chart_widget.interaction_state
        )
        assert any(
            item.metadata.get("operation") == "research_dataset_load"
            for item in app.task_manager.snapshots()
        )
        assert any(
            item.metadata.get("operation") == "research_resident_slice"
            for item in app.task_manager.snapshots()
        )
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
        qapp.processEvents()
