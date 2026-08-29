from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import leonardo.recipes.store as store_module
from leonardo.data import MarketId
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeGraphError,
    PortableRecipeGraphPlanner,
    PortableRecipeIdentityCollisionError,
    PortableRecipeProvenanceV1,
    PortableRecipeStore,
    PortableRecipeStoreError,
    PortableRecipeV1,
    build_portable_recipe,
)


def _recipes():
    fast = build_portable_recipe(
        tool_key="sma", kind="indicator", parameters={"period": 10},
        output_names=("sma_10",),
    )
    slow = build_portable_recipe(
        tool_key="sma", kind="indicator", parameters={"period": 20},
        output_names=("sma_20",),
    )
    delta = build_portable_recipe(
        tool_key="delta", kind="construct", parameters={"eps": 1e-12, "mode": "abs"},
        output_names=("fast_slow_delta",),
        dependencies=(
            PortableRecipeDependencyV1("fast", fast.recipe_id, "sma_10"),
            PortableRecipeDependencyV1("slow", slow.recipe_id, "sma_20"),
        ),
    )
    return fast, slow, delta


def _make_link(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if directory and os.name == "nt":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return
        pytest.skip(f"operating system denied symbolic-link creation: {exc}")


def test_graph_planner_resolves_transitive_deterministic_closure() -> None:
    fast, slow, delta = _recipes()
    values = {item.recipe_id: item for item in (fast, slow, delta)}
    plan = PortableRecipeGraphPlanner(values.__getitem__).plan((delta.recipe_id,))
    assert plan.root_recipe_ids == (delta.recipe_id,)
    assert plan.execution_stages[0] == tuple(sorted((fast.recipe_id, slow.recipe_id)))
    assert plan.execution_stages[1] == (delta.recipe_id,)
    assert plan.member_recipe_ids == tuple(item for stage in plan.execution_stages for item in stage)
    assert len(plan.dependency_edges) == 2


def test_graph_planner_rejects_missing_output_missing_recipe_and_explicit_cycle() -> None:
    fast, _slow, delta = _recipes()
    with pytest.raises(PortableRecipeGraphError, match="missing"):
        PortableRecipeGraphPlanner({delta.recipe_id: delta}.__getitem__).plan((delta.recipe_id,))

    broken = build_portable_recipe(
        tool_key="derivative", kind="construct", parameters={"period": 1},
        output_names=("value_derivative",),
        dependencies=(PortableRecipeDependencyV1("source", fast.recipe_id, "missing"),),
    )
    with pytest.raises(PortableRecipeGraphError, match="absent"):
        PortableRecipeGraphPlanner(
            {fast.recipe_id: fast, broken.recipe_id: broken}.__getitem__
        ).plan((broken.recipe_id,))

    left = build_portable_recipe(
        tool_key="sma", kind="indicator", parameters={"period": 2}, output_names=("left",)
    )
    right = build_portable_recipe(
        tool_key="ema", kind="indicator", parameters={"period": 2}, output_names=("right",)
    )
    object.__setattr__(left, "dependencies", (
        PortableRecipeDependencyV1("source", right.recipe_id, "right"),
    ))
    object.__setattr__(right, "dependencies", (
        PortableRecipeDependencyV1("source", left.recipe_id, "left"),
    ))
    with pytest.raises(PortableRecipeGraphError, match=f"{left.recipe_id}.*{right.recipe_id}.*{left.recipe_id}"):
        PortableRecipeGraphPlanner(
            {left.recipe_id: left, right.recipe_id: right}.__getitem__
        ).plan((left.recipe_id,))


def test_store_is_lazy_canonical_and_reuses_identical_objects(tmp_path: Path) -> None:
    root = tmp_path / "data_manager"
    store = PortableRecipeStore(root)
    recipe = _recipes()[0]
    assert store.list_recipe_summaries() == ()
    assert not root.exists()
    assert store.save_recipe(recipe) == recipe
    assert set(item.name for item in root.iterdir()) == {"recipes"}
    path = root / "recipes" / f"{recipe.recipe_id}.json"
    before = path.read_bytes()
    store.save_recipe(recipe)
    assert path.read_bytes() == before
    assert store.load_recipe(recipe.recipe_id) == recipe
    path.write_bytes(before.rstrip())
    with pytest.raises(PortableRecipeStoreError, match="not canonical"):
        store.load_recipe(recipe.recipe_id)
    with pytest.raises(PortableRecipeIdentityCollisionError):
        store.save_recipe(recipe)


def test_store_provenance_and_collection_revisions_are_durable(tmp_path: Path) -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    ticks = iter((now, now, now + timedelta(minutes=1), now + timedelta(minutes=1)))
    store = PortableRecipeStore(
        tmp_path / "data_manager",
        clock=lambda: next(ticks),
        collection_id_factory=lambda: "a" * 32,
    )
    fast, slow, delta = _recipes()
    for recipe in (fast, slow, delta):
        store.save_recipe(recipe)
    provenance = PortableRecipeProvenanceV1.build(
        recipe_id=fast.recipe_id,
        origin_market_id=MarketId("bybit", "linear", "BTCUSDT", "1h"),
        study_environment_id="env_one",
        study_environment_content_hash="b" * 64,
        study_environment_updated_at_utc=now,
        study_environment_display_name="Environment",
        study_entry_id="entry_fast",
        study_display_name="Fast",
        study_description="",
    )
    store.save_provenance(provenance)
    store.save_provenance(provenance)
    assert store.list_provenance(fast.recipe_id) == (provenance,)

    plan = PortableRecipeGraphPlanner(store).plan((delta.recipe_id,))
    first = store.create_collection("Pair", "", (delta.recipe_id,), plan.member_recipe_ids)
    second = store.update_collection(
        first.collection_id, "Pair Updated", "", (fast.recipe_id,), (fast.recipe_id,)
    )
    assert second.previous_revision_id == first.revision_id
    assert store.load_collection(first.collection_id) == second
    assert store.load_collection_revision(first.collection_id, first.revision_id) == first
    assert len(store.list_collection_revisions(first.collection_id)) == 2


def test_collection_update_expected_head_is_atomic_and_rejects_stale_edits(
    tmp_path: Path,
) -> None:
    store = PortableRecipeStore(
        tmp_path / "data_manager", collection_id_factory=lambda: "b" * 32
    )
    recipe = _recipes()[0]
    store.save_recipe(recipe)
    first = store.create_collection(
        "First", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    second = store.update_collection(
        first.collection_id,
        "Second",
        "",
        (recipe.recipe_id,),
        (recipe.recipe_id,),
        expected_head_revision_id=first.revision_id,
    )
    revision_paths = {
        item.revision_id: (
            store.root_dir
            / "recipe_collections"
            / first.collection_id
            / "revisions"
            / f"{item.revision_id}.json"
        ).read_bytes()
        for item in (first, second)
    }

    with pytest.raises(
        PortableRecipeStoreError, match="changed since it was selected"
    ):
        store.update_collection(
            first.collection_id,
            "Stale",
            "",
            (recipe.recipe_id,),
            (recipe.recipe_id,),
            expected_head_revision_id=first.revision_id,
        )

    assert store.load_collection(first.collection_id) == second
    assert store.list_collection_revisions(first.collection_id) == (first, second)
    for revision_id, expected in revision_paths.items():
        path = (
            store.root_dir
            / "recipe_collections"
            / first.collection_id
            / "revisions"
            / f"{revision_id}.json"
        )
        assert path.read_bytes() == expected


def test_recipe_deletion_removes_exact_recipe_and_provenance_after_preflight(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    store = PortableRecipeStore(tmp_path / "data_manager")
    fast, slow, _delta = _recipes()
    store.save_recipe(fast)
    store.save_recipe(slow)
    provenance = PortableRecipeProvenanceV1.build(
        recipe_id=fast.recipe_id,
        origin_market_id=MarketId("bybit", "linear", "BTCUSDT", "1h"),
        study_environment_id="env_delete",
        study_environment_content_hash="b" * 64,
        study_environment_updated_at_utc=now,
        study_environment_display_name="Delete",
        study_entry_id="entry_fast",
        study_display_name="Fast",
        study_description="",
    )
    store.save_provenance(provenance)
    callback_evidence: list[bool] = []

    deleted = store.delete_recipe(
        fast.recipe_id,
        before_delete=lambda: callback_evidence.append(
            store.load_recipe(fast.recipe_id) == fast
            and store.list_provenance(fast.recipe_id) == (provenance,)
        ),
    )

    assert deleted == fast
    assert callback_evidence == [True]
    assert store.load_recipe(slow.recipe_id) == slow
    with pytest.raises(FileNotFoundError):
        store.load_recipe(fast.recipe_id)
    assert not (store.root_dir / "recipe_provenance" / fast.recipe_id).exists()


def test_recipe_deletion_refuses_recipe_and_historical_collection_references(
    tmp_path: Path,
) -> None:
    store = PortableRecipeStore(
        tmp_path / "data_manager", collection_id_factory=lambda: "d" * 32
    )
    fast, slow, delta = _recipes()
    historical = build_portable_recipe(
        tool_key="ema", kind="indicator", parameters={"period": 3},
        output_names=("ema_3",),
    )
    for recipe in (fast, slow, delta, historical):
        store.save_recipe(recipe)
    with pytest.raises(PortableRecipeStoreError, match="another Recipe"):
        store.delete_recipe(fast.recipe_id)

    first = store.create_collection(
        "Historical", "", (historical.recipe_id,), (historical.recipe_id,)
    )
    store.update_collection(
        first.collection_id, "Current", "", (delta.recipe_id,),
        PortableRecipeGraphPlanner(store).plan((delta.recipe_id,)).member_recipe_ids,
    )
    with pytest.raises(PortableRecipeStoreError, match="Recipe Collection"):
        store.delete_recipe(historical.recipe_id)
    assert store.load_recipe(historical.recipe_id) == historical


def test_collection_deletion_is_exact_and_invalid_shapes_fail_before_callback(
    tmp_path: Path,
) -> None:
    store = PortableRecipeStore(
        tmp_path / "data_manager", collection_id_factory=lambda: "e" * 32
    )
    recipe = _recipes()[0]
    store.save_recipe(recipe)
    first = store.create_collection(
        "One", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    current = store.update_collection(
        first.collection_id, "Two", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    callback_values: list[str] = []
    assert store.delete_collection(
        first.collection_id,
        before_delete=lambda: callback_values.append(
            store.load_collection(first.collection_id).revision_id
        ),
    ) == current
    assert callback_values == [current.revision_id]
    assert store.load_recipe(recipe.recipe_id) == recipe
    assert not (store.root_dir / "recipe_collections" / first.collection_id).exists()

    second_store = PortableRecipeStore(
        tmp_path / "unsafe", collection_id_factory=lambda: "f" * 32
    )
    second_store.save_recipe(recipe)
    second = second_store.create_collection(
        "Unsafe", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    collection_dir = second_store.root_dir / "recipe_collections" / second.collection_id
    (collection_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    called: list[bool] = []
    with pytest.raises(PortableRecipeStoreError, match="unexpected"):
        second_store.delete_collection(
            second.collection_id, before_delete=lambda: called.append(True)
        )
    assert called == []
    assert second_store.load_collection(second.collection_id) == second


def test_failed_collection_head_publication_preserves_previous_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PortableRecipeStore(
        tmp_path / "data_manager", collection_id_factory=lambda: "c" * 32
    )
    recipe = _recipes()[0]
    store.save_recipe(recipe)
    first = store.create_collection("One", "", (recipe.recipe_id,), (recipe.recipe_id,))
    original = store.load_collection(first.collection_id)
    monkeypatch.setattr(store, "_write_mutable", lambda *_args: (_ for _ in ()).throw(OSError("head")))
    with pytest.raises(OSError, match="head"):
        store.update_collection(
            first.collection_id, "Two", "", (recipe.recipe_id,), (recipe.recipe_id,)
        )
    assert store.load_collection(first.collection_id) == original


def test_store_rejects_traversal_and_simulated_link_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PortableRecipeStore(tmp_path / "data_manager")
    with pytest.raises(PortableRecipeStoreError):
        store.load_recipe("../escape")
    root = store.root_dir
    root.mkdir()
    monkeypatch.setattr(store_module, "_is_link", lambda path: path == root)
    with pytest.raises(PortableRecipeStoreError, match="link"):
        store.list_recipe_summaries()


def test_invalid_recipe_json_produces_invalid_summary(tmp_path: Path) -> None:
    root = tmp_path / "data_manager"
    recipes = root / "recipes"
    recipes.mkdir(parents=True)
    (recipes / f"{'a' * 64}.json").write_text("{", encoding="utf-8")

    summaries = PortableRecipeStore(root).list_recipe_summaries()

    assert len(summaries) == 1
    assert not summaries[0].valid
    assert "PortableRecipeStoreError" in summaries[0].rejection_reason


def test_unexpected_recipe_model_runtime_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PortableRecipeStore(tmp_path / "data_manager")
    store.save_recipe(_recipes()[0])

    def fail_from_dict(_cls, _payload):
        raise RuntimeError("injected model defect")

    monkeypatch.setattr(PortableRecipeV1, "from_dict", classmethod(fail_from_dict))
    with pytest.raises(RuntimeError, match="injected model defect"):
        store.list_recipe_summaries()


def test_collection_without_valid_revisions_is_an_invalid_store_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PortableRecipeStore(
        tmp_path / "data_manager", collection_id_factory=lambda: "e" * 32
    )
    recipe = _recipes()[0]
    store.save_recipe(recipe)
    revision = store.create_collection(
        "Collection", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    monkeypatch.setattr(store, "list_collection_revisions", lambda _identity: ())

    summaries = store.list_collection_summaries()

    assert len(summaries) == 1
    assert summaries[0].collection_id == revision.collection_id
    assert not summaries[0].valid
    assert "no valid revisions" in summaries[0].rejection_reason
    assert "IndexError" not in summaries[0].rejection_reason


def test_linked_recipe_file_is_rejected_without_external_mutation(
    tmp_path: Path,
) -> None:
    recipe = _recipes()[0]
    root = tmp_path / "data_manager"
    recipes = root / "recipes"
    recipes.mkdir(parents=True)
    external = tmp_path / "external_recipe.json"
    before = recipe.canonical_json_bytes()
    external.write_bytes(before)
    _make_link(recipes / f"{recipe.recipe_id}.json", external, directory=False)

    with pytest.raises(PortableRecipeStoreError, match="link"):
        PortableRecipeStore(root).load_recipe(recipe.recipe_id)
    assert external.read_bytes() == before


def test_recipe_file_link_is_rejected_before_containment_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PortableRecipeStore(tmp_path / "data_manager")
    recipe = _recipes()[0]
    recipe_path = store.root_dir / "recipes" / f"{recipe.recipe_id}.json"
    containment_reached = False

    monkeypatch.setattr(
        store_module,
        "_is_link",
        lambda path: path == recipe_path,
    )

    def fail_containment(_path: Path) -> None:
        nonlocal containment_reached
        containment_reached = True
        raise AssertionError("containment resolution must not run for a direct link")

    monkeypatch.setattr(store, "_require_contained", fail_containment)

    with pytest.raises(PortableRecipeStoreError, match="link"):
        store.load_recipe(recipe.recipe_id)
    assert not containment_reached


def test_linked_recipes_directory_is_rejected_without_external_mutation(
    tmp_path: Path,
) -> None:
    recipe = _recipes()[0]
    root = tmp_path / "data_manager"
    root.mkdir()
    external = tmp_path / "external_recipes"
    external.mkdir()
    external_file = external / f"{recipe.recipe_id}.json"
    before = recipe.canonical_json_bytes()
    external_file.write_bytes(before)
    _make_link(root / "recipes", external, directory=True)

    with pytest.raises(PortableRecipeStoreError):
        PortableRecipeStore(root).list_recipe_summaries()
    assert external_file.read_bytes() == before


def test_linked_portable_recipe_root_is_rejected_without_external_mutation(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external_root"
    external.mkdir()
    marker = external / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    root = tmp_path / "data_manager"
    _make_link(root, external, directory=True)

    with pytest.raises(PortableRecipeStoreError, match="link"):
        PortableRecipeStore(root).list_recipe_summaries()
    assert marker.read_text(encoding="utf-8") == "unchanged"
