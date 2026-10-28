"""Read stored UTC measurements or replay them at an explicit available cutoff."""
from __future__ import annotations

from .utc_classification import _validate_utc_analysis, _replay_utc_prefix
from .utc_episode_metrics_models import UtcEpisodeMetricsResult
from ._calculation.utc_episode_metrics import _build_metrics


def get_utc_episode_metrics(result):
    if result.tool_key != "universal_trend_classifier":
        raise ValueError("episode metrics are only available for UTC")
    analysis = result.analysis
    core = _validate_utc_analysis(analysis)
    return (UtcEpisodeMetricsResult.from_dict(analysis["utc_episode_metrics"], classification=core)
            if "utc_episode_metrics" in analysis else None)


def measure_utc_as_of(data, parameters=None, *, context, as_of_ms):
    core, result = _replay_utc_prefix(data, parameters, context=context, as_of_ms=as_of_ms)
    evidence = result.analysis["utc_episode_metrics"]["evidence"] if result is not None else {"segments": [], "bars": []}
    return UtcEpisodeMetricsResult(_build_metrics(core, evidence), classification=core)
