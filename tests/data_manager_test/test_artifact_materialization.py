from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from leonardo.artifacts import (
    ArtifactService,
    ManagedArtifactVersionKey,
    compute_logical_artifact_id,
)
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerApplicationService,
    DataManagerArtifactMaterializationRequest,
    DataManagerOperationError,
    DataManagerService,
)
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeOHLCVInputV1,
    PortableRecipeStore,
    build_portable_recipe,
)
from leonardo.research import (
    AcceptedDatasetCatalog,
    HistoricalDatasetLoader,
    StudyEnvironmentStore,
)

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_portable_recipe_workflow import (
    _braid_instability_entries,
    _peaks_and_utc_entries,
    _save_environment,
)
from leonardo.data_manager.artifact_materialization import (
    _resolve_execution_configuration,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _domain(tmp_path: Path):
    historical_root = tmp_path / "historical"
    market, _frame = _accepted_dataset(historical_root, market=MARKET)
    recipe_store = PortableRecipeStore(
        tmp_path.parent / f"portable-{tmp_path.name[-8:]}"
    )
    artifacts = ArtifactService(historical_root)
    catalog = AcceptedDatasetCatalog(historical_root)
    environments = StudyEnvironmentStore(tmp_path / "study_environments")
    service = DataManagerService(
        catalog,
        HistoricalDatasetLoader(catalog),
        artifacts,
        environments,
        recipe_store,
        PortableRecipeGraphPlanner(recipe_store),
    )
    return market, service, artifacts, recipe_store, historical_root, environments


def _leaf(
    tool_key: str,
    parameters: dict[str, object] | None = None,
    *,
    ohlcv_inputs=(),
):
    resolved = dict(resolve_parameters(tool_key, parameters or {}))
    return build_portable_recipe(
        tool_key=tool_key,
        kind="indicator" if tool_key != "rsi" else "oscillator",
        parameters=resolved,
        output_names=resolve_output_names(tool_key, resolved),
        ohlcv_inputs=ohlcv_inputs,
    )


def _delta(fast, slow):
    parameters = {"eps": 1e-12, "mode": "abs"}
    naming = {
        **parameters,
        "fast": "__research_fast",
        "slow": "__research_slow",
    }
    return build_portable_recipe(
        tool_key="delta",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("delta", naming),
        dependencies=(
            PortableRecipeDependencyV1(
                "fast", fast.recipe_id, fast.output_names[0]
            ),
            PortableRecipeDependencyV1(
                "slow", slow.recipe_id, slow.output_names[0]
            ),
        ),
    )


def _construct(tool_key: str, parameters: dict[str, object], sources):
    selectors = {
        role: f"__research_{role}"
        for role, _recipe in sources
    }
    naming = {**parameters, **selectors}
    return build_portable_recipe(
        tool_key=tool_key,
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names(tool_key, naming),
        dependencies=tuple(
            PortableRecipeDependencyV1(
                role, recipe.recipe_id, recipe.output_names[0]
            )
            for role, recipe in sources
        ),
    )


def _unary_from_output(owner, output_name: str):
    parameters = {"order": 1}
    naming = {**parameters, "source": "__research_source"}
    return build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters=parameters,
        output_names=resolve_output_names("derivative", naming),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", owner.recipe_id, output_name
            ),
        ),
    )


def _utc_recipe(
    peaks=None,
    *,
    roles=None,
    trend_window: int = 5,
    range_window: int = 3,
    outputs_by_role=None,
):
    parameters = dict(
        resolve_parameters(
            "universal_trend_classifier",
            {
                "trend_fractal_window": trend_window,
                "range_fractal_window": range_window,
            },
        )
    )
    parameters.pop("peak_column")
    parameters.pop("trough_column")
    naming = {
        **parameters,
        "peak_column": "peak_fractal_5",
        "trough_column": "trough_fractal_5",
    }
    outputs_by_role = outputs_by_role or {
        "trend_peak": f"peak_fractal_{trend_window}",
        "trend_trough": f"trough_fractal_{trend_window}",
        "range_peak": f"peak_fractal_{range_window}",
        "range_trough": f"trough_fractal_{range_window}",
    }
    selected_roles = tuple(roles or ())
    dependencies = () if peaks is None else tuple(
        PortableRecipeDependencyV1(
            role, peaks.recipe_id, outputs_by_role[role]
        )
        for role in selected_roles
    )
    return build_portable_recipe(
        tool_key="universal_trend_classifier",
        kind="indicator",
        parameters=parameters,
        output_names=resolve_output_names(
            "universal_trend_classifier", naming
        ),
        dependencies=dependencies,
    )


def test_normalized_angle_momentum_recipes_reconstruct_execution_selectors() -> None:
    sma = _leaf("sma", {"period": 14})
    raw = build_portable_recipe(
        tool_key="angle_momentum",
        kind="construct",
        parameters={"n": 3, "source_columns": "close"},
        output_names=("close_ang_mtm_3",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("source_1", "close"),),
    )
    dependent = build_portable_recipe(
        tool_key="angle_momentum",
        kind="construct",
        parameters={"n": 3, "source_columns": "close"},
        output_names=("sma_14_ang_mtm_3",),
        dependencies=(
            PortableRecipeDependencyV1("source_1", sma.recipe_id, "sma_14"),
        ),
    )

    assert dict(raw.parameters) == {"n": 3}
    assert dict(dependent.parameters) == {"n": 3}
    assert _resolve_execution_configuration(raw).parameters["source_columns"] == "close"
    assert (
        _resolve_execution_configuration(dependent).parameters["source_columns"]
        == "__research_source_1"
    )


