from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd

import pytest

from leonardo.artifacts import ArtifactService, ArtifactValidationError
from leonardo.artifacts.identity import artifact_identity_payload, canonical_json_identity_bytes
from leonardo.artifacts.serialization import encode_canonical_json, sha256_bytes
from leonardo.data import MarketId
from leonardo.financial_tools import FinancialToolCalculationResult, calculate_financial_tool
from leonardo.ohlcv.store import Candle, OHLCVStore


def _frame(rows: int = 96) -> pd.DataFrame:
    x = np.arange(rows, dtype="float64")
    close = 100.0 + x * 0.1 + np.sin(x / 5.0)
    return pd.DataFrame(
        {
            "ts_ms": 1_700_000_000_000 + x.astype("int64") * 60_000,
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000.0 + x * 2.0,
        }
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted_dataset(root: Path, *, market: MarketId | None = None, rows: int = 96) -> tuple[MarketId, pd.DataFrame]:
    market = market or MarketId("bybit", "linear", "BTCUSDT", "1m")
    frame = _frame(rows)
    candles = [
        Candle(int(row.ts_ms), float(row.open), float(row.high), float(row.low), float(row.close), float(row.volume))
        for row in frame.itertuples(index=False)
    ]
    store = OHLCVStore(root)
    store.write(market, candles, source="test", persistence_status="committed")
    csv_path = store.csv_path(market)
    sidecar_path = store.sidecar_path(market)
    csv_stat = csv_path.stat()
    sidecar_stat = sidecar_path.stat()
    store.publish_validation(
        market,
        expected_csv_size=csv_stat.st_size,
        expected_csv_mtime_ns=csv_stat.st_mtime_ns,
        expected_csv_sha256=_sha(csv_path),
        expected_sidecar_size=sidecar_stat.st_size,
        expected_sidecar_mtime_ns=sidecar_stat.st_mtime_ns,
        expected_sidecar_sha256=_sha(sidecar_path),
        status="ok",
        row_count=len(frame),
        first_timestamp_ms=int(frame.ts_ms.iloc[0]),
        last_timestamp_ms=int(frame.ts_ms.iloc[-1]),
        warnings=(),
        issue_codes=(),
        error_count=0,
        warning_count=0,
        validator="task-1016-test",
    )
    return market, frame


def test_numeric_artifact_and_recipe_round_trip(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("sma", data, {"period": 3})
    original = result.to_frame()
    service = ArtifactService(tmp_path)

    saved = service.save_calculation(market, result, display_name="SMA 3")
    loaded = service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)
    recipe = service.load_recipe(market, "indicator", "sma", saved.metadata.recipe.recipe_id)

    assert recipe == saved.metadata.recipe
    assert loaded.metadata == saved.metadata
    pd.testing.assert_frame_equal(loaded.frame, original.reset_index(drop=True))
    assert loaded.analysis == {}
    pd.testing.assert_frame_equal(result.to_frame(), original)
    assert service.list_artifacts(market, kind="indicator", tool_key="sma")[0].artifact_id == saved.metadata.artifact_id
    assert service.list_recipes(market, kind="indicator", tool_key="sma")[0].recipe_id == recipe.recipe_id


def test_hck_categorical_round_trip(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("hck", data)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(
        market, "indicator", "hck", saved.metadata.artifact_id
    )
    expected_dtype = FinancialToolCalculationResult.categorical_output_dtype(
        tool_key="hck",
        output_name="vwap_color",
    )
    pd.testing.assert_frame_equal(
        loaded.frame,
        result.to_frame().reset_index(drop=True),
    )
    assert loaded.frame.vwap_color.dtype == expected_dtype
    assert tuple(loaded.frame.vwap_color.cat.categories) == (
        "red",
        "silver",
        "green",
    )
    assert loaded.frame.vwap_color.cat.ordered is False
    assert loaded.frame.fast_vwap.dtype == np.dtype("float32")


def test_strategy_categorical_round_trip(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path, rows=420)
    result = calculate_financial_tool("strategy", data)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(
        market, "indicator", "strategy", saved.metadata.artifact_id
    )
    expected_dtype = FinancialToolCalculationResult.categorical_output_dtype(
        tool_key="strategy",
        output_name="st_vwap_color",
    )
    pd.testing.assert_frame_equal(
        loaded.frame,
        result.to_frame().reset_index(drop=True),
    )
    assert loaded.frame.st_vwap_color.dtype == expected_dtype
    assert tuple(loaded.frame.st_vwap_color.cat.categories) == (
        "red",
        "silver",
        "green",
    )
    assert loaded.frame.st_vwap_color.cat.ordered is False
    assert all(
        loaded.frame[name].dtype == np.dtype("float32")
        for name in result.output_names
        if name != "st_vwap_color"
    )


def test_utc_boolean_and_numeric_round_trip(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    original_data = data.copy(deep=True)
    dependency_names = (
        "peak_fractal_3",
        "trough_fractal_3",
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_7",
        "trough_fractal_7",
        "peak_fractal_9",
        "trough_fractal_9",
        "peak_fractal_11",
        "trough_fractal_11",
    )
    dependencies = calculate_financial_tool("peaks_troughs", data)
    assert dependencies.output_names == dependency_names

    utc_data = data.copy(deep=True)
    dependency_frame = dependencies.to_frame()
    for output_name in dependencies.output_names:
        utc_data[output_name] = dependency_frame[output_name].to_numpy(copy=True)

    pd.testing.assert_frame_equal(data, original_data)
    pd.testing.assert_frame_equal(utc_data.loc[:, data.columns], original_data)
    assert utc_data.index.equals(original_data.index)
    assert len(utc_data) == len(original_data)

    result = calculate_financial_tool(
        "universal_trend_classifier",
        utc_data,
        {
            "peak_column": "peak_fractal_5",
            "trough_column": "trough_fractal_5",
        },
    )
    assert result.tool_key == "universal_trend_classifier"
    assert result.parameters["peak_column"] == "peak_fractal_5"
    assert result.parameters["trough_column"] == "trough_fractal_5"
    assert result.parameters["trend_fractal_window"] == 5
    assert result.parameters["range_fractal_window"] == 3
    assert len(result.output_names) == 27
    assert not set(dependency_names).intersection(result.output_names)
    assert not set(dependency_names).intersection(result.to_frame().columns)
    original_result = result.to_frame()

    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(
        market, "indicator", "universal_trend_classifier", saved.metadata.artifact_id
    )
    recipe = service.load_recipe(
        market,
        "indicator",
        "universal_trend_classifier",
        saved.metadata.recipe.recipe_id,
    )

    assert recipe == saved.metadata.recipe
    assert recipe.parameters["peak_column"] == "peak_fractal_5"
    assert recipe.parameters["trough_column"] == "trough_fractal_5"
    assert recipe.parameters["trend_fractal_window"] == 5
    assert recipe.parameters["range_fractal_window"] == 3
    assert loaded.metadata == saved.metadata
    assert loaded.metadata.recipe.recipe_id == saved.metadata.recipe.recipe_id
    assert not set(dependency_names).intersection(loaded.frame.columns)
    pd.testing.assert_frame_equal(
        loaded.frame,
        result.to_frame().reset_index(drop=True),
    )
    assert loaded.frame.horizontal_range.dtype == bool
    assert loaded.frame.hor_upper.dtype == np.dtype("float32")
    pd.testing.assert_frame_equal(result.to_frame(), original_result)
    pd.testing.assert_frame_equal(data, original_data)


def test_dynamic_binning_analysis_round_trip_and_tree(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    result = calculate_financial_tool("dynamic_binning", data)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(market, "construct", "dynamic_binning", saved.metadata.artifact_id)
    assert loaded.analysis == result.analysis
    assert tuple(loaded.frame.columns) == ("ts_ms",)
    assert {path.name for path in saved.path.iterdir()} == {
        "values.csv", "analysis.json", "artifact.meta.json"
    }


def test_standalone_recipe_is_idempotent_without_ohlcv(tmp_path: Path) -> None:
    data = _frame(12)
    result = calculate_financial_tool("ema", data, {"period": 3})
    service = ArtifactService(tmp_path)
    market = MarketId("bybit", "linear", "BTCUSDT", "1m")
    first = service.save_recipe_from_result(market, result)
    second = service.save_recipe_from_result(market, result)
    assert first.created is True
    assert second.created is False
    assert second.recipe == first.recipe


def _unsafe_configuration_result(
    result: FinancialToolCalculationResult,
    *,
    parameters: dict[str, object] | None = None,
    bindings: dict[str, object] | None = None,
    frame: pd.DataFrame | None = None,
) -> FinancialToolCalculationResult:
    unsafe = object.__new__(FinancialToolCalculationResult)
    object.__setattr__(unsafe, "tool_key", result.tool_key)
    object.__setattr__(unsafe, "kind", result.kind)
    object.__setattr__(
        unsafe, "parameters", MappingProxyType(dict(result.parameters if parameters is None else parameters))
    )
    object.__setattr__(
        unsafe, "bindings", MappingProxyType(dict(result.bindings if bindings is None else bindings))
    )
    object.__setattr__(unsafe, "output_names", result.output_names)
    object.__setattr__(unsafe, "row_count", result.row_count)
    object.__setattr__(unsafe, "first_timestamp_ms", result.first_timestamp_ms)
    object.__setattr__(unsafe, "last_timestamp_ms", result.last_timestamp_ms)
    object.__setattr__(unsafe, "_frame", result.to_frame() if frame is None else frame)
    object.__setattr__(unsafe, "_analysis", result.analysis)
    return unsafe


def test_service_rejects_invalid_result_configuration_before_persistence(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    derivative = calculate_financial_tool(
        "derivative", data, {"order": 1}, bindings={"source": "close"}
    )
    invalid_derivative = _unsafe_configuration_result(
        derivative, bindings={"source": " close "}
    )
    dynamic = calculate_financial_tool("dynamic_binning", data, {"window": 2})
    parameters = dict(dynamic.parameters)
    parameters["window"] = 1
    invalid_dynamic = _unsafe_configuration_result(dynamic, parameters=parameters)

    for result in (invalid_derivative, invalid_dynamic):
        with pytest.raises(ArtifactValidationError, match="configuration is invalid"):
            service.save_calculation(market, result)

    assert service.list_recipes(market) == ()
    assert service.list_artifacts(market) == ()


def test_service_rejects_forged_runtime_outputs_before_persistence(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    sma = calculate_financial_tool("sma", data, {"period": 3})
    numeric_text = sma.to_frame()
    numeric_text["sma_3"] = numeric_text["sma_3"].map(str).astype(object)
    hck = calculate_financial_tool("hck", data)
    bad_color = hck.to_frame()
    bad_color_values = bad_color["vwap_color"].astype(object).tolist()
    bad_color_values[0] = "blue"
    bad_color["vwap_color"] = pd.Series(
        pd.Categorical(
            bad_color_values,
            categories=("red", "silver", "green", "blue"),
            ordered=False,
        ),
        index=bad_color.index,
    )

    for result in (
        _unsafe_configuration_result(sma, frame=numeric_text),
        _unsafe_configuration_result(hck, frame=bad_color),
    ):
        with pytest.raises(ArtifactValidationError):
            service.save_calculation(market, result)

    assert service.list_recipes(market) == ()
    assert service.list_artifacts(market) == ()


def test_recipe_and_metadata_load_reject_noncanonical_json_bytes(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    recipe_path = saved.path.parents[3] / "recipes" / "indicator" / "sma" / (
        saved.metadata.recipe.recipe_id + ".json"
    )
    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe_path.write_bytes(json.dumps(recipe_payload, separators=(",", ":")).encode("utf-8"))
    with pytest.raises(ArtifactValidationError, match="bytes must be canonical"):
        service.load_recipe(market, "indicator", "sma", saved.metadata.recipe.recipe_id)

    metadata_path = saved.path / "artifact.meta.json"
    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata_path.write_bytes(json.dumps(metadata_payload, separators=(",", ":")).encode("utf-8"))
    with pytest.raises(ArtifactValidationError, match="bytes must be canonical"):
        service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)


def test_artifact_payload_inventory_is_exact(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    (saved.path / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(ArtifactValidationError, match="payload inventory"):
        service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)
    (saved.path / "unexpected.bin").unlink()
    (saved.path / "unexpected").mkdir()
    with pytest.raises(ArtifactValidationError, match="payload inventory"):
        service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)


def test_artifact_analysis_pairing_is_exact(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    ordinary = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    (ordinary.path / "analysis.json").write_bytes(b"{}\n")
    with pytest.raises(ArtifactValidationError, match="analysis file pairing"):
        service.load_artifact(market, "indicator", "sma", ordinary.metadata.artifact_id)

    dynamic = service.save_calculation(market, calculate_financial_tool("dynamic_binning", data))
    (dynamic.path / "analysis.json").unlink()
    with pytest.raises(ArtifactValidationError, match="analysis file pairing"):
        service.load_artifact(
            market, "construct", "dynamic_binning", dynamic.metadata.artifact_id
        )


def test_braids_numeric_state_round_trips_and_validates_current(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    result = calculate_financial_tool(
        "braids", data, {"fast": "open", "mid": "close", "slow": "volume"}
    )
    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(market, "construct", "braids", saved.metadata.artifact_id)

    pd.testing.assert_frame_equal(loaded.frame, result.to_frame().reset_index(drop=True))
    assert all(loaded.frame[name].dtype == np.dtype("float32") for name in result.output_names)
    assert service.validate_artifact_current(
        market, "construct", "braids", saved.metadata.artifact_id
    ).valid


def test_load_rejects_crlf_values_with_recomputed_hash_and_identity(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    crlf_values = (saved.path / "values.csv").read_bytes().replace(b"\n", b"\r\n")
    metadata = saved.metadata.to_dict()
    values_sha256 = sha256_bytes(crlf_values)
    metadata["values_sha256"] = values_sha256
    identity = artifact_identity_payload(
        recipe_id=saved.metadata.recipe.recipe_id,
        source_ohlcv=saved.metadata.source_ohlcv.to_dict(),
        source_artifacts=saved.metadata.recipe.source_artifacts,
        row_count=saved.metadata.row_count,
        first_timestamp_ms=saved.metadata.first_timestamp_ms,
        last_timestamp_ms=saved.metadata.last_timestamp_ms,
        values_sha256=values_sha256,
        analysis_sha256=None,
    )
    artifact_id = hashlib.sha256(canonical_json_identity_bytes(identity)).hexdigest()
    metadata["artifact_id"] = artifact_id
    directory = service._store.artifact_dir(market, "indicator", "sma", artifact_id)
    directory.mkdir()
    (directory / "values.csv").write_bytes(crlf_values)
    (directory / "artifact.meta.json").write_bytes(encode_canonical_json(metadata))

    with pytest.raises(ArtifactValidationError, match="values.csv bytes must be canonical"):
        service.load_artifact(market, "indicator", "sma", artifact_id)


def test_load_rejects_canonical_csv_with_invalid_hck_color_domain(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(market, calculate_financial_tool("hck", data))
    values = (saved.path / "values.csv").read_bytes()
    for accepted in (b"red", b"silver", b"green"):
        if accepted in values:
            values = values.replace(accepted, b"blue", 1)
            break
    else:
        raise AssertionError("HCK fixture produced no color state")
    metadata = saved.metadata.to_dict()
    values_sha256 = sha256_bytes(values)
    metadata["values_sha256"] = values_sha256
    identity = artifact_identity_payload(
        recipe_id=saved.metadata.recipe.recipe_id,
        source_ohlcv=saved.metadata.source_ohlcv.to_dict(),
        source_artifacts=(),
        row_count=saved.metadata.row_count,
        first_timestamp_ms=saved.metadata.first_timestamp_ms,
        last_timestamp_ms=saved.metadata.last_timestamp_ms,
        values_sha256=values_sha256,
        analysis_sha256=None,
    )
    artifact_id = hashlib.sha256(canonical_json_identity_bytes(identity)).hexdigest()
    metadata["artifact_id"] = artifact_id
    directory = service._store.artifact_dir(market, "indicator", "hck", artifact_id)
    directory.mkdir()
    (directory / "values.csv").write_bytes(values)
    (directory / "artifact.meta.json").write_bytes(encode_canonical_json(metadata))

    with pytest.raises(ArtifactValidationError, match="runtime outputs are invalid"):
        service.load_artifact(market, "indicator", "hck", artifact_id)


def test_integer_valued_float_timestamps_save_load_and_validate_current(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    floating = data.copy(deep=True)
    floating["ts_ms"] = floating["ts_ms"].astype("float64")
    result = calculate_financial_tool("sma", floating, {"period": 3})
    assert result.to_frame().ts_ms.dtype == np.dtype("float64")
    service = ArtifactService(tmp_path)

    saved = service.save_calculation(market, result)
    loaded = service.load_artifact(market, "indicator", "sma", saved.metadata.artifact_id)
    persisted = (saved.path / "values.csv").read_text(encoding="utf-8")

    assert ".0," not in persisted
    assert loaded.frame.ts_ms.dtype == np.dtype("int64")
    assert loaded.frame.ts_ms.tolist() == data.ts_ms.tolist()
    assert service.validate_artifact_current(
        market, "indicator", "sma", saved.metadata.artifact_id
    ).valid


def test_invalid_persisted_payloads_leave_no_recipe_or_artifact(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    valid = calculate_financial_tool("sma", data, {"period": 3})
    invalid_analysis = FinancialToolCalculationResult(
        tool_key=valid.tool_key,
        kind=valid.kind,
        parameters=valid.parameters,
        bindings=valid.bindings,
        output_names=valid.output_names,
        frame=valid.to_frame(),
        analysis={"bad": float("inf")},
    )
    invalid_timestamps = valid.to_frame()
    invalid_timestamps["ts_ms"] = invalid_timestamps["ts_ms"].map(str).astype(object)

    with pytest.raises(ArtifactValidationError):
        service.save_calculation(market, invalid_analysis)
    with pytest.raises(ArtifactValidationError, match="ts_ms"):
        service.save_calculation(
            market, _unsafe_configuration_result(valid, frame=invalid_timestamps)
        )

    assert service.list_recipes(market) == ()
    assert service.list_artifacts(market) == ()
