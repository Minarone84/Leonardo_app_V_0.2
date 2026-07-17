from __future__ import annotations

from leonardo.data import MarketId
from leonardo.gui.chart.annotation_scene import (
    ResearchChartAnnotationBundle,
    ResearchChartAnnotationProjection,
    build_annotation_scene,
)
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.price_scale import PriceRange, PriceScaleSnapshot
from leonardo.research.notebook import ResearchNotebookAnnotation
from leonardo.research.resident import ResidentOHLCVSlice
from leonardo.research.viewport import ViewportSnapshot


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")


def _annotation(
    row_id: str,
    kind: str,
    *,
    anchor: float | None,
    offset: int,
) -> ResearchNotebookAnnotation:
    return ResearchNotebookAnnotation(
        annotation_id=f"notebook_one:{row_id}",
        notebook_id="notebook_one",
        row_id=row_id,
        market_id=MARKET,
        kind=kind,
        timestamp_ms=1_000,
        anchor_price=anchor,
        label={"poi": "+", "trade_long": "L", "trade_short": "S"}[kind],
        title=row_id,
        tooltip=f"tooltip {row_id}",
        offset_px=offset,
    )


def _resident() -> ResidentOHLCVSlice:
    return ResidentOHLCVSlice(
        market_id=MARKET,
        dataset_fingerprint="a" * 64,
        base_index=0,
        end_index_exclusive=3,
        ts_ms=(1_000, 2_000, 3_000),
        open=(10.0, 11.0, 12.0),
        high=(14.0, 15.0, 16.0),
        low=(8.0, 9.0, 10.0),
        close=(12.0, 13.0, 14.0),
        volume=(1.0, 1.0, 1.0),
        has_more_left=False,
        has_more_right=False,
        first_timestamp_ms=1_000,
        last_timestamp_ms=3_000,
    )


def _viewport() -> ViewportSnapshot:
    return ViewportSnapshot(3, 0, 0, 0, 3, 0, 3, 3, None)


def test_scene_uses_explicit_and_candle_anchors_and_fixed_appearance() -> None:
    bundle = ResearchChartAnnotationBundle(
        MARKET,
        (
            ResearchChartAnnotationProjection(
                _annotation("long", "trade_long", anchor=None, offset=10), 0
            ),
            ResearchChartAnnotationProjection(
                _annotation("short", "trade_short", anchor=None, offset=-10), 1
            ),
            ResearchChartAnnotationProjection(
                _annotation("poi", "poi", anchor=13.0, offset=-10), 2
            ),
        ),
    )
    scene = build_annotation_scene(
        bundle,
        _resident(),
        _viewport(),
        PriceScaleSnapshot(True, PriceRange(0.0, 20.0)),
        SceneRect(0.0, 0.0, 300.0, 200.0),
    )

    assert [(item.shape, item.color) for item in scene.glyphs] == [
        ("triangle_up", "#00aa78"),
        ("triangle_down", "#d24646"),
        ("circle", "#f0b429"),
    ]
    assert [item.y for item in scene.glyphs] == [130.0, 40.0, 60.0]


def test_scene_stacks_same_candle_away_clips_and_filters_visibility() -> None:
    bundle = ResearchChartAnnotationBundle(
        MARKET,
        (
            ResearchChartAnnotationProjection(
                _annotation("first", "poi", anchor=20.0, offset=-200), 0
            ),
            ResearchChartAnnotationProjection(
                _annotation("second", "poi", anchor=20.0, offset=-200), 0
            ),
            ResearchChartAnnotationProjection(
                _annotation("hidden", "poi", anchor=20.0, offset=-10), 4
            ),
        ),
    )
    scene = build_annotation_scene(
        bundle,
        _resident(),
        _viewport(),
        PriceScaleSnapshot(True, PriceRange(0.0, 20.0)),
        SceneRect(0.0, 0.0, 300.0, 200.0),
    )

    assert len(scene.glyphs) == 2
    assert scene.glyphs[0].y == scene.glyphs[1].y == 5.0
    assert scene.glyphs[0].contains(scene.glyphs[0].x, scene.glyphs[0].y)
    assert scene.cache_identity()


def test_annotation_scene_module_has_no_pyside_dependency() -> None:
    source = (
        __import__("pathlib").Path("src/leonardo/gui/chart/annotation_scene.py")
        .read_text(encoding="utf-8")
    )
    assert "PySide6" not in source
