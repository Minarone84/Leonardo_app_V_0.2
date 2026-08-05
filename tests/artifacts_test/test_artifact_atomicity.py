from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import leonardo.artifacts._stores as stores_module
from leonardo.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactIdentityCollisionError,
    ArtifactLineageError,
    ArtifactService,
    ArtifactValidationError,
)
from leonardo.financial_tools import calculate_financial_tool

from test_artifact_service_roundtrip import _accepted_dataset, _frame


@pytest.mark.parametrize(
    "stage,tool",
    (
        ("before_values_write", "sma"),
        ("after_values_write", "sma"),
        ("during_analysis_write", "dynamic_binning"),
        ("during_metadata_write", "sma"),
        ("during_artifact_publication", "sma"),
    ),
)
def test_artifact_failure_leaves_no_final_or_staging_object(
    tmp_path: Path, stage: str, tool: str
) -> None:
    market, data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool(tool, data)
    service = ArtifactService(tmp_path)

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError(stage)

    service._store._failure_hook = fail
    with pytest.raises(RuntimeError, match=stage):
        service.save_calculation(market, result)
    artifacts = service.list_artifacts(market)
    assert artifacts == ()
    assert not tuple(tmp_path.rglob(".staging-*"))


def test_recipe_publication_failure_leaves_no_final_or_temporary_file(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path)
    market, _data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    service._store._failure_hook = lambda stage: (_ for _ in ()).throw(RuntimeError(stage))
    with pytest.raises(RuntimeError, match="during_recipe_publication"):
        service.save_recipe_from_result(market, result)
    assert service.list_recipes(market) == ()
    assert not tuple(tmp_path.rglob(".staging-*"))


def test_duplicate_artifact_never_changes_existing_bytes(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, result)
    before = {path.name: path.read_bytes() for path in saved.path.iterdir()}
    with pytest.raises(ArtifactAlreadyExistsError):
        service.save_calculation(market, result)
    after = {path.name: path.read_bytes() for path in saved.path.iterdir()}
    assert after == before


def test_recipe_identity_collision_is_rejected(tmp_path: Path) -> None:
    market, _data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    saved = service.save_recipe_from_result(market, result, display_name="First")
    with pytest.raises(ArtifactIdentityCollisionError):
        service.save_recipe_from_result(market, result, display_name="Different")
    with pytest.raises(ArtifactIdentityCollisionError):
        service._store.write_recipe(saved.path, b"{}\n")


def _inject_recipe_destination(root: Path, *, identical: bool) -> tuple[Path, bytes]:
    temporary = next(root.rglob(".staging-*.json"))
    submitted = temporary.read_bytes()
    recipe_id = json.loads(submitted.decode("utf-8"))["recipe_id"]
    final = temporary.with_name(f"{recipe_id}.json")
    final.write_bytes(submitted if identical else b"CONFLICT")
    return final, final.read_bytes()


def test_recipe_publication_race_reuses_identical_concurrent_bytes(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path)
    market, _data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    evidence: dict[str, object] = {}

    def inject(stage: str) -> None:
        if stage == "during_recipe_publication":
            final, before = _inject_recipe_destination(tmp_path, identical=True)
            evidence.update(final=final, before=before)

    service._store._failure_hook = inject
    saved = service.save_recipe_from_result(market, result)

    assert saved.created is False
    assert evidence["final"].read_bytes() == evidence["before"]  # type: ignore[union-attr]
    assert not tuple(tmp_path.rglob(".staging-*"))


def test_recipe_publication_race_preserves_different_concurrent_bytes(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path)
    market, _data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    evidence: dict[str, object] = {}

    def inject(stage: str) -> None:
        if stage == "during_recipe_publication":
            final, before = _inject_recipe_destination(tmp_path, identical=False)
            evidence.update(final=final, before=before)

    service._store._failure_hook = inject
    with pytest.raises(ArtifactIdentityCollisionError):
        service.save_recipe_from_result(market, result)

    assert evidence["final"].read_bytes() == evidence["before"] == b"CONFLICT"  # type: ignore[union-attr]
    assert not tuple(tmp_path.rglob(".staging-*"))


