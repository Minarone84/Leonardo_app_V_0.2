"""Collect pre-event search settings; Analysis owns all matching and cohorts."""
from PySide6.QtCore import QDateTime, QSignalBlocker, QTimeZone, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateTimeEdit, QFormLayout, QGroupBox, QLabel, QSpinBox

from leonardo.analysis.pattern_models import PreEventSpec
from leonardo.gui.display_time import current_display_time_zone_name
from .trend_start_results import identify


class PreEventPatternControls(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Pre-event combinations", parent)
        self._columns = {}
        form = QFormLayout(self)
        form.setContentsMargins(10, 26, 10, 10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.history = self._spin("history", 1, 100, 6)
        self.lead = self._spin("lead", 1, 100, 1)
        self.max_terms = self._spin("max_terms", 2, 4, 3)
        self.tolerance = self._combo("tolerance", (("Exact labels", 0), ("Include one neighboring bin", 1)))
        self.comparison = self._combo("comparison", (
            ("Different formation families", "other_families"),
            ("Different completed outcomes in the selected family scope", "other_outcomes"),
            ("Ordinary historical timestamps", "non_start"),
            ("Recurrence only (no comparison)", "recurrence")))
        for title, widget in (("History length (bars)", self.history), ("Lead before event (bars)", self.lead),
                              ("Maximum conditions", self.max_terms), ("Shared tolerance", self.tolerance),
                              ("Comparison question", self.comparison)):
            form.addRow(title, widget)
        self.override_box = QGroupBox("Per-column tolerance", self)
        self.override_form = QFormLayout(self.override_box)
        self.override_form.setContentsMargins(10, 26, 10, 10)
        self.override_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(self.override_box)
        self.chronological = identify(QCheckBox("Discover earlier, inspect later", self), "pre_event.chronological")
        self.custom_split = identify(QCheckBox("Choose the split date (otherwise 70% / 30% of rows)", self), "pre_event.custom_split")
        self.split = identify(QDateTimeEdit(self), "pre_event.split")
        self.split.setCalendarPopup(True)
        self.split.setDisplayFormat("yyyy-MM-dd HH:mm:ss.zzz")
        self.zone = QLabel(self)
        for widget in (self.chronological, self.custom_split, self.split, self.zone):
            form.addRow(widget)
        self.candidate_limit = self._spin("candidate_limit", 1, 100000, 100000)
        self.memory_limit = self._spin("memory_mib", 1, 128, 128)
        form.addRow("Candidate limit", self.candidate_limit)
        form.addRow("Match-state limit (MiB)", self.memory_limit)
        self.note = QLabel("Only negative offsets are searched. Tolerance stays within each column's own sign bins; "
            "zero is exact and missing labels never match. Later-period counts describe retrospective stability. "
            "After reviewing patterns, change the filters below and rerun to refine the analysis.", self)
        self.note.setWordWrap(True)
        form.addRow(self.note)
        self.chronological.toggled.connect(self._timing_changed)
        self.custom_split.toggled.connect(self._timing_changed)
        self.split.dateTimeChanged.connect(self.changed)
        self._timing_changed()

    def _spin(self, key, low, high, value):
        widget = identify(QSpinBox(self), "pre_event."+key)
        widget.setRange(low, high); widget.setValue(value)
        widget.valueChanged.connect(self.changed)
        return widget

    def _combo(self, key, choices):
        widget = identify(QComboBox(self), "pre_event."+key)
        widget.setMinimumContentsLength(14)
        widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for title, value in choices:
            widget.addItem(title, value)
        widget.currentIndexChanged.connect(self.changed)
        return widget

    def _timing_changed(self, *_):
        self.custom_split.setEnabled(self.chronological.isChecked())
        self.split.setEnabled(self.chronological.isChecked() and self.custom_split.isChecked())
        self.changed.emit()

    def set_columns(self, columns):
        while self.override_form.rowCount():
            self.override_form.removeRow(0)
        self._columns = {}
        for name, measurement, profile in columns:
            combo = self._combo("override."+name, (("Use shared default", None), ("Exact labels", 0), ("One neighbor", 1)))
            directional = measurement == "directional_intensity" and profile is not None
            if not directional:
                combo.setCurrentIndex(combo.findData(0))
                combo.setEnabled(False)
                combo.setToolTip("Exact only: ordered directional-bin metadata is unavailable for this column.")
            self.override_form.addRow(name, combo)
            self._columns[name] = combo

    def set_selected(self, names):
        for name, combo in self._columns.items():
            self.override_form.setRowVisible(combo, name in names)

    def value(self, names):
        overrides = tuple((name, self._columns[name].currentData()) for name in names
                          if name in self._columns and self._columns[name].currentData() is not None)
        return PreEventSpec(history=self.history.value(), lead=self.lead.value(), max_terms=self.max_terms.value(),
            tolerance=self.tolerance.currentData(), overrides=overrides, chronological=self.chronological.isChecked(),
            split_ms=self.split.dateTime().toMSecsSinceEpoch() if self.chronological.isChecked() and self.custom_split.isChecked() else None,
            candidate_limit=self.candidate_limit.value(), memory_limit_bytes=self.memory_limit.value()*1024*1024)

    def set_dates(self, first, last):
        zone = QTimeZone(current_display_time_zone_name().encode())
        with QSignalBlocker(self.split):
            self.split.setTimeZone(zone)
            self.split.setDateTime(QDateTime.fromMSecsSinceEpoch(first+(last-first)*7//10, zone))
        self.zone.setText("Split date in "+current_display_time_zone_name())

    def refresh_display_time(self):
        value = self.split.dateTime().toMSecsSinceEpoch()
        zone = QTimeZone(current_display_time_zone_name().encode())
        with QSignalBlocker(self.split):
            self.split.setTimeZone(zone)
            self.split.setDateTime(QDateTime.fromMSecsSinceEpoch(value, zone))
        self.zone.setText("Split date in "+current_display_time_zone_name())
