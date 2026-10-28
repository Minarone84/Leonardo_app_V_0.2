from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, StringIO

import pandas as pd
import pytest

from leonardo.artifacts import LoadedArtifact
from leonardo.data import MarketId
from leonardo.data_manager import (
    DatabaseSeedV1, DataManagerCreationError, DataManagerCreationStore,
)
from leonardo.data_manager.creation_models import (
    database_revision_from_dict, deterministic_hash,
)
from leonardo.data_manager.creation_store import _snapshot_rows
from leonardo.financial_tools import FinancialToolCalculationResult, calculate_financial_tool
from leonardo.ohlcv.store import OHLCVStore

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.seed_fixtures import create_legacy_seed_v2
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize, _persistence_bytes
from tests.data_manager_test.test_update_workflow import MARKET, _domain


def _csv_rows(values):
    return list(csv.reader(StringIO(values.decode("utf-8"))))


def _csv_bytes(rows):
    output = StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")


def _source_hashes(historical):
    store = OHLCVStore(historical)
    return tuple(sha256(path.read_bytes()).hexdigest() for path in (
        store.csv_path(MARKET), store.sidecar_path(MARKET),
    ))


def _pattern_artifact(service, artifacts, recipes, pattern, *, period=3):
    dataset = service._loader.load(MARKET)
    raw = pd.read_csv(dataset.csv_path, float_precision="round_trip")
    template = calculate_financial_tool("sma", raw, {"period": period})
    frame = template.to_frame()
    name = template.output_names[0]
    positions = {
        "leading": {0, 1}, "trailing": {len(frame) - 2, len(frame) - 1},
        "interior": {len(frame) // 2}, "all": set(range(len(frame))),
    }[pattern]
    frame[name] = pd.Series(
        [float("nan") if index in positions else float(index + 1) for index in range(len(frame))],
        dtype=frame[name].dtype,
    )
    result = FinancialToolCalculationResult(
        tool_key=template.tool_key, kind=template.kind, parameters=template.parameters,
        bindings=template.bindings, output_names=template.output_names, frame=frame,
    )
    recipe = _leaf("sma", {"period": period})
    recipes.save_recipe(recipe)
    source = artifacts.capture_accepted_source(MARKET)
    candidate = artifacts.prepare_managed_calculation(
        MARKET, recipe.recipe_id, result, expected_source=source,
    )
    artifacts.publish_managed_artifact_graph((candidate,), expected_source=source)
    loaded = artifacts.load_artifact_by_id(MARKET, candidate.metadata.artifact_id)
    pd.testing.assert_frame_equal(loaded.frame, frame)
    return candidate.logical_artifact_id, loaded.frame


def _collection(service, roots):
    plan = service.plan_artifact_collection_selection(MARKET, roots)
    assert set(plan.root_logical_artifact_ids) == set(roots)
    return service.create_artifact_collection_from_selection(plan, "NaN coverage")


def _compose(service, seed, roots, route):
    if route == "build":
        collection = _collection(service, roots)
        readiness = service.assess_database_readiness(seed.seed_id, collection.collection_id)
        assert readiness.ready, readiness.blockers
        assert readiness.warmup_excluded_rows == 0
        return service.build_database_revision(seed.seed_id, collection.collection_id)
    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "NaN Database")
    )
    if route == "individual":
        plan = service.plan_database_artifact_addition(database.database_id, roots)
    else:
        collection = _collection(service, roots)
        plan = service.plan_database_collection_addition(database.database_id, collection.collection_id)
    assert not plan.blocked, plan.blockers
    return service.execute_database_content_edit(plan)


