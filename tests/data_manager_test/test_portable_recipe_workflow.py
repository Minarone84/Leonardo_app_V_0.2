from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from leonardo.data import MarketId
from leonardo.data_manager import DataManagerOperationError, DataManagerService
from leonardo.data_manager.models import DataManagerPortableRecipeEntry
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeOHLCVInputV1,
    PortableRecipeStore,
    build_portable_recipe,
)
from leonardo.research import (
    StudyEnvironmentDraft,
    StudyEnvironmentSourceV1,
    StudyEnvironmentStore,
)

from tests.data_manager_test.test_data_manager_service import _Artifacts, _Catalog, _Loader
from tests.research_test.test_study_environment_models import fixture_environment


def _domain(tmp_path: Path):
    source = fixture_environment()
    ticks = iter(
        source.created_at_utc + timedelta(minutes=value) for value in range(20)
    )
    environments = StudyEnvironmentStore(
        tmp_path / "environments", clock=lambda: next(ticks)
    )
    recipes = PortableRecipeStore(
        tmp_path / "data_manager",
        clock=lambda: datetime(2026, 8, 2, tzinfo=UTC),
        collection_id_factory=lambda: "d" * 32,
    )
    service = DataManagerService(
        _Catalog(),
        _Loader(),
        _Artifacts(),
        environments,
        recipes,
        PortableRecipeGraphPlanner(recipes),
    )
    return service, environments, recipes


def _save_environment(
    store: StudyEnvironmentStore,
    *,
    environment_id: str = "env_portable",
    display_name: str = "Portable Environment",
    market: MarketId | None = MarketId("bybit", "linear", "BTCUSDT", "1h"),
    entries=None,
):
    source = fixture_environment()
    return store.create(
        StudyEnvironmentDraft(
            display_name,
            source.description,
            market,
            source.entries if entries is None else tuple(entries),
            environment_id,
        )
    )


def test_environment_catalog_classifies_and_filters_global_truth(tmp_path: Path) -> None:
    service, environments, _recipes = _domain(tmp_path)
    _save_environment(environments)
    _save_environment(
        environments,
        environment_id="env_unsupported",
        display_name="No Origin",
        market=None,
    )
    (environments.root_dir / "broken.json").write_text("{", encoding="utf-8")

    catalog = service.scan_study_environments()
    assert tuple(item.environment_id for item in catalog.environments) == (
        "broken", "env_unsupported", "env_portable"
    )
    portable = next(item for item in catalog.environments if item.environment_id == "env_portable")
    assert (
        portable.portable_count,
        portable.portable_with_dependencies_count,
        portable.market_bound_count,
        portable.unsupported_count,
        portable.invalid_count,
    ) == (2, 1, 1, 0, 0)
    assert service.scan_study_environments(exchange="BYBIT").environments == (portable,)
    assert service.scan_study_environments(market_type="Linear").environments == (portable,)
    assert service.scan_study_environments(symbol="BTC/USDT").environments == (portable,)
    assert service.scan_study_environments(timeframe="1h").environments == (portable,)
    assert service.scan_study_environments(
        exchange="bybit", market_type="Linear", symbol="BTC/USDT",
        timeframe="1h", display_name_text="portable"
    ).environments == (portable,)
    invalid = next(item for item in catalog.environments if item.environment_id == "broken")
    assert not invalid.valid and invalid.rejection_reason
    unsupported = next(
        item for item in catalog.environments if item.environment_id == "env_unsupported"
    )
    assert unsupported.unsupported_count == 4


def test_derivation_includes_support_excludes_presentation_and_persists_once(
    tmp_path: Path,
) -> None:
    service, environments, recipes = _domain(tmp_path)
    environment = _save_environment(environments)
    plan = service.plan_recipe_derivation(environment.environment_id, ("entry_003",))
    assert not plan.blocked
    assert plan.root_entry_ids == ("entry_003",)
    assert plan.support_entry_ids == ("entry_001", "entry_002")
    assert tuple(item.status for item in plan.entry_classifications) == (
        "PORTABLE", "PORTABLE", "PORTABLE_WITH_DEPENDENCIES", "MARKET_BOUND"
    )
    assert len(plan.execution_stages) == 2
    encoded = b"".join(item.canonical_json_bytes() for item in plan.recipes)
    for excluded in (b"presentation", b"display_name", b"user_metadata", b"BTCUSDT"):
        assert excluded not in encoded

    result = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_003",),
        create_collection=False,
    )
    repeated = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_003",),
        create_collection=False,
    )
    assert repeated == result
    assert len(recipes.list_recipe_summaries()) == 3
    assert all(len(recipes.list_provenance(item.recipe_id)) == 1 for item in plan.recipes)
    library = service.scan_portable_recipes(
        origin_exchange="bybit", origin_symbol="BTCUSDT"
    )
    assert len(library.recipes) == 3
    assert service.scan_portable_recipes(display_name_text="EMA 20").recipes[0].tool_key == "ema"
    assert {item.recipe_id for item in library.recipes} == {
        item.recipe_id for item in plan.recipes
    }


