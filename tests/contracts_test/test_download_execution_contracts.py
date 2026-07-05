from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.download_execution import (
    DownloadExecutionError,
    DownloadExecutionErrorCategory,
    DownloadExecutionEstimate,
    DownloadExecutionOutputRef,
    DownloadExecutionPhase,
    DownloadExecutionPlan,
    DownloadExecutionProgress,
    DownloadExecutionSnapshot,
    DownloadPreflightLayer,
    DownloadPreflightLayerResult,
    DownloadPreflightLayerStatus,
    default_execution_progress,
    is_failed_execution_phase,
    is_running_execution_phase,
    is_terminal_execution_phase,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOWNLOAD_EXECUTION_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "download_execution.py"
)


def test_download_execution_enum_values() -> None:
    assert DownloadExecutionPhase.PLANNED.value == "planned"
    assert DownloadExecutionPhase.PREFLIGHTING.value == "preflighting"
    assert DownloadExecutionPhase.PARTIALLY_COMPLETED.value == "partially_completed"
    assert DownloadExecutionErrorCategory.CONNECTION_UNAVAILABLE.value == (
        "connection_unavailable"
    )
    assert DownloadExecutionErrorCategory.RATE_LIMITED.value == "rate_limited"
    assert DownloadPreflightLayer.CONFLICT_POLICY.value == "conflict_policy"
    assert DownloadPreflightLayer.EXECUTION_COST.value == "execution_cost"
    assert DownloadPreflightLayerStatus.NOT_RUN.value == "not_run"
    assert DownloadPreflightLayerStatus.BLOCKED.value == "blocked"


def test_valid_download_execution_plan() -> None:
    plan = _plan()

    assert plan.plan_id == "plan-1"
    assert plan.request_id == "request-1"
    assert plan.workflow_kind == "download_data"
    assert plan.phase is DownloadExecutionPhase.PLANNED
    assert plan.operation_id == "operation-1"
    assert plan.task_id == "task-1"
    assert plan.connection_refs == ("connection-binance",)
    assert plan.adapter_ref == "adapter-binance"
    assert plan.storage_policy_ref == "ohlcv.v1"
    assert plan.dataset_refs == (_dataset_ref(),)
    assert plan.item_ids == ("request-1:BTCUSDT:1m",)


def test_plan_rejects_empty_required_ids() -> None:
    with pytest.raises(ValueError, match="plan_id"):
        _plan(plan_id=" ")
    with pytest.raises(ValueError, match="request_id"):
        _plan(request_id="")


def test_valid_preflight_layer_result() -> None:
    result = DownloadPreflightLayerResult(
        layer=DownloadPreflightLayer.CONNECTION,
        status=DownloadPreflightLayerStatus.WARNING,
        can_continue=True,
        issues=("Connection readiness is unresolved.",),
        metadata={"connection_refs": ["connection-binance"]},
    )

    assert result.layer is DownloadPreflightLayer.CONNECTION
    assert result.status is DownloadPreflightLayerStatus.WARNING
    assert result.can_continue is True
    assert result.issues == ("Connection readiness is unresolved.",)
    assert result.metadata["connection_refs"] == ("connection-binance",)


def test_valid_execution_estimate() -> None:
    estimate = DownloadExecutionEstimate(
        request_id="request-1",
        estimated_items=2,
        estimated_rows=1000,
        estimated_candles=1000,
        estimated_pages=4,
        estimated_bytes=8192,
        rate_limit_notes=("1200 weight per minute",),
    )

    assert estimate.estimated_items == 2
    assert estimate.estimated_rows == 1000
    assert estimate.estimated_candles == 1000
    assert estimate.estimated_pages == 4
    assert estimate.estimated_bytes == 8192
    assert estimate.rate_limit_notes == ("1200 weight per minute",)


def test_valid_execution_progress() -> None:
    progress = DownloadExecutionProgress(
        request_id="request-1",
        phase=DownloadExecutionPhase.RUNNING,
        total_items=4,
        completed_items=2,
        failed_items=1,
        skipped_items=0,
        running_items=1,
        current_item_id="request-1:BTCUSDT:1m",
        current_symbol="BTCUSDT",
        current_timeframe="1m",
        rows_downloaded=500,
        candles_downloaded=500,
        pages_fetched=2,
        percent=75,
        message="Fetching BTCUSDT 1m.",
        updated_at_utc="2026-01-01T00:00:00Z",
    )

    assert progress.phase is DownloadExecutionPhase.RUNNING
    assert progress.percent == 75.0
    assert progress.current_symbol == "BTCUSDT"
    assert progress.current_timeframe == "1m"
    assert progress.rows_downloaded == 500
    assert progress.pages_fetched == 2


