import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from leonardo.contracts.download_data_boundary import (
    CONNECTION_AREA_ID,
    CONNECTION_DOWNLOAD_MANAGER_MODULE_ID,
    CONNECTION_DOWNLOAD_MANAGER_OWNER_COMPONENT,
    CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN,
    CONNECTION_SUITE_ID,
    DOWNLOAD_DATA_ARTIFACT_ID,
    DOWNLOAD_DATA_MESSAGE_MAX_LENGTH,
    DownloadDataBoundaryDescriptor,
    DownloadDataCompletionItem,
    DownloadDataCompletionSummary,
    DownloadDataExchangeRangeSummary,
    DownloadDataItemStatus,
    DownloadDataLocalDatasetState,
    DownloadDataOutputRef,
    DownloadDataPartialPersistenceSummary,
    DownloadDataPersistenceStatus,
    DownloadDataPreflightItem,
    DownloadDataPreflightMode,
    DownloadDataPreflightSummary,
    DownloadDataProgressItem,
    DownloadDataProgressMessage,
    DownloadDataProgressSummary,
    DownloadDataSelectionDraft,
    DownloadDataSelectionSummary,
    DownloadDataStorageTargetRef,
    DownloadDataValidationStatus,
    DownloadDataWorkloadEstimate,
    DownloadDataWorkflowDescriptor,
    DownloadDataWorkflowStatus,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "download_data_boundary.py"
)
_DOC_PATH = _REPO_ROOT / "docs" / "contracts_docs" / "DOWNLOAD_DATA_BOUNDARY.md"


def test_enums_coerce_from_strings() -> None:
    workflow = DownloadDataWorkflowDescriptor(
        workflow_id="download_data",
        display_name="Download Data",
        status="preflight_ready",
    )
    preflight_item = _preflight_item(mode="update_existing", status="ready")
    output = _output_ref(
        persistence_status="complete",
        validation_status="valid",
        loadable=True,
        accepted=True,
    )

    assert workflow.status is DownloadDataWorkflowStatus.PREFLIGHT_READY
    assert preflight_item.mode is DownloadDataPreflightMode.UPDATE_EXISTING
    assert preflight_item.status is DownloadDataItemStatus.READY
    assert output.persistence_status is DownloadDataPersistenceStatus.COMPLETE
    assert output.validation_status is DownloadDataValidationStatus.VALID


def test_download_data_descriptors_expose_connection_suite_ownership() -> None:
    boundary = DownloadDataBoundaryDescriptor(
        boundary_id="download_data_boundary",
        display_name="Download Data Boundary",
        workflow_ids=("download_data",),
    )
    workflow = DownloadDataWorkflowDescriptor(
        workflow_id="download_data",
        display_name="Download Data",
    )

    for descriptor in (boundary, workflow):
        assert descriptor.owner_area_id == CONNECTION_AREA_ID
        assert descriptor.owner_suite_id == CONNECTION_SUITE_ID
        assert descriptor.owner_domain == CONNECTION_DOWNLOAD_MANAGER_OWNER_DOMAIN
        assert descriptor.owner_component == CONNECTION_DOWNLOAD_MANAGER_OWNER_COMPONENT
        assert descriptor.module_id == CONNECTION_DOWNLOAD_MANAGER_MODULE_ID
        assert descriptor.owner_area_id != "gui"
        assert descriptor.owner_domain not in {"gui", "core", "download.core"}
        assert descriptor.module_id != "download_data"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("owner_area_id", "gui"),
        ("owner_suite_id", "gui"),
        ("owner_domain", "gui"),
        ("owner_domain", "core"),
        ("owner_domain", "download.core"),
        ("module_id", "download_data"),
    ),
)
def test_download_data_boundary_rejects_non_connection_suite_ownership(
    field_name: str,
    value: str,
) -> None:
    kwargs = {
        "boundary_id": "download_data_boundary",
        "display_name": "Download Data Boundary",
        "workflow_ids": ("download_data",),
        field_name: value,
    }

    with pytest.raises(ValueError, match=field_name):
        DownloadDataBoundaryDescriptor(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("owner_area_id", "gui"),
        ("owner_suite_id", "gui"),
        ("owner_domain", "gui"),
        ("owner_domain", "core"),
        ("owner_domain", "download.core"),
        ("module_id", "download_data"),
    ),
)
def test_download_data_workflow_rejects_non_connection_suite_ownership(
    field_name: str,
    value: str,
) -> None:
    kwargs = {
        "workflow_id": "download_data",
        "display_name": "Download Data",
        field_name: value,
    }

    with pytest.raises(ValueError, match=field_name):
        DownloadDataWorkflowDescriptor(**kwargs)


