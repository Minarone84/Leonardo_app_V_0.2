import ast
import csv
import inspect
import json
from pathlib import Path

import pytest

import leonardo.download_data.bybit_ohlcv as bybit_ohlcv
import leonardo.download_data.ohlcv_storage_writer as ohlcv_storage_writer
import leonardo.download_data.smoke_execution as smoke_execution
from leonardo.contracts.download_data_boundary import DOWNLOAD_DATA_ARTIFACT_ID
from leonardo.contracts.download_data_execution import (
    DownloadDataExecutionMode,
    DownloadDataExecutionStatus,
    DownloadDataNormalizedCandle,
    DownloadDataProviderPageRequest,
    DownloadDataStorageWriteRequest,
    DownloadDataStorageWriteStatus,
)
from leonardo.download_data.bybit_ohlcv import (
    BYBIT_KLINE_ENDPOINT,
    build_bybit_kline_request,
    normalize_bybit_kline_response,
)
from leonardo.download_data.ohlcv_storage_writer import write_ohlcv_smoke_new_file
from leonardo.download_data.smoke_execution import run_bybit_ohlcv_smoke_slice


def test_bybit_kline_request_params_are_explicit_for_smoke_target() -> None:
    request = _page_request()
    descriptor = build_bybit_kline_request(request)
    params = descriptor["params"]

    assert descriptor["method"] == "GET"
    assert descriptor["endpoint"] == BYBIT_KLINE_ENDPOINT
    assert params["category"] == "spot"
    assert params["symbol"] == "BTCUSDT"
    assert params["interval"] == "1"
    assert params["limit"] == 10


def test_bybit_kline_request_builder_does_not_omit_category() -> None:
    descriptor = build_bybit_kline_request(_page_request())
    params = descriptor["params"]

    assert "category" in params
    assert params["category"] == "spot"


def test_reverse_sorted_fixture_rows_normalize_to_ascending_candles() -> None:
    result = normalize_bybit_kline_response(_page_request(), _fixture_response())

    assert [candle.timestamp_ms for candle in result.candles] == [
        1_700_000_000_000,
        1_700_000_060_000,
        1_700_000_120_000,
    ]


def test_normalized_candles_preserve_ohlcv_and_turnover() -> None:
    result = normalize_bybit_kline_response(_page_request(), _fixture_response())
    candle = result.candles[0]

    assert candle.timestamp_ms == 1_700_000_000_000
    assert candle.open == "42000.0"
    assert candle.high == "42010.0"
    assert candle.low == "41990.0"
    assert candle.close == "42005.0"
    assert candle.volume == "1.1"
    assert candle.turnover == "46200.0"


def test_malformed_kline_rows_are_rejected() -> None:
    malformed = {"retCode": 0, "result": {"list": [["1700000000000", "1"]]}}

    with pytest.raises(ValueError, match="OHLCV"):
        normalize_bybit_kline_response(_page_request(), malformed)


def test_storage_writer_writes_csv_under_temp_sandbox_root_only(tmp_path: Path) -> None:
    request = _write_request()
    result = write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)
    csv_path = tmp_path / request.csv_path

    assert csv_path.exists()
    assert csv_path.is_relative_to(tmp_path)
    assert result.status is DownloadDataStorageWriteStatus.WRITTEN


def test_storage_writer_writes_metadata_sidecar(tmp_path: Path) -> None:
    request = _write_request()
    write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)
    metadata_path = tmp_path / request.metadata_path

    assert metadata_path.exists()


def test_storage_writer_writes_csv_rows_in_ascending_order(tmp_path: Path) -> None:
    request = _write_request(
        candles=(
            _candle(timestamp_ms=1_700_000_120_000),
            _candle(timestamp_ms=1_700_000_000_000),
        )
    )
    write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)
    with (tmp_path / request.csv_path).open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert [int(row["timestamp_ms"]) for row in rows] == [
        1_700_000_000_000,
        1_700_000_120_000,
    ]


def test_metadata_sidecar_contains_artifact_identity_and_unaccepted_state(
    tmp_path: Path,
) -> None:
    request = _write_request()
    write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)
    metadata = json.loads((tmp_path / request.metadata_path).read_text("utf-8"))

    assert metadata["artifact_id"] == DOWNLOAD_DATA_ARTIFACT_ID
    assert metadata["accepted"] is False
    assert metadata["loadable"] is False
    assert metadata["validated"] is False
    assert metadata["source"] == "bybit"
    assert metadata["smoke"] is True


def test_storage_write_result_reports_counts_and_timestamps(tmp_path: Path) -> None:
    request = _write_request()
    result = write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)

    assert result.bars_written == 2
    assert result.first_timestamp_ms == 1_700_000_000_000
    assert result.last_timestamp_ms == 1_700_000_060_000
    assert result.accepted is False
    assert result.loadable is False
    assert result.validated is False


