from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QToolButton,
)

from leonardo.data import MarketId
from leonardo.financial_tools import ALL_FINANCIAL_TOOL_SPECS, FinancialToolSpec
from leonardo.gui.research import (
    ResearchFinancialToolsDialog,
    ResearchStudiesManagerDialog,
    ResearchSuiteWindow,
    ResearchWorkspaceWidget,
)
from leonardo.gui.research.financial_tools_dialog import (
    ResearchSavedArtifactBatchIntent,
    ResearchStudyApplyIntent,
    ResearchStudyEditDialog,
    _UtcPeaksTroughsOwnerSelector,
)
from leonardo.gui.widgets.study_manager_widget import StudyManagerWidget
from leonardo.gui.widgets.study_source_selector_widget import (
    StudySourceSelectorWidget,
)
from leonardo.research import (
    RESEARCH_FINANCIAL_TOOL_SPECS,
    StudyArtifactOption,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyPresentation,
)
from leonardo.research import StudySetupCatalog, StudySourceOption
from tools.dev_launch_research_gui_restoration import _build_chart_panel
from tools.research_gui_dev_fixtures import (
    ResearchGuiDevChartFixture,
    build_chart_fixture_for_market,
    build_primary_chart_fixture,
    build_study_setup_catalog_fixture,
)


