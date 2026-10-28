"""Read-only UTC event reconciliation and descriptive label-pattern counting."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
import json

import numpy as np
import pandas as pd

from leonardo.data import timeframe_duration_ms
from leonardo.financial_tools import UtcClassificationResult, UtcEpisodeMetricsResult
from leonardo.ohlcv.validation import _add_calendar_months
from .models import AnalysisResult
from .pattern_models import PatternCatalogue, PatternRefinement, PatternRequest, PatternStudy


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value):
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _checkpoint():
    pass


def _progress(*args):
    pass


def analysis_key(result):
    if not isinstance(result, AnalysisResult) or not result.columns:
        raise ValueError("complete Variation & Binning before selecting an event")
    ref = result.entry.reference
    return _hash((ref.database_id, ref.revision_id, ref.values_sha256, result.snapshot_read_ms,
                  [(c.request.source, c.request.measurement, c.request.policy.to_dict(),
                    c.profile.profile_id if c.profile is not None else None,
                    c.column.parameter_version) for c in result.columns]))


def _intervals(associations):
    return sorted(set((a["first_timestamp_ms"], a["last_timestamp_ms"]) for a in associations))


def _covered(timestamp, intervals):
    return any(first <= timestamp <= last for first, last in intervals)


def _swings(value):
    if isinstance(value, dict):
        if {"kind", "ts_ms", "available_at_ms", "value", "position"} <= set(value):
            yield value
        else:
            for child in value.values():
                yield from _swings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _swings(child)


def _frozen_facts(episode):
    return {k: v for k, v in episode.items() if k not in ("episode_id", "predecessor_episode_id", "status")}


def _witness_coverage(episode, report, associations, coverage, axis):
    required = {s["ts_ms"] for s in _swings(_frozen_facts(episode))}
    required.add(episode["decision_frontier_ms"])
    if any(t not in axis for t in required):
        return "pivot_outside_database", "unavailable", None
    if any(not _covered(t, coverage) for t in required):
        return "pivot_outside_classification_coverage", "unavailable", None
    closes = report["context"].get("bar_closed_at_ms")
    confirmed = episode["confirmed_at_ms"]
    if confirmed is not None and closes is not None:
        position = bisect_left(closes, confirmed)
        if position == len(closes):
            return "confirmation_beyond_covered_history", "verified_confirmation", None
        recognition = report["timestamps_ms"][position]
        basis = "verified_confirmation"
    else:
        recognition, basis = episode["decision_frontier_ms"], "structural_coverage_only"
    if recognition not in axis or not _covered(recognition, _intervals(associations)):
        return "recognition_outside_provider_coverage", basis, recognition
    return "", basis, recognition


def _episode_identities(report):
    return {e["episode_id"]: [e["segment_start_ms"], e["direction"], e["formation"][0]["ts_ms"]]
            for e in report["episodes"]}


def _semantic(value, identities):
    """Compare measurement meaning after alignment, keeping raw IDs in witnesses."""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == "position":
                continue
            if key == "pullback_id":
                result[key] = [identities[value["episode_id"]], value["launch"]["ts_ms"], value["launch"]["kind"]]
            elif key.endswith("episode_id"):
                result[key] = identities[child] if child is not None else None
            else:
                result[key] = _semantic(child, identities)
        return result
    if isinstance(value, list):
        return [_semantic(child, identities) for child in value]
    return value


def _recognition(report, frontier, available):
    closes = report["context"].get("bar_closed_at_ms")
    if available is not None and closes is not None:
        position = bisect_left(closes, available)
        return (report["timestamps_ms"][position] if position < len(closes) else None), "verified_availability"
    return frontier, "structural_coverage_only"


def _decision_coverage(view, frontier, available, axis):
    recognition, timing = _recognition(view["report"], frontier, available)
    reason = ("decision_outside_provider_coverage" if recognition not in axis
              or not _covered(recognition, view["intervals"]) else "")
    return {"reason": reason, "recognition_ms": recognition, "timing": timing}


def _source_segments(view):
    axis = view["report"]["timestamps_ms"]
    segments, swings = {}, {}
    for segment in view["metrics"]["evidence"]["segments"]:
        start = axis[segment["start_position"]]
        for i in range(segment["start_position"], segment["end_position"]+1):
            segments[axis[i]] = start
        for swing in segment["swings"]:
            swings[(swing["ts_ms"], swing["kind"])] = swing
    return segments, swings


def _prefix_agreement(carrier, donor, start, end, axis):
    new, old = carrier["report"], donor["report"]
    new_axis, old_axis = new["timestamps_ms"], old["timestamps_ms"]
    lo, hi = max(start, old_axis[0]), min(end, old_axis[-1])
    left = [t for t in new_axis if lo <= t <= hi]
    right = [t for t in old_axis if lo <= t <= hi]
    if left != right or (new["rule_version"], new["parameters"]) != (old["rule_version"], old["parameters"]):
        return "conflicting_source_prefix"
    new_closes, old_closes = new["context"].get("bar_closed_at_ms"), old["context"].get("bar_closed_at_ms")
    for timestamp in left:
        ni, oi = carrier["positions"][timestamp], donor["positions"][timestamp]
        if (any(carrier["metrics"]["evidence"]["bars"][ni][name] != donor["metrics"]["evidence"]["bars"][oi][name]
                for name in ("high", "low")) or carrier["segments"].get(timestamp) != donor["segments"].get(timestamp)):
            return "conflicting_source_prefix"
        if old_closes is not None and (new_closes is None or old_closes[oi] != new_closes[ni]):
            return "conflicting_source_prefix"
    frontier = old.get("as_of_ms") if old["status"] == "as_of" else old_closes[-1] if old_closes else None
    old_swings = {key: swing for key, swing in donor["swings"].items() if lo <= key[0] <= hi}
    new_swings = {key: swing for key, swing in carrier["swings"].items() if lo <= key[0] <= hi}
    for key, swing in old_swings.items():
        other = new_swings.get(key)
        if other is None or swing["value"] != other["value"]:
            return "conflicting_source_prefix"
        if swing["available_at_ms"] is not None and swing["available_at_ms"] != other["available_at_ms"]:
            return "conflicting_source_prefix"
    for key, swing in new_swings.items():
        previous = old_swings.get(key)
        if previous is not None and previous["available_at_ms"] == swing["available_at_ms"]:
            continue
        # Newly confirmed tail pivots can have old timestamps, but their new
        # knowledge must be supported after the donor's observation frontier.
        available = swing["available_at_ms"]
        if frontier is None or available is None or new_closes is None:
            return "unverifiable_prefix"
        recognition, _ = _recognition(new, swing["ts_ms"], available)
        if available <= frontier or recognition not in axis or not _covered(recognition, carrier["intervals"]):
            return "conflicting_source_prefix"
        evidence_start = old_axis[-1]
        supplied = [t for t in new_axis if evidence_start <= t <= recognition]
        imported = [t for t in axis if evidence_start <= t <= recognition]
        if supplied != imported:
            return "incomplete_ordered_timestamp_coverage"
    return ""


def _slice_coverage(view, providers, axis, start, end, checkpoint):
    source = view["report"]["timestamps_ms"]
    required = source[bisect_left(source, start):bisect_left(source, end)+1]
    stored = axis[bisect_left(axis, start):bisect_left(axis, end)+1]
    if not required or required[0] != start or required[-1] != end or required != stored:
        return "incomplete_ordered_timestamp_coverage"
    borrowed = [t for t in required if not _covered(t, view["intervals"])]
    if not borrowed:
        return ""
    donors = [p for p in providers if p is not view and any(_covered(t, p["intervals"]) for t in borrowed)]
    enriched = [p for p in donors if p["metrics"] is not None]
    for timestamp in borrowed:
        if not any(timestamp in p["positions"] and _covered(timestamp, p["intervals"]) for p in enriched):
            return "unverifiable_prefix" if any(_covered(timestamp, p["intervals"]) for p in donors) else "outside_classification_coverage"
    for donor in enriched:
        checkpoint()
        reason = _prefix_agreement(view, donor, start, end, axis)
        if reason:
            return reason
    return ""


def _basis_projection(metrics, basis):
    formation, current = metrics["formation_metrics"], metrics["episode_metrics"]
    if basis == "formation":
        return {"basis": basis, "status": "activated_formation", "formation": formation,
                "structural": {"duration": formation["duration"], "movement": formation["movement"]},
                "pullbacks": formation["pullbacks"], "pullback_summary": formation["pullback_summary"],
                "observation_limit": formation["interval_limit"]}
    structural = current["final_structural"] if basis == "completed" else current["observed_structural"]
    if structural is None or basis == "completed" and current["status"] != "ended":
        return None
    return {"basis": basis, "status": current["status"], "formation": formation,
        "structural": structural, "pullbacks": metrics["pullbacks"], "pullback_summary": current["pullback_summary"],
        **{name: current[name] for name in ("observation_limit", "endpoint_extension", "endpoint_extension_spacing",
            "observed_elapsed", "observation_spacing", "termination_trigger", "termination_frontier_ms",
            "termination_known_at_ms", "termination_frontier_delay_ms", "termination_recognition_delay_ms", "available_at_ms")}}


def _measurement_witness(witness, view, providers, axis, checkpoint):
    metrics = view["metrics"]
    if metrics is None:
        witness["metrics"] = None
        witness["measurement_projections"] = {}
        witness["context_projections"] = {}
        return
    episode = witness["episode"]
    measured = next(e for e in metrics["episodes"] if e["episode_id"] == episode["episode_id"])
    witness["metrics"] = measured
    identities = _episode_identities(view["report"])
    start = episode["formation"][0]["ts_ms"]
    projections = {}
    for basis in ("completed", "formation", "observed"):
        checkpoint()
        projection = _basis_projection(measured, basis)
        if projection is None:
            projections[basis] = {"reason": "completed_outcome_unavailable", "projection": None}
            continue
        end = projection["observation_limit"]["ts_ms"]
        reason = _slice_coverage(view, providers, axis, start, end, checkpoint)
        if basis == "formation":
            frontier, available = episode["decision_frontier_ms"], episode["confirmed_at_ms"]
        else:
            frontier = measured["episode_metrics"]["termination_frontier_ms"] or end
            available = measured["episode_metrics"]["available_at_ms"]
        decision = _decision_coverage(view, frontier, available, axis)
        if not reason:
            reason = decision["reason"]
        # A recognition row can be later than S-F/S-O; its exact slice is evidence,
        # not a fabricated timeframe-derived row.
        recognition = decision["recognition_ms"]
        if not reason and recognition is not None and recognition > end:
            reason = _slice_coverage(view, providers, axis, end, recognition, checkpoint)
        projections[basis] = {"reason": reason, "projection": _semantic(projection, identities),
                              "coverage": decision, "required_start_ms": start, "required_end_ms": end}
    witness["measurement_projections"] = projections
    preceding = measured["preceding_context"]
    bar = preceding["preceding_bar"]
    membership_reason = preceding["reason"] if bar is None else _slice_coverage(view, providers, axis, bar["ts_ms"], bar["ts_ms"], checkpoint)
    prior_id = preceding["previous_confirmed_episode_id"]
    prior = next((e for e in view["report"]["episodes"] if e["episode_id"] == prior_id), None)
    lineage_reason = ""
    if prior is not None:
        prior_end, _ = _recognition(view["report"], prior["decision_frontier_ms"], prior["confirmed_at_ms"])
        lineage_reason = ("previous_episode_evidence_unavailable" if prior_end is None else
            _slice_coverage(view, providers, axis, prior["formation"][0]["ts_ms"], prior_end, checkpoint))
    witness["context_projections"] = {
        "membership": {"reason": membership_reason, "projection": _semantic({"preceding_bar": bar,
            "preceding_membership": preceding["preceding_membership"], "interpretation": preceding["interpretation"]}, identities)},
        "lineage": {"reason": lineage_reason, "projection": _semantic({name: preceding[name] for name in
            ("previous_confirmed_episode_id", "previous_direction", "previous_formation_key")}, identities)}}


def _outcome(status="pass", reason=""):
    return {"status": status, "reason": reason}


def _bounded(value, condition, reason="measurement_unavailable"):
    if value is None:
        return _outcome("unavailable", reason)
    value = Decimal(str(value))
    if ((condition.minimum is not None and value < condition.minimum)
            or (condition.maximum is not None and value > condition.maximum)):
        return _outcome("mismatch", condition.field + "_outside_bounds")
    return _outcome()


def _group_outcome(outcomes):
    unavailable = [o["reason"] for o in outcomes if o["status"] == "unavailable"]
    mismatched = [o["reason"] for o in outcomes if o["status"] == "mismatch"]
    return {"status": "unavailable" if unavailable else "mismatch" if mismatched else "pass",
            "reason": "; ".join(unavailable + mismatched), "predicates": outcomes}


def _cohort_records(projection, cohort):
    formation = projection["formation"]
    if cohort == "formation_pending_at_boundary":
        return [p for p in formation["pullbacks"] if p["status"] == "pending" and p["phase"] == "formation"]
    boundary = formation["interval_limit"]["ts_ms"]
    predicates = {
        "all_observed": lambda p: True,
        "internal_recovered": lambda p: p["status"] == "recovered" and p["interval_membership"] == "inside_structural",
        "formation_recovered": lambda p: p["status"] == "recovered" and p["phase"] == "formation",
        "continuation_started": lambda p: p["launch"]["ts_ms"] >= boundary,
        "recovered_during_continuation": lambda p: p["status"] == "recovered" and p["recovery"]["ts_ms"] > boundary,
        "currently_pending": lambda p: p["status"] == "pending",
        "pending_internal_launch": lambda p: p["status"] == "pending" and p["launch_inside_structural"],
        "endpoint_context": lambda p: p["interval_membership"] != "inside_structural",
        "ended_unrecovered": lambda p: p["status"] == "ended_unrecovered",
        "interrupted": lambda p: p["status"] == "interrupted"}
    return [p for p in projection["pullbacks"] if predicates[cohort](p)]


def refine_event(event, refinement):
    """One predicate route for family refresh, both study cohorts and details."""
    if refinement is None:
        refinement = PatternRefinement()
    if not isinstance(refinement, PatternRefinement):
        raise TypeError("family selection requires a validated refinement")
    stages = {name: _outcome() for name in ("measurement_availability", "preceding_context", "movement", "duration", "pullbacks")}
    result = {"active": refinement.active, "eligible": event["eligible"], "basis": refinement.basis,
              "resolution": "disabled", "reasons": [], "stages": stages, "projection": None, "providers": []}
    if not refinement.active:
        return result
    membership = refinement.preceding.active and any(v is not None for v in
        (refinement.preceding.up, refinement.preceding.down, refinement.preceding.range))
    lineage = refinement.preceding.active and (refinement.preceding.previous_direction is not None
                                             or refinement.preceding.previous_family is not None)
    resolved = _refinement_resolve_saved(event, bases=(refinement.basis,) if refinement.measurements_active else (),
                                        membership=membership, lineage=lineage)
    result["rejected_witnesses"] = resolved["rejected_witnesses"]
    if resolved["resolution"] != "resolved":
        for name, active in (("measurement_availability", True), ("preceding_context", refinement.preceding.active),
                             ("movement", refinement.movement_active), ("duration", refinement.duration_active),
                             ("pullbacks", refinement.pullbacks.active)):
            if active:
                stages[name] = _outcome("unavailable", "; ".join(resolved["reasons"]))
        result.update(eligible=False, resolution=resolved["resolution"], reasons=resolved["reasons"], providers=resolved["providers"])
        if resolved["conflicting_providers"]:
            result["conflicting_providers"] = resolved["conflicting_providers"]
        return result
    selected, _, witness, context_reasons = resolved["candidates"][0]
    projection = dict(selected)
    if refinement.measurements_active:
        projection["measurements"] = selected["measurements"][refinement.basis]
    result.update(resolution="resolved", projection=projection, providers=resolved["providers"])
    if refinement.preceding.active:
        outcomes = [_outcome("unavailable", reason) for reason in context_reasons]
        if membership:
            for field, name, expected in (("up", "uptrend", refinement.preceding.up), ("down", "downtrend", refinement.preceding.down),
                                           ("range", "horizontal_range", refinement.preceding.range)):
                if expected is not None and not witness["context_projections"]["membership"]["reason"]:
                    actual, reason = _refinement_scalar(selected, witness, domain="context", field=field, unit="boolean")
                    if actual is not None:
                        outcomes.append(_outcome() if actual == expected else _outcome("mismatch", "preceding_"+name+"_mismatch"))
        if lineage:
            for field, expected, reason in (("previous_direction", refinement.preceding.previous_direction, "previous_direction_mismatch"),
                                             ("previous_family", refinement.preceding.previous_family, "previous_family_mismatch")):
                if expected is not None and not witness["context_projections"]["lineage"]["reason"]:
                    actual, _ = _refinement_scalar(selected, witness, domain="context", field=field, unit="category")
                    outcomes.append(_outcome() if actual == expected else _outcome("mismatch", reason))
        stages["preceding_context"] = _group_outcome(outcomes)
    for domain, active, conditions in (("movement", refinement.movement_active, refinement.movement),
                                       ("duration", refinement.duration_active, refinement.duration),
                                       ("pullbacks", refinement.pullbacks.active, refinement.pullbacks.conditions)):
        if active:
            outcomes = []
            for condition in conditions:
                if condition.active:
                    value, reason = _refinement_scalar(selected, witness, domain=domain, field=condition.field,
                        unit=condition.unit, basis=refinement.basis,
                        cohort=refinement.pullbacks.cohort if domain == "pullbacks" else None, statistic=condition.statistic)
                    outcomes.append(_bounded(value, condition, reason))
            stages[domain] = _group_outcome(outcomes)
    result["reasons"] = [stage["reason"] for stage in stages.values() if stage["status"] != "pass"]
    result["eligible"] = event["eligible"] and not result["reasons"]
    return result


def build_catalogue(result, bundle, timestamps, *, checkpoint=_checkpoint, progress=_progress):
    key = analysis_key(result)
    if result.entry.reference != bundle.reference:
        raise ValueError("UTC and binning database references disagree")
    ordered_axis = sorted(int(t) for t in timestamps)
    axis = set(ordered_axis)
    payload = bundle.to_dict()
    decoded, measured_reports = {}, {}
    for digest, analysis in payload["reports"].items():
        checkpoint()
        decoded[digest] = UtcClassificationResult.from_dict(analysis["utc_classification"]).to_dict() if analysis else None
        measured_reports[digest] = (UtcEpisodeMetricsResult.from_dict(analysis["utc_episode_metrics"],
            classification=decoded[digest]).to_dict() if analysis and "utc_episode_metrics" in analysis else None)
    groups = defaultdict(list)
    for association in payload["associations"]:
        groups[association["logical_artifact_id"]].append(association)
    instances = []
    for number, (identity, associations) in enumerate(sorted(groups.items())):
        checkpoint()
        progress("Reconciling copied UTC instances", number, len(groups))
        known = [a for a in associations if decoded[a["report_sha256"]] is not None]
        legacy = [a for a in associations if decoded[a["report_sha256"]] is None]
        coverage = _intervals(known)
        reports = {a["report_sha256"]: decoded[a["report_sha256"]] for a in known}
        configs = {_json((r["rule_version"], r["parameters"])) for r in reports.values()}
        if len(configs) > 1:
            raise ValueError(f"UTC instance {identity} has conflicting rules or configuration")
        providers = defaultdict(list)
        for a in known:
            providers[a["artifact_id"]].append(a)
        provider_views = {}
        for provider, selected in sorted(providers.items()):
            digests = {a["report_sha256"] for a in selected}
            if len(digests) != 1:
                raise ValueError("physical UTC provider has conflicting copied reports")
            digest = next(iter(digests))
            view = {"report": reports[digest], "metrics": measured_reports[digest], "intervals": _intervals(selected),
                    "positions": {t: i for i, t in enumerate(reports[digest]["timestamps_ms"])}}
            if view["metrics"] is not None:
                view["segments"], view["swings"] = _source_segments(view)
            provider_views[provider] = view
        events, segment_starts, control_associations = {}, set(), []
        inspected = 0
        for provider, selected in sorted(providers.items()):
            checkpoint()
            digests = {a["report_sha256"] for a in selected}
            if len(digests) != 1:
                raise ValueError("physical UTC provider has conflicting copied reports")
            digest = next(iter(digests))
            report = reports[digest]
            # Unknown clocks cannot establish an ordinary control population.
            control_eligible = (report["availability_status"] == "known"
                                and all(e["confirmed_at_ms"] is not None for e in report["episodes"]))
            provider_views[provider]["control_eligible"] = control_eligible
            if control_eligible:
                control_associations.extend(selected)
            continuations = defaultdict(list)
            for item in report["continuations"]:
                continuations[item["episode_id"]].append(item)
            for episode in report["episodes"]:
                checkpoint()
                inspected += 1
                anchor = episode["formation"][0]
                segment_starts.add(episode["segment_start_ms"])
                event_id = _hash((identity, report["rule_version"], report["parameters"],
                                  episode["segment_start_ms"], episode["direction"], anchor["ts_ms"]))
                facts = _frozen_facts(episode)
                reason, basis, recognition = _witness_coverage(episode, report, selected, coverage, axis)
                witness = {"artifact_id": provider, "report_sha256": digest,
                           "aliases": sorted({a["column_name"] for a in selected}),
                           "intervals": _intervals(selected), "episode": episode,
                           "continuations": continuations[episode["episode_id"]],
                           "exclusion": reason, "coverage_basis": basis, "recognition_ms": recognition}
                _measurement_witness(witness, provider_views[provider], list(provider_views.values()), ordered_axis, checkpoint)
                if event_id in events:
                    if events[event_id]["facts"] != facts:
                        raise ValueError(f"Conflicting frozen UTC formation facts at {anchor['ts_ms']} in {identity}")
                    events[event_id]["witnesses"].append(witness)
                else:
                    events[event_id] = {"event_id": event_id, "anchor_ts_ms": anchor["ts_ms"],
                        "event_kind": anchor["kind"], "direction": episode["direction"],
                        "family": episode["formation_key"], "origin": episode["origin"],
                        "facts": facts, "witnesses": [witness]}
        ordered = sorted(events.values(), key=lambda e: (e["anchor_ts_ms"], e["event_id"]))
        for event in ordered:
            usable = [w for w in event["witnesses"] if not w["exclusion"]]
            event["eligible"] = bool(usable)
            event["exclusion"] = "" if usable else "; ".join(sorted({w["exclusion"] for w in event["witnesses"]}))
            event["coverage_basis"] = (usable[0]["coverage_basis"] if usable else "unavailable")
        configuration = json.loads(next(iter(configs))) if configs else (None, {})
        instances.append({"instance_id": identity, "rule_version": configuration[0],
            "parameters": configuration[1], "aliases": sorted({a["column_name"] for a in associations}),
            "providers": sorted({a["artifact_id"] for a in associations}),
            "coverage": coverage, "control_coverage": _intervals(control_associations),
            "legacy_intervals": _intervals(legacy), "segment_starts": sorted(segment_starts),
            "events": ordered, "inspected_episodes": inspected, "duplicate_witnesses": inspected-len(ordered),
            "observation_evidence": [{"artifact_id": provider,
                "report_sha256": next(a["report_sha256"] for a in providers[provider]),
                "source_start_ms": view["report"]["timestamps_ms"][0], "intervals": view["intervals"],
                "known": view["report"]["availability_status"] == "known",
                "control_eligible": view["control_eligible"],
                "observed_at_ms": (view["report"].get("as_of_ms") if view["report"]["status"] == "as_of" else
                    (view["report"]["context"].get("bar_closed_at_ms") or [None])[-1])}
                for provider, view in sorted(provider_views.items())],
            "measurement_reports": {digest: {"classification": reports[digest], "metrics": measured_reports[digest]}
                                    for digest in sorted(reports) if measured_reports[digest] is not None},
            "status": "available" if known else "legacy_unavailable"})
    checkpoint()
    return PatternCatalogue(bundle.reference, key, _json({"status": bundle.status, "instances": instances}))


def _selected(event, kind, origin, start, end):
    return (event["event_kind"] == kind and (origin is None or event["origin"] == origin)
            and start <= event["anchor_ts_ms"] <= end)


def family_rows(instance, kind, origin=None, start=0, end=2**63-1, *, refinement=None):
    grouped = defaultdict(list)
    for event in instance["events"]:
        if _selected(event, kind, origin, start, end):
            grouped[event["family"]].append(event)
    rows = []
    for family, events in sorted(grouped.items()):
        eligible = [e for e in events if e["eligible"]]
        refined = [e for e in eligible if refine_event(e, refinement)["eligible"]]
        rows.append({"family": family, "starts": len(eligible), "excluded": len(events)-len(eligible),
            "original_starts": len(eligible), "refined_starts": len(refined), "refinement_excluded": len(eligible)-len(refined),
            "known_timing": sum(e["facts"]["confirmed_at_ms"] is not None for e in eligible),
            "unknown_timing": sum(e["facts"]["confirmed_at_ms"] is None for e in eligible),
            "origins": _json(dict(sorted(Counter(e["origin"] for e in eligible).items()))),
            "example": ", ".join(f"{s['kind']}{s['value']:g}" for s in events[0]["facts"]["formation"])})
    return rows


def _axis_and_columns(parent, timestamps, names, checkpoint=_checkpoint):
    columns = {c.request.source: c for c in parent.columns}
    if any(n not in columns for n in names):
        raise ValueError("study columns must belong to the completed binning run")
    data = {}
    for name in names:
        column = columns[name]
        frame = column.to_frame()
        if (len(frame) != len(timestamps) or frame.ts_ms.tolist() != list(timestamps)
                or not frame.ts_ms.is_unique):
            raise ValueError("binning and database timestamp axes disagree")
        label_field = "bin_label" if column.request.measurement == "directional_intensity" else "band"
        tokens, ready = [], []
        for index, row in enumerate(frame.itertuples(index=False)):
            if index % 256 == 0:
                checkpoint()
            label = getattr(row, label_field, None)
            zero = row.status == "zero_value"
            token = "Zero" if zero else str(label) if label is not None and not pd.isna(label) else None
            tokens.append(token)
            ready.append(token is not None and (zero or getattr(row, "support_status", None) == "ready"))
        data[name] = {"frame": frame, "tokens": tuple(tokens), "ready": tuple(ready),
                      "measurement": column.request.measurement,
                      "profile_id": column.profile.profile_id if column.profile is not None else None}
    return data


def _continuity(timestamps, timeframe, instance, checkpoint=_checkpoint):
    step = timeframe_duration_ms(timeframe)
    bad = np.zeros(len(timestamps), dtype="int64")
    for i in range(1, len(timestamps)):
        if i % 256 == 0:
            checkpoint()
        try:
            expected = (timestamps[i-1] + step if step is not None
                        else _add_calendar_months(timestamps[i-1], int(timeframe[:-1])))
        except (ValueError, OverflowError, OSError):
            expected = None
        if expected != timestamps[i]:
            bad[i] = 1
    segments = set(instance["segment_starts"])
    coverage = []
    for i, timestamp in enumerate(timestamps):
        if i % 256 == 0:
            checkpoint()
        coverage.append(_covered(timestamp, instance["coverage"]))
    for i in range(1, len(timestamps)):
        if i % 256 == 0:
            checkpoint()
        if timestamps[i] in segments or not coverage[i] or not coverage[i-1]:
            bad[i] = 1
    return np.cumsum(bad), tuple(coverage)


def _path_valid(data, left, right):
    lo, hi = sorted((left, right))
    return (0 <= lo <= hi < len(data["timestamps"]) and data["coverage"][lo] and data["coverage"][hi]
            and data["breaks"][lo] == data["breaks"][hi])


def _condition(data, anchor, terms, *, ordinary=False):
    values, ready = [], True
    for name, offset in terms:
        position = anchor + offset
        if not _path_valid(data, anchor, position):
            return None, False
        if ordinary:
            lo, hi = sorted((anchor, position))
            if data["control_uncovered"][hi+1] != data["control_uncovered"][lo]:
                return None, False
        column = data["columns"][name]
        token = column["tokens"][position]
        if token is None:
            return None, False
        values.append(token)
        ready = ready and column["ready"][position]
    return tuple(values), ready


def _counts(data, anchors, timing, terms, checkpoint, *, ordinary=False):
    counts, ready_counts = Counter(), Counter()
    denominator = ready_denominator = timing_withheld = 0
    for i, anchor in enumerate(anchors):
        if i % 256 == 0:
            checkpoint()
        values, ready = _condition(data, anchor, terms, ordinary=ordinary)
        if values is not None:
            counts[values] += 1
            denominator += 1
            timing_withheld += not timing[i]
            if ready and timing[i]:
                ready_counts[values] += 1
                ready_denominator += 1
    return counts, denominator, ready_counts, ready_denominator, timing_withheld


def _frequencies(data, groups, request, checkpoint):
    rows = []
    for family, anchors in sorted(groups.items()):
        for name in request.columns:
            column = data["columns"][name]
            first = request.pre_event.offsets[0] if request.pre_event is not None else -request.before
            for offset in range(first, request.after+1):
                checkpoint()
                counts, statuses = Counter(), Counter()
                missing = flagged = ready_count = 0
                for j, anchor in enumerate(anchors):
                    if j % 256 == 0:
                        checkpoint()
                    position = anchor+offset
                    if not 0 <= position < len(data["timestamps"]):
                        missing += 1
                        statuses["outside_history"] += 1
                        continue
                    flagged += not _path_valid(data, anchor, position)
                    token = column["tokens"][position]
                    statuses[str(column["frame"].iloc[position]["status"])] += 1
                    if token is None:
                        missing += 1
                    else:
                        counts[token] += 1
                        ready_count += column["ready"][position]
                assessable = len(anchors)-missing
                for label, count in sorted(counts.items()) or [(None, 0)]:
                    rows.append({"family": family, "column": name, "offset": offset, "label": label,
                        "matched": count, "assessable": assessable, "total": len(anchors), "unavailable": missing,
                        "frequency": count/assessable if assessable else None, "ready_observations": ready_count,
                        "gap_or_coverage_flags": flagged, "statuses": _json(dict(sorted(statuses.items())))})
    return rows


def _event_row(event, positions, timestamps):
    facts = event["facts"]
    anchor = event["anchor_ts_ms"]
    recognition = next((w["recognition_ms"] for w in event["witnesses"] if not w["exclusion"]), None)
    refinement = event["refinement"]
    return {"event_id": event["event_id"], "anchor_ts_ms": anchor, "event_kind": event["event_kind"],
        "role": "up_start" if event["event_kind"] == "T" else "down_start", "direction": event["direction"],
        "family": event["family"], "origin": event["origin"], "eligible": event["eligible"],
        "exclusion": event["exclusion"], "starting_available_at_ms": facts["formation"][0]["available_at_ms"],
        "confirming_pivot_ms": facts["formation"][-1]["ts_ms"], "confirmed_at_ms": facts["confirmed_at_ms"],
        "decision_frontier_ms": facts["decision_frontier_ms"], "coverage_basis": event["coverage_basis"],
        "confirmation_delay_ms": facts["confirmed_at_ms"]-anchor if facts["confirmed_at_ms"] is not None else None,
        "confirmation_delay_bars": positions[recognition]-positions[anchor] if recognition in positions and anchor in positions else None,
        "statuses": ", ".join(sorted({w["episode"]["status"] for w in event["witnesses"]})),
        "original_eligible": event["eligible"], "refinement_eligible": refinement["eligible"],
        "refinement_reasons": "; ".join(refinement["reasons"]), "measurement_basis": refinement["basis"],
        "measurement_resolution": refinement["resolution"], "metric_summary": _json(refinement["projection"]),
        "refinement": _json(refinement),
        "evidence": _json(event["witnesses"])}


def _refinement_funnel(events, cohort):
    rows = [{"cohort": cohort, "stage": "selected_starts", "incoming": len(events), "passed": len(events),
             "mismatched": 0, "unavailable": 0}]
    current = [e for e in events if e["eligible"]]
    rows.append({"cohort": cohort, "stage": "original_coverage_eligibility", "incoming": len(events),
                 "passed": len(current), "mismatched": 0, "unavailable": len(events)-len(current)})
    for stage in ("measurement_availability", "preceding_context", "movement", "duration", "pullbacks"):
        counts = Counter(e["refinement"]["stages"][stage]["status"] for e in current)
        rows.append({"cohort": cohort, "stage": stage, "incoming": len(current), "passed": counts["pass"],
                     "mismatched": counts["mismatch"], "unavailable": counts["unavailable"]})
        current = [e for e in current if e["refinement"]["stages"][stage]["status"] == "pass"]
    rows.append({"cohort": cohort, "stage": "included_starts", "incoming": len(current), "passed": len(current),
                 "mismatched": 0, "unavailable": 0})
    return rows


def run_study(parent, catalogue, request, timestamps, *, checkpoint=_checkpoint, progress=_progress):
    if not isinstance(request, PatternRequest):
        raise TypeError("study requires a validated event request")
    key = analysis_key(parent)
    if (request.reference != parent.entry.reference or catalogue.reference != request.reference
            or request.run_key != key or catalogue.run_key != key):
        raise ValueError("study and completed binning run identities disagree")
    instance = catalogue.instance(request.instance_id)
    if instance["status"] != "available":
        raise ValueError("copied UTC classification is unavailable for this instance")
    timestamps = tuple(int(t) for t in timestamps)
    if request.pre_event is not None:
        from .pre_event_patterns import run_pre_event
        return run_pre_event(parent, instance, request, timestamps, checkpoint, progress)
    positions = {t: i for i, t in enumerate(timestamps)}
    columns = _axis_and_columns(parent, timestamps, request.columns, checkpoint)
    breaks, coverage = _continuity(timestamps, parent.entry.market_id.timeframe, instance, checkpoint)
    events = [e for e in instance["events"] if _selected(e, request.event_kind, request.origin, request.start_ms, request.end_ms)]
    for event in instance["events"]:
        checkpoint()
        event["refinement"] = refine_event(event, request.refinement)
    target = [e for e in events if request.family is None or e["family"] == request.family]
    eligible = [e for e in target if e["refinement"]["eligible"]]
    groups = defaultdict(list)
    for event in eligible:
        groups[event["family"]].append(positions[event["anchor_ts_ms"]])
    targets = tuple(positions[e["anchor_ts_ms"]] for e in eligible)
    comparison_events = []
    comparison_candidates = []
    if request.family is not None and request.comparison == "other_families":
        comparison_candidates = [e for e in events if e["family"] != request.family]
        comparison_events = [e for e in comparison_candidates if e["refinement"]["eligible"]]
        controls = tuple(positions[e["anchor_ts_ms"]] for e in comparison_events)
    else:
        controls = ()
    data = {"timestamps": timestamps, "positions": positions, "columns": columns, "breaks": breaks,
            "coverage": coverage, "events": {e["event_id"]: e for e in instance["events"]},
            "measurement_reports": instance["measurement_reports"],
            "targets": eligible, "comparisons": comparison_events, "patterns": {}, "controls": controls}
    target_timing = tuple(e["coverage_basis"] == "verified_confirmation" for e in eligible)
    comparison_timing = tuple(e["coverage_basis"] == "verified_confirmation" for e in comparison_events)
    ordinary_controls = request.comparison == "non_start"
    if request.family is not None and request.comparison == "non_start":
        # Difference array excludes any control window intersecting either-direction start windows.
        blocked = np.zeros(len(timestamps)+1, dtype="int64")
        for event in instance["events"]:
            if event["eligible"]:
                anchor = positions[event["anchor_ts_ms"]]
                first, last = max(0, anchor-request.before-request.after), min(len(timestamps), anchor+request.after+request.before+1)
                blocked[first] += 1
                blocked[last] -= 1
        blocked = np.cumsum(blocked[:-1])
        ordinary = []
        control_uncovered = [0]
        for i, t in enumerate(timestamps):
            if i % 256 == 0:
                checkpoint()
            known = _covered(t, instance["control_coverage"])
            control_uncovered.append(control_uncovered[-1] + (not known))
            if request.start_ms <= t <= request.end_ms and not blocked[i] and known and coverage[i]:
                ordinary.append(i)
        controls = tuple(ordinary)
        data["controls"] = controls
        data["control_uncovered"] = tuple(control_uncovered)
        comparison_timing = (True,) * len(controls)
    data["ordinary_controls"] = ordinary_controls
    progress("Counting labels around selected starts")
    frequencies = _frequencies(data, groups, request, checkpoint)
    patterns = []
    if request.family is not None:
        templates = [("label", ((name, offset),)) for name in request.columns for offset in range(-request.before, request.after+1)]
        templates += [("sequence", tuple((name, offset) for offset in range(1-length, 1)))
                      for name in request.columns for length in request.sequence_lengths]
        templates += [("pair", ((left, 0), (right, 0))) for left, right in combinations(request.columns, 2)]
        for index, (kind, terms) in enumerate(templates):
            checkpoint()
            progress("Counting observed label patterns", index, len(templates))
            counts, total, ready_counts, ready_total, timing_withheld = _counts(data, targets, target_timing, terms, checkpoint)
            other, other_total, ready_other, ready_other_total, other_timing_withheld = _counts(
                data, controls, comparison_timing, terms, checkpoint, ordinary=ordinary_controls)
            for values, matched in sorted(counts.items()):
                compare_matched = other[values]
                frequency = matched/total
                baseline = compare_matched/other_total if other_total else None
                ratio = frequency/baseline if baseline else None
                rank_frequency = ready_counts[values]/ready_total if ready_total else None
                rank_baseline = ready_other[values]/ready_other_total if ready_other_total else None
                rank_ratio = rank_frequency/rank_baseline if rank_frequency is not None and rank_baseline else None
                rank = (ready_total >= request.min_target and ready_other_total >= request.min_comparison
                        and ready_counts[values] >= request.min_matches and rank_ratio is not None)
                timing_blocks_rank = ((not ready_total and timing_withheld)
                                      or (not ready_other_total and other_timing_withheld))
                pattern_id = _hash((kind, terms, values))
                data["patterns"][pattern_id] = (terms, values)
                patterns.append({"pattern_id": pattern_id, "kind": kind,
                    "condition": " AND ".join(f"{name}[{offset:+d}] = {value}" for (name, offset), value in zip(terms, values, strict=True)),
                    "matched": matched, "assessable": total, "excluded": len(targets)-total, "total": len(targets),
                    "frequency": frequency, "comparison_matched": compare_matched, "comparison_assessable": other_total,
                    "comparison_excluded": len(controls)-other_total, "comparison_total": len(controls),
                    "comparison_frequency": baseline, "difference_pp": 100*(frequency-baseline) if baseline is not None else None,
                    "frequency_ratio": ratio, "ready_matched": ready_counts[values], "ready_assessable": ready_total,
                    "comparison_ready_matched": ready_other[values], "comparison_ready_assessable": ready_other_total,
                    "timing_withheld": timing_withheld, "comparison_timing_withheld": other_timing_withheld,
                    "rank_ratio": rank_ratio, "rank_eligible": rank,
                    "rank_reason": "ready" if rank else "unverified_confirmation_timing" if timing_blocks_rank
                        else "zero_or_missing_comparison" if rank_ratio is None else "below_support_thresholds",
                    "conditions": _json([(name, offset, value) for (name, offset), value in zip(terms, values, strict=True)])})
    patterns.sort(key=lambda p: (not p["rank_eligible"], -(p["rank_ratio"] if p["rank_ratio"] is not None else -1), -p["matched"], p["pattern_id"]))
    overlap_groups = 0
    tail = None
    size = 0
    for anchor in sorted(targets):
        if tail is None or anchor-request.before > tail:
            overlap_groups += size > 1
            size = 1
        else:
            size += 1
        tail = max(tail or 0, anchor+request.after)
    overlap_groups += size > 1
    profile_description = [(n, columns[n]["measurement"], columns[n]["profile_id"]) for n in request.columns]
    context = _json({"database": parent.entry.name, "database_id": request.reference.database_id,
        "revision_id": request.reference.revision_id, "values_sha256": request.reference.values_sha256,
        "binning_run": key, "profiles": profile_description, "instance_id": request.instance_id,
        "utc_parameters": instance["parameters"], "rule_version": instance["rule_version"],
        "event_kind": request.event_kind, "role": request.role_label, "direction": request.trend_direction,
        "family": request.family or "All families (separate groups)", "origin": request.origin or "All origins",
        "start_ms": request.start_ms, "end_ms": request.end_ms, "before": request.before, "after": request.after,
        "comparison": request.comparison, "interpretation": "retrospective_full_history",
        "refinement": request.refinement.to_dict(), "refinement_summary": request.refinement.summary(),
        "refinement_interpretation": "Outcome-conditioned retrospective association; preceding memberships are retrospective and previous-episode lineage is scanner order, not known-at-start evidence",
        "snapshot_read_ms": parent.snapshot_read_ms})
    diagnostics = [("Interpretation", "Retrospective association; future-confirmed family and full-history profiles"),
        ("Inspected report episodes", instance["inspected_episodes"]), ("Duplicate witnesses", instance["duplicate_witnesses"]),
        ("Unique starts in UTC instance", len(instance["events"])), ("Selected starts", len(target)),
        ("Eligible target starts", len(eligible)), ("Excluded selected starts", len(target)-len(eligible)),
        ("Exclusion reasons", _json(dict(Counter(e["exclusion"] for e in target if not e["eligible"])))),
        ("Refinement", request.refinement.summary()),
        ("Refinement exclusion reasons", _json(dict(Counter(reason for e in target for reason in e["refinement"]["reasons"])))),
        ("Refinement interpretation", "Saved outcome conditioning and retrospective preceding context; ranking support is not known-at-start availability"),
        ("Known confirmation times", sum(e["facts"]["confirmed_at_ms"] is not None for e in eligible)),
        ("Unknown confirmation times", sum(e["facts"]["confirmed_at_ms"] is None for e in eligible)),
        ("Target starts withheld from ranking for unverified timing", len(target_timing)-sum(target_timing)),
        ("Comparison starts withheld from ranking for unverified timing", len(comparison_timing)-sum(comparison_timing)),
        ("Comparison observations", len(controls)), ("Examined candidates", len(patterns)),
        ("Ranking thresholds (target / comparison / matches)", f"{request.min_target} / {request.min_comparison} / {request.min_matches}"),
        ("Overlapping target-window groups", overlap_groups), ("Classification coverage", _json(instance["coverage"])),
        ("Legacy intervals", _json(instance["legacy_intervals"])), ("Ordinary control coverage", _json(instance["control_coverage"])),
        ("Pattern ranking", "Verified confirmation timing and ready-reference observations only; zero is explicit; structural-only starts remain descriptive; no significance or forecast probability"),
        ("Ordinary control assessability", "Known anchor coverage and both-direction window exclusion; required-term paths only; unused offsets do not exclude controls"),
        ("Overview", "Choose an exact family to compare patterns" if request.family is None else "Exact family selected"),
        ("UTC providers", _json(instance["providers"])), ("UTC aliases", _json(instance["aliases"])), ("Context", context)]
    checkpoint()
    tables = (("families", pd.DataFrame(family_rows(instance, request.event_kind, request.origin, request.start_ms, request.end_ms, refinement=request.refinement), dtype=object)),
        ("refinement_funnel", pd.DataFrame(_refinement_funnel(target, "target") + _refinement_funnel(comparison_candidates, "comparison"), dtype=object)),
        ("frequencies", pd.DataFrame(frequencies, dtype=object)), ("patterns", pd.DataFrame(patterns, dtype=object)),
        ("events", pd.DataFrame([_event_row(e, positions, timestamps) for e in target], dtype=object)),
        ("diagnostics", pd.DataFrame(diagnostics, columns=("field", "value"), dtype=object)))
    return PatternStudy(request, context, tables, data)


def event_evidence(data, event_id):
    if event_id.startswith("control:"):
        return {"event_id": event_id, "role": "ordinary_timestamp", "interpretation": "retrospective_control"}
    event = deepcopy(data["events"][event_id])
    event["copied_measurement_reports"] = {w["report_sha256"]: deepcopy(data["measurement_reports"][w["report_sha256"]])
        for w in event["witnesses"] if w["report_sha256"] in data["measurement_reports"]}
    return event


def event_window(data, request, event_id):
    if event_id.startswith("control:"):
        timestamp = int(event_id.split(":")[1])
    else:
        timestamp = data["events"][event_id]["anchor_ts_ms"]
    anchor = data["positions"].get(timestamp)
    rows = []
    first = request.pre_event.offsets[0] if request.pre_event is not None else -request.before
    for offset in range(first, request.after+1):
        position = None if anchor is None else anchor+offset
        for name, column in data["columns"].items():
            row = {"event_id": event_id, "anchor_ts_ms": timestamp, "column": name, "offset": offset,
                   "profile_id": column["profile_id"], "measurement": column["measurement"]}
            if request.pre_event is not None:
                row["use"] = "mined history" if offset in request.pre_event.offsets else "inspection only"
            if position is None or not 0 <= position < len(data["timestamps"]):
                row.update(ts_ms=None, elapsed_ms=None, status="outside_history", window_status="outside_history")
            else:
                row.update(column["frame"].iloc[position].to_dict())
                row.update(elapsed_ms=data["timestamps"][position]-timestamp,
                           window_status="continuous" if _path_valid(data, anchor, position) else "gap_segment_or_coverage")
            rows.append(row)
    return pd.DataFrame(rows, dtype=object)


def pattern_matches(data, pattern_id, cohort, *, checkpoint=_checkpoint):
    if data.get("pre_event"):
        from .pre_event_patterns import occurrences
        return occurrences(data, pattern_id, cohort, checkpoint)
    if cohort not in ("target", "comparison"):
        raise ValueError("select target or comparison matches")
    terms, values = data["patterns"][pattern_id]
    if cohort == "target":
        candidates = [(e["event_id"], data["positions"][e["anchor_ts_ms"]]) for e in data["targets"]]
    elif data["comparisons"]:
        candidates = [(e["event_id"], data["positions"][e["anchor_ts_ms"]]) for e in data["comparisons"]]
    else:
        candidates = [(f"control:{data['timestamps'][i]}", i) for i in data["controls"]]
    rows = []
    for index, (identity, anchor) in enumerate(candidates):
        if index % 256 == 0:
            checkpoint()
        ordinary = cohort == "comparison" and data["ordinary_controls"]
        actual, ready = _condition(data, anchor, terms, ordinary=ordinary)
        if actual == values:
            timing = ordinary or data["events"][identity]["coverage_basis"] == "verified_confirmation"
            rows.append({"event_id": identity, "anchor_ts_ms": data["timestamps"][anchor], "ready_reference": ready,
                         "verified_timing": timing, "ranking_support": ready and timing})
    checkpoint()
    return pd.DataFrame(rows, columns=("event_id", "anchor_ts_ms", "ready_reference", "verified_timing", "ranking_support"), dtype=object)


# Task 1079: shared saved-evidence resolution and scalar access.
def _refinement_provider(witness):
    return {"artifact_id": witness["artifact_id"], "report_sha256": witness["report_sha256"],
            "episode_id": witness["episode"]["episode_id"]}


def _refinement_formation_bridge(event, witness, bases, positions, checkpoint=_checkpoint):
    from .pre_event_cohorts import _refinement_completed_prefix_supported, _refinement_formation_witnesses
    if (positions is None or not {"formation", "completed"} <= set(bases) or not event["eligible"]
            or witness["exclusion"] != "recognition_outside_provider_coverage"
            or not _refinement_completed_prefix_supported(event, witness, positions, checkpoint=checkpoint)):
        return []
    formation = witness["measurement_projections"]["formation"]
    completed = witness["measurement_projections"]["completed"]
    coverage = formation.get("coverage", {})
    value, complete = formation.get("projection"), completed.get("projection")
    if (formation.get("reason") != "decision_outside_provider_coverage"
            or coverage.get("reason") != "decision_outside_provider_coverage"
            or coverage.get("timing") != "verified_availability" or value is None
            or value["formation"] != complete["formation"]):
        return []
    required = {formation.get("required_start_ms"), formation.get("required_end_ms"),
                coverage.get("recognition_ms"), witness["recognition_ms"], witness["episode"]["decision_frontier_ms"]}
    required.update(s["ts_ms"] for s in _swings(value))
    start = completed["required_start_ms"]
    end = max(completed["required_end_ms"], completed["coverage"]["recognition_ms"], complete["available_at_ms"])
    if any(t not in positions or not start <= t <= end for t in required):
        return []
    return [_refinement_provider(w) for w in _refinement_formation_witnesses(event, positions, checkpoint)
            if w.get("metrics") is not None]


def _refinement_resolve_saved(event, *, bases, membership, lineage, positions=None, checkpoint=_checkpoint):
    from .pattern_models import MEASUREMENT_BASES
    if (not isinstance(bases, tuple) or bases != tuple(b for b in MEASUREMENT_BASES if b in bases)
            or type(membership) is not bool or type(lineage) is not bool):
        raise ValueError("saved resolution requires canonical unique bases and boolean context flags")
    result = dict(resolution="disabled", selected=None, providers=[], rejected_witnesses=[],
                  conflicting_providers=[], candidates=[], reasons=[])
    if not bases and not membership and not lineage:
        return result
    candidates, rejected, conflicts = [], [], []
    for witness in event["witnesses"]:
        checkpoint()
        reasons, selected, context_reasons = [], {}, []
        if witness.get("metrics") is None:
            reasons.append("legacy_metrics_unavailable")
        else:
            if bases:
                selected["measurements"] = {}
                for basis in bases:
                    checkpoint()
                    projection = witness["measurement_projections"][basis]
                    bridge = (projection["reason"] == "decision_outside_provider_coverage" and basis == "formation"
                              and _refinement_formation_bridge(event, witness, bases, positions, checkpoint))
                    if projection["reason"] and not bridge:
                        reasons.append(projection["reason"])
                        if projection["reason"] == "conflicting_source_prefix" and not projection.get("coverage", {}).get("reason"):
                            conflicts.append(witness["artifact_id"])
                    selected["measurements"][basis] = projection["projection"]
            for domain, active in (("membership", membership), ("lineage", lineage)):
                if active:
                    projection = witness["context_projections"][domain]
                    if projection["reason"]:
                        context_reasons.append(projection["reason"])
                        if projection["reason"] == "conflicting_source_prefix" and not reasons:
                            conflicts.append(witness["artifact_id"])
                    selected[domain] = projection["projection"]
        provenance = {**_refinement_provider(witness), "reasons": reasons}
        if reasons:
            rejected.append(provenance)
        else:
            candidates.append((selected, provenance, witness, context_reasons))
    result.update(rejected_witnesses=rejected, candidates=candidates,
                  providers=[item[1] for item in candidates], conflicting_providers=sorted(set(conflicts)))
    if conflicts:
        result.update(resolution="unresolved_source_revision", reasons=["conflicting_source_prefix"])
        return result
    if not candidates:
        result.update(resolution="unavailable", reasons=sorted({r for item in rejected for r in item["reasons"]}) or ["metrics_unavailable"])
        return result
    fully_supported = [item for item in candidates if not item[3]]
    if fully_supported:
        rejected.extend({**item[1], "reasons": item[3]} for item in candidates if item[3])
        candidates = fully_supported
        result.update(candidates=candidates, providers=[item[1] for item in candidates])
    if len({_json(item[0]) for item in candidates}) != 1:
        result.update(resolution="ambiguous_saved_measurements", reasons=["ambiguous_saved_measurements"])
        return result
    result.update(resolution="resolved", selected=candidates[0][0])
    return result


def _refinement_scalar(selected, witness, *, domain, field, unit, basis=None, cohort=None, statistic=None):
    if domain == "context":
        part = "membership" if field in ("up", "down", "range") else "lineage"
        reason = witness["context_projections"][part]["reason"]
        if reason:
            return None, reason
        projection = selected[part]
        if part == "membership":
            flags = projection["preceding_membership"]
            value = None if flags is None else flags[{"up":"uptrend", "down":"downtrend", "range":"horizontal_range"}[field]]
            return value, "context_membership_unavailable" if value is None else ""
        value = projection["previous_direction" if field == "previous_direction" else "previous_formation_key"]
        return value or "NONE", ""
    projection = selected["measurements"][basis]
    if domain == "movement":
        movement = projection["structural"]["movement"]
        name = field + "_" + unit
        value = movement[name]
        reason = movement["unavailable_measurements"].get(name) or movement["percentage_reason"] or "movement_unavailable"
    elif domain == "duration":
        values = {"structural": projection["structural"]["duration"],
                  "endpoint_extension": projection.get("endpoint_extension"), "observed_elapsed": projection.get("observed_elapsed"),
                  "confirmation_delay": {"ms": projection["formation"]["confirmation_delay_ms"]}}
        value, reason = values[field][unit], "duration_unavailable"
    elif domain == "pullbacks":
        summary = projection["pullback_summary"][cohort]
        if field == "count":
            value, reason = summary["count"], "measurement_unavailable"
        else:
            members = _cohort_records(projection, cohort)
            stats = summary[field + "_" + unit]
            applicable = sum(p["status"] == "recovered" for p in members) if field == "recovered_duration" else summary["count"]
            if stats["eligible_count"] != applicable:
                return None, "partial_pullback_statistic_support"
            value, reason = stats[statistic], "empty_or_unavailable_pullback_statistic"
    else:
        raise ValueError("unsupported saved scalar domain")
    return value, reason if value is None else ""
