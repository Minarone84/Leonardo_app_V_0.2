"""Adaptive visual shell for up to eight embedded Research charts."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget
from leonardo.gui.widgets.research_workspace_layout import (
    RESEARCH_WORKSPACE_MODES,
    ResearchWorkspaceLayoutPlan,
    build_research_workspace_layout_in_order,
)


class ResearchWorkspaceWidget(QWidget):
    """Own slot widgets, adaptive placement, and visual active selection."""

    active_slot_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("research.workspace")
        self._mode = "scroll_4"
        self._active_slot_id: int | None = None
        self._slots: dict[int, ResearchChartSlotWidget] = {}
        self._attached_order: list[int] = []
        self._detached: set[int] = set()
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("research.workspace.scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().installEventFilter(self)
        self._grid_host = QWidget(self._scroll)
        self._grid_host.setObjectName("research.workspace.grid")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)
        self._scroll.setWidget(self._grid_host)
        self._empty = QLabel("No Research charts", self)
        self._empty.setObjectName("research.workspace.empty")
        self._empty.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._empty)
        layout.addWidget(self._scroll, stretch=1)
        self._relayout()

    @property
    def active_slot_id(self) -> int | None:
        return self._active_slot_id

    @property
    def visualization_mode(self) -> str:
        return self._mode

    @property
    def scroll_area(self) -> QScrollArea:
        return self._scroll

    @property
    def grid_host(self) -> QWidget:
        return self._grid_host

    def add_slot(self, slot_id: int) -> ResearchChartSlotWidget:
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        if slot_id in self._slots:
            raise ValueError(f"Research chart slot {slot_id} already exists")
        if len(self._slots) >= 8:
            raise ValueError("Research workspace already contains eight charts")
        widget = ResearchChartSlotWidget(slot_id, self._grid_host)
        widget.activated.connect(self._request_active_slot)
        self._slots[slot_id] = widget
        self._attached_order.append(slot_id)
        self._relayout()
        return widget

    def remove_slot(self, slot_id: int) -> ResearchChartSlotWidget:
        try:
            widget = self._slots.pop(slot_id)
        except KeyError as error:
            raise KeyError(f"Research chart slot {slot_id} does not exist") from error
        self._grid.removeWidget(widget)
        if slot_id in self._attached_order:
            self._attached_order.remove(slot_id)
        self._detached.discard(slot_id)
        widget.setParent(None)
        widget.deleteLater()
        if self._active_slot_id == slot_id:
            self._active_slot_id = None
        self._relayout()
        return widget

    def slot_widget(self, slot_id: int) -> ResearchChartSlotWidget:
        try:
            return self._slots[slot_id]
        except KeyError as error:
            raise KeyError(f"Research chart slot {slot_id} does not exist") from error

    def slot_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._slots))

    def chart_count(self) -> int:
        return len(self._slots)

    def set_attached_slot_order(self, slot_ids: object) -> None:
        if isinstance(slot_ids, (str, bytes)):
            raise TypeError("slot_ids must be an iterable of integers")
        try:
            supplied = tuple(slot_ids)  # type: ignore[arg-type]
        except TypeError as error:
            raise TypeError("slot_ids must be an iterable of integers") from error
        expected = set(self._slots) - self._detached
        if (
            len(supplied) != len(set(supplied))
            or set(supplied) != expected
            or any(type(slot_id) is not int for slot_id in supplied)
        ):
            raise ValueError(
                "attached slot order must contain every attached slot exactly once"
            )
        self._attached_order = list(supplied)
        self._relayout()

    def set_slot_detached(self, slot_id: int, detached: bool) -> None:
        if type(detached) is not bool:
            raise TypeError("detached must be a boolean")
        widget = self.slot_widget(slot_id)
        if detached:
            if slot_id not in self._detached:
                self._detached.add(slot_id)
                if slot_id in self._attached_order:
                    self._attached_order.remove(slot_id)
                self._grid.removeWidget(widget)
                widget.setParent(None)
        elif slot_id in self._detached:
            self._detached.remove(slot_id)
            self._attached_order.append(slot_id)
            widget.setParent(self._grid_host)
        widget.set_detached(detached)
        self._relayout()

    def attached_slot_ids(self) -> tuple[int, ...]:
        return tuple(self._attached_order)

    def detached_slot_ids(self) -> tuple[int, ...]:
        return tuple(slot_id for slot_id in self._slots if slot_id in self._detached)

    def is_slot_detached(self, slot_id: int) -> bool:
        self.slot_widget(slot_id)
        return slot_id in self._detached

    def set_active_slot(self, slot_id: int | None) -> None:
        if slot_id is not None and slot_id not in self._slots:
            raise KeyError(f"Research chart slot {slot_id} does not exist")
        self._active_slot_id = slot_id
        for current_id, widget in self._slots.items():
            widget.set_active(current_id == slot_id)

    def set_visualization_mode(self, mode: str) -> None:
        if mode not in RESEARCH_WORKSPACE_MODES:
            raise ValueError("mode must be 'scroll_4' or 'fit_8'")
        if mode == self._mode:
            return
        self._mode = mode
        self._relayout()

    def layout_plan(self) -> ResearchWorkspaceLayoutPlan:
        return build_research_workspace_layout_in_order(self._attached_order, self._mode)

    def clear(self) -> None:
        for slot_id in tuple(self._slots):
            self.remove_slot(slot_id)
        self._active_slot_id = None
        self._attached_order.clear()
        self._detached.clear()
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._apply_height_policy(self.layout_plan())

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._apply_height_policy(self.layout_plan())
        return super().eventFilter(watched, event)

    def _request_active_slot(self, slot_id: int) -> None:
        self.active_slot_requested.emit(slot_id)

    def _relayout(self) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        plan = self.layout_plan()
        for item in plan.items:
            self._grid.addWidget(
                self._slots[item.slot_id],
                item.row,
                item.column,
                item.row_span,
                item.column_span,
            )
        for row in range(4):
            self._grid.setRowStretch(row, 1 if row < plan.row_count else 0)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._empty.setText(
            "All Research charts are detached"
            if self._slots and not self._attached_order
            else "No Research charts"
        )
        self._empty.setVisible(not self._attached_order)
        self._scroll.setVisible(bool(self._attached_order))
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
            if plan.vertical_scroll == "as_needed"
            else Qt.ScrollBarAlwaysOff
        )
        self._apply_height_policy(plan)

    def _apply_height_policy(self, plan: ResearchWorkspaceLayoutPlan) -> None:
        viewport_height = self._scroll.viewport().height()
        if viewport_height <= 0:
            viewport_height = self.height()
        self._grid_host.setMinimumHeight(
            max(0, int(viewport_height * plan.minimum_height_ratio))
        )
