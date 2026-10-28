"""Backend entry points for descriptive analysis and fixed-reference classification."""

from __future__ import annotations

import pandas as pd

from ._calculation.variation_analysis import _analyze
from ._calculation.dynamic_binning import _classify_profile, _fit_profile
from .variation_models import (
    BinningPolicy, BinningResult, DynamicBinningProfile, VariationAnalysis, VariationContext,
)


def analyze_variation(
    data: pd.DataFrame,
    source: str,
    *,
    measurement: str = "value",
    policy: BinningPolicy = BinningPolicy(),
) -> VariationAnalysis:
    """Describe supplied parameter levels, or their magnitudes, without differencing."""
    return _analyze(data, source, measurement, policy)[0]


def fit_dynamic_binning(
    data: pd.DataFrame,
    context: VariationContext,
    *,
    profile_id: str,
    calibration_as_of_ms: int,
    provenance: tuple[str, ...],
    measurement: str = "value",
    policy: BinningPolicy = BinningPolicy(),
) -> DynamicBinningProfile:
    """Calibrate using supplied observations available through the explicit cutoff."""
    return _fit_profile(data, context, profile_id=profile_id,
                        calibration_as_of_ms=calibration_as_of_ms, provenance=provenance,
                        measurement=measurement, policy=policy)


def classify_dynamic_binning(
    data: pd.DataFrame,
    profile: DynamicBinningProfile,
    *,
    context: VariationContext,
    mode: str,
) -> BinningResult:
    """Apply a fixed profile without recalibrating or changing earlier results."""
    return _classify_profile(data, profile, context=context, mode=mode)
