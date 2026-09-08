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
from leonardo.recipes.identity import portable_recipe_object_semantic_key
from leonardo.recipes.models import (
    PortableRecipeOriginV1,
    PortableRecipePersistenceMetadataV1,
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


@pytest.mark.parametrize(
    ("tool_key", "parameters", "ohlcv_inputs", "dependencies", "expected"),
    (
        (
            "angle_momentum",
            {"n": 3, "source_columns": "close"},
            (PortableRecipeOHLCVInputV1("source_1", "close"),),
            (),
            {"n": 3},
        ),
        (
            "angle_momentum",
            {"n": 3, "source_columns": "close"},
            (),
            (PortableRecipeDependencyV1("source_1", _sma(14).recipe_id, "sma_14"),),
            {"n": 3},
        ),
        (
            "delta",
            {"fast": "close", "slow": "sma_14", "mode": "abs", "eps": 1e-12},
            (PortableRecipeOHLCVInputV1("fast", "close"),),
            (PortableRecipeDependencyV1("slow", _sma(14).recipe_id, "sma_14"),),
            {"mode": "abs", "eps": 1e-12},
        ),
        (
            "braids",
            {"fast": "a", "mid": "b", "slow": "c", "tie_policy": "carry"},
            (),
            tuple(
                PortableRecipeDependencyV1(role, _sma(period).recipe_id, f"sma_{period}")
                for role, period in zip(("fast", "mid", "slow"), (10, 20, 30), strict=True)
            ),
            {"tie_policy": "carry"},
        ),
        (
            "braid_instability",
            {"fast": "a", "mid": "b", "slow": "c", "n": 5},
            (),
            tuple(
                PortableRecipeDependencyV1(role, _sma(period).recipe_id, f"sma_{period}")
                for role, period in zip(("fast", "mid", "slow"), (10, 20, 30), strict=True)
            ),
            {"n": 5},
        ),
        (
            "trap_area",
            {"fast": "a", "mid": "b", "slow": "c", "window": 5},
            (),
            tuple(
                PortableRecipeDependencyV1(role, _sma(period).recipe_id, f"sma_{period}")
                for role, period in zip(("fast", "mid", "slow"), (10, 20, 30), strict=True)
            ),
            {"window": 5},
        ),
        (
            "percent_span_angle",
            {"source_columns": "close", "period": 5},
            (PortableRecipeOHLCVInputV1("source_1", "close"),),
            (),
            {"period": 5},
        ),
        (
            "universal_trend_classifier",
            {
                "trend_fractal_window": 5,
                "range_fractal_window": 3,
                "peak_column": "peak_fractal_5",
                "trough_column": "trough_fractal_5",
            },
            (),
            (
                PortableRecipeDependencyV1("trend_peak", _sma(14).recipe_id, "peak_fractal_5"),
                PortableRecipeDependencyV1("trend_trough", _sma(14).recipe_id, "trough_fractal_5"),
            ),
            {"trend_fractal_window": 5, "range_fractal_window": 3},
        ),
    ),
)
def test_new_recipes_persist_only_semantic_parameters(
    tool_key: str,
    parameters: dict[str, object],
    ohlcv_inputs: tuple[PortableRecipeOHLCVInputV1, ...],
    dependencies: tuple[PortableRecipeDependencyV1, ...],
    expected: dict[str, object],
) -> None:
    recipe = build_portable_recipe(
        tool_key=tool_key,
        kind="construct" if tool_key != "universal_trend_classifier" else "indicator",
        parameters=parameters,
        output_names=("output",),
        ohlcv_inputs=ohlcv_inputs,
        dependencies=dependencies,
    )

    assert dict(recipe.parameters) == expected


def test_recipe_parameter_normalization_requires_actual_input_evidence() -> None:
    recipe = build_portable_recipe(
        tool_key="angle_momentum",
        kind="construct",
        parameters={"n": 3, "source_columns": "close"},
        output_names=("output",),
    )

    assert dict(recipe.parameters) == {"n": 3, "source_columns": "close"}


def test_legacy_recipe_with_selector_residue_remains_readable() -> None:
    dependency = PortableRecipeDependencyV1(
        "source_1", _sma(14).recipe_id, "sma_14"
    )
    parameters = {"n": 3, "source_columns": "close"}
    recipe_id = compute_portable_recipe_id(
        tool_key="angle_momentum",
        tool_version="1.0",
        kind="construct",
        parameters=parameters,
        output_names=("angle_momentum",),
        ohlcv_inputs=(),
        dependencies=(dependency,),
    )
    payload = {
        "schema_version": "1.0",
        "object_type": "portable_recipe",
        "recipe_id": recipe_id,
        "tool_key": "angle_momentum",
        "tool_version": "1.0",
        "kind": "construct",
        "parameters": parameters,
        "output_names": ["angle_momentum"],
        "ohlcv_inputs": [],
        "dependencies": [dependency.to_dict()],
    }

    loaded = type(_sma()).from_dict(payload)
    canonical = build_portable_recipe(
        tool_key="angle_momentum",
        kind="construct",
        parameters=parameters,
        output_names=("angle_momentum",),
        dependencies=(dependency,),
    )
    assert dict(loaded.parameters) == parameters
    assert loaded.recipe_id != canonical.recipe_id
    assert portable_recipe_object_semantic_key(
        loaded, lambda _recipe_id: b"sma"
    ) == portable_recipe_object_semantic_key(
        canonical, lambda _recipe_id: b"sma"
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


def test_persistence_metadata_is_separate_from_recipe_semantic_identity() -> None:
    recipe = _sma()
    recorded_at = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    origin = PortableRecipeOriginV1.build(
        origin_kind="research_save",
        origin_recorded_at_utc=recorded_at,
        details={"study_id": "study_one"},
    )
    metadata = PortableRecipePersistenceMetadataV1(
        recipe.recipe_id, recorded_at, (origin,)
    )

    assert PortableRecipePersistenceMetadataV1.from_dict(metadata.to_dict()) == metadata
    assert recipe.recipe_id == _sma().recipe_id
    assert "first_persisted_at_utc" not in recipe.to_dict()
    assert "origins" not in recipe.to_dict()


def test_origin_identity_deduplicates_meaningful_origin_data() -> None:
    first = PortableRecipeOriginV1.build(
        origin_kind="research_save",
        origin_recorded_at_utc=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        details={"study_id": "study_one"},
    )
    repeated = PortableRecipeOriginV1.build(
        origin_kind="research_save",
        origin_recorded_at_utc=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
        details={"study_id": "study_one"},
    )
    distinct = PortableRecipeOriginV1.build(
        origin_kind="research_save",
        origin_recorded_at_utc=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
        details={"study_id": "study_two"},
    )

    assert repeated.origin_id == first.origin_id
    assert distinct.origin_id != first.origin_id
    no_study_identifier = PortableRecipeOriginV1.build(
        origin_kind="research_save",
        origin_recorded_at_utc=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        details={},
    )
    assert no_study_identifier.details == {}