SMA_ARTIFACT_ID = (
    "e6423b7911b3b62c73cc66dc134d615b4984f3c49b93e65d594ebab906b60992"
)
RSI_ARTIFACT_ID = (
    "ec7c06a96d8bfe7c658765e2d9ce3707ac291e5514dbad6858ea5f801e39ac31"
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dialog() -> ResearchFinancialToolsDialog:
    fixture = build_primary_chart_fixture()
    return ResearchFinancialToolsDialog(
        fixture.market_id,
        build_study_setup_catalog_fixture(fixture),
    )


def _select_tool(dialog: ResearchFinancialToolsDialog, title: str) -> None:
    for row in range(dialog.tool_list.count()):
        if dialog.tool_list.item(row).text() == title:
            dialog.tool_list.setCurrentRow(row)
            return
    raise AssertionError(f"tool not found: {title}")


def _tool_specs(dialog: ResearchFinancialToolsDialog) -> tuple[FinancialToolSpec, ...]:
    return tuple(
        dialog.tool_list.item(row).data(Qt.ItemDataRole.UserRole)
        for row in range(dialog.tool_list.count())
    )


def _ordinary_source_selector(
    dialog: ResearchFinancialToolsDialog,
) -> StudySourceSelectorWidget:
    selector = dialog.source_selector
    assert isinstance(selector, StudySourceSelectorWidget)
    return selector


def _source_roles(
    selector: StudySourceSelectorWidget,
) -> tuple[str, ...]:
    return tuple(row.role for row in selector._rows)


def _source_row(selector: StudySourceSelectorWidget, role: str):
    return next(row for row in selector._rows if row.role == role)


def _table_rows(
    table: QTableWidget,
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        tuple(table.item(row, column).text() for column in range(4))
        for row in range(table.rowCount())
    )


def _control_contract(control) -> tuple[object, ...]:
    if isinstance(control, QDoubleSpinBox):
        return (
            type(control),
            control.minimum(),
            control.maximum(),
            control.decimals(),
        )
    if isinstance(control, QSpinBox):
        return (type(control), control.minimum(), control.maximum())
    if isinstance(control, QComboBox):
        return (
            type(control),
            tuple(
                (
                    control.itemText(index),
                    control.itemData(index),
                )
                for index in range(control.count())
            ),
        )
    return (type(control),)


def _default_request(spec: FinancialToolSpec) -> StudyExecutionRequest:
    return StudyExecutionRequest(
        spec.key,
        {
            parameter.name: parameter.default
            for parameter in spec.parameters
        },
    )


def _peaks_owner_options(study_id: str) -> tuple[StudySourceOption, ...]:
    return tuple(
        StudySourceOption(
            source_kind="study",
            label=f"Peaks & Troughs {study_id}: {output_name}",
            family="indicator",
            study_id=study_id,
            output_name=output_name,
        )
        for window in (3, 5, 7, 9, 11)
        for output_name in (
            f"peak_fractal_{window}",
            f"trough_fractal_{window}",
        )
    )


def test_financial_tools_structure_and_initial_state(qapp: QApplication) -> None:
    dialog = _dialog()
    try:
        assert isinstance(dialog, QDialog)
        assert dialog.objectName() == "research_restoration.financial_tools"
        assert dialog.windowTitle() == "Financial Tools — BTCUSDT · 4h"
        assert not dialog.isModal()
        screen = dialog.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        assert abs(dialog.width() - round(available.width() / 2)) <= 2
        assert abs(dialog.height() - round(available.height() * 2 / 3)) <= 2
        assert dialog.minimumWidth() == 0 and dialog.minimumHeight() == 0
        assert dialog.context_label.text() == (
            "Historical Chart: Bybit_linear_BTCUSDT_4h"
        )
        assert dialog.family_combo.objectName() == (
            "research_restoration.financial_tools.family"
        )
        assert [
            dialog.family_combo.itemText(index)
            for index in range(dialog.family_combo.count())
        ] == ["All", "Indicator", "Oscillator", "Construct"]
        assert [
            dialog.family_combo.itemData(index)
            for index in range(dialog.family_combo.count())
        ] == [None, "indicator", "oscillator", "construct"]
        assert dialog.tool_list.currentItem() is None
        assert dialog.tool_list.count() == 25
        assert tuple(spec.key for spec in _tool_specs(dialog)) == tuple(
            spec.key for spec in RESEARCH_FINANCIAL_TOOL_SPECS
        )
        assert all(spec.key != "dynamic_binning" for spec in _tool_specs(dialog))
        assert all(spec.title != "Dynamic Binning" for spec in _tool_specs(dialog))
        assert dialog.description_label.text() == "Select a Financial Tool."
        assert dialog.status_label.text() == "Select a Financial Tool."
        assert not dialog.apply_button.isEnabled()
        assert dialog.save_button.text() == "Save"
        assert dialog.save_button.objectName() == (
            "research_restoration.financial_tools.save"
        )
        assert not dialog.save_button.isEnabled()
        assert dialog.findChild(
            QPushButton, "research_restoration.financial_tools.save_artifact"
        ) is None
        assert not dialog.apply_saved_artifact_button.isEnabled()
        assert isinstance(dialog.saved_artifact_table, QTableWidget)
        assert not hasattr(dialog, "saved_artifact_list")
        assert dialog.saved_artifact_table.objectName() == (
            "research_restoration.financial_tools.saved_artifacts"
        )
        assert dialog.saved_artifact_table.columnCount() == 4
        assert tuple(
            dialog.saved_artifact_table.horizontalHeaderItem(column).text()
            for column in range(4)
        ) == ("Apply", "Artifact", "Parameters", "Outputs")
        assert dialog.saved_artifact_table.selectionMode() == (
            QAbstractItemView.SelectionMode.NoSelection
        )
        assert dialog.saved_artifact_table.editTriggers() == (
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        assert not dialog.saved_artifact_table.isSortingEnabled()
        assert dialog.saved_artifact_table.verticalHeader().isHidden()
        assert not dialog.saved_artifact_table.horizontalHeader().isHidden()
        assert not dialog.saved_artifact_table.wordWrap()
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved SMA 20", "period=20", "sma_20"),
            ("", "Saved RSI 14", "period=14", "rsi_14"),
        )
        button_texts = {
            button.text()
            for button in (
                dialog.findChildren(QPushButton)
                + dialog.findChildren(QToolButton)
            )
            if button.isVisibleTo(dialog)
        }
        assert {"Apply", "Save", "Apply Checked Artifacts", "Close"} <= button_texts
        assert "Save Artifact" not in button_texts
        assert all("Recipe" not in text for text in button_texts)
    finally:
        dialog.close()


def test_parameters_and_canonical_calculation_intents(qapp: QApplication) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "SMA")
        period = dialog.findChild(
            QSpinBox, "research_restoration.financial_tools.parameter.period"
        )
        assert period is not None
        assert period.value() == ALL_FINANCIAL_TOOL_SPECS["sma"].parameters[0].default
        assert dialog.status_label.text() == "Ready"
        assert dialog.apply_button.isEnabled()

        apply_spy = QSignalSpy(dialog.apply_requested)
        save_spy = QSignalSpy(dialog.save_requested)
        dialog.apply_button.click()
        assert apply_spy.count() == 1
        assert save_spy.count() == 0
        apply_intent = apply_spy.at(0)[0]
        assert isinstance(apply_intent, ResearchStudyApplyIntent)
        assert apply_intent.request.tool_key == "sma"
        assert dict(apply_intent.guide_values) == {}
        dialog.save_button.click()
        assert apply_spy.count() == 1
        assert save_spy.count() == 1
        save_intent = save_spy.at(0)[0]
        assert save_intent.request == apply_intent.request
        assert dict(save_intent.guide_values) == dict(
            apply_intent.guide_values
        )
        assert dialog.isVisible() or not dialog.testAttribute(Qt.WA_DeleteOnClose)

        _select_tool(dialog, "Bollinger Bands")
        assert dialog.findChild(
            QSpinBox, "research_restoration.financial_tools.parameter.period"
        ) is not None
        std = dialog.findChild(
            QDoubleSpinBox, "research_restoration.financial_tools.parameter.std"
        )
        assert std is not None
        assert std.decimals() == 8

        _select_tool(dialog, "Delta")
        eps = dialog.findChild(
            QDoubleSpinBox, "research_restoration.financial_tools.parameter.eps"
        )
        assert eps is not None
        assert eps.decimals() == 12
        assert eps.value() == pytest.approx(1e-12)
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("tool_key", "guide_defaults"),
    (
        ("sma", {}),
        ("hck", {}),
        (
            "rsi",
            {"overbought": 70.0, "center": 50.0, "oversold": 30.0},
        ),
        (
            "arsi",
            {"overbought": 80.0, "center": 50.0, "oversold": 20.0},
        ),
        (
            "mfi",
            {"overbought": 70.0, "center": 50.0, "oversold": 30.0},
        ),
        (
            "tdirsi",
            {"overbought": 70.0, "center": 50.0, "oversold": 30.0},
        ),
        ("smi", {"zero": 0.0}),
    ),
)
def test_creation_and_edit_share_parameter_source_and_guide_controls(
    qapp: QApplication,
    tool_key: str,
    guide_defaults: dict[str, float],
) -> None:
    fixture = build_primary_chart_fixture()
    catalog = build_study_setup_catalog_fixture(fixture)
    spec = next(item for item in catalog.tools if item.key == tool_key)
    creation = ResearchFinancialToolsDialog(fixture.market_id, catalog)
    edit = None
    try:
        _select_tool(creation, spec.title)
        presentation = StudyPresentation(
            "study-parity",
            True,
            "price",
            {},
            {},
            tool_key=tool_key,
        )
        edit = ResearchStudyEditDialog(
            fixture.market_id,
            catalog,
            "study-parity",
            _default_request(spec),
            presentation,
        )

        assert tuple(creation.parameter_controls) == tuple(
            edit.parameter_controls
        )
        assert tuple(
            _control_contract(control)
            for control in creation.parameter_controls.values()
        ) == tuple(
            _control_contract(control)
            for control in edit.parameter_controls.values()
        )
        assert creation.source_selector.schema == edit.source_selector.schema
        assert tuple(creation.guide_controls) == tuple(edit.guide_controls)
        assert tuple(
            _control_contract(control)
            for control in creation.guide_controls.values()
        ) == tuple(
            _control_contract(control)
            for control in edit.guide_controls.values()
        )
        assert {
            name: control.value()
            for name, control in creation.guide_controls.items()
        } == guide_defaults
        assert {
            name: control.value()
            for name, control in edit.guide_controls.items()
        } == guide_defaults

        if tool_key == "universal_trend_classifier":
            assert creation.source_selector.schema == (
                "trend_peak",
                "trend_trough",
                "range_peak",
                "range_trough",
            )
        if tool_key == "hck":
            assert tuple(creation.parameter_controls) == (
                "fast_vwap_l",
                "slow_vwap_l",
            )
    finally:
        if edit is not None:
            edit.close()
        creation.close()


