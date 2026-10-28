from __future__ import annotations

import hashlib
import io
from dataclasses import replace
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


def _revalidate_unchanged(service, market):
    previous = service.capture_accepted_source(market)
    store = service._ohlcv_store
    csv = store.csv_path(market)
    sidecar = store.sidecar_path(market)
    before = csv.read_bytes()
    store.publish_validation(
        market,
        expected_csv_size=csv.stat().st_size,
        expected_csv_mtime_ns=csv.stat().st_mtime_ns,
        expected_csv_sha256=previous.csv_sha256,
        expected_sidecar_size=sidecar.stat().st_size,
        expected_sidecar_mtime_ns=sidecar.stat().st_mtime_ns,
        expected_sidecar_sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest(),
        status="ok", row_count=previous.row_count,
        first_timestamp_ms=previous.first_timestamp_ms,
        last_timestamp_ms=previous.last_timestamp_ms,
        warnings=(f"A1 renewed validation evidence: {previous.sidecar_sha256}",), issue_codes=(),
        error_count=0, warning_count=1, validator="A1-regression",
    )
    current = service.capture_accepted_source(market)
    assert csv.read_bytes() == before
    assert current.csv_sha256 == previous.csv_sha256
    assert current != previous
    return current


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


@pytest.mark.parametrize("multiple", (False, True))
def test_root_update_without_collection_or_recipe_store(tmp_path, multiple):
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    angle = _angle(derivative)
    for recipe in (sma, derivative):
        recipes.save_recipe(recipe)
    materialization = _materialize(service, recipes, angle)
    roots = materialization.root_logical_artifact_ids
    if multiple:
        roots += materialization.support_logical_artifact_ids
    for recipe in (angle, derivative, sma):
        recipes.delete_recipe(recipe.recipe_id)
    _append(historical)
    plan = service.plan_artifact_update(MARKET, roots)
    assert not plan.blocked, plan.blockers
    assert len(plan.nodes) == 3
    assert [n.tool_key for n in plan.nodes] == ["sma", "derivative", "angle"]
    assert all(n.action == "UPDATE" for n in plan.nodes)
    result = service.execute_artifact_update(plan)
    assert len(result.updated_logical_artifact_ids) == 3
    assert len(set(result.materialization.advanced_logical_artifact_ids)) == 3
    assert all(item.status == "CURRENT" for item in result.reconciliation_snapshot.artifacts)
    assert service.plan_artifact_update(MARKET, roots).nodes[-1].action == "REUSE_CURRENT"
    assert all(item.valid for item in artifacts.list_managed_artifacts(MARKET))


@pytest.mark.parametrize("append", (False, True))
def test_root_recreate_restores_head_then_reuses_or_updates(tmp_path, append):
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative)
    support = next(item for item in materialization.managed_artifacts if item.tool_key == "sma")
    head = artifacts._store.head_path(MARKET, support.logical_artifact_id)
    head.unlink()
    recipes.delete_recipe(derivative.recipe_id)
    recipes.delete_recipe(sma.recipe_id)
    if append:
        _append(historical)
    plan = service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids)
    assert not plan.blocked, plan.blockers
    node = next(n for n in plan.nodes if n.tool_key == "sma")
    assert node.action == "RECREATE"
    assert node.reconstruction_artifact_id == support.artifact_id
    result = service.execute_artifact_update(plan)
    assert result.recovered_logical_artifact_ids == (support.logical_artifact_id,)
    assert head.exists()
    if append:
        assert len(result.updated_logical_artifact_ids) == 2
    else:
        assert not result.updated_logical_artifact_ids
        assert len(result.reused_logical_artifact_ids) == 2
        assert not result.materialization.created_version_keys


def test_root_update_braid_roles_shared_inputs_and_stale_plan(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    fast, mid, slow = _sma(3), _sma(5), _sma(9)
    for recipe in (fast, mid, slow):
        recipes.save_recipe(recipe)
    braid = _braid(fast, mid, slow)
    materialization = _materialize(service, recipes, braid, _derivative(fast))
    _append(historical)
    plan = service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids)
    assert not plan.blocked, plan.blockers
    assert len(plan.nodes) == 5
    braid_id = next(n.logical_artifact_id for n in plan.nodes if n.tool_key == "braids")
    assert {edge.role for edge in plan.dependency_edges if edge.dependent_logical_artifact_id == braid_id} == {"fast", "mid", "slow"}
    result = service.execute_artifact_update(plan)
    assert len(result.updated_logical_artifact_ids) == 5
    loaded = artifacts.load_artifact_by_id(MARKET, artifacts.load_artifact_head(MARKET, braid_id).artifact_id)
    heads = {n.logical_artifact_id: artifacts.load_artifact_head(MARKET, n.logical_artifact_id).artifact_id for n in plan.nodes}
    assert {(ref.role, ref.artifact_id, ref.output_name) for ref in loaded.metadata.recipe.source_artifacts} == {
        (edge.role, heads[edge.dependency_logical_artifact_id], edge.output_name)
        for edge in plan.dependency_edges if edge.dependent_logical_artifact_id == braid_id
    }
    with pytest.raises(DataManagerOperationError, match="stale"):
        service.execute_artifact_update(plan)