def test_progress_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="failed_items"):
        DownloadExecutionProgress(
            request_id="request-1",
            phase=DownloadExecutionPhase.RUNNING,
            failed_items=-1,
        )
    with pytest.raises(ValueError, match="pages_fetched"):
        DownloadExecutionProgress(
            request_id="request-1",
            phase=DownloadExecutionPhase.RUNNING,
            pages_fetched=-1,
        )


def test_progress_rejects_invalid_percent() -> None:
    with pytest.raises(ValueError, match="percent"):
        DownloadExecutionProgress(
            request_id="request-1",
            phase=DownloadExecutionPhase.RUNNING,
            percent=101,
        )


def test_progress_rejects_item_counts_exceeding_total_items() -> None:
    with pytest.raises(ValueError, match="exceed total_items"):
        DownloadExecutionProgress(
            request_id="request-1",
            phase=DownloadExecutionPhase.RUNNING,
            total_items=2,
            completed_items=1,
            failed_items=1,
            running_items=1,
        )


def test_valid_output_ref_with_dataset_ref() -> None:
    output = _output_ref()

    assert output.dataset_ref == _dataset_ref()
    assert output.storage_format == "csv"
    assert output.value_relative_path == (
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/"
        "timeframe=1m/candles.csv"
    )
    assert output.metadata_relative_path == (
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/"
        "timeframe=1m/candles.meta.json"
    )
    assert output.validation_status == "unknown"
    assert output.quality_validation_status == "not_validated"


def test_output_ref_rejects_non_dataset_refs() -> None:
    with pytest.raises(ValueError, match="dataset://"):
        _output_ref(dataset_ref="file:///tmp/candles.csv")


def test_output_ref_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="relative"):
        _output_ref(value_relative_path="/absolute/candles.csv")
    with pytest.raises(ValueError, match="absolute"):
        _output_ref(value_relative_path="C:/data/candles.csv")


def test_output_ref_rejects_parent_path_segments() -> None:
    with pytest.raises(ValueError, match="parent"):
        _output_ref(value_relative_path="../candles.csv")
    with pytest.raises(ValueError, match="parent"):
        _output_ref(metadata_relative_path="ohlcv/../candles.meta.json")


def test_valid_execution_error() -> None:
    error = DownloadExecutionError(
        category=DownloadExecutionErrorCategory.RATE_LIMITED,
        message="Provider rate limit reached.",
        request_id="request-1",
        item_id="request-1:BTCUSDT:1m",
        provider_code="429",
        recoverable=True,
        metadata={"retry_after_seconds": 60},
    )

    assert error.category is DownloadExecutionErrorCategory.RATE_LIMITED
    assert error.recoverable is True
    assert error.metadata["retry_after_seconds"] == 60


def test_valid_execution_snapshot() -> None:
    plan = _plan()
    layer = DownloadPreflightLayerResult(
        layer=DownloadPreflightLayer.STRUCTURAL,
        status=DownloadPreflightLayerStatus.PASSED,
        can_continue=True,
    )
    estimate = DownloadExecutionEstimate(request_id="request-1", estimated_items=1)
    progress = DownloadExecutionProgress(
        request_id="request-1",
        phase=DownloadExecutionPhase.RUNNING,
        total_items=1,
        running_items=1,
    )
    output = _output_ref()
    error = DownloadExecutionError(
        category=DownloadExecutionErrorCategory.PROVIDER,
        message="Provider returned an empty page.",
        request_id="request-1",
        recoverable=False,
    )

    snapshot = DownloadExecutionSnapshot(
        plan=plan,
        preflight_layers=(layer,),
        estimate=estimate,
        progress=progress,
        outputs=(output,),
        errors=(error,),
        metadata={"source": "contract-test"},
    )

    assert snapshot.plan is plan
    assert snapshot.preflight_layers == (layer,)
    assert snapshot.estimate is estimate
    assert snapshot.progress is progress
    assert snapshot.outputs == (output,)
    assert snapshot.errors == (error,)
    assert snapshot.metadata["source"] == "contract-test"


