from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

import leonardo.financial_tools as financial_tools
from leonardo.financial_tools import FinancialToolCalculationResult, calculate_financial_tool


def _frame(rows: int = 48) -> pd.DataFrame:
    values = np.arange(rows, dtype="float64")
    return pd.DataFrame(
        {
            "ts_ms": 1_700_000_000_000 + values.astype("int64") * 60_000,
            "open": 100.0 + values,
            "high": 101.0 + values,
            "low": 99.0 + values,
            "close": 100.5 + values,
            "volume": 1_000.0 + values,
            "fast": values + 3.0,
            "mid": values + 2.0,
            "slow": values + 1.0,
        },
        index=pd.Index(range(100, 100 + rows), name="row"),
    )


def test_public_api_and_alias_are_exact() -> None:
    assert financial_tools.__all__ == (
        "ALL_FINANCIAL_TOOL_SPECS", "CANONICAL_TOOL_ALIASES", "CONSTRUCT_SPECS",
        "ConstructIOSpec", "DataInputSpec", "FinancialToolSpec",
        "FinancialToolCalculationResult", "INDICATOR_SPECS", "OSCILLATOR_SPECS",
        "OscillatorGuideLevelSpec", "OscillatorVisualSpec", "OutputSignalSpec",
        "ParameterSpec", "ToolBehaviorSpec", "ToolEditCapabilities", "ToolOutputSpec",
        "ToolStyleCapabilities", "build_source_token", "calculate_financial_tool",
        "canonicalize_tool_key", "get_financial_tool_spec", "list_financial_tool_specs",
        "resolve_output_names", "resolve_output_signals", "resolve_parameters", "validate_catalog",
    )
    result = calculate_financial_tool("UTC", _frame(96))
    assert result.tool_key == "universal_trend_classifier"
    assert isinstance(result, FinancialToolCalculationResult)


def test_parameters_and_bindings_are_strict() -> None:
    data = _frame()
    with pytest.raises(ValueError):
        calculate_financial_tool("sma", data, {"period": 3, "unknown": 1})
    with pytest.raises((TypeError, ValueError)):
        calculate_financial_tool("sma", data, {"period": "3"})
    with pytest.raises(ValueError):
        calculate_financial_tool("sma", data, bindings={"source": "close"})
    with pytest.raises(ValueError):
        calculate_financial_tool("derivative", data)
    with pytest.raises(ValueError):
        calculate_financial_tool("derivative", data, bindings={"source_column": "close"})
    with pytest.raises(ValueError):
        calculate_financial_tool("angle", data, bindings={"source": "missing"})
    result = calculate_financial_tool("derivative", data, {"order": 1}, bindings={"source": "close"})
    assert result.bindings == {"source": "close"}
    assert result.output_names == ("close__d1",)


def test_input_and_result_are_defensively_preserved() -> None:
    data = _frame()
    original = data.copy(deep=True)
    result = calculate_financial_tool("sma", data, {"period": 3})
    pd.testing.assert_frame_equal(data, original)
    output = result.to_frame()
    assert output.index.equals(data.index)
    assert output["ts_ms"].equals(data["ts_ms"])
    assert tuple(output.columns) == ("ts_ms", "sma_3")
    assert result.row_count == len(data)
    assert result.first_timestamp_ms == int(data["ts_ms"].iloc[0])
    assert result.last_timestamp_ms == int(data["ts_ms"].iloc[-1])
    assert isinstance(result.parameters, MappingProxyType)
    assert isinstance(result.bindings, MappingProxyType)
    output.iloc[0, 0] = -1
    assert result.to_frame()["ts_ms"].iloc[0] == data["ts_ms"].iloc[0]
    analysis = result.analysis
    analysis["changed"] = True
    assert result.analysis == {}
    with pytest.raises(TypeError):
        result.parameters["period"] = 4  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.tool_key = "ema"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutator",
    (
        lambda frame: frame.iloc[0:0],
        lambda frame: frame.drop(columns="ts_ms"),
        lambda frame: frame.assign(ts_ms=lambda item: item["ts_ms"].where(item.index != item.index[0])),
        lambda frame: frame.assign(ts_ms=lambda item: item["ts_ms"].astype("float64") + 0.5),
        lambda frame: frame.assign(ts_ms=lambda item: item["ts_ms"].mask(item.index == item.index[1], item["ts_ms"].iloc[0])),
        lambda frame: frame.sort_index(ascending=False),
        lambda frame: frame.set_axis([0] * len(frame)),
        lambda frame: frame.assign(close="not-numeric"),
    ),
)
def test_invalid_frames_are_rejected(mutator: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        calculate_financial_tool("sma", mutator(_frame()))  # type: ignore[operator]


def test_duplicate_columns_and_boolean_timestamps_are_rejected() -> None:
    duplicate = pd.concat([_frame(), _frame()[["close"]]], axis=1)
    with pytest.raises(ValueError):
        calculate_financial_tool("sma", duplicate)
    boolean_ts = _frame()
    boolean_ts["ts_ms"] = True
    with pytest.raises(ValueError):
        calculate_financial_tool("sma", boolean_ts)


def test_lowercase_volume_is_required() -> None:
    data = _frame().rename(columns={"volume": "Volume"})
    with pytest.raises(ValueError):
        calculate_financial_tool("volume", data)


def test_dynamic_binning_has_no_output_columns() -> None:
    result = calculate_financial_tool(
        "dynamic_binning",
        _frame(),
        {"source_columns": "close", "window": 4},
    )
    assert result.output_names == ()
    assert tuple(result.to_frame().columns) == ("ts_ms",)
    assert set(result.analysis) == {"steps", "variation_diagnostics", "binning_artifact", "labeled_rows"}
