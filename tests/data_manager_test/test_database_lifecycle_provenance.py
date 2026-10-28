"""Database preservation and exact consumed-version evidence (F2–F4)."""
import csv
from hashlib import sha256
from io import StringIO
from pathlib import Path

import pytest

from leonardo.artifacts._stores import _io_path
from leonardo.data_manager import ArtifactCollectionOutputV1, DataManagerCreationError, DataManagerOperationError
from leonardo.data_manager.creation_models import database_revision_from_dict, deterministic_hash
from tests.data_manager_test.test_creation_workflow import _leaf
from tests.data_manager_test.test_update_workflow import (
    MARKET, _angle, _append, _derivative, _domain, _materialize, _publish_modified, _sma,
)


def _setup(root: Path, *, dependent=True):
    service, artifacts, recipes, historical = _domain(root)
    sma = _sma(3)
    recipes.save_recipe(sma)
    recipe = _derivative(sma) if dependent else sma
    result = _materialize(service, recipes, recipe)
    logical_id = result.root_logical_artifact_ids[0]
    seed = service.create_database_seed(MARKET, "Lifecycle seed")
    collection = service.create_artifact_collection_from_selection(
        service.plan_artifact_collection_selection(MARKET, (logical_id,)), "Lifecycle collection",
    )
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    return service, artifacts, recipes, historical, logical_id, seed, collection, database


def _stored(root):
    root = _io_path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _grow(service, historical, root_id):
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (root_id,)))


def _refresh_build_targets(service, seed, collection):
    seed = service.execute_database_seed_append(service.plan_database_seed_append(seed.seed_id))
    plan = service.plan_artifact_collection_selection(
        MARKET, collection.root_logical_artifact_ids, collection_id=collection.collection_id,
        expected_revision_id=collection.revision_id,
    )
    collection = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id,
    )
    return seed, collection


def test_f2_old_seed_cannot_shrink_existing_database_but_can_create_new(tmp_path):
    service, _artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    _grow(service, historical, root_id)
    appended = service.execute_database_append(service.plan_database_update(database.database_id)).database_revision
    assert appended.row_count == 104
    before = _stored(tmp_path)
    with pytest.raises(DataManagerCreationError, match="preserv|append|row"):
        service.build_database_revision(seed.seed_id, collection.collection_id, database_id=database.database_id)
    assert _stored(tmp_path) == before
    assert service.load_database_revision(database.database_id).manifest == appended
    fresh = service.build_database_revision(seed.seed_id, collection.collection_id)
    assert fresh.database_id != database.database_id
    assert fresh.row_count == 96


def test_f2_existing_build_cannot_replace_historical_values(tmp_path):
    service, _artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    _publish_modified(historical, rows=96, mutate_row=40)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (root_id,)))
    _seed, collection = _refresh_build_targets(service, seed, collection)
    before = _stored(tmp_path)
    with pytest.raises(DataManagerCreationError, match="preserv|retained|content"):
        service.build_database_revision(seed.seed_id, collection.collection_id, database_id=database.database_id)
    assert _stored(tmp_path) == before


def test_f2_existing_build_cannot_drop_retained_column(tmp_path):
    service, _artifacts, recipes, _historical, _root, seed, collection, database = _setup(tmp_path)
    extra = _materialize(service, recipes, _sma(5))
    service.execute_database_content_edit(service.plan_database_artifact_addition(
        database.database_id, extra.root_logical_artifact_ids,
    ))
    before = _stored(tmp_path)
    with pytest.raises(DataManagerCreationError, match="preserv|retained|content"):
        service.build_database_revision(seed.seed_id, collection.collection_id, database_id=database.database_id)
    assert _stored(tmp_path) == before


def test_f2_unchanged_existing_build_preserves_payload_and_history(tmp_path):
    service, _artifacts, _recipes, _historical, _root, seed, collection, database = _setup(tmp_path)
    before = service.load_database_revision(database.database_id)
    repeated = service.build_database_revision(seed.seed_id, collection.collection_id, database_id=database.database_id)
    assert repeated.previous_revision_id == database.revision_id
    assert service.load_database_revision(database.database_id).values_csv == before.values_csv
    assert service.load_database_revision(database.database_id, database.revision_id) == before


