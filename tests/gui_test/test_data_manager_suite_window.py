from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QWidget,
)
from shiboken6 import isValid

from leonardo.artifacts import ManagedArtifactVersionKey, OHLCVSourceFingerprintV1
from leonardo.core.window_registry import WindowRegistry
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DataManagerArtifactEntry,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerRecipeEntry,
    DataManagerRecipeCollectionInspection,
    DataManagerStudyEntryPortability,
    DataManagerStudyEnvironmentEntry,
    DataManagerStudyEnvironmentInspection,
)
from leonardo.data_manager.models import (
    DUPLICATE_MAINTENANCE_DOMAINS,
    DuplicateMaintenanceCandidate,
    DuplicateMaintenanceGroup,
    DuplicateMaintenancePreflight,
    DuplicateMaintenancePurgeDetail,
    DuplicateMaintenancePurgeResult,
    DuplicateMaintenanceScanResult,
)
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.data_manager.direct_artifact import DataManagerDirectArtifactCatalog
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    data_manager_dataset_row,
)
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
REJECTED_MARKET = MarketId("bybit", "linear", "XRPUSDT", "4h")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dataset(accepted=True):
    return DataManagerDatasetEntry(
        MARKET if accepted else REJECTED_MARKET,
        accepted,
        6 if accepted else None,
        1 if accepted else None,
        6 if accepted else None,
        rejection_code="" if accepted else "hash",
        rejection_reason="" if accepted else "source changed",
    )


def _snapshot(valid=True):
    recipe = DataManagerRecipeEntry(
        MARKET,
        "r" * 64,
        "rsi",
        "oscillator",
        ("rsi",),
        "RSI",
        None,
        valid,
        "invalid recipe" if not valid else "",
    )
    artifact = DataManagerArtifactEntry(
        MARKET,
        "a" * 64,
        recipe.recipe_id,
        "rsi",
        "oscillator",
        ("rsi",),
        6,
        1,
        6,
        None,
        valid,
        "invalid artifact" if not valid else "",
        "unknown" if valid else "invalid",
    )
    return DataManagerMarketSnapshot(MARKET, _dataset(), (recipe,), (artifact,))


def _selector_row(window: DataManagerSuiteWindow, symbol: str) -> int:
    dialog = window.dataset_selector_dialog()
    assert dialog is not None
    table = dialog.table_for_id("data_manager.table.datasets")
    for row in range(table.rowCount()):
        if table.item(row, 3).text() == symbol:
            return row
    raise AssertionError(f"selector row not found: {symbol}")


def _direct_catalog(market: MarketId = MARKET) -> DataManagerDirectArtifactCatalog:
    fingerprint = OHLCVSourceFingerprintV1(
        market, "1" * 64, "2" * 64, 6, 1, 6, "committed", "ok", "1.0"
    )
    return DataManagerDirectArtifactCatalog(market, fingerprint, (), ())


def _environment_inspection(
    environment_id: str = "environment_1",
) -> DataManagerStudyEnvironmentInspection:
    environment = DataManagerStudyEnvironmentEntry(
        environment_id,
        "Environment",
        "Description",
        MARKET,
        1,
        1,
        0,
        0,
        0,
        0,
        datetime(2026, 8, 17, tzinfo=UTC),
        datetime(2026, 8, 17, tzinfo=UTC),
    )
    entry = DataManagerStudyEntryPortability(
        "entry_1",
        "EMA",
        "calculation",
        "indicator",
        "ema",
        "PORTABLE",
        "",
        (),
        "a" * 64,
    )
    return DataManagerStudyEnvironmentInspection(environment, (entry,))


def test_dataset_selection_remains_functional_without_legacy_object_tables(qapp) -> None:
    window = DataManagerSuiteWindow()
    selected: list[MarketId] = []
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(),)))
        assert window.property("object_id") == "data_manager_suite.window"
        assert window.findChild(QTableWidget, "data_manager.table.datasets") is None
        assert window.findChild(QTableWidget, "data_manager.table.artifacts") is None
        assert window.findChild(QTableWidget, "data_manager.table.recipes") is None

        for obsolete_button in (
            "data_manager.button.preview_artifact",
            "data_manager.button.validate_artifact",
            "data_manager.button.delete_artifact",
            "data_manager.button.delete_recipe",
        ):
            with pytest.raises(KeyError):
                window.button_for_id(obsolete_button)

        window.market_selected.connect(selected.append)
        window.button_for_id("data_manager.button.select_dataset").click()
        QCoreApplication.processEvents()
        dialog = window.dataset_selector_dialog()
        assert dialog is not None
        assert dialog.isVisible()
        table = dialog.table_for_id("data_manager.table.datasets")
        assert tuple(
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())
        ) == (
            "Select",
            "Exchange",
            "Market Type",
            "Symbol",
            "Timeframe",
            "Status",
            "Persistence",
            "Validation",
            "Rows",
            "First Data",
            "Last Data",
            "Details",
        )
        row = _selector_row(window, "BTCUSDT")
        cell = table.cellWidget(row, 0)
        assert cell is not None
        checkboxes = cell.findChildren(QCheckBox)
        assert len(checkboxes) == 1
        checkbox = checkboxes[0]
        checkbox.setChecked(True)
        table.selectRow(row)
        dialog.button_for_id("data_manager.dataset_selector.button.select").click()
        QCoreApplication.processEvents()
        assert selected == [MARKET]
        assert window.selected_market_id() == MARKET
        assert window._catalog_workspace._selected_market == MARKET
        assert window.button_for_id("data_manager.button.preview_dataset").isEnabled()

        window.set_market_snapshot(_snapshot())
        assert window._catalog_workspace._selected_market == MARKET
        assert window._operation_surface.context_text() == (
            "Accepted dataset ready for preview and Database workflows."
        )
        assert window.findChild(QTableWidget, "data_manager.table.artifacts") is None
        assert window.findChild(QTableWidget, "data_manager.table.recipes") is None

        window.set_busy(True, "preview")
        assert all(not button.isEnabled() for button in window._buttons.values())
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.refresh"
        ).isEnabled()
    finally:
        window.close()


