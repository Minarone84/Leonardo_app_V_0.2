"""Three-rule compatibility and immutable physical-provider regressions."""
from dataclasses import replace
import csv
from io import StringIO

import numpy as np
import pytest

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    DataManagerCreationError,
    DataManagerOperationError,
)
from leonardo.data_manager.creation_service import DataManagerCreationWorkflow
from leonardo.ohlcv.store import OHLCVStore
from tests.data_manager_test.test_creation_workflow import _leaf
from tests.data_manager_test.test_database_lifecycle_provenance import (
    _assert_exact_graph,
    _grow,
    _historical_update,
    _refresh_build_targets,
    _setup,
    _stored,
)
from tests.data_manager_test.test_seed_append_workflow import _publish_raw
from tests.data_manager_test.test_update_workflow import (
    MARKET,
    _append,
    _derivative,
    _domain,
    _materialize,
    _sma,
)


OHLCV = ("ts_ms", "open", "high", "low", "close", "volume")


def _columns(values):
    rows = list(csv.reader(StringIO(values.decode("utf-8"))))
    assert rows and all(len(row) == len(rows[0]) for row in rows)
    return {name: tuple(row[index] for row in rows[1:])
            for index, name in enumerate(rows[0])}


def _assert_retained(before, after, *, removed=()):
    old, new = _columns(before), _columns(after)
    assert set(OHLCV) <= old.keys() & new.keys()
    assert len(new["ts_ms"]) == len(old["ts_ms"])
    for name, tokens in old.items():
        if name not in removed:
            assert new[name] == tokens, name
    assert not set(removed) & new.keys()


def _assert_provider_column(artifacts, values, physical_id, output_name):
    columns = _columns(values)
    frame = artifacts.load_artifact_by_id(MARKET, physical_id).frame
    assert tuple(map(int, columns["ts_ms"])) == tuple(frame["ts_ms"])
    actual = np.array([float(token) if token else np.nan
                       for token in columns[output_name]])
    expected = frame[output_name].to_numpy(dtype="float64")
    # Compare every row, including warm-up NaNs; no dropna/fill/slicing.
    np.testing.assert_allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
    assert np.isnan(expected).any()
    assert np.isfinite(expected).any()


def _assert_providers(artifacts, manifest, providers, physical_ids):
    _assert_exact_graph(artifacts, manifest)
    evidence = manifest.to_dict()["value_provenance"]
    assert {member["artifact_id"] for member in evidence["members"]} == set(physical_ids)
    assert len(evidence["members"]) == len(physical_ids)
    assert len(evidence["outputs"]) == len(providers)
    assert {
        (output["column_name"], output["logical_artifact_id"],
         output["output_name"], output["artifact_id"],
         output["first_timestamp_ms"], output["last_timestamp_ms"])
        for output in evidence["outputs"]
    } == {
        (name, logical_id, name, physical_id,
         manifest.first_timestamp_ms, manifest.last_timestamp_ms)
        for name, (logical_id, physical_id) in providers.items()
    }


def _selected_collection(service, roots, name, **selection):
    return service.create_artifact_collection_from_selection(
        service.plan_artifact_collection_selection(MARKET, roots), name, **selection,
    )


def test_bb_new_outputs_keep_old_middle_and_exact_physical_versions(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("bb", {}))
    root = result.root_logical_artifact_ids[0]
    b1 = artifacts.load_artifact_head(MARKET, root).artifact_id
    seed = service.create_database_seed(MARKET, "BB seed")
    collection = _selected_collection(service, (root,), "Middle only", selected_outputs=(
        ArtifactCollectionOutputV1(root, "bb_middle", "bb_middle"),
    ))
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    old = service.load_database_revision(database.database_id)
    _historical_update(service, artifacts, historical, root)
    b2 = artifacts.load_artifact_head(MARKET, root).artifact_id
    assert not artifacts.load_artifact_by_id(MARKET, b1).frame["bb_middle"].equals(
        artifacts.load_artifact_by_id(MARKET, b2).frame["bb_middle"]
    )
    source_before = _stored(historical)
    plan = service.plan_database_artifact_addition(database.database_id, (root,))
    assert not plan.blocked, plan.blockers
    assert set(plan.added_column_names) == {"bb_lower_band", "bb_upper_band"}
    published = service.execute_database_content_edit(plan)
    values = service.load_database_revision(database.database_id).values_csv
    _assert_retained(old.values_csv, values)
    assert set(_columns(values)) == {*OHLCV, "bb_middle", "bb_lower_band", "bb_upper_band"}
    for name, provider in (("bb_middle", b1), ("bb_lower_band", b2), ("bb_upper_band", b2)):
        _assert_provider_column(artifacts, values, provider, name)
    _assert_providers(artifacts, published, {
        "bb_middle": (root, b1), "bb_lower_band": (root, b2), "bb_upper_band": (root, b2),
    }, {b1, b2})
    assert service.load_database_revision(database.database_id, database.revision_id) == old
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert _stored(historical) == source_before


