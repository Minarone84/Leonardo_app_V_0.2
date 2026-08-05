"""Pure planning and calculation helpers for managed Artifact materialization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from leonardo.artifacts import ArtifactSourceRefV1
from leonardo.data import MarketId
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    calculate_financial_tool,
    get_financial_tool_spec,
    resolve_output_signals,
    resolve_parameters,
)
from leonardo.recipes import PortableRecipeGraphEdge, PortableRecipeV1


class _HistoricalDataset(Protocol):
    ts_ms: object
    open: object
    high: object
    low: object
    close: object
    volume: object


class ArtifactMaterializationValidationError(ValueError):
    """Portable Recipe semantics cannot be materialized exactly."""


@dataclass(frozen=True, slots=True)
class _ResolvedExecutionConfiguration:
    parameters: Mapping[str, object]
    bindings: Mapping[str, object]
    selectors_by_role: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _CalculatedMaterializationNode:
    result: FinancialToolCalculationResult


def _dataset_frame(dataset: _HistoricalDataset) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ts_ms": dataset.ts_ms,
            "open": dataset.open,
            "high": dataset.high,
            "low": dataset.low,
            "close": dataset.close,
            "volume": dataset.volume,
        }
    )
    if frame["ts_ms"].duplicated().any():
        raise ArtifactMaterializationValidationError(
            "target OHLCV timestamps must be unique"
        )
    return frame


def _validate_recipe_execution(
    recipe: PortableRecipeV1,
    recipes_by_id: Mapping[str, PortableRecipeV1],
) -> None:
    if recipe.tool_key == "dynamic_binning":
        raise ArtifactMaterializationValidationError(
            "dynamic_binning cannot be materialized"
        )
    dependencies = tuple(recipe.dependencies)
    ohlcv_inputs = tuple(recipe.ohlcv_inputs)
    roles = {item.role for item in dependencies} | {item.role for item in ohlcv_inputs}
    if len(roles) != len(dependencies) + len(ohlcv_inputs):
        raise ArtifactMaterializationValidationError("source roles must be unique")
    for dependency in dependencies:
        upstream = recipes_by_id.get(dependency.recipe_id)
        if upstream is None:
            raise ArtifactMaterializationValidationError(
                f"missing portable Recipe dependency: {dependency.recipe_id}"
            )

    key = recipe.tool_key
    spec = get_financial_tool_spec(key)
    if spec.construct_io is None and key != "universal_trend_classifier":
        expected_inputs = {
            (data_input.name, data_input.name)
            for data_input in spec.data_inputs
            if data_input.required
        }
        actual_inputs = {
            (item.role, item.column_name) for item in ohlcv_inputs
        }
        if dependencies or (ohlcv_inputs and actual_inputs != expected_inputs):
            raise ArtifactMaterializationValidationError(
                "ordinary Financial Tool OHLCV inputs must be empty or exact "
                "canonical input bindings"
            )
    if key == "universal_trend_classifier":
        expected_roles = {
            "trend_peak", "trend_trough", "range_peak", "range_trough"
        }
        owner_ids = {item.recipe_id for item in dependencies}
        if (
            ohlcv_inputs
            or len(dependencies) != 4
            or roles != expected_roles
            or len(owner_ids) != 1
        ):
            raise ArtifactMaterializationValidationError(
                "UTC requires one complete Peaks & Troughs dependency set"
            )
        owner = recipes_by_id[next(iter(owner_ids))]
        if owner.tool_key != "peaks_troughs":
            raise ArtifactMaterializationValidationError(
                "UTC requires one complete Peaks & Troughs dependency set"
            )
        try:
            _validate_utc_outputs(recipe)
        except ArtifactMaterializationValidationError as exc:
            raise ArtifactMaterializationValidationError(
                "UTC requires one complete Peaks & Troughs dependency set"
            ) from exc

    for dependency in dependencies:
        upstream = recipes_by_id[dependency.recipe_id]
        if dependency.output_name not in upstream.output_names:
            raise ArtifactMaterializationValidationError(
                f"missing dependency output: {dependency.output_name}"
            )
        parameters, bindings = _target_configuration(upstream)
        naming_parameters = dict(parameters)
        naming_parameters.update(bindings)
        signals = {
            signal.name: signal
            for signal in resolve_output_signals(
                upstream.tool_key, naming_parameters
            )
        }
        signal = signals.get(dependency.output_name)
        if (
            signal is None
            or not signal.analysis_usable
            or signal.value_type != "numeric"
        ):
            raise ArtifactMaterializationValidationError(
                "dependency output is not a numeric analysis source"
            )

    if key in {"derivative", "angle"}:
        _require_roles(roles, ("source",), key)
    elif key == "delta":
        _require_roles(roles, ("fast", "slow"), key)
    elif key in {"braids", "braid_instability"}:
        _require_roles(roles, ("fast", "mid", "slow"), key)
        _require_source_compatibility(recipe, recipes_by_id)
    elif key == "trap_area":
        if roles not in ({"fast", "slow"}, {"fast", "mid", "slow"}):
            raise ArtifactMaterializationValidationError(
                "trap_area requires fast/slow or fast/mid/slow"
            )
    elif key in {"percent_span_angle", "angle_momentum"}:
        expected = tuple(f"source_{index}" for index in range(1, len(roles) + 1))
        _require_roles(roles, expected, key)
    elif key == "universal_trend_classifier":
        pass
    elif dependencies:
        raise ArtifactMaterializationValidationError(
            "ordinary Financial Tools cannot depend on portable Recipes"
        )
    elif recipe.kind == "construct" and roles:
        raise ArtifactMaterializationValidationError(
            f"unsupported source-role schema for {key}"
        )

    if recipe.kind == "construct" and key not in {
        "derivative",
        "angle",
        "delta",
        "braids",
        "braid_instability",
        "trap_area",
        "percent_span_angle",
        "angle_momentum",
    }:
        raise ArtifactMaterializationValidationError(
            f"unsupported construct for managed materialization: {key}"
        )
    if key not in {"braids", "braid_instability"}:
        _require_source_compatibility(recipe, recipes_by_id)


def _require_roles(
    actual: set[str], expected: Sequence[str], tool_key: str
) -> None:
    expected_set = set(expected)
    if actual != expected_set:
        raise ArtifactMaterializationValidationError(
            f"{tool_key} source roles must be exactly {tuple(expected)}"
        )


def _source_family(
    role: str,
    recipe: PortableRecipeV1,
    recipes_by_id: Mapping[str, PortableRecipeV1],
) -> str:
    dependency = next((item for item in recipe.dependencies if item.role == role), None)
    if dependency is None:
        return "ohlc"
    return recipes_by_id[dependency.recipe_id].kind


def _require_source_compatibility(
    recipe: PortableRecipeV1,
    recipes_by_id: Mapping[str, PortableRecipeV1],
) -> None:
    spec = get_financial_tool_spec(recipe.tool_key)
    construct = spec.construct_io
    if construct is None:
        return
    roles = tuple(
        sorted(
            {item.role for item in recipe.dependencies}
            | {item.role for item in recipe.ohlcv_inputs}
        )
    )
    families = tuple(_source_family(role, recipe, recipes_by_id) for role in roles)
    if any(family not in construct.allowed_source_families for family in families):
        raise ArtifactMaterializationValidationError(
            f"{recipe.tool_key} source-family mismatch"
        )
    if construct.source_compatibility == "same_family" and len(set(families)) > 1:
        raise ArtifactMaterializationValidationError(
            f"{recipe.tool_key} requires same-family sources"
        )


def _validate_utc_outputs(recipe: PortableRecipeV1) -> None:
    by_role = {item.role: item.output_name for item in recipe.dependencies}
    trend_window = int(
        recipe.parameters.get(
            "trend_fractal_window", recipe.parameters.get("fractal_window", 5)
        )
    )
    range_window = int(recipe.parameters.get("range_fractal_window", 3))
    expected = {
        "trend_peak": f"peak_fractal_{trend_window}",
        "trend_trough": f"trough_fractal_{trend_window}",
        "range_peak": f"peak_fractal_{range_window}",
        "range_trough": f"trough_fractal_{range_window}",
    }
    if by_role != expected:
        raise ArtifactMaterializationValidationError(
            "UTC dependency outputs do not match trend/range windows"
        )


def _resolve_execution_configuration(
    recipe: PortableRecipeV1,
) -> _ResolvedExecutionConfiguration:
    parameters = dict(recipe.parameters)
    bindings: dict[str, object] = {}
    key = recipe.tool_key
    selectors: dict[str, str] = {
        item.role: item.column_name for item in recipe.ohlcv_inputs
    }
    dependency_sources: dict[str, tuple[str, str]] = {}
    dependency_alias = {
        "source": "__research_source",
        "fast": "__research_fast",
        "mid": "__research_mid",
        "slow": "__research_slow",
    }
    for dependency in recipe.dependencies:
        if dependency.role.startswith("source_"):
            selector = f"__research_{dependency.role}"
        elif recipe.tool_key == "universal_trend_classifier":
            selector = dependency.output_name
        else:
            selector = dependency_alias.get(dependency.role)
            if selector is None:
                raise ArtifactMaterializationValidationError(
                    f"unsupported dependency role: {dependency.role}"
                )
        if selector in selectors.values():
            same_utc_source = (
                key == "universal_trend_classifier"
                and dependency_sources.get(selector)
                == (dependency.recipe_id, dependency.output_name)
            )
            if not same_utc_source:
                raise ArtifactMaterializationValidationError(
                    f"duplicate source selector: {selector}"
                )
        selectors[dependency.role] = selector
        dependency_sources.setdefault(
            selector, (dependency.recipe_id, dependency.output_name)
        )

    if key in {"derivative", "angle"}:
        bindings = {"source": selectors["source"]}
    elif key == "delta":
        parameters.update(fast=selectors["fast"], slow=selectors["slow"])
    elif key in {"braids", "braid_instability"}:
        parameters.update(
            fast=selectors["fast"], mid=selectors["mid"], slow=selectors["slow"]
        )
    elif key == "trap_area":
        parameters.update(fast=selectors["fast"], slow=selectors["slow"])
        if "mid" in selectors:
            parameters["mid"] = selectors["mid"]
        else:
            parameters.pop("mid", None)
    elif key in {"percent_span_angle", "angle_momentum"}:
        ordered = tuple(
            selectors[f"source_{index}"] for index in range(1, len(selectors) + 1)
        )
        parameters["source_columns"] = ",".join(ordered)
    elif key == "universal_trend_classifier" and recipe.dependencies:
        parameters["peak_column"] = selectors["trend_peak"]
        parameters["trough_column"] = selectors["trend_trough"]
    return _ResolvedExecutionConfiguration(parameters, bindings, selectors)


def _target_configuration(
    recipe: PortableRecipeV1,
) -> tuple[dict[str, object], dict[str, object]]:
    resolved = _resolve_execution_configuration(recipe)
    parameters = dict(resolve_parameters(recipe.tool_key, resolved.parameters))
    _key, _kind, parameters, bindings, names = (
        FinancialToolCalculationResult.validate_configuration(
            tool_key=recipe.tool_key,
            kind=recipe.kind,
            parameters=parameters,
            bindings=resolved.bindings,
            output_names=recipe.output_names,
        )
    )
    if names != recipe.output_names:
        raise ArtifactMaterializationValidationError(
            f"portable Recipe output-name mismatch for {recipe.tool_key}"
        )
    return parameters, bindings


def _calculate_recipe(
    recipe: PortableRecipeV1,
    recipes_by_id: Mapping[str, PortableRecipeV1],
    target_frame: pd.DataFrame,
    dependency_frames: Mapping[str, pd.DataFrame],
) -> _CalculatedMaterializationNode:
    _validate_recipe_execution(recipe, recipes_by_id)
    resolved = _resolve_execution_configuration(recipe)
    frame = target_frame.copy(deep=True)
    target_timestamps = tuple(int(value) for value in frame["ts_ms"])
    for dependency in recipe.dependencies:
        upstream = dependency_frames.get(dependency.recipe_id)
        if upstream is None:
            raise ArtifactMaterializationValidationError(
                f"dependency result is unavailable: {dependency.recipe_id}"
            )
        if dependency.output_name not in upstream.columns:
            raise ArtifactMaterializationValidationError(
                f"dependency output is unavailable: {dependency.output_name}"
            )
        upstream_timestamps = tuple(int(value) for value in upstream["ts_ms"])
        if len(set(upstream_timestamps)) != len(upstream_timestamps):
            raise ArtifactMaterializationValidationError(
                "dependency timestamps must be unique"
            )
        if upstream_timestamps != target_timestamps:
            raise ArtifactMaterializationValidationError(
                "dependency timestamp spine does not match target OHLCV"
            )
        selector = resolved.selectors_by_role[dependency.role]
        if selector in frame.columns:
            if recipe.tool_key != "universal_trend_classifier" or not frame[
                selector
            ].reset_index(drop=True).equals(
                upstream[dependency.output_name].reset_index(drop=True)
            ):
                raise ArtifactMaterializationValidationError(
                    f"source selector collision: {selector}"
                )
            continue
        frame[selector] = upstream[dependency.output_name].to_numpy(copy=True)
    result = calculate_financial_tool(
        recipe.tool_key,
        frame,
        resolved.parameters,
        bindings=resolved.bindings,
    )
    if result.output_names != recipe.output_names:
        raise ArtifactMaterializationValidationError(
            f"portable Recipe output-name mismatch for {recipe.tool_key}"
        )
    return _CalculatedMaterializationNode(result)


def _source_refs(
    recipe: PortableRecipeV1,
    artifact_ids_by_recipe: Mapping[str, str],
) -> tuple[ArtifactSourceRefV1, ...]:
    refs: list[ArtifactSourceRefV1] = []
    for dependency in recipe.dependencies:
        artifact_id = artifact_ids_by_recipe.get(dependency.recipe_id)
        if artifact_id is None:
            raise ArtifactMaterializationValidationError(
                f"dependency Artifact is unavailable: {dependency.recipe_id}"
            )
        refs.append(
            ArtifactSourceRefV1(
                dependency.role, artifact_id, dependency.output_name
            )
        )
    return tuple(refs)


def _plan_id(
    *,
    target_market_id: MarketId,
    source_ohlcv: Mapping[str, object],
    root_recipe_ids: Sequence[str],
    member_recipe_ids: Sequence[str],
    source_recipe_collection_id: str | None,
    source_recipe_collection_revision_id: str | None,
    dependency_edges: Sequence[PortableRecipeGraphEdge],
    execution_stages: Sequence[Sequence[str]],
) -> str:
    payload = {
        "schema": "data_manager_artifact_materialization_plan_v1",
        "target_market_id": {
            "exchange": target_market_id.exchange,
            "market_type": target_market_id.market_type,
            "symbol": target_market_id.symbol,
            "timeframe": target_market_id.timeframe,
        },
        "source_ohlcv": dict(source_ohlcv),
        "root_recipe_ids": list(root_recipe_ids),
        "member_recipe_ids": list(member_recipe_ids),
        "source_recipe_collection_id": source_recipe_collection_id,
        "source_recipe_collection_revision_id": source_recipe_collection_revision_id,
        "dependency_edges": [
            {
                "dependency_recipe_id": edge.dependency_recipe_id,
                "dependent_recipe_id": edge.dependent_recipe_id,
                "role": edge.role,
                "output_name": edge.output_name,
            }
            for edge in dependency_edges
        ],
        "execution_stages": [list(stage) for stage in execution_stages],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ()
