from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
)

from leonardo.data import MarketId
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.research.notebook import (
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
)


def test_editor_exposes_exact_ids_columns_and_duplicate_page_activation() -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    window.add_page(ResearchNotebookPageV1(market))
    window.add_page(ResearchNotebookPageV1(market))

    assert window.objectName() == "research.notebook_window"
    assert window.findChild(
        QTableWidget, "research.notebook_window.table.notes"
    ).horizontalHeaderItem(3).text() == "Note"
    assert window.findChild(
        QTableWidget, "research.notebook_window.table.trades"
    ).columnCount() == 10
    assert window.findChild(
        QTableWidget, "research.notebook_window.table.poi"
    ).columnCount() == 6
    assert len(window.current_draft().pages) == 1
    assert window.current_draft().pages[0].market_id == market


def test_editor_contains_no_rich_text_or_service_authority() -> None:
    source = __import__("pathlib").Path(
        "src/leonardo/gui/windows/research_notebook_window.py"
    ).read_text(encoding="utf-8")
    assert "QTextEdit" not in source
    assert "ResearchNotebookStore" not in source
    assert "CoreRunner" not in source


def _notes_table(window: ResearchNotebookWindow, index: int) -> QTableWidget:
    return window.findChild(QTabWidget, "research.notebook_window.tabs.pages").widget(
        index
    ).findChild(QTableWidget, "research.notebook_window.table.notes")


def test_malformed_go_to_reports_without_emitting_or_raising() -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    window.add_page(
        ResearchNotebookPageV1(
            market,
            notes=(ResearchNotebookNoteV1("note_one", 1000, "text"),),
        )
    )
    table = _notes_table(window, 0)
    table.item(0, 2).setText("not-a-timestamp")
    emitted: list[tuple[MarketId, int]] = []
    window.go_to_requested.connect(
        lambda selected, timestamp: emitted.append((selected, timestamp))
    )

    table.cellWidget(0, 0).click()

    assert emitted == []
    assert "integer timestamp" in window.findChild(
        QLabel, "research.notebook_window.label.status"
    ).text()


def test_remove_page_preserves_invalid_cells_on_other_pages(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    first = MarketId("bybit", "linear", "BTCUSDT", "1h")
    second = MarketId("bybit", "linear", "ETHUSDT", "1h")
    window.add_page(
        ResearchNotebookPageV1(
            first,
            notes=(ResearchNotebookNoteV1("note_one", 1000, "first"),),
        )
    )
    window.add_page(
        ResearchNotebookPageV1(
            second,
            notes=(ResearchNotebookNoteV1("note_two", 2000, "second"),),
        )
    )
    tabs = window.findChild(QTabWidget, "research.notebook_window.tabs.pages")
    _notes_table(window, 0).item(0, 2).setText("bad-first")
    _notes_table(window, 1).item(0, 2).setText("bad-second")
    tabs.setCurrentIndex(0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )

    window.findChild(
        QPushButton, "research.notebook_window.button.remove_page"
    ).click()

    assert tabs.count() == 1
    assert _notes_table(window, 0).item(0, 2).text() == "bad-second"


def test_add_page_preserves_invalid_input_and_only_activates_duplicates() -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    first = MarketId("bybit", "linear", "BTCUSDT", "1h")
    second = MarketId("bybit", "linear", "ETHUSDT", "1h")
    first_page = ResearchNotebookPageV1(
        first,
        notes=(ResearchNotebookNoteV1("note_one", 1000, "text"),),
    )
    window.add_page(first_page)
    table = _notes_table(window, 0)
    table.item(0, 2).setText("invalid")
    emitted: list[object] = []
    window.draft_changed.connect(emitted.append)

    window.add_page(first_page)

    assert table.item(0, 2).text() == "invalid"
    assert window.findChild(
        QTabWidget, "research.notebook_window.tabs.pages"
    ).count() == 1

    window.add_page(ResearchNotebookPageV1(second))

    assert table.item(0, 2).text() == "invalid"
    assert window.findChild(
        QTabWidget, "research.notebook_window.tabs.pages"
    ).count() == 1
    assert emitted == []
    assert "Cannot add page" in window.findChild(
        QLabel, "research.notebook_window.label.status"
    ).text()


def test_current_validity_and_save_pending_fence_all_mutations() -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    window.add_page(
        ResearchNotebookPageV1(
            market,
            notes=(ResearchNotebookNoteV1("note_one", 1000, "text"),),
        )
    )
    mutation_controls = (
        window.findChild(QLineEdit, "research.notebook_window.edit.name"),
        window.findChild(QLineEdit, "research.notebook_window.edit.description"),
        window.findChild(QCheckBox, "research.notebook_window.check.show_poi"),
        window.findChild(QCheckBox, "research.notebook_window.check.show_trades"),
        window.findChild(QSpinBox, "research.notebook_window.spin.poi_offset"),
        window.findChild(QSpinBox, "research.notebook_window.spin.long_offset"),
        window.findChild(QSpinBox, "research.notebook_window.spin.short_offset"),
        window.findChild(QTabWidget, "research.notebook_window.tabs.pages"),
        window.findChild(
            QPushButton, "research.notebook_window.button.add_current_chart"
        ),
        window.findChild(QPushButton, "research.notebook_window.button.remove_page"),
        window.findChild(QPushButton, "research.notebook_window.button.add_note"),
        window.findChild(QPushButton, "research.notebook_window.button.add_trade"),
        window.findChild(QPushButton, "research.notebook_window.button.add_poi"),
    )
    save = window.findChild(QPushButton, "research.notebook_window.button.save")
    save_as = window.findChild(
        QPushButton, "research.notebook_window.button.save_as"
    )
    close = window.findChild(QPushButton, "research.notebook_window.button.close")
    assert window.is_current_valid

    window.set_save_pending(True)

    assert all(not control.isEnabled() for control in mutation_controls)
    assert not save.isEnabled()
    assert not save_as.isEnabled()
    assert close.isEnabled()

    window.set_save_pending(False)

    assert all(control.isEnabled() for control in mutation_controls)
    assert save.isEnabled()
    assert save_as.isEnabled()

    table = _notes_table(window, 0)
    table.item(0, 2).setText("invalid")
    assert not window.is_current_valid
    window.set_save_pending(True)
    window.set_save_pending(False)
    assert all(control.isEnabled() for control in mutation_controls)
    assert not save.isEnabled()
    assert not save_as.isEnabled()

    table.item(0, 2).setText("1000")
    assert window.is_current_valid
    assert save.isEnabled()
    assert save_as.isEnabled()


@pytest.mark.parametrize(
    ("timestamp_text", "expected"),
    (("", ()), ("-1", ()), ("0", (0,)), ("1", (1,))),
)
def test_go_to_accepts_only_non_negative_timestamps(
    timestamp_text: str, expected: tuple[int, ...]
) -> None:
    QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    window.add_page(
        ResearchNotebookPageV1(
            market,
            notes=(ResearchNotebookNoteV1("note_one", 1000, "text"),),
        )
    )
    table = _notes_table(window, 0)
    table.item(0, 2).setText(timestamp_text)
    emitted: list[int] = []
    window.go_to_requested.connect(
        lambda _market, timestamp: emitted.append(timestamp)
    )

    table.cellWidget(0, 0).click()

    assert tuple(emitted) == expected