def test_terminal_running_and_failed_phase_helpers() -> None:
    assert is_terminal_execution_phase(DownloadExecutionPhase.COMPLETED) is True
    assert is_terminal_execution_phase("cancelled") is True
    assert is_terminal_execution_phase(DownloadExecutionPhase.RUNNING) is False
    assert is_running_execution_phase(DownloadExecutionPhase.RUNNING) is True
    assert is_running_execution_phase("queued") is True
    assert is_running_execution_phase(DownloadExecutionPhase.PLANNED) is False
    assert is_failed_execution_phase(DownloadExecutionPhase.FAILED) is True
    assert is_failed_execution_phase("blocked") is True
    assert is_failed_execution_phase(DownloadExecutionPhase.PARTIALLY_COMPLETED) is False


def test_default_execution_progress_helper() -> None:
    progress = default_execution_progress("request-1")

    assert progress.request_id == "request-1"
    assert progress.phase is DownloadExecutionPhase.PLANNED
    assert progress.completed_items == 0
    assert progress.total_items is None


def test_metadata_is_copied_readonly_and_nested_values_are_normalized() -> None:
    metadata = {"labels": ["alpha", "beta"], "nested": {"owner": "contracts"}}
    plan = _plan(metadata=metadata)
    metadata["labels"] = ["changed"]
    metadata["nested"] = {"owner": "changed"}

    assert plan.metadata["labels"] == ("alpha", "beta")
    assert plan.metadata["nested"]["owner"] == "contracts"
    with pytest.raises(TypeError):
        plan.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        plan.plan_id = "changed"  # type: ignore[misc]


def test_download_execution_contract_imports_no_core_or_gui() -> None:
    source = _DOWNLOAD_EXECUTION_CONTRACT.read_text(encoding="utf-8")
    blocked_imports = (
        "from leonardo." + "core",
        "import leonardo." + "core",
        "from leonardo." + "gui",
        "import leonardo." + "gui",
    )

    for blocked_import in blocked_imports:
        assert blocked_import not in source


def test_download_execution_contract_has_no_runtime_io_or_dependency_imports() -> None:
    source = _DOWNLOAD_EXECUTION_CONTRACT.read_text(encoding="utf-8")
    blocked_tokens = (
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    for token in blocked_tokens:
        assert token not in source


def _plan(
    *,
    plan_id: str = "plan-1",
    request_id: str = "request-1",
    metadata: dict[str, object] | None = None,
) -> DownloadExecutionPlan:
    return DownloadExecutionPlan(
        plan_id=plan_id,
        request_id=request_id,
        workflow_kind="download_data",
        phase=DownloadExecutionPhase.PLANNED,
        operation_id="operation-1",
        task_id="task-1",
        connection_refs=("connection-binance",),
        adapter_ref="adapter-binance",
        storage_policy_ref="ohlcv.v1",
        dataset_refs=(_dataset_ref(),),
        item_ids=("request-1:BTCUSDT:1m",),
        created_at_utc="2026-01-01T00:00:00Z",
        metadata=metadata or {"profile": "default"},
    )


def _output_ref(
    *,
    dataset_ref: str | None = None,
    value_relative_path: str | None = None,
    metadata_relative_path: str | None = None,
) -> DownloadExecutionOutputRef:
    return DownloadExecutionOutputRef(
        request_id="request-1",
        item_id="request-1:BTCUSDT:1m",
        dataset_ref=dataset_ref or _dataset_ref(),
        storage_format="csv",
        value_relative_path=value_relative_path
        or (
            "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/"
            "timeframe=1m/candles.csv"
        ),
        metadata_relative_path=metadata_relative_path
        or (
            "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/"
            "timeframe=1m/candles.meta.json"
        ),
        validation_status="unknown",
        quality_validation_status="not_validated",
    )


def _dataset_ref() -> str:
    return (
        "dataset://ohlcv/v1/provider=binance/market=spot/"
        "symbol=btcusdt/timeframe=1m/basis=raw"
    )
