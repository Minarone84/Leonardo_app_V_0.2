from __future__ import annotations

import pandas as pd
import pytest

from leonardo.data_manager import DataManagerArtifactMaterializationRequest
from leonardo.research import ResearchStudyService
from leonardo.research.study_projection import project_study

from tests.data_manager_test.test_direct_artifact_creation import _request
from tests.data_manager_test.test_nan_database_composition import (
    _assert_database, _compose, _source_hashes,
)
from tests.data_manager_test.test_portable_recipe_workflow import _save_environment
from tests.data_manager_test.test_update_workflow import MARKET, _domain
from tests.research_test.test_study_artifact_apply_save import _save_attempt
from tests.research_test.test_study_execution import prepare
from tests.research_test.test_study_projection import resident


def _artifact_frames(artifacts, materialization, timestamps):
    frames = {}
    for member in materialization.managed_artifacts:
        loaded = artifacts.load_artifact_by_id(MARKET, member.artifact_id)
        assert tuple(loaded.frame.ts_ms) == timestamps
        assert loaded.metadata.source_ohlcv == materialization.source_ohlcv
        frames[member.logical_artifact_id] = loaded.frame
    return frames


@pytest.mark.parametrize("collection_route", (False, True))
def test_saved_environment_recipe_routes_retain_full_axis_and_dependencies(tmp_path, collection_route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    before = _source_hashes(historical)
    dataset = service._loader.load(MARKET)
    environment = _save_environment(service._study_environments, market=MARKET)
    assert service._study_environments.load(environment.environment_id) == environment
    roots = ("entry_003",) if collection_route else ("entry_002",)
    derived = service.persist_recipe_derivation(
        environment.environment_id, roots, create_collection=collection_route,
        collection_display_name="Environment dependency graph" if collection_route else "",
    )
    request = (
        DataManagerArtifactMaterializationRequest(
            MARKET, recipe_collection_id=derived.collection_id,
            recipe_collection_revision_id=derived.revision_id,
        ) if collection_route else DataManagerArtifactMaterializationRequest(MARKET, derived.root_recipe_ids)
    )
    plan = service.plan_artifact_materialization(request)
    assert not plan.blocked, plan.blockers
    stage_by_recipe = {recipe_id: index for index, stage in enumerate(plan.execution_stages) for recipe_id in stage}
    for recipe_id in plan.member_recipe_ids:
        for dependency in recipes.load_recipe(recipe_id).dependencies:
            assert stage_by_recipe[dependency.recipe_id] < stage_by_recipe[recipe_id]
    materialization = service.execute_artifact_materialization(plan)
    assert materialization.source_ohlcv == artifacts.capture_accepted_source(MARKET)
    frames = _artifact_frames(artifacts, materialization, dataset.ts_ms)
    assert any(frame.iloc[:, 1:].isna().any().any() for frame in frames.values())
    seed = service.create_database_seed(MARKET, "Environment full Seed")
    assert seed.row_count == dataset.row_count == 96
    if collection_route:
        collection = service.create_artifact_collection(
            materialization, "Environment outputs",
            source_recipe_collection_id=derived.collection_id,
            source_recipe_collection_revision_id=derived.revision_id,
        )
        assert collection.source_recipe_collection_id == derived.collection_id
        assert collection.dependency_edges
        manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
        assert manifest.dependency_edges == collection.dependency_edges
        assert manifest.members == collection.members
        assert {(item.collection_id, item.revision_id) for item in manifest.collection_sources} == {
            (collection.collection_id, collection.revision_id)
        }
    else:
        manifest = _compose(service, seed, materialization.root_logical_artifact_ids, "individual")
    _assert_database(service, seed, manifest, frames)
    assert _source_hashes(historical) == before


@pytest.mark.parametrize("origin", ("research", "direct_dms"))
@pytest.mark.parametrize("route", ("individual", "build"))
def test_research_and_direct_artifacts_reach_database_on_same_accepted_source(tmp_path, origin, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    dataset = service._loader.load(MARKET)
    source = artifacts.capture_accepted_source(MARKET)
    before = _source_hashes(historical)
    if origin == "research":
        research = ResearchStudyService(artifacts, recipes)
        study = prepare(research, dataset, "sma", parameters={"period": 3})
        full_result = study.result.to_frame()
        projection = project_study(study, resident(dataset, 40, 46))
        assert projection.ts_ms == dataset.ts_ms[40:46]
        assert len(projection.ts_ms) == 6
        pd.testing.assert_frame_equal(study.result.to_frame(), full_result)
        saved = research.save_study(_save_attempt(study), dataset, study, (study,))
        loaded = artifacts.load_artifact_by_id(MARKET, saved.saved_link.artifact_id)
        pd.testing.assert_frame_equal(loaded.frame, full_result)
        assert loaded.metadata.source_ohlcv == source
        assert tuple(loaded.frame.ts_ms) == dataset.ts_ms
        assert loaded.frame.sma_3.isna().tolist() == [True, True] + [False] * 94
        portable_recipes = recipes.list_recipe_summaries()
        assert len(portable_recipes) == 1
        plan = service.plan_artifact_materialization(
            DataManagerArtifactMaterializationRequest(MARKET, (portable_recipes[0].recipe_id,))
        )
        assert not plan.blocked, plan.blockers
        materialization = service.execute_artifact_materialization(plan)
        assert saved.saved_link.artifact_id in materialization.reused_artifact_ids
    else:
        result = service.create_direct_artifact(_request(service, MARKET, "sma", {"period": 3}))
        materialization = result.materialization
    assert materialization.source_ohlcv == source
    frames = _artifact_frames(artifacts, materialization, dataset.ts_ms)
    for frame in frames.values():
        assert frame.sma_3.isna().tolist() == [True, True] + [False] * 94
    seed = service.create_database_seed(MARKET, "Same-source full Seed")
    assert seed.source_ohlcv == source and seed.row_count == 96
    manifest = _compose(service, seed, materialization.root_logical_artifact_ids, route)
    _assert_database(service, seed, manifest, frames)
    assert _source_hashes(historical) == before
