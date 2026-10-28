from __future__ import annotations

import csv
import json
from dataclasses import replace
from hashlib import sha256
from io import StringIO
from pathlib import Path

import pytest

from leonardo.artifacts import ArtifactError
from leonardo.data_manager import DatabaseSeedV1, DataManagerCreationError, DataManagerCreationStore
from leonardo.data_manager.creation_models import canonical_json_bytes, deterministic_hash
from leonardo.data_manager.creation_store import DataManagerCreationStoreError
from leonardo.ohlcv.store import OHLCVStore

from tests.data_manager_test.test_nan_snapshot_updates import _rows, _tree
from tests.data_manager_test.test_update_workflow import MARKET, _append, _domain, _materialize, _sma


OHLC = ("open", "high", "low", "close")


def _fixture(tmp_path):
    service, artifacts, recipes, historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Append snapshot", description="Keep identity")
    old = service.creation_store.load_seed_values(seed.seed_id)
    _append(historical, rows=104)
    plan = service.plan_database_seed_append(seed.seed_id)
    return service, historical, seed, old, plan


def _seed_tree(service):
    return _tree(service.creation_store.root_dir / "database_seeds")


def _serialize(rows):
    output = StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")


def _publish_raw(historical, rows):
    store = OHLCVStore(historical)
    path, sidecar = store.csv_path(MARKET), store.sidecar_path(MARKET)
    path.write_bytes(_serialize(rows))
    def evidence():
        return dict(expected_csv_size=path.stat().st_size, expected_csv_mtime_ns=path.stat().st_mtime_ns,
                    expected_csv_sha256=sha256(path.read_bytes()).hexdigest(),
                    expected_sidecar_size=sidecar.stat().st_size, expected_sidecar_mtime_ns=sidecar.stat().st_mtime_ns,
                    expected_sidecar_sha256=sha256(sidecar.read_bytes()).hexdigest())
    store.reconstruct_sidecar(MARKET, **evidence(), reconstruction_reason="Seed append disposable fixture")
    store.publish_validation(MARKET, **evidence(), status="ok", row_count=len(rows)-1,
                             first_timestamp_ms=int(rows[1][0]), last_timestamp_ms=int(rows[-1][0]),
                             warnings=(), issue_codes=(), error_count=0, warning_count=0, validator="task-1083-test")


@pytest.mark.parametrize("columns", (OHLC, (*OHLC, "volume")))
def test_explicit_append_96_104_128_preserves_snapshots_and_source(tmp_path, columns):
    service, artifacts, recipes, historical = _domain(tmp_path)
    materialization = _materialize(service, recipes, _sma(3))
    collection = service.create_artifact_collection(materialization, "Frozen membership")
    seed = service.create_database_seed(MARKET, "Same Seed", description="Unchanged", selected_ohlcv_columns=columns)
    base = service.execute_seed_only_database_creation(service.plan_seed_only_database_creation(seed.seed_id, "Old base"))
    populated = service.build_database_revision(seed.seed_id, collection.collection_id)
    databases = _tree(service.creation_store.root_dir / "databases")
    collections = _tree(service.creation_store.root_dir / "artifact_collections")
    old = service.creation_store.load_seed_values(seed.seed_id)
    for count in (104, 128):
        _append(historical, rows=count)
        source_before = _tree(historical)
        before = _seed_tree(service)
        plan = service.plan_database_seed_append(seed.seed_id)
        assert _seed_tree(service) == before
        assert plan.previous_row_count == len(_rows(old))-1
        assert plan.appended_row_count == count-plan.previous_row_count
        assert plan.previous_values_sha256 == sha256(old).hexdigest()
        result = service.execute_database_seed_append(plan)
        assert result.seed_id == seed.seed_id and type(result) is type(seed)
        for field in ("display_name", "description", "market_id", "selected_ohlcv_columns", "selected_range_start_ms", "created_at_utc"):
            assert getattr(result, field) == getattr(seed, field)
        values = service.creation_store.load_seed_values(seed.seed_id)
        assert values.startswith(old) and _rows(values)[1:len(_rows(old))] == _rows(old)[1:]
        assert result.row_count == result.source_row_count == count
        assert result.values_sha256 == sha256(values).hexdigest()
        source_rows = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
        indices = [source_rows[0].index(name) for name in ("ts_ms", *columns)]
        assert _rows(values) == [[row[i] for i in indices] for row in source_rows]
        assert result.source_ohlcv == artifacts.capture_accepted_source(MARKET)
        assert _tree(historical) == source_before
        assert _tree(service.creation_store.root_dir / "databases") == databases
        assert _tree(service.creation_store.root_dir / "artifact_collections") == collections
        assert service.load_database_revision(base.database_id).manifest == base
        assert service.load_database_revision(populated.database_id).manifest == populated
        assert set(_seed_tree(service)) == {f"{seed.seed_id}/manifest.json", f"{seed.seed_id}/values.csv"}
        old = values
    extended = service.execute_seed_only_database_creation(service.plan_seed_only_database_creation(seed.seed_id, "Extended base"))
    assert extended.row_count == 128
    assert service.load_database_revision(extended.database_id).values_csv == old


