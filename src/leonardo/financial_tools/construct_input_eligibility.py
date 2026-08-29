from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Sequence

from .models import FinancialToolSpec


ConstructSourcePolicy = Literal["all_numeric_signals", "none"]
ToolKind = Literal["indicator", "oscillator", "construct"]
SourceFamily = Literal["ohlc", "indicator", "oscillator", "construct"]
FamilyScope = Literal["all", "dependencies"]

_SUPPORTED_KINDS = frozenset({"indicator", "oscillator", "construct"})
_SUPPORTED_POLICIES = frozenset({"all_numeric_signals", "none"})
_CANONICAL_PATH = Path(__file__).with_name("construct_input_eligibility.json")
_SOURCE_FAMILIES = frozenset({"ohlc", "indicator", "oscillator", "construct"})


class FinancialToolInputCompatibilityError(ValueError):
    """Supplied sources do not satisfy a Financial Tool input contract."""


@dataclass(frozen=True, slots=True)
class FinancialToolInputSource:
    role: str
    family: SourceFamily
    output_name: str
    is_dependency: bool
    tool_key: str | None
    owner_id: str | None
    analysis_usable: bool
    value_type: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.role, "role"),
            (self.output_name, "output_name"),
            (self.value_type, "value_type"),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise FinancialToolInputCompatibilityError(
                    f"{field_name} must be canonical non-empty text"
                )
        if self.family not in _SOURCE_FAMILIES:
            raise FinancialToolInputCompatibilityError(
                f"unsupported source family: {self.family!r}"
            )
        if type(self.is_dependency) is not bool:
            raise FinancialToolInputCompatibilityError(
                "is_dependency must be boolean"
            )
        if type(self.analysis_usable) is not bool:
            raise FinancialToolInputCompatibilityError(
                "analysis_usable must be boolean"
            )
        if self.is_dependency:
            for value, field_name in (
                (self.tool_key, "tool_key"),
                (self.owner_id, "owner_id"),
            ):
                if not isinstance(value, str) or not value or value != value.strip():
                    raise FinancialToolInputCompatibilityError(
                        f"dependency {field_name} must be canonical non-empty text"
                    )
        elif self.tool_key is not None or self.owner_id is not None:
            raise FinancialToolInputCompatibilityError(
                "raw OHLC sources must not identify a dependency owner"
            )


def financial_tool_source_role_schema(
    spec: FinancialToolSpec,
) -> tuple[tuple[str, ...], ...]:
    if not isinstance(spec, FinancialToolSpec):
        raise TypeError("spec must be a FinancialToolSpec")
    if spec.key in {"derivative", "angle"}:
        return (("source",),)
    if spec.key == "delta":
        return (("fast", "slow"),)
    if spec.key in {"braids", "braid_instability"}:
        return (("fast", "mid", "slow"),)
    if spec.key == "trap_area":
        return (("fast", "slow"), ("fast", "mid", "slow"))
    if spec.key in {"percent_span_angle", "angle_momentum"}:
        return (("source_N",),)
    if spec.key == "universal_trend_classifier":
        return (("trend_peak", "trend_trough", "range_peak", "range_trough"),)
    return ((),)


