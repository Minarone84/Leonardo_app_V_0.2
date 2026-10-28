"""Display immutable analysis outcomes and page observations without recalculation."""
from __future__ import annotations

import math
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QTabWidget,
    QSizePolicy, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from leonardo.gui.analysis.distribution_widget import DistributionWidget
from leonardo.gui.display_time import format_display_timestamp_ms
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table

_HEADERS = {
    "ts_ms": "Observation time", "available_at_ms": "Snapshot availability time",
    "raw_value": "Original value", "bin_label": "Bin", "band": "Band",
    "directional_percentile": "Within-direction percentile", "percentile": "Reference percentile",
    "conditional_small_tail_frequency": "Within-direction small-tail frequency",
    "conditional_large_tail_frequency": "Within-direction large-tail frequency",
    "whole_small_tail_frequency": "Whole-reference small-tail frequency",
    "whole_large_tail_frequency": "Whole-reference large-tail frequency",
}
_FIRST = ("ts_ms", "raw_value", "direction", "bin_label", "band", "directional_percentile", "percentile", "status", "support_status")


def _display(value):
    if value is None or pd.isna(value):
        return "—"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


class ObservationModel(QAbstractTableModel):
    page_size = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()
        self.names = []
        self.page = 0

    def set_frame(self, frame):
        self.beginResetModel()
        self.frame = frame
        self.names = [name for name in _FIRST if name in frame] + [name for name in frame if name not in _FIRST]
        self.page = 0
        self.endResetModel()

    def set_page(self, page):
        self.beginResetModel()
        self.page = max(0, min(page, self.page_count - 1))
        self.endResetModel()

    @property
    def page_count(self):
        return max(1, math.ceil(len(self.frame) / self.page_size))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else min(self.page_size, max(0, len(self.frame) - self.page * self.page_size))

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.names)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        name = self.names[index.column()]
        value = self.frame.iloc[self.page * self.page_size + index.row()][name]
        if name in ("ts_ms", "available_at_ms"):
            return format_display_timestamp_ms(int(value))
        return _display(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.names):
            name = self.names[section]
            if role == Qt.ItemDataRole.ToolTipRole:
                return name
            if role == Qt.ItemDataRole.DisplayRole:
                return _HEADERS.get(name, name.replace("_", " ").capitalize())
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(self.page * self.page_size + section + 1)
        return None


