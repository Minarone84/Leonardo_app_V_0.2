from __future__ import annotations

import csv
from hashlib import sha256
from io import BytesIO, StringIO
from math import isfinite

import pandas as pd
import pytest

from leonardo.artifacts._stores import _io_path
from leonardo.data_manager import DataManagerOperationError
from leonardo.data_manager.artifact_materialization import _calculate_recipe, _dataset_frame
from leonardo.financial_tools import calculate_financial_tool, get_financial_tool_spec
from leonardo.ohlcv.store import OHLCVStore

from tests.data_manager_test.test_nan_database_composition import _compose, _source_hashes
from tests.data_manager_test.test_update_workflow import (
    MARKET, _angle, _append, _derivative, _domain, _materialize, _sma,
)


def _tree(root):
    root = _io_path(root)
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _rows(payload):
    return list(csv.reader(StringIO(payload.decode("utf-8"))))


def _immutable_snapshots(service):
    root = service.creation_store.root_dir
    return (
        _tree(root / "database_seeds"),
        _tree(root / "artifact_collections"),
        tuple(
            (item.collection_id, service.list_artifact_collection_revisions(item.collection_id))
            for item in service.list_artifact_collections()
        ),
    )


def _database_history(service, database_id):
    return {
        manifest.revision_id: (
            manifest,
            service.load_database_revision(database_id, manifest.revision_id).values_csv,
            _tree(service.creation_store.root_dir / "databases" / database_id / "revisions" / manifest.revision_id),
        )
        for manifest in service.list_database_revisions(database_id)
    }


def _assert_history(service, database_id, history):
    current = _database_history(service, database_id)
    assert all(current[revision_id] == saved for revision_id, saved in history.items())


def _current(artifacts, logical_id):
    head = artifacts.load_artifact_head(MARKET, logical_id)
    return artifacts.load_artifact_by_id(MARKET, head.artifact_id)


def _artifact_bytes(artifacts, loaded):
    recipe = loaded.metadata.recipe
    return _tree(artifacts._store.artifact_dir(
        MARKET, recipe.kind, recipe.tool_key, loaded.metadata.artifact_id
    ))


def _wait_for_explicit_artifact_work(service, historical, database_id):
    before = _tree(historical)
    database_before = _tree(service.creation_store.root_dir)
    waiting = service.plan_database_update(database_id)
    assert waiting.mode == "BLOCKED"
    assert waiting.status == "WAITING_FOR_ARTIFACT_UPDATE"
    assert any(node.action == "UPDATE" for node in waiting.prerequisite_nodes)
    with pytest.raises(DataManagerOperationError, match="requires mode APPEND"):
        service.execute_database_append(waiting)
    assert _tree(historical) == before
    assert _tree(service.creation_store.root_dir) == database_before


