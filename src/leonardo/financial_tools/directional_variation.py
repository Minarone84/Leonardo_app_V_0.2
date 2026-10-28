"""Public directional analysis API; supplied values are never differenced or centered."""
from __future__ import annotations

import pandas as pd

from ._calculation.directional_binning import _analyze_directional, _classify_directional, _fit_directional
from .directional_variation_models import (
    DirectionalBinningPolicy, DirectionalBinningProfile, DirectionalBinningResult, DirectionalVariationAnalysis,
)
from .variation_models import VariationContext


def analyze_directional_variation(data: pd.DataFrame, source: str, *,
                                  policy: DirectionalBinningPolicy = DirectionalBinningPolicy()) -> DirectionalVariationAnalysis:
    """Describe each original sign using only that sign's finite source observations."""
    return _analyze_directional(data, source, policy)


def fit_directional_binning(data: pd.DataFrame, context: VariationContext, *, profile_id: str,
                            calibration_as_of_ms: int, provenance: tuple[str, ...],
                            policy: DirectionalBinningPolicy = DirectionalBinningPolicy()) -> DirectionalBinningProfile:
    """Freeze independent sign references available through the explicit cutoff."""
    return _fit_directional(data, context, profile_id=profile_id, calibration_as_of_ms=calibration_as_of_ms,
                            provenance=provenance, policy=policy)


def classify_directional_binning(data: pd.DataFrame, profile: DirectionalBinningProfile, *,
                                 context: VariationContext, mode: str) -> DirectionalBinningResult:
    """Classify without modifying the reference; absent directions remain uncalibrated."""
    return _classify_directional(data, profile, context=context, mode=mode)
