from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox

from leonardo.data_manager import DatabaseCollectionReferenceV2
from leonardo.data_manager.creation_models import database_revision_from_dict, deterministic_hash
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


def _dispose_dialog(dialog, qapp) -> None:
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(
        dialog,
        QEvent.Type.DeferredDelete,
    )
    qapp.processEvents()


def _context(tmp_path: Path):
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    _seed, database = _seed_database(service, start_index=0)
    first = _materialize(service, recipes, _leaf("sma", {"period": 3}))
    second = _materialize(service, recipes, _leaf("ema", {"period": 4}))
    collection = service.create_artifact_collection(first, "Features")
    service.reconcile_update_status(force=True)
    snapshot = service.scan_product_catalogs()
    database_entry = next(
        item
        for item in snapshot.databases
        if item.definition.database_id == database.database_id
    )
    return service, snapshot, database_entry, first, second, collection


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
    output_name: str,
) -> int:
    return next(
        row
        for row, value in enumerate(dialog._source_values)
        if value.logical_artifact_id == logical_artifact_id
        and value.output_name == output_name
    )


def _collection_row(
    dialog: DataManagerDatabaseContentDialog,
    collection_id: str,
    revision_id: str,
) -> int:
    return next(
        row
        for row, value in enumerate(dialog._source_values)
        if value.collection_id == collection_id and value.revision_id == revision_id
    )


def _refresh(service, database_id: str):
    service.reconcile_update_status(force=True)
    snapshot = service.scan_product_catalogs()
    database = next(
        item for item in snapshot.databases
        if item.definition.database_id == database_id
    )
    baseline = service.plan_database_content_edit(database_id)
    assert baseline.no_op and not baseline.blocked
    return snapshot, database, baseline


