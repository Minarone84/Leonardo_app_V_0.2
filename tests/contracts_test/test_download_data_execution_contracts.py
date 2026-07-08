import ast
import inspect
import sys
from dataclasses import FrozenInstanceError, fields

import pytest

import leonardo.contracts.download_data_execution as execution_contracts
from leonardo.contracts.download_data_execution import (
    DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH,
    DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX,
    DownloadDataCandleSortOrder,
    DownloadDataExecutionCommand,
    DownloadDataExecutionDirection,
    DownloadDataExecutionError,
    DownloadDataExecutionMode,
    DownloadDataExecutionPlan,
    DownloadDataExecutionProgressEvent,
    DownloadDataExecutionResult,
    DownloadDataExecutionStatus,
    DownloadDataExecutionTarget,
    DownloadDataNormalizedCandle,
    DownloadDataProviderPageRequest,
    DownloadDataProviderPageResult,
    DownloadDataProviderResultStatus,
    DownloadDataStorageWriteRequest,
    DownloadDataStorageWriteResult,
    DownloadDataStorageWriteStatus,
)


def test_enums_coerce_from_strings() -> None:
    target = _target(mode="new_file", direction="backward_history")
    request = _page_request(direction="forward_update")
    page_result = _page_result(status="ok", sort_order="descending")
    write_request = _storage_write_request(write_mode="update_existing")
    write_result = _storage_write_result(status="written")
    progress = _progress_event(status="running")
    error = _execution_error(status="rate_limited")
    result = _execution_result(status="completed")

    assert target.mode is DownloadDataExecutionMode.NEW_FILE
    assert target.direction is DownloadDataExecutionDirection.BACKWARD_HISTORY
    assert request.direction is DownloadDataExecutionDirection.FORWARD_UPDATE
    assert page_result.status is DownloadDataProviderResultStatus.OK
    assert page_result.sort_order is DownloadDataCandleSortOrder.DESCENDING
    assert write_request.write_mode is DownloadDataExecutionMode.UPDATE_EXISTING
    assert write_result.status is DownloadDataStorageWriteStatus.WRITTEN
    assert progress.status is DownloadDataExecutionStatus.RUNNING
    assert error.status is DownloadDataProviderResultStatus.RATE_LIMITED
    assert result.status is DownloadDataExecutionStatus.COMPLETED


def test_all_contract_dataclasses_are_frozen_read_only() -> None:
    for contract in _all_contract_instances():
        field_name = fields(contract)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(contract, field_name, "changed")


def test_blank_required_identifiers_are_rejected() -> None:
    with pytest.raises(ValueError, match="exchange_id"):
        _target(exchange_id="")
    with pytest.raises(ValueError, match="command_id"):
        _command(command_id=" ")
    with pytest.raises(ValueError, match="category"):
        _page_request(category="")
    with pytest.raises(ValueError, match="event_id"):
        _progress_event(event_id="")
    with pytest.raises(ValueError, match="error_id"):
        _execution_error(error_id="")
    with pytest.raises(ValueError, match="plan_id"):
        _plan(plan_id="")


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="limit"):
        _target(limit=-1)
    with pytest.raises(ValueError, match="page_index"):
        _page_request(page_index=-1)
    with pytest.raises(ValueError, match="timestamp_ms"):
        _candle(timestamp_ms=-1)
    with pytest.raises(ValueError, match="bars_written"):
        _storage_write_result(bars_written=-1)
    with pytest.raises(ValueError, match="completed_steps"):
        _progress_event(completed_steps=-1)
    with pytest.raises(ValueError, match="partial_count"):
        _execution_result(partial_count=-1)


def test_timestamp_ordering_validation() -> None:
    with pytest.raises(ValueError, match="requested_start_timestamp_ms"):
        _target(requested_start_timestamp_ms=2000, requested_end_timestamp_ms=1000)
    with pytest.raises(ValueError, match="provider_earliest_timestamp_ms"):
        _target(provider_earliest_timestamp_ms=2000, provider_latest_timestamp_ms=1000)
    with pytest.raises(ValueError, match="start_timestamp_ms"):
        _page_request(start_timestamp_ms=2000, end_timestamp_ms=1000)
    with pytest.raises(ValueError, match="first_timestamp_ms"):
        _storage_write_result(first_timestamp_ms=2000, last_timestamp_ms=1000)


