"""Developer-only explicit GUI launch helper for Leonardo Light V2."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from leonardo.gui.app_entry import run_gui_app_from_settings_base

GuiAppEntryCallable = Callable[..., int]


def main(
    argv: Sequence[str] | None = None,
    app_entry: GuiAppEntryCallable = run_gui_app_from_settings_base,
) -> int:
    """Run the Light V2 GUI through the normal application entry point."""

    _build_parser().parse_args(argv)
    return int(app_entry())


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="dev_launch_gui",
        description="Launch the Leonardo Light V2 GUI for local development.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