def test_legacy_recipe_created_timestamp_uses_canonical_display_time(qapp) -> None:
    window = DataManagerSuiteWindow()
    table = QTableWidget(0, 7)
    window._tables["data_manager.table.recipes"] = table
    recipe = replace(
        _snapshot().recipes[0],
        created_at_utc=datetime(2026, 8, 9, 17, 42, 17, tzinfo=UTC),
    )
    try:
        window._recipes = (recipe,)
        window._populate_recipes()
        assert table.item(0, 5).text() == "2026-08-09 19:42:17 CEST (+02:00)"
        assert "2026-08-09T" not in table.item(0, 5).text()
    finally:
        window.close()


def test_top_strip_and_selected_dataset_projection_lifecycle(qapp) -> None:
    window = DataManagerSuiteWindow()
    try:
        assert window.windowTitle() == "Data Manager Suite"
        groups = window.findChildren(QGroupBox)
        assert not any(group.title() == "Data Manager Suite" for group in groups)
        actions = next(group for group in groups if group.title() == "Actions")
        selected_group = window.findChild(
            QGroupBox, "data_manager.selected_dataset.group"
        )
        assert selected_group is not None
        assert actions.parentWidget() is selected_group.parentWidget()
        strip_layout = actions.parentWidget().layout()
        assert strip_layout.indexOf(actions) < strip_layout.indexOf(selected_group)
        assert strip_layout.stretch(strip_layout.indexOf(actions)) == 0
        assert strip_layout.stretch(strip_layout.indexOf(selected_group)) == 1
        assert tuple(
            window.button_for_id(object_id).text()
            for object_id in (
                "data_manager.button.refresh",
                "data_manager.button.select_dataset",
                "data_manager.button.preview_dataset",
            )
        ) == ("Refresh", "Select Dataset", "Preview Dataset")
        for old_id in (
            "data_manager.label.selected_market",
            "data_manager.label.selection_details",
            "data_manager.label.status",
        ):
            assert window.findChild(QObject, old_id) is None

        table = window.findChild(
            QTableWidget, "data_manager.selected_dataset.table"
        )
        assert table is not None
        assert tuple(
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())
        ) == DATA_MANAGER_DATASET_COLUMNS
        assert table.rowCount() == 0

        original = _dataset()
        window.set_catalog(DataManagerCatalogSnapshot((original,)))
        assert table.rowCount() == 0
        assert window.select_market(MARKET, emit_selection=False)
        assert table.rowCount() == 1
        assert tuple(
            table.item(0, column).text() for column in range(table.columnCount())
        ) == data_manager_dataset_row(original)

        refreshed = replace(
            original,
            persistence_status="refreshed",
            validation_status="accepted",
            warnings=("catalog refreshed",),
        )
        window.set_catalog(DataManagerCatalogSnapshot((refreshed,)))
        assert tuple(
            table.item(0, column).text() for column in range(table.columnCount())
        ) == data_manager_dataset_row(refreshed)

        settled = replace(refreshed, source="snapshot")
        window.set_market_snapshot(DataManagerMarketSnapshot(MARKET, settled, (), ()))
        assert tuple(
            table.item(0, column).text() for column in range(table.columnCount())
        ) == data_manager_dataset_row(settled)
        window.clear_selected_market("Dataset unavailable")
        assert table.rowCount() == 0
    finally:
        window.close()


def test_rejected_dataset_remains_visible_but_cannot_be_selected(qapp) -> None:
    window = DataManagerSuiteWindow()
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(False), _dataset())))
        window.button_for_id("data_manager.button.select_dataset").click()
        QCoreApplication.processEvents()
        dialog = window.dataset_selector_dialog()
        assert dialog is not None
        table = dialog.table_for_id("data_manager.table.datasets")
        row = _selector_row(window, "XRPUSDT")
        table.selectRow(row)
        QCoreApplication.processEvents()
        assert window.selected_market_id() is None
        cell = table.cellWidget(row, 0)
        assert cell is not None
        checkboxes = cell.findChildren(QCheckBox)
        assert len(checkboxes) == 1
        checkbox = checkboxes[0]
        assert not checkbox.isEnabled()
        assert not checkbox.isChecked()
        assert "source changed" in table.item(row, 11).text()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
    finally:
        window.close()


