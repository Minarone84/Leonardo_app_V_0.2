from __future__ import annotations

from types import MappingProxyType

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.price_scale import PriceRange, PriceScaleSnapshot
from leonardo.gui.chart.study_scene import PriceStudyBundle, build_study_scene
from leonardo.research import (
    ResidentStudyProjection,
    StudyFillStyle,
    StudyLineStyle,
    StudyPresentation,
    ViewportSnapshot,
)


def _projection(
    study_id: str,
    render_series: dict[str, tuple[object, ...]],
    style_driver_series: dict[str, tuple[object, ...]] | None = None,
) -> ResidentStudyProjection:
    count = len(next(iter(render_series.values())))
    return ResidentStudyProjection(
        study_id=study_id,
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
        dataset_fingerprint="a" * 64,
        pane_role="price",
        base_index=2,
        end_index_exclusive=2 + count,
        ts_ms=tuple(range(count)),
        render_series=render_series,
        style_driver_series=style_driver_series or {},
    )


def _viewport() -> ViewportSnapshot:
    return ViewportSnapshot(10, 0, 0, 0, 10, 1, 8, 7, None)


def _scale(*, autoscale: bool = True) -> PriceScaleSnapshot:
    return PriceScaleSnapshot(autoscale, PriceRange(90.0, 120.0))


def test_bb_lines_fill_nan_breaks_order_autoscale_and_cache_identity() -> None:
    projection = _projection(
        "bb",
        {
            "bb_middle": (100.0, 101.0, float("nan"), 103.0, 104.0),
            "bb_upper_band": (105.0, 106.0, float("nan"), 108.0, 109.0),
            "bb_lower_band": (95.0, 96.0, float("nan"), 98.0, 99.0),
        },
    )
    styles = {
        "bb_middle": StudyLineStyle("bb_middle", "#F59E0B"),
        "bb_upper_band": StudyLineStyle(
            "bb_upper_band", "#60A5FA", line_pattern="dashed"
        ),
        "bb_lower_band": StudyLineStyle(
            "bb_lower_band", "#60A5FA", line_pattern="dashed"
        ),
    }
    presentation = StudyPresentation(
        "bb",
        True,
        "price",
        styles,
        {
            "bb_band": StudyFillStyle(
                "bb_band", "bb_upper_band", "bb_lower_band", "#60A5FA"
            )
        },
    )
    scene = build_study_scene(
        PriceStudyBundle((projection,), (presentation,)),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )

    assert tuple(strip.output_name for strip in scene.line_strips) == (
        "bb_middle",
        "bb_middle",
        "bb_upper_band",
        "bb_upper_band",
        "bb_lower_band",
        "bb_lower_band",
    )
    assert len(scene.fills) == 2
    assert scene.autoscale_values == (
        100.0,
        101.0,
        103.0,
        104.0,
        105.0,
        106.0,
        108.0,
        109.0,
        95.0,
        96.0,
        98.0,
        99.0,
    )
    assert scene.cache_identity != build_study_scene(
        PriceStudyBundle(
            (projection,),
            (
                StudyPresentation(
                    "bb", True, "price", styles, presentation.fill_styles, revision=1
                ),
            ),
        ),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    ).cache_identity


