from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.artifacts import (
    ArtifactMetadataV1,
    ManagedArtifactVersionKey,
)
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionValidation,
)
import leonardo.gui.windows.data_manager_collection_inspection_dialog as dialog_module
from leonardo.gui.windows.data_manager_collection_inspection_dialog import (
    DataManagerCollectionInspectionDialog,
)
from tests.gui_test.test_data_manager_recipe_collection_dialog import (
    ROOT_ID,
    SUPPORT_ID,
    _inspection,
    _recipe,
)


_QAPP = QApplication.instance() or QApplication([])
MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
ROOT_LOGICAL_ID = "1" * 64
SUPPORT_LOGICAL_ID = "2" * 64
ROOT_ARTIFACT_ID = "3" * 64
SUPPORT_ARTIFACT_ID = "4" * 64
ROOT_RECIPE_ID = "5" * 64
SUPPORT_RECIPE_ID = "6" * 64


def _table_rows(table) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(table.item(row, column).text() for column in range(table.columnCount()))
        for row in range(table.rowCount())
    )


def _artifact_metadata(
    artifact_id: str,
    recipe_id: str,
    tool_key: str,
    *,
    source_artifacts: tuple[object, ...] = (),
) -> ArtifactMetadataV1:
    value = object.__new__(ArtifactMetadataV1)
    recipe = SimpleNamespace(
        recipe_id=recipe_id,
        market_id=MARKET,
        tool_key=tool_key,
        kind="indicator",
        parameters={"period": 20},
        bindings={"source": "OHLCV.close"},
        source_artifacts=source_artifacts,
        output_names=(f"{tool_key}_20",),
    )
    for name, item in {
        "artifact_id": artifact_id,
        "recipe": recipe,
        "row_count": 2,
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3_600_000,
        "values_sha256": "7" * 64,
    }.items():
        object.__setattr__(value, name, item)
    return value


def _artifact_revision() -> ArtifactCollectionRevisionV1:
    root_member = SimpleNamespace(
        version_key=ManagedArtifactVersionKey(
            ROOT_LOGICAL_ID, ROOT_ARTIFACT_ID
        ),
        portable_recipe_id=ROOT_RECIPE_ID,
        tool_key="ema",
        kind="indicator",
        output_names=("ema_20",),
        values_sha256="7" * 64,
    )
    support_member = SimpleNamespace(
        version_key=ManagedArtifactVersionKey(
            SUPPORT_LOGICAL_ID, SUPPORT_ARTIFACT_ID
        ),
        portable_recipe_id=SUPPORT_RECIPE_ID,
        tool_key="sma",
        kind="indicator",
        output_names=("sma_20",),
        values_sha256="7" * 64,
    )
    value = object.__new__(ArtifactCollectionRevisionV1)
    for name, item in {
        "collection_id": "collection_1",
        "revision_id": "8" * 64,
        "display_name": "Artifacts",
        "description": "Saved collection",
        "market_id": MARKET,
        "root_logical_artifact_ids": (ROOT_LOGICAL_ID,),
        "support_logical_artifact_ids": (SUPPORT_LOGICAL_ID,),
        "members": (support_member, root_member),
        "selected_outputs": (
            ArtifactCollectionOutputV1(
                ROOT_LOGICAL_ID, "ema_20", "ema_column"
            ),
            ArtifactCollectionOutputV1(
                SUPPORT_LOGICAL_ID, "sma_20", "sma_column"
            ),
        ),
        "presentation_order": ("sma_column", "ema_column"),
        "source_recipe_collection_id": "source_collection",
        "source_recipe_collection_revision_id": "9" * 64,
        "validation_state": "valid",
        "first_timestamp_ms": 0,
        "last_timestamp_ms": 3_600_000,
        "created_at_utc": datetime(2026, 8, 28, tzinfo=UTC),
        "revised_at_utc": datetime(2026, 8, 29, tzinfo=UTC),
    }.items():
        object.__setattr__(value, name, item)
    return value


