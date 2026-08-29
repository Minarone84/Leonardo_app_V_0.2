from __future__ import annotations

import hashlib
from pathlib import Path

from leonardo.artifacts import (
    ArtifactService,
    ArtifactSourceRefV1,
    PreparedManagedArtifact,
)
from leonardo.data_manager.construct_sources import list_construct_source_signals
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    calculate_financial_tool,
)

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset


def _portable_id(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _publish(
    service: ArtifactService,
    market,
    result: FinancialToolCalculationResult,
    label: str,
    *,
    source_artifacts: tuple[ArtifactSourceRefV1, ...] = (),
    source_metadata=(),
) -> PreparedManagedArtifact:
    source = service.capture_accepted_source(market)
    candidate = service.prepare_managed_calculation(
        market,
        _portable_id(label),
        result,
        expected_source=source,
        source_artifacts=source_artifacts,
        source_metadata=source_metadata,
    )
    service.publish_managed_artifact_graph((candidate,), expected_source=source)
    return candidate


def _attach(frame, result: FinancialToolCalculationResult) -> None:
    values = result.to_frame()
    for output_name in result.output_names:
        frame[output_name] = values[output_name].to_numpy(copy=True)


def test_construct_source_catalog_projects_current_saved_numeric_signals(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    published: dict[str, tuple[PreparedManagedArtifact, FinancialToolCalculationResult]] = {}

    def publish_leaf(
        label: str,
        tool_key: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        result = calculate_financial_tool(tool_key, frame, parameters)
        published[label] = (_publish(service, market, result, label), result)

    publish_leaf("bb", "bb", {"period": 3, "std": 2.0})
    publish_leaf("hck", "hck", {"fast_vwap_l": 3, "slow_vwap_l": 5})
    publish_leaf("strategy", "strategy")
    publish_leaf("rsi", "rsi", {"period": 3})
    publish_leaf("arsi", "arsi", {"period": 3, "signal_period": 2})
    publish_leaf("smi", "smi", {"k_length": 3, "d_length": 2})
    publish_leaf("volume", "volume", {"period": 3})
    publish_leaf("sma_3", "sma", {"period": 3})
    publish_leaf("sma_5", "sma", {"period": 5})
    publish_leaf("peaks", "peaks_troughs")

    peaks_candidate, peaks_result = published["peaks"]
    utc_frame = frame.copy(deep=True)
    _attach(utc_frame, peaks_result)
    utc_result = calculate_financial_tool(
        "universal_trend_classifier",
        utc_frame,
        {"peak_column": "peak_fractal_5", "trough_column": "trough_fractal_5"},
    )
    utc_refs = tuple(
        ArtifactSourceRefV1(role, peaks_candidate.metadata.artifact_id, output)
        for role, output in (
            ("trend_peak", "peak_fractal_5"),
            ("trend_trough", "trough_fractal_5"),
            ("range_peak", "peak_fractal_3"),
            ("range_trough", "trough_fractal_3"),
        )
    )
    published["utc"] = (
        _publish(
            service,
            market,
            utc_result,
            "utc",
            source_artifacts=utc_refs,
            source_metadata=(peaks_candidate.metadata,),
        ),
        utc_result,
    )

    sma_candidate, sma_result = published["sma_3"]
    derivative_frame = frame.copy(deep=True)
    _attach(derivative_frame, sma_result)
    derivative_result = calculate_financial_tool(
        "derivative", derivative_frame, {"order": 1}, bindings={"source": "sma_3"}
    )
    derivative_candidate = _publish(
        service,
        market,
        derivative_result,
        "derivative",
        source_artifacts=(
            ArtifactSourceRefV1(
                "source", sma_candidate.metadata.artifact_id, "sma_3"
            ),
        ),
        source_metadata=(sma_candidate.metadata,),
    )
    published["derivative"] = (derivative_candidate, derivative_result)

    rsi_candidate, rsi_result = published["rsi"]
    braid_frame = frame.copy(deep=True)
    _attach(braid_frame, sma_result)
    _attach(braid_frame, rsi_result)
    _attach(braid_frame, derivative_result)
    braid_parameters = {
        "fast": "sma_3",
        "mid": "rsi_3",
        "slow": "sma_3__d1",
    }
    braid_refs = (
        ArtifactSourceRefV1("fast", sma_candidate.metadata.artifact_id, "sma_3"),
        ArtifactSourceRefV1("mid", rsi_candidate.metadata.artifact_id, "rsi_3"),
        ArtifactSourceRefV1(
            "slow", derivative_candidate.metadata.artifact_id, "sma_3__d1"
        ),
    )
    braid_metadata = (
        sma_candidate.metadata,
        rsi_candidate.metadata,
        derivative_candidate.metadata,
    )
    braids_result = calculate_financial_tool(
        "braids", braid_frame, {**braid_parameters, "tie_policy": "carry"}
    )
    published["braids"] = (
        _publish(
            service,
            market,
            braids_result,
            "braids",
            source_artifacts=braid_refs,
            source_metadata=braid_metadata,
        ),
        braids_result,
    )
    instability_result = calculate_financial_tool(
        "braid_instability", braid_frame, {**braid_parameters, "n": 3}
    )
    instability_candidate = _publish(
        service,
        market,
        instability_result,
        "braid_instability",
        source_artifacts=braid_refs,
        source_metadata=braid_metadata,
    )
    published["braid_instability"] = (instability_candidate, instability_result)

    signals = list_construct_source_signals(service, market)
    by_tool: dict[str, set[str]] = {}
    for signal in signals:
        by_tool.setdefault(signal.tool_key, set()).add(signal.output_name)

    assert by_tool["bb"] == {"bb_middle", "bb_upper_band", "bb_lower_band"}
    assert by_tool["hck"] == {"fast_vwap", "slow_vwap"}
    assert "vwap_color" not in by_tool["hck"]
    assert len(by_tool["strategy"]) == 17
    assert "st_vwap_color" not in by_tool["strategy"]
    assert by_tool["rsi"] == {"rsi_3"}
    assert by_tool["arsi"] == {"arsi_3_rma", "arsi_signal_3_rma_2_ema"}
    assert by_tool["smi"] == {"smi_3_2", "smi_signal_3_2"}
    assert by_tool["volume"] == {"volume", "volume_mean_3"}
    assert "peaks_troughs" not in by_tool
    assert "universal_trend_classifier" not in by_tool
    assert "braids" not in by_tool
    assert by_tool["braid_instability"] == set(instability_result.output_names)
    assert by_tool["derivative"] == {"sma_3__d1"}

    sma_entries = [signal for signal in signals if signal.tool_key == "sma"]
    assert {signal.output_name for signal in sma_entries} == {"sma_3", "sma_5"}
    assert len({signal.logical_artifact_id for signal in sma_entries}) == 2
    assert all(signal.market_id == market for signal in signals)
    assert all(signal.output_name not in {"open", "high", "low", "close"} for signal in signals)
    assert all(signal.source_ohlcv == service.capture_accepted_source(market) for signal in signals)

    instability_entry = next(
        signal for signal in signals if signal.tool_key == "braid_instability"
    )
    assert instability_entry.logical_artifact_id == instability_candidate.logical_artifact_id
    assert instability_entry.artifact_id == instability_candidate.metadata.artifact_id
    assert instability_entry.label == "Braid Instability"

    expected_order = sorted(
        signals,
        key=lambda item: (
            {"indicator": 0, "oscillator": 1, "construct": 2}[item.kind],
            item.tool_key,
            item.logical_artifact_id,
            item.output_name,
        ),
    )
    assert list(signals) == expected_order