def test_tuple_fields_normalize_and_reject_plain_strings() -> None:
    command = _command(targets=[_target()])  # type: ignore[arg-type]
    page_result = _page_result(
        candles=[_candle()],  # type: ignore[arg-type]
        warnings=["descending provider order"],  # type: ignore[arg-type]
    )
    plan = _plan(
        provider_page_requests=[_page_request()],  # type: ignore[arg-type]
        storage_write_requests=[_storage_write_request()],  # type: ignore[arg-type]
    )

    assert command.targets == (_target(),)
    assert page_result.candles == (_candle(),)
    assert page_result.warnings == ("descending provider order",)
    assert plan.provider_page_requests == (_page_request(),)
    assert plan.storage_write_requests == (_storage_write_request(),)

    with pytest.raises(TypeError, match="targets"):
        _command(targets="target")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="candles"):
        _page_result(candles="raw")  # type: ignore[arg-type]


def test_execution_command_requires_explicit_targets_and_sandbox_reference() -> None:
    command = _command(sandbox_root_ref="run-root")

    assert command.sandbox_root_ref == "run-root"
    assert command.targets == (_target(),)

    with pytest.raises(ValueError, match="targets"):
        _command(targets=())
    with pytest.raises(TypeError, match="dry_run"):
        _command(dry_run="yes")  # type: ignore[arg-type]


def test_provider_page_request_validates_provider_specific_bounds() -> None:
    request = _page_request(category="spot", interval="1", limit=200)

    assert request.category == "spot"
    assert request.interval == "1"
    assert request.limit == 200

    with pytest.raises(ValueError, match="limit"):
        _page_request(limit=0)
    with pytest.raises(ValueError, match="limit"):
        _page_request(limit=DOWNLOAD_DATA_PROVIDER_PAGE_LIMIT_MAX + 1)


def test_normalized_candle_rejects_missing_timestamp_or_ohlcv_values() -> None:
    candle = _candle(turnover="11.0", source_order=0)

    assert candle.timestamp_ms == 1_700_000_000_000
    assert candle.turnover == "11.0"
    assert candle.source_order == 0

    with pytest.raises(ValueError, match="open"):
        _candle(open="")
    with pytest.raises(ValueError, match="volume"):
        _candle(volume=object())


def test_page_result_keeps_normalized_candles_only_without_raw_responses() -> None:
    result = _page_result(
        candles=(_candle(),),
        sort_order=DownloadDataCandleSortOrder.DESCENDING,
        next_page_cursor="cursor-1",
    )

    assert result.candles == (_candle(),)
    assert result.sort_order is DownloadDataCandleSortOrder.DESCENDING
    assert result.next_page_cursor == "cursor-1"

    with pytest.raises(TypeError, match="candles"):
        _page_result(candles=("raw-row",))  # type: ignore[arg-type]


def test_storage_write_request_contains_paths_without_write_behavior() -> None:
    request = _storage_write_request()

    assert request.csv_path.endswith("/candles.csv")
    assert request.metadata_path.endswith("/candles.meta.json")
    assert request.sort_order is DownloadDataCandleSortOrder.ASCENDING
    assert not hasattr(request, "write")

    with pytest.raises(ValueError, match="ascending"):
        _storage_write_request(sort_order="descending")
    with pytest.raises(ValueError, match="csv_path"):
        _storage_write_request(csv_path="/absolute/candles.csv")
    with pytest.raises(ValueError, match="metadata_path"):
        _storage_write_request(metadata_path="../candles.meta.json")


def test_partial_storage_result_cannot_be_accepted_loadable_or_validated() -> None:
    partial = _storage_write_result(
        status="partially_written",
        partial=True,
        accepted=False,
        loadable=False,
        validated=False,
    )

    assert partial.accepted is False
    assert partial.loadable is False
    assert partial.validated is False

    with pytest.raises(ValueError, match="partial"):
        _storage_write_result(partial=True, accepted=True)
    with pytest.raises(ValueError, match="partial"):
        _storage_write_result(partial=True, loadable=True)
    with pytest.raises(ValueError, match="partial"):
        _storage_write_result(partial=True, validated=True)


def test_progress_and_error_messages_are_bounded_and_redacted() -> None:
    redacted_progress = _progress_event(message="client token leaked")
    redacted_error = _execution_error(message="raw response leaked")

    assert redacted_progress.message == "[redacted]"
    assert redacted_error.message == "[redacted]"

    with pytest.raises(ValueError, match="message"):
        _progress_event(message="x" * (DOWNLOAD_DATA_EXECUTION_MESSAGE_MAX_LENGTH + 1))
    with pytest.raises(ValueError, match="completed_steps"):
        _progress_event(completed_steps=2, total_steps=1)


