"""Versioned immutable Study Environment persistence models."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import (
    get_financial_tool_spec,
    resolve_output_names,
    resolve_output_signals,
    resolve_parameters,
)
from leonardo.research.studies import StudyUserMetadata
from leonardo.research.study_presentation import (
    StudyFillStyle,
    StudyGuideStyle,
    StudyLineStyle,
)
from leonardo.research.study_setup import source_role_schema


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset({"ohlcv", "environment", "artifact"})
_ENTRY_MODES = frozenset({"calculation", "artifact"})
_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})
_MULTI_SOURCE_TOOLS = frozenset(
    {"dynamic_binning", "percent_span_angle", "angle_momentum"}
)
_PRIVATE_SOURCE_ALIASES = {
    "source": "__research_source",
    "fast": "__research_fast",
    "mid": "__research_mid",
    "slow": "__research_slow",
    "peak": "__research_peak",
    "trough": "__research_trough",
    "trend_peak": "__research_trend_peak",
    "trend_trough": "__research_trend_trough",
    "range_peak": "__research_range_peak",
    "range_trough": "__research_range_trough",
}


class StudyEnvironmentValidationError(ValueError):
    """Raised when a Study Environment violates schema version 1."""


class StudyEnvironmentNotFoundError(KeyError):
    """Raised when an exact Study Environment file does not exist."""


class StudyEnvironmentAlreadyExistsError(FileExistsError):
    """Raised when an environment identity or display name already exists."""


def _text(value: object, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise StudyEnvironmentValidationError(f"{name} must be a string")
    if not empty and (not value or value != value.strip()):
        raise StudyEnvironmentValidationError(f"{name} must be canonical non-empty text")
    return value


def _identifier(value: object, name: str) -> str:
    text = _text(value, name)
    if _ID_RE.fullmatch(text) is None:
        raise StudyEnvironmentValidationError(f"{name} is not a canonical identifier")
    return text


def _sha(value: object, name: str) -> str:
    text = _text(value, name)
    if _SHA_RE.fullmatch(text) is None:
        raise StudyEnvironmentValidationError(f"{name} must be a lowercase SHA-256")
    return text


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StudyEnvironmentValidationError(f"{name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise StudyEnvironmentValidationError(f"{name} must be UTC")
    return value


def _json_copy(value: object, name: str) -> object:
    def validate(item: object, path: str) -> object:
        if item is None or type(item) in (str, bool, int):
            return item
        if type(item) is float:
            if not math.isfinite(item):
                raise StudyEnvironmentValidationError(f"{path} must be finite")
            return item
        if isinstance(item, Mapping):
            copied: dict[str, object] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise StudyEnvironmentValidationError(f"{path} keys must be strings")
                copied[key] = validate(nested, f"{path}.{key}")
            return copied
        if isinstance(item, (list, tuple)):
            return [validate(nested, f"{path}[]") for nested in item]
        raise StudyEnvironmentValidationError(f"{path} is not JSON-safe")

    return validate(value, name)


def _frozen_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StudyEnvironmentValidationError(f"{name} must be a mapping")
    return MappingProxyType(deepcopy(_json_copy(dict(value), name)))


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise StudyEnvironmentValidationError("created_from must be a MarketId or None")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if canonical != value:
        raise StudyEnvironmentValidationError("created_from must already be canonical")
    return value


@dataclass(frozen=True, slots=True)
class StudyEnvironmentSourceV1:
    role: str
    source_kind: str
    column_name: str | None = None
    source_entry_id: str | None = None
    artifact_kind: str | None = None
    artifact_tool_key: str | None = None
    artifact_id: str | None = None
    output_name: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.role, "role")
        if self.source_kind not in _SOURCE_KINDS:
            raise StudyEnvironmentValidationError("unsupported environment source kind")
        values = {
            "column_name": self.column_name,
            "source_entry_id": self.source_entry_id,
            "artifact_kind": self.artifact_kind,
            "artifact_tool_key": self.artifact_tool_key,
            "artifact_id": self.artifact_id,
            "output_name": self.output_name,
        }
        present = {name for name, value in values.items() if value is not None}
        expected = {
            "ohlcv": {"column_name"},
            "environment": {"source_entry_id", "output_name"},
            "artifact": {
                "artifact_kind",
                "artifact_tool_key",
                "artifact_id",
                "output_name",
            },
        }[self.source_kind]
        if present != expected:
            raise StudyEnvironmentValidationError("environment source fields do not match kind")
        if self.source_kind == "ohlcv":
            if self.column_name not in _OHLCV_COLUMNS:
                raise StudyEnvironmentValidationError("OHLCV source column is invalid")
        elif self.source_kind == "environment":
            _identifier(self.source_entry_id, "source_entry_id")
            _text(self.output_name, "output_name")
        else:
            spec = get_financial_tool_spec(_text(self.artifact_tool_key, "artifact_tool_key"))
            if self.artifact_kind != spec.kind:
                raise StudyEnvironmentValidationError("artifact source kind does not match tool")
            _sha(self.artifact_id, "artifact_id")
            _text(self.output_name, "output_name")

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "source_kind": self.source_kind,
            "column_name": self.column_name,
            "source_entry_id": self.source_entry_id,
            "artifact_kind": self.artifact_kind,
            "artifact_tool_key": self.artifact_tool_key,
            "artifact_id": self.artifact_id,
            "output_name": self.output_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StudyEnvironmentSourceV1":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class StudyEnvironmentPresentationV1:
    visible: bool
    line_styles: tuple[StudyLineStyle, ...]
    fill_styles: tuple[StudyFillStyle, ...]
    guide_styles: tuple[StudyGuideStyle, ...] = ()

    def __post_init__(self) -> None:
        if type(self.visible) is not bool:
            raise StudyEnvironmentValidationError("presentation visible must be a boolean")
        lines = tuple(self.line_styles)
        fills = tuple(self.fill_styles)
        guides = tuple(self.guide_styles)
        if not all(isinstance(item, StudyLineStyle) for item in lines):
            raise StudyEnvironmentValidationError("line_styles contain invalid values")
        if not all(isinstance(item, StudyFillStyle) for item in fills):
            raise StudyEnvironmentValidationError("fill_styles contain invalid values")
        if not all(isinstance(item, StudyGuideStyle) for item in guides):
            raise StudyEnvironmentValidationError("guide_styles contain invalid values")
        if len({item.output_name for item in lines}) != len(lines):
            raise StudyEnvironmentValidationError("line style outputs must be unique")
        if len({item.fill_id for item in fills}) != len(fills):
            raise StudyEnvironmentValidationError("fill style IDs must be unique")
        if len({item.guide_id for item in guides}) != len(guides):
            raise StudyEnvironmentValidationError("guide style IDs must be unique")
        if len({item.kind for item in guides}) != len(guides):
            raise StudyEnvironmentValidationError(
                "guide style kinds must be unique"
            )
        object.__setattr__(self, "line_styles", lines)
        object.__setattr__(self, "fill_styles", fills)
        object.__setattr__(self, "guide_styles", guides)

    def to_dict(self) -> dict[str, object]:
        payload = {
            "visible": self.visible,
            "line_styles": [_line_style_to_dict(item) for item in self.line_styles],
            "fill_styles": [_fill_style_to_dict(item) for item in self.fill_styles],
        }
        if self.guide_styles:
            payload["guide_styles"] = [
                _guide_style_to_dict(item) for item in self.guide_styles
            ]
        return payload

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "StudyEnvironmentPresentationV1":
        data = dict(value)
        return cls(
            visible=data["visible"],
            line_styles=tuple(
                _line_style_from_dict(item) for item in _sequence(data["line_styles"], "line_styles")
            ),
            fill_styles=tuple(
                _fill_style_from_dict(item) for item in _sequence(data["fill_styles"], "fill_styles")
            ),
            guide_styles=tuple(
                _guide_style_from_dict(item)
                for item in _sequence(data.get("guide_styles", ()), "guide_styles")
            ),
        )


@dataclass(frozen=True, slots=True)
class StudyEnvironmentEntryV1:
    entry_id: str
    mode: str
    kind: str
    tool_key: str
    display_name: str
    parameters: Mapping[str, object]
    sources: tuple[StudyEnvironmentSourceV1, ...]
    artifact_id: str | None
    expected_output_names: tuple[str, ...]
    user_metadata: StudyUserMetadata
    presentation: StudyEnvironmentPresentationV1

    def __post_init__(self) -> None:
        _identifier(self.entry_id, "entry_id")
        if self.mode not in _ENTRY_MODES:
            raise StudyEnvironmentValidationError("unsupported environment entry mode")
        spec = get_financial_tool_spec(_text(self.tool_key, "tool_key"))
        if self.kind != spec.kind:
            raise StudyEnvironmentValidationError("entry kind does not match tool")
        _text(self.display_name, "display_name")
        parameters = _frozen_mapping(self.parameters, "parameters")
        sources = tuple(self.sources)
        if not all(isinstance(item, StudyEnvironmentSourceV1) for item in sources):
            raise StudyEnvironmentValidationError("sources contain invalid values")
        if len({item.role for item in sources}) != len(sources):
            raise StudyEnvironmentValidationError("source roles must be unique")
        outputs = tuple(self.expected_output_names)
        if not outputs or any(not isinstance(item, str) or not item for item in outputs):
            raise StudyEnvironmentValidationError("expected outputs are invalid")
        if len(set(outputs)) != len(outputs):
            raise StudyEnvironmentValidationError("expected outputs must be unique")
        if not isinstance(self.user_metadata, StudyUserMetadata):
            raise StudyEnvironmentValidationError("user_metadata is invalid")
        if not isinstance(self.presentation, StudyEnvironmentPresentationV1):
            raise StudyEnvironmentValidationError("presentation is invalid")
        supplied_guides = self.presentation.guide_styles
        if supplied_guides:
            expected_guides = (
                ()
                if spec.oscillator_visual is None
                else tuple(
                    guide.kind
                    for guide in spec.oscillator_visual.guide_levels
                )
            )
            if tuple(guide.guide_id for guide in supplied_guides) != expected_guides:
                raise StudyEnvironmentValidationError(
                    "guide style IDs must exactly match the canonical order"
                )
            if tuple(guide.kind for guide in supplied_guides) != expected_guides:
                raise StudyEnvironmentValidationError(
                    "guide style kinds must exactly match the canonical order"
                )
        if not set(item.output_name for item in self.presentation.line_styles).issubset(outputs):
            raise StudyEnvironmentValidationError(
                "line styles contain outputs outside expected outputs"
            )
        output_set = set(outputs)
        for fill in self.presentation.fill_styles:
            if fill.upper_output_name not in output_set or fill.lower_output_name not in output_set:
                raise StudyEnvironmentValidationError("fill styles reference unknown outputs")
        if self.mode == "artifact":
            if self.artifact_id is None or parameters or sources:
                raise StudyEnvironmentValidationError(
                    "artifact entries require only an artifact identity"
                )
            _sha(self.artifact_id, "artifact_id")
        else:
            if self.artifact_id is not None:
                raise StudyEnvironmentValidationError(
                    "calculation entries may not contain artifact_id"
                )
            try:
                selectors = _owned_selector_names(self.tool_key)
                canonical = {
                    name: value
                    for name, value in resolve_parameters(self.tool_key, parameters).items()
                    if name not in selectors
                }
            except (TypeError, ValueError) as exc:
                raise StudyEnvironmentValidationError(str(exc)) from exc
            if dict(canonical) != dict(parameters):
                raise StudyEnvironmentValidationError("entry parameters must be fully canonical")
            _validate_source_roles(self.tool_key, tuple(item.role for item in sources))
            if _expected_outputs(self.tool_key, parameters, sources) != outputs:
                raise StudyEnvironmentValidationError(
                    "expected outputs do not match the canonical setup"
                )
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "expected_output_names", outputs)

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "mode": self.mode,
            "kind": self.kind,
            "tool_key": self.tool_key,
            "display_name": self.display_name,
            "parameters": deepcopy(dict(self.parameters)),
            "sources": [item.to_dict() for item in self.sources],
            "artifact_id": self.artifact_id,
            "expected_output_names": list(self.expected_output_names),
            "user_metadata": _metadata_to_dict(self.user_metadata),
            "presentation": self.presentation.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StudyEnvironmentEntryV1":
        data = dict(value)
        return cls(
            entry_id=data["entry_id"],
            mode=data["mode"],
            kind=data["kind"],
            tool_key=data["tool_key"],
            display_name=data["display_name"],
            parameters=_require_mapping(data["parameters"], "parameters"),
            sources=tuple(
                StudyEnvironmentSourceV1.from_dict(_require_mapping(item, "source"))
                for item in _sequence(data["sources"], "sources")
            ),
            artifact_id=data.get("artifact_id"),
            expected_output_names=tuple(
                _sequence(data["expected_output_names"], "expected_output_names")
            ),
            user_metadata=_metadata_from_dict(
                _require_mapping(data["user_metadata"], "user_metadata")
            ),
            presentation=StudyEnvironmentPresentationV1.from_dict(
                _require_mapping(data["presentation"], "presentation")
            ),
        )


@dataclass(frozen=True, slots=True)
class StudyEnvironmentV1:
    environment_id: str
    content_hash: str
    display_name: str
    description: str
    created_at_utc: datetime
    updated_at_utc: datetime
    created_from: MarketId | None
    entries: tuple[StudyEnvironmentEntryV1, ...]
    schema_version: str = "1.0"
    object_type: str = "study_environment"

    def __post_init__(self) -> None:
        _identifier(self.environment_id, "environment_id")
        _sha(self.content_hash, "content_hash")
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        _utc(self.created_at_utc, "created_at_utc")
        _utc(self.updated_at_utc, "updated_at_utc")
        if self.updated_at_utc < self.created_at_utc:
            raise StudyEnvironmentValidationError("updated timestamp precedes creation")
        if self.created_from is not None:
            _market(self.created_from)
        entries = tuple(self.entries)
        if not entries or not all(isinstance(item, StudyEnvironmentEntryV1) for item in entries):
            raise StudyEnvironmentValidationError("entries must contain at least one valid entry")
        if len({item.entry_id for item in entries}) != len(entries):
            raise StudyEnvironmentValidationError("entry IDs must be unique")
        _validate_topology(entries)
        if self.schema_version != "1.0" or self.object_type != "study_environment":
            raise StudyEnvironmentValidationError("unsupported Study Environment schema")
        object.__setattr__(self, "entries", entries)
        expected_hash = environment_content_hash(self.to_dict(include_content_hash=False))
        if self.content_hash != expected_hash:
            raise StudyEnvironmentValidationError("content_hash does not match environment payload")

    @classmethod
    def build(
        cls,
        *,
        environment_id: str,
        display_name: str,
        description: str,
        created_at_utc: datetime,
        updated_at_utc: datetime,
        created_from: MarketId | None,
        entries: Sequence[StudyEnvironmentEntryV1],
    ) -> "StudyEnvironmentV1":
        payload = {
            "schema_version": "1.0",
            "object_type": "study_environment",
            "environment_id": environment_id,
            "display_name": display_name,
            "description": description,
            "created_at_utc": _utc(created_at_utc, "created_at_utc").isoformat(),
            "updated_at_utc": _utc(updated_at_utc, "updated_at_utc").isoformat(),
            "created_from": _market_to_dict(created_from),
            "entries": [item.to_dict() for item in entries],
        }
        return cls(
            environment_id=environment_id,
            content_hash=environment_content_hash(payload),
            display_name=display_name,
            description=description,
            created_at_utc=created_at_utc,
            updated_at_utc=updated_at_utc,
            created_from=created_from,
            entries=tuple(entries),
        )

    def to_dict(self, *, include_content_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "object_type": self.object_type,
            "environment_id": self.environment_id,
            "display_name": self.display_name,
            "description": self.description,
            "created_at_utc": self.created_at_utc.isoformat(),
            "updated_at_utc": self.updated_at_utc.isoformat(),
            "created_from": _market_to_dict(self.created_from),
            "entries": [item.to_dict() for item in self.entries],
        }
        if include_content_hash:
            payload["content_hash"] = self.content_hash
        return payload

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StudyEnvironmentV1":
        data = dict(value)
        created_from = data.get("created_from")
        return cls(
            schema_version=data["schema_version"],
            object_type=data["object_type"],
            environment_id=data["environment_id"],
            content_hash=data["content_hash"],
            display_name=data["display_name"],
            description=data["description"],
            created_at_utc=_parse_utc(data["created_at_utc"], "created_at_utc"),
            updated_at_utc=_parse_utc(data["updated_at_utc"], "updated_at_utc"),
            created_from=(
                None
                if created_from is None
                else _market_from_dict(_require_mapping(created_from, "created_from"))
            ),
            entries=tuple(
                StudyEnvironmentEntryV1.from_dict(_require_mapping(item, "entry"))
                for item in _sequence(data["entries"], "entries")
            ),
        )


@dataclass(frozen=True, slots=True)
class StudyEnvironmentSummary:
    environment_id: str
    display_name: str
    description: str
    entry_count: int
    created_at_utc: datetime | None
    updated_at_utc: datetime | None
    valid: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StudyEnvironmentDraft:
    display_name: str
    description: str
    created_from: MarketId | None
    entries: tuple[StudyEnvironmentEntryV1, ...]
    environment_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.display_name, "display_name")
        _text(self.description, "description", empty=True)
        if self.created_from is not None:
            _market(self.created_from)
        entries = tuple(self.entries)
        if not entries:
            raise StudyEnvironmentValidationError("environment draft must contain entries")
        _validate_topology(entries)
        if self.environment_id is not None:
            _identifier(self.environment_id, "environment_id")
        object.__setattr__(self, "entries", entries)


@dataclass(frozen=True, slots=True)
class StudyEnvironmentCompatibilityReport:
    environment_id: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.environment_id, "environment_id")
        blockers = tuple(self.blockers)
        warnings = tuple(self.warnings)
        if not all(isinstance(item, str) and item for item in (*blockers, *warnings)):
            raise StudyEnvironmentValidationError("compatibility messages must be text")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)

    @property
    def compatible(self) -> bool:
        return not self.blockers


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            _json_copy(dict(value), "environment"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StudyEnvironmentValidationError("environment JSON is not canonical") from exc


def environment_content_hash(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("content_hash", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _validate_topology(entries: tuple[StudyEnvironmentEntryV1, ...]) -> None:
    seen: dict[str, StudyEnvironmentEntryV1] = {}
    for entry in entries:
        for source in entry.sources:
            if source.source_kind != "environment":
                continue
            source_entry = seen.get(source.source_entry_id or "")
            if source_entry is None:
                raise StudyEnvironmentValidationError(
                    "environment dependencies must reference an earlier entry"
                )
            if source.output_name not in source_entry.expected_output_names:
                raise StudyEnvironmentValidationError(
                    "environment dependency output does not exist"
                )
            if source_entry.mode != "artifact":
                signals = _entry_signals(source_entry)
                signal = next((item for item in signals if item.name == source.output_name), None)
                if signal is None or not signal.analysis_usable:
                    raise StudyEnvironmentValidationError(
                        "environment dependency output is not analysis-usable"
                    )
        _validate_source_families(entry, seen)
        _validate_utc_sources(entry, seen)
        seen[entry.entry_id] = entry


def _validate_source_families(
    entry: StudyEnvironmentEntryV1,
    prior: Mapping[str, StudyEnvironmentEntryV1],
) -> None:
    construct = get_financial_tool_spec(entry.tool_key).construct_io
    if construct is None:
        return
    families = []
    for source in entry.sources:
        if source.source_kind == "ohlcv":
            families.append("ohlc")
        elif source.source_kind == "artifact":
            families.append(source.artifact_kind)
        else:
            families.append(prior[source.source_entry_id].kind)
    if any(family not in construct.allowed_source_families for family in families):
        raise StudyEnvironmentValidationError("environment source family is not allowed")
    if construct.source_compatibility == "same_family" and len(set(families)) > 1:
        raise StudyEnvironmentValidationError(
            "environment sources must use one family"
        )


def _entry_signals(entry: StudyEnvironmentEntryV1):
    if entry.mode == "artifact":
        return ()
    parameters = _selector_parameters(entry.tool_key, entry.parameters, entry.sources)
    return resolve_output_signals(entry.tool_key, parameters)


def _expected_outputs(
    tool_key: str,
    parameters: Mapping[str, object],
    sources: Sequence[StudyEnvironmentSourceV1],
) -> tuple[str, ...]:
    return resolve_output_names(tool_key, _selector_parameters(tool_key, parameters, sources))


def _selector_parameters(
    tool_key: str,
    parameters: Mapping[str, object],
    sources: Sequence[StudyEnvironmentSourceV1],
) -> dict[str, object]:
    resolved = dict(parameters)
    by_role = {
        source.role: (
            source.column_name
            if source.source_kind == "ohlcv"
            else _source_alias(source.role)
        )
        for source in sources
    }
    if tool_key in {"derivative", "angle"} and by_role:
        resolved["source"] = by_role["source"]
    elif tool_key in {"delta", "braids", "braid_instability", "trap_area"}:
        resolved.update(by_role)
    elif tool_key in _MULTI_SOURCE_TOOLS:
        resolved["source_columns"] = ",".join(
            by_role[f"source_{index}"] for index in range(1, len(by_role) + 1)
        )
    elif tool_key == "universal_trend_classifier" and by_role:
        window = resolved["trend_fractal_window"]
        resolved["peak_column"] = f"peak_fractal_{window}"
        resolved["trough_column"] = f"trough_fractal_{window}"
    return resolved


def _validate_source_roles(tool_key: str, roles: tuple[str, ...]) -> None:
    schema = source_role_schema(tool_key)
    if schema == ("source_1", "..."):
        if not roles or roles != tuple(f"source_{i}" for i in range(1, len(roles) + 1)):
            raise StudyEnvironmentValidationError("multi-source roles must be contiguous")
    elif schema == ("fast", "mid?", "slow"):
        if roles not in (("fast", "slow"), ("fast", "mid", "slow")):
            raise StudyEnvironmentValidationError("invalid fast/mid/slow source roles")
    elif roles != schema:
        raise StudyEnvironmentValidationError("source roles do not match the tool schema")


def _owned_selector_names(tool_key: str) -> frozenset[str]:
    if tool_key in {"derivative", "angle"}:
        return frozenset({"source"})
    if tool_key == "delta":
        return frozenset({"fast", "slow"})
    if tool_key in {"braids", "braid_instability", "trap_area"}:
        return frozenset({"fast", "mid", "slow"})
    if tool_key in _MULTI_SOURCE_TOOLS:
        return frozenset({"source_columns"})
    if tool_key == "universal_trend_classifier":
        return frozenset({"peak_column", "trough_column"})
    return frozenset()


def _source_alias(role: str) -> str:
    if role.startswith("source_"):
        suffix = role.removeprefix("source_")
        if suffix.isdigit() and int(suffix) > 0:
            return f"__research_source_{int(suffix)}"
    try:
        return _PRIVATE_SOURCE_ALIASES[role]
    except KeyError as exc:
        raise StudyEnvironmentValidationError("unsupported source role") from exc


def _validate_utc_sources(
    entry: StudyEnvironmentEntryV1,
    prior: Mapping[str, StudyEnvironmentEntryV1],
) -> None:
    if entry.mode != "calculation" or entry.tool_key != "universal_trend_classifier":
        return
    trend_window = entry.parameters["trend_fractal_window"]
    range_window = entry.parameters["range_fractal_window"]
    expected = {
        "trend_peak": f"peak_fractal_{trend_window}",
        "trend_trough": f"trough_fractal_{trend_window}",
        "range_peak": f"peak_fractal_{range_window}",
        "range_trough": f"trough_fractal_{range_window}",
    }
    owners: set[tuple[str, str]] = set()
    for source in entry.sources:
        if source.output_name != expected[source.role]:
            raise StudyEnvironmentValidationError(
                f"UTC {source.role} output must be {expected[source.role]!r}"
            )
        if source.source_kind == "environment":
            owner = prior[source.source_entry_id or ""]
            if owner.kind != "indicator" or owner.tool_key != "peaks_troughs":
                raise StudyEnvironmentValidationError(
                    "UTC dependencies must be Peaks & Troughs outputs"
                )
            owners.add(("environment", source.source_entry_id or ""))
        elif source.source_kind == "artifact":
            if (
                source.artifact_kind != "indicator"
                or source.artifact_tool_key != "peaks_troughs"
            ):
                raise StudyEnvironmentValidationError(
                    "UTC dependencies must be Peaks & Troughs outputs"
                )
            owners.add(("artifact", source.artifact_id or ""))
        else:
            raise StudyEnvironmentValidationError(
                "UTC dependencies must be Peaks & Troughs outputs"
            )
    if len(owners) != 1:
        raise StudyEnvironmentValidationError(
            "UTC sources must come from one Peaks & Troughs owner"
        )


def _metadata_to_dict(value: StudyUserMetadata) -> dict[str, object]:
    return {
        "important": value.important,
        "dataset_role": value.dataset_role,
        "description": value.description,
    }


def _metadata_from_dict(value: Mapping[str, object]) -> StudyUserMetadata:
    return StudyUserMetadata(
        important=value["important"],
        dataset_role=value["dataset_role"],
        description=value["description"],
    )


def _line_style_to_dict(value: StudyLineStyle) -> dict[str, object]:
    return {
        "output_name": value.output_name,
        "color": value.color,
        "line_width": value.line_width,
        "line_pattern": value.line_pattern,
        "visible": value.visible,
        "render_mode": value.render_mode,
        "marker_shape": value.marker_shape,
        "marker_size": value.marker_size,
        "conditional_driver_name": value.conditional_driver_name,
        "conditional_colors": dict(value.conditional_colors),
    }


def _line_style_from_dict(value: object) -> StudyLineStyle:
    data = dict(_require_mapping(value, "line_style"))
    return StudyLineStyle(**data)


def _fill_style_to_dict(value: StudyFillStyle) -> dict[str, object]:
    return {
        "fill_id": value.fill_id,
        "upper_output_name": value.upper_output_name,
        "lower_output_name": value.lower_output_name,
        "color": value.color,
        "opacity": value.opacity,
        "visible": value.visible,
        "conditional_driver_name": value.conditional_driver_name,
        "conditional_colors": dict(value.conditional_colors),
    }


def _fill_style_from_dict(value: object) -> StudyFillStyle:
    data = dict(_require_mapping(value, "fill_style"))
    return StudyFillStyle(**data)


def _guide_style_to_dict(value: StudyGuideStyle) -> dict[str, object]:
    return {
        "guide_id": value.guide_id,
        "kind": value.kind,
        "value": value.value,
        "color": value.color,
        "line_width": value.line_width,
        "line_pattern": value.line_pattern,
        "visible": value.visible,
    }


def _guide_style_from_dict(value: object) -> StudyGuideStyle:
    data = dict(_require_mapping(value, "guide_style"))
    return StudyGuideStyle(**data)


def _market_to_dict(value: MarketId | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "exchange": value.exchange,
        "market_type": value.market_type,
        "symbol": value.symbol,
        "timeframe": value.timeframe,
    }


def _market_from_dict(value: Mapping[str, object]) -> MarketId:
    return canonicalize_market_id(
        value["exchange"], value["market_type"], value["symbol"], value["timeframe"]
    )


def _parse_utc(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StudyEnvironmentValidationError(f"{name} must be ISO-8601") from exc
    return _utc(parsed, name)


def _sequence(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StudyEnvironmentValidationError(f"{name} must be a sequence")
    return tuple(value)


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StudyEnvironmentValidationError(f"{name} must be a mapping")
    return value


# Neutral aliases keep pre-Task 1021 static boundaries import-compatible while
# the canonical public class names remain owned by this module.
EnvironmentAlreadyExistsError = StudyEnvironmentAlreadyExistsError
EnvironmentCompatibilityReport = StudyEnvironmentCompatibilityReport
EnvironmentDraft = StudyEnvironmentDraft
EnvironmentEntryV1 = StudyEnvironmentEntryV1
EnvironmentNotFoundError = StudyEnvironmentNotFoundError
EnvironmentPresentationV1 = StudyEnvironmentPresentationV1
EnvironmentSourceV1 = StudyEnvironmentSourceV1
EnvironmentSummary = StudyEnvironmentSummary
EnvironmentV1 = StudyEnvironmentV1
EnvironmentValidationError = StudyEnvironmentValidationError