def test_recipe_artifact_materialization_dialog_is_single_owned_and_tracked(
    qapp,
) -> None:
    tracked: list[tuple[object, str, str, str]] = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *values: tracked.append(values)
    )
    snapshot = replace(
        associated_product_snapshot(),
        catalog=DataManagerCatalogSnapshot((_dataset(),)),
    )
    recipe = snapshot.portable_recipes.recipes[0]
    collection = snapshot.recipe_collections.collections[0]
    try:
        window.set_product_catalogs(snapshot)
        assert window.select_market(MARKET, emit_selection=False)
        window.set_market_snapshot(_snapshot())
        window.show_recipe_artifact_materialization_dialog(recipe, snapshot)
        dialog = window.recipe_artifact_materialization_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Create Artifact from Recipe"
        assert dialog.target_market_id == MARKET
        assert tracked == [
            (
                dialog,
                "data_manager.recipe_artifact_materialization.window",
                "Recipe Artifact Materialization",
                "dialog",
            )
        ]

        window.show_recipe_artifact_materialization_dialog(collection, snapshot)
        assert window.recipe_artifact_materialization_dialog() is dialog
        assert dialog.windowTitle() == "Create Artifacts from Recipe Collection"
        assert dialog.source_labels["revision_id"].text() == collection.revision_id
        assert len(tracked) == 1

        window.set_busy(True, "materialization")
        assert not dialog.preview_button.isEnabled()
        window.set_busy(False)
        window.clear_selected_market("Unavailable")
        assert dialog.target_market_id is None
        assert not dialog.preview_button.isEnabled()

        dialog.close()
        QCoreApplication.processEvents()
        assert window.recipe_artifact_materialization_dialog() is None
        window.show_recipe_artifact_materialization_dialog(recipe, snapshot)
        reopened = window.recipe_artifact_materialization_dialog()
        assert reopened is not None and reopened is not dialog
        assert len(tracked) == 2
        window.close()
        QCoreApplication.processEvents()
        assert window.recipe_artifact_materialization_dialog() is None
        assert not isValid(reopened)
    finally:
        if isValid(window):
            window.close()


def test_catalog_details_span_body_below_workspace_and_operation(qapp) -> None:
    window = DataManagerSuiteWindow()
    try:
        window.show()
        QCoreApplication.processEvents()
        old_body = window.findChild(QSplitter, "data_manager.splitter.body")
        tabs = window.findChild(QTabWidget, "data_manager.tabs.workspace")
        old_right_rail = window.findChild(QWidget, "data_manager.panel.right_rail")
        body = window.findChild(QWidget, "data_manager.panel.body")
        upper = window.findChild(QWidget, "data_manager.panel.upper")
        details = window.findChild(
            QWidget, "data_manager.panel.catalog_details"
        )
        inspector_panel = window._catalog_workspace.inspector_panel()
        history_panel = window._catalog_workspace.history_panel()
        operation = window._operation_surface

        assert old_body is None
        assert old_right_rail is None
        assert body is not None
        assert tabs is not None
        assert upper is not None
        assert details is not None
        assert operation is not None
        assert tabs.parentWidget() is upper
        assert operation.parentWidget() is upper
        assert upper.layout().indexOf(tabs) == 0
        assert upper.layout().indexOf(operation) == 1
        assert upper.layout().stretch(0) == 3
        assert upper.layout().stretch(1) == 1
        assert details.parentWidget() is body
        assert inspector_panel.parentWidget() is details
        assert history_panel.parentWidget() is details
        assert details.layout().stretch(0) == 1
        assert details.layout().stretch(1) == 1
        assert body.layout().stretch(0) == 7
        assert body.layout().stretch(1) == 3
        assert window.findChild(
            QTableWidget, "data_manager.catalogs.table.inspector"
        ) is window._catalog_workspace.inspector
        assert window.findChild(
            QTableWidget, "data_manager.catalogs.table.history"
        ) is window._catalog_workspace.history
        assert len(
            window.findChildren(
                QTableWidget, "data_manager.catalogs.table.inspector"
            )
        ) == 1
        assert len(
            window.findChildren(
                QTableWidget, "data_manager.catalogs.table.history"
            )
        ) == 1
        assert details.isVisible()
        assert operation.isVisible()
        catalog_upper_height = upper.height()

        tabs.setCurrentIndex(1)
        QCoreApplication.processEvents()
        assert not details.isVisible()
        assert operation.isVisible()
        assert upper.height() >= catalog_upper_height

        tabs.setCurrentIndex(2)
        QCoreApplication.processEvents()
        assert not details.isVisible()
        assert operation.isVisible()

        tabs.setCurrentIndex(0)
        QCoreApplication.processEvents()
        assert details.isVisible()
        assert operation.isVisible()
    finally:
        window.close()


