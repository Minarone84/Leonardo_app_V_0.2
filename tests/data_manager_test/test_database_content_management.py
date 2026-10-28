from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
import shutil

import pandas as pd
import pytest

from leonardo.artifacts import LoadedArtifact
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    DatabaseRevisionManifestV2,
    DatabaseRevisionManifestV3,
    DataManagerCreationError,
)
from leonardo.data_manager.creation_models import deterministic_hash

from tests.data_manager_test.test_creation_workflow import (
    _advance_same_source,
    _derivative,
    _leaf,
    _materialize,
    _persistence_bytes,
)
from tests.data_manager_test.test_update_workflow import MARKET, _append, _domain
from tests.data_manager_test.seed_fixtures import create_legacy_seed_v2


def _seed_database(service, *, start_index: int = 4, end_index: int = -1):
    dataset = service._loader.load(MARKET)
    seed = create_legacy_seed_v2(
        service, MARKET,
        "Content Seed",
        description="Selected OHLCV base",
        start_ms=int(dataset.ts_ms[start_index]),
        end_ms=int(dataset.ts_ms[end_index]),
    )
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


def _source_key(source) -> tuple[str, str, str | None]:
    return (
        source["source_kind"],
        source["source_id"],
        source["source_revision_id"],
    )


def test_direct_artifacts_add_exact_slice_and_preserve_dependencies(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    before = service.load_database_revision(database.database_id).values_csv

    sma = _leaf("sma", {"period": 3})
    recipes.save_recipe(sma)
    derivative_result = _materialize(service, recipes, _derivative(sma))
    bb_result = _materialize(service, recipes, _leaf("bb", {}))
    roots = (
        *derivative_result.root_logical_artifact_ids,
        *bb_result.root_logical_artifact_ids,
    )

    plan = service.plan_database_artifact_addition(database.database_id, roots)

    assert not plan.blocked, plan.blockers
    assert plan.added_column_names == (
        "research_source__d1",
        "bb_lower_band",
        "bb_middle",
        "bb_upper_band",
    )
    assert len(plan.reviewed_members) == 3
    assert len(plan.dependency_edges) == 1
    dependency = plan.dependency_edges[0].dependency_logical_artifact_id
    assert dependency in {
        item.version_key.logical_artifact_id for item in plan.members
    }
    assert dependency not in {
        item.logical_artifact_id for item in plan.selected_outputs
    }
    assert plan.row_count == database.row_count

    published = service.execute_database_content_edit(plan)
    assert isinstance(published, DatabaseRevisionManifestV3)
    assert published.previous_revision_id == database.revision_id
    values = _frame(service, published)
    assert len(values) == database.row_count
    assert tuple(values["ts_ms"]) == tuple(_frame(service, database)["ts_ms"])
    assert set(plan.added_column_names) <= set(values.columns)
    assert service.load_database_revision(database.database_id, database.revision_id).values_csv == before


def test_duplicate_is_noop_and_mixed_adds_only_new_output(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    sma_root = sma.root_logical_artifact_ids[0]
    first = service.execute_database_content_edit(
        service.plan_database_artifact_addition(database.database_id, (sma_root,))
    )
    assert first is not None

    duplicate = service.plan_database_artifact_addition(first.database_id, (sma_root,))
    assert duplicate.no_op
    assert duplicate.added_column_names == ()
    assert not duplicate.ownership_changed
    assert service.execute_database_content_edit(duplicate) is None
    assert len(service.list_database_revisions(first.database_id)) == 2

    ema = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    mixed = service.plan_database_artifact_addition(
        first.database_id, (sma_root, ema.root_logical_artifact_ids[0])
    )
    assert not mixed.blocked
    assert mixed.added_column_names == ("ema_4",)
    second = service.execute_database_content_edit(mixed)
    assert second is not None
    assert {item.column_name for item in second.selected_outputs} == {
        "sma_3",
        "ema_4",
    }


def test_column_collisions_are_reviewable_and_publish_nothing(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    result = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 4}),
    )
    first, second = result.root_logical_artifact_ids

    base_collision = service.plan_database_content_edit(
        database.database_id,
        artifact_additions=(ArtifactCollectionOutputV1(first, "sma_3", "close"),),
    )
    assert base_collision.blocked
    assert "column collision" in base_collision.blockers[0]

    peer_collision = service.plan_database_content_edit(
        database.database_id,
        artifact_additions=(
            ArtifactCollectionOutputV1(first, "sma_3", "feature"),
            ArtifactCollectionOutputV1(second, "ema_4", "feature"),
        ),
    )
    assert peer_collision.blocked
    assert any("column collision" in item for item in peer_collision.blockers)
    with pytest.raises(DataManagerCreationError, match="blocked Database content edit"):
        service.execute_database_content_edit(peer_collision)
    assert service.load_database_revision(database.database_id).manifest == database
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_collection_capture_pins_revision_and_later_capture_adds_new_output(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    first_result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(first_result, "Features")
    first_plan = service.plan_database_collection_addition(
        database.database_id, collection.collection_id
    )
    first = service.execute_database_content_edit(first_plan)
    assert first is not None
    assert tuple((item.collection_id, item.revision_id) for item in first.collection_sources) == (
        (collection.collection_id, collection.revision_id),
    )

    second_result = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    revised = service.add_artifact_collection_branches(
        collection.collection_id, second_result
    )
    assert service.load_database_revision(first.database_id).manifest == first

    later = service.plan_database_collection_addition(
        first.database_id, revised.collection_id
    )
    assert later.added_column_names == ("ema_4",)
    assert later.ownership_changed
    second = service.execute_database_content_edit(later)
    assert second is not None
    assert {item.column_name for item in second.selected_outputs} == {
        "sma_3",
        "ema_4",
    }
    assert {(item.collection_id, item.revision_id) for item in second.collection_sources} == {
        (collection.collection_id, collection.revision_id),
        (revised.collection_id, revised.revision_id),
    }


def test_stale_database_or_artifact_and_cancellation_publish_nothing(tmp_path: Path) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    ema = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    stale = service.plan_database_artifact_addition(
        database.database_id, sma.root_logical_artifact_ids
    )
    service.execute_database_content_edit(
        service.plan_database_artifact_addition(
            database.database_id, ema.root_logical_artifact_ids
        )
    )
    with pytest.raises(DataManagerCreationError, match="changed after Preview"):
        service.execute_database_content_edit(stale)

    service2, artifacts2, recipes2, _historical2 = _domain(tmp_path / "artifact")
    _seed2, database2 = _seed_database(service2, start_index=0)
    result = _materialize(service2, recipes2, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    plan = service2.plan_database_artifact_addition(database2.database_id, (logical_id,))
    _advance_same_source(service2, artifacts2, logical_id)
    with pytest.raises(DataManagerCreationError, match="Artifact.*changed after Preview"):
        service2.execute_database_content_edit(plan)
    assert len(service2.list_database_revisions(database2.database_id)) == 1

    service3, _artifacts3, recipes3, _historical3 = _domain(tmp_path / "cancel")
    _seed3, database3 = _seed_database(service3, start_index=0)
    result3 = _materialize(service3, recipes3, _leaf("sma", {"period": 3}))
    plan3 = service3.plan_database_artifact_addition(
        database3.database_id, result3.root_logical_artifact_ids
    )
    before = _persistence_bytes(service3.creation_store.root_dir)
    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service3.execute_database_content_edit(plan3, cancellation_requested=lambda: True)
    assert _persistence_bytes(service3.creation_store.root_dir) == before


def test_live_source_and_collection_head_changes_do_not_invalidate_captured_edit(tmp_path: Path) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    _append(historical)
    artifact_plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    published = service.execute_database_content_edit(artifact_plan)
    assert published is not None

    service2, _artifacts2, recipes2, _historical2 = _domain(tmp_path / "collection")
    _seed2, database2 = _seed_database(service2, start_index=0)
    first = _materialize(service2, recipes2, _leaf("sma", {"period": 3}))
    collection = service2.create_artifact_collection(first, "Features")
    collection_plan = service2.plan_database_collection_addition(
        database2.database_id, collection.collection_id
    )
    second = _materialize(service2, recipes2, _leaf("ema", {"period": 4}))
    revised = service2.add_artifact_collection_branches(collection.collection_id, second)
    assert revised.revision_id != collection.revision_id
    published2 = service2.execute_database_content_edit(collection_plan)
    assert published2.collection_sources == (
        type(published2.collection_sources[0])(
            collection.collection_id, collection.revision_id
        ),
    )


def test_remove_source_preserves_overlapping_owner_and_removes_unowned_column(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.execute_database_content_edit(
        service.plan_database_artifact_addition(
            database.database_id, sma.root_logical_artifact_ids
        )
    )
    assert first is not None
    both = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 4}),
    )
    collection = service.create_artifact_collection(both, "Overlap")
    second = service.execute_database_content_edit(
        service.plan_database_collection_addition(
            database.database_id, collection.collection_id
        )
    )
    assert second is not None

    collection_source = next(
        source for source in second.selection_sources
        if source["source_kind"] == "collection"
    )
    plan = service.plan_database_content_edit(
        database.database_id, remove_sources=(_source_key(collection_source),)
    )
    assert plan.removed_column_names == ("ema_4",)
    assert plan.ownership_changed
    published = service.execute_database_content_edit(plan)
    assert {item.column_name for item in published.selected_outputs} == {"sma_3"}
    assert all(source["source_kind"] == "artifact" for source in published.selection_sources)


