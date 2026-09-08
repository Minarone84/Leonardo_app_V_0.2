from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QSplitter

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionRevisionV1,
    DataManagerArtifactMaterializationNode,
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationResult,
    DataManagerDatasetEntry,
    DataManagerManagedArtifactEntry,
)
import leonardo.gui.windows.data_manager_recipe_artifact_materialization_dialog as dialog_module
from leonardo.gui.windows.data_manager_recipe_artifact_materialization_dialog import (
    DATA_MANAGER_RECIPE_ARTIFACT_MATERIALIZATION_WINDOW_ID,
    DataManagerRecipeArtifactMaterializationDialog,
)
from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
DATASET = DataManagerDatasetEntry(MARKET, True, 5, 0, 4)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fingerprint(market: MarketId = MARKET) -> OHLCVSourceFingerprintV1:
    return OHLCVSourceFingerprintV1(
        market, "1" * 64, "2" * 64, 5, 0, 4, "committed", "ok", "1.0"
    )


def _plan(
    *,
    collection: bool = False,
    target: MarketId = MARKET,
    blocked: bool = False,
    advanced: bool = False,
) -> DataManagerArtifactMaterializationPlan:
    snapshot = associated_product_snapshot()
    root = snapshot.portable_recipes.recipes[0]
    support = snapshot.portable_recipes.recipes[1]
    collection_entry = snapshot.recipe_collections.collections[0]
    nodes = (
        DataManagerArtifactMaterializationNode(
            root.recipe_id,
            "3" * 64,
            root.tool_key,
            root.kind,
            "ROOT",
            "CREATE",
            ("4" * 64,),
            None,
            "9" * 64 if advanced else None,
        ),
        DataManagerArtifactMaterializationNode(
            support.recipe_id,
            "4" * 64,
            support.tool_key,
            support.kind,
            "SUPPORT",
            "BLOCKED" if blocked else "REUSE_CURRENT",
            (),
            None if blocked else "5" * 64,
            None,
            ("source unavailable",) if blocked else (),
        ),
    )
    return DataManagerArtifactMaterializationPlan(
        "6" * 64,
        target,
        _fingerprint(target),
        (root.recipe_id,),
        (root.recipe_id, support.recipe_id),
        collection_entry.collection_id if collection else None,
        collection_entry.revision_id if collection else None,
        (),
        ((support.recipe_id,), (root.recipe_id,)),
        nodes,
    )


def _result(plan: DataManagerArtifactMaterializationPlan):
    root, support = plan.nodes
    entries = (
        DataManagerManagedArtifactEntry(
            root.logical_artifact_id,
            root.portable_recipe_id,
            MARKET,
            "7" * 64,
            None,
            root.tool_key,
            root.kind,
            ("sma_20",),
            5,
            0,
            4,
            datetime(2026, 8, 31, tzinfo=UTC),
        ),
        DataManagerManagedArtifactEntry(
            support.logical_artifact_id,
            support.portable_recipe_id,
            MARKET,
            "5" * 64,
            None,
            support.tool_key,
            support.kind,
            ("rsi_14",),
            5,
            0,
            4,
            datetime(2026, 8, 31, tzinfo=UTC),
        ),
    )
    return DataManagerArtifactMaterializationResult(
        plan.plan_id,
        MARKET,
        plan.source_ohlcv,
        (root.logical_artifact_id,),
        (support.logical_artifact_id,),
        ("7" * 64,),
        ("5" * 64,),
        (ManagedArtifactVersionKey(root.logical_artifact_id, "7" * 64),),
        (ManagedArtifactVersionKey(support.logical_artifact_id, "5" * 64),),
        (root.logical_artifact_id,),
        entries,
    )


