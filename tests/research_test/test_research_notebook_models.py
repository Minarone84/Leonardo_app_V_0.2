import json
from copy import deepcopy
from pathlib import Path

import pytest

from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
    ResearchNotebookPointOfInterestV1,
    ResearchNotebookPotentialTradeV1,
    ResearchNotebookV1,
    ResearchNotebookValidationError,
)


FIXTURE = Path("tests/gui_test/fixtures/task_1023_research_notebook_input.json")


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["notebook"]


def test_frozen_notebook_fixture_round_trips_with_exact_content_hash():
    notebook = ResearchNotebookV1.from_dict(_payload())
    assert (
        notebook.content_hash
        == "d65bf9209e1ed6f70d60469e16f085dd1ae0cf48de5003abbb40438213ae6e6b"
    )
    assert notebook.to_dict() == _payload()
    assert tuple(page.market_id.symbol for page in notebook.pages) == (
        "BTCUSDT",
        "ETHUSDT",
    )


def test_pages_and_rows_are_canonicalized_and_row_ids_are_globally_unique():
    notebook = ResearchNotebookV1.from_dict(_payload())
    btc, eth = notebook.pages
    draft = ResearchNotebookDraft(
        notebook_id=notebook.notebook_id,
        display_name=notebook.display_name,
        description=notebook.description,
        annotation_settings=notebook.annotation_settings,
        pages=(eth, btc),
    )
    assert draft.pages == (btc, eth)
    duplicate = ResearchNotebookPageV1(
        market_id=eth.market_id,
        notes=(ResearchNotebookNoteV1("note_btc_001", None, "Duplicate"),),
    )
    with pytest.raises(ResearchNotebookValidationError, match="row IDs"):
        ResearchNotebookDraft(
            display_name="Duplicate",
            description="",
            annotation_settings=ResearchNotebookAnnotationSettingsV1(),
            pages=(btc, duplicate),
        )


def test_note_trade_and_poi_rows_normalize_in_amendment_one_order():
    notebook = ResearchNotebookV1.from_dict(_payload())
    market = notebook.pages[0].market_id
    page = ResearchNotebookPageV1(
        market_id=market,
        notes=(
            ResearchNotebookNoteV1("note_dated_b", 20, "Dated B"),
            ResearchNotebookNoteV1("note_null_b", None, "Null B"),
            ResearchNotebookNoteV1("note_dated_a", 20, "Dated A"),
            ResearchNotebookNoteV1("note_null_a", None, "Null A"),
            ResearchNotebookNoteV1("note_early", 10, "Early"),
        ),
        potential_trades=(
            ResearchNotebookPotentialTradeV1(
                "trade_b", 20, "long", None, None, None, "planned", "pending", ""
            ),
            ResearchNotebookPotentialTradeV1(
                "trade_a", 20, "short", None, None, None, "planned", "pending", ""
            ),
            ResearchNotebookPotentialTradeV1(
                "trade_early", 10, "long", None, None, None, "planned", "pending", ""
            ),
        ),
        points_of_interest=(
            ResearchNotebookPointOfInterestV1("poi_b", 20, None, "B", ""),
            ResearchNotebookPointOfInterestV1("poi_a", 20, None, "A", ""),
            ResearchNotebookPointOfInterestV1("poi_early", 10, None, "Early", ""),
        ),
    )
    assert tuple(item.row_id for item in page.notes) == (
        "note_null_a",
        "note_null_b",
        "note_early",
        "note_dated_a",
        "note_dated_b",
    )
    assert tuple(item.row_id for item in page.potential_trades) == (
        "trade_early",
        "trade_a",
        "trade_b",
    )
    assert tuple(item.row_id for item in page.points_of_interest) == (
        "poi_early",
        "poi_a",
        "poi_b",
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("html",), "<b>forbidden</b>"),
        (("pages", 0, "slot_id"), 1),
        (("pages", 0, "notes", 0, "widget_id"), "widget"),
        (("pages", 0, "potential_trades", 0, "study_id"), "study"),
        (("pages", 0, "points_of_interest", 0, "artifact_id"), "artifact"),
    ],
)
def test_forbidden_and_unknown_fields_are_rejected(path, value):
    payload = deepcopy(_payload())
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ResearchNotebookValidationError):
        ResearchNotebookV1.from_dict(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0.0])
def test_prices_must_be_positive_and_finite(value):
    payload = _payload()
    payload["pages"][0]["potential_trades"][0]["entry_price"] = value
    with pytest.raises(ResearchNotebookValidationError, match="positive and finite"):
        ResearchNotebookV1.from_dict(payload)


def test_plain_text_rows_and_annotation_defaults_are_exact():
    note = ResearchNotebookNoteV1("note_1", None, "<b>plain text characters</b>")
    trade = ResearchNotebookPotentialTradeV1(
        "trade_1", 1, "long", None, None, None, "planned", "pending", ""
    )
    point = ResearchNotebookPointOfInterestV1(
        "poi_1", 2, None, "Title", ""
    )
    assert note.text == "<b>plain text characters</b>"
    assert trade.entry_price is None
    assert point.price is None
    assert ResearchNotebookAnnotationSettingsV1().to_dict() == {
        "show_points_of_interest": True,
        "show_potential_trades": True,
        "poi_offset_px": -28,
        "long_offset_px": 56,
        "short_offset_px": -56,
    }


def test_notebook_models_import_without_qt():
    source = Path("src/leonardo/research/notebook.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