def test_recipe_read_projection_preserves_canonical_input_binding_order(
    tmp_path: Path,
) -> None:
    service, environments, _recipes = _domain(tmp_path)
    source = fixture_environment()
    delta_output = resolve_output_names(
        "delta",
        {**source.entries[2].parameters, "fast": "close", "slow": "research_slow"},
    )[0]
    delta = replace(
        source.entries[2],
        sources=(
            StudyEnvironmentSourceV1(
                "fast", "ohlcv", column_name="close"
            ),
            StudyEnvironmentSourceV1(
                "slow",
                "environment",
                source_entry_id="entry_002",
                output_name="rsi_14",
            ),
        ),
        expected_output_names=(delta_output,),
        presentation=replace(
            source.entries[2].presentation,
            line_styles=(
                replace(
                    source.entries[2].presentation.line_styles[0],
                    output_name=delta_output,
                ),
            ),
        ),
    )
    environment = _save_environment(
        environments,
        environment_id="env_bindings",
        entries=(source.entries[0], source.entries[1], delta, source.entries[3]),
    )
    plan = service.plan_recipe_derivation(
        environment.environment_id, ("entry_003",)
    )
    assert plan.support_entry_ids == ("entry_002",)
    service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_003",),
        create_collection=False,
    )

    planned_by_tool = {item.tool_key: item for item in plan.recipes}
    projected_by_tool = {
        item.tool_key: item for item in service.scan_portable_recipes().recipes
    }
    dependency_id = planned_by_tool["rsi"].recipe_id
    assert projected_by_tool["delta"].input_bindings == (
        "fast=OHLCV.close",
        f"slow=Recipe[{dependency_id}].rsi_14",
    )
    assert {item.recipe_id for item in projected_by_tool.values()} == {
        item.recipe_id for item in plan.recipes
    }


@pytest.mark.parametrize(
    ("display_name", "description"),
    (("", ""), (" Collection", ""), ("Collection", " Description ")),
)
def test_invalid_collection_metadata_prevents_every_derivation_write(
    tmp_path: Path, display_name: str, description: str
) -> None:
    service, environments, recipes = _domain(tmp_path)
    environment = _save_environment(environments)

    with pytest.raises(DataManagerOperationError):
        service.persist_recipe_derivation(
            environment.environment_id,
            ("entry_003",),
            create_collection=True,
            collection_display_name=display_name,
            collection_description=description,
        )

    assert not recipes.root_dir.exists()


def test_portable_recipe_read_model_parameters_are_recursively_immutable() -> None:
    parameters = {"nested": {"values": [1, {"enabled": True}]}}
    entry = DataManagerPortableRecipeEntry(
        "a" * 64,
        "sma",
        "1.0",
        "indicator",
        parameters,
        ("sma_20",),
        ("source=OHLCV.close",),
        0,
        1,
        (),
        (),
        (),
        0,
    )

    parameters["nested"]["values"][0] = 99
    assert entry.parameters["nested"]["values"][0] == 1
    assert entry.input_bindings == ("source=OHLCV.close",)
    with pytest.raises(TypeError):
        entry.parameters["nested"]["new"] = "value"
    with pytest.raises(TypeError):
        entry.parameters["nested"]["values"][0] = 2


