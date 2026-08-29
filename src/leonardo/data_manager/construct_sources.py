from __future__ import annotations

from dataclasses import dataclass

from leonardo.artifacts import ArtifactService, OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.financial_tools.construct_input_eligibility import (
    construct_input_policy,
)
from leonardo.financial_tools.specifications import resolve_output_signals


@dataclass(frozen=True, slots=True)
class ConstructSourceSignal:
    market_id: MarketId
    logical_artifact_id: str
    artifact_id: str
    tool_key: str
    kind: str
    output_name: str
    label: str
    source_ohlcv: OHLCVSourceFingerprintV1


def list_construct_source_signals(
    artifact_service: ArtifactService,
    market_id: MarketId,
) -> tuple[ConstructSourceSignal, ...]:
    signals: list[ConstructSourceSignal] = []
    for summary in artifact_service.list_managed_artifacts(market_id):
        if not summary.valid:
            continue
        loaded = artifact_service.load_artifact_by_id(market_id, summary.artifact_id)
        recipe = loaded.metadata.recipe
        if construct_input_policy(recipe.tool_key) == "none":
            continue
        configuration = {**recipe.parameters, **recipe.bindings}
        resolved_by_name = {
            signal.name: signal
            for signal in resolve_output_signals(recipe.tool_key, configuration)
        }
        for output_name in recipe.output_names:
            resolved = resolved_by_name.get(output_name)
            if (
                resolved is None
                or resolved.signal_type != "signal"
                or resolved.value_type != "numeric"
            ):
                continue
            signals.append(
                ConstructSourceSignal(
                    market_id=recipe.market_id,
                    logical_artifact_id=summary.logical_artifact_id,
                    artifact_id=summary.artifact_id,
                    tool_key=recipe.tool_key,
                    kind=recipe.kind,
                    output_name=output_name,
                    label=resolved.label or output_name,
                    source_ohlcv=loaded.metadata.source_ohlcv,
                )
            )
    kind_order = {"indicator": 0, "oscillator": 1, "construct": 2}
    return tuple(
        sorted(
            signals,
            key=lambda item: (
                kind_order[item.kind],
                item.tool_key,
                item.logical_artifact_id,
                item.output_name,
            ),
        )
    )