def test_sma_plan_is_read_only_then_execution_versions_and_reuses(tmp_path: Path) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    versions_root = historical_root / "bybit" / "linear" / "BTCUSDT" / "1m" / "artifact_versions"

    request = DataManagerArtifactMaterializationRequest(
        market, (sma.recipe_id,)
    )
    plan = service.plan_artifact_materialization(request)
    assert not plan.blocked
    assert plan.root_recipe_ids == (sma.recipe_id,)
    assert plan.member_recipe_ids == (sma.recipe_id,)
    assert plan.nodes[0].role == "ROOT"
    assert plan.nodes[0].status == "CREATE"
    assert plan.nodes[0].logical_artifact_id == compute_logical_artifact_id(
        market, sma.recipe_id
    )
    assert not versions_root.exists()

    first = service.execute_artifact_materialization(plan)
    assert len(first.created_artifact_ids) == 1
    assert first.reused_artifact_ids == ()
    assert len(artifacts.list_artifact_versions(
        market, plan.nodes[0].logical_artifact_id
    )) == 1

    second = service.execute_artifact_materialization(plan)
    assert second.created_artifact_ids == ()
    assert second.reused_artifact_ids == first.created_artifact_ids
    assert len(artifacts.list_artifact_versions(
        market, plan.nodes[0].logical_artifact_id
    )) == 1


def test_ordinary_ohlcv_inputs_are_implicit_or_exact_canonical(
    tmp_path: Path,
) -> None:
    (
        market,
        implicit_service,
        implicit_artifacts,
        implicit_recipes,
        _root,
        _environments,
    ) = _domain(tmp_path / "implicit")
    (
        explicit_market,
        explicit_service,
        explicit_artifacts,
        explicit_recipes,
        _explicit_root,
        _explicit_environments,
    ) = _domain(tmp_path / "explicit")
    implicit = _leaf("sma")
    explicit = _leaf(
        "sma",
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    source_open = _leaf(
        "sma",
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("source", "open"),),
    )
    close_open = _leaf(
        "sma",
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "open"),),
    )
    implicit_recipes.save_recipe(implicit)
    for recipe in (explicit, source_open, close_open):
        explicit_recipes.save_recipe(recipe)

    implicit_plan = implicit_service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (implicit.recipe_id,))
    )
    explicit_plan = explicit_service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(
            explicit_market, (explicit.recipe_id,)
        )
    )
    assert not implicit_plan.blocked
    assert not explicit_plan.blocked
    implicit_result = implicit_service.execute_artifact_materialization(
        implicit_plan
    )
    explicit_result = explicit_service.execute_artifact_materialization(
        explicit_plan
    )
    implicit_frame = implicit_artifacts.load_artifact_by_id(
        market, implicit_result.created_artifact_ids[0]
    ).frame
    explicit_frame = explicit_artifacts.load_artifact_by_id(
        explicit_market, explicit_result.created_artifact_ids[0]
    ).frame
    assert tuple(implicit_frame["ts_ms"]) == tuple(explicit_frame["ts_ms"])
    assert tuple(implicit_frame["sma_14"]) == pytest.approx(
        tuple(explicit_frame["sma_14"]), nan_ok=True
    )

    for invalid in (source_open, close_open):
        blocked = explicit_service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(
                explicit_market, (invalid.recipe_id,)
            )
        )
        assert blocked.blocked
        assert any(
            "ordinary Financial Tool OHLCV inputs must be empty or exact "
            "canonical input bindings" in blocker
            for node in blocked.nodes
            for blocker in node.blockers
        )


def test_utc_requires_complete_peaks_troughs_dependency_closure(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes, _root, _environments = _domain(tmp_path)
    peaks = _leaf("peaks_troughs")
    roles = (
        "trend_peak", "trend_trough", "range_peak", "range_trough"
    )
    complete = _utc_recipe(peaks, roles=roles)
    missing = _utc_recipe()
    partial = _utc_recipe(peaks, roles=roles[:2])
    for recipe in (peaks, complete, missing, partial):
        recipes.save_recipe(recipe)

    complete_plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (complete.recipe_id,))
    )
    assert not complete_plan.blocked
    service.execute_artifact_materialization(complete_plan)

    for invalid in (missing, partial):
        blocked = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(
                market, (invalid.recipe_id,)
            )
        )
        assert blocked.blocked
        assert any(
            "UTC requires one complete Peaks & Troughs dependency set"
            in blocker
            for node in blocked.nodes
            for blocker in node.blockers
        )


