from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QToolButton

from leonardo.gui.research import ResearchChartPanel, ResearchWorkspaceWidget
from tools.research_gui_dev_fixtures import (
    ResearchGuiDevChartFixture,
    build_additional_workspace_chart_fixtures,
    build_primary_chart_fixture,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _fixtures() -> tuple[ResearchGuiDevChartFixture, ...]:
    return (
        build_primary_chart_fixture(),
        *build_additional_workspace_chart_fixtures(),
    )


def _panel(fixture: ResearchGuiDevChartFixture) -> ResearchChartPanel:
    return ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )


def _shown_workspace(
    qapp: QApplication,
    count: int,
) -> tuple[QMainWindow, ResearchWorkspaceWidget, tuple[ResearchChartPanel, ...]]:
    window = QMainWindow()
    workspace = ResearchWorkspaceWidget(window)
    panels = tuple(_panel(fixture) for fixture in _fixtures()[:count])
    for slot_id, panel in enumerate(panels, start=1):
        workspace.add_chart(slot_id, panel)
    window.setCentralWidget(workspace)
    window.resize(1920, 1080)
    window.show()
    for _ in range(6):
        qapp.processEvents()
    return window, workspace, panels


def _close_workspace(
    qapp: QApplication,
    window: QMainWindow,
    workspace: ResearchWorkspaceWidget,
) -> None:
    workspace.clear_all_charts()
    window.close()
    qapp.processEvents()


def _assert_horizontal_containment(workspace: ResearchWorkspaceWidget) -> None:
    assert (
        workspace.grid_host.width()
        <= workspace.scroll_area.viewport().width() + 1
    )
    contents = workspace.grid_host.contentsRect()
    for slot_id in workspace.attached_slot_ids():
        geometry = workspace.chart_panel_for_slot(slot_id).geometry()
        assert geometry.left() >= contents.left()
        assert geometry.right() <= contents.right() + 1


def _assert_control_bar_containment(panel: ResearchChartPanel) -> None:
    controls = (
        panel.dataset_label,
        panel.position_label,
        panel.position_combo,
        panel.go_to_button,
        panel.financial_tools_button,
        panel.studies_button,
        panel.detach_button,
        panel.close_button,
        panel.autoscale_button,
    )
    contents = panel.control_bar.contentsRect()
    previous_right = contents.left() - 1
    for control in controls:
        geometry = control.geometry()
        assert geometry.left() >= contents.left()
        assert geometry.right() <= contents.right() + 1
        assert geometry.left() > previous_right
        previous_right = geometry.right()


def _oscillator_widgets(
    panel: ResearchChartPanel,
) -> tuple[object, ...]:
    widgets = []
    for pane_id in panel.chart_workspace.study_pane_ids():
        if not pane_id.startswith("oscillator:"):
            continue
        widget = panel.chart_workspace.oscillator_widget(
            pane_id.removeprefix("oscillator:")
        )
        assert widget is not None
        widgets.append(widget)
    return tuple(widgets)


