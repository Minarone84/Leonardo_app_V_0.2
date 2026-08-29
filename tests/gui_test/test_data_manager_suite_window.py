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
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QWidget,
)

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
        if table.item(row, 2).text() == symbol:
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
        assert dialog.table_for_id("data_manager.table.datasets").columnCount() == 11
        dialog.table_for_id("data_manager.table.datasets").selectRow(
            _selector_row(window, "BTCUSDT")
        )
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
        table.selectRow(_selector_row(window, "XRPUSDT"))
        QCoreApplication.processEvents()
        assert window.selected_market_id() is None
        assert "source changed" in table.item(
            _selector_row(window, "XRPUSDT"), 10
        ).text()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
    finally:
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