def test_data_manager_major_regions_resize_responsively(qapp) -> None:
    window = DataManagerSuiteWindow()
    window.show()
    QCoreApplication.processEvents()
    tabs = window._workspace_tabs
    catalog = window._catalog_workspace
    operation = window._operation_surface
    details = window._catalog_details_panel
    inspector = catalog.inspector_panel()
    history = catalog.history_panel()
    observed = {
        "catalog": set(),
        "operation": set(),
        "inspector": set(),
        "history": set(),
    }

    def verify_regions() -> None:
        widgets = (tabs, catalog, operation, details, inspector, history)
        for widget in widgets:
            assert widget is not None
            assert widget.isVisibleTo(window)
            assert widget.width() > 0
            assert widget.height() > 0
            origin = widget.mapTo(window, QPoint(0, 0))
            assert window.rect().intersects(QRect(origin, widget.size()))
        observed["catalog"].add((catalog.width(), catalog.height()))
        observed["operation"].add((operation.width(), operation.height()))
        observed["inspector"].add((inspector.width(), inspector.height()))
        observed["history"].add((history.width(), history.height()))

    try:
        for width, height in ((1280, 820), (1600, 900), (1024, 700)):
            window.showNormal()
            window.resize(width, height)
            QCoreApplication.processEvents()
            verify_regions()
        window.showMaximized()
        QCoreApplication.processEvents()
        verify_regions()

        assert all(len(sizes) > 1 for sizes in observed.values())
        for widget in (tabs, catalog, operation, details, inspector, history):
            assert widget.maximumWidth() > widget.minimumWidth()
            assert widget.maximumHeight() > widget.minimumHeight()
    finally:
        window.close()


def test_selector_instance_is_reused_and_closed_with_suite(qapp) -> None:
    window = DataManagerSuiteWindow()
    window_closed = False
    destroyed = []
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(),)))
        button = window.button_for_id("data_manager.button.select_dataset")
        button.click()
        QCoreApplication.processEvents()
        first = window.dataset_selector_dialog()
        assert first is not None and first.isVisible()
        first.reject()
        button.click()
        QCoreApplication.processEvents()
        assert window.dataset_selector_dialog() is first
        assert first.isVisible()
        window.close()
        window_closed = True
        assert not first.isVisible()
        QCoreApplication.processEvents()
    finally:
        if not window_closed:
            window.close()


def test_presentation_model_rejects_qt_runtime_objects(qapp) -> None:
    with pytest.raises(TypeError, match="source must be a string"):
        DataManagerDatasetEntry(MARKET, True, 1, 0, 0, source=QObject())


def test_artifact_creation_action_dialog_tracking_and_target_lifecycle(qapp) -> None:
    tracked = []
    destroyed = []
    window = DataManagerSuiteWindow(floating_window_tracker=lambda *args: tracked.append(args))
    forwarded = []
    window_closed = False
    try:
        workspace = window._catalog_workspace
        workspace.select_family("Artifacts")
        assert not workspace.create_artifact_button.isEnabled()
        window.set_market_snapshot(_snapshot())
        assert workspace.create_artifact_button.isEnabled()

        catalog = _direct_catalog()
        window.show_artifact_creation_dialog(catalog)
        QCoreApplication.processEvents()
        first = window.artifact_creation_dialog()
        assert first is not None and first.isVisible()
        first.destroyed.connect(lambda: destroyed.append(True))
        assert tracked[-1][1:] == (
            "data_manager.artifact_creation.window",
            "Create Artifact",
            "dialog",
        )
        window.show_artifact_creation_dialog(catalog)
        assert window.artifact_creation_dialog() is first
        assert len([item for item in tracked if item[1] == "data_manager.artifact_creation.window"]) == 1

        window.calculate_artifact_requested.connect(forwarded.append)
        sentinel = object()
        first.calculate_requested.emit(sentinel)
        assert forwarded == [sentinel]
        window.set_busy(True, "create_direct_artifact")
        assert not workspace.create_artifact_button.isEnabled()
        assert not first.calculate_button.isEnabled()
        window.set_busy(False)

        other = MarketId("bybit", "linear", "ETHUSDT", "1h")
        other_dataset = DataManagerDatasetEntry(other, True, 6, 1, 6)
        window.set_market_snapshot(
            DataManagerMarketSnapshot(other, other_dataset, (), ())
        )
        assert all(
            first.findChild(
                QLineEdit,
                f"data_manager.artifact_creation.dataset.{field}",
            ).text()
            == ""
            for field in ("exchange", "market_type", "asset", "timeframe")
        )
        assert not first.calculate_button.isEnabled()

        window.close()
        window_closed = True
        QCoreApplication.processEvents()
        assert destroyed == [True]
    finally:
        if not window_closed:
            window.close()


def test_construct_batch_dialog_is_single_tracked_and_closed_with_suite(qapp) -> None:
    tracked = []
    destroyed = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *args: tracked.append(args)
    )
    window_closed = False
    try:
        workspace = window._catalog_workspace
        workspace.select_family("Artifacts")
        window.set_market_snapshot(_snapshot())
        assert workspace.batch_constructs_button.isEnabled()

        catalog = _direct_catalog()
        window.show_construct_batch_dialog(catalog)
        QCoreApplication.processEvents()
        first = window.construct_batch_dialog()
        assert first is not None and first.isVisible()
        first.destroyed.connect(lambda: destroyed.append(True))
        assert tracked[-1][1:] == (
            "data_manager.construct_batch.window",
            "Batch Constructs",
            "dialog",
        )
        window.show_construct_batch_dialog(catalog)
        assert window.construct_batch_dialog() is first
        assert len(
            [item for item in tracked if item[1] == "data_manager.construct_batch.window"]
        ) == 1

        other = MarketId("bybit", "linear", "ETHUSDT", "1h")
        other_dataset = DataManagerDatasetEntry(other, True, 6, 1, 6)
        window.set_market_snapshot(
            DataManagerMarketSnapshot(other, other_dataset, (), ())
        )
        assert first.market_id is None
        assert not first.execute_button.isEnabled()

        window.close()
        window_closed = True
        QCoreApplication.processEvents()
        assert destroyed == [True]
    finally:
        if not window_closed:
            window.close()


