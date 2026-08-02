from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from leonardo.financial_tools import get_financial_tool_spec
from leonardo.research import (
    ResearchStudyService,
    StudyFillStyle,
    StudyGuideStyle,
    StudyPresentation,
    StudyLineStyle,
    StudyPresentationRegistry,
    StudyPresentationValidationError,
    StudyInputSource,
    build_default_study_presentation,
)
from leonardo.research.study_presentation import (
    StudyBackgroundRegionStyle,
    _compact_study_label,
    _format_scalar,
    _parameter_text,
    _source_text,
)

from tests.research_test.test_study_execution import accepted_context, prepare


def _study(tmp_path: Path, tool_key: str, parameters=None, sources=()):
    dataset, artifacts, _frame = accepted_context(tmp_path)
    return prepare(
        ResearchStudyService(artifacts),
        dataset,
        tool_key,
        parameters=parameters or {},
        sources=sources,
    )


def _study_source(role: str, output_name: str) -> StudyInputSource:
    return StudyInputSource(
        role,
        "study",
        study_id=f"study-{role}",
        output_name=output_name,
    )


@pytest.mark.parametrize(
    ("tool_key", "parameters", "sources", "ordinal", "expected"),
    (
        ("sma", {"period": 14}, (), None, "SMA 14"),
        ("ema", {"period": 20}, (), None, "EMA 20"),
        ("tema", {"period": 14}, (), None, "TEMA 14"),
        ("hma", {"period": 30}, (), None, "HMA 30"),
        (
            "kama",
            {"fast_period": 2, "slow_period": 30},
            (),
            None,
            "KAMA 2 30",
        ),
        ("bb", {"period": 20, "std": 2.0}, (), None, "BB 20 2"),
        (
            "hck",
            {"fast_vwap_l": 13, "slow_vwap_l": 48},
            (),
            None,
            "HCK 13 48",
        ),
        ("strategy", {}, (), 1, "Strategy1"),
        ("peaks_troughs", {}, (), 1, "P&T1"),
        ("universal_trend_classifier", {}, (), 1, "UTC1"),
        ("rsi", {"period": 14}, (), None, "RSI 14"),
        (
            "arsi",
            {
                "period": 14,
                "method": "RMA",
                "signal_period": 14,
                "signal_method": "EMA",
            },
            (),
            None,
            "ARSI 14 RMA 14 EMA",
        ),
        (
            "tdirsi",
            {
                "period": 14,
                "band_length": 34,
                "band_mult": 1.6185,
                "fast_len": 2,
                "slow_len": 7,
                "fast_smo": "EMA",
                "slow_smo": "RMA",
            },
            (),
            None,
            "TDI 14 34 1.6185 2 7 EMA RMA",
        ),
        ("smi", {"k_length": 14, "d_length": 3}, (), None, "SMI 14 3"),
        ("mfi", {"period": 14}, (), None, "MFI 14"),
        ("obv", {}, (), None, "OBV"),
        ("volume", {"period": 20}, (), None, "Volume 20"),
        (
            "derivative",
            {"order": 1},
            (_study_source("source", "sma_14"),),
            None,
            "Derivative SRC:SMA_14 O:1",
        ),
        (
            "angle",
            {"unit": "deg"},
            (_study_source("source", "ema_20"),),
            None,
            "Angle SRC:EMA_20 U:deg",
        ),
        (
            "braids",
            {},
            (
                _study_source("fast", "sma_14"),
                _study_source("mid", "sma_25"),
                _study_source("slow", "sma_50"),
            ),
            None,
            "Braids F:SMA_14, M:SMA_25, S:SMA_50",
        ),
        (
            "braid_instability",
            {"n": 5},
            (
                _study_source("fast", "sma_14"),
                _study_source("mid", "sma_25"),
                _study_source("slow", "sma_50"),
            ),
            None,
            "Braid Instability F:SMA_14, M:SMA_25, S:SMA_50, N:5",
        ),
        (
            "delta",
            {"mode": "abs"},
            (
                _study_source("fast", "ema_12"),
                _study_source("slow", "ema_26"),
            ),
            None,
            "Delta F:EMA_12, S:EMA_26, M:abs",
        ),
        (
            "trap_area",
            {},
            (
                _study_source("fast", "sma_14"),
                _study_source("mid", "sma_25"),
                _study_source("slow", "sma_50"),
            ),
            None,
            "Trap Area F:SMA_14, M:SMA_25, S:SMA_50",
        ),
        (
            "trap_area",
            {},
            (
                _study_source("fast", "sma_14"),
                _study_source("slow", "sma_50"),
            ),
            None,
            "Trap Area F:SMA_14, M:—, S:SMA_50",
        ),
        (
            "percent_span_angle",
            {"window": 10, "unit": "deg"},
            (
                StudyInputSource("source_1", "ohlcv", column_name="close"),
                _study_source("source_2", "sma_14"),
            ),
            None,
            "PS Angle SRC:CLOSE/SMA_14 W:10 U:deg",
        ),
        (
            "angle_momentum",
            {"n": 3},
            (
                StudyInputSource("source_1", "ohlcv", column_name="close"),
                _study_source("source_2", "sma_14"),
            ),
            None,
            "Angle Momentum SRC:CLOSE/SMA_14 N:3",
        ),
    ),
)
def test_research_compact_label_matrix_is_exact(
    tool_key,
    parameters,
    sources,
    ordinal,
    expected,
) -> None:
    assert _compact_study_label(
        tool_key, parameters, sources, ordinal
    ) == expected


