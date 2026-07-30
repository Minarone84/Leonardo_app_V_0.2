from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QPushButton,
    QToolButton,
)

from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.gui.research import ResearchChartPanel, ResearchWorkspaceWidget
from leonardo.gui.research.pane_overlays import (
    OscillatorPaneOverlay,
    PricePaneOverlay,
)
from tools.research_gui_dev_fixtures import build_primary_chart_fixture


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp: QApplication) -> ResearchChartPanel:
    fixture = build_primary_chart_fixture()
    widget = ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )
    widget.resize(1200, 760)
    widget.show()
    qapp.processEvents()
    widget.refresh_overlays()
    yield widget
    widget.close()


def _control_texts(panel: ResearchChartPanel) -> list[str]:
    layout = panel.control_bar.layout()
    output: list[str] = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if isinstance(widget, QComboBox):
            output.append(widget.currentText())
        elif widget is not None and hasattr(widget, "text"):
            output.append(widget.text())
    return output


def _rendered_pixel(widget, point: QPoint):
    image = QImage(
        widget.size(), QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(Qt.GlobalColor.transparent)
    widget.render(image)
    return image.pixelColor(point)


def test_panel_reuses_v2_workspace_and_has_only_bottom_controls(
    panel: ResearchChartPanel,
) -> None:
    assert isinstance(panel, QFrame)
    assert isinstance(panel.chart_workspace, ChartPaneWorkspaceWidget)
    assert len(panel.findChildren(ChartPaneWorkspaceWidget)) == 1
    assert panel.layout().itemAt(0).widget() is panel.chart_workspace
    assert panel.layout().itemAt(1).widget() is panel.control_bar
    assert _control_texts(panel) == [
        "Historical Chart: Bybit_linear_BTCUSDT_4h",
        "Position",
        "1",
        "Go to",
        "Financial Tools",
        "Studies",
        "Detach",
        "Close",
        "Autoscale",
    ]
    button_texts = {
        button.text()
        for button in panel.findChildren(QPushButton)
        + panel.findChildren(QToolButton)
    }
    assert "Add Study" not in button_texts
    assert "Show Volume" not in button_texts
    assert panel.dataset_label.text() == "Historical Chart: Bybit_linear_BTCUSDT_4h"
    assert [panel.position_combo.itemText(index) for index in range(8)] == [
        str(value) for value in range(1, 9)
    ]
    assert panel.position_combo.currentText() == "1"
    assert panel.autoscale_button.isCheckable()
    assert panel.autoscale_button.isChecked()
    assert panel.autoscale_button.text() == "Autoscale"
    assert "#86EFAC" in panel.autoscale_button.styleSheet()
    assert (
        panel.autoscale_button.toolTip()
        == "Autoscale is on. The vertical price range follows visible data."
    )
    assert panel.autoscale_button.accessibleName() == "Autoscale on"
    assert panel.chart_workspace.price_chart.autoscale_enabled


def test_price_overlay_ohlc_rows_controls_and_value_visibility(
    panel: ResearchChartPanel,
) -> None:
    overlay = panel.price_overlay
    assert isinstance(overlay, PricePaneOverlay)
    assert isinstance(overlay.parentWidget(), CandlestickChartWidget)
    assert overlay.pos() == QPoint(12, 12)
    assert overlay.title_label.text() == "BTCUSDT · 4h"
    for token in ("O:", "H:", "L:", "C:"):
        assert token in overlay.ohlc_label.text()
    assert [row.display_name for row in overlay.study_rows] == [
        "SMA 20",
        "BB 20 2",
    ]
    assert "Original Study name: BB 20 / 2" in (
        overlay.study_rows[1].name_label.toolTip()
    )
    for row in overlay.study_rows:
        assert [
            row.values_button.text(),
            row.style_button.text(),
            row.edit_button.text(),
            row.remove_button.text(),
        ] == ["V", "S", "E", "X"]
        assert row.values_button.toolTip() == "Show or hide current values"
        assert row.style_button.toolTip() == "Edit display style"
        assert row.edit_button.toolTip() == "Edit computation parameters"
        assert row.remove_button.toolTip() == "Remove study from chart"

    row = overlay.study_rows[0]
    assert row.name_label.isVisible()
    assert row.values_label.isVisible()
    assert panel.chart_workspace.price_chart.study_bundle.presentations[0].visible
    row.values_button.click()
    assert row.name_label.isVisible()
    assert row.values_label.isHidden()
    assert panel.chart_workspace.price_chart.study_bundle.presentations[0].visible
    row.values_button.click()
    assert row.values_label.isVisible()


def test_price_overlay_hover_and_retraction_preserve_existing_rows(
    qapp: QApplication, panel: ResearchChartPanel
) -> None:
    overlay = panel.price_overlay
    row_ids = tuple(id(row) for row in overlay.study_rows)
    overlay.study_rows[0].values_button.click()
    assert overlay.background_state == "outside"

    QApplication.sendEvent(overlay, QEvent(QEvent.Type.Enter))
    assert overlay.background_state == "inside"
    QApplication.sendEvent(overlay, QEvent(QEvent.Type.Leave))
    assert overlay.background_state == "outside"

    assert overlay.expanded
    assert overlay.retract_button.text() == "◀"
    overlay.retract_button.click()
    qapp.processEvents()
    assert not overlay.expanded
    assert overlay.content_widget.isHidden()
    assert overlay.retract_button.isVisible()
    assert overlay.retract_button.text() == "▶"
    overlay.retract_button.click()
    qapp.processEvents()
    assert overlay.expanded
    assert overlay.content_widget.isVisible()
    assert overlay.retract_button.text() == "◀"
    assert tuple(id(row) for row in overlay.study_rows) == row_ids
    assert not overlay.study_rows[0].current_values_visible


def test_overlay_surfaces_render_transparent_outside_and_half_black_inside(
    qapp: QApplication, panel: ResearchChartPanel
) -> None:
    previous_stylesheet = qapp.styleSheet()
    qapp.setStyleSheet("QWidget { background-color: #070B10; }")
    qapp.processEvents()
    try:
        overlays = (panel.price_overlay, *panel.oscillator_overlays)
        for overlay in overlays:
            sample = overlay.content_widget.mapTo(overlay, QPoint(2, 2))
            parent = overlay.parentWidget()
            parent_sample = overlay.mapTo(parent, sample)
            overlay.hide()
            qapp.processEvents()
            baseline = parent.grab().toImage().pixelColor(parent_sample)
            overlay.show()
            QApplication.sendEvent(overlay, QEvent(QEvent.Type.Leave))
            qapp.processEvents()
            assert overlay.background_state == "outside"
            outside = parent.grab().toImage().pixelColor(parent_sample)
            assert outside.toRgb().rgb() == baseline.toRgb().rgb()

            QApplication.sendEvent(overlay, QEvent(QEvent.Type.Enter))
            qapp.processEvents()
            inside = parent.grab().toImage().pixelColor(parent_sample)
            assert overlay.background_state == "inside"
            expected = tuple(
                round(channel * (127 / 255))
                for channel in (
                    baseline.red(),
                    baseline.green(),
                    baseline.blue(),
                )
            )
            actual = (inside.red(), inside.green(), inside.blue())
            assert all(
                abs(actual_channel - expected_channel) <= 1
                for actual_channel, expected_channel in zip(
                    actual, expected, strict=True
                )
            )

            QApplication.sendEvent(overlay, QEvent(QEvent.Type.Leave))
            assert overlay.background_state == "outside"

        price_row = panel.price_overlay.study_rows[0]
        row_surface = _rendered_pixel(price_row, QPoint(1, 1))
        assert row_surface.alpha() == 0
    finally:
        qapp.setStyleSheet(previous_stylesheet)
        qapp.processEvents()


def test_price_overlay_uses_shared_crosshair_state(panel: ResearchChartPanel) -> None:
    interaction = panel.chart_workspace.price_chart.interaction_state
    assert interaction is not None
    assert interaction is panel.price_overlay._interaction_state
    before = panel.price_overlay.ohlc_label.text()
    interaction.viewport.set_crosshair(10)
    panel.refresh_overlays()
    resident = interaction.resident
    assert resident is not None
    expected = (
        f"O: {resident.open[10]:.2f}  H: {resident.high[10]:.2f}  "
        f"L: {resident.low[10]:.2f}  C: {resident.close[10]:.2f}"
    )
    assert panel.price_overlay.ohlc_label.text() == expected
    assert panel.price_overlay.ohlc_label.text() != before


def test_oscillator_panes_and_overlays_use_dynamic_study_family(
    panel: ResearchChartPanel,
) -> None:
    assert panel.chart_workspace.study_pane_ids() == (
        "price",
        "oscillator:dev-rsi",
        "oscillator:dev-volume",
    )
    assert panel.chart_workspace.volume_visible is False
    assert panel.chart_workspace.volume_chart.isHidden()
    assert [overlay.study_id for overlay in panel.oscillator_overlays] == [
        "dev-rsi",
        "dev-volume",
    ]
    assert all(isinstance(item, OscillatorPaneOverlay) for item in panel.oscillator_overlays)
    assert [item.title_label.text() for item in panel.oscillator_overlays] == [
        "RSI 14",
        "Volume 20",
    ]
    assert "Period: 14" in panel.oscillator_overlays[0].title_label.toolTip()
    for overlay in panel.oscillator_overlays:
        assert overlay.parentWidget() is panel.chart_workspace.oscillator_widget(
            overlay.study_id
        )
        assert overlay.pos() == QPoint(12, 12)
        assert [
            overlay.move_up_button.text(),
            overlay.move_down_button.text(),
            overlay.values_button.text(),
            overlay.style_button.text(),
            overlay.edit_button.text(),
            overlay.remove_button.text(),
        ] == ["↑", "↓", "V", "S", "E", "X"]
        assert overlay.values_button.isChecked()
        assert overlay.values_label.text() not in {"", "—"}
    assert panel.oscillator_overlays[0].move_up_button.toolTip() == (
        "Move oscillator pane up"
    )
    assert panel.oscillator_overlays[0].move_down_button.toolTip() == (
        "Move oscillator pane down"
    )
    volume_values = panel.oscillator_overlays[1].values_label.text()
    assert "VOL" in volume_values
    assert "MEAN" in volume_values

    volume_pane = panel.chart_workspace.oscillator_widget("dev-volume")
    rsi_pane = panel.chart_workspace.oscillator_widget("dev-rsi")
    assert volume_pane is not None and volume_pane.scene_plan is not None
    assert rsi_pane is not None and rsi_pane.scene_plan is not None
    assert volume_pane.scene_plan.histogram_bars
    assert {bar.direction for bar in volume_pane.scene_plan.histogram_bars} >= {
        "bullish",
        "bearish",
    }
    assert [strip.output_name for strip in volume_pane.scene_plan.line_strips] == [
        "volume_mean_20"
    ]
    assert rsi_pane.scene_plan.histogram_bars == ()
    assert [strip.output_name for strip in rsi_pane.scene_plan.line_strips] == [
        "rsi_14"
    ]
    assert volume_pane._palette.bullish_volume == "#22C55E"
    assert volume_pane._palette.bearish_volume == "#EF4444"
    assert volume_pane._palette.neutral_volume == "#94A3B8"


def test_oscillator_overlay_hover_retraction_and_compact_intents(
    qapp: QApplication, panel: ResearchChartPanel
) -> None:
    overlay = panel.oscillator_overlays[0]
    values = QSignalSpy(panel.study_values_toggled)
    style = QSignalSpy(panel.study_style_requested)
    edit = QSignalSpy(panel.study_edit_requested)
    remove = QSignalSpy(panel.study_remove_requested)
    move_up = QSignalSpy(panel.oscillator_move_up_requested)
    move_down = QSignalSpy(panel.oscillator_move_down_requested)
    content_id = id(overlay.content_widget)

    QApplication.sendEvent(overlay, QEvent(QEvent.Type.Enter))
    assert overlay.background_state == "inside"
    QApplication.sendEvent(overlay, QEvent(QEvent.Type.Leave))
    assert overlay.background_state == "outside"

    overlay.values_button.click()
    assert overlay.values_label.isHidden()
    assert values.at(0) == ["dev-rsi", False]
    overlay.style_button.click()
    overlay.edit_button.click()
    overlay.remove_button.click()
    overlay.move_up_button.click()
    overlay.move_down_button.click()
    assert style.at(0) == ["dev-rsi"]
    assert edit.at(0) == ["dev-rsi"]
    assert remove.at(0) == ["dev-rsi"]
    assert move_up.at(0) == ["dev-rsi"]
    assert move_down.at(0) == ["dev-rsi"]

    overlay.retract_button.click()
    qapp.processEvents()
    assert not overlay.expanded
    assert overlay.retract_button.text() == "▶"
    assert overlay.retract_button.isVisible()
    overlay.retract_button.click()
    qapp.processEvents()
    assert overlay.expanded
    assert overlay.retract_button.text() == "◀"
    assert id(overlay.content_widget) == content_id
    assert not overlay.current_values_visible


def test_panel_control_and_overlay_intent_signals(panel: ResearchChartPanel) -> None:
    go_to = QSignalSpy(panel.go_to_requested)
    financial_tools = QSignalSpy(panel.financial_tools_requested)
    studies = QSignalSpy(panel.studies_requested)
    detach = QSignalSpy(panel.detach_requested)
    close = QSignalSpy(panel.close_requested)
    autoscale = QSignalSpy(panel.autoscale_toggled)
    position = QSignalSpy(panel.position_change_requested)
    panel.go_to_button.click()
    panel.financial_tools_button.click()
    panel.studies_button.click()
    panel.detach_button.click()
    panel.close_button.click()
    panel.autoscale_button.click()
    panel.position_combo.setCurrentText("3")
    assert all(spy.count() == 1 for spy in (go_to, financial_tools, studies, detach, close, autoscale, position))
    assert autoscale.at(0)[0] is False
    assert position.at(0)[0] == 3
    assert panel.workspace_position == 3

    values = QSignalSpy(panel.study_values_toggled)
    style = QSignalSpy(panel.study_style_requested)
    edit = QSignalSpy(panel.study_edit_requested)
    remove = QSignalSpy(panel.study_remove_requested)
    price_row = panel.price_overlay.study_rows[1]
    price_row.values_button.click()
    price_row.style_button.click()
    price_row.edit_button.click()
    price_row.remove_button.click()
    assert values.at(0) == ["dev-bb", False]
    assert style.at(0) == ["dev-bb"]
    assert edit.at(0) == ["dev-bb"]
    assert remove.at(0) == ["dev-bb"]

    move_up = QSignalSpy(panel.oscillator_move_up_requested)
    move_down = QSignalSpy(panel.oscillator_move_down_requested)
    oscillator = panel.oscillator_overlays[0]
    oscillator.move_up_button.click()
    oscillator.move_down_button.click()
    oscillator.style_button.click()
    oscillator.edit_button.click()
    oscillator.remove_button.click()
    assert move_up.at(0) == ["dev-rsi"]
    assert move_down.at(0) == ["dev-rsi"]
    assert style.at(1) == ["dev-rsi"]
    assert edit.at(1) == ["dev-rsi"]
    assert remove.at(1) == ["dev-rsi"]


def test_autoscale_visuals_and_programmatic_sync_signal_boundary(
    panel: ResearchChartPanel,
) -> None:
    autoscale = QSignalSpy(panel.autoscale_toggled)
    control_height = panel.control_bar.height()

    panel.autoscale_button.click()
    assert autoscale.count() == 1
    assert autoscale.at(0) == [False]
    assert not panel.autoscale_button.isChecked()
    assert "#FCA5A5" in panel.autoscale_button.styleSheet()
    assert "#111827" in panel.autoscale_button.styleSheet()
    assert (
        panel.autoscale_button.toolTip()
        == "Autoscale is off. The vertical price range remains manually controlled."
    )
    assert panel.autoscale_button.accessibleName() == "Autoscale off"

    panel.autoscale_button.click()
    assert autoscale.count() == 2
    assert autoscale.at(1) == [True]
    assert panel.autoscale_button.isChecked()
    assert "#86EFAC" in panel.autoscale_button.styleSheet()
    assert (
        panel.autoscale_button.toolTip()
        == "Autoscale is on. The vertical price range follows visible data."
    )
    assert panel.autoscale_button.accessibleName() == "Autoscale on"

    panel._interaction_state.set_autoscale_enabled(False)
    panel.show_interaction_state(
        panel._interaction_state,
        panel.chart_workspace.volume_chart.projection,
    )
    assert autoscale.count() == 2
    assert not panel.autoscale_button.isChecked()
    assert "#FCA5A5" in panel.autoscale_button.styleSheet()
    assert panel.control_bar.height() == control_height
    assert panel.autoscale_button.text() == "Autoscale"


def test_detached_label_and_workspace_host_lifecycle(
    qapp: QApplication,
    panel: ResearchChartPanel,
) -> None:
    panel.set_detached(True)
    assert panel.detach_button.text() == "Dock"
    panel.set_detached(False)
    assert panel.detach_button.text() == "Detach"

    workspace = ResearchWorkspaceWidget()
    try:
        workspace.show()
        workspace.show_single_chart(panel)
        qapp.processEvents()
        assert workspace.chart_panel is panel
        assert workspace.empty_state_label.isHidden()
        assert panel.isVisible()
        workspace.clear_chart()
        assert workspace.chart_panel is None
        assert panel.parentWidget() is None
        assert workspace.empty_state_label.text() == (
            "No Research charts loaded.\nUse File → New Chart to load one."
        )
        assert workspace.empty_state_label.isVisible()
    finally:
        workspace.close()


def test_dev_fixture_and_launcher_compose_exactly_one_restored_panel() -> None:
    fixture = build_primary_chart_fixture()
    assert fixture.market_id.as_key() == "bybit:linear:BTCUSDT:4h"
    resident = fixture.interaction_state.resident
    assert resident is not None and resident.row_count == 240
    assert all(
        right - left == 4 * 60 * 60 * 1000
        for left, right in zip(resident.ts_ms, resident.ts_ms[1:])
    )
    assert all(
        high >= max(open_value, close_value)
        and low <= min(open_value, close_value)
        and volume > 0
        for open_value, high, low, close_value, volume in zip(
            resident.open,
            resident.high,
            resident.low,
            resident.close,
            resident.volume,
            strict=True,
        )
    )
    assert [item.study_id for item in fixture.study_projections] == [
        "dev-sma",
        "dev-bb",
        "dev-rsi",
        "dev-volume",
    ]

    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    assert source.count("ResearchChartPanel(") == 1
    assert "build_primary_chart_fixture()" in source
    assert "window.workspace.show_single_chart(chart_panel)" in source
    for forbidden in (
        "LeonardoApp",
        "GuiCompositionRoot",
        "CoreRunner",
        "OHLCVStore",
        "ArtifactService",
    ):
        assert forbidden not in source