def test_root_unrecoverable_and_source_stale_refuse_publication(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    roots = materialization.root_logical_artifact_ids
    _append(historical)
    plan = service.plan_artifact_update(MARKET, roots)
    _append(historical, rows=112)
    with pytest.raises(DataManagerOperationError, match="stale"):
        service.execute_artifact_update(plan)
    import shutil
    from leonardo.artifacts._stores import _io_path
    shutil.rmtree(_io_path(artifacts._store.head_path(MARKET, roots[0]).parent))
    blocked = service.plan_artifact_update(MARKET, roots)
    assert blocked.blocked
    with pytest.raises(DataManagerOperationError, match="blocked"):
        service.execute_artifact_update(blocked)


def test_root_update_does_not_advance_artifact_collections(tmp_path):
    service, _artifacts, recipes, historical = _domain(tmp_path)
    first = _materialize(service, recipes, _sma(3))
    collection_a = service.create_artifact_collection(first, "A")
    both = _materialize(service, recipes, _sma(3), _sma(9))
    collection_b = service.create_artifact_collection(both, "B")
    revisions_a = service.list_artifact_collection_revisions(collection_a.collection_id)
    revisions_b = service.list_artifact_collection_revisions(collection_b.collection_id)

    _append(historical)
    plan = service.plan_artifact_update(MARKET, first.root_logical_artifact_ids)
    result = service.execute_artifact_update(plan)

    assert result.updated_logical_artifact_ids == first.root_logical_artifact_ids
    assert result.reconciled_collection_ids == ()
    assert result.awaiting_collection_ids == ()
    assert service.load_artifact_collection(collection_a.collection_id) == collection_a
    assert service.load_artifact_collection(collection_b.collection_id) == collection_b
    assert service.list_artifact_collection_revisions(collection_a.collection_id) == revisions_a
    assert service.list_artifact_collection_revisions(collection_b.collection_id) == revisions_b
    assert {item.status for item in result.reconciliation_snapshot.collections} == {"CURRENT"}

    equivalent = service.create_artifact_collection(
        result.materialization, "Equivalent after Artifact update"
    )
    assert equivalent == collection_a


@pytest.mark.parametrize("missing_head", (False, True))
def test_root_update_cancellation_and_destructive_gate_preserve_evidence(tmp_path, missing_head):
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    logical_id = materialization.root_logical_artifact_ids[0]
    head = artifacts._store.head_path(MARKET, logical_id)
    if missing_head:
        head.unlink()
    _append(historical)
    plan = service.plan_artifact_update(MARKET, (logical_id,))
    before = _tree_bytes(historical)
    with pytest.raises(DataManagerOperationError, match="cancelled"):
        service.execute_artifact_update(plan, cancellation_requested=lambda: True)
    assert _tree_bytes(historical) == before

    def refuse():
        raise DataManagerOperationError("destructive gate refused")

    with pytest.raises(DataManagerOperationError, match="destructive gate refused"):
        service.execute_artifact_update(plan, before_publish=refuse)
    assert _tree_bytes(historical) == before


def _tree_bytes(root):
    from leonardo.artifacts._stores import _io_path
    return {str(path.relative_to(root)): _io_path(path).read_bytes()
            for path in root.rglob("*") if path.is_file()}


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


def test_sidecar_only_evidence_change_reuses_unchanged_artifacts(tmp_path: Path) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, _derivative(sma))
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
    assert service._updates.classify_source_change(previous).status == "UNCHANGED"
    before = {p.relative_to(historical): p.read_bytes() for p in historical.rglob("*") if p.is_file()}
    plan = service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids)
    assert not plan.blocked
    assert all(node.action == "REUSE_CURRENT" for node in plan.nodes)
    assert all(item.status == "CURRENT" for item in service.reconcile_update_status(force=True).artifacts)
    result = service.execute_artifact_update(plan)
    assert result.updated_logical_artifact_ids == ()
    assert result.materialization.created_version_keys == ()
    assert len(result.reused_logical_artifact_ids) == 2
    assert all(item.status == "CURRENT" for item in result.reconciliation_snapshot.artifacts)
    assert {p.relative_to(historical): p.read_bytes() for p in historical.rglob("*") if p.is_file()} == before


def test_truncated_source_blocks_artifact_but_not_historical_collection(tmp_path: Path) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "Truncated source")
    previous = artifacts.capture_accepted_source(MARKET)
    _publish_modified(historical, rows=80)
    change = service._updates.classify_source_change(previous)
    assert change.status == "TRUNCATED"
    assert change.current_through_ms < change.previous_through_ms

    snapshot = service.reconcile_update_status(force=True)
    assert snapshot.artifacts[0].status == "BLOCKED_BY_SOURCE"
    assert snapshot.artifacts[0].reasons == (
        "TRUNCATED: current source coverage is shorter",
    )
    assert snapshot.collections[0].status == "CURRENT"
    validation = service.validate_artifact_collection(collection.collection_id)
    assert validation.valid

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.source_change.status == "UNCHANGED"
    assert collection_plan.execution_stages == ()
    assert collection_plan.nodes == ()


def test_collection_historical_integrity_detects_retained_artifact_corruption(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(
        materialization, "Historical integrity"
    )
    retained = collection.members[0].version_key
    artifact_dir = artifacts._store.find_artifact_dirs(
        MARKET, retained.artifact_id
    )[0]
    values_path = artifact_dir / "values.csv"
    values_path.write_bytes(values_path.read_bytes() + b"\n")

    validation = service.validate_artifact_collection(collection.collection_id)
    assert not validation.valid
    assert any("SHA-256 mismatch" in blocker for blocker in validation.blockers)

    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert plan.blocked
    assert plan.execution_stages == ()
    assert plan.nodes == ()


def test_collection_update_compatibility_is_no_work_and_publishes_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(result, "SMA derivative")
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)
    heads_before = tuple(artifacts.list_managed_artifacts(MARKET))
    _append(historical)

    snapshot = service.reconcile_update_status(force=True)
    assert {item.status for item in snapshot.artifacts} == {"APPEND_AVAILABLE"}
    assert snapshot.collections[0].status == "CURRENT"

    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert plan.execution_stages == ()
    assert plan.nodes == ()
    assert plan.blockers == ()

    def forbidden_publication(*_args, **_kwargs):
        pytest.fail("Collection compatibility execution attempted Artifact publication")

    monkeypatch.setattr(
        artifacts, "publish_managed_artifact_graph", forbidden_publication
    )
    updated = service.execute_artifact_collection_update(
        plan,
        before_publish=lambda: pytest.fail(
            "Collection compatibility execution attempted publication"
        ),
    )

    assert updated.collection_revision == collection
    assert updated.materialization.created_artifact_ids == ()
    assert updated.materialization.created_version_keys == ()
    assert updated.materialization.advanced_logical_artifact_ids == ()
    assert updated.reconciliation_snapshot.collections[0].status == "CURRENT"
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before
    assert tuple(artifacts.list_managed_artifacts(MARKET)) == heads_before