def test_utc_canonical_range_windows_and_shared_selectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    peaks = _leaf("peaks_troughs")
    roles = ("trend_peak", "trend_trough", "range_peak", "range_trough")
    distinct = _utc_recipe(
        peaks, roles=roles, trend_window=5, range_window=7
    )
    shared = _utc_recipe(
        peaks, roles=roles, trend_window=5, range_window=5
    )
    wrong_range = _utc_recipe(
        peaks,
        roles=roles,
        trend_window=5,
        range_window=7,
        outputs_by_role={
            "trend_peak": "peak_fractal_5",
            "trend_trough": "trough_fractal_5",
            "range_peak": "peak_fractal_3",
            "range_trough": "trough_fractal_3",
        },
    )
    other_peaks = _leaf(
        "peaks_troughs",
        ohlcv_inputs=(
            PortableRecipeOHLCVInputV1("high", "high"),
            PortableRecipeOHLCVInputV1("low", "low"),
        ),
    )
    mixed_owner = build_portable_recipe(
        tool_key="universal_trend_classifier",
        kind="indicator",
        parameters=shared.parameters,
        output_names=shared.output_names,
        dependencies=tuple(
            PortableRecipeDependencyV1(
                role,
                peaks.recipe_id if role.startswith("trend_") else other_peaks.recipe_id,
                "peak_fractal_5" if role.endswith("peak") else "trough_fractal_5",
            )
            for role in roles
        ),
    )
    for recipe in (peaks, distinct, shared, wrong_range, other_peaks, mixed_owner):
        recipes.save_recipe(recipe)

    import leonardo.data_manager.artifact_materialization as materialization

    original = materialization.calculate_financial_tool
    utc_columns: list[tuple[str, ...]] = []

    def capture_columns(tool_key, frame, parameters, *, bindings=None):
        if tool_key == "universal_trend_classifier":
            utc_columns.append(tuple(frame.columns))
        return original(tool_key, frame, parameters, bindings=bindings)

    monkeypatch.setattr(materialization, "calculate_financial_tool", capture_columns)
    for recipe in (distinct, shared):
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (recipe.recipe_id,))
        )
        assert not plan.blocked
        result = service.execute_artifact_materialization(plan)
        logical_id = compute_logical_artifact_id(market, recipe.recipe_id)
        loaded = artifacts.load_artifact_by_id(
            market, artifacts.load_artifact_head(market, logical_id).artifact_id
        )
        refs = loaded.metadata.recipe.source_artifacts
        assert len(refs) == 4
        assert {ref.role for ref in refs} == set(roles)
        assert result.root_logical_artifact_ids == (logical_id,)

    shared_columns = utc_columns[-1]
    assert shared_columns.count("peak_fractal_5") == 1
    assert shared_columns.count("trough_fractal_5") == 1

    for invalid in (wrong_range, mixed_owner):
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (invalid.recipe_id,))
        )
        assert plan.blocked


def test_execution_equivalent_roots_share_one_immutable_artifact(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    implicit = _leaf("sma")
    explicit = _leaf(
        "sma",
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    for recipe in (implicit, explicit):
        recipes.save_recipe(recipe)
    requested = (explicit.recipe_id, implicit.recipe_id)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, requested)
    )

    assert not plan.blocked
    result = service.execute_artifact_materialization(plan)
    semantic_winner = min(requested)
    assert result.root_logical_artifact_ids == (
        compute_logical_artifact_id(market, semantic_winner),
    )
    assert len(result.created_artifact_ids) == 1
    assert result.reused_artifact_ids == ()
    assert len(result.created_version_keys) == 1
    assert result.reused_version_keys == ()
    assert len(artifacts.list_artifacts(market)) == 1
    assert len(artifacts.list_recipes(market)) == 1
    managed = artifacts.list_managed_artifacts(market)
    assert len(managed) == 1
    assert {item.artifact_id for item in managed} == set(result.created_artifact_ids)
    assert all(
        len(artifacts.list_artifact_versions(market, logical_id)) == 1
        for logical_id in result.root_logical_artifact_ids
    )
    shared_artifact_id = result.created_artifact_ids[0]
    assert {
        key.logical_artifact_id for key in result.created_version_keys
    } == set(result.root_logical_artifact_ids)
    assert {
        key.artifact_id for key in result.created_version_keys
    } == {shared_artifact_id}
    assert {
        artifacts.load_artifact_head(market, logical_id).artifact_id
        for logical_id in result.root_logical_artifact_ids
    } == {shared_artifact_id}

    repeated = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, requested)
        )
    )
    assert repeated.created_artifact_ids == ()
    assert repeated.reused_artifact_ids == (shared_artifact_id,)
    assert repeated.created_version_keys == ()
    assert len(repeated.reused_version_keys) == 1
    assert set(repeated.reused_version_keys) == {
        ManagedArtifactVersionKey(logical_id, shared_artifact_id)
        for logical_id in result.root_logical_artifact_ids
    }


