"""GUI lifecycle scheduling for Data Manager reconciliation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class DataManagerReconciliationCoordinator(QObject):
    """Own the window-local 60-second reconciliation timer."""

    def __init__(
        self,
        *,
        refresh_when_opened: Callable[[], None],
        refresh_on_timer: Callable[[], None],
        is_busy: Callable[[], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._refresh_when_opened = refresh_when_opened
        self._refresh_on_timer = refresh_on_timer
        self._is_busy = is_busy
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._on_timeout)
        self._started = False

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._refresh_when_opened()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_timeout(self) -> None:
        if not self._is_busy():
            self._refresh_on_timer()


def schedule_post_show_reconciliation(context: object) -> bool:
    """Schedule one forced reconciliation for one composed application service."""

    service = getattr(context, "data_manager_service", None)
    submit = getattr(service, "submit_reconcile_status", None)
    if not callable(submit):
        return False
    marker = "_leonardo_post_show_reconciliation_scheduled"
    if bool(getattr(service, marker, False)):
        return False
    setattr(service, marker, True)
    QTimer.singleShot(0, lambda: submit(force=True))
    return True
