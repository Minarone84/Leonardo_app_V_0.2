"""Pure expansion and preview projection for Construct batches."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.financial_tools import (
    get_financial_tool_spec,
    resolve_output_names,
    resolve_parameters,
)

from .creation_models import (
    BatchArtifactSource,
    BatchArtifactBranchRequest,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DataManagerCreationError,
)
from .direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
    DataManagerDirectArtifactSource,
)


SUPPORTED_BATCH_CONSTRUCTS = (
    "derivative",
    "angle",
    "percent_span_angle",
    "angle_momentum",
    "delta",
    "trap_area",
    "braids",
    "braid_instability",
)


class ConstructBatchSourceScope(str, Enum):
    SELECTED_SIGNALS = "Selected Signals"
    ALL_INDICATORS = "All Indicators"
    ALL_OSCILLATORS = "All Oscillators"
    ALL_CONSTRUCTS = "All Constructs"


@dataclass(frozen=True, slots=True)
class ConstructBatchSignal:
    logical_artifact_id: str | None
    artifact_id: str | None
    output_name: str
    tool_key: str | None
    kind: str
    label: str
    source_kind: str = "artifact"
    market_id: MarketId | None = None
    source_ohlcv: OHLCVSourceFingerprintV1 | None = None
    column: str | None = None

    @classmethod
    def from_option(
        cls, option: DataManagerDirectArtifactOption, output_name: str
    ) -> "ConstructBatchSignal":
        if output_name not in option.output_names:
            raise DataManagerCreationError("signal output is not available")
        return cls(
            option.logical_artifact_id,
            option.artifact_id,
            output_name,
            option.tool_key,
            option.kind,
            f"{option.display_name} / {output_name}",
        )

    @classmethod
    def from_current_ohlcv(
        cls, catalog: DataManagerDirectArtifactCatalog, column: str
    ) -> "ConstructBatchSignal":
        source = BatchArtifactSource.current_ohlcv(
            "source", catalog.market_id, catalog.source_ohlcv, column
        )
        return cls(
            None,
            None,
            source.output_name,
            None,
            source.source_kind,
            source.label,
            source.source_kind,
            source.market_id,
            source.source_ohlcv,
            source.column,
        )

    def as_source(self, role: str) -> BatchArtifactSource:
        if self.source_kind == "current_ohlcv":
            return BatchArtifactSource.current_ohlcv(
                role, self.market_id, self.source_ohlcv, self.column
            )
        return BatchArtifactSource.from_artifact(
            DataManagerDirectArtifactSource(
                role, self.logical_artifact_id, self.artifact_id, self.output_name
            ),
            label=self.label,
        )


@dataclass(frozen=True, slots=True)
class ConstructBatchCombination:
    fast: ConstructBatchSignal
    slow: ConstructBatchSignal
    mid: ConstructBatchSignal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.fast, ConstructBatchSignal) or not isinstance(
            self.slow, ConstructBatchSignal
        ):
            raise TypeError("fast and slow must be ConstructBatchSignal values")
        if self.mid is not None and not isinstance(self.mid, ConstructBatchSignal):
            raise TypeError("mid must be a ConstructBatchSignal or None")

    def sources(self) -> tuple[BatchArtifactSource, ...]:
        values = [self.fast.as_source("fast")]
        if self.mid is not None:
            values.append(self.mid.as_source("mid"))
        values.append(self.slow.as_source("slow"))
        return tuple(values)


@dataclass(frozen=True, slots=True)
class ConstructBatchExpansionRequest:
    catalog: DataManagerDirectArtifactCatalog
    tool_key: str
    parameters: Mapping[str, object]
    source_scope: ConstructBatchSourceScope
    selected_signals: tuple[ConstructBatchSignal, ...] = ()
    fixed_signal: ConstructBatchSignal | None = None
    fixed_role: str | None = None
    combinations: tuple[ConstructBatchCombination, ...] = ()
    destination: str = "individual"
    collection_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        if self.tool_key not in SUPPORTED_BATCH_CONSTRUCTS:
            raise DataManagerCreationError("unsupported batch Construct")
        if not isinstance(self.source_scope, ConstructBatchSourceScope):
            raise TypeError("source_scope must be a ConstructBatchSourceScope")
        resolved = resolve_parameters(self.tool_key, self.parameters)
        object.__setattr__(
            self, "parameters", MappingProxyType(deepcopy(dict(resolved)))
        )
        selected = tuple(self.selected_signals)
        combinations = tuple(self.combinations)
        if not all(isinstance(item, ConstructBatchSignal) for item in selected):
            raise TypeError("selected_signals contain invalid values")
        if not all(isinstance(item, ConstructBatchCombination) for item in combinations):
            raise TypeError("combinations contain invalid values")
        object.__setattr__(self, "selected_signals", selected)
        object.__setattr__(self, "combinations", combinations)


@dataclass(frozen=True, slots=True)
class ConstructBatchPreviewRow:
    sources: str
    construct: str
    parameters: str
    inputs: str
    result: str


def catalog_signals(
    catalog: DataManagerDirectArtifactCatalog,
) -> tuple[ConstructBatchSignal, ...]:
    if not isinstance(catalog, DataManagerDirectArtifactCatalog):
        raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
    return tuple(
        ConstructBatchSignal.from_option(option, output_name)
        for option in catalog.construct_options
        for output_name in option.output_names
    )


def current_ohlcv_signals(
    catalog: DataManagerDirectArtifactCatalog,
) -> tuple[ConstructBatchSignal, ...]:
    if not isinstance(catalog, DataManagerDirectArtifactCatalog):
        raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
    return tuple(
        ConstructBatchSignal.from_current_ohlcv(catalog, column)
        for column in ("open", "high", "low", "close")
    )


def expand_construct_batch(
    value: ConstructBatchExpansionRequest,
) -> BatchArtifactRequest:
    if not isinstance(value, ConstructBatchExpansionRequest):
        raise TypeError("value must be a ConstructBatchExpansionRequest")
    artifact_signals = catalog_signals(value.catalog)
    available = (*current_ohlcv_signals(value.catalog), *artifact_signals)
    available_keys = {_signal_key(item) for item in available}
    pool = _resolve_scope(value, available, artifact_signals, available_keys)
    branches: list[BatchArtifactBranchRequest] = []
    if value.tool_key in {
        "derivative",
        "angle",
        "percent_span_angle",
        "angle_momentum",
    }:
        role = (
            "source_1"
            if value.tool_key in {"percent_span_angle", "angle_momentum"}
            else "source"
        )
        branches.extend(
            _branch(value.tool_key, value.parameters, (signal.as_source(role),))
            for signal in pool
        )
    elif value.tool_key == "delta":
        fixed = value.fixed_signal
        if fixed is None or _signal_key(fixed) not in available_keys:
            raise DataManagerCreationError("Delta requires one current fixed signal")
        if value.fixed_role not in {"fast", "slow"}:
            raise DataManagerCreationError("Delta fixed role must be fast or slow")
        for variable in pool:
            if _signal_key(variable) == _signal_key(fixed):
                continue
            fast, slow = (
                (fixed, variable)
                if value.fixed_role == "fast"
                else (variable, fixed)
            )
            branches.append(
                _branch(
                    value.tool_key,
                    value.parameters,
                    (fast.as_source("fast"), slow.as_source("slow")),
                )
            )
    else:
        pool_keys = {_signal_key(item) for item in pool}
        for combination in value.combinations:
            signals = (combination.fast, combination.slow)
            if combination.mid is not None:
                signals += (combination.mid,)
            if any(_signal_key(item) not in pool_keys for item in signals):
                raise DataManagerCreationError(
                    "explicit combination contains a signal outside the resolved scope"
                )
            if value.tool_key in {"braids", "braid_instability"} and combination.mid is None:
                raise DataManagerCreationError(
                    f"{value.tool_key} requires explicit fast/mid/slow triples"
                )
            branches.append(
                _branch(value.tool_key, value.parameters, combination.sources())
            )
    if not branches:
        raise DataManagerCreationError("batch expansion produced no branches")
    return BatchArtifactRequest(
        market_id=value.catalog.market_id,
        expected_source_ohlcv=value.catalog.source_ohlcv,
        branches=tuple(branches),
        destination=value.destination,
        collection_id=value.collection_id,
    )


def project_batch_preview(plan: BatchArtifactPlan) -> tuple[ConstructBatchPreviewRow, ...]:
    if not isinstance(plan, BatchArtifactPlan):
        raise TypeError("plan must be a BatchArtifactPlan")
    rows = []
    for branch, reuse_current in zip(
        plan.request.branches, plan.branch_reuse_current, strict=True
    ):
        sources = "; ".join(source.label for source in branch.sources)
        inputs = "; ".join(
            f"{source.role}={source.label}" for source in branch.sources
        )
        parameters = ", ".join(
            f"{key}={value}" for key, value in sorted(branch.parameters.items())
        )
        rows.append(
            ConstructBatchPreviewRow(
                sources,
                get_financial_tool_spec(branch.tool_key).title,
                parameters,
                inputs,
                "Reuse Current" if reuse_current else "New",
            )
        )
    return tuple(rows)


def visible_output_names(
    tool_key: str,
    parameters: Mapping[str, object],
    sources: tuple[BatchArtifactSource | DataManagerDirectArtifactSource, ...],
) -> tuple[str, ...]:
    naming = dict(resolve_parameters(tool_key, parameters))
    by_role = {source.role: source.output_name for source in sources}
    if tool_key in {"derivative", "angle"}:
        naming["source"] = by_role["source"]
    elif tool_key in {"percent_span_angle", "angle_momentum"}:
        naming["source_columns"] = ",".join(
            by_role[f"source_{index}"] for index in range(1, len(sources) + 1)
        )
    else:
        naming.update(by_role)
        if tool_key == "trap_area" and "mid" not in by_role:
            naming.pop("mid", None)
    return resolve_output_names(tool_key, naming)


def _resolve_scope(
    value: ConstructBatchExpansionRequest,
    available: tuple[ConstructBatchSignal, ...],
    artifact_signals: tuple[ConstructBatchSignal, ...],
    available_keys: set[tuple[object, ...]],
) -> tuple[ConstructBatchSignal, ...]:
    if value.source_scope is ConstructBatchSourceScope.SELECTED_SIGNALS:
        if any(_signal_key(item) not in available_keys for item in value.selected_signals):
            raise DataManagerCreationError("selected signal is not in the current catalogue")
        return value.selected_signals
    kind = {
        ConstructBatchSourceScope.ALL_INDICATORS: "indicator",
        ConstructBatchSourceScope.ALL_OSCILLATORS: "oscillator",
        ConstructBatchSourceScope.ALL_CONSTRUCTS: "construct",
    }[value.source_scope]
    return tuple(item for item in artifact_signals if item.kind == kind)


def _branch(
    tool_key: str,
    parameters: Mapping[str, object],
    sources: tuple[BatchArtifactSource, ...],
) -> BatchArtifactBranchRequest:
    return BatchArtifactBranchRequest(
        tool_key=tool_key,
        parameters=parameters,
        sources=sources,
        requested_outputs=visible_output_names(tool_key, parameters, sources),
    )


def _signal_key(signal: ConstructBatchSignal) -> tuple[object, ...]:
    if signal.source_kind == "current_ohlcv":
        return (
            signal.source_kind,
            signal.market_id,
            signal.source_ohlcv,
            signal.column,
        )
    return (
        signal.source_kind,
        signal.logical_artifact_id,
        signal.artifact_id,
        signal.output_name,
    )
