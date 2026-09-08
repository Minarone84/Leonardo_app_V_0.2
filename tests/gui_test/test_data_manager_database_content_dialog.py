from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QCheckBox

from leonardo.data_manager import ArtifactCollectionOutputV1
from leonardo.gui.windows.data_manager_database_content_dialog import (
    DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID,
    DataManagerDatabaseContentDialog,
)

from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_database_content_management import (
    MARKET,
    _seed_database,
)
from tests.data_manager_test.test_update_workflow import _domain


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _context(tmp_path: Path):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service)
    first = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    second = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    collection_a = service.create_artifact_collection(first, "First")
    collection_b = service.create_artifact_collection(second, "Second")
    service.reconcile_update_status(force=True)
    snapshot = service.scan_product_catalogs()
    database_entry = next(
        item
        for item in snapshot.databases
        if item.definition.database_id == database.database_id
    )
    return service, snapshot, database_entry, first, second, collection_a, collection_b


def _check(dialog: DataManagerDatabaseContentDialog, row: int) -> QCheckBox:
    checkbox = dialog.source_table.cellWidget(row, 0)
    assert isinstance(checkbox, QCheckBox)
    return checkbox


def _headers(table) -> tuple[str, ...]:
    return tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    )


def _artifact_row(
    dialog: DataManagerDatabaseContentDialog,
    logical_artifact_id: str,
) -> int:
    return next(
        row
        for row, value in enumerate(dialog._source_values)
        if value.logical_artifact_id == logical_artifact_id
    )


def test_artifact_mode_checkboxes_preview_and_plan_states(qapp, tmp_path: Path) -> None:
    service, snapshot, database, first, second, _ca, _cb = _context(tmp_path)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database, snapshot, mode="artifacts")
        assert dialog.property("object_id") == DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID
        assert dialog.windowTitle() == "Add Artifacts to Database"
        assert tuple(
            dialog.summary_table.item(row, 0).text()
            for row in range(dialog.summary_table.rowCount())
        ) == (
            "Database Name",
            "Database ID",
            "Exchange",
            "Market Type",
            "Asset",
            "Timeframe",
            "Current Revision",
            "Current Rows",
            "Current Columns",
        )
        assert _headers(dialog.source_table) == (
            "Select", "Artifact", "Tool", "Outputs", "Status"
        )
        assert _headers(dialog.preview_table) == (
            "Status", "Artifact", "Output", "Database Column", "Origin"
        )
        assert not dialog.preview_button.isEnabled()
        first_check = _check(dialog, 0)
        second_check = _check(dialog, 1)
        assert "indicator:checked" in first_check.styleSheet()
        assert "indicator:unchecked" in first_check.styleSheet()
        first_check.setChecked(True)
        second_check.setChecked(True)
        assert dialog.preview_button.isEnabled()
        assert len(dialog.selected_source_ids()) == 2

        plan = service.plan_database_artifact_addition(
            database.definition.database_id, dialog.selected_source_ids()
        )
        dialog.set_plan(plan)
        assert dialog.preview_table.rowCount() == 2
        assert set(
            dialog.preview_table.item(row, 0).text()
            for row in range(dialog.preview_table.rowCount())
        ) == {"ADD"}
        for label in (
            "Current schema:",
            "Proposed schema:",
            "Current row count:",
            "Proposed row count:",
            "Coverage:",
            "Leading warmup exclusions:",
            "Interior / later missing rows:",
            "Added output count:",
            "Already included count:",
            "Collision count:",
        ):
            assert label in dialog.preview_summary.text()
        assert dialog.add_button.isEnabled()
        first_check.setChecked(False)
        assert dialog.reviewed_plan is None
        assert not dialog.add_button.isEnabled()

        dialog.set_busy(True)
        assert not dialog.source_table.isEnabled()
        assert not dialog.preview_button.isEnabled()
        assert dialog.close_button.isEnabled()
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_collection_mode_requires_exactly_one_check(qapp, tmp_path: Path) -> None:
    service, snapshot, database, _first, _second, _ca, _cb = _context(tmp_path)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database, snapshot, mode="collection")
        assert dialog.windowTitle() == "Add Artifact Collection to Database"
        assert _headers(dialog.source_table) == (
            "Select", "Collection", "Revision", "Outputs", "Status"
        )
        assert not dialog.preview_button.isEnabled()
        _check(dialog, 0).setChecked(True)
        assert dialog.preview_button.isEnabled()
        _check(dialog, 1).setChecked(True)
        assert len(dialog.selected_source_ids()) == 2
        assert not dialog.preview_button.isEnabled()
        assert not dialog.add_button.isEnabled()
        _check(dialog, 1).setChecked(False)
        plan = service.plan_database_collection_addition(
            database.definition.database_id, dialog.selected_source_ids()[0]
        )
        dialog.set_plan(plan)
        assert dialog.add_button.isEnabled()
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_artifact_candidates_require_exact_current_reconciliation(
    qapp,
    tmp_path: Path,
) -> None:
    _service, snapshot, database, first, second, _ca, _cb = _context(tmp_path)
    stale_id = second.root_logical_artifact_ids[0]
    stale_rows = tuple(
        replace(
            item,
            status="APPEND_AVAILABLE",
            direct_staleness=True,
            reasons=("accepted OHLCV advanced",),
        )
        if item.logical_artifact_id == stale_id
        else item
        for item in snapshot.latest_reconciliation.artifacts
    )
    stale_snapshot = replace(
        snapshot,
        latest_reconciliation=replace(
            snapshot.latest_reconciliation,
            artifacts=stale_rows,
        ),
    )
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database, stale_snapshot, mode="artifacts")
        current_row = _artifact_row(dialog, first.root_logical_artifact_ids[0])
        stale_row = _artifact_row(dialog, stale_id)
        assert _check(dialog, current_row).isEnabled()
        assert dialog.source_table.item(current_row, 4).text() == "Current"
        assert not _check(dialog, stale_row).isEnabled()
        assert dialog.source_table.item(stale_row, 4).text() == (
            "Stale or source-incompatible"
        )
        _check(dialog, stale_row).setChecked(True)
        assert not _check(dialog, stale_row).isChecked()
        assert stale_id not in dialog.selected_source_ids()
        assert dialog.reviewed_plan is None
        assert not dialog.preview_button.isEnabled()
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_non_current_database_disables_artifact_and_collection_sources(
    qapp,
    tmp_path: Path,
) -> None:
    _service, snapshot, database, _first, _second, _ca, _cb = _context(tmp_path)
    assert database.currentness is not None
    stale_database = replace(
        database,
        currentness=replace(
            database.currentness,
            status="UPDATE_AVAILABLE",
            reasons=("accepted OHLCV advanced",),
        ),
    )
    dialog = DataManagerDatabaseContentDialog()
    try:
        for mode in ("artifacts", "collection"):
            dialog.set_context(stale_database, snapshot, mode=mode)
            assert dialog.source_table.rowCount() > 0
            for row in range(dialog.source_table.rowCount()):
                checkbox = _check(dialog, row)
                assert not checkbox.isEnabled()
                assert dialog.source_table.item(row, 4).text() == (
                    "Database update required"
                )
                checkbox.setChecked(True)
                assert not checkbox.isChecked()
            assert dialog.selected_source_ids() == ()
            assert dialog.reviewed_plan is None
            assert not dialog.preview_button.isEnabled()
            assert not dialog.add_button.isEnabled()
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_v1_transition_notice_uses_explicit_history_language(
    qapp,
    tmp_path: Path,
) -> None:
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    first = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    collection = service.create_artifact_collection(first, "Legacy")
    seed = service.create_database_seed(MARKET, "Legacy Database")
    database = service.build_database_revision(seed.seed_id, collection.collection_id)
    second = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    service.reconcile_update_status(force=True)
    snapshot = service.scan_product_catalogs()
    database_entry = next(
        item
        for item in snapshot.databases
        if item.definition.database_id == database.database_id
    )
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database_entry, snapshot, mode="artifacts")
        logical_id = second.root_logical_artifact_ids[0]
        row = next(
            row
            for row, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == logical_id
        )
        _check(dialog, row).setChecked(True)
        plan = service.plan_database_artifact_addition(
            database.database_id, (logical_id,)
        )
        dialog.set_plan(plan)
        assert plan.requires_v1_transition
        assert "legacy V1 collection-following revision format" in (
            dialog.preview_summary.text()
        )
        assert "Existing V1 revisions and history will remain unchanged" in (
            dialog.preview_summary.text()
        )
    finally:
        dialog.close()
        QCoreApplication.processEvents()


