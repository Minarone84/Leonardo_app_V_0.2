from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QStyle, QStyleOptionComboBox

from leonardo.gui.research import ResearchWorkspaceWidget
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.widgets.research_workspace_layout import build_research_workspace_layout_in_order
from tests.gui_test.test_research_gui_visual_freeze_geometry import qapp, _fixtures, _panel
from tests.gui_test.test_research_composed_transition_guards import composed, _review_snapshot
from tests.gui_test.test_research_single_chart_integration import _open_restored_chart, _wait_until


@pytest.fixture(autouse=True)
def research_theme(qapp):
    previous = qapp.styleSheet()
    apply_theme_stylesheet(qapp, load_default_theme())
    try:
        yield
    finally:
        qapp.setStyleSheet(previous)


@pytest.mark.parametrize("count", range(9, 17))
def test_fit_pages_reuse_existing_adaptive_geometry_and_scroll(qapp, count):
    workspace = ResearchWorkspaceWidget()
    panels = tuple(_panel(_fixtures()[index % 8]) for index in range(count))
    for slot, panel in enumerate(panels, 1):
        workspace.add_chart(slot, panel)
    workspace.resize(1920, 1080)
    workspace.set_visualization_mode("fit_8")
    workspace.show()
    try:
        for _ in range(6):
            qapp.processEvents()
        viewport = workspace.scroll_area.viewport()
        bar = workspace.scroll_area.verticalScrollBar()
        assert bar.maximum() > 0
        assert workspace.scroll_area.horizontalScrollBar().maximum() == 0
        for page, (host, grid) in enumerate(workspace._fit_pages):
            slots = tuple(range(1, count + 1))[page * 8:(page + 1) * 8]
            expected = build_research_workspace_layout_in_order(slots, "fit_8")
            assert abs(host.height() - viewport.height()) <= 2
            for item in expected.items:
                panel = workspace.chart_panel_for_slot(item.slot_id)
                index = grid.indexOf(panel)
                assert grid.getItemPosition(index) == (
                    item.row, item.column, item.row_span, item.column_span)
                assert panel._workspace_density == ("compact" if expected.row_count >= 3 else "normal")
                assert host.rect().contains(panel.geometry())
                option = QStyleOptionComboBox()
                panel.position_combo.initStyleOption(option)
                edit_rect = panel.position_combo.style().subControlRect(
                    QStyle.ComplexControl.CC_ComboBox, option,
                    QStyle.SubControl.SC_ComboBoxEditField, panel.position_combo)
                assert edit_rect.width() >= panel.position_combo.fontMetrics().horizontalAdvance(str(item.slot_id))
        bar.setValue(0)
        qapp.processEvents()
        assert panels[0].mapTo(viewport, QPoint()).y() == 0
        bar.setValue(bar.maximum())
        qapp.processEvents()
        assert abs(panels[8].mapTo(viewport, QPoint()).y()) <= 2
        output = os.environ.get("LEO_SMOKE_SCREENSHOTS")
        if output and count in (9, 11, 13, 16):
            root = Path(output)
            root.mkdir(parents=True, exist_ok=True)
            assert workspace.grab().save(str(root / f"fit_{count}_page_2.png"))
            bar.setValue(0)
            qapp.processEvents()
            assert workspace.grab().save(str(root / f"fit_{count}_page_1.png"))
        workspace.set_visualization_mode("scroll_4")
        qapp.processEvents()
        assert workspace.layout_plan().row_count == (count + 1) // 2
        if count % 2:
            assert workspace.layout_plan().items[-1].column_span == 2
        assert all(workspace.chart_panel_for_slot(slot) is panel for slot, panel in enumerate(panels, 1))
    finally:
        workspace.clear_all_charts()
        workspace.close()
        qapp.processEvents()


def test_page_order_detach_dock_removal_and_resize_preserve_panels(qapp):
    workspace = ResearchWorkspaceWidget()
    panels = tuple(_panel(_fixtures()[index % 8]) for index in range(16))
    for slot, panel in enumerate(panels, 1):
        workspace.add_chart(slot, panel)
    workspace.resize(1920, 1080)
    workspace.set_visualization_mode("fit_8")
    workspace.show()
    try:
        workspace.move_chart(16, 1)
        assert workspace.attached_slot_ids()[0] == 16
        assert panels[15].workspace_position == 1
        workspace.detach_chart(16)
        assert workspace.detached_window(16).chart_panel is panels[15]
        assert panels[15]._workspace_density == "normal"
        workspace.dock_chart(16)
        assert workspace.attached_slot_ids()[0] == 16
        assert workspace.chart_panel_for_slot(16) is panels[15]
        workspace.resize(1800, 1100)
        for _ in range(4):
            qapp.processEvents()
        assert all(abs(host.height() - workspace.scroll_area.viewport().height()) <= 2
                   for host, _ in workspace._fit_pages)
        for slot in range(8, 16):
            workspace.remove_chart(slot).deleteLater()
        qapp.processEvents()
        assert workspace.chart_count() == 8
        assert workspace.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert all(not host.isVisible() for host, _ in workspace._fit_pages)
        workspace.resize(1800, 1000)
        for _ in range(4):
            qapp.processEvents()
        assert workspace.grid_host.minimumHeight() == workspace.scroll_area.viewport().height()
    finally:
        workspace.clear_all_charts()
        workspace.close()
        qapp.processEvents()


@pytest.mark.parametrize("mode", ["replace", "append"])
def test_sixteen_chart_snapshot_round_trip_and_append_overflow(composed, mode):
    _, app, _, _, window, presenter = composed
    count = 16 if mode == "replace" else 8
    for _ in range(count):
        _open_restored_chart(window, presenter)
    workspace = window.workspace
    workspace.set_visualization_mode("fit_8")
    workspace.set_active_slot(count)
    domain = app.research_workspace_snapshot_domain
    saved = domain.create_snapshot(domain.build_draft(
        presenter._capture_snapshot_workspace(), display_name="Sixteen charts"))
    snapshot = domain.load_snapshot(saved.snapshot_id)
    assert len(snapshot.charts) == count
    assert snapshot.workspace.visualization_mode == "fit_8"
    overflow = domain.preflight(snapshot, "append", {"occupied_positions": tuple(range(1, 18 - count)), "idle": True})
    assert not overflow.compatible
    assert any("capacity" in blocker for blocker in overflow.blockers)
    old_sessions = tuple(item.session for item in presenter._chart_presenters.values())
    dialog, _ = _review_snapshot(app, window, presenter, snapshot, mode)
    dialog.load_button.click()
    _wait_until(lambda: presenter._snapshot_restore is None, timeout=15)
    assert presenter._current_workspace_snapshot_id == snapshot.snapshot_id
    assert workspace.chart_count() == 16
    assert workspace.active_slot_id == 16
    assert workspace.visualization_mode == "fit_8"
    assert all(session.is_disposed == (mode == "replace") for session in old_sessions)
    assert len({item.session.session_id for item in presenter._chart_presenters.values()}) == 16
    presenter._open_go_to(16)
    assert 16 in presenter._go_to_dialogs