def test_creation_guide_validation_intent_purity_and_reset(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "RSI")
        assert tuple(dialog.parameter_controls) == ("period",)
        assert tuple(dialog.guide_controls) == (
            "overbought",
            "center",
            "oversold",
        )
        assert dialog.apply_button.isEnabled()
        oversold = dialog.guide_controls["oversold"]
        center = dialog.guide_controls["center"]
        overbought = dialog.guide_controls["overbought"]
        oversold.setValue(25.0)
        assert dialog.apply_button.isEnabled()
        oversold.setValue(75.0)
        assert not dialog.apply_button.isEnabled()
        oversold.setValue(25.0)
        assert dialog.apply_button.isEnabled()
        center.setValue(overbought.value())
        assert not dialog.apply_button.isEnabled()
        center.setValue(50.0)
        assert dialog.apply_button.isEnabled()

        emitted: list[object] = []
        dialog.apply_requested.connect(emitted.append)
        dialog.apply_button.click()
        assert len(emitted) == 1
        intent = emitted[0]
        assert isinstance(intent, ResearchStudyApplyIntent)
        assert dict(intent.request.parameters) == {"period": 14}
        assert dict(intent.guide_values) == {
            "overbought": 70.0,
            "center": 50.0,
            "oversold": 25.0,
        }
        with pytest.raises(TypeError):
            intent.guide_values["oversold"] = 20.0

        _select_tool(dialog, "SMI")
        dialog.guide_controls["zero"].setValue(-12.5)
        assert dialog.apply_button.isEnabled()
        _select_tool(dialog, "SMA")
        assert dialog.guide_controls == {}
        assert dict(dialog._build_apply_intent().guide_values) == {}

        _select_tool(dialog, "RSI")
        assert dialog.guide_controls["oversold"].value() == 25.0
        dialog.guide_controls["oversold"].setValue(25.0)
        dialog.close()
        dialog.prepare_for_open()
        _select_tool(dialog, "RSI")
        assert dialog.guide_controls["oversold"].value() == 25.0
    finally:
        dialog.close()


def test_per_tool_form_state_survives_switch_reopen_and_catalog_refresh(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "RSI")
        dialog.parameter_controls["period"].setValue(21)
        dialog.guide_controls["oversold"].setValue(24.0)
        _select_tool(dialog, "SMA")
        dialog.parameter_controls["period"].setValue(55)
        _select_tool(dialog, "RSI")
        assert dialog.parameter_controls["period"].value() == 21
        assert dialog.guide_controls["oversold"].value() == 24.0
        _select_tool(dialog, "SMA")
        assert dialog.parameter_controls["period"].value() == 55

        _select_tool(dialog, "Derivatives")
        option = next(
            item
            for item in dialog._catalog.ohlcv_sources
            if item.column_name == "close"
        )
        dialog.source_selector.select_option("source", option)
        selected = dialog.source_selector.selections()
        _select_tool(dialog, "SMA")
        _select_tool(dialog, "Derivatives")
        assert dialog.source_selector.selections() == selected

        dialog.close()
        dialog.prepare_for_open()
        assert dialog.tool_list.currentItem().text() == "Derivatives"
        assert dialog.source_selector.selections() == selected
        dialog.set_catalog(dialog._catalog)
        assert dialog.tool_list.currentItem().text() == "Derivatives"
        assert dialog.source_selector.selections() == selected
    finally:
        dialog.close()