def test_duplicate_blocked_v1_and_success_refresh_presentation(
    qapp,
    tmp_path: Path,
) -> None:
    service, snapshot, database, first, second, _ca, _cb = _context(tmp_path)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database, snapshot, mode="artifacts")
        first_id = first.root_logical_artifact_ids[0]
        first_plan = service.plan_database_artifact_addition(
            database.definition.database_id, (first_id,)
        )
        first_row = next(
            row for row, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == first_id
        )
        _check(dialog, first_row).setChecked(True)
        dialog.set_plan(first_plan)
        published = service.execute_database_content_addition(first_plan)
        assert published is not None
        service.reconcile_update_status(force=True)
        refreshed = service.scan_product_catalogs()
        refreshed_database = next(
            item for item in refreshed.databases
            if item.definition.database_id == database.definition.database_id
        )
        dialog.publication_succeeded(refreshed_database, refreshed)
        assert dialog.reviewed_plan is None
        assert "published" in dialog.preview_summary.text()

        duplicate = service.plan_database_artifact_addition(
            published.database_id, (first_id,)
        )
        dialog.set_context(refreshed_database, refreshed, mode="artifacts")
        first_row = next(
            row for row, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == first_id
        )
        _check(dialog, first_row).setChecked(True)
        dialog.set_plan(duplicate)
        assert dialog.preview_table.item(0, 0).text() == "ALREADY INCLUDED"
        assert not dialog.add_button.isEnabled()

        collision = service._creation.plan_database_content_addition(
            published.database_id,
            service.plan_artifact_collection_selection(
                published.market_id, second.root_logical_artifact_ids
            ),
            selected_outputs=(
                ArtifactCollectionOutputV1(
                    second.root_logical_artifact_ids[0], "ema_4", "close"
                ),
            ),
            source_kind="artifacts",
        )
        dialog.set_context(refreshed_database, refreshed, mode="artifacts")
        second_row = next(
            row for row, value in enumerate(dialog._source_values)
            if value.logical_artifact_id == second.root_logical_artifact_ids[0]
        )
        _check(dialog, second_row).setChecked(True)
        dialog.set_plan(collision)
        assert dialog.preview_table.item(0, 0).text() == "BLOCKED"
        assert not dialog.add_button.isEnabled()
    finally:
        dialog.close()
        QCoreApplication.processEvents()
