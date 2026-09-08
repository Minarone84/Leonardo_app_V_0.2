from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QCheckBox

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerDatasetEntry,
    DatabaseSeedCreationPlan,
    DatabaseSeedV1,
    SeedOnlyDatabaseCreationPlan,
)
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.gui.windows.data_manager_database_creation_dialog import (
    DATA_MANAGER_DATABASE_CREATION_WINDOW_ID,
    DataManagerDatabaseCreationDialog,
)
from leonardo.gui.windows.data_manager_database_seed_dialog import (
    DATA_MANAGER_DATABASE_SEED_WINDOW_ID,
    DataManagerDatabaseSeedDialog,
)
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")
FIRST = 1_788_739_200_000
LAST = FIRST + 59 * 60_000


def _dataset() -> DataManagerDatasetEntry:
    return DataManagerDatasetEntry(
        MARKET,
        True,
        60,
        FIRST,
        LAST,
        "test",
        "committed",
        "ok",
    )


def _source() -> OHLCVSourceFingerprintV1:
    return OHLCVSourceFingerprintV1(
        MARKET,
        "1" * 64,
        "2" * 64,
        60,
        FIRST,
        LAST,
        "committed",
        "ok",
        "1.0",
    )


def _seed() -> DatabaseSeedV1:
    return DatabaseSeedV1(
        "seed_" + "a" * 32,
        "Base Seed",
        "Selected source",
        MARKET,
        _source(),
        60,
        FIRST,
        LAST,
        ("open", "close", "volume"),
        FIRST,
        LAST,
        datetime(2026, 9, 7, tzinfo=UTC),
    )


def _seed_plan(seed: DatabaseSeedV1) -> DatabaseSeedCreationPlan:
    return DatabaseSeedCreationPlan(deterministic_hash(seed.to_dict()), seed)


def _database_plan(seed: DatabaseSeedV1) -> SeedOnlyDatabaseCreationPlan:
    values = {
        "seed_id": seed.seed_id,
        "seed_sha256": hashlib.sha256(seed.canonical_json_bytes()).hexdigest(),
        "source_ohlcv": seed.source_ohlcv,
        "display_name": "Base Database",
        "description": "",
        "column_names": ("ts_ms", *seed.selected_ohlcv_columns),
        "row_count": seed.source_row_count,
        "first_timestamp_ms": seed.selected_range_start_ms,
        "last_timestamp_ms": seed.selected_range_end_ms,
    }
    draft = SeedOnlyDatabaseCreationPlan.__new__(SeedOnlyDatabaseCreationPlan)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    payload = {
        "seed_id": values["seed_id"],
        "seed_sha256": values["seed_sha256"],
        "source_ohlcv": seed.source_ohlcv.to_dict(),
        "display_name": values["display_name"],
        "description": values["description"],
        "column_names": list(values["column_names"]),
        "row_count": values["row_count"],
        "first_timestamp_ms": values["first_timestamp_ms"],
        "last_timestamp_ms": values["last_timestamp_ms"],
    }
    return SeedOnlyDatabaseCreationPlan(deterministic_hash(payload), **values)