def test_initial_geometry_and_two_row_equal_splitter_layout(qapp, monkeypatch) -> None:
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
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        assert calls == [(dialog, None, 0.75, 0.75)]
        groups = {
            group.title(): group
            for group in dialog.findChildren(QGroupBox)
        }
        expected = {
            "Source",
            "Target Dataset",
            "Materialization Preview",
            "Optional Artifact Collection",
        }
        assert expected <= groups.keys()
        assert all(
            groups[title].layout().contentsMargins().top() == 24
            for title in expected
        )
        assert dialog.minimumWidth() < dialog.maximumWidth()
        assert dialog.minimumHeight() < dialog.maximumHeight()

        top_splitter = dialog.findChild(
            QSplitter,
            "data_manager.recipe_artifact_materialization.splitter.top",
        )
        assert top_splitter is not None
        assert top_splitter.orientation() == Qt.Orientation.Horizontal
        assert top_splitter.count() == 2
        assert not top_splitter.childrenCollapsible()
        assert top_splitter.widget(0) is groups["Source"]
        assert top_splitter.widget(1) is groups["Target Dataset"]

        bottom_splitter = dialog.findChild(
            QSplitter,
            "data_manager.recipe_artifact_materialization.splitter.bottom",
        )
        assert bottom_splitter is not None
        assert bottom_splitter.orientation() == Qt.Orientation.Horizontal
        assert bottom_splitter.count() == 2
        assert not bottom_splitter.childrenCollapsible()
        assert bottom_splitter.widget(0) is groups["Materialization Preview"]
        assert bottom_splitter.widget(1) is groups["Optional Artifact Collection"]
        root = dialog.layout()
        assert root.stretch(root.indexOf(top_splitter)) == 0
        assert root.stretch(root.indexOf(bottom_splitter)) == 1

        snapshot = associated_product_snapshot()
        dialog.configure_recipe(
            snapshot.portable_recipes.recipes[0], snapshot, DATASET
        )
        assert top_splitter.widget(0) is groups["Source"]
        assert bottom_splitter.widget(0) is groups["Materialization Preview"]
        dialog.configure_recipe_collection(
            snapshot.recipe_collections.collections[0], snapshot, DATASET
        )
        assert top_splitter.widget(1) is groups["Target Dataset"]
        assert bottom_splitter.widget(1) is groups["Optional Artifact Collection"]

        dialog.show()
        qapp.processEvents()
        top_left, top_right = top_splitter.sizes()
        lower_left, lower_right = bottom_splitter.sizes()
        assert abs(top_left - top_right) <= 1
        assert abs(lower_left - lower_right) <= 1
    finally:
        dialog.close()


