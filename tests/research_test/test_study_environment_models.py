from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.research import (
    StudyEnvironmentEntryV1,
    StudyEnvironmentSourceV1,
    StudyEnvironmentV1,
    StudyEnvironmentValidationError,
    StudyGuideStyle,
    environment_content_hash,
)


FIXTURE = (
    Path(__file__).parents[1]
    / "gui_test"
    / "fixtures"
    / "task_1021_study_setup_environment_input.json"
)


def fixture_environment() -> StudyEnvironmentV1:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["environment"]
    return StudyEnvironmentV1.from_dict(payload)


def test_frozen_environment_fixture_round_trips_with_exact_hash() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["environment"]
    environment = StudyEnvironmentV1.from_dict(payload)

    assert environment.content_hash == "bd15fa8d969fe75ee9457e5a05fcb74cb9b1f76822a1c039d7d0849964777306"
    assert environment_content_hash(payload) == environment.content_hash
    assert environment.to_dict() == payload
    assert StudyEnvironmentV1.from_dict(
        json.loads(environment.canonical_json_bytes())
    ) == environment


def _rsi_guides() -> tuple[StudyGuideStyle, ...]:
    return (
        StudyGuideStyle(
            "overbought", "overbought", 75.0, "#EF4444", 1.0, "dashed"
        ),
        StudyGuideStyle(
            "center", "center", 50.0, "#94A3B8", 1.0, "dashed"
        ),
        StudyGuideStyle(
            "oversold", "oversold", 25.0, "#22C55E", 1.0, "dashed"
        ),
    )


def test_environment_round_trip_preserves_full_guide_styles() -> None:
    legacy = fixture_environment()
    rsi_entry = legacy.entries[1]
    customized = replace(
        rsi_entry,
        presentation=replace(
            rsi_entry.presentation,
            guide_styles=_rsi_guides(),
        ),
    )
    environment = StudyEnvironmentV1.build(
        environment_id=legacy.environment_id,
        display_name=legacy.display_name,
        description=legacy.description,
        created_at_utc=legacy.created_at_utc,
        updated_at_utc=legacy.updated_at_utc,
        created_from=legacy.created_from,
        entries=(legacy.entries[0], customized, *legacy.entries[2:]),
    )

    restored = StudyEnvironmentV1.from_dict(
        json.loads(environment.canonical_json_bytes())
    )
    assert restored.entries[1].presentation.guide_styles == _rsi_guides()
    assert restored.to_dict()["entries"][1]["presentation"]["guide_styles"] == [
        {
            "guide_id": guide.guide_id,
            "kind": guide.kind,
            "value": guide.value,
            "color": guide.color,
            "line_width": guide.line_width,
            "line_pattern": guide.line_pattern,
            "visible": guide.visible,
        }
        for guide in _rsi_guides()
    ]


def test_legacy_environment_without_guide_styles_remains_readable() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["environment"]
    assert all(
        "guide_styles" not in entry["presentation"]
        for entry in payload["entries"]
    )
    restored = StudyEnvironmentV1.from_dict(payload)
    assert all(
        entry.presentation.guide_styles == ()
        for entry in restored.entries
    )
    assert restored.to_dict() == payload


@pytest.mark.parametrize(
    "guides",
    (
        (_rsi_guides()[0], _rsi_guides()[0]),
        _rsi_guides()[:2],
        tuple(reversed(_rsi_guides())),
        (*_rsi_guides(), StudyGuideStyle(
            "zero", "zero", 0.0, "#94A3B8", 1.0, "dashed"
        )),
    ),
)
def test_nonempty_environment_guide_lists_must_be_exact(
    guides: tuple[StudyGuideStyle, ...],
) -> None:
    entry = fixture_environment().entries[1]
    with pytest.raises(StudyEnvironmentValidationError):
        replace(
            entry,
            presentation=replace(entry.presentation, guide_styles=guides),
        )


def test_environment_is_topological_and_contains_no_runtime_fields() -> None:
    environment = fixture_environment()
    encoded = environment.canonical_json_bytes().decode("utf-8")

    assert tuple(item.entry_id for item in environment.entries) == (
        "entry_001", "entry_002", "entry_003", "entry_004"
    )
    for forbidden in (
        "study_id", "session_id", "generation", "pane_id", "revision",
        "chart_slot", "workspace_position", "detached", "viewport", "dataframe",
        "renderer_key", "cache",
    ):
        assert f'"{forbidden}"' not in encoded


def test_forward_reference_and_invalid_metadata_are_rejected() -> None:
    environment = fixture_environment()
    source_entry = environment.entries[0]
    dependent = environment.entries[2]
    with pytest.raises(StudyEnvironmentValidationError, match="earlier"):
        StudyEnvironmentV1.build(
            environment_id="env_invalid",
            display_name="Invalid",
            description="",
            created_at_utc=environment.created_at_utc,
            updated_at_utc=environment.updated_at_utc,
            created_from=environment.created_from,
            entries=(dependent, source_entry),
        )
    with pytest.raises(ValueError):
        replace(source_entry.user_metadata, dataset_role="not_a_role")


def test_unknown_style_outputs_are_rejected() -> None:
    environment = fixture_environment()
    entry = environment.entries[0]
    line = replace(entry.presentation.line_styles[0], output_name="unknown")
    with pytest.raises(StudyEnvironmentValidationError, match="outside expected"):
        replace(
            entry,
            presentation=replace(entry.presentation, line_styles=(line,)),
        )