def test_retained_sma_s1_accepts_derivative_d2_that_consumed_s2(tmp_path):
    service, artifacts, recipes, historical, sma_id, _seed, _collection, database = _setup(
        tmp_path, dependent=False,
    )
    old = service.load_database_revision(database.database_id)
    s1 = artifacts.load_artifact_head(MARKET, sma_id).artifact_id
    _historical_update(service, artifacts, historical, sma_id)
    s2 = artifacts.load_artifact_head(MARKET, sma_id).artifact_id
    result = _materialize(service, recipes, _derivative(_sma(3)))
    derivative_id = result.root_logical_artifact_ids[0]
    d2 = artifacts.load_artifact_head(MARKET, derivative_id).artifact_id
    metadata = artifacts.load_artifact_metadata(MARKET, d2)
    assert [(ref.artifact_id, ref.role, ref.output_name) for ref in metadata.recipe.source_artifacts] == [
        (s2, "source", "sma_3"),
    ]
    source_before = _stored(historical)
    plan = service.plan_database_artifact_addition(database.database_id, (derivative_id,))
    assert not plan.blocked, plan.blockers
    published = service.execute_database_content_edit(plan)
    values = service.load_database_revision(database.database_id).values_csv
    output = metadata.recipe.output_names[0]
    _assert_retained(old.values_csv, values)
    _assert_provider_column(artifacts, values, s1, "sma_3")
    _assert_provider_column(artifacts, values, d2, output)
    _assert_providers(artifacts, published, {
        "sma_3": (sma_id, s1), output: (derivative_id, d2),
    }, {s1, s2, d2})
    assert service.load_database_revision(database.database_id, database.revision_id) == old
    assert _stored(historical) == source_before


def test_removed_output_can_be_readded_from_current_provider(tmp_path):
    service, artifacts, _recipes, historical, root, _seed, _collection, database = _setup(
        tmp_path, dependent=False,
    )
    old = service.load_database_revision(database.database_id)
    s1 = artifacts.load_artifact_head(MARKET, root).artifact_id
    _historical_update(service, artifacts, historical, root)
    s2 = artifacts.load_artifact_head(MARKET, root).artifact_id
    source_before = _stored(historical)
    removal = service.plan_database_content_edit(
        database.database_id, remove_outputs=((root, "sma_3"),),
    )
    assert not removal.blocked, removal.blockers
    removed = service.execute_database_content_edit(removal)
    base = service.load_database_revision(database.database_id)
    _assert_retained(old.values_csv, base.values_csv, removed=("sma_3",))
    assert removed.selected_outputs == ()
    assert removed.to_dict()["value_provenance"]["outputs"] == []
    addition = service.plan_database_artifact_addition(database.database_id, (root,))
    assert not addition.blocked, addition.blockers
    assert addition.added_column_names == ("sma_3",)
    published = service.execute_database_content_edit(addition)
    values = service.load_database_revision(database.database_id).values_csv
    _assert_retained(base.values_csv, values)
    _assert_provider_column(artifacts, values, s2, "sma_3")
    assert _columns(values)["sma_3"] != _columns(old.values_csv)["sma_3"]
    _assert_providers(artifacts, published, {"sma_3": (root, s2)}, {s2})
    _assert_providers(artifacts, old.manifest, {"sma_3": (root, s1)}, {s1})
    assert service.load_database_revision(database.database_id, database.revision_id) == old
    assert service.load_database_revision(database.database_id, removed.revision_id) == base
    assert _stored(historical) == source_before


