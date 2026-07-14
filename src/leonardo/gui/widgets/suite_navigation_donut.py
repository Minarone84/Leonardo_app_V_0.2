"""GUI-only Suite Navigation donut widget for Main Window suite intents."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, radians, sin

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from leonardo.gui.style import GuiTheme, load_default_theme


SEGMENT_DEGREES = 72.0
INNER_DIAMETER_RATIO = 0.80
OUTER_DIAMETER_SCALE = 0.92


@dataclass(frozen=True)
class SuiteNavigationSegment:
    """Static GUI mapping from one donut segment to an existing action ID."""

    object_id: str
    label: str
    short_label: str
    action_id: str
    target_area_id: str
    target_suite_id: str
    target_module_id: str


@dataclass(frozen=True)
class SuiteNavigationDonutGeometry:
    """Deterministic donut geometry derived from available widget dimensions."""

    center_x: float
    center_y: float
    outer_diameter: float
    inner_diameter: float
    segment_degrees: float = SEGMENT_DEGREES

    @property
    def outer_radius(self) -> float:
        """Return the outer donut radius."""

        return self.outer_diameter / 2.0

    @property
    def inner_radius(self) -> float:
        """Return the inner cutout radius."""

        return self.inner_diameter / 2.0

    @property
    def center(self) -> QPointF:
        """Return the donut center point."""

        return QPointF(self.center_x, self.center_y)


DEFAULT_SUITE_NAVIGATION_SEGMENTS: tuple[SuiteNavigationSegment, ...] = (
    SuiteNavigationSegment(
        object_id="main_window.donut.segment.connection_suite",
        label="Connection Suite",
        short_label="Connection",
        action_id="main_window.download_data",
        target_area_id="connection",
        target_suite_id="connection_suite",
        target_module_id="connection.download_manager",
    ),
    SuiteNavigationSegment(
        object_id="main_window.donut.segment.research_suite",
        label="Research Suite",
        short_label="Research",
        action_id="main_window.open_research_suite",
        target_area_id="research",
        target_suite_id="research_suite",
        target_module_id="research.gui_shell",
    ),
    SuiteNavigationSegment(
        object_id="main_window.donut.segment.data_manager",
        label="Data Manager Suite",
        short_label="Data",
        action_id="main_window.open_data_manager_suite",
        target_area_id="data_manager",
        target_suite_id="data_manager_suite",
        target_module_id="data_manager.gui_shell",
    ),
    SuiteNavigationSegment(
        object_id="main_window.donut.segment.analysis_suite",
        label="Analysis Suite",
        short_label="Analysis",
        action_id="main_window.open_analysis_suite",
        target_area_id="analysis",
        target_suite_id="analysis_suite",
        target_module_id="analysis.gui_shell",
    ),
    SuiteNavigationSegment(
        object_id="main_window.donut.segment.trading_suite",
        label="Trading Suite",
        short_label="Trading",
        action_id="main_window.open_trading_suite",
        target_area_id="trading",
        target_suite_id="trading_suite",
        target_module_id="trading.gui_shell",
    ),
)


class SuiteNavigationDonut(QWidget):
    """
    Paint and hit-test Main Window Suite Navigation segments.

    The widget is GUI presentation only. Segment activation emits the existing
    Main Window action identifier and does not execute suite, provider, storage,
    chart, analysis, or trading behavior.
    """

    segment_activated = Signal(str)

    def __init__(
        self,
        segments: tuple[SuiteNavigationSegment, ...] = DEFAULT_SUITE_NAVIGATION_SEGMENTS,
        *,
        theme: GuiTheme | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if len(segments) != 5:
            raise ValueError("Suite Navigation donut requires exactly five segments")
        self._segments = segments
        self._theme = theme if theme is not None else load_default_theme()
        self._hovered_index: int | None = None
        self._pressed_index: int | None = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Suite Navigation")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(260, 260))
        font = QFont(self._theme.typography.base_font_family)
        font.setPointSize(self._theme.typography.small_font_size)
        self.setFont(font)

    @property
    def theme_id(self) -> str:
        """Return the theme profile consumed by this widget."""

        return self._theme.theme_id

    def segments(self) -> tuple[SuiteNavigationSegment, ...]:
        """Return configured segments in clockwise display order."""

        return self._segments

    def segment_count(self) -> int:
        """Return the number of donut segments."""

        return len(self._segments)

    def geometry_model(self) -> SuiteNavigationDonutGeometry:
        """Return deterministic geometry for the current widget size."""

        return calculate_suite_navigation_donut_geometry(
            width=self.width(),
            height=self.height(),
            margin=self._theme.spacing.md,
        )

    def segment_at_point(self, point: QPoint | QPointF) -> SuiteNavigationSegment | None:
        """Return the segment containing a point, or ``None`` outside the ring."""

        index = self.segment_index_at_point(point)
        if index is None:
            return None
        return self._segments[index]

    def segment_index_at_point(self, point: QPoint | QPointF) -> int | None:
        """Return the segment index containing a point, or ``None`` outside the ring."""

        geometry = self.geometry_model()
        dx = float(point.x()) - geometry.center_x
        dy = float(point.y()) - geometry.center_y
        distance = hypot(dx, dy)
        if distance < geometry.inner_radius or distance > geometry.outer_radius:
            return None

        angle_from_top_clockwise = (degrees(atan2(dy, dx)) + 90.0) % 360.0
        index = int(angle_from_top_clockwise // SEGMENT_DEGREES)
        if index >= len(self._segments):
            return len(self._segments) - 1
        return index

    def activation_point_for_action_id(self, action_id: str) -> QPoint:
        """
        Return a deterministic point inside the segment for a Main Window action.

        The method supports focused GUI tests without exposing Qt internals or
        invoking action behavior directly.
        """

        for index, segment in enumerate(self._segments):
            if segment.action_id == action_id:
                return self._point_for_segment_index(index)
        raise KeyError(f"Unknown Suite Navigation action: {action_id}")

    def sizeHint(self) -> QSize:
        """Return the preferred donut display size."""

        return QSize(360, 360)

    def minimumSizeHint(self) -> QSize:
        """Return the minimum useful donut display size."""

        return QSize(260, 260)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Update hover feedback and tooltip for the segment under the pointer."""

        index = self.segment_index_at_point(event.position())
        if index != self._hovered_index:
            self._hovered_index = index
            tooltip = "" if index is None else self._segments[index].label
            self.setToolTip(tooltip)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Clear hover state when the pointer leaves the donut."""

        self._hovered_index = None
        self._pressed_index = None
        self.setToolTip("")
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Record the pressed segment for release-time activation."""

        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_index = self.segment_index_at_point(event.position())
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Emit the existing action ID when press and release hit the same segment."""

        if event.button() == Qt.MouseButton.LeftButton:
            released_index = self.segment_index_at_point(event.position())
            pressed_index = self._pressed_index
            self._pressed_index = None
            self.update()
            if released_index is not None and released_index == pressed_index:
                self.segment_activated.emit(self._segments[released_index].action_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Paint the theme-token-backed donut segments."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = self._segment_colors()
        geometry = self.geometry_model()
        for index, segment in enumerate(self._segments):
            fill = QColor(colors[index % len(colors)])
            if index == self._hovered_index:
                fill = fill.lighter(118)
            if index == self._pressed_index:
                fill = fill.darker(118)
            fill.setAlpha(190)

            path = _segment_path(geometry, index)
            painter.fillPath(path, fill)
            painter.setPen(QPen(QColor(self._theme.colors.border_active), 1.4))
            painter.drawPath(path)
            self._draw_segment_label(painter, geometry, index, segment.short_label)
        super().paintEvent(event)

    def _draw_segment_label(
        self,
        painter: QPainter,
        geometry: SuiteNavigationDonutGeometry,
        index: int,
        text: str,
    ) -> None:
        label_center = self._point_for_segment_index(index)
        label_rect = QRectF(
            label_center.x() - 46.0,
            label_center.y() - 14.0,
            92.0,
            28.0,
        )
        painter.setPen(QPen(QColor(self._theme.colors.text_primary)))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _point_for_segment_index(self, index: int) -> QPoint:
        geometry = self.geometry_model()
        radius = (geometry.inner_radius + geometry.outer_radius) / 2.0
        angle = radians(-90.0 + index * SEGMENT_DEGREES + SEGMENT_DEGREES / 2.0)
        x = geometry.center_x + cos(angle) * radius
        y = geometry.center_y + sin(angle) * radius
        return QPoint(round(x), round(y))

    def _segment_colors(self) -> tuple[str, ...]:
        colors = self._theme.colors
        return (
            colors.accent_primary,
            colors.accent_secondary,
            colors.accent_tertiary,
            colors.info,
            colors.warning,
        )


def calculate_suite_navigation_donut_geometry(
    *,
    width: int,
    height: int,
    utility_row_height: int = 0,
    spacing: int = 0,
    margin: int = 0,
) -> SuiteNavigationDonutGeometry:
    """
    Calculate deterministic donut geometry from a Suite Navigation panel size.

    ``utility_row_height`` and ``spacing`` reserve the bottom utility row area
    used by Runtime Manager and Settings controls before the outer diameter is
    calculated.
    """

    available_width = max(0, width - margin * 2)
    available_height = max(0, height - utility_row_height - spacing - margin * 2)
    base_diameter = min(available_width, available_height)
    outer_diameter = max(0.0, base_diameter * OUTER_DIAMETER_SCALE)
    inner_diameter = outer_diameter * INNER_DIAMETER_RATIO
    return SuiteNavigationDonutGeometry(
        center_x=width / 2.0,
        center_y=margin + available_height / 2.0,
        outer_diameter=outer_diameter,
        inner_diameter=inner_diameter,
    )


def _segment_path(
    geometry: SuiteNavigationDonutGeometry,
    index: int,
) -> QPainterPath:
    outer_radius = geometry.outer_radius
    inner_radius = geometry.inner_radius
    outer_rect = QRectF(
        geometry.center_x - outer_radius,
        geometry.center_y - outer_radius,
        geometry.outer_diameter,
        geometry.outer_diameter,
    )
    inner_rect = QRectF(
        geometry.center_x - inner_radius,
        geometry.center_y - inner_radius,
        geometry.inner_diameter,
        geometry.inner_diameter,
    )
    start_angle = 90.0 - index * SEGMENT_DEGREES
    path = QPainterPath()
    path.moveTo(geometry.center)
    path.arcTo(outer_rect, start_angle, -SEGMENT_DEGREES)
    path.closeSubpath()

    cutout = QPainterPath()
    cutout.addEllipse(inner_rect)
    return path.subtracted(cutout)
