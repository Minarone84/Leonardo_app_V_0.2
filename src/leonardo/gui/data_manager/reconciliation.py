"""GUI lifecycle scheduling for Data Manager reconciliation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class DataManagerReconciliationCoordinator(QObject):
    """Own the one-shot Data Manager reconciliation trigger used on open."""

    def __init__(
        self,
        *,
        refresh_when_opened: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._refresh_when_opened = refresh_when_opened
        self._started = False

    @property
    def active(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._refresh_when_opened()

    def stop(self) -> None:
        self._started = False


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