@pytest.mark.parametrize("route", ("artifact", "collection"))
def test_104_row_addition_requires_explicit_database_update(tmp_path, route):
    service, artifacts, recipes, historical, root, seed, _collection, database = _setup(
        tmp_path, dependent=False,
    )
    old = service.load_database_revision(database.database_id)
    old_provider = artifacts.load_artifact_head(MARKET, root).artifact_id
    _grow(service, historical, root)
    current_provider = artifacts.load_artifact_head(MARKET, root).artifact_id
    extra = _materialize(service, recipes, _sma(5))
    extra_id = extra.root_logical_artifact_ids[0]
    extra_provider = artifacts.load_artifact_head(MARKET, extra_id).artifact_id
    collection = _selected_collection(service, (extra_id,), "104 rows")

    def addition():
        if route == "artifact":
            return service.plan_database_artifact_addition(database.database_id, (extra_id,))
        return service.plan_database_collection_addition(database.database_id, collection.collection_id)

    before = _stored(tmp_path)
    if route == "artifact":
        refused = addition()
        assert refused.blocked and any("row count" in reason for reason in refused.blockers)
        assert refused.values_csv == old.values_csv
        with pytest.raises(DataManagerCreationError):
            service.execute_database_content_edit(refused)
    else:
        with pytest.raises(DataManagerCreationError, match="row count"):
            addition()
    assert _stored(tmp_path) == before
    source_before = _stored(historical)
    update = service.plan_database_update(database.database_id)
    assert update.mode == "APPEND" and not update.blocked, update.blockers
    appended = service.execute_database_append(update).database_revision
    extended = service.load_database_revision(database.database_id)
    assert appended.row_count == 104
    assert extended.values_csv.startswith(old.values_csv)
    _assert_exact_graph(artifacts, appended)
    segments = appended.to_dict()["value_provenance"]["outputs"]
    axis = tuple(map(int, _columns(extended.values_csv)["ts_ms"]))
    assert {(item["artifact_id"], item["first_timestamp_ms"], item["last_timestamp_ms"])
            for item in segments} == {
        (old_provider, axis[0], axis[95]), (current_provider, axis[96], axis[103]),
    }
    plan = addition()
    assert not plan.blocked, plan.blockers
    published = service.execute_database_content_edit(plan)
    values = service.load_database_revision(database.database_id).values_csv
    assert published.row_count == 104 and len(_columns(values)["ts_ms"]) == 104
    _assert_retained(extended.values_csv, values)
    _assert_provider_column(artifacts, values, extra_provider, "sma_5")
    _assert_exact_graph(artifacts, published)
    assert service.load_database_revision(database.database_id, database.revision_id) == old
    assert service.load_database_seed(seed.seed_id) == seed
    assert _stored(historical) == source_before


def test_104_row_collection_build_requires_explicit_seed_append(tmp_path):
    service, artifacts, _recipes, historical, root, seed, collection, database = _setup(
        tmp_path, dependent=False,
    )
    old = service.load_database_revision(database.database_id)
    seed_values = service.creation_store.load_seed_values(seed.seed_id)
    _grow(service, historical, root)
    plan = service.plan_artifact_collection_selection(
        MARKET, (root,), collection_id=collection.collection_id,
        expected_revision_id=collection.revision_id,
    )
    current = service.edit_artifact_collection_from_selection(
        collection.collection_id, plan, expected_revision_id=collection.revision_id,
    )
    before = _stored(tmp_path)
    readiness = service.assess_database_readiness(seed.seed_id, current.collection_id)
    assert not readiness.ready and any("row count" in reason for reason in readiness.blockers)
    with pytest.raises(DataManagerCreationError, match="row count"):
        service.build_database_revision(seed.seed_id, current.collection_id)
    assert _stored(tmp_path) == before
    source_before = _stored(historical)
    appended = service.execute_database_seed_append(service.plan_database_seed_append(seed.seed_id))
    assert appended.row_count == 104
    assert service.creation_store.load_seed_values(seed.seed_id).startswith(seed_values)
    published = service.build_database_revision(seed.seed_id, current.collection_id)
    values = service.load_database_revision(published.database_id).values_csv
    assert published.row_count == 104 and len(_columns(values)["ts_ms"]) == 104
    _assert_provider_column(artifacts, values, artifacts.load_artifact_head(MARKET, root).artifact_id, "sma_3")
    seed_columns = _columns(service.creation_store.load_seed_values(seed.seed_id))
    for name in OHLCV:
        np.testing.assert_array_equal(np.array(_columns(values)[name], dtype=float),
                                      np.array(seed_columns[name], dtype=float))
    _assert_exact_graph(artifacts, published)
    assert service.load_database_revision(database.database_id) == old
    assert service.load_artifact_collection(collection.collection_id, collection.revision_id) == collection
    assert _stored(historical) == source_before


