from __future__ import annotations

from collections.abc import Mapping
import math

import numpy as np
import pandas as pd

from .common import _json_safe, _numeric_frame, _source_columns


def _quantile(series: pd.Series, value: float, method: str) -> float:
    try:
        return float(series.quantile(value, method=method))
    except TypeError:
        return float(series.quantile(value, interpolation=method))


def _variation(
    frame: pd.DataFrame,
    *,
    window: int,
    multiplier: float,
    floor_quantile: float,
    global_min_step: float,
    quantile_method: str,
) -> tuple[dict[str, float], list[dict[str, object]]]:
    steps: dict[str, float] = {}
    diagnostics: list[dict[str, object]] = []
    for name in frame.columns:
        series = frame[name].dropna().astype("float64")
        difference = series.diff().dropna()
        absolute = difference.abs()
        count = len(difference)
        if count == 0:
            floor = np.nan
        elif count <= window:
            floor = _quantile(absolute, floor_quantile, quantile_method)
        else:
            floor = _quantile(absolute.rolling(window).mean().dropna(), floor_quantile, quantile_method)
        step = float(floor) * multiplier if np.isfinite(floor) else np.nan
        if not np.isfinite(step) or step <= 0.0:
            step = global_min_step
        if step <= 0.0:
            raise ValueError(f"dynamic_binning could not derive a positive step for {name!r}")
        steps[name] = float(step)
        diagnostics.append(
            {
                "series": name,
                "count": count,
                "mean": float(difference.mean()) if count else None,
                "std": float(difference.std(ddof=1)) if count > 1 else None,
                "min": float(difference.min()) if count else None,
                "max": float(difference.max()) if count else None,
                "abs_mean": float(absolute.mean()) if count else None,
                "abs_median": float(absolute.median()) if count else None,
                "pctile_95": _quantile(difference, 0.95, quantile_method) if count else None,
                "pctile_99": _quantile(difference, 0.99, quantile_method) if count else None,
                "abs_pctile_95": _quantile(absolute, 0.95, quantile_method) if count else None,
                "abs_pctile_99": _quantile(absolute, 0.99, quantile_method) if count else None,
                "floor_quantile": floor_quantile,
                "floor_mean": float(floor) if np.isfinite(floor) else None,
                "suggest_step": float(step),
            }
        )
    return steps, diagnostics


def _side_edges(values: np.ndarray, step: float, n_bins: int) -> np.ndarray:
    maximum = float(np.max(values))
    effective_step = min(step, maximum / n_bins)
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.quantile(values, quantiles).astype("float64")
    edges[0] = 0.0
    for position in range(1, len(edges)):
        edges[position] = max(edges[position], edges[position - 1] + effective_step)
    edges[-1] = maximum
    for position in range(len(edges) - 2, -1, -1):
        edges[position] = min(edges[position], edges[position + 1] - effective_step)
        if position == 0:
            edges[position] = 0.0
    np.maximum.accumulate(edges, out=edges)
    return np.clip(edges, 0.0, maximum)


def _fit_bins(
    frame: pd.DataFrame,
    steps: Mapping[str, float],
    *,
    n_bins: int,
    boundary_eps: float,
) -> dict[str, object]:
    series_artifacts: dict[str, object] = {}
    for name in frame.columns:
        values = frame[name].dropna().to_numpy(dtype="float64")
        positive = np.sort(values[values > 0.0])
        negative = np.sort(-values[values < 0.0])
        if positive.size and negative.size:
            positive_edges = _side_edges(positive, steps[name], n_bins)
            negative_edges = _side_edges(negative, steps[name], n_bins)
            sources = {"positive": "fit", "negative": "fit"}
        elif positive.size:
            positive_edges = _side_edges(positive, steps[name], n_bins)
            negative_edges = positive_edges.copy()
            sources = {"positive": "fit", "negative": "mirrored"}
        elif negative.size:
            negative_edges = _side_edges(negative, steps[name], n_bins)
            positive_edges = negative_edges.copy()
            sources = {"positive": "mirrored", "negative": "fit"}
        else:
            raise ValueError(f"dynamic_binning source {name!r} contains only zeros")
        thresholds: dict[str, float] = {}
        for position in range(n_bins):
            thresholds[f"AB{position}"] = float(positive_edges[position + 1])
            thresholds[f"BL{position}"] = -float(negative_edges[position + 1])
        series_artifacts[name] = {
            "min_step": float(steps[name]),
            "side_edges": {"positive": positive_edges.tolist(), "negative": negative_edges.tolist()},
            "label_thresholds": thresholds,
            "side_sources": sources,
        }
    return {"n_bins": n_bins, "boundary_eps": boundary_eps, "series": series_artifacts}


def _label(value: float, thresholds: Mapping[str, float], *, n_bins: int, boundary_eps: float) -> object:
    if pd.isna(value):
        return None
    numeric = float(value)
    if math.isclose(numeric, 0.0, abs_tol=boundary_eps):
        return "AB0"
    if numeric > 0.0:
        for position in range(n_bins):
            if numeric <= thresholds[f"AB{position}"] + boundary_eps:
                return f"AB{position}"
        return f"AB{n_bins - 1}"
    for position in range(n_bins):
        if numeric >= thresholds[f"BL{position}"] - boundary_eps:
            return f"BL{position}"
    return f"BL{n_bins - 1}"


def _calculate_dynamic_binning(
    data: pd.DataFrame, parameters: Mapping[str, object], bindings: Mapping[str, object]
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    columns = _source_columns(parameters["source_columns"], context="dynamic_binning.source_columns")
    frame = _numeric_frame(data, columns, context="dynamic_binning")
    window = int(parameters["window"])
    multiplier = float(parameters["multiplier"])
    floor_quantile = float(parameters["floor_quantile"])
    global_min_step = float(parameters["global_min_step"])
    quantile_method = str(parameters["quantile_method"])
    n_bins = int(parameters["n_bins"])
    boundary_eps = float(parameters["boundary_eps"])
    steps, diagnostics = _variation(
        frame,
        window=window,
        multiplier=multiplier,
        floor_quantile=floor_quantile,
        global_min_step=global_min_step,
        quantile_method=quantile_method,
    )
    artifact = _fit_bins(
        frame,
        steps,
        n_bins=n_bins,
        boundary_eps=boundary_eps,
    )
    labeled = pd.DataFrame(index=data.index)
    for name in columns:
        labeled[name] = frame[name]
        thresholds = artifact["series"][name]["label_thresholds"]  # type: ignore[index]
        labeled[f"{name}_lab"] = frame[name].map(
            lambda value: _label(value, thresholds, n_bins=n_bins, boundary_eps=boundary_eps)
        )
    labeled_rows = labeled.reset_index(drop=False).to_dict(orient="records")
    return (), {
        "steps": _json_safe(steps),
        "variation_diagnostics": _json_safe(diagnostics),
        "binning_artifact": _json_safe(artifact),
        "labeled_rows": _json_safe(labeled_rows),
    }
