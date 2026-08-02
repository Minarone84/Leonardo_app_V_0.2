"""Qt interaction and painting surface for the historical volume pane."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.candlestick_scene import (
    DEFAULT_AXIS_WIDTH,
    DEFAULT_LEFT_MARGIN,
    DEFAULT_TOP_MARGIN,
)
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.candlestick_widget import (
    _AxisTagPlan,
    _VALUE_TAG_BACKGROUND,
    _crosshair_x,
    _draw_axis_tag,
    _plan_axis_tag,
    _rectangles_overlap,
)
from leonardo.gui.chart.volume_scene import (
    DEFAULT_BOTTOM_MARGIN,
    VolumeRenderContract,
    VolumeScene,
    _format_volume,
    build_volume_scene,
)
from leonardo.research.volume import ResidentVolumeProjection


@dataclass(frozen=True, slots=True)
class VolumePalette:
    background: str = "#0b1016"
    grid: str = "#28303a"
    border: str = "#46515f"
    axis_text: str = "#aab4c2"
    message_text: str = "#a0a9b5"
    up_fill: str = "#00aa78"
    up_outline: str = "#00dca0"
    down_fill: str = "#d24646"
    down_outline: str = "#f06e6e"
    moving_mean: str = "#06b6d4"
    crosshair: str = "#758394"

    def cache_identity(self) -> tuple[str, ...]:
        return (
            self.background,
            self.grid,
            self.border,
            self.axis_text,
            self.message_text,
            self.up_fill,
            self.up_outline,
            self.down_fill,
            self.down_outline,
            self.moving_mean,
            self.crosshair,
        )


class VolumeChartWidget(QWidget):
    """Render one shared-x-axis historical volume pane.

    The widget consumes the same :class:`CandlestickInteractionState` as the
    price pane. It may update the shared horizontal camera and crosshair but owns
    no OHLCV truth, calculation semantics, persistence, or task lifecycle.
    """

    viewportChanged = Signal(object)
    crosshairChanged = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        palette: VolumePalette | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research.chart.volume")
        self.setProperty("appearance_role", "historical_volume_chart")
        self.setProperty(
            "editable_properties",
            ("font_family", "font_size", "foreground", "background"),
        )
        self.setMinimumHeight(100)
        self.setMouseTracking(True)
        self._palette = palette or VolumePalette()
        self._interaction: CandlestickInteractionState | None = None
        self._projection: ResidentVolumeProjection | None = None
        self._contract: VolumeRenderContract | None = None
        self._static_pixmap: QPixmap | None = None
        self._static_key: tuple[object, ...] | None = None
        self._static_rebuild_count = 0
        self._crosshair_y: float | None = None
        self._dragging = False
        self._last_drag_position: QPointF | None = None

    @property
    def render_contract(self) -> VolumeRenderContract | None:
        return self._contract

    @property
    def interaction_state(self) -> CandlestickInteractionState | None:
        return self._interaction

    @property
    def projection(self) -> ResidentVolumeProjection | None:
        return self._projection

    @property
    def static_rebuild_count(self) -> int:
        return self._static_rebuild_count

    def set_interaction_state(self, state: CandlestickInteractionState) -> None:
        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        self._interaction = state
        self._crosshair_y = None
        self.refresh_from_shared_state()

    def clear_interaction_state(self) -> None:
        self._interaction = None
        self._crosshair_y = None
        self._contract = None
        self.invalidate_static_scene()
        self.update()

    def set_projection(self, projection: ResidentVolumeProjection | None) -> None:
        if projection is not None and not isinstance(
            projection, ResidentVolumeProjection
        ):
            raise TypeError("projection must be a ResidentVolumeProjection or None")
        if projection is self._projection:
            return
        self._projection = projection
        self.refresh_from_shared_state()

    def refresh_from_shared_state(self) -> None:
        interaction = self._interaction
        if interaction is None:
            if self._contract is not None:
                self._contract = None
                self.invalidate_static_scene()
            self.update()
            return
        contract = VolumeRenderContract(
            viewport=interaction.viewport.snapshot(),
            resident=interaction.resident if self._projection is not None else None,
            projection=self._projection,
        )
        current_identity = (
            None if self._contract is None else self._contract.cache_identity()
        )
        self._contract = contract
        if current_identity != contract.cache_identity():
            self.invalidate_static_scene()
        self.update()

    def set_chart_palette(self, palette: VolumePalette) -> None:
        if not isinstance(palette, VolumePalette):
            raise TypeError("palette must be a VolumePalette")
        if palette == self._palette:
            return
        self._palette = palette
        self.invalidate_static_scene()
        self.update()

    def invalidate_static_scene(self) -> None:
        self._static_pixmap = None
        self._static_key = None

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.invalidate_static_scene()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        try:
            painter.drawPixmap(0, 0, self._static_scene_pixmap())
            self._draw_dynamic_crosshair(painter)
        finally:
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.LeftButton
            and self._interaction is not None
            and self._plot_rect().contains(event.position())
        ):
            self._dragging = True
            self._last_drag_position = event.position()
            self._interaction.clear_crosshair()
            self._crosshair_y = None
            self.refresh_from_shared_state()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        interaction = self._interaction
        if interaction is None:
            super().mouseMoveEvent(event)
            return
        position = event.position()
        plot = self._plot_rect()
        if self._dragging and self._last_drag_position is not None:
            delta_x = float(position.x() - self._last_drag_position.x())
            self._last_drag_position = position
            if interaction.pan_horizontal_pixels(delta_x, plot.width()):
                self.refresh_from_shared_state()
                self.viewportChanged.emit(interaction.viewport.snapshot())
            event.accept()
            return
        if plot.contains(position):
            relative = (float(position.x()) - plot.left()) / max(1.0, plot.width())
            changed = interaction.move_crosshair(relative)
            self._crosshair_y = float(position.y())
            self.refresh_from_shared_state()
            if changed:
                self.crosshairChanged.emit(interaction.viewport.snapshot())
            event.accept()
            return
        if interaction.clear_crosshair():
            self.refresh_from_shared_state()
            self.crosshairChanged.emit(interaction.viewport.snapshot())
        self._crosshair_y = None
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._last_drag_position = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        interaction = self._interaction
        if interaction is None:
            super().wheelEvent(event)
            return
        plot = self._plot_rect()
        position = event.position()
        if not plot.contains(position):
            event.ignore()
            return
        relative = (float(position.x()) - plot.left()) / max(1.0, plot.width())
        if interaction.zoom_horizontal(event.angleDelta().y(), relative):
            self.refresh_from_shared_state()
            self.viewportChanged.emit(interaction.viewport.snapshot())
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._dragging = False
        self._last_drag_position = None
        self._crosshair_y = None
        if self._interaction is not None and self._interaction.clear_crosshair():
            self.refresh_from_shared_state()
            self.crosshairChanged.emit(self._interaction.viewport.snapshot())
        self.update()
        super().leaveEvent(event)

    def _plot_rect(self) -> QRectF:
        return QRectF(
            DEFAULT_LEFT_MARGIN,
            DEFAULT_TOP_MARGIN,
            max(1.0, self.width() - DEFAULT_LEFT_MARGIN - DEFAULT_AXIS_WIDTH),
            max(1.0, self.height() - DEFAULT_TOP_MARGIN - DEFAULT_BOTTOM_MARGIN),
        )

    def _static_scene_pixmap(self) -> QPixmap:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        contract_identity = (
            None if self._contract is None else self._contract.cache_identity()
        )
        key = (
            self.width(),
            self.height(),
            ratio,
            contract_identity,
            self._palette.cache_identity(),
        )
        if self._static_pixmap is not None and self._static_key == key:
            return self._static_pixmap

        pixel_width = max(1, round(self.width() * ratio))
        pixel_height = max(1, round(self.height() * ratio))
        pixmap = QPixmap(pixel_width, pixel_height)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(self._palette.background))
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing, False)
            if self._contract is None:
                self._draw_message(painter, QRectF(self.rect()), "Volume unavailable")
            else:
                self._draw_scene(
                    painter,
                    build_volume_scene(
                        self._contract,
                        width=max(1, self.width()),
                        height=max(1, self.height()),
                    ),
                )
        finally:
            painter.end()

        self._static_pixmap = pixmap
        self._static_key = key
        self._static_rebuild_count += 1
        return pixmap

    def _draw_scene(self, painter: QPainter, scene: VolumeScene) -> None:
        plot = _qt_rect(scene.plot_rect)
        painter.fillRect(plot, QColor(self._palette.background))
        painter.setPen(QPen(QColor(self._palette.grid)))
        for line in scene.horizontal_grid:
            painter.drawLine(round(line.x1), round(line.y1), round(line.x2), round(line.y2))
        painter.setPen(QPen(QColor(self._palette.border)))
        painter.drawRect(plot)

        for bar in scene.bars:
            fill = QColor(self._palette.up_fill if bar.bullish else self._palette.down_fill)
            outline = QColor(
                self._palette.up_outline if bar.bullish else self._palette.down_outline
            )
            rect = QRectF(
                bar.x - bar.width / 2.0,
                bar.top,
                bar.width,
                bar.height,
            )
            painter.fillRect(rect, QBrush(fill))
            painter.setPen(QPen(outline))
            painter.drawRect(rect)

        mean_pen = QPen(QColor(self._palette.moving_mean))
        mean_pen.setWidth(1)
        painter.setPen(mean_pen)
        previous = None
        previous_index = None
        for point in scene.moving_mean:
            if previous is not None and previous_index is not None and point.global_index == previous_index + 1:
                painter.drawLine(
                    round(previous.x),
                    round(previous.y),
                    round(point.x),
                    round(point.y),
                )
            previous = point
            previous_index = point.global_index

        painter.setPen(QPen(QColor(self._palette.axis_text)))
        painter.setFont(QFont("Consolas", 8))
        for tick in scene.axis_ticks:
            painter.drawLine(
                round(scene.plot_rect.right),
                round(tick.y),
                round(scene.plot_rect.right + 6),
                round(tick.y),
            )
            painter.drawText(
                round(scene.plot_rect.right + 8),
                round(tick.y + 4),
                tick.label,
            )

        if scene.last_volume_tag is not None:
            tag = scene.last_volume_tag
            color = QColor(
                self._palette.up_outline if tag.bullish else self._palette.down_outline
            )
            rect = QRectF(
                scene.plot_rect.right + 2,
                tag.y - 9,
                max(1.0, scene.axis_rect.width - 4),
                18,
            )
            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(self._palette.background)))
            painter.drawText(rect, Qt.AlignCenter, tag.label)

        painter.setPen(QPen(QColor(self._palette.axis_text)))
        painter.drawText(round(scene.plot_rect.x + 6), round(scene.plot_rect.y + 14), "Volume")
        if scene.center_message:
            self._draw_message(painter, plot, scene.center_message)

    def _draw_dynamic_crosshair(self, painter: QPainter) -> None:
        contract = self._contract
        if contract is None or contract.viewport.crosshair_index is None:
            return
        plot = self._plot_rect()
        index = contract.viewport.crosshair_index
        relative = (
            index - contract.viewport.start_index + 0.5
        ) / max(1, contract.viewport.visible_count)
        x = plot.left() + relative * plot.width()
        if x < plot.left() or x > plot.right():
            return
        pen = QPen(QColor(self._palette.crosshair))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(round(x), round(plot.top()), round(x), round(plot.bottom()))
        if self._crosshair_y is not None and plot.top() <= self._crosshair_y <= plot.bottom():
            painter.drawLine(
                round(plot.left()),
                round(self._crosshair_y),
                round(plot.right()),
                round(self._crosshair_y),
            )
        for tag in self._dynamic_crosshair_tags(x):
            _draw_axis_tag(painter, tag)

    def _dynamic_crosshair_tags(
        self, crosshair_x: float | None = None
    ) -> tuple[_AxisTagPlan, ...]:
        contract = self._contract
        if contract is None or contract.viewport.crosshair_index is None:
            return ()
        plot = self._plot_rect()
        index = contract.viewport.crosshair_index
        x = crosshair_x if crosshair_x is not None else _crosshair_x(
            index, contract.viewport.start_index, contract.viewport.visible_count, plot
        )
        if (
            x < plot.left()
            or x > plot.right()
            or self._crosshair_y is None
            or not plot.top() <= self._crosshair_y <= plot.bottom()
        ):
            return ()
        scene = build_volume_scene(
            contract,
            width=max(1, self.width()),
            height=max(1, self.height()),
        )
        if scene.maximum <= 0:
            return ()
        fraction = (plot.bottom() - self._crosshair_y) / max(1.0, plot.height())
        value = min(scene.maximum, max(0.0, fraction * scene.maximum))
        axis = _qt_rect(scene.axis_rect)
        candidate = _plan_axis_tag(
            _format_volume(value),
            axis.center().x(),
            self._crosshair_y,
            axis,
            background=_VALUE_TAG_BACKGROUND,
            background_opacity=0.5,
            corner_radius=6.0,
        )
        static_tag = scene.last_volume_tag
        if static_tag is not None and _rectangles_overlap(
            candidate.rect,
            QRectF(
                scene.plot_rect.right + 2,
                static_tag.y - 9,
                max(1.0, scene.axis_rect.width - 4),
                18,
            ),
        ):
            return ()
        return (candidate,)

    def _draw_message(self, painter: QPainter, rect: QRectF, text: str) -> None:
        painter.save()
        try:
            painter.setPen(QPen(QColor(self._palette.message_text)))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(rect, Qt.AlignCenter, text)
        finally:
            painter.restore()


def _qt_rect(rect) -> QRectF:
    return QRectF(rect.x, rect.y, rect.width, rect.height)