def test_selection_created_collection_compatibility_update_is_no_work(
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
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)

    _append(historical)
    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert plan.execution_stages == ()
    assert plan.nodes == ()
    updated = service.execute_artifact_collection_update(plan)

    assert updated.collection_revision == collection
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before
    assert updated.reconciliation_snapshot.collections[0].status == "CURRENT"


def test_collection_no_work_never_consults_recipe_domain_after_creation(
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
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)
    heads_before = tuple(artifacts.list_managed_artifacts(MARKET))

    recipes.delete_recipe(derivative.recipe_id)
    recipes.delete_recipe(sma.recipe_id)
    for recipe_id in (sma.recipe_id, derivative.recipe_id):
        with pytest.raises(FileNotFoundError):
            recipes.load_recipe(recipe_id)

    def forbidden_recipe_access(*_args, **_kwargs):
        raise AssertionError("Artifact Collection compatibility path consulted Recipe authority")

    monkeypatch.setattr(service._portable_recipes, "load_recipe", forbidden_recipe_access)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden_recipe_access)
    _append(historical)

    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert plan.nodes == ()
    updated = service.execute_artifact_collection_update(plan)

    assert updated.collection_revision == collection
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before
    assert tuple(artifacts.list_managed_artifacts(MARKET)) == heads_before


def test_collection_no_work_is_distinct_from_artifact_update_readiness(
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

    publication_calls = 0

    def reject_publication(*_args, **_kwargs):
        nonlocal publication_calls
        publication_calls += 1
        raise AssertionError("planning reached Artifact publication")

    monkeypatch.setattr(
        artifacts, "publish_managed_artifact_graph", reject_publication
    )
    _append(historical)

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()
    assert service.validate_artifact_collection(collection.collection_id).valid

    artifact_plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
    assert artifact_plan.blocked
    assert any(
        "derivative source roles are invalid" in blocker
        for node in artifact_plan.nodes
        for blocker in node.blockers
    )
    assert publication_calls == 0
    assert service.list_artifact_collection_revisions(
        collection.collection_id
    ) == revisions_before


def test_braid_explicit_artifact_update_preserves_roles_without_collection_advancement(
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
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)
    for recipe in (braid, fast, mid, slow):
        recipes.delete_recipe(recipe.recipe_id)

    def forbidden_recipe_access(*_args, **_kwargs):
        raise AssertionError("explicit Artifact update consulted portable Recipe authority")

    monkeypatch.setattr(service._portable_recipes, "load_recipe", forbidden_recipe_access)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden_recipe_access)
    _append(historical)

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()

    plan = service.plan_artifact_update(MARKET, collection.root_logical_artifact_ids)
    assert not plan.blocked
    braid_node = next(node for node in plan.nodes if node.tool_key == "braids")
    support_nodes = tuple(node for node in plan.nodes if node.tool_key == "sma")
    assert len(support_nodes) == 3
    assert set(braid_node.dependency_logical_artifact_ids) == {
        node.logical_artifact_id for node in support_nodes
    }

    service.execute_artifact_update(plan)
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before

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
    original = artifacts.source_metadata

    def counted(market_id: MarketId):
        calls.append(market_id)
        return original(market_id)

    monkeypatch.setattr(artifacts, "source_metadata", counted)
    monkeypatch.setattr(
        artifacts, "capture_accepted_source",
        lambda _market: pytest.fail("metadata reconciliation invoked strict source capture"),
    )
    snapshot = service.reconcile_update_status(force=True)
    assert len(snapshot.artifacts) == 2
    assert len(snapshot.collections) == 1
    assert len(snapshot.databases) == 1
    assert calls == [MARKET]


def test_source_unavailable_blocks_artifact_but_not_historical_collection(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "Unavailable source")
    artifacts._ohlcv_store.sidecar_path(MARKET).unlink()

    snapshot = service.reconcile_update_status(force=True)
    assert len(snapshot.source_changes) == 1
    assert snapshot.source_changes[0].market_id == MARKET
    assert snapshot.source_changes[0].status == "INVALID_SOURCE"
    assert snapshot.source_changes[0].current_source is None
    assert snapshot.artifacts[0].logical_artifact_id == (
        materialization.managed_artifacts[0].logical_artifact_id
    )
    assert snapshot.artifacts[0].status == "BLOCKED_BY_SOURCE"
    assert snapshot.artifacts[0].reasons[0].startswith("INVALID_SOURCE:")
    assert snapshot.collections[0].status == "CURRENT"
    assert service.validate_artifact_collection(collection.collection_id).valid

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.source_change.status == "UNCHANGED"
    assert collection_plan.nodes == ()


