from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from leonardo.artifacts import LoadedArtifact
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DataManagerCreationError,
)

from tests.data_manager_test.test_creation_workflow import (
    _advance_same_source,
    _derivative,
    _leaf,
    _materialize,
    _persistence_bytes,
)
from tests.data_manager_test.test_seed_only_database_workflow import _create_seed
from tests.data_manager_test.test_update_workflow import MARKET, _append, _domain


def _seed_database(service):
    seed = _create_seed(service)
    manifest = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Content Database")
    )
    return seed, manifest


def _frame(service, manifest) -> pd.DataFrame:
    loaded = service.load_database_revision(
        manifest.database_id, manifest.revision_id
    )
    from io import BytesIO

    return pd.read_csv(BytesIO(loaded.values_csv))


def test_direct_artifacts_add_all_outputs_and_preserve_dependencies(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    sma = _leaf("sma", {"period": 3})
    recipes.save_recipe(sma)
    derivative = _derivative(sma)
    derivative_result = _materialize(service, recipes, derivative)
    bb_result = _materialize(service, recipes, _leaf("bb", {}))
    roots = (*derivative_result.root_logical_artifact_ids, *bb_result.root_logical_artifact_ids)

    plan = service.plan_database_artifact_addition(database.database_id, roots)

    assert not plan.blocked
    assert len(plan.output_preview_rows) == 4
    assert {item.status for item in plan.output_preview_rows} == {"ADD"}
    assert len(plan.final_dependency_edges) == 1
    dependency = plan.final_dependency_edges[0].dependency_logical_artifact_id
    assert dependency in {item.version_key.logical_artifact_id for item in plan.final_members}
    assert dependency not in {
        item.logical_artifact_id for item in plan.final_selected_outputs
    }
    assert tuple(item.column_name for item in plan.final_selected_outputs) == (
        derivative.output_names[0],
        "bb_middle",
        "bb_upper_band",
        "bb_lower_band",
    )

    artifact_bytes = _persistence_bytes(tmp_path / "historical")
    recipe_bytes = _persistence_bytes(recipes.root_dir)
    published = service.execute_database_content_addition(plan)
    assert isinstance(published, DatabaseRevisionManifestV2)
    assert published.previous_revision_id == database.revision_id
    assert tuple(service.list_database_revisions(database.database_id)) == (
        database,
        published,
    )
    values = _frame(service, published)
    assert tuple(values.columns) == tuple(published.column_mapping)
    assert set(plan.new_columns) <= set(values.columns)
    assert hashlib.sha256(
        service.load_database_revision(
            published.database_id, published.revision_id
        ).values_csv
    ).hexdigest() == published.values_sha256
    assert _persistence_bytes(tmp_path / "historical") == artifact_bytes
    assert _persistence_bytes(recipes.root_dir) == recipe_bytes


def test_duplicate_mixed_and_all_duplicate_plans_publish_only_new_outputs(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    sma_result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    sma_root = sma_result.root_logical_artifact_ids[0]
    first_plan = service.plan_database_artifact_addition(
        database.database_id, (sma_root,)
    )
    first = service.execute_database_content_addition(first_plan)
    assert first is not None

    duplicate = service.plan_database_artifact_addition(first.database_id, (sma_root,))
    assert [item.status for item in duplicate.output_preview_rows] == [
        "ALREADY_INCLUDED"
    ]
    assert not duplicate.has_additions
    assert service.execute_database_content_addition(duplicate) is None
    assert len(service.list_database_revisions(first.database_id)) == 2

    ema_result = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    mixed = service.plan_database_artifact_addition(
        first.database_id,
        (sma_root, ema_result.root_logical_artifact_ids[0]),
    )
    assert [item.status for item in mixed.output_preview_rows] == [
        "ALREADY_INCLUDED",
        "ADD",
    ]
    second = service.execute_database_content_addition(mixed)
    assert second is not None
    assert len(second.selected_outputs) == 2
    assert len(service.list_database_revisions(first.database_id)) == 3


def test_column_collisions_block_without_suffixing(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    result = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 4}),
    )
    selection = service.plan_artifact_collection_selection(
        MARKET, result.root_logical_artifact_ids
    )
    members = {
        item.version_key.logical_artifact_id: item for item in selection.members
    }
    first, second = selection.root_logical_artifact_ids

    base_collision = service._creation.plan_database_content_addition(
        database.database_id,
        selection,
        selected_outputs=(ArtifactCollectionOutputV1(
            first, members[first].output_names[0], "close"
        ),),
        source_kind="artifacts",
    )
    assert base_collision.blocked
    assert base_collision.output_preview_rows[0].status == "BLOCKED_COLLISION"
    assert base_collision.output_preview_rows[0].column_name == "close"

    peer_collision = service._creation.plan_database_content_addition(
        database.database_id,
        selection,
        selected_outputs=(
            ArtifactCollectionOutputV1(first, members[first].output_names[0], "feature"),
            ArtifactCollectionOutputV1(second, members[second].output_names[0], "feature"),
        ),
        source_kind="artifacts",
    )
    assert peer_collision.blocked
    assert {item.status for item in peer_collision.output_preview_rows} == {
        "BLOCKED_COLLISION"
    }
    assert {item.column_name for item in peer_collision.output_preview_rows} == {
        "feature"
    }
    with pytest.raises(DataManagerCreationError, match="blocked"):
        service._creation.execute_database_content_addition(peer_collision)
    assert service.load_database_revision(database.database_id).manifest == database


