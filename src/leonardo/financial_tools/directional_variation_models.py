"""Independent directional references owned by Financial Tools; no persistence I/O."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .variation_models import (
    VariationContext, _distribution_statistics, _empirical_rank, _finite, _integer, _keys, _text,
)

_ALGORITHM = "directional_empirical_midrank_v1"


def _bin_count(value: object, name: str) -> int:
    result = _integer(value, name, 1)
    if result > 1000:
        raise ValueError(f"{name} must be between 1 and 1000")
    return result


def _bin_indices(lower, equal, count: int, bins: int) -> np.ndarray:
    # Python integers preserve exact cutoff decisions even near the int64 limit.
    return np.fromiter((min(bins, 1 + bins * (2 * int(l) + int(e)) // (2 * count))
                        for l, e in zip(lower, equal, strict=True)), dtype="int64", count=len(lower))


def _label(direction: int, index: int) -> str:
    return f"{'P' if direction == 1 else 'N'}{index:02d}"


def _description(direction: int, index: int, count: int) -> str:
    return (f"{'Positive' if direction == 1 else 'Negative'} - bin {index} of {count} - "
            f"magnitude percentile {100 * (index - 1) / count:g} to {100 * index / count:g}")


def _same_payload(actual, expected) -> bool:
    """Canonical payload comparison also rejects booleans masquerading as counts."""
    if isinstance(expected, dict):
        return (isinstance(actual, Mapping) and set(actual) == set(expected)
                and all(_same_payload(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected)
                and all(_same_payload(a, b) for a, b in zip(actual, expected, strict=True)))
    return type(actual) is type(expected) and actual == expected


@dataclass(frozen=True, slots=True)
class DirectionalBinningPolicy:
    positive_bins: int = 10
    negative_bins: int = 10
    min_reference_count: int = 2000

    def __post_init__(self) -> None:
        for name in ("positive_bins", "negative_bins"):
            object.__setattr__(self, name, _bin_count(getattr(self, name), name))
        object.__setattr__(self, "min_reference_count", _integer(self.min_reference_count, "min_reference_count", 1))

    def to_dict(self) -> dict:
        return {"positive_bins": self.positive_bins, "negative_bins": self.negative_bins,
                "min_reference_count": self.min_reference_count, "tail_frequency_cutoffs": [0.01, 0.05]}

    @classmethod
    def from_dict(cls, payload: Mapping) -> DirectionalBinningPolicy:
        data = _keys(payload, {"positive_bins", "negative_bins", "min_reference_count", "tail_frequency_cutoffs"}, "directional policy")
        if not _same_payload(data["tail_frequency_cutoffs"], [0.01, 0.05]):
            raise ValueError("unsupported tail frequency policy")
        return cls(data["positive_bins"], data["negative_bins"], data["min_reference_count"])


@dataclass(frozen=True, slots=True)
class _DirectionalReference:
    direction: int
    bin_count: int
    min_reference_count: int
    values: tuple[float, ...]
    counts: tuple[int, ...]
    _ordered: np.ndarray = field(init=False, repr=False, compare=False)
    _cumulative: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        direction = _integer(self.direction, "direction")
        if direction not in (-1, 1):
            raise ValueError("reference direction must be -1 or 1")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "bin_count", _bin_count(self.bin_count, "bin_count"))
        object.__setattr__(self, "min_reference_count", _integer(self.min_reference_count, "min_reference_count", 1))
        values = tuple(_finite(value, "reference magnitude") for value in self.values)
        counts = tuple(_integer(count, "reference count", 1) for count in self.counts)
        if len(values) != len(counts) or any(value <= 0 for value in values) or any(a >= b for a, b in zip(values, values[1:])):
            raise ValueError("directional magnitudes must be positive, distinct and sorted with matching counts")
        _integer(sum(counts), "total reference count", 0)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "_ordered", np.frombuffer(np.asarray(values, dtype="float64").tobytes(), dtype="float64"))
        cumulative = np.cumsum((0, *counts), dtype="int64")
        object.__setattr__(self, "_cumulative", np.frombuffer(cumulative.tobytes(), dtype="int64"))

    @property
    def reference_count(self) -> int:
        return int(self._cumulative[-1])

    @property
    def status(self) -> str:
        return ("absent_reference" if not self.values else "degenerate_reference" if len(self.values) == 1
                else "limited_support" if self.reference_count < self.min_reference_count else "ready")

    def to_dict(self) -> dict:
        stats = (_distribution_statistics(self.values, self.counts) if self.values else
                 dict.fromkeys(("minimum", "maximum", "mean", "std", "q1", "median", "q3")))
        bins = [{"bin_index": index, "label": _label(self.direction, index),
                 "description": _description(self.direction, index, self.bin_count),
                 "percentile_start": 100.0 * (index - 1) / self.bin_count,
                 "percentile_end": 100.0 * index / self.bin_count,
                 "count": 0, "observed_signed_minimum": None, "observed_signed_maximum": None}
                for index in range(1, self.bin_count + 1)]
        if len(self.values) > 1:
            _, lower, equal = _empirical_rank(self._ordered, self._cumulative, self._ordered)
            for value, count, index in zip(self.values, self.counts, _bin_indices(lower, equal, self.reference_count, self.bin_count), strict=True):
                entry = bins[int(index) - 1]
                signed = self.direction * value
                entry["count"] += count
                for key, chooser in (("observed_signed_minimum", min), ("observed_signed_maximum", max)):
                    entry[key] = signed if entry[key] is None else chooser(entry[key], signed)
        occupied = sum(entry["count"] > 0 for entry in bins)
        return {"direction": self.direction, "bin_count": self.bin_count,
                "min_reference_count": self.min_reference_count,
                "values": list(self.values), "counts": list(self.counts),
                "reference_count": self.reference_count, "distinct_count": len(self.values),
                "status": self.status, "magnitude_statistics": stats,
                "occupied_bins": occupied, "empty_bins": self.bin_count - occupied, "bins": bins}

    @classmethod
    def from_dict(cls, payload: Mapping) -> _DirectionalReference:
        data = _keys(payload, {"direction", "bin_count", "min_reference_count", "values", "counts",
                              "reference_count", "distinct_count", "status", "magnitude_statistics",
                              "occupied_bins", "empty_bins", "bins"}, "directional reference")
        reference = cls(*(data[name] for name in ("direction", "bin_count", "min_reference_count", "values", "counts")))
        if not _same_payload(data, reference.to_dict()):
            raise ValueError("directional reference diagnostics contradict its distribution")
        return reference


@dataclass(frozen=True, slots=True)
class DirectionalVariationAnalysis:
    source: str
    policy: DirectionalBinningPolicy
    row_count: int
    missing_count: int
    zero_count: int
    reference_start_ms: int | None
    reference_end_ms: int | None
    positive: _DirectionalReference
    negative: _DirectionalReference

    def __post_init__(self) -> None:
        _text(self.source, "source")
        if not isinstance(self.policy, DirectionalBinningPolicy):
            raise ValueError("analysis requires a directional policy")
        for name in ("row_count", "missing_count", "zero_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), name, 0))
        for side, direction, bins in ((self.positive, 1, self.policy.positive_bins), (self.negative, -1, self.policy.negative_bins)):
            if (not isinstance(side, _DirectionalReference) or side.direction != direction
                    or side.bin_count != bins or side.min_reference_count != self.policy.min_reference_count):
                raise ValueError("analysis directional reference disagrees with its policy or sign")
        if self.row_count != self.valid_count + self.missing_count:
            raise ValueError("analysis row counts are inconsistent")
        for name in ("reference_start_ms", "reference_end_ms"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _integer(getattr(self, name), name))
        if self.row_count:
            if self.reference_start_ms is None or self.reference_end_ms is None or self.reference_start_ms > self.reference_end_ms:
                raise ValueError("nonempty analysis requires an ordered reference span")
        elif self.reference_start_ms is not None or self.reference_end_ms is not None:
            raise ValueError("empty analysis cannot have a reference span")

    @property
    def valid_count(self) -> int:
        return self.positive.reference_count + self.negative.reference_count + self.zero_count

    @property
    def reference_kind(self) -> str:
        p, n = bool(self.positive.reference_count), bool(self.negative.reference_count)
        return "mixed" if p and n else "positive_only" if p else "negative_only" if n else "zero_only" if self.zero_count else "empty"

    @property
    def status(self) -> str:
        return "available" if self.valid_count else "insufficient_reference"

    def to_dict(self) -> dict:
        total = self.valid_count
        return {"source": self.source, "policy": self.policy.to_dict(), "row_count": self.row_count,
                "valid_count": total, "missing_count": self.missing_count, "zero_count": self.zero_count,
                "positive_count": self.positive.reference_count, "negative_count": self.negative.reference_count,
                "positive_frequency": self.positive.reference_count / total if total else None,
                "negative_frequency": self.negative.reference_count / total if total else None,
                "zero_frequency": self.zero_count / total if total else None,
                "reference_start_ms": self.reference_start_ms, "reference_end_ms": self.reference_end_ms,
                "reference_kind": self.reference_kind, "status": self.status,
                "positive": self.positive.to_dict(), "negative": self.negative.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping) -> DirectionalVariationAnalysis:
        data = _keys(payload, {"source", "policy", "row_count", "valid_count", "missing_count", "zero_count",
                              "positive_count", "negative_count", "positive_frequency", "negative_frequency",
                              "zero_frequency", "reference_start_ms", "reference_end_ms", "reference_kind", "status",
                              "positive", "negative"}, "directional analysis")
        analysis = cls(data["source"], DirectionalBinningPolicy.from_dict(data["policy"]), data["row_count"],
                       data["missing_count"], data["zero_count"], data["reference_start_ms"], data["reference_end_ms"],
                       _DirectionalReference.from_dict(data["positive"]), _DirectionalReference.from_dict(data["negative"]))
        if not _same_payload(data, analysis.to_dict()):
            raise ValueError("directional analysis diagnostics contradict its references")
        return analysis


@dataclass(frozen=True, slots=True)
class DirectionalBinningProfile:
    profile_id: str
    context: VariationContext
    calibration_as_of_ms: int
    provenance: tuple[str, ...]
    analysis: DirectionalVariationAnalysis

    def __post_init__(self) -> None:
        _text(self.profile_id, "profile_id")
        if not isinstance(self.context, VariationContext) or not isinstance(self.analysis, DirectionalVariationAnalysis):
            raise ValueError("profile requires context and directional analysis")
        object.__setattr__(self, "calibration_as_of_ms", _integer(self.calibration_as_of_ms, "calibration_as_of_ms"))
        if (not self.analysis.valid_count or self.analysis.source != self.context.source
                or self.analysis.reference_end_ms > self.calibration_as_of_ms):
            raise ValueError("profile requires finite observations, matching source and valid calibration time")
        if isinstance(self.provenance, str):
            raise ValueError("provenance must be a sequence of source identifiers")
        provenance = tuple(_text(value, "provenance") for value in self.provenance)
        if not provenance or len(provenance) != len(set(provenance)):
            raise ValueError("provenance must contain unique source identifiers")
        object.__setattr__(self, "provenance", provenance)

    @property
    def policy(self) -> DirectionalBinningPolicy:
        return self.analysis.policy

    def to_dict(self) -> dict:
        return {"schema_version": 2, "algorithm_version": _ALGORITHM, "profile_id": self.profile_id,
                "context": self.context.to_dict(), "calibration_as_of_ms": self.calibration_as_of_ms,
                "provenance": list(self.provenance), "analysis": self.analysis.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping) -> DirectionalBinningProfile:
        data = _keys(payload, {"schema_version", "algorithm_version", "profile_id", "context",
                              "calibration_as_of_ms", "provenance", "analysis"}, "directional profile")
        if type(data["schema_version"]) is not int or data["schema_version"] != 2 or data["algorithm_version"] != _ALGORITHM:
            raise ValueError("unsupported directional profile version")
        return cls(data["profile_id"], VariationContext.from_dict(data["context"]), data["calibration_as_of_ms"],
                   data["provenance"], DirectionalVariationAnalysis.from_dict(data["analysis"]))


@dataclass(frozen=True, slots=True)
class DirectionalBinningResult:
    profile_id: str
    context: VariationContext
    mode: str
    _frame: pd.DataFrame = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frame", self._frame.copy(deep=True))

    def to_frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)
