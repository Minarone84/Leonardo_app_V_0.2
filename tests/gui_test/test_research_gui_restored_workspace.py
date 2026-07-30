from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from leonardo.gui.research import (
    ResearchChartPanel,
    ResearchDetachedChartWindow,
    ResearchWorkspaceWidget,
)
from leonardo.gui.widgets.research_workspace_layout import (
    build_research_workspace_layout_in_order,
)
from leonardo.research import (
    ResearchWorkspaceShellState,
    ResearchWorkspaceShellStateError,
)
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


def _workspace_with_charts(
    qapp: QApplication, count: int
) -> tuple[ResearchWorkspaceWidget, tuple[ResearchChartPanel, ...]]:
    workspace = ResearchWorkspaceWidget()
    panels = tuple(_panel(fixture) for fixture in _fixtures()[:count])
    for slot_id, panel in enumerate(panels, start=1):
        workspace.add_chart(slot_id, panel)
    workspace.resize(1400, 900)
    workspace.show()
    qapp.processEvents()
    return workspace, panels


def _positions(workspace: ResearchWorkspaceWidget) -> dict[int, int]:
    return {
        placement.slot_id: placement.workspace_position
        for placement in workspace.shell_state.placements()
    }


def test_workspace_reuses_canonical_state_and_layout_authorities(
    qapp: QApplication,
) -> None:
    workspace = ResearchWorkspaceWidget()
    try:
        assert isinstance(workspace.shell_state, ResearchWorkspaceShellState)
        assert workspace.layout_plan() == build_research_workspace_layout_in_order(
            (), "scroll_4"
        )
        source = Path(
            "src/leonardo/gui/research/workspace_widget.py"
        ).read_text(encoding="utf-8")
        assert "build_research_workspace_layout_in_order(" in source
        assert "@dataclass" not in source
        assert "ChildAdded" not in source
        assert "findChildren" not in source
    finally:
        workspace.close()


def test_eight_charts_have_stable_slots_positions_and_first_active(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 8)
    try:
        assert workspace.chart_count() == 8
        assert workspace.slot_ids() == tuple(range(1, 9))
        assert workspace.attached_slot_ids() == tuple(range(1, 9))
        assert _positions(workspace) == {slot_id: slot_id for slot_id in range(1, 9)}
        assert [panel.position_combo.currentText() for panel in panels] == [
            str(slot_id) for slot_id in range(1, 9)
        ]
        assert workspace.active_slot_id == 1
        assert panels[0].property("active_chart") is True
        assert all(panel.property("active_chart") is False for panel in panels[1:])
        assert workspace.chart_panel is None
    finally:
        workspace.clear_all_charts()
        workspace.close()


