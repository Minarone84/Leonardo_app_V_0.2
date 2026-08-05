from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pandas as pd

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import FinancialToolCalculationResult


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_OUTPUT_RE = re.compile(r"^[A-Za-z0-9_]+(?:__[A-Za-z0-9_]+)*$")
_KINDS = frozenset({"indicator", "oscillator", "construct"})


class ArtifactError(Exception):
    """Base error for canonical artifact and recipe operations."""


class ArtifactValidationError(ArtifactError, ValueError):
    """Persisted or supplied artifact data violates the frozen schema."""


class ArtifactNotFoundError(ArtifactError, FileNotFoundError):
    """A canonical artifact or recipe does not exist."""


class ArtifactAlreadyExistsError(ArtifactError, FileExistsError):
    """An immutable artifact already exists at its canonical identity."""


class ArtifactIdentityCollisionError(ArtifactError):
    """Existing content disagrees with content for the same identity."""


class ArtifactLineageError(ArtifactError):
    """Current source lineage cannot validate an artifact operation."""


class RecipeInUseError(ArtifactError):
    """A recipe cannot be deleted while an artifact references it."""


def _canonical_market(market_id: MarketId) -> MarketId:
    if not isinstance(market_id, MarketId):
        raise ArtifactValidationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )
    if market_id != canonical:
        raise ArtifactValidationError("market_id must already be canonical")
    return market_id


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ArtifactValidationError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_unique(values: tuple[object, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ArtifactValidationError(f"{field_name} must be unique")


def _validated_sha_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ArtifactValidationError(f"{field_name} must be a tuple")
    values = tuple(_sha256(item, field_name) for item in value)
    _require_unique(values, field_name)
    return values


def _validated_version_keys(
    value: object, field_name: str
) -> tuple[ManagedArtifactVersionKey, ...]:
    if not isinstance(value, tuple) or not all(
        isinstance(item, ManagedArtifactVersionKey) for item in value
    ):
        raise ArtifactValidationError(
            f"{field_name} must contain ManagedArtifactVersionKey values"
        )
    values = tuple(value)
    _require_unique(values, field_name)
    return values


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ArtifactValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ArtifactValidationError(f"{field_name} must be non-empty")
    return normalized


def _integer(value: object, field_name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ArtifactValidationError(f"{field_name} must be an integer")
    if minimum is not None and value < minimum:
        raise ArtifactValidationError(f"{field_name} must be >= {minimum}")
    return value


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ArtifactValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ArtifactValidationError(f"{field_name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactValidationError(f"{field_name} must be an ISO-8601 string") from exc
    return _utc(parsed, field_name)


def _freeze_json(value: object, field_name: str) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ArtifactValidationError(f"{field_name} mapping keys must be strings")
            frozen[key] = _freeze_json(item, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field_name) for item in value)
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArtifactValidationError(f"{field_name} must contain finite values")
        return value
    raise ArtifactValidationError(f"{field_name} must contain only JSON-safe finite values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return deepcopy(value)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError(f"{field_name} must be a mapping")
    frozen = _freeze_json(value, field_name)
    assert isinstance(frozen, Mapping)
    return frozen


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ArtifactValidationError(f"{field_name} must be a sequence")
    return value


def _exact_keys(data: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(data) != expected:
        raise ArtifactValidationError(
            f"{context} fields must be exactly {sorted(expected)}; got {sorted(data)}"
        )


def _market_to_dict(market_id: MarketId) -> dict[str, str]:
    return {
        "exchange": market_id.exchange,
        "market_type": market_id.market_type,
        "symbol": market_id.symbol,
        "timeframe": market_id.timeframe,
    }


def _market_from_dict(value: object) -> MarketId:
    if not isinstance(value, Mapping):
        raise ArtifactValidationError("market_id must be a mapping")
    _exact_keys(value, {"exchange", "market_type", "symbol", "timeframe"}, "market_id")
    market = MarketId(
        exchange=_text(value["exchange"], "market_id.exchange"),
        market_type=_text(value["market_type"], "market_id.market_type"),
        symbol=_text(value["symbol"], "market_id.symbol"),
        timeframe=_text(value["timeframe"], "market_id.timeframe"),
    )
    return _canonical_market(market)


def _canonical_persisted_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError("payload must be canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class OHLCVSourceFingerprintV1:
    market_id: MarketId
    csv_sha256: str
    sidecar_sha256: str
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    persistence_status: str
    validation_status: str
    sidecar_schema_version: str
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArtifactValidationError("unsupported OHLCV fingerprint schema_version")
        object.__setattr__(self, "market_id", _canonical_market(self.market_id))
        object.__setattr__(self, "csv_sha256", _sha256(self.csv_sha256, "csv_sha256"))
        object.__setattr__(self, "sidecar_sha256", _sha256(self.sidecar_sha256, "sidecar_sha256"))
        _integer(self.row_count, "row_count", minimum=1)
        _integer(self.first_timestamp_ms, "first_timestamp_ms")
        _integer(self.last_timestamp_ms, "last_timestamp_ms")
        if self.first_timestamp_ms > self.last_timestamp_ms:
            raise ArtifactValidationError("first_timestamp_ms cannot exceed last_timestamp_ms")
        if self.persistence_status not in {"committed", "repaired"}:
            raise ArtifactValidationError("persistence_status must be committed or repaired")
        if self.validation_status != "ok":
            raise ArtifactValidationError("validation_status must be ok")
        if self.sidecar_schema_version != "1.0":
            raise ArtifactValidationError("sidecar_schema_version must be 1.0")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "market_id": _market_to_dict(self.market_id),
            "csv_sha256": self.csv_sha256,
            "sidecar_sha256": self.sidecar_sha256,
            "row_count": self.row_count,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "persistence_status": self.persistence_status,
            "validation_status": self.validation_status,
            "sidecar_schema_version": self.sidecar_schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "OHLCVSourceFingerprintV1":
        expected = {
            "schema_version", "market_id", "csv_sha256", "sidecar_sha256", "row_count",
            "first_timestamp_ms", "last_timestamp_ms", "persistence_status",
            "validation_status", "sidecar_schema_version",
        }
        _exact_keys(data, expected, "OHLCVSourceFingerprintV1")
        return cls(
            schema_version=_text(data["schema_version"], "schema_version"),
            market_id=_market_from_dict(data["market_id"]),
            csv_sha256=_text(data["csv_sha256"], "csv_sha256"),
            sidecar_sha256=_text(data["sidecar_sha256"], "sidecar_sha256"),
            row_count=_integer(data["row_count"], "row_count"),
            first_timestamp_ms=_integer(data["first_timestamp_ms"], "first_timestamp_ms"),
            last_timestamp_ms=_integer(data["last_timestamp_ms"], "last_timestamp_ms"),
            persistence_status=_text(data["persistence_status"], "persistence_status"),
            validation_status=_text(data["validation_status"], "validation_status"),
            sidecar_schema_version=_text(data["sidecar_schema_version"], "sidecar_schema_version"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactSourceRefV1:
    role: str
    artifact_id: str
    output_name: str

    def __post_init__(self) -> None:
        role = _text(self.role, "role")
        output = _text(self.output_name, "output_name")
        if _ROLE_RE.fullmatch(role) is None:
            raise ArtifactValidationError("role must be a canonical source identifier")
        if _OUTPUT_RE.fullmatch(output) is None:
            raise ArtifactValidationError("output_name must be a canonical output identifier")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "output_name", output)

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "artifact_id": self.artifact_id, "output_name": self.output_name}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactSourceRefV1":
        _exact_keys(data, {"role", "artifact_id", "output_name"}, "ArtifactSourceRefV1")
        return cls(
            role=_text(data["role"], "role"),
            artifact_id=_text(data["artifact_id"], "artifact_id"),
            output_name=_text(data["output_name"], "output_name"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecipeV1:
    recipe_id: str
    market_id: MarketId
    tool_key: str
    kind: str
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    output_names: tuple[str, ...]
    source_artifacts: tuple[ArtifactSourceRefV1, ...]
    display_name: str
    description: str
    created_at_utc: datetime
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArtifactValidationError("unsupported recipe schema_version")
        market = _canonical_market(self.market_id)
        key = _text(self.tool_key, "tool_key")
        parameters = _mapping(self.parameters, "parameters")
        bindings = _mapping(self.bindings, "bindings")
        names = tuple(_text(item, "output_names item") for item in self.output_names)
        try:
            key, kind, validated_parameters, validated_bindings, names = (
                FinancialToolCalculationResult.validate_configuration(
                    tool_key=key,
                    kind=self.kind,
                    parameters=_thaw_json(parameters),
                    bindings=_thaw_json(bindings),
                    output_names=names,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactValidationError("recipe Financial Tool semantics are invalid") from exc
        parameters = _mapping(validated_parameters, "parameters")
        bindings = _mapping(validated_bindings, "bindings")
        supplied_refs = _sequence(self.source_artifacts, "source_artifacts")
        if not all(isinstance(item, ArtifactSourceRefV1) for item in supplied_refs):
            raise ArtifactValidationError("source_artifacts must contain ArtifactSourceRefV1 values")
        refs = tuple(
            sorted(supplied_refs, key=lambda item: (item.role, item.artifact_id, item.output_name))
        )
        if len({item.role for item in refs}) != len(refs):
            raise ArtifactValidationError("source artifact roles must be unique")
        created = _utc(self.created_at_utc, "created_at_utc")
        display = _text(self.display_name, "display_name")
        description = _text(self.description, "description", allow_empty=True)
        object.__setattr__(self, "recipe_id", _sha256(self.recipe_id, "recipe_id"))
        object.__setattr__(self, "market_id", market)
        object.__setattr__(self, "tool_key", key)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "output_names", names)
        object.__setattr__(self, "source_artifacts", refs)
        object.__setattr__(self, "display_name", display)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "created_at_utc", created)
        from .identity import compute_recipe_id
        if compute_recipe_id(self) != self.recipe_id:
            raise ArtifactValidationError("recipe_id does not match canonical recipe identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "market_id": _market_to_dict(self.market_id),
            "tool_key": self.tool_key,
            "kind": self.kind,
            "parameters": _thaw_json(self.parameters),
            "bindings": _thaw_json(self.bindings),
            "output_names": list(self.output_names),
            "source_artifacts": [item.to_dict() for item in self.source_artifacts],
            "display_name": self.display_name,
            "description": self.description,
            "created_at_utc": _utc_text(self.created_at_utc),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactRecipeV1":
        expected = {
            "schema_version", "recipe_id", "market_id", "tool_key", "kind", "parameters",
            "bindings", "output_names", "source_artifacts", "display_name", "description",
            "created_at_utc",
        }
        _exact_keys(data, expected, "ArtifactRecipeV1")
        refs = _sequence(data["source_artifacts"], "source_artifacts")
        names = _sequence(data["output_names"], "output_names")
        if not isinstance(data["parameters"], Mapping) or not isinstance(data["bindings"], Mapping):
            raise ArtifactValidationError("parameters and bindings must be mappings")
        return cls(
            schema_version=_text(data["schema_version"], "schema_version"),
            recipe_id=_text(data["recipe_id"], "recipe_id"),
            market_id=_market_from_dict(data["market_id"]),
            tool_key=_text(data["tool_key"], "tool_key"),
            kind=_text(data["kind"], "kind"),
            parameters=data["parameters"],
            bindings=data["bindings"],
            output_names=tuple(_text(item, "output_names item") for item in names),
            source_artifacts=tuple(
                ArtifactSourceRefV1.from_dict(item) if isinstance(item, Mapping) else _invalid_ref()
                for item in refs
            ),
            display_name=_text(data["display_name"], "display_name"),
            description=_text(data["description"], "description", allow_empty=True),
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
        )


def _invalid_ref() -> ArtifactSourceRefV1:
    raise ArtifactValidationError("source_artifacts entries must be mappings")


@dataclass(frozen=True, slots=True)
class ArtifactMetadataV1:
    artifact_id: str
    recipe: ArtifactRecipeV1
    source_ohlcv: OHLCVSourceFingerprintV1
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    values_sha256: str
    analysis_filename: str | None
    analysis_sha256: str | None
    created_at_utc: datetime
    values_filename: str = "values.csv"
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArtifactValidationError("unsupported artifact metadata schema_version")
        if not isinstance(self.recipe, ArtifactRecipeV1):
            raise ArtifactValidationError("recipe must be an ArtifactRecipeV1")
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1):
            raise ArtifactValidationError("source_ohlcv must be an OHLCVSourceFingerprintV1")
        if self.recipe.market_id != self.source_ohlcv.market_id:
            raise ArtifactValidationError("recipe and OHLCV source MarketId must match")
        _integer(self.row_count, "row_count", minimum=1)
        _integer(self.first_timestamp_ms, "first_timestamp_ms")
        _integer(self.last_timestamp_ms, "last_timestamp_ms")
        if self.first_timestamp_ms > self.last_timestamp_ms:
            raise ArtifactValidationError("first_timestamp_ms cannot exceed last_timestamp_ms")
        if (
            self.row_count != self.source_ohlcv.row_count
            or self.first_timestamp_ms != self.source_ohlcv.first_timestamp_ms
            or self.last_timestamp_ms != self.source_ohlcv.last_timestamp_ms
        ):
            raise ArtifactValidationError("artifact coverage must exactly match its OHLCV source")
        if self.values_filename != "values.csv":
            raise ArtifactValidationError("values_filename must be values.csv")
        object.__setattr__(self, "values_sha256", _sha256(self.values_sha256, "values_sha256"))
        if (self.analysis_filename is None) != (self.analysis_sha256 is None):
            raise ArtifactValidationError("analysis filename and hash must be paired")
        if self.analysis_filename is not None:
            if self.analysis_filename != "analysis.json":
                raise ArtifactValidationError("analysis_filename must be analysis.json")
            object.__setattr__(self, "analysis_sha256", _sha256(self.analysis_sha256, "analysis_sha256"))
        object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        from .identity import compute_artifact_id
        if compute_artifact_id(self) != self.artifact_id:
            raise ArtifactValidationError("artifact_id does not match canonical artifact identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "recipe": self.recipe.to_dict(),
            "source_ohlcv": self.source_ohlcv.to_dict(),
            "row_count": self.row_count,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "values_filename": self.values_filename,
            "values_sha256": self.values_sha256,
            "analysis_filename": self.analysis_filename,
            "analysis_sha256": self.analysis_sha256,
            "created_at_utc": _utc_text(self.created_at_utc),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactMetadataV1":
        expected = {
            "schema_version", "artifact_id", "recipe", "source_ohlcv", "row_count",
            "first_timestamp_ms", "last_timestamp_ms", "values_filename", "values_sha256",
            "analysis_filename", "analysis_sha256", "created_at_utc",
        }
        _exact_keys(data, expected, "ArtifactMetadataV1")
        if not isinstance(data["recipe"], Mapping) or not isinstance(data["source_ohlcv"], Mapping):
            raise ArtifactValidationError("recipe and source_ohlcv must be mappings")
        analysis_filename = data["analysis_filename"]
        analysis_sha256 = data["analysis_sha256"]
        return cls(
            schema_version=_text(data["schema_version"], "schema_version"),
            artifact_id=_text(data["artifact_id"], "artifact_id"),
            recipe=ArtifactRecipeV1.from_dict(data["recipe"]),
            source_ohlcv=OHLCVSourceFingerprintV1.from_dict(data["source_ohlcv"]),
            row_count=_integer(data["row_count"], "row_count"),
            first_timestamp_ms=_integer(data["first_timestamp_ms"], "first_timestamp_ms"),
            last_timestamp_ms=_integer(data["last_timestamp_ms"], "last_timestamp_ms"),
            values_filename=_text(data["values_filename"], "values_filename"),
            values_sha256=_text(data["values_sha256"], "values_sha256"),
            analysis_filename=None if analysis_filename is None else _text(analysis_filename, "analysis_filename"),
            analysis_sha256=None if analysis_sha256 is None else _text(analysis_sha256, "analysis_sha256"),
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactVersionRecordV1:
    logical_artifact_id: str
    artifact_id: str
    portable_recipe_id: str
    market_id: MarketId
    previous_artifact_id: str | None
    created_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "artifact_version_record"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArtifactValidationError("unsupported Artifact version schema_version")
        if self.object_type != "artifact_version_record":
            raise ArtifactValidationError("object_type must be artifact_version_record")
        logical_id = _sha256(self.logical_artifact_id, "logical_artifact_id")
        artifact_id = _sha256(self.artifact_id, "artifact_id")
        portable_id = _sha256(self.portable_recipe_id, "portable_recipe_id")
        market = _canonical_market(self.market_id)
        previous = self.previous_artifact_id
        if previous is not None:
            previous = _sha256(previous, "previous_artifact_id")
            if previous == artifact_id:
                raise ArtifactValidationError(
                    "previous_artifact_id must not equal artifact_id"
                )
        from .identity import compute_logical_artifact_id

        if compute_logical_artifact_id(market, portable_id) != logical_id:
            raise ArtifactValidationError(
                "logical_artifact_id does not match MarketId and portable Recipe"
            )
        object.__setattr__(self, "logical_artifact_id", logical_id)
        object.__setattr__(self, "artifact_id", artifact_id)
        object.__setattr__(self, "portable_recipe_id", portable_id)
        object.__setattr__(self, "market_id", market)
        object.__setattr__(self, "previous_artifact_id", previous)
        object.__setattr__(
            self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "logical_artifact_id": self.logical_artifact_id,
            "artifact_id": self.artifact_id,
            "portable_recipe_id": self.portable_recipe_id,
            "market_id": _market_to_dict(self.market_id),
            "previous_artifact_id": self.previous_artifact_id,
            "created_at_utc": _utc_text(self.created_at_utc),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactVersionRecordV1":
        expected = {
            "schema_version",
            "object_type",
            "logical_artifact_id",
            "artifact_id",
            "portable_recipe_id",
            "market_id",
            "previous_artifact_id",
            "created_at_utc",
        }
        _exact_keys(data, expected, "ArtifactVersionRecordV1")
        previous = data["previous_artifact_id"]
        return cls(
            schema_version=_text(data["schema_version"], "schema_version"),
            object_type=_text(data["object_type"], "object_type"),
            logical_artifact_id=_text(
                data["logical_artifact_id"], "logical_artifact_id"
            ),
            artifact_id=_text(data["artifact_id"], "artifact_id"),
            portable_recipe_id=_text(
                data["portable_recipe_id"], "portable_recipe_id"
            ),
            market_id=_market_from_dict(data["market_id"]),
            previous_artifact_id=(
                None
                if previous is None
                else _text(previous, "previous_artifact_id")
            ),
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
        )

    def canonical_json_bytes(self) -> bytes:
        return _canonical_persisted_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class ArtifactHeadV1:
    logical_artifact_id: str
    artifact_id: str
    updated_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "artifact_head"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0":
            raise ArtifactValidationError("unsupported Artifact head schema_version")
        if self.object_type != "artifact_head":
            raise ArtifactValidationError("object_type must be artifact_head")
        object.__setattr__(
            self,
            "logical_artifact_id",
            _sha256(self.logical_artifact_id, "logical_artifact_id"),
        )
        object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self, "updated_at_utc", _utc(self.updated_at_utc, "updated_at_utc")
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "logical_artifact_id": self.logical_artifact_id,
            "artifact_id": self.artifact_id,
            "updated_at_utc": _utc_text(self.updated_at_utc),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ArtifactHeadV1":
        expected = {
            "schema_version",
            "object_type",
            "logical_artifact_id",
            "artifact_id",
            "updated_at_utc",
        }
        _exact_keys(data, expected, "ArtifactHeadV1")
        return cls(
            schema_version=_text(data["schema_version"], "schema_version"),
            object_type=_text(data["object_type"], "object_type"),
            logical_artifact_id=_text(
                data["logical_artifact_id"], "logical_artifact_id"
            ),
            artifact_id=_text(data["artifact_id"], "artifact_id"),
            updated_at_utc=_parse_utc(data["updated_at_utc"], "updated_at_utc"),
        )

    def canonical_json_bytes(self) -> bytes:
        return _canonical_persisted_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class ManagedArtifactSummary:
    logical_artifact_id: str
    portable_recipe_id: str
    market_id: MarketId
    artifact_id: str
    previous_artifact_id: str | None
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str = ""


@dataclass(frozen=True, slots=True)
class ManagedArtifactVersionKey:
    logical_artifact_id: str
    artifact_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "logical_artifact_id",
            _sha256(self.logical_artifact_id, "logical_artifact_id"),
        )
        object.__setattr__(
            self, "artifact_id", _sha256(self.artifact_id, "artifact_id")
        )


@dataclass(frozen=True, slots=True)
class ManagedArtifactGraphPublicationResult:
    managed_artifacts: tuple[ManagedArtifactSummary, ...]
    created_artifact_ids: tuple[str, ...]
    reused_artifact_ids: tuple[str, ...]
    created_version_keys: tuple[ManagedArtifactVersionKey, ...]
    reused_version_keys: tuple[ManagedArtifactVersionKey, ...]
    advanced_logical_artifact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        managed = tuple(self.managed_artifacts)
        if not all(isinstance(item, ManagedArtifactSummary) for item in managed):
            raise ArtifactValidationError(
                "managed_artifacts must contain ManagedArtifactSummary values"
            )
        managed_logical_ids = tuple(item.logical_artifact_id for item in managed)
        _require_unique(managed_logical_ids, "managed Artifact logical IDs")
        for logical_id in managed_logical_ids:
            _sha256(logical_id, "managed logical_artifact_id")
        managed_logical_set = set(managed_logical_ids)
        managed_artifact_ids = {item.artifact_id for item in managed}
        managed_version_keys = {
            ManagedArtifactVersionKey(item.logical_artifact_id, item.artifact_id)
            for item in managed
        }

        created_ids = _validated_sha_tuple(
            self.created_artifact_ids, "created_artifact_ids"
        )
        reused_ids = _validated_sha_tuple(
            self.reused_artifact_ids, "reused_artifact_ids"
        )
        if set(created_ids) & set(reused_ids):
            raise ArtifactValidationError(
                "created and reused Artifact IDs must be disjoint"
            )
        if set(created_ids) | set(reused_ids) != managed_artifact_ids:
            raise ArtifactValidationError(
                "created and reused Artifact evidence must exactly match managed_artifacts"
            )

        created_keys = _validated_version_keys(
            self.created_version_keys, "created_version_keys"
        )
        reused_keys = _validated_version_keys(
            self.reused_version_keys, "reused_version_keys"
        )
        if set(created_keys) & set(reused_keys):
            raise ArtifactValidationError(
                "created and reused version keys must be disjoint"
            )
        if set(created_keys) | set(reused_keys) != managed_version_keys:
            raise ArtifactValidationError(
                "created and reused version-key evidence must exactly match managed_artifacts"
            )
        advanced = _validated_sha_tuple(
            self.advanced_logical_artifact_ids,
            "advanced_logical_artifact_ids",
        )
        if not set(advanced).issubset(managed_logical_set):
            raise ArtifactValidationError(
                "advanced logical Artifact IDs must belong to managed_artifacts"
            )
        object.__setattr__(self, "managed_artifacts", managed)
        object.__setattr__(self, "created_artifact_ids", created_ids)
        object.__setattr__(self, "reused_artifact_ids", reused_ids)
        object.__setattr__(self, "created_version_keys", created_keys)
        object.__setattr__(self, "reused_version_keys", reused_keys)
        object.__setattr__(self, "advanced_logical_artifact_ids", advanced)


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    market_id: MarketId
    artifact_id: str
    recipe_id: str
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecipeSummary:
    market_id: MarketId
    recipe_id: str
    tool_key: str
    kind: str
    output_names: tuple[str, ...]
    display_name: str
    created_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True, init=False)
class LoadedArtifact:
    _metadata: ArtifactMetadataV1 = field(repr=False)
    _frame: pd.DataFrame = field(repr=False)
    _analysis: dict[str, object] = field(repr=False)

    def __init__(self, metadata: ArtifactMetadataV1, frame: pd.DataFrame, analysis: Mapping[str, object]) -> None:
        object.__setattr__(self, "_metadata", ArtifactMetadataV1.from_dict(metadata.to_dict()))
        object.__setattr__(self, "_frame", frame.copy(deep=True))
        object.__setattr__(self, "_analysis", deepcopy(dict(analysis)))

    @property
    def metadata(self) -> ArtifactMetadataV1:
        return ArtifactMetadataV1.from_dict(self._metadata.to_dict())

    @property
    def frame(self) -> pd.DataFrame:
        return self._frame.copy(deep=True)

    @property
    def analysis(self) -> dict[str, object]:
        return deepcopy(self._analysis)


@dataclass(frozen=True, slots=True)
class RecipeSaveResult:
    recipe: ArtifactRecipeV1
    path: Path
    created: bool


@dataclass(frozen=True, slots=True)
class ArtifactSaveResult:
    metadata: ArtifactMetadataV1
    path: Path


def _validate_json_mapping(value: Mapping[str, object]) -> None:
    json.dumps(_thaw_json(value), allow_nan=False)
