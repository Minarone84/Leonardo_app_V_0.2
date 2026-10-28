"""Internal models for empirical variation analysis; no application persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from math import isclose, isfinite
from numbers import Integral, Real

import numpy as np
import pandas as pd

from leonardo.data.market_id import MarketId, canonicalize_market_id


_BANDS = ("very_low", "low", "below_typical", "typical", "above_typical", "high", "very_high")
_ALGORITHM = "empirical_midrank_v1"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str, minimum: int | None = None) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if not -(2**63) <= result < 2**63:
        raise ValueError(f"{name} is outside int64 range")
    return result


def _finite(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


def _keys(payload: object, expected: set[str], name: str) -> Mapping:
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError(f"{name} fields must be exactly {sorted(expected)}")
    return payload


def _measurement(value: str) -> str:
    if value not in ("value", "magnitude"):
        raise ValueError("measurement must be 'value' or 'magnitude'")
    return value


def _empirical_rank(
    ordered: np.ndarray, cumulative: np.ndarray, observations: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shared mid-distribution rank and strict/equal counts."""
    left = np.searchsorted(ordered, observations, side="left")
    right = np.searchsorted(ordered, observations, side="right")
    lower = cumulative[left]
    equal = cumulative[right] - lower
    ranks = 100.0 * (lower + equal / 2.0) / int(cumulative[-1])
    return ranks, lower, equal


def _distribution_statistics(values: tuple[float, ...] | np.ndarray,
                             counts: tuple[int, ...] | np.ndarray) -> dict[str, float]:
    """One authority for diagnostics of a nonempty, validated empirical reference."""
    ordered = np.asarray(values, dtype="float64")
    frequencies = np.asarray(counts, dtype="int64")
    cumulative = np.cumsum(frequencies, dtype="int64")
    count = int(cumulative[-1])
    scale = float(np.max(np.abs(ordered)))
    scaled = ordered / scale if scale else ordered
    mean = float(np.clip(np.average(scaled, weights=frequencies), scaled[0], scaled[-1]))
    # Population moments stay scaled to avoid overflow in sums and squares.
    # Standard deviation cannot exceed the largest absolute observation.
    std = min(float(np.sqrt(np.average((scaled - mean) ** 2, weights=frequencies))), 1.0) * scale
    quartiles = []
    for numerator in (1, 2, 3):
        # Integer ranks preserve frequencies without expanding repeated observations.
        lower, remainder = divmod((count - 1) * numerator, 4)
        upper = lower + bool(remainder)
        left, right = ordered[np.searchsorted(cumulative, [lower, upper], side="right")]
        fraction = remainder / 4.0
        if left < 0 < right:
            # Opposite-sign subtraction can overflow; these products cannot.
            value = (1.0 - fraction) * left + fraction * right
        elif fraction < 0.5:
            value = left + (right - left) * fraction
        else:
            value = right - (right - left) * (1.0 - fraction)
        quartiles.append(float(value))
    return dict(minimum=float(ordered[0]), maximum=float(ordered[-1]), mean=mean * scale, std=std,
                q1=quartiles[0], median=quartiles[1], q3=quartiles[2])


