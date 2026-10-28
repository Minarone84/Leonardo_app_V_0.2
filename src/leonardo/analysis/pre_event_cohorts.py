"""Retrospective populations and evidence-aware chronological partitions."""
from __future__ import annotations

from collections import Counter


def _event_interval(event, request, instance, positions):
    refined = event["refinement"]
    resolved = _refinement_evidence_intervals(event, instance, positions,
        bases=(request.refinement.basis,) if request.refinement.measurements_active else (),
        context_active=request.refinement.preceding.active, providers=refined["providers"],
        restrict_providers=request.refinement.active, resolution=refined["resolution"])
    intervals = [(row["start_ms"], row["end_ms"]) for row in resolved["intervals"]]
    return min(intervals, key=lambda pair: (pair[1], pair[0])) if intervals else (None, None)


def _ordinary_interval(anchor, data, instance, request):
    from .trend_start_patterns import _covered
    first = anchor + request.pre_event.offsets[0]
    if first < 0:
        return None, None
    required = data["timestamps"][first:anchor+1]
    supported = [e for e in instance["observation_evidence"] if e["control_eligible"]
                 and e["known"] and e["observed_at_ms"] is not None
                 and all(_covered(t, e["intervals"]) for t in required)]
    if not supported:
        return None, None
    chosen = min(supported, key=lambda e: (e["observed_at_ms"], e["source_start_ms"], e["artifact_id"]))
    return chosen["source_start_ms"], chosen["observed_at_ms"]


def partition_sample(sample, data, request, split):
    """Both partitions require the complete feature AND cohort evidence interval."""
    spec = request.pre_event
    first, cutoff = sample["anchor"] + spec.offsets[0], sample["anchor"] - spec.lead
    sample.update(feature_start_ms=data["timestamps"][first] if first >= 0 else None,
                  cutoff_ms=data["timestamps"][cutoff] if cutoff >= 0 else None,
                  partition="discovery", partition_reason="")
    if not spec.chronological:
        return
    boundaries = (sample["feature_start_ms"], sample["cutoff_ms"], sample["evidence_start_ms"], sample["evidence_end_ms"])
    if split is None or any(v is None for v in boundaries):
        sample.update(partition="excluded", partition_reason="unknown_feature_or_evidence_boundary")
    elif max(boundaries) < split:
        sample["partition"] = "discovery"
    elif min(boundaries) >= split:
        sample["partition"] = "later"
    else:
        sample.update(partition="excluded", partition_reason="feature_or_evidence_crosses_split")


