from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from leonardo.data_manager import (
    DatabaseCollectionReferenceV2,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DataManagerCreationError,
)
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.data_manager.creation_store import DataManagerCreationStoreError

from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_update_workflow import (
    MARKET,
    _append,
    _domain,
    _publish_modified,
)


def _files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _create_seed(service, *, end: int | None = None):
    dataset = service._loader.load(MARKET)
    plan = service.plan_database_seed_creation(
        MARKET,
        "Base Seed",
        description="Selected OHLCV base",
        selected_ohlcv_columns=("open", "close", "volume"),
        selected_range_start_ms=int(dataset.ts_ms[4]),
        selected_range_end_ms=(
            int(dataset.ts_ms[-1]) if end is None else end
        ),
    )
    return service.execute_database_seed_creation(plan)


def test_preview_is_read_only_and_seed_only_database_round_trips(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    store_root = service.creation_store.root_dir
    dataset = service._loader.load(MARKET)

    seed_plan = service.plan_database_seed_creation(
        MARKET,
        "Base Seed",
        selected_ohlcv_columns=("open", "close", "volume"),
        selected_range_start_ms=int(dataset.ts_ms[4]),
        selected_range_end_ms=int(dataset.ts_ms[-4]),
    )
    assert _files(store_root) == {}
    seed = service.execute_database_seed_creation(seed_plan)
    assert service.load_database_seed(seed.seed_id) == seed

    unrelated_before = {
        "artifacts": _files(tmp_path / "historical"),
        "recipes": _files(tmp_path / "recipes"),
    }
    database_plan = service.plan_seed_only_database_creation(
        seed.seed_id, "Base Database", description="No Artifact columns"
    )
    assert database_plan.column_names == ("ts_ms", "open", "close", "volume")
    assert _files(store_root / "databases") == {}
    manifest = service.execute_seed_only_database_creation(database_plan)

    assert isinstance(manifest, DatabaseRevisionManifestV2)
    assert manifest.members == manifest.dependency_edges == ()
    assert manifest.selected_outputs == manifest.collection_sources == ()
    loaded = service.load_database_revision(manifest.database_id)
    assert loaded.manifest == manifest
    frame = pd.read_csv(store_root / "databases" / manifest.database_id /
                        "revisions" / manifest.revision_id / "values.csv")
    assert tuple(frame.columns) == database_plan.column_names
    assert len(frame) == database_plan.row_count
    assert tuple(service.list_database_revisions(manifest.database_id)) == (manifest,)
    assert unrelated_before == {
        "artifacts": _files(tmp_path / "historical"),
        "recipes": _files(tmp_path / "recipes"),
    }


def test_stale_cancelled_and_failed_publications_leave_no_product(tmp_path: Path) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    seed_plan = service.plan_database_seed_creation(MARKET, "Stale Seed")
    _append(historical)
    with pytest.raises(DataManagerCreationError, match="fingerprint changed"):
        service.execute_database_seed_creation(seed_plan)
    assert service.list_database_seeds() == ()

    service, _artifacts, _recipes, _historical = _domain(tmp_path / "fresh")
    seed = _create_seed(service)
    plan = service.plan_seed_only_database_creation(seed.seed_id, "Database")
    before = _files(service.creation_store.root_dir)
    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service.execute_seed_only_database_creation(
            plan, cancellation_requested=lambda: True
        )
    assert _files(service.creation_store.root_dir) == before

    def refuse() -> None:
        raise RuntimeError("publication refused")

    with pytest.raises(RuntimeError, match="publication refused"):
        service.execute_seed_only_database_creation(plan, before_publish=refuse)
    assert _files(service.creation_store.root_dir) == before
    assert service.list_database_ids() == ()


def test_seed_tamper_and_source_change_at_publication_fail_closed(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path / "seed")
    plan = service.plan_database_seed_creation(MARKET, "Tampered Seed")
    seed_path = (
        service.creation_store.root_dir
        / "database_seeds"
        / f"{plan.seed.seed_id}.json"
    )
    service.execute_database_seed_creation(plan)
    database_plan = service.plan_seed_only_database_creation(
        plan.seed.seed_id, "Tamper refusal"
    )
    seed_path.write_bytes(seed_path.read_bytes() + b"\n")
    with pytest.raises(DataManagerCreationStoreError, match="canonical"):
        service.execute_seed_only_database_creation(database_plan)
    assert service.list_database_ids() == ()

    service, _artifacts, _recipes, historical = _domain(tmp_path / "source")
    seed = _create_seed(service)
    database_plan = service.plan_seed_only_database_creation(
        seed.seed_id, "Source refusal"
    )
    original_publish = service.creation_store.publish_database_revision

    def change_source_before_publication(*args, **kwargs):
        _append(historical)
        return original_publish(*args, **kwargs)

    service.creation_store.publish_database_revision = change_source_before_publication
    with pytest.raises(DataManagerCreationError, match="OHLCV changed"):
        service.execute_seed_only_database_creation(database_plan)
    assert service.list_database_ids() == ()


def test_database_load_rejects_payload_corruption_and_seed_deletion(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    seed = _create_seed(service)
    plan = service.plan_seed_only_database_creation(seed.seed_id, "Database")
    manifest = service.execute_seed_only_database_creation(plan)
    with pytest.raises(DataManagerCreationStoreError, match="referenced"):
        service.delete_database_seed(seed.seed_id)

    sma = _leaf("sma", {"period": 3})
    collection = service.create_artifact_collection(
        _materialize(service, recipes, sma), "Unrelated"
    )
    assert service.delete_artifact_collection(collection.collection_id) == collection

    values_path = (
        service.creation_store.root_dir
        / "databases"
        / manifest.database_id
        / "revisions"
        / manifest.revision_id
        / "values.csv"
    )
    values_path.write_bytes(values_path.read_bytes() + b"\n")
    with pytest.raises(DataManagerCreationStoreError, match="values hash"):
        service.load_database_revision(manifest.database_id)


def test_base_only_v2_update_preserves_full_end_and_fixed_end_rules(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path / "full")
    seed = _create_seed(service)
    manifest = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Full range")
    )
    original_revision_bytes = _files(
        service.creation_store.root_dir
        / "databases"
        / manifest.database_id
        / "revisions"
        / manifest.revision_id
    )
    _append(historical)
    append = service.plan_database_update(manifest.database_id)
    assert append.mode == "APPEND"
    updated = service.execute_database_append(append)
    assert isinstance(updated.database_revision, DatabaseRevisionManifestV2)
    assert updated.database_revision.previous_revision_id == manifest.revision_id
    assert updated.database_revision.row_count > manifest.row_count
    assert _files(
        service.creation_store.root_dir
        / "databases"
        / manifest.database_id
        / "revisions"
        / manifest.revision_id
    ) == original_revision_bytes

    _publish_modified(historical, rows=104, mutate_row=20)
    rebuild = service.plan_database_update(manifest.database_id)
    assert rebuild.mode == "REBUILD_REQUIRED"
    rebuilt = service.execute_database_rebuild(rebuild)
    assert rebuilt.database_revision.previous_revision_id == (
        updated.database_revision.revision_id
    )

    service, _artifacts, _recipes, historical = _domain(tmp_path / "fixed")
    dataset = service._loader.load(MARKET)
    seed = _create_seed(service, end=int(dataset.ts_ms[-8]))
    manifest = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Fixed range")
    )
    _append(historical)
    current = service.plan_database_update(manifest.database_id)
    assert current.mode == "CURRENT"
    assert current.column_names == tuple(manifest.column_mapping)


