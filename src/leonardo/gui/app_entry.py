"""Simple GUI application entry point."""

from __future__ import annotations

from pathlib import Path


def run_gui_app_from_settings_base(
    *,
    settings_base_dir: Path | str | None = None,
    config: object | None = None,
    runner=None,
    **_: object,
) -> int:
    """Run Leonardo GUI. Settings base is retained for launcher compatibility only."""

    del settings_base_dir
    if runner is None:
        from leonardo.gui.runner import run_gui_app
        runner = run_gui_app
    return int(runner(config=config))