def test_compact_label_matrix_excludes_dynamic_binning_and_formats_scalars() -> None:
    assert tuple(
        _format_scalar(value)
        for value in (14, 2.0, 1.6185, 1e-12, "RMA", True, False, None)
    ) == ("14", "2", "1.6185", "1e-12", "RMA", "True", "False", "—")
    with pytest.raises(
        StudyPresentationValidationError,
        match="unsupported Research compact-label tool",
    ):
        _compact_study_label("dynamic_binning", {}, ())


def test_parameter_and_source_presentation_rules_are_exact() -> None:
    no_guides = SimpleNamespace(guide_styles={})
    bb = SimpleNamespace(
        result=SimpleNamespace(
            tool_key="bb",
            parameters={"period": 20, "std": 2.0},
        )
    )
    assert _parameter_text(bb, no_guides) == (
        "period=20; std=2",
        "Period: 20\nStd Dev Multiplier: 2",
    )
    braids = SimpleNamespace(
        result=SimpleNamespace(
            tool_key="braids",
            parameters={
                "fast": "__research_fast",
                "mid": "__research_mid",
                "slow": "__research_slow",
                "tie_policy": "carry",
            },
        )
    )
    assert _parameter_text(braids, no_guides) == (
        "tie_policy=carry",
        "Tie Policy: carry",
    )
    utc = SimpleNamespace(
        result=SimpleNamespace(
            tool_key="universal_trend_classifier",
            parameters={
                "source": "close",
                "fractal_window": 5,
                "trend_fractal_window": 5,
                "peak_column": "peak_fractal_5",
                "trough_column": "trough_fractal_5",
            },
        )
    )
    assert _parameter_text(utc, no_guides) == (
        "source=close; trend_fractal_window=5",
        "Source: close\nUp/Down Trend Fractal: 5",
    )
    guides = SimpleNamespace(
        guide_styles={
            "oversold": StudyGuideStyle(
                "oversold", "oversold", 30, "#22C55E", 1, "dashed"
            ),
            "center": StudyGuideStyle(
                "center", "center", 50, "#94A3B8", 1, "dashed"
            ),
            "overbought": StudyGuideStyle(
                "overbought", "overbought", 70, "#EF4444", 1, "dashed"
            ),
        }
    )
    rsi = SimpleNamespace(
        result=SimpleNamespace(tool_key="rsi", parameters={"period": 14})
    )
    assert _parameter_text(rsi, guides) == (
        "period=14",
        (
            "Period: 14\nGuide levels:\n"
            "Oversold: 30\nCenter: 50\nOverbought: 70"
        ),
    )

    implicit = SimpleNamespace(
        result=SimpleNamespace(tool_key="mfi"),
        edit_request=SimpleNamespace(input_sources=()),
    )
    assert _source_text(implicit) == (
        "OHLCV: HIGH, LOW, CLOSE, VOLUME",
        "OHLCV inputs: high, low, close, volume",
    )
    explicit_sources = (
        _study_source("fast", "sma_14"),
        StudyInputSource(
            "slow",
            "artifact",
            artifact_kind="indicator",
            artifact_tool_key="ema",
            artifact_id="a" * 64,
            output_name="ema_26",
        ),
    )
    explicit = SimpleNamespace(
        result=SimpleNamespace(tool_key="delta"),
        edit_request=SimpleNamespace(input_sources=explicit_sources),
    )
    assert _source_text(explicit) == (
        "F:SMA_14, S:EMA_26",
        (
            "F: Study study-fast, output sma_14\n"
            "S: Saved Artifact ema, ID aaaaaaaaaaaa, output ema_26"
        ),
    )