def test_all_contract_dataclasses_are_frozen_read_only() -> None:
    for contract in _all_contract_instances():
        field_name = fields(contract)[0].name
        with pytest.raises(FrozenInstanceError):
            setattr(contract, field_name, "changed")


def test_blank_required_identifiers_are_rejected() -> None:
    with pytest.raises(ValueError, match="boundary_id"):
        DownloadDataBoundaryDescriptor(
            boundary_id="",
            display_name="Download Data",
            workflow_ids=("download_data",),
        )
    with pytest.raises(ValueError, match="workflow_id"):
        DownloadDataWorkflowDescriptor(workflow_id=" ", display_name="Download Data")
    with pytest.raises(ValueError, match="exchange_id"):
        DownloadDataSelectionSummary(
            exchange_id="",
            market_type="spot",
            symbol="BTCUSDT",
            selected_timeframes=("1m",),
        )
    with pytest.raises(ValueError, match="message_id"):
        DownloadDataProgressMessage(
            message_id="",
            timestamp_ms=1,
            timestamp_utc="2026-01-01T00:00:00Z",
            level="info",
            text="started",
        )


def test_sequence_fields_normalize_to_tuples_and_reject_plain_strings() -> None:
    draft = DownloadDataSelectionDraft(
        selected_timeframes=["1m", "5m"],  # type: ignore[arg-type]
        warnings=["missing range"],  # type: ignore[arg-type]
    )
    descriptor = DownloadDataBoundaryDescriptor(
        boundary_id="download_data_boundary",
        display_name="Download Data Boundary",
        workflow_ids=["download_data"],  # type: ignore[arg-type]
    )

    assert draft.selected_timeframes == ("1m", "5m")
    assert draft.warnings == ("missing range",)
    assert descriptor.workflow_ids == ("download_data",)

    with pytest.raises(TypeError, match="selected_timeframes"):
        DownloadDataSelectionDraft(selected_timeframes="1m")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="workflow_ids"):
        DownloadDataBoundaryDescriptor(
            boundary_id="download_data_boundary",
            display_name="Download Data Boundary",
            workflow_ids="download_data",  # type: ignore[arg-type]
        )


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="row_count"):
        DownloadDataLocalDatasetState(exists=True, row_count=-1)
    with pytest.raises(ValueError, match="expected_bars"):
        _workload(expected_bars=-1)
    with pytest.raises(ValueError, match="completed_steps"):
        _progress_item(completed_steps=-1)
    with pytest.raises(ValueError, match="bars_written"):
        _output_ref(bars_written=-1)
    with pytest.raises(ValueError, match="bars_persisted"):
        _partial_summary(bars_persisted=-1)


def test_timestamp_ordering_validation() -> None:
    with pytest.raises(ValueError, match="first_timestamp_ms"):
        DownloadDataLocalDatasetState(
            exists=True,
            first_timestamp_ms=2000,
            last_timestamp_ms=1000,
        )
    with pytest.raises(ValueError, match="first_available_timestamp_ms"):
        DownloadDataExchangeRangeSummary(
            exchange_id="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="1m",
            first_available_timestamp_ms=2000,
            last_available_timestamp_ms=1000,
        )
    with pytest.raises(ValueError, match="estimated_start_timestamp_ms"):
        _workload(estimated_start_timestamp_ms=2000, estimated_end_timestamp_ms=1000)


def test_storage_target_uses_old_leonardo_naming_policy() -> None:
    target = _storage_target()

    assert target.artifact_id == DOWNLOAD_DATA_ARTIFACT_ID
    assert target.csv_path == (
        "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.csv"
    )
    assert target.metadata_path == (
        "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.meta.json"
    )


