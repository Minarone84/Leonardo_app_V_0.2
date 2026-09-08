from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.artifacts import (
    ArtifactService,
    ArtifactSourceRefV1,
)
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerApplicationService,
    ArtifactCollectionOutputV1,
    BatchArtifactBranchRequest,
    BatchArtifactRequest,
    DataManagerArtifactMaterializationRequest,
    DataManagerCreationError,
    DataManagerCreationStore,
    DataManagerService,
)
from leonardo.data_manager.creation_models import (
    ArtifactCollectionHeadV1,
    BatchArtifactSource,
    canonical_json_bytes,
    deterministic_hash,
)
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactSource
from leonardo.data_manager.construct_batch import visible_output_names
from leonardo.data_manager.construct_sources import list_construct_source_signals
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.financial_tools import (
    calculate_financial_tool,
    resolve_output_names,
    resolve_parameters,
)
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeStore,
    build_portable_recipe,
)
import leonardo.data_manager.service as data_manager_service_module
from leonardo.research import (
    AcceptedDatasetCatalog,
    HistoricalDatasetLoader,
    StudyEnvironmentStore,
)

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_artifact_materialization import _delta


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _domain(tmp_path: Path):
    historical = tmp_path / "historical"
    market, _frame = _accepted_dataset(historical, market=MARKET)
    catalog = AcceptedDatasetCatalog(historical)
    artifacts = ArtifactService(historical)
    recipes = PortableRecipeStore(tmp_path / "recipe_library")
    planner = PortableRecipeGraphPlanner(recipes)
    service = DataManagerService(
        catalog,
        HistoricalDatasetLoader(catalog),
        artifacts,
        StudyEnvironmentStore(tmp_path / "study_environments"),
        recipes,
        planner,
        DataManagerCreationStore(tmp_path / "data_manager"),
    )
    return market, service, artifacts, recipes


def _leaf(tool_key: str, parameters: dict[str, object]):
    resolved = dict(resolve_parameters(tool_key, parameters))
    return build_portable_recipe(
        tool_key=tool_key,
        kind="indicator",
        parameters=resolved,
        output_names=resolve_output_names(tool_key, resolved),
    )


def _materialize(service: DataManagerService, recipes: PortableRecipeStore, *roots):
    for recipe in roots:
        recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(MARKET, tuple(item.recipe_id for item in roots))
    )
    assert not plan.blocked
    return service.execute_artifact_materialization(plan)


def _derivative(owner):
    parameters = dict(resolve_parameters("derivative", {"order": 1}))
    naming = {**parameters, "source": "__research_source"}
    return build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("derivative", naming),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", owner.recipe_id, owner.output_names[0]
            ),
        ),
    )


def _advance_same_source(
    service: DataManagerService,
    artifacts: ArtifactService,
    logical_artifact_id: str,
):
    summary = next(
        item
        for item in artifacts.list_managed_artifacts(MARKET)
        if item.logical_artifact_id == logical_artifact_id
    )
    dataset = service._loader.load(MARKET)
    frame = pd.DataFrame(
        {
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        }
    )
    frame.loc[frame.index[-1], "close"] += 1.0
    replacement = artifacts.prepare_managed_calculation(
        MARKET,
        summary.portable_recipe_id,
        calculate_financial_tool(
            summary.tool_key,
            frame,
            artifacts.load_artifact_by_id(
                MARKET, summary.artifact_id
            ).metadata.recipe.parameters,
        ),
        expected_source=artifacts.capture_accepted_source(MARKET),
        previous_artifact_id=summary.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,),
        expected_source=artifacts.capture_accepted_source(MARKET),
    )
    return summary, replacement


def _persistence_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _collection_revision_like(
    service: DataManagerService,
    source,
    *,
    collection_id: str,
    display_name: str | None = None,
    description: str | None = None,
    created_at_utc: datetime | None = None,
    source_ohlcv=None,
):
    created = source.created_at_utc if created_at_utc is None else created_at_utc
    return service._creation._build_collection_revision(
        collection_id=collection_id,
        display_name=source.display_name if display_name is None else display_name,
        description=source.description if description is None else description,
        market_id=source.market_id,
        roots=source.root_logical_artifact_ids,
        supports=source.support_logical_artifact_ids,
        members=source.members,
        edges=source.dependency_edges,
        selected_outputs=source.selected_outputs,
        presentation_order=source.presentation_order,
        source_recipe_collection_id=source.source_recipe_collection_id,
        source_recipe_collection_revision_id=(
            source.source_recipe_collection_revision_id
        ),
        source_ohlcv=source.source_ohlcv if source_ohlcv is None else source_ohlcv,
        first_timestamp_ms=source.first_timestamp_ms,
        last_timestamp_ms=source.last_timestamp_ms,
        previous_revision_id=None,
        created_at_utc=created,
        revised_at_utc=created,
    )


def _persist_legacy_collection(
    store: DataManagerCreationStore, revision
) -> None:
    collection_dir = (
        store.root_dir / "artifact_collections" / revision.collection_id
    )
    revision_path = (
        collection_dir / "revisions" / f"{revision.revision_id}.json"
    )
    store._write_immutable(revision_path, revision.canonical_json_bytes())
    head = ArtifactCollectionHeadV1(
        revision.collection_id, revision.revision_id, revision.revised_at_utc
    )
    store._write_atomic(
        collection_dir / "head.json", canonical_json_bytes(head.to_dict())
    )


def _collection_with_validation_state(revision, state: str):
    payload = revision.to_dict(include_revision_id=False)
    payload["validation_state"] = state
    payload["revision_id"] = deterministic_hash(payload)
    return type(revision).from_dict(payload)


def test_collection_revisions_are_immutable_and_reload_after_restart(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    materialization = _materialize(service, recipes, sma)

    created = service.create_artifact_collection(materialization, "Core features")
    renamed = service.revise_artifact_collection(
        created.collection_id, display_name="Primary features", description="Accepted set"
    )

    assert renamed.revision_id != created.revision_id
    assert renamed.previous_revision_id == created.revision_id
    assert service.load_artifact_collection(created.collection_id).revision_id == renamed.revision_id
    assert service.load_artifact_collection(created.collection_id, created.revision_id) == created
    assert len(service.list_artifact_collection_revisions(created.collection_id)) == 2

    _market, restarted, _restarted_artifacts, _restarted_recipes = _domain(tmp_path)
    assert restarted.load_artifact_collection(created.collection_id) == renamed


def test_selection_collection_uses_exact_artifact_closure_without_recipe_or_artifact_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    for recipe in (sma, ema):
        recipes.save_recipe(recipe)
    delta = _delta(sma, ema)
    materialization = _materialize(service, recipes, delta)
    root = materialization.root_logical_artifact_ids[0]
    support_ids = {
        item.logical_artifact_id
        for item in materialization.managed_artifacts
        if item.logical_artifact_id != root
    }
    artifact_bytes = _persistence_bytes(tmp_path / "historical")
    recipe_bytes = _persistence_bytes(recipes.root_dir)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("selection workflow consulted a forbidden authority")

    monkeypatch.setattr(recipes, "load_recipe", forbidden)
    monkeypatch.setattr(recipes, "list_recipe_summaries", forbidden)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden)
    monkeypatch.setattr(
        data_manager_service_module, "list_construct_source_signals", forbidden
    )

    plan = service.plan_artifact_collection_selection(market, (root,))
    assert plan.root_logical_artifact_ids == (root,)
    assert set(plan.support_logical_artifact_ids) == support_ids
    assert {item.version_key.logical_artifact_id for item in plan.members} == {
        root,
        *support_ids,
    }
    assert {item.role for item in plan.dependency_edges} == {"fast", "slow"}
    stage_by_id = {
        logical_id: index
        for index, stage in enumerate(plan.execution_stages)
        for logical_id in stage
    }
    assert all(
        stage_by_id[item.dependency_logical_artifact_id]
        < stage_by_id[item.dependent_logical_artifact_id]
        for item in plan.dependency_edges
    )

    collection = service.create_artifact_collection_from_selection(
        plan, "Selected Delta"
    )
    assert collection.root_logical_artifact_ids == plan.root_logical_artifact_ids
    assert collection.support_logical_artifact_ids == plan.support_logical_artifact_ids
    assert collection.members == plan.members
    assert collection.dependency_edges == plan.dependency_edges
    assert collection.source_recipe_collection_id is None
    assert collection.source_recipe_collection_revision_id is None
    assert _persistence_bytes(tmp_path / "historical") == artifact_bytes
    assert _persistence_bytes(recipes.root_dir) == recipe_bytes

    seed = service.create_database_seed(market, "Selection database")
    assert service.assess_database_readiness(
        seed.seed_id, collection.collection_id
    ).ready


