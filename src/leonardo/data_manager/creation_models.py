"""Canonical persisted models for Data Manager creation workflows."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId, canonicalize_market_id


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COLLECTION_RE = re.compile(r"^ac_[0-9a-f]{32}$")
_SEED_RE = re.compile(r"^seed_[0-9a-f]{32}$")
_DATABASE_RE = re.compile(r"^db_[0-9a-f]{32}$")
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_BATCH_RAW_OHLC_COLUMNS = ("open", "high", "low", "close")
_BATCH_TOOLS = frozenset(
    {
        "derivative",
        "angle",
        "angle_momentum",
        "delta",
        "trap_area",
        "percent_span_angle",
        "braids",
        "braid_instability",
    }
)


class DataManagerCreationError(ValueError):
    """Raised when Data Manager creation truth is invalid or unavailable."""


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DataManagerCreationError(f"{name} must be a string")
    if value != value.strip() or (not empty and not value):
        raise DataManagerCreationError(f"{name} must be canonical text")
    return value


def _identifier(value: object, name: str, pattern: re.Pattern[str]) -> str:
    text = _text(value, name)
    if pattern.fullmatch(text) is None:
        raise DataManagerCreationError(f"{name} has an invalid canonical identity")
    return text


def _sha(value: object, name: str) -> str:
    return _identifier(value, name, _SHA_RE)


def _integer(value: object, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise DataManagerCreationError(f"{name} must be an integer >= {minimum}")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DataManagerCreationError(f"{name} must be timezone-aware UTC")
    if value.utcoffset().total_seconds() != 0:
        raise DataManagerCreationError(f"{name} must be UTC")
    return value.astimezone(UTC)


def _parse_utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        return _utc(datetime.fromisoformat(text.replace("Z", "+00:00")), name)
    except ValueError as exc:
        raise DataManagerCreationError(f"{name} must be an ISO UTC timestamp") from exc


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise DataManagerCreationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if canonical != value:
        raise DataManagerCreationError("market_id must already be canonical")
    return value


def _market_dict(value: MarketId) -> dict[str, str]:
    return {
        "exchange": value.exchange,
        "market_type": value.market_type,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _market_from_dict(value: object) -> MarketId:
    if not isinstance(value, Mapping) or set(value) != {
        "exchange", "market_type", "symbol", "timeframe"
    }:
        raise DataManagerCreationError("market_id fields do not match schema")
    try:
        return _market(MarketId(**dict(value)))
    except (TypeError, ValueError) as exc:
        raise DataManagerCreationError("market_id is invalid") from exc


def _json_copy(value: object, name: str = "value") -> object:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise DataManagerCreationError(f"{name} must be finite")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise DataManagerCreationError(f"{name} keys must be strings")
            result[key] = _json_copy(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [_json_copy(item, f"{name}[]") for item in value]
    raise DataManagerCreationError(f"{name} must be JSON-safe")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            _json_copy(dict(value)), sort_keys=True, indent=2, ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def deterministic_hash(value: Mapping[str, object]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _strings(value: Sequence[object], name: str, *, empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise DataManagerCreationError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in value)
    if not empty and not result:
        raise DataManagerCreationError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise DataManagerCreationError(f"{name} must contain unique values")
    return result


def _column(value: object, name: str) -> str:
    text = _text(value, name)
    if _COLUMN_RE.fullmatch(text) is None:
        raise DataManagerCreationError(f"{name} must be a canonical column name")
    return text


def _exact(data: Mapping[str, object], fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(data, Mapping) or set(data) != fields:
        raise DataManagerCreationError(f"{name} fields do not match schema")
    return dict(data)


@dataclass(frozen=True, slots=True)
class ArtifactCollectionMemberV1:
    version_key: ManagedArtifactVersionKey
    portable_recipe_id: str
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    values_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.version_key, ManagedArtifactVersionKey):
            raise TypeError("version_key must be a ManagedArtifactVersionKey")
        _sha(self.portable_recipe_id, "portable_recipe_id")
        _text(self.tool_key, "tool_key")
        _text(self.kind, "kind")
        object.__setattr__(self, "output_names", _strings(self.output_names, "output_names"))
        _sha(self.values_sha256, "values_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_artifact_id": self.version_key.logical_artifact_id,
            "artifact_id": self.version_key.artifact_id,
            "portable_recipe_id": self.portable_recipe_id,
            "tool_key": self.tool_key,
            "kind": self.kind,
            "output_names": list(self.output_names),
            "values_sha256": self.values_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArtifactCollectionMemberV1":
        data = _exact(value, {
            "logical_artifact_id", "artifact_id", "portable_recipe_id", "tool_key",
            "kind", "output_names", "values_sha256",
        }, "Artifact Collection member")
        return cls(
            ManagedArtifactVersionKey(data["logical_artifact_id"], data["artifact_id"]),
            data["portable_recipe_id"], data["tool_key"], data["kind"],
            tuple(data["output_names"]), data["values_sha256"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactCollectionDependencyV1:
    dependency_logical_artifact_id: str
    dependent_logical_artifact_id: str
    role: str
    output_name: str

    def __post_init__(self) -> None:
        _sha(self.dependency_logical_artifact_id, "dependency_logical_artifact_id")
        _sha(self.dependent_logical_artifact_id, "dependent_logical_artifact_id")
        if self.dependency_logical_artifact_id == self.dependent_logical_artifact_id:
            raise DataManagerCreationError("Artifact Collection dependency cannot be self-referential")
        _text(self.role, "role")
        _text(self.output_name, "output_name")

    def to_dict(self) -> dict[str, str]:
        return {
            "dependency_logical_artifact_id": self.dependency_logical_artifact_id,
            "dependent_logical_artifact_id": self.dependent_logical_artifact_id,
            "role": self.role,
            "output_name": self.output_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArtifactCollectionDependencyV1":
        return cls(**_exact(value, {
            "dependency_logical_artifact_id", "dependent_logical_artifact_id", "role",
            "output_name",
        }, "Artifact Collection dependency"))


@dataclass(frozen=True, slots=True)
class ArtifactCollectionOutputV1:
    logical_artifact_id: str
    output_name: str
    column_name: str

    def __post_init__(self) -> None:
        _sha(self.logical_artifact_id, "logical_artifact_id")
        _text(self.output_name, "output_name")
        _column(self.column_name, "column_name")

    def to_dict(self) -> dict[str, str]:
        return {
            "logical_artifact_id": self.logical_artifact_id,
            "output_name": self.output_name,
            "column_name": self.column_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArtifactCollectionOutputV1":
        return cls(**_exact(value, {
            "logical_artifact_id", "output_name", "column_name",
        }, "Artifact Collection output"))


@dataclass(frozen=True, slots=True)
class ArtifactCollectionSelectionPlan:
    plan_id: str
    market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    root_logical_artifact_ids: tuple[str, ...]
    support_logical_artifact_ids: tuple[str, ...]
    members: tuple[ArtifactCollectionMemberV1, ...]
    dependency_edges: tuple[ArtifactCollectionDependencyV1, ...]
    execution_stages: tuple[tuple[str, ...], ...]
    first_timestamp_ms: int
    last_timestamp_ms: int

    def __post_init__(self) -> None:
        market = _market(self.market_id)
        if (
            not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1)
            or self.source_ohlcv.market_id != market
        ):
            raise DataManagerCreationError("source_ohlcv must match market_id")
        roots = _strings(
            self.root_logical_artifact_ids, "root_logical_artifact_ids"
        )
        supports = _strings(
            self.support_logical_artifact_ids,
            "support_logical_artifact_ids",
            empty=True,
        )
        for logical_id in (*roots, *supports):
            _sha(logical_id, "logical_artifact_id")
        if set(roots) & set(supports):
            raise DataManagerCreationError(
                "root and support members must be disjoint"
            )
        members = tuple(self.members)
        if not members or not all(
            isinstance(item, ArtifactCollectionMemberV1) for item in members
        ):
            raise DataManagerCreationError(
                "members must contain ArtifactCollectionMemberV1 values"
            )
        member_ids = tuple(
            item.version_key.logical_artifact_id for item in members
        )
        if (
            len(member_ids) != len(set(member_ids))
            or set(member_ids) != set(roots) | set(supports)
        ):
            raise DataManagerCreationError(
                "member identities must exactly match root/support membership"
            )
        edges = tuple(self.dependency_edges)
        if not all(
            isinstance(item, ArtifactCollectionDependencyV1) for item in edges
        ):
            raise DataManagerCreationError(
                "dependency_edges contain invalid values"
            )
        for edge in edges:
            if (
                edge.dependency_logical_artifact_id not in member_ids
                or edge.dependent_logical_artifact_id not in member_ids
            ):
                raise DataManagerCreationError(
                    "dependency edge references a non-member Artifact"
                )
        stages = tuple(tuple(stage) for stage in self.execution_stages)
        if not stages or any(not stage for stage in stages):
            raise DataManagerCreationError(
                "execution_stages must contain non-empty stages"
            )
        staged_ids = tuple(item for stage in stages for item in stage)
        for logical_id in staged_ids:
            _sha(logical_id, "execution stage logical_artifact_id")
        if (
            len(staged_ids) != len(set(staged_ids))
            or set(staged_ids) != set(member_ids)
        ):
            raise DataManagerCreationError(
                "every member must appear exactly once in execution_stages"
            )
        stage_by_id = {
            logical_id: index
            for index, stage in enumerate(stages)
            for logical_id in stage
        }
        if any(
            stage_by_id[edge.dependency_logical_artifact_id]
            >= stage_by_id[edge.dependent_logical_artifact_id]
            for edge in edges
        ):
            raise DataManagerCreationError(
                "execution_stages must place dependencies before dependents"
            )
        first = _integer(self.first_timestamp_ms, "first_timestamp_ms")
        last = _integer(self.last_timestamp_ms, "last_timestamp_ms")
        if first > last:
            raise DataManagerCreationError(
                "Artifact Collection selection coverage is empty"
            )
        object.__setattr__(self, "root_logical_artifact_ids", roots)
        object.__setattr__(self, "support_logical_artifact_ids", supports)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(self, "execution_stages", stages)
        expected = deterministic_hash(
            {
                "market_id": _market_dict(market),
                "source_ohlcv": self.source_ohlcv.to_dict(),
                "root_logical_artifact_ids": list(roots),
                "members": [item.to_dict() for item in members],
                "dependency_edges": [item.to_dict() for item in edges],
                "execution_stages": [list(stage) for stage in stages],
                "first_timestamp_ms": first,
                "last_timestamp_ms": last,
            }
        )
        if _sha(self.plan_id, "plan_id") != expected:
            raise DataManagerCreationError(
                "plan_id does not match Artifact Collection selection truth"
            )


@dataclass(frozen=True, slots=True)
class ArtifactCollectionRevisionV1:
    collection_id: str
    revision_id: str
    display_name: str
    description: str
    market_id: MarketId
    root_logical_artifact_ids: tuple[str, ...]
    support_logical_artifact_ids: tuple[str, ...]
    members: tuple[ArtifactCollectionMemberV1, ...]
    dependency_edges: tuple[ArtifactCollectionDependencyV1, ...]
    selected_outputs: tuple[ArtifactCollectionOutputV1, ...]
    presentation_order: tuple[str, ...]
    source_portable_recipe_ids: tuple[str, ...]
    source_recipe_collection_id: str | None
    source_recipe_collection_revision_id: str | None
    source_ohlcv: OHLCVSourceFingerprintV1
    first_timestamp_ms: int
    last_timestamp_ms: int
    validation_state: str
    database_ready: bool
    previous_revision_id: str | None
    created_at_utc: datetime
    revised_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "artifact_collection_revision"

    def __post_init__(self) -> None:
        _identifier(self.collection_id, "collection_id", _COLLECTION_RE)
        _sha(self.revision_id, "revision_id")
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        market = _market(self.market_id)
        roots = _strings(self.root_logical_artifact_ids, "root_logical_artifact_ids")
        supports = _strings(self.support_logical_artifact_ids, "support_logical_artifact_ids", empty=True)
        for item in (*roots, *supports):
            _sha(item, "logical_artifact_id")
        if set(roots) & set(supports):
            raise DataManagerCreationError("root and support members must be disjoint")
        members = tuple(self.members)
        edges = tuple(self.dependency_edges)
        outputs = tuple(self.selected_outputs)
        if not members or not all(isinstance(item, ArtifactCollectionMemberV1) for item in members):
            raise DataManagerCreationError("members must contain ArtifactCollectionMemberV1 values")
        if not all(isinstance(item, ArtifactCollectionDependencyV1) for item in edges):
            raise DataManagerCreationError("dependency_edges contain invalid values")
        if not outputs or not all(isinstance(item, ArtifactCollectionOutputV1) for item in outputs):
            raise DataManagerCreationError("selected_outputs contain invalid values")
        member_ids = tuple(item.version_key.logical_artifact_id for item in members)
        if len(member_ids) != len(set(member_ids)) or set(member_ids) != set(roots) | set(supports):
            raise DataManagerCreationError("member identities must exactly match root/support membership")
        member_by_id = {item.version_key.logical_artifact_id: item for item in members}
        for edge in edges:
            if edge.dependency_logical_artifact_id not in member_by_id or edge.dependent_logical_artifact_id not in member_by_id:
                raise DataManagerCreationError("dependency edge references a non-member Artifact")
        for output in outputs:
            member = member_by_id.get(output.logical_artifact_id)
            if member is None or output.output_name not in member.output_names:
                raise DataManagerCreationError("selected output is not provided by its Artifact")
        order = _strings(self.presentation_order, "presentation_order")
        columns = tuple(item.column_name for item in outputs)
        if len(columns) != len(set(columns)) or set(order) != set(columns):
            raise DataManagerCreationError("presentation_order must exactly order unique selected columns")
        recipes = _strings(self.source_portable_recipe_ids, "source_portable_recipe_ids")
        for item in recipes:
            _sha(item, "portable_recipe_id")
        if set(recipes) != {item.portable_recipe_id for item in members}:
            raise DataManagerCreationError("source portable Recipe IDs must match members")
        if (self.source_recipe_collection_id is None) != (self.source_recipe_collection_revision_id is None):
            raise DataManagerCreationError("source Recipe Collection identity and revision must be paired")
        if self.source_recipe_collection_revision_id is not None:
            _sha(self.source_recipe_collection_revision_id, "source_recipe_collection_revision_id")
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1) or self.source_ohlcv.market_id != market:
            raise DataManagerCreationError("source_ohlcv must match market_id")
        first = _integer(self.first_timestamp_ms, "first_timestamp_ms")
        last = _integer(self.last_timestamp_ms, "last_timestamp_ms")
        if first > last:
            raise DataManagerCreationError("Artifact Collection coverage is invalid")
        if self.validation_state not in {"valid", "invalid", "stale"}:
            raise DataManagerCreationError("validation_state is invalid")
        if type(self.database_ready) is not bool:
            raise DataManagerCreationError("database_ready must be a bool")
        if self.previous_revision_id is not None:
            _sha(self.previous_revision_id, "previous_revision_id")
        created = _utc(self.created_at_utc, "created_at_utc")
        revised = _utc(self.revised_at_utc, "revised_at_utc")
        if revised < created:
            raise DataManagerCreationError("revised_at_utc cannot precede created_at_utc")
        if self.schema_version != "1.0" or self.object_type != "artifact_collection_revision":
            raise DataManagerCreationError("unsupported Artifact Collection schema")
        object.__setattr__(self, "root_logical_artifact_ids", roots)
        object.__setattr__(self, "support_logical_artifact_ids", supports)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "dependency_edges", edges)
        object.__setattr__(self, "selected_outputs", outputs)
        object.__setattr__(self, "presentation_order", order)
        object.__setattr__(self, "source_portable_recipe_ids", recipes)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "revised_at_utc", revised)
        expected = deterministic_hash(self.to_dict(include_revision_id=False))
        if self.revision_id != expected:
            raise DataManagerCreationError("revision_id does not match Artifact Collection manifest")

    def to_dict(self, *, include_revision_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "collection_id": self.collection_id,
            "display_name": self.display_name,
            "description": self.description,
            "market_id": _market_dict(self.market_id),
            "root_logical_artifact_ids": list(self.root_logical_artifact_ids),
            "support_logical_artifact_ids": list(self.support_logical_artifact_ids),
            "members": [item.to_dict() for item in self.members],
            "dependency_edges": [item.to_dict() for item in self.dependency_edges],
            "selected_outputs": [item.to_dict() for item in self.selected_outputs],
            "presentation_order": list(self.presentation_order),
            "source_portable_recipe_ids": list(self.source_portable_recipe_ids),
            "source_recipe_collection_id": self.source_recipe_collection_id,
            "source_recipe_collection_revision_id": self.source_recipe_collection_revision_id,
            "source_ohlcv": self.source_ohlcv.to_dict(),
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "validation_state": self.validation_state,
            "database_ready": self.database_ready,
            "previous_revision_id": self.previous_revision_id,
            "created_at_utc": _utc_text(self.created_at_utc),
            "revised_at_utc": _utc_text(self.revised_at_utc),
        }
        if include_revision_id:
            payload["revision_id"] = self.revision_id
        return payload

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArtifactCollectionRevisionV1":
        fields = {
            "schema_version", "object_type", "collection_id", "revision_id", "display_name",
            "description", "market_id", "root_logical_artifact_ids",
            "support_logical_artifact_ids", "members", "dependency_edges",
            "selected_outputs", "presentation_order", "source_portable_recipe_ids",
            "source_recipe_collection_id", "source_recipe_collection_revision_id",
            "source_ohlcv", "first_timestamp_ms", "last_timestamp_ms", "validation_state",
            "database_ready", "previous_revision_id", "created_at_utc", "revised_at_utc",
        }
        data = _exact(value, fields, "Artifact Collection revision")
        return cls(
            collection_id=data["collection_id"], revision_id=data["revision_id"],
            display_name=data["display_name"], description=data["description"],
            market_id=_market_from_dict(data["market_id"]),
            root_logical_artifact_ids=tuple(data["root_logical_artifact_ids"]),
            support_logical_artifact_ids=tuple(data["support_logical_artifact_ids"]),
            members=tuple(ArtifactCollectionMemberV1.from_dict(item) for item in data["members"]),
            dependency_edges=tuple(ArtifactCollectionDependencyV1.from_dict(item) for item in data["dependency_edges"]),
            selected_outputs=tuple(ArtifactCollectionOutputV1.from_dict(item) for item in data["selected_outputs"]),
            presentation_order=tuple(data["presentation_order"]),
            source_portable_recipe_ids=tuple(data["source_portable_recipe_ids"]),
            source_recipe_collection_id=data["source_recipe_collection_id"],
            source_recipe_collection_revision_id=data["source_recipe_collection_revision_id"],
            source_ohlcv=OHLCVSourceFingerprintV1.from_dict(data["source_ohlcv"]),
            first_timestamp_ms=data["first_timestamp_ms"], last_timestamp_ms=data["last_timestamp_ms"],
            validation_state=data["validation_state"], database_ready=data["database_ready"],
            previous_revision_id=data["previous_revision_id"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            revised_at_utc=_parse_utc(data["revised_at_utc"], "revised_at_utc"),
            schema_version=data["schema_version"], object_type=data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class ArtifactCollectionHeadV1:
    collection_id: str
    revision_id: str
    updated_at_utc: datetime
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        _identifier(self.collection_id, "collection_id", _COLLECTION_RE)
        _sha(self.revision_id, "revision_id")
        object.__setattr__(self, "updated_at_utc", _utc(self.updated_at_utc, "updated_at_utc"))
        if self.schema_version != "1.0":
            raise DataManagerCreationError("unsupported Artifact Collection head schema")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "collection_id": self.collection_id,
                "revision_id": self.revision_id, "updated_at_utc": _utc_text(self.updated_at_utc)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ArtifactCollectionHeadV1":
        data = _exact(value, {"schema_version", "collection_id", "revision_id", "updated_at_utc"}, "Artifact Collection head")
        return cls(data["collection_id"], data["revision_id"], _parse_utc(data["updated_at_utc"], "updated_at_utc"), data["schema_version"])


@dataclass(frozen=True, slots=True)
class ArtifactCollectionValidation:
    collection_id: str
    revision_id: str
    valid: bool
    database_ready: bool
    blockers: tuple[str, ...]
    first_usable_timestamp_ms: int | None
    last_usable_timestamp_ms: int | None
    row_count: int
    column_count: int


@dataclass(frozen=True, slots=True)
class BatchArtifactSource:
    role: str
    source_kind: str
    label: str
    output_name: str
    logical_artifact_id: str | None = None
    artifact_id: str | None = None
    market_id: MarketId | None = None
    source_ohlcv: OHLCVSourceFingerprintV1 | None = None
    column: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _text(self.role, "role"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        object.__setattr__(
            self, "output_name", _text(self.output_name, "output_name")
        )
        if self.source_kind == "artifact":
            object.__setattr__(
                self,
                "logical_artifact_id",
                _sha(self.logical_artifact_id, "logical_artifact_id"),
            )
            object.__setattr__(
                self, "artifact_id", _sha(self.artifact_id, "artifact_id")
            )
            if any(
                value is not None
                for value in (self.market_id, self.source_ohlcv, self.column)
            ):
                raise DataManagerCreationError(
                    "Artifact batch sources cannot carry current OHLCV identity"
                )
            return
        if self.source_kind != "current_ohlcv":
            raise DataManagerCreationError("source_kind is invalid")
        market = _market(self.market_id)
        if (
            not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1)
            or self.source_ohlcv.market_id != market
        ):
            raise DataManagerCreationError(
                "current OHLCV source fingerprint must match market_id"
            )
        if self.column not in _BATCH_RAW_OHLC_COLUMNS:
            raise DataManagerCreationError(
                "current OHLCV column must be open, high, low, or close"
            )
        if self.output_name != self.column:
            raise DataManagerCreationError(
                "current OHLCV output_name must match column"
            )
        if self.label != self.column.title():
            raise DataManagerCreationError(
                "current OHLCV label must match its canonical column"
            )
        if self.logical_artifact_id is not None or self.artifact_id is not None:
            raise DataManagerCreationError(
                "current OHLCV sources cannot carry Artifact identity"
            )
        object.__setattr__(self, "market_id", market)

    @classmethod
    def from_artifact(
        cls,
        source: "DataManagerDirectArtifactSource",
        *,
        label: str | None = None,
    ) -> "BatchArtifactSource":
        from .direct_artifact import DataManagerDirectArtifactSource

        if not isinstance(source, DataManagerDirectArtifactSource):
            raise TypeError("source must be a DataManagerDirectArtifactSource")
        return cls(
            role=source.role,
            source_kind="artifact",
            label=label
            or f"{source.output_name} [{source.logical_artifact_id[:8]}]",
            output_name=source.output_name,
            logical_artifact_id=source.logical_artifact_id,
            artifact_id=source.artifact_id,
        )

    @classmethod
    def current_ohlcv(
        cls,
        role: str,
        market_id: MarketId,
        source_ohlcv: OHLCVSourceFingerprintV1,
        column: str,
    ) -> "BatchArtifactSource":
        label = column.title() if isinstance(column, str) else ""
        return cls(
            role=role,
            source_kind="current_ohlcv",
            label=label,
            output_name=column,
            market_id=market_id,
            source_ohlcv=source_ohlcv,
            column=column,
        )


@dataclass(frozen=True, slots=True)
class BatchArtifactBranchRequest:
    tool_key: str
    parameters: Mapping[str, object]
    sources: tuple[BatchArtifactSource, ...]
    requested_outputs: tuple[str, ...]

    def __post_init__(self) -> None:
        from .direct_artifact import DataManagerDirectArtifactSource

        if self.tool_key not in _BATCH_TOOLS:
            raise DataManagerCreationError("tool_key is not a supported batch Construct")
        copied = _json_copy(dict(self.parameters), "parameters")
        sources = tuple(
            item
            if isinstance(item, BatchArtifactSource)
            else BatchArtifactSource.from_artifact(item)
            if isinstance(item, DataManagerDirectArtifactSource)
            else item
            for item in self.sources
        )
        if not sources or not all(isinstance(item, BatchArtifactSource) for item in sources):
            raise DataManagerCreationError(
                "sources must contain exact batch source values"
            )
        if len({item.role for item in sources}) != len(sources):
            raise DataManagerCreationError("batch source roles must be unique")
        object.__setattr__(self, "parameters", _freeze(copied))
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "requested_outputs", _strings(self.requested_outputs, "requested_outputs"))


@dataclass(frozen=True, slots=True)
class BatchArtifactRequest:
    market_id: MarketId
    expected_source_ohlcv: OHLCVSourceFingerprintV1
    branches: tuple[BatchArtifactBranchRequest, ...]
    destination: str
    collection_id: str | None = None

    def __post_init__(self) -> None:
        market = _market(self.market_id)
        if not isinstance(self.expected_source_ohlcv, OHLCVSourceFingerprintV1):
            raise DataManagerCreationError(
                "expected_source_ohlcv must be an OHLCVSourceFingerprintV1"
            )
        if self.expected_source_ohlcv.market_id != market:
            raise DataManagerCreationError(
                "expected_source_ohlcv MarketId must match market_id"
            )
        branches = tuple(self.branches)
        if not branches or not all(isinstance(item, BatchArtifactBranchRequest) for item in branches):
            raise DataManagerCreationError("branches must contain explicit batch branches")
        if self.destination not in {"individual", "new_collection", "collection_revision"}:
            raise DataManagerCreationError("destination is invalid")
        if (self.destination == "collection_revision") != (self.collection_id is not None):
            raise DataManagerCreationError("collection_revision destination requires collection_id")
        if self.collection_id is not None:
            _identifier(self.collection_id, "collection_id", _COLLECTION_RE)
        object.__setattr__(self, "branches", branches)


@dataclass(frozen=True, slots=True)
class BatchArtifactPlan:
    request: BatchArtifactRequest
    branch_recipe_ids: tuple[str, ...]
    branch_reuse_current: tuple[bool, ...]
    recipe_ids: tuple[str, ...]
    dependency_edges: tuple[tuple[str, str, str, str], ...]
    execution_stages: tuple[tuple[str, ...], ...]
    new_recipe_ids: tuple[str, ...]
    reusable_recipe_ids: tuple[str, ...]
    new_logical_artifact_ids: tuple[str, ...]
    reusable_logical_artifact_ids: tuple[str, ...]
    naming_collisions: tuple[str, ...]
    unsupported_combinations: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        branch_recipe_ids = tuple(self.branch_recipe_ids)
        branch_reuse_current = tuple(self.branch_reuse_current)
        if len(branch_recipe_ids) != len(self.request.branches):
            raise DataManagerCreationError(
                "branch_recipe_ids must align with request branches"
            )
        if len(branch_reuse_current) != len(self.request.branches) or any(
            type(value) is not bool for value in branch_reuse_current
        ):
            raise DataManagerCreationError(
                "branch_reuse_current must align with request branches"
            )
        for recipe_id in branch_recipe_ids:
            _sha(recipe_id, "branch_recipe_id")
        object.__setattr__(self, "branch_recipe_ids", branch_recipe_ids)
        object.__setattr__(self, "branch_reuse_current", branch_reuse_current)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers or self.naming_collisions or self.unsupported_combinations)


@dataclass(frozen=True, slots=True)
class DatabaseSeedV1:
    seed_id: str
    display_name: str
    description: str
    market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    source_row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    selected_ohlcv_columns: tuple[str, ...]
    selected_range_start_ms: int
    selected_range_end_ms: int
    created_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "database_seed"

    def __post_init__(self) -> None:
        _identifier(self.seed_id, "seed_id", _SEED_RE)
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        market = _market(self.market_id)
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1) or self.source_ohlcv.market_id != market:
            raise DataManagerCreationError("source_ohlcv must match market_id")
        _integer(self.source_row_count, "source_row_count", minimum=1)
        first = _integer(self.first_timestamp_ms, "first_timestamp_ms")
        last = _integer(self.last_timestamp_ms, "last_timestamp_ms")
        start = _integer(self.selected_range_start_ms, "selected_range_start_ms")
        end = _integer(self.selected_range_end_ms, "selected_range_end_ms")
        if not first <= start <= end <= last:
            raise DataManagerCreationError("selected source range must be inside source coverage")
        columns = _strings(self.selected_ohlcv_columns, "selected_ohlcv_columns")
        if any(item not in _OHLCV_COLUMNS for item in columns):
            raise DataManagerCreationError("selected_ohlcv_columns contain unsupported values")
        object.__setattr__(self, "selected_ohlcv_columns", columns)
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        if self.schema_version != "1.0" or self.object_type != "database_seed":
            raise DataManagerCreationError("unsupported Database Seed schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "object_type": self.object_type,
            "seed_id": self.seed_id, "display_name": self.display_name,
            "description": self.description, "market_id": _market_dict(self.market_id),
            "source_ohlcv": self.source_ohlcv.to_dict(), "source_row_count": self.source_row_count,
            "first_timestamp_ms": self.first_timestamp_ms, "last_timestamp_ms": self.last_timestamp_ms,
            "selected_ohlcv_columns": list(self.selected_ohlcv_columns),
            "selected_range_start_ms": self.selected_range_start_ms,
            "selected_range_end_ms": self.selected_range_end_ms,
            "created_at_utc": _utc_text(self.created_at_utc),
        }

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DatabaseSeedV1":
        fields = {"schema_version", "object_type", "seed_id", "display_name", "description",
                  "market_id", "source_ohlcv", "source_row_count", "first_timestamp_ms",
                  "last_timestamp_ms", "selected_ohlcv_columns", "selected_range_start_ms",
                  "selected_range_end_ms", "created_at_utc"}
        data = _exact(value, fields, "Database Seed")
        return cls(
            seed_id=data["seed_id"], display_name=data["display_name"], description=data["description"],
            market_id=_market_from_dict(data["market_id"]),
            source_ohlcv=OHLCVSourceFingerprintV1.from_dict(data["source_ohlcv"]),
            source_row_count=data["source_row_count"], first_timestamp_ms=data["first_timestamp_ms"],
            last_timestamp_ms=data["last_timestamp_ms"],
            selected_ohlcv_columns=tuple(data["selected_ohlcv_columns"]),
            selected_range_start_ms=data["selected_range_start_ms"],
            selected_range_end_ms=data["selected_range_end_ms"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            schema_version=data["schema_version"], object_type=data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    seed_id: str
    collection_id: str
    collection_revision_id: str
    ready: bool
    blockers: tuple[str, ...]
    first_usable_timestamp_ms: int | None
    last_usable_timestamp_ms: int | None
    row_count: int
    column_count: int
    column_names: tuple[str, ...]
    warmup_excluded_rows: int


@dataclass(frozen=True, slots=True)
class DatabaseDefinitionV1:
    database_id: str
    display_name: str
    description: str
    market_id: MarketId
    seed_id: str
    created_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "database_definition"

    def __post_init__(self) -> None:
        _identifier(self.database_id, "database_id", _DATABASE_RE)
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        _market(self.market_id)
        _identifier(self.seed_id, "seed_id", _SEED_RE)
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        if self.schema_version != "1.0" or self.object_type != "database_definition":
            raise DataManagerCreationError("unsupported Database definition schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "object_type": self.object_type,
            "database_id": self.database_id, "display_name": self.display_name,
            "description": self.description, "market_id": _market_dict(self.market_id),
            "seed_id": self.seed_id, "created_at_utc": _utc_text(self.created_at_utc),
        }

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DatabaseDefinitionV1":
        data = _exact(value, {
            "schema_version", "object_type", "database_id", "display_name",
            "description", "market_id", "seed_id", "created_at_utc",
        }, "Database definition")
        return cls(
            data["database_id"], data["display_name"], data["description"],
            _market_from_dict(data["market_id"]), data["seed_id"],
            _parse_utc(data["created_at_utc"], "created_at_utc"),
            data["schema_version"], data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class DatabaseRevisionManifestV1:
    database_id: str
    revision_id: str
    display_name: str
    description: str
    seed_id: str
    market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    collection_id: str
    collection_revision_id: str
    collection_manifest_hash: str
    artifact_version_keys: tuple[ManagedArtifactVersionKey, ...]
    artifact_payload_hashes: tuple[str, ...]
    portable_recipe_ids: tuple[str, ...]
    column_mapping: Mapping[str, str]
    first_timestamp_ms: int
    last_timestamp_ms: int
    row_count: int
    column_count: int
    values_sha256: str
    previous_revision_id: str | None
    created_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "database_revision"

    def __post_init__(self) -> None:
        _identifier(self.database_id, "database_id", _DATABASE_RE)
        _sha(self.revision_id, "revision_id")
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        _identifier(self.seed_id, "seed_id", _SEED_RE)
        market = _market(self.market_id)
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1) or self.source_ohlcv.market_id != market:
            raise DataManagerCreationError("source_ohlcv must match market_id")
        _identifier(self.collection_id, "collection_id", _COLLECTION_RE)
        _sha(self.collection_revision_id, "collection_revision_id")
        _sha(self.collection_manifest_hash, "collection_manifest_hash")
        keys = tuple(self.artifact_version_keys)
        if not keys or not all(isinstance(item, ManagedArtifactVersionKey) for item in keys):
            raise DataManagerCreationError("artifact_version_keys are invalid")
        hashes = _strings(self.artifact_payload_hashes, "artifact_payload_hashes")
        recipes = _strings(self.portable_recipe_ids, "portable_recipe_ids")
        for value in (*hashes, *recipes):
            _sha(value, "SHA-256 identity")
        if len(keys) != len(hashes):
            raise DataManagerCreationError("Artifact keys and payload hashes must align")
        mapping = _json_copy(dict(self.column_mapping), "column_mapping")
        if not isinstance(mapping, dict) or not mapping:
            raise DataManagerCreationError("column_mapping must not be empty")
        for key, value in mapping.items():
            _column(key, "column_mapping key")
            _column(value, "column_mapping value")
        first = _integer(self.first_timestamp_ms, "first_timestamp_ms")
        last = _integer(self.last_timestamp_ms, "last_timestamp_ms")
        if first > last:
            raise DataManagerCreationError("Database coverage is invalid")
        _integer(self.row_count, "row_count", minimum=1)
        _integer(self.column_count, "column_count", minimum=2)
        _sha(self.values_sha256, "values_sha256")
        if self.previous_revision_id is not None:
            _sha(self.previous_revision_id, "previous_revision_id")
        object.__setattr__(self, "artifact_version_keys", keys)
        object.__setattr__(self, "artifact_payload_hashes", hashes)
        object.__setattr__(self, "portable_recipe_ids", recipes)
        object.__setattr__(self, "column_mapping", _freeze(mapping))
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        if self.schema_version != "1.0" or self.object_type != "database_revision":
            raise DataManagerCreationError("unsupported Database revision schema")
        if self.revision_id != deterministic_hash(self.to_dict(include_revision_id=False)):
            raise DataManagerCreationError("revision_id does not match Database manifest")

    def to_dict(self, *, include_revision_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version, "object_type": self.object_type,
            "database_id": self.database_id, "display_name": self.display_name,
            "description": self.description, "seed_id": self.seed_id,
            "market_id": _market_dict(self.market_id), "source_ohlcv": self.source_ohlcv.to_dict(),
            "collection_id": self.collection_id,
            "collection_revision_id": self.collection_revision_id,
            "collection_manifest_hash": self.collection_manifest_hash,
            "artifact_version_keys": [
                {"logical_artifact_id": item.logical_artifact_id, "artifact_id": item.artifact_id}
                for item in self.artifact_version_keys
            ],
            "artifact_payload_hashes": list(self.artifact_payload_hashes),
            "portable_recipe_ids": list(self.portable_recipe_ids),
            "column_mapping": _thaw(self.column_mapping),
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "row_count": self.row_count, "column_count": self.column_count,
            "values_sha256": self.values_sha256,
            "previous_revision_id": self.previous_revision_id,
            "created_at_utc": _utc_text(self.created_at_utc),
        }
        if include_revision_id:
            payload["revision_id"] = self.revision_id
        return payload

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DatabaseRevisionManifestV1":
        fields = {"schema_version", "object_type", "database_id", "revision_id", "display_name",
                  "description", "seed_id", "market_id", "source_ohlcv", "collection_id",
                  "collection_revision_id", "collection_manifest_hash", "artifact_version_keys",
                  "artifact_payload_hashes", "portable_recipe_ids", "column_mapping",
                  "first_timestamp_ms", "last_timestamp_ms", "row_count", "column_count",
                  "values_sha256", "previous_revision_id", "created_at_utc"}
        data = _exact(value, fields, "Database revision")
        return cls(
            database_id=data["database_id"], revision_id=data["revision_id"],
            display_name=data["display_name"], description=data["description"], seed_id=data["seed_id"],
            market_id=_market_from_dict(data["market_id"]),
            source_ohlcv=OHLCVSourceFingerprintV1.from_dict(data["source_ohlcv"]),
            collection_id=data["collection_id"], collection_revision_id=data["collection_revision_id"],
            collection_manifest_hash=data["collection_manifest_hash"],
            artifact_version_keys=tuple(ManagedArtifactVersionKey(item["logical_artifact_id"], item["artifact_id"]) for item in data["artifact_version_keys"]),
            artifact_payload_hashes=tuple(data["artifact_payload_hashes"]),
            portable_recipe_ids=tuple(data["portable_recipe_ids"]),
            column_mapping=data["column_mapping"], first_timestamp_ms=data["first_timestamp_ms"],
            last_timestamp_ms=data["last_timestamp_ms"], row_count=data["row_count"],
            column_count=data["column_count"], values_sha256=data["values_sha256"],
            previous_revision_id=data["previous_revision_id"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            schema_version=data["schema_version"], object_type=data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class DatabaseHeadV1:
    database_id: str
    revision_id: str
    updated_at_utc: datetime
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        _identifier(self.database_id, "database_id", _DATABASE_RE)
        _sha(self.revision_id, "revision_id")
        object.__setattr__(self, "updated_at_utc", _utc(self.updated_at_utc, "updated_at_utc"))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "database_id": self.database_id,
                "revision_id": self.revision_id, "updated_at_utc": _utc_text(self.updated_at_utc)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DatabaseHeadV1":
        data = _exact(value, {"schema_version", "database_id", "revision_id", "updated_at_utc"}, "Database head")
        return cls(data["database_id"], data["revision_id"], _parse_utc(data["updated_at_utc"], "updated_at_utc"), data["schema_version"])


@dataclass(frozen=True, slots=True)
class LoadedDatabaseRevision:
    manifest: DatabaseRevisionManifestV1
    values_csv: bytes