def test_edit_artifacts_is_output_level_and_removes_all_owners(
    qapp, tmp_path: Path
) -> None:
    service, snapshot, database, first, _second, collection = _context(tmp_path)
    database_id = database.definition.database_id
    baseline = service.plan_database_content_edit(database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(
            database, snapshot, mode="artifacts", baseline_plan=baseline
        )
        assert dialog.property("object_id") == DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID
        assert dialog.windowTitle() == "Edit Database Artifacts"
        assert _headers(dialog.source_table) == (
            "Include",
            "Artifact",
            "Tool",
            "Output",
            "Database Column",
            "Owners",
            "Status",
        )
        assert _headers(dialog.preview_table) == (
            "Action",
            "Artifact",
            "Output",
            "Database Column",
            "Owners Before",
            "Owners After",
        )

        root = first.root_logical_artifact_ids[0]
        row = _artifact_row(dialog, root, "sma_3")
        checkbox = _check(dialog, row)
        assert checkbox.isEnabled() and not checkbox.isChecked()
        checkbox.setChecked(True)
        intent = dialog.edit_intent()
        assert intent["artifact_additions"][0].logical_artifact_id == root
        plan = service.plan_database_content_edit(database_id, **intent)
        dialog.set_plan(plan)
        assert dialog.preview_table.item(0, 0).text() == "ADD"
        assert dialog.apply_button.isEnabled()
        direct_revision = service.execute_database_content_edit(plan)
        assert direct_revision is not None

        overlap = service.plan_database_content_edit(
            database_id,
            collection_additions=(
                DatabaseCollectionReferenceV2(
                    collection.collection_id, collection.revision_id
                ),
            ),
        )
        assert overlap.ownership_changed and not overlap.added_column_names
        assert service.execute_database_content_edit(overlap) is not None
        snapshot, database, baseline = _refresh(service, database_id)
        dialog.set_context(
            database, snapshot, mode="artifacts", baseline_plan=baseline
        )
        row = _artifact_row(dialog, root, "sma_3")
        checkbox = _check(dialog, row)
        assert checkbox.isChecked()
        owners = dialog.source_table.item(row, 5).text()
        assert "Artifact" in owners
        assert collection.collection_id in owners
        assert collection.revision_id in owners

        checkbox.setChecked(False)
        intent = dialog.edit_intent()
        assert intent["remove_columns"] == ("sma_3",)
        assert intent["remove_outputs"] == ()
        removal = service.plan_database_content_edit(database_id, **intent)
        assert removal.removed_column_names == ("sma_3",)
        assert removal.selection_sources == ()
        dialog.set_plan(removal)
        assert dialog.preview_table.item(0, 0).text() == "REMOVE"
        assert dialog.preview_table.item(0, 5).text() == "-"
        assert dialog.apply_button.isEnabled()
    finally:
        _dispose_dialog(dialog, qapp)


def test_edit_collections_displays_exact_captured_revisions_and_preserves_overlap(
    qapp, tmp_path: Path
) -> None:
    service, _snapshot, database, _first, second, collection = _context(tmp_path)
    database_id = database.definition.database_id
    first_capture = service.execute_database_content_edit(
        service.plan_database_collection_addition(database_id, collection.collection_id)
    )
    assert first_capture is not None
    revised = service.add_artifact_collection_branches(
        collection.collection_id, second
    )
    second_capture = service.execute_database_content_edit(
        service.plan_database_content_edit(
            database_id,
            collection_additions=(
                DatabaseCollectionReferenceV2(
                    revised.collection_id, revised.revision_id
                ),
            ),
        )
    )
    assert second_capture is not None
    snapshot, database, baseline = _refresh(service, database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(
            database, snapshot, mode="collections", baseline_plan=baseline
        )
        assert dialog.windowTitle() == "Edit Database Collections"
        assert _headers(dialog.source_table) == (
            "Include",
            "Collection",
            "Captured Revision",
            "Owned Database Columns",
            "Status",
        )
        first_row = _collection_row(
            dialog, collection.collection_id, collection.revision_id
        )
        revised_row = _collection_row(
            dialog, revised.collection_id, revised.revision_id
        )
        assert _check(dialog, first_row).isChecked()
        assert _check(dialog, revised_row).isChecked()
        assert dialog.source_table.item(first_row, 2).text() == collection.revision_id
        assert dialog.source_table.item(revised_row, 2).text() == revised.revision_id

        _check(dialog, first_row).setChecked(False)
        intent = dialog.edit_intent()
        assert intent["remove_sources"] == (
            ("collection", collection.collection_id, collection.revision_id),
        )
        plan = service.plan_database_content_edit(database_id, **intent)
        assert plan.removed_column_names == ()
        assert plan.ownership_changed
        dialog.set_plan(plan)
        actions = {
            dialog.preview_table.item(row, 0).text()
            for row in range(dialog.preview_table.rowCount())
        }
        assert "OWNERSHIP" in actions
        assert dialog.apply_button.isEnabled()
    finally:
        _dispose_dialog(dialog, qapp)


def test_deleted_captured_collection_remains_visible_and_removable(
    qapp, tmp_path: Path
) -> None:
    service, _snapshot, database, _first, _second, collection = _context(tmp_path)
    database_id = database.definition.database_id
    published = service.execute_database_content_edit(
        service.plan_database_collection_addition(database_id, collection.collection_id)
    )
    assert published is not None
    service.delete_artifact_collection(collection.collection_id)
    snapshot, database, baseline = _refresh(service, database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(
            database, snapshot, mode="collections", baseline_plan=baseline
        )
        row = _collection_row(
            dialog, collection.collection_id, collection.revision_id
        )
        checkbox = _check(dialog, row)
        assert checkbox.isEnabled() and checkbox.isChecked()
        assert "live revision unavailable" in dialog.source_table.item(row, 4).text()
        checkbox.setChecked(False)
        plan = service.plan_database_content_edit(database_id, **dialog.edit_intent())
        assert not plan.blocked
        assert plan.removed_column_names == ("sma_3",)
        dialog.set_plan(plan)
        assert dialog.apply_button.isEnabled()
    finally:
        _dispose_dialog(dialog, qapp)


def test_database_update_state_does_not_gate_safe_content_edit_candidates(
    qapp, tmp_path: Path
) -> None:
    service, snapshot, database, first, _second, collection = _context(tmp_path)
    assert database.currentness is not None
    non_current = replace(
        database,
        currentness=replace(
            database.currentness,
            status="UPDATE_AVAILABLE",
            reasons=("accepted OHLCV advanced",),
        ),
    )
    baseline = service.plan_database_content_edit(database.definition.database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(
            non_current, snapshot, mode="artifacts", baseline_plan=baseline
        )
        row = _artifact_row(
            dialog, first.root_logical_artifact_ids[0], "sma_3"
        )
        assert _check(dialog, row).isEnabled()
        assert dialog.source_table.item(row, 6).text() == "Available"

        dialog.set_context(
            non_current, snapshot, mode="collections", baseline_plan=baseline
        )
        row = _collection_row(
            dialog, collection.collection_id, collection.revision_id
        )
        assert _check(dialog, row).isEnabled()
        assert dialog.source_table.item(row, 4).text() == "Available"
    finally:
        _dispose_dialog(dialog, qapp)


def test_head_change_invalidates_reviewed_plan_and_baseline(qapp, tmp_path: Path) -> None:
    service, snapshot, database, first, second, _collection = _context(tmp_path)
    database_id = database.definition.database_id
    baseline = service.plan_database_content_edit(database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(
            database, snapshot, mode="artifacts", baseline_plan=baseline
        )
        row = _artifact_row(
            dialog, first.root_logical_artifact_ids[0], "sma_3"
        )
        _check(dialog, row).setChecked(True)
        reviewed = service.plan_database_content_edit(database_id, **dialog.edit_intent())
        dialog.set_plan(reviewed)
        assert dialog.apply_button.isEnabled()

        competing = service.plan_database_artifact_addition(
            database_id, second.root_logical_artifact_ids
        )
        assert service.execute_database_content_edit(competing) is not None
        snapshot, database, _new_baseline = _refresh(service, database_id)
        dialog.set_context(database, snapshot, mode="artifacts")
        assert dialog.baseline_plan is None
        assert dialog.reviewed_plan is None
        assert not dialog.preview_button.isEnabled()
        assert not dialog.apply_button.isEnabled()
    finally:
        _dispose_dialog(dialog, qapp)


@pytest.mark.parametrize("schema", ("3.0", "4.0"))
def test_content_preview_identifies_the_actual_new_revision_format(qapp, tmp_path, schema):
    service, snapshot, database, first, _second, _collection = _context(tmp_path)
    if schema == "3.0":
        payload = database.current_manifest.to_dict(include_revision_id=False)
        payload.pop("value_provenance")
        payload["schema_version"] = schema
        payload["previous_revision_id"] = database.current_manifest.revision_id
        payload["revision_id"] = deterministic_hash(payload)
        service.creation_store.publish_database_revision(
            database.definition, database_revision_from_dict(payload),
            service.load_database_revision(database.definition.database_id).values_csv,
            expected_head_revision_id=database.current_manifest.revision_id,
        )
    identity = database.definition.database_id
    snapshot, database, baseline = _refresh(service, identity)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(database, snapshot, mode="artifacts", baseline_plan=baseline)
        row = _artifact_row(dialog, first.root_logical_artifact_ids[0], "sma_3")
        _check(dialog, row).setChecked(True)
        plan = service.plan_database_content_edit(identity, **dialog.edit_intent())
        dialog.set_plan(plan)
        text = dialog.preview_summary.text()
        assert "V3 Database revision" not in text
        assert ("V4 Database revision" in text) == (schema == "3.0")
        if schema == "3.0":
            assert "value provenance" in text
            assert "Historical revisions remain unchanged." in text
    finally:
        _dispose_dialog(dialog, qapp)



@pytest.mark.parametrize("schema", ("1.0", "2.0"))
def test_a2_legacy_rows_remain_removable_and_preview_tracks_columns(qapp, tmp_path, schema):
    from tests.data_manager_test.test_database_content_management import _a2_snapshot
    service, _artifacts, recipes, _historical = _domain(tmp_path)
    original, collection, roots, _before = _a2_snapshot(service, recipes, schema)
    service.delete_artifact_collection(collection.collection_id)
    for root in roots:
        service.delete_managed_artifact(MARKET, root)
    snapshot, entry, baseline = _refresh(service, original.database_id)
    dialog = DataManagerDatabaseContentDialog()
    try:
        dialog.set_context(entry, snapshot, mode="artifacts", baseline_plan=baseline)
        assert dialog.source_table.rowCount() == 4
        assert all(_check(dialog, row).isEnabled() and _check(dialog, row).isChecked() for row in range(4))
        if schema == "1.0":
            assert "not recorded" in dialog.source_table.item(0, 6).text()
            assert dialog.selected_source_ids() == ()
        column = dialog._source_values[0].output.column_name
        _check(dialog, 0).setChecked(False)
        assert dialog.edit_intent()["remove_columns"] == (column,)
        plan = service.plan_database_content_edit(original.database_id, **dialog.edit_intent())
        dialog.set_plan(plan)
        assert dialog.apply_button.isEnabled()
        assert "REMOVE" in tuple(dialog.preview_table.item(row, 0).text() for row in range(4))
        _check(dialog, 1).setChecked(False)
        assert not dialog.apply_button.isEnabled()
        with pytest.raises(ValueError, match="does not match"):
            dialog.set_plan(plan)
    finally:
        _dispose_dialog(dialog, qapp)
