"""Evidence observer for the existing UTC scanner, not another detector."""
from __future__ import annotations

from hashlib import sha256

import numpy as np
import pandas as pd

from ..utc_classification_models import UtcClassificationContext, UtcClassificationResult, _key


def _availability(data, parameters, context):
    axis = tuple(int(v) for v in pd.to_numeric(data.ts_ms))
    n = len(axis)
    closes = context.bar_closed_at_ms
    if closes is not None:
        if len(closes) != n or any(c < t for c, t in zip(closes, axis)):
            raise ValueError("UTC bar close times must cover the input timeline")
    custom = context.swing_available_at_ms
    if custom is not None:
        if len(custom) != n:
            raise ValueError("UTC swing availability must cover the input timeline")
        for pos, value in enumerate(custom):
            if value is not None and value < closes[pos]:
                raise ValueError("UTC swing availability precedes its closed pivot bar")
        available = custom
    elif context.canonical_window is not None:
        if context.canonical_window != parameters["trend_fractal_window"]:
            raise ValueError("UTC canonical P/T window disagrees with trend dependency")
        from .common import _fractal_extrema
        for name, source, peak in ((parameters["peak_column"], "high", True),
                                   (parameters["trough_column"], "low", False)):
            expected = _fractal_extrema(data[source], window=context.canonical_window, peak=peak)
            actual = pd.to_numeric(data[name], errors="raise").astype("float32")
            if not np.array_equal(actual.to_numpy(), expected.astype("float32").to_numpy(), equal_nan=True):
                raise ValueError("UTC canonical availability requires verified canonical P/T values")
        half = context.canonical_window // 2
        available = tuple(closes[i + half] if i + half < n else None for i in range(n))
    else:
        available = (None,) * n
    from .common import _numeric_series
    peaks = _numeric_series(data, parameters["peak_column"], context="universal_trend_classifier")
    troughs = _numeric_series(data, parameters["trough_column"], context="universal_trend_classifier")
    previous = None
    for pos, (p, t) in enumerate(zip(peaks, troughs)):
        if bool(pd.notna(p) and np.isfinite(p)) == bool(pd.notna(t) and np.isfinite(t)):
            continue
        value = available[pos]
        if value is not None:
            if previous is not None and value < previous:
                raise ValueError("out-of-order UTC swing delivery requires a separate revision")
            previous = value
    return available