def test_recipe_derivation_dialog_is_single_tracked_busy_and_closed_with_suite(
    qapp,
) -> None:
    tracked = []
    destroyed = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *args: tracked.append(args)
    )
    window_closed = False
    try:
        inspection = _environment_inspection()
        window.show_recipe_derivation_dialog(inspection)
        QCoreApplication.processEvents()
        first = window.recipe_derivation_dialog()
        assert first is not None and first.isVisible()
        first.destroyed.connect(lambda: destroyed.append(True))
        assert first.objectName() == "data_manager.recipe_derivation.window"
        assert first.windowTitle() == "Derive Recipes"
        assert tracked[-1][1:] == (
            "data_manager.recipe_derivation.window",
            "Derive Recipes",
            "dialog",
        )

        window.show_recipe_derivation_dialog(
            _environment_inspection("environment_2")
        )
        assert window.recipe_derivation_dialog() is first
        assert first.environment_id == "environment_2"
        assert len(
            [
                item
                for item in tracked
                if item[1] == "data_manager.recipe_derivation.window"
            ]
        ) == 1

        first.study_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        assert first.preview_button.isEnabled()
        window.set_busy(True, "plan_recipe_derivation")
        assert not first.preview_button.isEnabled()
        window.set_busy(False)
        assert first.preview_button.isEnabled()

        window.close()
        window_closed = True
        QCoreApplication.processEvents()
        assert destroyed == [True]
        assert window.recipe_derivation_dialog() is None
    finally:
        if not window_closed:
            window.close()


def test_collection_dialogs_are_single_tracked_busy_refreshed_and_suite_owned(
    qapp,
) -> None:
    tracked: list[tuple] = []
    window = DataManagerSuiteWindow(
        floating_window_tracker=lambda *args: tracked.append(args)
    )
    window_closed = False
    snapshot = associated_product_snapshot()
    try:
        window.set_product_catalogs(snapshot)
        window.show_recipe_collection_dialog(snapshot)
        recipe = window.recipe_collection_dialog()
        assert recipe is not None and recipe.isVisible()
        window.show_recipe_collection_dialog(snapshot)
        assert window.recipe_collection_dialog() is recipe

        window.show_artifact_collection_dialog(snapshot)
        artifact = window.artifact_collection_dialog()
        assert artifact is not None and artifact.isVisible()
        window.show_artifact_collection_dialog(snapshot)
        assert window.artifact_collection_dialog() is artifact

        assert [item[1:] for item in tracked[-2:]] == [
            (
                "data_manager.recipe_collection.window",
                "Recipe Collection",
                "dialog",
            ),
            (
                "data_manager.artifact_collection.window",
                "Artifact Collection",
                "dialog",
            ),
        ]

        window.set_busy(True, "collection management")
        assert not recipe.recipe_table.isEnabled()
        assert not artifact.artifact_table.isEnabled()
        window.set_busy(False)

        recipe.name_input.setText("Preserved")
        window.set_product_catalogs(snapshot)
        assert recipe.name_input.text() == "Preserved"
        assert recipe.reviewed_plan is None
        assert artifact.reviewed_plan is None

        recipe.close()
        artifact.close()
        QCoreApplication.processEvents()
        assert window.recipe_collection_dialog() is None
        assert window.artifact_collection_dialog() is None

        window.show_recipe_collection_dialog(snapshot)
        window.show_artifact_collection_dialog(snapshot)
        window.close()
        window_closed = True
        QCoreApplication.processEvents()
        assert window.recipe_collection_dialog() is None
        assert window.artifact_collection_dialog() is None
    finally:
        if not window_closed:
            window.close()


