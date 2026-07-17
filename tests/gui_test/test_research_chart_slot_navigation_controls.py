from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

from leonardo.core.core_runner import TaskResult
from leonardo.data import MarketId
from leonardo.gui.widgets.research_chart_slot_widget import ResearchChartSlotWidget
from tests.gui_test.test_research_multi_chart_concurrency import (
    _controlled_suite,
    _open_pending,
)


def test_slot_navigation_controls_have_exact_ids_and_emit_intent_only() -> None:
    app = QApplication.instance() or QApplication([])
    widget = ResearchChartSlotWidget(4)
    positions: list[tuple[int, int]] = []
    go_to: list[int] = []
    detach: list[int] = []
    dock: list[int] = []
    activations: list[int] = []
    widget.position_change_requested.connect(lambda *args: positions.append(args))
    widget.go_to_requested.connect(go_to.append)
    widget.detach_requested.connect(detach.append)
    widget.dock_requested.connect(dock.append)
    widget.activated.connect(activations.append)
    try:
        prefix = "research.chart_slot.4"
        label = widget.findChild(QLabel, f"{prefix}.label.workspace_position")
        combo = widget.findChild(QComboBox, f"{prefix}.combo.workspace_position")
        go_button = widget.findChild(QPushButton, f"{prefix}.button.go_to")
        detach_button = widget.findChild(QPushButton, f"{prefix}.button.detach")
        assert label is not None and label.text() == "Chart 4"
        assert combo is not None and [combo.itemData(i) for i in range(8)] == list(range(1, 9))
        assert go_button is not None and not go_button.isEnabled()
        assert detach_button is not None and detach_button.text() == "Detach"
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)
        assert activations == [4]
        widget.set_workspace_position(2)
        assert positions == []
        combo.setCurrentIndex(6)
        assert positions == [(4, 7)]
        widget.set_dataset(MarketId("bybit", "linear", "BTCUSDT", "1m"))
        assert not go_button.isEnabled()
        widget.set_go_to_enabled(True)
        go_button.click()
        assert go_to == [4]
        detach_button.click()
        assert detach == [4]
        widget.set_detached(True)
        assert not combo.isEnabled() and detach_button.text() == "Dock"
        detach_button.click()
        assert dock == [4]
        widget.clear_chart_state()
        assert not go_button.isEnabled()
    finally:
        widget.close()
        app.processEvents()


def test_go_to_availability_follows_accepted_dataset_and_viewport_lifecycle(
    tmp_path,
) -> None:
    app = QApplication.instance() or QApplication([])
    window, presenter, data, _studies = _controlled_suite(tmp_path)
    try:
        slot_id, load_id = _open_pending(presenter, data)
        widget = window.workspace_widget.slot_widget(slot_id)
        go_button = widget.findChild(
            QPushButton, f"research.chart_slot.{slot_id}.button.go_to"
        )
        assert widget.market_id is not None
        assert not go_button.isEnabled()
        _kind, callback, _value = data.pending.pop(load_id)
        callback(TaskResult(load_id, "failed", error_message="load failed"))
        assert not go_button.isEnabled()

        presenter.set_active_slot(slot_id)
        presenter.chart_presenter(slot_id).open_dataset(widget.market_id)
        accepted_load = data.pending_ids("load")[-1]
        assert not go_button.isEnabled()
        data.complete(accepted_load)
        assert presenter.session_for(slot_id).dataset is not None
        assert presenter.viewport_for(slot_id) is not None
        assert go_button.isEnabled()
        resident_id = data.pending_ids("resident")[-1]
        _kind, resident_callback, _value = data.pending.pop(resident_id)
        resident_callback(
            TaskResult(resident_id, "failed", error_message="resident failed")
        )
        assert go_button.isEnabled()
    finally:
        presenter.dispose()
        window.close()
        app.processEvents()