@dataclass(frozen=True, slots=True)
class VariationContext:
    """Identity of one supplied parameter; definition includes all formula settings."""

    source: str
    market_id: MarketId
    parameter_definition: str
    parameter_version: str
    unit: str

    def __post_init__(self) -> None:
        for name in ("source", "parameter_definition", "parameter_version", "unit"):
            _text(getattr(self, name), name)
        if not isinstance(self.market_id, MarketId):
            raise ValueError("market_id must be a canonical MarketId")
        market = self.market_id
        canonical = canonicalize_market_id(market.exchange, market.market_type, market.symbol, market.timeframe)
        if canonical != market:
            raise ValueError("market_id must be canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "market_id": {name: getattr(self.market_id, name) for name in
                          ("exchange", "market_type", "symbol", "timeframe")},
            "parameter_definition": self.parameter_definition,
            "parameter_version": self.parameter_version,
            "unit": self.unit,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> VariationContext:
        data = dict(_keys(payload, {item.name for item in fields(cls)}, "context"))
        market = _keys(data["market_id"], {"exchange", "market_type", "symbol", "timeframe"}, "market_id")
        data["market_id"] = MarketId(**market)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class BinningPolicy:
    cutoffs: tuple[float, ...] = (1.0, 5.0, 25.0, 75.0, 95.0, 99.0)
    min_reference_count: int = 2000

    def __post_init__(self) -> None:
        cutoffs = tuple(_finite(value, "cutoff") for value in self.cutoffs)
        if len(cutoffs) != 6 or not all(0 < a < b < 100 for a, b in zip(cutoffs, cutoffs[1:])):
            raise ValueError("cutoffs must contain six strictly increasing values inside (0, 100)")
        object.__setattr__(self, "cutoffs", cutoffs)
        object.__setattr__(self, "min_reference_count", _integer(self.min_reference_count, "min_reference_count", 1))

    def to_dict(self) -> dict[str, object]:
        return {"cutoffs": list(self.cutoffs), "min_reference_count": self.min_reference_count,
                "tail_frequency_cutoffs": [0.01, 0.05]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> BinningPolicy:
        data = _keys(payload, {"cutoffs", "min_reference_count", "tail_frequency_cutoffs"}, "policy")
        if data["tail_frequency_cutoffs"] != [0.01, 0.05]:
            raise ValueError("unsupported tail frequency policy")
        return cls(cutoffs=data["cutoffs"], min_reference_count=data["min_reference_count"])


@dataclass(frozen=True, slots=True)
class VariationAnalysis:
    source: str
    measurement: str
    row_count: int
    valid_count: int
    missing_count: int
    distinct_count: int
    zero_count: int
    positive_count: int
    negative_count: int
    reference_start_ms: int | None
    reference_end_ms: int | None
    minimum: float | None
    maximum: float | None
    mean: float | None
    std: float | None
    median: float | None
    q1: float | None
    q3: float | None
    status: str
    band_counts: tuple[int, ...]

    def __post_init__(self) -> None:
        _text(self.source, "source")
        _measurement(self.measurement)
        for name in ("row_count", "valid_count", "missing_count", "distinct_count",
                     "zero_count", "positive_count", "negative_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), name, 0))
        if self.row_count != self.valid_count + self.missing_count:
            raise ValueError("analysis row counts are inconsistent")
        if self.valid_count != self.zero_count + self.positive_count + self.negative_count:
            raise ValueError("analysis sign counts are inconsistent")
        if not 0 <= self.distinct_count <= self.valid_count:
            raise ValueError("analysis distinct_count is inconsistent")
        bands = tuple(_integer(value, "band count", 0) for value in self.band_counts)
        if len(bands) != 7 or sum(bands) != (self.valid_count if self.distinct_count > 1 else 0):
            raise ValueError("analysis band counts are inconsistent")
        object.__setattr__(self, "band_counts", bands)
        for name in ("reference_start_ms", "reference_end_ms"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _integer(getattr(self, name), name))
        if self.row_count:
            if self.reference_start_ms is None or self.reference_end_ms is None:
                raise ValueError("nonempty analysis requires a reference span")
            if self.reference_start_ms > self.reference_end_ms:
                raise ValueError("reference span is reversed")
        elif self.reference_start_ms is not None or self.reference_end_ms is not None:
            raise ValueError("empty analysis cannot have a reference span")
        for name in ("minimum", "maximum", "mean", "std", "median", "q1", "q3"):
            value = getattr(self, name)
            if self.valid_count:
                object.__setattr__(self, name, _finite(value, name))
            elif value is not None:
                raise ValueError("empty reference statistics must be null")
        if self.valid_count:
            if not self.distinct_count or not self.minimum <= self.q1 <= self.median <= self.q3 <= self.maximum:
                raise ValueError("analysis statistics are inconsistent")
            if self.std < 0 or not self.minimum <= self.mean <= self.maximum:
                raise ValueError("analysis mean/std are inconsistent")
        expected = ("insufficient_reference" if not self.valid_count else
                    "degenerate_reference" if self.distinct_count == 1 else None)
        if (expected is not None and self.status != expected) or (
            expected is None and self.status not in ("ready", "limited_support")
        ):
            raise ValueError("analysis status is inconsistent")

    def to_dict(self) -> dict[str, object]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["band_counts"] = list(self.band_counts)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> VariationAnalysis:
        return cls(**_keys(payload, {item.name for item in fields(cls)}, "analysis"))


@dataclass(frozen=True, slots=True)
class DynamicBinningProfile:
    profile_id: str
    context: VariationContext
    measurement: str
    policy: BinningPolicy
    calibration_as_of_ms: int
    provenance: tuple[str, ...]
    analysis: VariationAnalysis
    values: tuple[float, ...]
    counts: tuple[int, ...]
    _ordered: np.ndarray = field(init=False, repr=False, compare=False)
    _cumulative: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.profile_id, "profile_id")
        _measurement(self.measurement)
        if not isinstance(self.context, VariationContext) or not isinstance(self.policy, BinningPolicy):
            raise ValueError("profile requires a context and policy")
        if not isinstance(self.analysis, VariationAnalysis):
            raise ValueError("profile requires analysis")
        object.__setattr__(self, "calibration_as_of_ms", _integer(self.calibration_as_of_ms, "calibration_as_of_ms"))
        if isinstance(self.provenance, str):
            raise ValueError("provenance must be a sequence of source identifiers")
        provenance = tuple(_text(value, "provenance") for value in self.provenance)
        if not provenance or len(provenance) != len(set(provenance)):
            raise ValueError("provenance must contain unique source identifiers")
        object.__setattr__(self, "provenance", provenance)
        values = tuple(_finite(value, "profile value") for value in self.values)
        counts = tuple(_integer(value, "profile count", 1) for value in self.counts)
        if not values or len(values) != len(counts) or any(a >= b for a, b in zip(values, values[1:])):
            raise ValueError("profile values must be nonempty, distinct and sorted with matching counts")
        if self.measurement == "magnitude" and values[0] < 0:
            raise ValueError("magnitude reference cannot contain negative values")
        analysis = self.analysis
        if (sum(counts) != analysis.valid_count or len(values) != analysis.distinct_count
                or values[0] != analysis.minimum or values[-1] != analysis.maximum
                or analysis.source != self.context.source or analysis.measurement != self.measurement):
            raise ValueError("profile distribution and analysis are inconsistent")
        expected = ("degenerate_reference" if len(values) == 1 else
                    "limited_support" if sum(counts) < self.policy.min_reference_count else "ready")
        if analysis.status != expected or analysis.reference_end_ms > self.calibration_as_of_ms:
            raise ValueError("profile support status or calibration time is inconsistent")
        zero_count = sum(count for value, count in zip(values, counts) if value == 0)
        if (analysis.zero_count != zero_count or (self.measurement == "value" and (
                analysis.negative_count != sum(count for value, count in zip(values, counts) if value < 0)
                or analysis.positive_count != sum(count for value, count in zip(values, counts) if value > 0)))):
            raise ValueError("profile distribution and analysis sign counts are inconsistent")
        statistics = _distribution_statistics(values, counts)
        # Allow roundoff from equivalent float64 summaries, including cancellation
        # in a signed mean. No absolute tolerance may hide tiny quartiles or std.
        mean_tolerance = 64 * np.finfo("float64").eps * max(abs(values[0]), abs(values[-1]))
        for name in ("mean", "std", "q1", "median", "q3"):
            if not isclose(getattr(analysis, name), statistics[name], rel_tol=1e-12,
                           abs_tol=mean_tolerance if name == "mean" else 0.0):
                raise ValueError(f"profile distribution and analysis statistics are inconsistent: {name}")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "counts", counts)
        # Bytes-backed arrays cannot be made writable by changing ndarray flags.
        ordered = np.frombuffer(np.asarray(values, dtype="float64").tobytes(), dtype="float64")
        cumulative = np.frombuffer(np.cumsum((0, *counts), dtype="int64").tobytes(), dtype="int64")
        object.__setattr__(self, "_ordered", ordered)
        object.__setattr__(self, "_cumulative", cumulative)
        ranks, _, _ = _empirical_rank(ordered, cumulative, ordered)
        occupancy = [0] * 7
        if len(values) > 1:
            for band, count in zip(np.searchsorted(self.policy.cutoffs, ranks, side="right"), counts):
                occupancy[int(band)] += count
        if tuple(occupancy) != analysis.band_counts:
            raise ValueError("profile band occupancy is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1, "algorithm_version": _ALGORITHM,
            "profile_id": self.profile_id, "context": self.context.to_dict(),
            "measurement": self.measurement, "policy": self.policy.to_dict(),
            "calibration_as_of_ms": self.calibration_as_of_ms, "provenance": list(self.provenance),
            "analysis": self.analysis.to_dict(), "values": list(self.values), "counts": list(self.counts),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DynamicBinningProfile:
        expected = {"schema_version", "algorithm_version", "profile_id", "context", "measurement",
                    "policy", "calibration_as_of_ms", "provenance", "analysis", "values", "counts"}
        data = dict(_keys(payload, expected, "profile"))
        if type(data.pop("schema_version")) is not int or payload["schema_version"] != 1:
            raise ValueError("unsupported profile schema version")
        if data.pop("algorithm_version") != _ALGORITHM:
            raise ValueError("unsupported profile algorithm version")
        data["context"] = VariationContext.from_dict(data["context"])
        data["policy"] = BinningPolicy.from_dict(data["policy"])
        data["analysis"] = VariationAnalysis.from_dict(data["analysis"])
        return cls(**data)


@dataclass(frozen=True, slots=True)
class BinningResult:
    profile_id: str
    context: VariationContext
    measurement: str
    mode: str
    _frame: pd.DataFrame = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))

    def to_frame(self) -> pd.DataFrame:
        """Return a defensive copy; missing outputs use pandas nullable types."""
        return self._frame.copy(deep=True)
