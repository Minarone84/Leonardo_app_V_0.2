from __future__ import annotations

import csv
from dataclasses import replace
from hashlib import sha256
from io import StringIO

import pytest

from leonardo.data_manager import DatabaseSeedCreationPlan, DatabaseSeedV1, DataManagerCreationError
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.ohlcv.store import OHLCVStore

from tests.data_manager_test.test_seed_only_database_application import _application
from tests.data_manager_test.test_update_workflow import MARKET, _domain


OHLC = ("open", "high", "low", "close")
OHLCV = (*OHLC, "volume")


@pytest.mark.parametrize("columns", (OHLC, OHLCV))
def test_full_source_tokens_metadata_and_owned_database_round_trip(tmp_path, columns):
    service, _artifacts, _recipes, historical = _domain(tmp_path)
    store = OHLCVStore(historical)
    csv_path, sidecar_path = store.csv_path(MARKET), store.sidecar_path(MARKET)
    rows = list(csv.reader(StringIO(csv_path.read_text(encoding="utf-8"))))
    rows[1][1:] = [
        "99.80000000000000000000000000000000001",
        "1.0100000000000000000000000000000001e+2",
        "+99.000000000000000",
        "100.00000000000000000000000000000001",
        "1.00000000000000000000000000000001E+3",
    ]
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerows(rows)
    csv_path.write_bytes(output.getvalue().encode("utf-8"))
    csv_stat, sidecar_stat = csv_path.stat(), sidecar_path.stat()
    store.reconstruct_sidecar(
        MARKET,
        expected_csv_size=csv_stat.st_size,
        expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=sha256(csv_path.read_bytes()).hexdigest(),
        expected_sidecar_size=sidecar_stat.st_size,
        expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=sha256(sidecar_path.read_bytes()).hexdigest(),
        reconstruction_reason="Precise decimal/exponent test fixture",
    )
    sidecar_stat = sidecar_path.stat()
    # Publish precise fixture evidence through the same authority as _accepted_dataset.
    store.publish_validation(
        MARKET,
        expected_csv_size=csv_stat.st_size,
        expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=sha256(csv_path.read_bytes()).hexdigest(),
        expected_sidecar_size=sidecar_stat.st_size,
        expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=sha256(sidecar_path.read_bytes()).hexdigest(),
        status="ok", row_count=len(rows) - 1,
        first_timestamp_ms=int(rows[1][0]), last_timestamp_ms=int(rows[-1][0]),
        warnings=(), issue_codes=(), error_count=0, warning_count=0,
        validator="task-1079-test",
    )
    source_before = (csv_path.read_bytes(), sidecar_path.read_bytes())
    source_stats = (csv_path.stat().st_mtime_ns, sidecar_path.stat().st_mtime_ns)
    plan = service.plan_database_seed_creation(
        MARKET, "Full source", description="Exact copied tokens", selected_ohlcv_columns=columns
    )
    assert service.list_database_seeds() == ()
    seed = service.execute_database_seed_creation(plan)
    assert seed.schema_version == "2.0"
    assert seed.display_name == "Full source" and seed.description == "Exact copied tokens"
    assert seed.market_id == MARKET and seed.created_at_utc.tzinfo is not None
    assert seed.source_ohlcv == service._artifacts.capture_accepted_source(MARKET)
    assert seed.source_ohlcv.csv_sha256 == sha256(source_before[0]).hexdigest()
    assert seed.source_row_count == seed.row_count == len(rows) - 1
    assert seed.first_timestamp_ms == seed.selected_range_start_ms == int(rows[1][0])
    assert seed.last_timestamp_ms == seed.selected_range_end_ms == int(rows[-1][0])
    assert seed.selected_ohlcv_columns == columns
    assert seed.column_count == len(columns) + 1
    assert seed.values_sha256 == sha256(plan.values_csv).hexdigest()
    indices = [rows[0].index(column) for column in ("ts_ms", *columns)]
    expected = [[row[index] for index in indices] for row in rows]
    assert list(csv.reader(StringIO(plan.values_csv.decode("utf-8")))) == expected
    dataset = service._loader.load(MARKET)
    assert tuple(int(row[0]) for row in expected[1:]) == dataset.ts_ms
    assert service.creation_store.load_seed_values(seed.seed_id) == plan.values_csv

    database = service.execute_seed_only_database_creation(
        service.plan_seed_only_database_creation(seed.seed_id, "Full source Database")
    )
    assert database.row_count == seed.row_count
    assert database.column_count == seed.column_count
    assert database.first_timestamp_ms == seed.first_timestamp_ms
    assert database.last_timestamp_ms == seed.last_timestamp_ms
    assert database.values_sha256 == seed.values_sha256
    restarted, *_ = _domain(tmp_path, initialize=False)
    assert restarted.load_database_seed(seed.seed_id) == seed
    assert restarted.creation_store.load_seed_values(seed.seed_id) == plan.values_csv
    loaded = restarted.load_database_revision(database.database_id)
    assert loaded.manifest == database
    assert loaded.values_csv == plan.values_csv
    assert (csv_path.read_bytes(), sidecar_path.read_bytes()) == source_before
    assert (csv_path.stat().st_mtime_ns, sidecar_path.stat().st_mtime_ns) == source_stats


