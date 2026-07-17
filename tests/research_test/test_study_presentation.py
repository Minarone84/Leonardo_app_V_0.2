from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.financial_tools import get_financial_tool_spec
from leonardo.research import (
    ResearchStudyService,
    StudyFillStyle,
    StudyLineStyle,
    StudyPresentationRegistry,
    StudyPresentationValidationError,
    StudyInputSource,
    build_default_study_presentation,
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
    assert first.signal_styles["sma_3"].color == "#F59E0B"
    assert first.signal_styles is not second.signal_styles

    bb_style = build_default_study_presentation(bb)
    assert bb_style.signal_styles["bb_middle"].line_pattern == "solid"
    assert bb_style.signal_styles["bb_upper_band"].line_pattern == "dashed"
    assert bb_style.fill_styles["bb_band"].opacity == 0.12

    hck_style = build_default_study_presentation(hck)
    assert tuple(hck_style.signal_styles) == ("fast_vwap", "slow_vwap")
    assert hck_style.signal_styles["fast_vwap"].conditional_driver_name == "vwap_color"
    assert "vwap_color" not in hck_style.signal_styles

    assert build_default_study_presentation(rsi).pane_id == "oscillator:study-rsi"
    dynamic_style = build_default_study_presentation(dynamic)
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
        for study in (sma_a, sma_b, bb, hck, rsi, dynamic)
    }
    assert actual == expected


def test_registry_revision_reset_and_manager_order(tmp_path: Path) -> None:
    first = _study(tmp_path / "first", "sma", {"period": 3})
    second = _study(tmp_path / "second", "sma", {"period": 3})
    registry = StudyPresentationRegistry()
    registry.register(first)
    registry.register(second)

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

    entries = registry.manager_entries((first, second))
    assert tuple(item.study_id for item in entries) == (first.study_id, second.study_id)
    assert tuple(item.pane_label for item in entries) == ("Price", "Price")


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
