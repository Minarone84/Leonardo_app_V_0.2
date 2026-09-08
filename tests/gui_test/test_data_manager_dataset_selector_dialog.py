from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QPushButton,
    QTextBrowser,
)

from leonardo.data import MarketId
from leonardo.data_manager import DataManagerCatalogSnapshot, DataManagerDatasetEntry
from leonardo.gui.windows.data_manager_dataset_selector_dialog import (
    DATA_MANAGER_DATASET_SEARCH_HELP_WINDOW_ID,
    DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
    DataManagerDatasetSelectorDialog,
)


BYBIT_BTC = MarketId("bybit", "linear", "BTCUSDT", "4h")
BYBIT_LINK = MarketId("bybit", "linear", "LINKUSDT", "1h")
BYBIT_INVERSE = MarketId("bybit", "inverse", "BTCUSD", "1d")
BINANCE_ETH = MarketId("binance", "spot", "ETHUSDT", "15m")
REJECTED = MarketId("kraken", "spot", "XRPUSD", "1h")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _accepted(
    market: MarketId,
    *,
    source: str = "canonical download",
    warning: str = "verified",
) -> DataManagerDatasetEntry:
    return DataManagerDatasetEntry(
        market,
        True,
        2,
        0,
        3_600_000,
        source=source,
        persistence_status="committed",
        validation_status="ok",
        warnings=(warning,),
    )


def _rejected() -> DataManagerDatasetEntry:
    return DataManagerDatasetEntry(
        REJECTED,
        False,
        source="legacy import",
        persistence_status="present",
        validation_status="invalid",
        rejection_code="schema",
        rejection_reason="missing close column",
        warnings=("timestamp gap detected",),
    )


def _snapshot() -> DataManagerCatalogSnapshot:
    return DataManagerCatalogSnapshot(
        (
            _accepted(BYBIT_BTC),
            _accepted(BYBIT_LINK, warning="link dataset verified"),
            _accepted(BYBIT_INVERSE),
            _accepted(BINANCE_ETH, source="provider download"),
            _rejected(),
        )
    )


def _sorting_snapshot() -> DataManagerCatalogSnapshot:
    return DataManagerCatalogSnapshot(
        (
            DataManagerDatasetEntry(
                BYBIT_BTC, True, 100, 7_200_000, 10_800_000,
                source="canonical download", persistence_status="committed",
                validation_status="ok", warnings=("verified",),
            ),
            DataManagerDatasetEntry(
                BYBIT_LINK, True, 2, 0, 3_600_000,
                source="canonical download", persistence_status="committed",
                validation_status="ok", warnings=("verified",),
            ),
            DataManagerDatasetEntry(
                BYBIT_INVERSE, True, 10, 3_600_000, 7_200_000,
                source="canonical download", persistence_status="committed",
                validation_status="ok", warnings=("verified",),
            ),
            DataManagerDatasetEntry(
                BINANCE_ETH, True, 20, 10_800_000, 14_400_000,
                source="provider download", persistence_status="committed",
                validation_status="ok", warnings=("verified",),
            ),
            _rejected(),
        )
    )


def _row_for_symbol(dialog: DataManagerDatasetSelectorDialog, symbol: str) -> int:
    table = dialog.table_for_id("data_manager.table.datasets")
    symbol_column = _dataset_column(table, "Symbol")
    for row in range(table.rowCount()):
        if table.item(row, symbol_column).text() == symbol:
            return row
    raise AssertionError(f"symbol not visible: {symbol}")


def _combo(dialog: DataManagerDatasetSelectorDialog, key: str):
    return dialog.filter_for_id(f"data_manager.dataset_selector.filter.{key}")


def _combo_values(
    dialog: DataManagerDatasetSelectorDialog,
    key: str,
) -> tuple[str, ...]:
    combo = _combo(dialog, key)
    return tuple(combo.itemText(index) for index in range(combo.count()))


def _select_combo(
    dialog: DataManagerDatasetSelectorDialog,
    key: str,
    value: str,
) -> None:
    combo = _combo(dialog, key)
    index = combo.findData(value)
    assert index >= 0, (key, value, _combo_values(dialog, key))
    combo.setCurrentIndex(index)
    QCoreApplication.processEvents()


