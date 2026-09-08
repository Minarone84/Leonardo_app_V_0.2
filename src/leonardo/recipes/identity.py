"""Deterministic identities for global portable Recipe objects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from .models import (
        PortableRecipeDependencyV1,
        PortableRecipeOHLCVInputV1,
        PortableRecipeV1,
    )


ObjectSemanticKey: TypeAlias = bytes

_DEPENDENCY_SELECTOR_PARAMETERS = {
    "delta": ("fast", "slow"),
    "braids": ("fast", "mid", "slow"),
    "braid_instability": ("fast", "mid", "slow"),
    "trap_area": ("fast", "mid", "slow"),
    "percent_span_angle": ("source_columns",),
    "angle_momentum": ("source_columns",),
    "universal_trend_classifier": ("peak_column", "trough_column"),
}

_SELECTOR_INPUT_ROLES = {
    "delta": {"fast": ("fast",), "slow": ("slow",)},
    "braids": {
        "fast": ("fast",),
        "mid": ("mid",),
        "slow": ("slow",),
    },
    "braid_instability": {
        "fast": ("fast",),
        "mid": ("mid",),
        "slow": ("slow",),
    },
    "trap_area": {
        "fast": ("fast",),
        "mid": ("mid",),
        "slow": ("slow",),
    },
    "percent_span_angle": {"source_columns": ("source_",)},
    "angle_momentum": {"source_columns": ("source_",)},
    "universal_trend_classifier": {
        "peak_column": ("trend_peak",),
        "trough_column": ("trend_trough",),
    },
}


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def object_semantic_key(
    artifact_or_tool: str,
    parameters: Mapping[str, object],
    inputs: Sequence[Mapping[str, object]],
) -> ObjectSemanticKey:
    """Return the shared duplicate identity for a calculated object."""

    return _canonical_bytes(
        {
            "artifact_or_tool": artifact_or_tool,
            "parameters": _plain(parameters),
            "inputs": [_plain(item) for item in inputs],
        }
    )


def object_semantic_parameters(
    artifact_or_tool: str,
    parameters: Mapping[str, object],
    *,
    has_object_inputs: bool,
) -> dict[str, object]:
    """Remove source selectors already represented by semantic object inputs."""

    resolved = dict(parameters)
    if has_object_inputs:
        for name in _DEPENDENCY_SELECTOR_PARAMETERS.get(artifact_or_tool, ()):
            resolved.pop(name, None)
    return resolved


def normalize_portable_recipe_parameters(
    artifact_or_tool: str,
    parameters: Mapping[str, object],
    *,
    ohlcv_inputs: Sequence[PortableRecipeOHLCVInputV1] = (),
    dependencies: Sequence[PortableRecipeDependencyV1] = (),
) -> dict[str, object]:
    """Remove execution selectors represented by portable Recipe inputs."""

    input_roles = {
        item.role for item in (*tuple(ohlcv_inputs), *tuple(dependencies))
    }
    resolved = dict(parameters)
    for selector, role_prefixes in _SELECTOR_INPUT_ROLES.get(
        artifact_or_tool, {}
    ).items():
        if any(
            role == prefix or role.startswith(prefix)
            for role in input_roles
            for prefix in role_prefixes
        ):
            resolved.pop(selector, None)
    return resolved


def portable_recipe_object_semantic_key(
    recipe: PortableRecipeV1,
    dependency_key: Callable[[str], ObjectSemanticKey],
    *,
    implicit_ohlcv_inputs: Sequence[str] = (),
) -> ObjectSemanticKey:
    """Resolve one portable Recipe to tool, parameters, and actual inputs."""

    inputs: list[dict[str, object]] = [
        {
            "role": item.role,
            "source": "ohlcv",
            "column_name": item.column_name,
        }
        for item in recipe.ohlcv_inputs
    ]
    if not recipe.ohlcv_inputs and not recipe.dependencies:
        inputs.extend(
            {
                "role": column_name,
                "source": "ohlcv",
                "column_name": column_name,
            }
            for column_name in implicit_ohlcv_inputs
        )
    inputs.extend(
        {
            "role": item.role,
            "source": "object",
            "object_semantic_key": dependency_key(item.recipe_id).hex(),
            "output_name": item.output_name,
        }
        for item in recipe.dependencies
    )
    return object_semantic_key(
        recipe.tool_key,
        normalize_portable_recipe_parameters(
            recipe.tool_key,
            recipe.parameters,
            ohlcv_inputs=recipe.ohlcv_inputs,
            dependencies=recipe.dependencies,
        ),
        tuple(sorted(inputs, key=lambda item: str(item["role"]))),
    )


def compute_portable_recipe_id(
    *,
    tool_key: str,
    tool_version: str,
    kind: str,
    parameters: Mapping[str, object],
    output_names: Sequence[str],
    ohlcv_inputs: Sequence[PortableRecipeOHLCVInputV1],
    dependencies: Sequence[PortableRecipeDependencyV1],
    schema_version: str = "1.0",
    object_type: str = "portable_recipe",
) -> str:
    """Return the semantic identity of one portable Recipe."""

    return _sha256(
        portable_recipe_semantic_payload(
            tool_key=tool_key,
            tool_version=tool_version,
            kind=kind,
            parameters=parameters,
            output_names=output_names,
            ohlcv_inputs=ohlcv_inputs,
            dependencies=dependencies,
            schema_version=schema_version,
            object_type=object_type,
        )
    )


def portable_recipe_semantic_payload(
    *,
    tool_key: str,
    tool_version: str,
    kind: str,
    parameters: Mapping[str, object],
    output_names: Sequence[str],
    ohlcv_inputs: Sequence[PortableRecipeOHLCVInputV1],
    dependencies: Sequence[PortableRecipeDependencyV1],
    schema_version: str = "1.0",
    object_type: str = "portable_recipe",
) -> dict[str, object]:
    """Return the canonical executable semantics used by Recipe identity."""

    return {
        "schema_version": schema_version,
        "object_type": object_type,
        "tool_key": tool_key,
        "tool_version": tool_version,
        "kind": kind,
        "parameters": _plain(parameters),
        "output_names": list(output_names),
        "ohlcv_inputs": [item.to_dict() for item in ohlcv_inputs],
        "dependencies": [item.to_dict() for item in dependencies],
    }


def compute_portable_recipe_provenance_id(payload: Mapping[str, object]) -> str:
    """Return the identity of one exact Recipe/environment relationship."""

    return _sha256(payload)


def compute_portable_recipe_origin_id(payload: Mapping[str, object]) -> str:
    """Return the identity of one meaningful Recipe persistence origin."""

    return _sha256(payload)


def compute_portable_recipe_collection_revision_id(
    payload: Mapping[str, object],
) -> str:
    """Return the identity of one immutable Collection revision."""

    return _sha256(payload)


def build_portable_recipe(
    *,
    tool_key: str,
    kind: str,
    parameters: Mapping[str, object],
    output_names: Sequence[str],
    ohlcv_inputs: Sequence[PortableRecipeOHLCVInputV1] = (),
    dependencies: Sequence[PortableRecipeDependencyV1] = (),
    tool_version: str = "1.0",
):
    """Build a validated Recipe without requiring callers to hash it."""

    from .models import PortableRecipeV1, PortableRecipeValidationError

    ordered_ohlcv = tuple(sorted(ohlcv_inputs, key=lambda item: (item.role, item.column_name)))
    ordered_dependencies = tuple(
        sorted(
            dependencies,
            key=lambda item: (item.role, item.recipe_id, item.output_name),
        )
    )
    semantic_parameters = normalize_portable_recipe_parameters(
        tool_key,
        parameters,
        ohlcv_inputs=ordered_ohlcv,
        dependencies=ordered_dependencies,
    )
    try:
        recipe_id = compute_portable_recipe_id(
            tool_key=tool_key,
            tool_version=tool_version,
            kind=kind,
            parameters=semantic_parameters,
            output_names=output_names,
            ohlcv_inputs=ordered_ohlcv,
            dependencies=ordered_dependencies,
        )
    except (TypeError, ValueError) as exc:
        raise PortableRecipeValidationError(
            "portable Recipe parameters must contain finite JSON-safe values"
        ) from exc
    return PortableRecipeV1(
        recipe_id=recipe_id,
        tool_key=tool_key,
        tool_version=tool_version,
        kind=kind,
        parameters=semantic_parameters,
        output_names=tuple(output_names),
        ohlcv_inputs=ordered_ohlcv,
        dependencies=ordered_dependencies,
    )


__all__ = (
    "ObjectSemanticKey",
    "build_portable_recipe",
    "compute_portable_recipe_collection_revision_id",
    "compute_portable_recipe_id",
    "compute_portable_recipe_provenance_id",
    "normalize_portable_recipe_parameters",
    "object_semantic_key",
    "object_semantic_parameters",
    "portable_recipe_object_semantic_key",
    "portable_recipe_semantic_payload",
)
