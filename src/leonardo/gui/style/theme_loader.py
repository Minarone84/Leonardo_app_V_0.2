"""Load GUI theme profiles from static data files."""

from __future__ import annotations

import json
from pathlib import Path

from leonardo.gui.style.theme_tokens import GuiTheme, ThemeValidationError, theme_from_mapping


DEFAULT_THEME_ID = "leonardo_jarvish_cockpit"
THEME_PROFILE_PATH = Path(__file__).resolve().parent / "themes" / (
    f"{DEFAULT_THEME_ID}.json"
)


def load_theme(path: Path | str = THEME_PROFILE_PATH) -> GuiTheme:
    """
    Load and validate one GUI theme profile.

    The loader reads static JSON only. It does not import Core services, mutate
    GUI metadata, construct Qt widgets, or apply stylesheets.
    """

    source_path = Path(path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ThemeValidationError("theme profile JSON root must be an object")
    return theme_from_mapping(data)


def load_default_theme() -> GuiTheme:
    """Load the current default GUI theme profile."""

    theme = load_theme(THEME_PROFILE_PATH)
    if theme.theme_id != DEFAULT_THEME_ID:
        raise ThemeValidationError(
            f"default theme ID mismatch: expected {DEFAULT_THEME_ID}, got {theme.theme_id}"
        )
    return theme
