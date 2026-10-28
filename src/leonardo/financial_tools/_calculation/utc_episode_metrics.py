"""Pure descriptions of UTC evidence; this module makes no trend decisions."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from json import JSONEncoder
import math

from ..utc_classification_models import _exact, _integer, _key, _swing


_RULE = "utc-episode-metrics-1"
_MEMBERSHIPS = ("uptrend", "downtrend", "horizontal_range")


def _digest(value):
    return sha256(JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False).encode(value).encode("utf-8")).hexdigest()


def _known(values):
    values = tuple(values)
    return max(values) if values and all(v is not None for v in values) else None


def _finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _finite_measurements(record):
    """Overflow is an unavailable optional measurement, never a detector change."""
    missing = {}
    for key, value in record.items():
        if isinstance(value, float) and not math.isfinite(value):
            record[key] = None
            missing[key] = "nonfinite_result"
    record["unavailable_measurements"] = missing
    return record


def _capture_evidence(data, output, trace):
    from .common import _numeric_series
    highs = _numeric_series(data, trace.parameters.get("high", "high"), context="universal_trend_classifier")
    lows = _numeric_series(data, trace.parameters.get("low", "low"), context="universal_trend_classifier")
    flags = {name: output[name].tolist() for name in _MEMBERSHIPS}
    return {"segments": deepcopy(trace.measurement_segments), "bars": [
        {"high": _finite(high), "low": _finite(low),
         **{name: bool(flags[name][i]) for name in _MEMBERSHIPS}}
        for i, (high, low) in enumerate(zip(highs, lows))]}


def _availability(core):
    context, axis = core["context"], core["timestamps_ms"]
    if context["canonical_window"] is not None:
        half = context["canonical_window"] // 2
        return [context["bar_closed_at_ms"][i + half] if i + half < len(axis) else None
                for i in range(len(axis))]
    return context["swing_available_at_ms"] or [None] * len(axis)


def _validate_evidence(core, evidence):
    _exact(evidence, ("segments", "bars"), "UTC measurement evidence")
    axis, availability = core["timestamps_ms"], _availability(core)
    if not isinstance(evidence["bars"], list) or len(evidence["bars"]) != len(axis):
        raise ValueError("UTC measurement bars disagree with timeline")
    for bar in evidence["bars"]:
        _exact(bar, ("high", "low", *_MEMBERSHIPS), "UTC measurement bar")
        for name in ("high", "low"):
            value = bar[name]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError("UTC measurement prices must be finite or missing")
        if any(type(bar[name]) is not bool for name in _MEMBERSHIPS):
            raise ValueError("UTC membership evidence must be boolean")
    if not isinstance(evidence["segments"], list):
        raise ValueError("UTC measurement segments must be a list")
    previous_end = -1
    segments = {}
    for segment in evidence["segments"]:
        _exact(segment, ("start_position", "end_position", "swings"), "UTC measurement segment")
        start = _integer(segment["start_position"], "segment start", nonnegative=True)
        end = _integer(segment["end_position"], "segment end", nonnegative=True)
        if not previous_end < start <= end < len(axis):
            raise ValueError("UTC measurement segments overlap or exceed timeline")
        previous_end = end
        if any(evidence["bars"][i][name] is None for i in range(start, end+1) for name in ("high", "low")):
            raise ValueError("UTC valid segment contains missing price evidence")
        if not isinstance(segment["swings"], list) or not segment["swings"]:
            raise ValueError("UTC measurement segment must retain its swings")
        prior = start - 1
        for swing in segment["swings"]:
            _swing(swing, axis, availability)
            if core["status"] == "as_of" and (swing["available_at_ms"] is None
                    or swing["available_at_ms"] > core["as_of_ms"]):
                raise ValueError("UTC measurement swing is unavailable at the as-of cutoff")
            if not prior < swing["position"] <= end:
                raise ValueError("UTC measurement swings must be unique and ordered in segment")
            prior = swing["position"]
        segments[axis[start]] = segment
    for episode in core["episodes"]:
        segment = segments.get(episode["segment_start_ms"])
        if segment is None:
            raise ValueError("UTC episode lacks its measurement segment")
        lookup = {s["position"]: s for s in segment["swings"]}
        formation = episode["formation"]
        if [s for s in segment["swings"] if formation[0]["position"] <= s["position"] <= formation[-1]["position"]] != formation:
            raise ValueError("UTC measurement formation evidence differs from classification")
        witnesses = list(formation)
        for restart in episode["restart_chain"]:
            witnesses.extend((restart["trigger"], restart["previous_anchor"]))
        if episode["shared_pivot"] is not None:
            witnesses.append(episode["shared_pivot"])
        if ((episode["status"] == "open" and segment["end_position"] != len(axis)-1)
                or (episode["status"] == "interrupted" and segment["end_position"] >= len(axis)-1)):
            raise ValueError("UTC episode status disagrees with measurement segment tail")
        for event in core["continuations"]:
            if event["episode_id"] == episode["episode_id"]:
                witnesses.append(event["swing"])
                witnesses.extend(s for state in (event["before"], event["after"]) for s in state.values() if s is not None)
                if event["decision_frontier_ms"] > axis[segment["end_position"]]:
                    raise ValueError("UTC event exceeds measurement segment")
        if any(lookup.get(s["position"]) != s for s in witnesses):
            raise ValueError("UTC measurement event evidence differs from classification")
    return segments


def _coordinate(axis, pos):
    return {"position": pos, "ts_ms": axis[pos]}


def _duration(axis, start, end):
    return {"bars": end - start, "ms": axis[end] - axis[start]}


def _spacing(axis, start, end):
    deltas = [axis[i] - axis[i-1] for i in range(start+1, end+1)]
    return {"row_count": end-start+1, "min_delta_ms": min(deltas) if deltas else None,
            "max_delta_ms": max(deltas) if deltas else None,
            "uniform": len(set(deltas)) == 1 if deltas else None}


def _movement(core, evidence, swings, start, end, direction, required):
    axis = core["timestamps_ms"]
    left, right = start["position"], end["position"]
    pivots = [s for s in swings if left <= s["position"] <= right]
    high = max(pivots, key=lambda s: s["value"])
    low = min(pivots, key=lambda s: s["value"])
    reference = start["value"]
    pct = lambda value: (value / reference) * 100 if reference > 0 else None
    signed = end["value"] - reference
    favorable = max(0., high["value"]-reference if direction == 1 else reference-low["value"])
    adverse = max(0., reference-low["value"] if direction == 1 else high["value"]-reference)
    pivot_known = _known([*required, *(s["available_at_ms"] for s in pivots)])
    envelope = {}
    for name, select in (("high", max), ("low", min)):
        values = [(i, evidence["bars"][i][name]) for i in range(left, right+1)]
        if any(v is None for _, v in values):
            envelope[name] = None
        else:
            pos, value = select(values, key=lambda item: item[1])
            envelope[name] = {**_coordinate(axis, pos), "value": value, "source_column": core["parameters"].get(name, name)}
    width = (envelope["high"]["value"]-envelope["low"]["value"]
             if all(envelope.values()) else None)
    closes = core["context"]["bar_closed_at_ms"]
    envelope_known = _known([*required, *(closes[left:right+1] if closes is not None else [None])])
    return _finite_measurements({
        "start": deepcopy(start), "endpoint": deepcopy(end),
        "signed_move_points": signed, "directional_move_points": direction*signed,
        "signed_move_pct": 100*(end["value"]/reference-1) if reference > 0 else None,
        "directional_move_pct": direction*100*(end["value"]/reference-1) if reference > 0 else None,
        "percentage_reason": None if reference > 0 else "nonpositive_reference_price",
        "pivot_high": deepcopy(high), "pivot_low": deepcopy(low),
        "pivot_span_points": high["value"]-low["value"], "pivot_span_pct": pct(high["value"]-low["value"]),
        "pivot_favorable_points": favorable, "pivot_favorable_pct": pct(favorable),
        "pivot_adverse_points": adverse, "pivot_adverse_pct": pct(adverse),
        "bar_envelope_high": envelope["high"], "bar_envelope_low": envelope["low"],
        "bar_envelope_span_points": width, "bar_envelope_span_pct": pct(width) if width is not None else None,
        "bar_envelope_reason": None if width is not None else "unavailable_price",
        "pivot_available_at_ms": pivot_known, "bar_envelope_available_at_ms": envelope_known,
        "available_at_ms": _known([pivot_known, envelope_known]),
        "spacing": _spacing(axis, left, right),
    })


def _pullbacks(core, episode, swings, endpoint, observation, *, formation_only=False):
    axis = core["timestamps_ms"]
    start, formation_end = episode["formation"][0], episode["formation"][-1]
    sign = 1 if episode["direction"] == "UP" else -1
    sequence = [s for s in swings if start["position"] <= s["position"] <= observation]
    events = [e for e in core["continuations"] if e["episode_id"] == episode["episode_id"]]
    result, active = [], None
    watermark = sequence[0]

    def known_through(pivot):
        times = [episode["confirmed_at_ms"]]
        times.extend(s["available_at_ms"] for s in sequence if s["position"] <= pivot["position"])
        if not formation_only:
            times.extend(e["known_at_ms"] for e in events if e["swing"]["position"] <= pivot["position"])
        return _known(times)

    def finish(item, recovery):
        launch, worst, extent = item["launch"], item["worst"], item["extent"]
        depth = sign*(launch["value"]-worst["value"])
        prior_gain = sign*(launch["value"]-start["value"])
        status = ("recovered" if recovery is not None else "pending" if formation_only or episode["status"] == "open"
                  else "ended_unrecovered" if episode["status"] == "ended" else "interrupted")
        phase = ("formation" if extent["position"] <= formation_end["position"] else
                 "continuation" if launch["position"] >= formation_end["position"] else "crosses_formation_boundary")
        membership = ("inside_structural" if extent["position"] <= endpoint["position"] else
                      "crosses_endpoint" if launch["position"] <= endpoint["position"] else "after_endpoint")
        return _finite_measurements({
            "pullback_id": _key((episode["episode_id"], _RULE, launch["position"], launch["kind"])),
            "episode_id": episode["episode_id"], "launch": deepcopy(launch),
            "first_adverse": deepcopy(item["first"]), "worst": deepcopy(worst),
            "recovery": deepcopy(recovery), "pivot_extent_end": deepcopy(extent),
            "depth_points": depth, "depth_pct": (depth/launch["value"])*100 if launch["value"] > 0 else None,
            "percentage_reason": None if launch["value"] > 0 else "nonpositive_reference_price",
            "retracement_of_prior_gain_pct": (depth/prior_gain)*100 if prior_gain > 0 and math.isfinite(prior_gain) else None,
            "retracement_reason": ("nonfinite_prior_gain" if not math.isfinite(prior_gain) else None if prior_gain > 0 else "nonpositive_prior_gain"),
            "descent_duration": _duration(axis, launch["position"], worst["position"]),
            "recovery_duration": _duration(axis, worst["position"], recovery["position"]) if recovery else None,
            "total_duration": _duration(axis, launch["position"], recovery["position"]) if recovery else None,
            "observed_duration": _duration(axis, launch["position"], observation) if recovery is None else None,
            "descent_spacing": _spacing(axis, launch["position"], worst["position"]),
            "recovery_spacing": _spacing(axis, worst["position"], recovery["position"]) if recovery else None,
            "total_spacing": _spacing(axis, launch["position"], recovery["position"]) if recovery else None,
            "observed_spacing": _spacing(axis, launch["position"], observation) if recovery is None else None,
            "adverse_leg_count": item["legs"], "status": status, "phase": phase,
            "interval_membership": membership, "launch_inside_structural": launch["position"] <= endpoint["position"],
            "opened_at_ms": known_through(item["first"]), "worst_known_at_ms": known_through(worst),
            "recovered_at_ms": known_through(recovery) if recovery else None,
        })

    previous = watermark
    for pivot in sequence[1:]:
        if active is None:
            if sign*(pivot["value"]-watermark["value"]) > 0:
                watermark = pivot
            elif sign*(pivot["value"]-watermark["value"]) < 0:
                active = {"launch": watermark, "first": pivot, "worst": pivot, "extent": pivot, "legs": 1}
        else:
            active["extent"] = pivot
            if sign*(pivot["value"]-previous["value"]) < 0:
                active["legs"] += 1
            if sign*(pivot["value"]-active["worst"]["value"]) < 0:
                active["worst"] = pivot
            if sign*(pivot["value"]-active["launch"]["value"]) >= 0:
                result.append(finish(active, pivot))
                watermark, active = pivot, None
        previous = pivot
    if active is not None:
        result.append(finish(active, None))
    return result


def _aggregate(records):
    def stats(values):
        values = [v for v in values if v is not None]
        return {"eligible_count": len(values), "mean": math.fsum(v/len(values) for v in values) if values else None,
                "maximum": max(values) if values else None}
    return {"count": len(records), "depth_points": stats([r["depth_points"] for r in records]),
            "depth_pct": stats([r["depth_pct"] for r in records]),
            **{"recovered_duration_"+unit: stats([r["total_duration"][unit] for r in records if r["status"] == "recovered"])
               for unit in ("bars", "ms")}}


def _cohorts(records, formation_end):
    return {name: _aggregate([r for r in records if predicate(r)]) for name, predicate in {
        "all_observed": lambda r: True,
        "internal_recovered": lambda r: r["status"] == "recovered" and r["interval_membership"] == "inside_structural",
        "formation_recovered": lambda r: r["status"] == "recovered" and r["phase"] == "formation",
        "formation_pending_at_boundary": lambda r: r["status"] == "pending" and r["phase"] == "formation",
        "continuation_started": lambda r: r["launch"]["position"] >= formation_end,
        "recovered_during_continuation": lambda r: r["status"] == "recovered" and r["recovery"]["position"] > formation_end,
        "currently_pending": lambda r: r["status"] == "pending",
        "pending_internal_launch": lambda r: r["status"] == "pending" and r["launch_inside_structural"],
        "endpoint_context": lambda r: r["interval_membership"] != "inside_structural",
        "ended_unrecovered": lambda r: r["status"] == "ended_unrecovered",
        "interrupted": lambda r: r["status"] == "interrupted",
    }.items()}


def _build_metrics(core, evidence):
    segments = _validate_evidence(core, evidence)
    axis = core["timestamps_ms"]
    episodes, previous = [], {}
    for episode in core["episodes"]:
        segment = segments[episode["segment_start_ms"]]
        swings = segment["swings"]
        start, formation_end = episode["formation"][0], episode["formation"][-1]
        sign = 1 if episode["direction"] == "UP" else -1
        events = [e for e in core["continuations"] if e["episode_id"] == episode["episode_id"]]
        termination = next((e for e in events if e["kind"] == "termination"), None)
        if (episode["status"] == "ended") != (termination is not None):
            raise ValueError("UTC structural completion requires its termination evidence")
        endpoint = (termination["before"]["endpoint"] if termination else
                    events[-1]["after"]["endpoint"] if events else formation_end)
        if endpoint is None or endpoint["position"] < formation_end["position"]:
            raise ValueError("UTC measurement endpoint precedes formation")
        observation = axis.index(termination["decision_frontier_ms"]) if termination else segment["end_position"]
        required = [episode["confirmed_at_ms"], *(e["known_at_ms"] for e in events)]
        formation_pulls = _pullbacks(core, episode, swings, formation_end, formation_end["position"], formation_only=True)
        pulls = _pullbacks(core, episode, swings, endpoint, observation)
        formation_metrics = {
            "interval_limit": deepcopy(formation_end), "decision_frontier_ms": episode["decision_frontier_ms"],
            "completeness": "activated_formation", "confirmed_at_ms": episode["confirmed_at_ms"],
            "confirmation_delay_ms": episode["confirmed_at_ms"]-start["ts_ms"] if episode["confirmed_at_ms"] is not None else None,
            "duration": _duration(axis, start["position"], formation_end["position"]),
            "movement": _movement(core, evidence, swings, start, formation_end, sign, [episode["confirmed_at_ms"]]),
            "pullbacks": formation_pulls, "pullback_summary": _cohorts(formation_pulls, formation_end["position"]),
        }
        structural = {"duration": _duration(axis, start["position"], endpoint["position"]),
                      "movement": _movement(core, evidence, swings, start, endpoint, sign, required)}
        preceding_pos = start["position"]-1
        prior = previous.get(episode["segment_start_ms"])
        preceding = {
            "origin": episode["origin"], "scanner_predecessor_episode_id": episode["predecessor_episode_id"],
            "previous_confirmed_episode_id": prior["episode_id"] if prior else None,
            "previous_direction": prior["direction"] if prior else None,
            "previous_formation_key": prior["formation_key"] if prior else None,
            "preceding_bar": _coordinate(axis, preceding_pos) if preceding_pos >= segment["start_position"] else None,
            "preceding_membership": {k: evidence["bars"][preceding_pos][k] for k in _MEMBERSHIPS} if preceding_pos >= segment["start_position"] else None,
            "reason": None if preceding_pos >= segment["start_position"] else "unavailable_at_segment_start",
            "interpretation": "retrospective", "available_at_ms": None,
            "configuration": {k: core["parameters"][k] for k in ("trend_fractal_window", "range_fractal_window", "peak_column", "trough_column")},
        }
        current = {
            "status": episode["status"], "observation_limit": _coordinate(axis, observation),
            "observed_structural": structural,
            "final_structural": deepcopy(structural) if episode["status"] == "ended" else None,
            "endpoint_extension": _duration(axis, formation_end["position"], endpoint["position"]),
            "endpoint_extension_spacing": _spacing(axis, formation_end["position"], endpoint["position"]),
            "observed_elapsed": _duration(axis, start["position"], observation),
            "observation_spacing": _spacing(axis, start["position"], observation),
            "termination_trigger": deepcopy(termination["swing"]) if termination else None,
            "termination_frontier_ms": termination["decision_frontier_ms"] if termination else None,
            "termination_known_at_ms": termination["known_at_ms"] if termination else None,
            "termination_frontier_delay_ms": termination["decision_frontier_ms"]-endpoint["ts_ms"] if termination else None,
            "termination_recognition_delay_ms": termination["known_at_ms"]-endpoint["ts_ms"] if termination and termination["known_at_ms"] is not None else None,
            "available_at_ms": _known([*required, core["context"]["bar_closed_at_ms"][observation] if core["context"]["bar_closed_at_ms"] is not None else None,
                                       *(s["available_at_ms"] for s in swings if start["position"] <= s["position"] <= observation)]),
            "pullback_summary": _cohorts(pulls, formation_end["position"]),
        }
        # The pending-at-F cohort always refers to the frozen snapshot, including after recovery.
        current["pullback_summary"]["formation_pending_at_boundary"] = deepcopy(formation_metrics["pullback_summary"]["formation_pending_at_boundary"])
        episodes.append({"episode_id": episode["episode_id"], "direction": episode["direction"],
                         "formation_key": episode["formation_key"], "formation_metrics": formation_metrics,
                         "episode_metrics": current, "preceding_context": preceding, "pullbacks": pulls})
        previous[episode["segment_start_ms"]] = episode
    context_at_cutoff = None
    if core["status"] == "as_of":
        context_at_cutoff = {"as_of_ms": core["as_of_ms"],
                             "last_available_bar": _coordinate(axis, len(axis)-1) if axis else None,
                             "published_membership": {k: evidence["bars"][-1][k] for k in _MEMBERSHIPS} if axis else None,
                             "open_confirmed_episode_ids": [e["episode_id"] for e in core["episodes"] if e["status"] == "open"]}
    return {"schema_version": "1.0", "measurement_rule_version": _RULE,
            "classification_sha256": _digest(core), "input_key": core["input_key"],
            "parameters": deepcopy(core["parameters"]), "timestamps_ms": list(axis),
            "identity_scope": core["identity_scope"], "observation_mode": core["status"], "as_of_ms": core["as_of_ms"],
            "observation_limit": _coordinate(axis, len(axis)-1) if axis else None,
            "evidence": deepcopy(evidence), "episodes": episodes, "context_at_cutoff": context_at_cutoff}
