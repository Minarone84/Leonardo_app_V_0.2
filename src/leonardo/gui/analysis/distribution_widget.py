"""Draw an Analysis-supplied empirical CDF; no statistical decisions in Qt."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from leonardo.gui.windows.shell_widgets import apply_identity


class DistributionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        apply_identity(self, "analysis_suite.binning.distribution", object_type="chart")
        self.setMinimumHeight(210)
        self.setMinimumWidth(0)
        self._display = None

    def set_distribution(self, display):
        self._display = display
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101c27"))
        painter.setPen(QColor("#c7dbe8"))
        display = self._display
        if display is None or not display.points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No finite observations to display")
            return
        bounds = QRectF(48, 30, max(1, self.width() - 74), max(1, self.height() - 76))
        painter.drawText(QRectF(8, 2, self.width() - 16, 24), "Cumulative share of finite observations")
        painter.setPen(QPen(QColor("#294252"), 1))
        for fraction in (0.0, 0.5, 1.0):
            y = bounds.bottom() - fraction * bounds.height()
            painter.drawLine(QPointF(bounds.left(), y), QPointF(bounds.right(), y))
            painter.drawText(QRectF(0, y - 9, 43, 18), Qt.AlignmentFlag.AlignRight, f"{fraction:.0%}")
        first, last = display.points[0][0], display.points[-1][0]
        scale = max(abs(first), abs(last)) or 1.0
        low, high = first / scale, last / scale

        def x_position(value):
            return bounds.left() + bounds.width() * (0.5 if low == high else (value / scale - low) / (high - low))

        path = QPainterPath(QPointF(x_position(first), bounds.bottom()))
        previous_y = bounds.bottom()
        for value, probability in display.points:
            x = x_position(value)
            y = bounds.bottom() - probability * bounds.height()
            path.lineTo(x, previous_y)
            path.lineTo(x, y)
            previous_y = y
        painter.setPen(QPen(QColor("#50c7dd"), 2))
        painter.drawPath(path)
        painter.setPen(QColor("#c7dbe8"))
        painter.drawText(QRectF(bounds.left(), bounds.bottom() + 5, bounds.width(), 20),
                         Qt.AlignmentFlag.AlignLeft, f"{first:.6g}")
        painter.drawText(QRectF(bounds.left(), bounds.bottom() + 5, bounds.width(), 20),
                         Qt.AlignmentFlag.AlignRight, f"{last:.6g}")
        painter.drawText(QRectF(bounds.left(), bounds.bottom() + 25, bounds.width(), 20),
                         Qt.AlignmentFlag.AlignCenter, "Original signed value")