def test_materialization_result_rejects_ambiguous_evidence(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes, _root, _environments = _domain(
        tmp_path
    )
    recipe = _leaf("sma")
    recipes.save_recipe(recipe)
    result = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (recipe.recipe_id,))
        )
    )
    artifact_id = result.created_artifact_ids[0]
    key = result.created_version_keys[0]
    with pytest.raises(ValueError, match="created_artifact_ids"):
        replace(result, created_artifact_ids=(artifact_id, artifact_id))
    with pytest.raises(ValueError, match="disjoint"):
        replace(
            result,
            reused_artifact_ids=(artifact_id,),
        )
    with pytest.raises(ValueError, match="created_version_keys"):
        replace(result, created_version_keys=(key, key))
    with pytest.raises(ValueError, match="disjoint"):
        replace(result, reused_version_keys=(key,))
    with pytest.raises(ValueError, match="root_logical_artifact_ids"):
        replace(
            result,
            root_logical_artifact_ids=(
                result.root_logical_artifact_ids[0],
                result.root_logical_artifact_ids[0],
            ),
        )
    unrelated_artifact_id = "d" * 64
    unrelated_logical_id = "e" * 64
    logical_id = result.root_logical_artifact_ids[0]
    with pytest.raises(ValueError, match="Artifact evidence"):
        replace(result, created_artifact_ids=(unrelated_artifact_id,))
    with pytest.raises(ValueError, match="Artifact evidence"):
        replace(
            result,
            created_artifact_ids=(),
            reused_artifact_ids=(unrelated_artifact_id,),
        )
    with pytest.raises(ValueError, match="Artifact evidence"):
        replace(result, created_artifact_ids=())
    with pytest.raises(ValueError, match="version-key evidence"):
        replace(
            result,
            created_version_keys=(
                ManagedArtifactVersionKey(unrelated_logical_id, artifact_id),
            ),
        )
    with pytest.raises(ValueError, match="version-key evidence"):
        replace(
            result,
            created_version_keys=(
                ManagedArtifactVersionKey(logical_id, unrelated_artifact_id),
            ),
        )
    with pytest.raises(ValueError, match="advanced logical"):
        replace(
            result,
            advanced_logical_artifact_ids=(unrelated_logical_id,),
        )
    with pytest.raises(ValueError, match="root and support"):
        replace(result, managed_artifacts=())
    extra = replace(
        result.managed_artifacts[0],
        logical_artifact_id=unrelated_logical_id,
        portable_recipe_id="f" * 64,
        artifact_id=unrelated_artifact_id,
    )
    with pytest.raises(ValueError, match="root and support"):
        replace(result, managed_artifacts=(*result.managed_artifacts, extra))


def test_sequential_execution_reuses_shared_immutable_artifact(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    implicit = _leaf("sma")
    explicit = _leaf(
        "sma",
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    for recipe in (implicit, explicit):
        recipes.save_recipe(recipe)

    first = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (implicit.recipe_id,))
        )
    )
    artifact_id = first.created_artifact_ids[0]
    artifact_dir = artifacts._store.find_artifact_dirs(market, artifact_id)[0]
    metadata_bytes = (artifact_dir / "artifact.meta.json").read_bytes()

    second = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (explicit.recipe_id,))
        )
    )
    assert second.created_artifact_ids == ()
    assert second.reused_artifact_ids == (artifact_id,)
    assert (artifact_dir / "artifact.meta.json").read_bytes() == metadata_bytes
    assert len(artifacts.list_artifacts(market)) == 1
    assert len(artifacts.list_recipes(market)) == 1
    assert artifacts.load_artifact_head(
        market, first.root_logical_artifact_ids[0]
    ).artifact_id == artifact_id
    assert len(
        artifacts.list_artifact_versions(
            market, first.root_logical_artifact_ids[0]
        )
    ) == 1


def test_dependency_output_must_be_numeric_and_analysis_usable(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes, _root, _environments = _domain(tmp_path)
    hck = _leaf("hck")
    hck_numeric = _unary_from_output(hck, "fast_vwap")
    hck_categorical = _unary_from_output(hck, "vwap_color")
    peaks = _leaf("peaks_troughs")
    utc = _utc_recipe(
        peaks,
        roles=(
            "trend_peak", "trend_trough", "range_peak", "range_trough"
        ),
    )
    utc_boolean = _unary_from_output(utc, "horizontal_range")
    utc_numeric = _unary_from_output(utc, "hor_upper")
    for recipe in (
        hck,
        hck_numeric,
        hck_categorical,
        peaks,
        utc,
        utc_boolean,
        utc_numeric,
    ):
        recipes.save_recipe(recipe)

    for accepted in (hck_numeric, utc_numeric):
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(
                market, (accepted.recipe_id,)
            )
        )
        assert not plan.blocked

    for rejected in (hck_categorical, utc_boolean):
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(
                market, (rejected.recipe_id,)
            )
        )
        assert plan.blocked
        assert any(
            "dependency output is not a numeric analysis source" in blocker
            for node in plan.nodes
            for blocker in node.blockers
        )

def test_dependency_graph_calculates_support_before_root_with_exact_lineage(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _historical_root, _environments = _domain(tmp_path)
    ema = _leaf("ema")
    rsi = _leaf("rsi")
    delta = _delta(ema, rsi)
    for recipe in (ema, rsi, delta):
        recipes.save_recipe(recipe)

    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (delta.recipe_id,))
    )
    assert plan.execution_stages == (
        tuple(sorted((ema.recipe_id, rsi.recipe_id))),
        (delta.recipe_id,),
    )
    assert {node.portable_recipe_id for node in plan.nodes if node.role == "SUPPORT"} == {
        ema.recipe_id,
        rsi.recipe_id,
    }
    result = service.execute_artifact_materialization(plan)
    assert len(result.created_artifact_ids) == 3
    assert len(artifacts.list_managed_artifacts(market)) == 3

    by_recipe = {
        entry.portable_recipe_id: entry for entry in result.managed_artifacts
    }
    delta_loaded = artifacts.load_artifact_by_id(
        market, by_recipe[delta.recipe_id].artifact_id
    )
    refs = delta_loaded.metadata.recipe.source_artifacts
    assert {(item.role, item.artifact_id, item.output_name) for item in refs} == {
        ("fast", by_recipe[ema.recipe_id].artifact_id, ema.output_names[0]),
        ("slow", by_recipe[rsi.recipe_id].artifact_id, rsi.output_names[0]),
    }
    assert tuple(delta_loaded.frame.ts_ms) == tuple(
        artifacts.load_artifact_by_id(
            market, by_recipe[ema.recipe_id].artifact_id
        ).frame.ts_ms
    )