def test_collection_dialog_tracking_identity_survives_create_edit_create(qapp) -> None:
    registry = WindowRegistry()
    trackers: list[GuiWindowTracker] = []

    def track(window, window_id, title, window_type) -> None:
        trackers.append(
            GuiWindowTracker(
                window,
                window_id=window_id,
                title=title,
                window_type=window_type,
                registry=registry,
            )
        )

    snapshot = associated_product_snapshot()
    recipe_collection = snapshot.recipe_collections.collections[0]
    recipe_inspection = DataManagerRecipeCollectionInspection(
        recipe_collection,
        recipe_collection.member_recipe_ids,
        recipe_collection.member_recipe_ids,
        (),
        (recipe_collection.member_recipe_ids,),
    )
    artifact = snapshot.managed_artifacts.artifacts[0]
    artifact_member = ArtifactCollectionMemberV1(
        ManagedArtifactVersionKey(
            artifact.logical_artifact_id,
            artifact.artifact_id,
        ),
        artifact.portable_recipe_id,
        artifact.tool_key,
        artifact.kind,
        artifact.output_names,
        "3" * 64,
    )
    artifact_output = ArtifactCollectionOutputV1(
        artifact.logical_artifact_id,
        artifact.output_names[0],
        artifact.output_names[0],
    )
    artifact_source = snapshot.artifact_collections[1].source_ohlcv
    artifact_revision_id = deterministic_hash(
        {
            "schema_version": "1.0",
            "object_type": "artifact_collection_revision",
            "collection_id": "ac_44444444444444444444444444444444",
            "display_name": "Edit Collection",
            "description": "",
            "market_id": {
                "exchange": artifact.market_id.exchange,
                "market_type": artifact.market_id.market_type,
                "symbol": artifact.market_id.symbol,
                "timeframe": artifact.market_id.timeframe,
            },
            "root_logical_artifact_ids": [artifact.logical_artifact_id],
            "support_logical_artifact_ids": [],
            "members": [artifact_member.to_dict()],
            "dependency_edges": [],
            "selected_outputs": [artifact_output.to_dict()],
            "presentation_order": [artifact_output.column_name],
            "source_portable_recipe_ids": [artifact.portable_recipe_id],
            "source_recipe_collection_id": None,
            "source_recipe_collection_revision_id": None,
            "source_ohlcv": artifact_source.to_dict(),
            "first_timestamp_ms": artifact.first_timestamp_ms,
            "last_timestamp_ms": artifact.last_timestamp_ms,
            "validation_state": "valid",
            "database_ready": True,
            "previous_revision_id": None,
            "created_at_utc": artifact.created_at_utc.isoformat().replace(
                "+00:00", "Z"
            ),
            "revised_at_utc": artifact.created_at_utc.isoformat().replace(
                "+00:00", "Z"
            ),
        }
    )
    artifact_revision = ArtifactCollectionRevisionV1(
        "ac_44444444444444444444444444444444",
        artifact_revision_id,
        "Edit Collection",
        "",
        artifact.market_id,
        (artifact.logical_artifact_id,),
        (),
        (artifact_member,),
        (),
        (artifact_output,),
        (artifact_output.column_name,),
        (artifact.portable_recipe_id,),
        None,
        None,
        artifact_source,
        artifact.first_timestamp_ms,
        artifact.last_timestamp_ms,
        "valid",
        True,
        None,
        artifact.created_at_utc,
        artifact.created_at_utc,
    )
    window = DataManagerSuiteWindow(floating_window_tracker=track)
    try:
        window.show_recipe_collection_dialog(snapshot)
        dialog = window.recipe_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Create Recipe Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.recipe_collection_dialog() is None

        window.show_recipe_collection_dialog(snapshot, inspection=recipe_inspection)
        dialog = window.recipe_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Edit Recipe Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.recipe_collection_dialog() is None

        window.show_recipe_collection_dialog(snapshot)
        dialog = window.recipe_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Create Recipe Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.recipe_collection_dialog() is None

        window.show_artifact_collection_dialog(snapshot)
        dialog = window.artifact_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Create Artifact Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.artifact_collection_dialog() is None

        window.show_artifact_collection_dialog(snapshot, revision=artifact_revision)
        dialog = window.artifact_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Edit Artifact Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.artifact_collection_dialog() is None

        window.show_artifact_collection_dialog(snapshot)
        dialog = window.artifact_collection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Create Artifact Collection"
        dialog.close()
        QCoreApplication.processEvents()
        assert window.artifact_collection_dialog() is None

        collection_records = {
            item.window_id: item
            for item in registry.list_windows()
            if "collection.window" in item.window_id
        }
        assert {
            window_id: (item.title, item.window_type)
            for window_id, item in collection_records.items()
        } == {
            "data_manager.recipe_collection.window": (
                "Recipe Collection",
                "dialog",
            ),
            "data_manager.artifact_collection.window": (
                "Artifact Collection",
                "dialog",
            ),
        }
        assert not any(
            "collection.window" in item.window_id
            for item in registry.open_windows()
        )
    finally:
        window.close()


