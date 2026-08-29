from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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
        assert dialog.publish_button.isEnabled()
        dialog.output_table.selectRow(1)
        dialog.move_up_button.click()
        assert dialog.presentation_order() == ("second", "value")
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
