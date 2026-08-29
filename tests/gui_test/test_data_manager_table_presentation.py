from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerDatasetEntry,
    DataManagerPreview,
    DataManagerReconciliationSnapshot,
    DataManagerSourceChange,
)
from leonardo.gui.data_manager.catalogs import DataManagerCatalogWorkspace
from leonardo.gui.data_manager.creation import DataManagerCreationWorkspace
from leonardo.gui.data_manager.operations import DataManagerOperationSurface
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    data_manager_dataset_details,
    data_manager_dataset_row,
    format_utc_timestamp_ms,
    resize_data_manager_table,
    sort_data_manager_rows,
)
from leonardo.gui.data_manager.update import DataManagerUpdateWorkspace
from leonardo.gui.windows.data_manager_preview_dialog import DataManagerPreviewDialog
from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot


TIMESTAMP_MS = 1786297337123
EXPECTED_TIMESTAMP = "2026-08-09 17:42:17 UTC"


def _sort_rows(*values: str):
    return tuple(((value,), index) for index, value in enumerate(values))


def test_typed_row_sorting_is_case_insensitive_stable_and_non_mutating() -> None:
    rows = _sort_rows("Zulu", "alpha", "ALPHA", "bravo")
    ascending = sort_data_manager_rows(
        rows, column=0, kind="text", descending=False
    )
    descending = sort_data_manager_rows(
        rows, column=0, kind="text", descending=True
    )

    assert tuple(row[0][0] for row in ascending) == (
        "alpha", "ALPHA", "bravo", "Zulu"
    )
    assert tuple(row[0][0] for row in descending) == (
        "Zulu", "bravo", "alpha", "ALPHA"
    )
    assert rows == _sort_rows("Zulu", "alpha", "ALPHA", "bravo")


def test_typed_row_sorting_uses_numeric_values_and_comma_grouping() -> None:
    rows = _sort_rows("100", "2", "12,345", "10")
    ascending = sort_data_manager_rows(
        rows, column=0, kind="number", descending=False
    )
    descending = sort_data_manager_rows(
        rows, column=0, kind="number", descending=True
    )

    assert tuple(row[0][0] for row in ascending) == (
        "2", "10", "100", "12,345"
    )
    assert tuple(row[0][0] for row in descending) == (
        "12,345", "100", "10", "2"
    )


def test_typed_row_sorting_uses_utc_chronology_in_both_directions() -> None:
    rows = _sort_rows(
        "2026-08-09 00:00:00 UTC",
        "2026-07-30 00:00:00 UTC",
        "2026-08-16 00:00:00 UTC",
    )
    ascending = sort_data_manager_rows(
        rows, column=0, kind="utc", descending=False
    )
    descending = sort_data_manager_rows(
        rows, column=0, kind="utc", descending=True
    )

    assert tuple(row[0][0] for row in ascending) == (
        "2026-07-30 00:00:00 UTC",
        "2026-08-09 00:00:00 UTC",
        "2026-08-16 00:00:00 UTC",
    )
    assert tuple(row[0][0] for row in descending) == tuple(
        reversed(tuple(row[0][0] for row in ascending))
    )


@pytest.mark.parametrize("descending", (False, True))
def test_typed_row_sorting_keeps_blanks_last(descending: bool) -> None:
    rows = _sort_rows("", "10", "2", "   ")
    sorted_rows = sort_data_manager_rows(
        rows, column=0, kind="number", descending=descending
    )

    assert tuple(row[0][0] for row in sorted_rows)[-2:] == ("", "   ")


