"""Pure dependency planning for globally portable Recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .models import PortableRecipeV1


class PortableRecipeGraphError(ValueError):
    """Raised when a portable Recipe graph cannot be planned."""


@dataclass(frozen=True, slots=True)
class PortableRecipeGraphEdge:
    dependency_recipe_id: str
    dependent_recipe_id: str
    role: str
    output_name: str


@dataclass(frozen=True, slots=True)
class PortableRecipeGraphPlan:
    root_recipe_ids: tuple[str, ...]
    member_recipe_ids: tuple[str, ...]
    dependency_edges: tuple[PortableRecipeGraphEdge, ...]
    execution_stages: tuple[tuple[str, ...], ...]


class PortableRecipeGraphPlanner:
    """Resolve and validate a portable Recipe dependency closure without writes."""

    def __init__(self, loader: Callable[[str], PortableRecipeV1] | object) -> None:
        if callable(loader):
            self._loader = loader
        else:
            method = getattr(loader, "load_recipe", None)
            if not callable(method):
                raise TypeError("loader must be callable or expose load_recipe()")
            self._loader = method

    def plan(
        self,
        root_recipe_ids: Sequence[str],
        *,
        recipes: Mapping[str, PortableRecipeV1] | None = None,
    ) -> PortableRecipeGraphPlan:
        roots = tuple(root_recipe_ids)
        if not roots:
            raise PortableRecipeGraphError("at least one root Recipe is required")
        if any(not isinstance(item, str) or not item for item in roots):
            raise PortableRecipeGraphError("root Recipe IDs must be non-empty strings")
        if len(set(roots)) != len(roots):
            raise PortableRecipeGraphError("root Recipe IDs must be unique")

        supplied_recipes = recipes
        loaded_recipes: dict[str, PortableRecipeV1] = {}
        edges: list[PortableRecipeGraphEdge] = []
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(recipe_id: str) -> None:
            marker = state.get(recipe_id, 0)
            if marker == 2:
                return
            if marker == 1:
                start = stack.index(recipe_id)
                cycle = (*stack[start:], recipe_id)
                raise PortableRecipeGraphError(
                    f"portable Recipe dependency cycle: {' -> '.join(cycle)}"
                )
            state[recipe_id] = 1
            stack.append(recipe_id)
            try:
                recipe = (
                    None
                    if supplied_recipes is None
                    else supplied_recipes.get(recipe_id)
                )
                if recipe is None:
                    try:
                        recipe = self._loader(recipe_id)
                    except (FileNotFoundError, KeyError) as exc:
                        raise PortableRecipeGraphError(
                            f"missing portable Recipe dependency: {recipe_id}"
                        ) from exc
                if not isinstance(recipe, PortableRecipeV1):
                    raise PortableRecipeGraphError(
                        f"loader returned an invalid portable Recipe: {recipe_id}"
                    )
                if recipe.recipe_id != recipe_id:
                    raise PortableRecipeGraphError(
                        f"loaded Recipe identity does not match request: {recipe_id}"
                    )
                loaded_recipes[recipe_id] = recipe
                for dependency in recipe.dependencies:
                    visit(dependency.recipe_id)
                    upstream = loaded_recipes[dependency.recipe_id]
                    if dependency.output_name not in upstream.output_names:
                        raise PortableRecipeGraphError(
                            "dependency output is absent from upstream Recipe: "
                            f"{dependency.recipe_id}.{dependency.output_name}"
                        )
                    edges.append(
                        PortableRecipeGraphEdge(
                            dependency_recipe_id=dependency.recipe_id,
                            dependent_recipe_id=recipe_id,
                            role=dependency.role,
                            output_name=dependency.output_name,
                        )
                    )
            finally:
                if stack and stack[-1] == recipe_id:
                    stack.pop()
            state[recipe_id] = 2

        for root in roots:
            visit(root)

        unique_edges = tuple(
            sorted(
                set(edges),
                key=lambda item: (
                    item.dependency_recipe_id,
                    item.dependent_recipe_id,
                    item.role,
                    item.output_name,
                ),
            )
        )
        dependencies_by_member: dict[str, set[str]] = {
            recipe_id: set() for recipe_id in loaded_recipes
        }
        for edge in unique_edges:
            dependencies_by_member[edge.dependent_recipe_id].add(
                edge.dependency_recipe_id
            )

        remaining = set(loaded_recipes)
        stages: list[tuple[str, ...]] = []
        completed: set[str] = set()
        while remaining:
            stage = tuple(
                sorted(
                    recipe_id
                    for recipe_id in remaining
                    if dependencies_by_member[recipe_id].issubset(completed)
                )
            )
            if not stage:
                raise PortableRecipeGraphError("portable Recipe graph contains a cycle")
            stages.append(stage)
            remaining.difference_update(stage)
            completed.update(stage)

        members = tuple(recipe_id for stage in stages for recipe_id in stage)
        return PortableRecipeGraphPlan(
            root_recipe_ids=roots,
            member_recipe_ids=members,
            dependency_edges=unique_edges,
            execution_stages=tuple(stages),
        )


__all__ = (
    "PortableRecipeGraphEdge",
    "PortableRecipeGraphError",
    "PortableRecipeGraphPlan",
    "PortableRecipeGraphPlanner",
)
