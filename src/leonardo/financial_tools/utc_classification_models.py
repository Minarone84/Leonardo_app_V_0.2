"""Versioned, nonvisual UTC evidence. No storage or chart ownership."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import math

import pandas as pd


def _plain(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("UTC mapping keys must be strings")
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("UTC evidence must contain finite JSON-compatible values")


def _key(value):
    def ordered(item):
        if isinstance(item, Mapping):
            return tuple((k, ordered(v)) for k, v in sorted(item.items()))
        if isinstance(item, (tuple, list)):
            return tuple(ordered(v) for v in item)
        return item
    return sha256(repr(ordered(_plain(value))).encode("utf-8")).hexdigest()


def _integer(value, name, *, nonnegative=False):
    lower = 0 if nonnegative else -(2**63)
    if type(value) is not int or not lower <= value <= 2**63 - 1:
        raise ValueError(f"{name} must be an int64 in the supported range")
    return value


def _exact(value, keys, name):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError(f"{name} fields are invalid")
    return value


@dataclass(frozen=True, slots=True)
class UtcClassificationContext:
    stream_id: str | None = None
    input_revision: str | None = None
    dependency_ids: tuple[str, ...] = ()
    bar_closed_at_ms: tuple[int, ...] | None = None
    swing_available_at_ms: tuple[int | None, ...] | None = None
    canonical_window: int | None = None

    def __post_init__(self):
        for name in ("stream_id", "input_revision"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be nonempty or null")
        ids = tuple(self.dependency_ids)
        if any(not isinstance(v, str) or not v for v in ids) or len(ids) != len(set(ids)):
            raise ValueError("dependency_ids must be unique strings")
        object.__setattr__(self, "dependency_ids", ids)
        for name in ("bar_closed_at_ms", "swing_available_at_ms"):
            value = getattr(self, name)
            if value is not None:
                value = tuple(value)
                for timestamp in value:
                    if timestamp is not None or name == "bar_closed_at_ms":
                        _integer(timestamp, name)
                if name == "bar_closed_at_ms" and any(a >= b for a, b in zip(value, value[1:])):
                    raise ValueError("bar close times must strictly increase")
                object.__setattr__(self, name, value)
        if self.canonical_window is not None:
            if type(self.canonical_window) is not int or self.canonical_window not in (3, 5, 7, 9, 11):
                raise ValueError("canonical_window must be a supported P/T window")
            if self.bar_closed_at_ms is None or self.swing_available_at_ms is not None:
                raise ValueError("canonical availability requires bar close times and no custom availability")
        if self.swing_available_at_ms is not None and self.bar_closed_at_ms is None:
            raise ValueError("custom swing availability requires explicit bar close times")

    def to_dict(self):
        return _plain({name: getattr(self, name) for name in self.__dataclass_fields__})

    @classmethod
    def from_dict(cls, value):
        _exact(value, cls.__dataclass_fields__, "UTC context")
        return cls(**value)


def _swing(value, axis, availability):
    _exact(value, ("kind", "position", "ts_ms", "value", "available_at_ms"), "swing")
    pos = _integer(value["position"], "swing position", nonnegative=True)
    _integer(value["ts_ms"], "swing timestamp")
    if pos >= len(axis) or value["ts_ms"] != axis[pos] or value["kind"] not in ("P", "T"):
        raise ValueError("swing does not match UTC timeline")
    if type(value["value"]) not in (int, float) or not math.isfinite(value["value"]):
        raise ValueError("swing price must be finite")
    if value["available_at_ms"] is not None:
        if _integer(value["available_at_ms"], "swing availability") < value["ts_ms"]:
            raise ValueError("swing availability precedes pivot")
    if value["available_at_ms"] != availability[pos]:
        raise ValueError("swing availability disagrees with UTC context")
    return value


@dataclass(frozen=True, slots=True, init=False)
class UtcClassificationResult:
    _payload: dict = field(repr=False)

    def __init__(self, payload):
        value = _plain(payload)
        _exact(value, ("schema_version", "rule_version", "status", "context", "parameters",
                       "timestamps_ms", "input_key", "identity_scope", "as_of_ms",
                       "availability_status", "availability_reason", "episodes", "continuations"), "UTC payload")
        if value["schema_version"] != "1.0" or value["rule_version"] != "utc-historical-1":
            raise ValueError("unsupported UTC classification schema or rule")
        if value["status"] not in ("retrospective", "as_of", "legacy_unavailable"):
            raise ValueError("invalid UTC classification status")
        context = UtcClassificationContext.from_dict(value["context"])
        if value["identity_scope"] not in ("stream", "input_local"):
            raise ValueError("invalid UTC identity scope")
        if value["availability_status"] not in ("known", "unknown"):
            raise ValueError("invalid UTC availability status")
        axis = value["timestamps_ms"]
        if not isinstance(axis, list):
            raise ValueError("UTC timeline must be a list")
        for timestamp in axis:
            _integer(timestamp, "UTC timestamp")
        if any(a >= b for a, b in zip(axis, axis[1:])):
            raise ValueError("UTC timeline must strictly increase")
        if (value["identity_scope"] == "stream") != (context.stream_id is not None):
            raise ValueError("UTC identity scope disagrees with context")
        for times in (context.bar_closed_at_ms, context.swing_available_at_ms):
            if times is not None and len(times) != len(axis):
                raise ValueError("UTC context must cover the timeline")
        if context.bar_closed_at_ms is not None:
            if any(close < ts for close, ts in zip(context.bar_closed_at_ms, axis)):
                raise ValueError("UTC close precedes bar timestamp")
            if context.swing_available_at_ms is not None and any(
                available is not None and available < close
                for available, close in zip(context.swing_available_at_ms, context.bar_closed_at_ms)
            ):
                raise ValueError("UTC availability precedes closed bar")
        has_timing = context.canonical_window is not None or context.swing_available_at_ms is not None
        if (value["availability_status"] == "known") != has_timing:
            raise ValueError("UTC availability status disagrees with context")
        expected_reason = ("legacy_payload_absent" if value["status"] == "legacy_unavailable"
                           else "canonical_centered_window" if context.canonical_window is not None
                           else "explicit_swing_availability" if context.swing_available_at_ms is not None
                           else "no_verified_availability_context")
        if value["availability_reason"] != expected_reason:
            raise ValueError("UTC availability reason disagrees with context")
        if value["as_of_ms"] is not None:
            _integer(value["as_of_ms"], "UTC cutoff")
        if (value["status"] == "as_of") != (value["as_of_ms"] is not None):
            raise ValueError("UTC cutoff disagrees with mode")
        if value["status"] == "as_of" and (
            not has_timing or any(t > value["as_of_ms"] for t in context.bar_closed_at_ms)
        ):
            raise ValueError("as-of timeline contains unclosed bars")
        if not isinstance(value["parameters"], dict) or not isinstance(value["input_key"], str):
            raise ValueError("invalid UTC configuration")
        from .specifications import resolve_parameters
        if dict(resolve_parameters("universal_trend_classifier", value["parameters"])) != value["parameters"]:
            raise ValueError("UTC parameters must be canonical")
        if context.canonical_window is not None:
            if context.canonical_window != value["parameters"]["trend_fractal_window"]:
                raise ValueError("UTC canonical window disagrees with trend dependency")
            half = context.canonical_window // 2
            availability = tuple(context.bar_closed_at_ms[i + half] if i + half < len(axis) else None
                                 for i in range(len(axis)))
        else:
            availability = context.swing_available_at_ms or (None,) * len(axis)
        availability_by_timestamp = dict(zip(axis, availability))
        if not isinstance(value["episodes"], list) or not isinstance(value["continuations"], list):
            raise ValueError("UTC episodes and continuations must be lists")
        if value["status"] == "legacy_unavailable" and (value["episodes"] or value["continuations"] or has_timing):
            raise ValueError("legacy UTC cannot assert classification")
        episodes = {}
        for episode in value["episodes"]:
            _exact(episode, ("episode_id", "direction", "segment_start_ms", "formation_key",
                             "formation", "origin", "restart_chain", "predecessor_episode_id",
                             "shared_pivot", "confirmed_at_ms", "decision_frontier_ms",
                             "status"), "episode")
            identity = episode["episode_id"]
            if not isinstance(identity, str) or not identity or identity in episodes:
                raise ValueError("duplicate or invalid UTC episode identity")
            if episode["direction"] not in ("UP", "DOWN"):
                raise ValueError("invalid episode direction")
            if episode["status"] not in ("open", "ended", "interrupted"):
                raise ValueError("invalid episode end status")
            if episode["origin"] not in ("initial_candidate", "candidate_restart", "post_break_restart", "direct_reversal", "unknown"):
                raise ValueError("invalid episode origin")
            formation = episode["formation"]
            if not isinstance(formation, list) or len(formation) < 3:
                raise ValueError("formation requires at least three swings")
            for swing in formation:
                _swing(swing, axis, availability)
            positions = [s["position"] for s in formation]
            if positions != sorted(set(positions)):
                raise ValueError("formation swings must be ordered and unique")
            if formation[0]["kind"] != ("T" if episode["direction"] == "UP" else "P"):
                raise ValueError("formation has wrong starting swing")
            if formation[-1]["kind"] != ("P" if episode["direction"] == "UP" else "T"):
                raise ValueError("formation has wrong confirming swing")
            ranks = {v: i for i, v in enumerate(sorted({s["value"] for s in formation}))}
            expected = episode["direction"] + "/" + "".join(s["kind"] for s in formation)
            expected += "/" + ",".join(str(ranks[s["value"]]) for s in formation)
            if episode["formation_key"] != expected:
                raise ValueError("formation key disagrees with P/T evidence")
            _integer(episode["segment_start_ms"], "segment start")
            if episode["segment_start_ms"] not in axis or episode["segment_start_ms"] > formation[0]["ts_ms"]:
                raise ValueError("invalid segment start")
            frontier = episode["decision_frontier_ms"]
            _integer(frontier, "decision frontier")
            if frontier not in axis or frontier < formation[-1]["ts_ms"]:
                raise ValueError("invalid decision frontier")
            confirmed = episode["confirmed_at_ms"]
            known = [availability_by_timestamp[frontier], *(s["available_at_ms"] for s in formation)]
            predecessor = episode["predecessor_episode_id"]
            if predecessor is not None and predecessor not in episodes:
                raise ValueError("episode predecessor must already exist")
            if episode["origin"] == "direct_reversal":
                if predecessor is None or episode["shared_pivot"] != formation[0]:
                    raise ValueError("direct reversal requires predecessor and shared pivot")
                if episodes[predecessor]["direction"] == episode["direction"]:
                    raise ValueError("direct reversal requires the opposite direction")
            elif episode["shared_pivot"] is not None:
                raise ValueError("only direct reversal has a shared pivot")
            if not isinstance(episode["restart_chain"], list):
                raise ValueError("UTC restart chain must be a list")
            for restart in episode["restart_chain"]:
                _exact(restart, ("reason", "trigger", "restart_ts_ms", "previous_anchor"), "restart")
                if restart["reason"] not in ("candidate_restart", "post_break_restart", "anchor_reselection"):
                    raise ValueError("invalid restart reason")
                _swing(restart["trigger"], axis, availability)
                _swing(restart["previous_anchor"], axis, availability)
                known.extend((restart["trigger"]["available_at_ms"], restart["previous_anchor"]["available_at_ms"]))
                _integer(restart["restart_ts_ms"], "restart timestamp")
                if restart["restart_ts_ms"] not in axis:
                    raise ValueError("invalid restart anchor")
            if confirmed is not None:
                _integer(confirmed, "confirmation")
                if any(v is None for v in known) or confirmed < max(frontier, *known):
                    raise ValueError("confirmation precedes available evidence")
                if value["as_of_ms"] is not None and confirmed > value["as_of_ms"]:
                    raise ValueError("confirmation exceeds cutoff")
            elif value["status"] == "as_of":
                raise ValueError("as-of formation requires known confirmation")
            episodes[identity] = episode
        event_ids = set()
        event_frontiers = {}
        event_known_times = {}
        for event in value["continuations"]:
            _exact(event, ("event_id", "episode_id", "kind", "swing", "known_at_ms",
                           "decision_frontier_ms", "before", "after"), "continuation")
            if (not isinstance(event["event_id"], str) or not event["event_id"]
                    or event["event_id"] in event_ids or event["episode_id"] not in episodes):
                raise ValueError("invalid continuation identity")
            event_ids.add(event["event_id"])
            if event["kind"] not in ("endpoint_extension", "endpoint_replacement", "supporting_swing",
                                     "ignored", "guard_failure", "termination", "reversal_activation"):
                raise ValueError("invalid continuation kind")
            _swing(event["swing"], axis, availability)
            _integer(event["decision_frontier_ms"], "continuation frontier")
            if event["decision_frontier_ms"] not in axis:
                raise ValueError("invalid continuation frontier")
            owner = episodes[event["episode_id"]]
            if event["decision_frontier_ms"] < max(event["swing"]["ts_ms"], owner["decision_frontier_ms"]):
                raise ValueError("continuation precedes formation or swing")
            previous_frontier = event_frontiers.get(event["episode_id"])
            if previous_frontier is not None and event["decision_frontier_ms"] < previous_frontier:
                raise ValueError("continuations must be in decision order")
            event_frontiers[event["episode_id"]] = event["decision_frontier_ms"]
            required = [event["swing"]["available_at_ms"], owner["confirmed_at_ms"],
                        availability_by_timestamp[event["decision_frontier_ms"]]]
            for state in (event["before"], event["after"]):
                _exact(state, ("endpoint", "guard"), "continuation state")
                for swing in state.values():
                    if swing is not None:
                        _swing(swing, axis, availability)
                        required.append(swing["available_at_ms"])
            if event["known_at_ms"] is not None:
                _integer(event["known_at_ms"], "continuation availability")
                if event["known_at_ms"] < event["decision_frontier_ms"]:
                    raise ValueError("continuation precedes decision")
                if any(t is None for t in required) or event["known_at_ms"] < max(required):
                    raise ValueError("continuation precedes available evidence")
                if value["as_of_ms"] is not None and event["known_at_ms"] > value["as_of_ms"]:
                    raise ValueError("continuation exceeds cutoff")
                previous_known = event_known_times.get(event["episode_id"])
                if previous_known is not None and event["known_at_ms"] < previous_known:
                    raise ValueError("continuations must be in availability order")
                event_known_times[event["episode_id"]] = event["known_at_ms"]
            elif value["status"] == "as_of":
                raise ValueError("as-of continuation requires known availability")
        object.__setattr__(self, "_payload", value)

    @classmethod
    def from_dict(cls, value):
        return cls(value)

    def to_dict(self):
        return deepcopy(self._payload)

    @property
    def status(self):
        return self._payload["status"]

    @property
    def episodes(self):
        return tuple(deepcopy(self._payload["episodes"]))

    @property
    def continuations(self):
        return tuple(deepcopy(self._payload["continuations"]))

    def to_episode_frame(self):
        records = []
        for episode in self.episodes:
            row = dict(episode)
            formation = row.pop("formation")
            row.update(starting_pivot_ms=formation[0]["ts_ms"],
                       starting_available_at_ms=formation[0]["available_at_ms"],
                       confirming_pivot_ms=formation[-1]["ts_ms"],
                       interpretation="retrospective_membership")
            records.append(row)
        return pd.DataFrame(records, dtype=object)

    def to_event_frame(self):
        return pd.DataFrame(list(self.continuations), dtype=object)

