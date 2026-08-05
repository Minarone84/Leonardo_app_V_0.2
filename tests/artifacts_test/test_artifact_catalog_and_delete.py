from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess
from threading import Event, Thread

import pytest

from leonardo.artifacts import (
    ArtifactIdentityCollisionError,
    ArtifactLineageError,
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


def test_source_artifact_cannot_be_deleted_while_dependent_persists(
    tmp_path: Path,
) -> None:
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

    with pytest.raises(
        ArtifactLineageError,
        match="artifact is referenced by dependent artifact",
    ):
        service.delete_artifact(
            market, "indicator", "sma", source.metadata.artifact_id
        )
    assert source.path.is_dir()
    assert dependent.path.is_dir()
    assert len(service.list_recipes(market)) == 2

    service.delete_artifact(
        market, "indicator", "ema", dependent.metadata.artifact_id
    )
    deleted = service.delete_artifact(
        market, "indicator", "sma", source.metadata.artifact_id
    )
    assert deleted.artifact_id == source.metadata.artifact_id


def test_source_deletion_wins_before_dependent_publication_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "sma_3")
    validated = Event()
    release = Event()
    errors: list[BaseException] = []
    original_validate = service._validate_source_refs

    def block_after_initial_validation(*args, **kwargs):
        original_validate(*args, **kwargs)
        validated.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(
        service, "_validate_source_refs", block_after_initial_validation
    )

    def publish() -> None:
        try:
            service.save_calculation(
                market,
                calculate_financial_tool("ema", data, {"period": 3}),
                source_artifacts=(ref,),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=publish)
    thread.start()
    assert validated.wait(timeout=5)
    service.delete_artifact(
        market, "indicator", "sma", source.metadata.artifact_id
    )
    release.set()
    thread.join(timeout=5)

    assert len(errors) == 1
    assert isinstance(errors[0], ArtifactLineageError)
    assert service.list_artifacts(market) == ()
    assert tuple(
        item.recipe_id for item in service.list_recipes(market)
    ) == (source.metadata.recipe.recipe_id,)


def test_recursive_source_removal_after_initial_validation_blocks_legacy_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    first = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    first_ref = ArtifactSourceRefV1(
        "first", first.metadata.artifact_id, "sma_3"
    )
    second = service.save_calculation(
        market,
        calculate_financial_tool("ema", data, {"period": 3}),
        source_artifacts=(first_ref,),
    )
    second_ref = ArtifactSourceRefV1(
        "second", second.metadata.artifact_id, "ema_3"
    )
    recipe_ids_before = {item.recipe_id for item in service.list_recipes(market)}
    original_validate = service._validate_source_refs

    def remove_first_after_initial_validation(*args, **kwargs):
        original_validate(*args, **kwargs)
        shutil.rmtree(first.path)

    monkeypatch.setattr(
        service,
        "_validate_source_refs",
        remove_first_after_initial_validation,
    )

    with pytest.raises(ArtifactLineageError, match="source artifact not found"):
        service.save_calculation(
            market,
            calculate_financial_tool("rsi", data, {"period": 3}),
            source_artifacts=(second_ref,),
        )

    assert {item.recipe_id for item in service.list_recipes(market)} == recipe_ids_before
    assert {
        item.artifact_id for item in service.list_artifacts(market) if item.valid
    } == {second.metadata.artifact_id}


def test_dependent_publication_wins_before_source_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "sma_3")
    publication_entered = Event()
    publication_release = Event()
    deletion_attempted = Event()
    deletion_finished = Event()
    published = []
    publication_errors: list[BaseException] = []
    deletion_errors: list[BaseException] = []
    original_validate = service._validate_exact_source_refs_locked

    def block_after_final_validation(*args, **kwargs):
        original_validate(*args, **kwargs)
        publication_entered.set()
        assert publication_release.wait(timeout=5)

    monkeypatch.setattr(
        service,
        "_validate_exact_source_refs_locked",
        block_after_final_validation,
    )

    def publish() -> None:
        try:
            published.append(
                service.save_calculation(
                    market,
                    calculate_financial_tool("ema", data, {"period": 3}),
                    source_artifacts=(ref,),
                )
            )
        except BaseException as exc:
            publication_errors.append(exc)

    def delete() -> None:
        deletion_attempted.set()
        try:
            service.delete_artifact(
                market, "indicator", "sma", source.metadata.artifact_id
            )
        except BaseException as exc:
            deletion_errors.append(exc)
        finally:
            deletion_finished.set()

    publication_thread = Thread(target=publish)
    publication_thread.start()
    assert publication_entered.wait(timeout=5)
    deletion_thread = Thread(target=delete)
    deletion_thread.start()
    assert deletion_attempted.wait(timeout=5)
    assert not deletion_finished.is_set()
    publication_release.set()
    publication_thread.join(timeout=5)
    deletion_thread.join(timeout=5)

    assert not publication_errors
    assert len(published) == 1
    assert len(deletion_errors) == 1
    assert isinstance(deletion_errors[0], ArtifactLineageError)
    assert "artifact is referenced by dependent artifact" in str(
        deletion_errors[0]
    )


def test_recipe_delete_waits_for_atomic_artifact_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    publication_entered = Event()
    publication_release = Event()
    delete_started = Event()
    delete_finished = Event()
    saved = []
    save_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []
    original_write = service._store.write_artifact

    def blocked_write(*args, **kwargs):
        publication_entered.set()
        assert publication_release.wait(timeout=5)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(service._store, "write_artifact", blocked_write)

    def save() -> None:
        try:
            saved.append(service.save_calculation(market, result))
        except BaseException as exc:
            save_errors.append(exc)

    save_thread = Thread(target=save)
    save_thread.start()
    assert publication_entered.wait(timeout=5)
    recipe = service.list_recipes(market)[0]

    def delete() -> None:
        delete_started.set()
        try:
            service.delete_recipe(
                market, recipe.kind, recipe.tool_key, recipe.recipe_id
            )
        except BaseException as exc:
            delete_errors.append(exc)
        finally:
            delete_finished.set()

    delete_thread = Thread(target=delete)
    delete_thread.start()
    assert delete_started.wait(timeout=5)
    assert not delete_finished.wait(timeout=0.1)
    publication_release.set()
    save_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert not save_errors
    assert len(saved) == 1
    assert len(delete_errors) == 1
    assert isinstance(delete_errors[0], RecipeInUseError)
    assert service.load_recipe(
        market, recipe.kind, recipe.tool_key, recipe.recipe_id
    ) == saved[0].metadata.recipe
    assert service.load_artifact_by_id(
        market, saved[0].metadata.artifact_id
    ).metadata == saved[0].metadata


def test_artifact_publication_recreates_recipe_deleted_first(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    recipe = service.save_recipe_from_result(market, result).recipe

    service.delete_recipe(market, recipe.kind, recipe.tool_key, recipe.recipe_id)
    saved = service.save_calculation(market, result)

    assert service.load_recipe(
        market, recipe.kind, recipe.tool_key, recipe.recipe_id
    ) == saved.metadata.recipe
    assert service.load_artifact_by_id(
        market, saved.metadata.artifact_id
    ).metadata == saved.metadata


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
