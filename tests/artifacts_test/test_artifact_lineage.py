from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import leonardo.artifacts.service as service_module
from leonardo.artifacts import (
    ArtifactLineageError,
    ArtifactMetadataV1,
    ArtifactService,
    ArtifactSourceRefV1,
    ArtifactValidationError,
)
from leonardo.artifacts.identity import artifact_identity_payload, canonical_json_identity_bytes
from leonardo.artifacts.serialization import encode_canonical_json, encode_values_csv, sha256_bytes
from leonardo.data import MarketId
from leonardo.financial_tools import FinancialToolCalculationResult, calculate_financial_tool
from leonardo.ohlcv.store import OHLCVStore

from test_artifact_service_roundtrip import _accepted_dataset


def test_missing_sidecar_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    OHLCVStore(tmp_path).sidecar_path(market).unlink()

    with pytest.raises(ArtifactLineageError, match="sidecar is missing"):
        ArtifactService(tmp_path).save_calculation(
            market, calculate_financial_tool("sma", data, {"period": 3})
        )


def test_nonaccepted_validation_status_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    store = OHLCVStore(tmp_path)
    store.write(
        market,
        store.read(market),
        source="test",
        persistence_status="committed",
    )

    with pytest.raises(ArtifactLineageError, match="not accepted"):
        ArtifactService(tmp_path).save_calculation(
            market, calculate_financial_tool("sma", data, {"period": 3})
        )


def test_csv_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    with OHLCVStore(tmp_path).csv_path(market).open("ab") as handle:
        handle.write(b"\n")

    with pytest.raises(ArtifactLineageError, match="hash does not match"):
        ArtifactService(tmp_path).save_calculation(
            market, calculate_financial_tool("sma", data, {"period": 3})
        )


def test_file_change_during_capture_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    market, data = _accepted_dataset(tmp_path)
    csv_path = OHLCVStore(tmp_path).csv_path(market)
    original = service_module.capture_file_state
    first_capture = True

    def unstable_capture(path: Path):
        nonlocal first_capture
        state = original(path)
        if first_capture and path == csv_path:
            first_capture = False
            with csv_path.open("ab") as handle:
                handle.write(b"\n")
        return state

    monkeypatch.setattr(service_module, "capture_file_state", unstable_capture)
    with pytest.raises(ArtifactLineageError, match="changed during lineage capture"):
        ArtifactService(tmp_path).save_calculation(
            market, calculate_financial_tool("sma", data, {"period": 3})
        )


def test_result_coverage_mismatch_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    partial = calculate_financial_tool("sma", data.iloc[:-1], {"period": 3})

    with pytest.raises(ArtifactLineageError, match="full OHLCV source"):
        ArtifactService(tmp_path).save_calculation(market, partial)


def test_same_market_source_artifact_is_accepted_and_current(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "sma_3")
    saved = service.save_calculation(
        market,
        calculate_financial_tool("ema", data, {"period": 3}),
        source_artifacts=(ref,),
    )

    assert saved.metadata.recipe.source_artifacts == (ref,)
    assert service.validate_artifact_current(
        market, "indicator", "ema", saved.metadata.artifact_id
    ).valid


def test_another_market_source_artifact_is_rejected(tmp_path: Path) -> None:
    first_market, first_data = _accepted_dataset(tmp_path)
    second_market = MarketId("bybit", "linear", "ETHUSDT", "1m")
    _, second_data = _accepted_dataset(tmp_path, market=second_market)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        first_market, calculate_financial_tool("sma", first_data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "sma_3")

    with pytest.raises(ArtifactLineageError, match="current MarketId"):
        service.save_recipe_from_result(
            second_market,
            calculate_financial_tool("ema", second_data, {"period": 3}),
            source_artifacts=(ref,),
        )


def test_missing_source_output_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    ref = ArtifactSourceRefV1("trend", source.metadata.artifact_id, "missing")

    with pytest.raises(ArtifactLineageError, match="has no output"):
        service.save_recipe_from_result(
            market,
            calculate_financial_tool("ema", data, {"period": 3}),
            source_artifacts=(ref,),
        )


def test_stale_source_artifact_is_rejected(tmp_path: Path) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    source = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    _accepted_dataset(tmp_path, rows=97)

    with pytest.raises(ArtifactLineageError, match="stale OHLCV lineage"):
        service.validate_artifact_current(
            market, "indicator", "sma", source.metadata.artifact_id
        )