def build_cohorts(data, instance, request, checkpoint):
    from .trend_start_patterns import _covered, _selected, refine_event
    selected = [e for e in instance["events"] if _selected(e, request.event_kind, request.origin,
                                                         request.start_ms, request.end_ms)]
    for event in instance["events"]:
        checkpoint()
        event["refinement"] = refine_event(event, request.refinement)
    from .pattern_models import _gr05_scope_enabled, _gr05_resolve_scope
    scope = (_gr05_resolve_scope(request, request.refinement, _gr05_family_universe(instance["events"],
        event_kind=request.event_kind, start_ms=request.start_ms, end_ms=request.end_ms))
        if _gr05_scope_enabled(request, request.refinement) else None)
    if scope is not None:
        data["_gr05_scope"] = scope
    selected_families = set(scope["selected_families"]) if scope is not None else None
    target_selection = [e for e in selected if (e["family"] in selected_families if scope is not None
                                               else request.family is None or e["family"] == request.family)]
    samples, assignment = [], []
    seen = set()
    for event in selected:
        checkpoint()
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        ref = event["refinement"]
        same = (event["family"] in selected_families if scope is not None
                else request.family is None or event["family"] == request.family)
        cohort, reason = None, "not_selected_family"
        if request.comparison == "other_outcomes":
            if same:
                stages = ref["stages"]
                unavailable = not event["eligible"] or any(s["status"] == "unavailable" for s in stages.values())
                if unavailable:
                    reason = "unavailable_outcome_or_context"
                elif stages["preceding_context"]["status"] != "pass":
                    reason = "preceding_context_mismatch"
                else:
                    cohort = "target" if ref["eligible"] else "comparison"
                    reason = "passes_outcome_bounds" if cohort == "target" else "fails_outcome_bounds"
        elif ref["eligible"]:
            if same:
                cohort, reason = "target", "included"
            elif request.comparison == "other_families":
                cohort, reason = "comparison", "included"
        elif same or request.comparison == "other_families":
            reason = "; ".join(ref["reasons"]) or event["exclusion"] or "unavailable"
        assignment.append({"event_id": event["event_id"], "anchor_ts_ms": event["anchor_ts_ms"],
            "family": event["family"], "cohort": cohort or "excluded", "reason": reason,
            "failed_conditions": "; ".join(p["reason"] for s in ref["stages"].values()
                for p in s.get("predicates", [s]) if p["status"] == "mismatch")})
        if cohort is not None:
            start, end = _event_interval(event, request, instance, data["positions"])
            samples.append({"event_id": event["event_id"], "anchor": data["positions"][event["anchor_ts_ms"]],
                "cohort": cohort, "ordinary": False, "timing": event["coverage_basis"] == "verified_confirmation",
                "evidence_start_ms": start, "evidence_end_ms": end})
    ordinary = request.comparison == "non_start" and (request.family is not None or scope is not None)
    data["ordinary_controls"] = ordinary
    covered = [_covered(t, instance["control_coverage"]) for t in data["timestamps"]]
    cumulative = [0]
    for flag in covered:
        cumulative.append(cumulative[-1] + (not flag))
    data["control_uncovered"] = tuple(cumulative)
    excluded_starts = Counter()
    if ordinary:
        starts = {e["anchor_ts_ms"] for e in instance["events"]}
        excluded_starts.update(e["direction"] for e in instance["events"]
                               if request.start_ms <= e["anchor_ts_ms"] <= request.end_ms)
        for anchor, timestamp in enumerate(data["timestamps"]):
            if anchor % 128 == 0:
                checkpoint()
            if (request.start_ms <= timestamp <= request.end_ms and timestamp not in starts
                    and covered[anchor] and data["coverage"][anchor]):
                start, end = _ordinary_interval(anchor, data, instance, request)
                samples.append({"event_id": f"control:{timestamp}", "anchor": anchor, "cohort": "comparison",
                    "ordinary": True, "timing": True, "evidence_start_ms": start, "evidence_end_ms": end})
    samples.sort(key=lambda s: (s["cohort"] != "target", s["anchor"], s["event_id"]))
    axis = [t for t in data["timestamps"] if request.start_ms <= t <= request.end_ms]
    split = request.pre_event.split_ms
    if request.pre_event.chronological and split is None and len(axis) >= 2:
        split = axis[min(len(axis)-1, max(1, int(len(axis)*.7)))]
    for sample in samples:
        checkpoint()
        partition_sample(sample, data, request, split)
    lookup = {s["event_id"]: s for s in samples}
    for row in assignment:
        sample = lookup.get(row["event_id"])
        row.update(partition=sample["partition"] if sample else "excluded",
                   partition_reason=sample["partition_reason"] if sample else "not_in_cohort")
    data.update(samples=samples, targets=[data["events"][s["event_id"]] for s in samples if s["cohort"] == "target"],
                comparisons=[data["events"][s["event_id"]] for s in samples if s["cohort"] == "comparison" and not s["ordinary"]],
                controls=tuple(s["anchor"] for s in samples if s["cohort"] == "comparison"), split_ms=split)
    summary = []
    for cohort in ("target", "comparison"):
        members = [s for s in samples if s["cohort"] == cohort]
        for partition in ("discovery", "later", "excluded"):
            group = [s for s in members if s["partition"] == partition]
            summary.append({"cohort": cohort, "stage": partition, "incoming": len(members), "passed": len(group),
                "mismatched": 0, "unavailable": sum(s["partition"] == "excluded" for s in members),
                "details": "; ".join(sorted({s["partition_reason"] for s in group if s["partition_reason"]}))})
    return target_selection, assignment, summary, dict(excluded_starts)


def overlap_groups(samples, history, lead):
    groups, size, tail = 0, 0, None
    for anchor in sorted(s["anchor"] for s in samples):
        left, right = anchor-history-lead+1, anchor-lead
        if tail is None or left > tail:
            groups += size > 1
            size = 1
        else:
            size += 1
        tail = max(tail if tail is not None else right, right)
    return groups + (size > 1)


# Task 1079: shared completed-prefix proof and per-carrier evidence intervals.
def _refinement_formation_witnesses(event, positions, checkpoint=None):
    found = []
    for witness in event["witnesses"]:
        if checkpoint is not None:
            checkpoint()
        if (not witness["exclusion"] and witness["coverage_basis"] == "verified_confirmation"
                and witness["episode"]["confirmed_at_ms"] is not None and witness["recognition_ms"] in positions):
            found.append(witness)
    return found


