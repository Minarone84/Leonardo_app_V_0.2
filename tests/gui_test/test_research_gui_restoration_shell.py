from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QToolButton,
)

from leonardo.data import MarketId
from leonardo.gui.research import ResearchSuiteWindow
from leonardo.gui.windows.research_suite_window import (
    ResearchSuiteWindow as CurrentResearchSuiteWindow,
)
from tools.research_gui_dev_fixtures import RESEARCH_GUI_DATASET_FIXTURES


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _menu_labels(menu) -> list[str]:
    return [action.text() for action in menu.actions()]


def test_restored_shell_menu_actions_and_quick_action_identity(qapp) -> None:
    window = ResearchSuiteWindow(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        assert isinstance(window, QMainWindow)
        assert not isinstance(window, CurrentResearchSuiteWindow)
        assert window.windowTitle() == "Leonardo - Research Suite"
        assert _menu_labels(window.file_menu) == [
            "New Chart...",
            "",
            "Save Study Environment...",
            "Load Study Environment...",
            "Manage Study Environments...",
            "",
            "Save Workspace...",
            "Load Workspace...",
            "Manage Workspaces...",
            "",
            "Clear Research Suite",
            "",
            "Close",
        ]
        assert _menu_labels(window.window_menu) == [
            "Pan Anchor",
            "",
            "Scroll 4",
            "Fit 8",
        ]
        assert _menu_labels(window.notes_menu) == [
            "Open Assigned Notebook",
            "Notebook Manager...",
        ]
        for removed in (
            "Create New Notebook",
            "Open Notebook",
            "Save Notebook",
            "Load Notebook",
        ):
            assert removed not in _menu_labels(window.notes_menu)
        with pytest.raises(KeyError):
            window.quick_button_for_action("Open Notebook")

        pan_anchor = window.action_for_text("Pan Anchor")
        scroll_4 = window.action_for_text("Scroll 4")
        fit_8 = window.action_for_text("Fit 8")
        assert pan_anchor.isCheckable()
        assert scroll_4.isCheckable() and fit_8.isCheckable()
        assert scroll_4.actionGroup() is fit_8.actionGroup()
        assert scroll_4.actionGroup().isExclusive()
        assert scroll_4.isChecked() and not fit_8.isChecked()

        corner = window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
        assert corner is not None
        expected_quick_actions = {
            "Open Assigned Notebook",
            "Save Study Environment...",
            "Load Study Environment...",
            "Save Workspace...",
            "Load Workspace...",
            "Clear Research Suite",
            "Pan Anchor",
        }
        for action_text in expected_quick_actions:
            button = window.quick_button_for_action(action_text)
            assert button.defaultAction() is window.action_for_text(action_text)

        view_label = corner.findChild(object, "research_restoration.label.view_mode")
        assert view_label.text() == "View: Scroll 4"
        fit_8.trigger()
        assert view_label.text() == "View: Fit 8"
        scroll_4.trigger()
        assert view_label.text() == "View: Scroll 4"
    finally:
        window.close()


def test_workspace_activity_and_forbidden_permanent_controls(qapp) -> None:
    window = ResearchSuiteWindow(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        assert window.centralWidget() is window.workspace
        assert window.workspace.empty_state_label.text() == (
            "No Research charts loaded.\nUse File → New Chart to load one."
        )
        assert window.findChildren(QProgressBar) == []

        forbidden = {
            "Refresh Datasets",
            "Open New Chart",
            "Cancel",
            "Close Active Chart",
            "Disable Autoscale",
            "Enable Autoscale",
            "Show Volume",
            "Add Study",
            "Open Data Manager",
        }
        permanent_controls = window.findChildren(QPushButton) + window.findChildren(
            QToolButton
        )
        assert forbidden.isdisjoint(control.text() for control in permanent_controls)

        body = window.findChild(object, "research_restoration.activity.body")
        toggle = window.findChild(QToolButton, "research_restoration.activity.toggle")
        activity_log = window.findChild(object, "research_restoration.activity.log")
        assert window.activity_expanded is False
        assert body.isHidden()
        toggle.click()
        assert window.activity_expanded is True
        assert not body.isHidden()
        window.action_for_text("New Chart...").trigger()
        assert activity_log.toPlainText().splitlines()[-1] == (
            "New Chart... requested"
        )
        toggle.click()
        assert window.activity_expanded is False
        assert body.isHidden()
    finally:
        window.close()


def test_exact_four_deterministic_fixture_market_ids(qapp) -> None:
    expected = (
        MarketId("bybit", "linear", "BTCUSDT", "4h"),
        MarketId("bybit", "linear", "ETHUSDT", "1h"),
        MarketId("binance", "spot", "BTCUSDT", "15m"),
        MarketId("binance", "spot", "ETHUSDT", "1d"),
    )
    assert len(RESEARCH_GUI_DATASET_FIXTURES) == 4
    assert tuple(item.market_id for item in RESEARCH_GUI_DATASET_FIXTURES) == expected

    window = ResearchSuiteWindow(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        assert tuple(item.market_id for item in window.dataset_summaries) == expected
    finally:
        window.close()


def test_dev_launcher_uses_only_restored_shell_and_fixture_read_models() -> None:
    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    assert "from leonardo.gui.research import ResearchSuiteWindow" in source
    assert "RESEARCH_GUI_DATASET_FIXTURES" in source
    for forbidden in (
        "leonardo.gui.windows.research_suite_window",
        "LeonardoApp",
        "GuiCompositionRoot",
        "CoreRunner",
        "OHLCVStore",
    ):
        assert forbidden not in source