def validate_financial_tool_source_roles(
    spec: FinancialToolSpec,
    roles: Sequence[str],
    *,
    allow_partial: bool = False,
) -> None:
    if not isinstance(spec, FinancialToolSpec):
        raise TypeError("spec must be a FinancialToolSpec")
    supplied = tuple(roles)
    if any(not isinstance(role, str) or not role for role in supplied):
        raise FinancialToolInputCompatibilityError(
            "source roles must be non-empty strings"
        )
    if len(set(supplied)) != len(supplied):
        raise FinancialToolInputCompatibilityError("source roles must be unique")

    schemas = financial_tool_source_role_schema(spec)
    if spec.key in {"percent_span_angle", "angle_momentum"}:
        indexes: list[int] = []
        for role in supplied:
            prefix, separator, suffix = role.partition("_")
            if prefix != "source" or separator != "_" or not suffix.isdigit():
                raise FinancialToolInputCompatibilityError(
                    "multi-source roles must use positive source_N identities"
                )
            index = int(suffix)
            if index < 1:
                raise FinancialToolInputCompatibilityError(
                    "multi-source roles must use positive source_N identities"
                )
            indexes.append(index)
        if not allow_partial and indexes != list(range(1, len(indexes) + 1)):
            raise FinancialToolInputCompatibilityError(
                "multi-source roles must be contiguous and ordered"
            )
        if not supplied and not allow_partial:
            raise FinancialToolInputCompatibilityError(
                "multi-source roles must contain at least one source"
            )
        return

    expected_sets = tuple(frozenset(schema) for schema in schemas)
    actual = frozenset(supplied)
    if spec.key == "universal_trend_classifier":
        if actual not in expected_sets:
            raise FinancialToolInputCompatibilityError(
                "UTC requires one complete Peaks & Troughs dependency set"
            )
        return
    if not allow_partial:
        if actual not in expected_sets:
            raise FinancialToolInputCompatibilityError(
                f"{spec.key} source roles are invalid"
            )
        return
    allowed = frozenset().union(*expected_sets)
    if not actual.issubset(allowed):
        raise FinancialToolInputCompatibilityError(
            f"{spec.key} source roles are invalid"
        )


def validate_financial_tool_inputs(
    spec: FinancialToolSpec,
    sources: Sequence[FinancialToolInputSource],
    *,
    parameters: Mapping[str, object] | None = None,
    allow_partial_roles: bool = False,
    family_scope: FamilyScope = "all",
) -> None:
    if family_scope not in {"all", "dependencies"}:
        raise ValueError(f"unsupported family_scope: {family_scope!r}")
    supplied = tuple(sources)
    if not all(isinstance(source, FinancialToolInputSource) for source in supplied):
        raise TypeError("sources must contain FinancialToolInputSource values")
    role_sources = supplied
    if spec.construct_io is None and spec.key != "universal_trend_classifier":
        role_sources = tuple(source for source in supplied if source.is_dependency)
    validate_financial_tool_source_roles(
        spec,
        tuple(source.role for source in role_sources),
        allow_partial=allow_partial_roles,
    )

    dependencies = tuple(source for source in supplied if source.is_dependency)
    for source in dependencies:
        if not source.analysis_usable or source.value_type != "numeric":
            raise FinancialToolInputCompatibilityError(
                "dependency output is not a numeric analysis source"
            )

    compatible = supplied if family_scope == "all" else dependencies
    construct = spec.construct_io
    if construct is not None:
        if any(
            source.family not in construct.allowed_source_families
            for source in compatible
        ):
            raise FinancialToolInputCompatibilityError(
                f"{spec.key} source-family mismatch"
            )
        families = {source.family for source in compatible}
        if construct.source_compatibility == "same_family" and len(families) > 1:
            raise FinancialToolInputCompatibilityError(
                f"{spec.key} requires same-family sources"
            )
        if construct.source_compatibility == "same_oscillator_type":
            tool_keys = {source.tool_key for source in compatible}
            if (
                any(source.family != "oscillator" for source in compatible)
                or len(tool_keys) > 1
            ):
                raise FinancialToolInputCompatibilityError(
                    f"{spec.key} requires one oscillator source type"
                )

    if spec.key == "universal_trend_classifier":
        by_role = {source.role: source for source in dependencies}
        owners = {source.owner_id for source in dependencies}
        if (
            len(dependencies) != 4
            or len(owners) != 1
            or any(
                source.family != "indicator" or source.tool_key != "peaks_troughs"
                for source in dependencies
            )
        ):
            raise FinancialToolInputCompatibilityError(
                "UTC requires one complete Peaks & Troughs dependency set"
            )
        resolved = {} if parameters is None else dict(parameters)
        trend_window = int(
            resolved.get("trend_fractal_window", resolved.get("fractal_window", 5))
        )
        range_window = int(resolved.get("range_fractal_window", 3))
        expected = {
            "trend_peak": f"peak_fractal_{trend_window}",
            "trend_trough": f"trough_fractal_{trend_window}",
            "range_peak": f"peak_fractal_{range_window}",
            "range_trough": f"trough_fractal_{range_window}",
        }
        if {role: source.output_name for role, source in by_role.items()} != expected:
            raise FinancialToolInputCompatibilityError(
                "UTC dependency outputs do not match trend/range windows"
            )


