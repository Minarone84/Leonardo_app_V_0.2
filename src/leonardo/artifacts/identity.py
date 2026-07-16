from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from leonardo.data import MarketId, canonicalize_market_id

from .models import ArtifactMetadataV1, ArtifactRecipeV1, ArtifactSourceRefV1


def canonical_json_identity_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def market_id_to_dict(market_id: MarketId) -> dict[str, str]:
    canonical = canonicalize_market_id(
        market_id.exchange,
        market_id.market_type,
        market_id.symbol,
        market_id.timeframe,
    )
    if canonical != market_id:
        raise ValueError("market_id must already be canonical")
    return {
        "exchange": market_id.exchange,
        "market_type": market_id.market_type,
        "symbol": market_id.symbol,
        "timeframe": market_id.timeframe,
    }


def recipe_identity_payload(
    *,
    market_id: MarketId,
    tool_key: str,
    kind: str,
    parameters: Mapping[str, object],
    bindings: Mapping[str, object],
    output_names: Sequence[str],
    source_artifacts: Sequence[ArtifactSourceRefV1],
    schema_version: str = "1.0",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "market_id": market_id_to_dict(market_id),
        "tool_key": tool_key,
        "kind": kind,
        "parameters": _plain(parameters),
        "bindings": _plain(bindings),
        "output_names": list(output_names),
        "source_artifacts": [item.to_dict() for item in source_artifacts],
    }


def compute_recipe_id(recipe: ArtifactRecipeV1) -> str:
    payload = recipe_identity_payload(
        schema_version=recipe.schema_version,
        market_id=recipe.market_id,
        tool_key=recipe.tool_key,
        kind=recipe.kind,
        parameters=recipe.parameters,
        bindings=recipe.bindings,
        output_names=recipe.output_names,
        source_artifacts=recipe.source_artifacts,
    )
    return hashlib.sha256(canonical_json_identity_bytes(payload)).hexdigest()


def artifact_identity_payload(
    *,
    recipe_id: str,
    source_ohlcv: Mapping[str, object],
    source_artifacts: Sequence[ArtifactSourceRefV1],
    row_count: int,
    first_timestamp_ms: int,
    last_timestamp_ms: int,
    values_sha256: str,
    analysis_sha256: str | None,
    schema_version: str = "1.0",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "recipe_id": recipe_id,
        "source_ohlcv": _plain(source_ohlcv),
        "source_artifacts": [item.to_dict() for item in source_artifacts],
        "row_count": row_count,
        "first_timestamp_ms": first_timestamp_ms,
        "last_timestamp_ms": last_timestamp_ms,
        "values_sha256": values_sha256,
        "analysis_sha256": analysis_sha256,
    }


def compute_artifact_id(metadata: ArtifactMetadataV1) -> str:
    payload = artifact_identity_payload(
        schema_version=metadata.schema_version,
        recipe_id=metadata.recipe.recipe_id,
        source_ohlcv=metadata.source_ohlcv.to_dict(),
        source_artifacts=metadata.recipe.source_artifacts,
        row_count=metadata.row_count,
        first_timestamp_ms=metadata.first_timestamp_ms,
        last_timestamp_ms=metadata.last_timestamp_ms,
        values_sha256=metadata.values_sha256,
        analysis_sha256=metadata.analysis_sha256,
    )
    return hashlib.sha256(canonical_json_identity_bytes(payload)).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value