def test_same_semantics_across_markets_share_recipe_and_add_provenance(
    tmp_path: Path,
) -> None:
    service, environments, recipes = _domain(tmp_path)
    btc = _save_environment(environments, environment_id="env_btc")
    link = _save_environment(
        environments,
        environment_id="env_link",
        display_name="LINK Environment",
        market=MarketId("bybit", "linear", "LINKUSDT", "4h"),
    )
    first = service.persist_recipe_derivation(
        btc.environment_id, ("entry_001",), create_collection=False
    )
    second = service.persist_recipe_derivation(
        link.environment_id, ("entry_001",), create_collection=False
    )
    assert first.root_recipe_ids == second.root_recipe_ids
    assert len(recipes.list_provenance(first.root_recipe_ids[0])) == 2
    item = service.scan_portable_recipes(tool_key="ema").recipes[0]
    assert {market.symbol for market in item.origin_market_ids} == {"BTCUSDT", "LINKUSDT"}


def _peaks_and_utc_entries():
    source = fixture_environment()
    template = source.entries[0]
    peaks_parameters = dict(resolve_parameters("peaks_troughs", {}))
    peaks = replace(
        template,
        entry_id="entry_peaks",
        tool_key="peaks_troughs",
        display_name="Peaks & Troughs",
        parameters=peaks_parameters,
        sources=(),
        expected_output_names=resolve_output_names("peaks_troughs", peaks_parameters),
        presentation=replace(template.presentation, line_styles=(), fill_styles=()),
    )
    utc_parameters = dict(resolve_parameters("universal_trend_classifier", {}))
    utc_parameters.pop("peak_column")
    utc_parameters.pop("trough_column")
    naming = {**utc_parameters, "peak_column": "peak_fractal_5", "trough_column": "trough_fractal_5"}
    roles = ("trend_peak", "trend_trough", "range_peak", "range_trough")
    outputs = (
        "peak_fractal_5", "trough_fractal_5", "peak_fractal_3", "trough_fractal_3"
    )
    utc = replace(
        template,
        entry_id="entry_utc",
        tool_key="universal_trend_classifier",
        display_name="UTC",
        parameters=utc_parameters,
        sources=tuple(
            StudyEnvironmentSourceV1(
                role,
                "artifact",
                artifact_kind="indicator",
                artifact_tool_key="peaks_troughs",
                artifact_id="e" * 64,
                output_name=output,
            )
            for role, output in zip(roles, outputs, strict=True)
        ),
        expected_output_names=resolve_output_names("universal_trend_classifier", naming),
        presentation=replace(template.presentation, line_styles=(), fill_styles=()),
    )
    return peaks, utc


def test_artifact_source_reconstructs_unique_prior_recipe_and_rejects_ambiguity(
    tmp_path: Path,
) -> None:
    service, environments, _recipes = _domain(tmp_path)
    peaks, utc = _peaks_and_utc_entries()
    environment = _save_environment(
        environments, environment_id="env_utc", entries=(peaks, utc)
    )
    plan = service.plan_recipe_derivation(environment.environment_id, ("entry_utc",))
    assert not plan.blocked
    assert plan.support_entry_ids == ("entry_peaks",)
    utc_recipe = plan.recipes[-1]
    assert {item.role for item in utc_recipe.dependencies} == {
        "trend_peak", "trend_trough", "range_peak", "range_trough"
    }

    duplicate = replace(peaks, entry_id="entry_peaks_duplicate")
    ambiguous = _save_environment(
        environments,
        environment_id="env_ambiguous",
        display_name="Ambiguous",
        entries=(peaks, duplicate, utc),
    )
    blocked = service.plan_recipe_derivation(ambiguous.environment_id, ("entry_utc",))
    assert blocked.blocked
    assert next(
        item for item in blocked.entry_classifications if item.entry_id == "entry_utc"
    ).status == "MARKET_BOUND"
    with pytest.raises(DataManagerOperationError):
        service.persist_recipe_derivation(
            ambiguous.environment_id, ("entry_utc",), create_collection=False
        )


