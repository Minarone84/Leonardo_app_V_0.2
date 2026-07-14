"""Launch the interactive Research candlestick visual-smoke surface.

This developer tool uses deterministic in-memory data.  It is not imported by
production composition and is not a Research fallback dataset.
"""

from __future__ import annotations

import math
import sys

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.research import HorizontalViewport, ResidentOHLCVSlice


def _fixture_state() -> CandlestickInteractionState:
    count = 1_200
    timestamps = tuple(1_700_000_000_000 + index * 60_000 for index in range(count))
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    volumes: list[float] = []
    previous_close = 42_000.0
    for index in range(count):
        open_price = previous_close
        movement = 8.0 + math.sin(index / 13.0) * 55.0 + math.sin(index / 47.0) * 30.0
        close_price = open_price + movement
        high_price = max(open_price, close_price) + 25.0 + abs(math.sin(index / 7.0)) * 35.0
        low_price = min(open_price, close_price) - 25.0 - abs(math.cos(index / 9.0)) * 35.0
        opens.append(open_price)
        highs.append(high_price)
        lows.append(low_price)
        closes.append(close_price)
        volumes.append(100.0 + abs(math.sin(index / 11.0)) * 900.0)
        previous_close = close_price

    resident = ResidentOHLCVSlice(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint="visual-smoke-fixture",
        base_index=0,
        end_index_exclusive=count,
        ts_ms=timestamps,
        open=tuple(opens),
        high=tuple(highs),
        low=tuple(lows),
        close=tuple(closes),
        volume=tuple(volumes),
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    return CandlestickInteractionState(
        HorizontalViewport(count, visible_count=500),
        resident,
    )


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Leonardo Light V2 — Task 0068 Price Interaction Smoke")
    layout = QVBoxLayout(window)
    instructions = QLabel(
        "Drag chart: pan. Wheel: horizontal zoom. Move mouse: crosshair. "
        "Disable autoscale, then drag chart vertically or drag price axis "
        "(Shift+axis drag pans; normal axis drag zooms)."
    )
    instructions.setWordWrap(True)
    chart = CandlestickChartWidget()
    chart.set_interaction_state(_fixture_state())
    toggle = QPushButton("Disable autoscale")

    def toggle_autoscale() -> None:
        enabled = not chart.autoscale_enabled
        chart.set_autoscale_enabled(enabled)
        toggle.setText("Disable autoscale" if enabled else "Enable autoscale")

    toggle.clicked.connect(toggle_autoscale)
    layout.addWidget(instructions)
    layout.addWidget(toggle)
    layout.addWidget(chart, 1)
    window.resize(1_200, 760)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
