"""Launch the real Leonardo application with the Data Manager Suite open."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from leonardo.core.app import LeonardoApp
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    market = _market_from_args(args)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    qapplication = QApplication.instance() or QApplication([])
    apply_theme_stylesheet(qapplication, load_default_theme())
    app = LeonardoApp()
    main_window = None
    try:
        app.startup()
        app.start_core_runtime()
        composition = GuiCompositionRoot(app.context)
        main_window = composition.create_main_window()
        main_window.show()
        main_window.action_for_id("main_window.open_data_manager_suite").trigger()
        if market is not None:
            QTimer.singleShot(
                0,
                lambda: composition.data_manager_suite_presenter.focus_market(
                    market, source="dev_launcher"
                ),
            )
        return int(qapplication.exec())
    finally:
        if main_window is not None:
            main_window.close()
        app.shutdown()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch Leonardo with the real Data Manager Suite open."
    )
    parser.add_argument("--exchange")
    parser.add_argument("--market-type")
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe")
    return parser


def _market_from_args(args: argparse.Namespace) -> MarketId | None:
    values = (args.exchange, args.market_type, args.symbol, args.timeframe)
    if not any(values):
        return None
    if not all(values):
        raise ValueError(
            "--exchange, --market-type, --symbol, and --timeframe are required together"
        )
    return canonicalize_market_id(*values)


if __name__ == "__main__":
    raise SystemExit(main())