def test_derivative_and_trap_area_variants_materialize_full_graphs(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    fast = _leaf("ema", {"period": 10})
    mid = _leaf("ema", {"period": 20})
    slow = _leaf("ema", {"period": 30})
    derivative = _construct("derivative", {"order": 1}, (("source", fast),))
    trap_two = _construct(
        "trap_area", {"zero_eps": 0.0}, (("fast", fast), ("slow", slow))
    )
    trap_three = _construct(
        "trap_area",
        {"zero_eps": 0.0},
        (("fast", fast), ("mid", mid), ("slow", slow)),
    )
    for recipe in (fast, mid, slow, derivative, trap_two, trap_three):
        recipes.save_recipe(recipe)

    for root in (derivative, trap_two, trap_three):
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (root.recipe_id,))
        )
        result = service.execute_artifact_materialization(plan)
        entry = next(
            item for item in result.managed_artifacts
            if item.portable_recipe_id == root.recipe_id
        )
        loaded = artifacts.load_artifact_by_id(market, entry.artifact_id)
        assert loaded.metadata.row_count == plan.source_ohlcv.row_count
        assert loaded.metadata.recipe.output_names == root.output_names
        assert tuple(item.role for item in loaded.metadata.recipe.source_artifacts) == tuple(
            sorted(item.role for item in root.dependencies)
        )


def test_braid_instability_transitive_graph_materializes_shared_dependencies_once(
    tmp_path: Path,
) -> None:
    market, service, artifacts, _recipes, _root, environments = _domain(tmp_path)
    environment = _save_environment(
        environments,
        environment_id="env_materialize_braid",
        display_name="Materialize Braid",
        entries=_braid_instability_entries(),
    )
    persisted = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_instability",),
        create_collection=False,
    )
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(
            market, persisted.root_recipe_ids
        )
    )
    assert len(plan.nodes) == 7
    assert len({item.portable_recipe_id for item in plan.nodes}) == 7
    result = service.execute_artifact_materialization(plan)
    assert len(result.created_artifact_ids) == 7
    assert len(artifacts.list_managed_artifacts(market)) == 7


def test_recipe_derivation_skips_existing_recipe_and_deduplicates_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _market, service, _artifacts, recipes, _root, environments = _domain(tmp_path)
    environment = _save_environment(
        environments,
        environment_id="env_recipe_reuse",
        display_name="Recipe Reuse",
        entries=_braid_instability_entries(),
    )
    initial = service.plan_recipe_derivation(
        environment.environment_id, ("entry_instability",)
    )
    candidate = initial.recipes[0]
    assert candidate.dependencies == ()
    assert candidate.ohlcv_inputs == ()
    existing = build_portable_recipe(
        tool_key=candidate.tool_key,
        tool_version=candidate.tool_version,
        kind=candidate.kind,
        parameters=candidate.parameters,
        output_names=candidate.output_names,
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    assert existing.recipe_id != candidate.recipe_id
    recipes.save_recipe(existing)
    saved_recipe_ids: list[str] = []
    original_persist_recipe = recipes.persist_recipe

    def record_save(recipe, *, origin_kind, origin_details) -> None:
        saved_recipe_ids.append(recipe.recipe_id)
        original_persist_recipe(
            recipe,
            origin_kind=origin_kind,
            origin_details=origin_details,
        )

    monkeypatch.setattr(recipes, "persist_recipe", record_save)

    mixed = service.plan_recipe_derivation(
        environment.environment_id, ("entry_instability",)
    )
    assert dict(mixed.recipe_actions)[existing.recipe_id] == "REUSE EXISTING"
    assert candidate.recipe_id not in {
        recipe.recipe_id for recipe in mixed.recipes
    }
    assert tuple(action for _recipe_id, action in mixed.recipe_actions).count("NEW") == (
        len(mixed.recipes) - 1
    )
    first = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_instability",),
        create_collection=False,
    )

    assert existing.recipe_id in first.reused_recipe_ids
    assert existing.recipe_id not in saved_recipe_ids
    assert set(saved_recipe_ids) == set(first.created_recipe_ids)
    assert len(saved_recipe_ids) == len(mixed.recipes) - 1
    assert len(first.new_provenance_ids) == len(mixed.provenances)
    assert first.existing_provenance_ids == ()

    saved_recipe_ids.clear()
    second = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_instability",),
        create_collection=False,
    )

    assert saved_recipe_ids == []
    assert set(second.reused_recipe_ids) == {
        recipe.recipe_id for recipe in mixed.recipes
    }
    assert second.new_provenance_ids == ()
    assert set(second.existing_provenance_ids) == set(first.new_provenance_ids)
    for recipe in mixed.recipes:
        metadata = recipes.load_persistence_metadata(recipe.recipe_id)
        assert metadata is not None
        assert metadata.first_persisted_at_utc is not None
        assert tuple(item.origin_kind for item in metadata.origins) == (
            "study_environment",
        )


