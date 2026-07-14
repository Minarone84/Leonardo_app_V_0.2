"""Launch the Task 0070 Research price/volume workspace with deterministic accepted OHLCV data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.ohlcv import OHLCVStore
from leonardo.storage import OHLCVSidecarV1


def _write_dataset(root: Path, rows: int = 12_000) -> None:
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    store = OHLCVStore(root)
    store.dataset_dir(market).mkdir(parents=True, exist_ok=True)
    csv_path = store.csv_path(market)
    lines = ["ts_ms,open,high,low,close,volume\n"]
    price = 42_000.0
    for index in range(rows):
        ts_ms = (index + 1) * 60_000
        wave = ((index % 120) - 60) * 0.7
        open_price = price
        close_price = price + wave * 0.08 + (4.0 if index % 2 == 0 else -3.0)
        high = max(open_price, close_price) + 12.0 + (index % 7)
        low = min(open_price, close_price) - 11.0 - (index % 5)
        lines.append(
            f"{ts_ms},{open_price:.4f},{high:.4f},{low:.4f},"
            f"{close_price:.4f},{1000 + index % 400}\n"
        )
        price = close_price
    csv_path.write_text("".join(lines), encoding="utf-8", newline="")
    sidecar = OHLCVSidecarV1(
        market_id=market,
        file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        row_count=rows,
        first_timestamp_ms=60_000,
        last_timestamp_ms=rows * 60_000,
        source="task0069-visual-smoke",
        persistence_status="committed",
        validation_status="ok",
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    store.sidecar_path(market).write_text(
        json.dumps(sidecar.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    with TemporaryDirectory(prefix="leonardo-research-0069-") as temp:
        root = Path(temp)
        config = replace(
            load_default_config(root),
            audit=AuditConfig(enabled=False),
        )
        _write_dataset(config.paths.historical_data_dir)
        app = LeonardoApp(config)
        app.startup()
        app.start_core_runtime()
        qapp = QApplication.instance() or QApplication([])
        apply_theme_stylesheet(qapp, load_default_theme())
        composition = GuiCompositionRoot(app.context)
        main_window = composition.create_main_window()
        main_window.show()
        main_window.action_for_id("main_window.open_research_suite").trigger()

        def show_volume_when_ready() -> None:
            window = composition.research_suite_window
            if window is None or window.status_text() != "Chart ready":
                QTimer.singleShot(50, show_volume_when_ready)
                return
            volume_button = window.button_for_id("research_suite.button.toggle_volume")
            if volume_button.isEnabled() and not window.volume_visible:
                volume_button.click()

        def open_when_ready() -> None:
            window = composition.research_suite_window
            if window is None or window.selected_market_id() is None:
                QTimer.singleShot(50, open_when_ready)
                return
            window.button_for_id("research_suite.button.open_chart").click()
            QTimer.singleShot(50, show_volume_when_ready)

        QTimer.singleShot(50, open_when_ready)
        try:
            return int(qapp.exec())
        finally:
            main_window.close()
            app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