def test_real_default_oscillator_guide_details_use_semantic_order(
    tmp_path: Path,
) -> None:
    rsi = _study(tmp_path / "rsi", "rsi")
    assert _parameter_text(rsi, build_default_study_presentation(rsi)) == (
        "period=14",
        (
            "Period: 14\n"
            "Guide levels:\n"
            "Oversold: 30\n"
            "Center: 50\n"
            "Overbought: 70"
        ),
    )

    arsi = _study(tmp_path / "arsi", "arsi")
    arsi_details = _parameter_text(
        arsi, build_default_study_presentation(arsi)
    )[1]
    assert arsi_details[arsi_details.index("Guide levels:") :] == (
        "Guide levels:\n"
        "Oversold: 20\n"
        "Center: 50\n"
        "Overbought: 80"
    )

    smi = _study(tmp_path / "smi", "smi")
    smi_details = _parameter_text(
        smi, build_default_study_presentation(smi)
    )[1]
    assert smi_details[smi_details.index("Guide levels:") :] == (
        "Guide levels:\nZero: 0"
    )


def test_strict_style_validation_and_defensive_conditional_copy() -> None:
    colors = {"green": "#22C55E"}
    style = StudyLineStyle(
        "fast_vwap",
        "#22C55E",
        conditional_driver_name="vwap_color",
        conditional_colors=colors,
    )
    colors["green"] = "#FFFFFF"
    assert style.conditional_colors == {"green": "#22C55E"}
    with pytest.raises(StudyPresentationValidationError):
        StudyLineStyle("value", "#ffffff")
    with pytest.raises(StudyPresentationValidationError):
        StudyLineStyle("value", "#FFFFFF", line_width=0.1)
    with pytest.raises(StudyPresentationValidationError):
        StudyLineStyle("value", "#FFFFFF", render_mode="marker")
    with pytest.raises(StudyPresentationValidationError):
        StudyFillStyle("fill", "same", "same", "#FFFFFF")


def test_fixture_structural_defaults_and_duplicate_independence(tmp_path: Path) -> None:
    sma_a = replace(_study(tmp_path / "a", "sma", {"period": 3}), study_id="study-sma-a")
    sma_b = replace(_study(tmp_path / "b", "sma", {"period": 3}), study_id="study-sma-b")
    bb = replace(_study(tmp_path / "bb", "bb", {"period": 3, "std": 1.5}), study_id="study-bb")
    hck = replace(
        _study(tmp_path / "hck", "hck", {"fast_vwap_l": 3, "slow_vwap_l": 5}),
        study_id="study-hck",
    )
    rsi = replace(_study(tmp_path / "rsi", "rsi", {"period": 3}), study_id="study-rsi")
    dynamic = replace(
        _study(
            tmp_path / "dynamic",
            "dynamic_binning",
            {"window": 3, "n_bins": 5},
            (StudyInputSource("source_1", "ohlcv", column_name="close"),),
        ),
        study_id="study-dynamic",
    )

    first = build_default_study_presentation(sma_a)
    second = build_default_study_presentation(sma_b)
    assert first.tool_key == "sma"
    assert first.signal_styles["sma_3"].color == "#F59E0B"
    assert first.signal_styles is not second.signal_styles

    bb_style = build_default_study_presentation(bb)
    assert bb_style.tool_key == "bb"
    assert bb_style.signal_styles["bb_middle"].line_pattern == "solid"
    assert bb_style.signal_styles["bb_upper_band"].line_pattern == "dashed"
    assert bb_style.fill_styles["bb_band"].opacity == 0.12

    hck_style = build_default_study_presentation(hck)
    assert hck_style.tool_key == "hck"
    assert tuple(hck_style.signal_styles) == ("fast_vwap", "slow_vwap")
    for output_name in ("fast_vwap", "slow_vwap"):
        style = hck_style.signal_styles[output_name]
        assert style.conditional_driver_name == "vwap_color"
        assert style.conditional_colors == {
            "green": "#22C55E",
            "red": "#EF4444",
            "silver": "#22C55E",
        }
    assert hck_style.fill_styles["hck_band"] == StudyFillStyle(
        "hck_band",
        "fast_vwap",
        "slow_vwap",
        "#22C55E",
        0.08,
        True,
        conditional_driver_name="vwap_color",
        conditional_colors={
            "green": "#22C55E",
            "red": "#EF4444",
            "silver": "#22C55E",
        },
    )
    assert "vwap_color" not in hck_style.signal_styles

    rsi_style = build_default_study_presentation(rsi)
    assert rsi_style.tool_key == "rsi"
    assert rsi_style.pane_id == "oscillator:study-rsi"
    dynamic_style = build_default_study_presentation(dynamic)
    assert dynamic_style.tool_key == "dynamic_binning"
    assert dynamic_style.pane_id is None
    assert dynamic_style.signal_styles == {}

    expected = json.loads(
        (
            Path(__file__).parents[1]
            / "gui_test/fixtures/task_1018_study_rendering_expected.json"
        ).read_text(encoding="utf-8")
    )["default_presentations"]
    actual = {
        study.study_id: _presentation_dict(
            build_default_study_presentation(study), study.result.tool_key
        )
        for study in (sma_a, sma_b, bb, rsi, dynamic)
    }
    expected.pop("study-hck")
    assert actual == expected


