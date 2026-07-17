import json
from pathlib import Path

from leonardo.data import MarketId
from leonardo.research.notebook import ResearchNotebookV1
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore


INPUT = Path("tests/gui_test/fixtures/task_1023_research_notebook_input.json")
EXPECTED = Path("tests/gui_test/fixtures/task_1023_research_notebook_expected.json")


def _notebook():
    return ResearchNotebookV1.from_dict(
        json.loads(INPUT.read_text(encoding="utf-8"))["notebook"]
    )


def test_annotation_projection_matches_frozen_fixture_and_excludes_notes(tmp_path):
    service = ResearchNotebookService(ResearchNotebookStore(tmp_path))
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))[
        "annotation_projection"
    ]
    for symbol, market in (
        ("BTCUSDT", MarketId("bybit", "linear", "BTCUSDT", "1h")),
        ("ETHUSDT", MarketId("bybit", "linear", "ETHUSDT", "15m")),
    ):
        projected = service.project_annotations(_notebook(), market)
        compact = [
            {
                "annotation_id": item.annotation_id,
                "kind": item.kind,
                "timestamp_ms": item.timestamp_ms,
                "anchor_price": item.anchor_price,
                "label": item.label,
                "offset_px": item.offset_px,
            }
            for item in projected
        ]
        assert compact == expected[symbol]
        assert all(not item.row_id.startswith("note_") for item in projected)


def test_projection_filters_exact_market_and_respects_visibility(tmp_path):
    service = ResearchNotebookService(ResearchNotebookStore(tmp_path))
    notebook = _notebook()
    assert (
        service.project_annotations(
            notebook, MarketId("bybit", "linear", "BTCUSDT", "15m")
        )
        == ()
    )
    hidden = notebook.build(
        notebook_id=notebook.notebook_id,
        display_name=notebook.display_name,
        description=notebook.description,
        created_at_utc=notebook.created_at_utc,
        updated_at_utc=notebook.updated_at_utc,
        annotation_settings=type(notebook.annotation_settings)(
            show_points_of_interest=False,
            show_potential_trades=False,
        ),
        pages=notebook.pages,
    )
    assert (
        service.project_annotations(
            hidden, MarketId("bybit", "linear", "BTCUSDT", "1h")
        )
        == ()
    )


def test_tooltips_contain_plain_text_row_details(tmp_path):
    service = ResearchNotebookService(ResearchNotebookStore(tmp_path))
    annotations = service.project_annotations(
        _notebook(), MarketId("bybit", "linear", "ETHUSDT", "15m")
    )
    assert "Status: closed" in annotations[0].tooltip
    assert "Outcome: win" in annotations[0].tooltip
    assert "Liquidity sweep" in annotations[1].tooltip
    assert "Anchor to the nearest candle high." in annotations[1].tooltip
