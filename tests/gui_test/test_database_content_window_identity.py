from __future__ import annotations

import csv
from dataclasses import replace
from io import StringIO

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QCheckBox
from shiboken6 import isValid

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.window_registry import WindowRegistry
from leonardo.gui.presenters.data_manager_presenter import DataManagerSuitePresenter
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.gui.windows.data_manager_database_content_dialog import (
    DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID,
    DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID,
)
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize
from tests.data_manager_test.test_seed_only_database_application import (
    _create_seed_only_database,
)
from tests.gui_test.test_data_manager_database_content_dialog import _context
from tests.gui_test.test_data_manager_database_content_vertical import (
    MARKET,
    _artifact_row,
    _select_database,
    _settle,
)


IDENTITIES = {
    "artifacts": (
        DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID,
        "Edit Database Artifacts",
    ),
    "collections": (
        DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID,
        "Edit Database Collections",
    ),
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Tracking:
    def __init__(self, registry: WindowRegistry) -> None:
        self.registry = registry
        self.trackers: dict[str, GuiWindowTracker] = {}
        self.created: list[GuiWindowTracker] = []

    def install(self, window, window_id, title, window_type) -> None:
        tracker = GuiWindowTracker(
            window,
            window_id=window_id,
            title=title,
            window_type=window_type,
            registry=self.registry,
        )
        self.trackers[window_id] = tracker
        self.created.append(tracker)

    def assert_state(self, mode: str, status: str) -> None:
        window_id, title = IDENTITIES[mode]
        entries = {entry.window_id: entry for entry in self.registry.list_windows()}
        entry = entries[window_id]
        assert entry.title == title
        assert entry.window_type == "window"
        assert entry.status == status
        assert (entry.closed_at_utc is not None) == (status == "closed")

    def assert_dialog(self, dialog, mode: str) -> None:
        window_id, title = IDENTITIES[mode]
        assert dialog.mode == mode
        assert dialog.property("object_id") == window_id
        assert dialog.windowTitle() == title
        assert dialog.objectName() == "data_manager_database_content_dialog"
        assert self.trackers[window_id].window_id == window_id
        assert self.trackers[window_id].parent() is dialog
        assert dialog.isVisible()
        self.assert_state(mode, "open")


def _dispose(window) -> None:
    if isValid(window):
        window.close()
        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.mark.parametrize("first_mode", ["artifacts", "collections"])
@pytest.mark.parametrize("close_between", [False, True])
def test_mode_identity_reuse_switch_reopen_and_parent_shutdown(
    qapp, tmp_path, first_mode, close_between
) -> None:
    assert DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID == (
        "data_manager.database_content.artifacts.window"
    )
    assert DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID == (
        "data_manager.database_content.collections.window"
    )
    assert DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID != DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID
    service, snapshot, database, *_ = _context(tmp_path)
    baseline = service.plan_database_content_edit(database.definition.database_id)
    tracking = _Tracking(WindowRegistry())
    window = DataManagerSuiteWindow(floating_window_tracker=tracking.install)
    second_mode = "collections" if first_mode == "artifacts" else "artifacts"

    def open_mode(mode):
        window.show_database_content_dialog(
            database, snapshot, mode=mode, baseline_plan=baseline
        )
        QCoreApplication.processEvents()
        dialog = window.database_content_dialog()
        assert dialog is not None
        tracking.assert_dialog(dialog, mode)
        return dialog

    try:
        window.show()
        first = open_mode(first_mode)
        first_tracker = tracking.created[0]
        closed = []
        first.closing.connect(lambda: closed.append(first_mode))
        assert open_mode(first_mode) is first
        assert first.baseline_plan is baseline
        assert tracking.created == [first_tracker]

        before_invalid = tracking.registry.list_windows()
        with pytest.raises(ValueError, match="mode must be artifacts or collections"):
            window.show_database_content_dialog(database, snapshot, mode="invalid")
        assert window.database_content_dialog() is first
        tracking.assert_dialog(first, first_mode)
        assert tracking.registry.list_windows() == before_invalid
        assert tracking.created == [first_tracker]
        assert closed == []

        if close_between:
            first.close()
            assert window.database_content_dialog() is None
            tracking.assert_state(first_mode, "closed")
        second = open_mode(second_mode)
        assert second is not first
        assert closed == [first_mode]
        assert not first.isVisible()
        assert first.property("object_id") == IDENTITIES[first_mode][0]
        assert first.windowTitle() == IDENTITIES[first_mode][1]
        tracking.assert_state(first_mode, "closed")
        assert len(tracking.created) == 2
        assert open_mode(second_mode) is second
        assert len(tracking.created) == 2
        assert len(tracking.registry.list_windows()) == 2

        second.close()
        tracking.assert_state(second_mode, "closed")
        reopened = open_mode(first_mode)
        assert reopened is not first and reopened is not second
        assert len(tracking.created) == 3
        assert len(tracking.registry.list_windows()) == 2
        tracking.assert_state(second_mode, "closed")
        assert open_mode(first_mode) is reopened
        assert len(tracking.created) == 3

        parent_closed = []
        reopened.closing.connect(lambda: parent_closed.append(True))
        window.close()
        assert window.database_content_dialog() is None
        assert parent_closed == [True]
        tracking.assert_state(first_mode, "closed")
        tracking.assert_state(second_mode, "closed")
        assert tracking.registry.open_windows() == ()
        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    finally:
        _dispose(window)


def test_real_presenter_artifact_then_collection_apply_with_tracking(qapp, tmp_path):
    _accepted_dataset(tmp_path / "historical_data", market=MARKET, rows=64)
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    app.start_core_runtime()
    window = None
    try:
        _seed, database = _create_seed_only_database(
            app.data_manager_service, "Tracked Content"
        )
        sma = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("sma", {"period": 1}),
        )
        ema = _materialize(
            app.data_manager_domain,
            app.data_manager_domain._portable_recipes,
            _leaf("ema", {"period": 1}),
        )
        collection = app.data_manager_domain.create_artifact_collection(
            ema, "Tracked Collection"
        )
        tracking = _Tracking(app.window_registry)
        window = DataManagerSuiteWindow(floating_window_tracker=tracking.install)
        presenter = DataManagerSuitePresenter(window, app.data_manager_service)
        window.show()
        presenter.refresh()
        _settle(presenter)
        _select_database(window)
        _settle(presenter)
        catalog = window._catalog_workspace
        catalog.edit_database_artifacts_button.click()
        _settle(presenter)
        artifact_dialog = window.database_content_dialog()
        tracking.assert_dialog(artifact_dialog, "artifacts")
        checkbox = artifact_dialog.source_table.cellWidget(
            _artifact_row(artifact_dialog, sma.root_logical_artifact_ids[0]), 0
        )
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        artifact_dialog.preview_button.click()
        _settle(presenter)
        artifact_plan = artifact_dialog.reviewed_plan
        assert artifact_plan is not None and not artifact_plan.blocked
        assert artifact_dialog.apply_button.isEnabled()
        artifact_dialog.apply_button.click()
        _settle(presenter)
        assert window.database_content_dialog() is None
        tracking.assert_state("artifacts", "closed")
        direct = app.data_manager_domain.load_database_revision(database.database_id)
        assert direct.manifest.revision_id != database.revision_id
        assert tuple(next(csv.reader(StringIO(direct.values_csv.decode("utf-8"))))) == (
            artifact_plan.column_names
        )
        assert direct.manifest.selected_outputs == artifact_plan.selected_outputs

        _select_database(window)
        _settle(presenter)
        catalog.edit_database_collections_button.click()
        _settle(presenter)
        collection_dialog = window.database_content_dialog()
        assert collection_dialog is not artifact_dialog
        tracking.assert_dialog(collection_dialog, "collections")
        tracking.assert_state("artifacts", "closed")
        row = next(
            index for index, value in enumerate(collection_dialog._source_values)
            if value.collection_id == collection.collection_id
            and value.revision_id == collection.revision_id
        )
        checkbox = collection_dialog.source_table.cellWidget(row, 0)
        assert isinstance(checkbox, QCheckBox)
        checkbox.setChecked(True)
        collection_dialog.preview_button.click()
        _settle(presenter)
        collection_plan = collection_dialog.reviewed_plan
        assert collection_plan is not None and not collection_plan.blocked
        assert collection_plan.collection_additions[0].revision_id == collection.revision_id
        assert collection_dialog.apply_button.isEnabled()
        collection_dialog.apply_button.click()
        _settle(presenter)
        assert window.database_content_dialog() is None
        tracking.assert_state("artifacts", "closed")
        tracking.assert_state("collections", "closed")
        assert len(tracking.created) == 2
        assert len(tracking.registry.list_windows()) == 2
        latest = app.data_manager_domain.load_database_revision(database.database_id)
        assert latest.manifest.revision_id != direct.manifest.revision_id
        latest_columns = tuple(next(csv.reader(StringIO(latest.values_csv.decode("utf-8")))))
        assert latest_columns == collection_plan.column_names
        assert latest.manifest.selected_outputs == collection_plan.selected_outputs
        assert latest.manifest.row_count == collection_plan.row_count
        assert set(artifact_plan.column_names) <= set(latest_columns)
        assert latest.manifest.collection_sources[-1].collection_id == collection.collection_id
        assert latest.manifest.collection_sources[-1].revision_id == collection.revision_id
        assert catalog.history.rowCount() == 3
    finally:
        if window is not None:
            _dispose(window)
        app.shutdown()
