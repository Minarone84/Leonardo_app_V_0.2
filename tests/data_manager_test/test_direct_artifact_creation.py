from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from leonardo.artifacts import ArtifactService, ArtifactSourceRefV1
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.data_manager.application import DataManagerApplicationService
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactRequest,
    DataManagerDirectArtifactSource,
    _build_direct_portable_recipe,
)
from leonardo.data_manager.models import DataManagerOperationError
from leonardo.data_manager.service import DataManagerService
from leonardo.financial_tools import calculate_financial_tool, resolve_parameters
from leonardo.recipes import PortableRecipeGraphPlanner, PortableRecipeStore
from leonardo.research import (
    AcceptedDatasetCatalog,
    HistoricalDatasetLoader,
    StudyEnvironmentStore,
)

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


def _domain(tmp_path: Path):
    historical = tmp_path / "historical"
    market, frame = _accepted_dataset(historical)
    artifacts = ArtifactService(historical)
    recipes = PortableRecipeStore(tmp_path / "portable")
    catalog = AcceptedDatasetCatalog(historical)
    service = DataManagerService(
        catalog,
        HistoricalDatasetLoader(catalog),
        artifacts,
        StudyEnvironmentStore(tmp_path / "study_environments"),
        recipes,
        PortableRecipeGraphPlanner(recipes),
    )
    return market, frame, service, artifacts, recipes, historical


def _request(service, market, tool_key, parameters=None, sources=()):
    return DataManagerDirectArtifactRequest(
        market_id=market,
        expected_source_ohlcv=service._artifacts.capture_accepted_source(market),
        tool_key=tool_key,
        parameters=parameters or {},
        sources=tuple(sources),
    )


def _option(service, market, tool_key):
    return next(
        item
        for item in service.build_direct_artifact_catalog(market).construct_options
        if item.tool_key == tool_key
    )


def _source(option, role, output_name=None):
    return DataManagerDirectArtifactSource(
        role,
        option.logical_artifact_id,
        option.artifact_id,
        output_name or option.output_names[0],
    )


def _persistence_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _root_entry(result):
    logical_id = result.materialization.root_logical_artifact_ids[0]
    return next(
        item
        for item in result.materialization.managed_artifacts
        if item.logical_artifact_id == logical_id
    )


def test_direct_base_artifacts_create_no_global_recipes_and_reuse_current(
    tmp_path: Path,
) -> None:
    market, _frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    requests = (
        _request(service, market, "sma", {"period": 3}),
        _request(service, market, "rsi", {"period": 3}),
        _request(service, market, "peaks_troughs"),
    )
    results = tuple(service.create_direct_artifact(request) for request in requests)

    assert recipes.list_recipe_summaries() == ()
    assert all(item.materialization.source_ohlcv == requests[0].expected_source_ohlcv for item in results)
    assert len(artifacts.list_managed_artifacts(market)) == 3
    assert recipes.list_collection_summaries() == ()
    assert service.list_artifact_collections() == ()

    first = results[0]
    second = service.create_direct_artifact(requests[0])
    assert second.portable_recipe_id == first.portable_recipe_id
    assert second.materialization.root_logical_artifact_ids == first.materialization.root_logical_artifact_ids
    assert second.materialization.created_artifact_ids == ()
    assert second.materialization.reused_artifact_ids == first.materialization.created_artifact_ids
    logical_id = first.materialization.root_logical_artifact_ids[0]
    assert len(artifacts.list_artifact_versions(market, logical_id)) == 1
    assert recipes.list_recipe_summaries() == ()


