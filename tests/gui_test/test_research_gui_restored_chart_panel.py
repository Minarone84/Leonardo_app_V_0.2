from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QPushButton,
    QToolButton,
)

from leonardo.gui.chart.candlestick_widget import (
    CandlestickChartWidget,
    CandlestickPalette,
    _format_crosshair_time,
)
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.gui.chart.volume_scene import _format_volume, build_volume_scene
from leonardo.gui.research import ResearchChartPanel, ResearchWorkspaceWidget
from leonardo.gui.research.pane_overlays import (
    OscillatorPaneOverlay,
    PricePaneOverlay,
)
from leonardo.research.volume import ResidentVolumeProjection
from leonardo.research import StudyLineStyle, StudyPresentation
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


def _semantic_text(label) -> str:
    return str(label.property("semantic_text"))


def _color_count(label, color: str) -> int:
    return label.text().count(f'color:{color}')


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
    assert _semantic_text(panel.price_overlay.ohlc_label) == expected
    assert panel.price_overlay.ohlc_label.text() != before


def test_price_overlay_colors_only_values_from_current_palette_and_styles(
    panel: ResearchChartPanel,
) -> None:
    fixture = build_primary_chart_fixture()
    interaction = panel.chart_widget.interaction_state
    assert interaction is not None and interaction.resident is not None
    palette = CandlestickPalette(up_fill="#123456", down_fill="#ABCDEF")
    panel.chart_widget.set_chart_palette(palette)
    assert panel.chart_widget.render_palette is palette

    interaction.viewport.set_crosshair(0)
    panel.refresh_overlays()
    assert interaction.resident.close[0] == interaction.resident.open[0]
    assert _color_count(panel.price_overlay.ohlc_label, palette.up_fill) == 4
    assert f'color:{palette.up_fill}">O:' not in panel.price_overlay.ohlc_label.text()

    bearish = next(
        index
        for index, (open_value, close_value) in enumerate(
            zip(
                interaction.resident.open,
                interaction.resident.close,
                strict=True,
            )
        )
        if close_value < open_value
    )
    interaction.viewport.set_crosshair(bearish)
    panel.refresh_overlays()
    assert _color_count(panel.price_overlay.ohlc_label, palette.down_fill) == 4

    sma_row, bb_row = panel.price_overlay.study_rows
    assert _color_count(sma_row.values_label, "#F59E0B") == 1
    assert sma_row.current_values_text == _semantic_text(sma_row.values_label)

    bb_presentation = replace(
        fixture.study_presentations[1],
        signal_styles={
            "bb_middle": replace(
                fixture.study_presentations[1].signal_styles["bb_middle"],
                color="#111111",
            ),
            "bb_upper_band": replace(
                fixture.study_presentations[1].signal_styles["bb_upper_band"],
                color="#222222",
            ),
            "bb_lower_band": replace(
                fixture.study_presentations[1].signal_styles["bb_lower_band"],
                color="#333333",
            ),
        },
    )
    presentations = list(fixture.study_presentations)
    presentations[1] = bb_presentation
    panel.set_study_snapshot(
        fixture.study_projections,
        tuple(presentations),
        fixture.study_entries,
    )
    for color in ("#111111", "#222222", "#333333"):
        assert _color_count(bb_row.values_label, color) == 1
    assert all(token in bb_row.current_values_text for token in ("M ", "U ", "L "))

    resident = interaction.resident
    interaction.set_resident(None)
    panel.refresh_overlays()
    assert _semantic_text(panel.price_overlay.ohlc_label) == (
        "O: —  H: —  L: —  C: —"
    )
    assert "color:" not in panel.price_overlay.ohlc_label.text()
    interaction.set_resident(resident)


