from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QProgressBar

from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerRecipeDerivationPlan,
    DataManagerRecipePersistenceResult,
    DataManagerStudyEntryPortability,
    DataManagerStudyEnvironmentEntry,
    DataManagerStudyEnvironmentInspection,
)
from leonardo.gui.windows.data_manager_recipe_derivation_dialog import (
    DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID,
    DataManagerRecipeDerivationDialog,
)


ROOT_RECIPE_ID = "a" * 64
SUPPORT_RECIPE_ID = "b" * 64


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _inspection() -> DataManagerStudyEnvironmentInspection:
    entries = (
        DataManagerStudyEntryPortability(
            "root", "Root Study", "calculation", "construct", "utc",
            "PORTABLE_WITH_DEPENDENCIES", "", ("support",), ROOT_RECIPE_ID,
        ),
        DataManagerStudyEntryPortability(
            "support", "Support Study", "calculation", "indicator", "ema",
            "PORTABLE", "", (), SUPPORT_RECIPE_ID,
        ),
        DataManagerStudyEntryPortability(
            "artifact", "Artifact Study", "artifact", "indicator", "ema",
            "MARKET_BOUND", "Artifact source is market-bound",
        ),
        DataManagerStudyEntryPortability(
            "invalid", "Invalid Study", "calculation", "indicator", "bad",
            "INVALID", "Invalid configuration",
        ),
    )
    environment = DataManagerStudyEnvironmentEntry(
        "environment_1",
        "Environment One",
        "Portable graph",
        MarketId("bybit", "linear", "BTCUSDT", "1h"),
        4,
        1,
        1,
        1,
        0,
        1,
        datetime(2026, 8, 17, tzinfo=UTC),
        datetime(2026, 8, 17, tzinfo=UTC),
    )
    return DataManagerStudyEnvironmentInspection(environment, entries)


def _plan(
    *,
    blockers: tuple[str, ...] = (),
    entry_classifications: tuple[DataManagerStudyEntryPortability, ...] | None = None,
) -> DataManagerRecipeDerivationPlan:
    value = object.__new__(DataManagerRecipeDerivationPlan)
    attributes = {
        "environment_id": "environment_1",
        "environment_content_hash": "c" * 64,
        "root_entry_ids": ("root",),
        "support_entry_ids": ("support",),
        "entry_classifications": (
            _inspection().entries
            if entry_classifications is None
            else entry_classifications
        ),
        "recipes": (),
        "provenances": (),
        "dependency_edges": (),
        "execution_stages": (),
        "warnings": (),
        "blockers": blockers,
    }
    for name, item in attributes.items():
        object.__setattr__(value, name, item)
    return value


def _row_for(dialog: DataManagerRecipeDerivationDialog, entry_id: str) -> int:
    return next(
        row
        for row, entry in enumerate(dialog._entries)
        if entry.entry_id == entry_id
    )


def _select_root(dialog: DataManagerRecipeDerivationDialog) -> None:
    dialog.study_table.item(_row_for(dialog, "root"), 0).setCheckState(
        Qt.CheckState.Checked
    )


def test_all_entries_are_visible_with_exact_root_selectability_and_reasons(qapp) -> None:
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    try:
        assert dialog.objectName() == DATA_MANAGER_RECIPE_DERIVATION_WINDOW_ID
        assert dialog.windowTitle() == "Derive Recipes"
        assert dialog.study_table.rowCount() == 4
        assert dialog.selected_root_entry_ids() == ()
        assert not dialog.preview_button.isEnabled()

        for entry in dialog._entries:
            row = _row_for(dialog, entry.entry_id)
            item = dialog.study_table.item(row, 0)
            selectable = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            assert selectable is (
                entry.status in {"PORTABLE", "PORTABLE_WITH_DEPENDENCIES"}
            )
            assert dialog.study_table.item(row, 5).text() == entry.status
            assert dialog.study_table.item(row, 7).text() == entry.reason
    finally:
        dialog.close()


def test_initial_size_collection_height_and_normal_resize(qapp) -> None:
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    try:
        screen = dialog.screen() or qapp.primaryScreen()
        available = screen.availableGeometry()
        assert dialog.width() == int(available.width() * 0.40)
        assert dialog.height() == int(available.height() * 0.60)

        collection = next(
            group
            for group in dialog.findChildren(QGroupBox)
            if group.title() == "Recipe Collection"
        )
        assert collection.minimumHeight() >= collection.sizeHint().height() + 12

        resized = dialog.size()
        dialog.resize(resized.width() + 20, resized.height() + 20)
        assert dialog.width() == resized.width() + 20
        assert dialog.height() == resized.height() + 20
    finally:
        dialog.close()