def test_explicit_artifact_update_overlap_matches_complete_calculation_without_collection_advance(
    tmp_path: Path, monkeypatch
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    angle = _angle(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, derivative, angle)
    collection = service.create_artifact_collection(materialization, "SMA transforms")
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)
    _append(historical)

    compared_rows: list[int] = []
    original = service._updates._require_frames_equal

    def record(left, right, context):
        if context == "overlap":
            compared_rows.append(len(left))
        return original(left, right, context)

    monkeypatch.setattr(service._updates, "_require_frames_equal", record)
    service.execute_artifact_update(
        service.plan_artifact_update(MARKET, collection.root_logical_artifact_ids)
    )
    assert len(compared_rows) == 3
    assert all(value >= 1 for value in compared_rows)
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before

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


def test_database_append_waits_for_explicit_artifact_update_and_preserves_history(
    tmp_path: Path, monkeypatch,
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    materialization = _materialize(service, recipes, sma)
    collection = service.create_artifact_collection(materialization, "SMA")
    collection_revisions = service.list_artifact_collection_revisions(
        collection.collection_id
    )
    seed = service.create_database_seed(MARKET, "Research database")
    original = service.build_database_revision(seed.seed_id, collection.collection_id)
    original_bytes = service.load_database_revision(
        original.database_id, original.revision_id
    ).values_csv

    _append(historical)
    waiting = service.plan_database_update(original.database_id)
    assert waiting.mode == "BLOCKED"
    assert waiting.status == "WAITING_FOR_ARTIFACT_UPDATE"
    assert any(node.action == "UPDATE" for node in waiting.prerequisite_nodes)

    service.execute_artifact_update(
        service.plan_artifact_update(
            MARKET, materialization.root_logical_artifact_ids
        )
    )
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert (
        service.list_artifact_collection_revisions(collection.collection_id)
        == collection_revisions
    )

    ready = service.plan_database_update(original.database_id)
    assert ready.mode == "APPEND"
    assert ready.status == "UPDATE_AVAILABLE"
    monkeypatch.setattr(
        service._updates,
        "execute_artifact_update",
        lambda *_args, **_kwargs: pytest.fail("Database append executed Artifact work"),
    )
    monkeypatch.setattr(
        service._creation,
        "load_database_seed",
        lambda *_args, **_kwargs: pytest.fail("Database append loaded its Seed"),
    )
    appended = service.execute_database_append(ready)
    assert appended.database_revision.previous_revision_id == original.revision_id
    assert appended.database_revision.row_count > original.row_count
    appended_bytes = service.load_database_revision(original.database_id).values_csv
    assert appended_bytes.startswith(original_bytes)
    assert service.load_database_revision(
        original.database_id, original.revision_id
    ).values_csv == original_bytes

    revision_count = len(service.list_database_revisions(original.database_id))
    _publish_modified(historical, rows=104, mutate_row=20)
    current = service.plan_database_update(original.database_id)
    assert current.mode == "CURRENT"
    assert current.status == "CURRENT"
    with pytest.raises(DataManagerOperationError, match="rebuild is retired"):
        service.execute_database_rebuild(current)
    assert len(service.list_database_revisions(original.database_id)) == revision_count
    assert service.load_artifact_collection(collection.collection_id) == collection


@pytest.mark.parametrize("gap_offset", (0, 3))
def test_database_append_rejects_boundary_and_interior_gaps_without_publication(
    tmp_path: Path, monkeypatch, gap_offset: int,
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "SMA")
    seed = service.create_database_seed(MARKET, "Research database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    _append(historical)
    service.execute_artifact_update(
        service.plan_artifact_update(
            MARKET, materialization.root_logical_artifact_ids
        )
    )

    summary = service._updates._accepted_summary(MARKET)
    source = artifacts.capture_accepted_source(MARKET)
    assert summary is not None
    lines = summary.csv_path.read_bytes().splitlines(keepends=True)
    suffix_rows = [
        index
        for index, line in enumerate(lines[1:], start=1)
        if int(line.split(b",", 1)[0]) > database.last_timestamp_ms
    ]
    removed = suffix_rows[gap_offset]
    gap_bytes = b"".join(lines[:removed] + lines[removed + 1 :])
    gap_path = tmp_path / f"accepted-gap-{gap_offset}.csv"
    gap_path.write_bytes(gap_bytes)
    digest = hashlib.sha256(gap_bytes).hexdigest()
    gap_source = replace(
        source, csv_sha256=digest, row_count=source.row_count - 1
    )
    gap_summary = replace(
        summary, csv_path=gap_path, file_sha256=digest,
        row_count=summary.row_count - 1,
    )
    monkeypatch.setattr(artifacts, "capture_accepted_source", lambda _market: gap_source)
    monkeypatch.setattr(service._updates, "_accepted_summary", lambda _market: gap_summary)

    before = service.list_database_revisions(database.database_id)
    plan = service.plan_database_update(database.database_id)
    assert plan.mode == "BLOCKED"
    assert plan.status == "SOURCE_INVALID"
    assert "boundary or interior gap" in plan.blockers[0]
    with pytest.raises(DataManagerOperationError, match="requires mode APPEND"):
        service.execute_database_append(plan)
    assert service.list_database_revisions(database.database_id) == before


def test_database_append_stale_plan_and_cancellation_publish_nothing(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "SMA")
    seed = service.create_database_seed(MARKET, "Research database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)

    _append(historical, rows=104)
    service.execute_artifact_update(
        service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids)
    )
    stale_plan = service.plan_database_update(database.database_id)
    assert stale_plan.mode == "APPEND"
    before = service.list_database_revisions(database.database_id)

    _append(historical, rows=105)
    with pytest.raises(DataManagerOperationError, match="plan is stale"):
        service.execute_database_append(stale_plan)
    assert service.list_database_revisions(database.database_id) == before

    service.execute_artifact_update(
        service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids)
    )
    ready = service.plan_database_update(database.database_id)
    assert ready.mode == "APPEND"
    checks = 0

    def cancellation_requested():
        nonlocal checks
        checks += 1
        return checks >= 5

    with pytest.raises(DataManagerOperationError, match="cancelled"):
        service.execute_database_append(
            ready, cancellation_requested=cancellation_requested
        )
    assert checks >= 5
    assert service.list_database_revisions(database.database_id) == before


def test_database_currentness_uses_owned_snapshot_not_live_collection_or_old_source(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
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
    before = service.load_database_revision(database.database_id).values_csv

    service.revise_artifact_collection(
        collection.collection_id,
        remove_root_logical_artifact_ids=(collection.root_logical_artifact_ids[1],),
    )
    collection_changed = service.plan_database_update(database.database_id)
    assert collection_changed.mode == "CURRENT"
    assert collection_changed.status == "CURRENT"

    _publish_modified(historical, rows=96, mutate_row=20)
    historical_changed = service.plan_database_update(database.database_id)
    assert historical_changed.mode == "CURRENT"
    assert historical_changed.status == "CURRENT"
    assert service.load_database_revision(database.database_id).values_csv == before


def test_database_missing_source_blocks_future_work_without_invalidating_snapshot(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "SMA")
    seed = service.create_database_seed(MARKET, "Research database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    stored = service.load_database_revision(database.database_id).values_csv

    artifacts._ohlcv_store.sidecar_path(MARKET).unlink()
    plan = service.plan_database_update(database.database_id)
    assert plan.mode == "BLOCKED"
    assert plan.status == "SOURCE_INVALID"
    assert service.load_database_revision(database.database_id).values_csv == stored

    snapshot = service.reconcile_update_status(force=True)
    currentness = next(
        item for item in snapshot.databases if item.database_id == database.database_id
    )
    assert currentness.status == "SOURCE_INVALID"
    assert currentness.prefix_integrity
    assert service.load_database_revision(database.database_id).values_csv == stored


def test_database_reconciliation_keeps_corrupt_snapshot_visible_invalid(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Corrupt snapshot")
    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Corrupt snapshot")
    )
    values_path = (
        service.creation_store.root_dir
        / "databases"
        / database.database_id
        / "revisions"
        / database.revision_id
        / "values.csv"
    )
    values_path.write_bytes(values_path.read_bytes() + b"\n")

    snapshot = service.reconcile_update_status(force=True)
    assert len(snapshot.databases) == 1
    currentness = snapshot.databases[0]
    assert currentness.database_id == database.database_id
    assert currentness.revision_id == database.revision_id
    assert currentness.status == "CURRENT"
    assert currentness.prefix_integrity
    assert not currentness.reasons
    with pytest.raises(ValueError, match="values hash"):
        service.load_database_revision(database.database_id)


def test_overlap_mismatch_aborts_before_managed_publication(tmp_path: Path, monkeypatch) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(result, "SMA derivative")
    _append(historical)
    plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
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
        service.execute_artifact_update(plan)
    assert overlap_calls == 2
    assert {
        item.logical_artifact_id: item.artifact_id
        for item in artifacts.list_managed_artifacts(MARKET)
    } == before_heads
    assert service.load_artifact_collection(collection.collection_id) == before_collection


def _persistent_bytes(root):
    from leonardo.artifacts.service import _io_path
    safe_root = _io_path(root)
    return {p.relative_to(safe_root).as_posix(): p.read_bytes() for p in safe_root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("missing_evidence", [False, True])

def test_explicit_artifact_recreate_uses_owned_evidence_without_collection_advance(
    tmp_path, monkeypatch, missing_evidence
):
    from leonardo.artifacts import ArtifactNotFoundError

    service, artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    angle = _angle(derivative)
    recipes.save_recipe(sma)
    recipes.save_recipe(derivative)
    result = _materialize(service, recipes, angle)
    collection = service.create_artifact_collection(result, "Recreate support")
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)
    member = next(item for item in collection.members if item.tool_key == "derivative")
    key = member.version_key
    original = artifacts.load_artifact_by_id(MARKET, key.artifact_id)
    artifacts._store.head_path(MARKET, key.logical_artifact_id).unlink()
    with pytest.raises(ArtifactNotFoundError):
        artifacts.load_artifact_head(MARKET, key.logical_artifact_id)
    assert artifacts.load_artifact_version(MARKET, key.logical_artifact_id, key.artifact_id)
    if missing_evidence:
        from leonardo.artifacts.service import _io_path

        _io_path(
            artifacts._store.version_record_path(
                MARKET, key.logical_artifact_id, key.artifact_id
            )
        ).unlink()
    for recipe in (angle, derivative, sma):
        recipes.delete_recipe(recipe.recipe_id)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Recreation planning accessed portable Recipe authority")

    monkeypatch.setattr(service._portable_recipes, "load_recipe", forbidden)
    monkeypatch.setattr(service._recipe_planner, "plan", forbidden)
    before = _persistent_bytes(tmp_path)

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()

    plan = service.plan_artifact_update(MARKET, collection.root_logical_artifact_ids)
    if missing_evidence:
        assert plan.blocked
        assert any("missing or ambiguous managed lineage" in item for item in plan.blockers)
        assert _persistent_bytes(tmp_path) == before
    else:
        node = next(
            item for item in plan.nodes if item.logical_artifact_id == key.logical_artifact_id
        )
        assert node.tool_key == derivative.tool_key
        assert node.portable_recipe_id == derivative.recipe_id
        assert node.action == "RECREATE"
        assert node.current_artifact_id is None
        assert node.reconstruction_artifact_id == key.artifact_id
        assert node.role == "SUPPORT"
        edges = tuple(
            edge
            for edge in collection.dependency_edges
            if edge.dependent_logical_artifact_id == key.logical_artifact_id
        )
        assert {edge.role for edge in edges} == {
            ref.role for ref in original.metadata.recipe.source_artifacts
        }
        assert set(node.dependency_logical_artifact_ids) == {
            edge.dependency_logical_artifact_id for edge in edges
        }
        result = service.execute_artifact_update(plan)
        assert key.logical_artifact_id in result.recovered_logical_artifact_ids
        assert service.load_artifact_collection(collection.collection_id) == collection
        assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before


def test_changed_valid_dependency_head_requires_artifact_update_not_collection_update(tmp_path):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, derivative)
    collection = service.create_artifact_collection(result, "Changed head")
    owner = next(item for item in result.managed_artifacts if item.tool_key == "sma")
    frame = _dataset_frame(service._loader.load(MARKET))
    calculated = _calculate_recipe(sma, {sma.recipe_id: sma}, frame, {}).result
    calculated = type(calculated)(
        tool_key=calculated.tool_key,
        kind=calculated.kind,
        parameters=calculated.parameters,
        bindings=calculated.bindings,
        output_names=calculated.output_names,
        frame=calculated.to_frame(),
        analysis={**calculated.analysis, "publication_note": "second version"},
    )
    prepared = artifacts.prepare_managed_calculation(
        MARKET,
        sma.recipe_id,
        calculated,
        expected_source=collection.source_ohlcv,
        previous_artifact_id=owner.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (prepared,), expected_source=collection.source_ohlcv
    )
    assert prepared.metadata.artifact_id != owner.artifact_id
    before = _persistent_bytes(tmp_path)

    snapshot = service.reconcile_update_status(force=True)
    dependent = next(
        item
        for item in snapshot.artifacts
        if item.portable_recipe_id == derivative.recipe_id
    )
    assert dependent.status == "REBUILD_REQUIRED"
    assert not dependent.direct_staleness
    assert "dependency head" in dependent.reasons[0]
    assert snapshot.collections[0].status == "CURRENT"

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()
    artifact_plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
    assert [item.action for item in artifact_plan.nodes] == ["REUSE_CURRENT", "UPDATE"]
    assert not artifact_plan.blocked
    assert _persistent_bytes(tmp_path) == before


def test_invalid_current_dependency_does_not_invalidate_historical_collection(tmp_path):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, _derivative(sma))
    collection = service.create_artifact_collection(result, "Invalid current dependency")
    owner = next(item for item in result.managed_artifacts if item.tool_key == "sma")
    artifacts._store.head_path(MARKET, owner.logical_artifact_id).write_text(
        "{}", encoding="utf-8"
    )
    before = _persistent_bytes(tmp_path)

    snapshot = service.reconcile_update_status(force=True)
    assert all(
        item.status in {"INVALID", "BLOCKED_BY_DEPENDENCY"}
        for item in snapshot.artifacts
    )
    assert snapshot.collections[0].status == "CURRENT"
    assert service.validate_artifact_collection(collection.collection_id).valid

    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()
    artifact_plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
    assert artifact_plan.blocked
    assert _persistent_bytes(tmp_path) == before


def test_historical_source_mutation_affects_artifact_update_not_collection_lifecycle(tmp_path):
    service, _artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma()
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, _derivative(sma))
    collection = service.create_artifact_collection(result, "Mutation and regression")
    revisions_before = service.list_artifact_collection_revisions(collection.collection_id)

    _publish_modified(historical, rows=96, mutate_row=20)
    before = _persistent_bytes(tmp_path)
    snapshot = service.reconcile_update_status(force=True)
    assert {item.status for item in snapshot.artifacts} == {"HISTORICAL_SOURCE_CHANGED"}
    assert snapshot.collections[0].status == "CURRENT"
    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.nodes == ()
    artifact_plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
    assert not artifact_plan.blocked
    assert _persistent_bytes(tmp_path) == before

    _publish_modified(historical, rows=80)
    snapshot = service.reconcile_update_status(force=True)
    assert {item.status for item in snapshot.artifacts} == {"BLOCKED_BY_SOURCE"}
    assert snapshot.collections[0].status == "CURRENT"
    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.source_change.status == "UNCHANGED"
    assert collection_plan.nodes == ()
    artifact_plan = service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    )
    assert artifact_plan.blocked
    assert all(node.action == "BLOCKED" for node in artifact_plan.nodes)
    assert service.list_artifact_collection_revisions(collection.collection_id) == revisions_before