def test_direct_artifact_entry_can_be_an_earlier_environment_dependency() -> None:
    environment = fixture_environment()
    artifact = environment.entries[3]
    delta = environment.entries[2]
    dependent = replace(
        delta,
        sources=(
            StudyEnvironmentSourceV1(
                "fast",
                "environment",
                source_entry_id=artifact.entry_id,
                output_name="sma_50",
            ),
            StudyEnvironmentSourceV1(
                "slow",
                "environment",
                source_entry_id=artifact.entry_id,
                output_name="sma_50",
            ),
        ),
    )
    rebuilt = StudyEnvironmentV1.build(
        environment_id="env_artifact_dependency",
        display_name="Artifact Dependency",
        description="",
        created_at_utc=environment.created_at_utc,
        updated_at_utc=environment.updated_at_utc,
        created_from=environment.created_from,
        entries=(artifact, dependent),
    )
    assert rebuilt.entries[1].sources[0].source_entry_id == artifact.entry_id


def test_braid_mid_is_required_while_trap_area_mid_remains_optional() -> None:
    environment = fixture_environment()
    delta = environment.entries[2]
    empty_presentation = replace(
        delta.presentation,
        line_styles=(),
        fill_styles=(),
    )

    for tool_key, parameters in (
        ("braids", {"tie_policy": "carry"}),
        ("braid_instability", {"n": 5}),
    ):
        with pytest.raises(StudyEnvironmentValidationError):
            replace(
                delta,
                tool_key=tool_key,
                display_name=tool_key,
                parameters=parameters,
                expected_output_names=("placeholder",),
                presentation=empty_presentation,
            )

    trap_area = replace(
        delta,
        tool_key="trap_area",
        display_name="Trap Area",
        parameters={"zero_eps": 0.0},
        expected_output_names=("research_fast_research_slow_trapA",),
        presentation=empty_presentation,
    )
    assert tuple(source.role for source in trap_area.sources) == ("fast", "slow")


def _utc_environment_entry(
    *,
    artifact_ids: tuple[str, str, str, str] = ("c" * 64,) * 4,
    outputs: tuple[str, str, str, str] = (
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_3",
        "trough_fractal_3",
    ),
) -> StudyEnvironmentEntryV1:
    template = fixture_environment().entries[2]
    canonical = dict(resolve_parameters("universal_trend_classifier", {}))
    canonical.pop("peak_column")
    canonical.pop("trough_column")
    selectors = {
        **canonical,
        "peak_column": "peak_fractal_5",
        "trough_column": "trough_fractal_5",
    }
    roles = ("trend_peak", "trend_trough", "range_peak", "range_trough")
    sources = tuple(
        StudyEnvironmentSourceV1(
            role,
            "artifact",
            artifact_kind="indicator",
            artifact_tool_key="peaks_troughs",
            artifact_id=artifact_id,
            output_name=output,
        )
        for role, artifact_id, output in zip(
            roles, artifact_ids, outputs, strict=True
        )
    )
    return replace(
        template,
        entry_id="entry_utc",
        kind="indicator",
        tool_key="universal_trend_classifier",
        display_name="Universal Trend Classifier",
        parameters=canonical,
        sources=sources,
        expected_output_names=resolve_output_names(
            "universal_trend_classifier", selectors
        ),
        presentation=replace(
            template.presentation,
            line_styles=(),
            fill_styles=(),
        ),
    )


def _build_utc_environment(entry: StudyEnvironmentEntryV1) -> StudyEnvironmentV1:
    template = fixture_environment()
    return StudyEnvironmentV1.build(
        environment_id="env_utc",
        display_name="UTC",
        description="UTC dependencies",
        created_at_utc=template.created_at_utc,
        updated_at_utc=template.updated_at_utc,
        created_from=template.created_from,
        entries=(entry,),
    )


def test_utc_environment_round_trip_preserves_exact_four_role_lineage() -> None:
    environment = _build_utc_environment(_utc_environment_entry())
    restored = StudyEnvironmentV1.from_dict(
        json.loads(environment.canonical_json_bytes())
    )
    assert tuple(source.role for source in restored.entries[0].sources) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )
    assert restored == environment


def test_utc_environment_rejects_missing_misordered_wrong_output_and_owner() -> None:
    entry = _utc_environment_entry()
    for sources in (entry.sources[:2], entry.sources[2:]):
        with pytest.raises(StudyEnvironmentValidationError):
            replace(entry, sources=sources)
    with pytest.raises(StudyEnvironmentValidationError):
        replace(entry, sources=tuple(reversed(entry.sources)))

    wrong_output = list(entry.sources)
    wrong_output[2] = replace(wrong_output[2], output_name="peak_fractal_5")
    with pytest.raises(StudyEnvironmentValidationError, match="must be"):
        _build_utc_environment(replace(entry, sources=tuple(wrong_output)))

    mixed_owner = _utc_environment_entry(
        artifact_ids=("c" * 64, "c" * 64, "d" * 64, "d" * 64)
    )
    with pytest.raises(StudyEnvironmentValidationError, match="one Peaks"):
        _build_utc_environment(mixed_owner)
