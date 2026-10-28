"""Paged presentation of supplied study tables and bounded event details."""
from __future__ import annotations

import json
import math
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpinBox, QTabWidget, QTableView, QVBoxLayout, QWidget,
)
from leonardo.gui.display_time import format_display_timestamp_ms
from leonardo.gui.windows.shell_widgets import apply_identity


def identify(widget, key, *, action=False):
    return apply_identity(widget, "analysis_suite.patterns."+key, object_type="control",
                          action_id="analysis_suite.patterns."+key if action else None)


def duration_text(value):
    """Milliseconds are elapsed time here, never a timezone-dependent instant."""
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    seconds = abs(float(value))/1000
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = [f"{int(n)} {unit}" for n, unit in ((days, "d"), (hours, "h"), (minutes, "min")) if n]
    if seconds or not parts:
        parts.append(f"{seconds:.9g} s")
    return sign+" ".join(parts)


def _duration_column(name):
    return name in ("elapsed_ms", "confirmation_delay_ms", "endpoint_extension_ms", "observed_elapsed_ms") or (
        name.endswith("_ms") and any(part in name for part in ("duration", "delay", "spacing", "delta")))


def _metric_lines(value, prefix="", *, duration_aggregate=False):
    """Render Analysis-supplied details without deriving financial measurements."""
    lines = []
    if isinstance(value, dict):
        for name, item in value.items():
            label = (prefix+" · " if prefix else "")+name.replace("_", " ")
            if isinstance(item, dict):
                lines.extend(_metric_lines(item, label, duration_aggregate=_duration_column(name)))
            elif isinstance(item, list):
                lines.append(label+": "+json.dumps(item, ensure_ascii=False))
            elif item is None:
                lines.append(label+": unavailable")
            elif duration_aggregate and name in ("mean", "maximum", "minimum", "sum"):
                lines.append(label+": "+duration_text(item))
            elif name.endswith("_ms") and not _duration_column(name):
                lines.append(label+": "+format_display_timestamp_ms(int(item)))
            elif _duration_column(name) or name == "ms":
                lines.append(label+": "+duration_text(item))
            else:
                lines.append(label+": "+str(item))
    else:
        lines.append(str(value))
    return lines


def _refinement_lines(detail, request):
    """A compact human-readable view; the complete copied evidence stays below."""
    if not detail.get("active"):
        return ["Refinements disabled. Original event eligibility applies."]
    value = lambda v: "unavailable" if v is None else f"{v:.9g}" if isinstance(v, float) else str(v)
    lines = ["Included after refinement" if detail["eligible"] else "Excluded after refinement",
             request.refinement.summary(), "Evidence: "+detail["resolution"].replace("_", " ")]
    lines.extend("Reason: "+reason.replace("_", " ") for reason in detail["reasons"])
    projection = detail.get("projection") or {}
    measured = projection.get("measurements")
    if measured:
        lines += ["", "SAVED OUTCOME · "+measured["status"].replace("_", " ")]
        movement = measured["structural"]["movement"]
        for title, boundary in (("Start (S)", measured["formation"]["movement"]["start"]),
                                ("Formation end (F)", measured["formation"]["interval_limit"]),
                                ("Structural endpoint (E)", movement["endpoint"]),
                                ("Observation limit (O)", measured["observation_limit"])):
            instant = boundary["ts_ms"]
            lines.append(title+": "+(format_display_timestamp_ms(instant) if instant is not None else "Unavailable"))
        if measured["basis"] == "formation":
            lines.append("Frozen formation: E and O coincide with F.")
        for title, name in (("Net directional movement", "directional_move"), ("Signed endpoint movement", "signed_move"),
                            ("Favorable pivot excursion", "pivot_favorable"), ("Adverse pivot excursion", "pivot_adverse"),
                            ("Pivot span", "pivot_span")):
            lines.append(f"{title}: {value(movement[name+'_points'])} points / {value(movement[name+'_pct'])} %")
        for title, item in (("Structural duration", measured["structural"]["duration"]),
                            ("Endpoint extension", measured.get("endpoint_extension")),
                            ("Observed elapsed", measured.get("observed_elapsed"))):
            if item is not None:
                lines.append(f"{title}: {value(item['bars'])} bars / {duration_text(item['ms'])}")
        lines.append("Formation confirmation delay: "+duration_text(measured["formation"]["confirmation_delay_ms"]))
        spacing = movement["spacing"]
        lines.append(f"Spacing: {spacing['row_count']} rows; gap {duration_text(spacing['min_delta_ms'])} to "
                     f"{duration_text(spacing['max_delta_ms'])}; uniform: {value(spacing['uniform'])}")
        cohort = request.refinement.pullbacks.cohort if request.refinement.pullbacks.active else (
            "formation_recovered" if request.refinement.basis == "formation" else "internal_recovered")
        summary = measured["pullback_summary"][cohort]
        lines += ["", "PULLBACKS · "+cohort.replace("_", " "), "Members: "+str(summary["count"])]
        for title, field, unit in (("Depth", "depth_points", "points"), ("Depth", "depth_pct", "%"),
                                   ("Total recovered duration", "recovered_duration_bars", "bars"),
                                   ("Total recovered duration", "recovered_duration_ms", "elapsed")):
            stats = summary[field]
            render = duration_text if unit == "elapsed" else value
            suffix = "" if unit == "elapsed" else " "+unit
            lines.append(f"{title}: mean {render(stats['mean'])}{suffix}; maximum {render(stats['maximum'])}{suffix}; "
                         f"supported members: {stats['eligible_count']}")
        lines.append("Recovered duration is launch to recovery. Cohorts can overlap.")
    membership = projection.get("membership")
    if membership:
        lines += ["", "PRECEDING ROW · retrospective membership"]
        flags = membership["preceding_membership"]
        lines.append("Unavailable at this segment start" if flags is None else
                     " · ".join(name+": "+str(flags[key]) for name, key in
                                (("UP", "uptrend"), ("DOWN", "downtrend"), ("RANGE", "horizontal_range"))))
    lineage = projection.get("lineage")
    if lineage:
        lines += ["Previous confirmed episode: "+(lineage["previous_direction"] or "none"),
                  "Previous family: "+(lineage["previous_formation_key"] or "none"),
                  "Previous confirmed refers to scanner order, not knowledge before this start."]
    lines += ["", "Full timings, individual pullbacks, coverage and provider identities are in the copied evidence below."]
    return lines