def test_older_terminal_source_blocks_artifact_but_not_historical_collection(tmp_path, monkeypatch):
    from dataclasses import replace

    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "Older terminal source")
    source = artifacts.capture_accepted_source(MARKET)
    older_terminal = replace(source, last_timestamp_ms=source.last_timestamp_ms - 1)
    monkeypatch.setattr(artifacts, "capture_accepted_source", lambda _market: older_terminal)
    monkeypatch.setattr(artifacts, "source_metadata", lambda _market: older_terminal)

    snapshot = service.reconcile_update_status(force=True)
    assert snapshot.source_changes[0].status == "TRUNCATED"
    assert snapshot.artifacts[0].status == "BLOCKED_BY_SOURCE"
    assert snapshot.artifacts[0].reasons == (
        "TRUNCATED: current source coverage is shorter",
    )
    assert snapshot.collections[0].status == "CURRENT"
    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert plan.source_change.status == "UNCHANGED"
    assert plan.nodes == ()


def test_source_identity_mismatch_blocks_artifact_but_not_historical_collection(tmp_path, monkeypatch):
    from dataclasses import replace

    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "Identity mismatch")
    source = artifacts.capture_accepted_source(MARKET)
    incompatible = replace(
        source, market_id=MarketId("bybit", "linear", "ETHUSDT", "1m")
    )
    original = service._updates._classify_captured_source

    def classify(
        _previous, market, current, summary, cancellation_requested, *, source_error=None, metadata_only=False,
    ):
        return original(
            incompatible,
            market,
            current,
            summary,
            cancellation_requested,
            source_error=source_error,
            metadata_only=metadata_only,
        )

    monkeypatch.setattr(service._updates, "_classify_captured_source", classify)
    snapshot = service.reconcile_update_status(force=True)
    assert snapshot.source_changes[0].status == "IDENTITY_MISMATCH"
    assert snapshot.artifacts[0].status == "BLOCKED_BY_SOURCE"
    assert snapshot.artifacts[0].reasons == (
        "IDENTITY_MISMATCH: previous source MarketId differs from requested MarketId",
    )
    assert snapshot.collections[0].status == "CURRENT"
    plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not plan.blocked
    assert plan.source_change.status == "UNCHANGED"
    assert plan.nodes == ()


