from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.research import (
    HorizontalViewport,
    ResidentOHLCVSlice,
    ResidentStudyProjection,
    StudyLineStyle,
    StudyPresentation,
)


def _interaction() -> CandlestickInteractionState:
    count = 30
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    resident = ResidentOHLCVSlice(
        market, "a" * 64, 0, count, tuple(range(count)),
        (1.0,) * count, (2.0,) * count, (0.0,) * count, (1.0,) * count,
        (1.0,) * count, False, False, 0, count - 1,
    )
    return CandlestickInteractionState(
        HorizontalViewport(count, visible_count=count, left_padding=0, right_padding=0),
        resident,
    )


def _pair(study_id: str, *, visible: bool = True, revision: int = 0):
    projection = ResidentStudyProjection(
        study_id, MarketId("bybit", "linear", "BTCUSDT", "1m"), "a" * 64,
        "oscillator", 0, 30, tuple(range(30)), {"rsi_3": (50.0,) * 30}, {},
    )
    presentation = StudyPresentation(
        study_id, visible, f"oscillator:{study_id}",
        {"rsi_3": StudyLineStyle("rsi_3", "#A855F7")}, {}, revision,
    )
    return projection, presentation


def test_workspace_owns_independent_stable_dynamic_panes() -> None:
    app = QApplication.instance() or QApplication([])
    workspace = ChartPaneWorkspaceWidget()
    workspace.set_interaction_state(_interaction())
    first = _pair("rsi-a")
    second = _pair("rsi-b")
    workspace.apply_study_state((first[0], second[0]), (first[1], second[1]))

    assert workspace.study_pane_ids() == (
        "price", "oscillator:rsi-a", "oscillator:rsi-b"
    )
    first_widget = workspace.oscillator_widget("rsi-a")
    second_widget = workspace.oscillator_widget("rsi-b")
    assert first_widget is not None and second_widget is not None
    assert first_widget is not second_widget
    assert first_widget.time_axis_visible is False
    assert second_widget.time_axis_visible is True

    refreshed = _pair("rsi-a", revision=1)
    hidden = _pair("rsi-b", visible=False, revision=1)
    workspace.apply_study_state(
        (refreshed[0], hidden[0]), (refreshed[1], hidden[1])
    )
    assert workspace.oscillator_widget("rsi-a") is first_widget
    assert workspace.oscillator_widget("rsi-b") is second_widget
    assert workspace.study_pane_ids() == ("price", "oscillator:rsi-a")

    shown = _pair("rsi-b", revision=2)
    workspace.apply_study_state(
        (refreshed[0], shown[0]), (refreshed[1], shown[1])
    )
    assert workspace.oscillator_widget("rsi-b") is second_widget
    assert workspace.study_pane_ids()[-1] == "oscillator:rsi-b"

    workspace.apply_study_state((shown[0],), (shown[1],))
    assert workspace.oscillator_widget("rsi-a") is None
    assert workspace.study_pane_ids() == ("price", "oscillator:rsi-b")
    workspace.clear_studies()
    assert workspace.study_pane_ids() == ("price",)
    workspace.close()
    app.processEvents()
