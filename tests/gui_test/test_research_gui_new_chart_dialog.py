from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QPushButton,
    QTableWidget,
    QToolButton,
)

from leonardo.data import MarketId
from leonardo.gui.research import (
    ResearchChartPanel,
    ResearchNewChartDialog,
    ResearchSuiteWindow,
    ResearchWorkspaceWidget,
)
from leonardo.research.catalog import AcceptedDatasetSummary
from tools import dev_launch_research_gui_restoration as dev_launcher
from tools.research_gui_dev_fixtures import (
    RESEARCH_GUI_DATASET_FIXTURES,
    ResearchGuiDevChartFixture,
    build_chart_fixture_for_market,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _select(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    assert index > 0
    combo.setCurrentIndex(index)


def _values(combo: QComboBox) -> list[str]:
    return [str(combo.itemData(index)) for index in range(combo.count())]


def _panel(fixture: ResearchGuiDevChartFixture) -> ResearchChartPanel:
    return ResearchChartPanel(
        fixture.market_id,
        fixture.interaction_state,
        fixture.study_projections,
        fixture.study_presentations,
        fixture.study_entries,
    )


def test_dialog_structure_object_names_and_initial_state(qapp: QApplication) -> None:
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        assert isinstance(dialog, QDialog)
        assert dialog.windowTitle() == "New Research Chart"
        assert dialog.isModal()
        assert dialog.objectName() == "research_restoration.new_chart_dialog"
        assert dialog.size().width() == 460 and dialog.size().height() == 240
        assert dialog.info_label.objectName() == "research_restoration.new_chart.info"
        assert dialog.exchange_combo.objectName() == (
            "research_restoration.new_chart.exchange"
        )
        assert dialog.market_type_combo.objectName() == (
            "research_restoration.new_chart.market_type"
        )
        assert dialog.asset_combo.objectName() == (
            "research_restoration.new_chart.asset"
        )
        assert dialog.timeframe_combo.objectName() == (
            "research_restoration.new_chart.timeframe"
        )
        assert dialog.create_button.objectName() == (
            "research_restoration.new_chart.create"
        )
        assert dialog.cancel_button.objectName() == (
            "research_restoration.new_chart.cancel"
        )
        assert dialog.create_button.text() == "Create Chart"
        assert dialog.cancel_button.text() == "Cancel"
        form = next(
            item.layout()
            for item in (dialog.layout().itemAt(index) for index in range(dialog.layout().count()))
            if isinstance(item.layout(), QFormLayout)
        )
        assert [
            form.labelForField(combo).text()
            for combo in (
                dialog.exchange_combo,
                dialog.market_type_combo,
                dialog.asset_combo,
                dialog.timeframe_combo,
            )
        ] == ["Exchange", "Market Type", "Asset", "Timeframe"]
        assert dialog.exchange_combo.isEnabled()
        assert not dialog.market_type_combo.isEnabled()
        assert not dialog.asset_combo.isEnabled()
        assert not dialog.timeframe_combo.isEnabled()
        assert not dialog.create_button.isEnabled()
        assert all(
            combo.currentIndex() == 0
            and combo.itemText(0) == ""
            and combo.itemData(0) == ""
            for combo in (
                dialog.exchange_combo,
                dialog.market_type_combo,
                dialog.asset_combo,
                dialog.timeframe_combo,
            )
        )
        assert dialog.findChildren(QTableWidget) == []
        forbidden = {"Refresh", "Maintenance", "Browse"}
        assert forbidden.isdisjoint(
            button.text() for button in dialog.findChildren(QPushButton)
        )
    finally:
        dialog.close()


def test_exchange_options_and_bybit_cascade_are_exact(qapp: QApplication) -> None:
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        assert [
            dialog.exchange_combo.itemText(index)
            for index in range(dialog.exchange_combo.count())
        ] == ["", "Binance", "Bybit"]
        assert _values(dialog.exchange_combo) == ["", "binance", "bybit"]
        assert dialog.info_label.text() == "Select an exchange to continue."

        _select(dialog.exchange_combo, "bybit")
        assert _values(dialog.market_type_combo) == ["", "linear"]
        assert dialog.market_type_combo.isEnabled()
        assert dialog.info_label.text() == "Select a market type."
        _select(dialog.market_type_combo, "linear")
        assert _values(dialog.asset_combo) == ["", "BTCUSDT", "ETHUSDT"]
        assert dialog.info_label.text() == "Select an asset."
        _select(dialog.asset_combo, "BTCUSDT")
        assert _values(dialog.timeframe_combo) == ["", "4h"]
        assert dialog.info_label.text() == "Select a timeframe."
        _select(dialog.timeframe_combo, "4h")
        assert dialog.create_button.isEnabled()
        assert dialog.info_label.text() == (
            "Selection complete. Create Chart is available."
        )

        dialog.asset_combo.setCurrentIndex(0)
        _select(dialog.asset_combo, "ETHUSDT")
        assert _values(dialog.timeframe_combo) == ["", "1h"]
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("symbol", "timeframe"), (("BTCUSDT", "15m"), ("ETHUSDT", "1d"))
)
def test_binance_cascade_is_exact(
    qapp: QApplication, symbol: str, timeframe: str
) -> None:
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        _select(dialog.exchange_combo, "binance")
        assert _values(dialog.market_type_combo) == ["", "spot"]
        _select(dialog.market_type_combo, "spot")
        _select(dialog.asset_combo, symbol)
        assert _values(dialog.timeframe_combo) == ["", timeframe]
    finally:
        dialog.close()


def test_upstream_changes_clear_downstream_selection(qapp: QApplication) -> None:
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        _select(dialog.exchange_combo, "bybit")
        _select(dialog.market_type_combo, "linear")
        _select(dialog.asset_combo, "BTCUSDT")
        _select(dialog.timeframe_combo, "4h")
        assert dialog.create_button.isEnabled()

        _select(dialog.exchange_combo, "binance")
        assert dialog.market_type_combo.currentIndex() == 0
        assert dialog.asset_combo.currentIndex() == 0
        assert dialog.timeframe_combo.currentIndex() == 0
        assert not dialog.asset_combo.isEnabled()
        assert not dialog.timeframe_combo.isEnabled()
        assert not dialog.create_button.isEnabled()

        _select(dialog.market_type_combo, "spot")
        _select(dialog.asset_combo, "BTCUSDT")
        _select(dialog.timeframe_combo, "15m")
        dialog.market_type_combo.setCurrentIndex(0)
        assert dialog.asset_combo.currentIndex() == 0
        assert dialog.timeframe_combo.currentIndex() == 0
        assert not dialog.asset_combo.isEnabled()
        assert not dialog.timeframe_combo.isEnabled()
        assert not dialog.create_button.isEnabled()

        _select(dialog.market_type_combo, "spot")
        _select(dialog.asset_combo, "ETHUSDT")
        _select(dialog.timeframe_combo, "1d")
        dialog.asset_combo.setCurrentIndex(0)
        assert dialog.timeframe_combo.currentIndex() == 0
        assert not dialog.timeframe_combo.isEnabled()
        assert not dialog.create_button.isEnabled()

        dialog.exchange_combo.setCurrentIndex(0)
        assert not dialog.market_type_combo.isEnabled()
        assert not dialog.create_button.isEnabled()
    finally:
        dialog.close()


def test_create_returns_exact_summary_and_cancel_returns_none(qapp: QApplication) -> None:
    expected = RESEARCH_GUI_DATASET_FIXTURES[1]
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    accepted = QSignalSpy(dialog.accepted)
    _select(dialog.exchange_combo, expected.market_id.exchange)
    _select(dialog.market_type_combo, expected.market_id.market_type)
    _select(dialog.asset_combo, expected.market_id.symbol)
    assert not dialog.create_button.isEnabled()
    _select(dialog.timeframe_combo, expected.market_id.timeframe)
    dialog.create_button.click()
    assert accepted.count() == 1
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_dataset_summary() is expected

    cancelled = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    rejected = QSignalSpy(cancelled.rejected)
    _select(cancelled.exchange_combo, "bybit")
    cancelled.cancel_button.click()
    assert rejected.count() == 1
    assert cancelled.result() == QDialog.DialogCode.Rejected
    assert cancelled.selected_dataset_summary() is None


def test_reset_selection_preserves_catalog_and_restores_full_cascade(
    qapp: QApplication,
) -> None:
    dialog = ResearchNewChartDialog(RESEARCH_GUI_DATASET_FIXTURES)
    catalog = dialog._dataset_summaries
    try:
        first = RESEARCH_GUI_DATASET_FIXTURES[0]
        _select(dialog.exchange_combo, first.market_id.exchange)
        _select(dialog.market_type_combo, first.market_id.market_type)
        _select(dialog.asset_combo, first.market_id.symbol)
        _select(dialog.timeframe_combo, first.market_id.timeframe)
        dialog._accept_selection()
        assert dialog.selected_dataset_summary() is first

        dialog.reset_selection()

        assert dialog._dataset_summaries is catalog
        assert dialog.selected_dataset_summary() is None
        assert dialog.exchange_combo.currentIndex() == 0
        assert dialog.exchange_combo.isEnabled()
        assert dialog.info_label.text() == "Select an exchange to continue."
        for combo in (
            dialog.market_type_combo,
            dialog.asset_combo,
            dialog.timeframe_combo,
        ):
            assert combo.currentIndex() == 0
            assert not combo.isEnabled()
        assert not dialog.create_button.isEnabled()

        second = RESEARCH_GUI_DATASET_FIXTURES[-1]
        _select(dialog.exchange_combo, second.market_id.exchange)
        _select(dialog.market_type_combo, second.market_id.market_type)
        _select(dialog.asset_combo, second.market_id.symbol)
        _select(dialog.timeframe_combo, second.market_id.timeframe)
        assert dialog.create_button.isEnabled()
        dialog._accept_selection()
        assert dialog.selected_dataset_summary() is second
        assert dialog._dataset_summaries is catalog
    finally:
        dialog.close()


def test_dev_launcher_reuses_blank_new_chart_dialog(
    qapp: QApplication, monkeypatch
) -> None:
    monkeypatch.delenv("LEONARDO_RESEARCH_GUI_POPULATE_8", raising=False)
    monkeypatch.setattr(QApplication, "exec", lambda _self: 0)
    invocations: list[tuple[int, object]] = []

    def execute(dialog: ResearchNewChartDialog) -> QDialog.DialogCode:
        invocations.append((id(dialog), dialog._dataset_summaries))
        assert dialog.selected_dataset_summary() is None
        assert dialog.exchange_combo.currentIndex() == 0
        assert dialog.exchange_combo.isEnabled()
        assert not dialog.market_type_combo.isEnabled()
        assert not dialog.asset_combo.isEnabled()
        assert not dialog.timeframe_combo.isEnabled()
        assert not dialog.create_button.isEnabled()
        target = RESEARCH_GUI_DATASET_FIXTURES[len(invocations) - 1]
        _select(dialog.exchange_combo, target.market_id.exchange)
        _select(dialog.market_type_combo, target.market_id.market_type)
        _select(dialog.asset_combo, target.market_id.symbol)
        _select(dialog.timeframe_combo, target.market_id.timeframe)
        dialog._accept_selection()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ResearchNewChartDialog, "exec", execute)
    assert dev_launcher.main() == 0
    qapp.processEvents()
    window = next(
        widget
        for widget in qapp.topLevelWidgets()
        if widget.objectName() == "research_restoration.window"
        and widget.isVisible()
        and hasattr(widget, "_dev_tracked_windows")
    )
    tracked = window._dev_tracked_windows
    try:
        window.new_chart_requested.emit()
        window.new_chart_requested.emit()
        qapp.processEvents()
        assert len(invocations) == 2
        assert invocations[0][0] == invocations[1][0]
        assert invocations[0][1] is invocations[1][1]
        assert window.workspace.slot_ids() == (1, 2, 3)
        assert tracked["research_restoration.new_chart"] is not None
    finally:
        for widget in tuple(tracked.values()):
            widget.close()
        window.close()
        qapp.processEvents()