@pytest.mark.parametrize("count", range(1, 9))
def test_workspace_geometry_matches_canonical_planner(
    qapp: QApplication, count: int
) -> None:
    workspace, _panels = _workspace_with_charts(qapp, count)
    try:
        plan = build_research_workspace_layout_in_order(
            tuple(range(1, count + 1)), "scroll_4"
        )
        assert workspace.layout_plan() == plan
        actual = []
        for item in plan.items:
            index = workspace._grid.indexOf(workspace.chart_panel_for_slot(item.slot_id))
            actual.append(workspace._grid.getItemPosition(index))
        assert actual == [
            (item.row, item.column, item.row_span, item.column_span)
            for item in plan.items
        ]
        if count in (3, 5, 7):
            spanning_index = 0 if count == 3 else count - 1
            assert plan.items[spanning_index].column_span == 2
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_scroll_and_fit_modes_preserve_panel_identity(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 8)
    try:
        identities = tuple(id(panel) for panel in panels)
        assert workspace.visualization_mode == "scroll_4"
        assert (
            workspace.scroll_area.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert (
            workspace.scroll_area.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        workspace.set_visualization_mode("fit_8")
        assert (
            workspace.scroll_area.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert tuple(id(workspace.chart_panel_for_slot(slot)) for slot in range(1, 9)) == identities
        workspace.set_visualization_mode("scroll_4")
        assert tuple(id(workspace.chart_panel_for_slot(slot)) for slot in range(1, 9)) == identities
        with pytest.raises(ValueError):
            workspace.set_visualization_mode("other")
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_move_swaps_then_compacts_and_synchronizes_controls(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 4)
    try:
        workspace.move_chart(4, 1)
        assert workspace.attached_slot_ids() == (4, 2, 3, 1)
        assert _positions(workspace) == {4: 1, 2: 2, 3: 3, 1: 4}
        assert [panel.workspace_position for panel in panels] == [4, 2, 3, 1]
        assert workspace.slot_ids() == (1, 2, 3, 4)
        removed = workspace.remove_chart(2)
        assert removed is panels[1]
        assert _positions(workspace) == {4: 1, 3: 2, 1: 3}
        assert panels[3].position_combo.currentText() == "1"
        assert panels[2].position_combo.currentText() == "2"
        assert panels[0].position_combo.currentText() == "3"
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_detach_reserves_position_and_dock_preserves_all_chart_state(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 4)
    panel = panels[1]
    identities = (
        id(panel),
        id(panel._interaction_state),
        id(panel.chart_workspace),
        id(panel.chart_workspace.price_chart),
        id(panel.chart_workspace.oscillator_widget("dev2-rsi")),
        id(panel.chart_workspace.oscillator_widget("dev2-volume")),
    )
    try:
        workspace.detach_chart(2)
        window = workspace.detached_window(2)
        assert isinstance(window, ResearchDetachedChartWindow)
        assert workspace.detached_slot_ids() == (2,)
        assert workspace.shell_state.placement_for(2).workspace_position == 2
        assert workspace._grid.indexOf(panel) == -1
        assert window.chart_panel is panel
        assert panel.parentWidget() is window
        assert panel.detach_button.text() == "Dock"
        assert panel.position_combo.currentText() == "2"
        workspace.set_active_slot(1)
        QTest.mouseClick(
            panel.chart_workspace.price_chart, Qt.MouseButton.LeftButton
        )
        assert workspace.active_slot_id == 2
        with pytest.raises(ResearchWorkspaceShellStateError):
            workspace.move_chart(4, 2)
        assert panels[3].position_combo.currentText() == "4"

        workspace.dock_chart(2)
        assert workspace.detached_window(2) is None
        assert workspace.detached_slot_ids() == ()
        assert workspace.chart_panel_for_slot(2) is panel
        assert panel.parentWidget() is workspace.grid_host
        assert panel.detach_button.text() == "Detach"
        assert (
            id(panel),
            id(panel._interaction_state),
            id(panel.chart_workspace),
            id(panel.chart_workspace.price_chart),
            id(panel.chart_workspace.oscillator_widget("dev2-rsi")),
            id(panel.chart_workspace.oscillator_widget("dev2-volume")),
        ) == identities
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_native_floating_close_docks_and_programmatic_close_does_not_emit(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 2)
    try:
        workspace.detach_chart(2)
        window = workspace.detached_window(2)
        assert window is not None
        dock_spy = QSignalSpy(window.dock_requested)
        window.close()
        qapp.processEvents()
        assert dock_spy.count() == 1
        assert workspace.detached_window(2) is None
        assert workspace.chart_panel_for_slot(2) is panels[1]

        independent_panel = _panel(build_primary_chart_fixture())
        independent = ResearchDetachedChartWindow(8, independent_panel)
        independent_spy = QSignalSpy(independent.dock_requested)
        independent.show()
        independent.request_programmatic_close()
        qapp.processEvents()
        assert independent_spy.count() == 0
        assert independent.chart_panel is independent_panel
        independent_panel.setParent(None)
        independent_panel.close()
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_close_attached_and_detached_compacts_and_selects_next_active(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 4)
    try:
        workspace.set_active_slot(2)
        panels[1].close_button.click()
        assert workspace.slot_ids() == (1, 3, 4)
        assert workspace.active_slot_id == 1
        assert _positions(workspace) == {1: 1, 3: 2, 4: 3}

        workspace.detach_chart(3)
        assert workspace.detached_window(3) is not None
        panels[2].close_button.click()
        assert workspace.detached_window(3) is None
        assert workspace.slot_ids() == (1, 4)
        assert _positions(workspace) == {1: 1, 4: 2}
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_explicit_activation_surfaces_and_local_intents_set_active_chart(
    qapp: QApplication,
) -> None:
    workspace, panels = _workspace_with_charts(qapp, 2)
    try:
        price = panels[1].chart_workspace.price_chart
        QTest.mouseClick(price, Qt.MouseButton.LeftButton)
        assert workspace.active_slot_id == 2
        assert panels[1].property("active_chart") is True
        assert panels[0].property("active_chart") is False

        workspace.set_active_slot(1)
        oscillator = panels[1].chart_workspace.oscillator_widget("dev2-rsi")
        assert oscillator is not None
        QTest.mouseClick(oscillator, Qt.MouseButton.LeftButton)
        assert workspace.active_slot_id == 2

        workspace.set_active_slot(1)
        panels[1].financial_tools_button.click()
        assert workspace.active_slot_id == 2
        surfaces = {
            surface
            for surface, slot_id in workspace._activation_slots.items()
            if slot_id == 2
        }
        assert surfaces == {
            panels[1],
            panels[1].chart_workspace.price_chart,
            panels[1].chart_workspace.oscillator_widget("dev2-rsi"),
            panels[1].chart_workspace.oscillator_widget("dev2-volume"),
        }
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_compatibility_api_and_all_detached_empty_states(
    qapp: QApplication,
) -> None:
    workspace = ResearchWorkspaceWidget()
    panel = _panel(build_primary_chart_fixture())
    try:
        workspace.show()
        workspace.show_single_chart(panel)
        qapp.processEvents()
        assert workspace.chart_panel is panel
        workspace.detach_chart(1)
        assert workspace.empty_state_label.text() == "All Research charts are detached"
        workspace.dock_chart(1)
        workspace.clear_chart()
        assert workspace.chart_panel is None
        assert workspace.active_slot_id is None
        assert workspace.empty_state_label.text() == (
            "No Research charts loaded.\nUse File \u2192 New Chart to load one."
        )
        assert workspace.empty_state_label.isVisible()
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_additional_dev_fixtures_are_exact_and_independent() -> None:
    primary = build_primary_chart_fixture()
    additional = build_additional_workspace_chart_fixtures()
    combined = (primary, *additional)
    assert len(additional) == 7
    assert [fixture.market_id.as_key() for fixture in combined] == [
        "bybit:linear:BTCUSDT:4h",
        "bybit:linear:ETHUSDT:1h",
        "binance:spot:BTCUSDT:15m",
        "binance:spot:ETHUSDT:1d",
        "bybit:linear:BTCUSDT:4h",
        "bybit:linear:ETHUSDT:1h",
        "binance:spot:BTCUSDT:15m",
        "binance:spot:ETHUSDT:1d",
    ]
    assert len({fixture.market_id for fixture in combined}) == 4
    assert len({id(fixture.interaction_state) for fixture in combined}) == 8
    assert len({id(fixture.interaction_state.viewport) for fixture in combined}) == 8
    assert len({id(fixture.interaction_state.resident) for fixture in combined}) == 8
    assert [item.study_id for item in primary.study_projections] == [
        "dev-sma",
        "dev-bb",
        "dev-rsi",
        "dev-volume",
    ]
    for slot_id, fixture in enumerate(additional, start=2):
        assert [item.study_id for item in fixture.study_projections] == [
            f"dev{slot_id}-sma",
            f"dev{slot_id}-bb",
            f"dev{slot_id}-rsi",
            f"dev{slot_id}-volume",
        ]


def test_dev_launcher_preserves_primary_path_and_bounded_composition() -> None:
    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    assert "build_primary_chart_fixture()" in source
    assert "window.workspace.show_single_chart(chart_panel)" in source
    assert "build_additional_workspace_chart_fixtures()" in source
    assert "window.workspace.add_chart(slot_id," in source
    assert source.count("ResearchChartPanel(") == 1
    assert 'action_for_text("Scroll 4")' in source
    assert 'set_visualization_mode("scroll_4")' in source
    assert 'action_for_text("Fit 8")' in source
    assert 'set_visualization_mode("fit_8")' in source
    for forbidden in (
        "LeonardoApp(",
        "GuiCompositionRoot(",
        "CoreRunner(",
        "OHLCVStore(",
        "ArtifactService(",
    ):
        assert forbidden not in source