class _UtcTrace:
    def __init__(self, data, parameters, context=None):
        self.data = data
        self.parameters = dict(parameters)
        self.context = context or UtcClassificationContext()
        if not isinstance(self.context, UtcClassificationContext):
            raise TypeError("utc_context must be UtcClassificationContext")
        self.axis = [int(v) for v in pd.to_numeric(data.ts_ms)]
        self.available = _availability(data, parameters, self.context)
        fingerprint = sha256(pd.util.hash_pandas_object(data, index=False).values.tobytes()).hexdigest()
        self.input_key = _key((tuple(data.columns), fingerprint, self.parameters, self.context.to_dict()))
        self.scope_key = _key((self.context.stream_id or self.input_key, self.parameters, "utc-historical-1"))
        self.episodes = []
        self.events = []
        self.current = None

        # Disposable copies for post-calculation measurement; never consulted by the scanner.
        self.measurement_segments = []

    def segment(self, start, end, swings):
        self.measurement_segments.append(dict(start_position=start, end_position=end,
                                             swings=[self.swing(s) for s in swings]))
        self.segment_start = start
        self.segment_end = end
        self.swings = swings
        self.swing_indices = {s.position: i for i, s in enumerate(swings)}
        self.frontier = -1
        self.known_frontier = None
        self.all_known = True
        self.origin = "initial_candidate"
        self.restarts = []
        self.predecessor = None
        self.current = None

    def swing(self, swing):
        if swing is None:
            return None
        return dict(kind="P" if swing.kind == "peak" else "T", position=swing.position,
                    ts_ms=self.axis[swing.position], value=float(swing.value),
                    available_at_ms=self.available[swing.position])

    def state(self, snapshot, direction):
        return {
            "endpoint": self.swing(snapshot["last_peak"] if direction == "UP" else snapshot["last_trough"]),
            "guard": self.swing(snapshot["last_trough"] if direction == "UP" else snapshot["last_peak"]),
        }

    def event(self, kind, swing, before, after):
        episode = self.current
        self.events.append(dict(
            event_id=_key((episode["episode_id"], len(self.events), kind, self.axis[self.frontier])),
            episode_id=episode["episode_id"], kind=kind, swing=self.swing(swing),
            known_at_ms=self.known_frontier if self.all_known else None,
            decision_frontier_ms=self.axis[self.frontier],
            before=self.state(before, episode["direction"]),
            after=self.state(after, episode["direction"]),
        ))

    def activate(self, after, swing, origin):
        start = after["start_i"]
        formation = [self.swing(s) for s in self.swings[start:self.swing_indices[swing.position] + 1]]
        direction = "UP" if after["mode"] == "active_up" else "DOWN"
        ranks = {value: i for i, value in enumerate(sorted({s["value"] for s in formation}))}
        pattern = direction + "/" + "".join(s["kind"] for s in formation)
        pattern += "/" + ",".join(str(ranks[s["value"]]) for s in formation)
        identity = _key((self.scope_key, self.axis[self.segment_start], direction, formation[0]["ts_ms"]))
        episode = dict(
            episode_id=identity, direction=direction, segment_start_ms=self.axis[self.segment_start],
            formation_key=pattern, formation=formation, origin=origin,
            restart_chain=list(self.restarts), predecessor_episode_id=self.predecessor,
            shared_pivot=formation[0] if origin == "direct_reversal" else None,
            confirmed_at_ms=self.known_frontier if self.all_known else None,
            decision_frontier_ms=self.axis[self.frontier], status="open",
        )
        self.episodes.append(episode)
        self.current = episode

    def observe(self, before, after, swing, next_i):
        if swing.position > self.frontier:
            self.frontier = swing.position
            known = self.available[swing.position]
            self.all_known = self.all_known and known is not None
            if known is not None:
                self.known_frontier = max(self.known_frontier or known, known)
        prior_mode, mode = before["mode"], after["mode"]
        prior_active = prior_mode in ("active_up", "active_down")
        active = mode in ("active_up", "active_down")
        if prior_active and self.current is not None:
            if mode != prior_mode:
                self.event("reversal_activation" if active else "guard_failure", swing, before, after)
                self.event("termination", swing, before, after)
                self.current["status"] = "ended"
                self.predecessor = self.current["episode_id"]
                self.current = None
                if active:
                    self.restarts = []
                    self.activate(after, swing, "direct_reversal")
            else:
                old = self.state(before, self.current["direction"])
                new = self.state(after, self.current["direction"])
                if old["endpoint"] != new["endpoint"]:
                    sign = 1 if self.current["direction"] == "UP" else -1
                    kind = ("endpoint_extension" if sign * (new["endpoint"]["value"] - old["endpoint"]["value"]) > 0
                            else "endpoint_replacement")
                elif old["guard"] != new["guard"]:
                    kind = "supporting_swing"
                else:
                    kind = "ignored"
                self.event(kind, swing, before, after)
        elif active:
            self.activate(after, swing, self.origin)
        if mode is None and prior_mode is not None:
            reason = "post_break_restart" if prior_active else "candidate_restart"
            self.origin = reason
            self.restarts.append(dict(reason=reason, trigger=self.swing(swing),
                                      restart_ts_ms=self.axis[self.swings[next_i].position],
                                      previous_anchor=self.swing(self.swings[before["start_i"]])))
        elif (prior_mode in ("candidate_up", "candidate_down") and mode == prior_mode
              and after["start_i"] != before["start_i"]):
            self.restarts.append(dict(reason="anchor_reselection", trigger=self.swing(swing),
                                      restart_ts_ms=self.axis[self.swings[after["start_i"]].position],
                                      previous_anchor=self.swing(self.swings[before["start_i"]])))

    def finish_segment(self):
        if self.current is not None and self.segment_end < len(self.axis) - 1:
            self.current["status"] = "interrupted"

    def report(self):
        payload = dict(
            schema_version="1.0", rule_version="utc-historical-1", status="retrospective",
            context=self.context.to_dict(), parameters=self.parameters, timestamps_ms=self.axis,
            input_key=self.input_key, identity_scope="stream" if self.context.stream_id else "input_local",
            as_of_ms=None,
            availability_status="known" if self.context.canonical_window is not None or self.context.swing_available_at_ms is not None else "unknown",
            availability_reason=("canonical_centered_window" if self.context.canonical_window is not None
                                 else "explicit_swing_availability" if self.context.swing_available_at_ms is not None
                                 else "no_verified_availability_context"),
            episodes=self.episodes, continuations=self.events,
        )
        return UtcClassificationResult(payload).to_dict()