def test_selection_plan_retains_exact_historical_support_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    first = _materialize(service, recipes, derivative)
    root_a = first.root_logical_artifact_ids[0]
    support = next(
        item
        for item in first.managed_artifacts
        if item.logical_artifact_id != root_a
    )
    support_v1 = support.artifact_id
    _old, replacement = _advance_same_source(
        service, artifacts, support.logical_artifact_id
    )

    historical_plan = service.plan_artifact_collection_selection(
        market, (root_a,)
    )
    selected_support = next(
        item
        for item in historical_plan.members
        if item.version_key.logical_artifact_id == support.logical_artifact_id
    )
    assert selected_support.version_key.artifact_id == support_v1
    assert selected_support.version_key.artifact_id != replacement.metadata.artifact_id

    source_loaded = artifacts.load_artifact_by_id(
        market, replacement.metadata.artifact_id
    )
    dataset = service._loader.load(market)
    frame = pd.DataFrame(
        {
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        }
    )
    output = source_loaded.metadata.recipe.output_names[0]
    frame[output] = source_loaded.frame[output].to_numpy(copy=True)
    angle_result = calculate_financial_tool(
        "angle", frame, {}, bindings={"source": output}
    )
    angle = artifacts.prepare_managed_calculation(
        market,
        "f" * 64,
        angle_result,
        expected_source=artifacts.capture_accepted_source(market),
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", replacement.metadata.artifact_id, output
            ),
        ),
        source_metadata=(source_loaded.metadata,),
    )
    root_b = artifacts.publish_managed_artifact_graph(
        (angle,), expected_source=artifacts.capture_accepted_source(market)
    ).managed_artifacts[0]

    with pytest.raises(
        DataManagerCreationError, match="conflicting physical versions"
    ):
        service.plan_artifact_collection_selection(
            market, (root_a, root_b.logical_artifact_id)
        )