def test_execution_result_aggregates_download_write_partial_and_failure_counts() -> None:
    target = _target()
    storage_results = (
        _storage_write_result(target=target, status="written", bars_written=5),
        _storage_write_result(
            target=target,
            status="partially_written",
            bars_written=3,
            partial=True,
            accepted=False,
            loadable=False,
            validated=False,
        ),
        _storage_write_result(target=target, status="failed", bars_written=0),
    )
    progress_events = (
        _progress_event(target=target, downloaded_bars=4),
        _progress_event(event_id="event-2", target=target, downloaded_bars=12),
    )
    result = _execution_result(
        targets=(target,),
        storage_results=storage_results,
        progress_events=progress_events,
        errors=(_execution_error(target=target),),
        total_bars_downloaded=1,
        total_bars_written=99,
        partial_count=99,
        failed_count=99,
    )

    assert result.total_bars_downloaded == 12
    assert result.total_bars_written == 8
    assert result.partial_count == 1
    assert result.failed_count == 2


def test_execution_plan_is_read_only_and_non_executing() -> None:
    plan = _plan(expected_steps=2, expected_bars=10)

    assert plan.targets == (_target(),)
    assert plan.provider_page_requests == (_page_request(),)
    assert plan.storage_write_requests == (_storage_write_request(),)
    assert not hasattr(plan, "execute")
    assert not hasattr(plan, "run")
    assert not hasattr(plan, "submit")


def test_metadata_rejects_sensitive_keys_recursively_and_is_read_only() -> None:
    target = _target(metadata={"safe": {"labels": ["spot", "smoke"]}})

    assert target.metadata["safe"]["labels"] == ("spot", "smoke")  # type: ignore[index]
    with pytest.raises(TypeError):
        target.metadata["new"] = "value"  # type: ignore[index]

    with pytest.raises(ValueError, match="metadata key"):
        _target(metadata={"safe": {"token": "x"}})
    with pytest.raises(ValueError, match="metadata key"):
        _page_result(metadata={"provider_response": "x"})
    with pytest.raises(TypeError, match="metadata"):
        _target(metadata={"safe": object()})


def test_metadata_rejects_non_finite_float_values_recursively() -> None:
    invalid_metadata_cases = (
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
        {"nested": {"value": float("nan")}},
        {"sequence": [1, {"value": float("inf")}]},
        {"sequence": (1, {"value": float("-inf")})},
    )

    for metadata in invalid_metadata_cases:
        with pytest.raises(ValueError, match="finite"):
            _target(metadata=metadata)


def test_to_dict_is_json_friendly() -> None:
    result = _execution_result(
        status=DownloadDataExecutionStatus.COMPLETED_WITH_WARNINGS,
        progress_events=(_progress_event(),),
        warnings=("slow page",),
        metadata={"labels": ("smoke",)},
    )
    data = result.to_dict()

    assert data["status"] == "completed_with_warnings"
    assert data["targets"][0]["mode"] == "new_file"
    assert data["progress_events"][0]["status"] == "running"
    assert data["warnings"] == ["slow page"]
    assert data["metadata"] == {"labels": ["smoke"]}


def test_contract_source_imports_no_runtime_gui_provider_or_network_modules() -> None:
    source = inspect.getsource(execution_contracts)
    tree = ast.parse(source)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names.append(node.module)

    blocked_prefixes = (
        "leonardo.core",
        "leonardo.gui",
        "leonardo.data",
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "websocket",
        "ccxt",
        "pybit",
    )
    assert all(
        not imported_name.startswith(blocked_prefixes)
        for imported_name in imported_names
    )

    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert {"execute", "run", "fetch", "write", "open", "discover"}.isdisjoint(
        function_names
    )


