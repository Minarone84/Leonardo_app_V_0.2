from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from leonardo.financial_tools import calculate_financial_tool


FIXTURES = Path(__file__).with_name("fixtures")


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
        assert np.isclose(float(actual), expected, rtol=1e-6, atol=1e-6, equal_nan=True)
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

    for tool_key, record in expected["tools"].items():
        result = calculate_financial_tool(
            tool_key,
            data,
            record["parameters"],
            bindings=record["bindings"],
        )
        frame = result.to_frame()
        assert result.tool_key == tool_key
        assert result.output_names == tuple(record["output_names"])
        assert frame.index.equals(data.index)
        assert frame["ts_ms"].equals(data["ts_ms"])

        for output_name, expected_values in record.get("outputs", {}).items():
            actual = frame[output_name]
            non_null = next((value for value in expected_values if value is not None), None)
            if isinstance(non_null, (bool, str)):
                assert actual.tolist() == expected_values
            else:
                np.testing.assert_allclose(
                    actual.to_numpy(dtype="float64"),
                    np.asarray(expected_values, dtype="float64"),
                    rtol=1e-6,
                    atol=1e-6,
                    equal_nan=True,
                    err_msg=f"{tool_key}.{output_name}",
                )
        _assert_nested(result.analysis, record.get("analysis", {}))