def test_cross_family_braids_and_instability_materialize_with_exact_lineage(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    sma = _leaf("sma", {"period": 3})
    rsi = _leaf("rsi", {"period": 3})
    derivative = _construct("derivative", {"order": 1}, (("source", sma),))
    sources = (("fast", sma), ("mid", rsi), ("slow", derivative))
    braids = _construct("braids", {"tie_policy": "carry"}, sources)
    instability = _construct("braid_instability", {"n": 3}, sources)
    for recipe in (sma, rsi, derivative, braids, instability):
        recipes.save_recipe(recipe)

    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(
            market, (braids.recipe_id, instability.recipe_id)
        )
    )
    assert not plan.blocked
    result = service.execute_artifact_materialization(plan)
    roots = {
        item.portable_recipe_id: item
        for item in result.managed_artifacts
        if item.logical_artifact_id in result.root_logical_artifact_ids
    }
    assert set(roots) == {braids.recipe_id, instability.recipe_id}
    for recipe in (braids, instability):
        loaded = artifacts.load_artifact_by_id(
            market, roots[recipe.recipe_id].artifact_id
        )
        assert tuple(ref.role for ref in loaded.metadata.recipe.source_artifacts) == (
            "fast", "mid", "slow"
        )
        assert {
            ref.output_name for ref in loaded.metadata.recipe.source_artifacts
        } == {sma.output_names[0], rsi.output_names[0], derivative.output_names[0]}
        assert loaded.metadata.source_ohlcv == plan.source_ohlcv


def test_portable_recipe_braid_with_raw_ohlc_sources_remains_blocked(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes, _root, _environments = _domain(tmp_path)
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

    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (braid.recipe_id,))
    )

    assert plan.blocked
    assert any(
        "braids source-family mismatch" in blocker
        for node in plan.nodes
        for blocker in node.blockers
    )


def test_utc_materializes_four_outputs_from_one_peaks_troughs_owner(
    tmp_path: Path,
) -> None:
    market, service, artifacts, _recipes, _root, environments = _domain(tmp_path)
    peaks, utc = _peaks_and_utc_entries()
    environment = _save_environment(
        environments,
        environment_id="env_materialize_utc",
        display_name="Materialize UTC",
        entries=(peaks, utc),
    )
    persisted = service.persist_recipe_derivation(
        environment.environment_id,
        ("entry_utc",),
        create_collection=False,
    )
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(
            market, persisted.root_recipe_ids
        )
    )
    result = service.execute_artifact_materialization(plan)
    assert len(result.created_artifact_ids) == 2
    root = next(
        item for item in result.managed_artifacts
        if item.logical_artifact_id in result.root_logical_artifact_ids
    )
    loaded = artifacts.load_artifact_by_id(market, root.artifact_id)
    refs = loaded.metadata.recipe.source_artifacts
    assert {item.role for item in refs} == {
        "trend_peak", "trend_trough", "range_peak", "range_trough"
    }
    assert len({item.artifact_id for item in refs}) == 1
    assert loaded.metadata.row_count == plan.source_ohlcv.row_count


def test_application_executes_and_records_exact_operation_ids(tmp_path: Path) -> None:
    market, service, _artifacts, recipes, _historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = DataManagerApplicationService(runner, service)
    results: list[TaskResult] = []
    ready = Event()

    def receive(result: TaskResult) -> None:
        results.append(result)
        ready.set()

    runner.start()
    try:
        planning = application.submit_plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,)),
            result_callback=receive,
        )
        assert ready.wait(5.0)
        assert results[-1].status == "completed"
        plan = results[-1].value
        ready.clear()
        execution = application.submit_execute_artifact_materialization(
            plan, result_callback=receive
        )
        assert ready.wait(5.0)
        assert results[-1].status == "completed"
        logical_id = plan.nodes[0].logical_artifact_id
        ready.clear()
        inspection = application.submit_inspect_managed_artifact(
            market, logical_id, result_callback=receive
        )
        assert ready.wait(5.0)
        ready.clear()
        versions = application.submit_list_managed_artifact_versions(
            market, logical_id, result_callback=receive
        )
        assert ready.wait(5.0)
        assert all(item.status == "completed" for item in results)
        assert len({planning.task_id, execution.task_id, inspection.task_id, versions.task_id}) == 4
        operations = {item.metadata.get("operation") for item in manager.snapshots()}
        assert {
            "data_manager.plan_artifact_materialization",
            "data_manager.execute_artifact_materialization",
            "data_manager.inspect_managed_artifact",
            "data_manager.list_managed_artifact_versions",
        }.issubset(operations)
    finally:
        runner.shutdown()


def test_source_change_after_planning_blocks_before_publication(tmp_path: Path) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,))
    )
    _accepted_dataset(historical_root, market=market, rows=97)

    with pytest.raises(DataManagerOperationError, match="source changed"):
        service.execute_artifact_materialization(plan)
    assert artifacts.list_artifacts(market) == ()
    assert artifacts.list_managed_artifacts(market) == ()


def test_reuse_only_execution_rechecks_accepted_source_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    request = DataManagerArtifactMaterializationRequest(
        market, (sma.recipe_id,)
    )
    first_plan = service.plan_artifact_materialization(request)
    first_result = service.execute_artifact_materialization(first_plan)
    reuse_plan = service.plan_artifact_materialization(request)
    assert reuse_plan.nodes[0].status == "REUSE_CURRENT"
    logical_id = reuse_plan.nodes[0].logical_artifact_id
    head_before = artifacts.load_artifact_head(market, logical_id)
    versions_before = artifacts.list_artifact_versions(market, logical_id)
    original_load = service._loader.load

    def load_then_replace(*args, **kwargs):
        loaded = original_load(*args, **kwargs)
        _accepted_dataset(historical_root, market=market, rows=97)
        return loaded

    monkeypatch.setattr(service._loader, "load", load_then_replace)
    with pytest.raises(
        DataManagerOperationError,
        match="accepted OHLCV source changed during reused materialization",
    ):
        service.execute_artifact_materialization(reuse_plan)

    assert artifacts.load_artifact_head(market, logical_id) == head_before
    assert artifacts.list_artifact_versions(market, logical_id) == versions_before
    assert tuple(item.artifact_id for item in versions_before) == (
        first_result.created_artifact_ids[0],
    )


