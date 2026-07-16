from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import subprocess

import pytest

from leonardo.artifacts import (
    ArtifactIdentityCollisionError,
    ArtifactNotFoundError,
    ArtifactService,
    ArtifactSourceRefV1,
    ArtifactValidationError,
    RecipeInUseError,
)
from leonardo.financial_tools import calculate_financial_tool

from test_artifact_service_roundtrip import _accepted_dataset, _frame


def test_catalog_is_deterministic_and_filterable(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    later = service.save_calculation(
        market,
        calculate_financial_tool("ema", data, {"period": 3}),
        created_at_utc=datetime(2025, 1, 2, tzinfo=UTC),
    )
    earlier = service.save_calculation(
        market,
        calculate_financial_tool("sma", data, {"period": 3}),
        created_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert [item.artifact_id for item in service.list_artifacts(market)] == [
        earlier.metadata.artifact_id,
        later.metadata.artifact_id,
    ]
    assert [item.recipe_id for item in service.list_recipes(market)] == [
        earlier.metadata.recipe.recipe_id,
        later.metadata.recipe.recipe_id,
    ]
    assert service.list_artifacts(market, kind="indicator", tool_key="sma")[0].artifact_id == (
        earlier.metadata.artifact_id
    )
    assert service.list_recipes(market, kind="indicator", tool_key="ema")[0].recipe_id == (
        later.metadata.recipe.recipe_id
    )
    assert service.list_artifacts(market, kind="construct") == ()


def test_invalid_entries_are_reported_as_typed_rejections(tmp_path: Path) -> None:
    market, _ = _accepted_dataset(tmp_path)
    root = tmp_path / "bybit" / "linear" / "BTCUSDT" / "1m"
    bad_recipe_id = "e" * 64
    recipe_path = root / "recipes" / "indicator" / "sma" / f"{bad_recipe_id}.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text("{}\n", encoding="utf-8", newline="\n")
    bad_artifact_id = "f" * 64
    artifact_dir = root / "artifacts" / "indicator" / "sma" / bad_artifact_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "values.csv").write_text("ts_ms,sma_3\n", encoding="utf-8", newline="\n")
    (artifact_dir / "artifact.meta.json").write_text("{}\n", encoding="utf-8", newline="\n")

    recipe = ArtifactService(tmp_path).list_recipes(market)[0]
    artifact = ArtifactService(tmp_path).list_artifacts(market)[0]

    assert recipe.recipe_id == bad_recipe_id
    assert recipe.valid is False
    assert recipe.rejection_reason.startswith("ArtifactValidationError:")
    assert artifact.artifact_id == bad_artifact_id
    assert artifact.valid is False
    assert artifact.rejection_reason.startswith("ArtifactValidationError:")


def test_delete_is_exact_without_cascade_and_recipe_is_protected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "sma_3")
    dependent = service.save_calculation(
        market,
        calculate_financial_tool("ema", data, {"period": 3}),
        source_artifacts=(ref,),
    )

    with pytest.raises(RecipeInUseError):
        service.delete_recipe(
            market,
            dependent.metadata.recipe.kind,
            dependent.metadata.recipe.tool_key,
            dependent.metadata.recipe.recipe_id,
        )

    deleted = service.delete_artifact(
        market, "indicator", "ema", dependent.metadata.artifact_id
    )
    assert deleted.artifact_id == dependent.metadata.artifact_id
    assert source.path.is_dir()
    assert source.metadata.recipe.source_artifacts == ()
    assert dependent.metadata.recipe.source_artifacts == (ref,)
    with pytest.raises(ArtifactNotFoundError):
        service.load_artifact(market, "indicator", "ema", dependent.metadata.artifact_id)

    recipe = service.delete_recipe(
        market,
        dependent.metadata.recipe.kind,
        dependent.metadata.recipe.tool_key,
        dependent.metadata.recipe.recipe_id,
    )
    assert recipe.recipe_id == dependent.metadata.recipe.recipe_id
    assert source.path.is_dir()
    assert source.metadata.recipe.recipe_id in {
        item.recipe_id for item in service.list_recipes(market)
    }


@pytest.mark.parametrize(
    ("kind", "tool_key", "artifact_id"),
    [
        ("../indicator", "sma", "a" * 64),
        ("indicator", "../sma", "a" * 64),
        ("indicator", "sma", "../" + "a" * 64),
    ],
)
def test_artifact_path_traversal_is_rejected(
    tmp_path: Path, kind: str, tool_key: str, artifact_id: str
) -> None:
    market, _ = _accepted_dataset(tmp_path)

    with pytest.raises(ArtifactValidationError):
        ArtifactService(tmp_path).load_artifact(market, kind, tool_key, artifact_id)