def test_strategy_embedded_hck_uses_the_same_conditional_policy(
    tmp_path: Path,
) -> None:
    strategy = _study(tmp_path, "strategy")
    presentation = build_default_study_presentation(strategy)
    for output_name in ("st_fast_vwap", "st_slow_vwap"):
        style = presentation.signal_styles[output_name]
        assert style.conditional_driver_name == "st_vwap_color"
        assert style.conditional_colors["silver"] == "#22C55E"
        assert style.conditional_colors["red"] == "#EF4444"
    fill = presentation.fill_styles["st_hck_band"]
    assert fill.upper_output_name == "st_fast_vwap"
    assert fill.lower_output_name == "st_slow_vwap"
    assert fill.opacity == 0.08
    assert fill.conditional_driver_name == "st_vwap_color"
    assert fill.conditional_colors == {
        "green": "#22C55E",
        "red": "#EF4444",
        "silver": "#22C55E",
    }
    assert presentation.signal_styles["st_ema_1"].color == "#F59E0B"
    assert presentation.signal_styles["st_bb_upper_band"].line_pattern == "solid"
    assert "st_vwap_color" not in presentation.signal_styles


def test_canonical_oscillator_defaults_and_tdirsi_fill_are_exact(
    tmp_path: Path,
) -> None:
    cases = (
        (
            "rsi",
            {"period": 3},
            (("rsi_3", "#A855F7", "solid", True),),
            (),
        ),
        (
            "arsi",
            {},
            (
                ("arsi_14_rma", "#8B5CF6", "solid", True),
                ("arsi_signal_14_rma_14_ema", "#FF5D00", "solid", True),
            ),
            (),
        ),
        (
            "mfi",
            {"period": 3},
            (("mfi_3", "#14B8A6", "solid", True),),
            (),
        ),
        (
            "tdirsi",
            {},
            (
                ("tdirsi_fast_ma_14_34_2_7_ema_rma", "#22C55E", "solid", True),
                ("tdirsi_slow_ma_14_34_2_7_ema_rma", "#EF4444", "solid", True),
                ("tdirsi_up_14_34_2_7_ema_rma", "#60A5FA", "dashed", True),
                ("tdirsi_dn_14_34_2_7_ema_rma", "#60A5FA", "dashed", True),
                ("tdirsi_mid_14_34_2_7_ema_rma", "#F59E0B", "solid", True),
            ),
            ("tdirsi_band",),
        ),
        (
            "smi",
            {},
            (
                ("smi_14_3", "#06B6D4", "solid", True),
                ("smi_signal_14_3", "#F59E0B", "solid", True),
            ),
            (),
        ),
    )
    for tool_key, parameters, expected_lines, expected_fills in cases:
        study = _study(tmp_path / tool_key, tool_key, parameters)
        presentation = build_default_study_presentation(study)
        assert presentation.pane_id == f"oscillator:{study.study_id}"
        assert tuple(
            (
                name,
                style.color,
                style.line_pattern,
                style.visible,
            )
            for name, style in presentation.signal_styles.items()
        ) == expected_lines
        assert all(
            style.line_width == 1.0
            for style in presentation.signal_styles.values()
        )
        assert tuple(presentation.fill_styles) == expected_fills

    tdirsi = _study(tmp_path / "tdirsi-fill", "tdirsi")
    presentation = build_default_study_presentation(tdirsi)
    fill = presentation.fill_styles["tdirsi_band"]
    assert fill == StudyFillStyle(
        "tdirsi_band",
        "tdirsi_up_14_34_2_7_ema_rma",
        "tdirsi_dn_14_34_2_7_ema_rma",
        "#60A5FA",
        0.10,
        True,
    )
    assert fill.conditional_driver_name is None
    assert fill.conditional_colors == {}


