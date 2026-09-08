from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionRevisionV1,
    DatabaseCollectionReferenceV2,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
)
from leonardo.data_manager.creation_models import (
    DatabaseHeadV1,
    canonical_json_bytes,
    deterministic_hash,
)

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")


def _completed(submit, *args, **kwargs):
    settled = Event()
    received: list[TaskResult] = []
    submit(
        *args,
        **kwargs,
        result_callback=lambda result: (received.append(result), settled.set()),
    )
    assert settled.wait(10.0), submit.__name__
    assert received[0].status == "completed", received[0]
    return received[0].value


def _settled(submit, *args, **kwargs):
    settled = Event()
    received: list[TaskResult] = []
    submission = submit(
        *args,
        **kwargs,
        result_callback=lambda result: (received.append(result), settled.set()),
    )
    assert settled.wait(10.0), submit.__name__
    return submission, received[0]


def _application(tmp_path: Path) -> tuple[LeonardoApp, object]:
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=48)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    return app, app.data_manager_service


def _create_seed_only_database(application, name: str):
    seed_plan = _completed(
        application.submit_plan_database_seed_creation,
        MARKET,
        f"{name} Seed",
        selected_ohlcv_columns=("open", "close", "volume"),
    )
    seed = _completed(application.submit_execute_database_seed_creation, seed_plan)
    database_plan = _completed(
        application.submit_plan_seed_only_database_creation,
        seed.seed_id,
        name,
    )
    manifest = _completed(
        application.submit_execute_seed_only_database_creation,
        database_plan,
    )
    return seed, manifest