def test_direct_catalog_and_construct_chains_use_only_task_1062_signals(
    tmp_path: Path,
) -> None:
    market, _frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    service.create_direct_artifact(_request(service, market, "sma", {"period": 3}))
    service.create_direct_artifact(_request(service, market, "rsi", {"period": 3}))
    peaks = service.create_direct_artifact(
        _request(service, market, "peaks_troughs")
    )

    catalog = service.build_direct_artifact_catalog(market)
    assert catalog.source_ohlcv == artifacts.capture_accepted_source(market)
    assert {item.kind for item in catalog.construct_options} >= {
        "indicator",
        "oscillator",
    }
    assert "peaks_troughs" not in {item.tool_key for item in catalog.construct_options}
    assert "universal_trend_classifier" not in {item.tool_key for item in catalog.construct_options}
    assert "braids" not in {item.tool_key for item in catalog.construct_options}
    assert len(catalog.utc_peaks_troughs_options) == 1
    assert catalog.utc_peaks_troughs_options[0].logical_artifact_id == peaks.materialization.root_logical_artifact_ids[0]
    assert not any(
        output in {"open", "high", "low", "close", "volume"}
        for option in catalog.construct_options
        for output in option.output_names
    )

    sma = _option(service, market, "sma")
    derivative = service.create_direct_artifact(
        _request(service, market, "derivative", {"order": 1}, (_source(sma, "source"),))
    )
    derivative_option = _option(service, market, "derivative")
    angle = service.create_direct_artifact(
        _request(service, market, "angle", {}, (_source(derivative_option, "source"),))
    )
    loaded_angle = artifacts.load_artifact_by_id(
        market, angle.materialization.managed_artifacts[-1].artifact_id
    )
    assert dict(loaded_angle.metadata.recipe.parameters) == dict(
        resolve_parameters("angle", {})
    )
    assert loaded_angle.metadata.recipe.source_artifacts[0].artifact_id == derivative.materialization.managed_artifacts[-1].artifact_id

    rsi = _option(service, market, "rsi")
    mixed = (
        _source(sma, "fast"),
        _source(rsi, "mid"),
        _source(derivative_option, "slow"),
    )
    braid = service.create_direct_artifact(
        _request(service, market, "braids", {"tie_policy": "carry"}, mixed)
    )
    service.create_direct_artifact(
        _request(service, market, "braid_instability", {"n": 3}, mixed)
    )
    refreshed = service.build_direct_artifact_catalog(market)
    keys = {item.tool_key for item in refreshed.construct_options}
    assert "braids" not in keys
    assert "braid_instability" in keys
    loaded_braid = artifacts.load_artifact_by_id(
        market, _root_entry(braid).artifact_id
    )
    assert {
        ref.role: (ref.artifact_id, ref.output_name)
        for ref in loaded_braid.metadata.recipe.source_artifacts
    } == {
        source.role: (source.artifact_id, source.output_name)
        for source in mixed
    }
    assert recipes.list_recipe_summaries() == ()


def test_construct_catalog_labels_use_persisted_parameter_order_and_values(
    tmp_path: Path,
) -> None:
    market, _frame, service, _artifacts, _recipes, _historical = _domain(tmp_path)
    sma_three = service.create_direct_artifact(
        _request(service, market, "sma", {"period": 3})
    )
    sma_four = service.create_direct_artifact(
        _request(service, market, "sma", {"period": 4})
    )
    bb = service.create_direct_artifact(
        _request(service, market, "bb", {"period": 5, "std": 2.0})
    )

    catalog = service.build_direct_artifact_catalog(market)
    sma_options = tuple(
        option for option in catalog.construct_options if option.tool_key == "sma"
    )
    assert {option.display_name for option in sma_options} == {
        "SMA [period=3]",
        "SMA [period=4]",
    }
    assert {
        option.logical_artifact_id for option in sma_options
    } == {
        sma_three.materialization.root_logical_artifact_ids[0],
        sma_four.materialization.root_logical_artifact_ids[0],
    }
    assert {
        option.artifact_id for option in sma_options
    } == {
        sma_three.materialization.managed_artifacts[-1].artifact_id,
        sma_four.materialization.managed_artifacts[-1].artifact_id,
    }

    bb_option = next(
        option for option in catalog.construct_options if option.tool_key == "bb"
    )
    assert bb_option.display_name == "Bollinger Bands [period=5, std=2]"
    assert bb_option.display_name.index("period=5") < bb_option.display_name.index(
        "std=2"
    )
    assert set(bb_option.output_names) == {
        "bb_middle",
        "bb_upper_band",
        "bb_lower_band",
    }
    assert bb_option.logical_artifact_id == (
        bb.materialization.root_logical_artifact_ids[0]
    )
    assert bb_option.artifact_id == bb.materialization.managed_artifacts[-1].artifact_id
    assert not any(
        output in {"open", "high", "low", "close", "volume"}
        for option in catalog.construct_options
        for output in option.output_names
    )
    assert "peaks_troughs" not in {
        option.tool_key for option in catalog.construct_options
    }


