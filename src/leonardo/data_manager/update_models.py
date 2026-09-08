"""Immutable Data Manager reconciliation and update models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from leonardo.artifacts.models import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.financial_tools.models import UpdateStrategy

from .creation_models import (
    ArtifactCollectionRevisionV1,
    DatabaseRevisionManifest,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
)
from .models import DataManagerArtifactMaterializationResult


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_STATUSES = {
    "UNCHANGED", "APPEND_ONLY", "HISTORICAL_MUTATION", "TRUNCATED",
    "IDENTITY_MISMATCH", "INVALID_SOURCE",
}
_ARTIFACT_STATUSES = {
    "CURRENT", "APPEND_AVAILABLE", "HISTORICAL_SOURCE_CHANGED",
    "REBUILD_REQUIRED", "INVALID", "BLOCKED_BY_DEPENDENCY", "RECIPE_CHANGED",
}
_COLLECTION_STATUSES = {
    "CURRENT", "MEMBERS_REQUIRE_UPDATE", "BLOCKED_BY_DEPENDENCY",
    "PARTIALLY_ALIGNED", "REBUILD_REQUIRED", "SOURCE_INVALID",
    "DATABASE_READY", "NOT_DATABASE_READY",
}
_DATABASE_STATUSES = {
    "CURRENT", "UPDATE_AVAILABLE", "WAITING_FOR_ARTIFACT_UPDATE",
    "REBUILD_REQUIRED", "SOURCE_INVALID", "COLLECTION_CHANGED",
    "SCHEMA_CHANGED", "PREFIX_MISMATCH",
}
_DATABASE_MODES = {"CURRENT", "APPEND", "REBUILD_REQUIRED", "BLOCKED"}
_NODE_ACTIONS = {"REUSE_CURRENT", "UPDATE", "BLOCKED"}


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{name} must be {'a string' if empty else 'a non-empty string'}")
    return value


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if _SHA_RE.fullmatch(text) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 value")
    return text


def _optional_sha(value: object, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _nonnegative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _optional_timestamp(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _nonnegative(value, name)


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise TypeError("market_id must be a MarketId")
    return value


def _market_key(value: MarketId) -> tuple[str, str, str, str]:
    return (value.exchange, value.market_type, value.symbol, value.timeframe)


def _strings(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a sequence")
    result = tuple(_text(value, name) for value in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DataManagerSourceChange:
    market_id: MarketId
    status: str
    previous_source: OHLCVSourceFingerprintV1 | None
    current_source: OHLCVSourceFingerprintV1 | None
    previous_through_ms: int | None
    current_through_ms: int | None
    missing_row_count: int
    reason: str

    def __post_init__(self) -> None:
        market = _market(self.market_id)
        if self.status not in _SOURCE_STATUSES:
            raise ValueError("unsupported source-change status")
        if self.previous_source is not None and not isinstance(
            self.previous_source, OHLCVSourceFingerprintV1
        ):
            raise TypeError("previous_source must be an OHLCVSourceFingerprintV1")
        if (
            self.previous_source is not None
            and self.previous_source.market_id != market
            and self.status != "IDENTITY_MISMATCH"
        ):
            raise ValueError("previous_source must match market_id")
        if self.current_source is not None and (
            not isinstance(self.current_source, OHLCVSourceFingerprintV1)
            or self.current_source.market_id != market
        ):
            raise ValueError("current_source must match market_id")
        _optional_timestamp(self.previous_through_ms, "previous_through_ms")
        _optional_timestamp(self.current_through_ms, "current_through_ms")
        _nonnegative(self.missing_row_count, "missing_row_count")
        _text(self.reason, "reason", empty=True)


@dataclass(frozen=True, slots=True)
class DataManagerArtifactCurrentness:
    logical_artifact_id: str
    artifact_id: str
    portable_recipe_id: str
    market_id: MarketId
    status: str
    direct_staleness: bool
    artifact_through_ms: int | None
    ohlcv_through_ms: int | None
    missing_row_count: int
    dependency_logical_artifact_ids: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.logical_artifact_id, "logical_artifact_id")
        _optional_sha(self.artifact_id or None, "artifact_id")
        _optional_sha(self.portable_recipe_id or None, "portable_recipe_id")
        _market(self.market_id)
        if self.status not in _ARTIFACT_STATUSES:
            raise ValueError("unsupported Artifact-currentness status")
        if type(self.direct_staleness) is not bool:
            raise TypeError("direct_staleness must be bool")
        _optional_timestamp(self.artifact_through_ms, "artifact_through_ms")
        _optional_timestamp(self.ohlcv_through_ms, "ohlcv_through_ms")
        _nonnegative(self.missing_row_count, "missing_row_count")
        dependencies = tuple(
            sorted(_sha(value, "dependency_logical_artifact_id") for value in self.dependency_logical_artifact_ids)
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("dependency logical Artifact IDs must be unique")
        object.__setattr__(self, "dependency_logical_artifact_ids", dependencies)
        object.__setattr__(self, "reasons", tuple(sorted(str(value) for value in self.reasons)))


@dataclass(frozen=True, slots=True)
class DataManagerCollectionCurrentness:
    collection_id: str
    revision_id: str
    market_id: MarketId
    status: str
    aligned_through_ms: int | None
    ohlcv_through_ms: int | None
    stale_member_count: int
    blocked_member_count: int
    database_ready: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.collection_id, "collection_id")
        _sha(self.revision_id, "revision_id")
        _market(self.market_id)
        if self.status not in _COLLECTION_STATUSES:
            raise ValueError("unsupported Collection-currentness status")
        _optional_timestamp(self.aligned_through_ms, "aligned_through_ms")
        _optional_timestamp(self.ohlcv_through_ms, "ohlcv_through_ms")
        _nonnegative(self.stale_member_count, "stale_member_count")
        _nonnegative(self.blocked_member_count, "blocked_member_count")
        if type(self.database_ready) is not bool:
            raise TypeError("database_ready must be bool")
        object.__setattr__(self, "reasons", tuple(sorted(str(value) for value in self.reasons)))


@dataclass(frozen=True, slots=True)
class DataManagerDatabaseCurrentness:
    database_id: str
    revision_id: str
    market_id: MarketId
    status: str
    snapshot_through_ms: int | None
    ohlcv_through_ms: int | None
    collection_through_ms: int | None
    missing_row_count: int
    prefix_integrity: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.database_id, "database_id")
        _sha(self.revision_id, "revision_id")
        _market(self.market_id)
        if self.status not in _DATABASE_STATUSES:
            raise ValueError("unsupported Database-currentness status")
        _optional_timestamp(self.snapshot_through_ms, "snapshot_through_ms")
        _optional_timestamp(self.ohlcv_through_ms, "ohlcv_through_ms")
        _optional_timestamp(self.collection_through_ms, "collection_through_ms")
        _nonnegative(self.missing_row_count, "missing_row_count")
        if type(self.prefix_integrity) is not bool:
            raise TypeError("prefix_integrity must be bool")
        object.__setattr__(self, "reasons", tuple(sorted(str(value) for value in self.reasons)))


@dataclass(frozen=True, slots=True)
class DataManagerReconciliationSnapshot:
    created_at_utc: datetime
    source_changes: tuple[DataManagerSourceChange, ...]
    artifacts: tuple[DataManagerArtifactCurrentness, ...]
    collections: tuple[DataManagerCollectionCurrentness, ...]
    databases: tuple[DataManagerDatabaseCurrentness, ...]
    failures: tuple[str, ...]
    evidence_signature: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc))
        object.__setattr__(self, "source_changes", tuple(sorted(
            self.source_changes, key=lambda value: _market_key(value.market_id)
        )))
        object.__setattr__(self, "artifacts", tuple(sorted(
            self.artifacts, key=lambda value: (_market_key(value.market_id), value.logical_artifact_id)
        )))
        object.__setattr__(self, "collections", tuple(sorted(
            self.collections, key=lambda value: value.collection_id
        )))
        object.__setattr__(self, "databases", tuple(sorted(
            self.databases, key=lambda value: value.database_id
        )))
        object.__setattr__(self, "failures", tuple(sorted(str(value) for value in self.failures)))
        _sha(self.evidence_signature, "evidence_signature")


@dataclass(frozen=True, slots=True)
class ArtifactUpdateNodePlan:
    portable_recipe_id: str
    logical_artifact_id: str
    tool_key: str
    role: str
    action: str
    current_artifact_id: str | None
    dependency_logical_artifact_ids: tuple[str, ...]
    update_strategy: UpdateStrategy
    context_rows: int
    revisable_tail_rows: int
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _sha(self.portable_recipe_id, "portable_recipe_id")
        _sha(self.logical_artifact_id, "logical_artifact_id")
        _text(self.tool_key, "tool_key")
        if self.role not in {"ROOT", "SUPPORT"}:
            raise ValueError("role must be ROOT or SUPPORT")
        if self.action not in _NODE_ACTIONS:
            raise ValueError("unsupported Artifact update action")
        _optional_sha(self.current_artifact_id, "current_artifact_id")
        dependencies = tuple(
            _sha(value, "dependency_logical_artifact_id")
            for value in self.dependency_logical_artifact_ids
        )
        object.__setattr__(self, "dependency_logical_artifact_ids", dependencies)
        if not isinstance(self.update_strategy, UpdateStrategy):
            raise TypeError("update_strategy must be an UpdateStrategy")
        _nonnegative(self.context_rows, "context_rows")
        _nonnegative(self.revisable_tail_rows, "revisable_tail_rows")
        object.__setattr__(self, "blockers", tuple(sorted(str(value) for value in self.blockers)))


@dataclass(frozen=True, slots=True)
class ArtifactCollectionUpdatePlan:
    plan_id: str
    collection_id: str
    collection_revision_id: str
    market_id: MarketId
    source_change: DataManagerSourceChange
    source_ohlcv: OHLCVSourceFingerprintV1 | None
    root_recipe_ids: tuple[str, ...]
    member_recipe_ids: tuple[str, ...]
    root_logical_artifact_ids: tuple[str, ...]
    support_logical_artifact_ids: tuple[str, ...]
    starting_artifact_heads: tuple[tuple[str, str], ...]
    execution_stages: tuple[tuple[str, ...], ...]
    nodes: tuple[ArtifactUpdateNodePlan, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        _text(self.collection_id, "collection_id")
        _sha(self.collection_revision_id, "collection_revision_id")
        market = _market(self.market_id)
        if self.source_change.market_id != market:
            raise ValueError("source_change must match market_id")
        if self.source_ohlcv is not None and self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv must match market_id")
        for field_name in (
            "root_recipe_ids", "member_recipe_ids", "root_logical_artifact_ids",
            "support_logical_artifact_ids",
        ):
            values = tuple(_sha(value, field_name) for value in getattr(self, field_name))
            object.__setattr__(self, field_name, values)
        heads = tuple(sorted(
            (_sha(logical, "logical_artifact_id"), _sha(artifact, "artifact_id"))
            for logical, artifact in self.starting_artifact_heads
        ))
        object.__setattr__(self, "starting_artifact_heads", heads)
        object.__setattr__(self, "execution_stages", tuple(tuple(stage) for stage in self.execution_stages))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "blockers", tuple(sorted(str(value) for value in self.blockers)))

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True, slots=True)
class ArtifactCollectionUpdateResult:
    plan_id: str
    materialization: DataManagerArtifactMaterializationResult
    collection_revision: ArtifactCollectionRevisionV1
    reconciliation_snapshot: DataManagerReconciliationSnapshot

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        if not isinstance(self.materialization, DataManagerArtifactMaterializationResult):
            raise TypeError("materialization must be a DataManagerArtifactMaterializationResult")
        if not isinstance(self.collection_revision, ArtifactCollectionRevisionV1):
            raise TypeError("collection_revision must be an ArtifactCollectionRevisionV1")
        if not isinstance(self.reconciliation_snapshot, DataManagerReconciliationSnapshot):
            raise TypeError("reconciliation_snapshot must be a DataManagerReconciliationSnapshot")


@dataclass(frozen=True, slots=True)
class DatabaseUpdatePlan:
    plan_id: str
    database_id: str
    database_revision_id: str
    market_id: MarketId
    mode: str
    status: str
    source_change: DataManagerSourceChange
    source_ohlcv: OHLCVSourceFingerprintV1 | None
    collection_id: str | None
    collection_revision_id: str | None
    starting_artifact_heads: tuple[tuple[str, str], ...]
    column_names: tuple[str, ...]
    execution_stages: tuple[tuple[str, ...], ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        _text(self.database_id, "database_id")
        _sha(self.database_revision_id, "database_revision_id")
        market = _market(self.market_id)
        if self.mode not in _DATABASE_MODES:
            raise ValueError("unsupported Database update mode")
        if self.status not in _DATABASE_STATUSES:
            raise ValueError("unsupported Database update status")
        if self.source_change.market_id != market:
            raise ValueError("source_change must match market_id")
        if self.source_ohlcv is not None and self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv must match market_id")
        if (self.collection_id is None) != (self.collection_revision_id is None):
            raise ValueError("Database collection identity must be paired")
        if self.collection_id is not None:
            _text(self.collection_id, "collection_id")
            _sha(self.collection_revision_id, "collection_revision_id")
        object.__setattr__(self, "starting_artifact_heads", tuple(sorted(
            (_sha(logical, "logical_artifact_id"), _sha(artifact, "artifact_id"))
            for logical, artifact in self.starting_artifact_heads
        )))
        object.__setattr__(self, "column_names", _strings(self.column_names, "column_names"))
        object.__setattr__(self, "execution_stages", tuple(tuple(stage) for stage in self.execution_stages))
        object.__setattr__(self, "blockers", tuple(sorted(str(value) for value in self.blockers)))

    @property
    def blocked(self) -> bool:
        return self.mode == "BLOCKED" or bool(self.blockers)


@dataclass(frozen=True, slots=True)
class DatabaseUpdateResult:
    plan_id: str
    mode: str
    database_revision: DatabaseRevisionManifest
    reconciliation_snapshot: DataManagerReconciliationSnapshot

    def __post_init__(self) -> None:
        _sha(self.plan_id, "plan_id")
        if self.mode not in {"APPEND", "REBUILD_REQUIRED"}:
            raise ValueError("result mode must be APPEND or REBUILD_REQUIRED")
        if not isinstance(
            self.database_revision,
            (DatabaseRevisionManifestV1, DatabaseRevisionManifestV2),
        ):
            raise TypeError("database_revision must be a Database revision manifest")
        if not isinstance(self.reconciliation_snapshot, DataManagerReconciliationSnapshot):
            raise TypeError("reconciliation_snapshot must be a DataManagerReconciliationSnapshot")


__all__ = (
    "ArtifactCollectionUpdatePlan", "ArtifactCollectionUpdateResult",
    "ArtifactUpdateNodePlan", "DataManagerArtifactCurrentness",
    "DataManagerCollectionCurrentness", "DataManagerDatabaseCurrentness",
    "DataManagerReconciliationSnapshot", "DataManagerSourceChange",
    "DatabaseUpdatePlan", "DatabaseUpdateResult",
)
