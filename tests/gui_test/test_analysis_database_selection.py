"""GUI interaction acceptance through database selection, using injected metadata."""
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton
from PySide6.QtTest import QTest
from leonardo.gui.analysis.database_presentation import DatabaseDisplayEntry, display_catalog
from leonardo.gui.display_time import format_display_timestamp_ms
from leonardo.gui.windows.analysis_suite_window import AnalysisSuiteWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def entries():
    # Two distinct database IDs intentionally share a market and a name.
    first = DatabaseDisplayEntry("a", "EMA Research", "bybit", "linear", "BTCUSDT", "4h", 10000, 12, 1704067200000, 1706745600000)
    return (first, replace(first, database_id="b", rows=90, columns=9),
            replace(first, database_id="c", name="ETH Study", exchange="binance", market_type="spot", asset="ETHUSDT", timeframe="1h", rows=1000))


@pytest.fixture
def window(qapp, entries):
    value = AnalysisSuiteWindow()
    value.set_database_catalog(entries, source_label="DEMONSTRATION METADATA — no real databases loaded")
    yield value
    value.close()
    value.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def item_for(table, identity):
    return next(table.item(row, 0) for row in range(table.rowCount())
                if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == identity)


def visible_ids(table):
    return [table.item(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(table.rowCount())]


def choose(window, *identities):
    window.open_database_selector()
    selector = window._selector
    for identity in identities:
        item_for(selector.table, identity).setCheckState(Qt.CheckState.Checked)
    selector.add_button.click()
    return selector


def test_production_starts_empty_without_demonstration_data(qapp):
    window = AnalysisSuiteWindow()
    try:
        assert window.selected_databases() == ()
        assert window.enabled_database_ids() == ()
        assert window.status_text() == "Analysis services are not connected"
        assert "No database catalogue connected" in window.catalog_label.text()
        assert not any(child.text() == "Analysis Suite" for child in window.findChildren(QLabel))
        window.open_database_selector()
        assert window._selector.table.rowCount() == 0
        assert not window._selector.add_button.isEnabled()
        assert window.findChild(QProgressBar, "analysis_suite.operation.progress").value() == 0
        assert not window.findChild(QPushButton, "analysis_suite.operation.cancel").isEnabled()
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("key,value,expected", [
    ("exchange", "bybit", {"a", "b"}), ("market_type", "spot", {"c"}),
    ("asset", "ETHUSDT", {"c"}), ("timeframe", "4h", {"a", "b"}),
])
def test_filters_and_all(window, key, value, expected):
    window.open_database_selector()
    selector = window._selector
    combo = selector.filter_for_key(key)
    assert combo.itemText(0) == "All"
    combo.setCurrentIndex(combo.findData(value))
    assert set(visible_ids(selector.table)) == expected
    combo.setCurrentIndex(0)
    assert set(visible_ids(selector.table)) == {"a", "b", "c"}


def test_hidden_checked_entries_are_included_on_accept(window):
    window.open_database_selector()
    selector = window._selector
    item_for(selector.table, "a").setCheckState(Qt.CheckState.Checked)
    combo = selector.filter_for_key("exchange")
    combo.setCurrentIndex(combo.findData("binance"))
    item_for(selector.table, "c").setCheckState(Qt.CheckState.Checked)
    assert "2 checked across all filters" in selector.count_label.text()
    selector.add_button.click()
    assert {entry.database_id for entry in window.selected_databases()} == {"a", "c"}
    assert set(window.enabled_database_ids()) == {"a", "c"}


def test_cancel_discards_staged_choices_and_reopen_restores_added_entries(window):
    choose(window, "a")
    window.open_database_selector()
    selector = window._selector
    item_for(selector.table, "a").setCheckState(Qt.CheckState.Unchecked)
    item_for(selector.table, "b").setCheckState(Qt.CheckState.Checked)
    selector.cancel_button.click()
    assert [entry.database_id for entry in window.selected_databases()] == ["a"]
    window.open_database_selector()
    assert [entry.database_id for entry in selector.selected_entries()] == ["a"]


def test_repeated_add_preserves_unchecked_use_and_deduplicates_by_id(window):
    choose(window, "a", "b")
    item_for(window.selected_table, "a").setCheckState(Qt.CheckState.Unchecked)
    choose(window, "c")
    choose(window, "a", "b", "c")
    assert len(window.selected_databases()) == 3
    assert set(window.enabled_database_ids()) == {"b", "c"}
    assert window.selection_count.text() == "3 selected · 2 checked for use"


def test_unchecking_in_selector_does_not_remove_existing_workspace_entries(window):
    choose(window, "a", "b")
    window.open_database_selector()
    item_for(window._selector.table, "a").setCheckState(Qt.CheckState.Unchecked)
    window._selector.add_button.click()
    assert len(window.selected_databases()) == 2


@pytest.mark.parametrize("column,expected", [(6, ["b", "c", "a"]), (7, ["b", "a", "c"])])
def test_numeric_sorting_uses_numbers_and_keeps_identity(window, column, expected):
    window.open_database_selector()
    selector = window._selector
    selector.table.sortItems(column, Qt.SortOrder.AscendingOrder)
    assert visible_ids(selector.table) == expected
    item_for(selector.table, "a").setCheckState(Qt.CheckState.Checked)
    selector.add_button.click()
    assert window.selected_databases()[0].database_id == "a"


def test_remove_after_sorting_targets_correct_database_and_allows_readd(window):
    choose(window, "a", "b", "c")
    assert window.selected_table.horizontalHeader().visualIndex(10) == 1
    window.selected_table.sortItems(6, Qt.SortOrder.AscendingOrder)
    row = item_for(window.selected_table, "b").row()
    window.selected_table.cellWidget(row, 10).click()
    assert {entry.database_id for entry in window.selected_databases()} == {"a", "c"}
    assert "database is unchanged" in window.status_log_text()
    choose(window, "b")
    assert len(window.selected_databases()) == 3


def test_inspector_and_timezone_display(window, entries):
    choose(window, "a")
    window.selected_table.selectRow(0)
    fields = {window.inspector.item(row, 0).text(): window.inspector.item(row, 1).text()
              for row in range(window.inspector.rowCount())}
    assert fields["Database ID"] == "a"
    assert fields["Rows"] == "10,000"
    assert fields["First Timestamp"] == format_display_timestamp_ms(entries[0].first_timestamp_ms)
    assert "(" in fields["Last Timestamp"]  # explicit UTC offset from existing display policy
    item_for(window.selected_table, "a").setCheckState(Qt.CheckState.Unchecked)
    assert window.inspector.item(window.inspector.rowCount() - 1, 1).text() == "Unchecked"
    window.remove_database("a")
    assert window.inspector.rowCount() == 0
    assert not window.empty_label.isHidden()


def test_no_matches_keeps_checks_but_empty_catalogue_disables_add(window):
    window.open_database_selector()
    selector = window._selector
    item_for(selector.table, "a").setCheckState(Qt.CheckState.Checked)
    selector.filter_for_key("exchange").setCurrentIndex(selector.filter_for_key("exchange").findData("bybit"))
    selector.filter_for_key("asset").setCurrentIndex(selector.filter_for_key("asset").findData("ETHUSDT"))
    assert selector.table.rowCount() == 0
    assert "match" in selector.empty_label.text()
    assert selector.add_button.isEnabled()
    selector.prepare(())
    assert not selector.add_button.isEnabled()


def test_close_window_rejects_open_selector(window):
    window.show()
    window.open_database_selector()
    selector = window._selector
    assert selector.isVisible()
    item_for(selector.table, "a").setCheckState(Qt.CheckState.Checked)
    window.close()
    assert not selector.isVisible()
    assert window.selected_databases() == ()


def test_ambiguous_identity_is_rejected_before_catalogue_replacement(window, entries):
    with pytest.raises(ValueError, match="unique"):
        window.set_database_catalog((entries[0], entries[0]))
    window.open_database_selector()
    assert window._selector.table.rowCount() == 3
    with pytest.raises(TypeError):
        display_catalog((object(),))


def test_action_observer_can_block_open_accept_and_remove(qapp, entries):
    decisions = []
    denied = set()
    def record(action_id, **kwargs):
        decisions.append((action_id, kwargs["window_id"]))
        return SimpleNamespace(allowed=action_id not in denied)
    window = AnalysisSuiteWindow(action_observer=SimpleNamespace(record_action=record))
    window.set_database_catalog(entries)
    try:
        denied.add("analysis_suite.action.select_databases")
        window.open_database_selector()
        assert window._selector is None
        denied.clear()
        window.open_database_selector()
        item_for(window._selector.table, "a").setCheckState(Qt.CheckState.Checked)
        denied.add("analysis_suite.database_selector.action.add")
        window._selector.add_button.click()
        assert window.selected_databases() == ()
        denied.clear()
        window._selector.add_button.click()
        denied.add("analysis_suite.action.remove_database")
        window.remove_database("a")
        assert len(window.selected_databases()) == 1
        assert ("analysis_suite.database_selector.action.add", "analysis_suite.database_selector.window") in decisions
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_keyboard_checkbox_interaction_and_dialog_escape(window, qapp):
    window.show()
    window.open_database_selector()
    table = window._selector.table
    item = item_for(table, "a")
    table.setCurrentItem(item)
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Space)
    assert item.checkState() == Qt.CheckState.Checked
    assert window._selector.add_button.isEnabled()
    QTest.keyClick(window._selector, Qt.Key.Key_Escape)
    assert not window._selector.isVisible()
    assert window.selected_databases() == ()