def test_direct_utc_uses_one_exact_current_peaks_troughs_owner(
    tmp_path: Path,
) -> None:
    market, _frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    service.create_direct_artifact(_request(service, market, "peaks_troughs"))
    owner = service.build_direct_artifact_catalog(market).utc_peaks_troughs_options[0]
    outputs = {
        "trend_peak": "peak_fractal_5",
        "trend_trough": "trough_fractal_5",
        "range_peak": "peak_fractal_3",
        "range_trough": "trough_fractal_3",
    }
    request = _request(
        service,
        market,
        "universal_trend_classifier",
        {"trend_fractal_window": 5, "range_fractal_window": 3},
        tuple(_source(owner, role, output) for role, output in outputs.items()),
    )
    result = service.create_direct_artifact(request)
    loaded = artifacts.load_artifact_by_id(
        market, _root_entry(result).artifact_id
    )
    assert loaded.metadata.recipe.tool_key == "universal_trend_classifier"
    assert {
        item.role: item.output_name
        for item in loaded.metadata.recipe.source_artifacts
    } == outputs
    assert {
        item.artifact_id for item in loaded.metadata.recipe.source_artifacts
    } == {owner.artifact_id}
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_rejects_forged_sources_dynamic_binning_and_stale_target(
    tmp_path: Path,
) -> None:
    market, _frame, service, _artifacts, _recipes, historical = _domain(tmp_path)
    service.create_direct_artifact(_request(service, market, "peaks_troughs"))
    peaks = service.build_direct_artifact_catalog(market).utc_peaks_troughs_options[0]
    forged = _request(
        service, market, "angle", {}, (_source(peaks, "source", "peak_fractal_3"),)
    )
    with pytest.raises(DataManagerOperationError, match="Task 1062"):
        service.create_direct_artifact(forged)
    with pytest.raises(ValueError, match="dynamic_binning"):
        _request(service, market, "dynamic_binning", {"source_columns": "close"})

    stale = _request(service, market, "sma", {"period": 3})
    _accepted_dataset(historical, market=market, rows=97)
    with pytest.raises(DataManagerOperationError, match="OHLCV source changed"):
        service.create_direct_artifact(stale)


def test_direct_creation_rejects_stale_managed_source_head(tmp_path: Path) -> None:
    market, frame, service, artifacts, _recipes, _historical = _domain(tmp_path)
    service.create_direct_artifact(_request(service, market, "sma", {"period": 3}))
    option = _option(service, market, "sma")
    request = _request(
        service, market, "angle", {}, (_source(option, "source"),)
    )
    replacement_result = calculate_financial_tool("sma", frame, {"period": 4})
    replacement = artifacts.prepare_managed_calculation(
        market,
        artifacts.list_managed_artifacts(market)[0].portable_recipe_id,
        replacement_result,
        expected_source=artifacts.capture_accepted_source(market),
        previous_artifact_id=option.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,), expected_source=artifacts.capture_accepted_source(market)
    )
    with pytest.raises(DataManagerOperationError, match="head changed"):
        service.create_direct_artifact(request)


def test_direct_creation_cancellation_before_publication_advances_no_head(
    tmp_path: Path,
) -> None:
    market, _frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    request = _request(service, market, "sma", {"period": 3})
    with pytest.raises(RuntimeError, match="cancelled"):
        service._create_direct_artifact(
            request,
            progress=None,
            cancellation_requested=lambda: True,
            before_publish=lambda: None,
        )
    assert artifacts.list_managed_artifacts(market) == ()
    assert recipes.list_recipe_summaries() == ()
    assert _persistence_bytes(recipes.root_dir) == {}


