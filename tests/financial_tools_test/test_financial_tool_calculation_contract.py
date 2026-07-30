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


def _utc_frame(rows: int = 96) -> pd.DataFrame:
    data = _frame(rows)
    dependencies = calculate_financial_tool("peaks_troughs", data).to_frame()
    for name in (
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_3",
        "trough_fractal_3",
    ):
        data[name] = dependencies[name]
    return data


def _utc_parameters() -> dict[str, object]:
    return {
        "peak_column": "peak_fractal_5",
        "trough_column": "trough_fractal_5",
    }


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
    result = calculate_financial_tool("UTC", _utc_frame(), _utc_parameters())
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


def _rebuild_result(
    result: FinancialToolCalculationResult,
    **changes: object,
) -> FinancialToolCalculationResult:
    values = {
        "tool_key": result.tool_key,
        "kind": result.kind,
        "parameters": result.parameters,
        "bindings": result.bindings,
        "output_names": result.output_names,
        "frame": result.to_frame(),
        "analysis": result.analysis,
    }
    values.update(changes)
    return FinancialToolCalculationResult(**values)  # type: ignore[arg-type]


def test_result_constructor_rejects_noncanonical_source_binding() -> None:
    result = calculate_financial_tool(
        "derivative", _frame(), {"order": 1}, bindings={"source": "close"}
    )
    with pytest.raises(ValueError, match="canonical non-empty"):
        _rebuild_result(result, bindings={"source": " close "})


@pytest.mark.parametrize("tool_key", ("dynamic_binning", "percent_span_angle"))
def test_result_constructor_rejects_forbidden_runtime_window(tool_key: str) -> None:
    result = calculate_financial_tool(tool_key, _frame(), {"window": 2})
    parameters = dict(result.parameters)
    parameters["window"] = 1
    with pytest.raises(ValueError, match="window must be >= 2"):
        _rebuild_result(result, parameters=parameters)


@pytest.mark.parametrize("tool_key", ("braids", "braid_instability"))
def test_result_constructor_rejects_empty_braid_mid(tool_key: str) -> None:
    result = calculate_financial_tool(
        tool_key, _frame(), {"fast": "fast", "mid": "mid", "slow": "slow"}
    )
    parameters = dict(result.parameters)
    parameters["mid"] = ""
    with pytest.raises(ValueError, match="mid must be a non-empty"):
        _rebuild_result(result, parameters=parameters)


def test_result_constructor_rejects_wrong_outputs_and_frame_columns() -> None:
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    with pytest.raises(ValueError, match="output_names"):
        _rebuild_result(result, output_names=("wrong",))
    with pytest.raises(ValueError, match="frame columns"):
        _rebuild_result(result, frame=result.to_frame().rename(columns={"sma_3": "wrong"}))


def test_result_constructor_rejects_invalid_frame_identity_and_analysis() -> None:
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    with pytest.raises(ValueError, match="strictly increasing"):
        _rebuild_result(
            result,
            frame=result.to_frame().assign(
                ts_ms=lambda frame: frame.ts_ms.mask(frame.index == frame.index[1], frame.ts_ms.iloc[0])
            ),
        )
    with pytest.raises(TypeError, match="analysis must be a mapping"):
        _rebuild_result(result, analysis=[1, 2])


@pytest.mark.parametrize(
    "values",
    (
        pd.Series(["1.0"] * 48, dtype="object"),
        pd.Series([True] * 48, dtype="bool"),
        pd.Series([1.0] * 48, dtype="float64"),
    ),
)
def test_result_constructor_rejects_noncanonical_numeric_runtime(values: pd.Series) -> None:
    result = calculate_financial_tool("sma", _frame(), {"period": 3})
    forged = result.to_frame()
    forged["sma_3"] = values.to_numpy()
    with pytest.raises(ValueError, match="runtime dtype must be float32"):
        _rebuild_result(result, frame=forged)


