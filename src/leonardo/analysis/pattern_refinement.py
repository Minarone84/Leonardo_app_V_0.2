"""Evaluate retained definitions against the pinned root without new discovery."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import platform

import pandas as pd

from .models import AnalysisResult
from .pattern_models import PatternCatalogue, PatternRefinement, PatternStudy
from .pre_event_cohorts import build_cohorts, _gr05_family_universe
from .pattern_models import _gr05_scope_enabled, _gr05_resolve_scope
from .pre_event_patterns import Term, observe, _mask, _merge_masks, _counts_for_masks
from .refinement_models import FrozenPattern, FrozenPatternSet, PatternEvaluation, _plain
from .trend_start_patterns import (
    _axis_and_columns, _checkpoint, _continuity, _hash, _json, _progress, analysis_key, family_rows,
)


_ASSIGNMENTS = ("event_id", "anchor_ts_ms", "family", "cohort", "reason", "failed_conditions",
                "partition", "partition_reason")
_CHANGES = ("event_id", "anchor_ts_ms", "ordinary", "parent_cohort", "current_cohort",
            "parent_partition", "current_partition", "parent_reason", "current_reason",
            "parent_partition_reason", "current_partition_reason", "change")


def _fingerprint(frame):
    content = pd.util.hash_pandas_object(frame, index=True).to_numpy(dtype="uint64").tobytes()
    return _hash((list(frame.columns), [str(t) for t in frame.dtypes], sha256(content).hexdigest()))


def _events_without_refinement(events):
    return {e["event_id"]: {k: v for k, v in e.items() if k != "refinement"} for e in events}


def _pin_source_binding(parent, instance, timestamps, *, checkpoint=_checkpoint):
    """Bind discovery to complete inputs without retaining another source copy."""
    checkpoint()
    axis = tuple(timestamps)
    if len(set(axis)) != len(axis):
        raise ValueError("duplicate discovery timestamps")
    detached = deepcopy(dict(instance))
    checkpoint()
    for event in detached["events"]:
        event.pop("refinement", None)
    instance_hash = _hash(_plain(detached))
    checkpoint()
    columns, names = [], set()
    for column in parent.columns:
        checkpoint()
        name = column.request.source
        if name in names:
            raise ValueError("duplicate analyzed source columns")
        names.add(name)
        frame = column.to_frame()
        if (not frame.columns.is_unique or not frame.ts_ms.is_unique
                or tuple(frame.ts_ms.tolist()) != axis):
            raise ValueError("binning and discovery timestamp axes disagree")
        checkpoint()
        profile = column.profile
        identity = (dict(type=None, payload_hash=None) if profile is None else
                    dict(type=type(profile).__module__ + "." + type(profile).__qualname__,
                         payload_hash=_hash(_plain(profile.to_dict()))))
        checkpoint()
        columns.append(dict(source=name, request=_plain(column.request), descriptor=_plain(column.column),
                            profile=identity, frame=_fingerprint(frame)))
        checkpoint()
    payload = dict(kind="gr01-pin-source-v1", entry=_plain(parent.entry),
        reference=_plain(parent.entry.reference), binning_run=analysis_key(parent),
        snapshot_read_ms=parent.snapshot_read_ms, timestamps_hash=_hash(axis),
        instance_hash=instance_hash, columns=columns)
    checkpoint()
    result = _json(_plain(payload))
    checkpoint()
    return result


def _selection(ids):
    if isinstance(ids, (str, bytes)):
        raise ValueError("pin 1 to 500 unique nonempty pattern IDs")
    result = []
    for identity in ids:
        if not isinstance(identity, str) or not identity.strip() or identity in result or len(result) == 500:
            raise ValueError("pin 1 to 500 unique nonempty pattern IDs")
        result.append(identity)
    if not result:
        raise ValueError("pin 1 to 500 unique nonempty pattern IDs")
    return set(result)


def pin_patterns(binning_result, catalogue, discovery, pattern_ids, *, checkpoint=_checkpoint, progress=_progress):
    checkpoint()
    if (not isinstance(binning_result, AnalysisResult) or not isinstance(catalogue, PatternCatalogue)
            or not isinstance(discovery, PatternStudy)):
        raise TypeError("pin requires AnalysisResult, PatternCatalogue and PatternStudy")
    selected = _selection(pattern_ids)
    request = discovery.request
    active = discovery.granular_definition or request.refinement
    scoped = _gr05_scope_enabled(request, active)
    if request.pre_event is None or not discovery._data.get("pre_event") or (request.family is None and not scoped):
        raise ValueError("pin requires an exact-family Pre-event combinations discovery")
    key = analysis_key(binning_result)
    if (request.reference != binning_result.entry.reference or catalogue.reference != request.reference
            or catalogue.run_key != key or request.run_key != key):
        raise ValueError("pinned source/reference/run identities disagree")
    context = json.loads(discovery.context)
    instance = catalogue.instance(request.instance_id)
    if instance["status"] != "available":
        raise ValueError("selected UTC instance is unavailable")
    timestamps = tuple(discovery._data["timestamps"])
    if not timestamps or any(type(t) is not int for t in timestamps) or any(a >= b for a,b in zip(timestamps,timestamps[1:])):
        raise ValueError("ordered timestamp axis is invalid")
    binding = discovery._data.get("_pin_source_binding")
    if not isinstance(binding, str) or not binding.strip():
        raise ValueError("source_discovery_binding_missing: rerun the original discovery explicitly")
    if binding != _pin_source_binding(binning_result, instance, timestamps, checkpoint=checkpoint):
        raise ValueError("source_discovery_binding_mismatch")
    checkpoint()
    prices = None
    if "_gr04_prices" in discovery._data or "_gr04_price_binding" in discovery._data:
        _gr04_require("_gr04_prices" in discovery._data and "_gr04_price_binding" in discovery._data, "both discovery keys required")
        prices = _gr04_validate_price_snapshot(discovery._data["_gr04_prices"], discovery._data["_gr04_price_binding"],
            request.reference, _gr04_market(binning_result.entry.market_id), timestamps, checkpoint=checkpoint)
    granular = any(k.startswith("_gr03_") for k in discovery._data) or any(
        k in context for k in ("active_filter_kind", "definition_id", "population_report_id", "search_parent"))
    universe = _gr05_family_universe(instance["events"], event_kind=request.event_kind, start_ms=request.start_ms, end_ms=request.end_ms)
    scope = _gr05_resolve_scope(request, active, universe) if scoped else None
    if scope is None and request.family is None:
        raise ValueError("pin requires an analytical family selection, not separate overview")
    if not granular:
        _gr05_verify_simple(discovery, universe, checkpoint)
    granular_parts = _gr03_verify_discovery(discovery, checkpoint) if granular else None
    # All analyzed columns are captured once, including those outside this study's subset.
    names = tuple(c.request.source for c in binning_result.columns)
    if len(set(names)) != len(names):
        raise ValueError("duplicate analyzed source columns")
    columns = _axis_and_columns(binning_result, timestamps, names, checkpoint)
    if set(discovery._data["columns"]) != set(request.columns):
        raise ValueError("discovery columns disagree with its request")
    for name in request.columns:
        checkpoint()
        current, stored = columns[name], discovery._data["columns"][name]
        try:
            pd.testing.assert_frame_equal(current["frame"], stored["frame"], check_exact=True)
        except AssertionError as exc:
            raise ValueError("discovery column frame differs from supplied binning") from exc
        if any(current[k] != stored[k] for k in ("measurement", "profile_id", "tokens", "ready")):
            raise ValueError("discovery column measurement/profile metadata disagrees")
    expected_context = dict(database=binning_result.entry.name, database_id=request.reference.database_id,
        revision_id=request.reference.revision_id, values_sha256=request.reference.values_sha256,
        binning_run=key, instance_id=request.instance_id, utc_parameters=instance["parameters"],
        rule_version=instance["rule_version"], event_kind=request.event_kind, role=request.role_label,
        direction=request.trend_direction, family=request.family, origin=request.origin,
        start_ms=request.start_ms, end_ms=request.end_ms, comparison=request.comparison,
        pre_event=request.pre_event.to_dict(), mined_offsets=request.pre_event.offsets,
        after_inspection_only=request.after, refinement=request.refinement.to_dict(),
        snapshot_read_ms=binning_result.snapshot_read_ms,
        profiles=[(n,columns[n]["measurement"],columns[n]["profile_id"]) for n in sorted(request.columns)])
    if any(_json(context.get(k)) != _json(_plain(v)) for k,v in expected_context.items()):
        raise ValueError("discovery context/configuration disagrees with pinned inputs")
    original_events = _events_without_refinement(discovery._data["events"].values())
    clean_events = _events_without_refinement(instance["events"])
    if (_json(original_events) != _json(clean_events)
            or _json(discovery._data["measurement_reports"]) != _json(instance["measurement_reports"])):
        raise ValueError("discovery event/report evidence disagrees with catalogue")
    breaks, coverage = _continuity(timestamps, binning_result.entry.market_id.timeframe, instance, checkpoint)
    if (tuple(breaks) != tuple(discovery._data["breaks"]) or coverage != discovery._data["coverage"]
            or discovery._data["positions"] != {t:i for i,t in enumerate(timestamps)}):
        raise ValueError("discovery axis/coverage disagrees with catalogue")
    instance["events"] = list(clean_events.values())
    families = family_rows(instance, request.event_kind, start=request.start_ms, end=request.end_ms)
    if scope is None and request.family not in {f["family"] for f in families}:
        raise ValueError("exact family is not compatible with this pinned universe")
    axis = [t for t in timestamps if request.start_ms <= t <= request.end_ms]
    split = request.pre_event.split_ms
    if request.pre_event.chronological and split is None and len(axis) >= 2:
        split = axis[min(len(axis)-1, max(1, int(len(axis)*.7)))]
    if context.get("split_ms") != split or discovery._data["split_ms"] != split:
        raise ValueError("discovery resolved split disagrees with root axis/request")
    rows = discovery.frame("patterns")
    if rows.empty or not rows.pattern_id.is_unique or set(rows.pattern_id) != set(discovery._data["patterns"]):
        raise ValueError("discovery retained table and internal pattern map disagree")
    if not selected <= set(rows.pattern_id):
        raise ValueError("unknown pattern ID in selection")
    patterns, atom_indices = [], {}
    for order, row in enumerate(rows.to_dict("records"), 1):
        checkpoint()
        if row["pattern_id"] not in selected:
            continue
        entry = discovery._data["patterns"][row["pattern_id"]]
        terms = tuple(entry["terms"])
        if (not terms or any(not isinstance(t, Term) or t.column not in request.columns
                            or t.offset not in request.pre_event.offsets
                            or t.profile_id != columns[t.column]["profile_id"] for t in terms)
                or _json(json.loads(row["conditions"])) != _json([t.to_dict() for t in terms])
                or row["pattern_id"] != _hash(tuple((t.column,t.offset,t.profile_id,t.allowed) for t in terms))):
            raise ValueError("frozen terms/conditions/pattern identity disagree")
        if (len(entry["indices"]) != len(terms) or any(type(i) is not int or i < 0
                or i >= len(discovery._data["atoms"]) for i in entry["indices"])
                or tuple(discovery._data["atoms"][i] for i in entry["indices"]) != terms):
            raise ValueError("discovery atom references disagree with frozen terms")
        for term, index in zip(terms, entry["indices"], strict=True):
            if term in atom_indices and atom_indices[term] != index:
                raise ValueError("discovery has inconsistent atom identities")
            atom_indices[term] = index
        patterns.append(FrozenPattern(row["pattern_id"], terms, order, _json(_plain(row))))
        progress("Pinning retained combinations", len(patterns), len(selected))
    checkpoint()
    profiles = [(c.request.source, c.profile.to_dict() if c.profile is not None else None) for c in binning_result.columns]
    source = dict(request=_plain(request), context=context, row_ids=rows.pattern_id.tolist(),
        instance_hash=_hash(instance), profiles=[(n,_hash(p)) for n,p in profiles],
        columns=[(n,_fingerprint(columns[n]["frame"])) for n in names])
    if granular_parts is not None:
        definition, report = granular_parts
        source.update(granular_definition=definition.to_dict(),
            granular_population_digest=_hash({k:v for k,v in report.items() if k!="accounting"}),
            granular_discovery_binding=discovery._data["_gr03_discovery_binding"], search_parent=context["search_parent"])
    discovery_id = _hash(("gr01-discovery-v1", source))
    root_id = _hash(("gr01-root-v1", discovery_id))
    set_id = _hash(("gr01-set-v1", root_id, [p.pattern_id for p in patterns]))
    metadata = dict(root_id=root_id, source_discovery_id=discovery_id, set_id=set_id,
        source=source, source_runtime={"python":platform.python_version(), "pandas":pd.__version__},
        fingerprint_portability="internal runtime-version-bound", profiles=profiles,
        compatible_families=families, resolved_split=split,
        automatic_split=request.pre_event.chronological and request.pre_event.split_ms is None,
        original_search=context["search"], selected_rules=len(patterns))
    root = dict(timestamps=timestamps, columns=columns, timeframe=binning_result.entry.market_id.timeframe,
        instance=_json(instance), assignments=deepcopy(discovery.frame("cohort_assignments").to_dict("records")),
        samples=deepcopy(discovery._data["samples"]), atom_indices=atom_indices)
    root["_gr03_source_binding"] = binding
    root["_gr03_filter_context"] = _gr03_filter_context(binning_result, request, (e["family"] for e in instance["events"]))
    if prices is not None:
        root["_gr04_prices"] = discovery._data["_gr04_prices"]
        root["_gr04_price_binding"] = discovery._data["_gr04_price_binding"]
        root["_gr03_filter_context"]["horizon_source"] = _gr04_capability(prices, root["_gr04_prices"],
            root["_gr04_price_binding"], request.trend_direction)
    if granular_parts is not None:
        root["_gr03_definition"], root["_gr03_population"] = granular_parts
    checkpoint()
    return FrozenPatternSet(root_id, discovery_id, set_id, request, split, _json(families),
                            tuple(patterns), _json(metadata), root)


def _statuses(assignments, samples, timestamps, *, population=None):
    rows = {r["event_id"]: dict(anchor_ts_ms=r["anchor_ts_ms"], ordinary=False, cohort=r["cohort"],
             partition=r["partition"], reason=r["reason"], partition_reason=r["partition_reason"]) for r in assignments}
    for sample in samples:
        row = rows.setdefault(sample["event_id"], dict(reason="ordinary_timestamp"))
        row.update(anchor_ts_ms=timestamps[sample["anchor"]], ordinary=sample["ordinary"],
                   cohort=sample["cohort"], partition=sample["partition"], partition_reason=sample["partition_reason"])
    if population is not None:
        for record in population["records"]:
            if record["row_id"] in rows:
                rows[record["row_id"]]["ordinary"] = record["ordinary"]
    return rows


def _changes(before, after):
    rows = []
    empty = dict(cohort="absent", partition="excluded", reason="absent", partition_reason="not_in_cohort")
    for identity in before.keys() | after.keys():
        old, new = before.get(identity, empty), after.get(identity, empty)
        old_in, new_in = old["cohort"] in ("target","comparison"), new["cohort"] in ("target","comparison")
        change = ("included" if new_in and not old_in else "excluded" if old_in and not new_in else
                  "reassigned" if old_in and new_in and old["cohort"] != new["cohort"] else
                  "unchanged" if old == new else "status_changed")
        source = after.get(identity, before.get(identity))
        rows.append(dict(event_id=identity, anchor_ts_ms=source["anchor_ts_ms"], ordinary=source["ordinary"], change=change,
            **{prefix+key: value[key] for prefix,value in (("parent_",old),("current_",new))
               for key in ("cohort","partition","reason","partition_reason")}))
    return sorted(rows, key=lambda r:(r["anchor_ts_ms"],r["event_id"]))


def evaluate_patterns(frozen, refinement, *, parent=None, checkpoint=_checkpoint, progress=_progress,
                      memory_limit_bytes=128 * 1024 * 1024):
    checkpoint()
    if not isinstance(frozen, FrozenPatternSet) or not isinstance(refinement, PatternRefinement):
        raise TypeError("evaluation requires FrozenPatternSet and PatternRefinement")
    if (parent is not None and (not isinstance(parent, PatternEvaluation)
            or parent.root_id != frozen.root_id or parent.set_id != frozen.set_id)):
        raise ValueError("parent must belong to the same frozen set and root")
    if type(memory_limit_bytes) is not int or not 1 <= memory_limit_bytes <= 128*1024*1024:
        raise ValueError("memory limit must be an integer from 1 through 128 MiB")
    request = replace(frozen.original_request, refinement=refinement)
    if request.pre_event.chronological and frozen.resolved_split is not None:
        request = replace(request, pre_event=replace(request.pre_event, split_ms=frozen.resolved_split))
    root = frozen._root
    checkpoint()
    instance = json.loads(root["instance"])
    timestamps = root["timestamps"]
    # The private, validated source columns are shared read-only; only per-call cohort state is mutable.
    columns = {n:root["columns"][n] for n in request.columns}
    for _ in columns:
        checkpoint()
    breaks, coverage = _continuity(timestamps, root["timeframe"], instance, checkpoint)
    data = dict(pre_event=True, timestamps=timestamps, positions={t:i for i,t in enumerate(timestamps)},
        columns=columns, breaks=breaks, coverage=coverage, events={e["event_id"]:e for e in instance["events"]},
        measurement_reports=instance["measurement_reports"], patterns={})
    checkpoint()
    scope = _gr05_bound_scope(frozen, refinement) if _gr05_scope_enabled(frozen.original_request, refinement) else None
    working = _gr05_search_request(frozen, refinement) if scope is not None else request
    _, assignments, funnel, excluded_starts = build_cohorts(data, instance, working, checkpoint)
    samples = data["samples"]
    rows, estimated = _gr03_match(frozen, data, request, checkpoint, progress, memory_limit_bytes)
    populations = data["populations"]
    metadata = frozen.metadata()
    parent_id = frozen.source_discovery_id if parent is None else parent.evaluation_id
    identity = _hash(("gr01-evaluation-v1", frozen.set_id, parent_id, refinement.to_dict()))
    before = (_statuses(root["assignments"],root["samples"],timestamps,population=root.get("_gr03_population")) if parent is None else
              _statuses(parent.frame("cohort_assignments").to_dict("records"),parent._data["samples"],timestamps,population=parent._data.get("_gr03_population")))
    changes = _changes(before,_statuses(assignments,samples,timestamps))
    context = dict(mode="frozen_evaluation", root_id=frozen.root_id,set_id=frozen.set_id,
        source_discovery_id=frozen.source_discovery_id, parent_id=parent_id,evaluation_id=identity,
        reference=_plain(request.reference),effective_request=_plain(request), refinement=refinement.to_dict(),
        frozen_split=frozen.resolved_split, automatic_split=metadata["automatic_split"],
        source_discovery_search=metadata["original_search"],source_runtime=metadata["source_runtime"],
        selected_rules_evaluated=len(rows),support_eligible_rules=sum(r["support_eligible"] for r in rows),
        population_counts={k:v.bit_count() for k,v in populations.items()},
        chronology_excluded=sum(s["partition"]=="excluded" for s in samples),
        excluded_events=sum(a["cohort"]=="excluded" for a in assignments),excluded_background_starts=excluded_starts,
        estimated_retained_match_state_bytes=estimated,memory_limit_bytes=memory_limit_bytes,
        memory_scope="Conservative retained atom/rule masks only; excludes frozen source, process RSS and lazy occurrence frames",
        funnel_semantics="existing build_cohorts cohort/partition summary",
        interpretation="retrospective_full_history; no forecasting probability or significance")
    tables = (("patterns",pd.DataFrame(rows,dtype=object)),
        ("cohort_assignments",pd.DataFrame(assignments,columns=_ASSIGNMENTS,dtype=object)),
        ("refinement_funnel",pd.DataFrame(funnel,dtype=object)),
        ("population_changes",pd.DataFrame(changes,columns=_CHANGES,dtype=object)),
        ("diagnostics",pd.DataFrame([(k,_json(_plain(v)) if isinstance(v,(dict,list,tuple)) else v)
                                    for k,v in context.items()],columns=("field","value"),dtype=object)))
    if scope is not None:
        summary = _gr05_family_population(assignments, samples, data["events"], timestamps, scope, checkpoint=checkpoint)
        data["_gr05_family_population"] = summary
        context.update(family_scope=scope, family_population=summary)
        tables += (("family_population", pd.DataFrame(summary, dtype=object)),)
    checkpoint()
    return PatternEvaluation(frozen.root_id,frozen.set_id,identity,parent_id,request,_json(context),tables,data)


# Task 1078: granular predicate foundation.
from collections.abc import Mapping as _granular_Mapping
from decimal import Decimal as _granular_Decimal
from .refinement_models import (
    GranularRefinement as _granular_Refinement,
    ResolvedFilterValue as _granular_ResolvedValue,
    _granular_decimal_string, _granular_token, _granular_family, _granular_sequence,
)
from .pattern_models import PrecedingContextFilter as _granular_PrecedingContextFilter


def validate_granular_context(spec, *, column_profiles, offsets):
    """Check supplied column/profile/offset metadata, not source or time evidence."""
    if type(spec) is not _granular_Refinement or not isinstance(column_profiles, _granular_Mapping):
        raise TypeError("granular context requires a validated definition and column mapping")
    for column, profile in column_profiles.items():
        _granular_token(column, "column")
        if profile is not None:
            _granular_token(profile, "profile ID")
    offsets = _granular_sequence(offsets, "offsets")
    if (not offsets or any(type(v) is not int or not -199 <= v <= -1 for v in offsets)
            or any(a >= b for a, b in zip(offsets, offsets[1:]))):
        raise ValueError("offsets require unique increasing negative integers within -199 through -1")
    for group in spec.common + spec.outcome:
        for predicate in group.conditions:
            if group.enabled and predicate.active and predicate.domain == "column":
                if (predicate.column not in column_profiles or column_profiles[predicate.column] != predicate.profile_id
                        or predicate.offset not in offsets):
                    raise ValueError("active column predicate does not match supplied column/profile/offset context")


def _granular_fact(predicate, resolved):
    if type(resolved) is not _granular_ResolvedValue:
        raise TypeError("requested measurements require ResolvedFilterValue")
    if not resolved.known:
        return None, resolved.unavailable_reason
    value = resolved.value
    if predicate.unit == "boolean":
        if type(value) is not bool:
            raise TypeError("context membership requires an actual bool fact")
    elif predicate.unit in ("category", "label"):
        _granular_token(value, "categorical fact")
        if predicate.field == "previous_direction":
            _granular_PrecedingContextFilter(previous_direction=value)
        elif predicate.field == "previous_family":
            _granular_family(value)
    else:
        if type(value) is not _granular_Decimal:
            raise TypeError("numeric predicates require numeric facts, not bool or strings")
        duration = predicate.domain == "duration" or (predicate.domain == "pullbacks" and predicate.field == "recovered_duration")
        count = predicate.domain == "pullbacks" and predicate.field == "count"
        if duration or count:
            if value < 0 or ((count or predicate.statistic != "mean") and value != value.to_integral_value()):
                raise ValueError("count and duration facts require nonnegative values; individual facts must be integral")
    return value, ""


def _granular_status(statuses, operator="ALL"):
    active = [s for s in statuses if s != "inactive"]
    if not active:
        return "inactive"
    if "unavailable" in active:
        return "unavailable"
    passed = all(s == "pass" for s in active) if operator == "ALL" else any(s == "pass" for s in active)
    return "pass" if passed else "mismatch"


def evaluate_granular_predicates(spec, values, *, checkpoint=_checkpoint):
    """Evaluate supplied scalar facts; never resolve sources or form populations."""
    checkpoint()
    if type(spec) is not _granular_Refinement or not isinstance(values, _granular_Mapping):
        raise TypeError("predicate evaluation requires GranularRefinement and a value mapping")
    cache, groups, predicates, purposes = {}, [], [], {}
    purpose_keys = {"common": set(), "outcome": set()}
    for purpose in ("common", "outcome"):
        group_statuses = []
        for group_index, group in enumerate(getattr(spec, purpose)):
            checkpoint()
            leaf_statuses = []
            active_count = 0
            for predicate_index, predicate in enumerate(group.conditions):
                checkpoint()
                measurement_key, predicate_key = predicate.measurement_key, predicate.predicate_key
                value = None
                if not group.enabled:
                    status, reason = "inactive", "group_disabled"
                elif not predicate.enabled:
                    status, reason = "inactive", "predicate_disabled"
                elif not predicate.active:
                    status, reason = "inactive", "empty_condition"
                else:
                    active_count += 1
                    purpose_keys[purpose].add(predicate_key)
                    if measurement_key not in cache:
                        checkpoint()
                        try:
                            supplied = values[measurement_key]
                        except KeyError:
                            cache[measurement_key] = (None, "required_value_missing")
                        else:
                            cache[measurement_key] = _granular_fact(predicate, supplied)
                    actual, reason = cache[measurement_key]
                    if actual is None:
                        status = "unavailable"
                    elif predicate.unit in ("category", "label", "boolean"):
                        value = actual
                        status = "pass" if actual in predicate.allowed else "mismatch"
                        reason = "" if status == "pass" else "not_allowed"
                    else:
                        value = _granular_decimal_string(actual)
                        below = predicate.minimum is not None and (actual < predicate.minimum or
                            (actual == predicate.minimum and not predicate.lower_inclusive))
                        above = predicate.maximum is not None and (actual > predicate.maximum or
                            (actual == predicate.maximum and not predicate.upper_inclusive))
                        status = "mismatch" if below or above else "pass"
                        reason = "outside_bounds" if status == "mismatch" else ""
                leaf_statuses.append(status)
                predicates.append(dict(path=f"{purpose}[{group_index}].conditions[{predicate_index}]",
                    purpose=purpose, group_index=group_index, predicate_index=predicate_index,
                    measurement_key=measurement_key, predicate_key=predicate_key, status=status, value=value, reason=reason))
            status = _granular_status(leaf_statuses, group.operator)
            groups.append(dict(purpose=purpose, group_index=group_index, operator=group.operator,
                               status=status, active_count=active_count))
            group_statuses.append(status)
        purposes[purpose] = _granular_status(group_statuses)
    overall = _granular_status(purposes.values())
    report = dict(kind="gr03-predicate-report-v1", definition_id=spec.identity,
        status="pass" if overall == "inactive" else overall, active_count=spec.active_count,
        required_measurements=sorted(cache), all_required_known=all(value is not None for value, _ in cache.values()),
        purposes=purposes, groups=groups, predicates=predicates,
        cross_purpose_predicates=sorted(purpose_keys["common"] & purpose_keys["outcome"]),
        scope="supplied_scalars_only_not_cohort_or_evidence_validation")
    checkpoint()
    return report


# Task 1079: coherent frozen-source and population resolution.
import numpy as _granular_np
from .refinement_models import GranularRefinement as _granular_Definition
from .pattern_models import MEASUREMENT_BASES as _granular_Bases


def _granular_active(definition):
    return {p.measurement_key: p for group in definition.common + definition.outcome if group.enabled
            for p in group.conditions if p.active}


def _granular_scalar(value):
    return value.item() if isinstance(value, _granular_np.generic) else value


def _granular_clock(value):
    value = _granular_scalar(value)
    if type(value) not in (int, float, _granular_Decimal):
        return None
    number = _granular_Decimal(str(value))
    return int(number) if number.is_finite() and 0 <= number < 2**63 and number == number.to_integral_value() else None


def _granular_empty_resolution(status):
    return dict(status=status, compatible_providers=[], chosen_provider=None, rejected_witnesses=[],
                formation_bridge=dict(used=False, carrier=None, formation_witnesses=[]), temporal_rejections=[])


def _granular_provider_order(provider):
    return provider["artifact_id"], provider["report_sha256"], provider["episode_id"]


def _granular_column_fact(predicate, anchor, data, ordinary, snapshot):
    from .trend_start_patterns import _path_valid
    column = data["columns"][predicate.column]
    position = anchor + predicate.offset
    inside = 0 <= position < len(data["timestamps"])
    valid = inside and _path_valid(data, position, anchor)
    reason = "" if valid else "column_path_unavailable"
    if valid and ordinary and data["control_uncovered"][anchor+1] != data["control_uncovered"][position]:
        valid, reason = False, "ordinary_control_path_unavailable"
    row = column["frame"].iloc[position] if inside else None
    clock = _granular_clock(row.get("available_at_ms")) if row is not None else None
    clock_basis = "stored_observation" if clock is not None else "unknown"
    if clock is None and inside:
        clock = _granular_clock(snapshot)
        if clock is not None:
            clock_basis = "snapshot_read_only"
    value = None
    if valid:
        if predicate.field == "label":
            value = column["tokens"][position]
            if value is None:
                reason = "label_unavailable"
        else:
            value = _granular_scalar(row.get("raw_value"))
            if (type(value) not in (int, float, _granular_Decimal)
                    or not _granular_Decimal(str(value)).is_finite()):
                value, reason = None, "raw_value_unavailable"
    source = dict(kind="column_observation", column=predicate.column, profile_id=predicate.profile_id,
        offset=predicate.offset, row=position if inside else None, ts_ms=data["timestamps"][position] if inside else None,
        measurement=column["measurement"], ready_reference=bool(column["ready"][position]) if inside else None,
        available_at_ms=clock, clock_basis=clock_basis, path_valid=bool(valid), support_reason=reason)
    return value, reason, source


def _granular_event_source(event, instance, data, active, checkpoint):
    from .trend_start_patterns import _refinement_resolve_saved, _refinement_provider, _refinement_formation_bridge
    from .pre_event_cohorts import _refinement_evidence_intervals
    bases = tuple(b for b in _granular_Bases if any(p.basis == b for p in active.values()))
    membership = any(p.domain == "context" and p.field in ("up", "down", "range") for p in active.values())
    lineage = any(p.domain == "context" and p.field in ("previous_direction", "previous_family") for p in active.values())
    requested = bool(bases or membership or lineage)
    source = _granular_empty_resolution("not_requested")
    resolved = None
    if requested:
        resolved = _refinement_resolve_saved(event, bases=bases, membership=membership, lineage=lineage,
                                            positions=data["positions"], checkpoint=checkpoint)
        source.update(status=resolved["resolution"],
            compatible_providers=sorted(deepcopy(resolved["providers"]), key=_granular_provider_order),
            rejected_witnesses=deepcopy(resolved["rejected_witnesses"]))
        if resolved["resolution"] != "resolved":
            return source, None, None, "; ".join(resolved["reasons"]) or resolved["resolution"], (None, None)
    intervals = _refinement_evidence_intervals(event, instance, data["positions"], bases=bases,
        context_active=membership or lineage, providers=resolved["providers"] if resolved else [],
        restrict_providers=requested, resolution=resolved["resolution"] if resolved else "disabled", checkpoint=checkpoint)
    source["temporal_rejections"] = intervals["rejected"]
    chosen = min(intervals["intervals"], key=lambda r:(r["end_ms"],r["start_ms"],r["artifact_id"],r["report_sha256"]), default=None)
    if chosen is not None:
        witness = next(w for w in event["witnesses"] if (w["artifact_id"],w["report_sha256"]) == (chosen["artifact_id"],chosen["report_sha256"]))
    elif resolved:
        witness = min(resolved["candidates"], key=lambda c:_granular_provider_order(c[1]))[2]
    else:
        witness = None
    selected = None
    if witness is not None:
        source["chosen_provider"] = _refinement_provider(witness)
        if resolved:
            selected = next(c[0] for c in resolved["candidates"] if c[2] is witness)
        bridge = _refinement_formation_bridge(event, witness, bases, data["positions"], checkpoint)
        if bridge:
            source["formation_bridge"] = dict(used=True, carrier=_refinement_provider(witness),
                formation_witnesses=sorted(bridge,key=_granular_provider_order))
    return source, selected, witness, "", (chosen["start_ms"],chosen["end_ms"]) if chosen else (None,None)


def _granular_utc_fact(predicate, selected, witness, unresolved, resolution, instance):
    from .trend_start_patterns import _refinement_scalar, _refinement_provider
    source = dict(kind="utc_projection", artifact_id=None, report_sha256=None, episode_id=None,
        basis=predicate.basis, cohort=predicate.cohort, projection_reason=unresolved, support_reason=unresolved,
        required_start_ms=None, required_end_ms=None, recognition_ms=None, available_at_ms=None,
        clock_basis="unknown", formation_bridge=False)
    if witness is None or selected is None:
        return None, unresolved, source
    source.update(_refinement_provider(witness))
    value, reason = _refinement_scalar(selected, witness, domain=predicate.domain, field=predicate.field,
        unit=predicate.unit, basis=predicate.basis, cohort=predicate.cohort, statistic=predicate.statistic)
    source["support_reason"] = reason
    if predicate.domain == "context":
        part = "membership" if predicate.field in ("up","down","range") else "lineage"
        source["projection_reason"] = witness["context_projections"][part]["reason"]
        evidence = next((e for e in instance["observation_evidence"] if
            (e["artifact_id"],e["report_sha256"]) == (witness["artifact_id"],witness["report_sha256"])),None)
        if evidence:
            source.update(required_start_ms=evidence["source_start_ms"],
                required_end_ms=max((b for _,b in evidence["intervals"]),default=None),
                available_at_ms=evidence["observed_at_ms"],clock_basis="saved_observation_retrospective")
    else:
        projection=witness["measurement_projections"][predicate.basis]
        coverage=projection.get("coverage",{})
        bridge=predicate.basis=="formation" and resolution["formation_bridge"]["used"]
        source.update(projection_reason=projection["reason"],required_start_ms=projection.get("required_start_ms"),
            required_end_ms=projection.get("required_end_ms"),recognition_ms=coverage.get("recognition_ms"),
            available_at_ms=witness["episode"]["confirmed_at_ms"] if predicate.basis=="formation" else projection["projection"].get("available_at_ms"),
            clock_basis="formation_via_verified_completed_prefix" if bridge else coverage.get("timing","unknown"),formation_bridge=bridge)
    return _granular_scalar(value), reason, source


def _granular_assign(comparison, ordinary, same, report):
    if report["status"] == "unavailable":
        return "excluded", "unavailable_requested_evidence"
    if report["purposes"]["common"] == "mismatch":
        return "excluded", "common_condition_mismatch"
    if ordinary:
        return "comparison", "ordinary_common_pass"
    if comparison == "other_outcomes":
        return ("target","passes_outcome_definition") if report["purposes"]["outcome"] == "pass" else ("comparison","fails_outcome_definition")
    if report["purposes"]["outcome"] == "mismatch":
        return "excluded", "outcome_condition_mismatch"
    return ("target" if same else "comparison"), "passes_filters"


def resolve_granular_population(frozen, definition, *, checkpoint=_checkpoint, progress=_progress,
                               memory_limit_bytes=128 * 1024 * 1024):
    from .trend_start_patterns import _selected
    from .pre_event_cohorts import partition_sample
    checkpoint()
    if type(frozen) is not FrozenPatternSet or type(definition) is not _granular_Definition:
        raise TypeError("population resolution requires FrozenPatternSet and GranularRefinement")
    if type(memory_limit_bytes) is not int or not 1 <= memory_limit_bytes <= 128*1024*1024:
        raise ValueError("memory limit must be an integer from 1 through 128 MiB")
    request = frozen.original_request
    root = frozen._root
    family_scope = _gr05_bound_scope(frozen, definition) if _gr05_scope_enabled(request, definition) else None
    horizon_model = _gr04_source(frozen, checkpoint) if _gr04_active_horizons(definition) else None
    horizon_header = _gr04_header(frozen, definition, horizon_model, checkpoint=checkpoint)
    validate_granular_definition(definition, source_request=request,
        column_profiles={n:c["profile_id"] for n,c in root["columns"].items()}, horizon_source=horizon_header,
        family_universe=None if family_scope is None else family_scope["compatible_families"])
    horizon_spacing = _gr04_spacing(root["timestamps"], root["timeframe"], checkpoint) if horizon_model is not None else None
    checkpoint()
    metadata=frozen.metadata();instance=json.loads(root["instance"])
    checkpoint()
    timestamps=root["timestamps"];positions={}
    for index,timestamp in enumerate(timestamps):
        if index%128==0:checkpoint()
        positions[timestamp]=index
    if family_scope is not None:
        from .pattern_models import FamilyScope
        effective = FamilyScope(family_scope["mode"], () if family_scope["mode"] == "all" else family_scope["selected_families"])
        neutral = replace(request, refinement=PatternRefinement(family_scope=effective),
            comparison="recurrence" if request.comparison == "other_outcomes" else request.comparison)
    else:
        neutral=replace(request,refinement=PatternRefinement(),comparison="other_families" if request.comparison=="other_outcomes" else request.comparison)
    if neutral.pre_event.chronological and frozen.resolved_split is not None:
        neutral=replace(neutral,pre_event=replace(neutral.pre_event,split_ms=frozen.resolved_split))
    breaks,coverage=_continuity(timestamps,root["timeframe"],instance,checkpoint)
    data=dict(timestamps=timestamps,positions=positions,columns=root["columns"],breaks=breaks,coverage=coverage,
              events={e["event_id"]:e for e in instance["events"]})
    build_cohorts(data,instance,neutral,checkpoint)
    ordinary_samples=[s for s in data["samples"] if s["ordinary"]]
    events=[e for e in instance["events"] if _selected(e,request.event_kind,request.origin,request.start_ms,request.end_ms)]
    candidates=[(e,None) for e in events]+[(None,s) for s in ordinary_samples]
    records=[];samples=[];retained=0;seen=set()
    snapshot=metadata["source"]["context"].get("snapshot_read_ms")
    for processed,(event,control) in enumerate(candidates,1):
        checkpoint()
        ordinary=control is not None
        row_id=control["event_id"] if ordinary else event["event_id"]
        if row_id in seen:continue
        seen.add(row_id)
        anchor=control["anchor"] if ordinary else positions.get(event["anchor_ts_ms"])
        timestamp=timestamps[anchor] if ordinary else event["anchor_ts_ms"]
        same=ordinary or (event["family"] in family_scope["selected_families"] if family_scope is not None else event["family"]==request.family)
        scope=same or request.comparison=="other_families"
        mandatory=ordinary or event["eligible"]
        record=dict(row_id=row_id,ordinary=ordinary,anchor=anchor,anchor_ts_ms=timestamp,family=None if ordinary else event["family"],
            scope_selected=scope,mandatory_eligible=mandatory,evaluation_scope="not_evaluated_scope" if not scope else "not_evaluated_mandatory",
            predicate_report=None,scalar_ledger=[],source_resolution=_granular_empty_resolution("not_applicable" if ordinary else "not_requested"),
            cohort="excluded",reason="outside_family_scope" if not scope else "mandatory_event_ineligible",
            partition="excluded",partition_reason="not_in_cohort",feature_start_ms=None,cutoff_ms=None,evidence_start_ms=None,evidence_end_ms=None)
        if scope and mandatory:
            evaluated=_granular_Definition(common=definition.common) if ordinary else definition
            required=_granular_active(evaluated)
            record["evaluation_scope"]="common_only_for_ordinary_control" if ordinary else "full_definition"
            if ordinary:
                selected=witness=None;unresolved=""
                interval=(control["evidence_start_ms"],control["evidence_end_ms"])
            else:
                resolution,selected,witness,unresolved,interval=_granular_event_source(event,instance,data,required,checkpoint)
                record["source_resolution"]=resolution
            values={};column_intervals=[]
            horizon_cache = {}
            horizon_predicates = [p for p in required.values() if p.domain == "horizon"]
            if horizon_predicates:
                record["horizon_windows"] = []
                for n in sorted({p.horizon_bars for p in horizon_predicates}):
                    roles = {r for p in horizon_predicates if p.horizon_bars == n
                             for r in _gr04_required_roles(p.field, request.trend_direction)}
                    cache_key = (horizon_header["price_snapshot_id"], anchor, request.trend_direction, n)
                    window, measured = _gr04_window(horizon_model, cache_key[0], row_id, anchor,
                        request.trend_direction, n, [r for r in ("close", "high", "low") if r in roles], horizon_spacing, checkpoint)
                    horizon_cache[cache_key] = (window, measured)
                    record["horizon_windows"].append(window)
            for key,predicate in sorted(required.items()):
                checkpoint()
                if predicate.domain=="column":
                    value,reason,source=_granular_column_fact(predicate,anchor,data,ordinary,snapshot)
                    column_intervals.append((source["ts_ms"],source["available_at_ms"]))
                elif predicate.domain == "horizon":
                    window, measured = horizon_cache[(horizon_header["price_snapshot_id"], anchor,
                                                     request.trend_direction, predicate.horizon_bars)]
                    value,reason,source = _gr04_fact(predicate, window, measured, request.trend_direction)
                    column_intervals.append((source["required_start_ms"], source["required_end_ms"]))
                else:
                    value,reason,source=_granular_utc_fact(predicate,selected,witness,unresolved,record["source_resolution"],instance)
                resolved=_granular_ResolvedValue(value) if value is not None else _granular_ResolvedValue(unavailable_reason=reason)
                values[key]=resolved
                selectors={name:getattr(predicate,name) for name in ("domain","field","unit","basis","cohort","statistic","column","profile_id","offset")}
                if predicate.domain == "horizon": selectors["horizon_bars"] = predicate.horizon_bars
                record["scalar_ledger"].append(dict(measurement_key=key,selectors=selectors,known=resolved.known,
                    value=_granular_decimal_string(resolved.value) if type(resolved.value) is _granular_Decimal else resolved.value,
                    unavailable_reason=resolved.unavailable_reason,source=source))
            horizon_cache.clear()
            if horizon_predicates:
                del window, measured
            report=evaluate_granular_predicates(evaluated,values,checkpoint=checkpoint)
            record["predicate_report"]=report
            record["cohort"],record["reason"]=_granular_assign(request.comparison,ordinary,same,report)
            all_intervals=[interval]+column_intervals
            if all(a is not None and b is not None for a,b in all_intervals):
                record["evidence_start_ms"]=min(min(a,b) for a,b in all_intervals)
                record["evidence_end_ms"]=max(max(a,b) for a,b in all_intervals)
            if record["cohort"]!="excluded":
                sample=dict(event_id=row_id,anchor=anchor,cohort=record["cohort"],ordinary=ordinary,
                    timing=control["timing"] if ordinary else event["coverage_basis"]=="verified_confirmation",
                    evidence_start_ms=record["evidence_start_ms"],evidence_end_ms=record["evidence_end_ms"])
                partition_sample(sample,data,request,frozen.resolved_split)
                for field in ("partition","partition_reason","feature_start_ms","cutoff_ms"):record[field]=sample[field]
                samples.append(sample)
        records.append(record)
        retained+=len(_json(record).encode("utf-8"))
        if retained>memory_limit_bytes:
            raise ValueError(f"granular_payload_limit: required_at_least={retained} allowed={memory_limit_bytes}")
        progress("Resolving granular population",processed,len(candidates))
    records.sort(key=lambda r:(r["anchor_ts_ms"],r["row_id"]))
    samples.sort(key=lambda s:(s["cohort"]!="target",s["anchor"],s["event_id"]))
    samples, anchor_range, anchor_summary = _grdate_apply(records, samples, definition, request, checkpoint)
    summary=dict(records_total=len(records),event_records=sum(not r["ordinary"] for r in records),control_records=sum(r["ordinary"] for r in records),
        scope_excluded=sum(r["reason"]=="outside_family_scope" for r in records),
        mandatory_excluded=sum(r["reason"]=="mandatory_event_ineligible" for r in records),
        unavailable_requested=sum(r["reason"]=="unavailable_requested_evidence" for r in records),
        known_filter_mismatch=sum(r["reason"] in ("common_condition_mismatch","outcome_condition_mismatch") for r in records),
        target_total=sum(r["cohort"]=="target" for r in records),comparison_total=sum(r["cohort"]=="comparison" for r in records),
        cohort_excluded=sum(r["cohort"]=="excluded" for r in records),
        by_cohort_partition=[dict(cohort=c,partition=p,count=sum(r["cohort"]==c and r["partition"]==p for r in records))
                            for c in ("target","comparison") for p in ("discovery","later","excluded")])
    report=dict(kind="gr03-population-report-v1",report_id=_gr04_result_identity("population", frozen, definition),
        root_id=frozen.root_id,set_id=frozen.set_id,source_discovery_id=frozen.source_discovery_id,source_request=_plain(request),
        legacy_filters_applied=False,definition_id=definition.identity,definition=definition.to_dict(),comparison=request.comparison,
        resolved_split_ms=frozen.resolved_split,records=records,samples=samples,summary=summary,
        scope="frozen_sources_and_population_only_not_rule_matching")
    checkpoint()
    if family_scope is not None:
        assignments = [dict(event_id=r["row_id"], anchor_ts_ms=r["anchor_ts_ms"], cohort=r["cohort"],
            partition=r["partition"], reason=r["reason"], partition_reason=r["partition_reason"]) for r in records]
        report.update(family_scope=family_scope, family_population=_gr05_family_population(
            assignments, samples, data["events"], timestamps, family_scope, population=report, checkpoint=checkpoint))
    if horizon_header is not None: report["horizon_source"] = horizon_header
    if anchor_range is not None:
        report.update(anchor_range=anchor_range, anchor_range_summary=anchor_summary)
        summary["anchor_range_excluded"] = anchor_summary["outside_candidates"]
    encoded=_json(report).encode("utf-8")
    if len(encoded)>memory_limit_bytes:
        raise ValueError(f"granular_payload_limit: required={len(encoded)} allowed={memory_limit_bytes}")
    report=json.loads(encoded)
    checkpoint()
    report["accounting"]=dict(retained_payload_bytes=len(encoded),limit_bytes=memory_limit_bytes,
        scope="canonical_UTF8_payload_bytes_not_process_RSS_or_frozen_source")
    checkpoint()
    return report


def _gr03_match(frozen, data, request, checkpoint, progress, memory_limit_bytes):
    samples = data["samples"]
    root = frozen._root
    populations = {prefix:_mask(samples,cohort,partition) for prefix,cohort,partition in
        (("","target","discovery"),("comparison_","comparison","discovery"),
         ("later_","target","later"),("later_comparison_","comparison","later"))}
    timing = sum(1 << i for i,s in enumerate(samples) if s["timing"])
    atoms = tuple(dict.fromkeys(t for p in frozen.patterns for t in p.terms))
    bit_cost = 4*(32+(len(samples)+7)//8)
    estimated = sum(1024+len(t.metadata.encode("utf-8"))+bit_cost for t in atoms)
    estimated += sum(2048+len(json.loads(p.original_row)["conditions"].encode("utf-8"))+bit_cost for p in frozen.patterns)
    if estimated > memory_limit_bytes:
        raise ValueError(f"evaluation_match_state_limit: required={estimated} allowed={memory_limit_bytes}")
    # Retain the source atom IDs so the existing detail helper also preserves
    # its subset ordering. Dict insertion order is frozen-rule first occurrence;
    # no unused source atom or mask is retained or regenerated.
    indices = {t:root["atom_indices"][t] for t in atoms}
    masks = {}
    for term in atoms:
        checkpoint()
        valid = ready = matched = exact = 0
        for i,sample in enumerate(samples):
            if i % 128 == 0:
                checkpoint()
            actual, supported, hit, center = observe(data,sample,(term,))
            bit = 1 << i
            if actual is not None: valid |= bit
            if supported: ready |= bit
            if hit: matched |= bit
            if center: exact |= bit
        masks[indices[term]] = (valid,ready,matched,exact)
    data.update(atoms={indices[t]:t for t in atoms}, atom_masks=masks, populations=populations, timing_mask=timing,
                control_ids=frozenset(s["event_id"] for s in samples if s["ordinary"]))
    metadata = frozen.metadata()
    rows = []
    for pattern in frozen.patterns:
        checkpoint()
        positions = tuple(indices[t] for t in pattern.terms)
        combined = _merge_masks([masks[i] for i in positions])
        data["patterns"][pattern.pattern_id] = dict(terms=pattern.terms, masks=combined, indices=positions)
        counts = _counts_for_masks(combined, populations, timing)
        original = json.loads(pattern.original_row)
        primary = len({t.column for t in pattern.terms}) >= 2 and len({t.offset for t in pattern.terms}) >= 2
        supported = (primary and counts["ready_assessable"] >= request.min_target
            and counts["comparison_ready_assessable"] >= request.min_comparison
            and counts["ready_matched"] >= request.min_matches and counts["difference_pp"] is not None)
        complete = metadata["original_search"]["complete"]
        reason = ("source_discovery_incomplete" if not complete else "single_baseline" if not primary else
                  "supported_historical_contrast" if supported else "below_support_or_unavailable_comparison")
        rows.append({**{k:original[k] for k in ("pattern_id","kind","condition","conditions","term_count",
            "additional_allowed_bins","interpretation")}, **counts, "original_order":pattern.original_order,
            **{"original_"+k:original[k] for k in ("rank_eligible","rank_reason","difference_pp",
                "frequency_ratio","matched","empirical_group")},
            "support_eligible":bool(supported and complete), "support_reason":reason})
        progress("Evaluating frozen combinations",len(rows),len(frozen.patterns))
    return rows, estimated


# Task 1080: integration over accepted source, predicate and matching authorities.
def validate_granular_definition(definition, *, source_request, column_profiles, horizon_source=None, family_universe=None):
    from .pattern_models import PatternRequest
    if type(definition) is not _granular_Definition or type(source_request) is not PatternRequest:
        raise TypeError("granular definition validation requires GranularRefinement and PatternRequest")
    request = source_request
    if _gr05_scope_enabled(request, definition):
        if _gr05_resolve_scope(request, definition, family_universe) is None:
            raise ValueError("granular population requires an analytical family selection")
    elif request.pre_event is None or request.family is None or request.comparison not in ("other_families","other_outcomes","non_start"):
        raise ValueError("granular population requires an exact-family pre-event frozen root and supported comparison")
    active = _granular_active(definition)
    if request.comparison == "other_outcomes" and not _granular_active(_granular_Definition(outcome=definition.outcome)):
        raise ValueError("other_outcomes requires an active outcome definition")
    if request.comparison == "non_start":
        if (request.origin is not None or any(p.domain=="context" for p in active.values())
                or any(p.domain!="column" for p in _granular_active(_granular_Definition(common=definition.common)).values())):
            raise ValueError("non_start requires All origins, no active context, and column-only common restrictions")
    validate_granular_context(definition,column_profiles=column_profiles,offsets=request.pre_event.offsets)
    horizons = [p for p in active.values() if p.domain == "horizon"]
    if horizons:
        if not horizon_source:
            raise ValueError("price_source_missing: explicitly run a fresh discovery through Analysis service and repin")
        for p in horizons:
            for role in _gr04_required_roles(p.field, request.trend_direction):
                capability = horizon_source.get("roles", {}).get(role, {})
                if capability.get("status") != "available":
                    raise ValueError(f"{role}: {capability.get('reason', 'canonical_price_column_missing')}")
    _grdate_resolve(definition, source_request)


def _gr03_request(frozen):
    request = frozen.original_request
    if request.pre_event.chronological and frozen.resolved_split is not None:
        request = replace(request, pre_event=replace(request.pre_event, split_ms=frozen.resolved_split))
    return request


def _gr03_charge(report):
    if not isinstance(report, dict) or report.get("kind") != "gr03-population-report-v1":
        raise ValueError("invalid granular population report")
    charge = len(_json({k:v for k,v in report.items() if k != "accounting"}).encode("utf-8"))
    accounting = report.get("accounting", {})
    if (not isinstance(accounting,dict) or type(accounting.get("retained_payload_bytes")) is not int or accounting["retained_payload_bytes"] != charge
            or type(accounting.get("limit_bytes")) is not int or not charge <= accounting["limit_bytes"] <= 134217728
            or accounting.get("scope") != "canonical_UTF8_payload_bytes_not_process_RSS_or_frozen_source"):
        raise ValueError("invalid granular population accounting")
    return charge


def _gr03_data(frozen, report, checkpoint):
    from .trend_start_patterns import _covered
    root = frozen._root
    request = _gr03_request(frozen)
    instance = json.loads(root["instance"])
    timestamps = root["timestamps"]
    breaks, coverage = _continuity(timestamps, root["timeframe"], instance, checkpoint)
    cumulative = [0]
    for i, t in enumerate(timestamps):
        if i % 128 == 0:
            checkpoint()
        cumulative.append(cumulative[-1] + (not _covered(t, instance["control_coverage"])))
    events = {e["event_id"]:e for e in instance["events"]}
    samples = report["samples"]
    data = dict(pre_event=True, timestamps=timestamps, positions={t:i for i,t in enumerate(timestamps)},
        columns={n:root["columns"][n] for n in request.columns}, breaks=breaks, coverage=coverage,
        events=events, measurement_reports=instance["measurement_reports"], patterns={}, samples=samples,
        split_ms=frozen.resolved_split, ordinary_controls=request.comparison=="non_start",
        control_uncovered=tuple(cumulative), control_ids=frozenset(s["event_id"] for s in samples if s["ordinary"]),
        targets=[events[s["event_id"]] for s in samples if s["cohort"]=="target"],
        comparisons=[events[s["event_id"]] for s in samples if s["cohort"]=="comparison" and not s["ordinary"]],
        controls=tuple(s["anchor"] for s in samples if s["cohort"]=="comparison"))
    if "family_scope" in report:
        data.update(_gr05_scope=deepcopy(report["family_scope"]), _gr05_family_population=deepcopy(report["family_population"]))
    return data


def _gr03_tables(report, events):
    columns = ("event_id", "anchor_ts_ms", "family", "ordinary", "cohort", "reason", "partition",
        "partition_reason", "scope_selected", "mandatory_eligible", "evaluation_scope", "common_status",
        "outcome_status", "source_resolution_status", "feature_start_ms", "cutoff_ms", "evidence_start_ms", "evidence_end_ms")
    date_columns = ("anchor_in_range", "before_date_cohort", "before_date_reason", "before_date_partition", "before_date_partition_reason")
    if "anchor_range" in report:
        columns += date_columns
    population, assignments = [], []
    for record in report["records"]:
        predicates = record["predicate_report"]
        row = {k:record[k] for k in columns if k in record}
        row.update(event_id=record["row_id"], common_status=None if predicates is None else predicates["purposes"]["common"],
            outcome_status=None if predicates is None else predicates["purposes"]["outcome"],
            source_resolution_status=record["source_resolution"]["status"])
        if "anchor_range" in report:
            check = record["anchor_range_check"]
            row.update(zip(date_columns, (check[k] for k in ("in_range", "prior_cohort", "prior_reason", "prior_partition", "prior_partition_reason")), strict=True))
        population.append(row)
        assignments.append({**{k:row[k] for k in _ASSIGNMENTS if k != "failed_conditions"},
            "failed_conditions":"; ".join(p["reason"] for p in (predicates["predicates"] if predicates else []) if p["status"]=="mismatch")})
    families = []
    for family in sorted({r["family"] for r in report["records"] if not r["ordinary"]}):
        group = [r for r in report["records"] if not r["ordinary"] and r["family"]==family]
        families.append(dict(family=family,source_starts=len(group),mandatory_excluded=sum(not r["mandatory_eligible"] for r in group),
            target=sum(r["cohort"]=="target" for r in group),comparison=sum(r["cohort"]=="comparison" for r in group),
            cohort_excluded=sum(r["cohort"]=="excluded" for r in group)))
    event_rows = [{**row,"event_kind":events.get(row["event_id"],{}).get("event_kind"),
        "origin":events.get(row["event_id"],{}).get("facts",{}).get("origin")} for row in population]
    return (("population",pd.DataFrame(population,columns=columns,dtype=object)),
        ("cohort_assignments",pd.DataFrame(assignments,columns=_ASSIGNMENTS,dtype=object)),
        ("refinement_funnel",pd.DataFrame([{**r,"scope":"granular accepted cohort/partition totals"} for r in report["summary"]["by_cohort_partition"]],dtype=object)),
        ("families",pd.DataFrame(families,columns=("family","source_starts","mandatory_excluded","target","comparison","cohort_excluded"),dtype=object)),
        ("events",pd.DataFrame(event_rows,columns=(*columns,"event_kind","origin"),dtype=object)))


def _gr03_attach(data, definition, report):
    data.update(_gr03_definition=definition,_gr03_population=report,
        _gr03_population_index={r["row_id"]:r for r in report["records"]})


def _gr03_context(frozen, definition, report):
    from .refinement_models import summarize_granular_refinement
    context = dict(active_filter_kind="granular",definition=definition.to_dict(),definition_id=definition.identity,
        population_report_id=report["report_id"],population_summary=deepcopy(report["summary"]),legacy_filters_applied=False,
        definition_summary=summarize_granular_refinement(definition),source_request=_plain(frozen.original_request),
        source_discovery_id=frozen.source_discovery_id,root_id=frozen.root_id,set_id=frozen.set_id,
        retained_population_bytes=_gr03_charge(report),interpretation="retrospective_full_history; no forecasting probability or significance")
    if "family_scope" in report:
        context.update(family_scope=deepcopy(report["family_scope"]), family_population=deepcopy(report["family_population"]))
    if _gr04_active_horizons(definition): context["horizon_source"] = deepcopy(report["horizon_source"])
    if "anchor_range" in report:
        context.update(anchor_range=deepcopy(report["anchor_range"]), anchor_range_summary=deepcopy(report["anchor_range_summary"]))
    return context


def evaluate_granular_patterns(frozen, definition, *, parent=None, checkpoint=_checkpoint, progress=_progress,
                              memory_limit_bytes=134217728):
    checkpoint()
    if type(frozen) is not FrozenPatternSet or type(definition) is not _granular_Definition:
        raise TypeError("granular evaluation requires FrozenPatternSet and GranularRefinement")
    if (parent is not None and (not isinstance(parent,PatternEvaluation) or parent.root_id!=frozen.root_id or parent.set_id!=frozen.set_id)):
        raise ValueError("parent must belong to the same frozen set and root")
    if type(memory_limit_bytes) is not int or not 1<=memory_limit_bytes<=134217728:
        raise ValueError("memory limit must be an integer from 1 through 128 MiB")
    report = resolve_granular_population(frozen,definition,checkpoint=checkpoint,progress=progress,memory_limit_bytes=memory_limit_bytes)
    charge = _gr03_charge(report)
    data = _gr03_data(frozen,report,checkpoint)
    request = _gr03_request(frozen)
    rows, estimated = _gr03_match(frozen,data,request,checkpoint,progress,memory_limit_bytes-charge)
    parent_id = frozen.source_discovery_id if parent is None else parent.evaluation_id
    identity = _gr04_result_identity("evaluation", frozen, definition, parent_id=parent_id)
    tables = _gr03_tables(report,data["events"])
    if "family_scope" in report:
        tables += (("family_population", pd.DataFrame(report["family_population"], dtype=object)),)
    assignments = next(frame for n,frame in tables if n=="cohort_assignments").to_dict("records")
    before = (_statuses(frozen._root["assignments"],frozen._root["samples"],data["timestamps"],population=frozen._root.get("_gr03_population")) if parent is None else
        _statuses(parent.frame("cohort_assignments").to_dict("records"),parent._data["samples"],data["timestamps"],population=parent._data.get("_gr03_population")))
    changes = _changes(before,_statuses(assignments,data["samples"],data["timestamps"],population=report))
    metadata = frozen.metadata()
    context = {**_gr03_context(frozen,definition,report),"mode":"frozen_evaluation","parent_id":parent_id,"evaluation_id":identity,
        "reference":_plain(request.reference),"effective_request":_plain(request),"frozen_split":frozen.resolved_split,
        "automatic_split":metadata["automatic_split"],"source_discovery_search":metadata["original_search"],"source_runtime":metadata["source_runtime"],
        "selected_rules_evaluated":len(rows),"support_eligible_rules":sum(r["support_eligible"] for r in rows),
        "population_counts":{k:v.bit_count() for k,v in data["populations"].items()},
        "chronology_excluded":sum(s["partition"]=="excluded" for s in data["samples"]),
        "estimated_retained_match_state_bytes":estimated,"retained_total_bytes":estimated+charge,"memory_limit_bytes":memory_limit_bytes,
        "memory_scope":"retained evaluation masks and canonical population payload only; excludes source/discovery masks, frames, indexes, definitions, temporary views and process RSS"}
    tables += (("patterns",pd.DataFrame(rows,dtype=object)),("population_changes",pd.DataFrame(changes,columns=_CHANGES,dtype=object)),
        ("diagnostics",pd.DataFrame([(k,_json(_plain(v)) if isinstance(v,(dict,list,tuple)) else v) for k,v in context.items()],columns=("field","value"),dtype=object)))
    _gr03_attach(data,definition,report)
    checkpoint()
    return PatternEvaluation(frozen.root_id,frozen.set_id,identity,parent_id,request,_json(context),tables,data)


def _gr03_discovery_stamp(discovery):
    data = discovery._data
    context = json.loads(discovery.context)
    report = data["_gr03_population"]
    rows = discovery.frame("patterns").to_dict("records")
    parts = ("gr03-discovery-binding-v1",data["_pin_source_binding"],_plain(discovery.request),
        data["_gr03_definition"].to_dict(),context["search_parent"],
        {k:v for k,v in report.items() if k!="accounting"},context["search"],_plain(rows),
        [[t.to_dict() for t in data["patterns"][r["pattern_id"]]["terms"]] for r in rows])
    if _gr04_active_horizons(data["_gr03_definition"]):
        _gr04_require(data.get("_gr04_price_binding") == _gr04_digest(data.get("_gr04_prices")), "search source binding")
        parts += (data["_gr04_price_binding"],)
    return _hash(parts)


def search_granular_patterns(frozen, binning_result, catalogue, definition, *, parent_id,
                            checkpoint=_checkpoint, progress=_progress, population_limit_bytes=134217728):
    from collections import defaultdict
    from .pre_event_patterns import mine
    from .trend_start_patterns import _frequencies
    checkpoint()
    if type(frozen) is not FrozenPatternSet or not isinstance(binning_result,AnalysisResult) or not isinstance(catalogue,PatternCatalogue):
        raise TypeError("granular search requires a pinned set and its retained inputs")
    if type(parent_id) is not str or not parent_id:
        raise ValueError("granular search requires a selected parent ID")
    request = _gr03_request(frozen)
    instance = catalogue.instance(request.instance_id)
    if (request.reference!=binning_result.entry.reference or catalogue.reference!=request.reference or
            catalogue.run_key!=request.run_key or analysis_key(binning_result)!=request.run_key or instance["status"]!="available"):
        raise ValueError("granular search source/reference/run identities disagree")
    binding = frozen._root.get("_gr03_source_binding")
    if type(binding) is not str or not binding:
        raise ValueError("granular search source stamp absent: repin the original discovery explicitly")
    if binding!=_pin_source_binding(binning_result,instance,frozen._root["timestamps"],checkpoint=checkpoint):
        raise ValueError("source_discovery_binding_mismatch")
    report = resolve_granular_population(frozen,definition,checkpoint=checkpoint,progress=progress,memory_limit_bytes=population_limit_bytes)
    data = _gr03_data(frozen,report,checkpoint)
    rows, search = mine(data,binning_result,request,checkpoint,progress)
    groups = defaultdict(list)
    for event in data["targets"]:
        groups[event["family"]].append(data["positions"][event["anchor_ts_ms"]])
    frequencies = _frequencies(data,groups,request,checkpoint)
    source_context = deepcopy(frozen.metadata()["source"]["context"])
    for key in ("family_scope", "family_population", "family_search_parent", "anchor_range", "anchor_range_summary"):
        source_context.pop(key, None)
    context = {**source_context,**_gr03_context(frozen,definition,report),
        "search":search,"split_ms":frozen.resolved_split,"pre_event":request.pre_event.to_dict(),
        "refinement":request.refinement.to_dict(),"refinement_provenance_only":True,
        "search_parent":{"root_id":frozen.root_id,"set_id":frozen.set_id,"checkpoint_id":parent_id},
        "discovery":"NEW DISCOVERY"}
    if not _gr04_active_horizons(definition): context.pop("horizon_source", None)
    tables = _gr03_tables(report,data["events"])+(("patterns",pd.DataFrame(rows,dtype=object) if rows else
        pd.DataFrame(columns=("pattern_id","kind","rank_eligible","conditions","condition"),dtype=object)),
        ("frequencies",pd.DataFrame(frequencies,dtype=object)),
        ("diagnostics",pd.DataFrame([(k,_json(_plain(v)) if isinstance(v,(dict,list,tuple)) else v) for k,v in context.items()],columns=("field","value"),dtype=object)))
    if "family_scope" in report:
        tables += (("family_population", pd.DataFrame(report["family_population"], dtype=object)),)
    _gr03_attach(data,definition,report)
    data["_pin_source_binding"] = binding
    study = PatternStudy(request,_json(context),tables,data)
    if "_gr04_prices" in frozen._root or "_gr04_price_binding" in frozen._root:
        model = _gr04_source(frozen, checkpoint)
        _gr04_attach_prices(study, (frozen._root["_gr04_prices"], frozen._root["_gr04_price_binding"]),
                           model["market_id"], checkpoint=checkpoint)
    data["_gr03_discovery_binding"] = _gr03_discovery_stamp(study)
    checkpoint()
    return study


def _gr03_filter_context(parent, request, families):
    from leonardo.financial_tools.variation_models import _BANDS
    columns = {}
    for column in parent.columns:
        profile = column.profile
        labels = []
        if profile is not None:
            if column.request.measurement=="directional_intensity":
                for side in (profile.analysis.negative,profile.analysis.positive):
                    labels.extend(b["label"] for b in side.to_dict()["bins"])
                if profile.analysis.zero_count:
                    labels.append("Zero")
            else:
                labels.extend(_BANDS)
        columns[column.request.source] = dict(profile_id=profile.profile_id if profile else None,
            measurement=column.request.measurement,labels=tuple(labels))
    return dict(original_request=request,offsets=request.pre_event.offsets,columns=columns,
        previous_families=tuple(sorted(set(families)|{"NONE"})))


def _gr03_verify_discovery(discovery, checkpoint):
    from types import SimpleNamespace
    data = discovery._data
    context = json.loads(discovery.context)
    definition = discovery.granular_definition
    report = data.get("_gr03_population")
    if (definition is None or not isinstance(report,dict) or type(data.get("_gr03_discovery_binding")) is not str
            or type(data.get("_pin_source_binding")) is not str):
        raise ValueError("granular discovery requires definition, population and both source stamps; rerun explicitly")
    _gr03_charge(report)
    scoped = _gr05_scope_enabled(discovery.request, definition)
    universe = _gr05_family_universe(data["events"].values(), event_kind=discovery.request.event_kind,
        start_ms=discovery.request.start_ms, end_ms=discovery.request.end_ms)
    scope = _gr05_resolve_scope(discovery.request, definition, universe) if scoped else None
    _gr05_validate_presentation(discovery, scope)
    if "_gr05_discovery_binding" in data or "family_search_parent" in context:
        raise ValueError("simple scope stamp cannot appear on a granular discovery")
    if scope is not None:
        summary = _gr05_family_population(discovery.frame("cohort_assignments").to_dict("records"), data["samples"],
            data["events"], data["timestamps"], scope, population=report, checkpoint=checkpoint)
        if summary != report["family_population"]:
            raise ValueError("granular family counts disagree with accepted population")
    if _gr04_active_horizons(definition):
        model = _gr04_validate_price_snapshot(data.get("_gr04_prices"), data.get("_gr04_price_binding"),
            discovery.request.reference, None, data["timestamps"], checkpoint=checkpoint)
        holder = SimpleNamespace(original_request=discovery.request, set_id=report["set_id"],
            _root={"_gr04_prices":data["_gr04_prices"], "_gr04_price_binding":data["_gr04_price_binding"]})
        header = _gr04_header(holder, definition, model, checkpoint=checkpoint)
        _gr04_require(report.get("horizon_source") == header == context.get("horizon_source")
            and report["report_id"] == _gr04_result_identity("population", holder, definition), "discovery horizon header")
    elif "horizon_source" in report or "horizon_source" in context:
        raise ValueError("inactive definition cannot carry a horizon report header")
    if (context.get("active_filter_kind")!="granular" or context.get("legacy_filters_applied") is not False
            or context.get("definition")!=definition.to_dict() or context.get("definition_id")!=definition.identity
            or report.get("definition")!=definition.to_dict() or report.get("definition_id")!=definition.identity
            or context.get("population_report_id")!=report.get("report_id") or context.get("population_summary")!=report.get("summary")
            or context.get("search_parent")!={"root_id":report.get("root_id"),"set_id":report.get("set_id"),"checkpoint_id":context.get("search_parent",{}).get("checkpoint_id")}
            or type(context["search_parent"]["checkpoint_id"]) is not str
            or data["samples"]!=report["samples"]):
        raise ValueError("granular discovery components disagree")
    source = deepcopy(_plain(discovery.request))
    original = deepcopy(report["source_request"])
    if original["pre_event"]["chronological"]:
        original["pre_event"]["split_ms"] = report["resolved_split_ms"]
    if source!=original or context.get("source_request")!=report["source_request"]:
        raise ValueError("granular discovery source request disagrees")
    if data["_gr03_discovery_binding"]!=_gr03_discovery_stamp(discovery):
        raise ValueError("granular discovery binding mismatch")
    _grdate_validate_presentation(discovery, discovery.request, definition)
    for name,expected in _gr03_tables(report,data["events"]):
        try:
            pd.testing.assert_frame_equal(discovery.frame(name),expected,check_exact=True)
        except (AssertionError,StopIteration,KeyError) as exc:
            raise ValueError("granular discovery population tables disagree") from exc
    rows = discovery.frame("patterns").to_dict("records")
    atoms, indices = data["atoms"], {}
    patterns = []
    for order,row in enumerate(rows,1):
        entry = data["patterns"][row["pattern_id"]]
        terms = entry["terms"]
        if len(terms)!=len(entry["indices"]) or any(type(i) is not int or not 0<=i<len(atoms) for i in entry["indices"]):
            raise ValueError("granular discovery atom references disagree")
        if tuple(atoms[i] for i in entry["indices"])!=tuple(terms):
            raise ValueError("granular discovery terms disagree with atoms")
        for term,index in zip(terms,entry["indices"],strict=True):
            if term in indices and indices[term]!=index:
                raise ValueError("granular discovery atom identities disagree")
            indices[term] = index
        patterns.append(FrozenPattern(row["pattern_id"],tuple(terms),order,_json(_plain(row))))
    # Use the one retained-rule matcher to verify supplied discovery masks/counts.
    prepared = {**data,"patterns":{}}
    holder = SimpleNamespace(patterns=patterns,_root={"atom_indices":indices},metadata=lambda:{"original_search":context["search"]})
    verified,_ = _gr03_match(holder,prepared,discovery.request,checkpoint,_progress,134217728)
    for actual,expected in zip(rows,verified,strict=True):
        if any(_plain(actual[k])!=_plain(expected[k]) for k in actual.keys() & expected.keys()):
            raise ValueError("granular discovery rule counts disagree")
        if data["patterns"][actual["pattern_id"]]["masks"]!=prepared["patterns"][actual["pattern_id"]]["masks"]:
            raise ValueError("granular discovery rule masks disagree")
    if any(data["atom_masks"][i]!=m for i,m in prepared["atom_masks"].items()):
        raise ValueError("granular discovery atom masks disagree")
    if any(data[k]!=prepared[k] for k in ("populations","timing_mask","control_ids")):
        raise ValueError("granular discovery population masks disagree")
    expected_targets = [s["event_id"] for s in report["samples"] if s["cohort"]=="target"]
    expected_comparisons = [s["event_id"] for s in report["samples"] if s["cohort"]=="comparison" and not s["ordinary"]]
    if ([e["event_id"] for e in data["targets"]]!=expected_targets or
            [e["event_id"] for e in data["comparisons"]]!=expected_comparisons or
            data["controls"]!=tuple(s["anchor"] for s in report["samples"] if s["cohort"]=="comparison") or
            data["split_ms"]!=report["resolved_split_ms"]):
        raise ValueError("granular discovery cohort fields disagree")
    return definition,report


# Task 1083: optional anchor population projection over the unchanged source.
def _grdate_resolve(definition, source_request):
    from .pattern_models import PatternRequest
    from .refinement_models import GranularRefinement
    if type(definition) is not GranularRefinement or type(source_request) is not PatternRequest:
        raise TypeError("anchor range requires GranularRefinement and PatternRequest")
    if definition.anchor_range is None:
        return None
    if source_request.pre_event is None:
        raise ValueError("anchor range requires the original Pre-event request")
    bounds = definition.anchor_range
    if not source_request.start_ms <= bounds.start_ms <= bounds.end_ms <= source_request.end_ms:
        raise ValueError("anchor date range must stay inside the original pinned interval")
    return dict(kind="gr-date-anchor-scope-v1", root_start_ms=source_request.start_ms,
        root_end_ms=source_request.end_ms, start_ms=bounds.start_ms, end_ms=bounds.end_ms,
        inclusive=True, basis="anchor_ts_ms")


def _grdate_status(prior, inside):
    fields = ("cohort", "reason", "partition", "partition_reason")
    if inside:
        return {key:prior[key] for key in fields}
    return dict(cohort="excluded", reason="outside_anchor_range", partition="excluded", partition_reason="outside_anchor_range")


def _grdate_summary(records):
    counts = dict(root_candidates=0, inside_candidates=0, outside_candidates=0, outside_target=0,
        outside_comparison=0, outside_previously_excluded=0, kept_target=0, kept_comparison=0, kept_excluded=0)
    for record in records:
        check = record["anchor_range_check"]
        counts["root_candidates"] += 1
        if check["in_range"]:
            counts["inside_candidates"] += 1
            counts["kept_"+record["cohort"]] += 1
        else:
            counts["outside_candidates"] += 1
            counts["outside_previously_excluded" if check["prior_cohort"] == "excluded" else "outside_"+check["prior_cohort"]] += 1
    return counts


def _grdate_apply(records, samples, definition, source_request, checkpoint):
    checkpoint()
    descriptor = _grdate_resolve(definition, source_request)
    if descriptor is None:
        return samples, None, None
    kept = set()
    for index, record in enumerate(records):
        if index % 128 == 0:
            checkpoint()
        inside = definition.anchor_range.contains(record["anchor_ts_ms"])
        prior = {key:record[key] for key in ("cohort", "reason", "partition", "partition_reason")}
        record["anchor_range_check"] = dict(in_range=inside, **{"prior_"+key:value for key,value in prior.items()})
        record.update(_grdate_status(prior, inside))
        if inside:
            kept.add(record["row_id"])
    filtered = []
    for index, sample in enumerate(samples):
        if index % 128 == 0:
            checkpoint()
        if sample["event_id"] in kept:
            filtered.append(sample)
    checkpoint()
    summary = _grdate_summary(records)
    checkpoint()
    return filtered, descriptor, summary


def _grdate_validate_presentation(result, source_request, definition):
    descriptor = _grdate_resolve(definition, source_request)
    report = result._data["_gr03_population"]
    context = json.loads(result.context)
    records = report["records"]
    columns = ("anchor_in_range", "before_date_cohort", "before_date_reason", "before_date_partition", "before_date_partition_reason")
    if descriptor is None:
        if (any(key in holder for holder in (report, context) for key in ("anchor_range", "anchor_range_summary"))
                or "anchor_range_excluded" in report["summary"]
                or any("anchor_range_check" in record for record in records)
                or any(name in result.frame(table).columns for table in ("population", "events") for name in columns)):
            raise ValueError("unexpected anchor date presentation without a range")
        return
    if any(holder.get("anchor_range") != descriptor for holder in (report, context)):
        raise ValueError("anchor date descriptor disagrees")
    by_id = {}
    expected_ids = set()
    fields = ("cohort", "reason", "partition", "partition_reason")
    for record in records:
        check = record.get("anchor_range_check")
        if (type(check) is not dict or set(check) != {"in_range", *("prior_"+key for key in fields)}
                or type(check["in_range"]) is not bool
                or any(type(check["prior_"+key]) is not str for key in fields)
                or check["prior_cohort"] not in ("target", "comparison", "excluded")
                or check["prior_partition"] not in ("discovery", "later", "excluded")):
            raise ValueError("invalid anchor date record check")
        inside = definition.anchor_range.contains(record["anchor_ts_ms"])
        prior = {key:check["prior_"+key] for key in fields}
        if check["in_range"] is not inside or any(record[key] != value for key,value in _grdate_status(prior, inside).items()):
            raise ValueError("anchor date final status disagrees")
        identity = record["row_id"]
        if identity in by_id:
            raise ValueError("duplicate anchor date record")
        by_id[identity] = record
        if inside and record["cohort"] in ("target", "comparison"):
            expected_ids.add(identity)
    counts = _grdate_summary(records)
    for holder in (report, context):
        supplied = holder.get("anchor_range_summary")
        if (type(supplied) is not dict or set(supplied) != set(counts)
                or any(type(v) is not int for v in supplied.values()) or supplied != counts):
            raise ValueError("anchor date counts disagree")
    excluded = report["summary"].get("anchor_range_excluded")
    if type(excluded) is not int or excluded != counts["outside_candidates"]:
        raise ValueError("anchor date exclusion count disagrees")
    seen = set()
    timestamps = result._data["timestamps"]
    for sample in report["samples"]:
        identity = sample["event_id"]
        if identity in seen or identity not in expected_ids:
            raise ValueError("escaped or duplicate anchor date sample")
        seen.add(identity)
        record = by_id[identity]
        anchor = sample["anchor"]
        if (type(anchor) is not int or not 0 <= anchor < len(timestamps)
                or timestamps[anchor] != record["anchor_ts_ms"]
                or any(sample.get(key) != record[key] for key in (
                    "anchor", "ordinary", "cohort", "partition", "partition_reason", "reason", "timing",
                    "feature_start_ms", "cutoff_ms", "evidence_start_ms", "evidence_end_ms")
                    if key in sample and key in record)
                or type(sample.get("ordinary")) is not bool or sample["ordinary"] is not record["ordinary"]):
            raise ValueError("anchor date sample fields disagree")
    if seen != expected_ids:
        raise ValueError("anchor date sample membership disagrees")
    for name, expected in _gr03_tables(report, result._data["events"]):
        if name not in ("population", "events", "cohort_assignments"):
            continue
        selected = ["event_id", "anchor_ts_ms", "cohort", "reason", "partition", "partition_reason"]
        if name != "cohort_assignments":
            selected += ["ordinary", *columns]
        try:
            pd.testing.assert_frame_equal(result.frame(name)[selected], expected[selected], check_exact=True)
        except (AssertionError, KeyError, StopIteration) as exc:
            raise ValueError("anchor date population tables disagree") from exc


# Task 1081: immutable revision-owned prices and fixed-horizon adaptation.
def _gr04_require(condition, detail):
    if not condition:
        raise ValueError("price_source_binding_mismatch: " + detail)


def _gr04_digest(payload, checkpoint=_checkpoint):
    _gr04_require(type(payload) is bytes, "source must be immutable bytes")
    digest = sha256()
    for start in range(0, len(payload), 65536):
        checkpoint()
        digest.update(payload[start:start + 65536])
    checkpoint()
    return digest.hexdigest()


def _gr04_market(market):
    return {key: getattr(market, key) for key in ("exchange", "market_type", "symbol", "timeframe")}


def _gr04_role_reason(manifest, role):
    if manifest["schema_version"] == "1.0":
        return "legacy_price_provenance_unavailable"
    outputs = manifest.get("selected_outputs", ())
    selections = manifest.get("selection_sources", ())
    provenance = manifest.get("value_provenance", {})
    if (any(o["column_name"] == role for o in outputs)
            or any(role in s["column_names"] for s in selections)
            or any(o["column_name"] == role for o in provenance.get("outputs", ()))):
        return "calculated_output_not_canonical_price"
    mapping = manifest["column_mapping"]
    if mapping.get(role) != role or list(mapping.values()).count(role) != 1:
        return "canonical_price_column_missing"
    return ""


def _gr04_capture_price_snapshot(loaded, rows, as_of, *, checkpoint=_checkpoint):
    checkpoint()
    manifest = loaded.manifest.to_dict()
    header, records = rows[0], rows[1:]
    _gr04_require(header[0] == "ts_ms" and manifest["column_mapping"].get("ts_ms") == "ts_ms", "timestamp mapping")
    roles = {}
    for role in ("close", "high", "low"):
        checkpoint()
        reason = _gr04_role_reason(manifest, role)
        values = []
        if not reason:
            _gr04_require(header.count(role) == 1, "canonical price header")
            column = header.index(role)
            for index, row in enumerate(records):
                if index % 64 == 0: checkpoint()
                values.append(row[column])
        roles[role] = dict(status="unavailable" if reason else "available", reason=reason,
                           column=None if reason else role, raw_values=values)
    reference = dict(database_id=loaded.manifest.database_id, revision_id=loaded.manifest.revision_id,
                     values_sha256=loaded.manifest.values_sha256)
    timestamps = []
    for index, row in enumerate(records):
        if index % 64 == 0: checkpoint()
        timestamps.append(int(row[0]))
    payload = _json(dict(kind="gr04-pinned-price-snapshot-v1", reference=reference,
        market_id=_gr04_market(loaded.manifest.market_id), manifest=manifest, acquired_at_ms=as_of,
        availability="snapshot_read_only", timestamps=timestamps, roles=roles)).encode("utf-8")
    binding = _gr04_digest(payload, checkpoint)
    _gr04_validate_price_snapshot(payload, binding, reference, _gr04_market(loaded.manifest.market_id),
                                 timestamps, checkpoint=checkpoint)
    checkpoint()
    return payload, binding


def _gr04_validate_price_snapshot(payload, binding, reference, market_id, timestamps, *, checkpoint=_checkpoint):
    from leonardo.data_manager.creation_models import database_revision_from_dict
    checkpoint()
    _gr04_require(type(binding) is str and len(binding) == 64 and binding == _gr04_digest(payload, checkpoint), "digest")
    try:
        model = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("price_source_binding_mismatch: invalid JSON") from exc
    _gr04_require(type(model) is dict and set(model) == {"kind", "reference", "market_id", "manifest",
        "acquired_at_ms", "availability", "timestamps", "roles"}, "snapshot shape")
    _gr04_require(model["kind"] == "gr04-pinned-price-snapshot-v1" and model["availability"] == "snapshot_read_only", "snapshot kind")
    try:
        manifest = database_revision_from_dict(model["manifest"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("price_source_binding_mismatch: manifest") from exc
    expected = dict(database_id=manifest.database_id, revision_id=manifest.revision_id, values_sha256=manifest.values_sha256)
    _gr04_require(model["reference"] == expected == _plain(reference), "reference")
    _gr04_require(model["market_id"] == _gr04_market(manifest.market_id)
                  and (market_id is None or model["market_id"] == _plain(market_id)), "market")
    axis = model["timestamps"]
    _gr04_require(type(axis) is list and bool(axis) and len(axis) == manifest.row_count, "axis shape")
    previous = -1
    for index, stamp in enumerate(axis):
        if index % 64 == 0: checkpoint()
        _gr04_require(type(stamp) is int and previous < stamp < 2**63, "ordered int64 axis")
        previous = stamp
    _gr04_require(tuple(axis) == tuple(timestamps) and axis[0] == manifest.first_timestamp_ms
        and axis[-1] == manifest.last_timestamp_ms and manifest.column_mapping.get("ts_ms") == "ts_ms", "timestamp association")
    _gr04_require(type(model["acquired_at_ms"]) is int and axis[-1] <= model["acquired_at_ms"] < 2**63, "read clock")
    _gr04_require(type(model["roles"]) is dict and set(model["roles"]) == {"close", "high", "low"}, "roles")
    for role, value in model["roles"].items():
        checkpoint()
        reason = _gr04_role_reason(manifest.to_dict(), role)
        _gr04_require(type(value) is dict and set(value) == {"status", "reason", "column", "raw_values"}, "role shape")
        _gr04_require(value["reason"] == reason and value["status"] == ("unavailable" if reason else "available")
            and value["column"] == (None if reason else role), "role association")
        raw = value["raw_values"]
        _gr04_require(type(raw) is list and len(raw) == (0 if reason else len(axis)), "role vector length")
        for index, cell in enumerate(raw):
            if index % 64 == 0: checkpoint()
            _gr04_require(type(cell) is str, "raw CSV cell")
    _gr04_require(_json(model).encode("utf-8") == payload, "canonical bytes")
    checkpoint()
    return model


def _gr04_attach_prices(study, prices, market_id, *, checkpoint=_checkpoint):
    payload, binding = prices
    _gr04_validate_price_snapshot(payload, binding, study.request.reference, market_id,
                                  study._data["timestamps"], checkpoint=checkpoint)
    checkpoint()
    study._data.update(_gr04_prices=payload, _gr04_price_binding=binding)


def _gr04_required_roles(field, direction):
    if field in ("terminal_signed", "terminal_directional"):
        return ("close",)
    upper = (field == "favorable_excursion") == (direction == "UP")
    return ("close", "high" if upper else "low")


def _gr04_capability(model, payload, binding, direction):
    fields = ("terminal_signed", "terminal_directional", "favorable_excursion", "adverse_excursion")
    return dict(price_snapshot_id=binding, reference=deepcopy(model["reference"]), acquired_at_ms=model["acquired_at_ms"],
        availability=model["availability"], source_payload_bytes=len(payload),
        roles={r: {k: model["roles"][r][k] for k in ("status", "reason")} for r in ("close", "high", "low")},
        supported_fields=[f for f in fields if all(model["roles"][r]["status"] == "available" for r in _gr04_required_roles(f, direction))])


def _gr04_active_horizons(definition):
    return tuple(sorted({p.horizon_bars for p in _granular_active(definition).values() if p.domain == "horizon"}))


def _gr04_source(frozen, checkpoint=_checkpoint):
    root = frozen._root
    if "_gr04_prices" not in root and "_gr04_price_binding" not in root:
        raise ValueError("price_source_missing: explicitly run a fresh discovery through Analysis service and repin")
    _gr04_require("_gr04_prices" in root and "_gr04_price_binding" in root, "both source keys required")
    model = _gr04_validate_price_snapshot(root["_gr04_prices"], root["_gr04_price_binding"],
        frozen.original_request.reference, None, root["timestamps"], checkpoint=checkpoint)
    _gr04_require(model["market_id"]["timeframe"] == root["timeframe"], "root timeframe")
    return model


def _gr04_header(frozen, definition, model=None, *, checkpoint=_checkpoint):
    horizons = _gr04_active_horizons(definition)
    if not horizons:
        return None
    model = _gr04_source(frozen, checkpoint) if model is None else model
    return {**_gr04_capability(model, frozen._root["_gr04_prices"], frozen._root["_gr04_price_binding"],
                               frozen.original_request.trend_direction),
            "horizons": list(horizons), "numerical_policy": "decimal50_half_even_v1"}


def _gr04_result_identity(kind, frozen, definition, *, parent_id=None):
    if kind not in ("population", "evaluation"):
        raise ValueError("unknown granular result identity kind")
    active = bool(_gr04_active_horizons(definition))
    parts = [("gr04-" if active else "gr03-") + kind + "-v1", frozen.set_id]
    if kind == "evaluation": parts.append(parent_id)
    parts.append(definition.identity)
    if active:
        root = frozen._root
        if "_gr04_prices" not in root and "_gr04_price_binding" not in root:
            raise ValueError("price_source_missing: explicitly run a fresh service discovery and repin")
        _gr04_require(root.get("_gr04_price_binding") == _gr04_digest(root.get("_gr04_prices")), "result source binding")
        parts.append(root["_gr04_price_binding"])
    return _hash(tuple(parts))


def _gr04_spacing(axis, timeframe, checkpoint):
    from leonardo.data import timeframe_duration_ms
    from leonardo.ohlcv.validation import _add_calendar_months
    step = timeframe_duration_ms(timeframe)
    prefix = [0]
    for index in range(1, len(axis)):
        if index % 64 == 0: checkpoint()
        try:
            expected = axis[index - 1] + step if step is not None else _add_calendar_months(axis[index - 1], int(timeframe[:-1]))
            bad = axis[index] != expected
        except (ValueError, OverflowError, OSError):
            bad = True
        prefix.append(prefix[-1] + bad)
    checkpoint()
    return prefix


def _gr04_window(model, snapshot_id, row_id, anchor, direction, n, roles, spacing, checkpoint):
    from decimal import Context, localcontext, InvalidOperation
    from leonardo.financial_tools.event_window_measurements import measure_event_window
    axis = model["timestamps"]
    inside = type(anchor) is int and 0 <= anchor < len(axis)
    end = anchor + n if inside else None
    complete = inside and end < len(axis)
    continuous = complete and spacing[end] == spacing[anchor]
    reason = ("horizon_anchor_unavailable" if not inside else "horizon_tail_incomplete" if not complete
              else "horizon_timestamp_gap" if not continuous else "")
    inputs = {}
    converted = {}
    for role in roles:
        start = anchor + (role != "close") if inside else 0
        raw = model["roles"][role]["raw_values"][start:end + 1] if inside else []
        inputs[role] = raw
        cells = []
        for index, cell in enumerate(raw):
            if index % 64 == 0: checkpoint()
            if cell == "": cells.append(None)
            else:
                with localcontext(Context(traps=[])):
                    try: value = _granular_Decimal(cell)
                    except (ValueError, InvalidOperation): value = _granular_Decimal("NaN")
                cells.append(value)
        converted[role] = cells
    window = dict(window_id=_hash(("gr04-window-v1", snapshot_id, row_id, direction, n)), price_snapshot_id=snapshot_id,
        source_reference=deepcopy(model["reference"]), manifest_identity=_hash(model["manifest"]), direction=direction,
        horizon_bars=n, reference="event_close", start_row=anchor if inside else None, end_row=end if complete else None,
        start_ts_ms=axis[anchor] if inside else None, end_ts_ms=axis[end] if complete else None,
        required_start_ms=axis[anchor] if inside else None, required_end_ms=model["acquired_at_ms"],
        acquired_at_ms=model["acquired_at_ms"], availability=model["availability"], numerical_policy="decimal50_half_even_v1",
        tail_status="complete" if complete else "incomplete", spacing_status="continuous" if continuous else "unavailable",
        reason=reason, inputs=inputs)
    values = None if reason else measure_event_window(converted["close"], high=converted.get("high"), low=converted.get("low"),
                                                     horizon_bars=n, direction=direction, checkpoint=checkpoint)
    return window, values


def _gr04_fact(predicate, window, values, direction):
    scalar = dict(value=None, reason=window["reason"]) if values is None else values[predicate.field + "_" + predicate.unit]
    source = dict(kind="fixed_horizon_price", window_id=window["window_id"], price_snapshot_id=window["price_snapshot_id"],
        direction=direction, horizon_bars=predicate.horizon_bars, field=predicate.field, unit=predicate.unit,
        required_roles=list(_gr04_required_roles(predicate.field, direction)), support_reason=scalar["reason"],
        required_start_ms=window["required_start_ms"], required_end_ms=window["required_end_ms"],
        available_at_ms=window["acquired_at_ms"], clock_basis=window["availability"])
    return scalar["value"], scalar["reason"], source


def _gr05_bound_scope(frozen, definition):
    from .pattern_models import _gr05_resolve_scope
    from .pre_event_cohorts import _gr05_family_universe
    request = frozen.original_request
    universe = _gr05_family_universe(json.loads(frozen._root["instance"])["events"],
        event_kind=request.event_kind, start_ms=request.start_ms, end_ms=request.end_ms)
    recorded = tuple(sorted(r["family"] for r in json.loads(frozen.compatible_families)))
    if universe != recorded:
        raise ValueError("family universe disagrees with the original frozen source")
    return _gr05_resolve_scope(request, definition, universe)


def _gr05_family_population(assignments, samples, events, timestamps, scope, *, population=None, checkpoint=_checkpoint):
    statuses = _statuses(assignments, samples, timestamps, population=population)
    rows = {}
    for family in scope["compatible_families"] + ([None] if scope["comparison"] == "non_start" else []):
        checkpoint()
        row = dict(family=family, ordinary=family is None, scope_selected=family in scope["selected_families"],
            candidate_rows=0, target=0, comparison=0, cohort_excluded=0)
        row.update({c+"_"+p:0 for c in ("target", "comparison") for p in ("discovery", "later", "chronology_excluded")})
        rows[family] = row
    for i, (identity, status) in enumerate(statuses.items()):
        if i % 128 == 0:
            checkpoint()
        family = None if status["ordinary"] else events[identity]["family"]
        row = rows[family]
        row["candidate_rows"] += 1
        cohort = status["cohort"]
        row["cohort_excluded" if cohort == "excluded" else cohort] += 1
        if cohort in ("target", "comparison"):
            row[cohort + "_" + ("chronology_excluded" if status["partition"] == "excluded" else status["partition"])] += 1
    return list(rows.values())


def _gr05_discovery_stamp(discovery):
    data = discovery._data
    rows = discovery.frame("patterns").to_dict("records")
    return _hash(("gr05-simple-discovery-binding-v1", data["_pin_source_binding"], _plain(discovery.request),
        data["_gr05_scope"], _plain(discovery.frame("cohort_assignments").to_dict("records")),
        _plain(data["samples"]), _plain(rows),
        [[t.to_dict() for t in data["patterns"][r["pattern_id"]]["terms"]] for r in rows],
        json.loads(discovery.context).get("family_search_parent")))


def _gr05_validate_presentation(result, scope):
    context = json.loads(result.context)
    data = result._data
    if scope is None:
        if any(k in data for k in ("_gr05_scope", "_gr05_family_population", "_gr05_discovery_binding")) or any(
                k in context for k in ("family_scope", "family_population", "family_search_parent")):
            raise ValueError("unexpected scoped result markers")
        return
    summary = data.get("_gr05_family_population")
    if data.get("_gr05_scope") != scope or context.get("family_scope") != scope or not isinstance(summary, list):
        raise ValueError("family scope result binding disagrees")
    if context.get("family_population") != summary:
        raise ValueError("family population context disagrees")
    try:
        pd.testing.assert_frame_equal(result.frame("family_population"), pd.DataFrame(summary, dtype=object), check_exact=True)
    except (AssertionError, KeyError, StopIteration) as exc:
        raise ValueError("family population table disagrees") from exc
    report = data.get("_gr03_population")
    if report is not None and (report.get("family_scope") != scope or report.get("family_population") != summary):
        raise ValueError("family population report disagrees")


def _gr05_verify_simple(discovery, universe, checkpoint):
    from .pattern_models import _gr05_resolve_scope, _gr05_scope_enabled
    request = discovery.request
    scope = _gr05_resolve_scope(request, request.refinement, universe) if _gr05_scope_enabled(request, request.refinement) else None
    _gr05_validate_presentation(discovery, scope)
    if scope is not None:
        if discovery._data.get("_gr05_discovery_binding") != _gr05_discovery_stamp(discovery):
            raise ValueError("simple family discovery binding mismatch")
        summary = _gr05_family_population(discovery.frame("cohort_assignments").to_dict("records"),
            discovery._data["samples"], discovery._data["events"], discovery._data["timestamps"], scope, checkpoint=checkpoint)
        if summary != discovery._data["_gr05_family_population"]:
            raise ValueError("simple family counts disagree with accepted assignments")
    return scope


def _gr05_search_request(frozen, refinement):
    from .pattern_models import _gr05_source_selection
    _gr05_bound_scope(frozen, refinement)
    scope = refinement.family_scope if refinement.family_scope is not None else _gr05_source_selection(frozen.original_request)
    request = replace(frozen.original_request, refinement=replace(refinement, family_scope=scope))
    if request.pre_event.chronological and frozen.resolved_split is not None:
        request = replace(request, pre_event=replace(request.pre_event, split_ms=frozen.resolved_split))
    return request


def _gr05_search_family_patterns(frozen, binning_result, catalogue, refinement, *, parent_id,
                                 checkpoint=_checkpoint, progress=_progress):
    from .pre_event_patterns import run_pre_event
    from .pattern_models import _gr05_scope_enabled
    checkpoint()
    if type(frozen) is not FrozenPatternSet or not isinstance(binning_result, AnalysisResult) or not isinstance(catalogue, PatternCatalogue):
        raise TypeError("family search requires a frozen set and retained inputs")
    if type(refinement) is not PatternRefinement or type(parent_id) is not str or not parent_id:
        raise ValueError("family search requires a simple definition and parent ID")
    if not _gr05_scope_enabled(frozen.original_request, refinement):
        raise ValueError("family search requires an explicit scope or recurrence")
    request = _gr05_search_request(frozen, refinement)
    instance = catalogue.instance(request.instance_id)
    if (request.reference != binning_result.entry.reference or catalogue.reference != request.reference
            or catalogue.run_key != request.run_key or analysis_key(binning_result) != request.run_key or instance["status"] != "available"):
        raise ValueError("family search source/reference/run identities disagree")
    binding = frozen._root.get("_gr03_source_binding")
    if type(binding) is not str or binding != _pin_source_binding(binning_result, instance, frozen._root["timestamps"], checkpoint=checkpoint):
        raise ValueError("source_discovery_binding_mismatch")
    study = run_pre_event(binning_result, json.loads(frozen._root["instance"]), request, frozen._root["timestamps"], checkpoint, progress)
    if "_gr04_prices" in frozen._root or "_gr04_price_binding" in frozen._root:
        model = _gr04_source(frozen, checkpoint)
        _gr04_attach_prices(study, (frozen._root["_gr04_prices"], frozen._root["_gr04_price_binding"]), model["market_id"], checkpoint=checkpoint)
    context = json.loads(study.context)
    context["family_search_parent"] = dict(root_id=frozen.root_id, set_id=frozen.set_id, checkpoint_id=parent_id)
    study = replace(study, context=_json(context))
    study._data["_gr05_discovery_binding"] = _gr05_discovery_stamp(study)
    checkpoint()
    return study


def resolve_inspection_measurements(frozen, result, metrics, *, checkpoint=_checkpoint,
                                   progress=_progress, memory_limit_bytes=134217728):
    """Detached scalar sidecar; never classify a population or alter its evidence union."""
    from .combination_explanations import _active_metrics, _canonical, _budget
    from .refinement_models import GranularPredicate
    from .pattern_models import PULLBACK_COHORTS
    from .pre_event_cohorts import partition_sample
    checkpoint()
    descriptors = tuple(metrics)
    if len(descriptors) > 40 or any(type(p) is not GranularPredicate for p in descriptors):
        raise ValueError("inspection requires at most 40 canonical numeric descriptors")
    if len({p.measurement_key for p in descriptors}) != len(descriptors):
        raise ValueError("duplicate inspection measurements")
    root = frozen._root; request = frozen.original_request
    active_metrics = _active_metrics(result)
    definition = result.granular_definition
    active = _granular_active(definition) if definition is not None else _gr06_simple_selectors(result.request.refinement)
    extras = {p.measurement_key:p for p in descriptors if p.measurement_key not in active_metrics}
    if len(extras) > 8: raise ValueError(f"inspection extras requested={len(extras)} allowed=8")
    horizons = {p.horizon_bars for p in (*active.values(), *extras.values()) if p.domain == "horizon"}
    if len(horizons)>8: raise ValueError(f"inspection horizons requested={len(horizons)} allowed=8")
    for p in descriptors:
        if (not p.enabled or p.minimum is not None or p.maximum is not None or p.allowed
                or not p.lower_inclusive or not p.upper_inclusive or p.domain=="context"
                or p.domain=="column" and p.field!="raw_value"):
            raise ValueError("inspection descriptors must be numeric and bounds-free")
        if p.domain=="column" and (p.column not in root["columns"]
                or root["columns"][p.column]["profile_id"]!=p.profile_id or p.offset not in request.pre_event.offsets):
            raise ValueError("inspection column/profile/offset is outside the frozen predictor context")
        if p.basis=="formation" and ((p.domain=="duration" and p.field in ("endpoint_extension","observed_elapsed"))
                or (p.domain=="pullbacks" and p.cohort not in PULLBACK_COHORTS[:4])):
            raise ValueError("inspection selector is unavailable for frozen formation")
    data={**result._data,"columns":root["columns"]}
    instance=json.loads(root["instance"])
    snapshot=frozen.metadata()["source"]["context"].get("snapshot_read_ms")
    samples={s["event_id"]:s for s in data["samples"]}
    population=data.get("_gr03_population")
    retained={r["row_id"]:r for r in population["records"]} if population is not None else {}
    statuses=_statuses(result.frame("cohort_assignments").to_dict("records"),data["samples"],data["timestamps"],population=population)
    model=spacing=None; price_reason=""
    if any(p.domain=="horizon" for p in extras.values()):
        try: model=_gr04_source(frozen,checkpoint)
        except ValueError as exc:
            if not str(exc).startswith("price_source_missing"): raise
            price_reason=str(exc)
        if model is not None: spacing=_gr04_spacing(root["timestamps"],root["timeframe"],checkpoint)
    output={}
    for ri,(row_id,status) in enumerate(statuses.items()):
        checkpoint()
        ordinary=status["ordinary"]; anchor=data["positions"].get(status["anchor_ts_ms"])
        event=data["events"].get(row_id); record=retained.get(row_id,{})
        saved={r["measurement_key"]:r for r in record.get("scalar_ledger",[])}
        resolution=_granular_empty_resolution("not_applicable" if ordinary else "not_requested")
        selected=witness=None; unresolved=""; coherent=True
        utc_extras={k:p for k,p in extras.items() if p.domain in ("movement","duration","pullbacks")}
        if not ordinary and (utc_extras or definition is None and active_metrics):
            resolution,selected,witness,unresolved,_=_granular_event_source(event,instance,data,{**active,**utc_extras},checkpoint)
            coherent=_gr06_coherent(result,event,record,active,selected,witness,resolution,instance)
        values={}; horizon_cache={}
        for p in descriptors:
            checkpoint();key=p.measurement_key; is_extra=key in extras
            if not is_extra and definition is not None:
                fact=deepcopy(saved.get(key))
                if fact is None:
                    fact=dict(measurement_key=key,selectors=p.to_dict(),known=False,value=None,
                        unavailable_reason="not_evaluated_at_completed_checkpoint",source=deepcopy(record.get("source_resolution",{})))
            else:
                value=None; reason=""; source={}
                if p.domain=="column":
                    value,reason,source=_granular_column_fact(p,anchor,data,ordinary,snapshot)
                elif ordinary:
                    reason="not_applicable_to_ordinary_control"
                elif not is_extra:
                    value,reason,source=_gr06_simple_value(event,p,instance)
                elif p.domain=="horizon":
                    if model is None: reason=price_reason
                    else:
                        roles=_gr04_required_roles(p.field,request.trend_direction)
                        capability=root["_gr03_filter_context"].get("horizon_source",{})
                        bad=[r for r in roles if capability.get("roles",{}).get(r,{}).get("status")!="available"]
                        if bad: reason="inspection_price_role_unavailable:"+",".join(bad)
                        else:
                            cache_key=(anchor,p.horizon_bars,tuple(roles))
                            if cache_key not in horizon_cache:
                                horizon_cache[cache_key]=_gr04_window(model,capability["price_snapshot_id"],row_id,anchor,
                                    request.trend_direction,p.horizon_bars,roles,spacing,checkpoint)
                            window,measured=horizon_cache[cache_key]
                            value,reason,source=_gr04_fact(p,window,measured,request.trend_direction)
                            source={**source,"window":window}
                elif not coherent:
                    reason="inspection_provider_incompatible";source=dict(resolution=resolution)
                else:
                    value,reason,source=_granular_utc_fact(p,selected,witness,unresolved,resolution,instance)
                fact=dict(measurement_key=key,selectors=p.to_dict(),known=value is not None,
                    value=_canonical(value),unavailable_reason=reason if value is None else None,source=_canonical(source))
            fact.update(inspection_only=is_extra,active_condition=not is_extra,anchor_ts_ms=status["anchor_ts_ms"],
                coherence_status="inspection_provider_incompatible" if is_extra and not coherent and p.domain in ("movement","duration","pullbacks") else "recorded" if not is_extra else "compatible",
                timing_withheld=False,metric_partition_reason="")
            if is_extra and fact["known"] and request.pre_event.chronological:
                base=samples.get(row_id)
                if base is None:
                    fact.update(timing_withheld=True,metric_partition_reason="base_not_in_partition")
                else:
                    source=fact["source"]
                    start=source.get("required_start_ms",source.get("ts_ms"))
                    end=source.get("required_end_ms",source.get("available_at_ms"))
                    intervals=(base["evidence_start_ms"],base["evidence_end_ms"],start,end)
                    diagnostic=deepcopy(base)
                    diagnostic.update(evidence_start_ms=None if any(v is None for v in intervals) else min(intervals),
                        evidence_end_ms=None if any(v is None for v in intervals) else max(intervals))
                    partition_sample(diagnostic,data,request,frozen.resolved_split)
                    fact.update(timing_withheld=diagnostic["partition"]!=base["partition"] or diagnostic["partition"]=="excluded",
                        metric_partition_reason=diagnostic["partition_reason"],diagnostic_partition=diagnostic["partition"])
            values[key]=fact
        output[row_id]=values
        if ri%32==0: _budget(output,memory_limit_bytes)
        progress("Resolving inspection-only measurements",ri+1,len(statuses))
    _budget(output,memory_limit_bytes);checkpoint()
    return _canonical(output)


def _gr06_simple_selectors(refinement):
    from .refinement_models import GranularPredicate
    values={}
    for domain,conditions,enabled,cohort in (
            ("movement",refinement.movement,refinement.movement_enabled,None),
            ("duration",refinement.duration,refinement.duration_enabled,None),
            ("pullbacks",refinement.pullbacks.conditions,refinement.pullbacks.enabled,refinement.pullbacks.cohort)):
        for c in conditions:
            if enabled and c.active:
                p=GranularPredicate(domain,c.field,c.unit,basis=refinement.basis,cohort=cohort,statistic=c.statistic)
                values[p.measurement_key]=p
    if refinement.preceding.active:
        for name in ("up","down","range","previous_direction","previous_family"):
            value=getattr(refinement.preceding,name)
            if value is not None:
                p=GranularPredicate("context",name,"boolean" if name in ("up","down","range") else "category",allowed=(value,))
                values[p.measurement_key]=p
    return values


def _gr06_simple_value(event,predicate,instance):
    from .trend_start_patterns import _refinement_provider
    saved=event.get("refinement",{})
    if saved.get("resolution")!="resolved" or saved.get("projection") is None:
        return None,"recorded_simple_projection_unavailable",dict(recorded_resolution=saved.get("resolution"))
    projection=deepcopy(saved["projection"])
    projection["measurements"]={saved["basis"]:projection["measurements"]}
    providers=saved.get("providers",[])
    witness=next((w for w in event["witnesses"] if any(all(_refinement_provider(w).get(k)==p.get(k)
        for k in ("artifact_id","report_sha256","episode_id")) for p in providers)),None)
    if witness is None: return None,"recorded_simple_provider_unavailable",dict(providers=providers)
    return _granular_utc_fact(predicate,projection,witness,"",_granular_empty_resolution("recorded_simple"),instance)


def _gr06_coherent(result,event,record,active,selected,witness,resolution,instance):
    from .trend_start_patterns import _refinement_provider
    if not active: return True
    utc={k:p for k,p in active.items() if p.domain in ("movement","duration","pullbacks","context")}
    if not utc: return True
    if selected is None or witness is None: return False
    provider=_refinement_provider(witness)
    if result.granular_definition is not None:
        recorded=record.get("source_resolution",{})
        candidates=recorded.get("compatible_providers",[])
        if not any(all(p.get(k)==provider.get(k) for k in ("artifact_id","report_sha256","episode_id")) for p in candidates):
            return False
        saved={r["measurement_key"]:r for r in record.get("scalar_ledger",[])}
        for key,p in utc.items():
            if key not in saved: return False
            value,reason,_=_granular_utc_fact(p,selected,witness,"",resolution,instance)
            actual=saved[key]["value"]
            if value is None:
                if saved[key]["known"] or reason!=saved[key]["unavailable_reason"]: return False
            elif p.unit in ("category","boolean","label"):
                if value!=actual: return False
            elif _granular_Decimal(str(value))!=_granular_Decimal(str(actual)): return False
    else:
        saved=event.get("refinement",{})
        if saved.get("resolution")!="resolved": return False
        providers=saved.get("providers",[])
        if not any(all(p.get(k)==provider.get(k) for k in ("artifact_id","report_sha256","episode_id")) for p in providers): return False
        projection=deepcopy(saved["projection"])
        if any(p.domain in ("movement","duration","pullbacks") for p in active.values()):
            projection["measurements"]={saved["basis"]:projection["measurements"]}
        for key,value in projection.items():
            if key=="measurements":
                if any(selected.get(key,{}).get(b)!=v for b,v in value.items()): return False
            elif selected.get(key)!=value: return False
    return True
