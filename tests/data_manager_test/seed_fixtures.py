"""Explicit saved historical Seed snapshots for Database regression fixtures."""

import csv
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO

from leonardo.data_manager import DatabaseSeedV2


def create_legacy_seed_v2(
    service, market, name, *, start_ms, end_ms,
    columns=("open", "close", "volume"), description="Selected OHLCV base",
):
    source = service._artifacts.capture_accepted_source(market)
    dataset = service._loader.load(market)
    rows = list(csv.reader(StringIO(dataset.csv_path.read_text(encoding="utf-8"))))
    header = rows[0]
    selected = ("ts_ms", *columns)
    indices = tuple(header.index(column) for column in selected)
    owned_rows = [
        tuple(row[index] for index in indices)
        for row in rows[1:] if start_ms <= int(row[0]) <= end_ms
    ]
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(selected)
    writer.writerows(owned_rows)
    values = output.getvalue().encode("utf-8")
    seed = DatabaseSeedV2(
        seed_id=service.creation_store.new_seed_id(), display_name=name,
        description=description, market_id=market, source_ohlcv=source,
        source_row_count=dataset.row_count,
        first_timestamp_ms=dataset.first_timestamp_ms,
        last_timestamp_ms=dataset.last_timestamp_ms,
        selected_ohlcv_columns=columns,
        selected_range_start_ms=start_ms, selected_range_end_ms=end_ms,
        created_at_utc=datetime.now(UTC), row_count=len(owned_rows),
        column_count=len(selected), values_sha256=sha256(values).hexdigest(),
    )
    return service.creation_store.save_seed(seed, values_csv=values)
