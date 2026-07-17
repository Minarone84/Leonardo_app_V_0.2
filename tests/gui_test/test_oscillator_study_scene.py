from __future__ import annotations

import pytest

from leonardo.data import MarketId
from leonardo.gui.chart.candlestick_scene import SceneRect
from leonardo.gui.chart.oscillator_scene import build_oscillator_scene
from leonardo.research import (
    ResidentStudyProjection,
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


def _presentation(study_id: str, name: str, *, visible: bool = True):
    return StudyPresentation(
        study_id,
        visible,
        f"oscillator:{study_id}",
        {name: StudyLineStyle(name, "#A855F7")},
        {},
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


def _multi_presentation(study_id: str, names: tuple[str, ...]):
    return StudyPresentation(
        study_id,
        True,
        f"oscillator:{study_id}",
        {name: StudyLineStyle(name, "#A855F7") for name in names},
        {},
    )


def _viewport(count: int = 10):
    return ViewportSnapshot(count, 0, 0, 0, count, 1, count, count - 1, None)


def test_rsi_uses_fixed_bounds_sorted_guides_and_shared_horizontal_range() -> None:
    projection = _projection("rsi", "rsi_3", (20.0, 30.0, 50.0, 70.0, 80.0))
    scene = build_oscillator_scene(
        projection,
        _presentation("rsi", "rsi_3"),
        _viewport(),
        SceneRect(0.0, 0.0, 900.0, 180.0),
    )

    assert (scene.axis_low, scene.axis_high) == (0.0, 100.0)
    assert tuple((guide.kind, guide.value) for guide in scene.guides) == (
        ("oversold", 30.0),
        ("center", 50.0),
        ("overbought", 70.0),
    )
    assert tuple(point.global_index for point in scene.line_strips[0].points) == (
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
    ("study_id", "output_names"),
    (
        ("derivative", ("close__d1",)),
        ("angle", ("close__ang",)),
        (
            "braids",
            (
                "sma_14_ema_14_hma_14",
                "sma_14_ema_14_hma_14_width",
                "sma_14_ema_14_hma_14_compression",
            ),
        ),
        ("braid-instability", ("sma_14_ema_14_hma_14_inst_5",)),
        ("delta", ("close_open_delta",)),
        (
            "trap-area",
            ("fast_mid_trapA", "fast_slow_trapA", "mid_slow_trapA"),
        ),
        (
            "percent-span-angle",
            ("close_ang_pct_span_10", "volume_ang_pct_span_10"),
        ),
        ("angle-momentum", ("close_ang_mtm_3", "volume_ang_mtm_3")),
    ),
)
def test_all_canonical_construct_oscillators_use_auto_bounds_without_guides(
    study_id: str, output_names: tuple[str, ...]
) -> None:
    scene = build_oscillator_scene(
        _multi_projection(study_id, output_names),
        _multi_presentation(study_id, output_names),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )

    assert scene.axis_low < 1.0
    assert scene.axis_high > float(len(output_names) + 2)
    assert scene.guides == ()


@pytest.mark.parametrize(
    ("study_id", "output_name", "fixed_bounds", "guide_values"),
    (
        ("rsi-native", "rsi_14", True, (30.0, 50.0, 70.0)),
        ("arsi-native", "arsi_14_RMA", True, (20.0, 50.0, 80.0)),
        (
            "tdirsi-native",
            "tdirsi_fast_ma_14_34_2_7_EMA_RMA",
            True,
            (30.0, 50.0, 70.0),
        ),
        ("smi-native", "smi_14_3", False, (0.0,)),
        ("mfi-native", "mfi_14", True, (30.0, 50.0, 70.0)),
        ("obv-native", "obv", False, ()),
        ("volume-native", "volume", False, ()),
    ),
)
def test_native_oscillator_axis_policies_remain_unchanged(
    study_id: str,
    output_name: str,
    fixed_bounds: bool,
    guide_values: tuple[float, ...],
) -> None:
    scene = build_oscillator_scene(
        _projection(study_id, output_name, (-10.0, 10.0, 30.0)),
        _presentation(study_id, output_name),
        _viewport(),
        SceneRect(0.0, 0.0, 500.0, 120.0),
    )

    if fixed_bounds:
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