def test_shared_dataset_projection_preserves_selector_display_semantics() -> None:
    entry = DataManagerDatasetEntry(
        MarketId("bybit", "linear", "BTCUSDT", "1h"),
        True,
        12_345,
        TIMESTAMP_MS,
        TIMESTAMP_MS,
        source="canonical",
        persistence_status="persisted",
        validation_status="valid",
        warnings=("warning one", "warning two"),
    )
    assert DATA_MANAGER_DATASET_COLUMNS == (
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
    assert data_manager_dataset_details(entry) == "warning one | warning two"
    assert data_manager_dataset_row(entry) == (
        "bybit",
        "linear",
        "BTCUSDT",
        "1h",
        "accepted",
        "persisted",
        "valid",
        "12,345",
        EXPECTED_TIMESTAMP,
        EXPECTED_TIMESTAMP,
        "warning one | warning two",
    )
    assert str(TIMESTAMP_MS) not in data_manager_dataset_row(entry)


def test_timestamp_formatter_and_shared_resize_are_content_derived() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    assert format_utc_timestamp_ms(TIMESTAMP_MS) == EXPECTED_TIMESTAMP
    table = QTableWidget(1, 1)
    try:
        table.setHorizontalHeaderLabels(("Value",))
        table.setItem(0, 0, QTableWidgetItem("short"))
        resize_data_manager_table(table)
        short = table.columnWidth(0)
        table.item(0, 0).setText("a substantially longer displayed Data Manager value")
        resize_data_manager_table(table)
        assert table.columnWidth(0) > short
    finally:
        table.close()


def test_representative_data_manager_tables_resize_after_population() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    catalog = DataManagerCatalogWorkspace()
    creation = DataManagerCreationWorkspace()
    update = DataManagerUpdateWorkspace()
    operation = DataManagerOperationSurface()
    widgets = (catalog, creation, update, operation)
    try:
        catalog.set_inspection((("field", "short"),))
        catalog_short = catalog.inspector.columnWidth(1)
        catalog.set_inspection((("field", "a substantially longer catalog value"),))
        assert catalog.inspector.columnWidth(1) > catalog_short

        creation.set_recipe_rows((("SMA", "indicator", "x", "0", "ok", "a"),))
        creation_short = creation.recipe_table.columnWidth(5)
        creation.set_recipe_rows((("SMA", "indicator", "x", "0", "ok", "a" * 64),))
        assert creation.recipe_table.columnWidth(5) > creation_short

        update.set_database_update_result(SimpleNamespace(
            mode="APPEND",
            database_revision=SimpleNamespace(
                database_id="db",
                revision_id="d" * 64,
                previous_revision_id=None,
                collection_revision_id="c" * 64,
                row_count=1,
                column_count=1,
                first_timestamp_ms=TIMESTAMP_MS,
                last_timestamp_ms=TIMESTAMP_MS,
                values_sha256="f" * 64,
            ),
        ))
        assert update.commit_report.columnWidth(1) > update.commit_report.columnWidth(0)

        operation.settle("completed", "done", (("Field", "short"),))
        operation_short = operation.details.columnWidth(1)
        operation.settle(
            "completed", "done", (("Field", "a substantially longer operation value"),)
        )
        assert operation.details.columnWidth(1) > operation_short
    finally:
        for widget in widgets:
            widget.close()


def test_creation_and_update_table_identity_columns_are_last() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    creation = DataManagerCreationWorkspace()
    update = DataManagerUpdateWorkspace()

    def headings(table) -> tuple[str, ...]:
        return tuple(
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())
        )

    try:
        assert headings(creation.recipe_table)[-1] == "Recipe ID"
        assert headings(creation.plan_table)[-2:] == (
            "Recipe ID", "Logical Artifact ID"
        )
        assert headings(creation.batch_table)[-1] == "Source Logical Artifact ID"
        assert headings(creation.collection_table)[-1] == "Logical Artifact ID"
        assert headings(update.artifact_plan_table)[-2:] == (
            "Recipe ID", "Logical Artifact ID"
        )
        assert headings(update.collection_validation_table)[-4:] == (
            "Collection ID", "Revision ID", "Root Logical Artifact IDs",
            "Support Logical Artifact IDs",
        )
        assert headings(update.database_plan_table)[-2:] == (
            "Collection Revision ID", "Database ID"
        )
    finally:
        creation.close()
        update.close()


def test_update_through_timestamps_use_canonical_utc_seconds() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    reconciliation = DataManagerReconciliationSnapshot(
        datetime(2026, 8, 9, tzinfo=UTC),
        (
            DataManagerSourceChange(
                market, "APPEND_ONLY", None, None, TIMESTAMP_MS,
                TIMESTAMP_MS, 0, "",
            ),
        ),
        (),
        (),
        (),
        (),
        "0" * 64,
    )
    workspace = DataManagerUpdateWorkspace()
    try:
        workspace.set_snapshot(
            replace(
                empty_product_snapshot(),
                latest_reconciliation=reconciliation,
            )
        )
        table = workspace.reconciliation_tables["sources"]
        assert table.item(0, 2).text() == EXPECTED_TIMESTAMP
        assert table.item(0, 3).text() == EXPECTED_TIMESTAMP
        assert str(TIMESTAMP_MS) not in table.item(0, 2).text()
    finally:
        workspace.close()


def test_preview_timestamp_and_width_use_displayed_content() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    short = DataManagerPreview(
        "Preview", market, "dataset", None, ("value",), (("x",),), 1, False, {}
    )
    long = DataManagerPreview(
        "Preview", market, "dataset", None, ("value",),
        (("a substantially longer preview value",),), 1, False, {},
    )
    timestamp = DataManagerPreview(
        "Preview", market, "dataset", None, ("ts_ms",),
        ((str(TIMESTAMP_MS),),), 1, False, {},
    )
    short_dialog = DataManagerPreviewDialog(short)
    long_dialog = DataManagerPreviewDialog(long)
    timestamp_dialog = DataManagerPreviewDialog(timestamp)
    try:
        short_table = short_dialog.findChild(QTableWidget, "data_manager_preview.table.values")
        long_table = long_dialog.findChild(QTableWidget, "data_manager_preview.table.values")
        timestamp_table = timestamp_dialog.findChild(QTableWidget, "data_manager_preview.table.values")
        assert long_table.columnWidth(0) > short_table.columnWidth(0)
        assert timestamp_table.horizontalHeaderItem(0).text() == "Timestamp"
        assert timestamp_table.item(0, 0).text() == EXPECTED_TIMESTAMP
    finally:
        short_dialog.close()
        long_dialog.close()
        timestamp_dialog.close()
