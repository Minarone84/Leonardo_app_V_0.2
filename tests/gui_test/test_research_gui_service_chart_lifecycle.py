from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.gui.research import ResearchChartPanel
from leonardo.research import DatasetCatalogReport
from tests.gui_test.test_research_gui_service_catalog import (
    _complete_catalog,
    _presenter,
    _select_complete_summary,
    _settle_qt,
)
from tools.research_gui_dev_fixtures import build_primary_chart_fixture


def _open_pending(presenter, service) -> tuple[int, str]:
    presenter.open_new_chart()
    _select_complete_summary(presenter)
    presenter._new_chart_dialog.create_button.click()
    _settle_qt()
    slot_id = presenter._workspace_state.active_slot_id
    assert slot_id is not None
    return slot_id, service.pending_ids("load")[-1]


def _open_catalog(presenter, service, summary) -> None:
    _complete_catalog(service, DatasetCatalogReport((summary,), ()))


def test_real_chart_loads_dataset_and_initial_resident_into_one_session() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        slot_id, load_id = _open_pending(presenter, service)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        session = presenter._workspace_state.session_for(slot_id)
        assert presenter._workspace_state.chart_count == 1
        assert panel.position_combo.isEnabled()
        assert panel.detach_button.isEnabled()
        assert not panel.go_to_button.isEnabled()

        service.complete(load_id)
        resident_id = service.pending_ids("resident")[0]
        service.complete(resident_id)
        window.show()
        _settle_qt()

        assert session.dataset is service.dataset
        assert session.resident is not None
        assert panel.status_text == "Chart ready"
        assert panel.chart_widget.interaction_state is not None
        assert panel.price_overlay is not None
        assert panel.price_overlay.isVisible()
        assert not panel.price_overlay.isHidden()
        assert panel.price_overlay.parentWidget() is panel.chart_workspace.price_chart
        assert panel.price_overlay.parentWidget().rect().contains(
            panel.price_overlay.pos()
        )
        assert panel.price_overlay.study_rows == ()
        assert panel.chart_workspace.volume_visible is False
        assert panel.chart_workspace.volume_chart.isHidden()
        assert panel.go_to_button.isEnabled()
        assert panel.position_combo.isEnabled()
        assert panel.detach_button.isEnabled()
        assert not panel.financial_tools_button.isEnabled()
        assert panel.studies_button.isEnabled()
        assert panel.autoscale_button.isVisible() is False or (
            panel.autoscale_button.text() == "Autoscale"
        )
    finally:
        presenter.dispose()
        window.close()


def test_duplicate_charts_have_independent_sessions_viewports_and_task_ids() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        first, first_load = _open_pending(presenter, service)
        second, second_load = _open_pending(presenter, service)
        assert (first, second) == (1, 2)
        assert first_load != second_load
        assert presenter._workspace_state.session_for(first) is not (
            presenter._workspace_state.session_for(second)
        )

        service.complete(first_load)
        first_resident = service.pending_ids("resident")[0]
        service.complete(second_load)
        resident_ids = service.pending_ids("resident")
        second_resident = next(item for item in resident_ids if item != first_resident)
        service.complete(first_resident)
        service.complete(second_resident)
        _settle_qt()

        first_presenter = presenter._chart_presenters[first]
        second_presenter = presenter._chart_presenters[second]
        assert first_presenter.session.selected_market_id == summary.market_id
        assert second_presenter.session.selected_market_id == summary.market_id
        assert first_presenter.viewport is not second_presenter.viewport
        assert first_presenter.interaction is not second_presenter.interaction
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("status", ("failed", "cancelled"))
def test_asynchronous_full_load_terminal_result_leaves_no_ghost(status: str) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        _slot_id, load_id = _open_pending(presenter, service)
        service.complete(load_id, status=status, error_message="load stopped")
        _settle_qt()
        assert window.workspace.slot_ids() == ()
        assert presenter._workspace_state.slot_ids() == ()
        assert presenter._chart_presenters == {}
    finally:
        presenter.dispose()
        window.close()


def test_close_during_full_load_cancels_and_late_result_cannot_mutate_reused_slot() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        slot_id, old_load = _open_pending(presenter, service)
        old_session = presenter._workspace_state.session_for(slot_id)
        window.workspace.chart_panel_for_slot(slot_id).close_button.click()
        assert service.cancel_counts[old_load] == 1
        assert old_session.is_disposed
        assert window.workspace.slot_ids() == ()

        reused, new_load = _open_pending(presenter, service)
        new_session = presenter._workspace_state.session_for(reused)
        assert reused == slot_id
        assert new_session.session_id != old_session.session_id
        service.replay(old_load)
        _settle_qt()
        assert new_session.dataset is None
        assert service.pending_ids("load")[-1] == new_load
    finally:
        presenter.dispose()
        window.close()


def test_close_during_resident_load_cancels_and_late_result_is_stale_safe() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        slot_id, load_id = _open_pending(presenter, service)
        service.complete(load_id)
        resident_id = service.pending_ids("resident")[0]
        old_session = presenter._workspace_state.session_for(slot_id)
        window.workspace.chart_panel_for_slot(slot_id).close_button.click()
        assert service.cancel_counts[resident_id] == 1
        assert old_session.is_disposed

        reused, _new_load = _open_pending(presenter, service)
        new_session = presenter._workspace_state.session_for(reused)
        service.replay(resident_id)
        _settle_qt()
        assert new_session.resident is None
        assert window.workspace.slot_ids() == (slot_id,)
    finally:
        presenter.dispose()
        window.close()


def test_resident_failure_removes_chart_and_presenter_disposal_is_idempotent() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _open_catalog(presenter, service, summary)
        _slot_id, load_id = _open_pending(presenter, service)
        service.complete(load_id)
        resident_id = service.pending_ids("resident")[0]
        service.complete(
            resident_id, status="failed", error_message="resident failed"
        )
        _settle_qt()
        assert window.workspace.slot_ids() == ()
        assert presenter._workspace_state.slot_ids() == ()
        assert presenter.dispose() is True
        assert presenter.dispose() is False
    finally:
        presenter.dispose()
        window.close()


def test_fixture_chart_construction_retains_immediate_overlays() -> None:
    _qapp = QApplication.instance() or QApplication([])
    fixture = build_primary_chart_fixture()
    panel = ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )
    try:
        assert panel.slot_id == 1
        assert panel.price_overlay is not None
        assert panel.oscillator_overlays
        assert panel.position_combo.isEnabled()
        assert panel.detach_button.isEnabled()
        assert panel.financial_tools_button.isEnabled()
        assert panel.studies_button.isEnabled()
    finally:
        panel.close()
