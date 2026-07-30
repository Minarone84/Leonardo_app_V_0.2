"""Restored adaptive workspace for up to eight Research chart panels."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from leonardo.gui.research.chart_panel import ResearchChartPanel
from leonardo.gui.research.detached_chart_window import ResearchDetachedChartWindow
from leonardo.gui.widgets.research_workspace_layout import (
    RESEARCH_WORKSPACE_MODES,
    ResearchWorkspaceLayoutPlan,
    build_research_workspace_layout_in_order,
)
from leonardo.research import (
    ResearchWorkspaceShellState,
    ResearchWorkspaceShellStateError,
)


EMPTY_STATE_TEXT = "No Research charts loaded.\nUse File → New Chart to load one."
DETACHED_STATE_TEXT = "All Research charts are detached"


class ResearchWorkspaceWidget(QWidget):
    """Compose restored chart panels around canonical transient shell state."""

    chart_close_requested = Signal(int)
    detached_window_created = Signal(int, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("research_restoration.workspace")
        self._mode = "scroll_4"
        self._shell_state = ResearchWorkspaceShellState()
        self._panels: dict[int, ResearchChartPanel] = {}
        self._detached_windows: dict[int, ResearchDetachedChartWindow] = {}
        self._activation_slots: dict[QObject, int] = {}
        self._active_slot_id: int | None = None
        self._synchronizing_positions = False
        self._external_close_owner = False

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName("research_restoration.workspace.scroll")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self._grid_host = QWidget(self._scroll_area)
        self._grid_host.setObjectName("research_restoration.workspace.grid")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)
        self._scroll_area.setWidget(self._grid_host)

        self.empty_state_label = QLabel(EMPTY_STATE_TEXT, self)
        self.empty_state_label.setObjectName(
            "research_restoration.workspace.empty_state"
        )
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.empty_state_label, stretch=1)
        layout.addWidget(self._scroll_area, stretch=1)
        self._relayout()

    @property
    def shell_state(self) -> ResearchWorkspaceShellState:
        return self._shell_state

    @property
    def visualization_mode(self) -> str:
        return self._mode

    @property
    def scroll_area(self) -> QScrollArea:
        return self._scroll_area

    @property
    def grid_host(self) -> QWidget:
        return self._grid_host

    @property
    def active_slot_id(self) -> int | None:
        return self._active_slot_id

    @property
    def chart_panel(self) -> ResearchChartPanel | None:
        if len(self._panels) != 1:
            return None
        return next(iter(self._panels.values()))

    def set_visualization_mode(self, mode: str) -> None:
        if mode not in RESEARCH_WORKSPACE_MODES:
            raise ValueError("mode must be 'scroll_4' or 'fit_8'")
        if mode == self._mode:
            return
        self._mode = mode
        self._relayout()

    def set_external_close_owner(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._external_close_owner = enabled

    def add_chart(self, slot_id: int, chart_panel: ResearchChartPanel) -> None:
        if not isinstance(chart_panel, ResearchChartPanel):
            raise TypeError("chart_panel must be a ResearchChartPanel")
        if slot_id in self._panels:
            raise ValueError(f"Research chart slot {slot_id} already exists")
        if len(self._panels) >= 8:
            raise ValueError("Research workspace already contains eight charts")
        placement = self._shell_state.register_slot(slot_id)
        self._panels[slot_id] = chart_panel
        chart_panel.setParent(self._grid_host)
        chart_panel.set_detached(False)
        self._connect_panel_signals(slot_id, chart_panel)
        self.refresh_activation_surfaces(slot_id)
        self._synchronize_positions()
        self._relayout()
        if self._active_slot_id is None:
            self.set_active_slot(placement.slot_id)
        else:
            self._refresh_active_properties()

    def remove_chart(self, slot_id: int) -> ResearchChartPanel:
        panel = self.chart_panel_for_slot(slot_id)
        placement = self._shell_state.placement_for(slot_id)
        window = self._detached_windows.pop(slot_id, None)
        if placement.detached:
            if window is None:
                raise RuntimeError("detached Research chart has no floating window")
            panel = window.take_chart_panel()
            window.request_programmatic_close()
        else:
            self._grid.removeWidget(panel)
        self._remove_activation_surfaces(slot_id)
        self._shell_state.remove_slot(slot_id)
        del self._panels[slot_id]
        panel.setParent(None)
        panel.set_detached(False)
        self._compact_attached_positions()
        if self._active_slot_id == slot_id:
            placements = self._shell_state.placements()
            self.set_active_slot(placements[0].slot_id if placements else None)
        else:
            self._refresh_active_properties()
        self._relayout()
        return panel

    def chart_panel_for_slot(self, slot_id: int) -> ResearchChartPanel:
        try:
            return self._panels[slot_id]
        except KeyError as error:
            raise KeyError(f"Research chart slot {slot_id} does not exist") from error

    def slot_ids(self) -> tuple[int, ...]:
        return tuple(sorted(self._panels))

    def attached_slot_ids(self) -> tuple[int, ...]:
        return self._shell_state.attached_slot_ids()

    def detached_slot_ids(self) -> tuple[int, ...]:
        return self._shell_state.detached_slot_ids()

    def chart_count(self) -> int:
        return len(self._panels)

    def can_add_chart(self) -> bool:
        return self.chart_count() < 8

    def next_free_slot_id(self) -> int | None:
        occupied = set(self.slot_ids())
        return next(
            (slot_id for slot_id in range(1, 9) if slot_id not in occupied),
            None,
        )

    def set_active_slot(self, slot_id: int | None) -> None:
        if slot_id is not None and slot_id not in self._panels:
            raise KeyError(f"Research chart slot {slot_id} does not exist")
        self._active_slot_id = slot_id
        self._refresh_active_properties()

    def move_chart(self, slot_id: int, target_position: int) -> None:
        self.chart_panel_for_slot(slot_id)
        try:
            self._shell_state.move_slot(slot_id, target_position)
        except ResearchWorkspaceShellStateError:
            self._synchronize_positions()
            raise
        self._compact_attached_positions()
        self._relayout()

    def detach_chart(self, slot_id: int) -> None:
        panel = self.chart_panel_for_slot(slot_id)
        placement = self._shell_state.placement_for(slot_id)
        if placement.detached:
            return
        self.set_active_slot(slot_id)
        self._shell_state.detach_slot(slot_id)
        self._grid.removeWidget(panel)
        panel.set_workspace_density("normal")
        window = ResearchDetachedChartWindow(slot_id, panel, self)
        window.dock_requested.connect(self.dock_chart)
        self._detached_windows[slot_id] = window
        panel.set_detached(True)
        self._compact_attached_positions()
        self._synchronize_positions()
        self._relayout()
        self.detached_window_created.emit(slot_id, window)
        window.show()

    def dock_chart(self, slot_id: int) -> None:
        placement = self._shell_state.placement_for(slot_id)
        if not placement.detached:
            raise ResearchWorkspaceShellStateError(
                "Research chart is not detached"
            )
        try:
            window = self._detached_windows[slot_id]
        except KeyError as error:
            raise RuntimeError(
                "detached Research chart has no floating window"
            ) from error
        panel = window.take_chart_panel()
        self._shell_state.dock_slot(slot_id)
        panel.setParent(self._grid_host)
        panel.set_detached(False)
        window.request_programmatic_close()
        del self._detached_windows[slot_id]
        self._compact_attached_positions()
        self._synchronize_positions()
        self._relayout()

    def detached_window(
        self, slot_id: int
    ) -> ResearchDetachedChartWindow | None:
        return self._detached_windows.get(slot_id)

    def clear_all_charts(self) -> None:
        for slot_id in tuple(self.slot_ids()):
            self.remove_chart(slot_id)
        self._shell_state.clear()
        self.set_active_slot(None)
        self._relayout()

    def show_single_chart(self, chart_panel: QWidget) -> None:
        if not isinstance(chart_panel, ResearchChartPanel):
            raise TypeError("chart_panel must be a ResearchChartPanel")
        self.clear_all_charts()
        self.add_chart(1, chart_panel)

    def clear_chart(self) -> None:
        self.clear_all_charts()

    def layout_plan(self) -> ResearchWorkspaceLayoutPlan:
        return build_research_workspace_layout_in_order(
            self.attached_slot_ids(), self._mode
        )

    def refresh_activation_surfaces(self, slot_id: int) -> None:
        panel = self.chart_panel_for_slot(slot_id)
        self._remove_activation_surfaces(slot_id)
        surfaces: list[QObject] = [panel, panel.chart_workspace.price_chart]
        for pane_id in panel.chart_workspace.study_pane_ids():
            if not pane_id.startswith("oscillator:"):
                continue
            study_id = pane_id.removeprefix("oscillator:")
            widget = panel.chart_workspace.oscillator_widget(study_id)
            if widget is not None:
                surfaces.append(widget)
        for surface in surfaces:
            self._activation_slots[surface] = slot_id
            surface.installEventFilter(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._apply_height_policy(self.layout_plan())

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        slot_id = self._activation_slots.get(watched)
        if slot_id is not None and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
        ):
            self.set_active_slot(slot_id)
        return super().eventFilter(watched, event)

    def _connect_panel_signals(
        self, slot_id: int, panel: ResearchChartPanel
    ) -> None:
        panel.position_change_requested.connect(
            lambda position, current=slot_id: self._on_position_requested(
                current, position
            )
        )
        panel.detach_requested.connect(
            lambda current=slot_id: self._on_detach_requested(current)
        )
        panel.close_requested.connect(
            lambda current=slot_id: self._on_close_requested(current)
        )
        for signal in (
            panel.go_to_requested,
            panel.financial_tools_requested,
            panel.studies_requested,
            panel.autoscale_toggled,
            panel.study_values_toggled,
            panel.study_style_requested,
            panel.study_edit_requested,
            panel.study_remove_requested,
            panel.oscillator_move_up_requested,
            panel.oscillator_move_down_requested,
        ):
            signal.connect(
                lambda *args, current=slot_id: self._activate_if_managed(current)
            )

    def _on_position_requested(self, slot_id: int, position: int) -> None:
        if self._synchronizing_positions or slot_id not in self._panels:
            return
        self.set_active_slot(slot_id)
        try:
            self.move_chart(slot_id, position)
        except ResearchWorkspaceShellStateError:
            self._synchronize_positions()

    def _on_detach_requested(self, slot_id: int) -> None:
        if slot_id not in self._panels:
            return
        self.set_active_slot(slot_id)
        if self._shell_state.placement_for(slot_id).detached:
            self.dock_chart(slot_id)
        else:
            self.detach_chart(slot_id)

    def _on_close_requested(self, slot_id: int) -> None:
        if slot_id not in self._panels:
            return
        self.set_active_slot(slot_id)
        if self._external_close_owner:
            self.chart_close_requested.emit(slot_id)
            return
        panel = self.remove_chart(slot_id)
        panel.deleteLater()

    def _activate_if_managed(self, slot_id: int) -> None:
        if slot_id in self._panels:
            self.set_active_slot(slot_id)

    def _compact_attached_positions(self) -> None:
        reserved = {
            placement.workspace_position
            for placement in self._shell_state.placements()
            if placement.detached
        }
        attached = tuple(
            placement
            for placement in self._shell_state.placements()
            if not placement.detached
        )
        targets = tuple(
            position for position in range(1, 9) if position not in reserved
        )[: len(attached)]
        for placement, target in zip(attached, targets, strict=True):
            current = self._shell_state.placement_for(placement.slot_id)
            if current.workspace_position != target:
                self._shell_state.move_slot(placement.slot_id, target)
        self._synchronize_positions()

    def _synchronize_positions(self) -> None:
        self._synchronizing_positions = True
        try:
            for placement in self._shell_state.placements():
                self._panels[placement.slot_id].set_workspace_position(
                    placement.workspace_position
                )
        finally:
            self._synchronizing_positions = False

    def _remove_activation_surfaces(self, slot_id: int) -> None:
        for surface, current_slot in tuple(self._activation_slots.items()):
            if current_slot != slot_id:
                continue
            try:
                surface.removeEventFilter(self)
            except RuntimeError:
                pass
            del self._activation_slots[surface]

    def _refresh_active_properties(self) -> None:
        for slot_id, panel in self._panels.items():
            panel.setProperty("active_chart", slot_id == self._active_slot_id)

    def _relayout(self) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        plan = self.layout_plan()
        density = (
            "compact"
            if self._mode == "fit_8" and plan.row_count >= 3
            else "normal"
        )
        for item in plan.items:
            self._panels[item.slot_id].set_workspace_density(density)
            self._grid.addWidget(
                self._panels[item.slot_id],
                item.row,
                item.column,
                item.row_span,
                item.column_span,
            )
        for row in range(4):
            self._grid.setRowStretch(row, 1 if row < plan.row_count else 0)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self.empty_state_label.setText(
            DETACHED_STATE_TEXT
            if self._panels and not plan.items
            else EMPTY_STATE_TEXT
        )
        self.empty_state_label.setVisible(not plan.items)
        self._scroll_area.setVisible(bool(plan.items))
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if plan.vertical_scroll == "as_needed"
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._apply_height_policy(plan)

    def _apply_height_policy(self, plan: ResearchWorkspaceLayoutPlan) -> None:
        viewport_height = self._scroll_area.viewport().height()
        if viewport_height <= 0:
            viewport_height = self.height()
        self._grid_host.setMinimumHeight(
            max(0, int(viewport_height * plan.minimum_height_ratio))
        )
