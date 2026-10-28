from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from leonardo.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactIdentityCollisionError,
    ArtifactService,
    ArtifactValidationError,
)
from leonardo.artifacts._stores import _io_path
from leonardo.financial_tools import calculate_financial_tool, get_financial_tool_spec
from leonardo.ohlcv.store import OHLCVStore
from leonardo.research import ResearchStudyService

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.artifacts_test.test_managed_artifact_versions import _recovery_bytes
from tests.data_manager_test.test_direct_artifact_creation import _domain, _request
from tests.research_test.test_study_execution import prepare


CREATED = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 2, 1, tzinfo=UTC)
PORTABLE_ID = "a" * 64
ROUTES = ("recipe", "calculation", "managed")
TOOLS = (("sma", "SMA"), ("ema", "EMA"), ("bb", "Bollinger Bands"))


def _source_hashes(root, market):
    store = OHLCVStore(root)
    return tuple(
        hashlib.sha256(_io_path(path).read_bytes()).hexdigest()
        for path in (store.csv_path(market), store.sidecar_path(market))
    )


def _invoke(route, service, market, calculation, **metadata):
    if route == "recipe":
        return service.save_recipe_from_result(market, calculation, **metadata)
    if route == "calculation":
        return service.save_calculation(market, calculation, **metadata)
    assert route == "managed"
    return service.prepare_managed_calculation(
        market, PORTABLE_ID, calculation,
        expected_source=service.capture_accepted_source(market), **metadata,
    )


def _recipe(route, result):
    return result.recipe if route == "recipe" else result.metadata.recipe


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("tool,title", TOOLS)
def test_automatic_titles_preserve_canonical_calculation(tmp_path, route, tool, title):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source_before = _source_hashes(tmp_path, market)
    calculation = calculate_financial_tool(tool, frame, {"period": 3})
    original = calculation.to_frame()
    result = _invoke(route, service, market, calculation)
    recipe = _recipe(route, result)
    assert recipe.display_name == title == get_financial_tool_spec(tool).title
    assert recipe.description == ""
    assert recipe.tool_key == calculation.tool_key == tool
    assert recipe.output_names == calculation.output_names
    assert recipe.parameters == calculation.parameters
    assert recipe.bindings == calculation.bindings
    if route == "recipe":
        result = service.save_calculation(market, calculation)
    elif route == "managed":
        service.publish_managed_artifact_graph(
            (result,), expected_source=service.capture_accepted_source(market)
        )
    loaded = service.load_artifact_by_id(market, result.metadata.artifact_id)
    assert loaded.metadata.recipe == recipe
    pd.testing.assert_frame_equal(loaded.frame, original.reset_index(drop=True))
    pd.testing.assert_frame_equal(calculation.to_frame(), original)
    assert _source_hashes(tmp_path, market) == source_before


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("name", ("SMA", "sma", "My SMA"))
@pytest.mark.parametrize("explicit", ("neither", "name", "description", "both"))
def test_existing_metadata_reuse_preserves_recipe_bytes(tmp_path, route, name, explicit):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    calculation = calculate_financial_tool("sma", frame, {"period": 3})
    source_before = _source_hashes(tmp_path, market)
    seeded = service.save_recipe_from_result(
        market, calculation, display_name=name, description="Saved description",
        created_at_utc=CREATED,
    )
    before = _recovery_bytes(tmp_path)
    recipe_bytes = _io_path(seeded.path).read_bytes()
    metadata = {"created_at_utc": LATER}
    if explicit in ("name", "both"):
        metadata["display_name"] = " " + name + " "
    if explicit in ("description", "both"):
        metadata["description"] = " Saved description "
    reused = _invoke(route, service, market, calculation, **metadata)
    assert _recipe(route, reused) == seeded.recipe
    assert _recipe(route, reused).created_at_utc == CREATED
    assert _io_path(seeded.path).read_bytes() == recipe_bytes
    after = _recovery_bytes(tmp_path)
    assert all(after[path] == content for path, content in before.items())
    if route != "calculation":
        assert after == before
    if route == "recipe":
        assert reused.created is False
    if route == "managed":
        assert reused.recipe_bytes == recipe_bytes
    assert _source_hashes(tmp_path, market) == source_before