def test_multi_source_empty_rows_survive_switch_reopen_catalog_and_filter(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "Percent Span Angle")
        selector = _ordinary_source_selector(dialog)
        assert _source_roles(selector) == ("source_1",)
        selector._add.click()
        selector._add.click()
        assert _source_roles(selector) == (
            "source_1",
            "source_2",
            "source_3",
        )
        source_1_option = next(
            option
            for option in dialog._catalog.study_sources
            if option.study_id == "dev-sma"
        )
        selector.select_option("source_1", source_1_option)
        selected_source_1 = selector.selections()[0]

        def assert_preserved() -> None:
            current = _ordinary_source_selector(dialog)
            assert _source_roles(current) == (
                "source_1",
                "source_2",
                "source_3",
            )
            assert current.selections() == (selected_source_1,)
            assert _source_row(current, "source_2").item.currentData() is None
            assert _source_row(current, "source_3").item.currentData() is None

        _select_tool(dialog, "SMA")
        _select_tool(dialog, "Percent Span Angle")
        assert_preserved()

        dialog.close()
        dialog.prepare_for_open()
        assert dialog.tool_list.currentItem().text() == "Percent Span Angle"
        assert_preserved()

        dialog.set_catalog(dialog._catalog)
        assert dialog.tool_list.currentItem().text() == "Percent Span Angle"
        assert_preserved()

        dialog.family_combo.setCurrentText("Indicator")
        dialog.family_combo.setCurrentText("Construct")
        _select_tool(dialog, "Percent Span Angle")
        assert_preserved()
    finally:
        dialog.close()


def test_optional_empty_mid_survives_switch_and_equivalent_catalog(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "Trap Area")
        selector = _ordinary_source_selector(dialog)
        selector._add.click()
        assert _source_roles(selector) == ("fast", "mid", "slow")
        close_option = next(
            option
            for option in dialog._catalog.ohlcv_sources
            if option.column_name == "close"
        )
        open_option = next(
            option
            for option in dialog._catalog.ohlcv_sources
            if option.column_name == "open"
        )
        selector.select_option("fast", close_option)
        selector.select_option("slow", open_option)
        selected = selector.selections()

        def assert_preserved() -> None:
            current = _ordinary_source_selector(dialog)
            assert _source_roles(current) == ("fast", "mid", "slow")
            assert current.selections() == selected
            assert _source_row(current, "mid").item.currentData() is None

        _select_tool(dialog, "SMA")
        _select_tool(dialog, "Trap Area")
        assert_preserved()

        dialog.set_catalog(dialog._catalog)
        assert dialog.tool_list.currentItem().text() == "Trap Area"
        assert_preserved()
    finally:
        dialog.close()


def test_multi_source_loss_preserves_empty_layout_without_substitution(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "Percent Span Angle")
        selector = _ordinary_source_selector(dialog)
        selector._add.click()
        selector._add.click()
        source_1_option = next(
            option
            for option in dialog._catalog.study_sources
            if option.study_id == "dev-sma"
        )
        source_3_option = next(
            option
            for option in dialog._catalog.study_sources
            if option.output_name == "bb_middle"
        )
        selector.select_option("source_1", source_1_option)
        selector.select_option("source_3", source_3_option)
        assert not dialog.apply_button.isEnabled()
        assert not dialog.save_button.isEnabled()

        replacement = replace(
            dialog._catalog,
            study_sources=tuple(
                option
                for option in dialog._catalog.study_sources
                if option != source_3_option
            ),
        )
        dialog.set_catalog(replacement)

        current = _ordinary_source_selector(dialog)
        assert _source_roles(current) == (
            "source_1",
            "source_2",
            "source_3",
        )
        assert tuple(
            selection.role for selection in current.selections()
        ) == ("source_1",)
        assert current.selections()[0].study_id == "dev-sma"
        assert _source_row(current, "source_2").item.currentData() is None
        assert _source_row(current, "source_3").item.currentData() is None
        assert dialog.apply_button.isEnabled()
        assert dialog.save_button.isEnabled()
        assert dialog.status_label.text() == "Ready"
    finally:
        dialog.close()


def test_catalog_source_loss_preserves_values_without_substitution(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "Derivatives")
        dialog.parameter_controls["order"].setValue(2)
        close_option = next(
            item
            for item in dialog._catalog.ohlcv_sources
            if item.column_name == "close"
        )
        dialog.source_selector.select_option("source", close_option)
        replacement = replace(
            dialog._catalog,
            ohlcv_sources=tuple(
                item
                for item in dialog._catalog.ohlcv_sources
                if item != close_option
            ),
        )
        dialog.set_catalog(replacement)
        assert dialog.parameter_controls["order"].value() == 2
        assert dialog.source_selector.selections() == ()
        assert not dialog.apply_button.isEnabled()
        assert not dialog.save_button.isEnabled()
        assert dialog.status_label.text()
    finally:
        dialog.close()