def test_task_1050_semantic_default_color_matrix_is_exact(tmp_path: Path) -> None:
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)

    def prepared(tool_key, *, parameters=None, sources=(), studies=()):
        return prepare(
            service,
            dataset,
            tool_key,
            parameters=parameters or {},
            sources=sources,
            studies=studies,
        )

    expected_single = {
        "sma": "#F59E0B",
        "ema": "#22C55E",
        "tema": "#A855F7",
        "hma": "#06B6D4",
        "kama": "#EF4444",
        "rsi": "#A855F7",
        "mfi": "#14B8A6",
        "obv": "#E5E7EB",
    }
    for tool_key, color in expected_single.items():
        presentation = build_default_study_presentation(prepared(tool_key))
        assert {style.color for style in presentation.signal_styles.values()} == {color}

    bb = build_default_study_presentation(prepared("bb"))
    assert bb.signal_styles["bb_middle"].color == "#F59E0B"
    assert bb.signal_styles["bb_upper_band"].color == "#60A5FA"
    assert bb.signal_styles["bb_lower_band"].color == "#60A5FA"
    assert bb.fill_styles["bb_band"].color == "#60A5FA"
    assert bb.fill_styles["bb_band"].opacity == 0.12

    arsi = build_default_study_presentation(prepared("arsi"))
    assert tuple(style.color for style in arsi.signal_styles.values()) == (
        "#8B5CF6",
        "#FF5D00",
    )
    smi = build_default_study_presentation(prepared("smi"))
    assert tuple(style.color for style in smi.signal_styles.values()) == (
        "#06B6D4",
        "#F59E0B",
    )
    volume = build_default_study_presentation(prepared("volume"))
    assert next(
        style.color
        for name, style in volume.signal_styles.items()
        if name.startswith("volume_mean_")
    ) == "#06B6D4"

    source_studies = tuple(
        prepared(key, parameters={"period": 3}) for key in ("sma", "ema", "hma")
    )
    source_names = tuple(study.result.output_names[0] for study in source_studies)
    construct_cases = {
        "derivative": (
            "#FF9F1C",
            (StudyInputSource("source", "ohlcv", column_name="close"),),
            (),
        ),
        "angle": (
            "#00E5FF",
            (StudyInputSource("source", "ohlcv", column_name="close"),),
            (),
        ),
        "braids": (
            "#B967FF",
            tuple(
                StudyInputSource(
                    role,
                    "study",
                    study_id=study.study_id,
                    output_name=output,
                )
                for role, study, output in zip(
                    ("fast", "mid", "slow"),
                    source_studies,
                    source_names,
                    strict=True,
                )
            ),
            source_studies,
        ),
        "braid_instability": (
            "#FF3DCE",
            tuple(
                StudyInputSource(
                    role,
                    "study",
                    study_id=study.study_id,
                    output_name=output,
                )
                for role, study, output in zip(
                    ("fast", "mid", "slow"),
                    source_studies,
                    source_names,
                    strict=True,
                )
            ),
            source_studies,
        ),
        "delta": (
            "#FFF200",
            (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            ),
            (),
        ),
        "trap_area": (
            "#FF6B35",
            (
                StudyInputSource("fast", "ohlcv", column_name="high"),
                StudyInputSource("slow", "ohlcv", column_name="low"),
            ),
            (),
        ),
        "percent_span_angle": (
            "#39FF14",
            (StudyInputSource("source_1", "ohlcv", column_name="close"),),
            (),
        ),
        "angle_momentum": (
            "#4DA3FF",
            (StudyInputSource("source_1", "ohlcv", column_name="close"),),
            (),
        ),
    }
    for tool_key, (color, sources, studies) in construct_cases.items():
        presentation = build_default_study_presentation(
            prepared(tool_key, sources=sources, studies=studies)
        )
        assert {style.color for style in presentation.signal_styles.values()} == {color}

    peaks = build_default_study_presentation(prepared("peaks_troughs"))
    assert len(peaks.signal_styles) == 10
    assert all(style.marker_size == 14 for style in peaks.signal_styles.values())
    assert {
        name for name, style in peaks.signal_styles.items() if style.visible
    } == {"peak_fractal_3", "trough_fractal_3"}


