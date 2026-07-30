from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from leonardo.research import DatasetCatalogReport

from tests.gui_test.test_research_gui_service_catalog import _settle_qt
from tests.gui_test.test_research_gui_service_financial_tools import (
    open_financial_tools,
    open_ready_chart,
)
from tests.gui_test.test_research_gui_service_study_apply import _select_tool
from tests.gui_test.test_research_gui_service_study_save import (
    _complete_latest_setup,
    saving_presenter,
)


def test_studies_availability_manager_reuse_tracking_detach_and_slot_reuse(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    tracked: list[tuple[object, str, str, str, bool]] = []

    def tracker(widget, window_id, title, window_type):
        tracked.append((widget, window_id, title, window_type, widget.isVisible()))

    window, presenter, datasets, _studies, _setup, summary = saving_presenter(
        tmp_path, tracker
    )
    try:
        from tests.gui_test.test_research_gui_service_catalog import (
            _select_complete_summary,
        )

        datasets.complete(
            datasets.pending_ids("catalog")[0],
            value=DatasetCatalogReport((summary,), ()),
        )
        _settle_qt()
        presenter.open_new_chart()
        _select_complete_summary(presenter)
        presenter._new_chart_dialog.create_button.click()
        slot_id = presenter._workspace_state.active_slot_id
        panel = window.workspace.chart_panel_for_slot(slot_id)
        assert not panel.studies_button.isEnabled()
        datasets.complete(datasets.pending_ids("load")[-1])
        datasets.complete(datasets.pending_ids("resident")[-1])
        _settle_qt()
        assert panel.studies_button.isEnabled()

        panel.studies_button.click()
        _settle_qt()
        dialog = presenter._studies_manager_dialogs[slot_id]
        assert dialog.entries == ()
        assert tracked[-1] == (
            dialog,
            f"research_restoration.studies_manager.{slot_id}",
            "Studies",
            "dialog",
            False,
        )
        panel.studies_button.click()
        assert presenter._studies_manager_dialogs[slot_id] is dialog
        window.workspace.detach_chart(slot_id)
        window.workspace.dock_chart(slot_id)
        assert presenter._studies_manager_dialogs[slot_id] is dialog

        panel.close_button.click()
        assert slot_id not in presenter._studies_manager_dialogs
        reused = open_ready_chart(window, presenter, datasets, summary)
        assert reused == slot_id
        new_panel = window.workspace.chart_panel_for_slot(reused)
        new_panel.studies_button.click()
        assert presenter._studies_manager_dialogs[reused] is not dialog
    finally:
        presenter.dispose()
        window.close()


def test_manager_refresh_visibility_save_remove_and_busy_state(tmp_path: Path) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, studies, setup, summary = saving_presenter(tmp_path)
    try:
        slot_id = open_ready_chart(window, presenter, datasets, summary)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel.studies_button.click()
        manager = presenter._studies_manager_dialogs[slot_id]
        financial = open_financial_tools(window, presenter, setup, slot_id)
        _select_tool(financial, "SMA")
        financial.apply_button.click()
        assert not manager.manager_widget.isEnabled()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert len(manager.entries) == 1
        table = manager.manager_widget.table
        assert tuple(
            table.horizontalHeaderItem(column).text()
            for column in range(8)
        ) == (
            "Visible",
            "Study",
            "Tool",
            "Parameters",
            "Sources",
            "Origin",
            "Saved",
            "Pane",
        )
        assert tuple(table.item(0, column).text() for column in range(1, 8)) == (
            "SMA 14",
            "SMA",
            "period=14",
            "OHLCV: CLOSE",
            "Calculated",
            "No",
            "Price",
        )
        study_id = manager.entries[0].study_id
        assert manager.manager_widget.select_study(study_id)
        _complete_latest_setup(setup)
        assert manager.manager_widget.isEnabled()
        assert manager.manager_widget.selected_study_id() == study_id

        item = manager.manager_widget.table.item(0, 0)
        item.setCheckState(Qt.CheckState.Unchecked)
        _settle_qt()
        assert not presenter._workspace_state.session_for(slot_id).study_presentations()[0].visible
        assert manager.entries[0].study_id == study_id

        manager.manager_widget._save.click()
        assert studies.submissions[-1][0] == "save"
        assert not manager.manager_widget.isEnabled()
        studies.complete(next(reversed(studies.pending)))
        _settle_qt()
        assert manager.entries[0].saved
        assert manager.manager_widget.table.item(0, 5).text() == "Calculated"
        assert manager.manager_widget.table.item(0, 6).text() == "Yes"
        _complete_latest_setup(setup)
        assert manager.entries[0].study_id == study_id

        manager.manager_widget._remove.click()
        _settle_qt()
        assert manager.entries == ()
        assert presenter._workspace_state.session_for(slot_id).study_count == 0
        _complete_latest_setup(setup)
    finally:
        presenter.dispose()
        window.close()


def test_duplicate_markets_keep_managers_isolated_and_suite_disposal_closes_all(
    tmp_path: Path,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, datasets, _studies, _setup, summary = saving_presenter(tmp_path)
    try:
        first = open_ready_chart(window, presenter, datasets, summary)
        first_panel = window.workspace.chart_panel_for_slot(first)
        first_panel.studies_button.click()
        first_manager = presenter._studies_manager_dialogs[first]

        second = open_ready_chart(window, presenter, datasets, summary)
        second_panel = window.workspace.chart_panel_for_slot(second)
        second_panel.studies_button.click()
        second_manager = presenter._studies_manager_dialogs[second]
        assert first_manager is not second_manager

        presenter.dispose()
        assert presenter._studies_manager_dialogs == {}
        assert not first_manager.isVisible()
        assert not second_manager.isVisible()
    finally:
        presenter.dispose()
        window.close()