def test_storage_target_rejects_noncanonical_artifact_or_unsafe_paths() -> None:
    with pytest.raises(ValueError, match="artifact_id"):
        _storage_target(artifact_id="ohlcv")
    with pytest.raises(ValueError, match="csv_path"):
        _storage_target(csv_path="/absolute/candles.csv")
    with pytest.raises(ValueError, match="metadata_path"):
        _storage_target(metadata_path="../candles.meta.json")


def test_no_default_selection_is_invented_and_void_selection_is_supported() -> None:
    draft = DownloadDataSelectionDraft()

    assert draft.exchange_id is None
    assert draft.market_type is None
    assert draft.symbol is None
    assert draft.selected_timeframes == ()
    assert draft.selection_complete is False


def test_selection_draft_marks_complete_only_when_all_identity_fields_exist() -> None:
    incomplete = DownloadDataSelectionDraft(
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
    )
    complete = DownloadDataSelectionDraft(
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        selected_timeframes=("1m",),
    )

    assert incomplete.selection_complete is False
    assert complete.selection_complete is True


def test_preflight_modes_distinguish_expected_outcomes() -> None:
    assert _preflight_item(mode="new_file").mode is DownloadDataPreflightMode.NEW_FILE
    assert (
        _preflight_item(mode="update_existing").mode
        is DownloadDataPreflightMode.UPDATE_EXISTING
    )
    assert (
        _preflight_item(mode="already_current").mode
        is DownloadDataPreflightMode.ALREADY_CURRENT
    )
    assert _preflight_item(mode="blocked").mode is DownloadDataPreflightMode.BLOCKED
    assert _preflight_item(mode="unknown").mode is DownloadDataPreflightMode.UNKNOWN


def test_preflight_summary_aggregates_item_counts_deterministically() -> None:
    items = (
        _preflight_item(mode="new_file", status="ready", expected_bars=10, expected_steps=2),
        _preflight_item(
            timeframe="5m",
            mode="update_existing",
            status="ready",
            expected_bars=20,
            expected_steps=3,
        ),
        _preflight_item(
            timeframe="15m",
            mode="already_current",
            status="skipped",
            expected_bars=0,
            expected_steps=0,
        ),
        _preflight_item(
            timeframe="1h",
            mode="blocked",
            status="blocked",
            expected_bars=0,
            expected_steps=0,
        ),
        _preflight_item(
            timeframe="1d",
            mode="unknown",
            status="pending",
            expected_bars=0,
            expected_steps=0,
        ),
    )
    summary = DownloadDataPreflightSummary(
        workflow_id="download_data",
        selection_summary=DownloadDataSelectionSummary(
            exchange_id="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            selected_timeframes=("1m", "5m", "15m", "1h", "1d"),
        ),
        items=items,
    )

    assert summary.total_items == 5
    assert summary.ready_items == 2
    assert summary.blocked_items == 1
    assert summary.new_file_items == 1
    assert summary.update_items == 1
    assert summary.already_current_items == 1
    assert summary.expected_total_bars == 30
    assert summary.expected_total_steps == 5


def test_workload_estimate_rejects_impossible_negative_values() -> None:
    with pytest.raises(ValueError, match="expected_steps"):
        _workload(expected_steps=-1)
    with pytest.raises(ValueError, match="bars_per_step"):
        _workload(bars_per_step=-1)


def test_progress_message_text_is_bounded() -> None:
    message = DownloadDataProgressMessage(
        message_id="message-1",
        timestamp_ms=1,
        timestamp_utc="2026-01-01T00:00:00Z",
        level="info",
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        text="download started",
    )

    assert message.text == "download started"

    with pytest.raises(ValueError, match="at most 280 characters"):
        DownloadDataProgressMessage(
            message_id="message-2",
            timestamp_ms=1,
            timestamp_utc="2026-01-01T00:00:00Z",
            level="info",
            text="x" * (DOWNLOAD_DATA_MESSAGE_MAX_LENGTH + 1),
        )