def test_result_preserves_requested_root_order(
    tmp_path: Path,
) -> None:
    market, service, _artifacts, recipes, _root, _environments = _domain(tmp_path)
    roots = (_leaf("sma"), _leaf("ema"))
    for recipe in roots:
        recipes.save_recipe(recipe)
    requested_ids = tuple(
        reversed(sorted(recipe.recipe_id for recipe in roots))
    )
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, requested_ids)
    )
    assert plan.root_recipe_ids == requested_ids

    result = service.execute_artifact_materialization(plan)
    logical_by_recipe = {
        node.portable_recipe_id: node.logical_artifact_id
        for node in plan.nodes
    }
    assert result.root_logical_artifact_ids == tuple(
        logical_by_recipe[recipe_id] for recipe_id in requested_ids
    )
    assert tuple(
        item.portable_recipe_id for item in result.managed_artifacts
    ) == plan.member_recipe_ids


def test_changed_accepted_source_advances_one_immutable_version(tmp_path: Path) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    request = DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,))
    first_plan = service.plan_artifact_materialization(request)
    first = service.execute_artifact_materialization(first_plan)
    first_artifact_id = first.created_artifact_ids[0]

    _accepted_dataset(historical_root, market=market, rows=97)
    second_plan = service.plan_artifact_materialization(request)
    assert second_plan.nodes[0].status == "CREATE"
    assert second_plan.nodes[0].previous_artifact_id == first_artifact_id
    second = service.execute_artifact_materialization(second_plan)
    second_artifact_id = second.created_artifact_ids[0]
    logical_id = second_plan.nodes[0].logical_artifact_id
    history = service.list_managed_artifact_versions(market, logical_id)

    assert second_artifact_id != first_artifact_id
    assert len(history.versions) == 2
    assert history.current.artifact_id == second_artifact_id
    newest = artifacts.load_artifact_version(
        market, logical_id, second_artifact_id
    )
    assert newest.previous_artifact_id == first_artifact_id
    assert artifacts.load_artifact_by_id(market, first_artifact_id).metadata.artifact_id == first_artifact_id


def test_managed_history_survives_recipe_deletion_and_service_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(
        tmp_path
    )
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    result = service.execute_artifact_materialization(
        service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,))
        )
    )
    managed = result.managed_artifacts[0]
    logical_id = managed.logical_artifact_id
    artifact_id = managed.artifact_id
    persisted_versions = artifacts.list_artifact_versions(market, logical_id)

    deleted = service.delete_portable_recipe(sma.recipe_id)
    assert deleted.recipe_id == sma.recipe_id
    assert recipes.list_recipe_summaries() == ()

    history = service.list_managed_artifact_versions(market, logical_id)
    inspection = service.inspect_managed_artifact(market, logical_id)
    assert history == inspection

    def reject_recipe_access(_recipe_id: str):
        raise AssertionError("managed Artifact history consulted Recipe Store")

    monkeypatch.setattr(recipes, "load_recipe", reject_recipe_access)
    history = service.list_managed_artifact_versions(market, logical_id)
    inspection = service.inspect_managed_artifact(market, logical_id)
    assert history == inspection
    assert history.current.logical_artifact_id == logical_id
    assert history.current.artifact_id == artifact_id
    assert history.current.portable_recipe_id == sma.recipe_id
    assert history.versions == persisted_versions
    assert all(
        version.portable_recipe_id == sma.recipe_id
        for version in history.versions
    )
    loaded = artifacts.load_artifact_by_id(market, artifact_id)
    assert len(loaded.frame.index) > 0
    assert loaded.metadata.artifact_id == artifact_id
    assert loaded.metadata.recipe.tool_key == sma.tool_key

    restarted_recipes = PortableRecipeStore(recipes.root_dir)
    restarted_artifacts = ArtifactService(historical_root)
    restarted_catalog = AcceptedDatasetCatalog(historical_root)
    restarted_service = DataManagerService(
        restarted_catalog,
        HistoricalDatasetLoader(restarted_catalog),
        restarted_artifacts,
        StudyEnvironmentStore(tmp_path / "study_environments"),
        restarted_recipes,
        PortableRecipeGraphPlanner(restarted_recipes),
    )
    assert restarted_recipes.list_recipe_summaries() == ()
    monkeypatch.setattr(restarted_recipes, "load_recipe", reject_recipe_access)
    restarted_history = restarted_service.list_managed_artifact_versions(
        market, logical_id
    )
    restarted_inspection = restarted_service.inspect_managed_artifact(
        market, logical_id
    )
    assert restarted_history == restarted_inspection == history
    restarted_loaded = restarted_artifacts.load_artifact_by_id(
        market, artifact_id
    )
    assert len(restarted_loaded.frame.index) > 0
    assert restarted_loaded.metadata == loaded.metadata