def test_timestamp_sorting_uses_instant_across_dst_fold(window, entries, qapp):
    from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
    prior = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, "Europe/Rome")
    try:
        # Local 02:45 CEST happens before local 02:15 CET on the autumn clock change.
        early = int(datetime.fromisoformat("2024-10-27T00:45:00+00:00").timestamp() * 1000)
        late = int(datetime.fromisoformat("2024-10-27T01:15:00+00:00").timestamp() * 1000)
        window.set_database_catalog((replace(entries[0], first_timestamp_ms=early), replace(entries[1], first_timestamp_ms=late)))
        window.open_database_selector()
        window._selector.table.sortItems(8, Qt.SortOrder.AscendingOrder)
        assert visible_ids(window._selector.table) == ["a", "b"]
        assert "02:45" in window._selector.table.item(0, 8).text()
        assert "02:15" in window._selector.table.item(1, 8).text()
    finally:
        qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, prior)


def test_existing_composition_opens_and_reuses_das_and_closes_selector(qapp, tmp_path, entries):
    from leonardo.core.app import LeonardoApp
    from leonardo.core.config import AuditConfig, load_default_config
    from leonardo.gui.composition import GuiCompositionRoot
    from tests.gui_test.test_analysis_execution_presenter import until
    app = LeonardoApp(replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False)))
    context = app.startup()
    app.start_core_runtime()
    composition = GuiCompositionRoot(context)
    main = composition.create_main_window()
    try:
        main.show()
        main.action_for_id("main_window.open_analysis_suite").trigger()
        window = composition.analysis_suite_window
        until(lambda: not composition.analysis_suite_presenter._busy)
        assert window.isVisible()
        window.set_database_catalog(entries)
        choose(window, "a")
        main.action_for_id("main_window.open_analysis_suite").trigger()
        assert composition.analysis_suite_window is window
        assert window.selected_databases()[0].database_id == "a"
        window.open_database_selector()
        main.close()
        assert composition.analysis_suite_window is None
        qapp.processEvents()
        assert app.window_registry.open_windows() == ()
    finally:
        main.close()
        app.shutdown()
        qapp.processEvents()