def test_existing_output_name_collision_blocks_without_revision(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.execute_database_content_addition(
        service.plan_database_artifact_addition(
            database.database_id, sma.root_logical_artifact_ids
        )
    )
    assert first is not None
    ema = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    selection = service.plan_artifact_collection_selection(
        MARKET, ema.root_logical_artifact_ids
    )
    logical_id = selection.root_logical_artifact_ids[0]
    member = next(
        item
        for item in selection.members
        if item.version_key.logical_artifact_id == logical_id
    )

    collision = service._creation.plan_database_content_addition(
        first.database_id,
        selection,
        selected_outputs=(
            ArtifactCollectionOutputV1(
                logical_id,
                member.output_names[0],
                "sma_3",
            ),
        ),
        source_kind="artifacts",
    )

    assert collision.blocked
    assert collision.output_preview_rows[0].status == "BLOCKED_COLLISION"
    assert collision.output_preview_rows[0].column_name == "sma_3"
    with pytest.raises(DataManagerCreationError, match="blocked"):
        service._creation.execute_database_content_addition(collision)
    assert service.load_database_revision(first.database_id).manifest == first
    assert len(service.list_database_revisions(first.database_id)) == 2


def test_collection_addition_pins_revision_and_only_later_explicit_add_imports_new(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    first_result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(first_result, "Features")
    plan = service.plan_database_collection_addition(
        database.database_id, collection.collection_id
    )
    first = service.execute_database_content_addition(plan)
    assert first is not None
    assert first.collection_sources[0].revision_id == collection.revision_id

    second_result = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    revised = service.add_artifact_collection_branches(
        collection.collection_id, second_result
    )
    assert service.load_database_revision(first.database_id).manifest == first
    assert len(first.selected_outputs) == 1

    later = service.plan_database_collection_addition(
        first.database_id, revised.collection_id
    )
    assert [item.status for item in later.output_preview_rows].count("ADD") == 1
    assert [item.status for item in later.output_preview_rows].count(
        "ALREADY_INCLUDED"
    ) == 1
    second = service.execute_database_content_addition(later)
    assert second is not None
    assert len(second.selected_outputs) == 2
    assert tuple(item.revision_id for item in second.collection_sources) == tuple(
        sorted((collection.revision_id, revised.revision_id))
    )


def test_stale_head_source_and_cancellation_publish_nothing(tmp_path: Path) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    ema = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    stale = service.plan_database_artifact_addition(
        database.database_id, sma.root_logical_artifact_ids
    )
    competing = service.plan_database_artifact_addition(
        database.database_id, ema.root_logical_artifact_ids
    )
    service.execute_database_content_addition(competing)
    with pytest.raises(DataManagerCreationError, match="changed after Preview"):
        service.execute_database_content_addition(stale)

    service, _artifacts, recipes, historical = _domain(tmp_path / "source")
    _seed, database = _seed_database(service)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    before = _persistence_bytes(service.creation_store.root_dir)
    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service.execute_database_content_addition(
            plan, cancellation_requested=lambda: True
        )
    assert _persistence_bytes(service.creation_store.root_dir) == before
    _append(historical)
    with pytest.raises(DataManagerCreationError, match="changed after Preview|update required"):
        service.execute_database_content_addition(plan)
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_artifact_head_drift_after_preview_publishes_no_revision(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    plan = service.plan_database_artifact_addition(
        database.database_id, (logical_id,)
    )
    _advance_same_source(service, artifacts, logical_id)

    with pytest.raises(DataManagerCreationError, match="changed after Preview"):
        service.execute_database_content_addition(plan)

    assert service.load_database_revision(database.database_id).manifest == database
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_collection_head_drift_after_preview_publishes_no_revision(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    first = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(first, "Features")
    plan = service.plan_database_collection_addition(
        database.database_id, collection.collection_id
    )
    second = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    revised = service.add_artifact_collection_branches(
        collection.collection_id, second
    )
    assert revised.revision_id != collection.revision_id

    with pytest.raises(DataManagerCreationError, match="changed after Preview"):
        service.execute_database_content_addition(plan)

    assert service.load_database_revision(database.database_id).manifest == database
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_v1_real_addition_transitions_to_v2_without_mutating_v1(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    first_result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(first_result, "Legacy")
    seed = service.create_database_seed(MARKET, "Legacy Database")
    v1 = service.build_database_revision(seed.seed_id, collection.collection_id)
    assert isinstance(v1, DatabaseRevisionManifestV1)
    v1_path = (
        service.creation_store.root_dir
        / "databases"
        / v1.database_id
        / "revisions"
        / v1.revision_id
        / "manifest.json"
    )
    v1_bytes = v1_path.read_bytes()

    duplicate = service.plan_database_artifact_addition(
        v1.database_id, first_result.root_logical_artifact_ids
    )
    assert not duplicate.requires_v1_transition
    assert service.execute_database_content_addition(duplicate) is None
    assert v1_path.read_bytes() == v1_bytes

    second_result = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    plan = service.plan_database_artifact_addition(
        v1.database_id, second_result.root_logical_artifact_ids
    )
    assert plan.requires_v1_transition
    v2 = service.execute_database_content_addition(plan)
    assert isinstance(v2, DatabaseRevisionManifestV2)
    assert v2.previous_revision_id == v1.revision_id
    assert v2.collection_sources[0].collection_id == collection.collection_id
    assert v1_path.read_bytes() == v1_bytes


def test_timestamp_join_warmup_accounting_and_no_fill(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    result = _materialize(service, recipes, _leaf("sma", {"period": 14}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    assert plan.leading_warmup_exclusions > 0
    assert plan.non_leading_missing_rows == 0
    assert plan.new_row_count + plan.leading_warmup_exclusions == plan.old_row_count
    published = service.execute_database_content_addition(plan)
    assert published is not None
    values = _frame(service, published)
    artifact = service._artifacts.load_artifact_by_id(
        MARKET, plan.output_preview_rows[0].artifact_id
    ).frame
    joined = values.merge(
        artifact.loc[:, ["ts_ms", plan.output_preview_rows[0].output_name]],
        on="ts_ms",
        how="left",
        suffixes=("_database", "_artifact"),
    )
    assert len(joined) == len(values)
    assert not values[plan.new_columns[0]].isna().any()


def test_interior_missing_row_is_removed_without_changing_retained_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    before = _frame(service, database)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    baseline_plan = service.plan_database_artifact_addition(
        database.database_id, (logical_id,)
    )
    summary = next(
        item
        for item in artifacts.list_managed_artifacts(MARKET)
        if item.logical_artifact_id == logical_id
    )
    loaded = artifacts.load_artifact_by_id(MARKET, summary.artifact_id)
    artifact_frame = loaded.frame
    output_name = summary.output_names[0]
    missing_index = 24
    missing_timestamp = int(artifact_frame.loc[missing_index, "ts_ms"])
    artifact_frame.loc[missing_index, output_name] = float("nan")
    projected = LoadedArtifact(loaded.metadata, artifact_frame, loaded.analysis)
    original_load = artifacts.load_artifact_by_id

    def load_with_interior_missing(market_id, artifact_id):
        if market_id == MARKET and artifact_id == summary.artifact_id:
            return projected
        return original_load(market_id, artifact_id)

    monkeypatch.setattr(
        artifacts,
        "load_artifact_by_id",
        load_with_interior_missing,
    )
    plan = service.plan_database_artifact_addition(
        database.database_id, (logical_id,)
    )

    assert plan.non_leading_missing_rows == 1
    assert plan.leading_warmup_exclusions == (
        baseline_plan.leading_warmup_exclusions
    )
    published = service.execute_database_content_addition(plan)
    assert published is not None
    values = _frame(service, published)
    assert missing_timestamp not in set(values["ts_ms"])
    assert not values[output_name].isna().any()

    retained = before.loc[
        before["ts_ms"].isin(values["ts_ms"]),
        tuple(before.columns),
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        values.loc[:, tuple(before.columns)].reset_index(drop=True),
        retained,
        check_dtype=False,
    )


def test_zero_usable_rows_blocks_publication(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    result = _materialize(service, recipes, _leaf("sma", {"period": 500}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    assert plan.blocked
    assert plan.new_row_count == 0
    with pytest.raises(DataManagerCreationError, match="no usable rows"):
        service.execute_database_content_addition(plan)
    assert len(service.list_database_revisions(database.database_id)) == 1