@pytest.mark.parametrize("complete", (False, True), ids=("empty", "complete"))
def test_artifact_publication_race_never_replaces_destination(
    tmp_path: Path, complete: bool
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    evidence: dict[str, object] = {}

    def inject(stage: str) -> None:
        if stage != "before_native_artifact_publication":
            return
        staging = next(tmp_path.rglob(".staging-*"))
        metadata = json.loads((staging / "artifact.meta.json").read_text(encoding="utf-8"))
        destination = staging.with_name(metadata["artifact_id"])
        destination.mkdir()
        if complete:
            for source in staging.iterdir():
                (destination / source.name).write_bytes(source.read_bytes())
        evidence["destination"] = destination
        evidence["before"] = {
            path.name: path.read_bytes() for path in destination.iterdir()
        }

    service._store._failure_hook = inject
    with pytest.raises(ArtifactAlreadyExistsError):
        service.save_calculation(market, result)

    destination = evidence["destination"]
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == evidence["before"]  # type: ignore[union-attr]
    assert not tuple(tmp_path.rglob(".staging-*"))


@pytest.mark.parametrize(
    "kwargs",
    (
        {"display_name": 1},
        {"description": 1},
        {"created_at_utc": datetime(2025, 1, 1)},
    ),
)
def test_invalid_recipe_arguments_are_rejected_before_initial_save(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    service = ArtifactService(tmp_path)
    market, _data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})

    with pytest.raises(ArtifactValidationError):
        service.save_recipe_from_result(market, result, **kwargs)  # type: ignore[arg-type]
    assert service.list_recipes(market) == ()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"display_name": 1},
        {"description": 1},
        {"created_at_utc": datetime(2025, 1, 1)},
    ),
)
def test_invalid_recipe_arguments_are_rejected_on_reuse_without_byte_changes(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    service = ArtifactService(tmp_path)
    market, _data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    saved = service.save_recipe_from_result(market, result)
    before = saved.path.read_bytes()

    with pytest.raises(ArtifactValidationError):
        service.save_recipe_from_result(market, result, **kwargs)  # type: ignore[arg-type]
    assert saved.path.read_bytes() == before


def test_prepublication_source_race_removes_staging_and_leaves_recipe(
    tmp_path: Path,
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})

    def mutate_source(stage: str) -> None:
        if stage == "before_native_artifact_publication":
            _accepted_dataset(tmp_path, rows=97)

    service._store._failure_hook = mutate_source
    with pytest.raises(ArtifactLineageError, match="before artifact publication"):
        service.save_calculation(market, result)

    assert service.list_artifacts(market) == ()
    assert len(service.list_recipes(market)) == 1
    assert not tuple(tmp_path.rglob(".staging-*"))


def test_postpublication_source_race_removes_exact_published_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    original_publish = stores_module._publish_directory_no_replace

    def publish_then_mutate(source: Path, destination: Path) -> None:
        original_publish(source, destination)
        _accepted_dataset(tmp_path, rows=97)

    monkeypatch.setattr(stores_module, "_publish_directory_no_replace", publish_then_mutate)
    with pytest.raises(ArtifactLineageError, match="during artifact publication"):
        service.save_calculation(market, result)

    assert service.list_artifacts(market) == ()
    assert len(service.list_recipes(market)) == 1
    assert not tuple(tmp_path.rglob(".staging-*"))


def test_managed_rollback_preserves_reconciled_recipe_and_artifact(
    tmp_path: Path,
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    created = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    sma_result = calculate_financial_tool("sma", data, {"period": 3})
    saved = service.save_calculation(
        market, sma_result, created_at_utc=created
    )
    recipe_path = service._store.recipe_path(
        market,
        saved.metadata.recipe.kind,
        saved.metadata.recipe.tool_key,
        saved.metadata.recipe.recipe_id,
    )
    recipe_before = recipe_path.read_bytes()
    artifact_before = service._store.read_artifact_bytes(saved.path)
    reused = service.prepare_managed_calculation(
        market,
        "a" * 64,
        sma_result,
        expected_source=source,
        created_at_utc=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    )
    created_candidate = service.prepare_managed_calculation(
        market,
        "b" * 64,
        calculate_financial_tool("ema", data, {"period": 3}),
        expected_source=source,
        created_at_utc=datetime(2026, 8, 3, 12, 2, tzinfo=UTC),
    )
    head_calls = 0

    def fail_second_head(stage: str) -> None:
        nonlocal head_calls
        if stage == "during_head_publication":
            head_calls += 1
            if head_calls == 2:
                raise OSError("injected later head failure")

    service._store._failure_hook = fail_second_head
    with pytest.raises(ArtifactLineageError, match="injected later head failure"):
        service.publish_managed_artifact_graph(
            (reused, created_candidate), expected_source=source
        )
    service._store._failure_hook = None

    assert recipe_path.read_bytes() == recipe_before
    assert service._store.read_artifact_bytes(saved.path) == artifact_before
    assert service.load_artifact_by_id(
        market, saved.metadata.artifact_id
    ).metadata == saved.metadata
    assert service.list_managed_artifacts(market) == ()
    assert service.list_artifact_versions(
        market, reused.logical_artifact_id
    ) == ()
    assert service.list_artifact_versions(
        market, created_candidate.logical_artifact_id
    ) == ()
    assert not service._store.artifact_dir(
        market,
        created_candidate.metadata.recipe.kind,
        created_candidate.metadata.recipe.tool_key,
        created_candidate.metadata.artifact_id,
    ).exists()
