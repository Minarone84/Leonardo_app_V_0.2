from pathlib import Path

import pytest

from tests.data_manager_test.test_update_workflow import MARKET, _domain, _materialize, _sma


def _populated(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    outputs = _materialize(service, recipes, _sma(3), _sma(5))
    seed = service.create_database_seed(MARKET, "Metadata Seed")
    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Metadata Database")
    )
    for logical_id in outputs.root_logical_artifact_ids:
        database = service.execute_database_content_edit(
            service.plan_database_artifact_addition(database.database_id, (logical_id,))
        )
    service.create_artifact_collection(outputs, "Metadata Collection")
    return service, artifacts, seed, database


def test_catalog_refresh_and_history_never_open_payloads(tmp_path, monkeypatch):
    service, artifacts, seed, database = _populated(tmp_path)
    original = Path.open
    reads = []

    def opened(path, mode="r", *args, **kwargs):
        if path.name in {"candles.csv", "values.csv", "analysis.json"} and "r" in mode:
            reads.append(str(path))
            raise AssertionError(f"Browsing opened payload: {path}")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    for force in (True, False, True):
        service.reconcile_update_status(force=force)
        snapshot = service.scan_product_catalogs()
        assert snapshot.databases[0].revision_count == 3
        assert len(snapshot.managed_artifacts.artifacts) == 2
        assert service.list_database_seeds() == (seed,)
        assert len(service.list_database_revisions(database.database_id)) == 3
        assert len(artifacts.list_artifacts_metadata(MARKET)) == 2
    assert reads == []


def test_metadata_discovery_does_not_replace_explicit_integrity_checks(tmp_path):
    service, artifacts, seed, database = _populated(tmp_path)
    path = service.creation_store.root_dir / "databases" / database.database_id / "revisions" / database.revision_id / "values.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    service.reconcile_update_status(force=True)
    assert service.scan_product_catalogs().databases[0].current_manifest == database
    with pytest.raises(ValueError, match="hash"):
        service.load_database_revision(database.database_id)