def test_later_first_timestamp_is_artifact_work_not_collection_update(tmp_path, monkeypatch):
    from dataclasses import replace

    service, artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma())
    collection = service.create_artifact_collection(materialization, "Later first timestamp")
    source = artifacts.capture_accepted_source(MARKET)
    later_first = replace(source, first_timestamp_ms=source.first_timestamp_ms + 1)
    monkeypatch.setattr(artifacts, "capture_accepted_source", lambda _market: later_first)
    monkeypatch.setattr(artifacts, "source_metadata", lambda _market: later_first)
    change = service._updates._classify_captured_source(
        source,
        MARKET,
        later_first,
        service._updates._accepted_summary(MARKET),
        lambda: False,
    )
    assert change.status == "HISTORICAL_MUTATION"
    snapshot = service.reconcile_update_status(force=True)
    assert snapshot.source_changes[0].status == "HISTORICAL_MUTATION"
    assert snapshot.artifacts[0].status == "HISTORICAL_SOURCE_CHANGED"
    assert snapshot.artifacts[0].status not in {"BLOCKED_BY_SOURCE", "INVALID"}
    assert snapshot.collections[0].status == "CURRENT"
    collection_plan = service.plan_artifact_collection_update(collection.collection_id)
    assert not collection_plan.blocked
    assert collection_plan.source_change.status == "UNCHANGED"
    assert collection_plan.nodes == ()
    assert not service.plan_artifact_update(
        MARKET, collection.root_logical_artifact_ids
    ).blocked



