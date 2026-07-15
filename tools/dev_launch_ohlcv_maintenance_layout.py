"""Launch a temporary-data OHLCV Maintenance layout and evidence smoke."""

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


def _write_fixture(app: LeonardoApp) -> None:
    valid = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    warning = canonicalize_market_id("bybit", "linear", "ETHUSDT", "1m")
    invalid = canonicalize_market_id("bybit", "linear", "XRPUSDT", "1m")
    missing_sidecar = canonicalize_market_id("bybit", "linear", "SOLUSDT", "5m")

    app.ohlcv_store.write(
        valid,
        (
            Candle(60_000, 100.0, 102.0, 99.0, 101.0, 1000.0),
            Candle(120_000, 101.0, 103.0, 100.0, 102.0, 1200.0),
            Candle(180_000, 102.0, 104.0, 101.0, 103.0, 1400.0),
        ),
        source="task1011-layout-smoke",
        persistence_status="committed",
    )
    app.ohlcv_maintenance_domain.validate(valid)

    app.ohlcv_store.write(
        warning,
        (
            Candle(60_000, 200.0, 202.0, 199.0, 201.0, 900.0),
            Candle(180_000, 202.0, 204.0, 201.0, 203.0, 1100.0),
        ),
        source="task1011-layout-smoke",
        persistence_status="committed",
    )
    app.ohlcv_maintenance_domain.validate(warning)

    app.ohlcv_store.write(
        invalid,
        (Candle(60_000, 305.0, 302.0, 299.0, 301.0, 500.0),),
        source="task1011-layout-smoke",
        persistence_status="committed",
    )
    app.ohlcv_maintenance_domain.validate(invalid)

    app.ohlcv_store.write(
        missing_sidecar,
        (
            Candle(300_000, 50.0, 52.0, 49.0, 51.0, 400.0),
            Candle(600_000, 51.0, 53.0, 50.0, 52.0, 450.0),
        ),
        source="task1011-layout-smoke",
        persistence_status="committed",
    )
    app.ohlcv_store.sidecar_path(missing_sidecar).unlink()


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    with TemporaryDirectory(prefix="leonardo-task1011-") as temp:
        root = Path(temp)
        config = replace(load_default_config(root), audit=AuditConfig(enabled=False))
        app = LeonardoApp(config)
        _write_fixture(app)
        app.startup()
        app.start_core_runtime()
        qapp = QApplication.instance() or QApplication([])
        apply_theme_stylesheet(qapp, load_default_theme())
        composition = GuiCompositionRoot(app.context)
        main_window = composition.create_main_window()
        main_window.show()
        main_window.action_for_id("main_window.ohlcv_maintenance").trigger()

        instructions = (
            "Task 1011 temporary-data Maintenance GUI smoke\n\n"
            "1. Confirm OHLCV Maintenance opens centered at about half the usable screen "
            "width and uses the full usable height without hiding the title bar.\n"
            "2. Confirm the local text is one point larger and remains readable.\n"
            "3. Confirm the upper workspace shows Datasets beside Selected Dataset Evidence.\n"
            "4. Confirm the lower workspace shows Validation Findings beside Repair Plan.\n"
            "5. Confirm actions occupy two tidy rows and the progress bar remains visible.\n"
            "6. Select BTCUSDT and confirm evidence includes UTC timestamps, CSV size, "
            "SHA-256, sidecar schema/times, validator, counts, and warnings.\n"
            "7. Select ETHUSDT, click Validate Selected, then Plan Repair; confirm findings "
            "and repair ranges remain readable in the lower panels.\n"
            "8. Select SOLUSDT and confirm evidence state is sidecar_missing and Rebuild "
            "Sidecar is enabled. Do not execute it for this layout smoke.\n"
            "9. Resize the splitters and window; confirm tables remain usable.\n"
            "10. Close the Main Window.\n\n"
            "All data lives in a temporary directory and is deleted on exit."
        )
        print(instructions, flush=True)
        QTimer.singleShot(
            100,
            lambda: QMessageBox.information(main_window, "Task 1011 Smoke", instructions),
        )
        try:
            return int(qapp.exec())
        finally:
            main_window.close()
            app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
