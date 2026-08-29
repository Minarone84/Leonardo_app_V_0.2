"""Canonical presentation helpers for Data Manager tables."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, TypeVar

from PySide6.QtWidgets import QTableWidget

from leonardo.data_manager import DataManagerDatasetEntry
from leonardo.gui.table_sizing import resize_table_columns_to_contents


DATA_MANAGER_DATASET_COLUMNS = (
    "Exchange",
    "Market Type",
    "Symbol",
    "Timeframe",
    "Status",
    "Persistence",
    "Validation",
    "Rows",
    "First Data UTC",
    "Last Data UTC",
    "Details",
)


_TIMESTAMP_FIELD_NAMES = {
    "first_timestamp_ms",
    "last_timestamp_ms",
    "selected_range_start_ms",
    "selected_range_end_ms",
    "snapshot_through_ms",
    "collection_through_ms",
    "aligned_through_ms",
    "ohlcv_through_ms",
    "artifact_through_ms",
    "previous_through_ms",
    "current_through_ms",
}

DataManagerSortKind = Literal["text", "number", "utc"]
_RowValue = TypeVar("_RowValue")


def sort_data_manager_rows(
    rows: Iterable[tuple[tuple[str, ...], _RowValue]],
    *,
    column: int,
    kind: DataManagerSortKind,
    descending: bool,
) -> tuple[tuple[tuple[str, ...], _RowValue], ...]:
    """Sort projected Data Manager rows while retaining their domain values."""
    materialized = tuple(rows)
    if type(column) is not int or column < 0:
        raise ValueError("column must be a non-negative integer")
    if kind not in {"text", "number", "utc"}:
        raise ValueError(f"unsupported Data Manager sort kind: {kind}")
    if type(descending) is not bool:
        raise TypeError("descending must be a boolean")
    if any(column >= len(values) for values, _value in materialized):
        raise IndexError("sort column is outside a projected row")

    populated = tuple(
        row for row in materialized if row[0][column].strip()
    )
    blanks = tuple(
        row for row in materialized if not row[0][column].strip()
    )

    def key(row: tuple[tuple[str, ...], _RowValue]) -> object:
        value = row[0][column].strip()
        if kind == "text":
            return value.casefold()
        if kind == "number":
            return Decimal(value.replace(",", ""))
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(
            tzinfo=UTC
        )

    return tuple(sorted(populated, key=key, reverse=descending)) + blanks


def format_utc_timestamp_ms(value: int | None) -> str:
    """Format an epoch-millisecond value for Data Manager presentation."""
    if value is None:
        return ""
    if type(value) is not int:
        raise TypeError("timestamp value must be an integer or None")
    return datetime.fromtimestamp(value / 1000, tz=UTC).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def format_utc_datetime(value: datetime | None) -> str:
    """Format a timezone-aware datetime in UTC for Data Manager presentation."""
    if value is None:
        return ""
    if not isinstance(value, datetime):
        raise TypeError("datetime value must be a datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime value must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_data_manager_value(field_name: str, value: object) -> str:
    """Format an Inspector value without changing its domain representation."""
    if isinstance(value, datetime):
        return format_utc_datetime(value)
    if type(value) is int and (
        field_name.endswith("_timestamp_ms")
        or field_name.endswith("_through_ms")
        or field_name in _TIMESTAMP_FIELD_NAMES
    ):
        return format_utc_timestamp_ms(value)
    return str(value)


def data_manager_dataset_row(
    entry: DataManagerDatasetEntry,
) -> tuple[str, ...]:
    """Project one canonical dataset catalog entry for GUI tables."""
    if not isinstance(entry, DataManagerDatasetEntry):
        raise TypeError("entry must be a DataManagerDatasetEntry")
    market = entry.market_id
    return (
        "" if market is None else market.exchange,
        "" if market is None else market.market_type,
        "" if market is None else market.symbol,
        "" if market is None else market.timeframe,
        "accepted" if entry.accepted else "rejected",
        entry.persistence_status,
        entry.validation_status,
        "" if entry.row_count is None else f"{entry.row_count:,}",
        format_utc_timestamp_ms(entry.first_timestamp_ms),
        format_utc_timestamp_ms(entry.last_timestamp_ms),
        data_manager_dataset_details(entry),
    )


def data_manager_dataset_details(entry: DataManagerDatasetEntry) -> str:
    """Project selector-compatible dataset detail text."""
    if not isinstance(entry, DataManagerDatasetEntry):
        raise TypeError("entry must be a DataManagerDatasetEntry")
    if not entry.accepted:
        return ": ".join(
            value
            for value in (entry.rejection_code, entry.rejection_reason)
            if value
        )
    details = [value for value in entry.warnings if value]
    return " | ".join(details) or "Accepted canonical OHLCV dataset"


def resize_data_manager_table(table: QTableWidget) -> None:
    """Resize a Data Manager table using the application content-size policy."""
    resize_table_columns_to_contents(table)