def test_checked_artifacts_preserve_hidden_state_and_emit_visible_order(
    qapp: QApplication,
) -> None:
    dialog = _dialog()
    try:
        for row in range(dialog.saved_artifact_table.rowCount()):
            dialog.saved_artifact_table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
            )
        assert dialog._checked_artifact_ids == {
            SMA_ARTIFACT_ID,
            RSI_ARTIFACT_ID,
        }
        dialog.family_combo.setCurrentText("Indicator")
        spy = QSignalSpy(dialog.apply_saved_artifact_requested)
        dialog.apply_saved_artifact_button.click()
        batch = spy.at(0)[0]
        assert tuple(
            request.artifact_id for request in batch.requests
        ) == (SMA_ARTIFACT_ID,)

        dialog.family_combo.setCurrentText("All")
        assert tuple(
            dialog.saved_artifact_table.item(row, 0).checkState()
            for row in range(dialog.saved_artifact_table.rowCount())
        ) == (Qt.CheckState.Checked, Qt.CheckState.Checked)
        dialog.prepare_for_open()
        dialog.set_catalog(dialog._catalog)
        assert dialog._checked_artifact_ids == {
            SMA_ARTIFACT_ID,
            RSI_ARTIFACT_ID,
        }
        dialog.set_catalog(
            replace(
                dialog._catalog,
                artifact_options=tuple(
                    option
                    for option in dialog._catalog.artifact_options
                    if option.artifact_id != RSI_ARTIFACT_ID
                ),
            )
        )
        assert dialog._checked_artifact_ids == {SMA_ARTIFACT_ID}
    finally:
        dialog.close()


def test_source_owned_parameters_use_existing_selector(qapp: QApplication) -> None:
    dialog = _dialog()
    try:
        _select_tool(dialog, "Derivatives")
        assert dialog.findChild(
            object, "research_restoration.financial_tools.parameter.source"
        ) is None
        selector = dialog.findChild(
            StudySourceSelectorWidget,
            "research_restoration.financial_tools.sources",
        )
        assert selector is dialog.source_selector
        assert selector.schema == ("source",)
        assert not dialog.apply_button.isEnabled()
        option = next(
            item
            for item in dialog._catalog.study_sources
            if item.study_id == "dev-sma" and item.output_name == "sma_20"
        )
        selector.select_option("source", option)
        assert dialog.apply_button.isEnabled()
        request = dialog._build_calculation_request()
        assert request.tool_key == "derivative"
        assert request.input_sources[0].study_id == "dev-sma"
    finally:
        dialog.close()