def test_database_seed_dialog_form_preview_recovery_and_geometry() -> None:
    qapp = QApplication.instance() or QApplication([])
    dialog = DataManagerDatabaseSeedDialog(_dataset())
    try:
        available = qapp.primaryScreen().availableGeometry()
        assert dialog.objectName() == DATA_MANAGER_DATABASE_SEED_WINDOW_ID
        assert dialog.width() == round(available.width() * 0.50)
        assert dialog.height() == round(available.height() * 0.65)
        assert dialog.range_start.timeSpec() == Qt.TimeSpec.UTC
        assert dialog.range_end.timeSpec() == Qt.TimeSpec.UTC
        assert not dialog.create_button.isEnabled()

        requests: list[dict[str, object]] = []
        dialog.preview_requested.connect(requests.append)
        dialog.name_edit.setText(" Invalid ")
        assert not dialog.preview_button.isEnabled()
        dialog.name_edit.setText("Base Seed")
        dialog.column_checks["high"].setChecked(False)
        dialog.column_checks["low"].setChecked(False)
        assert dialog.preview_button.isEnabled()
        dialog.preview_button.click()
        assert requests == [{
            "market_id": MARKET,
            "display_name": "Base Seed",
            "description": "",
            "selected_ohlcv_columns": ("open", "close", "volume"),
            "selected_range_start_ms": FIRST,
            "selected_range_end_ms": LAST,
        }]

        plan = _seed_plan(_seed())
        dialog.set_plan(plan)
        assert dialog.create_button.isEnabled()
        assert dialog.preview_table.rowCount() == 7
        dialog.description_edit.setText("Changed")
        assert dialog.reviewed_plan is None
        assert not dialog.create_button.isEnabled()
        assert dialog.preview_button.isEnabled()
        dialog.set_busy(True)
        assert not dialog.preview_button.isEnabled()
        assert not dialog.name_edit.isEnabled()
        assert dialog.close_button.isEnabled()
        dialog.resize(640, 480)
        assert dialog.preview_table.width() > 0
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_seed_only_database_dialog_snapshot_selection_and_invalidation() -> None:
    qapp = QApplication.instance() or QApplication([])
    seed = _seed()
    snapshot = replace(empty_product_snapshot(), database_seeds=(seed,))
    dialog = DataManagerDatabaseCreationDialog(snapshot, selected_seed=seed)
    try:
        available = qapp.primaryScreen().availableGeometry()
        assert dialog.objectName() == DATA_MANAGER_DATABASE_CREATION_WINDOW_ID
        assert dialog.width() == round(available.width() * 0.50)
        assert dialog.height() == round(available.height() * 0.60)
        assert dialog.selected_seed() == seed
        assert tuple(
            dialog.seed_table.horizontalHeaderItem(column).text()
            for column in range(dialog.seed_table.columnCount())
        ) == (
            "Select",
            "Name",
            "Exchange",
            "Market Type",
            "Asset",
            "Timeframe",
            "Columns",
            "Range Start",
            "Range End",
        )
        assert dialog.seed_table.item(0, 1).data(Qt.ItemDataRole.UserRole) == seed.seed_id
        checkbox = dialog.seed_table.cellWidget(0, 0)
        assert isinstance(checkbox, QCheckBox)
        assert checkbox.isChecked()
        assert "indicator:checked" in checkbox.styleSheet()
        assert "indicator:unchecked" in checkbox.styleSheet()
        assert not dialog.create_button.isEnabled()

        requests: list[dict[str, object]] = []
        dialog.preview_requested.connect(requests.append)
        dialog.name_edit.setText("Base Database")
        dialog.preview_button.click()
        assert requests == [{
            "seed_id": seed.seed_id,
            "display_name": "Base Database",
            "description": "",
        }]
        plan = _database_plan(seed)
        dialog.set_plan(plan)
        assert dialog.create_button.isEnabled()
        assert dialog.preview_table.rowCount() == 11
        dialog.name_edit.setText("Revised Database")
        assert dialog.reviewed_plan is None
        assert not dialog.create_button.isEnabled()

        dialog.set_catalog(snapshot, selected_seed=seed)
        assert dialog.selected_seed() == seed
        assert dialog.reviewed_plan is None
        dialog.set_busy(True)
        assert not dialog.seed_table.isEnabled()
        assert dialog.close_button.isEnabled()
        dialog.resize(640, 440)
        assert dialog.preview_table.height() > 0
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_database_creation_dialog_reuse_retargets_only_explicit_different_seed() -> None:
    qapp = QApplication.instance() or QApplication([])
    first = _seed()
    second = replace(
        first,
        seed_id="seed_" + "b" * 32,
        display_name="Second Seed",
    )
    snapshot = replace(empty_product_snapshot(), database_seeds=(first, second))
    tracked: list[tuple[object, ...]] = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *values: tracked.append(values)
    )
    try:
        window.show_database_creation_dialog(snapshot, selected_seed=first)
        dialog = window.database_creation_dialog()
        assert dialog is not None
        dialog.name_edit.setText("Unsaved Database")
        dialog.description_edit.setText("Unsaved description")
        plan = _database_plan(first)
        dialog.set_plan(plan)

        window.show_database_creation_dialog(snapshot, selected_seed=first)
        assert window.database_creation_dialog() is dialog
        assert dialog.selected_seed() == first
        assert dialog.name_edit.text() == "Unsaved Database"
        assert dialog.description_edit.text() == "Unsaved description"
        assert dialog.reviewed_plan is plan

        window.show_database_creation_dialog(snapshot, selected_seed=second)
        assert window.database_creation_dialog() is dialog
        assert dialog.selected_seed() == second
        assert dialog.name_edit.text() == "Unsaved Database"
        assert dialog.description_edit.text() == "Unsaved description"
        assert dialog.reviewed_plan is None
        assert not dialog.create_button.isEnabled()

        dialog.seed_table.selectRow(0)
        QCoreApplication.processEvents()
        window.show_database_creation_dialog(snapshot)
        assert dialog.selected_seed() == second
        assert dialog.name_edit.text() == "Unsaved Database"
        assert dialog.description_edit.text() == "Unsaved description"
        assert sum(item[0] is dialog for item in tracked) == 1

        dialog.close()
        QCoreApplication.processEvents()
        assert window.database_creation_dialog() is None
        window.show_database_creation_dialog(snapshot, selected_seed=second)
        reopened = window.database_creation_dialog()
        assert reopened is not None and reopened is not dialog
        assert reopened.selected_seed() == second
        assert sum(
            item[1] == DATA_MANAGER_DATABASE_CREATION_WINDOW_ID for item in tracked
        ) == 2
    finally:
        window.close()
        QCoreApplication.processEvents()
        del qapp


def test_database_creation_seed_checkboxes_are_authoritative() -> None:
    qapp = QApplication.instance() or QApplication([])
    first = _seed()
    second = replace(
        first,
        seed_id="seed_" + "b" * 32,
        display_name="Second Seed",
    )
    snapshot = replace(empty_product_snapshot(), database_seeds=(first, second))
    dialog = DataManagerDatabaseCreationDialog(snapshot, selected_seed=first)
    try:
        dialog.name_edit.setText("Database")
        first_check = dialog.seed_table.cellWidget(0, 0)
        second_check = dialog.seed_table.cellWidget(1, 0)
        assert isinstance(first_check, QCheckBox)
        assert isinstance(second_check, QCheckBox)
        assert first_check.isChecked() and not second_check.isChecked()
        assert dialog.preview_button.isEnabled()

        first_check.setChecked(False)
        assert dialog.selected_seed() is None
        assert not dialog.preview_button.isEnabled()
        dialog.seed_table.selectRow(1)
        assert dialog.selected_seed() is None

        first_check.setChecked(True)
        second_check.setChecked(True)
        assert dialog.selected_seed() is None
        assert not dialog.preview_button.isEnabled()
        assert not dialog.create_button.isEnabled()

        dialog.set_catalog(snapshot, selected_seed=second)
        assert dialog.selected_seed() == second
        checks = tuple(
            dialog.seed_table.cellWidget(row, 0)
            for row in range(dialog.seed_table.rowCount())
        )
        assert sum(
            isinstance(check, QCheckBox) and check.isChecked()
            for check in checks
        ) == 1
    finally:
        dialog.close()
        QCoreApplication.processEvents()
        del qapp