def _assert_database(service, seed, manifest, expected_artifacts):
    loaded = DataManagerCreationStore(service.creation_store.root_dir).load_database_revision(
        manifest.database_id, manifest.revision_id
    )
    assert loaded.manifest == manifest
    rows = _csv_rows(loaded.values_csv)
    base = _csv_rows(service._creation._seed_base_values(seed))
    assert [row[:len(base[0])] for row in rows] == base
    timestamps = tuple(int(row[0]) for row in base[1:])
    frame = pd.read_csv(BytesIO(loaded.values_csv))
    assert tuple(frame.ts_ms) == timestamps
    assert manifest.row_count == len(timestamps)
    assert manifest.first_timestamp_ms == timestamps[0]
    assert manifest.last_timestamp_ms == timestamps[-1]
    assert manifest.column_count == len(rows[0])
    assert manifest.values_sha256 == sha256(loaded.values_csv).hexdigest()
    assert manifest.source_ohlcv == seed.source_ohlcv
    assert set(manifest.column_mapping.values()) == set(rows[0])
    assert manifest.selection_sources
    assert {name for source in manifest.selection_sources for name in source["column_names"]} == {
        output.column_name for output in manifest.selected_outputs
    }
    members = {member.version_key.logical_artifact_id: member for member in manifest.members}
    for output in manifest.selected_outputs:
        artifact = expected_artifacts[output.logical_artifact_id]
        expected = artifact.set_index("ts_ms").loc[list(timestamps), output.output_name]
        assert frame[output.column_name].isna().tolist() == expected.isna().tolist()
        column = rows[0].index(output.column_name)
        assert [row[column] == "" for row in rows[1:]] == expected.isna().tolist()
        pd.testing.assert_series_equal(
            frame[output.column_name], expected.reset_index(drop=True),
            check_names=False, check_dtype=False, rtol=1e-6,
        )
        member = members[output.logical_artifact_id]
        metadata = service._artifacts.load_artifact_by_id(MARKET, member.version_key.artifact_id).metadata
        assert member.values_sha256 == metadata.values_sha256
    return loaded


@pytest.mark.parametrize("route", ("build", "individual", "collection"))
@pytest.mark.parametrize("pattern", ("leading", "trailing", "interior", "all"))
def test_numeric_nan_patterns_keep_full_axis_and_base_tokens(tmp_path, route, pattern):
    service, artifacts, recipes, historical = _domain(tmp_path)
    before = _source_hashes(historical)
    logical_id, frame = _pattern_artifact(service, artifacts, recipes, pattern)
    seed = service.create_database_seed(MARKET, "Full Seed")
    manifest = _compose(service, seed, (logical_id,), route)
    _assert_database(service, seed, manifest, {logical_id: frame})
    assert manifest.row_count == seed.row_count == 96
    assert _source_hashes(historical) == before