@dataclass(frozen=True, slots=True)
class ConstructInputEligibility:
    tool_key: str
    kind: ToolKind
    construct_source_policy: ConstructSourcePolicy


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def load_construct_input_eligibility(
    path: str | Path | None = None,
) -> Mapping[str, ConstructInputEligibility]:
    source = _CANONICAL_PATH if path is None else Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle, object_pairs_hook=_unique_object)
    if type(payload) is not dict or set(payload) != {"schema_version", "tools"}:
        raise ValueError("construct input eligibility must have exact top-level shape")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported construct input eligibility schema_version")
    tools = payload["tools"]
    if type(tools) is not dict:
        raise ValueError("construct input eligibility tools must be an object")

    registry: dict[str, ConstructInputEligibility] = {}
    for tool_key, entry in tools.items():
        if type(tool_key) is not str or not tool_key.strip():
            raise ValueError("construct input eligibility keys must be non-empty strings")
        if type(entry) is not dict or set(entry) != {"kind", "construct_source_policy"}:
            raise ValueError(f"malformed construct input eligibility entry: {tool_key!r}")
        kind = entry["kind"]
        policy = entry["construct_source_policy"]
        if type(kind) is not str or kind not in _SUPPORTED_KINDS:
            raise ValueError(f"unknown Financial Tool kind for {tool_key!r}: {kind!r}")
        if type(policy) is not str or policy not in _SUPPORTED_POLICIES:
            raise ValueError(f"unknown construct source policy for {tool_key!r}: {policy!r}")
        registry[tool_key] = ConstructInputEligibility(tool_key, kind, policy)
    return MappingProxyType(registry)


def validate_construct_input_eligibility(
    registry: Mapping[str, ConstructInputEligibility],
    specs: Mapping[str, object],
) -> None:
    if not isinstance(registry, Mapping):
        raise ValueError("construct input eligibility registry must be a mapping")
    if not isinstance(specs, Mapping):
        raise ValueError("Financial Tool specs must be a mapping")
    for tool_key, entry in registry.items():
        if type(tool_key) is not str or not tool_key.strip():
            raise ValueError("construct input eligibility keys must be non-empty strings")
        if not isinstance(entry, ConstructInputEligibility) or entry.tool_key != tool_key:
            raise ValueError(f"malformed construct input eligibility entry: {tool_key!r}")

    registry_keys = set(registry)
    spec_keys = set(specs)
    missing = tuple(sorted(spec_keys - registry_keys))
    unknown = tuple(sorted(registry_keys - spec_keys))
    if missing:
        raise ValueError(f"construct input eligibility is missing tools: {missing}")
    if unknown:
        raise ValueError(f"construct input eligibility has unknown tools: {unknown}")
    for tool_key, spec in specs.items():
        spec_kind = getattr(spec, "kind", None)
        if registry[tool_key].kind != spec_kind:
            raise ValueError(f"construct input eligibility kind mismatch: {tool_key!r}")


_CANONICAL_REGISTRY = load_construct_input_eligibility()


def construct_input_policy(tool_key: str) -> ConstructSourcePolicy:
    try:
        return _CANONICAL_REGISTRY[tool_key].construct_source_policy
    except (KeyError, TypeError) as exc:
        raise KeyError(f"unknown construct input eligibility key: {tool_key!r}") from exc