def test_utc_single_owner_form_and_generated_roles_are_canonical(
    qapp: QApplication,
) -> None:
    fixture = build_primary_chart_fixture()
    base_catalog = build_study_setup_catalog_fixture(fixture)
    dependencies = _peaks_owner_options("dev-peaks-troughs")
    catalog = StudySetupCatalog(
        market_id=base_catalog.market_id,
        tools=base_catalog.tools,
        ohlcv_sources=base_catalog.ohlcv_sources,
        study_sources=(*base_catalog.study_sources, *dependencies),
        artifact_options=base_catalog.artifact_options,
        artifact_rejections=base_catalog.artifact_rejections,
    )
    dialog = ResearchFinancialToolsDialog(fixture.market_id, catalog)
    try:
        _select_tool(dialog, "Universal Trend Classifier")
        for hidden_name in ("fractal_window", "peak_column", "trough_column"):
            assert dialog.findChild(
                object,
                f"research_restoration.financial_tools.parameter.{hidden_name}",
            ) is None

        trend = dialog.findChild(
            QComboBox,
            "research_restoration.financial_tools.parameter.trend_fractal_window",
        )
        range_window = dialog.findChild(
            QComboBox,
            "research_restoration.financial_tools.parameter.range_fractal_window",
        )
        assert trend is not None
        assert range_window is not None
        assert dialog._parameter_form.labelForField(trend).text() == (
            "Up/Down Trend Fractal"
        )
        assert dialog._parameter_form.labelForField(range_window).text() == (
            "Horizontal Range Fractal"
        )
        assert dialog.source_selector.schema == (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
        assert isinstance(
            dialog.source_selector, _UtcPeaksTroughsOwnerSelector
        )
        assert dialog.source_selector.owner_count == 1
        assert dialog.source_selector.selected_owner_key == (
            "study",
            "dev-peaks-troughs",
        )
        assert tuple(dialog.parameter_controls) == (
            "source",
            "trend_fractal_window",
            "min_hr_band_perc",
            "hr_trend_length",
            "hr_trend_atr_mult",
            "hr_trend_atr_len",
            "hr_trend_tol_mult",
            "hr_trend_max_gap",
            "hr_min_inside_ratio",
            "min_range_swings",
            "range_fractal_window",
            "hr_break_mode",
        )
        assert dialog.guide_controls == {}
        owner_combo = dialog.findChild(
            QComboBox,
            "research.utc_peaks_troughs_owner_selector.owner",
        )
        assert owner_combo is dialog.source_selector.owner_combo
        assert dialog.source_selector.layout().labelForField(owner_combo).text() == (
            "Peaks & Troughs Source"
        )

        trend.setCurrentIndex(trend.findData(5))
        range_window.setCurrentIndex(range_window.findData(3))

        request = dialog._build_calculation_request()
        assert request.parameters["fractal_window"] == 5
        assert request.parameters["trend_fractal_window"] == 5
        assert request.parameters["range_fractal_window"] == 3
        assert tuple(source.role for source in request.input_sources) == (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
        assert {source.study_id for source in request.input_sources} == {
            "dev-peaks-troughs"
        }
        assert tuple(source.output_name for source in request.input_sources) == (
            "peak_fractal_5",
            "trough_fractal_5",
            "peak_fractal_3",
            "trough_fractal_3",
        )
        trend.setCurrentIndex(trend.findData(7))
        range_window.setCurrentIndex(range_window.findData(5))
        changed = dialog._build_calculation_request()
        assert tuple(source.output_name for source in changed.input_sources) == (
            "peak_fractal_7",
            "trough_fractal_7",
            "peak_fractal_5",
            "trough_fractal_5",
        )
        trend.setCurrentIndex(trend.findData(5))
        same_window = dialog._build_calculation_request()
        assert tuple(source.role for source in same_window.input_sources) == (
            "trend_peak",
            "trend_trough",
            "range_peak",
            "range_trough",
        )
        assert tuple(source.output_name for source in same_window.input_sources) == (
            "peak_fractal_5",
            "trough_fractal_5",
            "peak_fractal_5",
            "trough_fractal_5",
        )
    finally:
        dialog.close()


def test_utc_owner_defaults_and_edit_restoration_are_deterministic(
    qapp: QApplication,
) -> None:
    fixture = build_primary_chart_fixture()
    base = build_study_setup_catalog_fixture(fixture)
    no_owner = ResearchFinancialToolsDialog(fixture.market_id, base)
    creation = None
    edit = None
    try:
        _select_tool(no_owner, "Universal Trend Classifier")
        assert isinstance(
            no_owner.source_selector, _UtcPeaksTroughsOwnerSelector
        )
        assert no_owner.source_selector.owner_count == 0
        assert not no_owner.apply_button.isEnabled()
        assert no_owner.status_label.text() == (
            "UTC requires a compatible Peaks & Troughs Study or Artifact."
        )

        catalog = replace(
            base,
            study_sources=(
                *base.study_sources,
                *_peaks_owner_options("peaks-a"),
                *_peaks_owner_options("peaks-b"),
            ),
        )
        creation = ResearchFinancialToolsDialog(fixture.market_id, catalog)
        _select_tool(creation, "Universal Trend Classifier")
        selector = creation.source_selector
        assert isinstance(selector, _UtcPeaksTroughsOwnerSelector)
        assert selector.owner_count == 2
        assert selector.selected_owner_key is None
        assert not creation.apply_button.isEnabled()
        selector.select_owner("study", "peaks-a")
        assert creation.apply_button.isEnabled()
        request = creation._build_calculation_request()

        edit = ResearchStudyEditDialog(
            fixture.market_id,
            catalog,
            "study-utc",
            request,
            StudyPresentation(
                "study-utc",
                True,
                "price",
                {},
                {},
                tool_key="universal_trend_classifier",
            ),
        )
        assert isinstance(edit.source_selector, _UtcPeaksTroughsOwnerSelector)
        assert edit.source_selector.selected_owner_key == ("study", "peaks-a")
        assert tuple(edit.parameter_controls) == tuple(
            creation.parameter_controls
        )
        assert not edit.apply_edit_button.isEnabled()
        edit.source_selector.select_owner("study", "peaks-b")
        assert edit.apply_edit_button.isEnabled()
        edit.source_selector.select_owner("study", "peaks-a")
        assert not edit.apply_edit_button.isEnabled()
        trend = edit.parameter_controls["trend_fractal_window"]
        trend.setCurrentIndex(trend.findData(7))
        assert edit.apply_edit_button.isEnabled()
        trend.setCurrentIndex(trend.findData(5))
        assert not edit.apply_edit_button.isEnabled()
    finally:
        if edit is not None:
            edit.close()
        if creation is not None:
            creation.close()
        no_owner.close()


def test_family_filters_and_selection_reset(qapp: QApplication) -> None:
    dialog = _dialog()
    try:
        for label, kind, count in (
            ("Indicator", "indicator", 10),
            ("Oscillator", "oscillator", 7),
            ("Construct", "construct", 8),
        ):
            dialog.family_combo.setCurrentText(label)
            assert dialog.tool_list.currentItem() is None
            specs = _tool_specs(dialog)
            assert len(specs) == count
            assert all(spec.kind == kind for spec in specs)
            assert all(spec.key != "dynamic_binning" for spec in specs)
            assert all(spec.title != "Dynamic Binning" for spec in specs)

        dialog.family_combo.setCurrentText("All")
        assert len(_tool_specs(dialog)) == 25
        _select_tool(dialog, "SMA")
        assert dialog.tool_list.currentItem() is not None
        dialog.family_combo.setCurrentText("Oscillator")
        assert dialog.tool_list.currentItem() is None
        assert dialog.parameter_controls == {}
        assert not dialog.apply_button.isEnabled()
    finally:
        dialog.close()


def test_saved_artifact_filtering_and_canonical_apply(qapp: QApplication) -> None:
    dialog = _dialog()
    try:
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved SMA 20", "period=20", "sma_20"),
            ("", "Saved RSI 14", "period=14", "rsi_14"),
        )
        _select_tool(dialog, "SMA")
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved SMA 20", "period=20", "sma_20"),
        )
        dialog.saved_artifact_table.item(0, 0).setCheckState(
            Qt.CheckState.Checked
        )
        assert dialog.apply_saved_artifact_button.isEnabled()
        spy = QSignalSpy(dialog.apply_saved_artifact_requested)
        dialog.apply_saved_artifact_button.click()
        assert spy.count() == 1
        batch = spy.at(0)[0]
        assert isinstance(batch, ResearchSavedArtifactBatchIntent)
        assert len(batch.requests) == 1
        request = batch.requests[0]
        assert request.tool_key == "sma"
        assert request.artifact_id == SMA_ARTIFACT_ID
        assert dialog.isVisible() or not dialog.testAttribute(Qt.WA_DeleteOnClose)
        tooltip = dialog.saved_artifact_table.item(0, 0).toolTip()
        assert tooltip == (
            "Artifact: Saved SMA 20\n"
            f"Artifact ID: {SMA_ARTIFACT_ID}\n"
            "Tool: sma\n"
            "Kind: indicator\n"
            "Parameters: period=20\n"
            "Outputs: sma_20"
        )
        assert all(
            SMA_ARTIFACT_ID not in dialog.saved_artifact_table.item(0, column).text()
            for column in range(4)
        )
        assert all(
            dialog.saved_artifact_table.item(0, column).toolTip() == tooltip
            for column in range(4)
        )

        dialog.family_combo.setCurrentText("All")
        _select_tool(dialog, "RSI")
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved RSI 14", "period=14", "rsi_14"),
        )
        option = dialog.saved_artifact_table.item(0, 0).data(Qt.UserRole)
        assert option.artifact_id == RSI_ARTIFACT_ID

        dialog.family_combo.setCurrentText("Indicator")
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved SMA 20", "period=20", "sma_20"),
        )
        assert not dialog.saved_artifact_table.selectedItems()
        assert dialog.apply_saved_artifact_button.isEnabled()
        dialog.family_combo.setCurrentText("Oscillator")
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "Saved RSI 14", "period=14", "rsi_14"),
        )
        dialog.family_combo.setCurrentText("Construct")
        assert _table_rows(dialog.saved_artifact_table) == ()
    finally:
        dialog.close()


