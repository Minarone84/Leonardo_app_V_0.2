from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
    ResearchNotebookPointOfInterestV1,
    ResearchNotebookPotentialTradeV1,
)
from tests.gui_test.test_research_notebook_presenter import (
    _open_legacy_notebook_suite,
)
from tests.gui_test.test_research_single_chart_integration import _wait_until


def test_only_trade_and_poi_rows_publish_to_exact_market_chart(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    app, main, window, presenter = _open_legacy_notebook_suite(tmp_path)
    try:
        presenter.new_notebook()
        editor = window.findChild(ResearchNotebookWindow)
        assert editor is not None
        market = presenter.session.dataset.market_id
        draft = ResearchNotebookDraft(
            "Annotations",
            "",
            ResearchNotebookAnnotationSettingsV1(),
            (
                ResearchNotebookPageV1(
                    market,
                    notes=(
                        ResearchNotebookNoteV1(
                            "note_one", 30_000_000, "Only text"
                        ),
                    ),
                    potential_trades=(
                        ResearchNotebookPotentialTradeV1(
                            "trade_one",
                            30_000_000,
                            "long",
                            100.0,
                            None,
                            None,
                            "planned",
                            "pending",
                            "",
                        ),
                    ),
                    points_of_interest=(
                        ResearchNotebookPointOfInterestV1(
                            "poi_one", 30_060_000, None, "POI", ""
                        ),
                    ),
                ),
            ),
        )
        editor.set_draft(draft, dirty=True)
        editor.draft_changed.emit(draft)
        presenter.chart_presenter(presenter.active_slot_id).chart_widget.repaint()
        QCoreApplication.processEvents()
        scene = presenter.chart_presenter(
            presenter.active_slot_id
        ).chart_widget.annotation_scene
        assert scene is not None
        assert {glyph.row_id for glyph in scene.glyphs} == {"trade_one", "poi_one"}
    finally:
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()


def test_snapshot_defers_go_to_and_duplicate_attached_detached_publication(
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
        presenter.detach_slot(second)
        presenter.new_notebook()
        editor = window.findChild(ResearchNotebookWindow)
        assert editor is not None
        market = presenter.session_for(first).dataset.market_id
        first_draft = ResearchNotebookDraft(
            "Annotations",
            "",
            ResearchNotebookAnnotationSettingsV1(),
            (
                ResearchNotebookPageV1(
                    market,
                    potential_trades=(
                        ResearchNotebookPotentialTradeV1(
                            "trade_one",
                            30_000_000,
                            "long",
                            100.0,
                            None,
                            None,
                            "planned",
                            "pending",
                            "",
                        ),
                    ),
                ),
            ),
        )
        editor.set_draft(first_draft, dirty=True)
        editor.draft_changed.emit(first_draft)
        for slot_id in (first, second):
            presenter.chart_presenter(slot_id).chart_widget.repaint()
        QCoreApplication.processEvents()

        assert {
            glyph.row_id
            for glyph in presenter.chart_presenter(first).chart_widget.annotation_scene.glyphs
        } == {"trade_one"}
        assert {
            glyph.row_id
            for glyph in presenter.chart_presenter(second).chart_widget.annotation_scene.glyphs
        } == {"trade_one"}

        second_draft = replace(
            first_draft,
            pages=(
                replace(
                    first_draft.pages[0],
                    points_of_interest=(
                        ResearchNotebookPointOfInterestV1(
                            "poi_two", 30_060_000, None, "POI", ""
                        ),
                    ),
                ),
            ),
        )
        go_calls: list[int] = []
        monkeypatch.setattr(
            presenter.chart_presenter(first),
            "go_to_timestamp_ms",
            lambda timestamp: go_calls.append(timestamp) or True,
        )
        presenter._snapshot_restore = object()
        editor.set_draft(second_draft, dirty=True)
        editor.draft_changed.emit(second_draft)
        presenter._notebook_go_to(market, 30_000_000)

        assert go_calls == []
        assert {
            glyph.row_id
            for glyph in presenter.chart_presenter(first).chart_widget.annotation_scene.glyphs
        } == {"trade_one"}

        presenter._snapshot_restore = None
        presenter._refresh_notebook_annotations()
        for slot_id in (first, second):
            presenter.chart_presenter(slot_id).chart_widget.repaint()
        QCoreApplication.processEvents()

        expected = {"trade_one", "poi_two"}
        assert {
            glyph.row_id
            for glyph in presenter.chart_presenter(first).chart_widget.annotation_scene.glyphs
        } == expected
        assert {
            glyph.row_id
            for glyph in presenter.chart_presenter(second).chart_widget.annotation_scene.glyphs
        } == expected
    finally:
        presenter._snapshot_restore = None
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
