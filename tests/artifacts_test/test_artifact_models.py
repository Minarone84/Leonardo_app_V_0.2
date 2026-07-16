from __future__ import annotations

import json
import hashlib
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from leonardo.artifacts.identity import canonical_json_identity_bytes, recipe_identity_payload
from leonardo.artifacts.models import (
    ArtifactMetadataV1,
    ArtifactRecipeV1,
    ArtifactSourceRefV1,
    ArtifactValidationError,
    LoadedArtifact,
    OHLCVSourceFingerprintV1,
)
from leonardo.data import MarketId
from leonardo.financial_tools import calculate_financial_tool

from test_artifact_service_roundtrip import _frame


FIXTURES = Path(__file__).with_name("fixtures")


def _fixture() -> dict[str, object]:
    return json.loads((FIXTURES / "task_1016_identity_fixtures.json").read_text(encoding="utf-8"))


def _recipe(*, display_name: str = "SMA", description: str = "") -> ArtifactRecipeV1:
    fixture = _fixture()
    market = OHLCVSourceFingerprintV1.from_dict(fixture["source_ohlcv"]).market_id  # type: ignore[arg-type]
    return ArtifactRecipeV1(
        recipe_id=str(fixture["expected_recipe_id"]),
        market_id=market,
        tool_key="sma",
        kind="indicator",
        parameters={"period": 3},
        bindings={},
        output_names=("sma_3",),
        source_artifacts=(),
        display_name=display_name,
        description=description,
        created_at_utc=datetime(2025, 1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
    )


def _metadata() -> ArtifactMetadataV1:
    fixture = _fixture()
    return ArtifactMetadataV1(
        artifact_id=str(fixture["expected_artifact_id"]),
        recipe=_recipe(),
        source_ohlcv=OHLCVSourceFingerprintV1.from_dict(fixture["source_ohlcv"]),  # type: ignore[arg-type]
        row_count=4,
        first_timestamp_ms=1_700_000_000_000,
        last_timestamp_ms=1_700_000_180_000,
        values_sha256=str(fixture["expected_values_sha256"]),
        analysis_filename=None,
        analysis_sha256=None,
        created_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_persisted_models_round_trip_and_normalize_utc() -> None:
    recipe = _recipe()
    assert recipe.created_at_utc == datetime(2025, 1, 1, tzinfo=UTC)
    assert ArtifactRecipeV1.from_dict(recipe.to_dict()) == recipe
    metadata = _metadata()
    assert ArtifactMetadataV1.from_dict(metadata.to_dict()) == metadata
    source = metadata.source_ohlcv
    assert OHLCVSourceFingerprintV1.from_dict(source.to_dict()) == source


def test_mappings_are_immutable_and_defensive() -> None:
    parameters = {"period": 3}
    recipe = _recipe()
    parameters["period"] = 4
    assert recipe.parameters == {"period": 3}
    with pytest.raises(TypeError):
        recipe.parameters["period"] = 4  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        recipe.tool_key = "ema"  # type: ignore[misc]


def test_loaded_artifact_returns_defensive_copies() -> None:
    frame = pd.DataFrame({"ts_ms": [1, 2], "sma_3": [1.0, 2.0]})
    loaded = LoadedArtifact(_metadata(), frame, {"nested": {"value": 1}})
    returned_frame = loaded.frame
    returned_frame.loc[0, "sma_3"] = 99
    returned_analysis = loaded.analysis
    returned_analysis["nested"]["value"] = 2  # type: ignore[index]
    assert loaded.frame.loc[0, "sma_3"] == 1.0
    assert loaded.analysis == {"nested": {"value": 1}}
    assert loaded.metadata == _metadata()


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_nonfinite_recipe_mappings_are_rejected(value: float) -> None:
    with pytest.raises(ArtifactValidationError):
        ArtifactRecipeV1(
            recipe_id="0" * 64,
            market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
            tool_key="sma",
            kind="indicator",
            parameters={"period": 3, "invalid": value},
            bindings={},
            output_names=("sma_3",),
            source_artifacts=(),
            display_name="SMA",
            description="",
            created_at_utc=datetime.now(UTC),
        )


def test_noncanonical_market_and_unsupported_versions_are_rejected() -> None:
    fixture = _fixture()
    source = dict(fixture["source_ohlcv"])  # type: ignore[arg-type]
    source["market_id"] = {"exchange": "BYBIT", "market_type": "linear", "symbol": "BTCUSDT", "timeframe": "1m"}
    with pytest.raises(ArtifactValidationError):
        OHLCVSourceFingerprintV1.from_dict(source)
    source = dict(fixture["source_ohlcv"])  # type: ignore[arg-type]
    source["schema_version"] = "2.0"
    with pytest.raises(ArtifactValidationError):
        OHLCVSourceFingerprintV1.from_dict(source)


def test_hashes_ids_and_recipe_identity_are_validated() -> None:
    recipe = _recipe()
    payload = recipe.to_dict()
    payload["recipe_id"] = "f" * 64
    with pytest.raises(ArtifactValidationError, match="recipe_id"):
        ArtifactRecipeV1.from_dict(payload)
    metadata = _metadata().to_dict()
    metadata["artifact_id"] = "f" * 64
    with pytest.raises(ArtifactValidationError, match="artifact_id"):
        ArtifactMetadataV1.from_dict(metadata)
    with pytest.raises(ArtifactValidationError):
        ArtifactSourceRefV1("source", "ABC", "sma_3")


def test_source_roles_are_unique_and_sorted() -> None:
    first = ArtifactSourceRefV1("slow", "b" * 64, "ema_20")
    second = ArtifactSourceRefV1("fast", "a" * 64, "ema_9")
    fixture = _fixture()
    market = OHLCVSourceFingerprintV1.from_dict(fixture["source_ohlcv"]).market_id  # type: ignore[arg-type]
    payload = {
        "schema_version": "1.0",
        "market_id": {"exchange": "bybit", "market_type": "linear", "symbol": "BTCUSDT", "timeframe": "1m"},
        "tool_key": "sma",
        "kind": "indicator",
        "parameters": {"period": 3},
        "bindings": {},
        "output_names": ["sma_3"],
        "source_artifacts": [second.to_dict(), first.to_dict()],
    }
    recipe_id = __import__("hashlib").sha256(canonical_json_identity_bytes(payload)).hexdigest()
    recipe = ArtifactRecipeV1(
        recipe_id=recipe_id, market_id=market, tool_key="sma", kind="indicator",
        parameters={"period": 3}, bindings={}, output_names=("sma_3",),
        source_artifacts=(first, second), display_name="SMA", description="",
        created_at_utc=datetime.now(UTC),
    )
    assert tuple(item.role for item in recipe.source_artifacts) == ("fast", "slow")
    with pytest.raises(ArtifactValidationError, match="roles"):
        ArtifactRecipeV1(
            recipe_id=recipe_id, market_id=market, tool_key="sma", kind="indicator",
            parameters={"period": 3}, bindings={}, output_names=("sma_3",),
            source_artifacts=(second, ArtifactSourceRefV1("fast", "c" * 64, "ema_20")),
            display_name="SMA", description="", created_at_utc=datetime.now(UTC),
        )


def _recipe_payload_for(tool_key: str, parameters: dict[str, object], **kwargs: object) -> dict[str, object]:
    result = calculate_financial_tool(tool_key, _frame(), parameters, **kwargs)
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    identity = recipe_identity_payload(
        market_id=market,
        tool_key=result.tool_key,
        kind=result.kind,
        parameters=result.parameters,
        bindings=result.bindings,
        output_names=result.output_names,
        source_artifacts=(),
    )
    recipe_id = hashlib.sha256(canonical_json_identity_bytes(identity)).hexdigest()
    return ArtifactRecipeV1(
        recipe_id=recipe_id,
        market_id=market,
        tool_key=result.tool_key,
        kind=result.kind,
        parameters=result.parameters,
        bindings=result.bindings,
        output_names=result.output_names,
        source_artifacts=(),
        display_name=result.tool_key,
        description="",
        created_at_utc=datetime.now(UTC),
    ).to_dict()


@pytest.mark.parametrize(
    "payload",
    (
        lambda: _recipe_payload_for("derivative", {"order": 1}, bindings={"source": "close"}),
        lambda: _recipe_payload_for("dynamic_binning", {"window": 2}),
        lambda: _recipe_payload_for("percent_span_angle", {"window": 2}),
        lambda: _recipe_payload_for(
            "braids", {"fast": "open", "mid": "close", "slow": "volume"}
        ),
    ),
)
def test_recipe_deserialization_rejects_invalid_result_configuration(payload: object) -> None:
    recipe = payload()  # type: ignore[operator]
    if recipe["tool_key"] == "derivative":
        recipe["bindings"] = {"source": " close "}
    elif recipe["tool_key"] in {"dynamic_binning", "percent_span_angle"}:
        recipe["parameters"]["window"] = 1  # type: ignore[index]
    else:
        recipe["parameters"]["mid"] = ""  # type: ignore[index]
    with pytest.raises(ArtifactValidationError, match="Financial Tool semantics"):
        ArtifactRecipeV1.from_dict(recipe)


def test_recipe_deserialization_rejects_wrong_output_names() -> None:
    recipe = _recipe().to_dict()
    recipe["output_names"] = ["wrong"]
    with pytest.raises(ArtifactValidationError, match="Financial Tool semantics"):
        ArtifactRecipeV1.from_dict(recipe)


def test_artifact_metadata_requires_full_source_coverage() -> None:
    metadata = _metadata()
    with pytest.raises(ArtifactValidationError, match="coverage"):
        ArtifactMetadataV1(
            artifact_id=metadata.artifact_id,
            recipe=metadata.recipe,
            source_ohlcv=metadata.source_ohlcv,
            row_count=metadata.row_count - 1,
            first_timestamp_ms=metadata.first_timestamp_ms,
            last_timestamp_ms=metadata.last_timestamp_ms - 60_000,
            values_sha256=metadata.values_sha256,
            analysis_filename=None,
            analysis_sha256=None,
            created_at_utc=metadata.created_at_utc,
        )


def test_direct_invalid_source_reference_has_typed_validation_error() -> None:
    recipe = _recipe()
    with pytest.raises(ArtifactValidationError, match="ArtifactSourceRefV1"):
        ArtifactRecipeV1(
            recipe_id=recipe.recipe_id,
            market_id=recipe.market_id,
            tool_key=recipe.tool_key,
            kind=recipe.kind,
            parameters=recipe.parameters,
            bindings=recipe.bindings,
            output_names=recipe.output_names,
            source_artifacts=({},),  # type: ignore[arg-type]
            display_name=recipe.display_name,
            description=recipe.description,
            created_at_utc=recipe.created_at_utc,
        )