def test_oscillator_overlay_colors_thresholds_conditionals_volume_and_missing_values(
    panel: ResearchChartPanel,
) -> None:
    fixture = build_primary_chart_fixture()
    interaction = panel.chart_widget.interaction_state
    assert interaction is not None and interaction.resident is not None
    projections = list(fixture.study_projections)
    presentations = list(fixture.study_presentations)

    rsi_presentation = replace(
        presentations[2], tool_key="rsi", guide_styles=None
    )
    presentations[2] = rsi_presentation
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    rsi_overlay = panel.oscillator_overlays[0]
    rsi_values = projections[2].render_series["rsi_14"]
    below = next(index for index, value in enumerate(rsi_values) if value < 30)
    above = next(index for index, value in enumerate(rsi_values) if value > 70)
    neutral = next(index for index, value in enumerate(rsi_values) if 30 < value < 70)
    for index, color in (
        (below, "#22C55E"),
        (neutral, "#A855F7"),
        (above, "#EF4444"),
    ):
        interaction.viewport.set_crosshair(index)
        panel.refresh_overlays()
        assert _color_count(rsi_overlay.values_label, color) == 1

    hidden_guides = {
        key: replace(guide, visible=False)
        for key, guide in rsi_presentation.guide_styles.items()
    }
    presentations[2] = replace(rsi_presentation, guide_styles=hidden_guides)
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    interaction.viewport.set_crosshair(below)
    panel.refresh_overlays()
    assert _color_count(rsi_overlay.values_label, "#22C55E") == 1

    editable_index = next(
        index for index, value in enumerate(rsi_values) if 30 < value < 40
    )
    edited_guides = dict(hidden_guides)
    edited_guides["oversold"] = replace(
        edited_guides["oversold"], value=40.0
    )
    presentations[2] = replace(
        rsi_presentation, guide_styles=edited_guides
    )
    original_projection = projections[2]
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    interaction.viewport.set_crosshair(editable_index)
    panel.refresh_overlays()
    assert rsi_overlay._projection is original_projection
    assert _color_count(rsi_overlay.values_label, "#22C55E") == 1

    equal_values = list(rsi_values)
    equal_values[editable_index] = 40.0
    projections[2] = replace(
        original_projection,
        render_series={"rsi_14": tuple(equal_values)},
    )
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    panel.refresh_overlays()
    assert _color_count(rsi_overlay.values_label, "#A855F7") == 1

    count = len(rsi_values)
    projections[2] = replace(
        original_projection,
        render_series={
            "arsi_14": (10.0,) * count,
            "arsi_signal_14": (10.0,) * count,
        },
    )
    presentations[2] = StudyPresentation(
        study_id="dev-rsi",
        visible=True,
        pane_id="oscillator:dev-rsi",
        signal_styles={
            "arsi_14": StudyLineStyle("arsi_14", "#8B5CF6"),
            "arsi_signal_14": StudyLineStyle("arsi_signal_14", "#FF5D00"),
        },
        fill_styles={},
        tool_key="arsi",
    )
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    interaction.viewport.set_crosshair(0)
    panel.refresh_overlays()
    assert _color_count(rsi_overlay.values_label, "#22C55E") == 1
    assert _color_count(rsi_overlay.values_label, "#FF5D00") == 1

    projections[2] = replace(
        original_projection, render_series={"mfi_14": (90.0,) * count}
    )
    presentations[2] = StudyPresentation(
        study_id="dev-rsi",
        visible=True,
        pane_id="oscillator:dev-rsi",
        signal_styles={"mfi_14": StudyLineStyle("mfi_14", "#A855F7")},
        fill_styles={},
        tool_key="mfi",
    )
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    panel.refresh_overlays()
    assert _color_count(rsi_overlay.values_label, "#EF4444") == 1

    driver = tuple("green" if index == 0 else "red" for index in range(count))
    projections[0] = replace(
        projections[0],
        render_series={
            "fast_vwap": (100.0,) * count,
            "slow_vwap": (99.0,) * count,
        },
        style_driver_series={"vwap_color": driver},
    )
    conditional = {
        "green": "#22C55E",
        "silver": "#22C55E",
        "red": "#EF4444",
    }
    presentations[0] = StudyPresentation(
        study_id="dev-sma",
        visible=True,
        pane_id="price",
        signal_styles={
            name: StudyLineStyle(
                name,
                "#64748B",
                conditional_driver_name="vwap_color",
                conditional_colors=conditional,
            )
            for name in ("fast_vwap", "slow_vwap")
        },
        fill_styles={},
        tool_key="hck",
    )
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    hck_row = panel.price_overlay.study_rows[0]
    interaction.viewport.set_crosshair(0)
    panel.refresh_overlays()
    assert _color_count(hck_row.values_label, "#22C55E") == 2
    interaction.viewport.set_crosshair(1)
    panel.refresh_overlays()
    assert _color_count(hck_row.values_label, "#EF4444") == 2

    projections = list(fixture.study_projections)
    presentations = list(fixture.study_presentations)
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    volume_overlay = panel.oscillator_overlays[1]
    volume_widget = panel.chart_workspace.oscillator_widget("dev-volume")
    assert volume_widget is not None
    assert volume_widget.render_palette is volume_widget._palette
    resident = interaction.resident
    bullish = next(
        index
        for index, (open_value, close_value) in enumerate(
            zip(resident.open, resident.close, strict=True)
        )
        if close_value >= open_value
    )
    bearish = next(
        index
        for index, (open_value, close_value) in enumerate(
            zip(resident.open, resident.close, strict=True)
        )
        if close_value < open_value
    )
    interaction.viewport.set_crosshair(bullish)
    panel.refresh_overlays()
    assert _color_count(
        volume_overlay.values_label,
        volume_widget.render_palette.bullish_volume,
    ) == 1
    assert _color_count(volume_overlay.values_label, "#F97316") == 1
    interaction.viewport.set_crosshair(bearish)
    panel.refresh_overlays()
    assert _color_count(
        volume_overlay.values_label,
        volume_widget.render_palette.bearish_volume,
    ) == 1

    interaction.set_resident(None)
    panel.refresh_overlays()
    assert _color_count(
        volume_overlay.values_label,
        volume_widget.render_palette.neutral_volume,
    ) == 1
    interaction.set_resident(resident)

    missing_index = 0
    volume_values = list(projections[3].render_series["volume"])
    mean_values = list(projections[3].render_series["volume_mean_20"])
    volume_values[missing_index] = float("nan")
    mean_values[missing_index] = float("inf")
    projections[3] = replace(
        projections[3],
        render_series={
            "volume": tuple(volume_values),
            "volume_mean_20": tuple(mean_values),
        },
    )
    panel.set_study_snapshot(
        tuple(projections), tuple(presentations), fixture.study_entries
    )
    interaction.viewport.set_crosshair(missing_index)
    panel.refresh_overlays()
    assert volume_overlay.current_values_text == "VOL —  MEAN —"
    assert "color:" not in volume_overlay.values_label.text()


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