def _assert_hck_categorical_rejected(values: pd.Series) -> None:
    result = calculate_financial_tool("hck", _frame())
    forged = result.to_frame()
    forged["vwap_color"] = values
    with pytest.raises(ValueError):
        _rebuild_result(result, frame=forged)


def _hck_color_values() -> tuple[pd.Index, list[object]]:
    values = calculate_financial_tool("hck", _frame()).to_frame()["vwap_color"]
    return values.index, values.astype(object).tolist()


@pytest.mark.parametrize("dtype", ("object", "string"))
def test_result_constructor_rejects_string_categorical_runtime(dtype: str) -> None:
    index, values = _hck_color_values()
    _assert_hck_categorical_rejected(pd.Series(values, index=index, dtype=dtype))


@pytest.mark.parametrize(
    ("categories", "ordered"),
    (
        (("green", "silver", "red"), False),
        (("red", "green"), False),
        (("red", "silver", "green", "blue"), False),
        (("red", "silver", "green"), True),
    ),
)
def test_result_constructor_rejects_noncanonical_categorical_dtype(
    categories: tuple[str, ...],
    ordered: bool,
) -> None:
    index, values = _hck_color_values()
    _assert_hck_categorical_rejected(
        pd.Series(
            pd.Categorical(values, categories=categories, ordered=ordered),
            index=index,
        )
    )


def test_result_constructor_rejects_unknown_categorical_value() -> None:
    index, values = _hck_color_values()
    _assert_hck_categorical_rejected(
        pd.Series(
            pd.Categorical(
                ["blue", *values[1:]],
                categories=("red", "silver", "green", "blue"),
                ordered=False,
            ),
            index=index,
        )
    )


def test_result_constructor_rejects_null_categorical_value() -> None:
    index, values = _hck_color_values()
    values[0] = None
    _assert_hck_categorical_rejected(
        pd.Series(
            pd.Categorical(
                values,
                categories=("red", "silver", "green"),
                ordered=False,
            ),
            index=index,
        )
    )


def test_braids_runtime_state_is_numeric_float32_and_domain_checked() -> None:
    result = calculate_financial_tool(
        "braids", _frame(), {"fast": "fast", "mid": "mid", "slow": "slow"}
    )
    ambient = result.output_names[0]
    assert result.to_frame()[ambient].dtype == np.dtype("float32")
    forged = result.to_frame()
    forged.loc[forged.index[0], ambient] = np.float32(7.0)
    with pytest.raises(ValueError, match="states 1 through 6"):
        _rebuild_result(result, frame=forged)


def test_utc_runtime_boolean_outputs_remain_bool() -> None:
    with pytest.raises(ValueError, match="trend dependency pair"):
        calculate_financial_tool("universal_trend_classifier", _frame(96))
    result = calculate_financial_tool(
        "universal_trend_classifier", _utc_frame(), _utc_parameters()
    )
    assert tuple(result.to_frame()) == ("ts_ms", *result.output_names)
    assert tuple(result.parameters) == (
        "source",
        "fractal_window",
        "trend_fractal_window",
        "peak_column",
        "trough_column",
        "min_hr_band_perc",
        "hr_trend_length",
        "hr_trend_atr_mult",
        "hr_trend_atr_len",
        "hr_trend_tol_mult",
        "hr_trend_max_gap",
        "hr_min_inside_ratio",
        "min_range_swings",
        "range_fractal_window",
        "hr_break_mode",
    )
    assert not {
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_3",
        "trough_fractal_3",
    }.intersection(result.output_names)
    runtime_types = FinancialToolCalculationResult.runtime_output_types(
        tool_key=result.tool_key,
        parameters=result.parameters,
        bindings=result.bindings,
        output_names=result.output_names,
    )
    for name, runtime_type in zip(result.output_names, runtime_types, strict=True):
        if runtime_type == "boolean":
            assert result.to_frame()[name].dtype == np.dtype("bool")
