"""Versioned persisted models for globally portable Recipes."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import canonicalize_tool_key, get_financial_tool_spec

from .identity import (
    compute_portable_recipe_collection_revision_id,
    compute_portable_recipe_id,
    compute_portable_recipe_origin_id,
    compute_portable_recipe_provenance_id,
)


_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COLLECTION_RE = re.compile(r"^prc_[0-9a-f]{32}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})
_ORIGIN_REQUIRED_DETAIL_KEYS = {
    "study_environment": frozenset(
        {"environment_id", "environment_content_hash", "entry_id"}
    ),
    "research_save": frozenset(),
    "data_manager_artifact": frozenset(),
}
_ORIGIN_ALLOWED_DETAIL_KEYS = {
    **_ORIGIN_REQUIRED_DETAIL_KEYS,
    "research_save": frozenset({"study_id"}),
}


class PortableRecipeValidationError(ValueError):
    """Raised when portable Recipe persisted truth is invalid."""


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PortableRecipeValidationError(f"{name} must be a string")
    if not empty and (not value or value != value.strip()):
        raise PortableRecipeValidationError(f"{name} must be canonical non-empty text")
    if empty and value != value.strip():
        raise PortableRecipeValidationError(f"{name} must be canonical text")
    return value


def _role(value: object, name: str = "role") -> str:
    text = _text(value, name)
    if _ROLE_RE.fullmatch(text) is None:
        raise PortableRecipeValidationError(f"{name} must be a canonical role")
    return text


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if _ID_RE.fullmatch(text) is None:
        raise PortableRecipeValidationError(f"{name} must be a canonical identifier")
    return text


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if _SHA_RE.fullmatch(text) is None:
        raise PortableRecipeValidationError(f"{name} must be a lowercase SHA-256")
    return text


def _collection_id(value: object) -> str:
    text = _text(value, "collection_id")
    if _COLLECTION_RE.fullmatch(text) is None:
        raise PortableRecipeValidationError("collection_id must match prc_<32 lowercase hex>")
    return text


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PortableRecipeValidationError(f"{name} must be timezone-aware UTC")
    if value.utcoffset().total_seconds() != 0:
        raise PortableRecipeValidationError(f"{name} must be UTC")
    return value.astimezone(UTC)


def _parse_utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PortableRecipeValidationError(f"{name} must be an ISO UTC timestamp") from exc
    return _utc(parsed, name)


def _json_copy(value: object, name: str) -> object:
    def copy(item: object, path: str) -> object:
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise PortableRecipeValidationError(f"{path} must be finite")
            return item
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise PortableRecipeValidationError(f"{path} keys must be strings")
                result[key] = copy(nested, f"{path}.{key}")
            return result
        if isinstance(item, (list, tuple)):
            return [copy(nested, f"{path}[]") for nested in item]
        raise PortableRecipeValidationError(f"{path} is not JSON-safe")

    return copy(value, name)


def _frozen_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PortableRecipeValidationError(f"{name} must be a mapping")
    copied = _json_copy(dict(value), name)
    assert isinstance(copied, dict)
    return _freeze_json(copied)  # type: ignore[return-value]


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _exact(value: Mapping[str, object], expected: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PortableRecipeValidationError(f"{name} must be a mapping")
    data = dict(value)
    if set(data) != expected:
        raise PortableRecipeValidationError(f"{name} fields do not match schema")
    return data


def _string_tuple(value: object, name: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PortableRecipeValidationError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in value)
    if nonempty and not result:
        raise PortableRecipeValidationError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise PortableRecipeValidationError(f"{name} must be unique")
    return result


def _persisted_array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise PortableRecipeValidationError(f"{name} must be a JSON array")
    return value


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise PortableRecipeValidationError("origin_market_id must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if canonical != value:
        raise PortableRecipeValidationError("origin_market_id must already be canonical")
    return value


def _market_dict(value: MarketId) -> dict[str, str]:
    return {
        "exchange": value.exchange,
        "market_type": value.market_type,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _market_from_dict(value: object) -> MarketId:
    data = _exact(
        value,  # type: ignore[arg-type]
        {"exchange", "market_type", "symbol", "timeframe"},
        "origin_market_id",
    )
    try:
        market = MarketId(
            data["exchange"], data["market_type"], data["symbol"], data["timeframe"]
        )
    except (TypeError, ValueError) as exc:
        raise PortableRecipeValidationError(
            "origin_market_id fields must be valid strings"
        ) from exc
    return _market(market)


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                _json_copy(dict(value), "payload"),
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PortableRecipeValidationError("payload is not canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class PortableRecipeOHLCVInputV1:
    role: str
    column_name: str

    def __post_init__(self) -> None:
        _role(self.role)
        if self.column_name not in _OHLCV_COLUMNS:
            raise PortableRecipeValidationError("column_name is not a canonical OHLCV column")

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role, "column_name": self.column_name}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeOHLCVInputV1":
        return cls(**_exact(value, {"role", "column_name"}, "OHLCV input"))


@dataclass(frozen=True, slots=True)
class PortableRecipeDependencyV1:
    role: str
    recipe_id: str
    output_name: str

    def __post_init__(self) -> None:
        _role(self.role)
        _sha(self.recipe_id, "recipe_id")
        _text(self.output_name, "output_name")

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "recipe_id": self.recipe_id,
            "output_name": self.output_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeDependencyV1":
        return cls(
            **_exact(value, {"role", "recipe_id", "output_name"}, "dependency")
        )


@dataclass(frozen=True, slots=True)
class PortableRecipeV1:
    recipe_id: str
    tool_key: str
    tool_version: str
    kind: str
    parameters: Mapping[str, object]
    output_names: tuple[str, ...]
    ohlcv_inputs: tuple[PortableRecipeOHLCVInputV1, ...]
    dependencies: tuple[PortableRecipeDependencyV1, ...]
    schema_version: str = "1.0"
    object_type: str = "portable_recipe"

    def __post_init__(self) -> None:
        _sha(self.recipe_id, "recipe_id")
        key = _text(self.tool_key, "tool_key")
        if canonicalize_tool_key(key) != key:
            raise PortableRecipeValidationError("tool_key must already be canonical")
        try:
            spec = get_financial_tool_spec(key)
        except KeyError as exc:
            raise PortableRecipeValidationError("tool_key is not in the Financial Tool catalog") from exc
        if key == "dynamic_binning":
            raise PortableRecipeValidationError("dynamic_binning is not a portable Recipe")
        if self.kind != spec.kind:
            raise PortableRecipeValidationError("kind must match the Financial Tool specification")
        if self.tool_version != "1.0":
            raise PortableRecipeValidationError("tool_version must equal '1.0'")
        if self.schema_version != "1.0" or self.object_type != "portable_recipe":
            raise PortableRecipeValidationError("unsupported portable Recipe schema")
        parameters = _frozen_mapping(self.parameters, "parameters")
        outputs = _string_tuple(self.output_names, "output_names")
        ohlcv = tuple(self.ohlcv_inputs)
        dependencies = tuple(self.dependencies)
        if not all(isinstance(item, PortableRecipeOHLCVInputV1) for item in ohlcv):
            raise PortableRecipeValidationError("ohlcv_inputs contain invalid values")
        if not all(isinstance(item, PortableRecipeDependencyV1) for item in dependencies):
            raise PortableRecipeValidationError("dependencies contain invalid values")
        if len({item.role for item in ohlcv}) != len(ohlcv):
            raise PortableRecipeValidationError("OHLCV input roles must be unique")
        if len({item.role for item in dependencies}) != len(dependencies):
            raise PortableRecipeValidationError("dependency roles must be unique")
        if {item.role for item in ohlcv} & {item.role for item in dependencies}:
            raise PortableRecipeValidationError("source roles must not overlap")
        if any(item.recipe_id == self.recipe_id for item in dependencies):
            raise PortableRecipeValidationError("a Recipe may not depend on itself")
        ordered_ohlcv = tuple(sorted(ohlcv, key=lambda item: (item.role, item.column_name)))
        ordered_dependencies = tuple(
            sorted(dependencies, key=lambda item: (item.role, item.recipe_id, item.output_name))
        )
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "output_names", outputs)
        object.__setattr__(self, "ohlcv_inputs", ordered_ohlcv)
        object.__setattr__(self, "dependencies", ordered_dependencies)
        expected = compute_portable_recipe_id(
            tool_key=key,
            tool_version=self.tool_version,
            kind=self.kind,
            parameters=parameters,
            output_names=outputs,
            ohlcv_inputs=ordered_ohlcv,
            dependencies=ordered_dependencies,
            schema_version=self.schema_version,
            object_type=self.object_type,
        )
        if self.recipe_id != expected:
            raise PortableRecipeValidationError("recipe_id does not match semantic Recipe identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "recipe_id": self.recipe_id,
            "tool_key": self.tool_key,
            "tool_version": self.tool_version,
            "kind": self.kind,
            "parameters": _thaw_json(self.parameters),
            "output_names": list(self.output_names),
            "ohlcv_inputs": [item.to_dict() for item in self.ohlcv_inputs],
            "dependencies": [item.to_dict() for item in self.dependencies],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeV1":
        data = _exact(
            value,
            {
                "schema_version", "object_type", "recipe_id", "tool_key",
                "tool_version", "kind", "parameters", "output_names",
                "ohlcv_inputs", "dependencies",
            },
            "portable Recipe",
        )
        return cls(
            schema_version=data["schema_version"],
            object_type=data["object_type"],
            recipe_id=data["recipe_id"],
            tool_key=data["tool_key"],
            tool_version=data["tool_version"],
            kind=data["kind"],
            parameters=data["parameters"],
            output_names=tuple(
                _persisted_array(data["output_names"], "output_names")
            ),
            ohlcv_inputs=tuple(
                PortableRecipeOHLCVInputV1.from_dict(item)
                for item in _persisted_array(data["ohlcv_inputs"], "ohlcv_inputs")
            ),
            dependencies=tuple(
                PortableRecipeDependencyV1.from_dict(item)
                for item in _persisted_array(data["dependencies"], "dependencies")
            ),
        )

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PortableRecipeOriginV1:
    origin_id: str
    origin_kind: str
    origin_recorded_at_utc: datetime
    details: Mapping[str, str]
    schema_version: str = "1.0"
    object_type: str = "portable_recipe_origin"

    def __post_init__(self) -> None:
        _sha(self.origin_id, "origin_id")
        if (
            not isinstance(self.origin_kind, str)
            or self.origin_kind not in _ORIGIN_REQUIRED_DETAIL_KEYS
        ):
            raise PortableRecipeValidationError("unsupported portable Recipe origin kind")
        if not isinstance(self.details, Mapping):
            raise PortableRecipeValidationError("origin details must be a mapping")
        details = dict(self.details)
        detail_keys = frozenset(details)
        if not _ORIGIN_REQUIRED_DETAIL_KEYS[self.origin_kind].issubset(
            detail_keys
        ) or not detail_keys.issubset(
            _ORIGIN_ALLOWED_DETAIL_KEYS[self.origin_kind]
        ):
            raise PortableRecipeValidationError(
                f"{self.origin_kind} origin details do not match their schema"
            )
        for key, value in details.items():
            _identifier(key, "origin detail name")
            if key == "environment_content_hash":
                _sha(value, key)
            else:
                _identifier(value, key)
        object.__setattr__(self, "details", MappingProxyType(details))
        object.__setattr__(
            self,
            "origin_recorded_at_utc",
            _utc(self.origin_recorded_at_utc, "origin_recorded_at_utc"),
        )
        if self.schema_version != "1.0" or self.object_type != "portable_recipe_origin":
            raise PortableRecipeValidationError("unsupported portable Recipe origin schema")
        if self.origin_id != compute_portable_recipe_origin_id(
            self._identity_payload()
        ):
            raise PortableRecipeValidationError("origin_id does not match origin payload")

    @classmethod
    def build(
        cls,
        *,
        origin_kind: str,
        origin_recorded_at_utc: datetime,
        details: Mapping[str, str],
    ) -> "PortableRecipeOriginV1":
        identity = {
            "schema_version": "1.0",
            "object_type": "portable_recipe_origin",
            "origin_kind": origin_kind,
            "details": dict(details),
        }
        return cls(
            origin_id=compute_portable_recipe_origin_id(identity),
            origin_kind=origin_kind,
            origin_recorded_at_utc=origin_recorded_at_utc,
            details=details,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "origin_kind": self.origin_kind,
            "details": dict(self.details),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "origin_id": self.origin_id,
            "origin_recorded_at_utc": self.origin_recorded_at_utc.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeOriginV1":
        data = _exact(
            value,
            {
                "schema_version", "object_type", "origin_id", "origin_kind",
                "origin_recorded_at_utc", "details",
            },
            "portable Recipe origin",
        )
        details = data["details"]
        if not isinstance(details, Mapping):
            raise PortableRecipeValidationError("origin details must be a mapping")
        return cls(
            origin_id=data["origin_id"],
            origin_kind=data["origin_kind"],
            origin_recorded_at_utc=_parse_utc(
                data["origin_recorded_at_utc"], "origin_recorded_at_utc"
            ),
            details=dict(details),
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )


@dataclass(frozen=True, slots=True)
class PortableRecipePersistenceMetadataV1:
    recipe_id: str
    first_persisted_at_utc: datetime | None
    origins: tuple[PortableRecipeOriginV1, ...]
    schema_version: str = "1.0"
    object_type: str = "portable_recipe_persistence_metadata"

    def __post_init__(self) -> None:
        _sha(self.recipe_id, "recipe_id")
        if self.first_persisted_at_utc is not None:
            object.__setattr__(
                self,
                "first_persisted_at_utc",
                _utc(self.first_persisted_at_utc, "first_persisted_at_utc"),
            )
        origins = tuple(self.origins)
        if not all(isinstance(item, PortableRecipeOriginV1) for item in origins):
            raise PortableRecipeValidationError(
                "origins must contain portable Recipe origin records"
            )
        if len({item.origin_id for item in origins}) != len(origins):
            raise PortableRecipeValidationError("origin identities must be unique")
        object.__setattr__(
            self, "origins", tuple(sorted(origins, key=lambda item: item.origin_id))
        )
        if (
            self.schema_version != "1.0"
            or self.object_type != "portable_recipe_persistence_metadata"
        ):
            raise PortableRecipeValidationError(
                "unsupported portable Recipe persistence metadata schema"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "recipe_id": self.recipe_id,
            "first_persisted_at_utc": (
                None
                if self.first_persisted_at_utc is None
                else self.first_persisted_at_utc.isoformat()
            ),
            "origins": [item.to_dict() for item in self.origins],
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "PortableRecipePersistenceMetadataV1":
        data = _exact(
            value,
            {
                "schema_version", "object_type", "recipe_id",
                "first_persisted_at_utc", "origins",
            },
            "portable Recipe persistence metadata",
        )
        first_persisted = data["first_persisted_at_utc"]
        return cls(
            recipe_id=data["recipe_id"],
            first_persisted_at_utc=(
                None
                if first_persisted is None
                else _parse_utc(first_persisted, "first_persisted_at_utc")
            ),
            origins=tuple(
                PortableRecipeOriginV1.from_dict(item)
                for item in _persisted_array(data["origins"], "origins")
            ),
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PortableRecipeProvenanceV1:
    provenance_id: str
    recipe_id: str
    origin_market_id: MarketId
    study_environment_id: str
    study_environment_content_hash: str
    study_environment_updated_at_utc: datetime
    study_environment_display_name: str
    study_entry_id: str
    study_display_name: str
    study_description: str
    schema_version: str = "1.0"
    object_type: str = "portable_recipe_provenance"

    def __post_init__(self) -> None:
        _sha(self.provenance_id, "provenance_id")
        _sha(self.recipe_id, "recipe_id")
        _market(self.origin_market_id)
        _identifier(self.study_environment_id, "study_environment_id")
        _sha(self.study_environment_content_hash, "study_environment_content_hash")
        object.__setattr__(
            self,
            "study_environment_updated_at_utc",
            _utc(self.study_environment_updated_at_utc, "study_environment_updated_at_utc"),
        )
        _text(self.study_environment_display_name, "study_environment_display_name")
        _identifier(self.study_entry_id, "study_entry_id")
        _text(self.study_display_name, "study_display_name")
        _text(self.study_description, "study_description", empty=True)
        if self.schema_version != "1.0" or self.object_type != "portable_recipe_provenance":
            raise PortableRecipeValidationError("unsupported portable Recipe provenance schema")
        if self.provenance_id != compute_portable_recipe_provenance_id(
            self.to_dict(include_provenance_id=False)
        ):
            raise PortableRecipeValidationError("provenance_id does not match provenance payload")

    @classmethod
    def build(
        cls,
        *,
        recipe_id: str,
        origin_market_id: MarketId,
        study_environment_id: str,
        study_environment_content_hash: str,
        study_environment_updated_at_utc: datetime,
        study_environment_display_name: str,
        study_entry_id: str,
        study_display_name: str,
        study_description: str,
    ) -> "PortableRecipeProvenanceV1":
        payload = {
            "schema_version": "1.0",
            "object_type": "portable_recipe_provenance",
            "recipe_id": recipe_id,
            "origin_market_id": _market_dict(origin_market_id),
            "study_environment_id": study_environment_id,
            "study_environment_content_hash": study_environment_content_hash,
            "study_environment_updated_at_utc": _utc(
                study_environment_updated_at_utc, "study_environment_updated_at_utc"
            ).isoformat(),
            "study_environment_display_name": study_environment_display_name,
            "study_entry_id": study_entry_id,
            "study_display_name": study_display_name,
            "study_description": study_description,
        }
        return cls(provenance_id=compute_portable_recipe_provenance_id(payload), **{
            "recipe_id": recipe_id,
            "origin_market_id": origin_market_id,
            "study_environment_id": study_environment_id,
            "study_environment_content_hash": study_environment_content_hash,
            "study_environment_updated_at_utc": study_environment_updated_at_utc,
            "study_environment_display_name": study_environment_display_name,
            "study_entry_id": study_entry_id,
            "study_display_name": study_display_name,
            "study_description": study_description,
        })

    def to_dict(self, *, include_provenance_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "recipe_id": self.recipe_id,
            "origin_market_id": _market_dict(self.origin_market_id),
            "study_environment_id": self.study_environment_id,
            "study_environment_content_hash": self.study_environment_content_hash,
            "study_environment_updated_at_utc": self.study_environment_updated_at_utc.isoformat(),
            "study_environment_display_name": self.study_environment_display_name,
            "study_entry_id": self.study_entry_id,
            "study_display_name": self.study_display_name,
            "study_description": self.study_description,
        }
        if include_provenance_id:
            payload["provenance_id"] = self.provenance_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeProvenanceV1":
        data = _exact(
            value,
            {
                "schema_version", "object_type", "provenance_id", "recipe_id",
                "origin_market_id", "study_environment_id",
                "study_environment_content_hash", "study_environment_updated_at_utc",
                "study_environment_display_name", "study_entry_id", "study_display_name",
                "study_description",
            },
            "portable Recipe provenance",
        )
        return cls(
            provenance_id=data["provenance_id"],
            recipe_id=data["recipe_id"],
            origin_market_id=_market_from_dict(data["origin_market_id"]),
            study_environment_id=data["study_environment_id"],
            study_environment_content_hash=data["study_environment_content_hash"],
            study_environment_updated_at_utc=_parse_utc(
                data["study_environment_updated_at_utc"],
                "study_environment_updated_at_utc",
            ),
            study_environment_display_name=data["study_environment_display_name"],
            study_entry_id=data["study_entry_id"],
            study_display_name=data["study_display_name"],
            study_description=data["study_description"],
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PortableRecipeCollectionRevisionV1:
    collection_id: str
    revision_id: str
    display_name: str
    description: str
    root_recipe_ids: tuple[str, ...]
    member_recipe_ids: tuple[str, ...]
    previous_revision_id: str | None
    created_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "portable_recipe_collection_revision"

    def __post_init__(self) -> None:
        _collection_id(self.collection_id)
        _sha(self.revision_id, "revision_id")
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        roots = _string_tuple(self.root_recipe_ids, "root_recipe_ids")
        members = _string_tuple(self.member_recipe_ids, "member_recipe_ids")
        for value in (*roots, *members):
            _sha(value, "recipe_id")
        if not set(roots).issubset(members):
            raise PortableRecipeValidationError("every Collection root must be a member")
        if self.previous_revision_id is not None:
            _sha(self.previous_revision_id, "previous_revision_id")
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        if self.schema_version != "1.0" or self.object_type != "portable_recipe_collection_revision":
            raise PortableRecipeValidationError("unsupported portable Recipe Collection schema")
        object.__setattr__(self, "root_recipe_ids", roots)
        object.__setattr__(self, "member_recipe_ids", members)
        if self.revision_id != compute_portable_recipe_collection_revision_id(
            self.to_dict(include_revision_id=False)
        ):
            raise PortableRecipeValidationError("revision_id does not match revision payload")

    @classmethod
    def build(
        cls,
        *,
        collection_id: str,
        display_name: str,
        description: str,
        root_recipe_ids: Sequence[str],
        member_recipe_ids: Sequence[str],
        previous_revision_id: str | None,
        created_at_utc: datetime,
    ) -> "PortableRecipeCollectionRevisionV1":
        payload = {
            "schema_version": "1.0",
            "object_type": "portable_recipe_collection_revision",
            "collection_id": collection_id,
            "display_name": display_name,
            "description": description,
            "root_recipe_ids": list(root_recipe_ids),
            "member_recipe_ids": list(member_recipe_ids),
            "previous_revision_id": previous_revision_id,
            "created_at_utc": _utc(created_at_utc, "created_at_utc").isoformat(),
        }
        return cls(
            collection_id=collection_id,
            revision_id=compute_portable_recipe_collection_revision_id(payload),
            display_name=display_name,
            description=description,
            root_recipe_ids=tuple(root_recipe_ids),
            member_recipe_ids=tuple(member_recipe_ids),
            previous_revision_id=previous_revision_id,
            created_at_utc=created_at_utc,
        )

    def to_dict(self, *, include_revision_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "collection_id": self.collection_id,
            "display_name": self.display_name,
            "description": self.description,
            "root_recipe_ids": list(self.root_recipe_ids),
            "member_recipe_ids": list(self.member_recipe_ids),
            "previous_revision_id": self.previous_revision_id,
            "created_at_utc": self.created_at_utc.isoformat(),
        }
        if include_revision_id:
            payload["revision_id"] = self.revision_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeCollectionRevisionV1":
        data = _exact(
            value,
            {
                "schema_version", "object_type", "collection_id", "revision_id",
                "display_name", "description", "root_recipe_ids", "member_recipe_ids",
                "previous_revision_id", "created_at_utc",
            },
            "portable Recipe Collection revision",
        )
        return cls(
            collection_id=data["collection_id"],
            revision_id=data["revision_id"],
            display_name=data["display_name"],
            description=data["description"],
            root_recipe_ids=tuple(
                _persisted_array(data["root_recipe_ids"], "root_recipe_ids")
            ),
            member_recipe_ids=tuple(
                _persisted_array(data["member_recipe_ids"], "member_recipe_ids")
            ),
            previous_revision_id=data["previous_revision_id"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class PortableRecipeCollectionHeadV1:
    collection_id: str
    revision_id: str
    updated_at_utc: datetime
    schema_version: str = "1.0"
    object_type: str = "portable_recipe_collection_head"

    def __post_init__(self) -> None:
        _collection_id(self.collection_id)
        _sha(self.revision_id, "revision_id")
        object.__setattr__(self, "updated_at_utc", _utc(self.updated_at_utc, "updated_at_utc"))
        if self.schema_version != "1.0" or self.object_type != "portable_recipe_collection_head":
            raise PortableRecipeValidationError("unsupported portable Recipe Collection head schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "collection_id": self.collection_id,
            "revision_id": self.revision_id,
            "updated_at_utc": self.updated_at_utc.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PortableRecipeCollectionHeadV1":
        data = _exact(
            value,
            {"schema_version", "object_type", "collection_id", "revision_id", "updated_at_utc"},
            "portable Recipe Collection head",
        )
        return cls(
            collection_id=data["collection_id"],
            revision_id=data["revision_id"],
            updated_at_utc=_parse_utc(data["updated_at_utc"], "updated_at_utc"),
            schema_version=data["schema_version"],
            object_type=data["object_type"],
        )

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


__all__ = (
    "PortableRecipeCollectionHeadV1",
    "PortableRecipeCollectionRevisionV1",
    "PortableRecipeDependencyV1",
    "PortableRecipeOHLCVInputV1",
    "PortableRecipeOriginV1",
    "PortableRecipePersistenceMetadataV1",
    "PortableRecipeProvenanceV1",
    "PortableRecipeV1",
    "PortableRecipeValidationError",
)