def test_tests_do_not_call_real_provider_transport_or_write_files() -> None:
    source = inspect.getsource(sys.modules[__name__])
    tree = ast.parse(source)
    blocked_modules = {"requests", "httpx", "aiohttp", "websocket", "ccxt", "pybit"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            assert node.func.id != "open"
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr != "write"
            if isinstance(node.func.value, ast.Name):
                assert node.func.value.id not in blocked_modules


def _all_contract_instances() -> tuple[object, ...]:
    target = _target()
    request = _page_request()
    candle = _candle()
    page_result = _page_result(request=request, candles=(candle,))
    write_request = _storage_write_request(target=target, candles=(candle,))
    write_result = _storage_write_result(target=target)
    progress = _progress_event(target=target)
    error = _execution_error(target=target)
    return (
        target,
        _command(targets=(target,)),
        request,
        candle,
        page_result,
        write_request,
        write_result,
        progress,
        error,
        _execution_result(
            targets=(target,),
            storage_results=(write_result,),
            progress_events=(progress,),
            errors=(error,),
        ),
        _plan(
            targets=(target,),
            provider_page_requests=(request,),
            storage_write_requests=(write_request,),
        ),
    )


def _target(**overrides: object) -> DownloadDataExecutionTarget:
    values: dict[str, object] = {
        "exchange_id": "bybit",
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "storage_target_ref": (
            "data/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv"
        ),
        "mode": DownloadDataExecutionMode.NEW_FILE,
        "direction": DownloadDataExecutionDirection.BACKWARD_HISTORY,
    }
    values.update(overrides)
    return DownloadDataExecutionTarget(**values)


def _command(**overrides: object) -> DownloadDataExecutionCommand:
    values: dict[str, object] = {
        "command_id": "command-1",
        "workflow_id": "download-data-workflow",
        "request_id": "request-1",
        "targets": (_target(),),
    }
    values.update(overrides)
    return DownloadDataExecutionCommand(**values)


def _page_request(**overrides: object) -> DownloadDataProviderPageRequest:
    values: dict[str, object] = {
        "exchange_id": "bybit",
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "category": "spot",
        "interval": "1",
        "start_timestamp_ms": 1_700_000_000_000,
        "end_timestamp_ms": 1_700_000_060_000,
    }
    values.update(overrides)
    return DownloadDataProviderPageRequest(**values)


def _candle(**overrides: object) -> DownloadDataNormalizedCandle:
    values: dict[str, object] = {
        "timestamp_ms": 1_700_000_000_000,
        "open": "1.0",
        "high": "2.0",
        "low": "0.5",
        "close": "1.5",
        "volume": "10.0",
    }
    values.update(overrides)
    return DownloadDataNormalizedCandle(**values)


def _page_result(**overrides: object) -> DownloadDataProviderPageResult:
    values: dict[str, object] = {
        "request": _page_request(),
        "status": DownloadDataProviderResultStatus.OK,
    }
    values.update(overrides)
    return DownloadDataProviderPageResult(**values)


def _storage_write_request(**overrides: object) -> DownloadDataStorageWriteRequest:
    values: dict[str, object] = {
        "target": _target(),
        "candles": (_candle(),),
        "csv_path": "data/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv",
        "metadata_path": (
            "data/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json"
        ),
        "write_mode": DownloadDataExecutionMode.NEW_FILE,
    }
    values.update(overrides)
    return DownloadDataStorageWriteRequest(**values)


def _storage_write_result(**overrides: object) -> DownloadDataStorageWriteResult:
    values: dict[str, object] = {
        "target": _target(),
        "status": DownloadDataStorageWriteStatus.WRITTEN,
        "csv_path": "data/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.csv",
        "metadata_path": (
            "data/historical/bybit/spot/BTCUSDT/1m/ohlcv/candles.meta.json"
        ),
        "bars_written": 1,
        "first_timestamp_ms": 1_700_000_000_000,
        "last_timestamp_ms": 1_700_000_000_000,
        "accepted": True,
        "loadable": True,
        "validated": True,
    }
    values.update(overrides)
    return DownloadDataStorageWriteResult(**values)


def _progress_event(**overrides: object) -> DownloadDataExecutionProgressEvent:
    values: dict[str, object] = {
        "event_id": "event-1",
        "workflow_id": "download-data-workflow",
        "target": _target(),
        "status": DownloadDataExecutionStatus.RUNNING,
        "message": "Fetching page",
        "timestamp_ms": 1_700_000_000_001,
        "completed_steps": 1,
        "total_steps": 2,
        "downloaded_bars": 1,
        "written_bars": 0,
    }
    values.update(overrides)
    return DownloadDataExecutionProgressEvent(**values)


def _execution_error(**overrides: object) -> DownloadDataExecutionError:
    values: dict[str, object] = {
        "error_id": "error-1",
        "status": DownloadDataProviderResultStatus.PROVIDER_ERROR,
        "code": "provider_unavailable",
        "message": "Provider unavailable",
    }
    values.update(overrides)
    return DownloadDataExecutionError(**values)


def _execution_result(**overrides: object) -> DownloadDataExecutionResult:
    values: dict[str, object] = {
        "workflow_id": "download-data-workflow",
        "status": DownloadDataExecutionStatus.COMPLETED,
        "targets": (_target(),),
    }
    values.update(overrides)
    return DownloadDataExecutionResult(**values)


def _plan(**overrides: object) -> DownloadDataExecutionPlan:
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "workflow_id": "download-data-workflow",
        "targets": (_target(),),
        "provider_page_requests": (_page_request(),),
        "storage_write_requests": (_storage_write_request(),),
    }
    values.update(overrides)
    return DownloadDataExecutionPlan(**values)
