from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QSizePolicy, QSplitter

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DataManagerCatalogSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerManagedArtifactEntry,
    DataManagerPortableRecipeCatalog,
    DataManagerProductCatalogSnapshot,
    DataManagerRecipeCollectionCatalog,
    DataManagerReconciliationSnapshot,
    DataManagerStudyEnvironmentCatalog,
)
from leonardo.data_manager.creation_models import ArtifactCollectionSelectionPlan
import leonardo.gui.windows.data_manager_artifact_collection_dialog as dialog_module
from leonardo.gui.windows.data_manager_artifact_collection_dialog import (
    DataManagerArtifactCollectionDialog,
)


_QAPP = QApplication.instance() or QApplication([])
MARKET_A = MarketId("bybit", "linear", "BTCUSDT", "1h")
MARKET_B = MarketId("bybit", "linear", "ETHUSDT", "1h")
ROOT_A = "a" * 64
ROOT_B = "b" * 64
ROOT_OTHER = "c" * 64
SUPPORT = "d" * 64


def _artifact(
    logical_id: str,
    market: MarketId,
    tool: str,
    outputs: tuple[str, ...] = ("value",),
    *,
    valid: bool = True,
) -> DataManagerManagedArtifactEntry:
    return DataManagerManagedArtifactEntry(
        logical_id if valid else "invalid_artifact",
        "1" * 64 if valid else "invalid_recipe",
        market,
        (logical_id[::-1] if valid else "invalid_version"),
        None,
        tool,
        "indicator",
        outputs,
        2,
        0,
        3_600_000,
        datetime(2026, 8, 28, tzinfo=UTC),
        valid,
        "rejected" if not valid else "",
    )


def _snapshot() -> DataManagerProductCatalogSnapshot:
    artifacts = (
        _artifact(ROOT_A, MARKET_A, "ema"),
        _artifact(ROOT_B, MARKET_A, "sma"),
        _artifact(ROOT_OTHER, MARKET_B, "rsi"),
        _artifact("invalid", MARKET_A, "bad", valid=False),
    )
    return DataManagerProductCatalogSnapshot(
        DataManagerCatalogSnapshot(()),
        DataManagerStudyEnvironmentCatalog(()),
        DataManagerPortableRecipeCatalog(()),
        DataManagerRecipeCollectionCatalog(()),
        DataManagerManagedArtifactCatalog(artifacts),
        (),
        (),
        (),
        DataManagerReconciliationSnapshot(
            datetime(2026, 8, 28, tzinfo=UTC), (), (), (), (), (), "0" * 64
        ),
    )


def _member(logical_id: str, tool: str, outputs: tuple[str, ...] = ("value",)):
    return SimpleNamespace(
        version_key=ManagedArtifactVersionKey(logical_id, logical_id[::-1]),
        tool_key=tool,
        kind="indicator",
        output_names=outputs,
        portable_recipe_id="1" * 64,
    )


def _plan(
    roots: tuple[str, ...],
    *,
    market: MarketId = MARKET_A,
) -> ArtifactCollectionSelectionPlan:
    members = []
    for logical_id in roots:
        members.append(_member(logical_id, "ema" if logical_id == ROOT_A else "sma"))
    members.append(_member(SUPPORT, "support", ("support_value",)))
    value = object.__new__(ArtifactCollectionSelectionPlan)
    for name, item in {
        "plan_id": "f" * 64,
        "market_id": market,
        "source_ohlcv": OHLCVSourceFingerprintV1(
            market, "1" * 64, "2" * 64, 2, 0, 3_600_000, "committed", "ok", "1.0"
        ),
        "root_logical_artifact_ids": roots,
        "support_logical_artifact_ids": (SUPPORT,),
        "members": tuple(members),
        "dependency_edges": (),
        "execution_stages": ((SUPPORT,), roots),
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3_600_000,
    }.items():
        object.__setattr__(value, name, item)
    return value


def _check(dialog: DataManagerArtifactCollectionDialog, logical_id: str) -> None:
    for row in range(dialog.artifact_table.rowCount()):
        item = dialog.artifact_table.item(row, 0)
        if item.data(Qt.ItemDataRole.UserRole) == logical_id:
            item.setCheckState(Qt.CheckState.Checked)
            return
    raise AssertionError(f"Artifact row not found: {logical_id}")


