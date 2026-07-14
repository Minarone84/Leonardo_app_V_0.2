"""Launch a temporary-data OHLCV sidecar reconstruction smoke."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.ohlcv import Candle


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    with TemporaryDirectory(prefix="leonardo-task1009-") as temp:
        root = Path(temp)
        config = replace(load_default_config(root), audit=AuditConfig(enabled=False))
        app = LeonardoApp(config)
        market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
        app.ohlcv_store.write(
            market,
            (
                Candle(60_000, 100.0, 102.0, 99.0, 101.0, 1000.0),
                Candle(120_000, 101.0, 103.0, 100.0, 102.0, 1200.0),
                Candle(180_000, 102.0, 104.0, 101.0, 103.0, 1400.0),
            ),
            source="task1009-smoke",
            persistence_status="committed",
        )
        validation = app.ohlcv_maintenance_domain.validate(market)
        if not validation.accepted:
            raise RuntimeError("Task 1009 smoke fixture did not pass canonical validation")
        app.historical_dataset_loader.load(market)
        if app.historical_dataset_loader.cache_size != 1:
            raise RuntimeError("Task 1009 smoke fixture was not loaded into Research cache")
        app.ohlcv_store.sidecar_path(market).unlink()

        app.startup()
        app.start_core_runtime()
        qapp = QApplication.instance() or QApplication([])
        apply_theme_stylesheet(qapp, load_default_theme())
        composition = GuiCompositionRoot(app.context)
        main_window = composition.create_main_window()
        main_window.show()
        main_window.action_for_id("main_window.open_research_suite").trigger()
        main_window.action_for_id("main_window.ohlcv_maintenance").trigger()

        instructions = (
            "Task 1009 temporary-data sidecar reconstruction smoke\n\n"
            "1. In OHLCV Maintenance select BTCUSDT 1m.\n"
            "2. Confirm Evidence State is sidecar_missing and Rebuild Sidecar is enabled.\n"
            "3. Click Rebuild Sidecar.\n"
            "4. Review the exact CSV and sidecar paths and confirm Yes.\n"
            "5. Confirm the final row shows committed / ok, source "
            "maintenance_reconstruction, and Evidence State complete.\n"
            "6. Confirm the status starts with Sidecar created and accepted.\n"
            "7. Switch to Research Suite, click Refresh, and confirm BTCUSDT remains available.\n"
            "8. Close the Main Window.\n\n"
            "The fixture begins accepted and cached, then its sidecar is removed. This exercises "
            "reconstruction, mandatory post-validation, and Research-cache invalidation. All "
            "files live in a temporary directory."
        )
        print(instructions, flush=True)
        QTimer.singleShot(
            100,
            lambda: QMessageBox.information(main_window, "Task 1009 Smoke", instructions),
        )
        try:
            return int(qapp.exec())
        finally:
            main_window.close()
            app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
