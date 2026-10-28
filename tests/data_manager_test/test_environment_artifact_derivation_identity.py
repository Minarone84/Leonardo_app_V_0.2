"""Exact metadata evidence for Study Artifact-source derivation (F1)."""
from dataclasses import replace

import pytest

from leonardo.artifacts import ArtifactLineageError
from leonardo.data_manager import DataManagerOperationError
from leonardo.financial_tools import resolve_output_names, resolve_parameters
from leonardo.recipes import build_portable_recipe
from leonardo.research import StudyEnvironmentDraft, StudyEnvironmentSourceV1
from tests.data_manager_test.test_update_workflow import (
    MARKET, _derivative, _domain, _materialize,
)
from tests.research_test.test_study_environment_models import fixture_environment


def _bb(period):
    parameters = dict(resolve_parameters("bb", {"period": period}))
    return build_portable_recipe(
        tool_key="bb", kind="indicator", parameters=parameters,
        output_names=resolve_output_names("bb", parameters),
    )


def _entry(recipe, identity, sources=()):
    template = fixture_environment().entries[0]
    return replace(
        template, entry_id=identity, kind=recipe.kind, tool_key=recipe.tool_key,
        display_name="Presentation is not calculation identity", parameters=recipe.parameters,
        sources=sources, expected_output_names=recipe.output_names,
        presentation=replace(template.presentation, line_styles=(), fill_styles=()),
    )


def _fixture(tmp_path, period=14, *, duplicate=False):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    saved_recipe = _bb(20)
    result = _materialize(service, recipes, saved_recipe)
    artifact_id = result.managed_artifacts[0].artifact_id
    source = StudyEnvironmentSourceV1(
        "source", "artifact", artifact_kind="indicator", artifact_tool_key="bb",
        artifact_id=artifact_id, output_name="bb_middle",
    )
    parameters = dict(resolve_parameters("derivative", {"order": 1}))
    derivative = build_portable_recipe(
        tool_key="derivative", kind="construct", parameters=parameters,
        output_names=resolve_output_names("derivative", {**parameters, "source": "__research_source"}),
    )
    entries = [_entry(_bb(period), "earlier")]
    if duplicate:
        entries.append(_entry(_bb(period), "duplicate"))
    entries.append(_entry(derivative, "dependent", (source,)))
    environment = service._study_environments.create(
        StudyEnvironmentDraft("F1 identity", "", MARKET, tuple(entries))
    )
    return service, artifacts, recipes, environment


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_different_parameters_block_derivation_without_publication(tmp_path):
    service, _artifacts, _recipes, environment = _fixture(tmp_path)
    before = _files(tmp_path)
    plan = service.plan_recipe_derivation(environment.environment_id, ("dependent",))
    assert plan.blocked
    with pytest.raises(DataManagerOperationError):
        service.persist_recipe_derivation(environment.environment_id, ("dependent",), create_collection=True, collection_display_name="F1 blocked")
    assert _files(tmp_path) == before


@pytest.mark.parametrize("collection", (False, True))
def test_equivalent_metadata_derives_without_payload_reads(tmp_path, monkeypatch, collection):
    service, artifacts, _recipes, environment = _fixture(tmp_path, period=20)
    def forbidden(*_args, **_kwargs):
        pytest.fail("derivation/classification read an Artifact payload")
    monkeypatch.setattr(artifacts, "load_artifact_by_id", forbidden)
    assert service.scan_study_environments().environments[0].valid
    plan = service.plan_recipe_derivation(environment.environment_id, ("dependent",))
    assert not plan.blocked, plan.blockers
    assert plan.support_entry_ids == ("earlier",)
    assert next(r for r in plan.recipes if r.tool_key == "bb").parameters["period"] == 20
    result = service.persist_recipe_derivation(environment.environment_id, ("dependent",), create_collection=collection, collection_display_name="F1 equivalent")
    assert result.root_recipe_ids


def test_missing_exact_artifact_metadata_blocks_without_aborting_catalog(tmp_path, monkeypatch):
    service, artifacts, _recipes, environment = _fixture(tmp_path, period=20)
    def missing(*_args):
        raise ArtifactLineageError("exact Artifact metadata unavailable")
    monkeypatch.setattr(artifacts, "load_artifact_metadata", missing)
    assert service.scan_study_environments().environments[0].valid
    plan = service.plan_recipe_derivation(environment.environment_id, ("dependent",))
    assert plan.blocked
    assert "metadata unavailable" in next(c.reason for c in plan.entry_classifications if c.entry_id == "dependent")


def test_ambiguous_equivalent_entries_remain_blocked(tmp_path):
    service, _artifacts, _recipes, environment = _fixture(tmp_path, period=20, duplicate=True)
    assert service.plan_recipe_derivation(environment.environment_id, ("dependent",)).blocked


def test_same_construct_output_does_not_hide_different_upstream_parameters(tmp_path):
    service, artifacts, recipes, _historical = _domain(tmp_path)
    saved_bb = _bb(20)
    recipes.save_recipe(saved_bb)
    saved_derivative = _derivative(saved_bb)
    result = _materialize(service, recipes, saved_derivative)
    artifact_id = artifacts.load_artifact_head(MARKET, result.root_logical_artifact_ids[0]).artifact_id
    prior_bb = _bb(14)
    prior_derivative = _derivative(prior_bb)
    root = _derivative(prior_derivative)
    environment = service._study_environments.create(StudyEnvironmentDraft(
        "Nested identity", "", MARKET, (
            _entry(prior_bb, "bb14"),
            _entry(prior_derivative, "d14", (StudyEnvironmentSourceV1(
                "source", "environment", source_entry_id="bb14", output_name=prior_bb.output_names[0],
            ),)),
            _entry(root, "root", (StudyEnvironmentSourceV1(
                "source", "artifact", artifact_kind="construct", artifact_tool_key="derivative",
                artifact_id=artifact_id, output_name=saved_derivative.output_names[0],
            ),)),
        ),
    ))
    assert service.plan_recipe_derivation(environment.environment_id, ("root",)).blocked