def _revision() -> ArtifactCollectionRevisionV1:
    value = object.__new__(ArtifactCollectionRevisionV1)
    members = (_member(ROOT_A, "ema"), _member(SUPPORT, "support", ("support_value",)))
    for name, item in {
        "collection_id": "collection_1",
        "revision_id": "e" * 64,
        "display_name": "Collection",
        "description": "Description",
        "market_id": MARKET_A,
        "root_logical_artifact_ids": (ROOT_A,),
        "support_logical_artifact_ids": (SUPPORT,),
        "members": members,
        "dependency_edges": (),
        "selected_outputs": (ArtifactCollectionOutputV1(ROOT_A, "value", "first"),),
        "presentation_order": ("first",),
        "source_portable_recipe_ids": ("1" * 64,),
        "source_recipe_collection_id": None,
        "source_recipe_collection_revision_id": None,
        "source_ohlcv": OHLCVSourceFingerprintV1(
            MARKET_A, "1" * 64, "2" * 64, 2, 0, 3_600_000, "committed", "ok", "1.0"
        ),
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3_600_000,
        "validation_state": "valid",
        "database_ready": True,
        "previous_revision_id": None,
        "created_at_utc": datetime(2026, 8, 28, tzinfo=UTC),
        "revised_at_utc": datetime(2026, 8, 28, tzinfo=UTC),
        "schema_version": "1.0",
        "object_type": "artifact_collection_revision",
    }.items():
        object.__setattr__(value, name, item)
    return value


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
    snapshot = _snapshot()
    dialog = DataManagerArtifactCollectionDialog(
        snapshot,
        browsing_market_id=MARKET_A,
    )
    try:
        assert calls == [(dialog, None, 0.75, 0.75)]
        groups = {
            group.title(): group
            for group in dialog.findChildren(QGroupBox)
        }
        expected = {"Collection", "Artifact roots", "Preview", "Output Mapping"}
        assert expected <= groups.keys()
        layouts = {title: groups[title].layout() for title in expected}
        assert all(layout.contentsMargins().top() == 24 for layout in layouts.values())
        assert dialog.minimumWidth() < dialog.maximumWidth()
        assert dialog.minimumHeight() < dialog.maximumHeight()
        workspace = dialog.findChild(
            QSplitter, "data_manager.artifact_collection.splitter.workspace"
        )
        right = dialog.findChild(
            QSplitter, "data_manager.artifact_collection.splitter.right"
        )
        assert workspace is dialog.workspace_splitter
        assert workspace.orientation() == Qt.Orientation.Horizontal
        assert workspace.count() == 2
        assert not workspace.childrenCollapsible()
        assert workspace.widget(0) is dialog.left_workspace
        assert workspace.widget(1) is right
        assert right is dialog.right_splitter
        assert right.orientation() == Qt.Orientation.Vertical
        assert right.count() == 2
        assert not right.childrenCollapsible()
        assert right.widget(0) is groups["Preview"]
        assert right.widget(1) is groups["Output Mapping"]

        left_layout = dialog.left_workspace.layout()
        assert left_layout.indexOf(groups["Collection"]) == 0
        assert left_layout.indexOf(groups["Artifact roots"]) == 1
        assert left_layout.spacing() == 10
        assert left_layout.stretch(0) == 0
        assert left_layout.stretch(1) == 1
        assert (
            groups["Collection"].sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Fixed
        )
        assert (
            groups["Artifact roots"].sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Expanding
        )

        dialog.resize(1200, 900)
        dialog.show()
        _QAPP.processEvents()
        left_size, right_size = workspace.sizes()
        assert abs(left_size - right_size) <= 1
        top_size, bottom_size = right.sizes()
        assert abs(top_size - bottom_size) <= 1

        dialog.configure_create(snapshot, browsing_market_id=MARKET_A)
        assert all(groups[title].layout() is layouts[title] for title in expected)
        dialog.configure_edit(_revision(), snapshot, browsing_market_id=MARKET_B)
        assert all(groups[title].layout() is layouts[title] for title in expected)
    finally:
        dialog.close()


