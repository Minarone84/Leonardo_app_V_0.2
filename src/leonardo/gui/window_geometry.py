"""Initial screen-relative geometry for resizable GUI windows."""

from __future__ import annotations

import math

from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget


def apply_initial_window_size(
    window: QWidget,
    *,
    parent: QWidget | None = None,
    width_fraction: float = 1 / 3,
    height_fraction: float = 1 / 2,
) -> None:
    """Resize ``window`` from available screen geometry without fixing its size."""
    if not isinstance(window, QWidget):
        raise TypeError("window must be a QWidget")
    for value, name in (
        (width_fraction, "width_fraction"),
        (height_fraction, "height_fraction"),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a positive finite number")
        if not math.isfinite(float(value)) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")

    screen = _window_screen(window)
    if screen is None and parent is not None:
        if not isinstance(parent, QWidget):
            raise TypeError("parent must be a QWidget or None")
        screen = _window_screen(parent) or parent.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("no available screen for initial window geometry")

    available = screen.availableGeometry()
    window.resize(
        round(available.width() * width_fraction),
        round(available.height() * height_fraction),
    )


def _window_screen(window: QWidget) -> QScreen | None:
    handle = window.windowHandle()
    return None if handle is None else handle.screen()
