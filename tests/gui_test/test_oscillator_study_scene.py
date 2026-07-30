from __future__ import annotations

from dataclasses import replace

import pytest

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.oscillator_scene import build_oscillator_scene
from leonardo.research import (
    ResidentOHLCVSlice,
    ResidentStudyProjection,
    StudyFillStyle,
    StudyLineStyle,
    StudyPresentation,
    ViewportSnapshot,
)


def _projection(study_id: str, name: str, values: tuple[object, ...]):
    return ResidentStudyProjection(
        study_id,
        MarketId("bybit", "linear", "BTCUSDT", "1m"),
        "a" * 64,
        "oscillator",
        2,
        2 + len(values),
        tuple(range(len(values))),
        {name: values},
        {},
    )


def _presentation(
    study_id: str,
    name: str,
    *,
    visible: bool = True,
    tool_key: str | None = None,
):
    return StudyPresentation(
        study_id,
        visible,
        f"oscillator:{study_id}",
        {name: StudyLineStyle(name, "#A855F7")},
        {},
        tool_key=tool_key,
    )


def _multi_projection(study_id: str, names: tuple[str, ...]):
    return ResidentStudyProjection(
        study_id,
        MarketId("bybit", "linear", "BTCUSDT", "1m"),
        "a" * 64,
        "oscillator",
        2,
        5,
        (0, 1, 2),
        {
            name: (float(index + 1), float(index + 2), float(index + 3))
            for index, name in enumerate(names)
        },
        {},
    )


def _series_projection(study_id: str, series: dict[str, tuple[object, ...]]):
    size = len(next(iter(series.values())))
    assert all(len(values) == size for values in series.values())
    return ResidentStudyProjection(
        study_id,
        MarketId("bybit", "linear", "BTCUSDT", "1m"),
        "a" * 64,
        "oscillator",
        2,
        2 + size,
        tuple(range(size)),
        series,
        {},
    )


def _styled_presentation(
    study_id: str,
    tool_key: str,
    styles: tuple[StudyLineStyle, ...],
    fills: tuple[StudyFillStyle, ...] = (),
    *,
    visible: bool = True,
):
    return StudyPresentation(
        study_id,
        visible,
        f"oscillator:{study_id}",
        {style.output_name: style for style in styles},
        {style.fill_id: style for style in fills},
        tool_key=tool_key,
    )


def _with_guide_values(
    presentation: StudyPresentation,
    **values: float,
) -> StudyPresentation:
    guides = {
        guide_id: replace(
            guide,
            value=values.get(guide_id, guide.value),
        )
        for guide_id, guide in presentation.guide_styles.items()
    }
    return replace(presentation, guide_styles=guides)


def _multi_presentation(
    study_id: str,
    names: tuple[str, ...],
    *,
    tool_key: str | None = None,
):
    return StudyPresentation(
        study_id,
        True,
        f"oscillator:{study_id}",
        {name: StudyLineStyle(name, "#A855F7") for name in names},
        {},
        tool_key=tool_key,
    )


def _viewport(count: int = 10):
    return ViewportSnapshot(count, 0, 0, 0, count, 1, count, count - 1, None)


def _volume_fixture():
    market_id = MarketId("bybit", "linear", "BTCUSDT", "1m")
    projection = ResidentStudyProjection(
        "volume",
        market_id,
        "a" * 64,
        "oscillator",
        2,
        7,
        (120_000, 180_000, 240_000, 300_000, 360_000),
        {
            "volume": (10.0, 20.0, 30.0, float("nan"), 50.0),
            "volume_mean_20": (12.0, 18.0, 25.0, 32.0, 40.0),
        },
        {},
    )
    presentation = StudyPresentation(
        "volume",
        True,
        "oscillator:volume",
        {
            "volume": StudyLineStyle("volume", "#A855F7"),
            "volume_mean_20": StudyLineStyle("volume_mean_20", "#F59E0B"),
        },
        {},
    )
    resident = ResidentOHLCVSlice(
        market_id,
        "a" * 64,
        2,
        4,
        (120_000, 180_000),
        (100.0, 102.0),
        (104.0, 103.0),
        (99.0, 98.0),
        (103.0, 99.0),
        (10.0, 20.0),
        False,
        True,
        120_000,
        180_000,
    )
    return projection, presentation, resident