def test_optional_reload_unavailable_source_and_current_are_read_only(tmp_path):
    service, historical, seed, old, _plan = _fixture(tmp_path)
    before = _seed_tree(service)
    reopened, *_ = _domain(tmp_path, initialize=False)
    assert reopened.load_database_seed(seed.seed_id) == seed
    assert reopened.validate_database_seed(seed.seed_id)[0]
    assert reopened.creation_store.load_seed_values(seed.seed_id) == old
    assert _seed_tree(service) == before
    csv_path = OHLCVStore(historical).csv_path(MARKET)
    csv_path.rename(csv_path.with_suffix(".unavailable"))
    assert reopened.validate_database_seed(seed.seed_id)[0]
    assert reopened.load_database_seed(seed.seed_id) == seed
    with pytest.raises((ArtifactError, ValueError, OSError)):
        reopened.plan_database_seed_append(seed.seed_id)
    assert _seed_tree(service) == before


def test_current_preserves_old_fingerprint_and_never_publishes(tmp_path):
    service, _, _, historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "Current")
    rows = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
    rows[1][1] += "0"
    _publish_raw(historical, rows)
    before = _tree(tmp_path)
    plan = service.plan_database_seed_append(seed.seed_id)
    assert plan.appended_row_count == 0 and plan.seed == seed
    assert plan.source_ohlcv != seed.source_ohlcv
    assert service.execute_database_seed_append(plan, before_publish=lambda: pytest.fail("no-op publication")) == seed
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("legacy", ("v1", "v2"))
def test_legacy_subset_columns_and_start_retained(tmp_path, legacy):
    service, _, _, historical = _domain(tmp_path)
    initial = service.plan_database_seed_creation(MARKET, "Legacy subset")
    selected = [initial.values_csv.splitlines()[0], *initial.values_csv.splitlines()[5:81]]
    rows = _rows(b"\n".join(selected)+b"\n")
    values = _serialize([[row[i] for i in (0, 1, 4)] for row in rows])
    seed = replace(initial.seed, selected_ohlcv_columns=("open", "close"), column_count=3,
                   selected_range_start_ms=int(rows[1][0]), selected_range_end_ms=int(rows[-1][0]),
                   row_count=len(rows)-1, values_sha256=sha256(values).hexdigest())
    if legacy == "v1":
        data = seed.to_dict()
        for key in ("row_count", "column_count", "values_sha256"):
            data.pop(key)
        data["schema_version"] = "1.0"
        seed = DatabaseSeedV1.from_dict(data)
        service.creation_store.save_seed(seed)
    else:
        # Historical payload without terminal LF remains a literal prefix.
        values = values.rstrip(b"\n")
        seed = replace(seed, values_sha256=sha256(values).hexdigest())
        service.creation_store.save_seed(seed, values_csv=values)
    _append(historical, rows=104)
    plan = service.plan_database_seed_append(seed.seed_id)
    assert plan.previous_row_count == 76 and plan.appended_row_count == 24
    assert plan.values_csv.startswith(values)
    result = service.execute_database_seed_append(plan)
    assert type(result) is type(seed) and result.seed_id == seed.seed_id
    assert result.selected_ohlcv_columns == ("open", "close")
    assert result.selected_range_start_ms == seed.selected_range_start_ms
    assert result.created_at_utc == seed.created_at_utc
    if legacy == "v1":
        assert set(_seed_tree(service)) == {seed.seed_id+".json"}
        assert service._creation._seed_base_values(result) == plan.values_csv
        changed = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
        changed[1][1] += "0"
        _publish_raw(historical, changed)
        with pytest.raises(DataManagerCreationError):
            service.plan_database_seed_append(seed.seed_id)
    else:
        assert service.creation_store.load_seed_values(seed.seed_id) == plan.values_csv