@pytest.mark.parametrize(
    ("tool_key", "parameters", "expected"),
    (
        ("rsi", {"period": 3}, (("oversold", 30.0), ("center", 50.0), ("overbought", 70.0))),
        ("arsi", {}, (("oversold", 20.0), ("center", 50.0), ("overbought", 80.0))),
        ("mfi", {"period": 3}, (("oversold", 30.0), ("center", 50.0), ("overbought", 70.0))),
        ("tdirsi", {}, (("oversold", 30.0), ("center", 50.0), ("overbought", 70.0))),
        ("smi", {}, (("zero", 0.0),)),
    ),
)
def test_canonical_guide_defaults_are_spec_owned_and_immutable(
    tmp_path: Path,
    tool_key: str,
    parameters: dict[str, object],
    expected: tuple[tuple[str, float], ...],
) -> None:
    presentation = build_default_study_presentation(
        _study(tmp_path / tool_key, tool_key, parameters)
    )
    assert {
        guide.kind: guide.value
        for guide in presentation.guide_styles.values()
    } == dict(expected)
    with pytest.raises(TypeError):
        presentation.guide_styles["extra"] = next(
            iter(presentation.guide_styles.values())
        )


def test_guide_validation_reconciliation_and_revision_are_exact(
    tmp_path: Path,
) -> None:
    current = _study(tmp_path / "current-rsi", "rsi", {"period": 3})
    replacement = replace(
        _study(tmp_path / "replacement-rsi", "rsi", {"period": 5}),
        study_id=current.study_id,
    )
    defaults = build_default_study_presentation(current)
    with pytest.raises(StudyPresentationValidationError):
        StudyGuideStyle(
            "oversold", "oversold", float("nan"), "#22C55E", 1.0, "dashed"
        )
    with pytest.raises(StudyPresentationValidationError):
        replace(
            defaults,
            guide_styles={
                **defaults.guide_styles,
                "oversold": replace(
                    defaults.guide_styles["oversold"], value=75.0
                ),
            },
        )
    with pytest.raises(StudyPresentationValidationError):
        replace(
            defaults,
            guide_styles={
                "wrong": defaults.guide_styles["oversold"],
                "center": defaults.guide_styles["center"],
                "overbought": defaults.guide_styles["overbought"],
            },
        )

    registry = StudyPresentationRegistry()
    registry.register(current)
    customized = tuple(
        replace(guide, value=25.0)
        if guide.guide_id == "oversold"
        else guide
        for guide in defaults.guide_styles.values()
    )
    changed = registry.replace_guide_styles(current, customized)
    assert changed.revision == 1
    assert registry.replace_guide_styles(current, customized) is changed
    reconciled = registry.reconcile_for_edit(current, replacement)
    assert reconciled.study_id == current.study_id
    assert reconciled.guide_styles["oversold"].value == 25.0
    assert reconciled.guide_styles["oversold"].color == "#22C55E"


def test_tdirsi_custom_styles_survive_compatible_edit_by_output_position(
    tmp_path: Path,
) -> None:
    current = _study(tmp_path / "current", "tdirsi")
    replacement = replace(
        _study(
            tmp_path / "replacement",
            "tdirsi",
            {"period": 10, "band_length": 20},
        ),
        study_id=current.study_id,
    )
    registry = StudyPresentationRegistry()
    registered = registry.register(current)
    first_name = current.renderable_output_names[0]
    custom_line = replace(
        registered.signal_styles[first_name],
        color="#FFFFFF",
        line_width=2.0,
        line_pattern="dotted",
    )
    registry.replace_line_style(current, first_name, custom_line)
    current_presentation = registry.replace_fill_style(
        current,
        "tdirsi_band",
        replace(
            registry.get(current.study_id).fill_styles["tdirsi_band"],
            color="#123456",
            opacity=0.25,
            visible=False,
        ),
    )

    reconciled = registry.reconcile_for_edit(current, replacement)

    new_first = replacement.renderable_output_names[0]
    assert reconciled.signal_styles[new_first] == replace(
        custom_line, output_name=new_first
    )
    assert reconciled.fill_styles["tdirsi_band"] == replace(
        build_default_study_presentation(replacement).fill_styles["tdirsi_band"],
        color="#123456",
        opacity=0.25,
        visible=False,
    )
    assert reconciled.revision == current_presentation.revision