def test_recipe_collection_mode_geometry_members_and_read_only_tables(
    monkeypatch,
) -> None:
    calls: list[tuple[float, float]] = []

    def capture_size(_window, *, parent=None, width_fraction, height_fraction):
        del parent
        calls.append((width_fraction, height_fraction))

    monkeypatch.setattr(dialog_module, "apply_initial_window_size", capture_size)
    dialog = DataManagerCollectionInspectionDialog()
    closed: list[bool] = []
    dialog.closing.connect(lambda: closed.append(True))
    try:
        inspection = _inspection()
        dialog.configure_recipe_collection(
            inspection,
            (_recipe(SUPPORT_ID, "sma"), _recipe(ROOT_ID, "ema")),
        )
        assert calls == [(0.75, 0.75)]
        assert dialog.windowTitle() == "Recipe Collection Inspection"
        assert not dialog.outputs_group.isVisible()
        assert dialog.metadata_table.editTriggers().value == 0
        assert dialog.members_table.editTriggers().value == 0
        metadata = dict(_table_rows(dialog.metadata_table))
        assert metadata["Collection ID"] == "collection_1"
        assert metadata["Root count"] == "1"
        assert _table_rows(dialog.members_table) == (
            (
                "SUPPORT", "1", "sma", "indicator", "period=20",
                "source=OHLCV.close", "sma_20", SUPPORT_ID,
            ),
            (
                "ROOT", "2", "ema", "indicator", "period=20",
                "source=OHLCV.close", "ema_20", ROOT_ID,
            ),
        )
    finally:
        dialog.close()
    assert closed == [True]


def test_artifact_collection_mode_projects_embedded_semantics_and_outputs() -> None:
    dialog = DataManagerCollectionInspectionDialog()
    revision = _artifact_revision()
    source = SimpleNamespace(
        role="source",
        artifact_id=SUPPORT_ARTIFACT_ID,
        output_name="sma_20",
    )
    root = _artifact_metadata(
        ROOT_ARTIFACT_ID,
        ROOT_RECIPE_ID,
        "ema",
        source_artifacts=(source,),
    )
    support = _artifact_metadata(
        SUPPORT_ARTIFACT_ID,
        SUPPORT_RECIPE_ID,
        "sma",
    )
    validation = ArtifactCollectionValidation(
        revision.collection_id,
        revision.revision_id,
        True,
        True,
        (),
        0,
        3_600_000,
        2,
        2,
    )
    try:
        dialog.configure_artifact_collection(
            revision, validation, (support, root)
        )
        assert dialog.windowTitle() == "Artifact Collection Inspection"
        assert not dialog.outputs_group.isHidden()
        metadata = dict(_table_rows(dialog.metadata_table))
        assert metadata["Exchange"] == "bybit"
        assert metadata["Collection ID"] == "collection_1"
        assert metadata["Source Recipe Collection ID"] == "source_collection"
        assert metadata["Source Recipe Collection Revision ID"] == "9" * 64
        rows = _table_rows(dialog.members_table)
        assert [row[0] for row in rows] == ["ROOT", "SUPPORT"]
        assert rows[0][3] == "period=20"
        assert rows[0][4] == "source=OHLCV.close"
        assert rows[0][5] == (
            f"source=Artifact[{SUPPORT_ARTIFACT_ID}].sma_20"
        )
        assert rows[0][6:8] == ("ema_20", "2")
        assert rows[0][8] == "1970-01-01 01:00:00 CET (+01:00)"
        assert rows[0][9] == "1970-01-01 02:00:00 CET (+01:00)"
        assert rows[0][10:] == (ROOT_LOGICAL_ID, ROOT_ARTIFACT_ID)
        assert _table_rows(dialog.outputs_table) == (
            ("1", "sma_20", "sma_column", SUPPORT_LOGICAL_ID),
            ("2", "ema_20", "ema_column", ROOT_LOGICAL_ID),
        )
    finally:
        dialog.close()
