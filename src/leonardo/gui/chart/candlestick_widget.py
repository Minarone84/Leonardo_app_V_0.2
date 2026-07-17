"""Qt interaction and painting surface for historical candlestick charts."""

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
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.candlestick_scene import (
    DEFAULT_AXIS_WIDTH,
    DEFAULT_LEFT_MARGIN,
    DEFAULT_TIME_AXIS_HEIGHT,
    DEFAULT_TOP_MARGIN,
    CandlestickRenderContract,
    CandlestickScene,
    SceneRect,
    build_candlestick_scene,
)
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.price_scale import PriceRange, PriceScaleSnapshot
from leonardo.gui.chart.study_scene import (
    PriceStudyBundle,
    StudyScene,
    build_study_scene,
    visible_price_study_values,
)


@dataclass(frozen=True, slots=True)
class CandlestickPalette:
    background: str = "#0b1016"
    grid: str = "#28303a"
    border: str = "#46515f"
    axis_text: str = "#aab4c2"
    message_text: str = "#a0a9b5"
    up_fill: str = "#00aa78"
    up_outline: str = "#00dca0"
    down_fill: str = "#d24646"
    down_outline: str = "#f06e6e"
    wick: str = "#c8c8d2"
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
            self.wick,
            self.crosshair,
        )