def test_v1_creation_and_update_remain_v1(tmp_path: Path) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "V1 Collection")
    seed = service.create_database_seed(MARKET, "V1 Database")
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    assert isinstance(manifest, DatabaseRevisionManifestV1)

    _append(historical)
    service.execute_artifact_collection_update(
        service.plan_artifact_collection_update(collection.collection_id)
    )
    updated = service.execute_database_append(
        service.plan_database_update(manifest.database_id)
    )
    assert isinstance(updated.database_revision, DatabaseRevisionManifestV1)


def test_member_bearing_v2_uses_fixed_membership_and_blocks_stale_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Fixed Members")
    seed = service.create_database_seed(MARKET, "Member Database")
    previous = service.build_database_revision(seed.seed_id, collection.collection_id)
    loaded = service.load_database_revision(previous.database_id)
    now = datetime.now(UTC)
    reference = DatabaseCollectionReferenceV2(
        collection.collection_id, collection.revision_id
    )
    payload = {
        "schema_version": "2.0",
        "object_type": "database_revision",
        "database_id": previous.database_id,
        "display_name": previous.display_name,
        "description": previous.description,
        "seed_id": previous.seed_id,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": previous.source_ohlcv.to_dict(),
        "members": [item.to_dict() for item in collection.members],
        "dependency_edges": [
            item.to_dict() for item in collection.dependency_edges
        ],
        "selected_outputs": [item.to_dict() for item in collection.selected_outputs],
        "collection_sources": [reference.to_dict()],
        "column_mapping": dict(previous.column_mapping),
        "first_timestamp_ms": previous.first_timestamp_ms,
        "last_timestamp_ms": previous.last_timestamp_ms,
        "row_count": previous.row_count,
        "column_count": previous.column_count,
        "values_sha256": hashlib.sha256(loaded.values_csv).hexdigest(),
        "previous_revision_id": previous.revision_id,
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
    }
    v2 = DatabaseRevisionManifestV2(
        database_id=previous.database_id,
        revision_id=deterministic_hash(payload),
        display_name=previous.display_name,
        description=previous.description,
        seed_id=previous.seed_id,
        market_id=MARKET,
        source_ohlcv=previous.source_ohlcv,
        members=collection.members,
        dependency_edges=collection.dependency_edges,
        selected_outputs=collection.selected_outputs,
        collection_sources=(reference,),
        column_mapping=dict(previous.column_mapping),
        first_timestamp_ms=previous.first_timestamp_ms,
        last_timestamp_ms=previous.last_timestamp_ms,
        row_count=previous.row_count,
        column_count=previous.column_count,
        values_sha256=hashlib.sha256(loaded.values_csv).hexdigest(),
        previous_revision_id=previous.revision_id,
        created_at_utc=now,
    )
    service.creation_store.publish_database_revision(
        service.load_database_definition(previous.database_id),
        v2,
        loaded.values_csv,
        expected_head_revision_id=previous.revision_id,
    )

    extra = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    revised = service.add_artifact_collection_branches(
        collection.collection_id, extra
    )
    assert len(revised.members) > len(v2.members)
    monkeypatch.setattr(
        "leonardo.financial_tools.calculate_financial_tool",
        lambda *_args, **_kwargs: pytest.fail("Database update calculated a tool"),
    )
    current = service.plan_database_update(previous.database_id)
    assert current.mode == "CURRENT"
    assert len(current.starting_artifact_heads) == len(v2.members)

    _append(historical)
    stale = service.plan_database_update(previous.database_id)
    assert stale.mode == "BLOCKED"
    assert stale.status == "WAITING_FOR_ARTIFACT_UPDATE"