def test_precise_suffix_tokens_and_rewritten_v2_history(tmp_path):
    service, historical, seed, old, _plan = _fixture(tmp_path)
    rows = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
    rows[1][1] += "0001"
    rows[97][1:] = ["99.80000000000000000000000000001", "1.010000000000000000000001e+2", "+99.00000000000000", "100.000000000000000000000000001", "1.0000000000000000000000001E+3"]
    _publish_raw(historical, rows)
    before = _tree(historical)
    plan = service.plan_database_seed_append(seed.seed_id)
    assert plan.values_csv.startswith(old)
    assert _rows(plan.values_csv)[97:] == rows[97:]
    service.execute_database_seed_append(plan)
    assert _tree(historical) == before


@pytest.mark.parametrize("bad", ("boundary", "interior", "blank", "nan", "inf"))
def test_invalid_source_publishes_nothing(tmp_path, bad):
    service, historical, seed, _old, _plan = _fixture(tmp_path)
    rows = _rows(OHLCVStore(historical).csv_path(MARKET).read_bytes())
    if bad in {"boundary", "interior"}:
        rows.pop(97 if bad == "boundary" else 100)
    else:
        rows[97][1] = {"blank": "", "nan": "NaN", "inf": "inf"}[bad]
    if bad in {"boundary", "interior"}:
        _publish_raw(historical, rows)
    else:
        # Deliberately malformed raw bytes with matching fixture evidence must
        # still be rejected by the loader/snapshot path, not silently copied.
        store = OHLCVStore(historical)
        path = store.csv_path(MARKET)
        path.write_bytes(_serialize(rows))
        sidecar = store.read_sidecar(MARKET)
        lineage = dict(sidecar.lineage, file_size=path.stat().st_size, file_mtime_ns=path.stat().st_mtime_ns)
        store._write_sidecar_atomic(store.sidecar_path(MARKET), replace(
            sidecar, file_sha256=sha256(path.read_bytes()).hexdigest(), lineage=lineage,
        ))
    before = _tree(tmp_path)
    with pytest.raises((ArtifactError, ValueError, OSError)):
        service.plan_database_seed_append(seed.seed_id)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("guard", ("stale_source", "stale_seed", "cancelled", "refused", "source_at_fence", "cancel_at_fence"))
def test_execution_guards_preserve_old_snapshot(tmp_path, guard):
    service, historical, seed, old, plan = _fixture(tmp_path)
    path = service.creation_store.root_dir / "database_seeds" / seed.seed_id / "manifest.json"
    if guard == "stale_source":
        _append(historical, rows=105)
    if guard == "stale_seed":
        seed = replace(seed, description="Changed after preview")
        path.write_bytes(seed.canonical_json_bytes())
    before = _seed_tree(service)
    cancelled = [guard == "cancelled"]
    def publication():
        assert service.load_database_seed(seed.seed_id) == seed
        assert service.creation_store.load_seed_values(seed.seed_id) == old
        if guard == "refused":
            raise DataManagerCreationError("refused")
        if guard == "source_at_fence":
            _append(historical, rows=105)
        if guard == "cancel_at_fence":
            cancelled[0] = True
    with pytest.raises(DataManagerCreationError):
        service.execute_database_seed_append(plan, cancellation_requested=lambda: cancelled[0], before_publish=publication)
    assert _seed_tree(service) == before


