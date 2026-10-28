"""Disposable Analysis requests and read models; no persisted schema."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping

import pandas as pd

from leonardo.data import MarketId
from leonardo.financial_tools import BinningPolicy, DirectionalBinningPolicy


@dataclass(frozen=True, slots=True)
class DatabaseReference:
    database_id: str
    revision_id: str
    values_sha256: str

    def __post_init__(self):
        for value, pattern in ((self.database_id, r"db_[0-9a-f]{32}"), (self.revision_id, r"[0-9a-f]{64}"),
                               (self.values_sha256, r"[0-9a-f]{64}")):
            if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
                raise ValueError("database reference requires canonical identities")


@dataclass(frozen=True, slots=True)
class DatabaseEntry:
    reference: DatabaseReference
    name: str
    market_id: MarketId
    rows: int
    columns: int
    first_timestamp_ms: int
    last_timestamp_ms: int


@dataclass(frozen=True, slots=True)
class DatabaseCatalog:
    entries: tuple[DatabaseEntry, ...]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisColumn:
    name: str
    eligible: bool
    reason: str
    definition: str
    parameter_version: str
    unit: str = "unspecified_database_native_unit"
    type_known: bool = False


@dataclass(frozen=True, slots=True)
class DatabaseColumns:
    entry: DatabaseEntry
    columns: tuple[AnalysisColumn, ...]


@dataclass(frozen=True, slots=True)
class ColumnRequest:
    source: str
    measurement: str
    policy: BinningPolicy | DirectionalBinningPolicy
    override: bool = False

    def __post_init__(self):
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("column source must be nonempty")
        if self.measurement not in ("directional_intensity", "value", "magnitude"):
            raise ValueError("unsupported measurement")
        expected = DirectionalBinningPolicy if self.measurement == "directional_intensity" else BinningPolicy
        if not isinstance(self.policy, expected) or type(self.override) is not bool:
            raise ValueError("column policy or override disagrees with measurement")

    @classmethod
    def from_settings(cls, settings: Mapping):
        mode = settings["measurement"]
        common = {"source", "measurement", "override", "min_reference_count"}
        expected = common | ({"positive_bins", "negative_bins"} if mode == "directional_intensity" else {"cutoffs"})
        if set(settings) != expected:
            raise ValueError("column settings fields disagree with measurement")
        policy = (DirectionalBinningPolicy(settings["positive_bins"], settings["negative_bins"], settings["min_reference_count"])
                  if mode == "directional_intensity" else
                  BinningPolicy(tuple(settings["cutoffs"]), settings["min_reference_count"]))
        return cls(settings["source"], mode, policy, settings["override"])


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    reference: DatabaseReference
    columns: tuple[ColumnRequest, ...]

    def __post_init__(self):
        if not isinstance(self.reference, DatabaseReference):
            raise TypeError("request requires a database reference")
        columns = tuple(self.columns)
        if not columns or any(not isinstance(c, ColumnRequest) for c in columns):
            raise ValueError("select at least one valid column")
        if len({c.source for c in columns}) != len(columns):
            raise ValueError("selected columns must be unique")
        object.__setattr__(self, "columns", columns)

    @classmethod
    def from_configuration(cls, reference: DatabaseReference, configuration: Mapping):
        if (set(configuration) != {"database_id", "reference", "columns"}
                or configuration["database_id"] != reference.database_id
                or configuration["reference"] != "full_history"):
            raise ValueError("configuration must identify this database and full history")
        return cls(reference, tuple(ColumnRequest.from_settings(c) for c in configuration["columns"]))


@dataclass(frozen=True, slots=True)
class DistributionDisplay:
    points: tuple[tuple[float, float], ...]
    distinct_count: int
    finite_count: int

    @property
    def reduced(self):
        return len(self.points) < self.distinct_count


@dataclass(frozen=True, slots=True)
class BinDisplay:
    direction: str
    label: str
    percentile_start: float
    percentile_end: float
    count: int
    observed_minimum: float | None
    observed_maximum: float | None
    support: str


@dataclass(frozen=True, slots=True)
class ColumnAnalysis:
    request: ColumnRequest
    column: AnalysisColumn
    profile: object | None
    outcome: str
    distribution: DistributionDisplay
    bins: tuple[BinDisplay, ...]
    diagnostics: tuple[tuple[str, object], ...]
    _frame: pd.DataFrame = field(repr=False, compare=False)

    def to_frame(self):
        return self._frame.copy(deep=True)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    entry: DatabaseEntry
    snapshot_read_ms: int
    columns: tuple[ColumnAnalysis, ...]

    @property
    def has_issues(self):
        return any(c.outcome != "completed" for c in self.columns)


@dataclass(frozen=True, slots=True)
class DatabaseUtcClassification:
    """Pinned revision-owned evidence; all returned containers are detached."""

    reference: DatabaseReference
    _payload: bytes | None = field(repr=False)

    @property
    def status(self):
        return "available" if self._payload is not None else "legacy_unavailable"

    def to_dict(self):
        import json
        return json.loads(self._payload) if self._payload is not None else {
            "schema_version": "1.0", "reports": {}, "associations": []
        }

    def report(self, artifact_id):
        from leonardo.financial_tools import UtcClassificationResult
        payload = self.to_dict()
        matches = [a for a in payload["associations"] if a["artifact_id"] == artifact_id]
        if not matches:
            raise KeyError("UTC Artifact is not part of this database revision")
        digests = {a["report_sha256"] for a in matches}
        if len(digests) != 1:
            raise ValueError("UTC physical Artifact has conflicting reports")
        analysis = payload["reports"][matches[0]["report_sha256"]]
        return (UtcClassificationResult.from_dict(analysis["utc_classification"])
                if analysis else None)

    def metrics(self, artifact_id):
        from leonardo.financial_tools import UtcEpisodeMetricsResult
        payload = self.to_dict()
        matches = [a for a in payload["associations"] if a["artifact_id"] == artifact_id]
        if not matches:
            raise KeyError("UTC Artifact is not part of this database revision")
        if len({a["report_sha256"] for a in matches}) != 1:
            raise ValueError("UTC physical Artifact has conflicting reports")
        analysis = payload["reports"][matches[0]["report_sha256"]]
        return (UtcEpisodeMetricsResult.from_dict(analysis["utc_episode_metrics"],
                                                 classification=analysis["utc_classification"])
                if "utc_episode_metrics" in analysis else None)

    def associations_frame(self):
        return pd.DataFrame(self.to_dict()["associations"], dtype=object)