def test_remove_output_removes_it_from_every_owner(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    sma = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    service.execute_database_content_edit(
        service.plan_database_artifact_addition(
            database.database_id, sma.root_logical_artifact_ids
        )
    )
    both = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 4}),
    )
    collection = service.create_artifact_collection(both, "Overlap")
    service.execute_database_content_edit(
        service.plan_database_collection_addition(
            database.database_id, collection.collection_id
        )
    )

    plan = service.plan_database_content_edit(
        database.database_id,
        remove_outputs=((sma.root_logical_artifact_ids[0], "sma_3"),),
    )
    assert plan.removed_column_names == ("sma_3",)
    published = service.execute_database_content_edit(plan)
    assert {item.column_name for item in published.selected_outputs} == {"ema_4"}
    assert all("sma_3" not in source["column_names"] for source in published.selection_sources)


def test_deleted_captured_collection_can_be_removed_without_live_lookup(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(result, "Disposable")
    published = service.execute_database_content_edit(
        service.plan_database_collection_addition(
            database.database_id, collection.collection_id
        )
    )
    source = next(iter(published.selection_sources))
    collection_dir = (
        service.creation_store.root_dir / "artifact_collections" / collection.collection_id
    )
    shutil.rmtree(collection_dir)

    plan = service.plan_database_content_edit(
        database.database_id, remove_sources=(_source_key(source),)
    )
    assert plan.removed_column_names == ("sma_3",)
    final = service.execute_database_content_edit(plan)
    assert final.selected_outputs == ()
    assert final.selection_sources == ()


def test_ownership_only_addition_publishes_without_rewriting_values(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.execute_database_content_edit(
        service.plan_database_artifact_addition(
            database.database_id, result.root_logical_artifact_ids
        )
    )
    collection = service.create_artifact_collection(result, "Second Owner")
    before = service.load_database_revision(database.database_id).values_csv

    plan = service.plan_database_collection_addition(
        database.database_id, collection.collection_id
    )
    assert plan.added_column_names == ()
    assert plan.ownership_changed
    assert not plan.no_op
    assert plan.values_csv == before
    second = service.execute_database_content_edit(plan)
    assert service.load_database_revision(database.database_id).values_csv == before
    assert len(second.selection_sources) == 2


def test_retained_decimal_tokens_are_preserved_exactly_when_column_added(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    loaded = service.load_database_revision(database.database_id)
    lines = loaded.values_csv.decode("utf-8").splitlines()
    header = next(csv.reader([lines[0]]))
    row = next(csv.reader([lines[1]]))
    open_index = header.index("open")
    sentinel = "100.12345678901234567890123456789"
    row[open_index] = sentinel
    out = StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(row)
    for line in lines[2:]:
        writer.writerow(next(csv.reader([line])))
    adversarial = out.getvalue().encode("utf-8")
    manifest = service._creation._database_v3_manifest(
        database, adversarial, (), (), (), (), value_provenance=database.to_dict()["value_provenance"]
    )
    service.creation_store.publish_database_revision(
        service.load_database_definition(database.database_id),
        manifest,
        adversarial,
        expected_head_revision_id=database.revision_id,
    )

    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    published = service.execute_database_content_edit(plan)
    after = service.load_database_revision(database.database_id, published.revision_id).values_csv
    first_after = next(csv.reader([after.decode("utf-8").splitlines()[1]]))
    assert first_after[open_index] == sentinel


@pytest.mark.parametrize("mode", ("missing_timestamp", "duplicate_timestamp"))
def test_alignment_failures_block_without_trimming_rows(tmp_path: Path, monkeypatch, mode: str) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    before = service.load_database_revision(database.database_id).values_csv
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    summary = next(
        item for item in artifacts.list_managed_artifacts(MARKET)
        if item.logical_artifact_id == logical_id
    )
    loaded = artifacts.load_artifact_by_id(MARKET, summary.artifact_id)
    frame = loaded.frame.copy()
    db_timestamps = set(_frame(service, database)["ts_ms"].astype(int))
    target_index = next(index for index, ts in enumerate(frame["ts_ms"]) if int(ts) in db_timestamps)
    if mode == "missing_timestamp":
        frame = frame.drop(index=target_index).reset_index(drop=True)
    elif mode == "duplicate_timestamp":
        duplicate = frame.iloc[[target_index]].copy()
        frame = pd.concat([frame, duplicate], ignore_index=True)
    projected = LoadedArtifact(loaded.metadata, frame, loaded.analysis)
    original = artifacts.load_artifact_by_id

    def load_modified(market_id, artifact_id):
        if market_id == MARKET and artifact_id == summary.artifact_id:
            return projected
        return original(market_id, artifact_id)

    monkeypatch.setattr(artifacts, "load_artifact_by_id", load_modified)
    plan = service.plan_database_artifact_addition(database.database_id, (logical_id,))
    assert plan.blocked
    assert plan.added_column_names == ()
    with pytest.raises(DataManagerCreationError, match="blocked Database content edit"):
        service.execute_database_content_edit(plan)
    assert service.load_database_revision(database.database_id).values_csv == before
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_numeric_nan_addition_preserves_base_axis_tokens_and_missing_cell(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    before = service.load_database_revision(database.database_id).values_csv
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    assert not plan.blocked, plan.blockers
    published = service.execute_database_content_edit(plan)
    after = service.load_database_revision(database.database_id).values_csv
    old_rows = list(csv.reader(StringIO(before.decode("utf-8"))))
    new_rows = list(csv.reader(StringIO(after.decode("utf-8"))))
    assert [row[:len(old_rows[0])] for row in new_rows] == old_rows
    assert new_rows[1][-1] == new_rows[2][-1] == ""
    assert _frame(service, published)["sma_3"].isna().tolist() == (
        [True, True] + [False] * (database.row_count - 2)
    )
    assert published.row_count == database.row_count
    assert len(service.list_database_revisions(database.database_id)) == 2


def test_broader_artifact_coverage_refuses_slicing(tmp_path: Path) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=20, end_index=-10)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    head = artifacts.load_artifact_head(MARKET, logical_id)
    artifact = artifacts.load_artifact_by_id(MARKET, head.artifact_id)
    assert artifact.metadata.first_timestamp_ms < database.first_timestamp_ms
    assert artifact.metadata.last_timestamp_ms > database.last_timestamp_ms

    before = service.load_database_revision(database.database_id)
    plan = service.plan_database_artifact_addition(database.database_id, (logical_id,))
    assert plan.blocked and any("row count" in item for item in plan.blockers)
    with pytest.raises(DataManagerCreationError, match="blocked"):
        service.execute_database_content_edit(plan)
    assert service.load_database_revision(database.database_id) == before
    assert len(service.list_database_revisions(database.database_id)) == 1


def test_explicit_edit_of_legacy_v2_publishes_v3_and_keeps_old_revision(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    loaded = service.load_database_revision(database.database_id)
    payload = {
        "schema_version": "2.0",
        "object_type": "database_revision",
        "database_id": database.database_id,
        "display_name": database.display_name,
        "description": database.description,
        "seed_id": database.seed_id,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": database.source_ohlcv.to_dict(),
        "members": [],
        "dependency_edges": [],
        "selected_outputs": [],
        "collection_sources": [],
        "column_mapping": dict(database.column_mapping),
        "first_timestamp_ms": database.first_timestamp_ms,
        "last_timestamp_ms": database.last_timestamp_ms,
        "row_count": database.row_count,
        "column_count": database.column_count,
        "values_sha256": hashlib.sha256(loaded.values_csv).hexdigest(),
        "previous_revision_id": database.revision_id,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    payload["revision_id"] = deterministic_hash(payload)
    legacy = DatabaseRevisionManifestV2.from_dict(payload)
    service.creation_store.publish_database_revision(
        service.load_database_definition(database.database_id),
        legacy,
        loaded.values_csv,
        expected_head_revision_id=database.revision_id,
    )
    old_bytes = service.load_database_revision(
        database.database_id, legacy.revision_id
    ).values_csv

    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    plan = service.plan_database_artifact_addition(
        database.database_id, result.root_logical_artifact_ids
    )
    published = service.execute_database_content_edit(plan)
    assert isinstance(published, DatabaseRevisionManifestV3)
    assert published.previous_revision_id == legacy.revision_id
    assert service.load_database_revision(
        database.database_id, legacy.revision_id
    ).values_csv == old_bytes


def test_two_collections_can_share_one_output_and_source_removal_preserves_overlap(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    sma_only = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.create_artifact_collection(sma_only, "First")

    sma_ema = _materialize(
        service,
        recipes,
        _leaf("sma", {"period": 3}),
        _leaf("ema", {"period": 4}),
    )
    sma_id = sma_ema.root_logical_artifact_ids[0]
    second = service.create_artifact_collection(
        sma_ema,
        "Second",
        selected_outputs=(ArtifactCollectionOutputV1(sma_id, "sma_3", "sma_3"),),
    )
    assert second.collection_id != first.collection_id

    one = service.execute_database_content_edit(
        service.plan_database_collection_addition(database.database_id, first.collection_id)
    )
    assert one is not None
    two_plan = service.plan_database_collection_addition(database.database_id, second.collection_id)
    assert two_plan.added_column_names == ()
    assert two_plan.ownership_changed
    two = service.execute_database_content_edit(two_plan)
    assert len(two.selection_sources) == 2
    assert all(source["column_names"] == ("sma_3",) for source in two.selection_sources)

    first_source = next(
        source for source in two.selection_sources
        if source["source_id"] == first.collection_id
    )
    remove = service.plan_database_content_edit(
        database.database_id, remove_sources=(_source_key(first_source),)
    )
    assert remove.removed_column_names == ()
    remaining = service.execute_database_content_edit(remove)
    assert {item.column_name for item in remaining.selected_outputs} == {"sma_3"}
    assert len(remaining.selection_sources) == 1
    assert remaining.selection_sources[0]["source_id"] == second.collection_id


def test_contradictory_add_remove_intent_is_rejected(tmp_path: Path) -> None:
    service, artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    head = artifacts.load_artifact_head(MARKET, logical_id)
    loaded = artifacts.load_artifact_by_id(MARKET, head.artifact_id)
    output_name = loaded.metadata.recipe.output_names[0]
    output = ArtifactCollectionOutputV1(logical_id, output_name, output_name)

    with pytest.raises(DataManagerCreationError, match="contradictory add/remove output"):
        service.plan_database_content_edit(
            database.database_id,
            artifact_additions=(output,),
            remove_outputs=((logical_id, output_name),),
        )
    with pytest.raises(DataManagerCreationError, match="contradictory add/remove source"):
        service.plan_database_content_edit(
            database.database_id,
            artifact_additions=(output,),
            remove_sources=(("artifact", logical_id, None),),
        )


def _a2_snapshot(service, recipes, schema="1.0", *, dependent=False):
    """Build real saved values, then capture the historical persisted shape."""
    from dataclasses import replace
    from leonardo.data_manager.creation_models import database_revision_from_dict

    sma = _leaf("sma", {"period": 3})
    recipes.save_recipe(sma)
    result = _materialize(service, recipes, _derivative(sma) if dependent else sma, _leaf("bb", {}))
    collection = service.create_artifact_collection_from_selection(
        service.plan_artifact_collection_selection(MARKET, result.root_logical_artifact_ids), "A2 inputs")
    seed = service.create_database_seed(MARKET, "A2 seed")
    current = service.build_database_revision(seed.seed_id, collection.collection_id)
    values = service.load_database_revision(current.database_id).values_csv
    if schema == "4.0":
        return current, collection, result.root_logical_artifact_ids, values
    identity = service.creation_store.new_database_id()
    definition = replace(service.load_database_definition(current.database_id), database_id=identity)
    payload = current.to_dict(include_revision_id=False)
    payload.pop("value_provenance")
    payload.update(schema_version=schema, database_id=identity, previous_revision_id=None)
    if schema in {"1.0", "2.0"}:
        payload.pop("selection_sources")
    if schema == "1.0":
        for name in ("members", "dependency_edges", "selected_outputs", "collection_sources"):
            payload.pop(name)
        payload.update(
            collection_id=collection.collection_id, collection_revision_id=collection.revision_id,
            collection_manifest_hash=hashlib.sha256(collection.canonical_json_bytes()).hexdigest(),
            artifact_version_keys=[dict(logical_artifact_id=m.version_key.logical_artifact_id,
                                        artifact_id=m.version_key.artifact_id) for m in collection.members],
            artifact_payload_hashes=[m.values_sha256 for m in collection.members],
            portable_recipe_ids=list(collection.source_portable_recipe_ids),
        )
    payload["revision_id"] = deterministic_hash(payload)
    legacy = database_revision_from_dict(payload)
    service.creation_store.publish_database_revision(definition, legacy, values, expected_head_revision_id=None)
    return legacy, collection, result.root_logical_artifact_ids, values


@pytest.mark.parametrize("schema", ("1.0", "2.0", "3.0", "4.0"))
@pytest.mark.parametrize("operation", ("partial", "all", "add", "mixed"))
def test_a2_edit_snapshot_without_deleted_providers(tmp_path, monkeypatch, schema, operation):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    original, collection, roots, before = _a2_snapshot(service, recipes, schema)
    extra = _materialize(service, recipes, _leaf("ema", {"period": 5})).root_logical_artifact_ids[0]
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    captured = original.canonical_json_bytes()
    original_load = artifacts.load_artifact_by_id
    deleted = {key.artifact_id for key in original.artifact_version_keys}

    def no_old_provider(market, identity):
        assert identity not in deleted, "Retained provider was loaded during an edit"
        return original_load(market, identity)

    monkeypatch.setattr(artifacts, "load_artifact_by_id", no_old_provider)
    noop = service.plan_database_content_edit(original.database_id)
    assert noop.no_op and not noop.blocked and len(noop.selected_outputs) == 4
    assert service.execute_database_content_edit(noop) is None
    assert len(service.list_database_revisions(original.database_id)) == 1
    removals = tuple(o.column_name for o in noop.selected_outputs)
    intent = {}
    if operation in {"partial", "mixed"}:
        intent["remove_columns"] = removals[:1]
    elif operation == "all":
        intent["remove_columns"] = removals
    if operation in {"add", "mixed"}:
        intent["artifact_additions"] = (ArtifactCollectionOutputV1(extra, "ema_5", "ema_5"),)
    plan = service.plan_database_content_edit(original.database_id, **intent)
    assert not plan.blocked, plan.blockers
    edited = service.execute_database_content_edit(plan)
    assert edited.schema_version == ("5.0" if schema in {"1.0", "2.0"} and operation != "all" else "4.0")
    after = service.load_database_revision(original.database_id).values_csv
    old_rows = list(csv.DictReader(StringIO(before.decode())))
    new_rows = list(csv.DictReader(StringIO(after.decode())))
    assert len(old_rows) == len(new_rows)
    for old, new in zip(old_rows, new_rows, strict=True):
        assert all(new[name] == token for name, token in old.items() if name not in intent.get("remove_columns", ()))
    assert service.load_database_revision(original.database_id, original.revision_id).manifest.canonical_json_bytes() == captured
    assert service.load_database_revision(original.database_id, original.revision_id).values_csv == before
    # A fresh service/store reader must handle the edited revision identically.
    fresh, *_ = _domain(tmp_path)
    assert fresh.load_database_revision(original.database_id).manifest == edited
    assert fresh.plan_database_content_edit(original.database_id).no_op
    if operation == "all":
        assert edited.selected_outputs == () and edited.value_provenance["outputs"] == ()
    else:
        again = fresh.plan_database_content_edit(original.database_id, remove_columns=(plan.selected_outputs[0].column_name,))
        assert not again.blocked
        fresh.execute_database_content_edit(again)


@pytest.mark.parametrize("columns", (("close",), ("missing",), ("sma_3", "sma_3")))
def test_a2_reject_invalid_column_removal_without_writes(tmp_path, columns):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    original, _collection, _roots, _before = _a2_snapshot(service, recipes)
    before = _persistence_bytes(tmp_path)
    with pytest.raises(DataManagerCreationError, match="unique existing derived columns"):
        service.plan_database_content_edit(original.database_id, remove_columns=columns)
    assert _persistence_bytes(tmp_path) == before



def test_a2_v1_to_v2_history_keeps_proved_collection_owner(tmp_path):
    from leonardo.data_manager.creation_models import database_revision_from_dict
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    original, collection, _roots, values = _a2_snapshot(service, recipes)
    current = next(service.load_database_revision(identity).manifest
                   for identity in service.creation_store.list_database_ids() if identity != original.database_id)
    payload = current.to_dict(include_revision_id=False)
    payload.pop("value_provenance")
    payload.pop("selection_sources")
    payload.update(schema_version="2.0", database_id=original.database_id, previous_revision_id=original.revision_id)
    payload["revision_id"] = deterministic_hash(payload)
    v2 = database_revision_from_dict(payload)
    service.creation_store.publish_database_revision(service.load_database_definition(original.database_id),
                                                     v2, values, expected_head_revision_id=original.revision_id)
    service.delete_artifact_collection(collection.collection_id)
    plan = service.plan_database_content_edit(original.database_id)
    assert plan.selection_sources == ({"source_kind": "collection", "source_id": collection.collection_id,
                                      "source_revision_id": collection.revision_id,
                                      "column_names": tuple(sorted(o.column_name for o in v2.selected_outputs))},)
    removal = service.plan_database_content_edit(original.database_id,
        remove_sources=(("collection", collection.collection_id, collection.revision_id),))
    assert len(removal.removed_column_names) == 4 and not removal.blocked
    service.execute_database_content_edit(removal)


@pytest.mark.parametrize("failure", ("cancel", "publication", "stale"))
def test_a2_legacy_edit_failures_leave_no_partial_write(tmp_path, failure):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    original, collection, roots, _ = _a2_snapshot(service, recipes)
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    baseline = service.plan_database_content_edit(original.database_id)
    plan = service.plan_database_content_edit(original.database_id, remove_columns=(baseline.selected_outputs[0].column_name,))
    if failure == "stale":
        other = service.plan_database_content_edit(original.database_id, remove_columns=(baseline.selected_outputs[1].column_name,))
        service.execute_database_content_edit(other)
    before = _persistence_bytes(tmp_path)
    def failed_publication():
        raise DataManagerCreationError("injected publication failure")
    options = ({"cancellation_requested": lambda: True} if failure == "cancel" else
               {"before_publish": failed_publication} if failure == "publication" else {})
    with pytest.raises(DataManagerCreationError):
        service.execute_database_content_edit(plan, **options)
    assert _persistence_bytes(tmp_path) == before



def test_a2_v1_uses_own_proved_history_without_live_inputs(tmp_path, monkeypatch):
    from leonardo.data_manager.creation_models import database_revision_from_dict
    service, artifacts, recipes, _historical = _domain(tmp_path)
    legacy, collection, roots, values = _a2_snapshot(service, recipes)
    current = next(service.load_database_revision(identity).manifest
                   for identity in service.creation_store.list_database_ids() if identity != legacy.database_id)
    payload = legacy.to_dict(include_revision_id=False)
    payload.update(database_id=current.database_id, previous_revision_id=current.revision_id)
    payload["revision_id"] = deterministic_hash(payload)
    legacy = database_revision_from_dict(payload)
    service.creation_store.publish_database_revision(service.load_database_definition(current.database_id),
                                                     legacy, values, expected_head_revision_id=current.revision_id)
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    monkeypatch.setattr(artifacts, "load_artifact_by_id", lambda *a, **k: pytest.fail("history projection loaded a provider"))
    baseline = service.plan_database_content_edit(current.database_id)
    assert baseline.selected_outputs == current.selected_outputs
    assert baseline.members == current.members
    plan = service.plan_database_content_edit(current.database_id,
        remove_outputs=((current.selected_outputs[0].logical_artifact_id, current.selected_outputs[0].output_name),))
    edited = service.execute_database_content_edit(plan)
    assert edited.schema_version == "4.0"
    assert service.load_database_revision(current.database_id, legacy.revision_id).values_csv == values