def test_source_artifact_cycle_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    current, current_timestamps = service._capture_accepted_ohlcv(market)
    a_id = "a" * 64
    b_id = "b" * 64
    timeline_frame = data[["ts_ms"]].copy(deep=True)
    loaded_a = SimpleNamespace(
        frame=timeline_frame,
        metadata=SimpleNamespace(
            artifact_id=a_id,
            source_ohlcv=current,
            recipe=SimpleNamespace(
                output_names=("a_output",),
                source_artifacts=(ArtifactSourceRefV1("b", b_id, "b_output"),),
            ),
        )
    )
    loaded_b = SimpleNamespace(
        frame=timeline_frame,
        metadata=SimpleNamespace(
            artifact_id=b_id,
            source_ohlcv=current,
            recipe=SimpleNamespace(
                output_names=("b_output",),
                source_artifacts=(ArtifactSourceRefV1("a", a_id, "a_output"),),
            ),
        )
    )
    sources = {a_id: loaded_a, b_id: loaded_b}
    monkeypatch.setattr(service, "_load_source_artifact", lambda _, artifact_id: sources[artifact_id])

    with pytest.raises(ArtifactLineageError, match="cycle"):
        service._validate_loaded_lineage(
            market, loaded_a, current, current_timestamps, visiting=set()
        )


def test_partial_artifact_is_rejected_by_model_load_catalog_and_current_validation(
    tmp_path: Path,
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    partial = calculate_financial_tool("sma", data.iloc[:-1], {"period": 3})
    values = encode_values_csv(
        partial.to_frame(),
        partial.output_names,
        FinancialToolCalculationResult.runtime_output_types(
            tool_key=partial.tool_key,
            parameters=partial.parameters,
            bindings=partial.bindings,
            output_names=partial.output_names,
        ),
    )
    metadata = saved.metadata.to_dict()
    metadata["row_count"] = partial.row_count
    metadata["first_timestamp_ms"] = partial.first_timestamp_ms
    metadata["last_timestamp_ms"] = partial.last_timestamp_ms
    metadata["values_sha256"] = sha256_bytes(values)
    identity = artifact_identity_payload(
        recipe_id=saved.metadata.recipe.recipe_id,
        source_ohlcv=saved.metadata.source_ohlcv.to_dict(),
        source_artifacts=(),
        row_count=partial.row_count,
        first_timestamp_ms=partial.first_timestamp_ms,
        last_timestamp_ms=partial.last_timestamp_ms,
        values_sha256=sha256_bytes(values),
        analysis_sha256=None,
    )
    partial_id = hashlib.sha256(canonical_json_identity_bytes(identity)).hexdigest()
    metadata["artifact_id"] = partial_id

    with pytest.raises(ArtifactValidationError, match="coverage"):
        ArtifactMetadataV1.from_dict(metadata)

    directory = service._store.artifact_dir(market, "indicator", "sma", partial_id)
    directory.mkdir()
    (directory / "values.csv").write_bytes(values)
    (directory / "artifact.meta.json").write_bytes(encode_canonical_json(metadata))

    with pytest.raises(ArtifactValidationError, match="coverage"):
        service.load_artifact(market, "indicator", "sma", partial_id)
    summary = next(item for item in service.list_artifacts(market) if item.artifact_id == partial_id)
    assert summary.valid is False
    assert "coverage" in str(summary.rejection_reason)
    with pytest.raises(ArtifactValidationError, match="coverage"):
        service.validate_artifact_current(market, "indicator", "sma", partial_id)


def test_middle_timestamp_forgery_loads_but_fails_current_timeline_validation(
    tmp_path: Path,
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    forged = service.load_artifact(
        market, "indicator", "sma", saved.metadata.artifact_id
    ).frame
    middle = len(forged) // 2
    forged.loc[middle, "ts_ms"] += 1
    runtime_types = FinancialToolCalculationResult.runtime_output_types(
        tool_key=saved.metadata.recipe.tool_key,
        parameters=saved.metadata.recipe.parameters,
        bindings=saved.metadata.recipe.bindings,
        output_names=saved.metadata.recipe.output_names,
    )
    values = encode_values_csv(forged, saved.metadata.recipe.output_names, runtime_types)
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
    directory = service._store.artifact_dir(market, "indicator", "sma", artifact_id)
    directory.mkdir()
    (directory / "values.csv").write_bytes(values)
    (directory / "artifact.meta.json").write_bytes(encode_canonical_json(metadata))

    loaded = service.load_artifact(market, "indicator", "sma", artifact_id)
    assert int(loaded.frame.ts_ms.iloc[middle]) == int(data.ts_ms.iloc[middle]) + 1
    with pytest.raises(ArtifactLineageError, match="timeline"):
        service.validate_artifact_current(market, "indicator", "sma", artifact_id)


def test_current_validation_rechecks_source_after_artifact_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, data = _accepted_dataset(tmp_path)
    service = ArtifactService(tmp_path)
    saved = service.save_calculation(
        market, calculate_financial_tool("sma", data, {"period": 3})
    )
    original_load = service.load_artifact

    def racing_load(*args: object, **kwargs: object):
        loaded = original_load(*args, **kwargs)  # type: ignore[arg-type]
        _accepted_dataset(tmp_path, rows=97)
        return loaded

    monkeypatch.setattr(service, "load_artifact", racing_load)
    with pytest.raises(ArtifactLineageError, match="during current validation"):
        service.validate_artifact_current(
            market, "indicator", "sma", saved.metadata.artifact_id
        )
