"""Chart-local overlays for the restored Research chart presentation."""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.oscillator_widget import OscillatorStudyWidget
from leonardo.research import ResidentStudyProjection, StudyManagerEntry


_OVERLAY_STYLE = """
QWidget[research_overlay="true"][background_state="inside"] {
    background-color: rgba(0, 0, 0, 128);
    border: 1px solid rgba(70, 81, 95, 180);
}
QWidget[research_overlay="true"][background_state="outside"] {
    background-color: transparent;
    border: 1px solid transparent;
}
QWidget[research_overlay="true"] QLabel {
    background: transparent;
    border: none;
}
QWidget[research_overlay_surface="true"] {
    background-color: transparent;
    border: none;
}
QToolButton[research_overlay_button="true"] {
    min-width: 20px;
    min-height: 18px;
    padding: 0 3px;
    background: transparent;
    border: 1px solid transparent;
}
QToolButton[research_overlay_button="true"]:hover {
    background: transparent;
    border: 1px solid rgba(148, 163, 184, 160);
}
QToolButton[research_overlay_button="true"]:pressed,
QToolButton[research_overlay_button="true"]:checked,
QToolButton[research_overlay_button="true"]:disabled,
QToolButton[research_overlay_button="true"]:focus {
    background: transparent;
}
"""