def _refinement_completed_prefix_supported(event, witness, positions, *, checkpoint=None):
    from .trend_start_patterns import _swings
    formation = _refinement_formation_witnesses(event, positions, checkpoint)
    projection = witness["measurement_projections"].get("completed", {})
    coverage = projection.get("coverage", {})
    value = projection.get("projection") or {}
    if (not formation or projection.get("reason", True) or coverage.get("reason", True)
            or coverage.get("timing") != "verified_availability"
            or value.get("status") != "ended" or value.get("available_at_ms") is None):
        return False
    required = {event["anchor_ts_ms"], witness["episode"]["decision_frontier_ms"], witness["recognition_ms"],
                coverage.get("recognition_ms"), projection.get("required_start_ms"), projection.get("required_end_ms"),
                value.get("termination_frontier_ms")}
    required.update(s["ts_ms"] for s in _swings(event["facts"]))
    required.update(s["ts_ms"] for s in _swings(value))
    return all(t in positions for t in required)


def _refinement_evidence_intervals(event, instance, positions, *, bases, context_active, providers,
                                  restrict_providers, resolution, checkpoint=None):
    from .trend_start_patterns import _swings, _refinement_formation_bridge, _refinement_provider, _checkpoint
    check = checkpoint if checkpoint is not None else _checkpoint
    selected_providers = {(p["artifact_id"], p["report_sha256"]) for p in providers}
    intervals, rejected = [], []
    for witness in event["witnesses"]:
        check()
        provider = _refinement_provider(witness)
        selected = (witness["artifact_id"], witness["report_sha256"]) in selected_providers
        if restrict_providers and not selected:
            continue
        reason = ""
        if witness["exclusion"]:
            if not ("completed" in bases and resolution == "resolved" and event["eligible"] and selected
                    and witness["exclusion"] == "recognition_outside_provider_coverage"
                    and _refinement_completed_prefix_supported(event, witness, positions, checkpoint=checkpoint)):
                reason = witness["exclusion"]
        facts = witness["episode"]
        confirmed, recognition = facts["confirmed_at_ms"], witness["recognition_ms"]
        swings = list(_swings(event["facts"]))
        if not reason and (confirmed is None or recognition is None or witness["coverage_basis"] != "verified_confirmation"
                           or any(s["available_at_ms"] is None for s in swings)):
            reason = "formation_time_unavailable"
        if reason:
            rejected.append({**provider, "reason": reason})
            continue
        start = min([event["anchor_ts_ms"], *[s["ts_ms"] for s in swings]])
        end = max([confirmed, recognition, *[s["available_at_ms"] for s in swings]])
        bridged = False
        for basis in bases:
            check()
            projection = witness["measurement_projections"][basis]
            coverage = projection.get("coverage", {})
            value = projection.get("projection") or {}
            available = confirmed if basis == "formation" else value.get("available_at_ms")
            bridge = (basis == "formation" and projection["reason"]
                      and _refinement_formation_bridge(event, witness, bases, positions, check))
            if ((projection["reason"] and not bridge) or coverage.get("timing") != "verified_availability" or available is None):
                reason = projection["reason"] or "measurement_time_unavailable"
                break
            bridged = bridged or bool(bridge)
            start = min(start, projection["required_start_ms"])
            end = max(end, projection["required_end_ms"], coverage["recognition_ms"], available)
        if not reason and context_active:
            evidence = next((e for e in instance["observation_evidence"] if
                (e["artifact_id"], e["report_sha256"]) == (witness["artifact_id"], witness["report_sha256"])), None)
            if evidence is None or evidence["observed_at_ms"] is None:
                reason = "context_observation_time_unavailable"
            else:
                start = min(start, evidence["source_start_ms"])
                end = max(end, evidence["observed_at_ms"])
        if reason:
            rejected.append({**provider, "reason": reason})
        else:
            intervals.append({"artifact_id": provider["artifact_id"], "report_sha256": provider["report_sha256"],
                              "start_ms": start, "end_ms": end, "formation_bridge": bridged})
    return {"intervals": intervals, "rejected": rejected}


def _gr05_family_universe(events, *, event_kind, start_ms, end_ms):
    from .trend_start_patterns import _selected
    return tuple(sorted({e["family"] for e in events if _selected(e, event_kind, None, start_ms, end_ms)}))