def test_registry_revision_reset_and_manager_order(tmp_path: Path) -> None:
    first = _study(tmp_path / "first", "sma", {"period": 3})
    second = _study(tmp_path / "second", "sma", {"period": 3})
    dynamic = _study(
        tmp_path / "dynamic",
        "dynamic_binning",
        {"window": 3, "n_bins": 5},
        (StudyInputSource("source_1", "ohlcv", column_name="close"),),
    )
    registry = StudyPresentationRegistry()
    registry.register(first)
    registry.register(second)
    registry.register(dynamic)

    original = registry.get(second.study_id)
    changed_style = replace(
        original.signal_styles["sma_3"],
        color="#FFFFFF",
        line_width=2.0,
        line_pattern="dashed",
    )
    changed = registry.replace_line_style(second, "sma_3", changed_style)
    assert changed.revision == 1
    assert registry.get(first.study_id).revision == 0
    assert registry.replace_line_style(second, "sma_3", changed_style) is changed
    hidden = registry.set_visibility(second, False)
    assert hidden.revision == 2
    reset = registry.reset(second)
    assert reset.revision == 3
    assert reset.signal_styles["sma_3"].color == "#F59E0B"

    entries = registry.manager_entries((first, dynamic, second))
    assert tuple(item.study_id for item in entries) == (first.study_id, second.study_id)
    assert tuple(item.pane_label for item in entries) == ("Price", "Price")
    assert entries[0].compact_label == "SMA 3"
    assert entries[0].parameter_summary == "period=3"
    assert entries[0].parameter_details == "Period: 3"
    assert entries[0].source_summary == "OHLCV: CLOSE"
    assert entries[0].source_details == "OHLCV inputs: close"
    assert entries[0].origin_label == "Calculated"


def _utc_study(tmp_path: Path):
    dataset, artifacts, _frame = accepted_context(tmp_path)
    service = ResearchStudyService(artifacts)
    peaks = prepare(service, dataset, "peaks_troughs")
    sources = (
        StudyInputSource(
            "trend_peak",
            "study",
            study_id=peaks.study_id,
            output_name="peak_fractal_5",
        ),
        StudyInputSource(
            "trend_trough",
            "study",
            study_id=peaks.study_id,
            output_name="trough_fractal_5",
        ),
        StudyInputSource(
            "range_peak",
            "study",
            study_id=peaks.study_id,
            output_name="peak_fractal_3",
        ),
        StudyInputSource(
            "range_trough",
            "study",
            study_id=peaks.study_id,
            output_name="trough_fractal_3",
        ),
    )
    return prepare(
        service,
        dataset,
        "universal_trend_classifier",
        sources=sources,
        studies=(peaks,),
    )


def test_numbered_study_ordinals_are_chart_local_stable_and_reset(
    tmp_path: Path,
) -> None:
    utc_one = replace(_utc_study(tmp_path / "utc"), study_id="utc-one")
    utc_two = replace(utc_one, study_id="utc-two")
    registry = StudyPresentationRegistry()
    registry.register(utc_one)
    registry.register(utc_two)
    assert tuple(
        entry.compact_label
        for entry in registry.manager_entries((utc_one, utc_two))
    ) == ("UTC1", "UTC2")

    registry.remove(utc_one.study_id)
    assert registry.manager_entries((utc_two,))[0].compact_label == "UTC2"
    utc_three = replace(utc_one, study_id="utc-three")
    registry.register(utc_three)
    assert tuple(
        entry.compact_label
        for entry in registry.manager_entries((utc_two, utc_three))
    ) == ("UTC2", "UTC3")

    peaks = replace(
        _study(tmp_path / "peaks", "peaks_troughs"),
        study_id="peaks-one",
    )
    strategy = replace(
        _study(tmp_path / "strategy", "strategy"),
        study_id="strategy-one",
    )
    registry.register(peaks)
    registry.register(strategy)
    entries = registry.manager_entries((utc_two, utc_three, peaks, strategy))
    assert tuple(entry.compact_label for entry in entries) == (
        "UTC2",
        "UTC3",
        "P&T1",
        "Strategy1",
    )
    assert "ema_1_period=9" in entries[-1].parameter_summary
    assert "EMA 1 Period: 9" in entries[-1].parameter_details
    assert entries[-1].source_summary == "OHLCV: HIGH, LOW, CLOSE, VOLUME"

    reconciled = registry.reconcile_for_edit(utc_two, utc_two)
    registry.replace_for_edit(utc_two, reconciled)
    assert (
        registry.manager_entries((utc_two, utc_three, peaks, strategy))[0]
        .compact_label
        == "UTC2"
    )

    assert registry.clear() == 4
    utc_reset = replace(utc_one, study_id="utc-reset")
    registry.register(utc_reset)
    assert registry.manager_entries((utc_reset,))[0].compact_label == "UTC1"


