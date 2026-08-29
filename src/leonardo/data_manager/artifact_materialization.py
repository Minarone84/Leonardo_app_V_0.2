"""Pure planning and calculation helpers for managed Artifact materialization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from leonardo.artifacts import ArtifactRecipeV1, ArtifactSourceRefV1
from leonardo.data import MarketId
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    calculate_financial_tool,
    get_financial_tool_spec,
    resolve_output_signals,
    resolve_parameters,
)
from leonardo.financial_tools.construct_input_eligibility import (
    FinancialToolInputCompatibilityError,
    FinancialToolInputSource,
    validate_financial_tool_inputs,
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
    input_sources = [
        FinancialToolInputSource(
            item.role,
            "ohlc",
            item.column_name,
            False,
            None,
            None,
            True,
            "numeric",
        )
        for item in ohlcv_inputs
    ]
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
        if signal is None:
            raise ArtifactMaterializationValidationError(
                f"missing dependency output: {dependency.output_name}"
            )
        input_sources.append(
            FinancialToolInputSource(
                dependency.role,
                upstream.kind,
                dependency.output_name,
                True,
                upstream.tool_key,
                upstream.recipe_id,
                signal.analysis_usable,
                signal.value_type,
            )
        )

    try:
        validate_financial_tool_inputs(
            spec,
            input_sources,
            parameters=recipe.parameters,
            allow_partial_roles=False,
            family_scope="all",
        )
    except FinancialToolInputCompatibilityError as exc:
        raise ArtifactMaterializationValidationError(str(exc)) from exc

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


def _calculate_artifact_configuration(
    *,
    tool_key: str,
    kind: str,
    parameters: Mapping[str, object],
    bindings: Mapping[str, object],
    output_names: tuple[str, ...],
    target_frame: pd.DataFrame,
    dependencies: Sequence[tuple[ArtifactSourceRefV1, pd.DataFrame]],
) -> FinancialToolCalculationResult:
    frame = target_frame.copy(deep=True)
    target_timestamps = tuple(int(value) for value in frame["ts_ms"])
    for ref, upstream in dependencies:
        if "ts_ms" not in upstream or ref.output_name not in upstream.columns:
            raise ArtifactMaterializationValidationError(
                f"dependency output is unavailable: {ref.output_name}"
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
        selector = _artifact_source_selector(
            tool_key, parameters, bindings, ref
        )
        values = upstream[ref.output_name].reset_index(drop=True)
        if selector in frame.columns:
            same_utc_source = (
                tool_key == "universal_trend_classifier"
                and frame[selector].reset_index(drop=True).equals(values)
            )
            if not same_utc_source:
                raise ArtifactMaterializationValidationError(
                    f"source selector collision: {selector}"
                )
            continue
        frame[selector] = values.to_numpy(copy=True)
    result = calculate_financial_tool(
        tool_key,
        frame,
        parameters,
        bindings=bindings,
    )
    if (
        result.tool_key != tool_key
        or result.kind != kind
        or dict(result.parameters) != dict(parameters)
        or dict(result.bindings) != dict(bindings)
        or result.output_names != output_names
    ):
        raise ArtifactMaterializationValidationError(
            "Artifact calculation result disagrees with persisted calculation metadata"
        )
    return result


def _calculate_artifact_recipe(
    recipe: ArtifactRecipeV1,
    target_frame: pd.DataFrame,
    dependencies: Sequence[tuple[ArtifactSourceRefV1, pd.DataFrame]],
) -> FinancialToolCalculationResult:
    return _calculate_artifact_configuration(
        tool_key=recipe.tool_key,
        kind=recipe.kind,
        parameters=recipe.parameters,
        bindings=recipe.bindings,
        output_names=recipe.output_names,
        target_frame=target_frame,
        dependencies=dependencies,
    )


def _artifact_source_selector(
    tool_key: str,
    parameters: Mapping[str, object],
    bindings: Mapping[str, object],
    ref: ArtifactSourceRefV1,
) -> str:
    for values in (bindings, parameters):
        selector = values.get(ref.role)
        if isinstance(selector, str) and selector.strip():
            return selector.strip()
    if ref.role.startswith("source_"):
        raw_columns = parameters.get("source_columns")
        if isinstance(raw_columns, str):
            columns = tuple(
                value.strip() for value in raw_columns.split(",") if value.strip()
            )
            try:
                index = int(ref.role.removeprefix("source_")) - 1
            except ValueError as exc:
                raise ArtifactMaterializationValidationError(
                    f"unsupported Artifact source role: {ref.role}"
                ) from exc
            if 0 <= index < len(columns):
                return columns[index]
    if tool_key == "universal_trend_classifier":
        return ref.output_name
    raise ArtifactMaterializationValidationError(
        f"Artifact source selector is unavailable for role: {ref.role}"
    )


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