def test_catalog_filter_path_traversal_is_rejected(tmp_path: Path) -> None:
    market, _ = _accepted_dataset(tmp_path)

    with pytest.raises(ArtifactValidationError):
        ArtifactService(tmp_path).list_artifacts(market, tool_key="../sma")


def _make_link(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if directory:
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return
        pytest.skip(f"operating system denied symbolic-link creation: {exc}")


def test_linked_artifact_load_and_delete_are_rejected_without_external_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "historical"
    market, data = _accepted_dataset(root)
    service = ArtifactService(root)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    external = tmp_path / "external_artifact"
    external.mkdir()
    for source in saved.path.iterdir():
        (external / source.name).write_bytes(source.read_bytes())
        source.unlink()
    saved.path.rmdir()
    before = {path.name: path.read_bytes() for path in external.iterdir()}
    _make_link(saved.path, external, directory=True)

    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)
    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.list_artifacts(market)
    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.delete_artifact(market, "indicator", "sma", saved.metadata.artifact_id)

    assert {path.name: path.read_bytes() for path in external.iterdir()} == before


def test_linked_artifact_payload_entry_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    market, data = _accepted_dataset(root)
    service = ArtifactService(root)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    external = tmp_path / "external.bin"
    external.write_bytes(b"external")
    _make_link(saved.path / "unexpected.bin", external, directory=False)

    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)
    assert external.read_bytes() == b"external"


def test_linked_recipe_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    market, _data = _accepted_dataset(root)
    service = ArtifactService(root)
    saved = service.save_recipe_from_result(
        market, calculate_financial_tool("sma", _frame(), {"period": 3})
    )
    external = tmp_path / "external_recipe.json"
    before = saved.path.read_bytes()
    external.write_bytes(before)
    saved.path.unlink()
    _make_link(saved.path, external, directory=False)

    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.load_recipe(market, "indicator", "sma", saved.recipe.recipe_id)
    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.list_recipes(market)
    assert external.read_bytes() == before


def test_linked_parent_cannot_redirect_recipe_save(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    root.mkdir()
    service = ArtifactService(root)
    market = _accepted_dataset(tmp_path / "source")[0]
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    target = service._store.recipe_path(
        market,
        result.kind,
        result.tool_key,
        "a" * 64,
    )
    recipes = target.parents[2]
    recipes.parent.mkdir(parents=True)
    external = tmp_path / "external_recipes"
    external.mkdir()
    _make_link(recipes, external, directory=True)

    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.save_recipe_from_result(market, result)
    assert tuple(external.iterdir()) == ()


def test_linked_historical_root_is_rejected(tmp_path: Path) -> None:
    external = tmp_path / "external_root"
    external.mkdir()
    linked_root = tmp_path / "linked_root"
    _make_link(linked_root, external, directory=True)

    with pytest.raises(ArtifactValidationError, match="historical_root"):
        ArtifactService(linked_root)


@pytest.mark.parametrize("invalid", (None, 1, b"id", [], {}))
def test_invalid_public_ids_raise_typed_artifact_validation(
    tmp_path: Path, invalid: object
) -> None:
    market, _ = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)

    with pytest.raises(ArtifactValidationError):
        service.load_artifact(market, "indicator", "sma", invalid)  # type: ignore[arg-type]
    with pytest.raises(ArtifactValidationError):
        service.load_recipe(market, "indicator", "sma", invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", (1, b"value", [], {}))
def test_invalid_public_kind_and_tool_filters_raise_typed_validation(
    tmp_path: Path, invalid: object
) -> None:
    market, _ = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)

    with pytest.raises(ArtifactValidationError):
        service.list_artifacts(market, kind=invalid)  # type: ignore[arg-type]
    with pytest.raises(ArtifactValidationError):
        service.list_recipes(market, tool_key=invalid)  # type: ignore[arg-type]
    with pytest.raises(ArtifactValidationError):
        service.load_artifact(market, invalid, "sma", "a" * 64)  # type: ignore[arg-type]
    with pytest.raises(ArtifactValidationError):
        service.load_recipe(market, "indicator", invalid, "a" * 64)  # type: ignore[arg-type]


def test_recipe_directory_collision_raises_typed_identity_error(tmp_path: Path) -> None:
    market, _ = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    saved = service.save_recipe_from_result(market, result)
    saved.path.unlink()
    saved.path.mkdir()

    with pytest.raises(ArtifactIdentityCollisionError):
        service.save_recipe_from_result(market, result)
    assert saved.path.is_dir()
