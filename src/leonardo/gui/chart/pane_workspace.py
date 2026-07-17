"""Single-chart workspace owning price, volume, and Study pane lifecycle."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QShowEvent
from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.annotation_scene import ResearchChartAnnotationBundle
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.oscillator_widget import OscillatorStudyWidget
from leonardo.gui.chart.study_scene import PriceStudyBundle
from leonardo.gui.chart.volume_widget import VolumeChartWidget
from leonardo.research import ResidentStudyProjection, StudyPresentation
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
        self._pane_size_by_id: dict[str, int] = {"price": 720, "volume": 220}
        self._oscillators: dict[str, OscillatorStudyWidget] = {}
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

    def snapshot_pane_sizes(self) -> Mapping[str, int]:
        """Return remembered sizes for every current runtime pane."""

        self._remember_sizes(0, 0)
        return {
            pane_id: self._pane_size_by_id[pane_id]
            for pane_id in self._pane_ids_in_splitter_order()
            if pane_id in self._pane_size_by_id
        }

    def restore_pane_sizes(self, sizes: Mapping[str, int]) -> None:
        """Restore validated pane sizes without emitting workflow intent."""

        if not isinstance(sizes, Mapping):
            raise TypeError("sizes must be a mapping")
        known = set(self._pane_ids_in_splitter_order())
        unknown = set(sizes) - known
        if unknown:
            raise ValueError(f"unknown pane refs: {', '.join(sorted(unknown))}")
        resolved: dict[str, int] = {}
        for pane_id, size in sizes.items():
            if type(pane_id) is not str or type(size) is not int or size <= 0:
                raise ValueError("pane sizes require string refs and positive integers")
            resolved[pane_id] = size
        self._pane_size_by_id.update(resolved)
        if "price" in resolved and "volume" in resolved:
            self._last_visible_sizes = (resolved["price"], resolved["volume"])
        blocked = self._splitter.blockSignals(True)
        try:
            self._apply_pane_sizes()
        finally:
            self._splitter.blockSignals(blocked)

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
        for widget in self._oscillators.values():
            widget.set_interaction_state(state)

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
            self._apply_pane_sizes()
        self._update_time_axis_owner()
        return True

    def apply_study_state(
        self,
        projections: Sequence[ResidentStudyProjection],
        presentations: Sequence[StudyPresentation],
    ) -> None:
        projection_snapshot = tuple(projections)
        presentation_snapshot = tuple(presentations)
        if not all(isinstance(item, ResidentStudyProjection) for item in projection_snapshot):
            raise TypeError("projections must contain ResidentStudyProjection values")
        if not all(isinstance(item, StudyPresentation) for item in presentation_snapshot):
            raise TypeError("presentations must contain StudyPresentation values")
        projection_by_id = {item.study_id: item for item in projection_snapshot}

        price_pairs = tuple(
            (projection_by_id[item.study_id], item)
            for item in presentation_snapshot
            if item.pane_id == "price" and item.study_id in projection_by_id
        )
        self._price.set_study_bundle(
            PriceStudyBundle(
                tuple(item[0] for item in price_pairs),
                tuple(item[1] for item in price_pairs),
            )
        )

        oscillator_presentations = tuple(
            item
            for item in presentation_snapshot
            if item.pane_id == f"oscillator:{item.study_id}"
        )
        oscillator_ids = {item.study_id for item in oscillator_presentations}
        for study_id in tuple(self._oscillators):
            if study_id not in oscillator_ids:
                widget = self._oscillators.pop(study_id)
                self._pane_size_by_id.pop(f"oscillator:{study_id}", None)
                widget.setParent(None)
                widget.deleteLater()

        for order, presentation in enumerate(oscillator_presentations):
            projection = projection_by_id.get(presentation.study_id)
            if projection is None:
                continue
            widget = self._oscillators.get(presentation.study_id)
            if widget is None:
                widget = OscillatorStudyWidget(presentation.study_id, self._splitter)
                widget.viewportChanged.connect(self._on_oscillator_viewport_changed)
                widget.crosshairChanged.connect(self._on_oscillator_crosshair_changed)
                self._oscillators[presentation.study_id] = widget
                self._pane_size_by_id.setdefault(presentation.pane_id, 180)
            self._splitter.insertWidget(2 + order, widget)
            if self._interaction is not None:
                widget.set_interaction_state(self._interaction)
            widget.set_study_state(projection, presentation)
            widget.setVisible(presentation.visible)
        self._apply_pane_sizes()
        self._update_time_axis_owner()

    def set_notebook_annotations(
        self, bundle: ResearchChartAnnotationBundle
    ) -> None:
        self._price.set_annotation_bundle(bundle)

    def clear_notebook_annotations(self) -> None:
        self._price.clear_annotations()

    def study_pane_ids(self) -> tuple[str, ...]:
        pane_ids = ["price"]
        if self._volume_visible:
            pane_ids.append("volume")
        pane_ids.extend(
            f"oscillator:{study_id}"
            for study_id, widget in self._oscillators.items()
            if not widget.isHidden()
        )
        return tuple(pane_ids)

    def oscillator_widget(self, study_id: str) -> OscillatorStudyWidget | None:
        return self._oscillators.get(study_id)

    def clear_studies(self) -> None:
        self._price.clear_studies()
        for study_id, widget in tuple(self._oscillators.items()):
            self._pane_size_by_id.pop(f"oscillator:{study_id}", None)
            widget.setParent(None)
            widget.deleteLater()
        self._oscillators.clear()
        self._apply_pane_sizes()
        self._update_time_axis_owner()

    def clear(self) -> None:
        self._interaction = None
        self._price.clear_interaction_state()
        self._price.clear_render_contract()
        self._volume.set_projection(None)
        self._volume.clear_interaction_state()
        self.clear_studies()
        self.clear_notebook_annotations()

    def refresh_from_shared_state(self) -> None:
        self._price.refresh_from_shared_state()
        self._volume.refresh_from_shared_state()
        for widget in self._oscillators.values():
            widget.refresh_from_shared_state()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._volume_visible:
            QTimer.singleShot(0, self._apply_visible_sizes)

    def _apply_visible_sizes(self) -> None:
        self._apply_pane_sizes()

    def _pane_ids_in_splitter_order(self) -> tuple[str, ...]:
        return (
            "price",
            "volume",
            *(f"oscillator:{study_id}" for study_id in self._oscillators),
        )

    def _apply_pane_sizes(self) -> None:
        sizes: list[int] = []
        for pane_id in self._pane_ids_in_splitter_order():
            if pane_id == "volume" and not self._volume_visible:
                sizes.append(0)
            elif pane_id.startswith("oscillator:"):
                study_id = pane_id.removeprefix("oscillator:")
                widget = self._oscillators.get(study_id)
                sizes.append(
                    self._pane_size_by_id.get(pane_id, 180)
                    if widget is not None and not widget.isHidden()
                    else 0
                )
            else:
                sizes.append(self._pane_size_by_id.get(pane_id, 180))
        if sizes:
            self._splitter.setSizes(sizes)

    def _remember_sizes(self, _position: int, _index: int) -> None:
        if not self.isVisible():
            return
        sizes = self._splitter.sizes()
        pane_ids = self._pane_ids_in_splitter_order()
        if len(sizes) != len(pane_ids):
            return
        for pane_id, size in zip(pane_ids, sizes, strict=True):
            if size > 0:
                self._pane_size_by_id[pane_id] = int(size)
        if self._volume_visible and sizes[0] > 0 and sizes[1] > 0:
            self._last_visible_sizes = (int(sizes[0]), int(sizes[1]))

    def _on_price_viewport_changed(self, snapshot: object) -> None:
        self._refresh_non_price_panes()
        self.viewportChanged.emit(snapshot)

    def _on_volume_viewport_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state()
        self._refresh_oscillators()
        self.viewportChanged.emit(snapshot)

    def _on_price_crosshair_changed(self, snapshot: object) -> None:
        self._refresh_non_price_panes()
        self.crosshairChanged.emit(snapshot)

    def _on_volume_crosshair_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state(refresh_price_scale=False)
        self._refresh_oscillators()
        self.crosshairChanged.emit(snapshot)

    def _on_oscillator_viewport_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state()
        self._volume.refresh_from_shared_state()
        self._refresh_oscillators()
        self.viewportChanged.emit(snapshot)

    def _on_oscillator_crosshair_changed(self, snapshot: object) -> None:
        self._price.refresh_from_shared_state(refresh_price_scale=False)
        self._volume.refresh_from_shared_state()
        self._refresh_oscillators()
        self.crosshairChanged.emit(snapshot)

    def _refresh_non_price_panes(self) -> None:
        self._volume.refresh_from_shared_state()
        self._refresh_oscillators()

    def _refresh_oscillators(self) -> None:
        for widget in self._oscillators.values():
            widget.refresh_from_shared_state()

    def _update_time_axis_owner(self) -> None:
        visible = tuple(widget for widget in self._oscillators.values() if not widget.isHidden())
        self._price.set_time_axis_visible(not visible)
        for widget in self._oscillators.values():
            widget.set_time_axis_visible(bool(visible) and widget is visible[-1])