def test_collection_inspection_signal_proxy_reuse_mode_switch_and_lifecycle(
    qapp,
) -> None:
    from leonardo.data_manager import ArtifactCollectionValidation
    from tests.gui_test.test_data_manager_catalogs import associated_product_snapshot
    from tests.gui_test.test_data_manager_collection_inspection_dialog import (
        _artifact_metadata,
        _artifact_revision,
        ROOT_ARTIFACT_ID,
        ROOT_RECIPE_ID,
        SUPPORT_ARTIFACT_ID,
        SUPPORT_RECIPE_ID,
    )
    from tests.gui_test.test_data_manager_recipe_collection_dialog import (
        _inspection,
        _recipe,
        ROOT_ID,
        SUPPORT_ID,
    )

    window = DataManagerSuiteWindow()
    window_closed = False
    recipe_signals: list[object] = []
    artifact_signals: list[object] = []
    window.inspect_recipe_collection_requested.connect(recipe_signals.append)
    window.inspect_artifact_collection_requested.connect(artifact_signals.append)
    try:
        snapshot = associated_product_snapshot()
        window.set_product_catalogs(snapshot)
        workspace = window._catalog_workspace
        workspace.select_family("Recipe Collections")
        recipe_entry = workspace._visible_values[0]
        workspace.table.selectRow(0)
        workspace.inspect_collection_button.click()
        assert recipe_signals == [recipe_entry]

        workspace.dataset_scope.setCurrentIndex(
            workspace.dataset_scope.findData("all")
        )
        workspace.select_family("Artifact Collections")
        artifact_entry = workspace._visible_values[0]
        workspace.table.selectRow(0)
        workspace.inspect_collection_button.click()
        assert artifact_signals == [artifact_entry]

        inspection = _inspection()
        recipes = (_recipe(SUPPORT_ID, "sma"), _recipe(ROOT_ID, "ema"))
        window.show_recipe_collection_inspection(inspection, recipes)
        dialog = window.collection_inspection_dialog()
        assert dialog is not None
        assert dialog.windowTitle() == "Recipe Collection Inspection"

        revision = _artifact_revision()
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
        metadata = (
            _artifact_metadata(
                SUPPORT_ARTIFACT_ID, SUPPORT_RECIPE_ID, "sma"
            ),
            _artifact_metadata(ROOT_ARTIFACT_ID, ROOT_RECIPE_ID, "ema"),
        )
        window.show_artifact_collection_inspection(
            revision, validation, metadata
        )
        assert window.collection_inspection_dialog() is dialog
        assert dialog.windowTitle() == "Artifact Collection Inspection"

        dialog.close()
        qapp.processEvents()
        assert window.collection_inspection_dialog() is None

        window.show_recipe_collection_inspection(inspection, recipes)
        reopened = window.collection_inspection_dialog()
        assert reopened is not None and reopened is not dialog
        window.close()
        window_closed = True
        qapp.processEvents()
        assert window.collection_inspection_dialog() is None
    finally:
        if not window_closed:
            window.close()