@pytest.mark.parametrize("schema", ("1.0", "2.0", "3.0", "4.0"))
@pytest.mark.parametrize("resolution", ("remove", "recreate"))
def test_a2_missing_provider_resolution_replans_append(tmp_path, schema, resolution):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    from tests.data_manager_test.test_creation_workflow import _leaf

    service, artifacts, recipes, historical = _domain(tmp_path)
    original, collection, roots, before = _a2_snapshot(service, recipes, schema)
    service.delete_artifact_collection(collection.collection_id)
    missing = next(root for root in roots if artifacts.load_artifact_metadata(
        MARKET, artifacts.load_artifact_head(MARKET, root).artifact_id).recipe.tool_key == "bb")
    service.delete_managed_artifact(MARKET, missing)
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    snapshot = service.load_database_revision(original.database_id)
    waiting = service.plan_database_update(original.database_id)
    assert waiting.blocked and waiting.mode == "BLOCKED"
    assert service.load_database_revision(original.database_id) == snapshot
    if resolution == "remove":
        # Unknown V1 attribution cannot exclude a deleted candidate by guessing;
        # all of its unbound outputs may be explicitly removed.
        baseline = service.plan_database_content_edit(original.database_id)
        columns = tuple(o.column_name for o in baseline.selected_outputs
                        if schema == "1.0" or o.logical_artifact_id == missing)
        service.execute_database_content_edit(service.plan_database_content_edit(
            original.database_id, remove_columns=columns))
        if schema != "1.0":
            service.execute_artifact_update(service.plan_artifact_update(MARKET, tuple(r for r in roots if r != missing)))
    else:
        recreated = _materialize(service, recipes, _leaf("bb", {}))
        assert missing in recreated.root_logical_artifact_ids
        service.execute_artifact_update(service.plan_artifact_update(MARKET, roots))
    with pytest.raises(DataManagerOperationError):
        service.execute_database_append(waiting)
    prefix = service.load_database_revision(original.database_id).values_csv
    fresh = service.plan_database_update(original.database_id)
    assert not fresh.blocked and fresh.mode == "APPEND", fresh.blockers
    updated = service.execute_database_append(fresh).database_revision
    assert updated.row_count == 104
    assert service.load_database_revision(original.database_id).values_csv.startswith(prefix)
    assert service.load_database_revision(original.database_id, original.revision_id).values_csv == before
    if schema == "1.0" and resolution == "recreate":
        segments = updated.to_dict()["value_provenance"]["outputs"]
        assert any("legacy_revision_id" in b and "logical_artifact_id" not in b for b in segments)
        assert any("artifact_id" in b and "logical_artifact_id" in b for b in segments)


