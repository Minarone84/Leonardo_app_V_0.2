"""Qt painting surface for one immutable oscillator Study scene."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.candlestick_scene import (
    DEFAULT_AXIS_WIDTH,
    DEFAULT_LEFT_MARGIN,
    DEFAULT_TOP_MARGIN,
    SceneRect,
)
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.oscillator_scene import OscillatorScene, build_oscillator_scene
from leonardo.research import ResidentStudyProjection, StudyPresentation


@dataclass(frozen=True, slots=True)
class OscillatorPalette:
    background: str = "#0B1016"
    grid: str = "#28303A"
    border: str = "#46515F"
    axis_text: str = "#AAB4C2"
    message_text: str = "#A0A9B5"
    crosshair: str = "#758394"


class OscillatorStudyWidget(QWidget):
    """Paint one Study projection using shared horizontal interaction state."""

    viewportChanged = Signal(object)
    crosshairChanged = Signal(object)

    def __init__(self, study_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not isinstance(study_id, str) or not study_id:
            raise ValueError("study_id must be non-empty text")
        self._study_id = study_id
        self.setObjectName(f"research.chart.oscillator.{study_id}")
        self.setMinimumHeight(100)
        self.setMouseTracking(True)
        self._palette = OscillatorPalette()
        self._interaction: CandlestickInteractionState | None = None
        self._projection: ResidentStudyProjection | None = None
        self._presentation: StudyPresentation | None = None
        self._scene: OscillatorScene | None = None
        self._pixmap: QPixmap | None = None
        self._pixmap_key: tuple[object, ...] | None = None
        self._dragging = False
        self._last_position: QPointF | None = None
        self._show_time_axis = False

    @property
    def study_id(self) -> str:
        return self._study_id

    @property
    def scene_plan(self) -> OscillatorScene | None:
        return self._scene

    @property
    def projection(self) -> ResidentStudyProjection | None:
        return self._projection

    @property
    def presentation(self) -> StudyPresentation | None:
        return self._presentation

    @property
    def time_axis_visible(self) -> bool:
        return self._show_time_axis

    def set_interaction_state(self, state: CandlestickInteractionState) -> None:
        if not isinstance(state, CandlestickInteractionState):
            raise TypeError("state must be a CandlestickInteractionState")
        self._interaction = state
        self.refresh_from_shared_state()

    def clear_interaction_state(self) -> None:
        self._interaction = None
        self._scene = None
        self._invalidate()

    def set_study_state(
        self,
        projection: ResidentStudyProjection,
        presentation: StudyPresentation,
    ) -> None:
        if not isinstance(projection, ResidentStudyProjection):
            raise TypeError("projection must be a ResidentStudyProjection")
        if not isinstance(presentation, StudyPresentation):
            raise TypeError("presentation must be a StudyPresentation")
        if projection.study_id != self._study_id or presentation.study_id != self._study_id:
            raise ValueError("Study state does not match widget")
        before = None if self._scene is None else self._scene.cache_identity
        self._projection = projection
        self._presentation = presentation
        self.refresh_from_shared_state()
        after = None if self._scene is None else self._scene.cache_identity
        if before != after:
            self._invalidate()

    def set_time_axis_visible(self, visible: bool) -> None:
        if type(visible) is not bool:
            raise TypeError("visible must be a boolean")
        if visible != self._show_time_axis:
            self._show_time_axis = visible
            self._invalidate()

    def refresh_from_shared_state(self) -> None:
        if self._interaction is None or self._projection is None or self._presentation is None:
            self._scene = None
        else:
            self._scene = build_oscillator_scene(
                self._projection,
                self._presentation,
                self._interaction.viewport.snapshot(),
                self._scene_rect(),
            )
        self._invalidate()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._invalidate()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        try:
            painter.drawPixmap(0, 0, self._static_pixmap())
            self._draw_crosshair(painter)
        finally:
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.LeftButton
            and self._interaction is not None
            and self._plot_rect().contains(event.position())
        ):
            self._dragging = True
            self._last_position = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._interaction is None:
            super().mouseMoveEvent(event)
            return
        position = event.position()
        plot = self._plot_rect()
        if self._dragging and self._last_position is not None:
            delta = float(position.x() - self._last_position.x())
            self._last_position = position
            if self._interaction.pan_horizontal_pixels(delta, plot.width()):
                self.refresh_from_shared_state()
                self.viewportChanged.emit(self._interaction.viewport.snapshot())
            event.accept()
            return
        if plot.contains(position):
            relative = (float(position.x()) - plot.left()) / max(1.0, plot.width())
            changed = self._interaction.move_crosshair(relative)
            self.update()
            if changed:
                self.crosshairChanged.emit(self._interaction.viewport.snapshot())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._last_position = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._interaction is None or not self._plot_rect().contains(event.position()):
            super().wheelEvent(event)
            return
        plot = self._plot_rect()
        relative = (float(event.position().x()) - plot.left()) / max(1.0, plot.width())
        if self._interaction.zoom_horizontal(event.angleDelta().y(), relative):
            self.refresh_from_shared_state()
            self.viewportChanged.emit(self._interaction.viewport.snapshot())
        event.accept()

    def _scene_rect(self) -> SceneRect:
        plot = self._plot_rect()
        return SceneRect(plot.x(), plot.y(), plot.width(), plot.height())

    def _plot_rect(self) -> QRectF:
        bottom = 24 if self._show_time_axis else 4
        return QRectF(
            DEFAULT_LEFT_MARGIN,
            DEFAULT_TOP_MARGIN,
            max(1.0, self.width() - DEFAULT_LEFT_MARGIN - DEFAULT_AXIS_WIDTH),
            max(1.0, self.height() - DEFAULT_TOP_MARGIN - bottom),
        )

    def _invalidate(self) -> None:
        self._pixmap = None
        self._pixmap_key = None
        self.update()

    def _static_pixmap(self) -> QPixmap:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        identity = None if self._scene is None else self._scene.cache_identity
        key = (self.width(), self.height(), ratio, identity, self._show_time_axis)
        if self._pixmap is not None and self._pixmap_key == key:
            return self._pixmap
        pixmap = QPixmap(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(self._palette.background))
        painter = QPainter(pixmap)
        try:
            if self._scene is None:
                painter.setPen(QColor(self._palette.message_text))
                painter.drawText(QRectF(self.rect()), Qt.AlignCenter, "Oscillator unavailable")
            else:
                self._draw_scene(painter, self._scene)
        finally:
            painter.end()
        self._pixmap = pixmap
        self._pixmap_key = key
        return pixmap

    def _draw_scene(self, painter: QPainter, scene: OscillatorScene) -> None:
        plot = QRectF(scene.plot_rect.x, scene.plot_rect.y, scene.plot_rect.width, scene.plot_rect.height)
        painter.setPen(QPen(QColor(self._palette.border)))
        painter.drawRect(plot)
        painter.setFont(QFont("Consolas", 8))
        for guide in scene.guides:
            pen = QPen(QColor(self._palette.grid))
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), guide.y), QPointF(plot.right(), guide.y))
            painter.setPen(QColor(self._palette.axis_text))
            painter.drawText(QPointF(plot.right() + 6, guide.y + 4), f"{guide.value:g}")
        for strip in scene.line_strips:
            pen = QPen(QColor(strip.color))
            pen.setWidthF(strip.line_width)
            pen.setStyle({"solid": Qt.SolidLine, "dashed": Qt.DashLine, "dotted": Qt.DotLine}[strip.line_pattern])
            painter.setPen(pen)
            for first, second in zip(strip.points, strip.points[1:]):
                painter.drawLine(QPointF(first.x, first.y), QPointF(second.x, second.y))
        if self._show_time_axis:
            painter.setPen(QColor(self._palette.axis_text))
            painter.setFont(QFont("Consolas", 8))
            for tick in scene.time_ticks:
                painter.drawText(
                    QRectF(tick.x - 45, plot.bottom() + 2, 90, 20),
                    Qt.AlignHCenter | Qt.AlignTop,
                    tick.label,
                )
        if scene.center_message:
            painter.setPen(QColor(self._palette.message_text))
            painter.drawText(plot, Qt.AlignCenter, scene.center_message)

    def _draw_crosshair(self, painter: QPainter) -> None:
        if self._interaction is None:
            return
        viewport = self._interaction.viewport.snapshot()
        if viewport.crosshair_index is None:
            return
        plot = self._plot_rect()
        relative = (viewport.crosshair_index - viewport.start_index + 0.5) / viewport.visible_count
        x = plot.left() + relative * plot.width()
        pen = QPen(QColor(self._palette.crosshair))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