def test_catalog_deletions_require_exact_confirmation_and_remain_distinct(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    del qapp
    window = DataManagerSuiteWindow()
    questions: list[tuple[str, str]] = []
    answer = [QMessageBox.StandardButton.No]

    def question(_parent, title, message):
        questions.append((title, message))
        return answer[0]

    monkeypatch.setattr(QMessageBox, "question", question)
    try:
        snapshot = associated_product_snapshot()
        window.set_product_catalogs(snapshot)
        workspace = window._catalog_workspace
        workspace.set_selected_market(MarketId("bybit", "linear", "ETHUSDT", "4h"))
        workspace.dataset_scope.setCurrentIndex(
            workspace.dataset_scope.findData("all")
        )
        window._sync_actions()
        cases = (
            (
                "Recipes", workspace.delete_recipe_button,
                window.catalog_delete_recipe_requested,
                "global Recipe", "Recipe ID",
            ),
            (
                "Recipe Collections", workspace.delete_recipe_collection_button,
                window.catalog_delete_recipe_collection_requested,
                "Member Recipes are not deleted", "Collection ID",
            ),
            (
                "Artifacts", workspace.delete_artifact_button,
                window.catalog_delete_artifact_requested,
                "complete managed Artifact", "Market:",
            ),
            (
                "Artifact Collections", workspace.delete_artifact_collection_button,
                window.catalog_delete_artifact_collection_requested,
                "Member Artifacts are not deleted", "Market:",
            ),
        )
        for family, button, signal, required_text, identity_text in cases:
            emitted: list[object] = []
            signal.connect(emitted.append)
            workspace.select_family(family)
            workspace.table.selectRow(0)
            selected = workspace._selected_value()
            button.click()
            assert emitted == []
            assert required_text in questions[-1][1]
            assert identity_text in questions[-1][1]
            if family == "Recipe Collections":
                assert "Member Recipes are not deleted" in questions[-1][1]
                assert (
                    "Artifact-domain objects are not deleted and do not block deletion."
                    in questions[-1][1]
                )
                assert (
                    "Deletion is refused if an Artifact Collection references it."
                    not in questions[-1][1]
                )
            answer[0] = QMessageBox.StandardButton.Yes
            button.click()
            assert emitted == [selected]
            answer[0] = QMessageBox.StandardButton.No

        legacy_artifact: list[bool] = []
        legacy_recipe: list[bool] = []
        window.delete_artifact_requested.connect(lambda: legacy_artifact.append(True))
        window.delete_recipe_requested.connect(lambda: legacy_recipe.append(True))
        assert legacy_artifact == []
        assert legacy_recipe == []

        window.set_busy(True, "deletion")
        assert all(not case[1].isEnabled() for case in cases)
    finally:
        window.close()


def test_duplicate_maintenance_context_action_maps_each_catalog_domain(qapp) -> None:
    del qapp
    window = DataManagerSuiteWindow()
    emitted: list[str] = []
    window.duplicate_maintenance_requested.connect(emitted.append)
    try:
        window.set_product_catalogs(associated_product_snapshot())
        button = window._buttons["data_manager.button.duplicate_maintenance"]
        for family, expected in (
            ("Recipes", "recipes"),
            ("Recipe Collections", "recipe_collections"),
            ("Artifacts", "artifacts"),
            ("Artifact Collections", "artifact_collections"),
        ):
            window._catalog_workspace.select_family(family)
            window._sync_actions()
            assert button.isEnabled()
            button.click()
            assert emitted[-1] == expected

        window._catalog_workspace.select_family("Databases")
        window._sync_actions()
        assert not button.isEnabled()
        assert emitted == [
            "recipes",
            "recipe_collections",
            "artifacts",
            "artifact_collections",
        ]
    finally:
        window.close()


def test_duplicate_maintenance_dialogs_are_suite_owned_reused_and_closed(qapp) -> None:
    tracked: list[tuple[str, object]] = []

    def track(dialog, window_id, _title, _window_type) -> None:
        tracked.append((window_id, dialog))

    window = DataManagerSuiteWindow(floating_window_tracker=track)
    recipes = DUPLICATE_MAINTENANCE_DOMAINS["recipes"]
    collections = DUPLICATE_MAINTENANCE_DOMAINS["recipe_collections"]
    first_preflight = DuplicateMaintenancePreflight(recipes, 25)
    second_preflight = DuplicateMaintenancePreflight(collections, 4)
    first_result = DuplicateMaintenanceScanResult(
        first_preflight,
        datetime(2026, 8, 20, tzinfo=UTC),
        25,
        (),
    )
    safe_group = DuplicateMaintenanceGroup(
        collections,
        "prc_11111111111111111111111111111111",
        (
            DuplicateMaintenanceCandidate(
                "prc_22222222222222222222222222222222",
                "SAFE",
                "younger equivalent",
            ),
        ),
        "Equivalent semantics",
    )
    second_result = DuplicateMaintenanceScanResult(
        second_preflight,
        datetime(2026, 8, 21, tzinfo=UTC),
        4,
        (safe_group,),
    )
    closed = False
    try:
        window.show_duplicate_maintenance_preflight(first_preflight)
        preflight_dialog = window.duplicate_maintenance_preflight_dialog()
        window.show_duplicate_maintenance_preflight(second_preflight)
        assert window.duplicate_maintenance_preflight_dialog() is preflight_dialog
        assert preflight_dialog.preflight is second_preflight

        window.show_duplicate_maintenance_results(first_result)
        results_dialog = window.duplicate_maintenance_results_dialog()
        window.show_duplicate_maintenance_results(second_result)
        assert window.duplicate_maintenance_results_dialog() is results_dialog
        assert results_dialog.result is second_result
        assert len(tracked) == 2

        window.close()
        closed = True
        qapp.processEvents()
        assert window.duplicate_maintenance_preflight_dialog() is None
        assert window.duplicate_maintenance_results_dialog() is None
    finally:
        if not closed:
            window.close()


def test_duplicate_purge_confirmation_is_explicit_and_result_invalidates_scan(
    qapp, monkeypatch: pytest.MonkeyPatch
) -> None:
    del qapp
    window = DataManagerSuiteWindow()
    domain = DUPLICATE_MAINTENANCE_DOMAINS["recipe_collections"]
    preflight = DuplicateMaintenancePreflight(domain, 2)
    candidate = DuplicateMaintenanceCandidate(
        "prc_22222222222222222222222222222222",
        "SAFE",
        "younger equivalent",
    )
    scan = DuplicateMaintenanceScanResult(
        preflight,
        datetime(2026, 8, 20, tzinfo=UTC),
        2,
        (
            DuplicateMaintenanceGroup(
                domain,
                "prc_11111111111111111111111111111111",
                (candidate,),
                "Equivalent semantics",
            ),
        ),
    )
    purge = DuplicateMaintenancePurgeResult(
        scan,
        datetime(2026, 8, 21, tzinfo=UTC),
        (
            DuplicateMaintenancePurgeDetail(
                domain,
                candidate.object_id,
                scan.groups[0].canonical_id,
                "PURGED",
                "deleted",
            ),
        ),
    )
    captured: list[tuple[str, str, tuple[str, ...]]] = []

    def execute(message_box: QMessageBox) -> int:
        buttons = tuple(button.text() for button in message_box.buttons())
        captured.append((message_box.windowTitle(), message_box.text(), buttons))
        next(button for button in message_box.buttons() if button.text() == "Execute Purge").click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", execute)
    try:
        assert window.confirm_duplicate_maintenance_purge(scan)
        assert captured[0][0] == "Duplicate Purge"
        assert "Safe duplicate objects selected:\n1" in captured[0][1]
        assert "No canonical winner will be deleted." in captured[0][1]
        assert set(captured[0][2]) == {"Execute Purge", "Cancel"}

        window.show_duplicate_maintenance_preflight(preflight)
        window.show_duplicate_maintenance_results(scan)
        old_result = window.duplicate_maintenance_results_dialog()
        window.show_duplicate_maintenance_purge_result(purge)
        assert window.duplicate_maintenance_preflight_dialog() is None
        result_dialog = window.duplicate_maintenance_results_dialog()
        assert result_dialog is not old_result
        assert result_dialog.result is purge
        assert result_dialog.windowTitle() == "Duplicate Maintenance Complete"
    finally:
        window.close()
