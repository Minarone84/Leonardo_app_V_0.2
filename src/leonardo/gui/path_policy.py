"""Appearance-settings path helper retained for future simple settings storage."""

from __future__ import annotations

from pathlib import Path


def resolve_appearance_settings_path(base_dir: Path | str) -> Path:
    path = Path(base_dir)
    return path / "appearance.json"