@pytest.mark.parametrize("name", ("SMA", "sma", "My SMA"))
def test_unmanaged_adoption_preserves_all_original_bytes_and_identity(tmp_path, name):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    calculation = calculate_financial_tool("sma", frame, {"period": 3})
    source_before = _source_hashes(tmp_path, market)
    saved = service.save_calculation(
        market, calculation, display_name=name, description="Saved description",
        created_at_utc=CREATED,
    )
    before = _recovery_bytes(tmp_path)
    original_values, original_analysis, original_metadata = service._store.read_artifact_bytes(saved.path)
    prepared = _invoke("managed", service, market, calculation, created_at_utc=LATER)
    assert prepared.metadata == saved.metadata
    assert prepared.metadata_bytes == original_metadata
    assert prepared.values_bytes == original_values
    assert prepared.analysis_bytes == original_analysis
    assert _recovery_bytes(tmp_path) == before
    published = service.publish_managed_artifact_graph(
        (prepared,), expected_source=service.capture_accepted_source(market)
    )
    assert published.reused_artifact_ids == (saved.metadata.artifact_id,)
    after = _recovery_bytes(tmp_path)
    assert all(after[path] == content for path, content in before.items())
    assert service.load_artifact_by_id(market, saved.metadata.artifact_id).metadata == saved.metadata
    with pytest.raises(ArtifactAlreadyExistsError):
        service.save_calculation(market, calculation)
    assert _recovery_bytes(tmp_path) == after
    assert _source_hashes(tmp_path, market) == source_before


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("metadata", (
    {"display_name": "Different SMA"},
    {"description": "Different description"},
    {"description": ""},
))
def test_explicit_metadata_collisions_leave_every_byte_unchanged(tmp_path, route, metadata):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    calculation = calculate_financial_tool("sma", frame, {"period": 3})
    service.save_recipe_from_result(
        market, calculation, display_name="My SMA", description="Saved description",
        created_at_utc=CREATED,
    )
    before = _recovery_bytes(tmp_path)
    source_before = _source_hashes(tmp_path, market)
    with pytest.raises(ArtifactIdentityCollisionError, match="recipe identity collision"):
        _invoke(route, service, market, calculation, **metadata)
    assert _recovery_bytes(tmp_path) == before
    assert _source_hashes(tmp_path, market) == source_before


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("metadata", (
    {"display_name": ""}, {"display_name": " "}, {"display_name": 12},
    {"description": None}, {"description": 12}, {"description": object()},
))
def test_invalid_explicit_metadata_fails_before_writes(tmp_path, route, existing, metadata):
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    calculation = calculate_financial_tool("sma", frame, {"period": 3})
    if existing:
        service.save_recipe_from_result(
            market, calculation, display_name="My SMA", description="Saved description"
        )
    before = _recovery_bytes(tmp_path)
    source_before = _source_hashes(tmp_path, market)
    with pytest.raises(ArtifactValidationError):
        _invoke(route, service, market, calculation, **metadata)
    assert _recovery_bytes(tmp_path) == before
    assert _source_hashes(tmp_path, market) == source_before


@pytest.mark.parametrize("tool,title", TOOLS)
def test_direct_dms_title_matches_research_on_same_source(tmp_path: Path, tool, title):
    market, _frame, service, artifacts, recipes, historical = _domain(tmp_path)
    source_before = _source_hashes(historical, market)
    dataset = service._loader.load(market)
    study = prepare(
        ResearchStudyService(artifacts, recipes), dataset, tool, parameters={"period": 3}
    )
    direct = service.create_direct_artifact(_request(service, market, tool, {"period": 3}))
    assert len(direct.materialization.managed_artifacts) == 1
    member = direct.materialization.managed_artifacts[0]
    loaded = artifacts.load_artifact_by_id(market, member.artifact_id)
    assert loaded.metadata.recipe.display_name == study.display_name == title
    assert loaded.metadata.recipe.output_names == study.result.output_names
    pd.testing.assert_frame_equal(loaded.frame, study.result.to_frame().reset_index(drop=True))
    assert _source_hashes(historical, market) == source_before