def test_progress_summary_aggregates_rows_and_messages() -> None:
    summary = DownloadDataProgressSummary(
        workflow_id="download_data",
        operation_id="operation-1",
        task_id="task-1",
        status="running",
        items=(
            _progress_item(status="completed", completed_steps=2, total_steps=2),
            _progress_item(
                timeframe="5m",
                status="failed",
                completed_steps=0,
                total_steps=2,
            ),
            _progress_item(
                timeframe="15m",
                status="cancelled",
                completed_steps=0,
                total_steps=1,
            ),
        ),
        messages=(
            DownloadDataProgressMessage(
                message_id="message-1",
                timestamp_ms=1,
                timestamp_utc="2026-01-01T00:00:00Z",
                level="info",
                text="step 1/2",
            ),
        ),
    )

    assert summary.status is DownloadDataWorkflowStatus.RUNNING
    assert summary.total_items == 3
    assert summary.completed_items == 1
    assert summary.failed_items == 1
    assert summary.cancelled_items == 1
    assert summary.total_steps == 5
    assert summary.completed_steps == 2
    assert len(summary.messages) == 1


def test_completion_summary_distinguishes_partial_from_accepted_loadable() -> None:
    complete_output = _output_ref(
        persistence_status="complete",
        validation_status="valid",
        loadable=True,
        accepted=True,
    )
    partial_output = _output_ref(
        timeframe="5m",
        persistence_status="partial_update",
        validation_status="not_validated",
        loadable=False,
        accepted=False,
    )
    summary = DownloadDataCompletionSummary(
        workflow_id="download_data",
        status="partial",
        output_refs=(complete_output, partial_output),
        items=(
            _completion_item(output_ref=complete_output, status="completed"),
            _completion_item(
                timeframe="5m",
                output_ref=partial_output,
                status="partial",
            ),
        ),
    )

    assert summary.status is DownloadDataWorkflowStatus.PARTIAL
    assert summary.total_items == 2
    assert summary.completed_items == 1
    assert summary.partial_items == 1
    assert complete_output.accepted is True
    assert partial_output.accepted is False
    assert partial_output.loadable is False


def test_partial_persistence_does_not_imply_validation_loadability_or_acceptance() -> None:
    partial = _partial_summary()

    assert partial.partial is True
    assert partial.persistence_status is DownloadDataPersistenceStatus.PARTIAL_NEW_FILE
    assert partial.maintenance_required is True
    assert not hasattr(partial, "validation_status")
    assert not hasattr(partial, "loadable")
    assert not hasattr(partial, "accepted")

    with pytest.raises(ValueError, match="cannot be accepted"):
        _output_ref(persistence_status="partial_new_file", accepted=True)
    with pytest.raises(ValueError, match="cannot be loadable"):
        _output_ref(persistence_status="partial_new_file", loadable=True)
    with pytest.raises(ValueError, match="cannot be validated"):
        _output_ref(
            persistence_status="partial_new_file",
            validation_status="valid",
        )


def test_partial_persistence_summary_requires_partial_status_when_partial() -> None:
    with pytest.raises(ValueError, match="partial persistence status"):
        _partial_summary(persistence_status="complete")


def test_metadata_is_readonly_and_rejects_sensitive_keys() -> None:
    descriptor = DownloadDataWorkflowDescriptor(
        workflow_id="download_data",
        display_name="Download Data",
        metadata={"labels": ["download"], "nested": {"owner": "data"}},
    )

    assert descriptor.metadata["labels"] == ("download",)
    assert descriptor.metadata["nested"]["owner"] == "data"  # type: ignore[index]
    with pytest.raises(TypeError):
        descriptor.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        descriptor.metadata["nested"]["new"] = "value"  # type: ignore[index]

    for key in (
        "credential",
        "token",
        "secret",
        "password",
        "api_key",
        "authorization",
        "bearer",
        "client",
        "socket",
        "payload",
        "raw_payload",
        "response",
    ):
        with pytest.raises(ValueError, match="sensitive key"):
            DownloadDataWorkflowDescriptor(
                workflow_id="download_data",
                display_name="Download Data",
                metadata={key: "not allowed"},
            )