def test_existing_build_preserves_append_provider_segments_with_identical_payload(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)

    def integer_source(rows):
        _append(historical, rows=rows)
        source_rows = list(csv.reader(StringIO(OHLCVStore(historical).csv_path(MARKET).read_text())))
        for index, row in enumerate(source_rows[1:]):
            row[1:] = [str(100 + index), str(102 + index), str(99 + index),
                       str(101 + index), str(1000 + 2 * index)]
        _publish_raw(historical, source_rows)
        service.invalidate_source(MARKET)

    integer_source(96)
    result = _materialize(service, recipes, _sma(1))
    root = result.root_logical_artifact_ids[0]
    provider96 = artifacts.load_artifact_head(MARKET, root).artifact_id
    seed = service.create_database_seed(MARKET, "Integer SMA1 seed")
    collection = _selected_collection(service, (root,), "Integer SMA1 collection")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    old = service.load_database_revision(database.database_id)

    integer_source(104)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (root,)))
    provider104 = artifacts.load_artifact_head(MARKET, root).artifact_id
    assert provider104 != provider96
    update = service.plan_database_update(database.database_id)
    assert update.mode == "APPEND" and not update.blocked, update.blockers
    appended = service.execute_database_append(update).database_revision
    retained = service.load_database_revision(database.database_id)
    assert appended.row_count == 104 and retained.values_csv.startswith(old.values_csv)
    evidence = appended.to_dict()["value_provenance"]
    axis = tuple(map(int, _columns(retained.values_csv)["ts_ms"]))
    assert len(evidence["outputs"]) == 2
    assert {(item["column_name"], item["artifact_id"],
             item["first_timestamp_ms"], item["last_timestamp_ms"])
            for item in evidence["outputs"]} == {
        ("sma_1", provider96, axis[0], axis[95]),
        ("sma_1", provider104, axis[96], axis[103]),
    }
    _assert_exact_graph(artifacts, appended)
    seed, collection = _refresh_build_targets(service, seed, collection)
    assert seed.row_count == collection.source_ohlcv.row_count == 104
    source_before = _stored(historical)
    # A fresh build proves the incoming payload is byte-identical, isolating
    # retained attribution from numeric formatting or historical cell changes.
    fresh = service.build_database_revision(seed.seed_id, collection.collection_id)
    assert service.load_database_revision(fresh.database_id).values_csv == retained.values_csv
    rebuilt = service.build_database_revision(
        seed.seed_id, collection.collection_id, database_id=database.database_id,
    )
    assert rebuilt.previous_revision_id == appended.revision_id
    assert service.load_database_revision(database.database_id).values_csv == retained.values_csv
    assert service.load_database_revision(database.database_id, database.revision_id) == old
    assert service.load_database_revision(database.database_id, appended.revision_id) == retained
    assert _stored(historical) == source_before
    assert rebuilt.to_dict()["value_provenance"] == evidence


def test_collection_branch_hash_change_retains_old_physical_provider(tmp_path):
    service, artifacts, recipes, historical, sma_id, seed, collection, database = _setup(
        tmp_path, dependent=False,
    )
    old = service.load_database_revision(database.database_id)
    s1 = artifacts.load_artifact_head(MARKET, sma_id).artifact_id
    _historical_update(service, artifacts, historical, sma_id)
    s2 = artifacts.load_artifact_head(MARKET, sma_id).artifact_id
    branch = _materialize(service, recipes, _derivative(_sma(3)))
    d_id = branch.root_logical_artifact_ids[0]
    d2 = artifacts.load_artifact_head(MARKET, d_id).artifact_id
    assert collection.source_ohlcv.csv_sha256 != branch.source_ohlcv.csv_sha256
    assert DataManagerCreationWorkflow._same_coverage(collection.source_ohlcv, branch.source_ohlcv)
    source_before = _stored(historical)
    revised = service.add_artifact_collection_branches(collection.collection_id, branch)
    output = artifacts.load_artifact_metadata(MARKET, d2).recipe.output_names[0]
    providers = {"sma_3": (sma_id, s1), output: (d_id, d2)}
    _assert_providers(artifacts, revised, providers, {s1, s2, d2})
    published = service.build_database_revision(seed.seed_id, revised.collection_id)
    values = service.load_database_revision(published.database_id).values_csv
    _assert_retained(old.values_csv, values)
    _assert_provider_column(artifacts, values, s1, "sma_3")
    _assert_provider_column(artifacts, values, d2, output)
    _assert_providers(artifacts, published, providers, {s1, s2, d2})
    assert service.load_artifact_collection(collection.collection_id, collection.revision_id) == collection
    assert service.load_database_revision(database.database_id) == old
    assert _stored(historical) == source_before


