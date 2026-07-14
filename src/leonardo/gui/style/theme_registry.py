"""Deterministic GUI theme registry."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from leonardo.gui.style.theme_loader import DEFAULT_THEME_ID, THEME_PROFILE_PATH, load_theme
from leonardo.gui.style.theme_tokens import GuiTheme, ThemeValidationError


class GuiThemeRegistry:
    """
    Resolve GUI theme profiles by stable theme identifier.

    The registry is an explicit mapping from theme ID to static profile path. It
    does not discover packages, scan directories, import plugin modules, or
    mutate GUI metadata.
    """

    def __init__(
        self,
        theme_paths: Mapping[str, Path | str],
        *,
        default_theme_id: str = DEFAULT_THEME_ID,
    ) -> None:
        if not theme_paths:
            raise ValueError("theme_paths must not be empty")
        self._theme_paths = MappingProxyType(
            {str(theme_id): Path(path) for theme_id, path in theme_paths.items()}
        )
        if default_theme_id not in self._theme_paths:
            raise ValueError(f"default theme is not registered: {default_theme_id}")
        self._default_theme_id = default_theme_id

    @property
    def default_theme_id(self) -> str:
        """Return the active default theme identifier."""

        return self._default_theme_id

    def available_theme_ids(self) -> tuple[str, ...]:
        """Return registered theme identifiers in deterministic order."""

        return tuple(sorted(self._theme_paths))

    def load_theme(self, theme_id: str) -> GuiTheme:
        """Load a registered theme by stable identifier."""

        if theme_id not in self._theme_paths:
            raise KeyError(f"Unknown GUI theme: {theme_id}")
        theme = load_theme(self._theme_paths[theme_id])
        if theme.theme_id != theme_id:
            raise ThemeValidationError(
                f"theme ID mismatch: expected {theme_id}, got {theme.theme_id}"
            )
        return theme

    def load_default_theme(self) -> GuiTheme:
        """Load the active default GUI theme."""

        return self.load_theme(self._default_theme_id)


def build_theme_registry() -> GuiThemeRegistry:
    """Return the bundled GUI theme registry."""

    return GuiThemeRegistry({DEFAULT_THEME_ID: THEME_PROFILE_PATH})