def _append_database(service, artifacts, historical, previous):
    history = _database_history(service, previous.database_id)
    old_bytes = history[previous.revision_id][1]
    source_hashes = _source_hashes(historical)
    source = artifacts.capture_accepted_source(MARKET)
    plan = service.plan_database_update(previous.database_id)
    assert plan.mode == "APPEND" and plan.status == "UPDATE_AVAILABLE"
    assert not plan.blocked
    assert plan.database_revision_id == previous.revision_id
    assert plan.source_ohlcv == source
    providers = {
        output.logical_artifact_id: _current(artifacts, output.logical_artifact_id)
        for output in previous.selected_outputs
    }
    assert dict(plan.starting_artifact_heads) == {
        logical_id: loaded.metadata.artifact_id for logical_id, loaded in providers.items()
    }
    artifact_bytes = _tree(historical)
    result = service.execute_database_append(plan)
    assert result.mode == "APPEND" and result.plan_id == plan.plan_id
    manifest = result.database_revision
    loaded = service.load_database_revision(previous.database_id)
    assert loaded.manifest == manifest
    assert manifest.previous_revision_id == previous.revision_id
    assert loaded.values_csv.startswith(old_bytes)
    assert manifest.source_ohlcv == source
    assert manifest.values_sha256 == sha256(loaded.values_csv).hexdigest()
    assert manifest.row_count == source.row_count
    assert manifest.first_timestamp_ms == previous.first_timestamp_ms == source.first_timestamp_ms
    assert manifest.last_timestamp_ms == source.last_timestamp_ms
    changed_fields = {
        "revision_id", "source_ohlcv", "row_count", "last_timestamp_ms", "values_sha256",
        "previous_revision_id", "created_at_utc", "members", "value_provenance",
    }
    assert {
        key: value for key, value in manifest.to_dict().items() if key not in changed_fields
    } == {
        key: value for key, value in previous.to_dict().items() if key not in changed_fields
    }
    old_provenance = previous.to_dict()["value_provenance"]
    new_provenance = manifest.to_dict()["value_provenance"]
    for section in ("members", "dependency_edges", "outputs"):
        assert all(record in new_provenance[section] for record in old_provenance[section])
    suffix = [record for record in new_provenance["outputs"] if record not in old_provenance["outputs"]]
    assert len(suffix) == len(manifest.selected_outputs)
    assert {record["artifact_id"] for record in suffix} == {
        loaded.metadata.artifact_id for loaded in providers.values()
    }
    assert all(record["first_timestamp_ms"] > previous.last_timestamp_ms
               and record["last_timestamp_ms"] == manifest.last_timestamp_ms for record in suffix)
    rows = _rows(loaded.values_csv)
    source_rows = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
    assert rows[0][:6] == source_rows[0]
    assert [row[:6] for row in rows[1:]] == source_rows[1:]
    assert all(token != "" for row in rows[1:] for token in row[:6])
    assert manifest.column_count == len(rows[0])
    assert len(rows) - 1 == manifest.row_count
    frame = pd.read_csv(BytesIO(loaded.values_csv), float_precision="round_trip")
    assert tuple(frame.ts_ms) == tuple(int(row[0]) for row in source_rows[1:])
    members = {member.version_key.logical_artifact_id: member for member in manifest.members}
    for output in manifest.selected_outputs:
        provider = providers[output.logical_artifact_id]
        member = members[output.logical_artifact_id]
        assert member.version_key.artifact_id == provider.metadata.artifact_id
        assert member.values_sha256 == provider.metadata.values_sha256
        expected = provider.frame[output.output_name].iloc[previous.row_count:].reset_index(drop=True)
        actual = frame[output.column_name].iloc[previous.row_count:].reset_index(drop=True)
        pd.testing.assert_series_equal(actual, expected, check_names=False, check_dtype=False, rtol=1e-6)
        assert actual.isna().tolist() == expected.isna().tolist()
        column = rows[0].index(output.column_name)
        assert [row[column] == "" for row in rows[previous.row_count + 1:]] == expected.isna().tolist()
        for token, expected_value in zip(
            (row[column] for row in rows[previous.row_count + 1:]),
            expected.tolist(), strict=True,
        ):
            if pd.isna(expected_value):
                assert token == ""
            else:
                assert float(token) == float(expected_value)
    assert _tree(historical) == artifact_bytes
    assert _source_hashes(historical) == source_hashes
    _assert_history(service, previous.database_id, history)
    return manifest


