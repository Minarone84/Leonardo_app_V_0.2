from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.core_runner import TaskResult
from leonardo.data_manager import (
    DataManagerDatabaseCatalogEntry,
    DataManagerDatabaseCurrentness,
    DatabaseDefinitionV1,
)
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.presenters import (
    DataManagerSuitePresenter,
    OhlcvMaintenancePresenter,
)
from leonardo.gui.windows import DataManagerSuiteWindow, OhlcvMaintenanceWindow
from tests.gui_test.test_data_manager_catalogs import (
    MARKET_B,
    TIMESTAMP_MS,
    associated_product_snapshot,
)
from tests.gui_test.test_data_manager_presenter import (
    _ControlledApplication,
    _settle_initial_warmup,
)
from tests.gui_test.test_ohlcv_maintenance_presenter import (
    _FakeMaintenanceService,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _snapshot(
    signature: str,
    *,
    artifact_status: str,
    database_status: str,
):
    snapshot = associated_product_snapshot()
    artifact = replace(
        snapshot.latest_reconciliation.artifacts[0],
        status=artifact_status,
        reasons=(f"Artifact is {artifact_status}",),
    )
    database = DataManagerDatabaseCurrentness(
        "db_" + "1" * 32,
        "3" * 64,
        MARKET_B,
        database_status,
        TIMESTAMP_MS,
        TIMESTAMP_MS,
        TIMESTAMP_MS,
        0,
        True,
        (f"Database is {database_status}",),
    )
    definition = DatabaseDefinitionV1(
        database.database_id,
        "Research Database",
        "",
        MARKET_B,
        "seed_" + "2" * 32,
        datetime(2026, 8, 9, tzinfo=UTC),
    )
    reconciliation = replace(
        snapshot.latest_reconciliation,
        artifacts=(artifact,),
        databases=(database,),
        evidence_signature=signature * 64,
    )
    return replace(
        snapshot,
        databases=(DataManagerDatabaseCatalogEntry(definition, None, 1, database),),
        latest_reconciliation=reconciliation,
    )


def _currentness(window: DataManagerSuiteWindow, family: str) -> str:
    workspace = window._catalog_workspace
    workspace.set_selected_market(MARKET_B)
    workspace.select_family(family)
    column = next(
        index
        for index in range(workspace.table.columnCount())
        if workspace.table.horizontalHeaderItem(index).text() == "Currentness"
    )
    assert workspace.table.rowCount() == 1
    return workspace.table.item(0, column).text()


def test_open_data_manager_reconciles_changed_ohlcv_without_publishing_products(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    initial = _snapshot(
        "a", artifact_status="CURRENT", database_status="CURRENT"
    )
    changed = _snapshot(
        "b",
        artifact_status="APPEND_AVAILABLE",
        database_status="WAITING_FOR_ARTIFACT_UPDATE",
    )
    later = _snapshot(
        "c", artifact_status="CURRENT", database_status="UPDATE_AVAILABLE"
    )
    data_view = DataManagerSuiteWindow()
    data_service = _ControlledApplication(product_catalogs=True)
    data_presenter = DataManagerSuitePresenter(data_view, data_service)
    _settle_initial_warmup(data_service, snapshot=initial)
    composition = object.__new__(GuiCompositionRoot)
    composition._data_manager_suite_presenter = data_presenter
    maintenance_service = _FakeMaintenanceService(tmp_path)
    maintenance_view = OhlcvMaintenanceWindow()
    maintenance_presenter = OhlcvMaintenancePresenter(  # type: ignore[arg-type]
        maintenance_view,
        maintenance_service,
        on_canonical_ohlcv_evidence_changed=(
            composition._notify_data_manager_ohlcv_change
        ),
    )
    calls_before = len(data_service.calls)
    try:
        assert _currentness(data_view, "Artifacts") == "CURRENT"
        assert _currentness(data_view, "Databases") == "CURRENT"

        maintenance_view.button_for_id("validate").click()
        maintenance_service.emit_validation_success()
        QCoreApplication.processEvents()

        reconcile = data_service.calls[-1]
        assert reconcile[0] == "reconcile_status"
        assert data_service.reconcile_forces[-1] is True
        reconcile[2](
            TaskResult(
                reconcile[1], "completed", changed.latest_reconciliation
            )
        )
        product_scan = data_service.calls[-1]
        assert product_scan[0] == "scan_product_catalogs"
        product_scan[2](TaskResult(product_scan[1], "completed", changed))

        assert _currentness(data_view, "Artifacts") == "UPDATE AVAILABLE"
        workspace = data_view._catalog_workspace
        workspace.table.selectRow(0)
        inspector = {
            workspace.inspector.item(index, 0).text(): workspace.inspector.item(
                index, 1
            ).text()
            for index in range(workspace.inspector.rowCount())
        }
        assert "Artifact is APPEND_AVAILABLE" in inspector["currentness.reasons"]
        artifact_inspection = data_service.calls[-1]
        assert artifact_inspection[0][0] == "inspect_artifact"
        artifact_inspection[2](
            TaskResult(
                artifact_inspection[1],
                "failed",
                error_message="expected inspection settlement",
            )
        )
        assert _currentness(data_view, "Databases") == "BLOCKED"

        calls_after_first = len(data_service.calls)
        assert maintenance_view.button_for_id("validate").isEnabled()
        maintenance_view.button_for_id("validate").click()
        maintenance_service.emit_validation_success()
        QCoreApplication.processEvents()
        assert len(data_service.calls) == calls_after_first + 1
        reconcile = data_service.calls[-1]
        assert reconcile[0] == "reconcile_status"
        reconcile[2](
            TaskResult(reconcile[1], "completed", later.latest_reconciliation)
        )
        product_scan = data_service.calls[-1]
        assert product_scan[0] == "scan_product_catalogs"
        product_scan[2](TaskResult(product_scan[1], "completed", later))
        assert data_presenter._product_catalogs is later

        assert _currentness(data_view, "Databases") == "UPDATE AVAILABLE"
        assert [call[0] for call in data_service.calls[calls_before:]] == [
            "reconcile_status",
            "scan_product_catalogs",
            artifact_inspection[0],
            "reconcile_status",
            "scan_product_catalogs",
        ]
        assert (
            initial.managed_artifacts.artifacts[0].artifact_id
            == changed.managed_artifacts.artifacts[0].artifact_id
            == later.managed_artifacts.artifacts[0].artifact_id
        )
        assert tuple(
            (item.collection_id, item.revision_id)
            for item in initial.artifact_collections
        ) == tuple(
            (item.collection_id, item.revision_id)
            for item in changed.artifact_collections
        ) == tuple(
            (item.collection_id, item.revision_id)
            for item in later.artifact_collections
        )
        assert all(item.current_manifest is None for item in later.databases)
    finally:
        maintenance_view.close()
        data_view.close()
        del maintenance_presenter
