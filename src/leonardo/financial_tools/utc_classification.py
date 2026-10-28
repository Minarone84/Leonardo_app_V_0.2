"""Read UTC-owned classification and replay the same detector as of a cutoff."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .utc_classification_models import UtcClassificationContext, UtcClassificationResult


def _validate_utc_analysis(analysis):
    if not analysis:
        return None
    if set(analysis) not in ({"utc_classification"}, {"utc_classification", "utc_episode_metrics"}):
        raise ValueError("invalid UTC analysis sections")
    core = UtcClassificationResult.from_dict(analysis["utc_classification"])
    if "utc_episode_metrics" in analysis:
        from .utc_episode_metrics_models import UtcEpisodeMetricsResult
        UtcEpisodeMetricsResult.from_dict(analysis["utc_episode_metrics"], classification=core)
    return core


def get_utc_classification(result):
    if result.tool_key != "universal_trend_classifier":
        raise ValueError("classification is only available for UTC")
    analysis = result.analysis
    if analysis:
        return _validate_utc_analysis(analysis)
    return UtcClassificationResult(dict(
        schema_version="1.0", rule_version="utc-historical-1", status="legacy_unavailable",
        context=UtcClassificationContext().to_dict(), parameters=dict(result.parameters),
        timestamps_ms=[int(v) for v in result.to_frame().ts_ms], input_key="legacy",
        identity_scope="input_local", as_of_ms=None, availability_status="unknown",
        availability_reason="legacy_payload_absent",
        episodes=[], continuations=[],
    ))


def classify_utc_as_of(data, parameters=None, *, context, as_of_ms):
    payload, _ = _replay_utc_prefix(data, parameters, context=context, as_of_ms=as_of_ms)
    return UtcClassificationResult(payload)


def _replay_utc_prefix(data, parameters=None, *, context, as_of_ms):
    from .calculation import calculate_financial_tool
    from .specifications import resolve_parameters
    from ._calculation.utc_classification import _availability, _UtcTrace
    from .utc_classification_models import _integer

    _integer(as_of_ms, "as_of_ms")
    if not isinstance(context, UtcClassificationContext) or context.bar_closed_at_ms is None:
        raise ValueError("as-of UTC requires verified availability and bar close times")
    if context.canonical_window is None and context.swing_available_at_ms is None:
        raise ValueError("as-of UTC requires verified swing availability")
    resolved = resolve_parameters("universal_trend_classifier", parameters)
    available = _availability(data, resolved, context)
    n = sum(t <= as_of_ms for t in context.bar_closed_at_ms)
    prefix = data.iloc[:n].copy(deep=True)
    for name in (resolved["peak_column"], resolved["trough_column"]):
        for pos in range(n):
            if available[pos] is None or available[pos] > as_of_ms:
                prefix.iloc[pos, prefix.columns.get_loc(name)] = np.nan
    # Range dependencies have their own centered window. Verify before masking.
    from ._calculation.common import _fractal_extrema
    range_window = int(resolved["range_fractal_window"])
    for name, source, peak in ((f"peak_fractal_{range_window}", "high", True),
                               (f"trough_fractal_{range_window}", "low", False)):
        if name in (resolved["peak_column"], resolved["trough_column"]):
            continue
        expected = _fractal_extrema(data[source], window=range_window, peak=peak).astype("float32")
        if not np.array_equal(data[name].astype("float32").to_numpy(), expected.to_numpy(), equal_nan=True):
            raise ValueError("as-of range dependencies require canonical P/T evidence")
        for pos in range(n):
            frontier = pos + range_window // 2
            if frontier >= len(data) or context.bar_closed_at_ms[frontier] > as_of_ms:
                prefix.iloc[pos, prefix.columns.get_loc(name)] = np.nan
    sliced = replace(context, bar_closed_at_ms=context.bar_closed_at_ms[:n],
                     canonical_window=None, swing_available_at_ms=tuple(available[:n]))
    if n:
        result = calculate_financial_tool("UTC", prefix, resolved, utc_context=sliced)
        payload = get_utc_classification(result).to_dict()
    else:
        result = None
        payload = _UtcTrace(prefix, resolved, sliced).report()
    payload["status"] = "as_of"
    payload["as_of_ms"] = as_of_ms
    return UtcClassificationResult(payload).to_dict(), result