def test_conditional_segments_markers_visibility_and_manual_scale() -> None:
    projection = _projection(
        "hck",
        {
            "fast_vwap": (100.0, 101.0, 102.0, 103.0, 104.0),
            "peak_3": (float("nan"), 105.0, float("inf"), 106.0, float("nan")),
        },
        {"vwap_color": ("green", "green", "red", "unknown", "silver")},
    )
    presentation = StudyPresentation(
        "hck",
        True,
        "price",
        {
            "fast_vwap": StudyLineStyle(
                "fast_vwap",
                "#22C55E",
                conditional_driver_name="vwap_color",
                conditional_colors=MappingProxyType(
                    {"green": "#22C55E", "red": "#EF4444", "silver": "#94A3B8"}
                ),
            ),
            "peak_3": StudyLineStyle(
                "peak_3",
                "#22C55E",
                render_mode="marker",
                marker_shape="triangle_down",
            ),
        },
        {},
    )
    scene = build_study_scene(
        PriceStudyBundle((projection,), (presentation,)),
        _viewport(),
        _scale(autoscale=False),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )

    assert tuple(strip.color for strip in scene.line_strips) == (
        "#22C55E",
        "#EF4444",
        "#22C55E",
        "#94A3B8",
    )
    assert tuple(
        tuple(point.global_index for point in strip.points)
        for strip in scene.line_strips
    ) == ((2, 3), (3, 4), (4, 5), (5, 6))
    assert sum(max(0, len(strip.points) - 1) for strip in scene.line_strips) == 4
    assert tuple(marker.point.value for marker in scene.markers) == (105.0, 106.0)
    assert "vwap_color" not in tuple(strip.output_name for strip in scene.line_strips)
    assert scene.autoscale_values == (100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0)
    assert _scale(autoscale=False).price_range == PriceRange(90.0, 120.0)

    hidden = StudyPresentation(
        "hck", False, "price", presentation.signal_styles, {}, revision=1
    )
    hidden_scene = build_study_scene(
        PriceStudyBundle((projection,), (hidden,)),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )
    assert not hidden_scene.line_strips
    assert not hidden_scene.markers
    assert not hidden_scene.autoscale_values


def test_conditional_fills_preserve_every_adjacent_finite_interval() -> None:
    projection = _projection(
        "conditional-fill",
        {
            "upper": (110.0, 111.0, 112.0, 113.0),
            "lower": (90.0, 91.0, 92.0, 93.0),
        },
        {"fill_state": ("a", "b", "a", "b")},
    )
    presentation = StudyPresentation(
        "conditional-fill",
        True,
        "price",
        {
            "upper": StudyLineStyle("upper", "#60A5FA", visible=False),
            "lower": StudyLineStyle("lower", "#60A5FA", visible=False),
        },
        {
            "band": StudyFillStyle(
                "band",
                "upper",
                "lower",
                "#60A5FA",
                conditional_driver_name="fill_state",
                conditional_colors=MappingProxyType(
                    {"a": "#22C55E", "b": "#EF4444"}
                ),
            )
        },
    )

    scene = build_study_scene(
        PriceStudyBundle((projection,), (presentation,)),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )

    assert tuple(fill.color for fill in scene.fills) == (
        "#EF4444",
        "#22C55E",
        "#EF4444",
    )
    assert tuple(
        tuple(point.global_index for point in fill.points) for fill in scene.fills
    ) == ((2, 3), (3, 4), (4, 5))
    assert sum(max(0, len(fill.points) - 1) for fill in scene.fills) == 3


def test_visible_fill_autoscale_includes_hidden_boundaries_once() -> None:
    projection = _projection(
        "fill-autoscale",
        {
            "upper": (180.0, 190.0, 200.0, 220.0),
            "lower": (140.0, 150.0, 160.0, 170.0),
            "hidden_upper": (900.0, 910.0, 920.0, 930.0),
            "hidden_lower": (800.0, 810.0, 820.0, 830.0),
        },
    )
    styles = {
        name: StudyLineStyle(name, "#60A5FA", visible=False)
        for name in projection.render_series
    }
    presentation = StudyPresentation(
        "fill-autoscale",
        True,
        "price",
        styles,
        {
            "band": StudyFillStyle("band", "upper", "lower", "#60A5FA"),
            "duplicate": StudyFillStyle(
                "duplicate", "upper", "lower", "#60A5FA"
            ),
            "hidden": StudyFillStyle(
                "hidden",
                "hidden_upper",
                "hidden_lower",
                "#60A5FA",
                visible=False,
            ),
        },
    )
    scene = build_study_scene(
        PriceStudyBundle((projection,), (presentation,)),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )

    assert scene.autoscale_values == (
        180.0,
        190.0,
        200.0,
        220.0,
        140.0,
        150.0,
        160.0,
        170.0,
    )
    hidden_study = StudyPresentation(
        "fill-autoscale", False, "price", styles, presentation.fill_styles
    )
    hidden_scene = build_study_scene(
        PriceStudyBundle((projection,), (hidden_study,)),
        _viewport(),
        _scale(),
        SceneRect(0.0, 0.0, 700.0, 300.0),
    )
    assert hidden_scene.autoscale_values == ()