def test_bulk_root_selection_is_exact_single_invalidation_and_busy_safe(
    qapp, monkeypatch
) -> None:
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    invalidations: list[str] = []
    original = dialog.invalidate_preview

    def record_invalidation(message: str = "Preview required.") -> None:
        invalidations.append(message)
        original(message)

    monkeypatch.setattr(dialog, "invalidate_preview", record_invalidation)
    try:
        assert dialog.select_all_button.objectName() == (
            "data_manager.recipe_derivation.action.select_all"
        )
        assert dialog.deselect_all_button.objectName() == (
            "data_manager.recipe_derivation.action.deselect_all"
        )
        assert dialog.select_all_button.isEnabled()
        assert not dialog.deselect_all_button.isEnabled()

        dialog.select_all_button.click()
        assert dialog.selected_root_entry_ids() == ("root", "support")
        assert dialog.study_table.item(_row_for(dialog, "artifact"), 0).checkState() == (
            Qt.CheckState.Unchecked
        )
        assert dialog.study_table.item(_row_for(dialog, "invalid"), 0).checkState() == (
            Qt.CheckState.Unchecked
        )
        assert len(invalidations) == 1

        dialog.select_all_button.click()
        assert len(invalidations) == 1

        dialog.set_busy(True)
        assert not dialog.select_all_button.isEnabled()
        assert not dialog.deselect_all_button.isEnabled()
        dialog.set_busy(False)
        assert dialog.select_all_button.isEnabled()
        assert dialog.deselect_all_button.isEnabled()

        dialog.deselect_all_button.click()
        assert dialog.selected_root_entry_ids() == ()
        assert len(invalidations) == 2
        dialog.deselect_all_button.click()
        assert len(invalidations) == 2
    finally:
        dialog.close()


def test_preview_projects_root_support_new_existing_and_blockers(qapp) -> None:
    dialog = DataManagerRecipeDerivationDialog(
        _inspection(), existing_recipe_ids=(ROOT_RECIPE_ID,)
    )
    try:
        _select_root(dialog)
        assert dialog.preview_button.isEnabled()
        assert dialog.set_plan(_plan())
        assert tuple(
            dialog.preview_table.item(row, 0).text()
            for row in range(dialog.preview_table.rowCount())
        ) == ("Root", "Support")
        assert tuple(
            dialog.preview_table.item(row, 5).text()
            for row in range(dialog.preview_table.rowCount())
        ) == ("Existing", "New")
        assert dialog.create_button.isEnabled()

        dialog.invalidate_preview()
        assert dialog.set_plan(_plan(blockers=("Canonical blocker",)))
        assert dialog.blockers_label.text() == "Canonical blocker"
        assert not dialog.create_button.isEnabled()
    finally:
        dialog.close()


def test_root_change_collection_controls_and_success_invalidate_preview(qapp) -> None:
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    try:
        assert dialog.findChildren(QProgressBar) == []
        assert not dialog.collection_name.isEnabled()
        assert not dialog.collection_description.isEnabled()
        dialog.collection_checkbox.setChecked(True)
        assert dialog.collection_name.isEnabled()
        assert dialog.collection_description.isEnabled()

        _select_root(dialog)
        assert dialog.set_plan(_plan())
        assert not dialog.create_button.isEnabled()
        dialog.collection_name.setText("Portable Set")
        assert dialog.create_button.isEnabled()

        dialog.study_table.item(_row_for(dialog, "support"), 0).setCheckState(
            Qt.CheckState.Checked
        )
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.create_button.isEnabled()

        dialog.study_table.item(_row_for(dialog, "support"), 0).setCheckState(
            Qt.CheckState.Unchecked
        )
        assert dialog.set_plan(_plan())
        dialog.settle_success(
            DataManagerRecipePersistenceResult(
                "environment_1",
                (ROOT_RECIPE_ID,),
                (SUPPORT_RECIPE_ID,),
                "collection_1",
                "d" * 64,
            )
        )
        assert "Recipes created/reused successfully" in dialog.status_label.text()
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.create_button.isEnabled()
        assert dialog.selected_root_entry_ids() == ("root",)
    finally:
        dialog.close()


def test_stale_missing_root_projects_inert_row_and_preserves_blocker(qapp) -> None:
    support_without_recipe = DataManagerStudyEntryPortability(
        "support", "Support Study", "calculation", "indicator", "ema",
        "MARKET_BOUND", "Support is market-bound", (), None,
    )
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    try:
        _select_root(dialog)
        assert dialog.set_plan(
            _plan(
                blockers=("Canonical stale-plan blocker",),
                entry_classifications=(support_without_recipe,),
            )
        )

        assert dialog.preview_table.rowCount() == 2
        assert tuple(
            dialog.preview_table.item(0, column).text()
            for column in range(dialog.preview_table.columnCount())
        ) == ("Root", "root", "", "", "", "", "")
        assert dialog.preview_table.item(1, 0).text() == "Support"
        assert dialog.preview_table.item(1, 5).text() == ""
        assert dialog.preview_table.item(1, 6).text() == ""
        assert dialog.blockers_label.text() == "Canonical stale-plan blocker"
        assert not dialog.create_button.isEnabled()
    finally:
        dialog.close()


def test_success_recipe_ids_are_immediately_projected_as_existing(qapp) -> None:
    dialog = DataManagerRecipeDerivationDialog(_inspection())
    plan = _plan()
    try:
        _select_root(dialog)
        assert dialog.set_plan(plan)
        assert tuple(
            dialog.preview_table.item(row, 5).text()
            for row in range(dialog.preview_table.rowCount())
        ) == ("New", "New")

        dialog.settle_success(
            DataManagerRecipePersistenceResult(
                "environment_1",
                (ROOT_RECIPE_ID,),
                (SUPPORT_RECIPE_ID,),
                None,
                None,
            )
        )
        assert dialog.preview_table.rowCount() == 0
        assert not dialog.create_button.isEnabled()

        assert dialog.set_plan(plan)
        assert tuple(
            dialog.preview_table.item(row, 5).text()
            for row in range(dialog.preview_table.rowCount())
        ) == ("Existing", "Existing")
    finally:
        dialog.close()
