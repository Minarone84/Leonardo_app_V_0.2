"""Empirical calibration and fixed-reference classification by original sign."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dynamic_binning import _availability
from .variation_analysis import _input_values, _timestamps
from ..variation_models import VariationContext, _empirical_rank, _integer
from ..directional_variation_models import (
    DirectionalBinningPolicy, DirectionalBinningProfile, DirectionalBinningResult,
    DirectionalVariationAnalysis, _DirectionalReference, _bin_indices, _description, _label,
)


def _analyze_directional(data: pd.DataFrame, source: str, policy: DirectionalBinningPolicy) -> DirectionalVariationAnalysis:
    if not isinstance(policy, DirectionalBinningPolicy):
        raise TypeError("policy must be a DirectionalBinningPolicy")
    timestamps, raw, _ = _input_values(data, source, "value")
    references = []
    for direction, bins in ((1, policy.positive_bins), (-1, policy.negative_bins)):
        values, counts = np.unique(np.abs(raw[raw > 0] if direction == 1 else raw[raw < 0]), return_counts=True)
        references.append(_DirectionalReference(direction, bins, policy.min_reference_count, values, counts))
    return DirectionalVariationAnalysis(
        source, policy, len(data), int(np.count_nonzero(np.isnan(raw))), int(np.count_nonzero(raw == 0)),
        int(timestamps[0]) if len(data) else None, int(timestamps[-1]) if len(data) else None,
        *references,
    )


def _fit_directional(data, context, *, profile_id, calibration_as_of_ms, provenance, policy):
    if not isinstance(context, VariationContext):
        raise TypeError("context must be a VariationContext")
    cutoff = _integer(calibration_as_of_ms, "calibration_as_of_ms")
    analysis = _analyze_directional(data, context.source, policy)
    if not analysis.valid_count:
        raise ValueError("insufficient_reference: no finite observations to calibrate")
    available = _availability(data, _timestamps(data, "ts_ms", ordered=True))
    if np.any(available > cutoff):
        raise ValueError("calibration includes observations available after calibration_as_of_ms")
    return DirectionalBinningProfile(profile_id, context, cutoff, provenance, analysis)


def _classify_directional(data, profile, *, context, mode):
    if not isinstance(profile, DirectionalBinningProfile):
        raise TypeError("profile must be a DirectionalBinningProfile")
    if not isinstance(context, VariationContext) or context != profile.context:
        raise ValueError("classification context does not match profile")
    if mode not in ("retrospective", "forward"):
        raise ValueError("mode must be explicitly 'retrospective' or 'forward'")
    timestamps, raw, _ = _input_values(data, context.source, "value")
    available = _availability(data, timestamps)
    if mode == "forward" and np.any(available <= profile.calibration_as_of_ms):
        raise ValueError("forward observations must be available after calibration_as_of_ms")
    size, total = len(data), profile.analysis.valid_count
    result = pd.DataFrame(index=data.index)
    result["ts_ms"], result["available_at_ms"] = timestamps, available
    for name, value in (("source", context.source), ("profile_id", profile.profile_id),
                        ("measurement", "directional_intensity"), ("mode", mode)):
        result[name] = pd.array([value] * size, dtype="string")
    result["raw_value"] = pd.array(raw, dtype="Float64")
    result["magnitude"] = pd.array(np.abs(raw), dtype="Float64")
    result["direction"] = pd.array(np.sign(raw), dtype="Int64")
    result["whole_reference_count"] = pd.array([total] * size, dtype="Int64")
    result["zero_reference_count"] = pd.array([profile.analysis.zero_count] * size, dtype="Int64")
    result["zero_reference_frequency"] = pd.array([profile.analysis.zero_count / total] * size, dtype="Float64")
    for name in ("directional_percentile", "tie_lower_percentile", "tie_upper_percentile", "direction_frequency",
                 "conditional_small_tail_frequency", "conditional_large_tail_frequency",
                 "whole_small_tail_frequency", "whole_large_tail_frequency", "bin_percentile_start", "bin_percentile_end"):
        result[name] = pd.array([pd.NA] * size, dtype="Float64")
    for name in ("directional_reference_count", "small_magnitude_tail_count", "large_magnitude_tail_count", "bin_index", "bin_count"):
        result[name] = pd.array([pd.NA] * size, dtype="Int64")
    for name in ("bin_label", "bin_description", "conditional_small_tail_label", "conditional_large_tail_label", "range_position", "support_status"):
        result[name] = pd.array([pd.NA] * size, dtype="string")
    result["outside_reference_range"] = pd.array([pd.NA] * size, dtype="boolean")
    result["status"] = pd.array(["missing_value"] * size, dtype="string")
    zero = raw == 0
    result.loc[zero, "status"] = "zero_value"
    result.loc[zero, "support_status"] = "not_applicable"
    result.loc[zero, "direction_frequency"] = profile.analysis.zero_count / total
    for side in (profile.analysis.positive, profile.analysis.negative):
        selected = raw > 0 if side.direction == 1 else raw < 0
        magnitudes = np.abs(raw[selected])
        count = side.reference_count
        result.loc[selected, "directional_reference_count"] = count
        result.loc[selected, "direction_frequency"] = count / total
        result.loc[selected, "bin_count"] = side.bin_count
        result.loc[selected, "support_status"] = side.status
        if not count:
            result.loc[selected, "status"] = "uncalibrated_direction"
            continue
        below, above = magnitudes < side.values[0], magnitudes > side.values[-1]
        outside = below | above
        relation = np.where(below, "below", np.where(above, "above", "equal" if len(side.values) == 1 else "inside"))
        result.loc[selected, "range_position"] = relation
        result.loc[selected, "outside_reference_range"] = outside
        result.loc[selected, "status"] = side.status
        if len(side.values) == 1:
            continue
        ranks, lower, equal = _empirical_rank(side._ordered, side._cumulative, magnitudes)
        small, large = lower + equal, count - lower
        indices = _bin_indices(lower, equal, count, side.bin_count)
        for name, values in (
            ("directional_percentile", ranks), ("tie_lower_percentile", 100.0 * lower / count),
            ("tie_upper_percentile", 100.0 * (lower + equal) / count),
            ("small_magnitude_tail_count", small), ("large_magnitude_tail_count", large),
            ("conditional_small_tail_frequency", small / count), ("conditional_large_tail_frequency", large / count),
            ("whole_small_tail_frequency", small / total), ("whole_large_tail_frequency", large / total),
            ("bin_index", indices), ("bin_percentile_start", 100.0 * (indices - 1) / side.bin_count),
            ("bin_percentile_end", 100.0 * indices / side.bin_count),
            ("bin_label", [_label(side.direction, int(index)) for index in indices]),
            ("bin_description", [_description(side.direction, int(index), side.bin_count) for index in indices]),
        ):
            result.loc[selected, name] = values
        result.loc[selected, "status"] = np.where(outside, "outside_reference_range", side.status)
        if side.status == "ready":
            positions = np.flatnonzero(selected)[~outside]
            for name, tail in (("conditional_small_tail_label", small), ("conditional_large_tail_label", large)):
                # Integer comparisons keep threshold inclusion exact for large references.
                labels = ["very_rare" if int(n) * 100 <= count else "rare" if int(n) * 20 <= count else "common"
                          for n in tail[~outside]]
                result.iloc[positions, result.columns.get_loc(name)] = labels
    return DirectionalBinningResult(profile.profile_id, context, mode, result)