def test_no_data_and_invalid_constructor_inputs(qapp: QApplication) -> None:
    dialog = ResearchNewChartDialog(())
    try:
        assert not dialog.exchange_combo.isEnabled()
        assert not dialog.create_button.isEnabled()
        assert dialog.info_label.text() == (
            "No accepted OHLCV datasets are available for Research."
        )
    finally:
        dialog.close()
    with pytest.raises(ValueError):
        ResearchNewChartDialog(
            (RESEARCH_GUI_DATASET_FIXTURES[0], RESEARCH_GUI_DATASET_FIXTURES[0])
        )
    with pytest.raises(TypeError):
        ResearchNewChartDialog((object(),))


def test_suite_existing_action_emits_new_chart_intent_once(qapp: QApplication) -> None:
    window = ResearchSuiteWindow(RESEARCH_GUI_DATASET_FIXTURES)
    try:
        action = window.action_for_text("New Chart...")
        spy = QSignalSpy(window.new_chart_requested)
        action.trigger()
        assert spy.count() == 1
        assert window.file_menu.actions()[0] is action
        permanent = window.findChildren(QPushButton) + window.findChildren(QToolButton)
        assert all(button.text() != "New Chart..." for button in permanent)
        activity = window.findChild(
            object, "research_restoration.activity.log"
        ).toPlainText()
        assert activity.splitlines()[-1] == "New Chart... requested"
    finally:
        window.close()


