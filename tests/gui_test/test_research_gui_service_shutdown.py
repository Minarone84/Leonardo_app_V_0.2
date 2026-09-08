from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from leonardo.core.window_registry import WindowRegistry
from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
from leonardo.gui.window_tracking import GuiWindowTracker
from leonardo.research import DatasetCatalogReport
from tests.gui_test.test_research_gui_service_catalog import (
    _ControlledDatasetService,
    _ControlledStudyService,
    _complete_catalog,
    _dataset_bundle,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_chart_lifecycle import _open_pending


class _CloseEventCounter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Close:
            self.count += 1
        return super().eventFilter(watched, event)


def _tracked_presenter():
    dataset, summary = _dataset_bundle()
    service = _ControlledDatasetService(dataset)
    registry = WindowRegistry()
    window = ResearchSuiteWindow()

    def tracker(widget, window_id, title, window_type) -> None:
        GuiWindowTracker(
            widget,
            window_id=window_id,
            title=title,
            window_type=window_type,
            registry=registry,
        )

    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService(), tracker
    )
    return window, presenter, service, summary, registry


def _ready_chart(presenter, service) -> int:
    slot_id, load_id = _open_pending(presenter, service)
    service.complete(load_id)
    service.complete(service.pending_ids("resident")[-1])
    _settle_qt()
    return slot_id


def test_dispose_with_catalog_active_cancels_once_and_is_idempotent() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, _summary, registry = _tracked_presenter()
    catalog_id = service.pending_ids("catalog")[0]
    presenter.open_new_chart()
    assert registry.open_windows()
    assert presenter.dispose() is True
    assert presenter.dispose() is False
    assert service.cancel_counts[catalog_id] == 1
    assert presenter._active_catalog_task_id is None
    assert presenter._chart_presenters == {}
    assert presenter._go_to_dialogs == {}
    assert window.workspace.slot_ids() == ()
    assert registry.open_windows() == ()
    window.close()


def test_dispose_cancels_full_load_resident_refill_and_clears_every_runtime() -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary, registry = _tracked_presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))

        loading_slot, load_id = _open_pending(presenter, service)
        resident_slot, resident_load = _open_pending(presenter, service)
        service.complete(resident_load)
        resident_id = service.pending_ids("resident")[-1]

        ready_slot, ready_load = _open_pending(presenter, service)
        service.complete(ready_load)
        ready_resident = service.pending_ids("resident")[-1]
        service.complete(ready_resident)
        _settle_qt()
        ready_panel = window.workspace.chart_panel_for_slot(ready_slot)
        ready_panel.go_to_button.click()
        ready_panel.detach_button.click()
        _settle_qt()
        go_to = presenter._go_to_dialogs[ready_slot]
        close_counter = _CloseEventCounter()
        go_to.installEventFilter(close_counter)

        sessions = tuple(
            presenter._workspace_state.session_for(slot_id)
            for slot_id in (loading_slot, resident_slot, ready_slot)
        )
        assert presenter._go_to_dialogs
        assert window.workspace.detached_slot_ids() == (ready_slot,)

        assert presenter.dispose() is True
        qapp.processEvents()
        assert service.cancel_counts[load_id] == 1
        assert service.cancel_counts[resident_id] == 1
        assert close_counter.count == 1
        assert not go_to.isVisible()
        assert all(session.is_disposed for session in sessions)
        assert presenter._chart_presenters == {}
        assert presenter._go_to_dialogs == {}
        assert window.workspace.slot_ids() == ()
        assert window.workspace.detached_slot_ids() == ()
        assert registry.open_windows() == ()
        assert not window.action_for_text("Pan Anchor").isEnabled()
        assert not window.action_for_text("Pan Anchor").isChecked()
        service.complete(load_id)
        qapp.processEvents()
        assert presenter._chart_presenters == {}
        assert window.workspace.slot_ids() == ()
        assert presenter.dispose() is False
    finally:
        presenter.dispose()
        window.close()


def test_suite_close_orders_presenter_disposal_without_event_drain_workaround() -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary, registry = _tracked_presenter()
    _complete_catalog(service, DatasetCatalogReport((summary,), ()))
    slot_id, load_id = _open_pending(presenter, service)
    session = presenter._workspace_state.session_for(slot_id)
    window.show()
    window.close()
    assert presenter._disposed
    assert session.is_disposed
    assert service.cancel_counts[load_id] == 1
    assert window.workspace.slot_ids() == ()
    assert registry.open_windows() == ()

    lifecycle_source = Path(
        "src/leonardo/gui/research/lifecycle_presenter.py"
    ).read_text(encoding="utf-8")
    launcher_source = Path(
        "tools/dev_launch_research_gui_service_wiring.py"
    ).read_text(encoding="utf-8")
    assert "processEvents" not in lifecycle_source
    assert "processEvents" not in launcher_source
    qapp.processEvents()


def test_clear_research_suite_confirms_resets_and_remains_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary, _registry = _tracked_presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id, load_id = _open_pending(presenter, service)
        assert not window.action_for_text("Clear Research Suite").isEnabled()
        service.complete(load_id)
        service.complete(service.pending_ids("resident")[-1])
        _settle_qt()
        assert window.action_for_text("Clear Research Suite").isEnabled()
        window.workspace.detach_chart(slot_id)
        window.action_for_text("Pan Anchor").trigger()
        window.action_for_text("Fit 8").trigger()
        presenter._current_workspace_snapshot_id = "snapshot_current"
        presenter._assigned_notebook_id = "notebook_current"
        action = window.action_for_text("Clear Research Suite")
        quick = window.quick_button_for_action("Clear Research Suite")
        assert action.objectName() == "research_restoration.action.clear_research_suite"
        assert quick.objectName() == "research_restoration.quick.clear_research_suite"
        assert quick.defaultAction() is action

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
        )
        action.trigger()
        assert window.workspace.slot_ids() == (slot_id,)
        assert window.workspace.detached_slot_ids() == (slot_id,)

        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        class _DirtyNotebook:
            is_dirty = True

            @staticmethod
            def dirty_decision():
                return "cancel"

        presenter._notebook_editor = _DirtyNotebook()
        action.trigger()
        assert window.workspace.slot_ids() == (slot_id,)
        presenter._notebook_editor = None
        action.trigger()
        qapp.processEvents()
        assert window.workspace.slot_ids() == ()
        assert window.workspace.detached_slot_ids() == ()
        assert presenter._chart_presenters == {}
        assert not presenter._disposed
        assert presenter._current_workspace_snapshot_id is None
        assert presenter._assigned_notebook_id is None
        assert not window.action_for_text("Pan Anchor").isChecked()
        assert "#FCA5A5" in window.quick_button_for_action("Pan Anchor").styleSheet()
        assert window.action_for_text("Scroll 4").isChecked()
        assert window.workspace.visualization_mode == "scroll_4"
        assert window.findChild(
            object, "research_restoration.activity.log"
        ).toPlainText() == "Research Suite cleared."
        assert window.dataset_summaries == (summary,)

        window.action_for_text("New Chart...").trigger()
        assert presenter._new_chart_dialog.isVisible()
    finally:
        presenter.dispose()
        window.close()
        qapp.processEvents()