def test_selection_create_and_edit_reject_stale_plan_and_revision(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    materialization = _materialize(service, recipes, sma)
    root = materialization.root_logical_artifact_ids[0]
    stale_plan = service.plan_artifact_collection_selection(market, (root,))
    _advance_same_source(service, artifacts, root)
    with pytest.raises(
        DataManagerCreationError,
        match="Artifact Collection selection changed since Preview",
    ):
        service.create_artifact_collection_from_selection(stale_plan, "Stale")

    current_plan = service.plan_artifact_collection_selection(market, (root,))
    created = service.create_artifact_collection_from_selection(
        current_plan, "Current"
    )
    revised = service.edit_artifact_collection_from_selection(
        created.collection_id,
        current_plan,
        description="Revision one",
        expected_revision_id=created.revision_id,
    )
    assert revised.previous_revision_id == created.revision_id
    assert service.load_artifact_collection(
        created.collection_id, created.revision_id
    ) == created
    with pytest.raises(DataManagerCreationError, match="revision changed"):
        service.edit_artifact_collection_from_selection(
            created.collection_id,
            current_plan,
            description="Stale revision",
            expected_revision_id=created.revision_id,
        )
    assert service.list_artifact_collection_revisions(created.collection_id) == (
        created,
        revised,
    )


def test_selection_edit_preserves_outputs_and_appends_new_root_outputs(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    result = _materialize(service, recipes, sma, ema)
    by_tool = {item.tool_key: item for item in result.managed_artifacts}
    first_plan = service.plan_artifact_collection_selection(
        market, (by_tool["sma"].logical_artifact_id,)
    )
    created = service.create_artifact_collection_from_selection(
        first_plan, "Average selection"
    )
    second_plan = service.plan_artifact_collection_selection(
        market,
        (
            by_tool["sma"].logical_artifact_id,
            by_tool["ema"].logical_artifact_id,
        ),
    )

    revised = service.edit_artifact_collection_from_selection(
        created.collection_id,
        second_plan,
        expected_revision_id=created.revision_id,
    )

    assert revised.selected_outputs[0] == created.selected_outputs[0]
    assert revised.selected_outputs[1].logical_artifact_id == (
        by_tool["ema"].logical_artifact_id
    )
    assert revised.presentation_order == tuple(
        item.column_name for item in revised.selected_outputs
    )
    assert service.load_artifact_collection(
        created.collection_id, created.revision_id
    ) == created


def test_selection_edit_preserves_custom_columns_and_removes_obsolete_outputs(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    bb = _leaf("bb", {"period": 3, "std": 2.0})
    result = _materialize(service, recipes, sma, ema, bb)
    by_tool = {item.tool_key: item for item in result.managed_artifacts}
    initial_plan = service.plan_artifact_collection_selection(
        market,
        (
            by_tool["sma"].logical_artifact_id,
            by_tool["ema"].logical_artifact_id,
        ),
    )
    explicit = (
        ArtifactCollectionOutputV1(
            by_tool["sma"].logical_artifact_id,
            by_tool["sma"].output_names[0],
            "first_average",
        ),
        ArtifactCollectionOutputV1(
            by_tool["ema"].logical_artifact_id,
            by_tool["ema"].output_names[0],
            "retained_average",
        ),
    )
    created = service.create_artifact_collection_from_selection(
        initial_plan, "Custom outputs", selected_outputs=explicit
    )
    artifact_bytes = _persistence_bytes(tmp_path / "historical")
    original_revision_path = (
        service.creation_store.root_dir
        / "artifact_collections"
        / created.collection_id
        / "revisions"
        / f"{created.revision_id}.json"
    )
    original_revision_bytes = original_revision_path.read_bytes()
    next_plan = service.plan_artifact_collection_selection(
        market,
        (
            by_tool["ema"].logical_artifact_id,
            by_tool["bb"].logical_artifact_id,
        ),
    )

    revised = service.edit_artifact_collection_from_selection(
        created.collection_id,
        next_plan,
        expected_revision_id=created.revision_id,
    )

    assert revised.selected_outputs[0] == explicit[1]
    assert revised.presentation_order[0] == "retained_average"
    assert "first_average" not in revised.presentation_order
    assert tuple(
        item.output_name
        for item in revised.selected_outputs[1:]
    ) == by_tool["bb"].output_names
    assert original_revision_path.read_bytes() == original_revision_bytes
    assert _persistence_bytes(tmp_path / "historical") == artifact_bytes


def test_selection_default_output_collision_requires_explicit_mapping(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    first = _leaf("bb", {"period": 3, "std": 2.0})
    second = _leaf("bb", {"period": 5, "std": 2.0})
    result = _materialize(service, recipes, first, second)
    plan = service.plan_artifact_collection_selection(
        market, result.root_logical_artifact_ids
    )
    with pytest.raises(DataManagerCreationError, match="explicit mapping"):
        service.create_artifact_collection_from_selection(plan, "Collision")
    explicit = tuple(
        ArtifactCollectionOutputV1(
            member.version_key.logical_artifact_id,
            output_name,
            f"root_{index}_{output_name}",
        )
        for index, member in enumerate(plan.members, start=1)
        if member.version_key.logical_artifact_id
        in plan.root_logical_artifact_ids
        for output_name in member.output_names
    )
    created = service.create_artifact_collection_from_selection(
        plan, "Mapped", selected_outputs=explicit
    )
    assert created.selected_outputs == explicit


def test_selection_rejects_artifact_from_stale_accepted_source(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    root = _materialize(service, recipes, sma).root_logical_artifact_ids[0]
    before = _persistence_bytes(tmp_path / "historical")
    _accepted_dataset(tmp_path / "historical", market=market, rows=97)
    changed = _persistence_bytes(tmp_path / "historical")
    assert changed != before

    with pytest.raises(
        DataManagerCreationError,
        match="metadata disagrees|OHLCV|source",
    ):
        service.plan_artifact_collection_selection(market, (root,))
    assert _persistence_bytes(tmp_path / "historical") == changed


def test_selection_rejects_semantically_stable_malformed_dependency_role(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    support = _materialize(service, recipes, sma).managed_artifacts[0]
    support_loaded = artifacts.load_artifact_by_id(market, support.artifact_id)
    dataset = service._loader.load(market)
    frame = pd.DataFrame(
        {
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        }
    )
    malformed = artifacts.prepare_managed_calculation(
        market,
        "e" * 64,
        calculate_financial_tool(
            "derivative",
            frame,
            {"order": 1},
            bindings={"source": "close"},
        ),
        expected_source=artifacts.capture_accepted_source(market),
        source_artifacts=(
            ArtifactSourceRefV1(
                "fast", support.artifact_id, support.output_names[0]
            ),
        ),
        source_metadata=(support_loaded.metadata,),
    )
    root = artifacts.publish_managed_artifact_graph(
        (malformed,), expected_source=artifacts.capture_accepted_source(market)
    ).managed_artifacts[0]

    with pytest.raises(
        DataManagerCreationError, match="derivative source roles are invalid"
    ):
        service.plan_artifact_collection_selection(
            market, (root.logical_artifact_id,)
        )


def test_collection_preserves_support_members_and_allows_optional_root_removal(
    tmp_path: Path,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    for recipe in (sma, ema):
        recipes.save_recipe(recipe)
    delta = _delta(sma, ema)
    recipes.save_recipe(delta)
    result = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(MARKET, (sma.recipe_id, delta.recipe_id))
        )
    )
    collection = service.create_artifact_collection(result, "Features")

    assert len(collection.root_logical_artifact_ids) == 2
    assert len(collection.support_logical_artifact_ids) == 1
    revised = service.revise_artifact_collection(
        collection.collection_id,
        remove_root_logical_artifact_ids=(collection.root_logical_artifact_ids[0],),
    )
    required_by_delta = {edge.dependency_logical_artifact_id for edge in revised.dependency_edges}
    assert required_by_delta.issubset(set(revised.support_logical_artifact_ids))


def test_explicit_collection_branch_outputs_replace_existing_selection(
    tmp_path: Path,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    base = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(base, "Base")
    branch = _materialize(service, recipes, ema)
    entry = branch.managed_artifacts[0]
    replacement = ArtifactCollectionOutputV1(
        entry.logical_artifact_id,
        entry.output_names[0],
        "replacement_output",
    )

    revised = service.add_artifact_collection_branches(
        collection.collection_id,
        branch,
        selected_outputs=(replacement,),
    )

    assert revised.selected_outputs == (replacement,)
    assert revised.presentation_order == ("replacement_output",)


def test_batch_branch_reuses_artifact_and_can_advance_collection(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    base = _materialize(service, recipes, sma, ema)
    collection = service.create_artifact_collection(base, "Base")
    source = next(item for item in base.managed_artifacts if item.tool_key == "sma")
    output = source.output_names[0]
    requested = resolve_output_names("derivative", {"order": 1, "source": output})
    request = BatchArtifactRequest(
        market_id=market,
        expected_source_ohlcv=base.source_ohlcv,
        branches=(
            BatchArtifactBranchRequest(
                tool_key="derivative",
                parameters={"order": 1},
                sources=(DataManagerDirectArtifactSource(
                    "source", source.logical_artifact_id, source.artifact_id, output
                ),),
                requested_outputs=requested,
            ),
        ),
        destination="collection_revision",
        collection_id=collection.collection_id,
    )
    transient_recipe = service._creation._build_batch_portable_recipe(
        request,
        request.branches[0],
        {"source": source.portable_recipe_id},
    )
    recipes.save_recipe(transient_recipe)
    recipe_bytes = _persistence_bytes(recipes.root_dir)
    metadata_before = recipes.load_persistence_metadata(transient_recipe.recipe_id)
    assert metadata_before is not None

    plan = service.plan_batch_artifacts(request)
    assert not plan.blocked
    assert len(plan.new_recipe_ids) == 1
    result, revised = service.execute_batch_artifacts(plan)
    assert result.root_logical_artifact_ids
    assert revised is not None
    assert revised.previous_revision_id == collection.revision_id
    assert revised.selected_outputs[: len(collection.selected_outputs)] == (
        collection.selected_outputs
    )
    assert len(revised.selected_outputs) == len(collection.selected_outputs) + 1
    assert revised.selected_outputs[-1].column_name == requested[0]
    persisted_after = _persistence_bytes(recipes.root_dir)
    metadata_path = (
        f"recipe_provenance/{transient_recipe.recipe_id}/metadata.json"
    )
    assert {
        path: content
        for path, content in persisted_after.items()
        if path != metadata_path
    } == {
        path: content
        for path, content in recipe_bytes.items()
        if path != metadata_path
    }
    metadata_after = recipes.load_persistence_metadata(transient_recipe.recipe_id)
    assert metadata_after is not None
    assert (
        metadata_after.first_persisted_at_utc
        == metadata_before.first_persisted_at_utc
    )
    assert {item.origin_kind for item in metadata_after.origins} == {
        "data_manager_artifact"
    }
    replay = service.plan_batch_artifacts(request)
    assert replay.reusable_recipe_ids == plan.recipe_ids
    assert _persistence_bytes(recipes.root_dir) == persisted_after


def test_raw_ohlc_batch_materializes_with_native_bindings_and_no_fake_lineage(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    source = artifacts.capture_accepted_source(market)
    close = BatchArtifactSource.current_ohlcv(
        "source", market, source, "close"
    )
    branch = BatchArtifactBranchRequest(
        "derivative",
        {"order": 1},
        (close,),
        visible_output_names("derivative", {"order": 1}, (close,)),
    )
    request = BatchArtifactRequest(
        market, source, (branch,), "individual"
    )

    plan = service.plan_batch_artifacts(request)
    result, collection = service.execute_batch_artifacts(plan)
    root = next(
        item
        for item in result.managed_artifacts
        if item.logical_artifact_id in result.root_logical_artifact_ids
    )
    recipe = artifacts.load_artifact_by_id(
        market, root.artifact_id
    ).metadata.recipe

    assert collection is None
    assert result.root_logical_artifact_ids
    assert dict(recipe.bindings) == {"source": "close"}
    assert recipe.source_artifacts == ()
    persisted = recipes.load_recipe(plan.branch_recipe_ids[0])
    assert dict(persisted.parameters) == {"order": 1}
    assert tuple(
        (item.role, item.column_name) for item in persisted.ohlcv_inputs
    ) == (("source", "close"),)
    replay = service.plan_batch_artifacts(request)
    assert replay.branch_recipe_ids == plan.branch_recipe_ids
    assert replay.branch_reuse_current == (True,)


def test_mixed_raw_and_artifact_batch_preserves_exact_artifact_lineage(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma_recipe = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma_recipe)
    sma = base.managed_artifacts[0]
    close = BatchArtifactSource.current_ohlcv(
        "fast", market, base.source_ohlcv, "close"
    )
    saved = DataManagerDirectArtifactSource(
        "slow",
        sma.logical_artifact_id,
        sma.artifact_id,
        sma.output_names[0],
    )
    branch = BatchArtifactBranchRequest(
        "delta",
        {},
        (close, saved),
        visible_output_names("delta", {}, (close, saved)),
    )
    request = BatchArtifactRequest(
        market, base.source_ohlcv, (branch,), "individual"
    )

    plan = service.plan_batch_artifacts(request)
    result, _collection = service.execute_batch_artifacts(plan)
    root = next(
        item
        for item in result.managed_artifacts
        if item.logical_artifact_id in result.root_logical_artifact_ids
    )
    recipe = artifacts.load_artifact_by_id(
        market, root.artifact_id
    ).metadata.recipe

    assert tuple(
        (item.role, item.artifact_id, item.output_name)
        for item in recipe.source_artifacts
    ) == (("slow", sma.artifact_id, sma.output_names[0]),)
    assert recipe.parameters["fast"] == "close"
    assert recipe.parameters["slow"] == "__research_slow"
    persisted = recipes.load_recipe(plan.branch_recipe_ids[0])
    assert dict(persisted.parameters) == {"eps": 1e-12, "mode": "abs"}
    assert tuple(
        (item.role, item.column_name) for item in persisted.ohlcv_inputs
    ) == (("fast", "close"),)
    assert tuple(
        (item.role, item.recipe_id, item.output_name)
        for item in persisted.dependencies
    ) == (("slow", sma_recipe.recipe_id, sma.output_names[0]),)


def test_raw_ohlc_batch_rejects_changed_fingerprint_before_artifact_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    source = artifacts.capture_accepted_source(market)
    close = BatchArtifactSource.current_ohlcv(
        "source", market, source, "close"
    )
    branch = BatchArtifactBranchRequest(
        "angle", {}, (close,), visible_output_names("angle", {}, (close,))
    )
    request = BatchArtifactRequest(
        market, source, (branch,), "individual"
    )
    plan = service.plan_batch_artifacts(request)
    changed = replace(source, csv_sha256="f" * 64)
    monkeypatch.setattr(
        artifacts, "capture_accepted_source", lambda _market: changed
    )
    saves = []
    monkeypatch.setattr(recipes, "save_recipe", lambda recipe: saves.append(recipe))

    with pytest.raises(DataManagerCreationError, match="OHLCV source changed"):
        service.execute_batch_artifacts(plan)
    assert saves == []


def test_batch_plan_rejects_incompatible_collection_before_publication(
    tmp_path: Path, monkeypatch,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(base, "Base")
    source = base.managed_artifacts[0]
    exact = DataManagerDirectArtifactSource(
        "source",
        source.logical_artifact_id,
        source.artifact_id,
        source.output_names[0],
    )
    request = BatchArtifactRequest(
        market,
        base.source_ohlcv,
        (
            BatchArtifactBranchRequest(
                "derivative",
                {"order": 1},
                (exact,),
                visible_output_names("derivative", {"order": 1}, (exact,)),
            ),
        ),
        "collection_revision",
        collection.collection_id,
    )
    incompatible = SimpleNamespace(
        market_id=market,
        source_ohlcv=replace(base.source_ohlcv, csv_sha256="f" * 64),
    )
    monkeypatch.setattr(
        service._creation,
        "load_artifact_collection",
        lambda _collection_id: incompatible,
    )
    publications = []
    monkeypatch.setattr(
        service._creation,
        "_execute_batch_materialization",
        lambda *_args, **_kwargs: publications.append(True),
    )

    with pytest.raises(DataManagerCreationError, match="incompatible"):
        service.plan_batch_artifacts(request)

    assert publications == []


@pytest.mark.parametrize(
    "tool_key",
    (
        "derivative",
        "angle",
        "angle_momentum",
        "delta",
        "trap_area",
        "percent_span_angle",
        "braids",
        "braid_instability",
    ),
)
def test_all_authorized_batch_constructs_plan_and_materialize(
    tmp_path: Path, tool_key: str,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    bb = _leaf("bb", {"period": 3, "std": 2.0})
    base = _materialize(service, recipes, bb)
    source = base.managed_artifacts[0]
    first, second, third = source.output_names
    parameters = dict(resolve_parameters(tool_key))
    naming = dict(parameters)
    if tool_key in {"derivative", "angle"}:
        naming["source"] = first
    elif tool_key in {"angle_momentum", "percent_span_angle"}:
        naming["source_columns"] = first
    elif tool_key == "delta":
        parameters["slow_output"] = second
        naming.update({"fast": first, "slow": second})
    else:
        parameters.update({"mid_output": second, "slow_output": third})
        naming.update({"fast": first, "mid": second, "slow": third})
    request = BatchArtifactRequest(
        market_id=market,
        expected_source_ohlcv=base.source_ohlcv,
        branches=(BatchArtifactBranchRequest(
            tool_key=tool_key,
            parameters={
                key: value for key, value in parameters.items()
                if not key.endswith("_output")
            },
            sources=tuple(
                DataManagerDirectArtifactSource(
                    role, source.logical_artifact_id, source.artifact_id, output
                )
                for role, output in (
                    (("source", first),)
                    if tool_key in {"derivative", "angle"}
                    else (("source_1", first),)
                    if tool_key in {"angle_momentum", "percent_span_angle"}
                    else (("fast", first), ("slow", second))
                    if tool_key == "delta"
                    else (("fast", first), ("mid", second), ("slow", third))
                )
            ),
            requested_outputs=resolve_output_names(tool_key, naming),
        ),),
        destination="new_collection",
    )
    recipe_ids_before = {
        item.recipe_id for item in recipes.list_recipe_summaries()
    }

    plan = service.plan_batch_artifacts(request)
    assert not plan.blocked
    result, collection = service.execute_batch_artifacts(plan)
    assert result.root_logical_artifact_ids
    assert collection is not None
    assert collection.root_logical_artifact_ids == result.root_logical_artifact_ids
    assert {
        item.recipe_id for item in recipes.list_recipe_summaries()
    } == recipe_ids_before | {plan.branch_recipe_ids[0]}
    if tool_key in {"braids", "braid_instability"}:
        root = next(
            item
            for item in result.managed_artifacts
            if item.logical_artifact_id in result.root_logical_artifact_ids
        )
        root_recipe = artifacts.load_artifact_by_id(
            market, root.artifact_id
        ).metadata.recipe
        assert tuple(
            (item.role, item.artifact_id, item.output_name)
            for item in root_recipe.source_artifacts
        ) == (
            ("fast", source.artifact_id, first),
            ("mid", source.artifact_id, second),
            ("slow", source.artifact_id, third),
        )


def test_batch_plan_publishes_global_recipes_and_individual_outputs_do_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    base = _materialize(service, recipes, sma, ema)
    sources = tuple(
        DataManagerDirectArtifactSource(
            "source", item.logical_artifact_id, item.artifact_id,
            item.output_names[0],
        )
        for item in base.managed_artifacts
        if item.logical_artifact_id in base.root_logical_artifact_ids
    )
    branches = tuple(
        BatchArtifactBranchRequest(
            "derivative",
            {"order": 1},
            (source,),
            visible_output_names("derivative", {"order": 1}, (source,)),
        )
        for source in sources
    )
    request = BatchArtifactRequest(
        market, base.source_ohlcv, branches, "individual"
    )
    recipe_ids_before = {
        item.recipe_id for item in recipes.list_recipe_summaries()
    }
    publications = []
    publish = artifacts.publish_managed_artifact_graph
    monkeypatch.setattr(
        artifacts,
        "publish_managed_artifact_graph",
        lambda candidates, **options: (
            publications.append(tuple(candidates)),
            publish(candidates, **options),
        )[1],
    )
    plan = service.plan_batch_artifacts(request)
    assert plan.naming_collisions == ()
    assert plan.branch_reuse_current == (False, False)
    result, collection = service.execute_batch_artifacts(plan)
    assert collection is None
    assert len(result.root_logical_artifact_ids) == 2
    assert len(publications) == 1
    assert len(publications[0]) == 2
    recipe_ids_after = {
        item.recipe_id for item in recipes.list_recipe_summaries()
    }
    assert recipe_ids_after == recipe_ids_before | set(plan.branch_recipe_ids)
    versions_before_replay = {
        logical_id: artifacts.list_artifact_versions(market, logical_id)
        for logical_id in result.root_logical_artifact_ids
    }

    replay = service.plan_batch_artifacts(request)
    assert replay.branch_recipe_ids == plan.branch_recipe_ids
    assert replay.branch_reuse_current == (True, True)
    assert set(replay.reusable_logical_artifact_ids) == set(
        result.root_logical_artifact_ids
    )
    replay_result, replay_collection = service.execute_batch_artifacts(replay)
    assert replay_collection is None
    assert replay_result.root_logical_artifact_ids == (
        result.root_logical_artifact_ids
    )
    assert {
        logical_id: artifacts.list_artifact_versions(market, logical_id)
        for logical_id in result.root_logical_artifact_ids
    } == versions_before_replay
    assert len(publications) == 1
    assert {
        item.recipe_id for item in recipes.list_recipe_summaries()
    } == recipe_ids_after


@pytest.mark.parametrize("tool_key", ("braids", "braid_instability"))
def test_batch_preserves_mixed_raw_ohlc_and_saved_artifact_sources(
    tmp_path: Path,
    tool_key: str,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    support = base.managed_artifacts[0]
    expected_source = artifacts.capture_accepted_source(market)
    fast = BatchArtifactSource.current_ohlcv(
        "fast", market, expected_source, "high"
    )
    mid = DataManagerDirectArtifactSource(
        "mid",
        support.logical_artifact_id,
        support.artifact_id,
        support.output_names[0],
    )
    slow = BatchArtifactSource.current_ohlcv(
        "slow", market, expected_source, "low"
    )
    parameters = {"tie_policy": "carry"} if tool_key == "braids" else {"n": 3}
    sources = (fast, BatchArtifactSource.from_artifact(mid), slow)
    branch = BatchArtifactBranchRequest(
        tool_key,
        parameters,
        sources,
        visible_output_names(tool_key, parameters, sources),
    )
    request = BatchArtifactRequest(
        market, expected_source, (branch,), "individual"
    )
    recipe_ids_before = {
        item.recipe_id for item in recipes.list_recipe_summaries()
    }

    plan = service.plan_batch_artifacts(request)
    assert not plan.blocked
    result, collection = service.execute_batch_artifacts(plan)

    assert collection is None
    root = next(
        item
        for item in result.managed_artifacts
        if item.logical_artifact_id in result.root_logical_artifact_ids
    )
    loaded = artifacts.load_artifact_by_id(market, root.artifact_id)
    assert dict(loaded.metadata.recipe.parameters)["fast"] == "high"
    assert dict(loaded.metadata.recipe.parameters)["slow"] == "low"
    assert loaded.metadata.recipe.source_artifacts == (
        ArtifactSourceRefV1(
            "mid", support.artifact_id, support.output_names[0]
        ),
    )
    selection = service.plan_artifact_collection_selection(
        market, (root.logical_artifact_id,)
    )
    assert selection.support_logical_artifact_ids == (
        support.logical_artifact_id,
    )
    assert tuple(
        (
            item.dependency_logical_artifact_id,
            item.dependent_logical_artifact_id,
            item.role,
            item.output_name,
        )
        for item in selection.dependency_edges
    ) == (
        (
            support.logical_artifact_id,
            root.logical_artifact_id,
            "mid",
            support.output_names[0],
        ),
    )
    assert {
        item.recipe_id for item in recipes.list_recipe_summaries()
    } == recipe_ids_before | {plan.branch_recipe_ids[0]}


def test_batch_multi_root_deduplicates_shared_support_and_publishes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    bb = _leaf("bb", {"period": 3, "std": 2.0})
    base = _materialize(service, recipes, bb)
    support = base.managed_artifacts[0]
    source = DataManagerDirectArtifactSource(
        "source",
        support.logical_artifact_id,
        support.artifact_id,
        support.output_names[0],
    )
    branches = tuple(
        BatchArtifactBranchRequest(
            tool_key,
            {"order": 1} if tool_key == "derivative" else {},
            (source,),
            visible_output_names(
                tool_key,
                {"order": 1} if tool_key == "derivative" else {},
                (source,),
            ),
        )
        for tool_key in ("derivative", "angle")
    )
    request = BatchArtifactRequest(
        market, base.source_ohlcv, branches, "individual"
    )
    publications = []
    publish = artifacts.publish_managed_artifact_graph
    monkeypatch.setattr(
        artifacts,
        "publish_managed_artifact_graph",
        lambda candidates, **options: (
            publications.append(tuple(candidates)),
            publish(candidates, **options),
        )[1],
    )

    plan = service.plan_batch_artifacts(request)
    result, collection = service.execute_batch_artifacts(plan)

    assert collection is None
    assert len(plan.recipe_ids) == 2
    assert len(plan.execution_stages) == 3
    assert len(result.root_logical_artifact_ids) == 2
    assert result.support_logical_artifact_ids == (
        support.logical_artifact_id,
    )
    assert len(publications) == 1
    assert len(publications[0]) == 2


def test_batch_rejects_shared_support_semantic_lineage_drift(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    bb = _leaf("bb", {"period": 3, "std": 2.0})
    base = _materialize(service, recipes, bb)
    support = base.managed_artifacts[0]
    dataset = service._loader.load(market)
    frame = pd.DataFrame({
        "ts_ms": dataset.ts_ms,
        "open": dataset.open,
        "high": dataset.high,
        "low": dataset.low,
        "close": dataset.close,
        "volume": dataset.volume,
    })
    replacement = artifacts.prepare_managed_calculation(
        market,
        support.portable_recipe_id,
        calculate_financial_tool("bb", frame, {"period": 4, "std": 2.0}),
        expected_source=base.source_ohlcv,
        previous_artifact_id=support.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,), expected_source=base.source_ohlcv
    )
    current = next(
        item
        for item in artifacts.list_managed_artifacts(market)
        if item.logical_artifact_id == support.logical_artifact_id
    )
    source = DataManagerDirectArtifactSource(
        "source",
        current.logical_artifact_id,
        current.artifact_id,
        current.output_names[0],
    )
    request = BatchArtifactRequest(
        market,
        base.source_ohlcv,
        (
            BatchArtifactBranchRequest(
                "angle",
                {},
                (source,),
                visible_output_names("angle", {}, (source,)),
            ),
        ),
        "individual",
    )

    with pytest.raises(
        DataManagerCreationError,
        match="managed Artifact lineage changes semantic calculation identity",
    ):
        service.plan_batch_artifacts(request)


def test_batch_rejects_existing_root_semantic_signature_mismatch(
    tmp_path: Path,
) -> None:
    market, service, artifacts, _recipes = _domain(tmp_path)
    source = artifacts.capture_accepted_source(market)
    close = BatchArtifactSource.current_ohlcv(
        "source", market, source, "close"
    )
    branch = BatchArtifactBranchRequest(
        "derivative",
        {"order": 1},
        (close,),
        visible_output_names("derivative", {"order": 1}, (close,)),
    )
    request = BatchArtifactRequest(
        market, source, (branch,), "individual"
    )
    transient = service._creation._build_batch_portable_recipe(
        request, branch, {}
    )
    dataset = service._loader.load(market)
    frame = pd.DataFrame({
        "ts_ms": dataset.ts_ms,
        "open": dataset.open,
        "high": dataset.high,
        "low": dataset.low,
        "close": dataset.close,
        "volume": dataset.volume,
    })
    wrong = artifacts.prepare_managed_calculation(
        market,
        transient.recipe_id,
        calculate_financial_tool(
            "derivative",
            frame,
            {"order": 2},
            bindings={"source": "close"},
        ),
        expected_source=source,
    )
    artifacts.publish_managed_artifact_graph(
        (wrong,), expected_source=source
    )

    with pytest.raises(
        DataManagerCreationError,
        match=(
            "managed Artifact semantic identity disagrees with requested "
            "calculation"
        ),
    ):
        service.plan_batch_artifacts(request)


def test_batch_plan_and_execution_reject_stale_frozen_truth_before_artifact_publication(
    tmp_path: Path, monkeypatch,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    source = base.managed_artifacts[0]
    exact = DataManagerDirectArtifactSource(
        "source", source.logical_artifact_id, source.artifact_id,
        source.output_names[0],
    )
    branch = BatchArtifactBranchRequest(
        "derivative",
        {"order": 1},
        (exact,),
        visible_output_names("derivative", {"order": 1}, (exact,)),
    )
    request = BatchArtifactRequest(
        market, base.source_ohlcv, (branch,), "individual"
    )
    plan = service.plan_batch_artifacts(request)

    changed_source = replace(base.source_ohlcv, csv_sha256="f" * 64)
    monkeypatch.setattr(artifacts, "capture_accepted_source", lambda _market: changed_source)
    with pytest.raises(DataManagerCreationError, match="OHLCV source changed"):
        service.plan_batch_artifacts(request)
    with pytest.raises(DataManagerCreationError, match="OHLCV source changed"):
        service.execute_batch_artifacts(plan)

    monkeypatch.setattr(
        artifacts, "capture_accepted_source", lambda _market: base.source_ohlcv
    )
    frozen_signals = list_construct_source_signals(artifacts, market)
    monkeypatch.setattr(
        "leonardo.data_manager.creation_service.list_construct_source_signals",
        lambda _artifacts, _market: frozen_signals,
    )
    original_summaries = artifacts.list_managed_artifacts(market)
    monkeypatch.setattr(
        artifacts,
        "list_managed_artifacts",
        lambda _market: tuple(
            replace(item, artifact_id="e" * 64)
            if item.logical_artifact_id == source.logical_artifact_id
            else item
            for item in original_summaries
        ),
    )
    saves = []
    monkeypatch.setattr(recipes, "save_recipe", lambda recipe: saves.append(recipe))
    with pytest.raises(DataManagerCreationError, match="head changed"):
        service.execute_batch_artifacts(plan)
    assert saves == []


def test_batch_execution_rejects_disappeared_output_and_never_recurses_into_new_results(
    tmp_path: Path, monkeypatch,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    source = base.managed_artifacts[0]
    exact = DataManagerDirectArtifactSource(
        "source", source.logical_artifact_id, source.artifact_id,
        source.output_names[0],
    )
    branch = BatchArtifactBranchRequest(
        "angle", {}, (exact,), visible_output_names("angle", {}, (exact,))
    )
    request = BatchArtifactRequest(
        market, base.source_ohlcv, (branch,), "individual"
    )
    plan = service.plan_batch_artifacts(request)
    original = list_construct_source_signals(artifacts, market)

    monkeypatch.setattr(
        "leonardo.data_manager.creation_service.list_construct_source_signals",
        lambda _artifacts, _market: tuple(
            item for item in original if item.output_name != exact.output_name
        ),
    )
    saves = []
    monkeypatch.setattr(recipes, "save_recipe", lambda recipe: saves.append(recipe))
    with pytest.raises(DataManagerCreationError, match="no longer admitted"):
        service.execute_batch_artifacts(plan)
    assert saves == []

    monkeypatch.undo()
    calls = []
    original_owner = list_construct_source_signals
    monkeypatch.setattr(
        "leonardo.data_manager.creation_service.list_construct_source_signals",
        lambda _artifacts, _market: calls.append(True)
        or original_owner(_artifacts, _market),
    )
    service.execute_batch_artifacts(plan)
    assert calls == [True]


def test_database_seed_readiness_build_and_exact_reload(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    materialization = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(materialization, "Feature set")
    seed = service.create_database_seed(
        market, "BTC research", selected_ohlcv_columns=("open", "close", "volume")
    )

    valid, blockers = service.validate_database_seed(seed.seed_id)
    readiness = service.assess_database_readiness(seed.seed_id, collection.collection_id)
    assert valid and blockers == ()
    assert readiness.ready
    assert readiness.warmup_excluded_rows == 2
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    loaded = service.load_database_revision(manifest.database_id, manifest.revision_id)

    assert loaded.manifest == manifest
    definition = service.load_database_definition(manifest.database_id)
    assert definition.seed_id == seed.seed_id
    assert definition.market_id == market
    assert loaded.values_csv.startswith(b"ts_ms,open,close,volume,")
    assert len(service.list_database_revisions(manifest.database_id)) == 1
    assert service.load_database_revision(manifest.database_id).manifest == manifest

    _market, restarted, _a, _r = _domain(tmp_path)
    assert restarted.load_database_seed(seed.seed_id) == seed
    assert restarted.load_artifact_collection(collection.collection_id) == collection
    assert restarted.load_database_revision(manifest.database_id, manifest.revision_id) == loaded


def test_seed_reference_and_database_publication_are_atomic(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    result = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(result, "Feature set")
    seed = service.create_database_seed(market, "Database")

    with pytest.raises(RuntimeError, match="stop before publish"):
        service.build_database_revision(
            seed.seed_id,
            collection.collection_id,
            before_publish=lambda: (_ for _ in ()).throw(RuntimeError("stop before publish")),
        )
    assert service.list_database_ids() == ()
    assert service.delete_database_seed(seed.seed_id) == seed


def _fail_head_publication(
    monkeypatch: pytest.MonkeyPatch,
    store: DataManagerCreationStore,
    persistence_root: str,
) -> None:
    write_atomic = store._write_atomic

    def controlled_failure(path: Path, payload: bytes) -> None:
        if path.name == "head.json" and persistence_root in path.parts:
            raise RuntimeError(f"controlled {persistence_root} head failure")
        write_atomic(path, payload)

    monkeypatch.setattr(store, "_write_atomic", controlled_failure)


def test_new_collection_head_failure_leaves_no_logical_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    _fail_head_publication(monkeypatch, service.creation_store, "artifact_collections")

    with pytest.raises(RuntimeError, match="controlled artifact_collections head failure"):
        service.create_artifact_collection(materialization, "Failed Collection")

    assert service.list_artifact_collections() == ()
    assert service.creation_store.list_collection_ids() == ()
    _market, restarted, _artifacts, _recipes = _domain(tmp_path)
    assert restarted.list_artifact_collections() == ()
    assert restarted.creation_store.list_collection_ids() == ()


def test_existing_collection_head_failure_preserves_previous_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    accepted = service.create_artifact_collection(materialization, "Accepted Collection")
    _fail_head_publication(monkeypatch, service.creation_store, "artifact_collections")

    with pytest.raises(RuntimeError, match="controlled artifact_collections head failure"):
        service.revise_artifact_collection(accepted.collection_id, description="Rejected")

    assert service.load_artifact_collection(accepted.collection_id) == accepted
    assert service.list_artifact_collection_revisions(accepted.collection_id) == (accepted,)
    assert service.load_artifact_collection(
        accepted.collection_id, accepted.revision_id
    ) == accepted
    _market, restarted, _artifacts, _recipes = _domain(tmp_path)
    assert restarted.load_artifact_collection(accepted.collection_id) == accepted
    assert restarted.list_artifact_collection_revisions(accepted.collection_id) == (
        accepted,
    )
    assert restarted.load_artifact_collection(
        accepted.collection_id, accepted.revision_id
    ) == accepted


def test_new_database_head_failure_removes_definition_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Features")
    seed = service.create_database_seed(market, "Failed Database")
    _fail_head_publication(monkeypatch, service.creation_store, "databases")

    with pytest.raises(RuntimeError, match="controlled databases head failure"):
        service.build_database_revision(seed.seed_id, collection.collection_id)

    assert service.list_database_ids() == ()
    assert service.delete_database_seed(seed.seed_id) == seed
    _market, restarted, _artifacts, _recipes = _domain(tmp_path)
    assert restarted.list_database_ids() == ()
    assert restarted.list_database_seeds() == ()


def test_existing_database_head_failure_preserves_previous_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Features")
    seed = service.create_database_seed(market, "Accepted Database")
    accepted = service.build_database_revision(seed.seed_id, collection.collection_id)
    accepted_loaded = service.load_database_revision(
        accepted.database_id, accepted.revision_id
    )
    revised_collection = service.revise_artifact_collection(
        collection.collection_id, description="Next revision"
    )
    _fail_head_publication(monkeypatch, service.creation_store, "databases")

    with pytest.raises(RuntimeError, match="controlled databases head failure"):
        service.build_database_revision(
            seed.seed_id,
            revised_collection.collection_id,
            database_id=accepted.database_id,
        )

    assert service.load_database_revision(accepted.database_id) == accepted_loaded
    assert service.list_database_revisions(accepted.database_id) == (accepted,)
    assert service.load_database_revision(
        accepted.database_id, accepted.revision_id
    ) == accepted_loaded
    _market, restarted, _artifacts, _recipes = _domain(tmp_path)
    assert restarted.load_database_revision(accepted.database_id) == accepted_loaded
    assert restarted.list_database_revisions(accepted.database_id) == (accepted,)
    assert restarted.load_database_revision(
        accepted.database_id, accepted.revision_id
    ) == accepted_loaded


def test_output_collisions_are_rejected_before_database_build(tmp_path: Path) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    result = _materialize(service, recipes, sma, ema)
    first, second = result.root_logical_artifact_ids
    by_logical = {item.logical_artifact_id: item for item in result.managed_artifacts}
    with pytest.raises(DataManagerCreationError, match="unique|presentation_order"):
        service.create_artifact_collection(
            result,
            "Invalid",
            selected_outputs=(
                ArtifactCollectionOutputV1(first, by_logical[first].output_names[0], "feature"),
                ArtifactCollectionOutputV1(second, by_logical[second].output_names[0], "feature"),
            ),
        )


def test_selected_outputs_and_presentation_order_advance_only_the_head(tmp_path: Path) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    ema = _leaf("ema", {"period": 3})
    result = _materialize(service, recipes, sma, ema)
    by_logical = {item.logical_artifact_id: item for item in result.managed_artifacts}
    first, second = result.root_logical_artifact_ids
    collection = service.create_artifact_collection(
        result,
        "Features",
        selected_outputs=(
            ArtifactCollectionOutputV1(first, by_logical[first].output_names[0], "sma_feature"),
            ArtifactCollectionOutputV1(second, by_logical[second].output_names[0], "ema_feature"),
        ),
    )
    revised = service.revise_artifact_collection(
        collection.collection_id,
        selected_outputs=collection.selected_outputs,
        presentation_order=("ema_feature", "sma_feature"),
    )

    assert revised.presentation_order == ("ema_feature", "sma_feature")
    assert service.load_artifact_collection(collection.collection_id).revision_id == revised.revision_id
    assert service.load_artifact_collection(
        collection.collection_id, collection.revision_id
    ).presentation_order == ("sma_feature", "ema_feature")


def test_batch_unsupported_combination_and_cancellation_do_not_mutate_collection(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(base, "Base")
    source = base.managed_artifacts[0]
    unsupported = BatchArtifactRequest(
        market_id=market,
        expected_source_ohlcv=base.source_ohlcv,
        branches=(BatchArtifactBranchRequest(
            tool_key="delta",
            parameters={"mode": "abs", "eps": 1e-12},
            sources=(
                DataManagerDirectArtifactSource(
                    "fast", source.logical_artifact_id, source.artifact_id,
                    source.output_names[0],
                ),
                DataManagerDirectArtifactSource(
                    "slow", source.logical_artifact_id, source.artifact_id,
                    source.output_names[0],
                ),
            ),
            requested_outputs=("invalid",),
        ),),
        destination="collection_revision",
        collection_id=collection.collection_id,
    )
    with pytest.raises(DataManagerCreationError, match="requested outputs"):
        service.plan_batch_artifacts(unsupported)

    output = source.output_names[0]
    valid = BatchArtifactRequest(
        market_id=market,
        expected_source_ohlcv=base.source_ohlcv,
        branches=(BatchArtifactBranchRequest(
            tool_key="derivative",
            parameters={"order": 1},
            sources=(DataManagerDirectArtifactSource(
                "source", source.logical_artifact_id, source.artifact_id, output
            ),),
            requested_outputs=resolve_output_names(
                "derivative", {"order": 1, "source": output}
            ),
        ),),
        destination="collection_revision",
        collection_id=collection.collection_id,
    )
    plan = service.plan_batch_artifacts(valid)
    recipes_before = _persistence_bytes(recipes.root_dir)
    artifacts_before = _persistence_bytes(tmp_path / "historical")
    managed_before = _artifacts.list_managed_artifacts(market)
    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service.execute_batch_artifacts(plan, cancellation_requested=lambda: True)
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert _artifacts.list_managed_artifacts(market) == managed_before
    assert _persistence_bytes(tmp_path / "historical") == artifacts_before
    assert _persistence_bytes(recipes.root_dir) == recipes_before


def test_database_revisions_retain_exact_old_snapshots_and_protect_seed(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    result = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(result, "Features")
    seed = service.create_database_seed(market, "Database")
    first = service.build_database_revision(seed.seed_id, collection.collection_id)
    first_loaded = service.load_database_revision(first.database_id, first.revision_id)
    revised_collection = service.revise_artifact_collection(
        collection.collection_id, description="Reviewed"
    )
    second = service.build_database_revision(
        seed.seed_id,
        revised_collection.collection_id,
        database_id=first.database_id,
    )

    assert second.previous_revision_id == first.revision_id
    assert len(service.list_database_revisions(first.database_id)) == 2
    assert service.load_database_revision(first.database_id, first.revision_id) == first_loaded
    with pytest.raises(DataManagerCreationError, match="referenced"):
        service.delete_database_seed(seed.seed_id)


def test_semantically_equivalent_collection_reuses_shared_artifact_versions(
    tmp_path: Path,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    result = _materialize(service, recipes, sma)
    first = service.create_artifact_collection(result, "First")
    values = service._creation._collection_values_from_materialization(result, None)
    assert service.creation_store.find_equivalent_collection(
        market_id=values["market_id"],
        source_ohlcv=values["source_ohlcv"],
        root_logical_artifact_ids=values["roots"],
        support_logical_artifact_ids=values["supports"],
        members=values["members"],
        selected_outputs=values["selected_outputs"],
        presentation_order=values["presentation_order"],
    ) == first
    artifact_bytes = _persistence_bytes(tmp_path / "historical")
    service.creation_store._token_factory = lambda: pytest.fail(
        "equivalent Create must not allocate a Collection identity"
    )

    second = service.create_artifact_collection(
        result, "Second", description="requested metadata"
    )

    assert second == first
    assert first.members == second.members
    assert first.collection_id == second.collection_id
    assert first.revision_id == second.revision_id
    assert second.display_name == "First"
    assert second.description == ""
    assert service.creation_store.list_collection_ids() == (first.collection_id,)
    assert _persistence_bytes(tmp_path / "historical") == artifact_bytes
    collection_root = service.creation_store.root_dir / "artifact_collections"
    assert not any(path.name == "values.csv" for path in collection_root.rglob("*"))


def test_selection_create_reuses_equivalent_root_and_member_order(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    result = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 3}),
    )
    roots = result.root_logical_artifact_ids
    first_plan = service.plan_artifact_collection_selection(market, roots)
    outputs = tuple(
        ArtifactCollectionOutputV1(
            logical_id,
            next(
                item for item in first_plan.members
                if item.version_key.logical_artifact_id == logical_id
            ).output_names[0],
            f"feature_{index}",
        )
        for index, logical_id in enumerate(sorted(roots), start=1)
    )
    first = service.create_artifact_collection_from_selection(
        first_plan, "First", selected_outputs=outputs
    )
    reversed_plan = service.plan_artifact_collection_selection(
        market, tuple(reversed(roots))
    )

    reused = service.create_artifact_collection_from_selection(
        reversed_plan,
        "Different name",
        description="different description",
        selected_outputs=outputs,
    )

    assert reused == first
    assert reversed_plan.root_logical_artifact_ids != (
        first_plan.root_logical_artifact_ids
    )
    assert reversed_plan.members != first_plan.members
    assert service.creation_store.list_collection_ids() == (first.collection_id,)


def test_collection_semantics_ignore_member_version_output_and_order(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes = _domain(tmp_path)
    result = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 3}),
    )
    plan = service.plan_artifact_collection_selection(
        market, result.root_logical_artifact_ids
    )
    outputs = tuple(
        ArtifactCollectionOutputV1(
            member.version_key.logical_artifact_id,
            member.output_names[0],
            f"feature_{index}",
        )
        for index, member in enumerate(plan.members, start=1)
    )
    original = service.create_artifact_collection_from_selection(
        plan, "Original", selected_outputs=outputs
    )
    remapped = (
        replace(outputs[0], column_name="remapped_feature"),
        *outputs[1:],
    )
    mapping_variant = service.create_artifact_collection_from_selection(
        plan, "Mapping variant", selected_outputs=remapped
    )
    order_variant = service.create_artifact_collection_from_selection(
        plan, "Order variant", selected_outputs=tuple(reversed(outputs))
    )

    logical_id = plan.root_logical_artifact_ids[0]
    _advance_same_source(service, artifacts, logical_id)
    advanced_plan = service.plan_artifact_collection_selection(
        market, plan.root_logical_artifact_ids
    )
    advanced_outputs = tuple(
        ArtifactCollectionOutputV1(
            item.version_key.logical_artifact_id,
            item.output_names[0],
            outputs[index].column_name,
        )
        for index, item in enumerate(advanced_plan.members)
    )
    version_variant = service.create_artifact_collection_from_selection(
        advanced_plan, "Version variant", selected_outputs=advanced_outputs
    )

    assert len(
        {
            original.collection_id,
            mapping_variant.collection_id,
            order_variant.collection_id,
            version_variant.collection_id,
        }
    ) == 1
    assert mapping_variant == original
    assert order_variant == original
    assert version_variant == original


def test_collection_semantics_include_source_and_ignore_recipe_collection_provenance(
    tmp_path: Path,
) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.create_artifact_collection(
        result,
        "First",
        source_recipe_collection_id="prc_" + "a" * 32,
        source_recipe_collection_revision_id="1" * 64,
    )
    reused = service.create_artifact_collection(
        result,
        "Different provenance",
        source_recipe_collection_id="prc_" + "b" * 32,
        source_recipe_collection_revision_id="2" * 64,
    )
    changed_source = replace(first.source_ohlcv, csv_sha256="f" * 64)
    source_variant = service.creation_store.create_collection_revision(
        market_id=first.market_id,
        source_ohlcv=changed_source,
        root_logical_artifact_ids=first.root_logical_artifact_ids,
        support_logical_artifact_ids=first.support_logical_artifact_ids,
        members=first.members,
        selected_outputs=first.selected_outputs,
        presentation_order=first.presentation_order,
        revision_factory=lambda collection_id: _collection_revision_like(
            service,
            first,
            collection_id=collection_id,
            source_ohlcv=changed_source,
        ),
    )

    assert reused == first
    assert reused.source_recipe_collection_id == "prc_" + "a" * 32
    assert source_variant.collection_id != first.collection_id
    assert source_variant.source_ohlcv == changed_source


def test_collection_revision_collision_reuses_oldest_peer_without_mutation(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    plan = service.plan_artifact_collection_selection(
        market, result.root_logical_artifact_ids
    )
    oldest = service.create_artifact_collection_from_selection(plan, "Oldest")
    younger = _collection_revision_like(
        service,
        oldest,
        collection_id="ac_" + "f" * 32,
        display_name="Younger duplicate",
        created_at_utc=oldest.created_at_utc + timedelta(microseconds=1),
    )
    _persist_legacy_collection(service.creation_store, younger)

    reused = service.edit_artifact_collection_from_selection(
        younger.collection_id,
        plan,
        display_name="Requested metadata",
        description="must not publish",
        expected_revision_id=younger.revision_id,
    )

    assert reused == oldest
    assert service.load_artifact_collection(oldest.collection_id) == oldest
    assert service.load_artifact_collection(younger.collection_id) == younger
    assert service.list_artifact_collection_revisions(younger.collection_id) == (
        younger,
    )

    assert service.revise_artifact_collection(
        younger.collection_id, description="still no publication"
    ) == oldest
    assert service.add_artifact_collection_branches(
        younger.collection_id, result
    ) == oldest
    assert service.list_artifact_collection_revisions(younger.collection_id) == (
        younger,
    )

    revised_oldest = service.edit_artifact_collection_from_selection(
        oldest.collection_id,
        plan,
        display_name="Oldest updated",
        expected_revision_id=oldest.revision_id,
    )
    assert revised_oldest.collection_id == oldest.collection_id
    assert revised_oldest.revision_id != oldest.revision_id
    assert service.load_artifact_collection(younger.collection_id) == younger


def test_collection_oldest_winner_uses_collection_id_tie_break_and_skips_stale(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    values = service._creation._collection_values_from_materialization(
        result, None
    )
    template = service._creation._build_collection_revision(
        collection_id="ac_" + "f" * 32,
        display_name="Template",
        description="",
        source_recipe_collection_id=None,
        source_recipe_collection_revision_id=None,
        previous_revision_id=None,
        created_at_utc=service._creation._clock(),
        revised_at_utc=service._creation._clock(),
        **values,
    )
    lexical_winner = _collection_revision_like(
        service,
        template,
        collection_id="ac_" + "1" * 32,
        display_name="Lexical winner",
    )
    lexical_loser = _collection_revision_like(
        service,
        template,
        collection_id="ac_" + "2" * 32,
        display_name="Lexical loser",
    )
    stale = _collection_with_validation_state(
        _collection_revision_like(
            service,
            template,
            collection_id="ac_" + "0" * 32,
            display_name="Stale",
            created_at_utc=template.created_at_utc - timedelta(seconds=1),
        ),
        "stale",
    )
    for revision in (lexical_loser, stale, lexical_winner):
        _persist_legacy_collection(service.creation_store, revision)

    reused = service.create_artifact_collection(result, "Requested")

    assert reused == lexical_winner
    assert reused.market_id == market
    assert service.creation_store.list_collection_ids() == (
        stale.collection_id,
        lexical_winner.collection_id,
        lexical_loser.collection_id,
    )


def test_import_and_store_construction_create_no_runtime_directories(tmp_path: Path) -> None:
    store = DataManagerCreationStore(tmp_path / "data_manager")
    assert store.list_collection_ids() == ()
    assert store.list_database_ids() == ()
    assert store.list_seeds() == ()
    assert not store.root_dir.exists()


def test_creation_operations_run_through_shared_core_runner(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    result = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(result, "Features")
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = DataManagerApplicationService(runner, service)
    completed = Event()
    received: list[TaskResult] = []
    runner.start()
    try:
        application.submit_create_database_seed(
            market,
            "Core-supervised Database",
            result_callback=lambda item: (received.append(item), completed.set()),
        )
        assert completed.wait(3.0)
        assert received[0].status == "completed"
        seed = received[0].value
        completed.clear()
        application.submit_assess_database_readiness(
            seed.seed_id,
            collection.collection_id,
            result_callback=lambda item: (received.append(item), completed.set()),
        )
        assert completed.wait(3.0)
        assert received[-1].value.ready
        operations = {item.metadata.get("operation") for item in manager.snapshots()}
        assert "data_manager.create_database_seed" in operations
        assert "data_manager.assess_database_readiness" in operations
    finally:
        runner.shutdown()
