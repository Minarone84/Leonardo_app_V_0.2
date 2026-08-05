from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from leonardo.data import MarketId
from leonardo.recipes import (
    PortableRecipeCollectionRevisionV1,
    PortableRecipeDependencyV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeProvenanceV1,
    PortableRecipeValidationError,
    build_portable_recipe,
    compute_portable_recipe_id,
)


def _sma(period: int = 20, *, role: str = "source", dependency=None):
    return build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": period},
        output_names=(f"sma_{period}",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1(role, "close"),)
        if dependency is None
        else (),
        dependencies=() if dependency is None else (dependency,),
    )


def test_recipe_identity_is_semantic_and_strict() -> None:
    first = _sma()
    second = _sma()
    assert first.recipe_id == second.recipe_id
    assert _sma(21).recipe_id != first.recipe_id
    assert json.loads(first.canonical_json_bytes()) == first.to_dict()
    with pytest.raises(PortableRecipeValidationError):
        type(first).from_dict({**first.to_dict(), "extra": True})
    with pytest.raises(PortableRecipeValidationError, match="finite"):
        build_portable_recipe(
            tool_key="sma",
            kind="indicator",
            parameters={"period": float("nan")},
            output_names=("sma",),
        )
    with pytest.raises(PortableRecipeValidationError, match="dynamic_binning"):
        build_portable_recipe(
            tool_key="dynamic_binning",
            kind="construct",
            parameters={},
            output_names=("bins",),
        )


def test_recipe_from_dict_rejects_matching_identity_with_string_output_names() -> None:
    recipe = _sma()
    payload = recipe.to_dict()
    payload["output_names"] = "ab"
    payload["recipe_id"] = compute_portable_recipe_id(
        tool_key=recipe.tool_key,
        tool_version=recipe.tool_version,
        kind=recipe.kind,
        parameters=recipe.parameters,
        output_names="ab",
        ohlcv_inputs=recipe.ohlcv_inputs,
        dependencies=recipe.dependencies,
    )

    with pytest.raises(PortableRecipeValidationError, match="JSON array"):
        type(recipe).from_dict(payload)


@pytest.mark.parametrize(
    ("field", "malformed"),
    (
        (field, malformed)
        for field in ("output_names", "ohlcv_inputs", "dependencies")
        for malformed in ("value", (), {}, 1, None)
    ),
)
def test_recipe_from_dict_requires_json_arrays(field: str, malformed: object) -> None:
    payload = _sma().to_dict()
    payload[field] = malformed
    with pytest.raises(PortableRecipeValidationError, match="JSON array"):
        type(_sma()).from_dict(payload)


@pytest.mark.parametrize(
    ("field", "malformed"),
    (
        (field, malformed)
        for field in ("root_recipe_ids", "member_recipe_ids")
        for malformed in ("value", (), {}, 1, None)
    ),
)
def test_collection_from_dict_requires_json_recipe_id_arrays(
    field: str, malformed: object
) -> None:
    recipe = _sma()
    revision = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_" + "a" * 32,
        display_name="Collection",
        description="",
        root_recipe_ids=(recipe.recipe_id,),
        member_recipe_ids=(recipe.recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    payload = revision.to_dict()
    payload[field] = malformed
    with pytest.raises(PortableRecipeValidationError, match="JSON array"):
        PortableRecipeCollectionRevisionV1.from_dict(payload)


def test_dependency_output_and_role_change_recipe_identity() -> None:
    upstream = _sma()
    first = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"period": 1},
        output_names=("sma_20_derivative",),
        dependencies=(
            PortableRecipeDependencyV1("source", upstream.recipe_id, "sma_20"),
        ),
    )
    output_changed = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"period": 1},
        output_names=("sma_20_derivative",),
        dependencies=(
            PortableRecipeDependencyV1("source", upstream.recipe_id, "other"),
        ),
    )
    role_changed = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"period": 1},
        output_names=("sma_20_derivative",),
        dependencies=(
            PortableRecipeDependencyV1("input", upstream.recipe_id, "sma_20"),
        ),
    )
    assert len({first.recipe_id, output_changed.recipe_id, role_changed.recipe_id}) == 3


def test_provenance_changes_without_changing_recipe_identity() -> None:
    recipe = _sma()
    values = dict(
        recipe_id=recipe.recipe_id,
        study_environment_id="env_one",
        study_environment_content_hash="a" * 64,
        study_environment_updated_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
        study_environment_display_name="Environment",
        study_entry_id="entry_one",
        study_display_name="SMA 20",
        study_description="Average",
    )
    btc = PortableRecipeProvenanceV1.build(
        origin_market_id=MarketId("bybit", "linear", "BTCUSDT", "4h"), **values
    )
    link = PortableRecipeProvenanceV1.build(
        origin_market_id=MarketId("bybit", "linear", "LINKUSDT", "1h"), **values
    )
    assert btc.recipe_id == link.recipe_id == recipe.recipe_id
    assert btc.provenance_id != link.provenance_id
    assert PortableRecipeProvenanceV1.from_dict(btc.to_dict()) == btc
    changed_revision = PortableRecipeProvenanceV1.build(
        origin_market_id=btc.origin_market_id,
        **{**values, "study_environment_content_hash": "b" * 64},
    )
    assert changed_revision.provenance_id != btc.provenance_id