class StudyTableModel(QAbstractTableModel):
    page_size = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()
        self.page = 0
        self.heat_columns = set()
        self.tooltips = {}
        self.check_state = None
        self.check_change = None

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0 and self.check_state is not None:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if (role == Qt.ItemDataRole.CheckStateRole and index.isValid() and index.column() == 0
                and self.check_change is not None):
            identity = self.frame.iloc[self.page*self.page_size+index.row()]["pattern_id"]
            accepted = self.check_change(identity, value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value))
            if accepted:
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return accepted
        return False

    def set_frame(self, frame, *, heat_columns=(), tooltips=None):
        self.beginResetModel()
        self.frame = frame.copy(deep=True)
        self.page = 0
        self.heat_columns = set(heat_columns)
        self.tooltips = tooltips or {}
        self.endResetModel()

    def set_page(self, page):
        self.beginResetModel()
        self.page = min(max(0, page), self.page_count-1)
        self.endResetModel()

    @property
    def page_count(self):
        return max(1, math.ceil(len(self.frame)/self.page_size))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else min(self.page_size, max(0, len(self.frame)-self.page_size*self.page))

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.page*self.page_size+index.row()
        name = self.frame.columns[index.column()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0 and self.check_state is not None:
            return Qt.CheckState.Checked if self.check_state(self.frame.iloc[row]["pattern_id"]) else Qt.CheckState.Unchecked
        value = self.frame.iloc[row, index.column()]
        missing = value is None or pd.isna(value)
        if role == Qt.ItemDataRole.BackgroundRole and name in self.heat_columns and not missing:
            return QColor(32, 135, 152, int(25+180*float(value)))
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        if role == Qt.ItemDataRole.ToolTipRole and (row, name) in self.tooltips:
            return self.tooltips[row, name]
        if missing:
            return "—"
        if _duration_column(name):
            return duration_text(value) if role == Qt.ItemDataRole.DisplayRole else f"{value} milliseconds elapsed"
        if name.endswith("_ms"):
            return format_display_timestamp_ms(int(value))
        if name in self.heat_columns:
            return f"{100*float(value):.1f}%"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(self.page_size*self.page+section+1)
        if not 0 <= section < len(self.frame.columns):
            return None
        name = self.frame.columns[section]
        return name if role == Qt.ItemDataRole.ToolTipRole or name in self.heat_columns else name.replace("_", " ").capitalize()


class StudyTable(QWidget):
    selected = Signal(object)
    activated = Signal(object)

    def __init__(self, key, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = identify(QTableView(self), key+".table")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setMinimumWidth(0)
        self.table.setMinimumHeight(180)
        self.model = StudyTableModel(self.table)
        self.table.setModel(self.model)
        layout.addWidget(self.table)
        nav = QHBoxLayout()
        self.previous = identify(QPushButton("Previous", self), key+".previous")
        self.next = identify(QPushButton("Next", self), key+".next")
        self.page = identify(QSpinBox(self), key+".page")
        self.page.setMinimum(1)
        self.info = QLabel(self)
        for widget in (self.previous, self.page, self.next, self.info):
            nav.addWidget(widget)
        layout.addLayout(nav)
        self.previous.clicked.connect(lambda: self.page.setValue(self.page.value()-1))
        self.next.clicked.connect(lambda: self.page.setValue(self.page.value()+1))
        self.page.valueChanged.connect(self._page)
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self.selected.emit(self.current_row()))
        self.table.doubleClicked.connect(lambda *_: self.activated.emit(self.current_row()))
        self.set_frame(pd.DataFrame())

    def set_frame(self, frame, **kwargs):
        self.model.set_frame(frame, **kwargs)
        with QSignalBlocker(self.page):
            self.page.setRange(1, self.model.page_count)
            self.page.setValue(1)
        self._sync()
        for i, name in enumerate(frame.columns):
            self.table.setColumnWidth(i, 235 if name in ("family", "condition", "value", "event_id") or name.endswith("_ms") else 135)

    def _page(self, page):
        self.model.set_page(page-1)
        self._sync()

    def _sync(self):
        self.info.setText(f"{len(self.model.frame):,} rows · page {self.model.page+1}/{self.model.page_count}")
        self.previous.setEnabled(self.model.page > 0)
        self.next.setEnabled(self.model.page+1 < self.model.page_count)

    def current_row(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.frame.iloc[self.model.page*self.model.page_size+index.row()].to_dict()

    def refresh_display_time(self):
        self.model.layoutChanged.emit()


class TrendStartResults(QWidget):
    family_selected = Signal(str)
    matches_requested = Signal(str, str)
    pin_requested = Signal(object)
    pin_clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result = None
        self._busy = False
        self._pin_ids = set()
        self._occurrences = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.context = identify(QLabel("No event study yet.", self), "result_context")
        self.context.setWordWrap(True)
        root.addWidget(self.context)
        self.views = identify(QTabWidget(self), "views")
        self.views.setMinimumWidth(0)
        self.views.setUsesScrollButtons(True)
        self.views.setElideMode(Qt.TextElideMode.ElideRight)
        self.views.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        root.addWidget(self.views)
        self.families = StudyTable("families", self)
        self.families.activated.connect(self._family_activated)
        self.views.addTab(self.families, "Trend families")
        frequency_page = QWidget(self)
        frequency_layout = QVBoxLayout(frequency_page)
        self.column = identify(QComboBox(self), "result_column")
        self.family = identify(QComboBox(self), "result_family")
        for combo in (self.column, self.family):
            combo.setMinimumContentsLength(12)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            frequency_layout.addWidget(combo)
        self.frequency_note = QLabel("Each cell shows its observed frequency; hover for counts. Positive offsets describe aftermath.", self)
        self.frequency_note.setWordWrap(True)
        frequency_layout.addWidget(self.frequency_note)
        self.frequency = StudyTable("frequency", self)
        frequency_layout.addWidget(self.frequency)
        self.views.addTab(frequency_page, "Labels around event")
        pattern_page = QWidget(self)
        pattern_layout = QVBoxLayout(pattern_page)
        self.ranked = identify(QCheckBox("Show ranked candidates only", self), "ranked_only")
        self.pattern_kind = identify(QComboBox(self), "pattern_kind")
        self.pattern_kind.addItem("Combinations across columns and bars", "combination")
        self.pattern_kind.addItem("Single-condition baselines", "single baseline")
        self.pattern_kind.addItem("All retained candidates", None)
        self.pattern_note = QLabel(self)
        self.pattern_note.setWordWrap(True)
        pattern_layout.addWidget(self.ranked)
        pattern_layout.addWidget(self.pattern_kind)
        pattern_layout.addWidget(self.pattern_note)
        self.patterns = StudyTable("patterns", self)
        pattern_layout.addWidget(self.patterns)
        self.pattern_detail = identify(QPlainTextEdit(self), "pattern_detail")
        self.pattern_detail.setReadOnly(True)
        self.pattern_detail.setMaximumHeight(210)
        pattern_layout.addWidget(self.pattern_detail)
        self.pin_count = identify(QLabel(self), "pin_count")
        self.pin_count.setWordWrap(True)
        self.pin_selected = identify(QPushButton("Pin combinations for refinement", self), "pin_selected", action=True)
        self.pin_clear = identify(QPushButton("Clear pin selection", self), "pin_clear", action=True)
        for widget in (self.pin_count, self.pin_selected, self.pin_clear):
            pattern_layout.addWidget(widget)
        self.pin_selected.clicked.connect(lambda: self.pin_requested.emit(self.pin_selection()))
        self.pin_clear.clicked.connect(self.pin_clear_requested)
        self.target_matches = identify(QPushButton("Inspect matching starts", self), "target_matches", action=True)
        self.comparison_matches = identify(QPushButton("Inspect comparison matches", self), "comparison_matches", action=True)
        pattern_layout.addWidget(self.target_matches)
        pattern_layout.addWidget(self.comparison_matches)
        self.views.addTab(pattern_page, "Patterns")
        event_page = QWidget(self)
        event_layout = QVBoxLayout(event_page)
        self.event_note = QLabel("Select an event to inspect its actual observations and evidence.", self)
        self.event_note.setWordWrap(True)
        self.all_events = identify(QPushButton("Show all selected events", self), "all_events")
        event_layout.addWidget(self.event_note)
        event_layout.addWidget(self.all_events)
        self.occurrence_kind = identify(QComboBox(self), "occurrence_kind")
        for title, value in (("Tolerant matches", "matched"), ("Exact center matches", "exact_match"),
                ("Matches added by tolerance", "added_by_tolerance"), ("All assessable observations", "assessable"),
                ("Unavailable observations", "unavailable"), ("All cohort observations", "all")):
            self.occurrence_kind.addItem(title, value)
        self.partition = identify(QComboBox(self), "occurrence_partition")
        for title, value in (("Discovery period", "discovery"), ("Later period", "later"),
                              ("Excluded by timing", "excluded"), ("All partitions", None)):
            self.partition.addItem(title, value)
        event_layout.addWidget(self.occurrence_kind)
        event_layout.addWidget(self.partition)
        self.events = StudyTable("events", self)
        self.event_detail = identify(QLabel(self), "event_detail")
        self.event_detail.setWordWrap(True)
        self.metric_detail = identify(QPlainTextEdit(self), "event_metrics")
        self.metric_detail.setReadOnly(True)
        self.metric_detail.setMaximumHeight(230)
        self.metric_detail.setPlaceholderText("Saved UTC measurements and refinement reasons appear here.")
        self.window = StudyTable("event_window", self)
        self.evidence_text = identify(QPlainTextEdit(self), "event_evidence")
        self.evidence_text.setReadOnly(True)
        self.evidence_text.setMaximumHeight(130)
        for widget in (self.events, self.event_detail, self.metric_detail, self.window, self.evidence_text):
            event_layout.addWidget(widget)
        self.family_breakdown_status = identify(QLabel(self), "family_breakdown_status")
        self.family_breakdown_status.setWordWrap(True)
        self.family_breakdown_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.family_breakdown = StudyTable("family_breakdown", self)
        event_layout.addWidget(self.family_breakdown_status)
        event_layout.addWidget(self.family_breakdown)
        self.views.addTab(event_page, "Events")
        self.diagnostics = StudyTable("diagnostics", self)
        self.views.addTab(self.diagnostics, "Diagnostics")
        self.funnel = StudyTable("refinement_funnel", self)
        self.assignments = StudyTable("cohort_assignments", self)
        refinement_page = QWidget(self)
        refinement_layout = QVBoxLayout(refinement_page)
        refinement_layout.addWidget(self.funnel)
        refinement_layout.addWidget(self.assignments)
        self.views.addTab(refinement_page, "Refinement")
        self.views.setMinimumHeight(500)
        self.column.currentIndexChanged.connect(self._frequency)
        self.family.currentIndexChanged.connect(self._frequency)
        self.ranked.toggled.connect(self._patterns)
        self.pattern_kind.currentIndexChanged.connect(self._patterns)
        self.patterns.selected.connect(self._pattern_selected)
        self.occurrence_kind.currentIndexChanged.connect(self._filter_occurrences)
        self.partition.currentIndexChanged.connect(self._filter_occurrences)
        self.target_matches.clicked.connect(lambda: self._request_matches("target"))
        self.comparison_matches.clicked.connect(lambda: self._request_matches("comparison"))
        self.all_events.clicked.connect(self._all_events)
        self.events.selected.connect(self._event)
        self.clear()

    def clear(self, message="No event study yet."):
        self._pin_ids.clear()
        self.patterns.model.check_state = self.patterns.model.check_change = None
        self._result = None
        self._occurrences = None
        self.context.setText(message)
        self.context.setToolTip("")
        for table in (self.families, self.frequency, self.patterns, self.events, self.window, self.diagnostics, self.funnel, self.assignments, self.family_breakdown):
            table.set_frame(pd.DataFrame())
        self.evidence_text.clear()
        self.event_detail.clear()
        self.metric_detail.clear()
        self.family_breakdown_status.clear()
        self.event_note.setText("Select an event to inspect its actual observations and evidence.")
        self.pattern_note.clear()
        self.pattern_detail.clear()
        for widget in (self.pattern_kind, self.pattern_detail, self.occurrence_kind, self.partition, self.assignments):
            widget.hide()
        for combo in (self.column, self.family):
            with QSignalBlocker(combo):
                combo.clear()
        self._buttons()

    def set_result(self, result):
        self.clear()
        self._result = result
        self._context()
        r = result.request
        pre_mode = r.pre_event is not None
        if pre_mode:
            self.patterns.model.check_state = self._pin_ids.__contains__
            self.patterns.model.check_change = self._check_pin
        self.pattern_kind.setVisible(pre_mode)
        self.pattern_detail.setVisible(pre_mode)
        self.assignments.setVisible(pre_mode)
        self.patterns.model.page_size = 50 if pre_mode else 500
        self.target_matches.setText("Inspect target observations" if pre_mode else "Inspect matching starts")
        self.comparison_matches.setText("Inspect comparison observations" if pre_mode else "Inspect comparison matches")
        context = json.loads(result.context)
        self.families.set_frame(_gr05_display_families(context["family_population"]) if "family_population" in context else result.frame("families"))
        self.diagnostics.set_frame(result.frame("diagnostics"))
        self.funnel.set_frame(result.frame("refinement_funnel"))
        if pre_mode:
            self.assignments.set_frame(result.frame("cohort_assignments"))
        with QSignalBlocker(self.column), QSignalBlocker(self.family):
            self.column.addItems(list(r.columns))
            frequency = result.frame("frequencies")
            if not frequency.empty:
                self.family.addItems(sorted(set(frequency.family)))
        self._frequency()
        self._patterns()
        self._all_events()
        self._buttons()

    def _context(self):
        result = self._result
        if result is None:
            return
        context = json.loads(result.context)
        if "family_scope" in context:
            r = result.request
            self.context.setText(_gr05_scope_caption(context["family_scope"])+
                f"\n{context['database']} · revision {r.reference.revision_id[:12]} · {r.role_label} · UTC {r.instance_id[:12]}"+
                f"\nOriginal request selection: {r.refinement.family_scope.summary() if r.refinement.family_scope is not None else r.family}"+
                "\n"+context.get("definition_summary", context.get("refinement_summary", ""))+
                "\nPooled frequencies use pooled counts; family mix can change the result.\nRetrospective association; after-event rows are inspection only.")
            self.context.setToolTip(json.dumps(context, indent=2))
            return
        if result.granular_definition is not None:
            r=result.request
            text=("NEW DISCOVERY · granular filters\n"+context["definition_summary"]+
                f"\n{context['database']} · revision {r.reference.revision_id[:12]} · {r.role_label} · exact family {r.family}"+
                f"\nSearch parent: {context['search_parent']['checkpoint_id']}"+
                "\nLegacy filters are source provenance only. Family rows are descriptive; no family pooling.\nRetrospective association; after-event rows are inspection only.")
            self.context.setText(" ".join("\u200b".join(word[i:i+16] for i in range(0,len(word),16)) for word in text.split(" ")))
            self.context.setToolTip(json.dumps(context,indent=2))
            return
        r = result.request
        window_text = (f"offsets {r.pre_event.offsets[0]} to {r.pre_event.offsets[-1]} mined / {r.after} after for inspection"
                       if r.pre_event is not None else f"{r.before} bars before / {r.after} after {r.anchor_label}")
        self.context.setText(f"{r.event_kind} / {r.role_label} / {r.family or 'All families, separate groups'}\n"
            f"{context['database']} · revision {r.reference.revision_id[:12]} · UTC {r.instance_id[:12]}\n"
            f"P/T window {context['utc_parameters'].get('trend_fractal_window', 'unknown')} · "
            f"range window {context['utc_parameters'].get('range_fractal_window', 'unknown')} · {r.origin or 'All origins'} · {window_text}\n"
            f"Anchors: {format_display_timestamp_ms(r.start_ms)} — {format_display_timestamp_ms(r.end_ms)}\n"
            "Historical association · independent full-history construct profiles")
        self.context.setToolTip(json.dumps(context, indent=2))
        if r.refinement.active:
            self.context.setText(self.context.text()+"\n"+r.refinement.summary())
        if r.pre_event is not None:
            spec = r.pre_event
            self.context.setText(self.context.text()+f"\nPre-event combinations: offsets {spec.offsets[0]} to {spec.offsets[-1]}; "
                f"lead {spec.lead} bars. Aftermath is inspection only.\n"+
                ("Retrospective temporal stability. " if spec.chronological else "Full selected period discovery. ")+
                "Refine the filters above and rerun after inspecting these patterns.")

    def set_busy(self, busy):
        self._busy = busy
        self._buttons()

    def _buttons(self):
        enabled = self._result is not None and not self._busy
        selected = self.patterns.current_row() is not None
        self.target_matches.setEnabled(enabled and selected)
        self.comparison_matches.setEnabled(enabled and selected)
        self.all_events.setEnabled(enabled)
        self.families.setEnabled(not self._busy)
        for widget in (self.patterns, self.pattern_kind, self.ranked):
            widget.setEnabled(not self._busy)
        pre_mode = self._result is not None and self._result.request.pre_event is not None
        for widget in (self.pin_count, self.pin_selected, self.pin_clear):
            widget.setVisible(pre_mode)
        self.pin_selected.setEnabled(enabled and pre_mode and (self._result.request.family is not None or
                                     json.loads(self._result.context).get("family_scope") is not None)
                                     and bool(self.pin_selection()))
        self.pin_clear.setEnabled(not self._busy and bool(self._pin_ids))
        visible = set(self.patterns.model.frame.get("pattern_id", ()))
        hidden = len(self._pin_ids-visible)
        self.pin_count.setText(f"{len(self._pin_ids)} explicitly checked · {hidden} hidden by view filters. "
            + ("Selections persist across pages." if self._pin_ids else "No checkmarks: Pin uses the current row."))

    def pin_selection(self):
        if self._result is None or self._result.request.pre_event is None:
            return ()
        patterns = self._result.frame("patterns")
        if len(patterns.index) == 0:
            return ()
        selected = self._pin_ids
        if not selected:
            row = self.patterns.current_row()
            selected = {row["pattern_id"]} if row else set()
        return tuple(identity for identity in patterns.pattern_id if identity in selected)

    def _check_pin(self, identity, checked):
        if self._busy:
            return False
        if checked and identity not in self._pin_ids and len(self._pin_ids) >= 500:
            self.pin_count.setText("Maximum 500 pinned rules. Uncheck a rule before selecting another.")
            return False
        if checked:
            self._pin_ids.add(identity)
        else:
            self._pin_ids.discard(identity)
        self._buttons()
        return True

    def clear_pin_selection(self):
        self._pin_ids.clear()
        self.patterns.model.layoutChanged.emit()
        self._buttons()

    def _family_activated(self, row):
        if self._result is not None and (self._result.granular_definition is not None or "family_scope" in json.loads(self._result.context)):
            return
        if row and not self._busy:
            self.family_selected.emit(row["family"])

    def _frequency(self, *_):
        if self._result is None:
            return
        frame = self._result.frame("frequencies")
        if frame.empty:
            self.frequency.set_frame(frame)
            return
        frame = frame[(frame.column == self.column.currentText()) & (frame.family == self.family.currentText())]
        labels = sorted(set(frame.label.dropna()))
        rows, tips = [], {}
        for offset in sorted(set(frame.offset)):
            entries = frame[frame.offset == offset]
            first = entries.iloc[0]
            values = {r.label: r for r in entries.itertuples() if r.label is not None}
            row = {"offset": f"0 ({self._result.request.anchor_label})" if offset == 0 else str(offset)}
            for label in labels:
                found = values.get(label)
                row[label] = found.frequency if found is not None else 0.0 if first.assessable else None
                tips[len(rows), label] = (f"{int(found.matched) if found is not None else 0}/{first.assessable} assessable; "
                    f"{first.unavailable} unavailable; {first.gap_or_coverage_flags} gap/coverage flags. {first.statuses}")
            row.update(assessable=first.assessable, unavailable=first.unavailable, total=first.total,
                       gap_or_coverage_flags=first.gap_or_coverage_flags)
            rows.append(row)
        self.frequency.set_frame(pd.DataFrame(rows, dtype=object), heat_columns=labels, tooltips=tips)
        if self._result.request.pre_event is not None:
            offsets = self._result.request.pre_event.offsets
            self.frequency_note.setText(f"Only offsets {offsets[0]} to {offsets[-1]} are mined. All other rows are inspection only. "
                "Frequencies here describe the complete selected event cohort, before chronological partitioning.")
        else:
            self.frequency_note.setText("Each cell shows its observed frequency; hover for counts. Positive offsets describe aftermath.")

    def _patterns(self, *_):
        if self._result is None:
            return
        rows = self._result.frame("patterns")
        pre_mode = self._result.request.pre_event is not None
        if rows.empty:
            self.pattern_note.setText("Choose an exact family and run the study to compare patterns." if self._result.request.family is None and "family_scope" not in json.loads(self._result.context) else "No assessable patterns for this selection.")
        else:
            self.pattern_note.setText(f"{len(rows):,} observed candidates · {int(rows.rank_eligible.sum()):,} rank eligible. "
                "Ratios describe historical frequency, not prediction probability. Ready-reference counts determine ranking.")
            if self.ranked.isChecked():
                rows = rows[rows.rank_eligible == True]
            if pre_mode:
                search = json.loads(self._result.context)["search"]
                self.pattern_note.setText(("Complete search" if search["complete"] else "INCOMPLETE SEARCH — "+search["reason"])+
                    f" · {search['examined']:,} candidates examined. First 50 per page. "
                    "Counts are discovery observations; later-period columns are retrospective stability. "
                    "Inspect a rule for same-row simpler comparisons. Change filters and rerun to refine the study.")
                if self.pattern_kind.currentData() is not None:
                    rows = rows[rows.kind == self.pattern_kind.currentData()]
            first = ["condition", "kind", "matched", "assessable", "comparison_matched", "comparison_assessable", "frequency_ratio", "rank_eligible"]
            if pre_mode:
                first = ["condition", "matched", "exact_matched", "added_by_tolerance", "assessable",
                    "comparison_matched", "comparison_exact_matched", "comparison_assessable", "difference_pp", "rank_eligible"]
            rows = rows[first+[name for name in rows if name not in first]]
        if pre_mode and self._result.frame("patterns").empty:
            search = json.loads(self._result.context)["search"]
            self.pattern_note.setText(("Complete search" if search["complete"] else "INCOMPLETE SEARCH")+
                f" · {search['examined']} candidates examined. "+(search["reason"] or "No supported observed candidates for this selection."))
        self.patterns.set_frame(rows)
        if "conditions" in rows:
            self.patterns.table.setColumnHidden(rows.columns.get_loc("conditions"), pre_mode)
        self._buttons()

    def _pattern_selected(self, row):
        self.family_breakdown.set_frame(pd.DataFrame()); self.family_breakdown_status.clear()
        self._buttons()
        if row is None:
            self.pattern_detail.clear()
            return
        if not row or self._result is None or self._result.request.pre_event is None:
            return
        self._describe_pattern(json.loads(row["conditions"]), row["condition"])

    def _describe_pattern(self, terms, condition):
        lines = [condition, "", "Each column keeps its own profile. Allowed sets do not cross signs."]
        for term in terms:
            lines.append(f"{term['column']} at {term['offset']} · representative center {term['center']} · allowed {', '.join(term['allowed'])}")
            if len(term["center_aliases"]) > 1:
                lines.append("  Equivalent centers for this allowed set: "+", ".join(term["center_aliases"]))
            if (self._result.request.pre_event.radius(term["column"]) > 0 and len(term["allowed"]) == 1
                    and any("bin_index" in entry for entry in term["bins"])):
                lines.append("  Tolerance has no effect: this sign has one bin.")
            for entry in term["bins"]:
                if "percentile_start" in entry:
                    lines.append(f"  {entry['label']}: percentiles {entry['percentile_start']:g}–{entry['percentile_end']:g}; "
                        f"observed values {entry['observed_signed_minimum']} to {entry['observed_signed_maximum']}; reference count {entry['count']}")
        lines += ["", "Aggregate exact matches, matches added by tolerance and exact occurrence views use the representative centers above.",
            "Observed ranges are not decision boundaries. Inspect either cohort to load exact counts for all center interpretations and simpler-rule comparisons on the same assessable rows."]
        self.pattern_detail.setPlainText("\n".join(lines))

    def _all_events(self):
        if self._result is None:
            return
        self.event_note.setText("Granular population, including exclusions and controls. Select a row for its resolved condition/source evidence." if
            self._result.granular_definition is not None else "Selected starts, including exclusions. Select a row for its label window and UTC evidence.")
        self._occurrences = None
        self.occurrence_kind.hide(); self.partition.hide()
        frame = self._result.frame("events")
        if not frame.empty:
            first = [n for n in ("anchor_ts_ms", "event_kind", "family", "origin", "confirmed_at_ms", "eligible", "exclusion",
                     "refinement_eligible", "refinement_reasons", "measurement_basis", "measurement_resolution") if n in frame]
            frame = frame[first+[n for n in frame if n not in first]]
        self.events.set_frame(frame)
        self.window.set_frame(pd.DataFrame())
        self.evidence_text.clear()
        self.event_detail.clear()
        self.metric_detail.clear()

    def _event(self, row):
        if row is None:
            self.window.set_frame(pd.DataFrame())
            self.event_detail.clear()
            self.metric_detail.clear()
            self.evidence_text.clear()
            return
        if self._result is None:
            return
        if self._result.granular_definition is not None:
            record=self._result.population_record(row["event_id"])
            conditions,readable,exact=_gr03_evidence(record,self._result.granular_definition)
            self.window.set_frame(conditions)
            self.event_detail.setText(f"{record['cohort']} · {record['reason']} · {record['partition']}")
            self.metric_detail.setPlainText(readable);self.evidence_text.setPlainText(exact)
            return
        frame = self._result.event_window(row["event_id"])
        first = [n for n in ("offset", "column", "ts_ms", "raw_value", "bin_label", "band", "status", "support_status", "window_status") if n in frame]
        self.window.set_frame(frame[first+[n for n in frame if n not in first]])
        evidence = self._result.evidence(row["event_id"])
        facts = evidence.get("facts")
        if facts is not None:
            def time(value):
                return format_display_timestamp_ms(value) if value is not None else "Unknown"
            self.event_detail.setText(f"{evidence['family']} · {evidence['origin']}\n"
                f"{evidence['event_kind']}0: {time(evidence['anchor_ts_ms'])}\n"
                f"Starting swing available: {time(facts['formation'][0]['available_at_ms'])}\n"
                f"Confirmed: {time(facts['confirmed_at_ms'])} · frontier: {time(facts['decision_frontier_ms'])}")
            refinement = evidence.get("refinement")
            self.metric_detail.setPlainText("\n".join(_refinement_lines(refinement, self._result.request)) if refinement is not None
                                          else "No enriched measurement selection for this event.")
        else:
            self.event_detail.setText("Ordinary timestamp control · no selected UTC formation")
            self.metric_detail.clear()
        self.evidence_text.setPlainText(json.dumps(evidence, indent=2))

    def _request_matches(self, cohort):
        row = self.patterns.current_row()
        if row is not None and not self._busy:
            self.matches_requested.emit(row["pattern_id"], cohort)

    def show_matches(self, frame, *, cohort, condition):
        self.event_note.setText(f"{cohort.title()} matches: {condition}")
        if self._result is not None and self._result.request.pre_event is not None:
            self.event_note.setText(f"{cohort.title()} observations: {condition}. Select the exact, tolerant or denominator view below.")
            self._occurrences = frame.copy(deep=True)
            self.occurrence_kind.show(); self.partition.show()
            with QSignalBlocker(self.occurrence_kind), QSignalBlocker(self.partition):
                self.occurrence_kind.setCurrentIndex(0); self.partition.setCurrentIndex(0)
            self._filter_occurrences()
            detail = json.loads(frame.attrs.get("pattern_detail", "{}"))
            self.family_breakdown.set_frame(_gr05_display_families(detail.get("family_breakdown", [])))
            self.family_breakdown_status.setText("Selected rule: "+condition+"\n"+_gr05_scope_caption(detail["family_scope"])+
                "\nBoth cohorts and all partitions use the same retained rule masks." if "family_scope" in detail else "")
            self._describe_pattern(detail.get("conditions", []), condition)
            lines = ["EXACT CENTER INTERPRETATIONS"]
            if not self._result.request.pre_event.chronological:
                lines.append("Later period: not selected.")
            representative = [t["center"] for t in detail.get("conditions", [])]
            for alias in detail.get("exact_center_aliases", []):
                label = " AND ".join(f"{t['column']}[{t['offset']}]={center}"
                    for t, center in zip(detail["conditions"], alias["centers"], strict=True))
                lines += ["", label+(" (representative)" if alias["centers"] == representative else " (equivalent allowed set)"),
                    f"  Discovery exact: target {alias['exact_matched']}; comparison {alias['comparison_exact_matched']}"]
                if self._result.request.pre_event.chronological:
                    lines.append(f"  Later exact: target {alias['later_exact_matched']}; comparison {alias['later_comparison_exact_matched']}")
            lines += ["", "SIMPLER CONDITIONS · same assessable rows as the selected combination"]
            for row in detail.get("simpler_on_same_assessable_rows", []):
                label = " AND ".join(f"{t['column']}[{t['offset']}] in {{{', '.join(t['allowed'])}}}" for t in row["conditions"])
                lines.append(f"{label}: target {row['matched']}/{row['assessable']}; comparison {row['comparison_matched']}/{row['comparison_assessable']}")
            lines.append(detail.get("note", ""))
            self.pattern_detail.appendPlainText("\n"+"\n".join(lines))
        else:
            self.events.set_frame(frame)
        self.window.set_frame(pd.DataFrame())
        self.evidence_text.clear()
        self.event_detail.clear()
        self.metric_detail.clear()
        self.views.setCurrentIndex(3)

    def _filter_occurrences(self, *_):
        if self._occurrences is None:
            return
        frame = self._occurrences
        if not frame.empty:
            partition = self.partition.currentData()
            if partition is not None:
                frame = frame[frame.partition == partition]
            kind = self.occurrence_kind.currentData()
            if kind == "unavailable":
                frame = frame[frame.assessable == False]
            elif kind != "all":
                frame = frame[frame[kind] == True]
        self.events.set_frame(frame)
        self._event(None)

    def refresh_display_time(self):
        self._context()
        row = self.events.current_row()
        if row is not None:
            self._event(row)
        for table in (self.families, self.frequency, self.patterns, self.events, self.window, self.diagnostics, self.funnel, self.assignments, self.family_breakdown):
            table.refresh_display_time()


def _gr03_evidence(record, definition):
    """Format one already resolved population member; no source decoding or calculations."""
    ledger = {value["measurement_key"]:value for value in record["scalar_ledger"]}
    rows = []
    report = record["predicate_report"]
    for leaf in report["predicates"] if report else ():
        predicate = getattr(definition,leaf["purpose"])[leaf["group_index"]].conditions[leaf["predicate_index"]]
        value = ledger.get(leaf["measurement_key"],{})
        selectors = value.get("selectors",{key:getattr(predicate,key) for key in
            ("domain","field","unit","basis","cohort","statistic","column","profile_id","offset")})
        source = value.get("source",{})
        if predicate.domain == "horizon": selectors["horizon_bars"] = predicate.horizon_bars
        rows.append(dict(purpose=leaf["purpose"],path=leaf["path"],status=leaf["status"],reason=leaf["reason"],
            exact_value=value.get("value"),**selectors,minimum=predicate.minimum,maximum=predicate.maximum,
            lower_inclusive=predicate.lower_inclusive,upper_inclusive=predicate.upper_inclusive,
            allowed=json.dumps(predicate.allowed),provider=source.get("artifact_id"),report_sha256=source.get("report_sha256"),
            available_at_ms=source.get("available_at_ms"),recognition_ms=source.get("recognition_ms"),
            row_ts_ms=source.get("ts_ms"),clock_basis=source.get("clock_basis"),source=json.dumps(source,sort_keys=True)))
    lines = [f"{record['row_id']} · {format_display_timestamp_ms(record['anchor_ts_ms'])}",
        f"Population: {record['cohort']} · {record['reason']}",
        f"Chronology: {record['partition']} · {record['partition_reason'] or 'no exclusion'}",
        "Feature start / cutoff: "+str(record["feature_start_ms"])+" / "+str(record["cutoff_ms"]),
        "Evidence start / end: "+str(record["evidence_start_ms"])+" / "+str(record["evidence_end_ms"]),
        "Source resolution: "+record["source_resolution"]["status"],
        "Source/provider/clock evidence:",json.dumps(record["source_resolution"],indent=2),
        "Unique scalar ledger (shared measurements counted once):",json.dumps(record["scalar_ledger"],indent=2)]
    if "anchor_range_check" in record:
        check = record["anchor_range_check"]
        bounds = definition.anchor_range
        lines.extend(["Anchor date restriction",
            f"Applied inclusive UTC-ms bounds: {bounds.start_ms} through {bounds.end_ms}",
            f"Anchor in range: {check['in_range']}",
            f"Before dates: {check['prior_cohort']} · {check['prior_reason']}",
            f"Before-date chronology: {check['prior_partition']} · {check['prior_partition_reason']}",
            f"Final population: {record['cohort']} · {record['reason']}"])
    windows = {w["window_id"]:w for w in record.get("horizon_windows", ())}
    for value in record["scalar_ledger"]:
        source = value["source"]
        if source.get("kind") != "fixed_horizon_price": continue
        window = windows[source["window_id"]]
        lines.extend([f"Fixed horizon: {source['field']} · N={source['horizon_bars']} · {source['unit']} · {source['direction']} · reference=event_close",
            f"Value: {value['value']} · reason: {value['unavailable_reason'] or 'known'}",
            f"Rows: {window['start_row']} -> {window['end_row']} · timestamps: {window['start_ts_ms']} -> {window['end_ts_ms']}",
            f"Required roles: {', '.join(source['required_roles'])} · tail: {window['tail_status']} · spacing: {window['spacing_status']}",
            "Actual window values: "+json.dumps(window['inputs'],sort_keys=True),
            "Database revision/hash: "+json.dumps(window['source_reference'],sort_keys=True),
            f"Price snapshot: {window['price_snapshot_id']} · availability: {window['availability']} · numerical policy: {window['numerical_policy']}",
            f"Required interval: {window['required_start_ms']} -> {window['required_end_ms']} · acquired: {window['acquired_at_ms']}"])
    if report and report["cross_purpose_predicates"]:
        lines.append("Repeated across purposes: shared predicates are not independent evidence.")
    return pd.DataFrame(rows,dtype=object),"\n".join(lines),json.dumps(record,indent=2)


def _gr05_scope_caption(scope):
    title = {"exact": "Exact family", "selected": "Selected families", "all": "All compatible families"}[scope["mode"]]
    return (title + f" · {len(scope['selected_families'])} selected / {len(scope['compatible_families'])} compatible\n" +
        ", ".join(scope["selected_families"]) + "\n" + ("No comparison requested; contrast unavailable" if
        scope["comparison"] == "recurrence" else "Fixed comparison: " + scope["comparison"].replace("_", " ")))


def _gr05_display_families(rows):
    frame = pd.DataFrame(rows, dtype=object)
    if not frame.empty:
        frame.loc[frame.ordinary == True, "family"] = "Ordinary timestamps (not a family)"
    return frame