def test_to_dict_output_is_json_friendly() -> None:
    summary = DownloadDataCompletionSummary(
        workflow_id="download_data",
        status=DownloadDataWorkflowStatus.COMPLETED,
        output_refs=(
            _output_ref(
                persistence_status="complete",
                validation_status="valid",
                loadable=True,
                accepted=True,
            ),
        ),
        items=(
            _completion_item(
                status="completed",
                output_ref=_output_ref(
                    persistence_status="complete",
                    validation_status="valid",
                    loadable=True,
                    accepted=True,
                ),
            ),
        ),
        metadata={"labels": ("download",)},
    )

    serialized = summary.to_dict()

    assert serialized["status"] == "completed"
    assert serialized["output_refs"][0]["artifact_id"] == DOWNLOAD_DATA_ARTIFACT_ID
    assert serialized["items"][0]["mode"] == "new_file"
    assert serialized["metadata"]["labels"] == ["download"]


def test_contracts_expose_no_execution_methods() -> None:
    for contract in _all_contract_instances():
        for name in (
            "execute",
            "start",
            "submit",
            "process",
            "cancel",
            "write",
            "connect",
            "subscribe",
        ):
            assert not hasattr(contract, name)


def test_contract_module_has_no_runtime_provider_registry_or_network_imports() -> None:
    source = _CONTRACT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imported_modules(tree)

    assert all(
        blocked not in module
        for blocked in (
            "leonardo.core",
            "leonardo.gui",
            "leonardo.connection",
            "PySide6",
            "PyQt6",
            "requests",
            "httpx",
            "aiohttp",
            "websocket",
            "ccxt",
        )
        for module in imported_modules
    )

    blocked_tokens = (
        "ProviderRegistry",
        "register_provider",
        "pkgutil",
        "importlib",
        "os.walk",
        "Path.rglob",
        "globals()",
        "RuntimeManager",
        "RuntimeManagerBackend",
        "ReadOnlyObjectMapService",
        "TaskManager",
        "OperationRegistry",
        "StateStore",
        "AuditLog",
        "CoreRuntimeBridge",
        "CoreRunner",
        "ConnectionRegistry",
    )
    for token in blocked_tokens:
        assert token not in source


def test_contract_fields_do_not_store_provider_handles_or_raw_messages() -> None:
    forbidden_field_parts = (
        "credential",
        "token",
        "secret",
        "password",
        "api_key",
        "authorization",
        "bearer",
        "client",
        "socket",
        "payload",
        "raw_payload",
        "response",
    )

    for contract in _all_contract_instances():
        field_names = {field.name for field in fields(contract)}
        for field_name in field_names:
            assert not any(part in field_name for part in forbidden_field_parts)


def test_docs_record_boundary_and_partial_persistence_policy() -> None:
    doc = _DOC_PATH.read_text(encoding="utf-8")

    assert "Connection Suite Download Manager module" in doc
    assert "`owner_area_id = connection`" in doc
    assert "`owner_suite_id = connection_suite`" in doc
    assert "`owner_domain = connection.download_manager`" in doc
    assert "`module_id = connection.download_manager`" in doc
    assert "Core owns runtime primitives" in doc
    assert "Core does not own Download Manager domain" in doc
    assert "behavior." in doc
    assert "The GUI owns presentation shells only" in doc
    assert "Data Manager owns accepted or managed data artifacts" in doc
    assert "storage/data layer owns persisted OHLCV value truth" in doc
    assert "data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv" in doc
    assert "No default selections" in doc
    assert "partial persistence is not accepted, loadable, validated, or clean data" in doc
    assert "OHLCV Maintenance" in doc