class Interrupted(BaseException):
    pass


def _interrupt(monkeypatch, store, point, error_type):
    original_atomic, original_immutable, original_unlink = store._write_atomic, store._write_immutable, Path.unlink
    fired = []
    def fail():
        if not fired:
            fired.append(point)
            raise error_type(point)
    def immutable(path, payload):
        is_record = path.name.startswith(".seed-append-") and path.suffix == ".json"
        is_backup = path.parent.name.startswith(".seed-append-")
        if is_backup and point == "before_backup_"+path.name:
            fail()
        if is_record and point == "before_record":
            fail()
        original_immutable(path, payload)
        if is_backup and point == "after_backup_"+path.name:
            fail()
        if is_record and point == "record":
            fail()
    def atomic(path, payload):
        original_atomic(path, payload)
        if path.parent.name.startswith("seed_") and point == path.name:
            fail()
    def unlink(path, *args, **kwargs):
        original_unlink(path, *args, **kwargs)
        if path.name.startswith(".seed-append-") and path.suffix == ".json" and point == "committed":
            fail()
    monkeypatch.setattr(store, "_write_immutable", immutable)
    monkeypatch.setattr(store, "_write_atomic", atomic)
    monkeypatch.setattr(Path, "unlink", unlink)
    return fail if point == "publication" else None


@pytest.mark.parametrize("point", ("before_backup_manifest.json", "after_backup_manifest.json",
                                   "before_backup_values.csv", "after_backup_values.csv",
                                   "before_record", "values.csv", "manifest.json", "publication"))
def test_ordinary_io_failure_rolls_back_exact_pair(tmp_path, monkeypatch, point):
    service, _historical, seed, old, plan = _fixture(tmp_path)
    before = _seed_tree(service)
    publication = _interrupt(monkeypatch, service.creation_store, point, OSError)
    with pytest.raises(OSError, match=point):
        service.execute_database_seed_append(plan, before_publish=publication)
    assert _seed_tree(service) == before
    assert service.load_database_seed(seed.seed_id) == seed
    assert service.creation_store.load_seed_values(seed.seed_id) == old


@pytest.mark.parametrize("point", ("before_record", "record", "values.csv", "manifest.json", "publication", "committed"))
@pytest.mark.parametrize("next_action", ("retry", "delete"))
def test_interruption_read_only_reload_then_explicit_recovery(tmp_path, monkeypatch, point, next_action):
    service, _historical, seed, old, plan = _fixture(tmp_path)
    with monkeypatch.context() as patch:
        publication = _interrupt(patch, service.creation_store, point, Interrupted)
        with pytest.raises(Interrupted, match=point):
            service.execute_database_seed_append(plan, before_publish=publication)
    reopened = DataManagerCreationStore(service.creation_store.root_dir)
    expected = plan.seed if point == "committed" else seed
    expected_values = plan.values_csv if point == "committed" else old
    before = _seed_tree(service)
    assert reopened.load_seed(seed.seed_id) == expected
    assert reopened.load_seed_values(seed.seed_id) == expected_values
    assert reopened.list_seeds() == (expected,)
    assert service.validate_database_seed(seed.seed_id)[0]
    assert _seed_tree(service) == before
    if next_action == "delete":
        reopened.delete_seed(seed.seed_id)
        assert reopened.list_seeds() == ()
        assert not (reopened.root_dir / "database_seeds" / f".seed-append-{seed.seed_id}.json").exists()
    else:
        result = service.execute_database_seed_append(service.plan_database_seed_append(seed.seed_id))
        assert result == plan.seed and result.row_count == 104
        assert reopened.load_seed_values(seed.seed_id) == plan.values_csv


