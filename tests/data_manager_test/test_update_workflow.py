from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest

from leonardo.artifacts import ArtifactService, ArtifactSourceRefV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerArtifactMaterializationResult,
    DataManagerArtifactMaterializationRequest,
    ArtifactCollectionOutputV1,
    DataManagerCreationStore,
    DataManagerOperationError,
    DataManagerService,
)
from leonardo.data_manager.artifact_materialization import (
    _calculate_recipe,
    _dataset_frame,
)
from leonardo.financial_tools import (
    calculate_financial_tool,
    resolve_output_names,
    resolve_parameters,
)
from leonardo.ohlcv.store import Candle, OHLCVStore
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


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _domain(tmp_path: Path, *, initialize: bool = True):
    historical = tmp_path / "historical"
    if initialize:
        _accepted_dataset(historical, market=MARKET, rows=96)
    catalog = AcceptedDatasetCatalog(historical)
    artifacts = ArtifactService(historical)
    recipes = PortableRecipeStore(tmp_path / "recipes")
    service = DataManagerService(
        catalog,
        HistoricalDatasetLoader(catalog),
        artifacts,
        StudyEnvironmentStore(tmp_path / "environments"),
        recipes,
        PortableRecipeGraphPlanner(recipes),
        DataManagerCreationStore(tmp_path / "data_manager"),
    )
    return service, artifacts, recipes, historical


def _sma(period: int = 3):
    parameters = dict(resolve_parameters("sma", {"period": period}))
    return build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters=parameters,
        output_names=resolve_output_names("sma", parameters),
    )


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


def _angle(owner):
    parameters = dict(resolve_parameters("angle", {}))
    naming = {**parameters, "source": "__research_source"}
    return build_portable_recipe(
        tool_key="angle",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("angle", naming),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", owner.recipe_id, owner.output_names[0]
            ),
        ),
    )


def _braid(fast, mid, slow):
    parameters = dict(resolve_parameters("braids", {"tie_policy": "carry"}))
    naming = {
        **parameters,
        "fast": "__research_fast",
        "mid": "__research_mid",
        "slow": "__research_slow",
    }
    return build_portable_recipe(
        tool_key="braids",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("braids", naming),
        dependencies=(
            PortableRecipeDependencyV1("fast", fast.recipe_id, fast.output_names[0]),
            PortableRecipeDependencyV1("mid", mid.recipe_id, mid.output_names[0]),
            PortableRecipeDependencyV1("slow", slow.recipe_id, slow.output_names[0]),
        ),
    )


def _materialize(service, recipes, *roots):
    for recipe in roots:
        recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(
            MARKET, tuple(item.recipe_id for item in roots)
        )
    )
    assert not plan.blocked
    return service.execute_artifact_materialization(plan)


def _append(historical: Path, rows: int = 104) -> None:
    _accepted_dataset(historical, market=MARKET, rows=rows)


def _publish_modified(historical: Path, *, rows: int, mutate_row: int | None = None) -> None:
    _accepted_dataset(historical, market=MARKET, rows=rows)
    store = OHLCVStore(historical)
    candles = store.read(MARKET)
    if mutate_row is not None:
        candle = candles[mutate_row]
        candles[mutate_row] = Candle(
            candle.ts_ms,
            candle.open,
            candle.high,
            candle.low,
            candle.close + 0.25,
            candle.volume,
        )
        store.write(
            MARKET,
            candles,
            source="test",
            persistence_status="committed",
        )
        csv_path = store.csv_path(MARKET)
        sidecar_path = store.sidecar_path(MARKET)
        csv_stat = csv_path.stat()
        sidecar_stat = sidecar_path.stat()
        store.publish_validation(
            MARKET,
            expected_csv_size=csv_stat.st_size,
            expected_csv_mtime_ns=csv_stat.st_mtime_ns,
            expected_csv_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            expected_sidecar_size=sidecar_stat.st_size,
            expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
            expected_sidecar_sha256=hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
            status="ok",
            row_count=len(candles),
            first_timestamp_ms=candles[0].ts_ms,
            last_timestamp_ms=candles[-1].ts_ms,
            warnings=(),
            issue_codes=(),
            error_count=0,
            warning_count=0,
            validator="task-1060-test",
        )