def _header_texts(table) -> tuple[str, ...]:
    return tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    )


def _dataset_column(table, label: str) -> int:
    return _header_texts(table).index(label)


def _dataset_column_values(table, label: str) -> tuple[str, ...]:
    column = _dataset_column(table, label)
    return tuple(
        table.item(row, column).text() for row in range(table.rowCount())
    )


def _click_dataset_header(table, label: str) -> None:
    table.horizontalHeader().sectionClicked.emit(_dataset_column(table, label))
    QCoreApplication.processEvents()


def _dataset_checkbox(
    dialog: DataManagerDatasetSelectorDialog,
    symbol: str,
) -> QCheckBox:
    table = dialog.table_for_id("data_manager.table.datasets")
    holder = table.cellWidget(_row_for_symbol(dialog, symbol), 0)
    assert holder is not None
    checkbox = holder.findChild(QCheckBox)
    assert checkbox is not None
    return checkbox


def test_dialog_structure_removes_old_text_and_labels_both_searches(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        assert dialog.property("object_id") == DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID
        assert dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.instructions",
        ) is None
        assert dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.current_market",
        ) is None
        id_label = dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.text",
        )
        source_label = dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.source_reason",
        )
        assert id_label is not None and id_label.text() == "Dataset ID / State"
        assert source_label is not None
        assert source_label.text() == "Source / Warning / Reason"
        assert dialog.filter_for_id(
            "data_manager.dataset_selector.filter.text"
        ).placeholderText().startswith("Example:")
        assert dialog.filter_for_id(
            "data_manager.dataset_selector.filter.source_reason"
        ).placeholderText().startswith("Example:")
        active_label = dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.active_dataset",
        )
        active_table = dialog.table_for_id(
            "data_manager.dataset_selector.table.active_dataset"
        )
        assert active_label is not None and active_label.isHidden()
        assert active_table.isHidden()
        assert active_table.rowCount() == 0
    finally:
        dialog.close()