def test_saved_artifact_duplicate_names_are_distinguished_by_recipe_truth(
    qapp: QApplication,
) -> None:
    fixture = build_primary_chart_fixture()
    base = build_study_setup_catalog_fixture(fixture)
    catalog = replace(
        base,
        artifact_options=(
            StudyArtifactOption(
                fixture.market_id,
                "a" * 64,
                "indicator",
                "sma",
                "SMA",
                ("sma_20",),
                parameters={"period": 20},
            ),
            StudyArtifactOption(
                fixture.market_id,
                "b" * 64,
                "indicator",
                "sma",
                "SMA",
                ("sma_200",),
                parameters={"period": 200},
            ),
        ),
    )
    dialog = ResearchFinancialToolsDialog(fixture.market_id, catalog)
    try:
        assert _table_rows(dialog.saved_artifact_table) == (
            ("", "SMA", "period=20", "sma_20"),
            ("", "SMA", "period=200", "sma_200"),
        )
    finally:
        dialog.close()


def test_saved_artifact_summaries_compact_without_truncating_tooltip(
    qapp: QApplication,
) -> None:
    fixture = build_primary_chart_fixture()
    base = build_study_setup_catalog_fixture(fixture)
    option = StudyArtifactOption(
        fixture.market_id,
        "c" * 64,
        "indicator",
        "universal_trend_classifier",
        "UTC",
        ("one", "two", "three", "four", "five"),
        parameters={
            "source": "close",
            "trend_fractal_window": 5,
            "range_fractal_window": 3,
        },
        source_bindings=(
            ("trend_peak", "peak_fractal_5"),
            ("trend_trough", "trough_fractal_5"),
            ("range_peak", "peak_fractal_3"),
            ("range_trough", "trough_fractal_3"),
        ),
    )
    dialog = ResearchFinancialToolsDialog(
        fixture.market_id,
        replace(base, artifact_options=(option,)),
    )
    try:
        assert _table_rows(dialog.saved_artifact_table) == (
            (
                "",
                "UTC",
                "source=close; trend_fractal_window=5; "
                "range_fractal_window=3; trend_peak=peak_fractal_5; ... (+3)",
                "one, two, three, ... (+2)",
            ),
        )
        tooltip = dialog.saved_artifact_table.item(0, 0).toolTip()
        assert "range_trough=trough_fractal_3" in tooltip
        assert "Outputs: one, two, three, four, five" in tooltip
        assert "... (+" not in tooltip
    finally:
        dialog.close()


