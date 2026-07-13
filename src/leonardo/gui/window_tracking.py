"""Qt event-filter adapter for the Core WindowRegistry."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from leonardo.core.window_registry import WindowRegistry


class GuiWindowTracker(QObject):
    def __init__(
        self,
        window: QWidget,
        *,
        window_id: str,
        title: str,
        window_type: str,
        registry: WindowRegistry,
    ) -> None:
        super().__init__(window)
        if not isinstance(window, QWidget):
            raise TypeError("window must be a QWidget")
        if not isinstance(registry, WindowRegistry):
            raise TypeError("registry must be a WindowRegistry")
        self._window = window
        self._window_id = window_id
        self._registry = registry
        self._registry.register_window(
            window_id,
            title=title,
            window_type=window_type,
        )
        window.installEventFilter(self)

    @property
    def window_id(self) -> str:
        return self._window_id

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window:
            if event.type() == QEvent.Type.Show:
                self._registry.open_window(self._window_id)
            elif event.type() in {QEvent.Type.WindowActivate, QEvent.Type.FocusIn}:
                try:
                    self._registry.focus_window(self._window_id)
                except RuntimeError:
                    pass
            elif event.type() == QEvent.Type.Close:
                try:
                    self._registry.request_window_close(self._window_id)
                except KeyError:
                    pass
                self._registry.close_window(self._window_id)
        return super().eventFilter(watched, event)