def test_later_calculation_failure_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    ema = _leaf("ema")
    rsi = _leaf("rsi")
    delta = _delta(ema, rsi)
    for recipe in (ema, rsi, delta):
        recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (delta.recipe_id,))
    )

    import leonardo.data_manager.service as service_module

    original = service_module._calculate_recipe
    calls = 0

    def fail_later(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("injected later calculation failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service_module, "_calculate_recipe", fail_later)
    with pytest.raises(DataManagerOperationError, match="injected later calculation failure"):
        service.execute_artifact_materialization(plan)
    assert calls == 2
    assert artifacts.list_artifacts(market) == ()
    assert artifacts.list_managed_artifacts(market) == ()
    market_root = historical_root / "bybit" / "linear" / "BTCUSDT" / "1m"
    assert not (market_root / "recipes").exists()
    assert not (market_root / "artifact_versions").exists()


def test_managed_graph_publication_rolls_back_every_new_object(tmp_path: Path) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    ema = _leaf("ema")
    rsi = _leaf("rsi")
    delta = _delta(ema, rsi)
    for recipe in (ema, rsi, delta):
        recipes.save_recipe(recipe)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (delta.recipe_id,))
    )

    artifacts._store._failure_hook = (
        lambda stage: (_ for _ in ()).throw(OSError("injected head failure"))
        if stage == "during_head_publication"
        else None
    )
    with pytest.raises(DataManagerOperationError, match="injected head failure"):
        service.execute_artifact_materialization(plan)
    artifacts._store._failure_hook = None
    assert artifacts.list_artifacts(market) == ()
    assert artifacts.list_recipes(market) == ()
    assert artifacts.list_managed_artifacts(market) == ()
    market_root = historical_root / "bybit" / "linear" / "BTCUSDT" / "1m"
    assert not any(market_root.rglob(".staging-*"))


def test_managed_rollback_failure_reports_original_and_rollback_errors(
    tmp_path: Path,
) -> None:
    market, service, artifacts, recipes, _root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,))
    )

    def fail(stage: str) -> None:
        if stage == "during_head_publication":
            raise OSError("original publication failure")
        if stage == "during_managed_rollback":
            raise OSError("secondary rollback failure")

    artifacts._store._failure_hook = fail
    with pytest.raises(DataManagerOperationError) as captured:
        service.execute_artifact_materialization(plan)
    artifacts._store._failure_hook = None
    assert "original publication failure" in str(captured.value)
    assert "secondary rollback failure" in str(captured.value)


def test_application_cancellation_gate_before_and_after_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, service, artifacts, recipes, historical_root, _environments = _domain(tmp_path)
    sma = _leaf("sma")
    recipes.save_recipe(sma)
    plan = service.plan_artifact_materialization(
        DataManagerArtifactMaterializationRequest(market, (sma.recipe_id,))
    )
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = DataManagerApplicationService(runner, service)
    entered = Event()
    release = Event()
    settled = Event()
    results: list[TaskResult] = []
    original_prepare = artifacts.prepare_managed_calculation

    def blocking_prepare(*args, **kwargs):
        entered.set()
        if not release.wait(5.0):
            raise RuntimeError("pre-publication test release timed out")
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(artifacts, "prepare_managed_calculation", blocking_prepare)
    runner.start()
    try:
        submission = application.submit_execute_artifact_materialization(
            plan,
            result_callback=lambda result: (results.append(result), settled.set()),
        )
        assert entered.wait(5.0)
        assert application.cancel(submission.task_id) is True
        release.set()
        assert settled.wait(5.0)
        assert results[-1].status == "cancelled"
        assert artifacts.list_artifacts(market) == ()
        assert artifacts.list_managed_artifacts(market) == ()
    finally:
        release.set()
        runner.shutdown()

    monkeypatch.setattr(
        artifacts, "prepare_managed_calculation", original_prepare
    )
    publication_entered = Event()
    publication_release = Event()

    def block_after_gate(stage: str) -> None:
        if stage == "before_values_write":
            publication_entered.set()
            if not publication_release.wait(5.0):
                raise RuntimeError("publication test release timed out")

    artifacts._store._failure_hook = block_after_gate
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = DataManagerApplicationService(runner, service)
    settled = Event()
    results.clear()
    runner.start()
    try:
        submission = application.submit_execute_artifact_materialization(
            plan,
            result_callback=lambda result: (results.append(result), settled.set()),
        )
        assert publication_entered.wait(5.0)
        assert application.cancel(submission.task_id) is False
        publication_release.set()
        assert settled.wait(5.0)
        assert results[-1].status == "completed"
        assert len(artifacts.list_managed_artifacts(market)) == 1
    finally:
        artifacts._store._failure_hook = None
        publication_release.set()
        runner.shutdown()


def test_materialization_helper_preserves_architecture_boundaries() -> None:
    path = Path("src/leonardo/data_manager/artifact_materialization.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(name == "PySide6" or name.startswith("PySide6.") for name in imported)
    assert not any(
        name == "leonardo.research" or name.startswith("leonardo.research.")
        for name in imported
    )
    text = path.read_text(encoding="utf-8")
    assert "calculate_financial_tool" in text
    for forbidden in (
        "ArtifactService(",
        "PortableRecipeStore(",
        "CoreRunner(",
        "TaskManager(",
        "ProcessManager",
    ):
        assert forbidden not in text