def test_eight_chart_scroll_and_fit_geometry(
    qapp: QApplication,
) -> None:
    window, workspace, panels = _shown_workspace(qapp, 8)
    try:
        assert (
            workspace.scroll_area.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        _assert_horizontal_containment(workspace)
        for panel in (panels[0], panels[1]):
            _assert_control_bar_containment(panel)

        workspace.set_visualization_mode("fit_8")
        for _ in range(6):
            qapp.processEvents()
        _assert_horizontal_containment(workspace)
        for panel in (panels[0], panels[1]):
            _assert_control_bar_containment(panel)
        for fixture, panel in zip(_fixtures(), panels, strict=True):
            assert panel._workspace_density == "compact"
            assert panel.chart_workspace.price_chart.isVisible()
            assert panel.chart_workspace.price_chart.height() >= 80
            oscillators = _oscillator_widgets(panel)
            assert len(oscillators) == 2
            assert all(widget.isVisible() and widget.height() >= 48 for widget in oscillators)
            expected_ids = {
                entry.study_id
                for entry in fixture.study_entries
                if entry.display_name in {"RSI 14", "Volume"}
            }
            assert expected_ids == {
                pane_id.removeprefix("oscillator:")
                for pane_id in panel.chart_workspace.study_pane_ids()
                if pane_id.startswith("oscillator:")
            }

        workspace.set_visualization_mode("scroll_4")
        for _ in range(6):
            qapp.processEvents()
        _assert_horizontal_containment(workspace)
        for panel in panels:
            assert panel._workspace_density == "normal"
            assert panel.chart_workspace.price_chart.minimumHeight() == 220
            assert all(
                widget.minimumHeight() == 100
                for widget in _oscillator_widgets(panel)
            )
    finally:
        _close_workspace(qapp, window, workspace)


@pytest.mark.parametrize("count", range(1, 9))
def test_fit_density_uses_canonical_row_threshold(
    qapp: QApplication,
    count: int,
) -> None:
    window, workspace, panels = _shown_workspace(qapp, count)
    try:
        workspace.set_visualization_mode("fit_8")
        for _ in range(4):
            qapp.processEvents()
        plan = workspace.layout_plan()
        expected = "compact" if plan.row_count >= 3 else "normal"
        assert expected == ("compact" if count >= 5 else "normal")
        assert all(panel._workspace_density == expected for panel in panels)
    finally:
        _close_workspace(qapp, window, workspace)


def test_density_validation_and_dataset_tooltip() -> None:
    fixture = build_primary_chart_fixture()
    panel = _panel(fixture)
    try:
        assert panel._workspace_density == "normal"
        assert panel.dataset_label.toolTip() == panel.dataset_label.text()
        with pytest.raises(ValueError, match="density"):
            panel.set_workspace_density("other")
    finally:
        panel.close()


def test_fit_detach_and_dock_preserve_panel_identity_and_density(
    qapp: QApplication,
) -> None:
    window, workspace, panels = _shown_workspace(qapp, 8)
    panel = panels[1]
    identity = id(panel)
    try:
        workspace.set_visualization_mode("fit_8")
        for _ in range(4):
            qapp.processEvents()
        assert panel._workspace_density == "compact"

        workspace.detach_chart(2)
        qapp.processEvents()
        detached = workspace.detached_window(2)
        assert detached is not None
        assert id(detached.chart_panel) == identity
        assert panel._workspace_density == "normal"
        assert panel.chart_workspace.price_chart.minimumHeight() == 220
        assert all(
            widget.minimumHeight() == 100 for widget in _oscillator_widgets(panel)
        )

        workspace.dock_chart(2)
        for _ in range(4):
            qapp.processEvents()
        assert id(workspace.chart_panel_for_slot(2)) == identity
        assert panel._workspace_density == "compact"
        assert panel.chart_workspace.price_chart.minimumHeight() == 80
        assert all(
            widget.minimumHeight() == 48 for widget in _oscillator_widgets(panel)
        )
    finally:
        _close_workspace(qapp, window, workspace)


def test_overlay_buttons_are_transparent_in_every_scoped_state() -> None:
    panel = _panel(build_primary_chart_fixture())
    try:
        overlays = (panel.price_overlay, *panel.oscillator_overlays)
        buttons = tuple(
            button
            for overlay in overlays
            for button in overlay.findChildren(QToolButton)
        )
        assert buttons
        assert all(
            button.property("research_overlay_button") is True
            for button in buttons
        )
        oscillator = panel.oscillator_overlays[0]
        for button in (
            oscillator.values_button,
            oscillator.style_button,
            oscillator.edit_button,
            oscillator.remove_button,
            oscillator.move_up_button,
            oscillator.move_down_button,
            oscillator.retract_button,
        ):
            assert button.property("research_overlay_button") is True

        stylesheet = oscillator.styleSheet()
        assert 'QToolButton[research_overlay_button="true"] {' in stylesheet
        assert 'QToolButton[research_overlay_button="true"]:hover {' in stylesheet
        assert 'QToolButton[research_overlay_button="true"]:pressed,' in stylesheet
        assert 'QToolButton[research_overlay_button="true"]:checked,' in stylesheet
        assert 'QToolButton[research_overlay_button="true"]:disabled,' in stylesheet
        assert 'QToolButton[research_overlay_button="true"]:focus {' in stylesheet
        assert stylesheet.count("background: transparent;") >= 4
        assert "border: 1px solid rgba(148, 163, 184, 160);" in stylesheet

        oscillator.enterEvent(QEvent(QEvent.Type.Enter))
        assert oscillator.background_state == "inside"
        assert "background-color: rgba(0, 0, 0, 128);" in stylesheet
        oscillator.leaveEvent(QEvent(QEvent.Type.Leave))
        assert oscillator.background_state == "outside"
    finally:
        panel.close()