def test_source_change_classification_uses_exact_csv_prefix(tmp_path: Path) -> None:
    service, artifacts, _recipes, historical = _domain(tmp_path)
    previous = artifacts.capture_accepted_source(MARKET)

    assert service._updates.classify_source_change(previous).status == "UNCHANGED"
    _append(historical)
    append = service._updates.classify_source_change(previous)
    assert append.status == "APPEND_ONLY"
    assert append.missing_row_count == 8

    csv_path = AcceptedDatasetCatalog(historical).inspect_market(MARKET).csv_path
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    fields = lines[2].split(",")
    fields[4] = str(float(fields[4]) + 10.0)
    lines[2] = ",".join(fields)
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert service._updates.classify_source_change(previous).status == "INVALID_SOURCE"


def test_sidecar_only_evidence_change_is_not_unchanged(tmp_path: Path) -> None:
    service, artifacts, _recipes, historical = _domain(tmp_path)
    previous = artifacts.capture_accepted_source(MARKET)
    store = artifacts._ohlcv_store
    sidecar = store.read_sidecar(MARKET)
    stat = store.csv_path(MARKET).stat()
    sidecar_stat = store.sidecar_path(MARKET).stat()
    store.publish_validation(
        MARKET,
        expected_csv_size=stat.st_size,
        expected_csv_mtime_ns=stat.st_mtime_ns,
        expected_csv_sha256=previous.csv_sha256,
        expected_sidecar_size=sidecar_stat.st_size,
        expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=previous.sidecar_sha256,
        status="ok",
        row_count=sidecar.row_count,
        first_timestamp_ms=sidecar.first_timestamp_ms,
        last_timestamp_ms=sidecar.last_timestamp_ms,
        warnings=("evidence changed",),
        issue_codes=(),
        error_count=0,
        warning_count=1,
        validator="task-1060-test",
    )
    assert service._updates.classify_source_change(previous).status == "HISTORICAL_MUTATION"


def test_truncated_source_is_classified_without_terminal_inference(tmp_path: Path) -> None:
    service, artifacts, _recipes, historical = _domain(tmp_path)
    previous = artifacts.capture_accepted_source(MARKET)
    _publish_modified(historical, rows=80)
    change = service._updates.classify_source_change(previous)
    assert change.status == "TRUNCATED"
    assert change.current_through_ms < change.previous_through_ms