def test_f2_same_values_cannot_replace_retained_provider_mapping(tmp_path):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    collections = []
    for tool in ("sma", "ema"):
        result = _materialize(service, recipes, _leaf(tool, {"period": 1}))
        logical_id = result.root_logical_artifact_ids[0]
        collections.append(service.create_artifact_collection_from_selection(
            service.plan_artifact_collection_selection(MARKET, (logical_id,)), tool,
            selected_outputs=(ArtifactCollectionOutputV1(logical_id, f"{tool}_1", "feature"),),
        ))
    seed = service.create_database_seed(MARKET, "Same values")
    original = service.build_database_revision(seed.seed_id, collections[0].collection_id)
    candidate = service.build_database_revision(seed.seed_id, collections[1].collection_id)
    # Isolate mapping preservation: values, axis and column names are identical.
    assert service.load_database_revision(original.database_id).values_csv == service.load_database_revision(candidate.database_id).values_csv
    before = _stored(tmp_path)
    with pytest.raises(DataManagerCreationError, match="preserve"):
        service.build_database_revision(seed.seed_id, collections[1].collection_id, database_id=original.database_id)
    assert _stored(tmp_path) == before
    assert service.load_database_revision(original.database_id).manifest == original


def _assert_exact_graph(artifacts, manifest):
    provenance = manifest.to_dict()["value_provenance"]
    members = {m["artifact_id"]: m for m in provenance["members"]}
    expected_edges = set()
    for artifact_id, member in members.items():
        metadata = artifacts.load_artifact_metadata(MARKET, artifact_id)
        assert metadata.values_sha256 == member["values_sha256"]
        for ref in metadata.recipe.source_artifacts:
            assert ref.artifact_id in members
            expected_edges.add((ref.artifact_id, artifact_id, ref.role, ref.output_name))
    assert {
        (e["dependency_artifact_id"], e["dependent_artifact_id"], e["role"], e["output_name"])
        for e in provenance["dependency_edges"]
    } == expected_edges


def _advance_support(service, artifacts, historical, collection):
    support_id = collection.support_logical_artifact_ids[0]
    consumed_id = artifacts.load_artifact_head(MARKET, support_id).artifact_id
    _publish_modified(historical, rows=104, mutate_row=40)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (support_id,)))
    assert artifacts.load_artifact_head(MARKET, support_id).artifact_id != consumed_id
    return support_id, consumed_id


@pytest.mark.parametrize("route", ("build", "append"))
@pytest.mark.parametrize("support_advanced", (False, True))
def test_f3_records_consumed_support_not_collection_pin_or_latest_head(tmp_path, route, support_advanced):
    service, artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    old = service.load_database_revision(database.database_id)
    _grow(service, historical, root_id)
    support_id = collection.support_logical_artifact_ids[0]
    consumed_id = artifacts.load_artifact_head(MARKET, support_id).artifact_id
    if support_advanced:
        assert _advance_support(service, artifacts, historical, collection) == (support_id, consumed_id)
    if route == "build":
        seed, collection = _refresh_build_targets(service, seed, collection)
        published = service.build_database_revision(seed.seed_id, collection.collection_id)
        assert published.row_count == 104
    else:
        plan = service.plan_database_update(database.database_id)
        assert plan.mode == "APPEND", plan.blockers
        assert {key for key, _version in plan.starting_artifact_heads} == {root_id}
        published = service.execute_database_append(plan).database_revision
        assert published.row_count == 104
        assert published.previous_revision_id == database.revision_id
        assert service.load_database_revision(database.database_id).values_csv.startswith(old.values_csv)
    by_id = {m.version_key.logical_artifact_id: m for m in published.members}
    assert by_id[support_id].version_key.artifact_id == consumed_id
    _assert_exact_graph(artifacts, published)
    assert published.selected_outputs == database.selected_outputs
    assert [(ref.collection_id, ref.revision_id) for ref in published.collection_sources] == [
        (collection.collection_id, collection.revision_id)
    ]
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.load_database_revision(database.database_id, database.revision_id) == old