class BinningResults(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        apply_identity(self, "analysis_suite.binning.results", object_type="widget")
        self._result = None
        self._current = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.source = QLabel("No results yet.", self)
        self.source.setWordWrap(True)
        layout.addWidget(self.source)
        self.column = QComboBox(self)
        self.column.setMinimumContentsLength(16)
        self.column.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        apply_identity(self.column, "analysis_suite.binning.result_column", object_type="combo_box")
        layout.addWidget(self.column)
        self.views = QTabWidget(self)
        self.views.setMinimumWidth(0)
        self.views.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.views.setUsesScrollButtons(True)
        self.views.setElideMode(Qt.TextElideMode.ElideRight)
        apply_identity(self.views, "analysis_suite.binning.views", object_type="tab_widget")
        layout.addWidget(self.views)
        distribution_page = QWidget(self.views)
        distribution_layout = QVBoxLayout(distribution_page)
        self.chart = DistributionWidget(distribution_page)
        distribution_layout.addWidget(self.chart)
        self.distribution_note = QLabel(distribution_page)
        self.distribution_note.setWordWrap(True)
        distribution_layout.addWidget(self.distribution_note)
        self.views.addTab(distribution_page, "Distribution")
        bins_page = QWidget(self.views)
        bins_layout = QVBoxLayout(bins_page)
        note = QLabel("Observed ranges describe assigned historical values; they are not continuous decision thresholds. Empty bins are retained.", bins_page)
        note.setWordWrap(True)
        bins_layout.addWidget(note)
        self.bins = configure_table(QTableWidget(bins_page), object_id="analysis_suite.binning.bins", columns=(
            "Direction", "Bin / Band", "Percentile from", "Percentile to", "Count", "Observed signed minimum", "Observed signed maximum", "Support"))
        self.bins.setMinimumWidth(0)
        bins_layout.addWidget(self.bins)
        self.views.addTab(bins_page, "Bins / Bands")
        self.diagnostics = configure_table(QTableWidget(self.views), object_id="analysis_suite.binning.diagnostics", columns=("Field", "Value"))
        self.diagnostics.setMinimumWidth(0)
        self.views.addTab(self.diagnostics, "Diagnostics")
        observations_page = QWidget(self.views)
        observations_layout = QVBoxLayout(observations_page)
        self.observations = QTableView(observations_page)
        apply_identity(self.observations, "analysis_suite.binning.observations", object_type="table")
        self.observations.setMinimumWidth(0)
        self.observations.setWordWrap(False)
        self.model = ObservationModel(self.observations)
        self.observations.setModel(self.model)
        observations_layout.addWidget(self.observations)
        navigation = QHBoxLayout()
        self.previous = QPushButton("Previous", observations_page)
        self.next = QPushButton("Next", observations_page)
        self.page = QSpinBox(observations_page)
        self.page.setMinimum(1)
        self.page_label = QLabel(observations_page)
        for key, widget in (("previous", self.previous), ("next", self.next), ("page", self.page)):
            apply_identity(widget, f"analysis_suite.binning.observations.{key}", object_type="control")
            navigation.addWidget(widget)
        navigation.addWidget(self.page_label)
        observations_layout.addLayout(navigation)
        self.views.addTab(observations_page, "Observations")
        self.views.setMinimumHeight(320)
        self.column.currentIndexChanged.connect(self._select_column)
        self.page.valueChanged.connect(self._page_changed)
        self.previous.clicked.connect(lambda: self.page.setValue(self.page.value() - 1))
        self.next.clicked.connect(lambda: self.page.setValue(self.page.value() + 1))
        self.clear()

    def clear(self, message="No results yet. Select columns and run analysis."):
        self._result = None
        self._current = None
        with QSignalBlocker(self.column):
            self.column.clear()
        self.source.setText(message)
        self.bins.setRowCount(0)
        self.diagnostics.setRowCount(0)
        self.chart.set_distribution(None)
        self.distribution_note.clear()
        self.model.set_frame(pd.DataFrame())
        self._sync_page()

    def set_result(self, result):
        self.clear()
        self._result = result
        reference = result.entry.reference
        self.source.setText(f"{result.entry.name} · revision {reference.revision_id[:12]}\nFull-history retrospective analysis · {len(result.columns)} columns")
        self.source.setToolTip(f"Database: {reference.database_id}\nRevision: {reference.revision_id}\nValues: {reference.values_sha256}")
        with QSignalBlocker(self.column):
            for column in result.columns:
                self.column.addItem(f"{column.request.source} · {column.request.measurement} · {column.outcome.replace('_', ' ')}")
        self._select_column()

    def _select_column(self, *_args):
        index = self.column.currentIndex()
        if self._result is None or index < 0:
            return
        column = self._result.columns[index]
        self._current = column
        self.chart.set_distribution(column.distribution)
        detail = "Reduced drawing detail; all observations were used for calibration." if column.distribution.reduced else "All distinct values drawn."
        summaries = [f"{key}: {_display(value)}" for key, value in column.diagnostics
                     if key in ("Positive magnitude median", "Negative magnitude median", "Positive support", "Negative support")]
        self.distribution_note.setText(f"{column.distribution.finite_count:,} finite observations · {column.distribution.distinct_count:,} distinct values. {detail}\n" + "\n".join(summaries))
        self.bins.setRowCount(len(column.bins))
        for row, value in enumerate(column.bins):
            for col, text in enumerate((value.direction, value.label, value.percentile_start, value.percentile_end,
                                       value.count, value.observed_minimum, value.observed_maximum, value.support)):
                item = QTableWidgetItem(_display(text))
                item.setToolTip(item.text())
                self.bins.setItem(row, col, item)
        self.bins.resizeColumnsToContents()
        self._render_diagnostics()
        self.model.set_frame(column.to_frame())
        self.observations.resizeColumnsToContents()
        self._sync_page()

    def _render_diagnostics(self):
        if self._current is None:
            return
        values = self._current.diagnostics
        self.diagnostics.setRowCount(len(values))
        for row, (key, value) in enumerate(values):
            if key.endswith("timestamp"):
                value = format_display_timestamp_ms(value)
            for col, text in enumerate((key, value)):
                item = QTableWidgetItem(_display(text))
                item.setToolTip(item.text())
                self.diagnostics.setItem(row, col, item)
        self.diagnostics.setColumnWidth(0, 195)
        self.diagnostics.setColumnWidth(1, 470)

    def _page_changed(self, page):
        self.model.set_page(page - 1)
        self._sync_page()

    def _sync_page(self):
        with QSignalBlocker(self.page):
            self.page.setRange(1, self.model.page_count)
            self.page.setValue(self.model.page + 1)
        self.page_label.setText(f"of {self.model.page_count:,} · {len(self.model.frame):,} rows")
        self.previous.setEnabled(self.model.page > 0)
        self.next.setEnabled(self.model.page + 1 < self.model.page_count)

    def refresh_display_time(self):
        self._render_diagnostics()
        self.model.set_page(self.model.page)
