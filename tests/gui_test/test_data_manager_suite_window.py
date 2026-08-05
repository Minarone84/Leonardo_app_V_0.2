from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidget

from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerArtifactEntry,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerRecipeEntry,
)
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")
REJECTED_MARKET = MarketId("bybit", "linear", "XRPUSDT", "4h")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dataset(accepted=True):
    return DataManagerDatasetEntry(
        MARKET if accepted else REJECTED_MARKET,
        accepted,
        6 if accepted else None,
        1 if accepted else None,
        6 if accepted else None,
        rejection_code="" if accepted else "hash",
        rejection_reason="" if accepted else "source changed",
    )


def _snapshot(valid=True):
    recipe = DataManagerRecipeEntry(
        MARKET, "r" * 64, "rsi", "oscillator", ("rsi",), "RSI", None, valid,
        "invalid recipe" if not valid else "",
    )
    artifact = DataManagerArtifactEntry(
        MARKET, "a" * 64, recipe.recipe_id, "rsi", "oscillator", ("rsi",),
        6, 1, 6, None, valid, "invalid artifact" if not valid else "",
        "unknown" if valid else "invalid",
    )
    return DataManagerMarketSnapshot(MARKET, _dataset(), (recipe,), (artifact,))


def _selector_row(window: DataManagerSuiteWindow, symbol: str) -> int:
    dialog = window.dataset_selector_dialog()
    assert dialog is not None
    table = dialog.table_for_id("data_manager.table.datasets")
    for row in range(table.rowCount()):
        if table.item(row, 2).text() == symbol:
            return row
    raise AssertionError(f"selector row not found: {symbol}")


def test_exact_ids_columns_and_selection_enablement(qapp) -> None:
    window = DataManagerSuiteWindow()
    selected: list[MarketId] = []
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(),)))
        assert window.property("object_id") == "data_manager_suite.window"
        assert window.findChild(QTableWidget, "data_manager.table.datasets") is None
        assert window.table_for_id("data_manager.table.artifacts").columnCount() == 7
        assert window.table_for_id("data_manager.table.recipes").columnCount() == 7
        window.market_selected.connect(selected.append)
        window.button_for_id("data_manager.button.select_dataset").click()
        QCoreApplication.processEvents()
        dialog = window.dataset_selector_dialog()
        assert dialog is not None
        assert dialog.isVisible()
        assert dialog.table_for_id("data_manager.table.datasets").columnCount() == 11
        dialog.table_for_id("data_manager.table.datasets").selectRow(
            _selector_row(window, "BTCUSDT")
        )
        dialog.button_for_id("data_manager.dataset_selector.button.select").click()
        QCoreApplication.processEvents()
        assert selected == [MARKET]
        assert window.selected_market_id() == MARKET
        assert window.button_for_id("data_manager.button.preview_dataset").isEnabled()
        window.set_market_snapshot(_snapshot())
        assert not window.button_for_id("data_manager.button.preview_artifact").isEnabled()
        window.table_for_id("data_manager.table.artifacts").selectRow(0)
        assert window.button_for_id("data_manager.button.preview_artifact").isEnabled()
        assert window.button_for_id("data_manager.button.validate_artifact").isEnabled()
        assert window.button_for_id("data_manager.button.delete_artifact").isEnabled()
        window.set_busy(True, "preview")
        assert all(not button.isEnabled() for button in window._buttons.values())
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.refresh"
        ).isEnabled()
    finally:
        window.close()


def test_rejected_and_invalid_entries_remain_visible_but_disabled(qapp) -> None:
    window = DataManagerSuiteWindow()
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(False), _dataset())))
        window.button_for_id("data_manager.button.select_dataset").click()
        QCoreApplication.processEvents()
        dialog = window.dataset_selector_dialog()
        assert dialog is not None
        table = dialog.table_for_id("data_manager.table.datasets")
        table.selectRow(_selector_row(window, "XRPUSDT"))
        QCoreApplication.processEvents()
        assert window.selected_market_id() is None
        assert "source changed" in table.item(
            _selector_row(window, "XRPUSDT"), 10
        ).text()
        assert not dialog.button_for_id(
            "data_manager.dataset_selector.button.select"
        ).isEnabled()
        window.set_market_snapshot(_snapshot(False))
        window.table_for_id("data_manager.table.artifacts").selectRow(0)
        window.table_for_id("data_manager.table.recipes").selectRow(0)
        assert not window.button_for_id("data_manager.button.preview_artifact").isEnabled()
        assert not window.button_for_id("data_manager.button.delete_recipe").isEnabled()
    finally:
        window.close()


def test_selector_instance_is_reused_and_closed_with_suite(qapp) -> None:
    window = DataManagerSuiteWindow()
    window_closed = False
    try:
        window.set_catalog(DataManagerCatalogSnapshot((_dataset(),)))
        button = window.button_for_id("data_manager.button.select_dataset")
        button.click()
        QCoreApplication.processEvents()
        first = window.dataset_selector_dialog()
        assert first is not None and first.isVisible()
        first.reject()
        button.click()
        QCoreApplication.processEvents()
        assert window.dataset_selector_dialog() is first
        assert first.isVisible()
        window.close()
        window_closed = True
        assert not first.isVisible()
        QCoreApplication.processEvents()
    finally:
        if not window_closed:
            window.close()


def test_presentation_model_rejects_qt_runtime_objects(qapp) -> None:
    with pytest.raises(TypeError, match="source must be a string"):
        DataManagerDatasetEntry(MARKET, True, 1, 0, 0, source=QObject())


@pytest.mark.parametrize(
    ("table_id", "button_id", "signal_name"),
    (
        (
            "data_manager.table.artifacts",
            "data_manager.button.delete_artifact",
            "delete_artifact_requested",
        ),
        (
            "data_manager.table.recipes",
            "data_manager.button.delete_recipe",
            "delete_recipe_requested",
        ),
    ),
)
def test_exact_delete_confirmation_emits_only_after_yes(
    qapp, monkeypatch, table_id, button_id, signal_name
) -> None:
    window = DataManagerSuiteWindow()
    emitted = []
    try:
        window.set_market_snapshot(_snapshot())
        window.table_for_id(table_id).selectRow(0)
        getattr(window, signal_name).connect(lambda: emitted.append(True))
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args: QMessageBox.StandardButton.Cancel,
        )
        window.button_for_id(button_id).click()
        assert emitted == []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        window.button_for_id(button_id).click()
        assert emitted == [True]
    finally:
        window.close()
