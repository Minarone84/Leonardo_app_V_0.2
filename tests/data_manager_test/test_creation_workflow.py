from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from leonardo.artifacts import ArtifactService
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
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeStore,
    build_portable_recipe,
)
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


def test_explicit_batch_branch_reuses_recipe_and_can_advance_collection(tmp_path: Path) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    base = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(base, "Base")
    source = base.managed_artifacts[0]
    output = source.output_names[0]
    requested = resolve_output_names("derivative", {"order": 1, "source": output})
    request = BatchArtifactRequest(
        market,
        (
            BatchArtifactBranchRequest(
                source.logical_artifact_id,
                output,
                "derivative",
                {"order": 1},
                requested,
            ),
        ),
        "collection_revision",
        collection.collection_id,
    )

    plan = service.plan_batch_artifacts(request)
    assert not plan.blocked
    assert len(plan.new_recipe_ids) == 1
    result, revised = service.execute_batch_artifacts(plan)
    assert result.root_logical_artifact_ids
    assert revised is not None
    assert revised.previous_revision_id == collection.revision_id
    replay = service.plan_batch_artifacts(request)
    assert replay.reusable_recipe_ids == plan.recipe_ids


@pytest.mark.parametrize(
    "tool_key",
    ("derivative", "angle", "angle_momentum", "delta", "trap_area", "percent_span_angle"),
)
def test_all_authorized_batch_constructs_plan_and_materialize(
    tmp_path: Path, tool_key: str,
) -> None:
    market, service, _artifacts, recipes = _domain(tmp_path)
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
        market,
        (BatchArtifactBranchRequest(
            source.logical_artifact_id,
            first,
            tool_key,
            parameters,
            resolve_output_names(tool_key, naming),
        ),),
        "new_collection",
    )

    plan = service.plan_batch_artifacts(request)
    assert not plan.blocked
    result, collection = service.execute_batch_artifacts(plan)
    assert result.root_logical_artifact_ids
    assert collection is not None
    assert collection.root_logical_artifact_ids == result.root_logical_artifact_ids


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
        market,
        (BatchArtifactBranchRequest(
            source.logical_artifact_id,
            source.output_names[0],
            "delta",
            {"mode": "abs", "eps": 1e-12},
            ("invalid",),
        ),),
        "collection_revision",
        collection.collection_id,
    )
    assert service.plan_batch_artifacts(unsupported).blocked

    output = source.output_names[0]
    valid = BatchArtifactRequest(
        market,
        (BatchArtifactBranchRequest(
            source.logical_artifact_id,
            output,
            "derivative",
            {"order": 1},
            resolve_output_names("derivative", {"order": 1, "source": output}),
        ),),
        "collection_revision",
        collection.collection_id,
    )
    plan = service.plan_batch_artifacts(valid)
    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service.execute_batch_artifacts(plan, cancellation_requested=lambda: True)
    assert service.load_artifact_collection(collection.collection_id) == collection


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


def test_shared_artifact_versions_are_referenced_not_copied(tmp_path: Path) -> None:
    _market, service, _artifacts, recipes = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    result = _materialize(service, recipes, sma)
    first = service.create_artifact_collection(result, "First")
    second = service.create_artifact_collection(result, "Second")

    assert first.members == second.members
    assert first.collection_id != second.collection_id
    collection_root = service.creation_store.root_dir / "artifact_collections"
    assert not any(path.name == "values.csv" for path in collection_root.rglob("*"))


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
