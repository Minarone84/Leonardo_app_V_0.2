"""Launch a temporary-data OHLCV source-invalid diagnosis smoke."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from leonardo.connection import ProviderCandle
from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data import canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.ohlcv import Candle


class _SourceInvalidSmokeProvider:
    name = "sourceinvalid"

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
        return 180_000

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
            ProviderCandle(120_000, 110.0, 105.0, 100.0, 102.0, 1200.0),
            ProviderCandle(180_000, 102.0, 104.0, 101.0, 103.0, 1400.0),
        )
        lower = 0 if start_ms is None else int(start_ms)
        upper = 2**63 - 1 if end_ms is None else int(end_ms)
        filtered = tuple(row for row in rows if lower <= row.ts_ms <= upper)
        if limit not in (None, 0):
            filtered = filtered[-int(limit) :]
        return filtered


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    with TemporaryDirectory(prefix="leonardo-task1010-") as temp:
        root = Path(temp)
        config = replace(load_default_config(root), audit=AuditConfig(enabled=False))
        app = LeonardoApp(config)
        app.provider_registry.register("sourceinvalid", _SourceInvalidSmokeProvider)
        market = canonicalize_market_id("sourceinvalid", "linear", "BTCUSDT", "1m")
        app.ohlcv_store.write(
            market,
            (
                Candle(60_000, 100.0, 102.0, 99.0, 101.0, 1000.0),
                Candle(120_000, 108.0, 105.0, 100.0, 102.0, 1200.0),
                Candle(180_000, 102.0, 104.0, 101.0, 103.0, 1400.0),
            ),
            source="task1010-fixture",
            persistence_status="committed",
        )

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
            "Task 1010 temporary-data source-invalid diagnosis smoke\n\n"
            "1. In OHLCV Maintenance select sourceinvalid / BTCUSDT / 1m.\n"
            "2. Click Validate Selected and confirm validation becomes error.\n"
            "3. Click Plan Repair and confirm the reviewed range covers anchor 120000.\n"
            "4. Click Execute Repair and approve the confirmation.\n"
            "5. Confirm the final status starts with Provider source remains invalid.\n"
            "6. Confirm the status includes anchors=120000 and no local correction applied.\n"
            "7. Confirm the row remains repaired / error.\n"
            "8. In Research click Refresh and confirm BTCUSDT is unavailable.\n"
            "9. Close the Main Window.\n\n"
            "The fake provider deliberately returns an invalid replacement candle at the exact "
            "reviewed anchor. All data lives in a temporary directory."
        )
        print(instructions, flush=True)
        QTimer.singleShot(
            100,
            lambda: QMessageBox.information(main_window, "Task 1010 Smoke", instructions),
        )
        try:
            return int(qapp.exec())
        finally:
            main_window.close()
            app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