def _braid_instability_entries():
    source = fixture_environment()
    template = source.entries[0]
    empty_presentation = replace(template.presentation, line_styles=(), fill_styles=())
    averages = []
    for index, period in enumerate((10, 20, 30), start=1):
        parameters = dict(resolve_parameters("sma", {"period": period}))
        averages.append(
            replace(
                template,
                entry_id=f"entry_sma_{index}",
                tool_key="sma",
                display_name=f"SMA {period}",
                parameters=parameters,
                expected_output_names=resolve_output_names("sma", parameters),
                presentation=empty_presentation,
            )
        )
    deltas = []
    pairs = ((0, 1), (1, 2), (0, 2))
    for index, (fast_index, slow_index) in enumerate(pairs, start=1):
        fast = averages[fast_index]
        slow = averages[slow_index]
        parameters = {"eps": 1e-12, "mode": "abs"}
        sources = (
            StudyEnvironmentSourceV1(
                "fast", "environment", source_entry_id=fast.entry_id,
                output_name=fast.expected_output_names[0],
            ),
            StudyEnvironmentSourceV1(
                "slow", "environment", source_entry_id=slow.entry_id,
                output_name=slow.expected_output_names[0],
            ),
        )
        naming = {
            **parameters,
            "fast": "__research_fast",
            "slow": "__research_slow",
        }
        deltas.append(
            replace(
                template,
                entry_id=f"entry_delta_{index}",
                kind="construct",
                tool_key="delta",
                display_name=f"Delta {index}",
                parameters=parameters,
                sources=sources,
                expected_output_names=resolve_output_names("delta", naming),
                presentation=empty_presentation,
            )
        )
    roles = ("fast", "mid", "slow")
    instability_parameters = {"n": 5}
    instability_sources = tuple(
        StudyEnvironmentSourceV1(
            role,
            "environment",
            source_entry_id=entry.entry_id,
            output_name=entry.expected_output_names[0],
        )
        for role, entry in zip(roles, deltas, strict=True)
    )
    naming = {
        **instability_parameters,
        "fast": "__research_fast",
        "mid": "__research_mid",
        "slow": "__research_slow",
    }
    instability = replace(
        template,
        entry_id="entry_instability",
        kind="construct",
        tool_key="braid_instability",
        display_name="Braid Instability",
        parameters=instability_parameters,
        sources=instability_sources,
        expected_output_names=resolve_output_names("braid_instability", naming),
        presentation=empty_presentation,
    )
    return (*averages, *deltas, instability)


def test_braid_instability_derivation_resolves_transitive_shared_closure(
    tmp_path: Path,
) -> None:
    service, environments, _recipes = _domain(tmp_path)
    environment = _save_environment(
        environments,
        environment_id="env_braid_instability",
        display_name="Braid Instability",
        entries=_braid_instability_entries(),
    )
    plan = service.plan_recipe_derivation(
        environment.environment_id, ("entry_instability",)
    )
    assert not plan.blocked
    assert len(plan.recipes) == 7
    assert len({item.recipe_id for item in plan.recipes}) == 7
    assert len(plan.execution_stages) == 3
    assert plan.support_entry_ids == tuple(
        item.entry_id for item in environment.entries[:-1]
    )


def test_collection_operations_use_graph_members_and_keep_revisions(tmp_path: Path) -> None:
    service, environments, recipes = _domain(tmp_path)
    environment = _save_environment(environments)
    persisted = service.persist_recipe_derivation(
        environment.environment_id, ("entry_003",), create_collection=False
    )
    expected = PortableRecipeGraphPlanner(recipes).plan(persisted.root_recipe_ids)
    plan = service.plan_recipe_collection(persisted.root_recipe_ids)
    assert plan == expected
    assert plan.root_recipe_ids == persisted.root_recipe_ids
    assert plan.member_recipe_ids == tuple(
        recipe_id for stage in plan.execution_stages for recipe_id in stage
    )
    assert plan.dependency_edges == expected.dependency_edges
    assert plan.execution_stages == expected.execution_stages
    created = service.create_recipe_collection(
        "Structure", "", persisted.root_recipe_ids
    )
    assert created.collection.root_count == 1
    assert created.collection.member_count == 3
    first_revision = recipes.load_collection(created.collection.collection_id)
    assert first_revision.root_recipe_ids == plan.root_recipe_ids
    assert first_revision.member_recipe_ids == plan.member_recipe_ids
    first_path = (
        recipes.root_dir
        / "recipe_collections"
        / first_revision.collection_id
        / "revisions"
        / f"{first_revision.revision_id}.json"
    )
    first_bytes = first_path.read_bytes()
    next_roots = (persisted.support_recipe_ids[0],)
    next_plan = service.plan_recipe_collection(next_roots)
    updated = service.update_recipe_collection(
        created.collection.collection_id,
        "Structure Updated",
        "",
        next_roots,
        expected_revision_id=created.collection.revision_id,
    )
    assert updated.collection.revision_id != created.collection.revision_id
    second_revision = recipes.load_collection(created.collection.collection_id)
    assert second_revision.previous_revision_id == first_revision.revision_id
    assert second_revision.root_recipe_ids == next_plan.root_recipe_ids
    assert second_revision.member_recipe_ids == next_plan.member_recipe_ids
    revisions = recipes.list_collection_revisions(created.collection.collection_id)
    assert revisions == (first_revision, second_revision)
    assert first_path.read_bytes() == first_bytes
    revision_bytes = {
        revision.revision_id: (
            recipes.root_dir
            / "recipe_collections"
            / revision.collection_id
            / "revisions"
            / f"{revision.revision_id}.json"
        ).read_bytes()
        for revision in revisions
    }
    with pytest.raises(
        DataManagerOperationError, match="changed since it was selected"
    ):
        service.update_recipe_collection(
            created.collection.collection_id,
            "Stale",
            "",
            persisted.root_recipe_ids,
            expected_revision_id=created.collection.revision_id,
        )
    assert recipes.load_collection(created.collection.collection_id) == second_revision
    assert recipes.list_collection_revisions(created.collection.collection_id) == revisions
    for revision_id, expected_bytes in revision_bytes.items():
        path = (
            recipes.root_dir
            / "recipe_collections"
            / created.collection.collection_id
            / "revisions"
            / f"{revision_id}.json"
        )
        assert path.read_bytes() == expected_bytes

    restarted_recipes = PortableRecipeStore(recipes.root_dir)
    restarted = DataManagerService(
        _Catalog(),
        _Loader(),
        _Artifacts(),
        environments,
        restarted_recipes,
        PortableRecipeGraphPlanner(restarted_recipes),
    )
    assert restarted.inspect_recipe_collection(
        created.collection.collection_id
    ).collection.revision_id == second_revision.revision_id
    assert restarted.inspect_recipe_collection(
        created.collection.collection_id, first_revision.revision_id
    ).member_recipe_ids == first_revision.member_recipe_ids
    assert service.list_recipe_collections().collections[0].display_name == "Structure Updated"