@pytest.mark.parametrize("route", ("build", "append"))
def test_f3_nested_shared_closure_keeps_only_selected_columns(tmp_path, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    sma = _sma(3)
    derivative = _derivative(sma)
    for recipe in (sma, derivative):
        recipes.save_recipe(recipe)
    result = _materialize(service, recipes, _angle(derivative), derivative)
    collection = service.create_artifact_collection(result, "Shared nested closure")
    seed = service.create_database_seed(MARKET, "Nested seed")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    old = service.load_database_revision(database.database_id)
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, result.root_logical_artifact_ids))
    published = (
        service.build_database_revision(seed.seed_id, collection.collection_id)
        if route == "build" else
        service.execute_database_append(service.plan_database_update(database.database_id)).database_revision
    )
    _assert_exact_graph(artifacts, published)
    assert len(published.members) == 3
    assert len(published.selected_outputs) == 2
    assert dict(published.column_mapping) == dict(database.column_mapping)
    assert "sma_3" not in published.column_mapping
    assert published.collection_sources == database.collection_sources
    assert service.load_database_revision(database.database_id, database.revision_id) == old


@pytest.mark.parametrize("route", ("build", "append"))
def test_f3_root_changes_at_publication_cannot_publish(tmp_path, route):
    service, artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    _grow(service, historical, root_id)
    _advance_support(service, artifacts, historical, collection)
    plan = service.plan_database_update(database.database_id)
    before = _stored(tmp_path / "data_manager")

    def advance_root():
        service.execute_artifact_update(service.plan_artifact_update(MARKET, (root_id,)))

    if route == "build":
        # A pinned Collection import does not silently follow its Artifact heads.
        published = service.build_database_revision(seed.seed_id, collection.collection_id, before_publish=advance_root)
        assert published.value_provenance == database.value_provenance
        assert published.row_count == database.row_count
    else:
        with pytest.raises((DataManagerCreationError, DataManagerOperationError), match="changed|stale"):
            service.execute_database_append(plan, before_publish=advance_root)
        assert _stored(tmp_path / "data_manager") == before


@pytest.mark.parametrize("route", ("build", "append"))
def test_f3_support_head_may_advance_after_review_without_invalidating_exact_version(tmp_path, route):
    service, artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    _grow(service, historical, root_id)
    support_id = collection.support_logical_artifact_ids[0]
    consumed_id = artifacts.load_artifact_head(MARKET, support_id).artifact_id
    if route == "build":
        seed, collection = _refresh_build_targets(service, seed, collection)
    _publish_modified(historical, rows=104, mutate_row=40)
    service.invalidate_source(MARKET)
    plan = service.plan_database_update(database.database_id)

    def advance_support():
        service.execute_artifact_update(service.plan_artifact_update(MARKET, (support_id,)))

    published = (
        service.build_database_revision(seed.seed_id, collection.collection_id, before_publish=advance_support)
        if route == "build" else
        service.execute_database_append(plan, before_publish=advance_support).database_revision
    )
    assert artifacts.load_artifact_head(MARKET, support_id).artifact_id != consumed_id
    assert {m.version_key.logical_artifact_id: m.version_key.artifact_id for m in published.members}[support_id] == consumed_id
    _assert_exact_graph(artifacts, published)


@pytest.mark.parametrize("route", ("build", "append"))
def test_f3_missing_exact_support_refuses_publication(tmp_path, route):
    service, artifacts, _recipes, historical, root_id, seed, collection, database = _setup(tmp_path)
    _grow(service, historical, root_id)
    if route == "build":
        seed, collection = _refresh_build_targets(service, seed, collection)
    support_id, consumed_id = _advance_support(service, artifacts, historical, collection)
    # Remove only this isolated fixture's recorded exact support ownership.
    _io_path(artifacts._store.version_record_path(MARKET, support_id, consumed_id)).unlink()
    before = _stored(tmp_path / "data_manager")
    if route == "build":
        with pytest.raises(DataManagerCreationError, match="owner"):
            service.build_database_revision(seed.seed_id, collection.collection_id)
    else:
        plan = service.plan_database_update(database.database_id)
        assert plan.blocked
        assert any("owner" in blocker for blocker in plan.blockers)
        with pytest.raises(DataManagerOperationError):
            service.execute_database_append(plan)
    assert _stored(tmp_path / "data_manager") == before