def test_dev_catalog_is_complete_in_memory_fixture(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = build_primary_chart_fixture()

    def forbidden_open(*_args, **_kwargs):
        raise AssertionError("fixture catalog must not access the filesystem")

    monkeypatch.setattr(Path, "open", forbidden_open)
    catalog = build_study_setup_catalog_fixture(fixture)
    assert catalog.market_id == fixture.market_id
    assert len(catalog.tools) == 25
    assert tuple(item.key for item in catalog.tools) == tuple(
        item.key for item in RESEARCH_FINANCIAL_TOOL_SPECS
    )
    assert "dynamic_binning" not in tuple(item.key for item in catalog.tools)
    assert [item.label for item in catalog.ohlcv_sources] == [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]
    assert all(item.family == "ohlcv" for item in catalog.ohlcv_sources)
    assert catalog.study_sources
    assert {
        (item.study_id, item.output_name) for item in catalog.study_sources
    } >= {
        ("dev-sma", "sma_20"),
        ("dev-rsi", "rsi_14"),
    }
    assert len(catalog.artifact_options) == 2
    assert [item.artifact_id for item in catalog.artifact_options] == [
        SMA_ARTIFACT_ID,
        RSI_ARTIFACT_ID,
    ]
    assert [dict(item.parameters) for item in catalog.artifact_options] == [
        {"period": 20},
        {"period": 14},
    ]
    with pytest.raises(TypeError):
        build_study_setup_catalog_fixture(object())  # type: ignore[arg-type]


def test_studies_manager_structure_entries_and_forwarded_signals(
    qapp: QApplication,
) -> None:
    fixture = build_primary_chart_fixture()
    dialog = ResearchStudiesManagerDialog(fixture.market_id, fixture.study_entries)
    try:
        assert isinstance(dialog, QDialog)
        assert dialog.objectName() == "research_restoration.studies_manager"
        assert dialog.windowTitle() == "Studies — BTCUSDT · 4h"
        assert not dialog.isModal()
        assert dialog.size().width() == 860 and dialog.size().height() == 440
        assert dialog.findChild(
            object, "research_restoration.studies_manager.context"
        ).text() == "Historical Chart: Bybit_linear_BTCUSDT_4h"
        managers = dialog.findChildren(StudyManagerWidget)
        assert managers == [dialog.manager_widget]
        assert tuple(item.display_name for item in dialog.entries) == (
            "SMA 20",
            "BB 20 / 2",
            "RSI 14",
            "Volume",
        )
        assert [
            dialog.manager_widget.table.horizontalHeaderItem(index).text()
            for index in range(8)
        ] == [
            "Visible",
            "Study",
            "Tool",
            "Parameters",
            "Sources",
            "Origin",
            "Saved",
            "Pane",
        ]

        visibility = QSignalSpy(dialog.visibility_requested)
        style = QSignalSpy(dialog.style_requested)
        reset = QSignalSpy(dialog.reset_style_requested)
        save = QSignalSpy(dialog.save_requested)
        remove = QSignalSpy(dialog.remove_requested)
        assert dialog.manager_widget.select_study("dev-sma")
        dialog.manager_widget.table.item(0, 0).setCheckState(Qt.Unchecked)
        dialog.findChild(
            QPushButton, "research.study_manager.button.style"
        ).click()
        dialog.findChild(
            QPushButton, "research.study_manager.button.reset_style"
        ).click()
        dialog.findChild(
            QPushButton, "research.study_manager.button.save"
        ).click()
        dialog.findChild(
            QPushButton, "research.study_manager.button.remove"
        ).click()
        assert visibility.at(0) == ["dev-sma", False]
        assert style.at(0) == ["dev-sma"]
        assert reset.at(0) == ["dev-sma"]
        assert save.at(0) == ["dev-sma"]
        assert remove.at(0) == ["dev-sma"]

        replacement = fixture.study_entries[:2]
        dialog.set_entries(replacement)
        assert dialog.entries == replacement
    finally:
        dialog.close()


def test_no_permanent_study_manager_in_suite_or_workspace(
    qapp: QApplication,
) -> None:
    window = ResearchSuiteWindow(())
    workspace = ResearchWorkspaceWidget()
    try:
        assert window.findChildren(StudyManagerWidget) == []
        assert workspace.findChildren(StudyManagerWidget) == []
    finally:
        workspace.close()
        window.close()


def test_launcher_owns_one_dialog_per_exact_chart_and_reuses_through_detach(
    qapp: QApplication,
) -> None:
    financial: dict = {}
    studies: dict = {}
    market = MarketId("bybit", "linear", "BTCUSDT", "4h")
    first_fixture = build_chart_fixture_for_market(market, slot_id=1)
    second_fixture = build_chart_fixture_for_market(market, slot_id=5)
    first = _build_chart_panel(first_fixture, financial, studies)
    second = _build_chart_panel(second_fixture, financial, studies)
    workspace = ResearchWorkspaceWidget()
    try:
        workspace.add_chart(1, first)
        workspace.add_chart(2, second)
        first.financial_tools_button.click()
        first.studies_button.click()
        first_financial = financial[first]
        first_studies = studies[first]
        first.financial_tools_button.click()
        first.studies_button.click()
        assert financial[first] is first_financial
        assert studies[first] is first_studies

        second.financial_tools_button.click()
        second.studies_button.click()
        assert financial[second] is not first_financial
        assert studies[second] is not first_studies
        assert financial[second].windowTitle() == "Financial Tools — BTCUSDT · 4h"

        workspace.detach_chart(1)
        first.financial_tools_button.click()
        first.studies_button.click()
        assert financial[first] is first_financial
        assert studies[first] is first_studies
        workspace.dock_chart(1)
        first.financial_tools_button.click()
        first.studies_button.click()
        assert financial[first] is first_financial
        assert studies[first] is first_studies
    finally:
        for dialog in (*financial.values(), *studies.values()):
            dialog.close()
        workspace.clear_all_charts()
        workspace.close()


def test_launcher_source_preserves_isolation_and_existing_paths() -> None:
    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    assert source.count("ResearchChartPanel(") == 1
    assert "build_primary_chart_fixture()" in source
    assert "window.workspace.show_single_chart(chart_panel)" in source
    assert 'os.environ.get("LEONARDO_RESEARCH_GUI_POPULATE_8") == "1"' in source
    assert "ResearchNewChartDialog(" in source
    assert "build_chart_fixture_for_market(" in source
    assert "panel.financial_tools_requested.connect(open_financial_tools)" in source
    assert "panel.studies_requested.connect(open_studies_manager)" in source
    assert "workspace.active_slot_id" not in source
    for forbidden in (
        "LeonardoApp(",
        "GuiCompositionRoot(",
        "CoreRunner(",
        "OHLCVStore(",
        "ArtifactService(",
        "AcceptedDatasetCatalog(",
    ):
        assert forbidden not in source