@pytest.mark.parametrize("route", ("individual", "build"))
def test_sma120_full_axis_updates_cross_warmup_without_rewriting_snapshots(tmp_path, route):
    service, artifacts, recipes, historical = _domain(tmp_path)
    initial_source = _source_hashes(historical)
    recipe = _sma(120)
    materialization = _materialize(service, recipes, recipe)
    logical_id = materialization.root_logical_artifact_ids[0]
    initial = _current(artifacts, logical_id)
    assert initial.frame.sma_120.isna().tolist() == [True] * 96
    initial_bytes = _artifact_bytes(artifacts, initial)
    seed = service.create_database_seed(MARKET, "SMA120 snapshot")
    manifest = _compose(service, seed, (logical_id,), route)
    assert manifest.row_count == seed.row_count == 96
    immutable = _immutable_snapshots(service)
    assert bool(immutable[1]) == (route == "build")
    initial_database = service.load_database_revision(manifest.database_id)
    assert pd.read_csv(BytesIO(initial_database.values_csv)).iloc[:, 6:].isna().all().all()
    assert _source_hashes(historical) == initial_source

    for rows, missing in ((104, 104), (128, 119)):
        previous_artifact = _current(artifacts, logical_id)
        previous_bytes = _artifact_bytes(artifacts, previous_artifact)
        _append(historical, rows=rows)
        source_after_fixture = _source_hashes(historical)
        _wait_for_explicit_artifact_work(service, historical, manifest.database_id)
        plan = service.plan_artifact_update(MARKET, (logical_id,))
        assert not plan.blocked, plan.blockers
        assert len(plan.nodes) == 1 and plan.nodes[0].action == "UPDATE"
        policy = get_financial_tool_spec("sma").update_policy
        assert plan.nodes[0].context_rows == policy.effective_context_rows(recipe.parameters)
        assert plan.nodes[0].context_rows > len(previous_artifact.frame)
        updated = service.execute_artifact_update(plan)
        assert updated.updated_logical_artifact_ids == (logical_id,)
        current = _current(artifacts, logical_id)
        expected = calculate_financial_tool(
            "sma", _dataset_frame(service._loader.load(MARKET)), {"period": 120}
        ).to_frame()
        pd.testing.assert_frame_equal(current.frame, expected)
        assert current.frame.sma_120.isna().tolist() == [True] * missing + [False] * (rows - missing)
        assert all(isfinite(value) for value in current.frame.sma_120.dropna())
        assert current.metadata.row_count == rows
        assert current.metadata.source_ohlcv == artifacts.capture_accepted_source(MARKET)
        assert _artifact_bytes(artifacts, previous_artifact) == previous_bytes
        old = artifacts.load_artifact_by_id(MARKET, initial.metadata.artifact_id)
        assert old.metadata == initial.metadata
        pd.testing.assert_frame_equal(old.frame, initial.frame)
        assert _artifact_bytes(artifacts, old) == initial_bytes
        manifest = _append_database(service, artifacts, historical, manifest)
        full = pd.read_csv(BytesIO(service.load_database_revision(manifest.database_id).values_csv))
        column = manifest.selected_outputs[0].column_name
        assert full[column].isna().tolist() == [True] * missing + [False] * (rows - missing)
        assert _immutable_snapshots(service) == immutable
        assert _source_hashes(historical) == source_after_fixture

    history = _database_history(service, manifest.database_id)
    reopened, reopened_artifacts, _recipes, _historical = _domain(tmp_path, initialize=False)
    assert _database_history(reopened, manifest.database_id) == history
    assert _immutable_snapshots(reopened) == immutable
    reloaded = _current(reopened_artifacts, logical_id)
    assert reloaded.metadata == current.metadata
    pd.testing.assert_frame_equal(reloaded.frame, expected)
    before = _tree(tmp_path)
    current_plan = reopened.plan_database_update(manifest.database_id)
    assert current_plan.mode == current_plan.status == "CURRENT"
    with pytest.raises(DataManagerOperationError, match="requires mode APPEND"):
        reopened.execute_database_append(current_plan)
    assert _tree(tmp_path) == before
    assert _database_history(reopened, manifest.database_id) == history
    assert _source_hashes(historical) == source_after_fixture