@pytest.mark.parametrize("period, missing", ((3, 2), (120, 96)))
@pytest.mark.parametrize("route", ("build", "individual", "collection"))
def test_real_sma_warmup_and_all_nan_are_usable(tmp_path, period, missing, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    before = _source_hashes(historical)
    result = _materialize(service, recipes, _leaf("sma", {"period": period}))
    logical_id = result.root_logical_artifact_ids[0]
    head = artifacts.load_artifact_head(MARKET, logical_id)
    frame = artifacts.load_artifact_by_id(MARKET, head.artifact_id).frame
    assert frame[f"sma_{period}"].isna().tolist() == [True] * missing + [False] * (96 - missing)
    collection = service.create_artifact_collection(result, "Real SMA")
    validation = service.validate_artifact_collection(collection.collection_id)
    assert validation.database_ready
    seed = service.create_database_seed(MARKET, "Full Seed")
    readiness = service.assess_database_readiness(seed.seed_id, collection.collection_id)
    assert readiness.ready and readiness.row_count == 96 and readiness.warmup_excluded_rows == 0
    manifest = _compose(service, seed, (logical_id,), route)
    _assert_database(service, seed, manifest, {logical_id: frame})
    assert _source_hashes(historical) == before


def test_retained_nan_columns_survive_add_remove_and_reconciliation(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    before = _source_hashes(historical)
    first_id, first_frame = _pattern_artifact(service, artifacts, recipes, "leading")
    seed = service.create_database_seed(MARKET, "Full Seed")
    first = _compose(service, seed, (first_id,), "individual")
    original = service.load_database_revision(first.database_id)
    second_id, second_frame = _pattern_artifact(service, artifacts, recipes, "interior", period=4)
    collection = _collection(service, (second_id,))
    plan = service.plan_database_collection_addition(first.database_id, collection.collection_id)
    assert not plan.blocked, plan.blockers
    second = service.execute_database_content_edit(plan)
    _assert_database(service, seed, second, {first_id: first_frame, second_id: second_frame})
    plan = service.plan_database_content_edit(
        first.database_id, remove_outputs=((second_id, "sma_4"),)
    )
    assert not plan.blocked, plan.blockers
    third = service.execute_database_content_edit(plan)
    final = _assert_database(service, seed, third, {first_id: first_frame})
    assert final.values_csv == original.values_csv
    assert service.load_database_revision(first.database_id, first.revision_id) == original
    snapshot = service.reconcile_update_status(force=True)
    assert next(item for item in snapshot.databases if item.database_id == first.database_id).status == "CURRENT"
    update = service.plan_database_update(first.database_id)
    assert not update.blocked and update.mode == "CURRENT"
    catalog = service.scan_product_catalogs()
    assert next(item for item in catalog.databases if item.definition.database_id == first.database_id).valid
    assert _source_hashes(historical) == before


@pytest.mark.parametrize("column", ("ts_ms", "open", "high", "low", "close", "volume", "calculated"))
@pytest.mark.parametrize("token", ("", " ", "nan", "NaN", "null", "inf", "-inf", "Infinity"))
def test_only_declared_calculated_empty_cells_are_permitted(column, token):
    header = ["ts_ms", "open", "high", "low", "close", "volume", "calculated"]
    row = ["1", "1", "2", "0", "1", "3", "4"]
    row[header.index(column)] = token
    payload = _csv_bytes([header, row])
    if column == "calculated" and token == "":
        assert _snapshot_rows(payload, nullable_columns=("calculated",))[1][0][-1] == ""
    else:
        with pytest.raises(DataManagerCreationError):
            _snapshot_rows(payload, nullable_columns=("calculated",))
    with pytest.raises(DataManagerCreationError):
        _snapshot_rows(payload)


@pytest.mark.parametrize("version", ("1.0", "2.0", "3.0"))
def test_nullable_metadata_versions_and_payload_hash_remain_authoritative(tmp_path, version):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    logical_id, _frame = _pattern_artifact(service, artifacts, recipes, "leading")
    collection = _collection(service, (logical_id,))
    seed = service.create_database_seed(MARKET, "Full Seed")
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    values = service.load_database_revision(manifest.database_id).values_csv
    payload = manifest.to_dict()
    payload["schema_version"] = version
    payload.pop("value_provenance")
    if version != "3.0":
        del payload["selection_sources"]
    if version == "1.0":
        for key in ("members", "dependency_edges", "selected_outputs", "collection_sources"):
            del payload[key]
        payload.update(
            collection_id=collection.collection_id, collection_revision_id=collection.revision_id,
            collection_manifest_hash=sha256(collection.canonical_json_bytes()).hexdigest(),
            artifact_version_keys=[{
                "logical_artifact_id": member.version_key.logical_artifact_id,
                "artifact_id": member.version_key.artifact_id,
            } for member in manifest.members],
            artifact_payload_hashes=[member.values_sha256 for member in manifest.members],
            portable_recipe_ids=[member.portable_recipe_id for member in manifest.members],
        )
        rows = _csv_rows(values)
        rows[0][-1] = "mapped_sma"
        values = _csv_bytes(rows)
        payload["column_mapping"]["sma_3"] = "mapped_sma"
        payload["values_sha256"] = sha256(values).hexdigest()
    payload.pop("revision_id")
    payload["revision_id"] = deterministic_hash(payload)
    candidate = database_revision_from_dict(payload)
    service.creation_store._validate_database_values(candidate, values)
    with pytest.raises(DataManagerCreationError, match="hash"):
        service.creation_store._validate_database_values(candidate, values + b"\n")
    rows = _csv_rows(values)
    rows[1][1] = ""
    invalid = _csv_bytes(rows)
    payload["values_sha256"] = sha256(invalid).hexdigest()
    payload.pop("revision_id")
    payload["revision_id"] = deterministic_hash(payload)
    with pytest.raises(DataManagerCreationError, match="missing or nonfinite"):
        service.creation_store._validate_database_values(database_revision_from_dict(payload), invalid)


@pytest.mark.parametrize("mode", ("missing", "duplicate"))
def test_invalid_artifact_timestamps_block_both_routes_without_publication(tmp_path, monkeypatch, mode):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    collection = service.create_artifact_collection(result, "Timestamp coverage")
    seed = service.create_database_seed(MARKET, "Full Seed")
    database = service.execute_seed_only_database_creation(service.plan_seed_only_database_creation(seed.seed_id, "Base"))
    before = _persistence_bytes(service.creation_store.root_dir)
    head = artifacts.load_artifact_head(MARKET, logical_id)
    loaded = artifacts.load_artifact_by_id(MARKET, head.artifact_id)
    frame = loaded.frame.drop(index=20).reset_index(drop=True) if mode == "missing" else pd.concat(
        [loaded.frame, loaded.frame.iloc[[20]]], ignore_index=True
    )
    original = artifacts.load_artifact_by_id

    def invalid_timestamps(market, artifact_id):
        if market == MARKET and artifact_id == head.artifact_id:
            return LoadedArtifact(loaded.metadata, frame, loaded.analysis)
        return original(market, artifact_id)

    monkeypatch.setattr(artifacts, "load_artifact_by_id", invalid_timestamps)
    plan = service.plan_database_artifact_addition(database.database_id, (logical_id,))
    assert plan.blocked
    with pytest.raises(DataManagerCreationError):
        service.execute_database_content_edit(plan)
    readiness = service.assess_database_readiness(seed.seed_id, collection.collection_id)
    assert not readiness.ready and readiness.row_count == 0
    with pytest.raises(DataManagerCreationError):
        service.build_database_revision(seed.seed_id, collection.collection_id)
    assert _persistence_bytes(service.creation_store.root_dir) == before


def test_other_market_collection_cannot_compose_with_seed(tmp_path):
    service, _artifacts, recipes, historical = _domain(tmp_path)
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(result, "BTC outputs")
    other = MarketId("bybit", "linear", "ETHUSDT", "1m")
    _accepted_dataset(historical, market=other)
    seed = service.create_database_seed(other, "ETH Seed")
    before = _persistence_bytes(service.creation_store.root_dir)
    readiness = service.assess_database_readiness(seed.seed_id, collection.collection_id)
    assert not readiness.ready and any("MarketId" in reason for reason in readiness.blockers)
    with pytest.raises(DataManagerCreationError):
        service.build_database_revision(seed.seed_id, collection.collection_id)
    assert _persistence_bytes(service.creation_store.root_dir) == before


def _precise_source(historical):
    store = OHLCVStore(historical)
    path, sidecar = store.csv_path(MARKET), store.sidecar_path(MARKET)
    rows = _csv_rows(path.read_bytes())
    for row in rows[1:]:
        row[1:] = ["99.80000000000000000000000001", "1.010000000000000000000001e+2",
                   "+99.000000000000000", "100.000000000000000000000001", "1.000000000000000000000001E+3"]
    path.write_bytes(_csv_bytes(rows))
    csv_stat, sidecar_stat = path.stat(), sidecar.stat()
    store.reconstruct_sidecar(
        MARKET, expected_csv_size=csv_stat.st_size, expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=sha256(path.read_bytes()).hexdigest(),
        expected_sidecar_size=sidecar_stat.st_size, expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=sha256(sidecar.read_bytes()).hexdigest(), reconstruction_reason="Task1080 precise fixture",
    )
    sidecar_stat = sidecar.stat()
    store.publish_validation(
        MARKET, expected_csv_size=csv_stat.st_size, expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=sha256(path.read_bytes()).hexdigest(),
        expected_sidecar_size=sidecar_stat.st_size, expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=sha256(sidecar.read_bytes()).hexdigest(), status="ok", row_count=len(rows)-1,
        first_timestamp_ms=int(rows[1][0]), last_timestamp_ms=int(rows[-1][0]), warnings=(), issue_codes=(),
        error_count=0, warning_count=0, validator="task-1080-test",
    )
    return rows


@pytest.mark.parametrize("seed_kind", ("new_v2", "legacy_v1", "legacy_v2"))
@pytest.mark.parametrize("route", ("build", "individual", "collection"))
def test_precise_tokens_and_legacy_formats_survive_aligned_composition(tmp_path, seed_kind, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    raw_rows = _precise_source(historical)
    before = _source_hashes(historical)
    dataset = service._loader.load(MARKET)
    if seed_kind == "new_v2":
        seed = service.create_database_seed(MARKET, "Precise full Seed")
        expected = raw_rows
    else:
        expected = raw_rows
        legacy = create_legacy_seed_v2(
            service, MARKET, "Precise legacy Seed", start_ms=dataset.ts_ms[0], end_ms=dataset.ts_ms[-1],
            columns=("open", "high", "low", "close", "volume"),
        )
        if seed_kind == "legacy_v1":
            payload = legacy.to_dict()
            for key in ("row_count", "column_count", "values_sha256"):
                del payload[key]
            payload["schema_version"] = "1.0"
            payload["seed_id"] = service.creation_store.new_seed_id()
            seed = service.creation_store.save_seed(DatabaseSeedV1.from_dict(payload))
        else:
            seed = legacy
    result = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    logical_id = result.root_logical_artifact_ids[0]
    head = artifacts.load_artifact_head(MARKET, logical_id)
    frame = artifacts.load_artifact_by_id(MARKET, head.artifact_id).frame
    assert _csv_rows(service._creation._seed_base_values(seed)) == expected
    manifest = _compose(service, seed, (logical_id,), route)
    loaded = _assert_database(service, seed, manifest, {logical_id: frame})
    assert [row[:6] for row in _csv_rows(loaded.values_csv)] == expected
    plan = service.plan_database_content_edit(manifest.database_id, remove_outputs=((logical_id, "sma_3"),))
    assert not plan.blocked, plan.blockers
    removed = service.execute_database_content_edit(plan)
    assert _csv_rows(service.load_database_revision(removed.database_id).values_csv) == expected
    assert _source_hashes(historical) == before


@pytest.mark.parametrize("source_change", ("changed", "missing"))
def test_owned_nan_snapshot_loads_after_source_change_or_disappearance(tmp_path, source_change):
    service, artifacts, recipes, historical = _domain(tmp_path)
    logical_id, frame = _pattern_artifact(service, artifacts, recipes, "all")
    seed = service.create_database_seed(MARKET, "Full Seed")
    manifest = _compose(service, seed, (logical_id,), "individual")
    saved = _assert_database(service, seed, manifest, {logical_id: frame})
    artifact_heads = tuple(artifacts.list_managed_artifacts(MARKET))
    path = OHLCVStore(historical).csv_path(MARKET)
    if source_change == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    restarted, *_ = _domain(tmp_path, initialize=False)
    assert restarted.load_database_revision(manifest.database_id) == saved
    snapshot = restarted.reconcile_update_status(force=True)
    row = next(item for item in snapshot.databases if item.database_id == manifest.database_id)
    assert row.status == ("SOURCE_INVALID" if source_change == "missing" else "CURRENT")
    assert restarted.load_database_revision(manifest.database_id) == saved
    assert tuple(artifacts.list_managed_artifacts(MARKET)) == artifact_heads