@pytest.mark.parametrize("rows", (88, 104))
def test_collection_branch_row_count_mismatch_is_read_only(tmp_path, rows):
    service, _artifacts, recipes, historical, _root, _seed, collection, _database = _setup(
        tmp_path, dependent=False,
    )
    _append(historical, rows=rows)
    service.invalidate_source(MARKET)
    branch = _materialize(service, recipes, _sma(5))
    assert branch.source_ohlcv.row_count == rows
    assert collection.source_ohlcv.row_count == 96
    before = _stored(tmp_path)
    with pytest.raises(DataManagerCreationError, match="incompatible"):
        service.add_artifact_collection_branches(collection.collection_id, branch)
    assert _stored(tmp_path) == before
    assert service.load_artifact_collection(collection.collection_id) == collection


def test_smaller_ohlcv_conflicts_with_database_and_seed_without_snapshot_writes(tmp_path):
    service, _artifacts, _recipes, historical, _root, seed, _collection, database = _setup(tmp_path)
    old = service.load_database_revision(database.database_id)
    seed_values = service.creation_store.load_seed_values(seed.seed_id)
    _append(historical, rows=88)
    service.invalidate_source(MARKET)
    assert len(OHLCVStore(historical).read(MARKET)) == 88
    before = _stored(tmp_path)
    update = service.plan_database_update(database.database_id)
    assert update.blocked and update.mode == "BLOCKED"
    assert update.status == "SOURCE_INVALID"
    assert any("coverage conflict" in reason for reason in update.blockers)
    with pytest.raises(DataManagerOperationError):
        service.execute_database_append(update)
    with pytest.raises(DataManagerCreationError, match="coverage conflict"):
        service.plan_database_seed_append(seed.seed_id)
    status = service.reconcile_update_status(force=True)
    advisory = next(item for item in status.databases if item.database_id == database.database_id)
    assert advisory.status == "SOURCE_INVALID" and advisory.status != "CURRENT"
    assert any("coverage conflict" in reason for reason in advisory.reasons)
    assert service.database_seed_newer_source_available(seed.seed_id) is None
    assert service.validate_database_seed(seed.seed_id)[0]
    assert service.load_database_revision(database.database_id) == old
    assert service.load_database_seed(seed.seed_id) == seed
    assert service.creation_store.load_seed_values(seed.seed_id) == seed_values
    assert _stored(tmp_path) == before


@pytest.mark.parametrize("field,value", (
    ("exchange", "binance"), ("market_type", "spot"),
    ("symbol", "ETHUSDT"), ("timeframe", "5m"),
    ("row_count", 88), ("first_timestamp_ms", 60_000),
    ("last_timestamp_ms", 96 * 60_000),
))
def test_three_rule_helpers_reject_each_independent_mismatch(field, value):
    source = OHLCVSourceFingerprintV1(
        MARKET, "a" * 64, "b" * 64, 96, 0, 95 * 60_000, "committed", "ok", "1.0",
    )
    if field in {"exchange", "market_type", "symbol", "timeframe"}:
        candidate = replace(source, market_id=replace(MARKET, **{field: value}))
        diagnostic = "identity"
    else:
        candidate = replace(source, **{field: value})
        diagnostic = "row count" if field == "row_count" else "timestamps"
    # Every case changes one compatibility component only.
    assert not DataManagerCreationWorkflow._same_coverage(source, candidate)
    assert not DataManagerCreationWorkflow._same_coverage(candidate, source)
    with pytest.raises(DataManagerCreationError, match=diagnostic):
        DataManagerCreationWorkflow._require_coverage(
            source.market_id, source.row_count, source.first_timestamp_ms,
            source.last_timestamp_ms, candidate,
        )