@pytest.mark.parametrize("tool", ("derivative", "angle"))
def test_revisable_artifact_tail_does_not_backfill_database_nan(tmp_path, tool):
    service, artifacts, recipes, historical = _domain(tmp_path)
    source_before = _source_hashes(historical)
    sma = _sma(3)
    transform = _derivative(sma) if tool == "derivative" else _angle(sma)
    recipes.save_recipe(sma)
    materialization = _materialize(service, recipes, transform)
    logical_id = materialization.root_logical_artifact_ids[0]
    initial = _current(artifacts, logical_id)
    output_name = transform.output_names[0]
    assert pd.isna(initial.frame[output_name].iloc[95])
    initial_artifact_bytes = _artifact_bytes(artifacts, initial)
    seed = service.create_database_seed(MARKET, "Revisable tail snapshot")
    original = _compose(service, seed, (logical_id,), "build")
    immutable = _immutable_snapshots(service)
    old_database = service.load_database_revision(original.database_id)
    column = next(output.column_name for output in original.selected_outputs if output.logical_artifact_id == logical_id)
    assert _rows(old_database.values_csv)[96][_rows(old_database.values_csv)[0].index(column)] == ""
    assert _source_hashes(historical) == source_before
    _append(historical, rows=104)
    source_after_fixture = _source_hashes(historical)
    _wait_for_explicit_artifact_work(service, historical, original.database_id)
    plan = service.plan_artifact_update(MARKET, (logical_id,))
    assert not plan.blocked, plan.blockers
    assert [node.tool_key for node in plan.nodes] == ["sma", tool]
    stage = {logical: index for index, group in enumerate(plan.execution_stages) for logical in group}
    assert stage[plan.nodes[0].logical_artifact_id] < stage[logical_id]
    policy = get_financial_tool_spec(tool).update_policy
    assert plan.nodes[-1].revisable_tail_rows == policy.revisable_tail_rows == 1
    update = service.execute_artifact_update(plan)
    assert set(update.updated_logical_artifact_ids) == {node.logical_artifact_id for node in plan.nodes}
    current = _current(artifacts, logical_id)
    target = _dataset_frame(service._loader.load(MARKET))
    recipe_map = {item.recipe_id: item for item in (sma, transform)}
    sma_frame = _calculate_recipe(sma, recipe_map, target, {}).result.to_frame()
    expected = _calculate_recipe(transform, recipe_map, target, {sma.recipe_id: sma_frame}).result.to_frame()
    pd.testing.assert_frame_equal(current.frame, expected)
    assert current.frame[output_name].isna().tolist() == expected[output_name].isna().tolist()
    assert len(current.frame) == 104
    assert pd.notna(current.frame[output_name].iloc[95])
    assert pd.isna(current.frame[output_name].iloc[-1])
    preserved = len(initial.frame) - policy.revisable_tail_rows
    pd.testing.assert_frame_equal(current.frame.iloc[:preserved], initial.frame.iloc[:preserved])
    assert _artifact_bytes(artifacts, initial) == initial_artifact_bytes
    appended = _append_database(service, artifacts, historical, original)
    reopened, reopened_artifacts, _recipes, _historical = _domain(tmp_path, initialize=False)
    frozen = reopened.load_database_revision(appended.database_id)
    assert frozen.values_csv.startswith(old_database.values_csv)
    frozen_frame = pd.read_csv(BytesIO(frozen.values_csv))
    assert pd.isna(frozen_frame[column].iloc[95])
    assert pd.isna(frozen_frame[column].iloc[-1])
    assert pd.notna(_current(reopened_artifacts, logical_id).frame[output_name].iloc[95])
    assert reopened.load_database_revision(original.database_id, original.revision_id).values_csv == old_database.values_csv
    assert _immutable_snapshots(reopened) == immutable
    assert _source_hashes(historical) == source_after_fixture


@pytest.mark.parametrize("guard", ("stale_source", "cancelled", "publication_refused"))
def test_nan_append_failure_guards_preserve_database_bytes_and_head(tmp_path, guard):
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma(120))
    seed = service.create_database_seed(MARKET, "Guarded NaN snapshot")
    original = _compose(service, seed, materialization.root_logical_artifact_ids, "build")
    old = service.load_database_revision(original.database_id)
    immutable = _immutable_snapshots(service)
    _append(historical, rows=104)
    source_after_fixture = _source_hashes(historical)
    service.execute_artifact_update(service.plan_artifact_update(MARKET, materialization.root_logical_artifact_ids))
    assert _source_hashes(historical) == source_after_fixture
    current = _current(artifacts, materialization.root_logical_artifact_ids[0])
    assert current.frame.sma_120.isna().tolist() == [True] * 104
    plan = service.plan_database_update(original.database_id)
    assert plan.mode == "APPEND" and not plan.blocked
    database_root = service.creation_store.root_dir / "databases"
    before_database = _tree(database_root)
    history = _database_history(service, original.database_id)
    head = service.creation_store.load_database_head(original.database_id)
    if guard == "stale_source":
        _append(historical, rows=105)
        source_after_fixture = _source_hashes(historical)
    before = _tree(tmp_path)
    calls = []

    def refuse():
        calls.append("publication_refused")
        raise DataManagerOperationError("publication refused")

    kwargs = (
        {"cancellation_requested": lambda: True} if guard == "cancelled"
        else {"before_publish": refuse} if guard == "publication_refused" else {}
    )
    message = {"stale_source": "plan is stale", "cancelled": "cancelled", "publication_refused": "publication refused"}[guard]
    with pytest.raises(DataManagerOperationError, match=message):
        service.execute_database_append(plan, **kwargs)
    assert calls == (["publication_refused"] if guard == "publication_refused" else [])
    assert _tree(tmp_path) == before
    assert _tree(database_root) == before_database
    assert service.creation_store.load_database_head(original.database_id) == head
    assert _database_history(service, original.database_id) == history
    assert service.load_database_revision(original.database_id, original.revision_id).values_csv == old.values_csv
    assert _immutable_snapshots(service) == immutable
    assert _source_hashes(historical) == source_after_fixture