def test_crosshair_time_tag_owner_and_volume_value_tag_follow_existing_panes(
    qapp: QApplication, panel: ResearchChartPanel
) -> None:
    workspace = panel.chart_workspace
    price = workspace.price_chart
    interaction = price.interaction_state
    assert interaction is not None
    price_pairs = tuple(
        zip(
            price.study_bundle.projections,
            price.study_bundle.presentations,
            strict=True,
        )
    )
    oscillator_pairs = tuple(
        (
            workspace.oscillator_widget(study_id).projection,
            workspace.oscillator_widget(study_id).presentation,
        )
        for study_id in ("dev-rsi", "dev-volume")
    )
    assert all(projection is not None and presentation is not None for projection, presentation in oscillator_pairs)
    all_pairs = price_pairs + oscillator_pairs
    interaction.viewport.set_crosshair(180)
    price.refresh_from_shared_state(refresh_price_scale=False)
    price._crosshair_y = price._plot_rect().center().y()

    workspace.apply_study_state(
        tuple(projection for projection, _presentation in price_pairs),
        tuple(presentation for _projection, presentation in price_pairs),
    )
    qapp.processEvents()
    assert price._time_axis_visible
    assert any(tag.background == "#E1E1E1" for tag in price._dynamic_crosshair_tags())

    one_oscillator = price_pairs + oscillator_pairs[:1]
    workspace.apply_study_state(
        tuple(projection for projection, _presentation in one_oscillator),
        tuple(presentation for _projection, presentation in one_oscillator),
    )
    qapp.processEvents()
    rsi = workspace.oscillator_widget("dev-rsi")
    assert rsi is not None
    assert not price._time_axis_visible
    assert not any(tag.background == "#E1E1E1" for tag in price._dynamic_crosshair_tags())
    assert rsi.time_axis_visible
    assert len(rsi._dynamic_crosshair_tags()) == 1

    workspace.apply_study_state(
        tuple(projection for projection, _presentation in all_pairs),
        tuple(presentation for _projection, presentation in all_pairs),
    )
    qapp.processEvents()
    rsi = workspace.oscillator_widget("dev-rsi")
    bottom = workspace.oscillator_widget("dev-volume")
    assert rsi is not None and bottom is not None
    assert not rsi.time_axis_visible
    assert rsi._dynamic_crosshair_tags() == ()
    assert bottom.time_axis_visible
    bottom_tags = bottom._dynamic_crosshair_tags()
    assert len(bottom_tags) == 1
    assert bottom.projection is not None
    assert bottom_tags[0].text == _format_crosshair_time(
        bottom.projection.ts_ms[180 - bottom.projection.base_index]
    )

    workspace.set_volume_visible(True)
    qapp.processEvents()
    volume = workspace.volume_chart
    resident = interaction.resident
    assert resident is not None
    volume.set_projection(
        ResidentVolumeProjection(
            market_id=resident.market_id,
            dataset_fingerprint=resident.dataset_fingerprint,
            base_index=resident.base_index,
            end_index_exclusive=resident.end_index_exclusive,
            period=20,
            volume=resident.volume,
            moving_mean=tuple(None for _value in resident.volume),
            bullish=tuple(
                close >= open_value
                for open_value, close in zip(resident.open, resident.close, strict=True)
            ),
        )
    )
    qapp.processEvents()
    volume._crosshair_y = volume._plot_rect().center().y()
    volume.grab()
    rebuilds = volume.static_rebuild_count
    tags = volume._dynamic_crosshair_tags()
    assert len(tags) == 1
    assert volume.render_contract is not None
    volume_scene = build_volume_scene(
        volume.render_contract,
        width=volume.width(),
        height=volume.height(),
    )
    assert tags[0].text == _format_volume(volume_scene.maximum * 0.5)
    assert tags[0].background == "#FFA500"
    assert tags[0].background_opacity == 0.5
    assert tags[0].text_color == "#000000"
    assert volume_scene.last_volume_tag is not None
    static_rect = QRectF(
        volume_scene.plot_rect.right + 2,
        volume_scene.last_volume_tag.y - 9,
        max(1.0, volume_scene.axis_rect.width - 4),
        18,
    )

    volume._crosshair_y = volume_scene.last_volume_tag.y
    assert volume._dynamic_crosshair_tags() == ()
    assert volume._plot_rect().contains(
        volume._plot_rect().center().x(), volume._crosshair_y
    )
    assert volume.static_rebuild_count == rebuilds

    volume._crosshair_y = static_rect.bottom() + 30.0
    separated_tags = volume._dynamic_crosshair_tags()
    assert len(separated_tags) == 1
    separated_tag = separated_tags[0]
    fraction = (
        volume._plot_rect().bottom() - volume._crosshair_y
    ) / volume._plot_rect().height()
    expected_value = min(
        volume_scene.maximum,
        max(0.0, fraction * volume_scene.maximum),
    )
    assert separated_tag.text == _format_volume(expected_value)
    assert volume.static_rebuild_count == rebuilds

    volume._crosshair_y = static_rect.bottom() + separated_tag.height / 2.0
    edge_tags = volume._dynamic_crosshair_tags()
    assert len(edge_tags) == 1
    assert edge_tags[0].rect.top() == pytest.approx(static_rect.bottom())
    assert volume.static_rebuild_count == rebuilds

    interaction.viewport.set_crosshair(181)
    volume.refresh_from_shared_state()
    volume.grab()
    assert volume.static_rebuild_count == rebuilds


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