def test_workspace_next_free_logical_slot_and_capacity(qapp: QApplication) -> None:
    workspace = ResearchWorkspaceWidget()
    panels: list[ResearchChartPanel] = []
    try:
        assert workspace.can_add_chart()
        assert workspace.next_free_slot_id() == 1
        for slot_id in (1, 2, 4):
            fixture = build_chart_fixture_for_market(
                RESEARCH_GUI_DATASET_FIXTURES[0].market_id,
                slot_id=slot_id,
            )
            panel = _panel(fixture)
            panels.append(panel)
            workspace.add_chart(slot_id, panel)
        assert workspace.next_free_slot_id() == 3
        for slot_id in (3, 5, 6, 7, 8):
            fixture = build_chart_fixture_for_market(
                RESEARCH_GUI_DATASET_FIXTURES[0].market_id,
                slot_id=slot_id,
            )
            panel = _panel(fixture)
            panels.append(panel)
            workspace.add_chart(slot_id, panel)
        assert not workspace.can_add_chart()
        assert workspace.next_free_slot_id() is None
    finally:
        workspace.clear_all_charts()
        workspace.close()


def test_market_fixture_factory_ids_validation_and_independence() -> None:
    primary_market = RESEARCH_GUI_DATASET_FIXTURES[0].market_id
    other_market = RESEARCH_GUI_DATASET_FIXTURES[1].market_id
    primary = build_chart_fixture_for_market(primary_market, slot_id=1)
    slot_one_other = build_chart_fixture_for_market(other_market, slot_id=1)
    first = build_chart_fixture_for_market(primary_market, slot_id=6)
    second = build_chart_fixture_for_market(primary_market, slot_id=6)
    assert primary.market_id == primary_market
    assert [item.study_id for item in primary.study_projections] == [
        "dev-sma",
        "dev-bb",
        "dev-rsi",
        "dev-volume",
    ]
    assert [item.study_id for item in slot_one_other.study_projections] == [
        "dev1-sma",
        "dev1-bb",
        "dev1-rsi",
        "dev1-volume",
    ]
    assert [item.study_id for item in first.study_projections] == [
        "dev6-sma",
        "dev6-bb",
        "dev6-rsi",
        "dev6-volume",
    ]
    assert first.interaction_state is not second.interaction_state
    assert first.interaction_state.viewport is not second.interaction_state.viewport
    assert first.interaction_state.resident is not second.interaction_state.resident
    with pytest.raises(TypeError):
        build_chart_fixture_for_market("bybit", slot_id=1)  # type: ignore[arg-type]
    for invalid in (False, 0, 9):
        with pytest.raises(ValueError):
            build_chart_fixture_for_market(primary_market, slot_id=invalid)


def test_dev_launcher_preserves_paths_and_new_chart_isolation() -> None:
    source = Path("tools/dev_launch_research_gui_restoration.py").read_text(
        encoding="utf-8"
    )
    assert "build_primary_chart_fixture()" in source
    assert "window.workspace.show_single_chart(chart_panel)" in source
    assert 'os.environ.get("LEONARDO_RESEARCH_GUI_POPULATE_8") == "1"' in source
    assert "build_additional_workspace_chart_fixtures()" in source
    assert "window.workspace.add_chart(slot_id," in source
    assert "window.new_chart_requested.connect(open_new_chart)" in source
    assert "ResearchNewChartDialog(" in source
    assert "build_chart_fixture_for_market(" in source
    assert "window.workspace.next_free_slot_id()" in source
    assert "window.workspace.set_active_slot(slot_id)" in source
    assert source.count("ResearchChartPanel(") == 1
    for forbidden in (
        "LeonardoApp(",
        "GuiCompositionRoot(",
        "CoreRunner(",
        "OHLCVStore(",
        "ArtifactService(",
        "AcceptedDatasetCatalog(",
    ):
        assert forbidden not in source