def test_utc_background_regions_are_exact_immutable_additional_defaults(
    tmp_path: Path,
) -> None:
    utc = _utc_study(tmp_path)
    presentation = build_default_study_presentation(utc)
    assert tuple(presentation.background_region_styles) == (
        "utc_uptrend",
        "utc_downtrend",
    )
    assert presentation.background_region_styles["utc_uptrend"] == (
        StudyBackgroundRegionStyle("utc_uptrend", "uptrend", "#22C55E")
    )
    assert presentation.background_region_styles["utc_downtrend"] == (
        StudyBackgroundRegionStyle("utc_downtrend", "downtrend", "#EF4444")
    )
    assert "utc_range" not in presentation.fill_styles
    assert presentation.signal_styles["hor_upper"].visible
    assert presentation.signal_styles["hor_lower"].visible
    marker_names = {
        "hr_start_marker",
        "hr_end_marker",
        "uptrend_start_marker",
        "uptrend_end_marker",
        "downtrend_start_marker",
        "downtrend_end_marker",
    }
    assert {
        name
        for name, style in presentation.signal_styles.items()
        if style.render_mode == "marker" and style.marker_shape == "circle"
    } == marker_names
    assert not {
        "horizontal_range",
        "uptrend",
        "downtrend",
        "uptrend_reclaim",
        "downtrend_reclaim",
        "hr_reclaim_marker",
    }.intersection(presentation.signal_styles)
    assert presentation.background_region_styles["utc_uptrend"].opacity == 0.08
    assert presentation.background_region_styles["utc_downtrend"].opacity == 0.08
    with pytest.raises(TypeError):
        presentation.background_region_styles["extra"] = StudyBackgroundRegionStyle(
            "extra", "uptrend", "#22C55E"
        )
    with pytest.raises(StudyPresentationValidationError):
        StudyBackgroundRegionStyle(
            "invalid", "uptrend", "#22C55E", opacity=float("nan")
        )

    registry = StudyPresentationRegistry()
    registry.register(utc)
    hidden = replace(
        presentation.background_region_styles["utc_uptrend"],
        visible=False,
    )
    retained = registry._replace(
        utc,
        replace(
            presentation,
            background_region_styles={
                **presentation.background_region_styles,
                "utc_uptrend": hidden,
            },
        ),
    )
    assert not retained.background_region_styles["utc_uptrend"].visible
    with pytest.raises(
        StudyPresentationValidationError, match="unknown background region driver"
    ):
        registry._replace(
            utc,
            replace(
                presentation,
                background_region_styles={
                    "unknown": StudyBackgroundRegionStyle(
                        "unknown", "not_an_output", "#22C55E"
                    )
                },
            ),
        )


def _presentation_dict(presentation, tool_key: str) -> dict[str, object]:
    result: dict[str, object] = {
        "pane_id": presentation.pane_id,
        "signal_styles": {
            name: {
                "color": style.color,
                "line_pattern": style.line_pattern,
                "line_width": style.line_width,
                "render_mode": style.render_mode,
                "visible": style.visible,
                **(
                    {
                        "conditional_driver_name": style.conditional_driver_name,
                        "conditional_colors": dict(style.conditional_colors),
                    }
                    if style.conditional_driver_name is not None
                    else {}
                ),
            }
            for name, style in presentation.signal_styles.items()
        },
        "visible": presentation.visible,
    }
    if presentation.fill_styles:
        result["fills"] = {
            fill_id: {
                "color": style.color,
                "lower_output_name": style.lower_output_name,
                "opacity": style.opacity,
                "upper_output_name": style.upper_output_name,
                "visible": style.visible,
            }
            for fill_id, style in presentation.fill_styles.items()
        }
    visual = get_financial_tool_spec(tool_key).oscillator_visual
    if visual is not None:
        result["axis"] = {
            "bounds": list(visual.bounds) if visual.bounds is not None else None,
            "guides": [
                {"kind": guide.kind, "value": guide.value}
                for guide in sorted(visual.guide_levels, key=lambda item: item.value)
                if guide.visible
            ],
            "range_mode": visual.range_mode,
        }
    return result