def test_direct_creation_never_consults_global_recipe_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, _frame, service, artifacts, recipes, _historical = _domain(tmp_path)

    def reject_recipe_authority(*_args, **_kwargs):
        raise AssertionError("Direct Artifact creation consulted Recipe authority")

    monkeypatch.setattr(recipes, "save_recipe", reject_recipe_authority)
    monkeypatch.setattr(recipes, "load_recipe", reject_recipe_authority)
    monkeypatch.setattr(service._recipe_planner, "plan", reject_recipe_authority)

    service.create_direct_artifact(
        _request(service, market, "sma", {"period": 3})
    )
    service.create_direct_artifact(
        _request(service, market, "rsi", {"period": 3})
    )
    service.create_direct_artifact(_request(service, market, "peaks_troughs"))
    sma = _option(service, market, "sma")
    derivative = service.create_direct_artifact(
        _request(
            service,
            market,
            "derivative",
            {"order": 1},
            (_source(sma, "source"),),
        )
    )
    derivative_option = _option(service, market, "derivative")
    service.create_direct_artifact(
        _request(
            service,
            market,
            "angle",
            {},
            (_source(derivative_option, "source"),),
        )
    )
    rsi = _option(service, market, "rsi")
    braid_sources = (
        _source(sma, "fast"),
        _source(rsi, "mid"),
        _source(derivative_option, "slow"),
    )
    braid = service.create_direct_artifact(
        _request(
            service,
            market,
            "braids",
            {"tie_policy": "carry"},
            braid_sources,
        )
    )
    service.create_direct_artifact(
        _request(
            service,
            market,
            "braid_instability",
            {"n": 3},
            braid_sources,
        )
    )
    owner = service.build_direct_artifact_catalog(
        market
    ).utc_peaks_troughs_options[0]
    utc_outputs = {
        "trend_peak": "peak_fractal_5",
        "trend_trough": "trough_fractal_5",
        "range_peak": "peak_fractal_3",
        "range_trough": "trough_fractal_3",
    }
    utc = service.create_direct_artifact(
        _request(
            service,
            market,
            "universal_trend_classifier",
            {"trend_fractal_window": 5, "range_fractal_window": 3},
            tuple(
                _source(owner, role, output)
                for role, output in utc_outputs.items()
            ),
        )
    )

    loaded_braid = artifacts.load_artifact_by_id(
        market, _root_entry(braid).artifact_id
    )
    braid_recipe = loaded_braid.metadata.recipe
    assert braid_recipe.tool_key == "braids"
    assert braid_recipe.kind == "construct"
    assert dict(braid_recipe.parameters) == {
        **dict(resolve_parameters("braids", {"tie_policy": "carry"})),
        "fast": "__research_fast",
        "mid": "__research_mid",
        "slow": "__research_slow",
    }
    assert dict(braid_recipe.bindings) == {}
    assert braid_recipe.output_names
    assert {
        ref.role: (ref.artifact_id, ref.output_name)
        for ref in braid_recipe.source_artifacts
    } == {
        source.role: (source.artifact_id, source.output_name)
        for source in braid_sources
    }
    loaded_utc = artifacts.load_artifact_by_id(
        market, _root_entry(utc).artifact_id
    )
    assert {
        ref.role: (ref.artifact_id, ref.output_name)
        for ref in loaded_utc.metadata.recipe.source_artifacts
    } == {
        role: (owner.artifact_id, output)
        for role, output in utc_outputs.items()
    }
    assert _root_entry(derivative).portable_recipe_id == derivative.portable_recipe_id
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_preserves_global_recipe_persistence_bytes(
    tmp_path: Path,
) -> None:
    market, _frame, service, _artifacts, recipes, _historical = _domain(tmp_path)
    matching_request = _request(service, market, "sma", {"period": 3})
    matching_recipe = _build_direct_portable_recipe(matching_request, {})
    recipes.save_recipe(matching_recipe)
    before = _persistence_bytes(recipes.root_dir)

    matching = service.create_direct_artifact(matching_request)
    service.create_direct_artifact(
        _request(service, market, "rsi", {"period": 3})
    )

    assert matching.portable_recipe_id == matching_recipe.recipe_id
    assert _persistence_bytes(recipes.root_dir) == before
    assert tuple(
        item.recipe_id for item in recipes.list_recipe_summaries()
    ) == (matching_recipe.recipe_id,)
    assert recipes.list_collection_summaries() == ()