@pytest.mark.parametrize("field", ("csv_sha256", "sidecar_sha256"))
def test_three_rule_helpers_accept_hash_difference(field):
    source = OHLCVSourceFingerprintV1(
        MARKET, "a" * 64, "b" * 64, 96, 0, 95 * 60_000, "committed", "ok", "1.0",
    )
    candidate = replace(source, **{field: "c" * 64})
    assert source != candidate
    assert DataManagerCreationWorkflow._same_coverage(source, candidate)
    assert DataManagerCreationWorkflow._same_coverage(candidate, source)
    DataManagerCreationWorkflow._require_coverage(
        source.market_id, source.row_count, source.first_timestamp_ms,
        source.last_timestamp_ms, candidate,
    )


def _legacy_snapshot(service, recipes):
    from leonardo.data_manager import DatabaseRevisionManifestV3
    from leonardo.data_manager.creation_models import deterministic_hash

    roots = tuple(_materialize(service, recipes, _leaf(tool, {"period": period})).root_logical_artifact_ids[0]
                  for tool, period in (("sma", 3), ("ema", 4)))
    collection = _selected_collection(service, roots, "Legacy inputs")
    seed = service.create_database_seed(MARKET, "Legacy seed")
    source = service.build_database_revision(seed.seed_id, collection.collection_id)
    values = service.load_database_revision(source.database_id).values_csv
    identity = service.creation_store.new_database_id()
    definition = replace(service.load_database_definition(source.database_id), database_id=identity)
    payload = source.to_dict(include_revision_id=False)
    payload.pop("value_provenance")
    payload.update(schema_version="3.0", database_id=identity, previous_revision_id=None)
    payload["revision_id"] = deterministic_hash(payload)
    legacy = DatabaseRevisionManifestV3.from_dict(payload)
    service.creation_store.publish_database_revision(definition, legacy, values, expected_head_revision_id=None)
    assert len(service.list_database_revisions(identity)) == 1
    return legacy, collection, roots, values


@pytest.mark.parametrize("remove_all", (False, True))
def test_legacy_snapshot_edits_survive_app_deleted_original_artifacts(tmp_path, remove_all):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    legacy, collection, roots, before = _legacy_snapshot(service, recipes)
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    noop = service.plan_database_content_edit(legacy.database_id)
    assert noop.no_op and not noop.blocked
    assert service.execute_database_content_edit(noop) is None
    outputs = tuple((o.logical_artifact_id, o.output_name) for o in legacy.selected_outputs)
    plan = service.plan_database_content_edit(legacy.database_id, remove_outputs=outputs if remove_all else outputs[:1])
    assert not plan.blocked
    published = service.execute_database_content_edit(plan)
    assert published.schema_version == "4.0"
    _assert_retained(before, service.load_database_revision(legacy.database_id).values_csv,
                     removed=plan.removed_column_names)
    provenance = published.to_dict()["value_provenance"]
    assert provenance["members"] == provenance["dependency_edges"] == []
    if remove_all:
        assert provenance == {"members": [], "dependency_edges": [], "outputs": []}
    else:
        assert provenance["legacy_revisions"] == [legacy.to_dict()]
        assert all(segment["legacy_revision_id"] == legacy.revision_id and "artifact_id" not in segment
                   for segment in provenance["outputs"])
    assert service.load_database_revision(legacy.database_id, legacy.revision_id).values_csv == before
    assert service.load_database_revision(legacy.database_id, legacy.revision_id).manifest == legacy


