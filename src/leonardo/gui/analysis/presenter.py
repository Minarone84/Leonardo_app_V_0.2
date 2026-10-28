"""Coordinate Analysis interaction without owning storage or calculations."""
from __future__ import annotations

from threading import RLock
from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtWidgets import QMessageBox

from leonardo.analysis.models import AnalysisRequest
from leonardo.gui.analysis.database_presentation import DatabaseDisplayEntry
from leonardo.gui.analysis.variation_binning_tab import DatabaseColumnDisplayEntry


class _QtDispatch(QObject):
    pending = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self._lock = RLock()
        self._closed = False
        self.pending.connect(self._invoke, Qt.ConnectionType.QueuedConnection)

    def dispatch(self, callback):
        with self._lock:
            if not self._closed:
                self.pending.emit(callback)

    def close(self):
        with self._lock:
            self._closed = True

    def _invoke(self, callback):
        with self._lock:
            if self._closed:
                return
        callback()


class AnalysisSuitePresenter(QObject):
    def __init__(self, view, service):
        super().__init__(view)
        self.view = view
        self.service = service
        self.session = service.begin_session()
        self._dispatcher = _QtDispatch(self)
        self._catalog = {}
        self._catalog_summary = None
        self._loaded = None
        self._binning_result = None
        self._study_result = None
        self._busy = False
        self._kind = None
        self._generation = 0
        self._disposed = False
        self._applying = False
        self._pending_source = False
        self._reload_identity = None
        self._waiting_refresh = False
        self._operation_token = None
        self._refinement_active = False
        self._retry = QTimer(self)
        self._retry.setInterval(100)
        self._retry.timeout.connect(self._resume_after_drain)
        view.refresh_requested.connect(self.refresh)
        view.cancel_requested.connect(self.cancel)
        view.closing.connect(self.dispose)
        tab = view.variation_tab
        tab.source_changed.connect(self._source_changed)
        tab.configuration_changed.connect(self._configuration_changed)
        tab.reload_requested.connect(self.reload)
        tab.run_requested.connect(self.run)
        view.pattern_tab.load_requested.connect(self.load_pattern_catalogue)
        view.pattern_tab.run_requested.connect(self.run_patterns)
        view.pattern_tab.configuration_changed.connect(self._study_configuration_changed)
        view.pattern_tab.results.matches_requested.connect(self.pattern_matches)
        view.pattern_tab.results.pin_requested.connect(self.pin_patterns)
        view.pattern_tab.results.pin_clear_requested.connect(self.clear_pin_selection)
        page = view.pattern_tab.post_refinement
        page.action_requested.connect(self.refinement_action)
        page.draft_changed.connect(self.refinement_draft_changed)
        page.checkpoint_requested.connect(self.select_refinement_checkpoint)
        page.matches_requested.connect(self.refinement_matches)
        page.rule_changed.connect(self._refinement_rule_changed)
        page.inspection_requested.connect(self.inspect_refinement_combination)
        page.sensitivity_requested.connect(self.run_refinement_sensitivity)
        page.inspection_options_changed.connect(self._inspection_options_changed)
        page.report_clear_requested.connect(self._clear_refinement_reports)
        self._sync()

    @property
    def is_disposed(self):
        return self._disposed

    def start(self):
        self.refresh(record_action=False)

    def _allowed(self, action):
        return self.view._record_action(action)

    def _sync(self, message=""):
        if not self._disposed:
            ready = self._loaded is not None and self.view.variation_tab.active_database_id() == self._loaded.entry.reference.database_id
            fields = ()
            if ready:
                entry = self._loaded.entry
                reference = entry.reference
                fields = (("Active analysis database", f"{entry.name} [{reference.database_id}]"),
                          ("Pinned revision", reference.revision_id), ("Values SHA-256", reference.values_sha256))
            self.view.show_source_details(fields)
            self.view.set_execution_state(connected=True, busy=self._busy or self._waiting_refresh, source_ready=ready, message=message)
            self.view.pattern_tab.post_refinement.set_busy(self._kind if self._busy else None)

    def refresh(self, *, record_action=True):
        if self._disposed or self._busy:
            return
        if record_action and not self._allowed("analysis_suite.action.refresh_databases"):
            return
        if self.service.has_draining_workers:
            self._waiting_refresh = True
            self._retry.start()
            self._sync("Waiting for the cancelled analysis worker to finish.")
            self.view.set_operation("Database catalogue", "Cancelling", "Waiting for the previous worker to finish.")
            return
        self._waiting_refresh = False
        self._retry.stop()
        self.view._source_label = "Loading saved databases…"
        self.view.catalog_label.setText("Loading saved databases…")
        self._submit("catalog", self.service.submit_catalog, self._catalog_loaded)

    def _resume_after_drain(self):
        if not self._disposed and not self.service.has_draining_workers:
            self.refresh(record_action=False)

    def reload(self):
        if self._disposed or self._busy or not self._allowed("analysis_suite.action.reload_database"):
            return
        identity = self.view.variation_tab.active_database_id()
        if identity is None:
            return
        self._reload_identity = identity
        self._loaded = None
        self.view.variation_tab.results.clear("Reloading the selected database.")
        self._invalidate_patterns()
        self.refresh(record_action=False)

    def _catalog_loaded(self, catalog):
        previous = self._catalog
        self._catalog = {entry.reference.database_id: entry for entry in catalog.entries}
        changed = {identity for identity, entry in previous.items()
                   if identity not in self._catalog or entry.reference != self._catalog[identity].reference}
        if self._reload_identity is not None:
            changed.add(self._reload_identity)
        active = self.view.variation_tab.active_database_id()
        if active in changed:
            self._loaded = None
            self._invalidate_patterns()
            self.view.variation_tab.results.clear("Database revision refreshed. Select columns again.")
        label = f"{len(catalog.entries)} saved databases available."
        if catalog.issues:
            label += f" {len(catalog.issues)} database(s) unavailable; details in Log."
            for issue in catalog.issues:
                self.view.log.append("Catalogue warning: " + issue)
        self._catalog_summary = label
        self._applying = True
        try:
            self.view.reconcile_database_catalog(tuple(_display_entry(entry) for entry in catalog.entries),
                                                 invalidated_ids=changed, source_label=label)
        finally:
            self._applying = False
        self._reload_identity = None
        identity = self.view.variation_tab.active_database_id()
        if self._loaded is None and identity is not None:
            self._source_changed(identity)

    def _source_changed(self, identity):
        if self._disposed or self._applying:
            return
        self._generation += 1
        self._loaded = None
        self.view.variation_tab.results.clear()
        self._invalidate_patterns()
        if self._busy:
            self._pending_source = True
            self.service.cancel(self.session)
            self._sync("Cancelling the previous operation before loading this source.")
            return
        if identity is None:
            self._sync()
            return
        entry = self._catalog.get(identity)
        if entry is None:
            self._sync("This database is unavailable. Refresh the catalogue.")
            return
        self.view.variation_tab.clear_source_columns(identity)
        self._submit("columns", lambda session, **kw: self.service.submit_columns(session, entry.reference, **kw), self._columns_loaded)

    def _columns_loaded(self, loaded):
        if self.view.variation_tab.active_database_id() != loaded.entry.reference.database_id:
            return
        self._loaded = loaded
        self._applying = True
        try:
            columns = tuple(DatabaseColumnDisplayEntry(loaded.entry.reference.database_id, c.name,
                            "Not recorded", "Stored snapshot column; formula not recorded", c.eligible) for c in loaded.columns)
            reference = loaded.entry.reference
            self.view.set_database_columns(reference.database_id, columns,
                source_label=f"Revision {reference.revision_id[:12]} · {loaded.entry.rows:,} rows · full history")
            excluded = [f"{c.name}: {c.reason}" for c in loaded.columns if not c.eligible]
            untyped = [c.name for c in loaded.columns if c.eligible and not c.type_known]
            message = "Excluded: " + "; ".join(excluded) if excluded else ""
            if untyped:
                message += "\nUntyped numeric columns: " + ", ".join(untyped)
            self.view.variation_tab.column_issues.setText(message)
        finally:
            self._applying = False

    def _configuration_changed(self):
        if self._disposed or self._applying:
            return
        self.view.variation_tab.results.clear("Configuration changed. Run analysis to produce matching results.")
        self._invalidate_patterns()
        if self._busy and self._kind in ("analysis", "utc_catalogue", "patterns", "pattern_matches"):
            self._generation += 1
            self.service.cancel(self.session)
            self._sync("Configuration changed. Waiting for the cancelled analysis to finish.")

    def run(self):
        if self._disposed or self._busy or self._loaded is None or not self._allowed("analysis_suite.action.run_binning"):
            return
        try:
            configuration = self.view.variation_tab.configuration()
            if configuration is None:
                raise ValueError("Select one or more columns with valid settings.")
            request = AnalysisRequest.from_configuration(self._loaded.entry.reference, configuration)
        except (ValueError, TypeError, KeyError) as exc:
            self._error(str(exc))
            return
        self.view.variation_tab.results.clear("Analysis running…")
        self._invalidate_patterns()
        self._submit("analysis", lambda session, **kw: self.service.submit_analysis(session, request, **kw), self._analysis_completed)

    def _analysis_completed(self, result):
        from leonardo.analysis.trend_start_patterns import analysis_key
        self._binning_result = result
        self.view.pattern_tab.set_source(result.entry, analysis_key(result), tuple(
            (c.request.source, c.request.measurement, c.profile.profile_id if c.profile is not None else None)
            for c in result.columns))
        self.view.variation_tab.results.set_result(result)
        message = "Completed with column issues" if result.has_issues else "Analysis completed"
        self.view.set_operation("Variation & Binning", "Completed", message, current=1, total=1)
        self.view.log.append(f"{message}: {result.entry.name}, revision {result.entry.reference.revision_id[:12]}, {len(result.columns)} independent columns.")

    def _invalidate_patterns(self):
        if self._refinement_active and not self._disposed:
            self.service.clear_refinement_workspace(self.session)
            self._generation += 1
        self._refinement_active = False
        self.view.pattern_tab.post_refinement.clear()
        self._binning_result = None
        self._study_result = None
        self.view.pattern_tab.clear_source()

    def _study_configuration_changed(self):
        if self._disposed or self._applying:
            return
        self._study_result = None
        if self._busy and self._kind in ("patterns", "pattern_matches"):
            self._generation += 1
            self.service.cancel(self.session)
            self._sync("Event context changed. Waiting for the cancelled study to finish.")

    def load_pattern_catalogue(self):
        if (self._disposed or self._busy or self._binning_result is None
                or not self._allowed("analysis_suite.patterns.load_catalogue")):
            return
        parent = self._binning_result
        self._study_result = None
        self.view.pattern_tab.clear_catalogue()
        self._submit("utc_catalogue", lambda session, **kw: self.service.submit_pattern_catalogue(session, parent, **kw),
                     self.view.pattern_tab.set_catalogue)

    def run_patterns(self):
        if (self._disposed or self._busy or self._binning_result is None
                or not self._allowed("analysis_suite.patterns.run")):
            return
        try:
            request = self.view.pattern_tab.request()
        except (ValueError, TypeError) as exc:
            self._error(str(exc))
            return
        parent = self._binning_result
        self._study_result = None
        self.view.pattern_tab.results.clear("Event study running…")
        self._submit("patterns", lambda session, **kw: self.service.submit_patterns(session, parent, request, **kw), self._patterns_completed)

    def _patterns_completed(self, result):
        self._study_result = result
        self.view.pattern_tab.results.set_result(result)
        self.view.log.append(f"Event study completed: {result.request.role_label}, {result.request.family or 'All families'}, "
                             f"revision {result.request.reference.revision_id[:12]}. Retrospective association.")

    def pattern_matches(self, pattern_id, cohort):
        action = "target_matches" if cohort == "target" else "comparison_matches"
        if (self._disposed or self._busy or self._study_result is None
                or not self._allowed("analysis_suite.patterns."+action)):
            return
        study = self._study_result
        rows = study.frame("patterns")
        condition = rows.loc[rows.pattern_id == pattern_id, "condition"].iloc[0]
        self._submit("pattern_matches",
            lambda session, **kw: self.service.submit_pattern_matches(session, study, pattern_id, cohort, **kw),
            lambda frame: self.view.pattern_tab.results.show_matches(frame, cohort=cohort, condition=condition))

    def _submit(self, kind, submit, handler):
        self._busy = True
        self._kind = kind
        self._generation += 1
        generation = self._generation
        token = object()
        self._operation_token = token
        title = {"utc_catalogue": "UTC event catalogue", "patterns": "Trend Start Patterns", "pattern_matches": "Pattern occurrences"}.get(kind, kind.title())
        self._sync("Loading database catalogue…" if kind == "catalog" else "Loading database columns…" if kind == "columns" else title + " running…")
        self.view.set_operation(title, "Running", "Starting " + title)

        def progress(value):
            if not self._disposed and self._operation_token is token and generation == self._generation and self._busy:
                self.view.set_operation(title, "Running", value.message, current=value.current, total=value.total)

        def finished(value):
            if self._disposed or self._operation_token is not token:
                return
            self._operation_token = None
            self._busy = False
            self._kind = None
            current = generation == self._generation
            if not current or value.status == "cancelled":
                self.view.set_operation(title, "Cancelled", "Cancelled; no result was published.")
                if kind == "catalog":
                    self._catalog_cancelled()
                if kind == "analysis" and not self._pending_source:
                    self.view.variation_tab.results.clear("Analysis cancelled. No result was published.")
                if kind == "patterns":
                    self.view.pattern_tab.results.clear("Study cancelled. No result was published.")
                if kind == "utc_catalogue" and not self._pending_source:
                    self.view.pattern_tab.clear_catalogue("UTC catalogue cancelled. Load again to retry.")
            elif value.status == "failed":
                self._error(value.error_message or "Analysis operation failed")
                if kind == "analysis":
                    self.view.variation_tab.results.clear("Analysis failed. See Operation and Log for details.")
                if kind == "patterns":
                    self.view.pattern_tab.results.clear("Study failed. See Operation and Log for details.")
                if kind == "utc_catalogue":
                    self.view.pattern_tab.clear_catalogue("UTC catalogue failed. See Operation and Log.")
                if kind == "catalog":
                    self.view.catalog_label.setText("Catalogue load failed. Open Select Databases and refresh to retry.")
                    self.view._source_label = self.view.catalog_label.text()
            else:
                self.view.set_operation(title, "Completed", title + " completed", current=1, total=1)
                handler(value.value)
            if self._pending_source and not self._busy:
                self._pending_source = False
                self._source_changed(self.view.variation_tab.active_database_id())
            if not self._busy:
                self._sync()

        try:
            submit(self.session, progress_callback=progress, result_callback=finished, callback_dispatcher=self._dispatcher.dispatch)
        except (RuntimeError, ValueError, TypeError) as exc:
            if self._operation_token is not token:
                return
            self._operation_token = None
            self._busy = False
            self._kind = None
            self._error(str(exc))
            self._sync(str(exc))

    def clear_pin_selection(self):
        if not self._disposed and not self._busy and self._allowed("analysis_suite.patterns.pin_clear"):
            self.view.pattern_tab.results.clear_pin_selection()

    def _confirm_refinement(self, message):
        return QMessageBox.question(self.view, "Pinned refinement", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def pin_patterns(self, pattern_ids):
        if (self._disposed or self._busy or self._study_result is None or self._binning_result is None
                or not self._allowed("analysis_suite.patterns.pin_selected")):
            return
        self._refinement_active = True
        snapshot = self.service.refinement_snapshot(self.session)
        replacing = snapshot["workspace_present"]
        if replacing and not self._confirm_refinement("Replace the current pinned workspace and its in-session evaluations? "
                "The existing database and discovery results are not deleted."):
            return
        self._submit("refinement_pin", lambda session, **kw: self.service.submit_pin_patterns(session,
            self._binning_result, self.view.pattern_tab._catalogue, self._study_result, tuple(pattern_ids),
            replace_workspace=replacing, **kw), self._refinement_completed)

    def _refinement_completed(self, _=None):
        snapshot = self.service.refinement_snapshot(self.session)
        page = self.view.pattern_tab.post_refinement
        if snapshot["workspace_present"]:
            result = self.service.refinement_result(self.session, snapshot["set_id"], snapshot["active_checkpoint_id"])
            page.show_checkpoint(snapshot, result)
            self.view.pattern_tab.results.views.setCurrentWidget(page)
        else:
            page.clear()

    def refinement_draft_changed(self):
        if self._disposed or not self._refinement_active:
            return
        self._allowed(self.view.pattern_tab.post_refinement.editor.objectName())
        self.service.invalidate_refinement_draft(self.session)
        if self._busy and self._kind.startswith("refinement_"):
            self._generation += 1
            self._sync("Draft changed; previous checkpoint retained.")

    def select_refinement_checkpoint(self, checkpoint_id):
        if self._disposed or not self._refinement_active or not self._allowed("analysis_suite.patterns.post_refinement.history"):
            return
        try:
            snapshot = self.service.refinement_snapshot(self.session)
            self.service.select_refinement_checkpoint(self.session, snapshot["set_id"], checkpoint_id)
            if self._busy:
                self._generation += 1
            self._refinement_completed()
        except (ValueError, RuntimeError) as exc:
            self._error(str(exc))

    def refinement_action(self, action):
        if (self._disposed or self._busy or not self._refinement_active
                or not self._allowed("analysis_suite.patterns.post_refinement."+action)):
            return
        try:
            snapshot = self.service.refinement_snapshot(self.session)
            if not snapshot["workspace_present"]:
                raise ValueError("Pin combinations before refining")
            set_id, current = snapshot["set_id"], snapshot["active_checkpoint_id"]
            page = self.view.pattern_tab.post_refinement
            if action == "compare_parent":
                page.show_comparison(self.service.refinement_comparison(self.session, set_id, current))
            elif action in ("reset_parent", "reset_discovery"):
                selected = snapshot["source_discovery_id"] if action == "reset_discovery" else next(
                    row["parent_id"] for row in snapshot["history"] if row["checkpoint_id"] == current)
                self.service.select_refinement_checkpoint(self.session, set_id, selected)
                self._refinement_completed()
            elif action == "discard":
                if self._confirm_refinement("Discard this leaf evaluation from the in-session history?"):
                    self.service.discard_refinement_checkpoint(self.session, set_id, current)
                    self._refinement_completed()
            elif action == "clear_workspace":
                if self._confirm_refinement("Clear the pinned workspace and its in-session evaluations? No database is deleted."):
                    self.service.clear_refinement_workspace(self.session)
                    self._refinement_completed()
            elif action in ("evaluate", "search_new"):
                refinement = page.draft()
                submit = self.service.submit_evaluate_pinned if action == "evaluate" else self.service.submit_refinement_search
                kind = "refinement_evaluate" if action == "evaluate" else "refinement_search"
                self._submit(kind, lambda session, **kw: submit(session, set_id, current, snapshot["generation"], refinement, **kw),
                    self._refinement_completed if action == "evaluate" else self._refinement_search_completed)
        except (ValueError, RuntimeError, TypeError) as exc:
            self._error(str(exc))

    def _refinement_search_completed(self, result):
        self._patterns_completed(result)
        snapshot = self.service.refinement_snapshot(self.session)
        checkpoint = snapshot["active_checkpoint_id"]
        if result.granular_definition is not None:
            checkpoint = checkpoint[:12]+"… (full identity in tooltip)"
        self.view.pattern_tab.results.context.setText("New discovery from pinned checkpoint "+checkpoint+
            "\nNEW DISCOVERY\n"+self.view.pattern_tab.results.context.text())
        self.view.pattern_tab.results.views.setCurrentIndex(2)
        self.view.log.append("NEW DISCOVERY completed. The pinned workspace and its selected checkpoint were retained.")
        if result.granular_definition is not None:
            from leonardo.analysis.refinement_models import summarize_granular_refinement
            self.view.log.append("Applied granular definition: "+summarize_granular_refinement(result.granular_definition))

    def refinement_matches(self, pattern_id, cohort):
        if (self._disposed or self._busy or not self._refinement_active
                or not self._allowed("analysis_suite.patterns.post_refinement."+cohort+"_matches")):
            return
        snapshot = self.service.refinement_snapshot(self.session)
        self._submit("refinement_matches", lambda session, **kw: self.service.submit_refinement_matches(session,
            snapshot["set_id"], snapshot["active_checkpoint_id"], pattern_id, cohort, **kw),
            self.view.pattern_tab.post_refinement.show_matches)

    def _refinement_rule_changed(self):
        if not self._disposed and self._busy and self._kind in ("refinement_matches", "refinement_inspection"):
            self.service.invalidate_refinement_draft(self.session)
            self._generation += 1

    def inspect_refinement_combination(self, payload):
        if (self._disposed or self._busy or not self._refinement_active
                or not self._allowed("analysis_suite.patterns.post_refinement.inspector.inspect")):
            return
        snapshot=self.service.refinement_snapshot(self.session)
        self._submit("refinement_inspection",lambda session,**kw:self.service.submit_combination_inspection(
            session,snapshot["set_id"],snapshot["active_checkpoint_id"],snapshot["generation"],
            payload["pattern_id"],payload["options"],variant_key=payload.get("variant_key"),**kw),self._inspection_completed)

    def run_refinement_sensitivity(self, omissions):
        if (self._disposed or self._busy or not self._refinement_active
                or not self._allowed("analysis_suite.patterns.post_refinement.inspector.sensitivity")):
            return
        snapshot=self.service.refinement_snapshot(self.session)
        self._submit("refinement_sensitivity",lambda session,**kw:self.service.submit_refinement_sensitivity(
            session,snapshot["set_id"],snapshot["active_checkpoint_id"],snapshot["generation"],tuple(omissions),**kw),self._sensitivity_completed)

    def _inspection_completed(self, report):
        snapshot=self.service.refinement_snapshot(self.session)
        accepted=self.service.refinement_inspection_result(self.session,snapshot["set_id"])
        if accepted is None or accepted.report_id!=report.report_id:
            self._error("Inspection binding is stale; completed checkpoint retained.");return
        self.view.pattern_tab.post_refinement.show_inspection(accepted,snapshot)

    def _sensitivity_completed(self, report):
        snapshot=self.service.refinement_snapshot(self.session)
        accepted=self.service.refinement_sensitivity_result(self.session,snapshot["set_id"])
        if accepted is None or accepted.report_id!=report.report_id:
            self._error("Sensitivity binding is stale; completed checkpoint retained.");return
        page=self.view.pattern_tab.post_refinement
        page.show_inspection(self.service.refinement_inspection_result(self.session,snapshot["set_id"]),snapshot)
        page.show_sensitivity(accepted,snapshot)

    def _inspection_options_changed(self):
        page=self.view.pattern_tab.post_refinement
        if (not self._disposed and self._busy and self._kind==page.inspector.pending_intent_kind
                and self._kind in ("refinement_inspection","refinement_sensitivity")):
            self.service.invalidate_refinement_draft(self.session)
            self._generation+=1
            self._sync("Report options changed; previous completed checkpoint/report retained.")

    def _clear_refinement_reports(self):
        if (self._disposed or not self._refinement_active
                or not self._allowed("analysis_suite.patterns.post_refinement.inspector.clear_reports")):
            return
        snapshot=self.service.refinement_snapshot(self.session)
        self.service.clear_refinement_reports(self.session,snapshot["set_id"])
        if self._busy:self._generation+=1
        snapshot=self.service.refinement_snapshot(self.session)
        page=self.view.pattern_tab.post_refinement
        page.show_inspection(None,snapshot);page.show_sensitivity(None,snapshot)
        self._sync("Report cache cleared; history and draft retained.")


    def _error(self, message):
        self.view.set_operation("Analysis", "Failed", message)
        self.view.log.append("Analysis error: " + message)

    def _catalog_cancelled(self):
        if self._catalog_summary is None:
            message = "Catalogue load cancelled. No catalogue loaded. Use Refresh Databases to retry."
        else:
            message = f"Catalogue refresh cancelled. Previous catalogue retained: {self._catalog_summary} Use Refresh Databases to retry."
        self._reload_identity = None
        self.view._source_label = message
        self.view.catalog_label.setText(message)

    def cancel(self):
        if self._disposed or not self._allowed("analysis_suite.action.cancel_binning"):
            return
        if self._waiting_refresh:
            self._waiting_refresh = False
            self._retry.stop()
            self._catalog_cancelled()
            self.view.set_operation("Database catalogue", "Cancelled", self.view._source_label)
            self._sync()
            return
        if self._busy and self.service.cancel(self.session):
            self._generation += 1
            name = self.view.operation_labels["name"].text()
            self.view.set_operation(name, "Cancelling", "Waiting for the current operation to finish; its result will be discarded.")
            self._sync("Cancelling…")

    def refresh_display_time(self):
        if not self._disposed:
            self.view.refresh_display_time()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._generation += 1
        self._retry.stop()
        self._dispatcher.close()
        self.service.end_session(self.session)
        self._loaded = None
        self._catalog.clear()
        self.view.show_source_details(())
        self.view.variation_tab.results.clear()
        self._invalidate_patterns()


def _display_entry(entry):
    market = entry.market_id
    return DatabaseDisplayEntry(entry.reference.database_id, entry.name, market.exchange, market.market_type,
                                market.symbol, market.timeframe, entry.rows, entry.columns,
                                entry.first_timestamp_ms, entry.last_timestamp_ms)