def test_direct_creation_recalculates_stale_artifact_support_from_metadata(
    tmp_path: Path,
) -> None:
    market, frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    service.create_direct_artifact(
        _request(service, market, "sma", {"period": 3})
    )
    sma = _option(service, market, "sma")
    service.create_direct_artifact(
        _request(
            service,
            market,
            "derivative",
            {"order": 1},
            (_source(sma, "source"),),
        )
    )
    derivative = _option(service, market, "derivative")
    sma_summary = next(
        item
        for item in artifacts.list_managed_artifacts(market)
        if item.logical_artifact_id == sma.logical_artifact_id
    )
    changed_frame = frame.copy(deep=True)
    changed_frame.loc[changed_frame.index[-1], "close"] += 1.0
    replacement = artifacts.prepare_managed_calculation(
        market,
        sma_summary.portable_recipe_id,
        calculate_financial_tool("sma", changed_frame, {"period": 3}),
        expected_source=artifacts.capture_accepted_source(market),
        previous_artifact_id=sma.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,),
        expected_source=artifacts.capture_accepted_source(market),
    )

    angle = service.create_direct_artifact(
        _request(
            service,
            market,
            "angle",
            {},
            (_source(derivative, "source"),),
        )
    )

    derivative_versions = artifacts.list_artifact_versions(
        market, derivative.logical_artifact_id
    )
    assert len(derivative_versions) == 2
    refreshed_derivative = artifacts.load_artifact_by_id(
        market, derivative_versions[-1].artifact_id
    )
    assert refreshed_derivative.metadata.recipe.source_artifacts[0].artifact_id == (
        replacement.metadata.artifact_id
    )
    assert derivative.logical_artifact_id in (
        angle.materialization.advanced_logical_artifact_ids
    )
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_rejects_managed_semantic_lineage_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, frame, service, artifacts, recipes, _historical = _domain(tmp_path)
    service.create_direct_artifact(
        _request(service, market, "bb", {"period": 5, "std": 2})
    )
    bb = _option(service, market, "bb")
    service.create_direct_artifact(
        _request(
            service,
            market,
            "derivative",
            {"order": 1},
            (_source(bb, "source", "bb_middle"),),
        )
    )
    derivative = _option(service, market, "derivative")
    bb_summary = next(
        item
        for item in artifacts.list_managed_artifacts(market)
        if item.logical_artifact_id == bb.logical_artifact_id
    )
    replacement = artifacts.prepare_managed_calculation(
        market,
        bb_summary.portable_recipe_id,
        calculate_financial_tool("bb", frame, {"period": 6, "std": 2}),
        expected_source=artifacts.capture_accepted_source(market),
        previous_artifact_id=bb.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,),
        expected_source=artifacts.capture_accepted_source(market),
    )
    bb_versions_before = artifacts.list_artifact_versions(
        market, bb.logical_artifact_id
    )
    derivative_versions_before = artifacts.list_artifact_versions(
        market, derivative.logical_artifact_id
    )

    def reject_recipe_authority(*_args, **_kwargs):
        raise AssertionError("Direct Artifact creation consulted Recipe authority")

    monkeypatch.setattr(recipes, "save_recipe", reject_recipe_authority)
    monkeypatch.setattr(recipes, "load_recipe", reject_recipe_authority)
    monkeypatch.setattr(service._recipe_planner, "plan", reject_recipe_authority)

    with pytest.raises(
        DataManagerOperationError,
        match="managed Artifact lineage changes semantic calculation identity",
    ):
        service.create_direct_artifact(
            _request(
                service,
                market,
                "angle",
                {},
                (_source(derivative, "source"),),
            )
        )

    assert artifacts.list_artifact_versions(
        market, bb.logical_artifact_id
    ) == bb_versions_before
    assert artifacts.list_artifact_versions(
        market, derivative.logical_artifact_id
    ) == derivative_versions_before
    assert not any(
        item.tool_key == "angle"
        for item in artifacts.list_managed_artifacts(market)
    )
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_rejects_semantically_stable_malformed_support(
    tmp_path: Path,
) -> None:
    market, frame, service, artifacts, recipes, historical = _domain(tmp_path)
    sma_result = service.create_direct_artifact(
        _request(service, market, "sma", {"period": 3})
    )
    sma = _root_entry(sma_result)
    sma_loaded = artifacts.load_artifact_by_id(market, sma.artifact_id)
    source = artifacts.capture_accepted_source(market)
    malformed = artifacts.prepare_managed_calculation(
        market,
        "f" * 64,
        calculate_financial_tool(
            "derivative",
            frame,
            {"order": 1},
            bindings={"source": "close"},
        ),
        expected_source=source,
        source_artifacts=(
            ArtifactSourceRefV1(
                "fast", sma.artifact_id, sma.output_names[0]
            ),
        ),
        source_metadata=(sma_loaded.metadata,),
    )
    publication = artifacts.publish_managed_artifact_graph(
        (malformed,), expected_source=source
    )
    malformed_summary = publication.managed_artifacts[0]
    persistence_before = _persistence_bytes(historical)

    with pytest.raises(
        DataManagerOperationError, match="derivative source roles are invalid"
    ):
        service.create_direct_artifact(
            _request(
                service,
                market,
                "angle",
                {},
                (
                    DataManagerDirectArtifactSource(
                        "source",
                        malformed_summary.logical_artifact_id,
                        malformed_summary.artifact_id,
                        malformed_summary.output_names[0],
                    ),
                ),
            )
        )

    assert _persistence_bytes(historical) == persistence_before
    assert not any(
        item.tool_key == "angle"
        for item in artifacts.list_managed_artifacts(market)
    )
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_rejects_existing_root_semantic_lineage_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, frame, service, artifacts, recipes, historical = _domain(tmp_path)
    first = service.create_direct_artifact(
        _request(service, market, "bb", {"period": 5, "std": 2})
    )
    root = _root_entry(first)
    replacement = artifacts.prepare_managed_calculation(
        market,
        root.portable_recipe_id,
        calculate_financial_tool("bb", frame, {"period": 6, "std": 2}),
        expected_source=artifacts.capture_accepted_source(market),
        previous_artifact_id=root.artifact_id,
    )
    artifacts.publish_managed_artifact_graph(
        (replacement,),
        expected_source=artifacts.capture_accepted_source(market),
    )
    versions_before = artifacts.list_artifact_versions(
        market, root.logical_artifact_id
    )
    assert len(versions_before) == 2
    _accepted_dataset(historical, market=market, rows=97)
    persistence_before = _persistence_bytes(historical)

    def reject_recipe_authority(*_args, **_kwargs):
        raise AssertionError("Direct Artifact creation consulted Recipe authority")

    monkeypatch.setattr(recipes, "save_recipe", reject_recipe_authority)
    monkeypatch.setattr(recipes, "load_recipe", reject_recipe_authority)
    monkeypatch.setattr(service._recipe_planner, "plan", reject_recipe_authority)

    with pytest.raises(
        DataManagerOperationError,
        match="managed Artifact lineage changes semantic calculation identity",
    ):
        service.create_direct_artifact(
            _request(service, market, "bb", {"period": 5, "std": 2})
        )

    assert artifacts.list_artifact_versions(
        market, root.logical_artifact_id
    ) == versions_before
    assert _persistence_bytes(historical) == persistence_before
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_rejects_first_root_version_with_wrong_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, frame, service, artifacts, recipes, historical = _domain(tmp_path)
    request = _request(service, market, "bb", {"period": 5, "std": 2})
    transient_recipe = _build_direct_portable_recipe(request, {})
    candidate = artifacts.prepare_managed_calculation(
        market,
        transient_recipe.recipe_id,
        calculate_financial_tool("bb", frame, {"period": 6, "std": 2}),
        expected_source=artifacts.capture_accepted_source(market),
    )
    artifacts.publish_managed_artifact_graph(
        (candidate,),
        expected_source=artifacts.capture_accepted_source(market),
    )
    summary = artifacts.list_managed_artifacts(market)[0]
    versions_before = artifacts.list_artifact_versions(
        market, summary.logical_artifact_id
    )
    assert len(versions_before) == 1
    assert summary.portable_recipe_id == transient_recipe.recipe_id
    assert artifacts.load_artifact_by_id(
        market, versions_before[0].artifact_id
    ).metadata.recipe.parameters["period"] == 6
    persistence_before = _persistence_bytes(historical)

    def reject_recipe_authority(*_args, **_kwargs):
        raise AssertionError("Direct Artifact creation consulted Recipe authority")

    monkeypatch.setattr(recipes, "save_recipe", reject_recipe_authority)
    monkeypatch.setattr(recipes, "load_recipe", reject_recipe_authority)
    monkeypatch.setattr(service._recipe_planner, "plan", reject_recipe_authority)

    with pytest.raises(
        DataManagerOperationError,
        match=(
            "managed Artifact semantic identity disagrees with "
            "requested calculation"
        ),
    ):
        service.create_direct_artifact(request)

    versions_after = artifacts.list_artifact_versions(
        market, summary.logical_artifact_id
    )
    assert versions_after == versions_before
    assert artifacts.load_artifact_by_id(
        market, versions_after[0].artifact_id
    ).metadata.recipe.parameters["period"] == 6
    assert _persistence_bytes(historical) == persistence_before
    assert recipes.list_recipe_summaries() == ()