def test_legacy_snapshot_retains_legacy_evidence_beside_exact_new_column_and_append(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    legacy, _collection, roots, before = _legacy_snapshot(service, recipes)
    extra = _materialize(service, recipes, _leaf("sma", {"period": 5})).root_logical_artifact_ids[0]
    physical = artifacts.load_artifact_head(MARKET, extra).artifact_id
    edited = service.execute_database_content_edit(service.plan_database_artifact_addition(legacy.database_id, (extra,)))
    first = edited.to_dict()["value_provenance"]
    assert first["legacy_revisions"] == [legacy.to_dict()]
    assert {b["artifact_id"] for b in first["outputs"] if "artifact_id" in b} == {physical}
    assert len([b for b in first["outputs"] if "legacy_revision_id" in b]) == 2
    _assert_retained(before, service.load_database_revision(legacy.database_id).values_csv)
    prefix = service.load_database_revision(legacy.database_id).values_csv
    _append(historical, rows=104)
    service.invalidate_source(MARKET)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, (*roots, extra)))
    updated = service.execute_database_append(service.plan_database_update(legacy.database_id)).database_revision
    combined = updated.to_dict()["value_provenance"]
    assert combined["legacy_revisions"] == first["legacy_revisions"]
    assert all(segment in combined["outputs"] for segment in first["outputs"])
    suffix = [b for b in combined["outputs"] if b not in first["outputs"]]
    assert len(suffix) == 3
    for segment in suffix:
        assert segment["first_timestamp_ms"] > legacy.last_timestamp_ms
        assert "legacy_revision_id" not in segment
        assert segment["artifact_id"] == artifacts.load_artifact_head(MARKET, segment["logical_artifact_id"]).artifact_id
    assert service.load_database_revision(legacy.database_id).values_csv.startswith(prefix)
    assert service.load_database_revision(legacy.database_id, legacy.revision_id).values_csv == before


def test_legacy_collection_validation_uses_saved_evidence_without_live_owner(tmp_path):
    from leonardo.artifacts.service import _io_path
    from leonardo.data_manager import ArtifactCollectionRevisionV1
    from leonardo.data_manager.creation_models import deterministic_hash
    from tests.data_manager_test.test_update_workflow import _angle

    service, artifacts, recipes, _historical = _domain(tmp_path)
    sma = _sma()
    derivative = _derivative(sma)
    recipes.save_recipe(sma)
    recipes.save_recipe(derivative)
    current = service.create_artifact_collection(_materialize(service, recipes, _angle(derivative)), "Legacy recovery")
    payload = current.to_dict(include_revision_id=False)
    payload.pop("value_provenance")
    payload.update(schema_version="1.0", previous_revision_id=current.revision_id)
    payload["revision_id"] = deterministic_hash(payload)
    legacy = ArtifactCollectionRevisionV1.from_dict(payload)
    service.creation_store.save_collection_revision(legacy, expected_head_revision_id=current.revision_id)
    key = next(m.version_key for m in legacy.members if m.tool_key == "derivative")
    _io_path(artifacts._store.head_path(MARKET, key.logical_artifact_id)).unlink()
    _io_path(artifacts._store.version_record_path(MARKET, key.logical_artifact_id, key.artifact_id)).unlink()
    before = _stored(tmp_path)
    plan = service.plan_artifact_collection_update(legacy.collection_id)
    assert not plan.blocked and plan.nodes == ()
    assert _stored(tmp_path) == before
    assert service.load_artifact_collection(legacy.collection_id) == legacy



@pytest.mark.parametrize("schema", ("1.0", "2.0", "3.0", "4.0"))
def test_a2_dependency_snapshot_survives_deleted_lineage_and_second_edit(tmp_path, schema):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    service, artifacts, recipes, _historical = _domain(tmp_path)
    original, collection, _roots, before = _a2_snapshot(service, recipes, schema, dependent=True)
    service.delete_artifact_collection(collection.collection_id)
    for member in reversed(collection.members):
        service.delete_managed_artifact(MARKET, member.version_key.logical_artifact_id)
    baseline = service.plan_database_content_edit(original.database_id)
    removal = service.plan_database_content_edit(original.database_id, remove_columns=(baseline.selected_outputs[0].column_name,))
    first = service.execute_database_content_edit(removal)
    extra = _materialize(service, recipes, _leaf("ema", {"period": 5})).root_logical_artifact_ids[0]
    second = service.execute_database_content_edit(service.plan_database_artifact_addition(original.database_id, (extra,)))
    _assert_retained(before, service.load_database_revision(original.database_id).values_csv,
                     removed=removal.removed_column_names)
    assert first.first_timestamp_ms == second.first_timestamp_ms == original.first_timestamp_ms
    assert first.last_timestamp_ms == second.last_timestamp_ms == original.last_timestamp_ms
    assert first.row_count == second.row_count == original.row_count
    if schema != "4.0":
        segments = second.to_dict()["value_provenance"]["outputs"]
        assert any("legacy_revision_id" in b for b in segments)
        assert any("artifact_id" in b for b in segments)
