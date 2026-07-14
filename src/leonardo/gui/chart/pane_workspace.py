"""Single-chart pane workspace for price and optional base volume."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.volume_widget import VolumeChartWidget
from leonardo.research.volume import ResidentVolumeProjection


class ChartPaneWorkspaceWidget(QWidget):
    """Own pane lifecycle while panes consume shared horizontal state."""

    viewportChanged = Signal(object)
    priceScaleChanged = Signal(object)
    crosshairChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("research.chart.workspace")
        self.setProperty("appearance_role", "historical_chart_workspace")
        self._splitter = QSplitter(Qt.Vertical, self)
        self._splitter.setObjectName("research.chart.workspace.splitter")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(3)
        self._price = CandlestickChartWidget(self._splitter)
        self._volume = VolumeChartWidget(self._splitter)
        self._splitter.addWidget(self._price)
        self._splitter.addWidget(self._volume)
        self._volume.setVisible(False)
        self._volume_visible = False
        self._last_visible_sizes: tuple[int, int] = (720, 220)
        self._interaction: CandlestickInteractionState | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._splitter)

        self._price.viewportChanged.connect(self._on_price_viewport_changed)
        self._price.priceScaleChanged.connect(self.priceScaleChanged.emit)
        self._price.crosshairChanged.connect(self._on_price_crosshair_changed)
        self._volume.viewportChanged.connect(self._on_volume_viewport_changed)
        self._volume.crosshairChanged.connect(self._on_volume_crosshair_changed)
        self._splitter.splitterMoved.connect(self._remember_sizes)

    @property
    def price_chart(self) -> CandlestickChartWidget:
        return self._price

    @property
    def volume_chart(self) -> VolumeChartWidget:
        return self._volume

    @property
    def volume_visible(self) -> bool:
        return self._volume_visible

    def pane_sizes(self) -> tuple[int, int]:
        """Return the authoritative visible-pane sizes.

        Before the workspace has visible geometry, Qt may report arbitrary equal
        placeholder sizes for the splitter. Those values are not user state and
        must not replace the configured price-dominant proportions.
        """

        if not self._volume_visible or not self.isVisible():
            return self._last_visible_sizes
        sizes = self._splitter.sizes()
        if len(sizes) != 2 or sizes[0] <= 0 or sizes[1] <= 0:
            return self._last_visible_sizes
        return int(sizes[0]), int(sizes[1])

    def apply_chart_state(
        self,
        state: CandlestickInteractionState,
        projection: ResidentVolumeProjection | None,
    ) -> None:
        """Apply one coherent price/volume resident state.

        Clearing the previous projection before replacing the resident prevents
        a transient old-projection/new-resident combination during refills.
        """

        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        if projection is not None and not isinstance(
            projection, ResidentVolumeProjection
        ):
            raise TypeError("projection must be a ResidentVolumeProjection or None")
        self._volume.set_projection(None)
        self.set_interaction_state(state)
        self._volume.set_projection(projection)

    def set_interaction_state(self, state: CandlestickInteractionState) -> None:
        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        projection = self._volume.projection
        resident = state.resident
        if projection is not None and (
            resident is None
            or projection.market_id != resident.market_id
            or projection.dataset_fingerprint != resident.dataset_fingerprint
            or projection.base_index != resident.base_index
            or projection.end_index_exclusive != resident.end_index_exclusive
        ):
            self._volume.set_projection(None)
        self._interaction = state
        self._price.set_interaction_state(state)
        self._volume.set_interaction_state(state)

    def set_volume_projection(
        self, projection: ResidentVolumeProjection | None
    ) -> None:
        self._volume.set_projection(projection)

    def set_volume_visible(self, visible: bool) -> bool:
        if type(visible) is not bool:
            raise TypeError("visible must be a boolean")
        if visible == self._volume_visible:
            return False
        if not visible and self.isVisible():
            sizes = self._splitter.sizes()
            if len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0:
                self._last_visible_sizes = (int(sizes[0]), int(sizes[1]))
        self._volume_visible = visible
        self._volume.setVisible(visible)
        if visible:
            self._apply_visible_sizes()
            self._volume.refresh_from_shared_state()
        else:
            self._splitter.setSizes([max(1, self.height()), 0])
        return True

    def clear(self) -> None:
        self._interaction = None
        self._price.clear_interaction_state()
        self._price.clear_render_contract()
        self._volume.set_projection(None)
        self._volume.clear_interaction_state()

    def refresh_from_shared_state(self) -> None:
        self._price.refresh_from_shared_state()
        self._volume.refresh_from_shared_state()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._volume_visible:
            QTimer.singleShot(0, self._apply_visible_sizes)

    def _apply_visible_sizes(self) -> None:
        self._splitter.setSizes(list(self._last_visible_sizes))

    def _remember_sizes(self, _position: int, _index: int) -> None:
        if not self._volume_visible or not self.isVisible():
            return
        sizes = self._splitter.sizes()
        if len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0:
            self._last_visible_sizes = (int(sizes[0]), int(sizes[1]))

    def _on_price_viewport_changed(self, snapshot: object) -> None:
        self._volume.refresh_from_shared_state()
        self.viewportChanged.emit(snapshot)

    def _on_volume_viewport_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state()
        self.viewportChanged.emit(snapshot)

    def _on_price_crosshair_changed(self, snapshot: object) -> None:
        self._volume.refresh_from_shared_state()
        self.crosshairChanged.emit(snapshot)

    def _on_volume_crosshair_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state(refresh_price_scale=False)
        self.crosshairChanged.emit(snapshot)
