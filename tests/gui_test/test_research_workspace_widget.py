from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from leonardo.gui.widgets.research_workspace_widget import ResearchWorkspaceWidget


EXPECTED_WIDGET_EXPORTS = (
    "DEFAULT_SUITE_NAVIGATION_SEGMENTS",
    "SuiteNavigationDonut",
    "SuiteNavigationDonutGeometry",
    "SuiteNavigationSegment",
    "calculate_suite_navigation_donut_geometry",
    "StudyManagerWidget",
    "ResearchChartSlotWidget",
    "ResearchWorkspaceWidget",
)


def test_workspace_empty_add_remove_active_capacity_and_identity() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = ResearchWorkspaceWidget()
    requested: list[int] = []
    workspace.active_slot_requested.connect(requested.append)
    try:
        assert workspace.objectName() == "research.workspace"
        assert workspace.findChild(object, "research.workspace.scroll") is not None
        assert workspace.findChild(object, "research.workspace.grid") is not None
        empty = workspace.findChild(object, "research.workspace.empty")
        assert empty is not None and empty.isHidden() is False
        first = workspace.add_slot(1)
        third = workspace.add_slot(3)
        assert workspace.slot_ids() == (1, 3)
        assert workspace.chart_count() == 2
        assert empty.isHidden() is True
        workspace.set_active_slot(3)
        assert workspace.active_slot_id == 3
        assert third.property("active") is True
        QTest.mouseClick(first, Qt.LeftButton)
        assert requested == [1]

        identities = {slot_id: workspace.slot_widget(slot_id) for slot_id in (1, 3)}
        workspace.set_visualization_mode("fit_8")
        assert workspace.visualization_mode == "fit_8"
        assert workspace.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        workspace.set_visualization_mode("scroll_4")
        assert workspace.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert all(workspace.slot_widget(slot_id) is widget for slot_id, widget in identities.items())

        workspace.remove_slot(1)
        assert workspace.slot_ids() == (3,)
        for slot_id in (1, 2, 4, 5, 6, 7, 8):
            if slot_id not in workspace.slot_ids():
                workspace.add_slot(slot_id)
        assert workspace.chart_count() == 8
        with pytest.raises(ValueError, match="1 through 8"):
            workspace.add_slot(9)
        workspace.clear()
        assert workspace.chart_count() == 0
        assert empty.isHidden() is False
    finally:
        workspace.close()
        app.processEvents()


def test_workspace_layout_geometry_and_no_session_ownership() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = ResearchWorkspaceWidget()
    try:
        workspace.resize(1000, 800)
        for slot_id in range(1, 9):
            workspace.add_slot(slot_id)
        workspace.show()
        app.processEvents()
        assert workspace.layout_plan().row_count == 4
        assert workspace.grid_host.minimumHeight() >= workspace.scroll_area.viewport().height() * 2
        workspace.set_visualization_mode("fit_8")
        app.processEvents()
        assert workspace.grid_host.minimumHeight() == workspace.scroll_area.viewport().height()
    finally:
        workspace.close()
        app.processEvents()

    source = Path("src/leonardo/gui/widgets/research_workspace_widget.py").read_text(
        encoding="utf-8"
    )
    ast.parse(source)
    for forbidden in (
        "ChartSessionState",
        "ResearchDatasetApplicationService",
        "ResearchStudyApplicationService",
        "ArtifactService",
        "pathlib",
    ):
        assert forbidden not in source


def test_widget_package_preserves_and_caches_complete_public_exports() -> None:
    import leonardo.gui.widgets as widgets

    assert tuple(widgets.__all__) == EXPECTED_WIDGET_EXPORTS
    for name in EXPECTED_WIDGET_EXPORTS:
        exported = getattr(widgets, name)
        assert vars(widgets)[name] is exported
    with pytest.raises(AttributeError, match="unknown_export"):
        getattr(widgets, "unknown_export")