def test_direct_creation_advances_existing_semantically_stable_root(
    tmp_path: Path,
) -> None:
    market, _frame, service, artifacts, recipes, historical = _domain(tmp_path)
    first = service.create_direct_artifact(
        _request(service, market, "bb", {"period": 5, "std": 2})
    )
    first_root = _root_entry(first)
    _accepted_dataset(historical, market=market, rows=97)
    current_source = artifacts.capture_accepted_source(market)

    second = service.create_direct_artifact(
        _request(service, market, "bb", {"period": 5, "std": 2})
    )
    second_root = _root_entry(second)
    versions = artifacts.list_artifact_versions(
        market, first_root.logical_artifact_id
    )
    first_loaded = artifacts.load_artifact_by_id(market, first_root.artifact_id)
    second_loaded = artifacts.load_artifact_by_id(market, second_root.artifact_id)

    assert second.portable_recipe_id == first.portable_recipe_id
    assert second_root.logical_artifact_id == first_root.logical_artifact_id
    assert second_root.artifact_id != first_root.artifact_id
    assert len(versions) == 2
    assert {
        item.artifact_id for item in versions
    } == {first_root.artifact_id, second_root.artifact_id}
    assert first_loaded.metadata.recipe.parameters["period"] == 5
    assert second_loaded.metadata.recipe.parameters["period"] == 5
    assert second_loaded.metadata.source_ohlcv == current_source
    assert recipes.list_recipe_summaries() == ()


def test_direct_application_operations_run_through_core_with_progress(
    tmp_path: Path,
) -> None:
    market, _frame, service, _artifacts, _recipes, _historical = _domain(tmp_path)
    manager = TaskManager()
    runner = CoreRunner(manager)
    application = DataManagerApplicationService(runner, service)
    results: list[TaskResult] = []
    progress = []
    ready = Event()
    runner.start()
    try:
        application.submit_build_direct_artifact_catalog(
            market,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert ready.wait(3.0)
        assert results[-1].status == "completed"
        ready.clear()
        application.submit_create_direct_artifact(
            _request(service, market, "sma", {"period": 3}),
            progress_callback=progress.append,
            result_callback=lambda result: (results.append(result), ready.set()),
        )
        assert ready.wait(5.0)
        assert results[-1].status == "completed"
        assert progress
        operations = {item.metadata.get("operation") for item in manager.snapshots()}
        assert "data_manager.build_direct_artifact_catalog" in operations
        assert "data_manager.create_direct_artifact" in operations
    finally:
        runner.shutdown()