def test_a2_unbound_append_does_not_guess_from_surviving_candidate(tmp_path):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    service, artifacts, recipes, historical = _domain(tmp_path)
    original, collection, roots, _ = _a2_snapshot(service, recipes)
    service.delete_artifact_collection(collection.collection_id)
    service.delete_managed_artifact(MARKET, roots[0])
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    plan = service.plan_database_update(original.database_id)
    assert plan.blocked and any("unprovable" in reason for reason in plan.blockers)
    state = next(s for s in service.reconcile_update_status(force=True).databases if s.database_id == original.database_id)
    assert state.status != "INVALID"
    assert service.plan_database_content_edit(original.database_id).no_op


@pytest.mark.parametrize("schema", ("1.0", "4.0"))
@pytest.mark.parametrize("delete_removed_provider", (False, True))
def test_second_append_needs_only_already_proved_remaining_provider(
    tmp_path, schema, delete_removed_provider
):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot

    service, artifacts, recipes, historical = _domain(tmp_path)
    original, collection, roots, original_values = _a2_snapshot(service, recipes, schema)
    service.delete_artifact_collection(collection.collection_id)
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, roots))
    first_plan = service.plan_database_update(original.database_id)
    assert not first_plan.blocked, first_plan.blockers
    first = service.execute_database_append(first_plan).database_revision
    exact_sma = [segment for segment in first.to_dict()["value_provenance"]["outputs"]
                 if segment["output_name"] == "sma_3" and "artifact_id" in segment
                 and segment["first_timestamp_ms"] > original.last_timestamp_ms]
    assert len(exact_sma) == 1
    sma_id = exact_sma[0]["logical_artifact_id"]
    bb_id = next(root for root in roots if root != sma_id)
    removal = service.plan_database_content_edit(
        original.database_id,
        remove_columns=tuple(o.column_name for o in first.selected_outputs if o.output_name != "sma_3"),
    )
    service.execute_database_content_edit(removal)
    if delete_removed_provider:
        service.delete_managed_artifact(MARKET, bb_id)
    # Reopen the same temporary stores to prove the provider comes from saved evidence.
    service, artifacts, recipes, historical = _domain(tmp_path, initialize=False)
    prefix = service.load_database_revision(original.database_id).values_csv
    _append(historical, rows=112)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (sma_id,)))
    plan = service.plan_database_update(original.database_id)
    assert not plan.blocked, (
        "SMA provider already proved by exact previous suffix; removed BB has no remaining columns",
        plan.blockers,
    )
    result = service.execute_database_append(plan).database_revision
    assert result.row_count == 112
    assert service.load_database_revision(original.database_id).values_csv.startswith(prefix)
    assert service.load_database_revision(original.database_id, original.revision_id).values_csv == original_values

    if schema == "1.0":
        segments = result.to_dict()["value_provenance"]["outputs"]
        historical_segments = [segment for segment in segments if "legacy_revision_id" in segment]
        assert len(historical_segments) == 1
        assert "logical_artifact_id" not in historical_segments[0]
        assert historical_segments[0]["last_timestamp_ms"] == original.last_timestamp_ms
        assert {segment["logical_artifact_id"] for segment in segments if "artifact_id" in segment} == {sma_id}


@pytest.mark.parametrize("missing", ("provider", "dependency"))
def test_a2_recorded_future_provider_still_requires_current_lineage(tmp_path, monkeypatch, missing):
    from leonardo.artifacts import ArtifactNotFoundError
    from tests.data_manager_test.test_database_content_management import _a2_snapshot

    service, artifacts, recipes, historical = _domain(tmp_path)
    original, collection, roots, original_values = _a2_snapshot(service, recipes, dependent=True)
    service.delete_artifact_collection(collection.collection_id)
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, roots))
    first = service.execute_database_append(service.plan_database_update(original.database_id)).database_revision
    bb_id = next(root for root in roots if artifacts.load_artifact_metadata(
        MARKET, artifacts.load_artifact_head(MARKET, root).artifact_id).recipe.tool_key == "bb")
    provider_id = next(root for root in roots if root != bb_id)
    removals = tuple(o.column_name for o in first.selected_outputs if o.output_name.startswith("bb_"))
    assert len(removals) == 3
    service.execute_database_content_edit(service.plan_database_content_edit(original.database_id, remove_columns=removals))
    service.delete_managed_artifact(MARKET, bb_id)
    _append(historical, rows=112)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (provider_id,)))
    reviewed = service.plan_database_update(original.database_id)
    assert not reviewed.blocked, reviewed.blockers
    before = service.load_database_revision(original.database_id)
    revisions = service.list_database_revisions(original.database_id)
    if missing == "provider":
        service.delete_managed_artifact(MARKET, provider_id)
    else:
        # Supported deletion correctly refuses an in-use dependency. Simulate an
        # unavailable payload at the existing Artifact read boundary instead.
        metadata = artifacts.load_artifact_metadata(MARKET, artifacts.load_artifact_head(MARKET, provider_id).artifact_id)
        dependency_physical = metadata.recipe.source_artifacts[0].artifact_id
        original_load = artifacts.load_artifact_by_id

        def unavailable_dependency(market, artifact_id):
            if artifact_id == dependency_physical:
                raise ArtifactNotFoundError("required dependency payload unavailable")
            return original_load(market, artifact_id)

        monkeypatch.setattr(artifacts, "load_artifact_by_id", unavailable_dependency)
    fresh = service.plan_database_update(original.database_id)
    assert fresh.blocked and fresh.mode == "BLOCKED"
    with pytest.raises(DataManagerOperationError, match="stale"):
        service.execute_database_append(reviewed)
    assert service.load_database_revision(original.database_id) == before
    assert service.list_database_revisions(original.database_id) == revisions
    assert service.load_database_revision(original.database_id, original.revision_id).values_csv == original_values