def test_scope_first_root_market_anchor_and_reset() -> None:
    dialog = DataManagerArtifactCollectionDialog(
        _snapshot(), browsing_market_id=MARKET_A
    )
    try:
        assert dialog.artifact_table.rowCount() == 3
        dialog.dataset_scope.setCurrentIndex(1)
        assert dialog.artifact_table.rowCount() == 4
        _check(dialog, ROOT_A)
        assert dialog.selection_market_id == MARKET_A
        other = next(
            dialog.artifact_table.item(row, 0)
            for row in range(dialog.artifact_table.rowCount())
            if dialog.artifact_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            == ROOT_OTHER
        )
        assert not bool(other.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        dialog.deselect_all_button.click()
        assert dialog.selection_market_id is None
        assert dialog.selected_root_logical_artifact_ids() == ()
    finally:
        dialog.close()


def test_preview_projects_support_and_requires_unique_output_columns() -> None:
    dialog = DataManagerArtifactCollectionDialog(
        _snapshot(), browsing_market_id=MARKET_A
    )
    created: list[tuple] = []
    dialog.create_requested.connect(lambda *values: created.append(values))
    try:
        _check(dialog, ROOT_A)
        _check(dialog, ROOT_B)
        plan = _plan((ROOT_A, ROOT_B))
        assert dialog.set_plan(plan)
        assert [dialog.preview_table.item(row, 0).text() for row in range(3)] == [
            "ROOT",
            "ROOT",
            "SUPPORT",
        ]
        assert SUPPORT not in {
            dialog.output_table.item(row, 4).text()
            for row in range(dialog.output_table.rowCount())
        }
        dialog.name_input.setText("Collection")
        assert not dialog.publish_button.isEnabled()
        dialog.output_table.item(1, 3).setText("second")
        assert not dialog.publish_button.isEnabled()
        dialog.output_table.selectRow(1)
        dialog.move_up_button.click()
        assert dialog.presentation_order() == ("second", "value")
        assert dialog.set_collection_prediction(plan, None)
        assert dialog.publish_button.isEnabled()
        dialog.publish_button.click()
        assert created[0][0] is plan
        assert tuple(item.column_name for item in created[0][3]) == (
            "second",
            "value",
        )
    finally:
        dialog.close()


def test_edit_fixed_market_mapping_preservation_busy_and_close() -> None:
    snapshot = _snapshot()
    dialog = DataManagerArtifactCollectionDialog(
        snapshot, browsing_market_id=MARKET_B
    )
    closed: list[bool] = []
    dialog.closing.connect(lambda: closed.append(True))
    dialog.configure_edit(_revision(), snapshot, browsing_market_id=MARKET_B)
    try:
        assert dialog.selection_market_id == MARKET_A
        assert dialog.collection_id == "collection_1"
        assert dialog.expected_revision_id == "e" * 64
        assert dialog.output_table.item(0, 3).text() == "first"
        dialog.dataset_scope.setCurrentIndex(1)
        _check(dialog, ROOT_B)
        plan = _plan((ROOT_A, ROOT_B))
        assert dialog.set_plan(plan)
        assert dialog.output_table.item(0, 3).text() == "first"
        assert dialog.output_table.item(1, 3).text() == "value"
        dialog.set_busy(True)
        assert not dialog.artifact_table.isEnabled()
        assert not dialog.output_table.isEnabled()
    finally:
        dialog.close()
    assert closed == [True]


def test_preview_reports_equivalent_collection_winner() -> None:
    dialog = DataManagerArtifactCollectionDialog(
        _snapshot(), browsing_market_id=MARKET_A
    )
    winner = _revision()
    try:
        _check(dialog, ROOT_A)
        dialog.name_input.setText("Different requested name")
        plan = _plan((ROOT_A,))
        assert dialog.set_plan(plan)
        assert dialog.set_collection_prediction(plan, winner)
        assert "Result: REUSE EXISTING COLLECTION" in dialog.preview_summary.text()
        assert winner.display_name in dialog.preview_summary.text()
        assert winner.collection_id in dialog.preview_summary.text()
        assert winner.revision_id in dialog.preview_summary.text()
        assert dialog.publish_button.isEnabled()
    finally:
        dialog.close()
