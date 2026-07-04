"""Developer-only explicit GUI launch helper for Leonardo V2."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from leonardo.gui.app_entry import run_gui_app_from_settings_base


GuiAppEntryCallable = Callable[..., int]


def main(
    argv: Sequence[str] | None = None,
    app_entry: GuiAppEntryCallable = run_gui_app_from_settings_base,
) -> int:
    """
    Run the GUI through the app-entry helper using an explicit settings base.

    This helper is intentionally developer-only. It is not installed as a
    package entry point and does not define a production settings path policy.
    """

    args = _build_parser().parse_args(argv)
    return int(app_entry(settings_base_dir=args.settings_base_dir))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dev_launch_gui",
        description="Launch the Leonardo V2 GUI for local development.",
    )
    parser.add_argument(
        "--settings-base-dir",
        required=True,
        type=Path,
        help="Explicit settings base directory for GUI persisted overrides.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