def test_recipe_mode_summary_and_exact_request(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    requests: list[object] = []
    dialog.preview_requested.connect(requests.append)
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        assert dialog.objectName() == DATA_MANAGER_RECIPE_ARTIFACT_MATERIALIZATION_WINDOW_ID
        assert dialog.windowTitle() == "Create Artifact from Recipe"
        assert dialog.source_labels["source_type"].text() == "Recipe"
        assert dialog.source_labels["tool"].text() == recipe.tool_key
        assert dialog.source_labels["recipe_id"].text() == recipe.recipe_id
        assert dialog.target_label.text() == MARKET.as_key()
        assert dialog.target_labels["exchange"].text() == "bybit"
        assert dialog.target_labels["market_type"].text() == "linear"
        assert dialog.target_labels["asset"].text() == "BTCUSDT"
        assert dialog.target_labels["timeframe"].text() == "1h"
        assert dialog.target_labels["rows"].text() == "5"
        assert dialog.target_labels["first_timestamp"].text() == (
            "1970-01-01 01:00:00 CET (+01:00)"
        )
        assert dialog.target_labels["last_timestamp"].text() == (
            "1970-01-01 01:00:00 CET (+01:00)"
        )
        dialog.preview_button.click()
        assert requests[0].target_market_id == MARKET
        assert requests[0].root_recipe_ids == (recipe.recipe_id,)
        assert requests[0].recipe_collection_id is None
    finally:
        dialog.close()


def test_collection_mode_keeps_exact_revision_and_request(qapp) -> None:
    snapshot = associated_product_snapshot()
    collection = snapshot.recipe_collections.collections[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe_collection(collection, snapshot, DATASET)
        request = dialog.current_request()
        assert dialog.windowTitle() == "Create Artifacts from Recipe Collection"
        assert dialog.source_labels["source_type"].text() == "Recipe Collection"
        assert dialog.source_labels["collection_id"].text() == collection.collection_id
        assert dialog.source_labels["revision_id"].text() == collection.revision_id
        assert request is not None
        assert request.root_recipe_ids == ()
        assert request.recipe_collection_id == collection.collection_id
        assert request.recipe_collection_revision_id == collection.revision_id
    finally:
        dialog.close()


def test_target_and_source_changes_invalidate_preview(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        assert dialog.set_plan(_plan())
        assert dialog.execute_button.isEnabled()
        dialog.set_target(None)
        assert dialog.reviewed_plan is None
        assert not dialog.preview_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
        dialog.set_target(DATASET)
        dialog.set_catalog(
            type(snapshot)(
                snapshot.catalog,
                snapshot.study_environments,
                type(snapshot.portable_recipes)(()),
                snapshot.recipe_collections,
                snapshot.managed_artifacts,
                snapshot.artifact_collections,
                snapshot.database_seeds,
                snapshot.databases,
                    snapshot.latest_reconciliation,
            )
        )
        assert "unavailable" in dialog.source_status.text().lower()
        assert not dialog.preview_button.isEnabled()
    finally:
        dialog.close()


def test_matching_plan_projects_roles_statuses_and_root_outputs(qapp) -> None:
    snapshot = associated_product_snapshot()
    collection = snapshot.recipe_collections.collections[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe_collection(collection, snapshot, DATASET)
        plan = _plan(collection=True)
        assert dialog.set_plan(plan)
        assert dialog.preview_table.rowCount() == 2
        assert tuple(dialog.preview_table.item(row, 2).text() for row in range(2)) == (
            "ROOT",
            "SUPPORT",
        )
        assert tuple(dialog.preview_table.item(row, 3).text() for row in range(2)) == (
            "NEW",
            "REUSE CURRENT",
        )
        assert "Artifacts considered: 2" in dialog.preview_summary.text()
        assert "New: 1" in dialog.preview_summary.text()
        assert "Reuse Current: 1" in dialog.preview_summary.text()
        assert "Advance Lineage: 0" in dialog.preview_summary.text()
        assert "first=1970-01-01 01:00:00 CET (+01:00)" in (
            dialog.preview_summary.text()
        )
        assert "last=1970-01-01 01:00:00 CET (+01:00)" in (
            dialog.preview_summary.text()
        )
        assert "first=0," not in dialog.preview_summary.text()
        assert "last=4," not in dialog.preview_summary.text()
        assert dialog.output_table.rowCount() == 1
        assert dialog.output_table.item(0, 1).text() == plan.nodes[0].tool_key
        assert dialog.output_table.item(0, 4).text() == plan.nodes[0].logical_artifact_id
        assert dialog.set_plan(_plan(collection=False)) is False
    finally:
        dialog.close()


def test_blocked_plan_and_optional_collection_mapping_gates(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        assert dialog.set_plan(_plan(blocked=True))
        assert not dialog.execute_button.isEnabled()
        assert dialog.preview_table.item(1, 3).text() == "BLOCKED"

        assert dialog.set_plan(_plan())
        assert not dialog.create_collection_checkbox.isChecked()
        assert dialog.execute_button.isEnabled()
        dialog.create_collection_checkbox.setChecked(True)
        assert not dialog.execute_button.isEnabled()
        dialog.collection_name_input.setText("Indicators")
        assert not dialog.execute_button.isEnabled()
        dialog.output_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        assert not dialog.execute_button.isEnabled()
        dialog.output_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog.output_table.item(0, 3).setText("custom_sma")
        assert dialog.set_collection_prediction(dialog.reviewed_plan, None)
        assert dialog.execute_button.isEnabled()
        assert dialog.selected_outputs()[0].column_name == "custom_sma"
    finally:
        dialog.close()


def test_optional_artifact_collection_preview_reports_existing_winner(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    winner = object.__new__(ArtifactCollectionRevisionV1)
    object.__setattr__(winner, "collection_id", "ac_11111111111111111111111111111111")
    object.__setattr__(winner, "revision_id", "e" * 64)
    object.__setattr__(winner, "display_name", "Persisted Winner")
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        plan = _plan()
        assert dialog.set_plan(plan)
        dialog.create_collection_checkbox.setChecked(True)
        dialog.collection_name_input.setText("Different requested name")
        assert dialog.set_collection_prediction(plan, winner)
        assert "Artifact Collection: REUSE EXISTING COLLECTION" in (
            dialog.preview_summary.text()
        )
        assert "Existing Name: Persisted Winner" in dialog.preview_summary.text()
        assert "ac_11111111111111111111111111111111" in (
            dialog.preview_summary.text()
        )
    finally:
        dialog.close()


def test_preview_distinguishes_advance_lineage(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        assert dialog.set_plan(_plan(advanced=True))
        assert dialog.preview_table.item(0, 3).text() == "ADVANCE LINEAGE"
        assert "Advance Lineage: 1" in dialog.preview_summary.text()
    finally:
        dialog.close()


def test_output_order_busy_result_and_close_lifecycle(qapp) -> None:
    snapshot = associated_product_snapshot()
    recipe = snapshot.portable_recipes.recipes[0]
    dialog = DataManagerRecipeArtifactMaterializationDialog()
    closed: list[bool] = []
    dialog.closing.connect(lambda: closed.append(True))
    try:
        dialog.configure_recipe(recipe, snapshot, DATASET)
        plan = _plan()
        assert dialog.set_plan(plan)
        first = dialog._output_rows()[0]
        dialog._set_output_rows(
            (
                first,
                type(first)(True, "ema", "ema_20", "ema_20", "8" * 64),
            )
        )
        dialog.create_collection_checkbox.setChecked(True)
        dialog.output_table.selectRow(1)
        dialog.move_up_button.click()
        assert dialog._output_rows()[0].output_name == "ema_20"
        dialog.set_busy(True)
        assert not dialog.preview_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
        assert dialog.close_button.isEnabled()
        dialog.set_busy(False)
        dialog.settle_materialization_success(_result(plan))
        assert "roots=1" in dialog.result_summary.text()
        assert "support=1" in dialog.result_summary.text()
        assert dialog.reviewed_plan is None

        revision = object.__new__(ArtifactCollectionRevisionV1)
        object.__setattr__(revision, "collection_id", "collection_1")
        object.__setattr__(revision, "revision_id", "9" * 64)
        dialog.settle_collection_success(revision)
        assert "collection_1" in dialog.result_summary.text()
        dialog.close()
        QCoreApplication.processEvents()
        assert closed == [True]
    finally:
        dialog.close()