@pytest.mark.parametrize("route", ("build", "append"))
def test_f3_distinct_exact_versions_with_matching_coverage_are_accepted(tmp_path, route):
    service, artifacts, _recipes, historical, root_id, seed, collection, _database = _setup(tmp_path)
    support_id = collection.support_logical_artifact_ids[0]
    both = service.create_artifact_collection_from_selection(
        service.plan_artifact_collection_selection(MARKET, (root_id, support_id)), "Both outputs",
    )
    database = service.build_database_revision(seed.seed_id, both.collection_id)
    _grow(service, historical, root_id)
    _advance_support(service, artifacts, historical, collection)
    if route == "build":
        seed, both = _refresh_build_targets(service, seed, both)
        published = service.build_database_revision(seed.seed_id, both.collection_id)
    else:
        plan = service.plan_database_update(database.database_id)
        assert not plan.blocked, plan.blockers
        published = service.execute_database_append(plan).database_revision
    assert published.row_count == 104
    _assert_exact_graph(artifacts, published)
    versions = {m["artifact_id"] for m in published.value_provenance["members"]
                if m["logical_artifact_id"] == support_id}
    assert len(versions) >= 2


@pytest.mark.parametrize("schema", ("1.0", "2.0"))
def test_f3_legacy_append_keeps_old_revision_and_records_exact_support(tmp_path, schema):
    service, artifacts, _recipes, historical, root_id, _seed, collection, database = _setup(tmp_path)
    old = service.load_database_revision(database.database_id)
    payload = database.to_dict(include_revision_id=False)
    payload.pop("selection_sources")
    payload.pop("value_provenance")
    payload["schema_version"] = schema
    payload["previous_revision_id"] = database.revision_id
    if schema == "1.0":
        for key in ("members", "dependency_edges", "selected_outputs", "collection_sources"):
            payload.pop(key)
        payload.update(
            collection_id=collection.collection_id,
            collection_revision_id=collection.revision_id,
            collection_manifest_hash=sha256(collection.canonical_json_bytes()).hexdigest(),
            artifact_version_keys=[
                {"logical_artifact_id": m.version_key.logical_artifact_id, "artifact_id": m.version_key.artifact_id}
                for m in collection.members
            ],
            artifact_payload_hashes=[m.values_sha256 for m in collection.members],
            portable_recipe_ids=list(collection.source_portable_recipe_ids),
        )
    payload["revision_id"] = deterministic_hash(payload)
    legacy = database_revision_from_dict(payload)
    service.creation_store.publish_database_revision(
        service.load_database_definition(database.database_id), legacy, old.values_csv,
        expected_head_revision_id=database.revision_id,
    )
    _grow(service, historical, root_id)
    support_id, consumed_id = _advance_support(service, artifacts, historical, collection)
    published = service.execute_database_append(service.plan_database_update(database.database_id)).database_revision
    assert published.schema_version == "4.0"
    assert published.previous_revision_id == legacy.revision_id
    assert {key.logical_artifact_id: key.artifact_id for key in published.artifact_version_keys}[support_id] == consumed_id
    assert published.column_mapping == legacy.column_mapping
    assert service.load_database_revision(database.database_id).values_csv.startswith(old.values_csv)
    assert service.load_database_revision(database.database_id, legacy.revision_id).manifest == legacy
    if schema == "2.0":
        _assert_exact_graph(artifacts, published)


def _historical_update(service, artifacts, historical, root_id):
    old = artifacts.load_artifact_head(MARKET, root_id).artifact_id
    _publish_modified(historical, rows=96, mutate_row=40)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (root_id,)))
    assert artifacts.load_artifact_head(MARKET, root_id).artifact_id != old