def test_dependency_reconciliation_and_collection_update_are_atomic(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(result, "SMA derivative")
    old_artifacts = {
        item.logical_artifact_id: item.artifact_id for item in result.managed_artifacts
    }
    _append(historical)

    snapshot = service.reconcile_update_status(force=True)
    assert {item.status for item in snapshot.artifacts} == {
        "APPEND_AVAILABLE",
        "BLOCKED_BY_DEPENDENCY",
    }
    assert snapshot.collections[0].status == "BLOCKED_BY_DEPENDENCY"
    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert tuple(node.tool_key for node in plan.nodes) == ("sma", "derivative")
    assert all(node.action == "UPDATE" for node in plan.nodes)

    with pytest.raises(DataManagerOperationError, match="cancelled"):
        service.execute_artifact_collection_update(
            plan, cancellation_requested=lambda: True
        )
    assert {
        item.logical_artifact_id: item.artifact_id
        for item in artifacts.list_managed_artifacts(MARKET)
    } == old_artifacts
    assert service.load_artifact_collection(collection.collection_id) == collection

    publication_calls = 0
    publish = artifacts.publish_managed_artifact_graph

    def counted_publish(*args, **kwargs):
        nonlocal publication_calls
        publication_calls += 1
        return publish(*args, **kwargs)

    monkeypatch.setattr(artifacts, "publish_managed_artifact_graph", counted_publish)
    updated = service.execute_artifact_collection_update(plan)
    assert publication_calls == 1
    assert updated.collection_revision.previous_revision_id == collection.revision_id
    assert updated.collection_revision.source_ohlcv.row_count == 104
    assert updated.reconciliation_snapshot.collections[0].status == "CURRENT"
    assert service.load_artifact_collection(
        collection.collection_id, collection.revision_id
    ) == collection
    for logical_id, artifact_id in old_artifacts.items():
        assert artifacts.load_artifact_version(MARKET, logical_id, artifact_id)


def test_selection_created_collection_preserves_update_vertical(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative)
    selection = service.plan_artifact_collection_selection(
        MARKET, materialization.root_logical_artifact_ids
    )
    collection = service.create_artifact_collection_from_selection(
        selection, "Selected derivative"
    )

    _append(historical)
    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert tuple(node.tool_key for node in plan.nodes) == ("sma", "derivative")
    updated = service.execute_artifact_collection_update(plan)

    assert updated.collection_revision.previous_revision_id == collection.revision_id
    assert updated.collection_revision.root_logical_artifact_ids == (
        selection.root_logical_artifact_ids
    )
    assert {item.role for item in updated.collection_revision.dependency_edges} == {
        "source"
    }


def test_collection_update_never_consults_recipe_domain_after_artifact_creation(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(
        materialization, "Recipe-independent derivative"
    )
    recipes.delete_recipe(derivative.recipe_id)
    recipes.delete_recipe(sma.recipe_id)
    for recipe_id in (sma.recipe_id, derivative.recipe_id):
        with pytest.raises(FileNotFoundError):
            recipes.load_recipe(recipe_id)

    def forbidden_recipe_access(*_args, **_kwargs):
        raise AssertionError("Artifact Collection update consulted Recipe authority")

    monkeypatch.setattr(service._portable_recipes, "load_recipe", forbidden_recipe_access)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden_recipe_access)
    _append(historical)

    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    updated = service.execute_artifact_collection_update(plan)
    assert updated.collection_revision.previous_revision_id == collection.revision_id

    heads = {
        item.portable_recipe_id: item
        for item in artifacts.list_managed_artifacts(MARKET)
    }
    source = artifacts.load_artifact_by_id(
        MARKET, heads[sma.recipe_id].artifact_id
    )
    dependent = artifacts.load_artifact_by_id(
        MARKET, heads[derivative.recipe_id].artifact_id
    )
    recipe = dependent.metadata.recipe
    selector = recipe.bindings["source"]
    complete_input = _dataset_frame(service._loader.load(MARKET))
    complete_input[selector] = source.frame[sma.output_names[0]].to_numpy(copy=True)
    expected = calculate_financial_tool(
        recipe.tool_key,
        complete_input,
        recipe.parameters,
        bindings=recipe.bindings,
    )
    pd.testing.assert_frame_equal(dependent.frame, expected.to_frame())
    assert dependent.metadata.recipe.source_artifacts == (
        ArtifactSourceRefV1("source", source.metadata.artifact_id, sma.output_names[0]),
    )


def test_collection_update_rejects_matching_but_invalid_artifact_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, _recipes, historical = _domain(tmp_path)
    dataset = service._loader.load(MARKET)
    frame = _dataset_frame(dataset)
    source = artifacts.capture_accepted_source(MARKET)
    sma = artifacts.prepare_managed_calculation(
        MARKET,
        "a" * 64,
        calculate_financial_tool("sma", frame, {"period": 3}),
        expected_source=source,
    )
    malformed = artifacts.prepare_managed_calculation(
        MARKET,
        "b" * 64,
        calculate_financial_tool(
            "derivative",
            frame,
            {"order": 1},
            bindings={"source": "close"},
        ),
        expected_source=source,
        source_artifacts=(
            ArtifactSourceRefV1(
                "fast", sma.metadata.artifact_id, sma.metadata.recipe.output_names[0]
            ),
        ),
        source_metadata=(sma.metadata,),
    )
    publication = artifacts.publish_managed_artifact_graph(
        (sma, malformed), expected_source=source
    )
    entries = service.scan_managed_artifacts().artifacts
    by_id = {item.logical_artifact_id: item for item in entries}
    materialization = DataManagerArtifactMaterializationResult(
        "c" * 64,
        MARKET,
        source,
        (malformed.logical_artifact_id,),
        (sma.logical_artifact_id,),
        publication.created_artifact_ids,
        publication.reused_artifact_ids,
        publication.created_version_keys,
        publication.reused_version_keys,
        publication.advanced_logical_artifact_ids,
        (by_id[sma.logical_artifact_id], by_id[malformed.logical_artifact_id]),
    )
    collection = service.create_artifact_collection(
        materialization, "Malformed derivative"
    )
    assert collection.dependency_edges[0].role == "fast"
    revisions_before = service.list_artifact_collection_revisions(
        collection.collection_id
    )
    heads_before = tuple(artifacts.list_managed_artifacts(MARKET))
    publication_calls = 0

    def reject_publication(*_args, **_kwargs):
        nonlocal publication_calls
        publication_calls += 1
        raise AssertionError("invalid Update reached Artifact publication")

    monkeypatch.setattr(
        artifacts, "publish_managed_artifact_graph", reject_publication
    )
    _append(historical)

    plan = service.plan_artifact_collection_update(collection.collection_id)

    assert plan.blocked
    assert any("derivative source roles are invalid" in item for item in plan.blockers)
    assert publication_calls == 0
    assert service.list_artifact_collection_revisions(
        collection.collection_id
    ) == revisions_before
    assert tuple(artifacts.list_managed_artifacts(MARKET)) == heads_before


def test_braid_update_preserves_fast_mid_slow_roles_without_recipe_authority(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    fast = _sma(3)
    mid = _sma(5)
    slow = _sma(8)
    braid = _braid(fast, mid, slow)
    for recipe in (fast, mid, slow):
        recipes.save_recipe(recipe)
    materialization = _materialize(service, recipes, braid)
    collection = service.create_artifact_collection(materialization, "Braid")
    for recipe in (braid, fast, mid, slow):
        recipes.delete_recipe(recipe.recipe_id)

    def forbidden_recipe_access(*_args, **_kwargs):
        raise AssertionError("Braid update consulted Recipe authority")

    monkeypatch.setattr(service._portable_recipes, "load_recipe", forbidden_recipe_access)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden_recipe_access)
    _append(historical)

    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    braid_node = next(node for node in plan.nodes if node.tool_key == "braids")
    support_nodes = tuple(node for node in plan.nodes if node.tool_key == "sma")
    assert len(support_nodes) == 3
    assert all(
        plan.member_recipe_ids.index(node.portable_recipe_id)
        < plan.member_recipe_ids.index(braid_node.portable_recipe_id)
        for node in support_nodes
    )
    assert set(braid_node.dependency_logical_artifact_ids) == {
        node.logical_artifact_id for node in support_nodes
    }

    service.execute_artifact_collection_update(plan)
    heads = {
        item.portable_recipe_id: item
        for item in artifacts.list_managed_artifacts(MARKET)
    }
    braid_artifact = artifacts.load_artifact_by_id(
        MARKET, heads[braid.recipe_id].artifact_id
    )
    refs = {ref.role: ref for ref in braid_artifact.metadata.recipe.source_artifacts}
    expected = {
        "fast": (heads[fast.recipe_id].artifact_id, fast.output_names[0]),
        "mid": (heads[mid.recipe_id].artifact_id, mid.output_names[0]),
        "slow": (heads[slow.recipe_id].artifact_id, slow.output_names[0]),
    }
    assert tuple(refs) == ("fast", "mid", "slow")
    assert {
        role: (ref.artifact_id, ref.output_name) for role, ref in refs.items()
    } == expected
    assert braid_artifact.metadata.recipe.output_names == braid.output_names


def test_reconciliation_captures_one_source_for_all_managed_dependents(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(materialization, "SMA derivative")
    seed = service.create_database_seed(MARKET, "Research database")
    service.build_database_revision(seed.seed_id, collection.collection_id)

    calls: list[MarketId] = []
    original = artifacts.capture_accepted_source

    def counted(market_id: MarketId):
        calls.append(market_id)
        return original(market_id)

    monkeypatch.setattr(artifacts, "capture_accepted_source", counted)
    snapshot = service.reconcile_update_status(force=True)
    assert len(snapshot.artifacts) == 2
    assert len(snapshot.collections) == 1
    assert len(snapshot.databases) == 1
    assert calls == [MARKET]


def test_standalone_managed_artifact_reports_invalid_missing_source(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    artifacts._ohlcv_store.sidecar_path(MARKET).unlink()

    snapshot = service.reconcile_update_status(force=True)
    assert len(snapshot.source_changes) == 1
    assert snapshot.source_changes[0].market_id == MARKET
    assert snapshot.source_changes[0].status == "INVALID_SOURCE"
    assert snapshot.source_changes[0].current_source is None
    assert snapshot.artifacts[0].logical_artifact_id == (
        materialization.managed_artifacts[0].logical_artifact_id
    )
    assert snapshot.artifacts[0].status == "INVALID"


def test_overlap_boundaries_are_nonempty_and_match_complete_calculation(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    angle = _angle(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative, angle)
    collection = service.create_artifact_collection(materialization, "SMA transforms")
    _append(historical)

    compared_rows: list[int] = []
    original = service._updates._require_frames_equal

    def record(left, right, context):
        if context == "overlap":
            compared_rows.append(len(left))
        return original(left, right, context)

    monkeypatch.setattr(service._updates, "_require_frames_equal", record)
    service.execute_artifact_collection_update(
        service.plan_artifact_collection_update(collection.collection_id)
    )
    assert len(compared_rows) == 3
    assert all(value >= 1 for value in compared_rows)

    target = _dataset_frame(service._loader.load(MARKET))
    recipe_map = {item.recipe_id: item for item in (sma, derivative, angle)}
    sma_result = _calculate_recipe(sma, recipe_map, target, {}).result
    dependency_frames = {sma.recipe_id: sma_result.to_frame()}
    expected = {
        derivative.recipe_id: _calculate_recipe(
            derivative, recipe_map, target, dependency_frames
        ).result.to_frame(),
        angle.recipe_id: _calculate_recipe(
            angle, recipe_map, target, dependency_frames
        ).result.to_frame(),
    }
    heads = {
        item.portable_recipe_id: item.artifact_id
        for item in artifacts.list_managed_artifacts(MARKET)
    }
    for recipe_id, frame in expected.items():
        pd.testing.assert_frame_equal(
            artifacts.load_artifact_by_id(MARKET, heads[recipe_id]).frame,
            frame,
        )


def test_database_append_and_explicit_rebuild_preserve_history(tmp_path: Path) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    materialization = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(materialization, "SMA")
    seed = service.create_database_seed(MARKET, "Research database")
    original = service.build_database_revision(seed.seed_id, collection.collection_id)
    original_bytes = service.load_database_revision(
        original.database_id, original.revision_id
    ).values_csv
    _append(historical)
    artifact_plan = service.plan_artifact_collection_update(collection.collection_id)
    service.execute_artifact_collection_update(artifact_plan)

    append_plan = service.plan_database_update(original.database_id)
    assert append_plan.mode == "APPEND"
    appended = service.execute_database_append(append_plan)
    assert appended.database_revision.previous_revision_id == original.revision_id
    assert appended.database_revision.row_count > original.row_count
    assert service.load_database_revision(
        original.database_id, original.revision_id
    ).values_csv == original_bytes

    _publish_modified(historical, rows=104, mutate_row=20)
    assert service.plan_database_update(original.database_id).mode == "BLOCKED"
    rebuild_artifacts = service.plan_artifact_collection_update(collection.collection_id)
    service.execute_artifact_collection_update(rebuild_artifacts)
    rebuild_plan = service.plan_database_update(original.database_id)
    assert rebuild_plan.mode == "REBUILD_REQUIRED"
    with pytest.raises(DataManagerOperationError, match="requires mode APPEND"):
        service.execute_database_append(rebuild_plan)
    rebuilt = service.execute_database_rebuild(rebuild_plan)
    assert rebuilt.database_revision.previous_revision_id == appended.database_revision.revision_id
    assert len(service.list_database_revisions(original.database_id)) == 3


def test_database_truncation_membership_schema_and_prefix_require_rebuild(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    materialization = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(materialization, "SMA")
    seed = service.create_database_seed(MARKET, "Research database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)

    _publish_modified(historical, rows=80)
    service.execute_artifact_collection_update(
        service.plan_artifact_collection_update(collection.collection_id)
    )
    truncated = service.plan_database_update(database.database_id)
    assert truncated.mode == "REBUILD_REQUIRED"

    service.execute_database_rebuild(truncated)
    current_collection = service.load_artifact_collection(collection.collection_id)
    output = current_collection.selected_outputs[0]
    renamed = ArtifactCollectionOutputV1(
        output.logical_artifact_id, output.output_name, "renamed_sma"
    )
    service.revise_artifact_collection(
        collection.collection_id,
        selected_outputs=(renamed,),
        presentation_order=("renamed_sma",),
    )
    schema = service.plan_database_update(database.database_id)
    assert schema.status == "SCHEMA_CHANGED"
    assert schema.mode == "REBUILD_REQUIRED"


def test_database_collection_membership_and_prefix_mismatch_require_rebuild(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    ema_parameters = dict(resolve_parameters("ema", {"period": 3}))
    ema = build_portable_recipe(
        tool_key="ema",
        kind="indicator",
        parameters=ema_parameters,
        output_names=resolve_output_names("ema", ema_parameters),
    )
    materialization = _materialize(service, recipes, sma, ema)
    collection = service.create_artifact_collection(materialization, "Averages")
    seed = service.create_database_seed(MARKET, "Research database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)

    service.revise_artifact_collection(
        collection.collection_id,
        remove_root_logical_artifact_ids=(collection.root_logical_artifact_ids[1],),
    )
    membership = service.plan_database_update(database.database_id)
    assert membership.status == "COLLECTION_CHANGED"
    assert membership.mode == "REBUILD_REQUIRED"

    service.execute_database_rebuild(membership)
    current = service.load_database_revision(database.database_id)
    current_collection = service.load_artifact_collection(collection.collection_id)
    frame = pd.read_csv(io.BytesIO(current.values_csv))
    value_column = frame.columns[-1]
    frame.loc[10, value_column] = float(frame.loc[10, value_column]) + 0.5
    values = frame.to_csv(
        index=False, lineterminator="\n", float_format="%.17g"
    ).encode("utf-8")
    forged = service._updates._database_manifest(
        service.load_database_definition(database.database_id),
        current.manifest,
        current_collection,
        current.manifest.source_ohlcv,
        frame,
        values,
    )
    service.creation_store.publish_database_revision(
        service.load_database_definition(database.database_id),
        forged,
        values,
        expected_head_revision_id=current.manifest.revision_id,
    )
    prefix = service.plan_database_update(database.database_id)
    assert prefix.status == "PREFIX_MISMATCH"
    assert prefix.mode == "REBUILD_REQUIRED"


def test_overlap_mismatch_aborts_before_managed_publication(tmp_path: Path, monkeypatch) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(result, "SMA derivative")
    _append(historical)
    plan = service.plan_artifact_collection_update(collection.collection_id)
    before_heads = {
        item.logical_artifact_id: item.artifact_id
        for item in artifacts.list_managed_artifacts(MARKET)
    }
    before_collection = service.load_artifact_collection(collection.collection_id)
    original = service._updates._require_frames_equal
    overlap_calls = 0

    def reject_second_overlap(left, right, context):
        nonlocal overlap_calls
        if context != "overlap":
            return original(left, right, context)
        overlap_calls += 1
        if overlap_calls == 1:
            return original(left, right, context)
        altered = right.copy()
        value_column = altered.columns[-1]
        row = altered[value_column].first_valid_index()
        assert row is not None
        altered.loc[row, value_column] = float(altered.loc[row, value_column]) + 1.0
        return original(left, altered, context)

    monkeypatch.setattr(
        service._updates, "_require_frames_equal", reject_second_overlap
    )
    with pytest.raises(DataManagerOperationError, match="overlap numeric mismatch"):
        service.execute_artifact_collection_update(plan)
    assert overlap_calls == 2
    assert {
        item.logical_artifact_id: item.artifact_id
        for item in artifacts.list_managed_artifacts(MARKET)
    } == before_heads
    assert service.load_artifact_collection(collection.collection_id) == before_collection