class CandlestickChartWidget(QWidget):
    """Render and locally interact with one historical price chart.

    The injected :class:`CandlestickInteractionState` owns the mutable viewport
    and vertical price-scale authorities.  This widget translates mouse gestures,
    paints immutable contracts, and emits read-only state changes.  It performs
    no I/O, persistence, OHLCV validation, Financial Tool calculation, or task
    lifecycle management.
    """

    viewportChanged = Signal(object)
    priceScaleChanged = Signal(object)
    crosshairChanged = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        palette: CandlestickPalette | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("research.chart.candlestick")
        self.setProperty("appearance_role", "historical_candlestick_chart")
        self.setProperty(
            "editable_properties",
            ("font_family", "font_size", "foreground", "background"),
        )
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self._palette = palette or CandlestickPalette()
        self._contract: CandlestickRenderContract | None = None
        self._study_bundle = PriceStudyBundle()
        self._study_scene: StudyScene | None = None
        self._interaction: CandlestickInteractionState | None = None
        self._static_pixmap: QPixmap | None = None
        self._static_key: tuple[object, ...] | None = None
        self._static_rebuild_count = 0
        self._crosshair_y: float | None = None
        self._plot_dragging = False
        self._axis_dragging = False
        self._axis_drag_mode = "zoom"
        self._last_drag_position: QPointF | None = None
        self._time_axis_visible = True

    @property
    def render_contract(self) -> CandlestickRenderContract | None:
        return self._contract

    @property
    def static_rebuild_count(self) -> int:
        return self._static_rebuild_count

    @property
    def interaction_state(self) -> CandlestickInteractionState | None:
        return self._interaction

    @property
    def study_bundle(self) -> PriceStudyBundle:
        return self._study_bundle

    @property
    def study_scene(self) -> StudyScene | None:
        return self._study_scene

    @property
    def autoscale_enabled(self) -> bool:
        return True if self._interaction is None else self._interaction.price_scale.autoscale_enabled

    def set_render_contract(self, contract: CandlestickRenderContract) -> None:
        if not isinstance(contract, CandlestickRenderContract):
            raise TypeError("contract must be a CandlestickRenderContract")
        new_identity = contract.cache_identity()
        current_identity = None if self._contract is None else self._contract.cache_identity()
        self._contract = contract
        if new_identity != current_identity:
            self.invalidate_static_scene()
        self.update()

    def set_interaction_state(self, state: CandlestickInteractionState) -> None:
        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        self._interaction = state
        self._crosshair_y = None
        self._refresh_from_interaction()

    def set_study_bundle(self, bundle: PriceStudyBundle) -> None:
        if not isinstance(bundle, PriceStudyBundle):
            raise TypeError("bundle must be a PriceStudyBundle")
        if bundle.cache_identity() == self._study_bundle.cache_identity():
            return
        self._study_bundle = bundle
        self.invalidate_static_scene()
        if self._interaction is not None:
            self._refresh_from_interaction()
        else:
            self.update()

    def clear_interaction_state(self) -> None:
        self._interaction = None
        self._crosshair_y = None

    def clear_studies(self) -> None:
        self._study_bundle = PriceStudyBundle()
        self._study_scene = None
        self.invalidate_static_scene()
        if self._interaction is not None:
            self._refresh_from_interaction()
        else:
            self.update()

    def set_time_axis_visible(self, visible: bool) -> None:
        if type(visible) is not bool:
            raise TypeError("visible must be a boolean")
        if visible != self._time_axis_visible:
            self._time_axis_visible = visible
            self.invalidate_static_scene()
            self.update()

    def clear_render_contract(self) -> None:
        if self._contract is None:
            return
        self._contract = None
        self.invalidate_static_scene()
        self.update()

    def set_autoscale_enabled(self, enabled: bool) -> bool:
        if self._interaction is None:
            return False
        changed = self._interaction.set_autoscale_enabled(enabled)
        if changed:
            self._refresh_from_interaction()
            self.priceScaleChanged.emit(
                self._interaction.price_scale_snapshot(
                    extra_visible_prices=self._visible_overlay_values()
                )
            )
        return changed

    def refresh_from_shared_state(
        self, *, refresh_price_scale: bool = True
    ) -> None:
        """Refresh from the injected shared interaction authority.

        Pane workspaces call this after another pane changes the shared
        horizontal viewport or crosshair.  The method does not mutate the
        viewport itself.
        """

        self._refresh_from_interaction(refresh_price_scale=refresh_price_scale)

    def set_chart_palette(self, palette: CandlestickPalette) -> None:
        if not isinstance(palette, CandlestickPalette):
            raise TypeError("palette must be a CandlestickPalette")
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
        if event.button() != Qt.LeftButton or self._interaction is None:
            super().mousePressEvent(event)
            return
        position = event.position()
        plot = self._plot_rect()
        if self._price_axis_rect().contains(position):
            if not self._interaction.price_scale.autoscale_enabled:
                self._axis_dragging = True
                self._axis_drag_mode = (
                    "pan" if event.modifiers() & Qt.ShiftModifier else "zoom"
                )
                self._last_drag_position = position
            event.accept()
            return
        if plot.contains(position):
            self._plot_dragging = True
            self._last_drag_position = position
            self._interaction.clear_crosshair()
            self._crosshair_y = None
            self._refresh_from_interaction()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._interaction is None:
            super().mouseMoveEvent(event)
            return
        position = event.position()
        plot = self._plot_rect()
        previous = self._last_drag_position

        if self._axis_dragging and previous is not None:
            delta_y = float(position.y() - previous.y())
            if self._axis_drag_mode == "pan":
                changed = self._interaction.pan_price_pixels(delta_y, plot.height())
            else:
                changed = self._interaction.zoom_price_pixels(delta_y)
            self._last_drag_position = position
            if changed:
                self._refresh_from_interaction()
                self.priceScaleChanged.emit(
                    self._interaction.price_scale_snapshot(
                        extra_visible_prices=self._visible_overlay_values()
                    )
                )
            event.accept()
            return

        if self._plot_dragging and previous is not None:
            delta_x = float(position.x() - previous.x())
            delta_y = float(position.y() - previous.y())
            horizontal_changed = self._interaction.pan_horizontal_pixels(
                delta_x, plot.width()
            )
            vertical_changed = self._interaction.pan_price_pixels(
                delta_y, plot.height()
            )
            self._last_drag_position = position
            if horizontal_changed or vertical_changed:
                self._refresh_from_interaction()
            if horizontal_changed:
                self.viewportChanged.emit(self._interaction.viewport.snapshot())
            if vertical_changed:
                self.priceScaleChanged.emit(
                    self._interaction.price_scale_snapshot(
                        extra_visible_prices=self._visible_overlay_values()
                    )
                )
            event.accept()
            return

        if plot.contains(position):
            relative = (float(position.x()) - plot.left()) / max(1.0, plot.width())
            changed = self._interaction.move_crosshair(relative)
            self._crosshair_y = float(position.y())
            self._refresh_from_interaction(refresh_price_scale=False)
            if changed:
                self.crosshairChanged.emit(self._interaction.viewport.snapshot())
            else:
                self.update()
            event.accept()
            return

        if self._interaction.clear_crosshair():
            self._refresh_from_interaction(refresh_price_scale=False)
            self.crosshairChanged.emit(self._interaction.viewport.snapshot())
        self._crosshair_y = None
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and (
            self._plot_dragging or self._axis_dragging
        ):
            self._plot_dragging = False
            self._axis_dragging = False
            self._last_drag_position = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._interaction is None:
            super().wheelEvent(event)
            return
        plot = self._plot_rect()
        position = event.position()
        if not plot.contains(position):
            event.ignore()
            return
        relative = (float(position.x()) - plot.left()) / max(1.0, plot.width())
        changed = self._interaction.zoom_horizontal(event.angleDelta().y(), relative)
        if changed:
            self._refresh_from_interaction()
            self.viewportChanged.emit(self._interaction.viewport.snapshot())
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._plot_dragging = False
        self._axis_dragging = False
        self._last_drag_position = None
        self._crosshair_y = None
        if self._interaction is not None and self._interaction.clear_crosshair():
            self._refresh_from_interaction(refresh_price_scale=False)
            self.crosshairChanged.emit(self._interaction.viewport.snapshot())
        self.update()
        super().leaveEvent(event)

    def _refresh_from_interaction(
        self, *, refresh_price_scale: bool = True
    ) -> None:
        if self._interaction is not None:
            self.set_render_contract(
                self._interaction.render_contract(
                    refresh_price_scale=refresh_price_scale,
                    extra_visible_prices=self._visible_overlay_values(),
                )
            )

    def _visible_overlay_values(self) -> tuple[float, ...]:
        if self._interaction is None:
            return ()
        return visible_price_study_values(
            self._study_bundle,
            self._interaction.viewport.snapshot(),
        )

    def _plot_rect(self) -> QRectF:
        return QRectF(
            DEFAULT_LEFT_MARGIN,
            DEFAULT_TOP_MARGIN,
            max(1.0, self.width() - DEFAULT_LEFT_MARGIN - DEFAULT_AXIS_WIDTH),
            max(1.0, self.height() - DEFAULT_TOP_MARGIN - DEFAULT_TIME_AXIS_HEIGHT),
        )

    def _price_axis_rect(self) -> QRectF:
        plot = self._plot_rect()
        return QRectF(plot.right(), plot.top(), DEFAULT_AXIS_WIDTH, plot.height())

    def _static_scene_pixmap(self) -> QPixmap:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        contract_identity = None if self._contract is None else self._contract.cache_identity()
        key = (
            self.width(),
            self.height(),
            ratio,
            contract_identity,
            self._study_bundle.cache_identity(),
            self._time_axis_visible,
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
                self._draw_empty_message(painter, "No accepted OHLCV data")
            else:
                candle_scene = build_candlestick_scene(
                    self._contract,
                    width=max(1, self.width()),
                    height=max(1, self.height()),
                )
                self._study_scene = build_study_scene(
                    self._study_bundle,
                    self._contract.viewport,
                    self._contract.price_scale
                    or PriceScaleSnapshot(
                        True, PriceRange(candle_scene.price_low, candle_scene.price_high)
                    ),
                    candle_scene.plot_rect,
                )
                self._draw_scene(painter, candle_scene, self._study_scene)
        finally:
            painter.end()

        self._static_pixmap = pixmap
        self._static_key = key
        self._static_rebuild_count += 1
        return pixmap

    def _draw_scene(
        self, painter: QPainter, scene: CandlestickScene, studies: StudyScene
    ) -> None:
        plot = _qt_rect(scene.plot_rect)
        painter.fillRect(plot, QColor(self._palette.background))

        grid_pen = QPen(QColor(self._palette.grid))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for line in (*scene.horizontal_grid, *scene.vertical_grid):
            painter.drawLine(round(line.x1), round(line.y1), round(line.x2), round(line.y2))

        painter.setPen(QPen(QColor(self._palette.border)))
        painter.drawRect(plot)

        for fill in studies.fills:
            polygon = QPolygonF(
                [QPointF(point.x, point.upper_y) for point in fill.points]
                + [QPointF(point.x, point.lower_y) for point in reversed(fill.points)]
            )
            color = QColor(fill.color)
            color.setAlphaF(fill.opacity)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(polygon)

        wick_pen = QPen(QColor(self._palette.wick))
        for candle in scene.candles:
            painter.setPen(wick_pen)
            painter.drawLine(
                round(candle.x),
                round(candle.wick_top),
                round(candle.x),
                round(candle.wick_bottom),
            )
            body = QRectF(
                candle.x - candle.body_width / 2.0,
                candle.body_top,
                candle.body_width,
                candle.body_height,
            )
            if candle.bullish:
                fill = QColor(self._palette.up_fill)
                outline = QColor(self._palette.up_outline)
            else:
                fill = QColor(self._palette.down_fill)
                outline = QColor(self._palette.down_outline)
            painter.fillRect(body, QBrush(fill))
            painter.setPen(QPen(outline))
            painter.drawRect(body)

        for strip in studies.line_strips:
            pen = QPen(QColor(strip.color))
            pen.setWidthF(strip.line_width)
            pen.setStyle(_qt_line_style(strip.line_pattern))
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for first, second in zip(strip.points, strip.points[1:]):
                painter.drawLine(QPointF(first.x, first.y), QPointF(second.x, second.y))

        for marker in studies.markers:
            painter.setPen(QPen(QColor(marker.color)))
            painter.setBrush(QBrush(QColor(marker.color)))
            _draw_marker(painter, marker.point.x, marker.point.y, marker.marker_shape, marker.marker_size)

        painter.setPen(QPen(QColor(self._palette.axis_text)))
        painter.setFont(QFont("Consolas", 9))
        for tick in scene.price_ticks:
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

        if self._time_axis_visible:
            painter.setFont(QFont("Consolas", 8))
            for tick in scene.time_ticks:
                label_rect = QRectF(
                    tick.x - 45,
                    scene.time_axis_rect.y,
                    90,
                    scene.time_axis_rect.height,
                )
                painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, tick.label)

        if scene.last_price_tag is not None:
            tag = scene.last_price_tag
            color = QColor(
                self._palette.up_outline if tag.bullish else self._palette.down_outline
            )
            line_pen = QPen(color)
            line_pen.setStyle(Qt.DashLine)
            painter.setPen(line_pen)
            painter.drawLine(
                round(scene.plot_rect.x),
                round(tag.y),
                round(scene.plot_rect.right),
                round(tag.y),
            )
            tag_rect = QRectF(
                scene.plot_rect.right + 2,
                tag.y - 9,
                max(1.0, scene.price_axis_rect.width - 4),
                18,
            )
            painter.fillRect(tag_rect, color)
            painter.setPen(QPen(QColor(self._palette.background)))
            painter.setFont(QFont("Consolas", 8))
            painter.drawText(tag_rect, Qt.AlignCenter, tag.label)

        if scene.left_gap_rect is not None and scene.left_gap_message:
            self._draw_message_in_rect(
                painter, _qt_rect(scene.left_gap_rect), scene.left_gap_message
            )
        if scene.center_message:
            self._draw_message_in_rect(painter, plot, scene.center_message)

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

    def _draw_empty_message(self, painter: QPainter, text: str) -> None:
        self._draw_message_in_rect(painter, QRectF(self.rect()), text)

    def _draw_message_in_rect(self, painter: QPainter, rect: QRectF, text: str) -> None:
        painter.save()
        try:
            painter.setPen(QPen(QColor(self._palette.message_text)))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(rect, Qt.AlignCenter, text)
        finally:
            painter.restore()


def _qt_rect(rect: SceneRect) -> QRectF:
    return QRectF(rect.x, rect.y, rect.width, rect.height)


def _qt_line_style(pattern: str):
    return {
        "solid": Qt.SolidLine,
        "dashed": Qt.DashLine,
        "dotted": Qt.DotLine,
    }[pattern]


def _draw_marker(
    painter: QPainter, x: float, y: float, shape: str, size: int
) -> None:
    half = size / 2.0
    if shape == "circle":
        painter.drawEllipse(QPointF(x, y), half, half)
    elif shape == "square":
        painter.drawRect(QRectF(x - half, y - half, size, size))
    elif shape == "triangle_up":
        painter.drawPolygon(
            QPolygonF(
                [QPointF(x, y - half), QPointF(x - half, y + half), QPointF(x + half, y + half)]
            )
        )
    elif shape == "triangle_down":
        painter.drawPolygon(
            QPolygonF(
                [QPointF(x, y + half), QPointF(x - half, y - half), QPointF(x + half, y - half)]
            )
        )
