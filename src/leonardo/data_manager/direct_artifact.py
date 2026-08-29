"""Typed internal state for direct managed Artifact creation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import (
    get_financial_tool_spec,
    resolve_output_names,
    resolve_parameters,
)
from leonardo.financial_tools.construct_input_eligibility import (
    validate_financial_tool_source_roles,
)
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeV1,
    build_portable_recipe,
)

from .models import DataManagerArtifactMaterializationResult


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
def _canonical_market(value: object, field_name: str) -> MarketId:
    if not isinstance(value, MarketId):
        raise TypeError(f"{field_name} must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if value != canonical:
        raise ValueError(f"{field_name} must already be canonical")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 value")
    return text


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    copied = deepcopy(dict(value))
    if not all(isinstance(key, str) for key in copied):
        raise ValueError(f"{field_name} keys must be strings")
    return MappingProxyType(copied)


def _outputs(value: object, field_name: str) -> tuple[str, ...]:
    values = tuple(value) if isinstance(value, (tuple, list)) else ()
    if not values or any(
        not isinstance(item, str) or not item or item != item.strip()
        for item in values
    ):
        raise ValueError(f"{field_name} must contain canonical non-empty text")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class DataManagerDirectArtifactSource:
    role: str
    logical_artifact_id: str
    artifact_id: str
    output_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _text(self.role, "role"))
        object.__setattr__(
            self,
            "logical_artifact_id",
            _sha(self.logical_artifact_id, "logical_artifact_id"),
        )
        object.__setattr__(self, "artifact_id", _sha(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self, "output_name", _text(self.output_name, "output_name")
        )


@dataclass(frozen=True, slots=True)
class DataManagerDirectArtifactOption:
    market_id: MarketId
    logical_artifact_id: str
    artifact_id: str
    tool_key: str
    kind: str
    display_name: str
    output_names: tuple[str, ...]
    source_ohlcv: OHLCVSourceFingerprintV1

    def __post_init__(self) -> None:
        market = _canonical_market(self.market_id, "market_id")
        object.__setattr__(self, "market_id", market)
        object.__setattr__(
            self,
            "logical_artifact_id",
            _sha(self.logical_artifact_id, "logical_artifact_id"),
        )
        object.__setattr__(self, "artifact_id", _sha(self.artifact_id, "artifact_id"))
        spec = get_financial_tool_spec(_text(self.tool_key, "tool_key"))
        if self.tool_key != spec.key:
            raise ValueError("tool_key must already be canonical")
        if self.kind != spec.kind:
            raise ValueError("kind must match the Financial Tool specification")
        _text(self.display_name, "display_name")
        object.__setattr__(
            self, "output_names", _outputs(self.output_names, "output_names")
        )
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1):
            raise TypeError("source_ohlcv must be an OHLCVSourceFingerprintV1")
        if self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv MarketId must match market_id")


@dataclass(frozen=True, slots=True)
class DataManagerDirectArtifactCatalog:
    market_id: MarketId
    source_ohlcv: OHLCVSourceFingerprintV1
    construct_options: tuple[DataManagerDirectArtifactOption, ...]
    utc_peaks_troughs_options: tuple[DataManagerDirectArtifactOption, ...]

    def __post_init__(self) -> None:
        market = _canonical_market(self.market_id, "market_id")
        object.__setattr__(self, "market_id", market)
        if not isinstance(self.source_ohlcv, OHLCVSourceFingerprintV1):
            raise TypeError("source_ohlcv must be an OHLCVSourceFingerprintV1")
        if self.source_ohlcv.market_id != market:
            raise ValueError("source_ohlcv MarketId must match market_id")
        for field_name in ("construct_options", "utc_peaks_troughs_options"):
            values = tuple(getattr(self, field_name))
            if not all(
                isinstance(item, DataManagerDirectArtifactOption)
                and item.market_id == market
                and item.source_ohlcv == self.source_ohlcv
                for item in values
            ):
                raise ValueError(f"{field_name} contains mismatched options")
            identities = tuple(item.logical_artifact_id for item in values)
            if len(set(identities)) != len(identities):
                raise ValueError(f"{field_name} must contain unique logical Artifacts")
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class DataManagerDirectArtifactRequest:
    market_id: MarketId
    expected_source_ohlcv: OHLCVSourceFingerprintV1
    tool_key: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    sources: tuple[DataManagerDirectArtifactSource, ...] = ()

    def __post_init__(self) -> None:
        market = _canonical_market(self.market_id, "market_id")
        object.__setattr__(self, "market_id", market)
        if not isinstance(self.expected_source_ohlcv, OHLCVSourceFingerprintV1):
            raise TypeError(
                "expected_source_ohlcv must be an OHLCVSourceFingerprintV1"
            )
        if self.expected_source_ohlcv.market_id != market:
            raise ValueError("expected_source_ohlcv MarketId must match market_id")
        spec = get_financial_tool_spec(_text(self.tool_key, "tool_key"))
        if self.tool_key != spec.key:
            raise ValueError("tool_key must already be canonical")
        if spec.key == "dynamic_binning":
            raise ValueError("dynamic_binning is not available for direct creation")
        object.__setattr__(self, "parameters", _mapping(self.parameters, "parameters"))
        sources = tuple(self.sources)
        if not all(isinstance(item, DataManagerDirectArtifactSource) for item in sources):
            raise TypeError("sources must contain DataManagerDirectArtifactSource values")
        roles = tuple(item.role for item in sources)
        if len(set(roles)) != len(roles):
            raise ValueError("source roles must be unique")
        _validate_source_roles(spec.key, spec.kind, roles)
        object.__setattr__(self, "sources", sources)


@dataclass(frozen=True, slots=True)
class DataManagerDirectArtifactResult:
    portable_recipe_id: str
    materialization: DataManagerArtifactMaterializationResult

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "portable_recipe_id",
            _sha(self.portable_recipe_id, "portable_recipe_id"),
        )
        if not isinstance(
            self.materialization, DataManagerArtifactMaterializationResult
        ):
            raise TypeError(
                "materialization must be a DataManagerArtifactMaterializationResult"
            )


def _validate_source_roles(tool_key: str, kind: str, roles: tuple[str, ...]) -> None:
    spec = get_financial_tool_spec(tool_key)
    if spec.kind != kind:
        raise ValueError("kind must match the Financial Tool specification")
    validate_financial_tool_source_roles(spec, roles)


def _build_direct_portable_recipe(
    request: DataManagerDirectArtifactRequest,
    source_recipe_ids: Mapping[str, str],
) -> PortableRecipeV1:
    """Project one validated direct request into a global portable Recipe."""

    if not isinstance(request, DataManagerDirectArtifactRequest):
        raise TypeError("request must be a DataManagerDirectArtifactRequest")
    if not isinstance(source_recipe_ids, Mapping):
        raise TypeError("source_recipe_ids must be a mapping")
    roles = tuple(item.role for item in request.sources)
    if set(source_recipe_ids) != set(roles):
        raise ValueError("source Recipe roles must exactly match request sources")
    recipe_ids = {
        role: _sha(recipe_id, f"source_recipe_ids[{role!r}]")
        for role, recipe_id in source_recipe_ids.items()
    }
    spec = get_financial_tool_spec(request.tool_key)
    resolved = dict(resolve_parameters(spec.key, request.parameters))
    naming = dict(resolved)
    if spec.key in {"derivative", "angle"}:
        naming["source"] = "__research_source"
    elif spec.key == "delta":
        naming.update(fast="__research_fast", slow="__research_slow")
    elif spec.key in {"braids", "braid_instability"}:
        naming.update(
            fast="__research_fast",
            mid="__research_mid",
            slow="__research_slow",
        )
    elif spec.key == "trap_area":
        naming.update(fast="__research_fast", slow="__research_slow")
        if "mid" in roles:
            naming["mid"] = "__research_mid"
        else:
            naming.pop("mid", None)
    elif spec.key in {"percent_span_angle", "angle_momentum"}:
        naming["source_columns"] = ",".join(
            f"__research_source_{index}" for index in range(1, len(roles) + 1)
        )
    dependencies = tuple(
        PortableRecipeDependencyV1(
            source.role,
            recipe_ids[source.role],
            source.output_name,
        )
        for source in request.sources
    )
    return build_portable_recipe(
        tool_key=spec.key,
        kind=spec.kind,
        parameters=resolved,
        output_names=resolve_output_names(spec.key, naming),
        dependencies=dependencies,
    )
