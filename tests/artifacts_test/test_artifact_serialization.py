from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from leonardo.artifacts.models import ArtifactValidationError
from leonardo.artifacts.serialization import (
    decode_canonical_json,
    decode_analysis_json,
    decode_values_csv,
    encode_analysis_json,
    encode_values_csv,
    sha256_bytes,
)
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    resolve_output_names,
    resolve_parameters,
)


FIXTURES = Path(__file__).with_name("fixtures")


def _runtime(
    tool_key: str,
    parameters: dict[str, object] | None = None,
    bindings: dict[str, object] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    resolved = resolve_parameters(tool_key, parameters)
    canonical_bindings = dict(bindings or {})
    naming = dict(resolved)
    naming.update(canonical_bindings)
    names = resolve_output_names(tool_key, naming)
    types = FinancialToolCalculationResult.runtime_output_types(
        tool_key=tool_key,
        parameters=resolved,
        bindings=canonical_bindings,
        output_names=names,
    )
    return names, types


def test_canonical_values_fixture_is_exact_lf_csv() -> None:
    frame = pd.DataFrame(
        {"ts_ms": [1_700_000_000_000, 1_700_000_060_000, 1_700_000_120_000, 1_700_000_180_000],
         "sma_3": np.asarray([np.nan, np.nan, 101.0, 102.0], dtype="float32")}
    )
    names, runtime_types = _runtime("sma", {"period": 3})
    encoded = encode_values_csv(frame, names, runtime_types)
    expected = (FIXTURES / "task_1016_canonical_values.csv").read_bytes()
    assert encoded == expected
    assert b"\r\n" not in encoded
    assert sha256_bytes(encoded) == "2a3d4a028860e79e7ac965834cde3522b25b9a858e2000d680b59869765f19d7"
    loaded = decode_values_csv(encoded, names, runtime_types)
    assert isinstance(loaded.index, pd.RangeIndex)
    assert loaded.sma_3.dtype == np.dtype("float32")
    np.testing.assert_allclose(loaded.sma_3, frame.sma_3, equal_nan=True)


def test_boolean_and_categorical_values_round_trip_exactly() -> None:
    utc_names, utc_types = _runtime("universal_trend_classifier")
    utc = pd.DataFrame({"ts_ms": [1, 2]})
    for name, runtime_type in zip(utc_names, utc_types, strict=True):
        utc[name] = [False, True] if runtime_type == "boolean" else np.asarray([1.25, np.nan], dtype="float32")
    utc_loaded = decode_values_csv(encode_values_csv(utc, utc_names, utc_types), utc_names, utc_types)
    for name, runtime_type in zip(utc_names, utc_types, strict=True):
        if runtime_type == "boolean":
            assert utc_loaded[name].dtype == bool
            assert utc_loaded[name].tolist() == [False, True]

    hck_names, hck_types = _runtime("hck")
    hck = pd.DataFrame({"ts_ms": [1, 2], "fast_vwap": np.asarray([1, 2], dtype="float32"),
                        "slow_vwap": np.asarray([2, 1], dtype="float32"), "vwap_color": ["red", "green"]})
    loaded = decode_values_csv(encode_values_csv(hck, hck_names, hck_types), hck_names, hck_types)
    assert loaded.vwap_color.tolist() == ["red", "green"]


def test_dynamic_binning_analysis_round_trips_recursively() -> None:
    analysis = {"steps": {"close": 0.125}, "rows": [{"label": "AB0", "value": 1}], "active": True}
    encoded = encode_analysis_json(analysis)
    assert encoded.endswith(b"\n")
    assert decode_analysis_json(encoded) == analysis


@pytest.mark.parametrize(
    "payload",
    (
        b"ts_ms,sma_3\n1,not-a-number\n",
        b"ts_ms,wrong\n1,1\n",
        b"ts_ms,sma_3\n2,1\n1,2\n",
        b"ts_ms,sma_3\n",
    ),
)
def test_corrupt_values_csv_is_rejected(payload: bytes) -> None:
    with pytest.raises(ArtifactValidationError):
        decode_values_csv(payload, *_runtime("sma", {"period": 3}))


def test_noncanonical_values_csv_bytes_are_rejected() -> None:
    canonical = (FIXTURES / "task_1016_canonical_values.csv").read_bytes()
    variants = (
        canonical.replace(b"\n", b"\r\n"),
        canonical[:-1],
        canonical.replace(b"ts_ms,sma_3", b'"ts_ms",sma_3'),
        canonical.replace(b",101\n", b",101.0\n"),
        canonical.replace(b",102\n", b", 102\n"),
    )
    for payload in variants:
        with pytest.raises(ArtifactValidationError, match="bytes must be canonical"):
            decode_values_csv(payload, *_runtime("sma", {"period": 3}))


def test_integer_valued_float_timestamps_encode_as_decimal_integers() -> None:
    names, runtime_types = _runtime("sma", {"period": 3})
    frame = pd.DataFrame(
        {
            "ts_ms": np.asarray([1.0, 2.0], dtype="float64"),
            "sma_3": np.asarray([1.0, 2.0], dtype="float32"),
        }
    )
    encoded = encode_values_csv(frame, names, runtime_types)
    assert encoded == b"ts_ms,sma_3\n1,1\n2,2\n"
    loaded = decode_values_csv(encoded, names, runtime_types)
    assert loaded.ts_ms.dtype == np.dtype("int64")
    assert loaded.ts_ms.tolist() == [1, 2]


@pytest.mark.parametrize(
    "timestamp",
    (True, np.bool_(False), "1", float("nan"), float("inf"), 1.5, object()),
)
def test_invalid_timestamp_scalars_are_rejected(timestamp: object) -> None:
    names, runtime_types = _runtime("sma", {"period": 3})
    frame = pd.DataFrame(
        {"ts_ms": [timestamp], "sma_3": np.asarray([1.0], dtype="float32")}
    )
    with pytest.raises(ArtifactValidationError, match="ts_ms"):
        encode_values_csv(frame, names, runtime_types)


def test_analysis_rejects_nonfinite_and_nonobject_payloads() -> None:
    with pytest.raises(ArtifactValidationError):
        encode_analysis_json({"bad": float("nan")})
    with pytest.raises(ArtifactValidationError):
        decode_analysis_json(json.dumps([1, 2]).encode("utf-8"))


def test_numeric_serialization_rejects_python_and_numpy_booleans() -> None:
    names, runtime_types = _runtime("sma", {"period": 3})
    for value in (True, np.bool_(False)):
        frame = pd.DataFrame({"ts_ms": [1], "sma_3": [value]})
        with pytest.raises(ArtifactValidationError, match="not booleans"):
            encode_values_csv(frame, names, runtime_types)


@pytest.mark.parametrize(
    "payload",
    (
        b'{"a":1}\n',
        b'{\n  "a": 1\n}',
        b'{\n  "a": 1\n}\n\n',
        b'{\n    "a": 1\n}\n',
        b'{\n  "b": 2,\n  "a": 1\n}\n',
    ),
)
def test_persisted_json_requires_exact_canonical_bytes(payload: bytes) -> None:
    with pytest.raises(ArtifactValidationError, match="bytes must be canonical"):
        decode_canonical_json(payload, context="test")
