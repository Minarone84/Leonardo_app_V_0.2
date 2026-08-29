from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerCatalogSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerPortableRecipeCatalog,
    DataManagerPortableRecipeEntry,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionCatalog,
    DataManagerRecipeCollectionEntry,
    DataManagerRecipeCollectionInspection,
    DataManagerReconciliationSnapshot,
    DataManagerStudyEnvironmentCatalog,
)
from leonardo.gui.windows.data_manager_recipe_collection_dialog import (
    DataManagerRecipeCollectionDialog,
)
from leonardo.recipes import PortableRecipeGraphEdge, PortableRecipeGraphPlan


_QAPP = QApplication.instance() or QApplication([])
MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
ROOT_ID = "a" * 64
SUPPORT_ID = "b" * 64


def _recipe(
    recipe_id: str,
    tool_key: str,
    *,
    valid: bool = True,
) -> DataManagerPortableRecipeEntry:
    return DataManagerPortableRecipeEntry(
        recipe_id,
        tool_key,
        "1.0",
        "indicator",
        {"period": 20},
        (f"{tool_key}_20",),
        ("source=OHLCV.close",),
        0,
        1,
        (MARKET,),
        (),
        (),
        1,
        valid,
        "rejected" if not valid else "",
    )


def _snapshot(*recipes: DataManagerPortableRecipeEntry) -> DataManagerProductCatalogSnapshot:
    return DataManagerProductCatalogSnapshot(
        DataManagerCatalogSnapshot(()),
        DataManagerStudyEnvironmentCatalog(()),
        DataManagerPortableRecipeCatalog(tuple(recipes)),
        DataManagerRecipeCollectionCatalog(()),
        DataManagerManagedArtifactCatalog(()),
        (),
        (),
        (),
        DataManagerReconciliationSnapshot(
            datetime(2026, 8, 28, tzinfo=UTC), (), (), (), (), (), "0" * 64
        ),
    )


def _plan(roots: tuple[str, ...] = (ROOT_ID,)) -> PortableRecipeGraphPlan:
    members = (SUPPORT_ID, *roots)
    return PortableRecipeGraphPlan(
        roots,
        members,
        (
            PortableRecipeGraphEdge(SUPPORT_ID, ROOT_ID, "source", "value"),
        ) if ROOT_ID in roots else (),
        ((SUPPORT_ID,), roots),
    )


def _inspection() -> DataManagerRecipeCollectionInspection:
    entry = DataManagerRecipeCollectionEntry(
        "collection_1",
        "c" * 64,
        "Collection",
        "Description",
        1,
        2,
        (ROOT_ID, SUPPORT_ID),
        1,
        2,
        datetime(2026, 8, 28, tzinfo=UTC),
        datetime(2026, 8, 28, tzinfo=UTC),
    )
    return DataManagerRecipeCollectionInspection(
        entry,
        (ROOT_ID,),
        (SUPPORT_ID, ROOT_ID),
        (PortableRecipeGraphEdge(SUPPORT_ID, ROOT_ID, "source", "value"),),
        ((SUPPORT_ID,), (ROOT_ID,)),
    )


def _set_checked(dialog: DataManagerRecipeCollectionDialog, recipe_id: str) -> None:
    for row in range(dialog.recipe_table.rowCount()):
        if dialog.recipe_table.item(row, 6).text() == recipe_id:
            dialog.recipe_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
            return
    raise AssertionError(f"Recipe row not found: {recipe_id}")


def test_create_catalog_selection_and_invalid_recipe() -> None:
    invalid = _recipe("invalid_recipe", "bad", valid=False)
    dialog = DataManagerRecipeCollectionDialog(
        _snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"), invalid)
    )
    try:
        assert dialog.windowTitle() == "Create Recipe Collection"
        assert dialog.recipe_table.rowCount() == 3
        dialog.select_all_button.click()
        assert set(dialog.selected_root_recipe_ids()) == {ROOT_ID, SUPPORT_ID}
        invalid_row = next(
            row
            for row in range(dialog.recipe_table.rowCount())
            if dialog.recipe_table.item(row, 6).text() == "invalid_recipe"
        )
        assert not bool(
            dialog.recipe_table.item(invalid_row, 0).flags()
            & Qt.ItemFlag.ItemIsUserCheckable
        )
        dialog.deselect_all_button.click()
        assert dialog.selected_root_recipe_ids() == ()
    finally:
        dialog.close()


def test_matching_preview_root_support_and_metadata_stability() -> None:
    dialog = DataManagerRecipeCollectionDialog(
        _snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"))
    )
    try:
        _set_checked(dialog, ROOT_ID)
        plan = _plan()
        assert dialog.set_plan(plan)
        assert [dialog.preview_table.item(row, 0).text() for row in range(2)] == [
            "SUPPORT",
            "ROOT",
        ]
        dialog.name_input.setText("Named")
        dialog.description_input.setText("Description")
        assert dialog.reviewed_plan is plan
        assert dialog.set_plan(_plan((SUPPORT_ID,))) is False
        _set_checked(dialog, SUPPORT_ID)
        assert dialog.reviewed_plan is None
    finally:
        dialog.close()


def test_edit_revision_publish_payload_busy_and_close() -> None:
    snapshot = _snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"))
    dialog = DataManagerRecipeCollectionDialog(snapshot)
    inspection = _inspection()
    dialog.configure_edit(inspection, snapshot)
    published: list[tuple] = []
    closed: list[bool] = []
    dialog.update_requested.connect(lambda *values: published.append(values))
    dialog.closing.connect(lambda: closed.append(True))
    try:
        assert dialog.collection_id == "collection_1"
        assert dialog.expected_revision_id == "c" * 64
        assert dialog.selected_root_recipe_ids() == (ROOT_ID,)
        assert dialog.set_plan(_plan())
        dialog.publish_button.click()
        assert published == [
            (
                "collection_1",
                "Collection",
                "Description",
                (ROOT_ID,),
                "c" * 64,
            )
        ]
        dialog.set_busy(True)
        assert not dialog.recipe_table.isEnabled()
        assert not dialog.publish_button.isEnabled()
    finally:
        dialog.close()
    assert closed == [True]