def _pending_fixture(tmp_path, monkeypatch):
    service, historical, seed, old, plan = _fixture(tmp_path)
    with monkeypatch.context() as patch:
        _interrupt(patch, service.creation_store, "manifest.json", Interrupted)
        with pytest.raises(Interrupted):
            service.execute_database_seed_append(plan)
    record = service.creation_store.root_dir / "database_seeds" / f".seed-append-{seed.seed_id}.json"
    data = json.loads(record.read_bytes())
    backup = record.parent / f".seed-append-{seed.seed_id}-{data['backup_token']}"
    return service, historical, seed, old, plan, record, backup


@pytest.mark.parametrize("tamper", ("bool_version", "extra", "token", "identity", "hash", "encoding", "missing_backup", "backup_bytes", "v1"))
def test_pending_tampering_fails_closed_without_deletion(tmp_path, monkeypatch, tamper):
    service, _historical, seed, _old, _plan, record, backup = _pending_fixture(tmp_path, monkeypatch)
    data = json.loads(record.read_bytes())
    if tamper == "bool_version": data["version"] = True
    if tamper == "extra": data["path"] = "../escape"
    if tamper == "token": data["backup_token"] = "../"+"a"*29
    if tamper == "identity": data["seed_id"] = "seed_"+"f"*32
    if tamper == "hash": data["values_sha256"] = "0"*64
    record.write_bytes(canonical_json_bytes(data) if tamper != "encoding" else json.dumps(data, indent=2).encode())
    if tamper == "missing_backup": (backup / "values.csv").unlink()
    if tamper == "backup_bytes": (backup / "values.csv").write_bytes(b"tampered")
    if tamper == "v1": (record.parent / (seed.seed_id+".json")).write_bytes(b"{}")
    before = _tree(tmp_path)
    for call in (lambda: service.creation_store.load_seed(seed.seed_id),
                 lambda: service.creation_store.load_seed_values(seed.seed_id),
                 service.creation_store.list_seeds, lambda: service.creation_store.delete_seed(seed.seed_id)):
        with pytest.raises((DataManagerCreationError, OSError)):
            call()
        assert _tree(tmp_path) == before


def test_pending_noop_never_recovers(tmp_path, monkeypatch):
    service, historical, seed, old, _plan, _record, _backup = _pending_fixture(tmp_path, monkeypatch)
    _append(historical, rows=96)
    before = _tree(tmp_path)
    plan = service.plan_database_seed_append(seed.seed_id)
    assert plan.appended_row_count == 0
    assert service.execute_database_seed_append(plan) == seed
    assert service.creation_store.load_seed_values(seed.seed_id) == old
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("tamper", ("record", "backup", "collision"))
def test_operation_ownership_is_rechecked_and_foreign_evidence_retained(tmp_path, monkeypatch, tamper):
    service, _historical, seed, _old, plan = _fixture(tmp_path)
    store = service.creation_store
    root = store.root_dir / "database_seeds"
    record = root / f".seed-append-{seed.seed_id}.json"
    captured = []
    def interfere():
        data = json.loads(record.read_bytes())
        if tamper == "backup":
            (root / f".seed-append-{seed.seed_id}-{data['backup_token']}" / "values.csv").write_bytes(b"foreign")
        else:
            record.write_bytes(b"foreign record")
        captured.append(_seed_tree(service))
    if tamper == "collision":
        original = store._write_immutable
        def collision(path, payload):
            if path == record:
                record.write_bytes(b"foreign record")
                captured.append(_seed_tree(service))
            return original(path, payload)
        monkeypatch.setattr(store, "_write_immutable", collision)
    with pytest.raises(DataManagerCreationError):
        service.execute_database_seed_append(plan, before_publish=None if tamper == "collision" else interfere)
    assert len(captured) == 1 and _seed_tree(service) == captured[0]


