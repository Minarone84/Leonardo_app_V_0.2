"""Event/context selection; analytical truth remains in the Analysis area."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from PySide6.QtCore import QDateTime, QSignalBlocker, Qt, QTimeZone, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)
from leonardo.analysis.pattern_models import (
    ORIGINS, PatternRequest, PatternRefinement, NumericCondition,
    PrecedingContextFilter, PullbackFilter,
)
from leonardo.gui.display_time import current_display_time_zone_name
from .trend_start_results import TrendStartResults, identify
from .pre_event_pattern_controls import PreEventPatternControls


_MOVEMENTS = (("Net movement in trend direction", "directional_move"),
              ("Signed endpoint movement", "signed_move"),
              ("Favorable pivot excursion", "pivot_favorable"),
              ("Adverse pivot excursion", "pivot_adverse"), ("Pivot price span", "pivot_span"))
_DURATIONS = (("Structural duration", "structural"), ("Endpoint extension", "endpoint_extension"),
              ("Observed elapsed duration", "observed_elapsed"), ("Formation confirmation delay", "confirmation_delay"))
_PULLBACKS = (("Member count", "count"), ("Depth", "depth"),
              ("Total duration of recovered pullbacks", "recovered_duration"))
_TIME_UNITS = (("Milliseconds", "ms"), ("Seconds", "seconds"), ("Minutes", "minutes"),
               ("Hours", "hours"), ("Days", "days"))
_COHORTS = (("Recovered inside the structural interval", "internal_recovered"),
            ("Recovered during formation", "formation_recovered"),
            ("Pending at the formation boundary", "formation_pending_at_boundary"),
            ("All observed (includes incomplete / endpoint context)", "all_observed"),
            ("Launched during continuation", "continuation_started"),
            ("Recovered during continuation", "recovered_during_continuation"),
            ("Currently pending", "currently_pending"),
            ("Pending with an internal launch", "pending_internal_launch"),
            ("Crossing or after the structural endpoint", "endpoint_context"),
            ("Ended without recovery", "ended_unrecovered"), ("Interrupted", "interrupted"))


def _bounded_combo(combo):
    combo.setMinimumContentsLength(12)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    return combo


class NumericFilterRow(QWidget):
    """Collect explicit bounds; the Analysis model validates their meaning."""
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, kind, number, parent=None, *, identity_prefix="refinement"):
        super().__init__(parent)
        self.kind = kind
        self._retain_empty = False
        key = f"{identity_prefix}.{kind}.{number}"
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 4)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.field = identify(QComboBox(self), key+".measure")
        self.unit = identify(QComboBox(self), key+".unit")
        self.statistic = identify(QComboBox(self), key+".statistic")
        for combo in (self.field, self.unit, self.statistic):
            _bounded_combo(combo)
        for text, value in ((_MOVEMENTS if kind == "movement" else _DURATIONS if kind == "duration" else _PULLBACKS)):
            self.field.addItem(text, value)
        self.statistic.addItem("Maximum", "maximum")
        self.statistic.addItem("Mean", "mean")
        self.minimum = identify(QLineEdit(self), key+".minimum")
        self.maximum = identify(QLineEdit(self), key+".maximum")
        self.minimum.setPlaceholderText("No minimum")
        self.maximum.setPlaceholderText("No maximum")
        for editor in (self.minimum, self.maximum):
            editor.setToolTip("Inclusive bound. Blank is unbounded; zero is a real value. Scientific notation is accepted.")
        self.remove = identify(QPushButton("Remove condition", self), key+".remove", action=True)
        form.addRow("Measure", self.field)
        self.statistic_label = QLabel("Statistic", self)
        form.addRow(self.statistic_label, self.statistic)
        form.addRow("Unit", self.unit)
        bounds = QHBoxLayout()
        bounds.addWidget(QLabel("Minimum", self)); bounds.addWidget(self.minimum)
        bounds.addWidget(QLabel("Maximum", self)); bounds.addWidget(self.maximum)
        form.addRow(bounds)
        form.addRow(self.remove)
        self.field.currentIndexChanged.connect(self._field_changed)
        for combo in (self.unit, self.statistic):
            combo.currentIndexChanged.connect(self.changed)
        for editor in (self.minimum, self.maximum):
            editor.textChanged.connect(self.changed)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))
        self._field_changed()

    def _field_changed(self, *_):
        field = self.field.currentData()
        old = self.unit.currentData()
        if self.kind == "movement" or field == "depth":
            units = (("Percent", "pct"), ("Points", "points"))
        elif field == "count":
            units = (("Members", "count"),)
        elif field == "confirmation_delay":
            units = _TIME_UNITS
        else:
            units = (("Stored bars", "bars"), *_TIME_UNITS)
        with QSignalBlocker(self.unit):
            self.unit.clear()
            for text, value in units:
                self.unit.addItem(text, value)
            index = self.unit.findData(old)
            if index >= 0:
                self.unit.setCurrentIndex(index)
        aggregate = self.kind == "pullbacks" and field != "count"
        self.statistic.setVisible(aggregate)
        self.statistic_label.setVisible(aggregate)
        self.changed.emit()

    def value(self):
        def bound(editor):
            text = editor.text().strip()
            if not text:
                return None
            try:
                value = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError("Refinement bounds must be numbers.") from exc
            if not value.is_finite():
                raise ValueError("Refinement bounds must be finite numbers.")
            return value
        lower, upper = bound(self.minimum), bound(self.maximum)
        if lower is None and upper is None and not self._retain_empty:
            return None
        return NumericCondition(self.field.currentData(), self.unit.currentData(), lower, upper,
            self.statistic.currentData() if self.kind == "pullbacks" and self.field.currentData() != "count" else None)


class NumericFilterGroup(QGroupBox):
    changed = Signal()

    def __init__(self, title, kind, parent=None, *, identity_prefix="refinement"):
        super().__init__(title, parent)
        identify(self, identity_prefix+"."+kind+".enabled")
        self.kind, self.rows, self._next = kind, [], 0
        self._identity_prefix = identity_prefix
        self.setCheckable(True)
        self.setChecked(False)
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(10, 24, 10, 10)
        self.add_button = identify(QPushButton("Add condition", self), identity_prefix+"."+kind+".add", action=True)
        self.stack.addWidget(self.add_button)
        self.add_button.clicked.connect(self.add_row)
        self.toggled.connect(self.changed)
        self.add_row()

    def add_row(self, *_):
        row = NumericFilterRow(self.kind, self._next, self, identity_prefix=self._identity_prefix)
        self._next += 1
        self.rows.append(row)
        self.stack.insertWidget(self.stack.count()-1, row)
        row.changed.connect(self.changed)
        row.remove_requested.connect(self.remove_row)
        self.changed.emit()
        return row

    def remove_row(self, row):
        self.rows.remove(row)
        self.stack.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.changed.emit()

    def conditions(self, *, include_disabled=False):
        if not self.isChecked() and not include_disabled:
            return ()
        return tuple(value for row in self.rows if (value := row.value()) is not None)

    def reset(self):
        with QSignalBlocker(self):
            self.setChecked(False)
            for row in tuple(self.rows):
                self.remove_row(row)
            self.add_row()


class RefinementControls(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *, identity_prefix="refinement", family_scoping=False):
        super().__init__(parent)
        self._applying = True
        self._previous_families = ()
        self._retain_disabled = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.toggle = identify(QToolButton(self), identity_prefix+".expand")
        self.toggle.setText("Refine selected starts")
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        root.addWidget(self.toggle)
        self.body = QWidget(self)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.body.hide()
        root.addWidget(self.body)
        self.toggle.toggled.connect(self._expand)
        self.note = QLabel("Optional historical context and outcome filters. Empty bounds have no effect. "
            "The same filters apply to both trend-family groups; ordinary non-start comparison requires filters off.", self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.basis = identify(QComboBox(self), identity_prefix+".basis")
        _bounded_combo(self.basis)
        for text, value in (("Completed trend · final outcome", "completed"),
                            ("Frozen formation · through first activation", "formation"),
                            ("Observed progress · may be incomplete", "observed")):
            self.basis.addItem(text, value)
        form.addRow("Measurement basis", self.basis)
        layout.addLayout(form)
        self.preceding = identify(QGroupBox("Preceding context", self), identity_prefix+".preceding.enabled")
        self.preceding.setCheckable(True); self.preceding.setChecked(False)
        prior = QFormLayout(self.preceding)
        prior.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        prior.setContentsMargins(10, 24, 10, 10)
        self.memberships = {}
        for key, title in (("up", "Prior row UP"), ("down", "Prior row DOWN"), ("range", "Prior row RANGE")):
            combo = identify(QComboBox(self), identity_prefix+".preceding."+key)
            _bounded_combo(combo)
            for text, value in (("Any", None), ("True", True), ("False", False)):
                combo.addItem(text, value)
            self.memberships[key] = combo
            prior.addRow(title, combo)
            combo.currentIndexChanged.connect(self._changed)
        self.previous_direction = identify(QComboBox(self), identity_prefix+".preceding.previous_direction")
        _bounded_combo(self.previous_direction)
        for text, value in (("Any previous episode", None), ("UP", "UP"), ("DOWN", "DOWN"),
                            ("No previous confirmed episode", "NONE")):
            self.previous_direction.addItem(text, value)
        self.previous_family = identify(QComboBox(self), identity_prefix+".preceding.previous_family")
        _bounded_combo(self.previous_family)
        self.previous_family.addItem("Any previous family", None)
        prior.addRow("Previous confirmed direction", self.previous_direction)
        prior.addRow("Previous exact family", self.previous_family)
        prior_note = QLabel("Memberships may overlap. Previous confirmed means scanner activation order; "
            "it need not have been known before the starting swing.", self)
        prior_note.setWordWrap(True)
        prior.addRow(prior_note)
        layout.addWidget(self.preceding)
        self.movement = NumericFilterGroup("Movement", "movement", self, identity_prefix=identity_prefix)
        self.duration = NumericFilterGroup("Duration", "duration", self, identity_prefix=identity_prefix)
        self.pullbacks = NumericFilterGroup("Internal pullbacks", "pullbacks", self, identity_prefix=identity_prefix)
        self.cohort = identify(QComboBox(self), identity_prefix+".pullbacks.cohort")
        _bounded_combo(self.cohort)
        for text, value in _COHORTS:
            self.cohort.addItem(text, value)
        self.pullbacks.stack.insertWidget(0, self.cohort)
        self.cohort.setToolTip("Cohorts can overlap. Total recovered duration includes descent (launch to recovery). "
            "Empty/partly supported statistics are unavailable, not zero.")
        for group in (self.movement, self.duration, self.pullbacks):
            layout.addWidget(group)
            group.changed.connect(self._changed)
        self.family_scope = None
        if family_scoping:
            from .family_scope_controls import FamilyScopeControls
            self.family_scope = FamilyScopeControls(self, identity_prefix=identity_prefix+".family_scope")
            layout.insertWidget(0, self.family_scope)
            self.family_scope.changed.connect(self._changed)
        self.clear_button = identify(QPushButton("Clear refinements", self), identity_prefix+".clear", action=True)
        layout.addWidget(self.clear_button)
        self.clear_button.clicked.connect(self.reset)
        self.basis.currentIndexChanged.connect(self._basis_changed)
        self.cohort.currentIndexChanged.connect(self._changed)
        self.preceding.toggled.connect(self._changed)
        self.previous_direction.currentIndexChanged.connect(self._previous_changed)
        self.previous_family.currentIndexChanged.connect(self._changed)
        self._applying = False

    def _expand(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _changed(self, *_):
        if not self._applying:
            self.changed.emit()

    def _basis_changed(self, *_):
        formation = self.basis.currentData() == "formation"
        old = self.cohort.currentData()
        with QSignalBlocker(self.cohort):
            self.cohort.clear()
            for text, value in _COHORTS:
                if not formation or value in ("all_observed", "internal_recovered", "formation_recovered", "formation_pending_at_boundary"):
                    self.cohort.addItem(text, value)
            default = "formation_recovered" if formation else "internal_recovered"
            self.cohort.setCurrentIndex(self.cohort.findData(default if old in ("formation_recovered", "internal_recovered") else old))
            if self.cohort.currentIndex() < 0:
                self.cohort.setCurrentIndex(self.cohort.findData(default))
        self._changed()

    def set_previous_families(self, families):
        self._previous_families = tuple(families)
        self._previous_changed(emit=False)

    def _previous_changed(self, *_, emit=True):
        old, direction = self.previous_family.currentData(), self.previous_direction.currentData()
        with QSignalBlocker(self.previous_family):
            self.previous_family.clear()
            self.previous_family.addItem("Any previous family", None)
            if direction in ("UP", "DOWN"):
                for family in self._previous_families:
                    if family.startswith(direction+"/"):
                        self.previous_family.addItem(family, family)
                index = self.previous_family.findData(old)
                if index >= 0:
                    self.previous_family.setCurrentIndex(index)
        self.previous_family.setEnabled(direction in ("UP", "DOWN"))
        if emit:
            self._changed()

    def value(self):
        return PatternRefinement(basis=self.basis.currentData(),
            preceding=PrecedingContextFilter(enabled=self.preceding.isChecked(),
                **{key: combo.currentData() for key, combo in self.memberships.items()},
                previous_direction=self.previous_direction.currentData(), previous_family=self.previous_family.currentData()),
            movement_enabled=self.movement.isChecked(), movement=self.movement.conditions(include_disabled=self._retain_disabled),
            duration_enabled=self.duration.isChecked(), duration=self.duration.conditions(include_disabled=self._retain_disabled),
            pullbacks=PullbackFilter(enabled=self.pullbacks.isChecked(), cohort=self.cohort.currentData(),
                                     conditions=self.pullbacks.conditions(include_disabled=self._retain_disabled)),
            family_scope=self.family_scope.value() if self.family_scope is not None else None)

    def set_value(self, value):
        if not isinstance(value, PatternRefinement):
            raise TypeError("refinement editor requires PatternRefinement")
        if self.family_scope is None and value.family_scope is not None:
            raise ValueError("This numerical editor does not own family selection")
        if self.family_scope is not None:
            self.family_scope.set_value(value.family_scope)
        self._applying = True
        self._retain_disabled = True
        try:
            def choose(combo, selected):
                index = combo.findData(selected)
                if index < 0:
                    combo.addItem(str(selected), selected)
                    index = combo.count()-1
                combo.setCurrentIndex(index)
            choose(self.basis, value.basis)
            self.preceding.setChecked(value.preceding.enabled)
            for key, combo in self.memberships.items():
                choose(combo, getattr(value.preceding, key))
            choose(self.previous_direction, value.preceding.previous_direction)
            choose(self.previous_family, value.preceding.previous_family)
            choose(self.cohort, value.pullbacks.cohort)
            for group, enabled, conditions in (
                    (self.movement, value.movement_enabled, value.movement),
                    (self.duration, value.duration_enabled, value.duration),
                    (self.pullbacks, value.pullbacks.enabled, value.pullbacks.conditions)):
                for row in tuple(group.rows):
                    group.remove_row(row)
                for condition in conditions:
                    row = group.add_row()
                    row._retain_empty = not condition.active
                    choose(row.field, condition.field)
                    choose(row.unit, condition.unit)
                    if condition.statistic is not None:
                        choose(row.statistic, condition.statistic)
                    row.minimum.setText("" if condition.minimum is None else str(condition.minimum))
                    row.maximum.setText("" if condition.maximum is None else str(condition.maximum))
                if not conditions:
                    group.add_row()
                group.setChecked(enabled)
        finally:
            self._applying = False
        self._changed()

    def reset(self):
        self._applying = True
        if self.family_scope is not None:
            self.family_scope.set_value(None)
        self.basis.setCurrentIndex(0)
        self.preceding.setChecked(False)
        for combo in (*self.memberships.values(), self.previous_direction, self.previous_family):
            combo.setCurrentIndex(0)
        for group in (self.movement, self.duration, self.pullbacks):
            group.reset()
        self.cohort.setCurrentIndex(self.cohort.findData("internal_recovered"))
        self._applying = False
        self._changed()


    def _gr05_set_context(self, context):
        if self.family_scope is not None:
            self.family_scope.set_context(context)


class TrendStartPatternsTab(QWidget):
    load_requested = Signal()
    run_requested = Signal()
    configuration_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry = None
        self._run_key = None
        self._catalogue = None
        self._applying = True
        self._connected = self._busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = identify(QScrollArea(self), "scroll")
        self.scroll.setWidgetResizable(True)
        content = QWidget(self.scroll)
        layout = QVBoxLayout(content)
        content_margins = layout.contentsMargins()
        layout.setContentsMargins(0, content_margins.top(), 0, content_margins.bottom())
        self.source = identify(QLabel(self), "source")
        self.source.setWordWrap(True)
        layout.addWidget(self.source)
        self.load_button = identify(QPushButton("Load UTC event catalogue", content), "load_catalogue", action=True)
        self.load_button.clicked.connect(self.load_requested)
        layout.addWidget(self.load_button)
        self.controls = QGroupBox("Define the event and its context", content)
        form = QFormLayout(self.controls)
        form.setContentsMargins(10, 26, 10, 10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode = self._combo("mode")
        self.mode.addItem("Existing patterns", "existing")
        self.mode.addItem("Pre-event combinations", "pre_event")
        form.addRow("Study mode", self.mode)
        self.utc = self._combo("utc_instance")
        self.event = self._combo("event_kind")
        self.event.addItem("Choose P or T…", None)
        self.event.addItem("Trough (T)", "T")
        self.event.addItem("Peak (P)", "P")
        self.role = identify(QLabel("Trend start · choose a swing", self), "role")
        self.family = self._combo("family")
        self.origin = self._combo("origin")
        self.origin.addItem("All origins", None)
        for origin in ORIGINS:
            self.origin.addItem(origin.replace("_", " ").capitalize(), origin)
        for name, widget in (("UTC instance", self.utc), ("Event", self.event), ("Role / trend", self.role),
                             ("Trend family", self.family), ("Origin", self.origin)):
            form.addRow(name, widget)
        self.utc_details = identify(QLabel(self), "utc_details")
        self.utc_details.setWordWrap(True)
        form.addRow(self.utc_details)
        self.start = identify(QDateTimeEdit(self), "start_date")
        self.end = identify(QDateTimeEdit(self), "end_date")
        for editor in (self.start, self.end):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss.zzz")
        self.date_zone = QLabel(self)
        form.addRow("Anchor dates from", self.start)
        form.addRow("Through (inclusive)", self.end)
        form.addRow(self.date_zone)
        window_row = QHBoxLayout()
        self.before = self._spin("before", 0, 100, 20)
        self.after = self._spin("after", 0, 100, 20)
        window_row.addWidget(QLabel("Before", self))
        window_row.addWidget(self.before)
        self.after_label = QLabel("After", self)
        window_row.addWidget(self.after_label)
        window_row.addWidget(self.after)
        form.addRow("Stored bars", window_row)
        self.columns = identify(QListWidget(self), "columns")
        self.columns.setMaximumHeight(125)
        form.addRow("Analyzed columns (1–8)", self.columns)
        self.comparison = self._combo("comparison")
        self.comparison.addItem("Other families of the same start event", "other_families")
        self.comparison.addItem("Non-start timestamps", "non_start")
        form.addRow("Compare with", self.comparison)
        sequence_row = QHBoxLayout()
        self.lengths = {}
        for length in range(1, 6):
            check = identify(QCheckBox(str(length), self), f"sequence_{length}")
            check.setChecked(length in (2, 3))
            check.toggled.connect(self._changed)
            sequence_row.addWidget(check)
            self.lengths[length] = check
        form.addRow("Sequence lengths", sequence_row)
        self.min_target = self._spin("min_target", 1, 1000000000, 20)
        self.min_comparison = self._spin("min_comparison", 1, 1000000000, 20)
        self.min_matches = self._spin("min_matches", 1, 1000000000, 5)
        form.addRow("Minimum target sample", self.min_target)
        form.addRow("Minimum comparison", self.min_comparison)
        form.addRow("Minimum matches", self.min_matches)
        layout.addWidget(self.controls)
        self.pre_event_controls = PreEventPatternControls(content)
        layout.addWidget(self.pre_event_controls)
        from .family_scope_controls import FamilyScopeControls
        self.family_scope = FamilyScopeControls(content, identity_prefix="pre_event.family_scope", initial=True)
        self._gr05_context_key = None
        layout.addWidget(self.family_scope)
        self.family_scope.changed.connect(self._changed)
        self.pre_event_controls.changed.connect(self._changed)
        self.mode.currentIndexChanged.connect(self._changed)
        self.refinement = RefinementControls(content)
        layout.addWidget(self.refinement)
        self.refinement.changed.connect(lambda: self._choices_changed(reset=False))
        self.context = identify(QLabel(self), "selection_context")
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        self.note = QLabel("Historical association: trend family membership is known only when UTC confirms the formation. "
            "Each construct keeps its own full-history bins. Dates filter event anchors; windows can extend beyond those dates.", content)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.run_button = identify(QPushButton("Analyze selected events", content), "run", action=True)
        self.run_button.clicked.connect(self.run_requested)
        layout.addWidget(self.run_button)
        self.results = TrendStartResults(content)
        from .pattern_refinement_controls import PatternRefinementControls
        self.post_refinement = PatternRefinementControls(content)
        self.results.views.addTab(self.post_refinement, "Pinned refinement")
        self.results.family_selected.connect(self._select_family)
        layout.addWidget(self.results)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll)
        self.utc.currentIndexChanged.connect(lambda *_: self._choices_changed(reset=True))
        self.event.currentIndexChanged.connect(lambda *_: self._choices_changed(reset=True))
        for control in (self.origin,):
            control.currentIndexChanged.connect(lambda *_: self._choices_changed(reset=False))
        for control in (self.start, self.end):
            control.dateTimeChanged.connect(lambda *_: self._choices_changed(reset=False))
        for control in (self.family, self.comparison):
            control.currentIndexChanged.connect(self._changed)
        for control in (self.before, self.after, self.min_target, self.min_comparison, self.min_matches):
            control.valueChanged.connect(self._changed)
        self.columns.itemChanged.connect(self._changed)
        self._applying = False
        self.clear_source()

    def _combo(self, key):
        combo = identify(QComboBox(self), key)
        combo.setMinimumContentsLength(14)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        return combo

    def _spin(self, key, minimum, maximum, value):
        spin = identify(QSpinBox(self), key)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def clear_source(self, message="Complete Variation & Binning to describe an event."):
        self._applying = True
        self._entry = self._run_key = self._catalogue = None
        self.mode.setCurrentIndex(0)
        self._gr05_context_key = None
        self.family_scope.set_context({}); self.family_scope.set_value(None)
        self.pre_event_controls.set_columns(())
        self.refinement.reset()
        self.columns.clear()
        self.utc.clear()
        self.utc.addItem("Load the UTC catalogue…", None)
        self.event.setCurrentIndex(0)
        self.family.clear()
        self.family.addItem("Choose event and UTC instance…", "__choose__")
        self.source.setText(message)
        self.source.setToolTip("")
        self.utc_details.clear()
        self.utc_details.setToolTip("")
        self.results.clear()
        self._applying = False
        self._sync()

    def set_source(self, entry, run_key, columns):
        columns = tuple(columns)
        self.clear_source()
        self._applying = True
        self._entry, self._run_key = entry, run_key
        self.source.setText(f"{entry.name} · pinned revision {entry.reference.revision_id[:12]}\nCompleted binning run · {len(columns)} independent columns")
        self.source.setToolTip(f"Database: {entry.reference.database_id}\nRevision: {entry.reference.revision_id}\nValues SHA-256: {entry.reference.values_sha256}\nBinning run: {run_key}")
        for name, mode, profile in columns:
            item = QListWidgetItem(f"{name} · {mode}", self.columns)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(f"Column: {name}\nMeasurement: {mode}\nProfile: {profile or 'No fitted profile'}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.pre_event_controls.set_columns(columns)
        self.pre_event_controls.set_dates(entry.first_timestamp_ms, entry.last_timestamp_ms)
        self._set_dates(entry.first_timestamp_ms, entry.last_timestamp_ms)
        self._applying = False
        self._sync()

    def set_catalogue(self, catalogue):
        if self._entry is None or catalogue.reference != self._entry.reference or catalogue.run_key != self._run_key:
            raise ValueError("UTC catalogue no longer matches the displayed binning run")
        self._applying = True
        self._catalogue = catalogue
        self.utc.clear()
        self.utc.addItem("Choose UTC instance…", None)
        for instance in catalogue.selection_instances():
            window = instance["parameters"].get("trend_fractal_window", "unknown")
            self.utc.addItem(f"{', '.join(instance['aliases'])} · P/T {window} · {instance['instance_id'][:10]}", instance["instance_id"])
            self.utc.setItemData(self.utc.count()-1, json.dumps({k:v for k,v in instance.items() if k != "events"}, indent=2), Qt.ItemDataRole.ToolTipRole)
        self._applying = False
        self._choices_changed(reset=True)
        if self.utc.count() == 1:
            self.utc_details.setText("No copied UTC classification is available. Import a classified UTC output through Data Manager and reload explicitly.")

    def clear_catalogue(self, message="Loading copied UTC evidence…"):
        self._applying = True
        self._catalogue = None
        self._gr05_context_key = None
        self.family_scope.set_context({}); self.family_scope.set_value(None)
        self.utc.clear()
        self.utc.addItem("Load the UTC catalogue…", None)
        self.family.clear()
        self.family.addItem("Choose event and UTC instance…", "__choose__")
        self.utc_details.setText(message)
        self.utc_details.setToolTip("")
        self.results.clear(message)
        self._applying = False
        self._sync()

    def _choices_changed(self, *, reset):
        if self._applying:
            return
        key = (self.utc.currentData(), self.event.currentData(), self.start.dateTime().toMSecsSinceEpoch(), self.end.dateTime().toMSecsSinceEpoch())
        if key != self._gr05_context_key:
            self.family_scope.set_context({}); self.family_scope.set_value(None)
            self._gr05_context_key = key
        old = self.family.currentData() if not reset else "__choose__"
        self._applying = True
        self.utc_details.clear()
        self.utc_details.setToolTip("")
        self.family.clear()
        self.family.addItem("Choose trend family…", "__choose__")
        if self._catalogue and self.utc.currentData() and self.event.currentData():
            instance = self._catalogue.selection_instance(self.utc.currentData())
            self.utc_details.setText(f"P/T window {instance['parameters'].get('trend_fractal_window', 'unknown')} · "
                f"range window {instance['parameters'].get('range_fractal_window', 'unknown')} · "
                f"{len(instance['providers'])} providers · {len(instance['legacy_intervals'])} legacy intervals · {instance['status']}")
            self.utc_details.setToolTip(json.dumps({k:v for k,v in instance.items() if k != "events"}, indent=2))
            self.family.addItem("All families (separate overview)", None)
            self.refinement.set_previous_families(sorted({e["family"] for e in instance["events"]}))
            invalid_refinement = False
            try:
                refinement = self.refinement.value()
            except (ValueError, TypeError):
                refinement = None
                invalid_refinement = True
            rows = self._catalogue.families(self.utc.currentData(), self.event.currentData(), origin=self.origin.currentData(),
                start_ms=self.start.dateTime().toMSecsSinceEpoch(), end_ms=self.end.dateTime().toMSecsSinceEpoch(), refinement=refinement)
            for row in rows:
                count = (f"{row['refined_starts']} / {row['original_starts']} starts after refinement"
                         if refinement is not None and refinement.active else f"{row['starts']} starts")
                if invalid_refinement:
                    count += " before refinement · fix invalid settings"
                self.family.addItem(f"{row['family']} · {count}", row["family"])
                self.family.setItemData(self.family.count()-1, json.dumps(row, indent=2), Qt.ItemDataRole.ToolTipRole)
            if old != "__choose__":
                index = self.family.findData(old)
                if index < 0 and old is not None:
                    self.family.addItem(f"{old} · 0 matching starts", old)
                    index = self.family.count()-1
                self.family.setCurrentIndex(index)
        elif self._catalogue is not None and self.utc.count() == 1:
            self.utc_details.setText("No copied UTC classification is available. Import a classified UTC output through Data Manager and reload explicitly.")
        self._applying = False
        self._changed()

    def _changed(self, *_):
        if self._applying:
            return
        self.results.clear("Event context changed. Run the study for this selection.")
        for length, check in self.lengths.items():
            check.setEnabled(not self._busy and length <= self.before.value()+1)
            if length > self.before.value()+1:
                with QSignalBlocker(check):
                    check.setChecked(False)
        self.configuration_changed.emit()
        self._sync()

    def request(self):
        scoped = self.mode.currentData() == "pre_event" and self.family_scope.mode.currentData() is not None
        if self._entry is None or self._catalogue is None or not self.utc.currentData() or not self.event.currentData() or (not scoped and self.family.currentIndex() < 1):
            raise ValueError("Choose a UTC instance, P or T, and a trend family.")
        kind = self.event.currentData()
        names = tuple(self.columns.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.columns.count())
                      if self.columns.item(i).checkState() == Qt.CheckState.Checked)
        pre_event = self.pre_event_controls.value(names) if self.mode.currentData() == "pre_event" else None
        from dataclasses import replace
        from leonardo.analysis.pattern_models import _gr05_resolve_scope
        refinement = self.refinement.value()
        if pre_event is not None:
            refinement = replace(refinement, family_scope=self.family_scope.value())
        request = PatternRequest(self._entry.reference, self._run_key, self.utc.currentData(), kind,
            "UP" if kind == "T" else "DOWN", names, self.start.dateTime().toMSecsSinceEpoch(), self.end.dateTime().toMSecsSinceEpoch(),
            family=None if scoped else self.family.currentData(), origin=self.origin.currentData(), before=self.before.value(), after=self.after.value(),
            sequence_lengths=() if pre_event is not None else tuple(n for n,c in self.lengths.items() if c.isChecked()),
            comparison=self.pre_event_controls.comparison.currentData() if pre_event is not None else self.comparison.currentData(),
            min_target=self.min_target.value(), min_comparison=self.min_comparison.value(), min_matches=self.min_matches.value(),
            refinement=refinement, pre_event=pre_event)
        if scoped:
            _gr05_resolve_scope(request, refinement, self.family_scope._context.get("families"))
        return request

    def set_execution_state(self, *, connected, busy):
        self._connected, self._busy = connected, busy
        self._sync()

    def _sync(self):
        pre_mode = self.mode.currentData() == "pre_event"
        self.family_scope.setVisible(pre_mode)
        self.family_scope.setEnabled(self._connected and not self._busy and self._entry is not None)
        self._gr05_refresh_context()
        self.family.setEnabled(not (pre_mode and self.family_scope.mode.currentData() is not None))
        self.pre_event_controls.setVisible(pre_mode)
        self.pre_event_controls.setEnabled(self._connected and not self._busy and self._entry is not None)
        names = tuple(self.columns.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.columns.count())
                      if self.columns.item(i).checkState() == Qt.CheckState.Checked)
        self.pre_event_controls.set_selected(names)
        self.before.setEnabled(not pre_mode)
        self.comparison.setEnabled(not pre_mode)
        self.after_label.setText("After (inspection only)" if pre_mode else "After")
        self.refinement.note.setText(
            "Change these filters after inspecting patterns, then rerun. Empty bounds have no effect. "
            "Different families: identical filters on both groups. Different completed outcomes: bounds split the same family. "
            "Ordinary timestamps: outcome bounds apply to targets only; use All origins and no preceding-context restrictions."
            if pre_mode else
            "Optional historical context and outcome filters. Empty bounds have no effect. "
            "The same filters apply to both trend-family groups; ordinary non-start comparison requires filters off.")
        self.load_button.setEnabled(self._connected and not self._busy and self._entry is not None)
        self.controls.setEnabled(self._connected and not self._busy and self._entry is not None)
        self.refinement.setEnabled(self._connected and not self._busy and self._entry is not None)
        self.family.setEnabled(self._catalogue is not None and self.utc.currentData() is not None and self.event.currentData() is not None
                               and not (pre_mode and self.family_scope.mode.currentData() is not None))
        kind = self.event.currentData()
        self.role.setText("Trend start · " + ("up_start / Uptrend" if kind == "T" else "down_start / Downtrend" if kind == "P" else "choose P or T"))
        for length, check in self.lengths.items():
            check.setEnabled(not pre_mode and not self._busy and length <= self.before.value()+1)
        self.results.set_busy(self._busy)
        try:
            request = self.request()
        except (ValueError, TypeError) as exc:
            self.context.setText(str(exc))
            self.context.setToolTip("")
            ready = False
        else:
            self.context.setText(f"{request.event_kind} / {request.role_label} / {request.family or 'All families, separate groups'}\n"
                f"{request.origin or 'All origins'} · {len(request.columns)} columns · {request.before} bars before / {request.after} after {request.anchor_label}")
            self.context.setToolTip(f"UTC: {request.instance_id}\nRevision: {request.reference.revision_id}\nBinning run: {request.run_key}")
            if request.refinement.active:
                self.context.setText(self.context.text()+"\n"+request.refinement.summary())
            if request.pre_event is not None:
                spec = request.pre_event
                self.context.setText(f"Find combinations from {len(request.columns)} columns at offsets "
                    f"{spec.offsets[0]} to {spec.offsets[-1]} before {request.role_label} / {request.refinement.family_scope.summary() if request.refinement.family_scope is not None else request.family or 'All families, separate overview'}.\n"
                    f"Compare: {self.pre_event_controls.comparison.currentText()}. Shared neighboring tolerance: {spec.tolerance}; "
                    f"overrides: {dict(spec.overrides) or 'none'}. After-event window: inspection only.\n"+request.refinement.summary()+
                    "\nAfter the first pattern check, change filters and rerun to refine these populations.")
                if len(request.columns) < 2 or spec.history < 2:
                    self.context.setText(self.context.text()+"\nPrimary combinations disabled: select at least two columns and two history bars. Single baselines remain available.")
            if request.refinement.family_scope is not None:
                self.context.setText(self.context.text()+"\nAPPLIED INITIAL SELECTION: "+request.refinement.family_scope.summary()+
                    "\nExisting exact/overview selector is not applied. Pooled frequencies use pooled counts; family mix can change the result.")
            instance = self._catalogue.selection_instance(request.instance_id)
            ready = instance["status"] == "available"
        self.run_button.setEnabled(self._connected and not self._busy and ready)

    def _select_family(self, family):
        index = self.family.findData(family)
        if index >= 0:
            self.family.setCurrentIndex(index)
            self.context.setText(self.context.text()+"\nRun the study to compare this exact family.")

    def _set_dates(self, first, last):
        zone = QTimeZone(current_display_time_zone_name().encode())
        self.date_zone.setText("Anchor dates in " + current_display_time_zone_name())
        for editor, value in ((self.start, first), (self.end, last)):
            with QSignalBlocker(editor):
                editor.setTimeZone(zone)
                editor.setDateTime(QDateTime.fromMSecsSinceEpoch(value, zone))

    def refresh_display_time(self):
        if self._entry is not None:
            self._set_dates(self.start.dateTime().toMSecsSinceEpoch(), self.end.dateTime().toMSecsSinceEpoch())
        self.results.refresh_display_time()
        self.pre_event_controls.refresh_display_time()
        self.post_refinement.refresh_display_time()


    def _gr05_refresh_context(self):
        from leonardo.analysis.pre_event_cohorts import _gr05_family_universe
        from leonardo.analysis.pattern_models import FamilyScope
        if self._catalogue is None or not self.utc.currentData() or not self.event.currentData():
            self.family_scope.set_context({})
            return
        families = _gr05_family_universe(self._catalogue.selection_instance(self.utc.currentData())["events"],
            event_kind=self.event.currentData(), start_ms=self.start.dateTime().toMSecsSinceEpoch(), end_ms=self.end.dateTime().toMSecsSinceEpoch())
        family = self.family.currentData()
        selection = FamilyScope("exact", (family,)).to_dict() if family not in (None, "__choose__") else None
        self.family_scope.set_context(dict(families=families, direction="UP" if self.event.currentData()=="T" else "DOWN",
            comparison=self.pre_event_controls.comparison.currentData(), source_selection=selection))
