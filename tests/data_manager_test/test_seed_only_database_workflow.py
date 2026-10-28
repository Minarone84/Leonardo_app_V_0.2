from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from leonardo.data_manager import (
    DatabaseCollectionReferenceV2,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DatabaseRevisionManifestV3,
    DatabaseRevisionManifestV4,
    DatabaseSeedV1,
    DatabaseSeedV2,
    DataManagerCreationError,
)
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.data_manager.creation_store import DataManagerCreationStoreError

from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.seed_fixtures import create_legacy_seed_v2
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
    return create_legacy_seed_v2(
        service, MARKET,
        "Base Seed",
        description="Selected OHLCV base",
        start_ms=int(dataset.ts_ms[4]),
        end_ms=(
            int(dataset.ts_ms[-1]) if end is None else end
        ),
    )


def _legacy_seed(service, *, name: str = "Legacy Seed") -> DatabaseSeedV1:
    dataset = service._loader.load(MARKET)
    source = service._artifacts.capture_accepted_source(MARKET)
    seed = DatabaseSeedV1(
        seed_id=service.creation_store.new_seed_id(),
        display_name=name,
        description="Legacy manifest-only Seed",
        market_id=MARKET,
        source_ohlcv=source,
        source_row_count=dataset.row_count,
        first_timestamp_ms=dataset.first_timestamp_ms,
        last_timestamp_ms=dataset.last_timestamp_ms,
        selected_ohlcv_columns=("open", "close", "volume"),
        selected_range_start_ms=int(dataset.ts_ms[4]),
        selected_range_end_ms=int(dataset.ts_ms[-4]),
        created_at_utc=datetime.now(UTC),
    )
    service.creation_store.save_seed(seed)
    return seed


def test_seed_v2_owns_exact_payload_and_live_source_is_advisory(tmp_path: Path) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    dataset = service._loader.load(MARKET)
    plan = service.plan_database_seed_creation(
        MARKET,
        "Owned Seed",
        selected_ohlcv_columns=("open", "high", "low", "close", "volume"),
    )
    seed = service.execute_database_seed_creation(plan)

    assert isinstance(seed, DatabaseSeedV2)
    seed_dir = service.creation_store.root_dir / "database_seeds" / seed.seed_id
    assert sorted(path.name for path in seed_dir.iterdir()) == [
        "manifest.json",
        "values.csv",
    ]
    assert not (seed_dir.parent / f"{seed.seed_id}.json").exists()
    assert (seed_dir / "manifest.json").read_bytes() == seed.canonical_json_bytes()
    values = (seed_dir / "values.csv").read_bytes()
    assert values == plan.values_csv
    assert hashlib.sha256(values).hexdigest() == seed.values_sha256
    rows = values.decode("utf-8").splitlines()
    assert rows[0] == "ts_ms,open,high,low,close,volume"
    assert len(rows) - 1 == seed.row_count
    assert seed.column_count == 6
    assert seed.row_count == dataset.row_count
    assert seed.selected_range_start_ms == dataset.first_timestamp_ms
    assert seed.selected_range_end_ms == dataset.last_timestamp_ms
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    assert service.database_seed_newer_source_available(seed.seed_id) is False

    original_plan = service.plan_seed_only_database_creation(seed.seed_id, "Old DB")
    _append(historical)
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    assert service.database_seed_newer_source_available(seed.seed_id) is True
    evolved_plan = service.plan_seed_only_database_creation(seed.seed_id, "Old DB")
    assert evolved_plan.row_count == original_plan.row_count == seed.row_count
    assert evolved_plan.first_timestamp_ms == seed.selected_range_start_ms
    assert evolved_plan.last_timestamp_ms == seed.selected_range_end_ms

    shutil.rmtree(historical)
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    assert service.database_seed_newer_source_available(seed.seed_id) is None
    missing_source_plan = service.plan_seed_only_database_creation(
        seed.seed_id, "Offline Source DB"
    )
    manifest = service.execute_seed_only_database_creation(missing_source_plan)
    assert manifest.row_count == seed.row_count
    assert manifest.first_timestamp_ms == seed.selected_range_start_ms
    assert manifest.last_timestamp_ms == seed.selected_range_end_ms


