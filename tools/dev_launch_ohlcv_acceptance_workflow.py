"""Launch a temporary-data Download → Maintenance → Research acceptance smoke."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from leonardo.connection import ProviderCandle
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme


class _AcceptanceSmokeProvider:
    name = "workflow"

    def supported_markets(self) -> set[str]:
        return {"linear"}

    def supported_timeframes(self, market: str) -> set[str]:
        if market != "linear":
            raise ValueError(f"unsupported market: {market}")
        return {"1m"}

    def max_historical_ohlcv_limit(self, market: str) -> int:
        if market != "linear":
            raise ValueError(f"unsupported market: {market}")
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
            ProviderCandle(60_000, 100.0, 102.0, 99.0, 101.0, 1000.0),
            ProviderCandle(120_000, 101.0, 103.0, 100.0, 102.0, 1200.0),
            ProviderCandle(180_000, 102.0, 104.0, 101.0, 103.0, 1400.0),
        )
        lower = 0 if start_ms is None else int(start_ms)
        upper = 2**63 - 1 if end_ms is None else int(end_ms)
        filtered = tuple(row for row in rows if lower <= row.ts_ms <= upper)
        if limit not in (None, 0):
            filtered = filtered[-int(limit) :]
        return filtered


def _select(combo, value: str) -> None:
    index = combo.findText(value)
    if index < 0:
        raise RuntimeError(f"smoke provider option is missing: {value}")
    combo.setCurrentIndex(index)


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QMessageBox

    with TemporaryDirectory(prefix="leonardo-task1006-") as temp:
        root = Path(temp)
        config = replace(load_default_config(root), audit=AuditConfig(enabled=False))
        app = LeonardoApp(config)
        app.provider_registry.register("workflow", _AcceptanceSmokeProvider)
        app.startup()
        app.start_core_runtime()
        qapp = QApplication.instance() or QApplication([])
        apply_theme_stylesheet(qapp, load_default_theme())
        composition = GuiCompositionRoot(app.context)
        main_window = composition.create_main_window()
        main_window.show()
        main_window.action_for_id("main_window.download_data").trigger()
        connection_window = composition.connection_suite_window
        if connection_window is None:
            raise RuntimeError("Connection Suite did not open")
        connection_window.button_for_id(
            "connection_suite.button.view_historical_download_manager"
        ).click()
        download_window = composition.historical_download_manager_window
        if download_window is None:
            raise RuntimeError("Historical Download Manager did not open")

        exchange = download_window.field_widget_for_id("exchange")
        market = download_window.field_widget_for_id("market_type")
        symbol = download_window.field_widget_for_id("symbol")
        start_ms = download_window.field_widget_for_id("start_ms")
        end_ms = download_window.field_widget_for_id("end_ms")
        if not isinstance(exchange, QComboBox) or not isinstance(market, QComboBox):
            raise RuntimeError("Download provider selectors are unavailable")
        if not all(isinstance(item, QLineEdit) for item in (symbol, start_ms, end_ms)):
            raise RuntimeError("Download request fields are unavailable")
        _select(exchange, "workflow")
        _select(market, "linear")
        symbol.setText("BTCUSDT")
        start_ms.setText("60000")
        end_ms.setText("180000")
        download_window.timeframe_checkbox_for_value("1m").setChecked(True)

        instructions = (
            "Task 1006 temporary-data acceptance smoke\n\n"
            "1. In Historical Download Manager click Start.\n"
            "2. In Preflight click Start Download and wait for Completed.\n"
            "3. Click OHLCV Maintenance, select BTCUSDT and Validate Selected.\n"
            "4. Confirm the dataset status becomes committed / ok.\n"
            "5. From the Main Window open Research Suite, click Refresh, then Open Chart.\n"
            "6. Confirm the chart reaches Chart ready with price and volume controls.\n"
            "7. Close the Main Window.\n\n"
            "All data lives in a temporary directory and is deleted on exit."
        )
        print(instructions, flush=True)
        QTimer.singleShot(
            100,
            lambda: QMessageBox.information(main_window, "Task 1006 Smoke", instructions),
        )
        try:
            return int(qapp.exec())
        finally:
            main_window.close()
            app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