def test_volume_uses_histogram_candle_direction_and_mean_line() -> None:
    projection, presentation, resident = _volume_fixture()
    plot = SceneRect(0.0, 0.0, 100.0, 100.0)
    scene = build_oscillator_scene(
        projection, presentation, _viewport(), plot, resident
    )

    assert scene.axis_low == 0.0
    assert scene.axis_high > 50.0
    assert [bar.global_index for bar in scene.histogram_bars] == [2, 3, 4, 6]
    assert [bar.direction for bar in scene.histogram_bars] == [
        "bullish",
        "bearish",
        "neutral",
        "neutral",
    ]
    assert all(bar.bottom == plot.height for bar in scene.histogram_bars)
    expected_width = plot.width / _viewport().visible_count * 0.8
    assert all(
        bar.width == pytest.approx(expected_width)
        for bar in scene.histogram_bars
    )
    assert [strip.output_name for strip in scene.line_strips] == [
        "volume_mean_20"
    ]
    assert len(scene.histogram_bars) == 4

    neutral = build_oscillator_scene(
        projection, presentation, _viewport(), plot
    )
    assert {bar.direction for bar in neutral.histogram_bars} == {"neutral"}


def test_rsi_uses_fixed_bounds_sorted_guides_and_shared_horizontal_range() -> None:
    projection = _projection("rsi", "rsi_3", (20.0, 30.0, 50.0, 70.0, 80.0))
    scene = build_oscillator_scene(
        projection,
        _presentation("rsi", "rsi_3", tool_key="rsi"),
        _viewport(),
        SceneRect(0.0, 0.0, 900.0, 180.0),
    )

    assert (scene.axis_low, scene.axis_high) == (0.0, 100.0)
    assert tuple((guide.kind, guide.value) for guide in scene.guides) == (
        ("oversold", 30.0),
        ("center", 50.0),
        ("overbought", 70.0),
    )
    assert tuple(
        (guide.color, guide.line_width, guide.line_pattern)
        for guide in scene.guides
    ) == (
        ("#22C55E", 1.0, "dashed"),
        ("#94A3B8", 1.0, "dashed"),
        ("#EF4444", 1.0, "dashed"),
    )
    assert tuple(
        dict.fromkeys(
            point.global_index
            for strip in scene.line_strips
            for point in strip.points
        )
    ) == (
        2,
        3,
        4,
        5,
        6,
    )
    assert scene.time_ticks
    assert tuple(tick.global_index for tick in scene.time_ticks) == tuple(
        sorted(tick.global_index for tick in scene.time_ticks)
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    (
        (
            (20.0, 80.0),
            (
                ("#22C55E", (20.0, 30.0)),
                ("#A855F7", (30.0, 70.0)),
                ("#EF4444", (70.0, 80.0)),
            ),
        ),
        (
            (80.0, 20.0),
            (
                ("#EF4444", (80.0, 70.0)),
                ("#A855F7", (70.0, 30.0)),
                ("#22C55E", (30.0, 20.0)),
            ),
        ),
    ),
)
def test_rsi_threshold_crossings_insert_exact_ordered_points(
    values: tuple[float, ...],
    expected: tuple[tuple[str, tuple[float, ...]], ...],
) -> None:
    scene = build_oscillator_scene(
        _projection("rsi-crossing", "rsi_3", values),
        _styled_presentation(
            "rsi-crossing",
            "rsi",
            (StudyLineStyle("rsi_3", "#A855F7"),),
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple(
        (strip.color, tuple(point.value for point in strip.points))
        for strip in scene.line_strips
    ) == expected


def test_custom_rsi_thresholds_drive_guides_segments_and_cache_identity() -> None:
    projection = _projection("rsi-custom", "rsi_3", (20.0, 80.0))
    default = _styled_presentation(
        "rsi-custom",
        "rsi",
        (StudyLineStyle("rsi_3", "#A855F7"),),
    )
    customized = _with_guide_values(
        default,
        oversold=25.0,
        center=55.0,
        overbought=75.0,
    )
    scene = build_oscillator_scene(
        projection,
        customized,
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple((guide.kind, guide.value) for guide in scene.guides) == (
        ("oversold", 25.0),
        ("center", 55.0),
        ("overbought", 75.0),
    )
    assert tuple(
        (strip.color, tuple(point.value for point in strip.points))
        for strip in scene.line_strips
    ) == (
        ("#22C55E", (20.0, 25.0)),
        ("#A855F7", (25.0, 75.0)),
        ("#EF4444", (75.0, 80.0)),
    )
    center_changed = build_oscillator_scene(
        projection,
        _with_guide_values(customized, center=60.0),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple(
        (strip.color, tuple(point.value for point in strip.points))
        for strip in center_changed.line_strips
    ) == tuple(
        (strip.color, tuple(point.value for point in strip.points))
        for strip in scene.line_strips
    )
    default_scene = build_oscillator_scene(
        projection,
        default,
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert scene.cache_identity != default_scene.cache_identity


@pytest.mark.parametrize(
    ("tool_key", "series", "primary_name", "secondary_name"),
    (
        (
            "arsi",
            {
                "arsi_14_rma": (5.0, 95.0),
                "arsi_signal_14_rma_14_ema": (5.0, 95.0),
            },
            "arsi_14_rma",
            "arsi_signal_14_rma_14_ema",
        ),
        (
            "mfi",
            {"mfi_3": (5.0, 95.0)},
            "mfi_3",
            None,
        ),
    ),
)
def test_custom_arsi_and_mfi_thresholds_preserve_primary_coloring(
    tool_key: str,
    series: dict[str, tuple[object, ...]],
    primary_name: str,
    secondary_name: str | None,
) -> None:
    presentation = _styled_presentation(
        tool_key,
        tool_key,
        tuple(
            StudyLineStyle(
                name,
                "#8B5CF6" if name == primary_name else "#FF5D00",
            )
            for name in series
        ),
    )
    scene = build_oscillator_scene(
        _series_projection(tool_key, series),
        _with_guide_values(
            presentation,
            oversold=10.0,
            center=50.0,
            overbought=90.0,
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple(
        strip.color
        for strip in scene.line_strips
        if strip.output_name == primary_name
    ) == ("#22C55E", "#8B5CF6", "#EF4444")
    if secondary_name is not None:
        assert tuple(
            strip.color
            for strip in scene.line_strips
            if strip.output_name == secondary_name
        ) == ("#FF5D00",)


def test_custom_tdirsi_guides_and_smi_zero_are_scene_authority() -> None:
    tdi_name = "tdirsi_fast_ma_14_34_2_7_ema_rma"
    tdi_presentation = _styled_presentation(
        "tdi-custom",
        "tdirsi",
        (StudyLineStyle(tdi_name, "#22C55E"),),
    )
    tdi = build_oscillator_scene(
        _projection("tdi-custom", tdi_name, (35.0, 65.0)),
        _with_guide_values(
            tdi_presentation,
            oversold=20.0,
            center=45.0,
            overbought=80.0,
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple((guide.kind, guide.value) for guide in tdi.guides) == (
        ("oversold", 20.0),
        ("center", 45.0),
        ("overbought", 80.0),
    )

    smi_presentation = _styled_presentation(
        "smi-custom",
        "smi",
        (StudyLineStyle("smi_14_3", "#06B6D4"),),
    )
    smi = build_oscillator_scene(
        _projection("smi-custom", "smi_14_3", (60.0, 70.0)),
        _with_guide_values(smi_presentation, zero=50.0),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple((guide.kind, guide.value) for guide in smi.guides) == (
        ("zero", 50.0),
    )
    assert smi.axis_low < 50.0 < smi.axis_high


def test_threshold_endpoint_equality_nan_breaks_arsi_primary_only_and_mfi() -> None:
    equality = build_oscillator_scene(
        _projection("rsi-equality", "rsi_3", (30.0, 50.0, 70.0)),
        _styled_presentation(
            "rsi-equality",
            "rsi",
            (StudyLineStyle("rsi_3", "#A855F7"),),
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple(strip.color for strip in equality.line_strips) == ("#A855F7",)
    assert tuple(point.value for point in equality.line_strips[0].points) == (
        30.0,
        50.0,
        70.0,
    )

    nan_break = build_oscillator_scene(
        _projection(
            "mfi-break",
            "mfi_3",
            (20.0, 40.0, float("nan"), 80.0, 60.0),
        ),
        _styled_presentation(
            "mfi-break",
            "mfi",
            (StudyLineStyle("mfi_3", "#14B8A6"),),
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple(strip.color for strip in nan_break.line_strips) == (
        "#22C55E",
        "#14B8A6",
        "#EF4444",
        "#14B8A6",
    )
    assert all(
        strip.points[-1].x != strip.points[0].x
        for strip in nan_break.line_strips
    )

    arsi = build_oscillator_scene(
        _series_projection(
            "arsi",
            {
                "arsi_14_rma": (10.0, 90.0),
                "arsi_signal_14_rma_14_ema": (10.0, 90.0),
            },
        ),
        _styled_presentation(
            "arsi",
            "arsi",
            (
                StudyLineStyle("arsi_14_rma", "#8B5CF6"),
                StudyLineStyle("arsi_signal_14_rma_14_ema", "#FF5D00"),
            ),
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    primary = tuple(
        strip.color
        for strip in arsi.line_strips
        if strip.output_name == "arsi_14_rma"
    )
    signal = tuple(
        strip.color
        for strip in arsi.line_strips
        if strip.output_name == "arsi_signal_14_rma_14_ema"
    )
    assert primary == ("#22C55E", "#8B5CF6", "#EF4444")
    assert signal == ("#FF5D00",)


def test_tdirsi_fill_geometry_visibility_and_smi_zero_semantics() -> None:
    names = (
        "tdirsi_fast_ma_14_34_2_7_ema_rma",
        "tdirsi_slow_ma_14_34_2_7_ema_rma",
        "tdirsi_up_14_34_2_7_ema_rma",
        "tdirsi_dn_14_34_2_7_ema_rma",
        "tdirsi_mid_14_34_2_7_ema_rma",
    )
    projection = _series_projection(
        "tdirsi",
        {
            names[0]: (40.0,) * 7,
            names[1]: (45.0,) * 7,
            names[2]: (70.0, 71.0, float("nan"), 72.0, 73.0, 74.0, float("nan")),
            names[3]: (30.0, 29.0, float("nan"), 28.0, 27.0, float("nan"), 26.0),
            names[4]: (50.0,) * 7,
        },
    )
    fill = StudyFillStyle(
        "tdirsi_band", names[2], names[3], "#123456", 0.25, True
    )
    presentation = _styled_presentation(
        "tdirsi",
        "tdirsi",
        (
            StudyLineStyle(names[0], "#22C55E"),
            StudyLineStyle(names[1], "#EF4444"),
            StudyLineStyle(names[2], "#60A5FA", line_pattern="dashed"),
            StudyLineStyle(names[3], "#60A5FA", line_pattern="dashed"),
            StudyLineStyle(names[4], "#F59E0B"),
        ),
        (fill,),
    )
    scene = build_oscillator_scene(
        projection,
        presentation,
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert tuple((item.fill_id, item.color, item.opacity) for item in scene.fills) == (
        ("tdirsi_band", "#123456", 0.25),
        ("tdirsi_band", "#123456", 0.25),
    )
    assert tuple(len(item.points) for item in scene.fills) == (2, 2)
    assert tuple(
        (strip.output_name, strip.color, strip.line_pattern)
        for strip in scene.line_strips
        if strip.output_name in names
    )[:2] == (
        (names[0], "#22C55E", "solid"),
        (names[1], "#EF4444", "solid"),
    )
    hidden = build_oscillator_scene(
        projection,
        replace(presentation, fill_styles={"tdirsi_band": replace(fill, visible=False)}),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert hidden.fills == ()

    smi = build_oscillator_scene(
        _series_projection(
            "smi",
            {
                "smi_14_3": (-10.0, 10.0),
                "smi_signal_14_3": (-5.0, 5.0),
            },
        ),
        _styled_presentation(
            "smi",
            "smi",
            (
                StudyLineStyle("smi_14_3", "#06B6D4"),
                StudyLineStyle("smi_signal_14_3", "#F59E0B"),
            ),
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 100.0, 100.0),
    )
    assert (smi.axis_low, smi.axis_high) != (0.0, 100.0)
    assert tuple(
        (guide.kind, guide.value, guide.color, guide.line_pattern)
        for guide in smi.guides
    ) == (("zero", 0.0, "#94A3B8", "dashed"),)
    assert tuple(strip.color for strip in smi.line_strips) == (
        "#06B6D4",
        "#F59E0B",
    )


def test_smi_auto_bounds_empty_flat_nan_breaks_and_hidden_output() -> None:
    projection = _projection(
        "smi", "smi_3_2", (10.0, 20.0, float("nan"), 30.0, 40.0)
    )
    scene = build_oscillator_scene(
        projection,
        _presentation("smi", "smi_3_2"),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )
    assert scene.axis_low < 10.0
    assert scene.axis_high > 40.0
    assert len(scene.line_strips) == 2

    flat = build_oscillator_scene(
        _projection("smi-flat", "smi_3_2", (5.0, 5.0, 5.0)),
        _presentation("smi-flat", "smi_3_2"),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )
    assert flat.axis_high - flat.axis_low >= 2.0

    empty = build_oscillator_scene(
        _projection("smi-empty", "smi_3_2", (float("nan"),) * 3),
        _presentation("smi-empty", "smi_3_2"),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )
    assert (empty.axis_low, empty.axis_high) == (0.0, 1.0)
    assert empty.center_message == "No visible oscillator data"

    hidden = build_oscillator_scene(
        projection,
        _presentation("smi", "smi_3_2", visible=False),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )
    assert not hidden.line_strips
    assert (hidden.axis_low, hidden.axis_high) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("study_id", "tool_key", "output_names"),
    (
        (
            "derivative",
            "derivative",
            ("close__d1",),
        ),
        (
            "angle",
            "angle",
            ("close__ang",),
        ),
        (
            "braids",
            "braids",
            ("sma_14_ema_14_hma_14",),
        ),
        (
            "braid-instability",
            "braid_instability",
            ("sma_14_ema_14_hma_14_inst_5",),
        ),
        (
            "delta",
            "delta",
            ("close_open_delta",),
        ),
        (
            "trap-area",
            "trap_area",
            ("fast_mid_trapA", "fast_slow_trapA", "mid_slow_trapA"),
        ),
        (
            "percent-span-angle",
            "percent_span_angle",
            ("close_ang_pct_span_10", "volume_ang_pct_span_10"),
        ),
        (
            "angle-momentum",
            "angle_momentum",
            ("close_ang_mtm_3", "volume_ang_mtm_3"),
        ),
    ),
)
def test_all_canonical_construct_oscillators_use_auto_bounds_without_guides(
    study_id: str,
    tool_key: str,
    output_names: tuple[str, ...],
) -> None:
    scene = build_oscillator_scene(
        _multi_projection(study_id, output_names),
        _multi_presentation(
            study_id,
            output_names,
            tool_key=tool_key,
        ),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )

    assert scene.axis_low < 1.0
    assert scene.axis_high > float(len(output_names) + 2)
    assert scene.guides == ()


@pytest.mark.parametrize(
    ("tool_key", "study_id", "output_name", "fixed_bounds", "guide_values"),
    (
        ("rsi", "rsi-native", "rsi_14", True, (30.0, 50.0, 70.0)),
        ("arsi", "arsi-native", "arsi_14_RMA", True, (20.0, 50.0, 80.0)),
        (
            "tdirsi",
            "tdirsi-native",
            "tdirsi_fast_ma_14_34_2_7_EMA_RMA",
            True,
            (30.0, 50.0, 70.0),
        ),
        ("smi", "smi-native", "smi_14_3", False, (0.0,)),
        ("mfi", "mfi-native", "mfi_14", True, (30.0, 50.0, 70.0)),
        ("obv", "obv-native", "obv", False, ()),
        ("volume", "volume-native", "volume", False, ()),
    ),
)
def test_native_oscillator_axis_policies_remain_unchanged(
    tool_key: str,
    study_id: str,
    output_name: str,
    fixed_bounds: bool,
    guide_values: tuple[float, ...],
) -> None:
    scene = build_oscillator_scene(
        _projection(study_id, output_name, (-10.0, 10.0, 30.0)),
        _presentation(study_id, output_name, tool_key=tool_key),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )

    if output_name == "volume":
        assert scene.axis_low == 0.0
        assert scene.axis_high > 30.0
    elif fixed_bounds:
        assert (scene.axis_low, scene.axis_high) == (0.0, 100.0)
    else:
        assert scene.axis_low < -10.0
        assert scene.axis_high > 30.0
    assert tuple(guide.value for guide in scene.guides) == guide_values


@pytest.mark.parametrize(
    "output_names",
    (
        ("close__d0",),
        ("sma_14_ema_14_hma_14", "sma_14_ema_14_hma_14_width"),
        ("close_ang_pct_span_0",),
        ("unknown_output",),
    ),
)
def test_malformed_unknown_oscillator_output_signatures_fail(
    output_names: tuple[str, ...]
) -> None:
    with pytest.raises(
        ValueError, match="oscillator projection outputs do not match Task 1014"
    ):
        build_oscillator_scene(
            _multi_projection("malformed", output_names),
            _multi_presentation("malformed", output_names),
            _viewport(),
            SceneRect(0.0, 0.0, 500.0, 120.0),
        )