def test_collection_plan_rejects_invalid_member_and_catalog_inspection_agree(
    tmp_path: Path,
) -> None:
    service, _environments, recipes = _domain(tmp_path)
    sma_parameters = dict(resolve_parameters("sma", {"period": 14}))
    sma = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters=sma_parameters,
        output_names=resolve_output_names("sma", sma_parameters),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    derivative_parameters = dict(resolve_parameters("derivative", {}))
    derivative = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters=derivative_parameters,
        output_names=resolve_output_names(
            "derivative", {**derivative_parameters, "source": sma.output_names[0]}
        ),
        dependencies=(
            PortableRecipeDependencyV1("fast", sma.recipe_id, sma.output_names[0]),
        ),
    )
    recipes.save_recipe(sma)
    recipes.save_recipe(derivative)

    with pytest.raises(DataManagerOperationError, match="roles"):
        service.plan_recipe_collection((derivative.recipe_id,))
    assert not (recipes.root_dir / "recipe_collections").exists()

    graph = PortableRecipeGraphPlanner(recipes).plan((derivative.recipe_id,))
    revision = recipes.create_collection(
        "Invalid", "", graph.root_recipe_ids, graph.member_recipe_ids
    )
    catalog_entry = service.list_recipe_collections().collections[0]
    assert catalog_entry.collection_id == revision.collection_id
    assert not catalog_entry.valid
    assert "roles" in catalog_entry.rejection_reason
    with pytest.raises(DataManagerOperationError, match="roles"):
        service.inspect_recipe_collection(revision.collection_id)


def test_collection_plan_rejects_recipe_braid_with_raw_ohlc_sources(
    tmp_path: Path,
) -> None:
    service, _environments, recipes = _domain(tmp_path)
    parameters = dict(resolve_parameters("braids", {"tie_policy": "carry"}))
    naming = {**parameters, "fast": "high", "mid": "close", "slow": "low"}
    braid = build_portable_recipe(
        tool_key="braids",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("braids", naming),
        ohlcv_inputs=(
            PortableRecipeOHLCVInputV1("fast", "high"),
            PortableRecipeOHLCVInputV1("mid", "close"),
            PortableRecipeOHLCVInputV1("slow", "low"),
        ),
    )
    recipes.save_recipe(braid)

    with pytest.raises(DataManagerOperationError, match="source-family"):
        service.plan_recipe_collection((braid.recipe_id,))
    assert not (recipes.root_dir / "recipe_collections").exists()
