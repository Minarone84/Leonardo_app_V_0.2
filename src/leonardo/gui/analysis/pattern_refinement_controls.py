"""In-session pinned-rule draft and supplied-result presentation."""
from __future__ import annotations

from dataclasses import replace
import json
import pandas as pd
from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget, QMessageBox,
)
from .trend_start_results import StudyTable, identify, _metric_lines, _refinement_lines


class PatternRefinementControls(QWidget):
    action_requested = Signal(str)
    draft_changed = Signal()
    checkpoint_requested = Signal(str)
    matches_requested = Signal(str, str)
    rule_changed = Signal()
    inspection_requested = Signal(object)
    sensitivity_requested = Signal(object)
    inspection_options_changed = Signal()
    report_clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from .trend_start_patterns_tab import RefinementControls
        identify(self, "post_refinement.page")
        self._snapshot = None
        self._result = None
        self._occurrences = None
        self._applying = False
        self._busy_kind = None
        self._granular_edited = False
        self._population_frame = pd.DataFrame()
        root = QVBoxLayout(self)
        self.context = self._label("context")
        root.addWidget(self.context)
        self.history = identify(QComboBox(self), "post_refinement.history")
        self.history.setMinimumContentsLength(12)
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        root.addWidget(self.history)
        self.history_status = self._label("history_status")
        self.history_status.setToolTip("Estimate covers retained evaluation atom/rule match masks only. "
            "It excludes frozen source/discovery data, event evidence and process RSS.")
        root.addWidget(self.history_status)
        self.mode = identify(QComboBox(self), "post_refinement.mode", action=True)
        self.mode.addItem("Simple filters", "simple"); self.mode.addItem("Granular filters", "granular")
        root.addWidget(self.mode)
        self.convert_granular = identify(QPushButton("Convert current simple filters", self), "post_refinement.convert_granular", action=True)
        root.addWidget(self.convert_granular)
        self.editor = RefinementControls(self, identity_prefix="post_refinement.filters", family_scoping=True)
        identify(self.editor, "post_refinement.filters", action=True)
        self.editor.toggle.setChecked(True)
        self.editor.note.setText("Evaluate these existing AND filters against the frozen root universe. "
            "All conditions share one measurement basis. Completed outcomes are retrospective.")
        root.addWidget(self.editor)
        from .refinement_filter_editor import GranularFilterEditor
        self.granular_editor = GranularFilterEditor(self)
        root.addWidget(self.granular_editor)
        self.draft_status = self._label("draft_status")
        root.addWidget(self.draft_status)
        self.actions = {}
        for key, title in (
            ("evaluate", "Evaluate pinned combinations"), ("compare_parent", "Compare with parent"),
            ("reset_parent", "Reset to parent"), ("reset_discovery", "Reset to discovery"),
            ("discard", "Discard selected leaf evaluation"),
            ("search_new", "Search new combinations\nwith these conditions"),
            ("clear_workspace", "Start new pinned workspace")):
            button = identify(QPushButton(title, self), "post_refinement."+key, action=True)
            button.clicked.connect(lambda checked=False, key=key: self.action_requested.emit(key))
            self.actions[key] = button
            root.addWidget(button)
        warning = QLabel("Search new combinations is NEW DISCOVERY: it mines again using this pinned source "
            "and draft. It does not change the pinned rules or add an evaluation checkpoint.", self)
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.views = QTabWidget(self)
        self.views.setMinimumWidth(0)
        self.views.setUsesScrollButtons(True)
        root.addWidget(self.views)
        result_page = QWidget(self)
        result_layout = QVBoxLayout(result_page)
        self.results = self._table("results")
        self.results.model.page_size = 50
        result_layout.addWidget(self.results)
        self.rule_details = identify(QPlainTextEdit(self), "post_refinement.rule_details")
        self.rule_details.setReadOnly(True)
        self.rule_details.setMaximumHeight(180)
        result_layout.addWidget(self.rule_details)
        self.target_matches = identify(QPushButton("Inspect target observations", self), "post_refinement.target_matches", action=True)
        self.comparison_matches = identify(QPushButton("Inspect comparison observations", self), "post_refinement.comparison_matches", action=True)
        for cohort, button in (("target", self.target_matches), ("comparison", self.comparison_matches)):
            button.clicked.connect(lambda checked=False, cohort=cohort: self._request_matches(cohort))
            result_layout.addWidget(button)
        self.family_population_status = self._label("family_population_status")
        self.family_population = self._table("family_population")
        result_layout.addWidget(self.family_population_status)
        result_layout.addWidget(self.family_population)
        self.views.addTab(result_page, "Results")
        self.comparison = self._table("comparison")
        self.comparison.model.page_size = 50
        self.views.addTab(self.comparison, "Compare")
        self.changes = self._table("changes")
        self.views.addTab(self.changes, "Population changes")
        occurrence_page = QWidget(self)
        occurrence_layout = QVBoxLayout(occurrence_page)
        self.occurrence_kind = identify(QComboBox(self), "post_refinement.occurrence_kind")
        for title, key in (("Tolerant matches", "matched"), ("Exact center matches", "exact_match"),
                ("Added by tolerance", "added_by_tolerance"), ("All assessable", "assessable"),
                ("Unavailable", "unavailable"), ("All observations", "all")):
            self.occurrence_kind.addItem(title, key)
        self.occurrence_partition = identify(QComboBox(self), "post_refinement.occurrence_partition")
        for title, key in (("Discovery", "discovery"), ("Later", "later"), ("Excluded", "excluded"), ("All partitions", None)):
            self.occurrence_partition.addItem(title, key)
        occurrence_layout.addWidget(self.occurrence_kind)
        occurrence_layout.addWidget(self.occurrence_partition)
        self.occurrences = self._table("occurrences")
        self.event_window = self._table("event_window")
        self.event_details = identify(QPlainTextEdit(self), "post_refinement.event_details")
        self.event_details.setReadOnly(True)
        self.event_details.setMaximumHeight(240)
        for widget in (self.occurrences, self.event_window, self.event_details):
            occurrence_layout.addWidget(widget)
        self.family_breakdown_status = self._label("family_breakdown_status")
        self.family_breakdown = self._table("family_breakdown")
        occurrence_layout.addWidget(self.family_breakdown_status)
        occurrence_layout.addWidget(self.family_breakdown)
        self.views.addTab(occurrence_page, "Occurrences")
        population_page = QWidget(self); population_layout = QVBoxLayout(population_page)
        self.population_status = self._label("population.status"); population_layout.addWidget(self.population_status)
        for key, choices in (("cohort", (("All cohorts",None),("Target","target"),("Comparison","comparison"),("Excluded","excluded"))),
                ("partition", (("All partitions",None),("Discovery","discovery"),("Later","later"),("Excluded","excluded"))),
                ("reason", (("All reasons",None),("Scope","outside_family_scope"),("Mandatory","mandatory_event_ineligible"),
                    ("Unavailable","unavailable_requested_evidence"),("Common mismatch","common_condition_mismatch"),("Outcome mismatch","outcome_condition_mismatch"),("Anchor dates","outside_anchor_range")))):
            combo = identify(QComboBox(self), "post_refinement.population."+key)
            for title,value in choices:combo.addItem(title,value)
            setattr(self,"population_"+key,combo);population_layout.addWidget(combo)
            combo.currentIndexChanged.connect(self._population_changed)
        self.population = self._table("population.members");self.population.model.page_size=50
        self.condition_evidence = self._table("population.conditions");self.condition_evidence.model.page_size=50
        self.population_detail = identify(QPlainTextEdit(self),"post_refinement.population.detail")
        self.population_json = identify(QPlainTextEdit(self),"post_refinement.population.json")
        for widget in (self.population_detail,self.population_json):widget.setReadOnly(True);widget.setMaximumHeight(220)
        for widget in (self.population,self.condition_evidence,self.population_detail,self.population_json):population_layout.addWidget(widget)
        self.views.addTab(population_page,"Population evidence")
        self.population.selected.connect(self._population_selected)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.convert_granular.clicked.connect(self._convert_granular)
        self.granular_editor.changed.connect(self._granular_changed)
        note = QLabel("In-session only. Closing Analysis Suite discards this refinement history. No studies are saved to disk.", self)
        note.setWordWrap(True)
        root.addWidget(note)
        self.history.activated.connect(self._history_changed)
        self.editor.changed.connect(self._draft_changed)
        self.results.selected.connect(self._rule_selected)
        self.occurrences.selected.connect(self._event_selected)
        self.occurrence_kind.currentIndexChanged.connect(self._filter_occurrences)
        self.occurrence_partition.currentIndexChanged.connect(self._filter_occurrences)
        from .combination_inspector import CombinationInspector
        self.inspector = CombinationInspector(self)
        self.views.addTab(self.inspector, "Combination inspector")
        self.inspect_selected = identify(QPushButton("Inspect selected combination",self),"post_refinement.inspector.inspect_selected",action=True)
        result_layout.insertWidget(2,self.inspect_selected)
        self.inspect_selected.clicked.connect(self._gr06_inspect_selected)
        self.inspector.inspection_requested.connect(self.inspection_requested)
        self.inspector.sensitivity_requested.connect(self.sensitivity_requested)
        self.inspector.inspection_options_changed.connect(self.inspection_options_changed)
        self.inspector.report_clear_requested.connect(self.report_clear_requested)
        self.inspector.rule_changed.connect(self.rule_changed)
        self.clear()

    def _table(self, key):
        table = StudyTable("post_refinement."+key, self)
        # Keep the existing pager, with totals on their own line in this pane.
        table.layout().itemAt(1).layout().removeWidget(table.info)
        table.layout().addWidget(table.info)
        return table

    def _label(self, key):
        label = identify(QLabel(self), "post_refinement."+key)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def clear(self):
        self.inspector.clear()
        self._snapshot = self._result = self._occurrences = None
        self._applying = True
        try:
            from leonardo.analysis.pattern_models import PatternRefinement
            from leonardo.analysis.refinement_models import GranularRefinement
            with QSignalBlocker(self.mode):self.mode.setCurrentIndex(0)
            self.editor._gr05_set_context({})
            self.editor.set_value(PatternRefinement());self.editor.show()
            self.granular_editor.set_context({});self.granular_editor.set_value(GranularRefinement());self.granular_editor.hide()
            self._granular_edited=False;self._population_frame=pd.DataFrame()
            for combo in (self.population_cohort,self.population_partition,self.population_reason):
                with QSignalBlocker(combo):combo.setCurrentIndex(0)
            self._population_changed()
        finally:self._applying=False
        with QSignalBlocker(self.history):
            self.history.clear()
        self.context.setText("Pin existing Pre-event combinations to begin a separate refinement workspace.")
        self.context.setToolTip("")
        self.history_status.setText("0 / 20 evaluations · 0 / 134217728 bytes retained match-state estimate")
        self.family_population_status.clear(); self.family_breakdown_status.clear()
        for table in (self.results, self.comparison, self.changes, self.occurrences, self.event_window, self.family_population, self.family_breakdown):
            table.set_frame(pd.DataFrame())
        self.rule_details.clear()
        self.event_details.clear()
        self.draft_status.clear()
        self._sync()

    def show_checkpoint(self, snapshot, result):
        self._applying = True
        try:
            replacing = self._snapshot is None or self._snapshot["set_id"]!=snapshot["set_id"]
            if replacing:
                from leonardo.analysis.pattern_models import PatternRefinement
                from leonardo.analysis.refinement_models import GranularRefinement
                self.editor.set_value(PatternRefinement());self.granular_editor.set_value(GranularRefinement());self._granular_edited=False
            self._snapshot, self._result, self._occurrences = snapshot, result, None
            request = snapshot["original_request"]
            identity = snapshot["active_checkpoint_id"]
            context = json.loads(result.context)
            search = context.get("source_discovery_search", context.get("search", {}))
            self.context.setText(f"Pinned source · {request.reference.database_id} · revision {request.reference.revision_id[:12]}\n"
                f"{request.role_label} · {request.family} · {snapshot['pinned_count']} fixed rules\n"
                f"UTC {request.instance_id[:12]} · source discovery {snapshot['source_discovery_id'][:12]}\n"
                f"Selected checkpoint / next evaluation parent: {identity[:16]}\n"
                "Independent of the legacy discovery form above. All retained rules are shown, including zero counts.\n"+
                ("Source discovery: complete search." if search.get("complete") else
                 "Source discovery: INCOMPLETE SEARCH · "+str(search.get("reason", "unknown"))))
            self.context.setToolTip(f"Root: {snapshot['root_id']}\nSet: {snapshot['set_id']}\n"
                f"Source discovery: {snapshot['source_discovery_id']}\nCheckpoint: {identity}\n"
                f"Revision: {request.reference.revision_id}\nUTC: {request.instance_id}\nBinning run: {request.run_key}\n"
                f"Pinned request: {request}\nSupplied result context:\n"+json.dumps(context, indent=2))
            with QSignalBlocker(self.history):
                self.history.clear()
                ordinals = {row["checkpoint_id"]: row["ordinal"] for row in snapshot["history"]}
                for row in snapshot["history"]:
                    self.history.addItem(f"{row['ordinal']}: {row['kind']} / {row.get('filter_kind','simple')} · parent {ordinals.get(row['parent_id'], 'none')} · {row['refinement_summary']}", row["checkpoint_id"])
                    self.history.setItemData(self.history.count()-1, json.dumps(row, indent=2), Qt.ItemDataRole.ToolTipRole)
                self.history.setCurrentIndex(self.history.findData(identity))
            self.history_status.setText(f"{snapshot['evaluation_count']} / 20 evaluations · "
                f"{snapshot['retained_match_bytes']} bytes / 128 MiB retained match-state estimate")
            family_context = snapshot.get("filter_context", {}).get("family_scope_context", {})
            self.editor._gr05_set_context(family_context)
            from .trend_start_results import _gr05_scope_caption, _gr05_display_families
            if "family_scope" in context:
                self.context.setText(self.context.text()+"\nORIGINAL REQUEST selection: "+str(family_context.get("source_selection"))+
                    "\nAPPLIED completed selection: "+_gr05_scope_caption(context["family_scope"]))
            self.family_population_status.setText("Pooled frequencies use pooled counts; family mix can change the result." if
                "family_population" in context else "Family pooling not applied to this checkpoint")
            self.family_population.set_frame(_gr05_display_families(context.get("family_population", [])))
            self.family_breakdown.set_frame(pd.DataFrame()); self.family_breakdown_status.clear()
            self.editor.set_previous_families(snapshot["previous_families"])
            kind = snapshot.get("active_filter_kind","simple")
            self.granular_editor.set_context(snapshot.get("filter_context",{}))
            with QSignalBlocker(self.mode):self.mode.setCurrentIndex(self.mode.findData(kind))
            if kind=="granular":
                self.granular_editor.set_value(snapshot["active_refinement"]);self._granular_edited=False
            else:self.editor.set_value(snapshot["active_refinement"])
            self.editor.setVisible(kind=="simple");self.granular_editor.setVisible(kind=="granular")
            self.history_status.setText(f"{snapshot['evaluation_count']} / 20 evaluations · match estimate {snapshot['retained_match_bytes']} bytes · "
                f"population payload {snapshot.get('retained_population_bytes',0)} bytes · combined {snapshot.get('retained_total_bytes',snapshot['retained_match_bytes'])} / 134217728 bytes")
            self.history_status.setToolTip("Combined scope: retained evaluation masks plus unique canonical population payloads. "
                "Excludes source/bin frames, discovery masks, indexes, small definitions, temporary display copies and process RSS.")
            self._population_frame = result.frame("population") if result.granular_definition is not None else pd.DataFrame()
            for combo in (self.population_cohort,self.population_partition,self.population_reason):
                with QSignalBlocker(combo):combo.setCurrentIndex(0)
            self._population_changed()
            frame = result.frame("patterns")
            frame = frame.set_index("pattern_id", drop=False).loc[list(snapshot["pinned_ids"])].reset_index(drop=True)
            first = [name for name in ("condition", "matched", "assessable", "comparison_matched", "comparison_assessable",
                "difference_pp", "exact_matched", "added_by_tolerance", "support_eligible", "original_order") if name in frame]
            self.results.set_frame(frame[first+[name for name in frame if name not in first]])
            if "conditions" in frame:
                self.results.table.setColumnHidden(self.results.model.frame.columns.get_loc("conditions"), True)
            for table in (self.comparison, self.occurrences, self.event_window):
                table.set_frame(pd.DataFrame())
            self.changes.set_frame(pd.DataFrame() if identity == snapshot["source_discovery_id"] else result.frame("population_changes"))
            self.inspector.bind(snapshot,result)
            self._grdate_caption_base = self.context.text()
            self._grdate_refresh_caption()
            self.rule_details.clear()
            self.event_details.clear()
        finally:
            self._applying = False
        self._sync()

    def draft(self):
        if self.mode.currentData()=="granular":
            return self.granular_editor.value()
        value = self.editor.value()
        if self._snapshot is not None:
            replace(self._snapshot["original_request"], refinement=value)
        return value

    def set_busy(self, kind):
        self._busy_kind = kind
        self._sync()

    def _sync(self):
        present = self._snapshot is not None
        busy = self._busy_kind is not None
        evaluation_pending = self._busy_kind == "refinement_evaluate"
        report_pending = self._busy_kind in ("refinement_inspection","refinement_sensitivity")
        self.editor.setEnabled(present and (not busy or evaluation_pending or report_pending))
        self.granular_editor.setEnabled(present and (not busy or evaluation_pending or report_pending))
        self.mode.setEnabled(present and (not busy or evaluation_pending or report_pending))
        self.convert_granular.setEnabled(present and not busy)
        self.history.setEnabled(present and (not busy or self._busy_kind in ("refinement_evaluate", "refinement_matches", "refinement_inspection", "refinement_sensitivity")))
        valid, dirty = False, False
        if present:
            try:
                draft = self.draft()
                dirty = draft != self._snapshot["active_refinement"]
                valid = True
                if dirty:
                    self.draft_status.setText("Draft changed; cancelling prior evaluation. Previous checkpoint retained." if evaluation_pending else
                        f"Draft changed; showing checkpoint {self._snapshot['active_checkpoint_id']}. Evaluate to apply these settings.")
                else:
                    self.draft_status.setText("Showing saved settings and completed counts. Source rows retain their original rank criterion." if
                        self._snapshot["active_checkpoint_id"] == self._snapshot["source_discovery_id"] else "Showing saved settings and completed counts. Support eligibility is not a new ranking.")
            except (ValueError, TypeError) as exc:
                self.draft_status.setText("Invalid draft: "+str(exc)+" Previous checkpoint retained.")
        if present and self._result.granular_definition is not None:
            context=json.loads(self._result.context)
            self.draft_status.setText(self.draft_status.text()+"\nApplied granular definition: "+context["definition_summary"]+
                "\nShared predicates across purposes are not independent evidence.")
        active = next((r for r in self._snapshot["history"] if r["active"]), None) if present else None
        for key, button in self.actions.items():
            enabled = present and not busy
            if key in ("evaluate", "search_new"):
                enabled = enabled and valid
            if key in ("compare_parent", "reset_parent", "discard"):
                enabled = enabled and active["parent_id"] is not None
            if key == "discard" and enabled:
                enabled = not any(r["parent_id"] == active["checkpoint_id"] for r in self._snapshot["history"])
            button.setEnabled(enabled)
        selected = self.results.current_row() is not None
        self.target_matches.setEnabled(present and not busy and selected)
        self.comparison_matches.setEnabled(present and not busy and selected)
        self.inspect_selected.setEnabled(present and not busy and selected)
        self.inspector.set_state(self._busy_kind,self.draft_status.text())

    def _draft_changed(self):
        if not self._applying:
            self.draft_changed.emit()
            self._sync()

    def _history_changed(self):
        if not self._applying and self.history.currentData() is not None:
            self.checkpoint_requested.emit(self.history.currentData())

    def _rule_selected(self, row):
        if row is not None:self.inspector.select_rule(row["pattern_id"])
        self.family_breakdown.set_frame(pd.DataFrame()); self.family_breakdown_status.clear()
        if not self._applying:
            self.rule_changed.emit()
        self.rule_details.setPlainText("" if row is None else row["condition"]+"\n"+
            json.dumps(json.loads(row["conditions"]), indent=2)+"\nOriginal column profiles and allowed centers are unchanged.")
        self._sync()

    def _request_matches(self, cohort):
        row = self.results.current_row()
        if row is not None:
            self.matches_requested.emit(row["pattern_id"], cohort)

    def show_comparison(self, frame):
        self.comparison.set_frame(frame)
        self.views.setCurrentIndex(1)

    def show_matches(self, frame):
        from .trend_start_results import _gr05_display_families, _gr05_scope_caption
        detail = json.loads(frame.attrs.get("pattern_detail", "{}"))
        self.family_breakdown.set_frame(_gr05_display_families(detail.get("family_breakdown", [])))
        self.family_breakdown_status.setText("Selected rule: "+str(detail.get("conditions"))+"\n"+
            _gr05_scope_caption(detail["family_scope"])+"\nBoth cohorts and all partitions use the same retained rule masks." if
            "family_scope" in detail else "Family pooling not applied to this checkpoint")
        self._occurrences = frame.copy(deep=True)
        self._filter_occurrences()
        self.views.setCurrentIndex(3)
        self.event_details.setPlainText(json.dumps(frame.attrs, indent=2, default=str))

    def _filter_occurrences(self):
        if self._occurrences is None:
            return
        frame = self._occurrences.copy(deep=True)
        kind, partition = self.occurrence_kind.currentData(), self.occurrence_partition.currentData()
        if not frame.empty:
            if partition is not None:
                frame = frame[frame.partition == partition]
            if kind != "all":
                frame = frame[frame.assessable == False] if kind == "unavailable" else frame[frame[kind] == True]
        self.occurrences.set_frame(frame)
        self.event_window.set_frame(pd.DataFrame())
        self.event_details.clear()

    def _event_selected(self, row):
        if row is None or self._result is None:
            return
        identity = row["event_id"]
        self.event_window.set_frame(self._result.event_window(identity))
        if self._result.granular_definition is not None:
            from .trend_start_results import _gr03_evidence
            _,readable,exact=_gr03_evidence(self._result.population_record(identity),self._result.granular_definition)
            self.event_details.setPlainText("Rule occurrence within its cohort.\n"+readable+"\n"+exact)
            return
        evidence = self._result.evidence(identity)
        lines = (_refinement_lines(evidence.get("refinement") or {}, self._result.request)
                 if evidence.get("facts") is not None else ["Ordinary timestamp control · no selected UTC formation"])
        lines += _metric_lines(evidence.get("facts", {}))
        self.event_details.setPlainText("\n".join(lines)+"\n"+json.dumps(evidence, indent=2, default=str))

    def refresh_display_time(self):
        self.inspector.refresh_display_time()
        with QSignalBlocker(self.granular_editor):
            self.granular_editor.refresh_display_time()
            self._grdate_refresh_caption()
        for table in (self.results, self.comparison, self.changes, self.occurrences, self.event_window, self.population, self.condition_evidence, self.family_population, self.family_breakdown):
            table.refresh_display_time()

    def show_inspection(self, report, snapshot=None):
        if snapshot is not None:self._snapshot=snapshot
        self.inspector.show_inspection(report,snapshot)
        if report is not None:self.views.setCurrentWidget(self.inspector)
        self._sync()

    def show_sensitivity(self, report, snapshot=None):
        if snapshot is not None:self._snapshot=snapshot
        self.inspector.show_sensitivity(report,snapshot)
        if report is not None:
            self.views.setCurrentWidget(self.inspector)
            self.inspector.views.setCurrentWidget(self.inspector.pages["Sensitivity"])
        self._sync()

    def _gr06_inspect_selected(self):
        row=self.results.current_row()
        if row is not None:
            self.inspector.select_rule(row["pattern_id"])
            self.inspector.request_inspection()


    def _grdate_refresh_caption(self):
        if self._snapshot is None or self._result is None:
            return
        from leonardo.gui.display_time import current_display_time_zone_name
        from PySide6.QtCore import QDateTime, QTimeZone
        context = json.loads(self._result.context)
        descriptor = context.get("anchor_range")
        base = self._grdate_caption_base
        if descriptor is None:
            self.context.setText(base)
            return
        zone_name = current_display_time_zone_name()
        zone = QTimeZone(zone_name.encode())
        values = [QDateTime.fromMSecsSinceEpoch(descriptor[key], zone).toString('yyyy-MM-dd HH:mm:ss.zzz')
                  for key in ('start_ms', 'end_ms')]
        self.context.setText(base+f"\nCOMPLETED original interval: {descriptor['root_start_ms']} through {descriptor['root_end_ms']} UTC ms"
            +f"\nAPPLIED completed anchor interval: {values[0]} through {values[1]} {zone_name}, inclusive"
            +f"\nExact UTC ms: {descriptor['start_ms']} through {descriptor['end_ms']}; editor below is the draft."
            +"\nAnchor date counts: "+', '.join(f'{key}={value}' for key,value in context['anchor_range_summary'].items()))

    def _mode_changed(self):
        self.editor.setVisible(self.mode.currentData()=="simple")
        self.granular_editor.setVisible(self.mode.currentData()=="granular")
        self._draft_changed()

    def _convert_granular(self):
        from leonardo.analysis.refinement_models import convert_legacy_refinement
        if self._snapshot is None or self._busy_kind is not None:
            return
        try:
            current = self.editor.value()
            replace(self._snapshot["original_request"],refinement=current)
            definition = convert_legacy_refinement(current,comparison=self._snapshot["original_request"].comparison)
            if (self._granular_edited and any(self.granular_editor.groups.values())) or self.granular_editor.anchor_range.enabled.isChecked():
                if QMessageBox.question(self,"Convert simple filters","Replace the edited granular draft with the current simple filters?",
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                    return
            self._applying = True
            try:
                self.granular_editor.set_value(definition)
                with QSignalBlocker(self.mode):self.mode.setCurrentIndex(self.mode.findData("granular"))
                self.editor.hide();self.granular_editor.show();self._granular_edited=True
            finally:self._applying=False
            self._draft_changed()
        except (ValueError,TypeError) as exc:
            self.draft_status.setText("Conversion failed: "+str(exc)+" Previous draft and checkpoint retained.")

    def _granular_changed(self):
        if not self._applying:
            self._granular_edited=True
            self._draft_changed()

    def _population_changed(self):
        if self._result is None or self._result.granular_definition is None:
            self.population.set_frame(pd.DataFrame())
            self.population_status.setText("No granular condition report is attached. Simple diagnostics remain available.")
            self.condition_evidence.set_frame(pd.DataFrame());self.population_detail.clear();self.population_json.clear()
            return
        frame=self._population_frame
        cohort=self.population_cohort.currentData();partition=self.population_partition.currentData();reason=self.population_reason.currentData()
        if cohort is not None:frame=frame[frame.cohort==cohort]
        if partition is not None:frame=frame[frame.partition==partition]
        if reason is not None:
            reasons=(reason,"fails_outcome_definition") if reason=="outcome_condition_mismatch" else (reason,)
            frame=frame[frame.reason.isin(reasons)]
        self.population.set_frame(frame)
        totals=json.loads(self._result.context)["population_summary"]["by_cohort_partition"]
        self.population_status.setText(f"{len(frame)} visible / {len(self._population_frame)} total population rows. Presentation filters only.\n"+
            "; ".join(f"{r['cohort']} / {r['partition']}: {r['count']}" for r in totals)+
            "\nPopulation exclusions are separate from rule non-assessability in Occurrences.")
        self.condition_evidence.set_frame(pd.DataFrame());self.population_detail.clear();self.population_json.clear()

    def _population_selected(self,row):
        if row is None or self._result is None or self._result.granular_definition is None:
            return
        from .trend_start_results import _gr03_evidence
        record=self._result.population_record(row["event_id"])
        frame,readable,exact=_gr03_evidence(record,self._result.granular_definition)
        self.condition_evidence.set_frame(frame);self.population_detail.setPlainText(readable);self.population_json.setPlainText(exact)
