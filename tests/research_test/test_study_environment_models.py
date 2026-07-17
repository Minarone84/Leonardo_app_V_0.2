from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from leonardo.research import (
    StudyEnvironmentEntryV1,
    StudyEnvironmentSourceV1,
    StudyEnvironmentV1,
    StudyEnvironmentValidationError,
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
