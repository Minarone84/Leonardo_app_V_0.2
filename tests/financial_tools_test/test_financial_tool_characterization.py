from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    calculate_financial_tool,
)


FIXTURES = Path(__file__).with_name("fixtures")
CONTINUOUS_ATOL = 0.00005
CONTINUOUS_RTOL = 0.0


def _assert_nested(actual: object, expected: object) -> None:
    if isinstance(expected, Mapping):
        assert isinstance(actual, Mapping)
        assert set(actual) == set(expected)
        for key, value in expected.items():
            _assert_nested(actual[key], value)
        return
    if isinstance(expected, list):
        assert isinstance(actual, Sequence) and not isinstance(actual, (str, bytes))
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            _assert_nested(actual_item, expected_item)
        return
    if isinstance(expected, float):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert np.isclose(
            float(actual),
            expected,
            rtol=CONTINUOUS_RTOL,
            atol=CONTINUOUS_ATOL,
            equal_nan=True,
        )
        return
    assert actual == expected


def test_all_26_tools_match_frozen_characterization_fixture() -> None:
    data = pd.read_csv(
        FIXTURES / "task_1015_characterization_input.csv",
        float_precision="round_trip",
    )
    expected = json.loads(
        (FIXTURES / "task_1015_characterization_expected.json").read_text(encoding="utf-8")
    )
    assert expected["row_count"] == len(data) == 640
    assert len(expected["tools"]) == 26

    original = data.copy(deep=True)
    peaks_record = expected["tools"]["peaks_troughs"]
    peaks_result = calculate_financial_tool(
        "peaks_troughs",
        data,
        peaks_record["parameters"],
        bindings=peaks_record["bindings"],
    )
    assert peaks_result.output_names == tuple(peaks_record["output_names"])
    utc_data = data.copy(deep=True)
    peaks_frame = peaks_result.to_frame()
    for output_name in peaks_result.output_names:
        utc_data[output_name] = peaks_frame[output_name].copy(deep=True)
    pd.testing.assert_frame_equal(data, original)

    for tool_key, record in expected["tools"].items():
        tool_data = (
            utc_data
            if tool_key == "universal_trend_classifier"
            else data
        )
        result = calculate_financial_tool(
            tool_key,
            tool_data,
            record["parameters"],
            bindings=record["bindings"],
        )
        frame = result.to_frame()
        assert result.tool_key == tool_key
        assert dict(result.parameters) == record["parameters"]
        assert dict(result.bindings) == record["bindings"]
        assert result.output_names == tuple(record["output_names"])
        assert frame.index.equals(data.index)
        assert frame["ts_ms"].equals(data["ts_ms"])

        runtime_types = FinancialToolCalculationResult.runtime_output_types(
            tool_key=result.tool_key,
            parameters=result.parameters,
            bindings=result.bindings,
            output_names=result.output_names,
        )
        runtime_by_name = dict(zip(result.output_names, runtime_types, strict=True))
        for output_name, expected_values in record.get("outputs", {}).items():
            actual = frame[output_name]
            runtime_type = runtime_by_name[output_name]
            if runtime_type == "numeric":
                expected_array = np.asarray(
                    [
                        np.nan if value is None else float(value)
                        for value in expected_values
                    ],
                    dtype="float64",
                )
                assert actual.dtype == np.dtype("float32")
                actual_array = actual.to_numpy(dtype="float64", copy=False)
                actual_nan = np.isnan(actual_array)
                expected_nan = np.isnan(expected_array)
                np.testing.assert_array_equal(
                    actual_nan,
                    expected_nan,
                    err_msg=f"{tool_key}.{output_name} NaN mask",
                )
                valid = ~actual_nan
                np.testing.assert_allclose(
                    actual_array[valid],
                    expected_array[valid],
                    rtol=CONTINUOUS_RTOL,
                    atol=CONTINUOUS_ATOL,
                    err_msg=f"{tool_key}.{output_name} continuous values",
                )
            elif runtime_type == "boolean":
                assert actual.dtype == np.dtype("bool")
                assert actual.tolist() == expected_values
            else:
                assert runtime_type == "categorical"
                expected_dtype = (
                    FinancialToolCalculationResult.categorical_output_dtype(
                        tool_key=tool_key,
                        output_name=output_name,
                    )
                )
                assert isinstance(actual.dtype, pd.CategoricalDtype)
                assert tuple(actual.cat.categories) == tuple(expected_dtype.categories)
                assert actual.cat.ordered is expected_dtype.ordered
                assert not actual.isna().any()
                assert actual.tolist() == expected_values
        _assert_nested(result.analysis, record.get("analysis", {}))
