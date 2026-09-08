from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QSplitter

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
import leonardo.gui.windows.data_manager_recipe_collection_dialog as dialog_module
from leonardo.gui.windows.data_manager_recipe_collection_dialog import (
    DataManagerRecipeCollectionDialog,
)
from leonardo.recipes import (
    PortableRecipeCollectionRevisionV1,
    PortableRecipeGraphEdge,
    PortableRecipeGraphPlan,
)


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


def test_initial_geometry_group_clearance_and_create_edit_parity(monkeypatch) -> None:
    calls: list[tuple[object, object, float, float]] = []

    def capture_initial_size(
        window,
        *,
        parent=None,
        width_fraction=0.0,
        height_fraction=0.0,
    ) -> None:
        calls.append((window, parent, width_fraction, height_fraction))

    monkeypatch.setattr(dialog_module, "apply_initial_window_size", capture_initial_size)
    snapshot = _snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"))
    dialog = DataManagerRecipeCollectionDialog(snapshot)
    try:
        assert calls == [(dialog, None, 0.75, 0.75)]
        groups = {
            group.title(): group
            for group in dialog.findChildren(QGroupBox)
        }
        expected = {"Collection", "Recipe roots", "Preview"}
        assert expected <= groups.keys()
        layouts = {title: groups[title].layout() for title in expected}
        assert all(layout.contentsMargins().top() == 24 for layout in layouts.values())
        assert dialog.minimumWidth() < dialog.maximumWidth()
        assert dialog.minimumHeight() < dialog.maximumHeight()
        splitter = dialog.findChild(
            QSplitter, "data_manager.recipe_collection.splitter.workspace"
        )
        assert splitter is dialog.workspace_splitter
        assert splitter.orientation() == Qt.Orientation.Horizontal
        assert splitter.count() == 2
        assert not splitter.childrenCollapsible()
        assert splitter.widget(0) is groups["Recipe roots"]
        assert splitter.widget(1) is groups["Preview"]
        dialog.resize(1200, 800)
        dialog.show()
        _QAPP.processEvents()
        left_size, right_size = splitter.sizes()
        assert abs(left_size - right_size) <= 1

        dialog.configure_create(snapshot)
        assert all(groups[title].layout() is layouts[title] for title in expected)
        dialog.configure_edit(_inspection(), snapshot)
        assert all(groups[title].layout() is layouts[title] for title in expected)
    finally:
        dialog.close()


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
        plan = _plan()
        assert dialog.set_plan(plan)
        assert dialog.set_collection_prediction(plan, None)
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


def test_preview_reports_equivalent_collection_winner() -> None:
    dialog = DataManagerRecipeCollectionDialog(
        _snapshot(_recipe(ROOT_ID, "ema"), _recipe(SUPPORT_ID, "sma"))
    )
    winner = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_11111111111111111111111111111111",
        display_name="Persisted Winner",
        description="Existing metadata",
        root_recipe_ids=(ROOT_ID,),
        member_recipe_ids=(SUPPORT_ID, ROOT_ID),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 28, tzinfo=UTC),
    )
    try:
        assert dialog.preview_summary.minimumHeight() >= (
            dialog.preview_summary.fontMetrics().lineSpacing() * 2
        )
        _set_checked(dialog, ROOT_ID)
        dialog.name_input.setText(" Existing collection ")
        plan = _plan()
        assert dialog.set_plan(plan)
        assert dialog.set_collection_prediction(plan, winner)
        assert "Result: REUSE EXISTING COLLECTION" in dialog.preview_summary.text()
        assert "Persisted Winner" in dialog.preview_summary.text()
        assert winner.collection_id in dialog.preview_summary.text()
        assert winner.revision_id in dialog.preview_summary.text()
        assert not dialog.publish_button.isEnabled()
        dialog.name_input.setText("Corrected collection")
        assert dialog.publish_button.isEnabled()
    finally:
        dialog.close()
