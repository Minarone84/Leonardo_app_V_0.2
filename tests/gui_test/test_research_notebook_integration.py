from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.data import MarketId
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from tests.gui_test.test_research_notebook_presenter import (
    _open_legacy_notebook_suite,
)
from tests.gui_test.test_research_single_chart_integration import _wait_until


def test_composed_notebook_save_creates_one_canonical_file(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        presenter.new_notebook()
        editor = window.findChild(ResearchNotebookWindow)
        assert editor is not None
        editor.save_requested.emit(
            __import__(
                "leonardo.gui.windows.research_notebook_window",
                fromlist=["ResearchNotebookSaveIntent"],
            ).ResearchNotebookSaveIntent(editor.current_draft(), True)
        )
        _wait_until(lambda: editor.notebook_id is not None)
        files = tuple(app.config.paths.research_notebooks_dir.glob("*.json"))
        assert len(files) == 1
        assert files[0].read_bytes().endswith(b"\n")
        assert app.research_notebook_store.load(editor.notebook_id).content_hash
    finally:
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_go_to_prefers_active_then_lowest_position_and_never_opens_chart(
    tmp_path, monkeypatch
) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        presenter.open_selected_dataset()
        _wait_until(lambda: len(presenter.slot_ids()) == 2)
        _wait_until(
            lambda: all(
                presenter.session_for(slot_id).resident is not None
                for slot_id in presenter.slot_ids()
            )
        )
        first, second = presenter.slot_ids()
        market = presenter.session_for(first).dataset.market_id
        calls: list[tuple[int, int]] = []
        for slot_id in (first, second):
            monkeypatch.setattr(
                presenter.chart_presenter(slot_id),
                "go_to_timestamp_ms",
                lambda timestamp, slot_id=slot_id: calls.append(
                    (slot_id, timestamp)
                )
                or True,
            )

        presenter.set_active_slot(second)
        presenter._notebook_go_to(market, 1000)
        assert calls == [(second, 1000)]

        calls.clear()
        monkeypatch.setattr(presenter, "_active_presenter", lambda: None)
        presenter._notebook_go_to(market, 2000)
        assert calls == [(first, 2000)]

        count = len(presenter.slot_ids())
        presenter._notebook_go_to(
            MarketId("bybit", "linear", "ETHUSDT", "1h"), 3000
        )
        assert len(presenter.slot_ids()) == count
        assert "No open Research chart" in window.status_text()
    finally:
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