class _RetractableOverlay(QWidget):
    """Share pointer transparency and presentation-only retraction."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("research_overlay", True)
        self.setProperty("background_state", "outside")
        self._expanded = True
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_OVERLAY_STYLE)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.content_widget = QWidget(self)
        _configure_transparent_surface(self.content_widget)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(6, 4, 6, 4)
        self.content_layout.setSpacing(2)
        shell.addWidget(self.content_widget)

        self.retract_button = _tool_button(
            "◀", "Collapse overlay", self
        )
        shell.addWidget(
            self.retract_button,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        self.retract_button.clicked.connect(self._toggle_expanded)

    @property
    def background_state(self) -> str:
        return str(self.property("background_state"))

    @property
    def expanded(self) -> bool:
        return self._expanded

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        del event
        self._set_background_state("inside")

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        del event
        self._set_background_state("outside")

    def _set_background_state(self, state: str) -> None:
        self.setProperty("background_state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.content_widget.setVisible(self._expanded)
        self.retract_button.setText("◀" if self._expanded else "▶")
        self.retract_button.setToolTip(
            "Collapse overlay" if self._expanded else "Expand overlay"
        )
        self.adjustSize()


class PriceStudyOverlayRow(QWidget):
    """Display one price Study name, current values, and local intents."""

    values_toggled = Signal(str, bool)
    style_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        study_id: str,
        display_name: str,
        detail_tooltip: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.study_id = study_id
        self.display_name = display_name
        self.setObjectName(f"research_restoration.price_overlay.row.{study_id}")
        _configure_transparent_surface(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.name_label = QLabel(display_name, self)
        self.name_label.setToolTip(detail_tooltip)
        self.values_label = QLabel("—", self)
        layout.addWidget(self.name_label)
        layout.addWidget(self.values_label)
        layout.addStretch(1)

        self.values_button = _tool_button(
            "V", "Show or hide current values", self, checkable=True
        )
        self.style_button = _tool_button("S", "Edit display style", self)
        self.edit_button = _tool_button(
            "E", "Edit computation parameters", self
        )
        self.remove_button = _tool_button("X", "Remove study from chart", self)
        for button in (
            self.values_button,
            self.style_button,
            self.edit_button,
            self.remove_button,
        ):
            layout.addWidget(button)

        self.values_button.setChecked(True)
        self.values_button.toggled.connect(self._on_values_toggled)
        self.style_button.clicked.connect(
            lambda: self.style_requested.emit(self.study_id)
        )
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.study_id)
        )
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.study_id)
        )

    @property
    def current_values_visible(self) -> bool:
        return self.values_button.isChecked()

    def set_current_values(self, text: str) -> None:
        self.values_label.setText(text)

    def set_display_name(
        self,
        display_name: str,
        detail_tooltip: str,
    ) -> None:
        if not isinstance(display_name, str) or not display_name:
            raise ValueError("display_name must be non-empty text")
        self.display_name = display_name
        self.name_label.setText(display_name)
        self.name_label.setToolTip(detail_tooltip)

    def set_actions_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self.set_action_availability(
            style=available, edit=available, remove=available
        )

    def set_action_availability(
        self,
        *,
        style: bool,
        edit: bool,
        remove: bool,
        phase_gate_tooltips: bool = False,
    ) -> None:
        if not all(
            type(value) is bool
            for value in (style, edit, remove, phase_gate_tooltips)
        ):
            raise TypeError("action availability values must be boolean")
        self.style_button.setEnabled(style)
        self.edit_button.setEnabled(edit)
        self.remove_button.setEnabled(remove)
        self.edit_button.setToolTip(
            "Edit computation parameters"
            if edit
            else "Computation Edit is not available while the chart is busy."
            if phase_gate_tooltips
            else "Edit computation parameters"
        )

    def _on_values_toggled(self, visible: bool) -> None:
        self.values_label.setVisible(visible)
        self.values_toggled.emit(self.study_id, visible)


class PricePaneOverlay(_RetractableOverlay):
    """Floating top-left OHLC and price-Study presentation."""

    values_toggled = Signal(str, bool)
    style_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        market_id: MarketId,
        interaction_state: CandlestickInteractionState,
        studies: Sequence[tuple[ResidentStudyProjection, StudyManagerEntry]],
        parent: CandlestickChartWidget,
    ) -> None:
        super().__init__(parent)
        if not isinstance(parent, CandlestickChartWidget):
            raise TypeError("parent must be a CandlestickChartWidget")
        self._market_id = market_id
        self._interaction_state = interaction_state
        self._studies = tuple(studies)
        self._actions_available = True
        self._action_availability = (True, True, True)
        self._phase_gate_tooltips = False
        self.setObjectName("research_restoration.price_overlay")
        layout = self.content_layout

        self.title_label = QLabel(
            f"{market_id.symbol} · {market_id.timeframe}", self
        )
        self.title_label.setObjectName("research_restoration.price_overlay.title")
        self.ohlc_label = QLabel("", self)
        self.ohlc_label.setObjectName("research_restoration.price_overlay.ohlc")
        layout.addWidget(self.title_label)
        layout.addWidget(self.ohlc_label)

        self._rows_by_study_id: dict[str, PriceStudyOverlayRow] = {}
        self.study_rows: tuple[PriceStudyOverlayRow, ...] = ()
        self.set_studies(self._studies)
        self.refresh()

    def set_studies(
        self,
        studies: Sequence[tuple[ResidentStudyProjection, StudyManagerEntry]],
    ) -> None:
        snapshot = tuple(studies)
        for projection, entry in snapshot:
            if not isinstance(projection, ResidentStudyProjection):
                raise TypeError("studies must contain ResidentStudyProjection values")
            if not isinstance(entry, StudyManagerEntry):
                raise TypeError("studies must contain StudyManagerEntry values")
            if projection.study_id != entry.study_id:
                raise ValueError("projection and manager entry study IDs must match")
        if len({entry.study_id for _projection, entry in snapshot}) != len(snapshot):
            raise ValueError("price Study IDs must be unique")

        retained_ids = {entry.study_id for _projection, entry in snapshot}
        for study_id in tuple(self._rows_by_study_id):
            if study_id in retained_ids:
                continue
            row = self._rows_by_study_id.pop(study_id)
            self.content_layout.removeWidget(row)
            row.deleteLater()

        rows: list[PriceStudyOverlayRow] = []
        for _projection, entry in snapshot:
            row = self._rows_by_study_id.get(entry.study_id)
            if row is None:
                row = PriceStudyOverlayRow(
                    entry.study_id,
                    entry.compact_label,
                    _entry_detail_tooltip(entry),
                    self.content_widget,
                )
                row.values_toggled.connect(self.values_toggled.emit)
                row.style_requested.connect(self.style_requested.emit)
                row.edit_requested.connect(self.edit_requested.emit)
                row.remove_requested.connect(self.remove_requested.emit)
                self._rows_by_study_id[entry.study_id] = row
            else:
                row.set_display_name(
                    entry.compact_label,
                    _entry_detail_tooltip(entry),
                )
            row.set_action_availability(
                style=self._action_availability[0],
                edit=self._action_availability[1],
                remove=self._action_availability[2],
                phase_gate_tooltips=self._phase_gate_tooltips,
            )
            self.content_layout.addWidget(row)
            rows.append(row)
        self._studies = snapshot
        self.study_rows = tuple(rows)
        self.refresh()

    def set_actions_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._actions_available = available
        self._action_availability = (available, available, available)
        self._phase_gate_tooltips = False
        for row in self.study_rows:
            row.set_actions_available(available)

    def set_action_availability(
        self,
        *,
        style: bool,
        edit: bool,
        remove: bool,
        phase_gate_tooltips: bool = False,
    ) -> None:
        if not all(
            type(value) is bool
            for value in (style, edit, remove, phase_gate_tooltips)
        ):
            raise TypeError("action availability values must be boolean")
        self._action_availability = (style, edit, remove)
        self._phase_gate_tooltips = phase_gate_tooltips
        for row in self.study_rows:
            row.set_action_availability(
                style=style,
                edit=edit,
                remove=remove,
                phase_gate_tooltips=phase_gate_tooltips,
            )

    def refresh(self) -> None:
        snapshot = self._interaction_state.viewport.snapshot()
        resident = self._interaction_state.resident
        global_index = snapshot.crosshair_index
        if resident is None:
            self.ohlc_label.setText("O: —  H: —  L: —  C: —")
        else:
            if global_index is None or not resident.contains_global_index(global_index):
                global_index = resident.last_global_index
            local_index = global_index - resident.base_index
            self.ohlc_label.setText(
                "O: {0}  H: {1}  L: {2}  C: {3}".format(
                    _format_number(resident.open[local_index]),
                    _format_number(resident.high[local_index]),
                    _format_number(resident.low[local_index]),
                    _format_number(resident.close[local_index]),
                )
            )

        for row, (projection, _entry) in zip(
            self.study_rows, self._studies, strict=True
        ):
            row.set_current_values(
                _format_projection_values(projection, global_index)
            )
        self.adjustSize()
        self.move(12, 12)
        self.raise_()


class OscillatorPaneOverlay(_RetractableOverlay):
    """Floating top-left controls and values for one oscillator Study pane."""

    move_up_requested = Signal(str)
    move_down_requested = Signal(str)
    values_toggled = Signal(str, bool)
    style_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        projection: ResidentStudyProjection,
        entry: StudyManagerEntry,
        interaction_state: CandlestickInteractionState,
        parent: OscillatorStudyWidget,
    ) -> None:
        super().__init__(parent)
        if not isinstance(parent, OscillatorStudyWidget):
            raise TypeError("parent must be an OscillatorStudyWidget")
        self._projection = projection
        self._interaction_state = interaction_state
        self.study_id = entry.study_id
        self._actions_available = True
        self._action_availability = (True, True, True, True)
        self.setObjectName(
            f"research_restoration.oscillator_overlay.{entry.study_id}"
        )
        layout = self.content_layout
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(3)

        self.title_label = QLabel(entry.compact_label, self)
        self.title_label.setToolTip(_entry_detail_tooltip(entry))
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.move_up_button = _tool_button(
            "↑", "Move oscillator pane up", self
        )
        self.move_down_button = _tool_button(
            "↓", "Move oscillator pane down", self
        )
        self.values_button = _tool_button(
            "V", "Show or hide current values", self, checkable=True
        )
        self.style_button = _tool_button("S", "Edit display style", self)
        self.edit_button = _tool_button(
            "E", "Edit computation parameters", self
        )
        self.remove_button = _tool_button("X", "Remove study from chart", self)
        for button in (
            self.move_up_button,
            self.move_down_button,
            self.values_button,
            self.style_button,
            self.edit_button,
            self.remove_button,
        ):
            header.addWidget(button)
        layout.addLayout(header)

        self.values_label = QLabel("—", self)
        layout.addWidget(self.values_label)

        self.values_button.setChecked(True)
        self.values_button.toggled.connect(self._on_values_toggled)
        self.move_up_button.clicked.connect(
            lambda: self.move_up_requested.emit(self.study_id)
        )
        self.move_down_button.clicked.connect(
            lambda: self.move_down_requested.emit(self.study_id)
        )
        self.style_button.clicked.connect(
            lambda: self.style_requested.emit(self.study_id)
        )
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.study_id)
        )
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.study_id)
        )
        self.refresh()

    def set_snapshot(
        self,
        projection: ResidentStudyProjection,
        entry: StudyManagerEntry,
        interaction_state: CandlestickInteractionState,
    ) -> None:
        if not isinstance(projection, ResidentStudyProjection):
            raise TypeError("projection must be a ResidentStudyProjection")
        if not isinstance(entry, StudyManagerEntry):
            raise TypeError("entry must be a StudyManagerEntry")
        if not isinstance(interaction_state, CandlestickInteractionState):
            raise TypeError("interaction_state must be a CandlestickInteractionState")
        if projection.study_id != self.study_id or entry.study_id != self.study_id:
            raise ValueError("oscillator snapshot must retain the same study ID")
        self._projection = projection
        self._interaction_state = interaction_state
        self.title_label.setText(entry.compact_label)
        self.title_label.setToolTip(_entry_detail_tooltip(entry))
        self.refresh()

    def set_actions_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._actions_available = available
        self.set_action_availability(
            style=available,
            edit=available,
            remove=available,
            move=available,
        )

    def set_action_availability(
        self,
        *,
        style: bool,
        edit: bool,
        remove: bool,
        move: bool,
        phase_gate_tooltips: bool = False,
    ) -> None:
        if not all(
            type(value) is bool
            for value in (style, edit, remove, move, phase_gate_tooltips)
        ):
            raise TypeError("action availability values must be boolean")
        self._action_availability = (style, edit, remove, move)
        self.style_button.setEnabled(style)
        self.edit_button.setEnabled(edit)
        self.remove_button.setEnabled(remove)
        self.move_up_button.setEnabled(move)
        self.move_down_button.setEnabled(move)
        self.edit_button.setToolTip(
            "Edit computation parameters"
            if edit
            else "Computation Edit is not available while the chart is busy."
            if phase_gate_tooltips
            else "Edit computation parameters"
        )
        self.move_up_button.setToolTip(
            "Pane ordering is not available in this integration phase."
            if phase_gate_tooltips
            else "Move oscillator pane up"
        )
        self.move_down_button.setToolTip(
            "Pane ordering is not available in this integration phase."
            if phase_gate_tooltips
            else "Move oscillator pane down"
        )

    @property
    def current_values_visible(self) -> bool:
        return self.values_button.isChecked()

    def _on_values_toggled(self, visible: bool) -> None:
        self.values_label.setVisible(visible)
        self.values_toggled.emit(self.study_id, visible)

    def refresh(self) -> None:
        snapshot = self._interaction_state.viewport.snapshot()
        self.values_label.setText(
            _format_projection_values(self._projection, snapshot.crosshair_index)
        )
        self.adjustSize()
        self.move(12, 12)
        self.raise_()


def _tool_button(
    text: str,
    tooltip: str,
    parent: QWidget,
    *,
    checkable: bool = False,
) -> QToolButton:
    button = QToolButton(parent)
    button.setText(text)
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setAutoRaise(True)
    button.setProperty("research_overlay_button", True)
    return button


def _entry_detail_tooltip(entry: StudyManagerEntry) -> str:
    return (
        f"Tool: {entry.tool_title}\n"
        f"Original Study name: {entry.display_name}\n"
        f"Parameters:\n{entry.parameter_details}\n"
        f"Sources:\n{entry.source_details}"
    )


def _configure_transparent_surface(widget: QWidget) -> None:
    widget.setProperty("research_overlay_surface", True)
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)


def _format_projection_values(
    projection: ResidentStudyProjection,
    global_index: int | None,
) -> str:
    if (
        global_index is None
        or global_index < projection.base_index
        or global_index >= projection.end_index_exclusive
    ):
        global_index = projection.end_index_exclusive - 1
    local_index = global_index - projection.base_index
    values = {
        name: series[local_index]
        for name, series in projection.render_series.items()
    }
    names = tuple(values)
    if names == ("bb_middle", "bb_upper_band", "bb_lower_band"):
        return "  ".join(
            (
                f"M {_format_number(values['bb_middle'])}",
                f"U {_format_number(values['bb_upper_band'])}",
                f"L {_format_number(values['bb_lower_band'])}",
            )
        )
    if names == ("volume", "volume_mean_20"):
        return (
            f"VOL {_format_number(values['volume'])}  "
            f"MEAN {_format_number(values['volume_mean_20'])}"
        )
    if len(names) == 1:
        return _format_number(values[names[0]])
    return "  ".join(
        f"{_abbreviation(name)} {_format_number(values[name])}" for name in names
    )


def _format_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    resolved = float(value)
    return f"{resolved:.2f}" if math.isfinite(resolved) else "—"


def _abbreviation(output_name: str) -> str:
    parts = tuple(part for part in output_name.split("_") if part)
    if not parts:
        return "VAL"
    if len(parts) == 1:
        return parts[0][:4].upper()
    return "".join(part[0] for part in parts[:4]).upper()