def test_failed_rollback_keeps_readable_old_recovery_pair(tmp_path, monkeypatch):
    service, _historical, seed, old, plan = _fixture(tmp_path)
    def fail_restore(*_args): raise OSError("rollback unavailable")
    monkeypatch.setattr(service.creation_store, "_restore_atomic_target", fail_restore)
    with pytest.raises(OSError, match="rollback unavailable"):
        service.execute_database_seed_append(plan, before_publish=lambda: (_ for _ in ()).throw(OSError("refuse")))
    reopened = DataManagerCreationStore(service.creation_store.root_dir)
    assert reopened.load_seed(seed.seed_id) == seed
    assert reopened.load_seed_values(seed.seed_id) == old


def test_postcommit_cleanup_oserror_does_not_misreport_commit(tmp_path, monkeypatch):
    service, _historical, seed, _old, plan = _fixture(tmp_path)
    original = Path.unlink
    def fail_backup(path, *args, **kwargs):
        if path.parent.name.startswith(".seed-append-") and path.name == "manifest.json":
            raise OSError("backup cleanup unavailable")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_backup)
    assert service.execute_database_seed_append(plan) == plan.seed
    assert service.creation_store.load_seed_values(seed.seed_id) == plan.values_csv


def test_pending_backup_symlink_is_rejected(tmp_path, monkeypatch):
    service, _historical, seed, _old, _plan, _record, backup = _pending_fixture(tmp_path, monkeypatch)
    moved = backup.with_name(backup.name+"-original")
    backup.rename(moved)
    try:
        backup.symlink_to(moved, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink privilege unavailable: {exc}")
    with pytest.raises(DataManagerCreationStoreError):
        service.creation_store.load_seed(seed.seed_id)
    assert moved.is_dir() and backup.is_symlink()


def test_immutable_save_and_mixed_seed_enumeration_unchanged(tmp_path):
    service, _, _, _historical = _domain(tmp_path)
    seed = service.create_database_seed(MARKET, "V2")
    data = seed.to_dict()
    for key in ("row_count", "column_count", "values_sha256"): data.pop(key)
    data.update(schema_version="1.0", seed_id="seed_"+"f"*32, display_name="V1")
    legacy = DatabaseSeedV1.from_dict(data)
    service.creation_store.save_seed(legacy)
    before = _seed_tree(service)
    assert {item.seed_id for item in service.list_database_seeds()} == {seed.seed_id, legacy.seed_id}
    with pytest.raises(DataManagerCreationError):
        service.creation_store.save_seed(replace(seed, description="Collision"), values_csv=service.creation_store.load_seed_values(seed.seed_id))
    assert _seed_tree(service) == before


@pytest.mark.parametrize("field,value", (("previous_row_count", True), ("appended_row_count", -1),
                                       ("previous_seed_sha256", "bad"), ("previous_values_sha256", "bad"),
                                       ("plan_id", "0"*64), ("values_csv", b"bad")))
def test_append_plan_rejects_invalid_fields(tmp_path, field, value):
    service, _historical, _seed, _old, plan = _fixture(tmp_path)
    before = _seed_tree(service)
    with pytest.raises((TypeError, DataManagerCreationError)):
        replace(plan, **{field: value})
    assert _seed_tree(service) == before


def test_rehashed_forged_append_plan_is_still_stale(tmp_path):
    service, _historical, _seed, _old, plan = _fixture(tmp_path)
    candidate = replace(plan.seed, description="Not the reviewed identity")
    payload = plan.identity_payload()
    payload["seed"] = candidate.to_dict()
    forged = replace(plan, seed=candidate, plan_id=deterministic_hash(payload))
    before = _seed_tree(service)
    with pytest.raises(DataManagerCreationError, match="stale"):
        service.execute_database_seed_append(forged)
    assert _seed_tree(service) == before
