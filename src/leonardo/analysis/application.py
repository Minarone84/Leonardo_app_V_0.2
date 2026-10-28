"""Submit Analysis work to shared Core; retain cancelled workers until drained."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import json
from threading import Event, RLock
from uuid import uuid4

from leonardo.core.core_runner import CoreRunner, TaskResult
from .models import AnalysisRequest, DatabaseReference
from .service import AnalysisService


@dataclass
class _RefinementWorkspace:
    frozen: object
    discovery: object
    binning: object
    catalogue: object
    active: str
    evaluations: dict = field(default_factory=dict)
    ordinals: dict = field(default_factory=dict)
    next_ordinal: int = 1
    candidate: dict | None = None
    inspection: object | None = None
    sensitivity: object | None = None

    @property
    def retained_bytes(self):
        return sum(json.loads(e.context)["estimated_retained_match_state_bytes"]
                   for e in self.evaluations.values())

    @property
    def retained_population_bytes(self):
        return _gr03_population_bytes(self)

    @property
    def retained_total_bytes(self):
        return self.retained_bytes + self.retained_population_bytes + self.retained_report_bytes

    @property
    def retained_report_bytes(self):
        return sum(report.retained_bytes for report in (self.inspection, self.sensitivity) if report is not None)


@dataclass
class _Operation:
    session: str
    cancelled: Event = field(default_factory=Event)
    started: bool = False
    finished: bool = False
    terminal: TaskResult | None = None
    task_id: str | None = None
    delivered: bool = False
    queued: bool = False

    def checkpoint(self):
        if self.cancelled.is_set():
            raise asyncio.CancelledError("Analysis cancellation requested")


class AnalysisApplicationService:
    def __init__(self, runner: CoreRunner, service: AnalysisService):
        self._runner = runner
        self._service = service
        self._lock = RLock()
        self._sessions: set[str] = set()
        self._operations: dict[str, _Operation] = {}
        self._refinements: dict[str, _RefinementWorkspace] = {}
        self._refinement_generations: dict[str, int] = {}

    def begin_session(self):
        session = uuid4().hex
        with self._lock:
            self._sessions.add(session)
            self._refinement_generations[session] = 0
        return session

    def end_session(self, session):
        with self._lock:
            self._sessions.discard(session)
        self.cancel(session)
        with self._lock:
            self._refinements.pop(session, None)
            self._refinement_generations.pop(session, None)
            operation = self._operations.get(session)
            if operation is not None and operation.finished:
                self._operations.pop(session)

    def _refinement_session(self, session):
        if session not in self._sessions:
            raise RuntimeError("Analysis session is closed")

    def _workspace(self, session, set_id, checkpoint_id=None):
        self._refinement_session(session)
        workspace = self._refinements.get(session)
        if workspace is None or workspace.frozen.set_id != set_id:
            raise ValueError("frozen set does not belong to this session")
        if checkpoint_id is not None and checkpoint_id != workspace.frozen.source_discovery_id and checkpoint_id not in workspace.evaluations:
            raise ValueError("checkpoint does not belong to this workspace")
        return workspace

    def refinement_snapshot(self, session):
        with self._lock:
            self._refinement_session(session)
            workspace = self._refinements.get(session)
            snapshot = dict(generation=self._refinement_generations[session], workspace_present=workspace is not None,
                root_id=None, set_id=None, source_discovery_id=None, active_checkpoint_id=None,
                original_request=None, active_refinement=None, pinned_count=0, pinned_ids=(),
                previous_families=(), evaluation_count=0, evaluation_limit=20,
                retained_match_bytes=0, match_budget_bytes=134217728, history=[],
                active_filter_kind="simple", source_filter_kind="simple", filter_context={},
                retained_population_bytes=0, retained_total_bytes=0, retained_budget_bytes=134217728)
            if workspace is None:
                return snapshot
            frozen = workspace.frozen
            source_definition = _gr03_definition(workspace.discovery, frozen.original_request.refinement)
            history = [dict(checkpoint_id=frozen.source_discovery_id, parent_id=None, kind="discovery",
                ordinal=0, refinement_summary=_gr03_summary(source_definition), filter_kind=_gr03_kind(source_definition),
                definition_id=source_definition.identity if _gr03_kind(source_definition)=="granular" else None,
                active=workspace.active == frozen.source_discovery_id)]
            history.extend(dict(checkpoint_id=e.evaluation_id, parent_id=e.parent_id, kind="evaluation",
                ordinal=workspace.ordinals[e.evaluation_id], refinement_summary=_gr03_summary(_gr03_definition(e,e.request.refinement)),
                filter_kind=_gr03_kind(_gr03_definition(e,e.request.refinement)),
                definition_id=e.granular_definition.identity if e.granular_definition is not None else None,
                active=workspace.active == e.evaluation_id) for e in workspace.evaluations.values())
            active = workspace.evaluations.get(workspace.active)
            snapshot.update(root_id=frozen.root_id, set_id=frozen.set_id, source_discovery_id=frozen.source_discovery_id,
                active_checkpoint_id=workspace.active, original_request=frozen.original_request,
                active_refinement=source_definition if active is None else _gr03_definition(active,active.request.refinement),
                active_filter_kind=_gr03_kind(source_definition if active is None else _gr03_definition(active,active.request.refinement)),
                source_filter_kind=_gr03_kind(source_definition), filter_context=frozen.filter_context(),
                retained_population_bytes=workspace.retained_population_bytes,retained_total_bytes=workspace.retained_total_bytes,
                pinned_count=len(frozen.patterns), pinned_ids=tuple(p.pattern_id for p in frozen.patterns),
                previous_families=tuple(sorted({event["family"] for event in
                    workspace.catalogue.instance(frozen.original_request.instance_id)["events"]})),
                evaluation_count=len(workspace.evaluations), retained_match_bytes=workspace.retained_bytes, history=history)
            from .pattern_models import _gr05_scope_enabled, _gr05_resolve_scope
            universe = snapshot["filter_context"].get("family_scope_context", {}).get("families")
            def scope_for(definition):
                return _gr05_resolve_scope(frozen.original_request, definition, universe)
            if _gr05_scope_enabled(frozen.original_request, source_definition):
                snapshot["source_family_scope"] = scope_for(source_definition)
            if _gr05_scope_enabled(frozen.original_request, snapshot["active_refinement"]):
                snapshot["applied_family_scope"] = scope_for(snapshot["active_refinement"])
            for row in history:
                result = workspace.evaluations.get(row["checkpoint_id"])
                definition = source_definition if result is None else _gr03_definition(result, result.request.refinement)
                if _gr05_scope_enabled(frozen.original_request, definition):
                    row["applied_family_scope"] = scope_for(definition)
                    row["source_family_scope"] = scope_for(source_definition)
            if workspace.inspection is not None or workspace.sensitivity is not None:
                snapshot["retained_report_bytes"] = workspace.retained_report_bytes
                for name,report in (("inspection_report",workspace.inspection),("sensitivity_report",workspace.sensitivity)):
                    if report is not None: snapshot[name] = _gr06_report_metadata(report,workspace)
            return snapshot

    def refinement_result(self, session, set_id, checkpoint_id):
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            return workspace.discovery if checkpoint_id == workspace.frozen.source_discovery_id else workspace.evaluations[checkpoint_id]

    def refinement_comparison(self, session, set_id, checkpoint_id):
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            if checkpoint_id == workspace.frozen.source_discovery_id:
                raise ValueError("source discovery has no parent comparison")
            evaluation = workspace.evaluations[checkpoint_id]
            parent = workspace.evaluations.get(evaluation.parent_id)
            frozen = workspace.frozen
        return self._service.compare_pattern_evaluation(frozen, evaluation, parent=parent)

    def invalidate_refinement_draft(self, session):
        with self._lock:
            generation, task_id = self._invalidate_refinement_locked(session)
        if task_id is not None:
            self._runner.cancel(task_id)
        return generation

    def clear_refinement_workspace(self, session):
        with self._lock:
            _, task_id = self._invalidate_refinement_locked(session)
            self._refinements.pop(session, None)
        if task_id is not None:
            self._runner.cancel(task_id)

    def select_refinement_checkpoint(self, session, set_id, checkpoint_id):
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            _, task_id = self._invalidate_refinement_locked(session)
            workspace.active = checkpoint_id
            snapshot = self.refinement_snapshot(session)
        if task_id is not None:
            self._runner.cancel(task_id)
        return snapshot

    def discard_refinement_checkpoint(self, session, set_id, checkpoint_id):
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            if checkpoint_id == workspace.frozen.source_discovery_id:
                raise ValueError("source discovery cannot be discarded")
            if any(e.parent_id == checkpoint_id for e in workspace.evaluations.values()):
                raise ValueError("only a leaf evaluation can be discarded")
            _, task_id = self._invalidate_refinement_locked(session)
            evaluation = workspace.evaluations.pop(checkpoint_id)
            workspace.ordinals.pop(checkpoint_id)
            if workspace.active == checkpoint_id:
                workspace.active = evaluation.parent_id
            snapshot = self.refinement_snapshot(session)
        if task_id is not None:
            self._runner.cancel(task_id)
        return snapshot

    def _refinement_submission(self, session, kind, work, accept, *, workspace=None, parent_id=None,
                               generation=None, metadata=None, **callbacks):
        with self._lock:
            self._refinement_session(session)
            if generation is not None and generation != self._refinement_generations[session]:
                raise ValueError("refinement draft generation is stale")
            if session in self._operations or self.has_draining_workers:
                raise RuntimeError("An Analysis operation is still running or cancelling")
            self._refinement_generations[session] += 1
            captured = self._refinement_generations[session]
            def current():
                return (session in self._sessions and self._refinement_generations[session] == captured
                    and self._refinements.get(session) is workspace
                    and (parent_id is None or workspace.active == parent_id))
            details = {"generation": captured, **(metadata or {})}
            if workspace is not None and kind != "refinement_pin":
                frozen = workspace.frozen
                details.update(root_id=frozen.root_id, set_id=frozen.set_id,
                               source_discovery_id=frozen.source_discovery_id,
                               database_id=frozen.original_request.reference.database_id,
                               revision_id=frozen.original_request.reference.revision_id)
            if parent_id is not None:
                details["parent_id"] = parent_id
            return self._submit(session, kind, work, metadata=details, refinement_guard=current,
                                refinement_accept=accept, **callbacks)

    def submit_pin_patterns(self, session, binning, catalogue, discovery, pattern_ids,
                            *, replace_workspace=False, **callbacks):
        with self._lock:
            self._refinement_session(session)
            workspace = self._refinements.get(session)
            if workspace is not None and not replace_workspace:
                raise ValueError("confirm replacement of the current pinned workspace")
            ids = tuple(pattern_ids)
            def accept(frozen):
                from .refinement_models import FrozenPatternSet
                if (not isinstance(frozen, FrozenPatternSet) or frozen.original_request != discovery.request
                        or {p.pattern_id for p in frozen.patterns} != set(ids)):
                    raise ValueError("pin returned inconsistent source or rule identities")
                replacement = _RefinementWorkspace(frozen, discovery, binning, catalogue, frozen.source_discovery_id)
                if frozen.granular_definition != discovery.granular_definition:
                    raise ValueError("pin returned inconsistent granular source definition")
                if replacement.retained_total_bytes > 134217728:
                    raise ValueError("pinned population exceeds retained workspace budget")
                self._refinements[session] = replacement
            return self._refinement_submission(session, "refinement_pin",
                lambda **kw: self._service.pin_pattern_set(binning, catalogue, discovery, ids, **kw), accept,
                workspace=workspace, metadata={"database_id": discovery.request.reference.database_id,
                    "revision_id": discovery.request.reference.revision_id}, **callbacks)

    def submit_evaluate_pinned(self, session, set_id, parent_id, generation, refinement, **callbacks):
        from .pattern_models import PatternRefinement
        from .refinement_models import PatternEvaluation
        with self._lock:
            workspace = self._workspace(session, set_id, parent_id)
            if workspace.active != parent_id:
                raise ValueError("evaluation parent must be the selected checkpoint")
            frozen = workspace.frozen
            _gr03_validate_draft(frozen,refinement)
            granular = _gr03_kind(refinement)=="granular"
            request = frozen.original_request if granular else replace(frozen.original_request, refinement=refinement)
            if request.pre_event.chronological and frozen.resolved_split is not None:
                request = replace(request, pre_event=replace(request.pre_event, split_ms=frozen.resolved_split))
            duplicate = next((e for e in workspace.evaluations.values()
                if e.parent_id == parent_id and type(_gr03_definition(e,e.request.refinement)) is type(refinement)
                and (e.granular_definition.identity==refinement.identity if granular and e.granular_definition is not None
                     else e.granular_definition is None and e.request.refinement==refinement)), None)
            remaining = 134217728-workspace.retained_total_bytes
            if duplicate is None and len(workspace.evaluations) >= 20:
                raise ValueError("20 evaluation limit reached; discard a leaf or replace the workspace")
            if duplicate is None and remaining < 1:
                raise ValueError("retained match-state budget exhausted; discard a leaf or replace the workspace")
            parent = workspace.evaluations.get(parent_id)
            def work(**kw):
                kw["checkpoint"]()
                return duplicate if duplicate is not None else self._service.evaluate_pattern_set(
                    frozen, refinement if granular else request.refinement, parent=parent, memory_limit_bytes=remaining, **kw)
            def accept(evaluation):
                if (not isinstance(evaluation, PatternEvaluation) or evaluation.root_id != frozen.root_id
                        or evaluation.set_id != set_id or evaluation.parent_id != parent_id
                        or evaluation.request != request or not evaluation.evaluation_id
                        or evaluation.evaluation_id == frozen.source_discovery_id):
                    raise ValueError("evaluation returned inconsistent workspace or parent identities")
                if granular:
                    total = _gr03_validate_output(evaluation,frozen,refinement,parent_id)
                elif evaluation.granular_definition is not None:
                    raise ValueError("simple evaluation returned a granular definition")
                _gr05_validate_delivery(evaluation, frozen, refinement, parent_id)
                if evaluation.evaluation_id not in workspace.evaluations:
                    if granular and total > 134217728-workspace.retained_total_bytes:
                        raise ValueError("evaluation exceeds retained combined workspace budget")
                    estimate = json.loads(evaluation.context)["estimated_retained_match_state_bytes"]
                    if type(estimate) is not int or estimate < 0 or estimate > remaining:
                        raise ValueError("evaluation exceeds the retained match-state budget")
                    workspace.evaluations[evaluation.evaluation_id] = evaluation
                    workspace.ordinals[evaluation.evaluation_id] = workspace.next_ordinal
                    workspace.next_ordinal += 1
                workspace.active = evaluation.evaluation_id
            return self._refinement_submission(session, "refinement_evaluate", work, accept,
                workspace=workspace, parent_id=parent_id, generation=generation, **callbacks)

    def submit_refinement_matches(self, session, set_id, checkpoint_id, pattern_id, cohort, **callbacks):
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            if workspace.active != checkpoint_id or pattern_id not in {p.pattern_id for p in workspace.frozen.patterns}:
                raise ValueError("select a pinned rule in the active checkpoint")
            if cohort not in ("target", "comparison"):
                raise ValueError("select target or comparison observations")
            result = self.refinement_result(session, set_id, checkpoint_id)
            return self._refinement_submission(session, "refinement_matches",
                lambda **kw: self._service.pattern_matches(result, pattern_id, cohort, **kw), lambda value: None,
                workspace=workspace, parent_id=checkpoint_id,
                metadata={"pattern_id": pattern_id, "cohort": cohort}, **callbacks)

    def submit_refinement_search(self, session, set_id, parent_id, generation, refinement, **callbacks):
        with self._lock:
            workspace = self._workspace(session, set_id, parent_id)
            if workspace.active != parent_id:
                raise ValueError("search parent must be the selected checkpoint")
            frozen = workspace.frozen
            _gr03_validate_draft(frozen,refinement)
            granular = _gr03_kind(refinement)=="granular"
            from .pattern_models import _gr05_scope_enabled
            from .pattern_refinement import _gr05_search_request
            scoped_simple = not granular and _gr05_scope_enabled(frozen.original_request, refinement)
            request = (_gr05_search_request(frozen, refinement) if scoped_simple else
                frozen.original_request if granular else replace(frozen.original_request, refinement=refinement))
            if request.pre_event.chronological and frozen.resolved_split is not None:
                request = replace(request, pre_event=replace(request.pre_event, split_ms=frozen.resolved_split))
            remaining = 134217728-workspace.retained_bytes-_gr03_population_bytes(workspace,without_candidate=True)-workspace.retained_report_bytes
            if granular and remaining < 1:
                raise ValueError("retained population budget exhausted; discard a leaf or replace the workspace")
            def accept(study):
                from .pattern_models import PatternStudy
                if not isinstance(study, PatternStudy) or study.request != request:
                    raise ValueError("new discovery returned inconsistent request")
                if granular:
                    charge = _gr03_validate_output(study,frozen,refinement,parent_id,search=True)
                    if charge > 134217728-workspace.retained_bytes-_gr03_population_bytes(workspace,without_candidate=True)-workspace.retained_report_bytes:
                        raise ValueError("new discovery exceeds retained population budget")
                elif study.granular_definition is not None:
                    raise ValueError("simple discovery returned a granular definition")
                _gr05_validate_delivery(study, frozen, refinement, parent_id, search=True)
                candidate = dict(source_discovery_id=frozen.source_discovery_id, set_id=set_id,
                    parent_id=parent_id, generation=self._refinement_generations[session], request=request)
                if granular:
                    candidate["study"] = study
                workspace.candidate = candidate
            def work(**kw):
                if granular:
                    return self._service.search_granular_patterns(frozen,workspace.binning,workspace.catalogue,refinement,
                        parent_id=parent_id,population_limit_bytes=remaining,**kw)
                if scoped_simple:
                    return self._service.search_family_patterns(frozen, workspace.binning, workspace.catalogue,
                        refinement, parent_id=parent_id, **kw)
                return self._service.run_patterns(workspace.binning,request,**kw)
            return self._refinement_submission(session, "refinement_search", work, accept,
                workspace=workspace, parent_id=parent_id, generation=generation,
                metadata={"database_id": request.reference.database_id, "revision_id": request.reference.revision_id,
                          "discovery": "NEW DISCOVERY"}, **callbacks)

    def submit_combination_inspection(self, session, set_id, checkpoint_id, generation,
                                     pattern_id, options, *, variant_key=None, **callbacks):
        from .refinement_models import CombinationInspection, InspectionOptions
        from .trend_start_patterns import _json
        with self._lock:
            workspace = self._workspace(session, set_id, checkpoint_id)
            if workspace.active != checkpoint_id or pattern_id not in {p.pattern_id for p in workspace.frozen.patterns}:
                raise ValueError("select a retained rule at the active completed checkpoint")
            if type(options) is not InspectionOptions:
                raise TypeError("inspection requires InspectionOptions")
            current = workspace.evaluations.get(checkpoint_id, workspace.discovery)
            parent = workspace.evaluations.get(getattr(current, "parent_id", None))
            sensitivity = workspace.sensitivity if variant_key is not None else None
            if variant_key is not None:
                if sensitivity is None or not _gr06_current(sensitivity, workspace):
                    raise ValueError("select a variant from the current sensitivity report")
                current = sensitivity.variant(variant_key)
                parent = workspace.evaluations.get(current.parent_id)
            remaining = 134217728-workspace.retained_total_bytes
            if remaining < 1: raise ValueError("report allowance exhausted; Clear report cache explicitly")
            expected = dict(root_id=workspace.frozen.root_id, set_id=set_id,
                source_discovery_id=workspace.frozen.source_discovery_id,
                checkpoint_id=checkpoint_id, pattern_id=pattern_id, options_id=options.identity,
                definition_id=_gr06_definition_id(current),
                actual_parent_id=getattr(current, "parent_id", None))
            if sensitivity is not None:
                expected.update(sensitivity_report_id=sensitivity.report_id,variant_key=variant_key,
                    variant_evaluation_id=current.evaluation_id)
            def work(**kw):
                report = self._service.inspect_combination(workspace.frozen, workspace.discovery, current, parent,
                    pattern_id, options, memory_limit_bytes=remaining, **kw)
                if sensitivity is not None:
                    payload = json.loads(report.payload)
                    payload["header"].update(checkpoint_id=checkpoint_id, sensitivity_report_id=sensitivity.report_id,
                        variant_key=variant_key,variant_evaluation_id=current.evaluation_id,
                        variant_notice="Sensitivity variant, not a checkpoint")
                    report = CombinationInspection(_json(payload))
                return report
            def accept(report):
                if type(report) is not CombinationInspection:
                    raise TypeError("inspection returned the wrong report model")
                _gr06_validate_report(report, expected, workspace)
                if sensitivity is not None and workspace.sensitivity is not sensitivity:
                    raise ValueError("sensitivity report was replaced before inspection delivery")
                workspace.inspection = report
            return self._refinement_submission(session, "refinement_inspection", work, accept,
                workspace=workspace,parent_id=checkpoint_id,generation=generation,
                metadata=dict(pattern_id=pattern_id,options_id=options.identity,variant_key=variant_key),**callbacks)

    def submit_refinement_sensitivity(self, session, set_id, checkpoint_id, generation, omissions, **callbacks):
        from .refinement_models import RefinementSensitivity
        from .combination_explanations import plan_filter_omissions
        with self._lock:
            workspace=self._workspace(session,set_id,checkpoint_id)
            if workspace.active!=checkpoint_id:
                raise ValueError("sensitivity requires the active completed checkpoint")
            current=workspace.evaluations.get(checkpoint_id,workspace.discovery)
            context=workspace.frozen.filter_context();omissions=tuple(omissions)
            plan=plan_filter_omissions(current.granular_definition,omissions,source_request=workspace.frozen.original_request,
                column_profiles={n:c["profile_id"] for n,c in context["columns"].items()},
                horizon_source=context.get("horizon_source"),family_universe=context.get("family_scope_context",{}).get("families"))
            remaining=134217728-workspace.retained_total_bytes
            if remaining<1: raise ValueError("report allowance exhausted; Clear report cache explicitly")
            expected=dict(root_id=workspace.frozen.root_id,set_id=set_id,
                source_discovery_id=workspace.frozen.source_discovery_id,checkpoint_id=checkpoint_id,
                definition_id=_gr06_definition_id(current),rule_ids=[p.pattern_id for p in workspace.frozen.patterns])
            def accept(report):
                if type(report) is not RefinementSensitivity:
                    raise TypeError("sensitivity returned the wrong report model")
                _gr06_validate_report(report,expected,workspace)
                if list(report.plan)!=list(plan): raise ValueError("sensitivity changed its planned full definitions")
                if {k for k,_ in report.evaluations}!={p["variant_key"] for p in plan if p["status"]=="valid"}:
                    raise ValueError("sensitivity variant membership mismatch")
                for key,evaluation in report.evaluations:
                    definition=next(p["after"] for p in plan if p["variant_key"]==key)
                    from .refinement_models import GranularRefinement
                    _gr03_validate_output(evaluation,workspace.frozen,GranularRefinement.from_dict(definition),checkpoint_id)
                    if list(evaluation.frame("patterns").pattern_id)!=expected["rule_ids"]:
                        raise ValueError("sensitivity dropped or reordered a pinned rule")
                previous=workspace.sensitivity
                if workspace.inspection is not None and previous is not None and workspace.inspection.header.get("sensitivity_report_id")==previous.report_id:
                    workspace.inspection=None
                workspace.sensitivity=report
            return self._refinement_submission(session,"refinement_sensitivity",
                lambda **kw:self._service.refinement_sensitivity(workspace.frozen,current,omissions,memory_limit_bytes=remaining,**kw),
                accept,workspace=workspace,parent_id=checkpoint_id,generation=generation,
                metadata=dict(omissions=[p["variant_key"] for p in plan],pinned_count=len(workspace.frozen.patterns)),**callbacks)

    def refinement_inspection_result(self, session, set_id):
        with self._lock:
            workspace=self._workspace(session,set_id)
            report=workspace.inspection
            if report is None or not _gr06_current(report,workspace): return None
            sensitivity_id=report.header.get("sensitivity_report_id")
            if sensitivity_id is not None and (workspace.sensitivity is None or workspace.sensitivity.report_id!=sensitivity_id): return None
            return report.validate()

    def refinement_sensitivity_result(self, session, set_id):
        with self._lock:
            workspace=self._workspace(session,set_id)
            report=workspace.sensitivity
            return report.validate() if report is not None and _gr06_current(report,workspace) else None

    def clear_refinement_reports(self, session, set_id):
        with self._lock:
            workspace=self._workspace(session,set_id)
            generation,task_id=self._invalidate_refinement_locked(session)
            workspace.inspection=None
            workspace.sensitivity=None
        if task_id is not None:
            self._runner.cancel(task_id)
        return generation


    def is_busy(self, session):
        with self._lock:
            return session in self._operations

    @property
    def has_draining_workers(self):
        with self._lock:
            return any(op.cancelled.is_set() and not op.finished for op in self._operations.values())

    def submit_catalog(self, session, **callbacks):
        return self._submit(session, "catalog", self._service.catalog, **callbacks)

    def submit_columns(self, session, reference: DatabaseReference, **callbacks):
        return self._submit(session, "columns", lambda **kw: self._service.load_columns(reference, **kw),
                            metadata={"database_id": reference.database_id, "revision_id": reference.revision_id}, **callbacks)

    def submit_analysis(self, session, request: AnalysisRequest, **callbacks):
        return self._submit(session, "analysis", lambda **kw: self._service.run(request, **kw),
                            metadata={"database_id": request.reference.database_id, "revision_id": request.reference.revision_id,
                                      "columns": tuple(c.source for c in request.columns)}, **callbacks)

    def submit_pattern_catalogue(self, session, result, **callbacks):
        return self._submit(session, "utc_catalogue", lambda **kw: self._service.load_pattern_catalogue(result, **kw),
                            metadata={"database_id": result.entry.reference.database_id,
                                      "revision_id": result.entry.reference.revision_id}, **callbacks)

    def submit_patterns(self, session, result, request, **callbacks):
        return self._submit(session, "patterns", lambda **kw: self._service.run_patterns(result, request, **kw),
                            metadata={"database_id": request.reference.database_id,
                                      "revision_id": request.reference.revision_id,
                                      "event_kind": request.event_kind, "family": request.family}, **callbacks)

    def submit_pattern_matches(self, session, study, pattern_id, cohort, **callbacks):
        return self._submit(session, "pattern_matches",
                            lambda **kw: self._service.pattern_matches(study, pattern_id, cohort, **kw),
                            metadata={"database_id": study.request.reference.database_id,
                                      "pattern_id": pattern_id, "cohort": cohort}, **callbacks)

    def _cancel_locked(self, session):
        """Mark the current operation atomically; the caller holds the Analysis lock."""
        operation = self._operations.get(session)
        if operation is None or operation.cancelled.is_set():
            return False, None
        operation.cancelled.set()
        if session in self._refinement_generations:
            self._refinement_generations[session] += 1
        return True, operation.task_id

    def _invalidate_refinement_locked(self, session):
        """Invalidate and capture cancellation without waiting on Core under the lock."""
        self._refinement_session(session)
        self._refinement_generations[session] += 1
        _, task_id = self._cancel_locked(session)
        return self._refinement_generations[session], task_id

    def cancel(self, session):
        with self._lock:
            cancelled, task_id = self._cancel_locked(session)
        if task_id is not None:
            self._runner.cancel(task_id)
        return cancelled

    def cancel_all_pending(self):
        with self._lock:
            sessions = tuple(self._operations)
        return tuple(session for session in sessions if self.cancel(session))

    def _submit(self, session, kind, work, *, result_callback, callback_dispatcher,
                progress_callback=None, metadata=None, refinement_guard=None, refinement_accept=None):
        with self._lock:
            if session not in self._sessions:
                raise RuntimeError("Analysis session is closed")
            if session in self._operations or self.has_draining_workers:
                raise RuntimeError("An Analysis operation is still running or cancelling")
            operation = _Operation(session)
            self._operations[session] = operation

        def deliver_if_finished():
            with self._lock:
                if operation.delivered or operation.queued or not operation.finished or operation.terminal is None:
                    return
                if refinement_guard is not None:
                    operation.queued = True
                    live = session in self._sessions
                    if not live:
                        self._operations.pop(session, None)
                        operation.delivered = True
                    else:
                        callback_dispatcher(deliver_refinement)
                    return
                operation.delivered = True
                self._operations.pop(session, None)
                live = session in self._sessions
                terminal = operation.terminal
                if operation.cancelled.is_set():
                    terminal = TaskResult(terminal.task_id, "cancelled")
            if live:
                # The dispatcher is supplied by the presenter and is safe after
                # disposal. Qt delivery also verifies its session generation.
                callback_dispatcher(lambda: result_callback(terminal))

        def deliver_refinement():
            with self._lock:
                if operation.delivered:
                    return
                operation.delivered = True
                live = session in self._sessions
                terminal = operation.terminal
                valid = (self._operations.get(session) is operation and not operation.cancelled.is_set()
                         and refinement_guard())
                if not valid:
                    terminal = TaskResult(terminal.task_id, "cancelled")
                elif terminal.status == "completed":
                    try:
                        refinement_accept(terminal.value)
                    except (ValueError, TypeError, KeyError) as exc:
                        terminal = TaskResult(terminal.task_id, "failed", error_type=type(exc).__name__, error_message=str(exc))
                if self._operations.get(session) is operation:
                    self._operations.pop(session)
            if live:
                result_callback(terminal)

        def job(reporter):
            with self._lock:
                if operation.finished:
                    raise asyncio.CancelledError()
                operation.started = True
            try:
                operation.checkpoint()
                return work(checkpoint=operation.checkpoint,
                            progress=lambda message, current=None, total=None: reporter.report(message, current=current, total=total))
            finally:
                with self._lock:
                    operation.finished = True
                deliver_if_finished()

        def on_result(result):
            with self._lock:
                operation.terminal = result
                # If the executor future was cancelled before it started, no
                # worker finally block will run. Seal entry under the same lock.
                if not operation.started:
                    operation.finished = True
            deliver_if_finished()

        def on_progress(progress):
            with self._lock:
                live = session in self._sessions and not operation.cancelled.is_set() and not operation.delivered
            if live and progress_callback is not None:
                if refinement_guard is None:
                    callback_dispatcher(lambda: progress_callback(progress))
                else:
                    def deliver_progress():
                        with self._lock:
                            current = (not operation.delivered and not operation.cancelled.is_set()
                                       and self._operations.get(session) is operation and refinement_guard())
                        if current:
                            progress_callback(progress)
                    callback_dispatcher(deliver_progress)

        try:
            submission = self._runner.submit_blocking_job(
                job, task_name=f"analysis.{kind}", allow_duplicate_name=True,
                result_callback=on_result, progress_callback=on_progress,
                correlation_id=uuid4().hex,
                metadata={"area": "analysis", "operation": kind, "session": session, **(metadata or {})},
            )
        except Exception:
            with self._lock:
                self._operations.pop(session, None)
            raise
        with self._lock:
            operation.task_id = submission.task_id
            cancelled = operation.cancelled.is_set()
        if cancelled:
            self._runner.cancel(submission.task_id)
        return submission


def _gr03_definition(result, fallback):
    return result.granular_definition if result.granular_definition is not None else fallback


def _gr03_kind(definition):
    from .refinement_models import GranularRefinement
    return "granular" if type(definition) is GranularRefinement else "simple"


def _gr03_summary(definition):
    from .refinement_models import summarize_granular_refinement
    return summarize_granular_refinement(definition) if _gr03_kind(definition)=="granular" else definition.summary()


def _gr03_populations(workspace, *, without_candidate=False):
    results = [workspace.discovery,*workspace.evaluations.values()]
    if not without_candidate and workspace.candidate and "study" in workspace.candidate:
        results.append(workspace.candidate["study"])
    reports = {}
    for result in results:
        if result.granular_definition is not None:
            report = result._data["_gr03_population"]
            reports[id(report)] = report
    return reports


def _gr03_population_bytes(workspace, *, without_candidate=False):
    from .pattern_refinement import _gr03_charge
    return sum(_gr03_charge(report) for report in _gr03_populations(workspace,without_candidate=without_candidate).values())


def _gr03_validate_draft(frozen, definition):
    from .pattern_models import PatternRefinement
    from .refinement_models import GranularRefinement
    from .pattern_refinement import validate_granular_definition
    if type(definition) is GranularRefinement:
        context = frozen.filter_context()
        if not context:
            raise ValueError("granular editor context absent: repin the original discovery explicitly")
        validate_granular_definition(definition,source_request=frozen.original_request,
            column_profiles={n:c["profile_id"] for n,c in context["columns"].items()},
            horizon_source=context.get("horizon_source"),
            family_universe=context.get("family_scope_context", {}).get("families"))
    elif not isinstance(definition,PatternRefinement):
        raise TypeError("evaluation requires PatternRefinement or exact GranularRefinement")
    else:
        from .pattern_models import _gr05_scope_enabled, _gr05_resolve_scope
        if _gr05_scope_enabled(frozen.original_request, definition):
            scope = _gr05_resolve_scope(frozen.original_request, definition,
                frozen.filter_context().get("family_scope_context", {}).get("families"))
            if scope is None:
                raise ValueError("evaluation requires an analytical family selection")


def _gr03_validate_output(result, frozen, definition, parent_id, *, search=False):
    from .pattern_refinement import _gr03_charge, _gr03_discovery_stamp, _gr04_result_identity, _gr04_header
    from .refinement_models import _plain
    from .trend_start_patterns import _hash
    context = json.loads(result.context)
    if not isinstance(context,dict):
        raise ValueError("granular output requires a context object")
    report = result._data.get("_gr03_population")
    if (result.granular_definition != definition or type(result.granular_definition) is not type(definition)
            or context.get("definition_id")!=definition.identity or context.get("definition")!=definition.to_dict()
            or context.get("active_filter_kind")!="granular" or context.get("legacy_filters_applied") is not False
            or not isinstance(report,dict) or report.get("root_id")!=frozen.root_id or report.get("set_id")!=frozen.set_id
            or report.get("source_discovery_id")!=frozen.source_discovery_id or report.get("definition_id")!=definition.identity
            or report.get("definition")!=definition.to_dict() or report.get("source_request")!=_plain(frozen.original_request)
            or report.get("report_id")!=_gr04_result_identity("population",frozen,definition)
            or context.get("population_report_id")!=report["report_id"] or result._data.get("samples")!=report.get("samples")):
        raise ValueError("granular output returned inconsistent definition or population identities")
    from .pattern_refinement import _grdate_validate_presentation
    _grdate_validate_presentation(result, frozen.original_request, definition)
    header = _gr04_header(frozen, definition)
    if header is not None:
        if context.get("horizon_source") != header or report.get("horizon_source") != header:
            raise ValueError("granular output returned inconsistent horizon source")
    elif "horizon_source" in context or "horizon_source" in report:
        raise ValueError("inactive definition cannot carry a horizon report header")
    if search and ("_gr04_prices" in frozen._root or "_gr04_price_binding" in frozen._root):
        if any(result._data.get(k) != frozen._root.get(k) for k in ("_gr04_prices", "_gr04_price_binding")):
            raise ValueError("granular discovery returned inconsistent pinned prices")
    _gr05_validate_delivery(result, frozen, definition, parent_id, search=search)
    charge = _gr03_charge(report)
    if context.get("retained_population_bytes")!=charge:
        raise ValueError("granular output returned inconsistent population accounting")
    if search:
        expected = dict(root_id=frozen.root_id,set_id=frozen.set_id,checkpoint_id=parent_id)
        if context.get("search_parent")!=expected or result._data.get("_gr03_discovery_binding")!=_gr03_discovery_stamp(result):
            raise ValueError("granular discovery returned inconsistent source or parent binding")
        return charge
    expected = _gr04_result_identity("evaluation",frozen,definition,parent_id=parent_id)
    if (result.evaluation_id!=expected or context.get("evaluation_id")!=expected
            or context.get("root_id")!=frozen.root_id or context.get("set_id")!=frozen.set_id or context.get("parent_id")!=parent_id):
        raise ValueError("granular output returned inconsistent evaluation identity")
    estimate = context.get("estimated_retained_match_state_bytes")
    if type(estimate) is not int or estimate<0 or context.get("retained_total_bytes")!=estimate+charge:
        raise ValueError("granular output returned inconsistent match accounting")
    return charge+estimate


def _gr05_validate_delivery(result, frozen, definition, parent_id, *, search=False):
    from .pattern_models import _gr05_scope_enabled, _gr05_resolve_scope
    from .pattern_refinement import _gr05_validate_presentation, _gr05_discovery_stamp
    from .refinement_models import GranularRefinement
    scope = (_gr05_resolve_scope(frozen.original_request, definition,
        frozen.filter_context().get("family_scope_context", {}).get("families"))
        if _gr05_scope_enabled(frozen.original_request, definition) else None)
    _gr05_validate_presentation(result, scope)
    if search and scope is not None and type(definition) is not GranularRefinement:
        expected = dict(root_id=frozen.root_id, set_id=frozen.set_id, checkpoint_id=parent_id)
        if (json.loads(result.context).get("family_search_parent") != expected
                or result._data.get("_gr05_discovery_binding") != _gr05_discovery_stamp(result)):
            raise ValueError("family discovery returned inconsistent source or parent binding")
        if any(result._data.get(k) != frozen._root.get(k) for k in ("_gr04_prices", "_gr04_price_binding")):
            raise ValueError("family discovery returned inconsistent pinned prices")


def _gr06_definition_id(result):
    from .trend_start_patterns import _hash
    return _hash(_gr03_definition(result,result.request.refinement).to_dict())


def _gr06_current(report,workspace):
    header=report.header
    return (header["root_id"]==workspace.frozen.root_id and header["set_id"]==workspace.frozen.set_id
            and header["checkpoint_id"]==workspace.active)


def _gr06_report_metadata(report,workspace):
    header=report.header
    return dict(report_id=report.report_id,root_id=header["root_id"],set_id=header["set_id"],
        checkpoint_id=header["checkpoint_id"],status="current" if _gr06_current(report,workspace) else "stale",
        retained_bytes=report.retained_bytes)


def _gr06_validate_report(report,expected,workspace):
    report.validate()
    header=report.header
    if any(header.get(k)!=v for k,v in expected.items()):
        raise ValueError("report returned inconsistent captured identities")
    from .refinement_models import CombinationInspection
    if isinstance(report,CombinationInspection):
        from .pattern_refinement import _statuses
        content=json.loads(report.payload)
        current=workspace.evaluations.get(expected["checkpoint_id"],workspace.discovery)
        if "variant_key" in expected:
            current=workspace.sensitivity.variant(expected["variant_key"])
        parent=workspace.evaluations.get(getattr(current,"parent_id",None),workspace.discovery)
        sides={"source":workspace.discovery,"current":current}
        if expected["actual_parent_id"] is not None:sides["parent"]=parent
        if set(content["records"])!=set(sides):raise ValueError("inspection side membership mismatch")
        for side,result in sides.items():
            data=result._data
            statuses=_statuses(result.frame("cohort_assignments").to_dict("records"),data["samples"],
                data["timestamps"],population=data.get("_gr03_population"))
            records=content["records"][side]
            if set(statuses)!=set(records):raise ValueError("inspection row membership mismatch")
            for key,status in statuses.items():
                row=records[key]
                if row.get("row_id")!=key or row.get("side")!=side or any(row.get(k)!=v for k,v in status.items()):
                    raise ValueError("inspection row identity or status mismatch")
        for link in content["links"].values():
            if link["side"] not in sides or len(link["row_ids"])!=len(set(link["row_ids"])) or not set(link["row_ids"])<=set(content["records"][link["side"]]):
                raise ValueError("inspection support membership mismatch")
    charge=report.retained_bytes
    remaining=134217728-workspace.retained_total_bytes
    if type(charge) is not int or charge<1 or charge>remaining:
        raise ValueError(f"report exceeds retained workspace budget: required={charge} available={remaining}; Clear report cache explicitly")
