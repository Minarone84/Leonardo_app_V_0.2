"""Deterministic identities for global portable Recipe objects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import PortableRecipeDependencyV1, PortableRecipeOHLCVInputV1


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

    payload = {
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
    return _sha256(payload)


def compute_portable_recipe_provenance_id(payload: Mapping[str, object]) -> str:
    """Return the identity of one exact Recipe/environment relationship."""

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
    try:
        recipe_id = compute_portable_recipe_id(
            tool_key=tool_key,
            tool_version=tool_version,
            kind=kind,
            parameters=parameters,
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
        parameters=parameters,
        output_names=tuple(output_names),
        ohlcv_inputs=ordered_ohlcv,
        dependencies=ordered_dependencies,
    )


__all__ = (
    "build_portable_recipe",
    "compute_portable_recipe_collection_revision_id",
    "compute_portable_recipe_id",
    "compute_portable_recipe_provenance_id",
)