@pytest.mark.parametrize(
    "corruption",
    ("hash", "header", "count", "range", "extra", "value", "timestamp"),
)
def test_seed_v2_self_validation_rejects_corruption(
    tmp_path: Path, corruption: str
) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path / corruption)
    seed = _create_seed(service)
    assert isinstance(seed, DatabaseSeedV2)
    seed_dir = service.creation_store.root_dir / "database_seeds" / seed.seed_id
    manifest_path = seed_dir / "manifest.json"
    values_path = seed_dir / "values.csv"

    if corruption == "extra":
        (seed_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    elif corruption == "hash":
        values_path.write_bytes(values_path.read_bytes() + b"\n")
    elif corruption == "header":
        lines = values_path.read_bytes().splitlines(keepends=True)
        lines[0] = b"ts_ms,close,open,volume\n"
        payload = b"".join(lines)
        values_path.write_bytes(payload)
        manifest_path.write_bytes(
            replace(seed, values_sha256=hashlib.sha256(payload).hexdigest()).canonical_json_bytes()
        )
    elif corruption in {"value", "timestamp"}:
        lines = values_path.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split(",")
        if corruption == "value":
            fields[-1] = "nan"
            lines[1] = ",".join(fields)
        else:
            next_fields = lines[2].split(",")
            next_fields[0] = fields[0]
            lines[2] = ",".join(next_fields)
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        values_path.write_bytes(payload)
        manifest_path.write_bytes(
            replace(seed, values_sha256=hashlib.sha256(payload).hexdigest()).canonical_json_bytes()
        )
    elif corruption == "count":
        manifest_path.write_bytes(replace(seed, row_count=seed.row_count - 1).canonical_json_bytes())
    else:
        dataset = service._loader.load(MARKET)
        manifest_path.write_bytes(
            replace(
                seed,
                selected_range_end_ms=int(dataset.ts_ms[-2]),
            ).canonical_json_bytes()
        )

    valid, blockers = service.validate_database_seed(seed.seed_id)
    assert not valid
    assert blockers
    with pytest.raises(DataManagerCreationStoreError):
        service.load_database_seed(seed.seed_id)


def test_seed_v2_duplicate_legacy_layout_is_rejected(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed = _create_seed(service)
    assert isinstance(seed, DatabaseSeedV2)
    legacy = DatabaseSeedV1(
        seed_id=seed.seed_id,
        display_name=seed.display_name,
        description=seed.description,
        market_id=seed.market_id,
        source_ohlcv=seed.source_ohlcv,
        source_row_count=seed.source_row_count,
        first_timestamp_ms=seed.first_timestamp_ms,
        last_timestamp_ms=seed.last_timestamp_ms,
        selected_ohlcv_columns=seed.selected_ohlcv_columns,
        selected_range_start_ms=seed.selected_range_start_ms,
        selected_range_end_ms=seed.selected_range_end_ms,
        created_at_utc=seed.created_at_utc,
    )
    legacy_path = (
        service.creation_store.root_dir / "database_seeds" / f"{seed.seed_id}.json"
    )
    legacy_path.write_bytes(legacy.canonical_json_bytes())

    with pytest.raises(DataManagerCreationStoreError, match="both Seed layouts"):
        service.load_database_seed(seed.seed_id)


def test_seed_listing_supports_mixed_v1_and_v2_layouts(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    legacy = _legacy_seed(service)
    current = _create_seed(service)
    assert legacy.seed_id != current.seed_id

    seed_root = service.creation_store.root_dir / "database_seeds"
    before = _files(seed_root)
    listed = service.list_database_seeds()
    by_id = {seed.seed_id: seed for seed in listed}

    assert set(by_id) == {legacy.seed_id, current.seed_id}
    assert isinstance(by_id[legacy.seed_id], DatabaseSeedV1)
    assert isinstance(by_id[current.seed_id], DatabaseSeedV2)
    assert (seed_root / f"{legacy.seed_id}.json").is_file()
    assert not (seed_root / legacy.seed_id).exists()
    assert (seed_root / current.seed_id).is_dir()
    assert not (seed_root / f"{current.seed_id}.json").exists()
    assert _files(seed_root) == before


def test_product_catalog_scan_completes_with_legacy_seed_persistence(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    legacy = _legacy_seed(service)

    service.reconcile_update_status(force=True)
    snapshot = service.scan_product_catalogs()

    assert snapshot.catalog.accepted_count == 1
    assert snapshot.catalog.accepted_market(MARKET) is not None
    assert tuple(seed.seed_id for seed in snapshot.database_seeds) == (legacy.seed_id,)
    assert isinstance(snapshot.database_seeds[0], DatabaseSeedV1)
    assert tuple(status.seed_id for status in snapshot.database_seed_statuses) == (
        legacy.seed_id,
    )


def test_seed_listing_rejects_unsafe_non_directory_candidate(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed_root = service.creation_store.root_dir / "database_seeds"
    seed_root.mkdir(parents=True)
    unsafe = seed_root / ("seed_" + ("f" * 32))
    unsafe.write_text("not a directory", encoding="utf-8")

    with pytest.raises(
        DataManagerCreationStoreError, match="unsafe persistence directory"
    ):
        service.list_database_seeds()


def test_seed_v2_path_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed = _create_seed(service)
    assert isinstance(seed, DatabaseSeedV2)
    original = service.creation_store.root_dir / "database_seeds" / seed.seed_id
    wrong_id = "seed_" + ("f" * 32)
    wrong = original.parent / wrong_id
    original.rename(wrong)

    valid, blockers = service.validate_database_seed(wrong_id)
    assert not valid
    assert blockers
    with pytest.raises(DataManagerCreationStoreError, match="identity disagrees"):
        service.load_database_seed(wrong_id)


def test_legacy_seed_uses_exact_source_prefix_without_becoming_live_coupled(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    seed = _legacy_seed(service)
    legacy_path = (
        service.creation_store.root_dir / "database_seeds" / f"{seed.seed_id}.json"
    )
    v2_path = legacy_path.with_suffix("")
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    original = service.plan_seed_only_database_creation(seed.seed_id, "Legacy DB")
    assert legacy_path.is_file()
    assert not v2_path.exists()

    _append(historical)
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    assert service.database_seed_newer_source_available(seed.seed_id) is True
    from_prefix = service.plan_seed_only_database_creation(seed.seed_id, "Legacy DB")
    assert from_prefix.row_count == original.row_count
    assert from_prefix.first_timestamp_ms == original.first_timestamp_ms
    assert from_prefix.last_timestamp_ms == original.last_timestamp_ms
    assert legacy_path.is_file()
    assert not v2_path.exists()

    _publish_modified(historical, rows=104, mutate_row=20)
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    with pytest.raises(DataManagerCreationError, match="source bytes cannot be proven"):
        service.plan_seed_only_database_creation(seed.seed_id, "Unprovable Legacy DB")
    assert service.load_database_seed(seed.seed_id) == seed
    assert service.delete_database_seed(seed.seed_id) == seed
    assert not legacy_path.exists()


def test_seed_source_advisory_unavailable_does_not_change_integrity(
    tmp_path: Path, monkeypatch
) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    seed = _create_seed(service)
    monkeypatch.setattr(
        service._artifacts,
        "source_metadata",
        lambda _market: (_ for _ in ()).throw(DataManagerCreationError("unavailable")),
    )
    assert service.database_seed_newer_source_available(seed.seed_id) is None
    assert service.validate_database_seed(seed.seed_id) == (True, ())


def test_preview_is_read_only_and_seed_only_database_round_trips(tmp_path: Path) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path)
    store_root = service.creation_store.root_dir
    dataset = service._loader.load(MARKET)

    seed_plan = service.plan_database_seed_creation(
        MARKET,
        "Base Seed",
        selected_ohlcv_columns=("open", "high", "low", "close", "volume"),
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
    assert database_plan.column_names == ("ts_ms", "open", "high", "low", "close", "volume")
    assert database_plan.row_count == dataset.row_count
    assert database_plan.first_timestamp_ms == dataset.first_timestamp_ms
    assert database_plan.last_timestamp_ms == dataset.last_timestamp_ms
    assert _files(store_root / "databases") == {}
    manifest = service.execute_seed_only_database_creation(database_plan)

    assert isinstance(manifest, DatabaseRevisionManifestV3)
    assert manifest.members == manifest.dependency_edges == ()
    assert manifest.selected_outputs == manifest.collection_sources == ()
    assert manifest.selection_sources == ()
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


def test_collection_backed_database_v3_captures_exact_source_and_reviewed_provider(
    tmp_path: Path,
) -> None:
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Features")
    historical_member = next(
        member
        for member in collection.members
        if member.version_key.logical_artifact_id
        == collection.selected_outputs[0].logical_artifact_id
    )
    seed = service.create_database_seed(MARKET, "Base Seed")

    _append(historical)
    artifact_plan = service.plan_artifact_update(
        MARKET, materialization.root_logical_artifact_ids
    )
    artifact_result = service.execute_artifact_update(artifact_plan)
    assert artifact_result.materialization.advanced_logical_artifact_ids
    assert service.load_artifact_collection(collection.collection_id) == collection

    current_head = artifacts.load_artifact_head(
        MARKET, collection.selected_outputs[0].logical_artifact_id
    )
    assert current_head.artifact_id != historical_member.version_key.artifact_id

    manifest = service.build_database_revision(
        seed.seed_id, collection.collection_id
    )

    assert isinstance(manifest, DatabaseRevisionManifestV3)
    assert manifest.collection_sources == (
        DatabaseCollectionReferenceV2(
            collection.collection_id, collection.revision_id
        ),
    )
    assert len(manifest.selection_sources) == 1
    source = manifest.selection_sources[0]
    assert source["source_kind"] == "collection"
    assert source["source_id"] == collection.collection_id
    assert source["source_revision_id"] == collection.revision_id
    assert source["column_names"] == tuple(
        sorted(output.column_name for output in collection.selected_outputs)
    )
    reviewed_member = next(
        member
        for member in manifest.members
        if member.version_key.logical_artifact_id
        == collection.selected_outputs[0].logical_artifact_id
    )
    assert reviewed_member.version_key.artifact_id == historical_member.version_key.artifact_id
    assert reviewed_member.values_sha256 == artifacts.load_artifact_by_id(
        MARKET, historical_member.version_key.artifact_id
    ).metadata.values_sha256
    assert service.load_database_revision(manifest.database_id).manifest == manifest

    service.creation_store.delete_collection(collection.collection_id)
    assert service.load_database_revision(manifest.database_id).manifest == manifest


def test_stale_cancelled_and_failed_publications_leave_no_product(tmp_path: Path) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    seed_plan = service.plan_database_seed_creation(MARKET, "Stale Seed")
    _append(historical)
    with pytest.raises(DataManagerCreationError, match="fingerprint changed"):
        service.execute_database_seed_creation(seed_plan)
    assert service.list_database_seeds() == ()

    service, _artifacts, _recipes, historical = _domain(tmp_path / "publication")
    seed_plan = service.plan_database_seed_creation(MARKET, "Publication Gate Seed")

    def change_source_during_publication() -> None:
        _append(historical)

    with pytest.raises(DataManagerCreationError, match="fingerprint changed"):
        service.execute_database_seed_creation(
            seed_plan, before_publish=change_source_during_publication
        )
    seed_root = service.creation_store.root_dir / "database_seeds"
    assert service.list_database_seeds() == ()
    assert not seed_root.exists() or not tuple(seed_root.iterdir())

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


def test_seed_owned_payload_tamper_blocks_use_but_live_source_change_does_not(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, _historical = _domain(tmp_path / "seed")
    seed = _create_seed(service)
    assert isinstance(seed, DatabaseSeedV2)
    database_plan = service.plan_seed_only_database_creation(
        seed.seed_id, "Tamper refusal"
    )
    values_path = (
        service.creation_store.root_dir
        / "database_seeds"
        / seed.seed_id
        / "values.csv"
    )
    values_path.write_bytes(values_path.read_bytes() + b"\n")
    with pytest.raises(DataManagerCreationStoreError, match="values hash"):
        service.execute_seed_only_database_creation(database_plan)
    assert service.list_database_ids() == ()

    service, _artifacts, _recipes, historical = _domain(tmp_path / "source")
    seed = _create_seed(service)
    database_plan = service.plan_seed_only_database_creation(
        seed.seed_id, "Source-independent snapshot"
    )
    original_publish = service.creation_store.publish_database_revision

    def change_source_before_publication(*args, **kwargs):
        _append(historical)
        return original_publish(*args, **kwargs)

    service.creation_store.publish_database_revision = change_source_before_publication
    manifest = service.execute_seed_only_database_creation(database_plan)
    assert service.load_database_revision(manifest.database_id).manifest == manifest
    assert service.validate_database_seed(seed.seed_id) == (True, ())
    assert service.database_seed_newer_source_available(seed.seed_id) is True


def test_database_load_rejects_payload_corruption_and_seed_deletion_is_independent(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    seed = _create_seed(service)
    plan = service.plan_seed_only_database_creation(seed.seed_id, "Database")
    manifest = service.execute_seed_only_database_creation(plan)
    original = service.load_database_revision(
        manifest.database_id, manifest.revision_id
    ).values_csv

    assert service.delete_database_seed(seed.seed_id) == seed
    assert seed.seed_id not in {item.seed_id for item in service.list_database_seeds()}
    assert service.load_database_revision(
        manifest.database_id, manifest.revision_id
    ).values_csv == original

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


def test_database_snapshot_survives_upstream_deletion_and_only_future_append_blocks(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Base Seed")
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Snapshot Source")
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    original = service.load_database_revision(
        manifest.database_id, manifest.revision_id
    ).values_csv

    assert service.delete_database_seed(seed.seed_id) == seed
    assert service.delete_artifact_collection(collection.collection_id) == collection
    logical_id = materialization.root_logical_artifact_ids[0]
    deleted = service.delete_managed_artifact(MARKET, logical_id)
    assert deleted.logical_artifact_id == logical_id

    loaded = service.load_database_revision(manifest.database_id)
    assert loaded.values_csv == original
    current = service.plan_database_update(manifest.database_id)
    assert current.mode == "CURRENT"
    assert current.status == "CURRENT"
    assert current.blockers == ()

    _append(historical)
    blocked = service.plan_database_update(manifest.database_id)
    assert blocked.mode == "BLOCKED"
    assert blocked.status == "BLOCKED_BY_DEPENDENCY"
    assert any("Artifact head not found" in item for item in blocked.blockers)
    assert service.load_database_revision(manifest.database_id).values_csv == original


def test_database_deletion_quarantine_cleanup_retry_and_upstream_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Base Seed")
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Deletion Source")
    manifest = service.build_database_revision(seed.seed_id, collection.collection_id)
    other = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Other Database")
    )
    database_root = service.creation_store.root_dir / "databases"
    live = database_root / manifest.database_id
    quarantine = database_root / f".deleted-{manifest.database_id}"
    original_rmtree = shutil.rmtree
    destructive: list[bool] = []
    invalidations: list[bool] = []
    monkeypatch.setattr(
        service._updates, "invalidate", lambda: invalidations.append(True)
    )

    unexpected = live / "unexpected.txt"
    unexpected.write_text("not Database-owned")
    with pytest.raises(
        DataManagerCreationStoreError, match="owned paths are not exact"
    ):
        service.delete_database(
            manifest.database_id,
            before_delete=lambda: destructive.append(True),
        )
    assert live.exists()
    assert not quarantine.exists()
    assert destructive == []
    assert invalidations == []
    unexpected.unlink()

    def fail_cleanup(path, *args, **kwargs):
        if Path(path) == quarantine:
            raise OSError("simulated quarantine cleanup failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        "leonardo.data_manager.creation_store.shutil.rmtree", fail_cleanup
    )
    with pytest.raises(
        DataManagerCreationStoreError,
        match="deletion committed; cleanup incomplete",
    ):
        service.delete_database(
            manifest.database_id,
            before_delete=lambda: destructive.append(True),
        )

    assert destructive == [True]
    assert invalidations == [True]
    assert not live.exists()
    assert quarantine.exists()
    assert manifest.database_id not in service.list_database_ids()
    snapshot = service.reconcile_update_status(force=True)
    assert manifest.database_id not in {item.database_id for item in snapshot.databases}
    assert service.load_database_seed(seed.seed_id) == seed
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.load_database_revision(other.database_id).manifest == other
    logical_id = materialization.root_logical_artifact_ids[0]
    assert (
        service._artifacts.load_artifact_head(MARKET, logical_id).logical_artifact_id
        == logical_id
    )

    monkeypatch.setattr(
        "leonardo.data_manager.creation_store.shutil.rmtree", original_rmtree
    )
    assert service.delete_database(
        manifest.database_id,
        before_delete=lambda: destructive.append(True),
    ) == manifest.database_id
    assert destructive == [True]
    assert invalidations == [True, True]
    assert not quarantine.exists()
    with pytest.raises(FileNotFoundError):
        service.load_database_revision(manifest.database_id)
    assert service.load_database_seed(seed.seed_id) == seed
    assert service.load_artifact_collection(collection.collection_id) == collection
    assert service.load_database_revision(other.database_id).manifest == other
    assert (
        service._artifacts.load_artifact_head(MARKET, logical_id).logical_artifact_id
        == logical_id
    )



def test_seed_only_v3_append_preserves_ownership_and_old_seed_snapshot_rules(
    tmp_path: Path,
) -> None:
    service, _artifacts, _recipes, historical = _domain(tmp_path / "full")
    seed = _create_seed(service)
    manifest = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Full range")
    )
    assert isinstance(manifest, DatabaseRevisionManifestV3)
    assert manifest.selection_sources == ()
    original = service.load_database_revision(
        manifest.database_id, manifest.revision_id
    ).values_csv
    _append(historical)
    append = service.plan_database_update(manifest.database_id)
    assert append.mode == "APPEND"
    updated = service.execute_database_append(append)
    assert isinstance(updated.database_revision, DatabaseRevisionManifestV3)
    assert updated.database_revision.selection_sources == ()
    assert updated.database_revision.previous_revision_id == manifest.revision_id
    assert updated.database_revision.row_count > manifest.row_count
    assert service.load_database_revision(manifest.database_id).values_csv.startswith(
        original
    )

    revision_count = len(service.list_database_revisions(manifest.database_id))
    _publish_modified(historical, rows=104, mutate_row=20)
    current = service.plan_database_update(manifest.database_id)
    assert current.mode == "CURRENT"
    assert current.status == "CURRENT"
    assert len(service.list_database_revisions(manifest.database_id)) == revision_count

    service, _artifacts, _recipes, historical = _domain(tmp_path / "old-seed")
    dataset = service._loader.load(MARKET)
    seed = _create_seed(service, end=int(dataset.ts_ms[-8]))
    manifest = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Old snapshot")
    )
    assert isinstance(manifest, DatabaseRevisionManifestV3)
    first_append = service.plan_database_update(manifest.database_id)
    assert first_append.mode == "APPEND"
    first_updated = service.execute_database_append(first_append)
    assert first_updated.database_revision.last_timestamp_ms == int(dataset.ts_ms[-1])
    _append(historical)
    second_append = service.plan_database_update(manifest.database_id)
    assert second_append.mode == "APPEND"
    second_updated = service.execute_database_append(second_append)
    assert second_updated.database_revision.last_timestamp_ms > (
        first_updated.database_revision.last_timestamp_ms
    )


def test_legacy_v1_safe_append_preserves_old_format_and_publishes_provenance(tmp_path: Path) -> None:
    service, _artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "V1 Collection")
    seed = service.create_database_seed(MARKET, "V1 Database")
    current = service.build_database_revision(seed.seed_id, collection.collection_id)
    loaded = service.load_database_revision(current.database_id)
    now = datetime.now(UTC)
    payload = {
        "schema_version": "1.0",
        "object_type": "database_revision",
        "database_id": current.database_id,
        "display_name": current.display_name,
        "description": current.description,
        "seed_id": current.seed_id,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": current.source_ohlcv.to_dict(),
        "collection_id": collection.collection_id,
        "collection_revision_id": collection.revision_id,
        "collection_manifest_hash": hashlib.sha256(
            collection.canonical_json_bytes()
        ).hexdigest(),
        "artifact_version_keys": [
            {
                "logical_artifact_id": member.version_key.logical_artifact_id,
                "artifact_id": member.version_key.artifact_id,
            }
            for member in collection.members
        ],
        "artifact_payload_hashes": [member.values_sha256 for member in collection.members],
        "portable_recipe_ids": list(collection.source_portable_recipe_ids),
        "column_mapping": dict(current.column_mapping),
        "first_timestamp_ms": current.first_timestamp_ms,
        "last_timestamp_ms": current.last_timestamp_ms,
        "row_count": current.row_count,
        "column_count": current.column_count,
        "values_sha256": hashlib.sha256(loaded.values_csv).hexdigest(),
        "previous_revision_id": current.revision_id,
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
    }
    payload["revision_id"] = deterministic_hash(payload)
    legacy = DatabaseRevisionManifestV1.from_dict(payload)
    service.creation_store.publish_database_revision(
        service.load_database_definition(current.database_id),
        legacy,
        loaded.values_csv,
        expected_head_revision_id=current.revision_id,
    )

    _append(historical)
    waiting = service.plan_database_update(legacy.database_id)
    assert waiting.status == "WAITING_FOR_ARTIFACT_UPDATE"
    service.execute_artifact_update(
        service.plan_artifact_update(
            MARKET, materialization.root_logical_artifact_ids
        )
    )
    ready = service.plan_database_update(legacy.database_id)
    assert ready.mode == "APPEND"
    updated = service.execute_database_append(ready)
    assert isinstance(updated.database_revision, DatabaseRevisionManifestV4)
    assert updated.database_revision.previous_revision_id == legacy.revision_id
    assert service.load_database_revision(legacy.database_id).values_csv.startswith(
        loaded.values_csv
    )


def test_legacy_v2_append_uses_selected_providers_and_preserves_old_revision(
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
    payload["revision_id"] = deterministic_hash(payload)
    v2 = DatabaseRevisionManifestV2.from_dict(payload)
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
    current = service.plan_database_update(previous.database_id)
    assert current.mode == "CURRENT"
    assert current.starting_artifact_heads == ()

    _append(historical)
    waiting = service.plan_database_update(previous.database_id)
    assert waiting.mode == "BLOCKED"
    assert waiting.status == "WAITING_FOR_ARTIFACT_UPDATE"
    stored_roots = tuple(
        sorted({output.logical_artifact_id for output in v2.selected_outputs})
    )
    artifact_plan = service.plan_artifact_update(MARKET, stored_roots)
    assert any(node.action == "UPDATE" for node in artifact_plan.nodes)
    service.execute_artifact_update(artifact_plan)
    ready = service.plan_database_update(previous.database_id)
    assert ready.mode == "APPEND"

    monkeypatch.setattr(
        service._updates,
        "execute_artifact_update",
        lambda *_args, **_kwargs: pytest.fail("Database append calculated an Artifact"),
    )
    updated = service.execute_database_append(ready)
    assert isinstance(updated.database_revision, DatabaseRevisionManifestV4)
    assert updated.database_revision.previous_revision_id == v2.revision_id
    assert tuple(
        member.version_key.logical_artifact_id
        for member in updated.database_revision.members
    ) == tuple(
        member.version_key.logical_artifact_id for member in v2.members
    )
    assert service.load_database_revision(previous.database_id).values_csv.startswith(
        loaded.values_csv
    )


def _legacy_manifest_payload(seed, collection, *, schema_version: str):
    output = collection.selected_outputs[0]
    mapping = {
        "ts_ms": "ts_ms",
        **{column: column for column in seed.selected_ohlcv_columns},
        output.output_name: output.column_name,
    }
    base = {
        "schema_version": schema_version,
        "object_type": "database_revision",
        "database_id": "db_" + "d" * 32,
        "display_name": "Legacy ownership",
        "description": "",
        "seed_id": seed.seed_id,
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "source_ohlcv": seed.source_ohlcv.to_dict(),
        "column_mapping": mapping,
        "first_timestamp_ms": seed.selected_range_start_ms,
        "last_timestamp_ms": seed.selected_range_end_ms,
        "row_count": seed.row_count,
        "column_count": len(mapping),
        "values_sha256": "e" * 64,
        "previous_revision_id": None,
        "created_at_utc": "2026-09-13T10:00:00Z",
    }
    return base


def test_legacy_v1_ownership_uses_manifest_identity_without_live_collection(
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(materialization, "Legacy source")
    seed = _create_seed(service)
    payload = _legacy_manifest_payload(seed, collection, schema_version="1.0")
    payload.update(
        {
            "collection_id": collection.collection_id,
            "collection_revision_id": collection.revision_id,
            "collection_manifest_hash": hashlib.sha256(
                collection.canonical_json_bytes()
            ).hexdigest(),
            "artifact_version_keys": [
                {
                    "logical_artifact_id": member.version_key.logical_artifact_id,
                    "artifact_id": member.version_key.artifact_id,
                }
                for member in collection.members
            ],
            "artifact_payload_hashes": [
                member.values_sha256 for member in collection.members
            ],
            "portable_recipe_ids": list(collection.source_portable_recipe_ids),
        }
    )
    payload["revision_id"] = deterministic_hash(payload)
    manifest = DatabaseRevisionManifestV1.from_dict(payload)

    service.creation_store.delete_collection(collection.collection_id)
    assert not service.creation_store.list_collection_ids()

    sources = service._creation._database_selection_sources(manifest)

    assert sources == (
        {
            "source_kind": "collection",
            "source_id": collection.collection_id,
            "source_revision_id": collection.revision_id,
            "column_names": (collection.selected_outputs[0].column_name,),
        },
    )


def test_legacy_v2_overlap_attribution_refuses_to_guess(tmp_path: Path) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    first = service.create_artifact_collection(materialization, "Captured source")
    second = service.revise_artifact_collection(
        first.collection_id, display_name="Captured source revision"
    )
    seed = _create_seed(service)
    payload = _legacy_manifest_payload(seed, second, schema_version="2.0")
    payload.update(
        {
            "members": [member.to_dict() for member in second.members],
            "dependency_edges": [
                edge.to_dict() for edge in second.dependency_edges
            ],
            "selected_outputs": [
                output.to_dict() for output in second.selected_outputs
            ],
            "collection_sources": [
                reference.to_dict()
                for reference in sorted(
                    (
                        DatabaseCollectionReferenceV2(
                            first.collection_id, first.revision_id
                        ),
                        DatabaseCollectionReferenceV2(
                            second.collection_id, second.revision_id
                        ),
                    ),
                    key=lambda reference: (
                        reference.collection_id, reference.revision_id
                    ),
                )
            ],
        }
    )
    payload["revision_id"] = deterministic_hash(payload)
    manifest = DatabaseRevisionManifestV2.from_dict(payload)

    # A2 preserves the unresolved claim instead of refusing all local edits.
    sources = service._creation._database_selection_sources(manifest)
    assert sources == ({
        "source_kind": "legacy_snapshot", "source_id": manifest.database_id,
        "source_revision_id": manifest.revision_id,
        "column_names": tuple(o.column_name for o in manifest.selected_outputs),
    },)