def test_smoke_execution_result_reports_completed_download_and_write(
    tmp_path: Path,
) -> None:
    result = run_bybit_ohlcv_smoke_slice(
        sandbox_root=tmp_path,
        transport=_fixture_transport,
    )

    assert result.status is DownloadDataExecutionStatus.COMPLETED
    assert result.total_bars_downloaded == 3
    assert result.total_bars_written == 3
    assert result.storage_results[0].bars_written == 3


def test_smoke_execution_produces_read_model_progress_events(tmp_path: Path) -> None:
    result = run_bybit_ohlcv_smoke_slice(
        sandbox_root=tmp_path,
        transport=_fixture_transport,
    )

    assert len(result.progress_events) == 3
    assert [event.status for event in result.progress_events] == [
        DownloadDataExecutionStatus.PENDING,
        DownloadDataExecutionStatus.RUNNING,
        DownloadDataExecutionStatus.COMPLETED,
    ]
    assert all(not hasattr(event, "cancel") for event in result.progress_events)


def test_fixture_transport_receives_params_and_no_real_network_is_used(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fixture_transport(params: object) -> dict[str, object]:
        calls.append(dict(params))  # type: ignore[arg-type]
        return _fixture_response()

    run_bybit_ohlcv_smoke_slice(sandbox_root=tmp_path, transport=fixture_transport)

    assert calls == [
        {
            "category": "spot",
            "symbol": "BTCUSDT",
            "interval": "1",
            "limit": 10,
        }
    ]


def test_smoke_slice_does_not_create_project_data_directory(tmp_path: Path) -> None:
    project_data_dir = Path.cwd() / "data" / "historical"
    existed_before = project_data_dir.exists()

    run_bybit_ohlcv_smoke_slice(
        sandbox_root=tmp_path,
        transport=_fixture_transport,
    )

    assert project_data_dir.exists() is existed_before


def test_storage_writer_rejects_project_root_as_sandbox() -> None:
    with pytest.raises(ValueError, match="project root"):
        write_ohlcv_smoke_new_file(_write_request(), sandbox_root=Path.cwd())


def test_storage_writer_rejects_update_mode(tmp_path: Path) -> None:
    request = _write_request(write_mode=DownloadDataExecutionMode.UPDATE_EXISTING)

    with pytest.raises(ValueError, match="new_file"):
        write_ohlcv_smoke_new_file(request, sandbox_root=tmp_path)


def test_download_data_modules_import_no_gui_runtime_or_network_modules() -> None:
    for module in (bybit_ohlcv, ohlcv_storage_writer, smoke_execution):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imports = _imported_module_names(tree)

        assert all(
            not imported_name.startswith(
                (
                    "leonardo.gui",
                    "leonardo.core",
                    "requests",
                    "httpx",
                    "aiohttp",
                    "websocket",
                    "ccxt",
                    "pybit",
                )
            )
            for imported_name in imports
        )


def _imported_module_names(tree: ast.AST) -> tuple[str, ...]:
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names.append(node.module)
    return tuple(imported_names)


def _page_request(**overrides: object) -> DownloadDataProviderPageRequest:
    values: dict[str, object] = {
        "exchange_id": "bybit",
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "category": "spot",
        "interval": "1",
        "limit": 10,
    }
    values.update(overrides)
    return DownloadDataProviderPageRequest(**values)


def _write_request(**overrides: object) -> DownloadDataStorageWriteRequest:
    values: dict[str, object] = {
        "target": smoke_execution._smoke_target(),
        "candles": (
            _candle(timestamp_ms=1_700_000_000_000),
            _candle(timestamp_ms=1_700_000_060_000),
        ),
        "csv_path": "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv",
        "metadata_path": "historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json",
        "write_mode": DownloadDataExecutionMode.NEW_FILE,
    }
    values.update(overrides)
    return DownloadDataStorageWriteRequest(**values)


def _candle(**overrides: object) -> DownloadDataNormalizedCandle:
    values: dict[str, object] = {
        "timestamp_ms": 1_700_000_000_000,
        "open": "42000.0",
        "high": "42010.0",
        "low": "41990.0",
        "close": "42005.0",
        "volume": "1.1",
        "turnover": "46200.0",
    }
    values.update(overrides)
    return DownloadDataNormalizedCandle(**values)


def _fixture_transport(params: object) -> dict[str, object]:
    expected = {
        "category": "spot",
        "symbol": "BTCUSDT",
        "interval": "1",
        "limit": 10,
    }
    if dict(params) != expected:  # type: ignore[arg-type]
        raise AssertionError("unexpected Bybit kline params")
    return _fixture_response()


def _fixture_response() -> dict[str, object]:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "spot",
            "symbol": "BTCUSDT",
            "list": [
                [
                    "1700000120000",
                    "42020.0",
                    "42030.0",
                    "42010.0",
                    "42025.0",
                    "1.3",
                    "54600.0",
                ],
                [
                    "1700000060000",
                    "42005.0",
                    "42020.0",
                    "42000.0",
                    "42015.0",
                    "1.2",
                    "50400.0",
                ],
                [
                    "1700000000000",
                    "42000.0",
                    "42010.0",
                    "41990.0",
                    "42005.0",
                    "1.1",
                    "46200.0",
                ],
            ],
        },
    }