def _publish_v2_after_v1(domain, previous, collection):
    loaded = domain.load_database_revision(previous.database_id, previous.revision_id)
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
        "selected_outputs": [
            item.to_dict() for item in collection.selected_outputs
        ],
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
    manifest = DatabaseRevisionManifestV2(
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
    domain.creation_store.publish_database_revision(
        domain.load_database_definition(previous.database_id),
        manifest,
        loaded.values_csv,
        expected_head_revision_id=previous.revision_id,
    )
    return manifest


def test_seed_only_database_application_create_scan_inspect_and_restart(
    tmp_path: Path,
) -> None:
    app, application = _application(tmp_path)
    try:
        seed_plan = _completed(
            application.submit_plan_database_seed_creation,
            MARKET,
            "Application Seed",
            selected_ohlcv_columns=("open", "close", "volume"),
        )
        seed = _completed(
            application.submit_execute_database_seed_creation, seed_plan
        )
        database_plan = _completed(
            application.submit_plan_seed_only_database_creation,
            seed.seed_id,
            "Application Database",
        )
        manifest = _completed(
            application.submit_execute_seed_only_database_creation,
            database_plan,
        )
        assert isinstance(manifest, DatabaseRevisionManifestV2)
        assert manifest.members == manifest.collection_sources == ()

        _completed(application.submit_reconcile_status, force=True)
        snapshot = _completed(application.submit_scan_product_catalogs)
        entry = next(
            item
            for item in snapshot.databases
            if item.definition.database_id == manifest.database_id
        )
        assert entry.current_manifest == manifest
        assert entry.revision_count == 1
        loaded = _completed(
            application.submit_load_database_revision, manifest.database_id
        )
        assert loaded.manifest == manifest
    finally:
        app.shutdown()

    restarted = LeonardoApp(
        replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    )
    restarted.startup()
    restarted.start_core_runtime()
    try:
        application = restarted.data_manager_service
        assert _completed(application.submit_load_database_seed, seed.seed_id) == seed
        assert _completed(
            application.submit_load_database_revision,
            manifest.database_id,
            manifest.revision_id,
        ).manifest == manifest
        history = _completed(
            application.submit_list_database_revisions, manifest.database_id
        )
        assert history == (manifest,)
    finally:
        restarted.shutdown()


def test_cancelled_application_execution_settles_without_publication(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, application = _application(tmp_path)
    entered = Event()
    release = Event()
    original = app.data_manager_domain.execute_database_seed_creation

    def delayed(plan, **options):
        entered.set()
        assert release.wait(10.0)
        return original(plan, **options)

    try:
        plan = _completed(
            application.submit_plan_database_seed_creation,
            MARKET,
            "Cancelled Seed",
        )
        monkeypatch.setattr(
            app.data_manager_domain,
            "execute_database_seed_creation",
            delayed,
        )
        settled = Event()
        results: list[TaskResult] = []
        submission = application.submit_execute_database_seed_creation(
            plan,
            result_callback=lambda result: (results.append(result), settled.set()),
        )
        assert entered.wait(10.0)
        assert application.cancel(submission.task_id)
        release.set()
        assert settled.wait(10.0)
        assert results[0].status in {"cancelled", "failed"}
        assert app.data_manager_domain.list_database_seeds() == ()
    finally:
        release.set()
        app.shutdown()


def test_failed_application_execution_is_terminal_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app, application = _application(tmp_path)
    try:
        plan = _completed(
            application.submit_plan_database_seed_creation,
            MARKET,
            "Failed Seed",
        )

        def fail(_plan, **_options):
            raise RuntimeError("forced Seed publication failure")

        monkeypatch.setattr(
            app.data_manager_domain,
            "execute_database_seed_creation",
            fail,
        )
        submission, result = _settled(
            application.submit_execute_database_seed_creation,
            plan,
        )
        assert result.status == "failed"
        assert result.error_message == "forced Seed publication failure"
        assert app.task_manager.get_snapshot(submission.task_id).status == "failed"
        assert not application.cancel(submission.task_id)
        assert app.data_manager_domain.list_database_seeds() == ()
        assert app.data_manager_domain.list_database_ids() == ()
    finally:
        app.shutdown()


def test_product_catalog_uses_database_head_not_latest_revision_timestamp(
    tmp_path: Path,
) -> None:
    app, application = _application(tmp_path)
    try:
        _seed, first = _create_seed_only_database(application, "Head Database")
        _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
        update_plan = _completed(
            application.submit_plan_database_update, first.database_id
        )
        assert update_plan.mode == "APPEND"
        second = _completed(
            application.submit_execute_database_append, update_plan
        ).database_revision
        assert second.created_at_utc > first.created_at_utc

        store = app.data_manager_domain.creation_store
        head = DatabaseHeadV1(first.database_id, first.revision_id, datetime.now(UTC))
        head_path = store.root_dir / "databases" / first.database_id / "head.json"
        head_path.write_bytes(canonical_json_bytes(head.to_dict()))

        _completed(application.submit_reconcile_status, force=True)
        snapshot = _completed(application.submit_scan_product_catalogs)
        entry = next(
            item
            for item in snapshot.databases
            if item.definition.database_id == first.database_id
        )
        history = _completed(
            application.submit_list_database_revisions, first.database_id
        )
        assert max(history, key=lambda item: item.created_at_utc) == second
        assert entry.current_manifest == first
        assert _completed(
            application.submit_load_database_revision, first.database_id
        ).manifest == first
    finally:
        app.shutdown()


def test_mixed_v1_v2_history_is_readable_without_v1_conversion(tmp_path: Path) -> None:
    app, application = _application(tmp_path)
    try:
        domain = app.data_manager_domain
        materialization = _materialize(
            domain,
            domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        collection = domain.create_artifact_collection(
            materialization, "Mixed History Collection"
        )
        seed = _completed(
            application.submit_create_database_seed, MARKET, "Mixed History Seed"
        )
        v1 = _completed(
            application.submit_build_database_revision,
            seed.seed_id,
            collection.collection_id,
        )
        assert isinstance(v1, DatabaseRevisionManifestV1)
        v1_path = (
            domain.creation_store.root_dir
            / "databases"
            / v1.database_id
            / "revisions"
            / v1.revision_id
            / "manifest.json"
        )
        v1_bytes = v1_path.read_bytes()
        v2 = _publish_v2_after_v1(domain, v1, collection)

        history = _completed(
            application.submit_list_database_revisions, v1.database_id
        )
        assert history == (v1, v2)
        assert isinstance(
            _completed(
                application.submit_load_database_revision,
                v1.database_id,
                v1.revision_id,
            ).manifest,
            DatabaseRevisionManifestV1,
        )
        assert isinstance(
            _completed(
                application.submit_load_database_revision,
                v1.database_id,
                v2.revision_id,
            ).manifest,
            DatabaseRevisionManifestV2,
        )
        assert v1_path.read_bytes() == v1_bytes
    finally:
        app.shutdown()


def test_v2_collection_references_feed_duplicate_and_deletion_blockers(
    tmp_path: Path,
) -> None:
    app, application = _application(tmp_path)
    try:
        domain = app.data_manager_domain
        materialization = _materialize(
            domain,
            domain._portable_recipes,
            _leaf("sma", {"period": 3}),
        )
        first = domain.create_artifact_collection(materialization, "First Duplicate")
        second_payload = first.to_dict()
        second_payload.pop("revision_id")
        second_payload.update({
            "collection_id": "ac_" + "f" * 32,
            "display_name": "Second Duplicate",
            "description": "",
            "previous_revision_id": None,
            "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "revised_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        })
        second_payload["revision_id"] = deterministic_hash(second_payload)
        second = ArtifactCollectionRevisionV1.from_dict(second_payload)
        domain.creation_store._publish_collection_revision(second)
        seed = _completed(
            application.submit_create_database_seed, MARKET, "Reference Seed"
        )
        v1 = _completed(
            application.submit_build_database_revision,
            seed.seed_id,
            first.collection_id,
        )
        _publish_v2_after_v1(domain, v1, second)

        preflight = _completed(
            application.submit_prepare_duplicate_maintenance,
            "artifact_collections",
            MARKET,
        )
        scan = _completed(application.submit_scan_duplicate_maintenance, preflight)
        candidate = next(
            candidate
            for group in scan.groups
            for candidate in group.duplicates
            if candidate.object_id == second.collection_id
        )
        assert candidate.classification == "BLOCKED"
        assert any(v1.database_id in blocker for blocker in candidate.blockers)

        _submission, deletion = _settled(
            application.submit_delete_artifact_collection,
            second.collection_id,
        )
        assert deletion.status == "failed"
        assert "referenced" in str(deletion.error_message).lower()
        assert domain.load_artifact_collection(second.collection_id) == second
    finally:
        app.shutdown()
