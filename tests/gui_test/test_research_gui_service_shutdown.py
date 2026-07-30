from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

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
    _qapp = QApplication.instance() or QApplication([])
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

        sessions = tuple(
            presenter._workspace_state.session_for(slot_id)
            for slot_id in (loading_slot, resident_slot, ready_slot)
        )
        assert presenter._go_to_dialogs
        assert window.workspace.detached_slot_ids() == (ready_slot,)

        assert presenter.dispose() is True
        assert service.cancel_counts[load_id] == 1
        assert service.cancel_counts[resident_id] == 1
        assert all(session.is_disposed for session in sessions)
        assert presenter._chart_presenters == {}
        assert presenter._go_to_dialogs == {}
        assert window.workspace.slot_ids() == ()
        assert window.workspace.detached_slot_ids() == ()
        assert registry.open_windows() == ()
        assert not window.action_for_text("Pan Anchor").isEnabled()
        assert not window.action_for_text("Pan Anchor").isChecked()
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