@pytest.mark.parametrize("columns", (
    (), ("volume",), ("open", "close", "volume"),
    *(tuple(column for column in OHLCV if column != missing) for missing in OHLC),
    (*OHLC, "close"), (*OHLCV, "volume"),
    ("high", "open", "low", "close"), ("volume", *OHLC), (*OHLC, "unknown"),
))
def test_new_seed_rejects_every_noncanonical_column_selection(tmp_path, columns):
    service, *_ = _domain(tmp_path)
    for create in (service.plan_database_seed_creation, service.create_database_seed):
        with pytest.raises(DataManagerCreationError, match="OHLC with optional Volume"):
            create(MARKET, "Invalid columns", selected_ohlcv_columns=columns)
    assert service.list_database_seeds() == ()


@pytest.mark.parametrize("keyword", ("selected_range_start_ms", "selected_range_end_ms"))
def test_removed_range_kwargs_fail_at_new_entry_points(tmp_path, keyword):
    app, application = _application(tmp_path)
    try:
        service = app.data_manager_domain
        for create in (
            service._creation.create_database_seed,
            service._creation.plan_database_seed_creation,
            service.create_database_seed,
            service.plan_database_seed_creation,
            application.submit_create_database_seed,
            application.submit_plan_database_seed_creation,
        ):
            with pytest.raises(TypeError, match=keyword):
                create(MARKET, "No range API", **{keyword: 1})
        assert service.list_database_seeds() == ()
        assert app.task_manager.snapshots() == ()
    finally:
        app.shutdown()


@pytest.mark.parametrize("forgery", ("cropped", "incomplete", "altered", "v1"))
def test_manually_constructed_creation_plan_cannot_bypass_full_source(tmp_path, forgery):
    service, *_ = _domain(tmp_path)
    original = service.plan_database_seed_creation(MARKET, "Forged candidate")
    seed = original.seed
    rows = list(csv.reader(StringIO(original.values_csv.decode("utf-8"))))
    if forgery == "v1":
        seed = DatabaseSeedV1(
            seed_id=seed.seed_id, display_name=seed.display_name, description=seed.description,
            market_id=seed.market_id, source_ohlcv=seed.source_ohlcv,
            source_row_count=seed.source_row_count,
            first_timestamp_ms=seed.first_timestamp_ms, last_timestamp_ms=seed.last_timestamp_ms,
            selected_ohlcv_columns=seed.selected_ohlcv_columns,
            selected_range_start_ms=seed.selected_range_start_ms,
            selected_range_end_ms=seed.selected_range_end_ms, created_at_utc=seed.created_at_utc,
        )
        values = None
    else:
        if forgery == "cropped":
            rows = [rows[0], *rows[5:-3]]
            seed = replace(seed, row_count=len(rows) - 1,
                           selected_range_start_ms=int(rows[1][0]),
                           selected_range_end_ms=int(rows[-1][0]))
        elif forgery == "incomplete":
            rows = [[row[index] for index in (0, 1, 4, 5)] for row in rows]
            seed = replace(seed, selected_ohlcv_columns=("open", "close", "volume"), column_count=4)
        else:
            rows[1][1] += "0"
        output = StringIO(newline="")
        csv.writer(output, lineterminator="\n").writerows(rows)
        values = output.getvalue().encode("utf-8")
        seed = replace(seed, values_sha256=sha256(values).hexdigest())
    forged = DatabaseSeedCreationPlan(deterministic_hash(seed.to_dict()), seed, values)
    with pytest.raises(DataManagerCreationError, match="new Seed"):
        service.execute_database_seed_creation(forged)
    assert service.list_database_seeds() == ()
    root = service.creation_store.root_dir / "database_seeds"
    assert not root.exists() or not tuple(root.iterdir())


@pytest.mark.parametrize("cancel_at", (1, 2, 3))
def test_full_source_creation_cancellation_preserves_no_publication(tmp_path, cancel_at):
    service, *_ = _domain(tmp_path)
    plan = service.plan_database_seed_creation(MARKET, "Cancelled")
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks == cancel_at

    with pytest.raises(DataManagerCreationError, match="cancelled"):
        service.execute_database_seed_creation(plan, cancellation_requested=cancelled)
    assert service.list_database_seeds() == ()
    root = service.creation_store.root_dir / "database_seeds"
    assert not root.exists() or not tuple(root.iterdir())
