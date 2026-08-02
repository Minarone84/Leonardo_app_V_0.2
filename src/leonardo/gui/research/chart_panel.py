"""Restored single-chart Research presentation using current V2 primitives."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.gui.research.pane_overlays import (
    OscillatorPaneOverlay,
    PricePaneOverlay,
)
from leonardo.research import (
    ResidentStudyProjection,
    ResidentVolumeProjection,
    StudyManagerEntry,
    StudyPresentation,
)


class ResearchChartPanel(QFrame):
    """Display one prepared Research chart without owning domain services."""

    position_change_requested = Signal(int)
    go_to_requested = Signal()
    financial_tools_requested = Signal()
    studies_requested = Signal()
    detach_requested = Signal()
    close_requested = Signal()
    autoscale_toggled = Signal(bool)
    study_values_toggled = Signal(str, bool)
    study_style_requested = Signal(str)
    study_edit_requested = Signal(str)
    study_remove_requested = Signal(str)
    oscillator_move_up_requested = Signal(str)
    oscillator_move_down_requested = Signal(str)

    def __init__(
        self,
        market_id: MarketId,
        interaction_state: CandlestickInteractionState | None = None,
        study_projections: Sequence[ResidentStudyProjection] = (),
        study_presentations: Sequence[StudyPresentation] = (),
        study_entries: Sequence[StudyManagerEntry] = (),
        parent: QWidget | None = None,
        *,
        slot_id: int = 1,
    ) -> None:
        super().__init__(parent)
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if interaction_state is not None and not isinstance(
            interaction_state, CandlestickInteractionState
        ):
            raise TypeError(
                "interaction_state must be a CandlestickInteractionState or None"
            )
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        projections = tuple(study_projections)
        presentations = tuple(study_presentations)
        entries = tuple(study_entries)
        if not all(isinstance(item, ResidentStudyProjection) for item in projections):
            raise TypeError("study_projections must contain ResidentStudyProjection values")
        if not all(isinstance(item, StudyPresentation) for item in presentations):
            raise TypeError("study_presentations must contain StudyPresentation values")
        if not all(isinstance(item, StudyManagerEntry) for item in entries):
            raise TypeError("study_entries must contain StudyManagerEntry values")

        self._market_id = market_id
        self._interaction_state = interaction_state
        self._slot_id = slot_id
        self._status_text = "Empty" if interaction_state is None else "Chart ready"
        self._progress: tuple[int | None, int | None] = (None, None)
        self._busy = False
        self._go_to_requested_enabled = False
        self._navigation_available = True
        self._workspace_lifecycle_available = True
        self._financial_tools_available = True
        self._studies_available = True
        self._study_overlay_actions_available = True
        self._study_overlay_action_availability = (True, True, True, True)
        self._real_service_overlay_policy = False
        self._workspace_position = 1
        self._workspace_density = "normal"
        self.setObjectName("research_restoration.chart_panel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        panel_policy = self.sizePolicy()
        panel_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        self.setSizePolicy(panel_policy)
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._chart_workspace = ChartPaneWorkspaceWidget(self)
        self._chart_workspace.setObjectName(
            "research_restoration.chart_panel.workspace"
        )
        layout.addWidget(self._chart_workspace, stretch=1)

        self.control_bar = QWidget(self)
        self.control_bar.setObjectName("research_restoration.chart_panel.controls")
        controls = QHBoxLayout(self.control_bar)
        controls.setContentsMargins(2, 3, 2, 3)
        controls.setSpacing(1)

        exchange = market_id.exchange[:1].upper() + market_id.exchange[1:]
        dataset_text = (
            "Historical Chart: "
            f"{exchange}_{market_id.market_type}_{market_id.symbol}_{market_id.timeframe}"
        )
        self.dataset_label = QLabel(dataset_text, self.control_bar)
        self.dataset_label.setObjectName(
            "research_restoration.chart_panel.dataset"
        )
        self.dataset_label.setToolTip(dataset_text)
        dataset_policy = self.dataset_label.sizePolicy()
        dataset_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.dataset_label.setSizePolicy(dataset_policy)
        self.dataset_label.setMinimumWidth(0)
        controls.addWidget(self.dataset_label, stretch=1)

        self.position_label = QLabel("Position", self.control_bar)
        controls.addWidget(self.position_label)
        self.position_combo = QComboBox(self.control_bar)
        self.position_combo.addItems(tuple(str(value) for value in range(1, 9)))
        self.position_combo.setCurrentText("1")
        controls.addWidget(self.position_combo)

        self.go_to_button = QPushButton("Go to", self.control_bar)
        self.financial_tools_button = QPushButton(
            "Financial Tools", self.control_bar
        )
        self.studies_button = QPushButton("Studies", self.control_bar)
        self.detach_button = QPushButton("Detach", self.control_bar)
        self.close_button = QPushButton("Close", self.control_bar)
        self.autoscale_button = QPushButton("Autoscale", self.control_bar)
        self.autoscale_button.setCheckable(True)
        self.autoscale_button.setChecked(
            interaction_state is not None
            and interaction_state.price_scale.autoscale_enabled
        )
        self._refresh_autoscale_visual_state()
        for button in (
            self.go_to_button,
            self.financial_tools_button,
            self.studies_button,
            self.detach_button,
            self.close_button,
            self.autoscale_button,
        ):
            controls.addWidget(button)

        text_first_controls = (
            self.position_label,
            self.position_combo,
            self.go_to_button,
            self.financial_tools_button,
            self.studies_button,
            self.detach_button,
            self.close_button,
            self.autoscale_button,
        )
        for control in text_first_controls:
            control.setMinimumWidth(max(1, control.sizeHint().width()))

        all_controls = (self.dataset_label, *text_first_controls)
        margins = controls.contentsMargins()
        natural_height = max(control.sizeHint().height() for control in all_controls)
        self.control_bar.setFixedHeight(
            natural_height + margins.top() + margins.bottom()
        )
        layout.addWidget(self.control_bar)

        if interaction_state is not None:
            self._chart_workspace.set_interaction_state(interaction_state)
        self._chart_workspace.set_volume_visible(False)
        self._chart_workspace.apply_study_state(projections, presentations)

        projection_by_id = {item.study_id: item for item in projections}
        presentation_by_id = {item.study_id: item for item in presentations}
        entry_by_id = {item.study_id: item for item in entries}
        price_studies = tuple(
            (
                projection_by_id[item.study_id],
                item,
                entry_by_id[item.study_id],
            )
            for item in presentations
            if item.pane_id == "price"
            and item.study_id in projection_by_id
            and item.study_id in entry_by_id
        )
        self.price_overlay: PricePaneOverlay | None = None
        if interaction_state is not None:
            self.price_overlay = self._create_price_overlay(
                interaction_state, price_studies
            )

        self._oscillator_overlays: dict[str, OscillatorPaneOverlay] = {}
        oscillator_overlays: list[OscillatorPaneOverlay] = []
        for entry in entries:
            presentation = presentation_by_id.get(entry.study_id)
            projection = projection_by_id.get(entry.study_id)
            if (
                presentation is None
                or projection is None
                or presentation.pane_id is None
                or not presentation.pane_id.startswith("oscillator:")
            ):
                continue
            pane = self._chart_workspace.oscillator_widget(entry.study_id)
            if pane is None:
                continue
            if interaction_state is None:
                continue
            overlay = OscillatorPaneOverlay(
                projection,
                presentation,
                entry,
                interaction_state,
                pane,
            )
            overlay.move_up_requested.connect(
                self.oscillator_move_up_requested.emit
            )
            overlay.move_down_requested.connect(
                self.oscillator_move_down_requested.emit
            )
            overlay.values_toggled.connect(self.study_values_toggled.emit)
            overlay.style_requested.connect(self.study_style_requested.emit)
            overlay.edit_requested.connect(self.study_edit_requested.emit)
            overlay.remove_requested.connect(self.study_remove_requested.emit)
            self._oscillator_overlays[entry.study_id] = overlay
            oscillator_overlays.append(overlay)
        self.oscillator_overlays = tuple(oscillator_overlays)
        self.set_workspace_density("normal")

        self.position_combo.currentTextChanged.connect(
            self._on_position_changed
        )
        self.go_to_button.clicked.connect(self.go_to_requested.emit)
        self.financial_tools_button.clicked.connect(
            self.financial_tools_requested.emit
        )
        self.studies_button.clicked.connect(self.studies_requested.emit)
        self.detach_button.clicked.connect(self.detach_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)
        self.autoscale_button.toggled.connect(self._on_autoscale_toggled)
        self._chart_workspace.crosshairChanged.connect(
            lambda _snapshot: self.refresh_overlays()
        )
        self._chart_workspace.viewportChanged.connect(
            lambda _snapshot: self.refresh_overlays()
        )
        self.autoscale_button.setEnabled(interaction_state is not None)
        self.refresh_overlays()

    @property
    def market_id(self) -> MarketId:
        return self._market_id

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def chart_widget(self):
        return self._chart_workspace.price_chart

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def chart_workspace(self) -> ChartPaneWorkspaceWidget:
        return self._chart_workspace

    @property
    def workspace_position(self) -> int:
        return self._workspace_position

    def set_dataset(self, market_id: MarketId | None) -> None:
        if market_id is not None and not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        if market_id is None:
            dataset_text = "No dataset"
        else:
            exchange = market_id.exchange[:1].upper() + market_id.exchange[1:]
            dataset_text = (
                "Historical Chart: "
                f"{exchange}_{market_id.market_type}_{market_id.symbol}_"
                f"{market_id.timeframe}"
            )
        self.dataset_label.setText(dataset_text)
        self.dataset_label.setToolTip(dataset_text)

    def set_go_to_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._go_to_requested_enabled = enabled
        self.go_to_button.setEnabled(enabled and self._navigation_available)

    def set_status(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._status_text = message

    def set_progress(self, current: int | None, total: int | None) -> None:
        if current is not None and type(current) is not int:
            raise TypeError("current must be an integer or None")
        if total is not None and type(total) is not int:
            raise TypeError("total must be an integer or None")
        self._progress = (current, total)

    def set_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._busy = busy
        self.setProperty("busy", busy)
        self.autoscale_button.setEnabled(
            not busy and self._interaction_state is not None
        )
        self.go_to_button.setEnabled(
            not busy
            and self._navigation_available
            and self._go_to_requested_enabled
        )
        self.financial_tools_button.setEnabled(
            not busy and self._financial_tools_available
        )
        self.studies_button.setEnabled(not busy and self._studies_available)

    def show_interaction_state(
        self,
        state: CandlestickInteractionState,
        volume_projection: ResidentVolumeProjection | None,
    ) -> None:
        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        if volume_projection is not None and not isinstance(
            volume_projection, ResidentVolumeProjection
        ):
            raise TypeError(
                "volume_projection must be a ResidentVolumeProjection or None"
            )
        self._interaction_state = state
        self._chart_workspace.apply_chart_state(state, volume_projection)
        self._chart_workspace.set_volume_visible(False)
        if self.price_overlay is None:
            self.price_overlay = self._create_price_overlay(state, ())
            self.price_overlay.set_actions_available(
                self._study_overlay_actions_available
            )
            self._apply_price_overlay_availability()
            self.price_overlay.show()
        blocked = self.autoscale_button.blockSignals(True)
        self.autoscale_button.setChecked(state.price_scale.autoscale_enabled)
        self.autoscale_button.blockSignals(blocked)
        self._refresh_autoscale_visual_state()
        self.autoscale_button.setEnabled(not self._busy)
        self.refresh_overlays()

    def set_study_state(
        self,
        projections: Sequence[ResidentStudyProjection],
        presentations: Sequence[StudyPresentation],
    ) -> None:
        projection_snapshot = tuple(projections)
        presentation_snapshot = tuple(presentations)
        self._chart_workspace.apply_study_state(
            projection_snapshot, presentation_snapshot
        )
        self._chart_workspace.refresh_from_shared_state()
        self._chart_workspace.price_chart.repaint()

    def set_study_snapshot(
        self,
        projections: Sequence[ResidentStudyProjection],
        presentations: Sequence[StudyPresentation],
        entries: Sequence[StudyManagerEntry],
    ) -> None:
        projection_snapshot = tuple(projections)
        presentation_snapshot = tuple(presentations)
        entry_snapshot = tuple(entries)
        if not all(
            isinstance(item, ResidentStudyProjection)
            for item in projection_snapshot
        ):
            raise TypeError("projections must contain ResidentStudyProjection values")
        if not all(
            isinstance(item, StudyPresentation)
            for item in presentation_snapshot
        ):
            raise TypeError("presentations must contain StudyPresentation values")
        if not all(isinstance(item, StudyManagerEntry) for item in entry_snapshot):
            raise TypeError("entries must contain StudyManagerEntry values")

        projection_by_id = {item.study_id: item for item in projection_snapshot}
        presentation_by_id = {
            item.study_id: item for item in presentation_snapshot
        }
        entry_by_id = {item.study_id: item for item in entry_snapshot}
        oscillator_ids = tuple(
            presentation.study_id
            for presentation in presentation_snapshot
            if presentation.pane_id is not None
            and presentation.pane_id.startswith("oscillator:")
            and presentation.study_id in projection_by_id
            and presentation.study_id in entry_by_id
        )
        for study_id in tuple(self._oscillator_overlays):
            if study_id in oscillator_ids:
                continue
            overlay = self._oscillator_overlays.pop(study_id)
            overlay.hide()
            overlay.deleteLater()

        self.set_study_state(projection_snapshot, presentation_snapshot)
        price_studies = tuple(
            (
                projection_by_id[presentation.study_id],
                presentation,
                entry_by_id[presentation.study_id],
            )
            for presentation in presentation_snapshot
            if presentation.pane_id == "price"
            and presentation.study_id in projection_by_id
            and presentation.study_id in entry_by_id
        )
        if self.price_overlay is not None:
            self.price_overlay.set_studies(price_studies)
            self.price_overlay.set_actions_available(
                self._study_overlay_actions_available
            )
            self._apply_price_overlay_availability()

        if self._interaction_state is not None:
            for study_id in oscillator_ids:
                pane = self._chart_workspace.oscillator_widget(study_id)
                if pane is None:
                    continue
                projection = projection_by_id[study_id]
                presentation = presentation_by_id[study_id]
                entry = entry_by_id[study_id]
                overlay = self._oscillator_overlays.get(study_id)
                created = overlay is None
                if overlay is None:
                    overlay = OscillatorPaneOverlay(
                        projection,
                        presentation,
                        entry,
                        self._interaction_state,
                        pane,
                    )
                    overlay.move_up_requested.connect(
                        self.oscillator_move_up_requested.emit
                    )
                    overlay.move_down_requested.connect(
                        self.oscillator_move_down_requested.emit
                    )
                    overlay.values_toggled.connect(self.study_values_toggled.emit)
                    overlay.style_requested.connect(self.study_style_requested.emit)
                    overlay.edit_requested.connect(self.study_edit_requested.emit)
                    overlay.remove_requested.connect(self.study_remove_requested.emit)
                    self._oscillator_overlays[study_id] = overlay
                else:
                    overlay.set_snapshot(
                        projection,
                        presentation,
                        entry,
                        self._interaction_state,
                    )
                overlay.set_actions_available(
                    self._study_overlay_actions_available
                )
                self._apply_oscillator_overlay_availability(overlay)
                if created:
                    overlay.show()
        self.oscillator_overlays = tuple(
            self._oscillator_overlays[study_id]
            for study_id in oscillator_ids
            if study_id in self._oscillator_overlays
        )
        self.refresh_overlays()

    def clear_chart_state(self) -> None:
        self._interaction_state = None
        self._chart_workspace.clear()
        self._chart_workspace.set_volume_visible(False)
        self.set_dataset(None)
        self.set_go_to_enabled(False)
        self.set_progress(None, None)
        self.set_busy(False)
        self.set_status("Empty")

    def set_navigation_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._navigation_available = available
        self.go_to_button.setEnabled(
            available and self._go_to_requested_enabled
        )

    def set_workspace_lifecycle_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._workspace_lifecycle_available = available
        self.position_label.setEnabled(available)
        self.position_combo.setEnabled(available)
        self.detach_button.setEnabled(available)

    def set_study_commands_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self.set_financial_tools_available(available)
        self.set_studies_available(available)

    def set_financial_tools_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._financial_tools_available = available
        self.financial_tools_button.setEnabled(available and not self._busy)

    def set_studies_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._studies_available = available
        self.studies_button.setEnabled(available and not self._busy)

    def set_study_overlay_actions_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._study_overlay_actions_available = available
        self._study_overlay_action_availability = (
            available, available, available, available
        )
        self._real_service_overlay_policy = False
        if self.price_overlay is not None:
            self.price_overlay.set_actions_available(available)
        for overlay in self.oscillator_overlays:
            overlay.set_actions_available(available)

    def set_study_overlay_action_availability(
        self, *, style: bool, edit: bool, remove: bool, move: bool
    ) -> None:
        if not all(type(value) is bool for value in (style, edit, remove, move)):
            raise TypeError("action availability values must be boolean")
        self._study_overlay_action_availability = (style, edit, remove, move)
        self._real_service_overlay_policy = True
        self._study_overlay_actions_available = all(
            self._study_overlay_action_availability
        )
        self._apply_price_overlay_availability()
        for overlay in self.oscillator_overlays:
            self._apply_oscillator_overlay_availability(overlay)

    def _apply_price_overlay_availability(self) -> None:
        if self.price_overlay is None:
            return
        style, edit, remove, _move = self._study_overlay_action_availability
        self.price_overlay.set_action_availability(
            style=style,
            edit=edit,
            remove=remove,
            phase_gate_tooltips=self._real_service_overlay_policy,
        )

    def _apply_oscillator_overlay_availability(
        self, overlay: OscillatorPaneOverlay
    ) -> None:
        style, edit, remove, move = self._study_overlay_action_availability
        overlay.set_action_availability(
            style=style,
            edit=edit,
            remove=remove,
            move=move,
            phase_gate_tooltips=self._real_service_overlay_policy,
        )

    def set_workspace_position(self, position: int) -> None:
        if type(position) is not int or not 1 <= position <= 8:
            raise ValueError("position must be an integer from 1 through 8")
        self.position_combo.setCurrentText(str(position))

    def set_workspace_density(self, density: str) -> None:
        if density not in {"normal", "compact"}:
            raise ValueError("density must be 'normal' or 'compact'")
        self._workspace_density = density
        price_minimum = 220 if density == "normal" else 80
        oscillator_minimum = 100 if density == "normal" else 48
        self._chart_workspace.price_chart.setMinimumHeight(price_minimum)
        for pane_id in self._chart_workspace.study_pane_ids():
            if not pane_id.startswith("oscillator:"):
                continue
            study_id = pane_id.removeprefix("oscillator:")
            widget = self._chart_workspace.oscillator_widget(study_id)
            if widget is not None:
                widget.setMinimumHeight(oscillator_minimum)

    def set_detached(self, detached: bool) -> None:
        if type(detached) is not bool:
            raise TypeError("detached must be a boolean")
        self.detach_button.setText("Dock" if detached else "Detach")

    def refresh_overlays(self) -> None:
        if self.price_overlay is not None:
            self.price_overlay.refresh()
        for overlay in self.oscillator_overlays:
            overlay.refresh()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.refresh_overlays()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.refresh_overlays()

    def _on_position_changed(self, text: str) -> None:
        self._workspace_position = int(text)
        self.position_change_requested.emit(self._workspace_position)

    def _on_autoscale_toggled(self, enabled: bool) -> None:
        self._chart_workspace.price_chart.set_autoscale_enabled(enabled)
        self._refresh_autoscale_visual_state()
        self.autoscale_toggled.emit(enabled)

    def _refresh_autoscale_visual_state(self) -> None:
        enabled = self.autoscale_button.isChecked()
        color = "#86EFAC" if enabled else "#FCA5A5"
        self.autoscale_button.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: #111827; }}"
        )
        self.autoscale_button.setToolTip(
            "Autoscale is on. The vertical price range follows visible data."
            if enabled
            else "Autoscale is off. The vertical price range remains manually controlled."
        )
        self.autoscale_button.setAccessibleName(
            "Autoscale on" if enabled else "Autoscale off"
        )

    def _create_price_overlay(
        self,
        interaction_state: CandlestickInteractionState,
        price_studies,
    ) -> PricePaneOverlay:
        overlay = PricePaneOverlay(
            self._market_id,
            interaction_state,
            price_studies,
            self._chart_workspace.price_chart,
        )
        overlay.values_toggled.connect(self.study_values_toggled.emit)
        overlay.style_requested.connect(self.study_style_requested.emit)
        overlay.edit_requested.connect(self.study_edit_requested.emit)
        overlay.remove_requested.connect(self.study_remove_requested.emit)
        return overlay