def test_dropdowns_cascade_left_to_right_and_filter_the_table(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        assert _combo_values(dialog, "exchange") == (
            "All",
            "binance",
            "bybit",
            "kraken",
        )
        _select_combo(dialog, "exchange", "bybit")
        assert _combo_values(dialog, "market_type") == (
            "All",
            "inverse",
            "linear",
        )
        _select_combo(dialog, "market_type", "linear")
        assert _combo_values(dialog, "symbol") == (
            "All",
            "BTCUSDT",
            "LINKUSDT",
        )
        _select_combo(dialog, "symbol", "LINKUSDT")
        assert _combo_values(dialog, "timeframe") == ("All", "1h")
        assert "4h" not in _combo_values(dialog, "timeframe")
        _select_combo(dialog, "timeframe", "1h")
        table = dialog.table_for_id("data_manager.table.datasets")
        assert table.rowCount() == 1
        assert table.item(0, _dataset_column(table, "Exchange")).text() == "bybit"
        assert table.item(0, _dataset_column(table, "Market Type")).text() == "linear"
        assert table.item(0, _dataset_column(table, "Symbol")).text() == "LINKUSDT"
        assert table.item(0, _dataset_column(table, "Timeframe")).text() == "1h"
    finally:
        dialog.close()


def test_valid_downstream_values_survive_and_invalid_values_reset(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        _select_combo(dialog, "market_type", "linear")
        _select_combo(dialog, "symbol", "LINKUSDT")
        _select_combo(dialog, "timeframe", "1h")
        _select_combo(dialog, "exchange", "bybit")
        assert _combo(dialog, "market_type").currentData() == "linear"
        assert _combo(dialog, "symbol").currentData() == "LINKUSDT"
        assert _combo(dialog, "timeframe").currentData() == "1h"

        _select_combo(dialog, "symbol", "BTCUSDT")
        assert _combo_values(dialog, "timeframe") == ("All", "4h")
        assert _combo(dialog, "timeframe").currentData() == ""

        _select_combo(dialog, "exchange", "binance")
        assert _combo(dialog, "market_type").currentData() == ""
        assert _combo_values(dialog, "market_type") == ("All", "spot")
        assert _combo(dialog, "symbol").currentData() == ""
        assert _combo_values(dialog, "symbol") == ("All", "ETHUSDT")
        assert _combo_values(dialog, "timeframe") == ("All", "15m")
    finally:
        dialog.close()


def test_two_text_searches_combine_with_dropdowns_using_and(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        _select_combo(dialog, "exchange", "bybit")
        _select_combo(dialog, "market_type", "linear")
        id_state = dialog.filter_for_id(
            "data_manager.dataset_selector.filter.text"
        )
        source_reason = dialog.filter_for_id(
            "data_manager.dataset_selector.filter.source_reason"
        )
        id_state.setText("linkusdt")
        source_reason.setText("link dataset")
        QCoreApplication.processEvents()
        table = dialog.table_for_id("data_manager.table.datasets")
        assert table.rowCount() == 1
        assert table.item(0, _dataset_column(table, "Symbol")).text() == "LINKUSDT"
        source_reason.setText("legacy import")
        QCoreApplication.processEvents()
        assert table.rowCount() == 0
        id_state.clear()
        source_reason.setText("missing close")
        QCoreApplication.processEvents()
        assert table.rowCount() == 0
        _select_combo(dialog, "exchange", "kraken")
        QCoreApplication.processEvents()
        assert table.rowCount() == 1
        assert table.item(0, _dataset_column(table, "Symbol")).text() == "XRPUSD"
    finally:
        dialog.close()


def test_all_button_resets_every_filter_and_restores_full_catalog(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        dialog.set_current_market(BYBIT_LINK)
        _select_combo(dialog, "exchange", "bybit")
        _select_combo(dialog, "market_type", "linear")
        _select_combo(dialog, "symbol", "LINKUSDT")
        _select_combo(dialog, "timeframe", "1h")
        dialog.filter_for_id(
            "data_manager.dataset_selector.filter.text"
        ).setText("accepted")
        dialog.filter_for_id(
            "data_manager.dataset_selector.filter.source_reason"
        ).setText("verified")
        dialog.button_for_id(
            "data_manager.dataset_selector.button.show_all"
        ).click()
        QCoreApplication.processEvents()
        assert all(_combo(dialog, key).currentData() == "" for key in (
            "exchange",
            "market_type",
            "symbol",
            "timeframe",
        ))
        assert not dialog.filter_for_id(
            "data_manager.dataset_selector.filter.text"
        ).text()
        assert not dialog.filter_for_id(
            "data_manager.dataset_selector.filter.source_reason"
        ).text()
        table = dialog.table_for_id("data_manager.table.datasets")
        assert table.rowCount() == len(_snapshot().datasets)
        rows = table.selectionModel().selectedRows()
        assert len(rows) == 1
        assert table.item(
            rows[0].row(), _dataset_column(table, "Symbol")
        ).text() == "LINKUSDT"
    finally:
        dialog.close()


def test_active_dataset_uses_one_row_matching_table_and_hides_when_absent(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        dialog.set_current_market(BYBIT_BTC)
        QCoreApplication.processEvents()
        active_label = dialog.findChild(
            QLabel,
            "data_manager.dataset_selector.label.active_dataset",
        )
        active = dialog.table_for_id(
            "data_manager.dataset_selector.table.active_dataset"
        )
        catalog = dialog.table_for_id("data_manager.table.datasets")
        assert active_label is not None and not active_label.isHidden()
        assert not active.isHidden()
        assert active.rowCount() == 1
        assert active.item(0, 2).text() == "BTCUSDT"
        assert active.selectionMode() == QAbstractItemView.SelectionMode.NoSelection
        assert _header_texts(catalog)[0] == "Select"
        assert _header_texts(active) == _header_texts(catalog)[1:]
        rows = catalog.selectionModel().selectedRows()
        assert len(rows) == 1
        assert catalog.item(
            rows[0].row(), _dataset_column(catalog, "Symbol")
        ).text() == "BTCUSDT"

        dialog.set_current_market(None)
        QCoreApplication.processEvents()
        assert active_label.isHidden()
        assert active.isHidden()
        assert active.rowCount() == 0
    finally:
        dialog.close()


def test_filter_minimum_widths_and_table_columns_fit_contents(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        dialog.set_current_market(BYBIT_LINK)
        dialog.show()
        QCoreApplication.processEvents()
        for key in ("exchange", "market_type", "symbol", "timeframe"):
            combo = _combo(dialog, key)
            label = dialog.findChild(
                QLabel,
                f"data_manager.dataset_selector.label.{key}",
            )
            assert label is not None
            item_width = max(
                combo.fontMetrics().horizontalAdvance(combo.itemText(index))
                for index in range(combo.count())
            )
            label_width = label.fontMetrics().horizontalAdvance(label.text())
            expected_text_width = math.ceil(max(item_width, label_width) * 1.5)
            assert combo.minimumWidth() >= expected_text_width
            assert combo.width() >= combo.minimumWidth()

        for table_id in (
            "data_manager.dataset_selector.table.active_dataset",
            "data_manager.table.datasets",
        ):
            table = dialog.table_for_id(table_id)
            for column in range(table.columnCount()):
                if table.cellWidget(0, column) is not None:
                    continue
                visible_text = [
                    table.horizontalHeaderItem(column).text(),
                    *(
                        table.item(row, column).text()
                        for row in range(table.rowCount())
                    ),
                ]
                text_width = max(
                    table.fontMetrics().horizontalAdvance(value)
                    for value in visible_text
                )
                assert table.columnWidth(column) >= text_width
    finally:
        dialog.close()


def test_human_time_rejected_gating_and_exact_selection_emission(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    emitted: list[MarketId] = []
    try:
        dialog.set_catalog(_snapshot())
        table = dialog.table_for_id("data_manager.table.datasets")
        btc_row = _row_for_symbol(dialog, "BTCUSDT")
        assert table.item(
            btc_row, _dataset_column(table, "First Data")
        ).text() == "1970-01-01 01:00:00 CET (+01:00)"
        assert table.item(
            btc_row, _dataset_column(table, "Last Data")
        ).text() == "1970-01-01 02:00:00 CET (+01:00)"
        assert table.item(btc_row, _dataset_column(table, "Rows")).text() == "2"

        rejected_row = _row_for_symbol(dialog, "XRPUSD")
        table.selectRow(rejected_row)
        QCoreApplication.processEvents()
        assert "missing close column" in table.item(
            rejected_row, _dataset_column(table, "Details")
        ).text()
        assert dialog.selected_market_id() is None
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()

        _dataset_checkbox(dialog, "LINKUSDT").setChecked(True)
        dialog.market_selected.connect(emitted.append)
        dialog.button_for_id("data_manager.dataset_selector.button.select").click()
        assert emitted == [BYBIT_LINK]
    finally:
        dialog.close()


def test_dataset_navigation_table_uses_typed_sorting_and_excludes_active_table(
    qapp,
) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_sorting_snapshot())
        table = dialog.table_for_id("data_manager.table.datasets")
        active = dialog.table_for_id(
            "data_manager.dataset_selector.table.active_dataset"
        )
        header = table.horizontalHeader()

        assert header.sectionsClickable()
        assert not header.isSortIndicatorShown()
        assert _dataset_column_values(table, "Rows") == ("20", "10", "100", "2", "")
        assert not active.isSortingEnabled()
        assert not active.horizontalHeader().isSortIndicatorShown()

        _click_dataset_header(table, "Symbol")
        assert _dataset_column_values(table, "Symbol") == (
            "BTCUSD", "BTCUSDT", "ETHUSDT", "LINKUSDT", "XRPUSD"
        )
        assert header.sortIndicatorSection() == _dataset_column(table, "Symbol")
        assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        _click_dataset_header(table, "Symbol")
        assert _dataset_column_values(table, "Symbol") == (
            "XRPUSD", "LINKUSDT", "ETHUSDT", "BTCUSDT", "BTCUSD"
        )
        assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

        _click_dataset_header(table, "Rows")
        assert _dataset_column_values(table, "Rows") == ("2", "10", "20", "100", "")
        _click_dataset_header(table, "First Data")
        assert _dataset_column_values(table, "First Data") == (
            "1970-01-01 01:00:00 CET (+01:00)",
            "1970-01-01 02:00:00 CET (+01:00)",
            "1970-01-01 03:00:00 CET (+01:00)",
            "1970-01-01 04:00:00 CET (+01:00)",
            "",
        )
        _click_dataset_header(table, "First Data")
        assert _dataset_column_values(table, "First Data") == (
            "1970-01-01 04:00:00 CET (+01:00)",
            "1970-01-01 03:00:00 CET (+01:00)",
            "1970-01-01 02:00:00 CET (+01:00)",
            "1970-01-01 01:00:00 CET (+01:00)",
            "",
        )
        _click_dataset_header(table, "Last Data")
        assert _dataset_column_values(table, "Last Data") == (
            "1970-01-01 02:00:00 CET (+01:00)",
            "1970-01-01 03:00:00 CET (+01:00)",
            "1970-01-01 04:00:00 CET (+01:00)",
            "1970-01-01 05:00:00 CET (+01:00)",
            "",
        )
    finally:
        dialog.close()


def test_dataset_sort_preserves_selection_filters_search_show_all_and_refresh(
    qapp,
) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        snapshot = _sorting_snapshot()
        dialog.set_catalog(snapshot)
        table = dialog.table_for_id("data_manager.table.datasets")
        _dataset_checkbox(dialog, "LINKUSDT").setChecked(True)
        assert dialog.selected_market_id() == BYBIT_LINK

        _click_dataset_header(table, "Rows")
        assert dialog.selected_market_id() == BYBIT_LINK
        assert _dataset_column_values(table, "Rows") == ("2", "10", "20", "100", "")

        _select_combo(dialog, "exchange", "bybit")
        assert _dataset_column_values(table, "Rows") == ("2", "10", "100")
        assert dialog.selected_market_id() == BYBIT_LINK

        search = dialog.filter_for_id("data_manager.dataset_selector.filter.text")
        search.setText("BTC")
        QCoreApplication.processEvents()
        assert _dataset_column_values(table, "Rows") == ("10", "100")
        search.clear()
        QCoreApplication.processEvents()
        assert _dataset_column_values(table, "Rows") == ("2", "10", "100")

        dialog.button_for_id("data_manager.dataset_selector.button.show_all").click()
        QCoreApplication.processEvents()
        assert _dataset_column_values(table, "Rows") == ("2", "10", "20", "100", "")
        _dataset_checkbox(dialog, "LINKUSDT").setChecked(True)
        assert dialog.selected_market_id() == BYBIT_LINK

        dialog.set_catalog(
            DataManagerCatalogSnapshot(tuple(reversed(snapshot.datasets)))
        )
        assert _dataset_column_values(table, "Rows") == ("2", "10", "20", "100", "")
        assert dialog.selected_market_id() == BYBIT_LINK
        dialog.set_current_market(BYBIT_LINK)
        assert dialog.selected_market_id() == BYBIT_LINK
    finally:
        dialog.close()


def test_dataset_checkboxes_are_exact_selection_authority(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    emitted: list[MarketId] = []
    try:
        dialog.set_catalog(_snapshot())
        dialog.set_current_market(BYBIT_LINK)
        table = dialog.table_for_id("data_manager.table.datasets")
        assert _header_texts(table)[0] == "Select"
        link_check = _dataset_checkbox(dialog, "LINKUSDT")
        btc_check = _dataset_checkbox(dialog, "BTCUSDT")
        assert link_check.isChecked() and not btc_check.isChecked()
        assert "indicator:checked" in link_check.styleSheet()
        assert "indicator:unchecked" in link_check.styleSheet()

        link_check.setChecked(False)
        assert dialog.selected_market_id() is None
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
        table.selectRow(_row_for_symbol(dialog, "BTCUSDT"))
        assert dialog.selected_market_id() is None

        _dataset_checkbox(dialog, "BTCUSDT").setChecked(True)
        assert dialog.selected_market_id() == BYBIT_BTC
        assert dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
        _dataset_checkbox(dialog, "LINKUSDT").setChecked(True)
        assert dialog.selected_market_id() is None
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()

        _dataset_checkbox(dialog, "LINKUSDT").setChecked(False)
        _click_dataset_header(table, "Rows")
        assert dialog.selected_market_id() == BYBIT_BTC

        _select_combo(dialog, "symbol", "LINKUSDT")
        assert dialog.selected_market_id() is None
        dialog.button_for_id("data_manager.dataset_selector.button.show_all").click()
        _dataset_checkbox(dialog, "LINKUSDT").setChecked(True)
        dialog.market_selected.connect(emitted.append)
        dialog.button_for_id("data_manager.dataset_selector.button.select").click()
        assert emitted == [BYBIT_LINK]
    finally:
        dialog.close()


def test_search_help_is_reusable_catalog_aware_and_closable(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    try:
        dialog.set_catalog(_snapshot())
        dialog.show()
        help_button = dialog.button_for_id(
            "data_manager.dataset_selector.button.filter_help"
        )
        assert help_button.toolTip() == "Open dataset search help."
        assert not dialog.filter_for_id(
            "data_manager.dataset_selector.filter.text"
        ).toolTip()
        assert not dialog.filter_for_id(
            "data_manager.dataset_selector.filter.source_reason"
        ).toolTip()

        help_button.click()
        QCoreApplication.processEvents()
        help_dialog = dialog.findChild(
            QDialog,
            "data_manager_dataset_selector_search_help_dialog",
        )
        assert help_dialog is not None
        assert help_dialog.property(
            "object_id"
        ) == DATA_MANAGER_DATASET_SEARCH_HELP_WINDOW_ID
        assert help_dialog.windowTitle() == "Dataset Search Help"
        assert help_dialog.windowModality() == Qt.WindowModality.WindowModal
        assert help_dialog.width() <= 700
        assert help_dialog.height() <= 540
        assert help_dialog.isVisible()

        content = help_dialog.findChild(
            QTextBrowser,
            "data_manager.dataset_selector.search_help.content",
        )
        assert content is not None
        help_text = content.toPlainText()
        assert "Dataset ID / State" in help_text
        assert "Example: BTCUSDT" in help_text
        assert "States" in help_text
        assert "accepted" in help_text
        assert "rejected" in help_text
        assert "Persistence" in help_text
        assert "committed" in help_text
        assert "present" in help_text
        assert "Validation" in help_text
        assert "ok" in help_text
        assert "invalid" in help_text
        assert "Source / Warning / Reason" in help_text
        assert "Example: timestamp gap" in help_text
        assert "Sources" in help_text
        assert "canonical download" in help_text
        assert "legacy import" in help_text
        assert "provider download" in help_text
        assert "Warnings" in help_text
        assert "timestamp gap detected" in help_text
        assert "Rejection codes" in help_text
        assert "schema" in help_text
        assert "Rejection reasons" in help_text
        assert "missing close column" in help_text
        assert "case-insensitive" in help_text
        assert "using AND" in help_text
        assert "never create, modify, or delete" in help_text

        close_button = help_dialog.findChild(
            QPushButton,
            "data_manager.dataset_selector.search_help.button.close",
        )
        assert close_button is not None
        close_button.click()
        QCoreApplication.processEvents()
        assert not help_dialog.isVisible()

        help_button.click()
        QCoreApplication.processEvents()
        assert dialog.findChild(
            QDialog,
            "data_manager_dataset_selector_search_help_dialog",
        ) is help_dialog
        assert help_dialog.isVisible()

        dialog.reject()
        QCoreApplication.processEvents()
        assert not help_dialog.isVisible()
    finally:
        dialog.close()


def test_refresh_cancel_and_busy_controls(qapp) -> None:
    dialog = DataManagerDatasetSelectorDialog()
    refreshed: list[bool] = []
    try:
        dialog.set_catalog(_snapshot())
        dialog.refresh_requested.connect(lambda: refreshed.append(True))
        dialog.button_for_id("data_manager.dataset_selector.button.refresh").click()
        assert refreshed == [True]

        table = dialog.table_for_id("data_manager.table.datasets")
        _dataset_checkbox(dialog, "BTCUSDT").setChecked(True)
        dialog.set_busy(True)
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.refresh"
        ).isEnabled()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.show_all"
        ).isEnabled()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.filter_help"
        ).isEnabled()
        assert dialog.button_for_id(
            "data_manager.dataset_selector.button.cancel"
        ).isEnabled()

        dialog.set_busy(False)
        dialog.show()
        QCoreApplication.processEvents()
        dialog.button_for_id("data_manager.dataset_selector.button.cancel").click()
        QCoreApplication.processEvents()
        assert not dialog.isVisible()
    finally:
        dialog.close()