def _all_contract_instances() -> tuple[object, ...]:
    selection = DownloadDataSelectionSummary(
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        selected_timeframes=("1m",),
    )
    preflight_item = _preflight_item()
    progress_item = _progress_item()
    progress_message = DownloadDataProgressMessage(
        message_id="message-1",
        timestamp_ms=1,
        timestamp_utc="2026-01-01T00:00:00Z",
        level="info",
        text="download started",
    )
    output_ref = _output_ref()
    completion_item = _completion_item(output_ref=output_ref)
    return (
        DownloadDataBoundaryDescriptor(
            boundary_id="download_data_boundary",
            display_name="Download Data Boundary",
            workflow_ids=("download_data",),
        ),
        DownloadDataWorkflowDescriptor(
            workflow_id="download_data",
            display_name="Download Data",
        ),
        DownloadDataSelectionDraft(),
        selection,
        _storage_target(),
        DownloadDataLocalDatasetState(exists=False),
        _range_summary(),
        _workload(),
        preflight_item,
        DownloadDataPreflightSummary(
            workflow_id="download_data",
            selection_summary=selection,
            items=(preflight_item,),
        ),
        progress_item,
        progress_message,
        DownloadDataProgressSummary(
            workflow_id="download_data",
            items=(progress_item,),
            messages=(progress_message,),
        ),
        output_ref,
        completion_item,
        DownloadDataCompletionSummary(
            workflow_id="download_data",
            status="completed",
            output_refs=(output_ref,),
            items=(completion_item,),
        ),
        _partial_summary(),
    )


def _storage_target(**overrides: object) -> DownloadDataStorageTargetRef:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
    }
    values.update(overrides)
    return DownloadDataStorageTargetRef(**values)


def _local_state(**overrides: object) -> DownloadDataLocalDatasetState:
    values = {
        "exists": False,
        "persistence_status": "not_started",
        "validation_status": "unknown",
    }
    values.update(overrides)
    return DownloadDataLocalDatasetState(**values)


def _range_summary(**overrides: object) -> DownloadDataExchangeRangeSummary:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "page_limit": 1000,
        "source": "metadata",
    }
    values.update(overrides)
    return DownloadDataExchangeRangeSummary(**values)


def _workload(**overrides: object) -> DownloadDataWorkloadEstimate:
    values = {"expected_bars": 10, "expected_steps": 2, "bars_per_step": 5}
    values.update(overrides)
    return DownloadDataWorkloadEstimate(**values)


def _preflight_item(**overrides: object) -> DownloadDataPreflightItem:
    timeframe = str(overrides.get("timeframe", "1m"))
    expected_bars = overrides.pop("expected_bars", 10)
    expected_steps = overrides.pop("expected_steps", 2)
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": timeframe,
        "mode": "new_file",
        "status": "ready",
        "local_dataset_state": _local_state(),
        "exchange_range_summary": _range_summary(timeframe=timeframe),
        "workload_estimate": _workload(
            expected_bars=expected_bars,
            expected_steps=expected_steps,
        ),
        "storage_target": _storage_target(timeframe=timeframe),
    }
    values.update(overrides)
    return DownloadDataPreflightItem(**values)


def _progress_item(**overrides: object) -> DownloadDataProgressItem:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "running",
        "mode": "new_file",
        "completed_steps": 1,
        "total_steps": 2,
        "downloaded_bars": 5,
    }
    values.update(overrides)
    return DownloadDataProgressItem(**values)


def _output_ref(**overrides: object) -> DownloadDataOutputRef:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "bars_written": 10,
        "persistence_status": "new_file",
        "validation_status": "unknown",
        "loadable": False,
        "accepted": False,
    }
    values.update(overrides)
    return DownloadDataOutputRef(**values)


def _completion_item(**overrides: object) -> DownloadDataCompletionItem:
    output_ref = overrides.pop("output_ref", _output_ref())
    values = {
        "exchange_id": output_ref.exchange_id,
        "market_type": output_ref.market_type,
        "symbol": output_ref.symbol,
        "timeframe": output_ref.timeframe,
        "mode": "new_file",
        "status": "completed",
        "output_ref": output_ref,
        "bars_downloaded": output_ref.bars_written,
    }
    values.update(overrides)
    return DownloadDataCompletionItem(**values)


def _partial_summary(**overrides: object) -> DownloadDataPartialPersistenceSummary:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "csv_path": "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.csv",
        "metadata_path": (
            "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.meta.json"
        ),
        "partial": True,
        "persistence_status": "partial_new_file",
        "bars_persisted": 5,
    }
    values.update(overrides)
    return DownloadDataPartialPersistenceSummary(**values)


def _imported_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return tuple(modules)