@pytest.mark.parametrize("direction", ("collection_to_direct", "direct_to_collection"))
def test_f4_ownership_only_preserves_payload_and_exact_provenance(tmp_path, direction):
    service, artifacts, _recipes, historical, root_id, _seed, collection, database = _setup(tmp_path)
    if direction == "direct_to_collection":
        service.execute_database_content_edit(service.plan_database_artifact_addition(database.database_id, (root_id,)))
        service.execute_database_content_edit(service.plan_database_content_edit(
            database.database_id, remove_sources=(("collection", collection.collection_id, collection.revision_id),),
        ))
    old = service.load_database_revision(database.database_id)
    _historical_update(service, artifacts, historical, root_id)
    plan = (
        service.plan_database_artifact_addition(database.database_id, (root_id,))
        if direction == "collection_to_direct" else
        service.plan_database_collection_addition(database.database_id, collection.collection_id)
    )
    assert plan.ownership_changed and not plan.no_op and not plan.blocked
    assert plan.added_column_names == plan.removed_column_names == ()
    assert plan.values_csv == old.values_csv
    if direction == "collection_to_direct":
        assert {m.version_key for m in plan.reviewed_members} != {m.version_key for m in old.manifest.members}
    assert plan.value_provenance == old.manifest.value_provenance
    assert plan.members == old.manifest.members
    assert plan.dependency_edges == old.manifest.dependency_edges
    published = service.execute_database_content_edit(plan)
    assert published.members == old.manifest.members
    assert published.dependency_edges == old.manifest.dependency_edges
    assert {source["source_kind"] for source in published.selection_sources} == {"artifact", "collection"}
    assert published.selected_outputs == old.manifest.selected_outputs
    assert service.load_database_revision(database.database_id).values_csv == old.values_csv
    assert service.load_database_revision(database.database_id, old.manifest.revision_id) == old
    _assert_exact_graph(artifacts, published)


def test_f4_mixed_ownership_and_new_output_preserves_retained_versions_and_cells(tmp_path):
    service, artifacts, recipes, historical, root_id, _seed, _collection, database = _setup(tmp_path)
    old = service.load_database_revision(database.database_id)
    _historical_update(service, artifacts, historical, root_id)
    extra = _materialize(service, recipes, _sma(5))
    extra_id = extra.root_logical_artifact_ids[0]
    plan = service.plan_database_artifact_addition(database.database_id, (root_id, extra_id))
    assert not plan.blocked
    assert plan.ownership_changed
    assert plan.added_column_names == ("sma_5",)
    by_id = {m.version_key.logical_artifact_id: m for m in plan.members}
    for member in old.manifest.members:
        assert by_id[member.version_key.logical_artifact_id] == member
    assert by_id[extra_id].version_key.artifact_id == artifacts.load_artifact_head(MARKET, extra_id).artifact_id
    published = service.execute_database_content_edit(plan)
    _assert_exact_graph(artifacts, published)
    before_rows = list(csv.reader(StringIO(old.values_csv.decode())))
    after_rows = list(csv.reader(StringIO(service.load_database_revision(database.database_id).values_csv.decode())))
    assert [row[:-1] for row in after_rows] == before_rows
    assert service.load_database_revision(database.database_id, database.revision_id) == old


def test_f4_duplicate_owner_remains_noop_after_provider_update(tmp_path):
    service, artifacts, _recipes, historical, root_id, _seed, collection, database = _setup(tmp_path)
    old = service.load_database_revision(database.database_id)
    _historical_update(service, artifacts, historical, root_id)
    before = _stored(tmp_path)
    plan = service.plan_database_collection_addition(database.database_id, collection.collection_id)
    assert plan.no_op and not plan.blocked
    assert plan.values_csv == old.values_csv
    assert plan.members == old.manifest.members
    assert plan.dependency_edges == old.manifest.dependency_edges
    assert service.execute_database_content_edit(plan) is None
    assert _stored(tmp_path) == before
