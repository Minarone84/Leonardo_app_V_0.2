from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.download_data_boundary import (
    DOWNLOAD_DATA_ARTIFACT_ID,
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
    DownloadDataProgressSummary,
    DownloadDataSelectionDraft,
    DownloadDataSelectionSummary,
    DownloadDataStorageTargetRef,
    DownloadDataValidationStatus,
    DownloadDataWorkflowDescriptor,
    DownloadDataWorkflowStatus,
    DownloadDataWorkloadEstimate,
)
from leonardo.contracts.object_map import ObjectMapSection
from leonardo.core.download_data_boundary_trace import (
    DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND,
    DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID,
    DOWNLOAD_DATA_COMPLETION_OBJECT_KIND,
    DOWNLOAD_DATA_OUTPUT_OBJECT_KIND,
    DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND,
    DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND,
    DOWNLOAD_DATA_PROGRESS_OBJECT_KIND,
    DOWNLOAD_DATA_SELECTION_OBJECT_KIND,
    DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND,
    DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND,
    build_download_data_boundary_trace_provider_descriptor,
    build_download_data_boundary_trace_section,
    download_data_boundary_relationships_from_descriptors,
    download_data_boundary_trace_ref_from_descriptor,
    download_data_boundary_trace_summary_from_descriptor,
    download_data_completion_trace_ref_from_summary,
    download_data_completion_trace_summary_from_summary,
    download_data_output_trace_ref,
    download_data_output_trace_summary,
    download_data_partial_persistence_trace_ref,
    download_data_partial_persistence_trace_summary,
    download_data_preflight_trace_ref_from_summary,
    download_data_preflight_trace_summary_from_summary,
    download_data_progress_trace_ref_from_summary,
    download_data_progress_trace_summary_from_summary,
    download_data_selection_trace_ref_from_draft,
    download_data_selection_trace_summary_from_draft,
    download_data_storage_target_trace_ref,
    download_data_storage_target_trace_summary,
    download_data_workflow_trace_ref_from_descriptor,
    download_data_workflow_trace_summary_from_descriptor,
)
from leonardo.core.object_map_service import (
    ObjectMapProviderEntry,
    ReadOnlyObjectMapService,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRACE_HELPER = _REPO_ROOT / "src" / "leonardo" / "core" / "download_data_boundary_trace.py"
_OBJECT_MAP_SERVICE = _REPO_ROOT / "src" / "leonardo" / "core" / "object_map_service.py"


def test_provider_descriptor_is_read_only_and_mutation_forbidden() -> None:
    descriptor = build_download_data_boundary_trace_provider_descriptor()

    assert descriptor.provider_id == DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID
    assert descriptor.owner_domain == "core"
    assert descriptor.owner_component == "DownloadDataBoundaryTrace"
    assert descriptor.supports_summary_listing is True
    assert descriptor.supports_relationship_listing is True
    assert descriptor.supports_interrogation is False
    assert descriptor.read_only is True
    assert descriptor.mutation_forbidden is True
    assert descriptor.metadata["descriptor_source"] == "explicit_descriptor_inputs"
    assert set(descriptor.object_kinds) >= {
        "download_data_boundary",
        "download_data_workflow",
        "download_data_selection",
        "download_data_preflight",
        "download_data_preflight_item",
        "download_data_progress",
        "download_data_progress_item",
        "download_data_completion",
        "download_data_completion_item",
        "download_data_storage_target",
        "download_data_output",
        "download_data_partial_persistence",
        "provider_capability",
        "storage_policy",
        "operation",
        "task",
        "permission",
        "object_family",
    }


def test_boundary_and_workflow_refs_preserve_download_data_identity() -> None:
    boundary = _boundary()
    workflow = _workflow()

    boundary_ref = download_data_boundary_trace_ref_from_descriptor(boundary)
    workflow_ref = download_data_workflow_trace_ref_from_descriptor(workflow)
    boundary_summary = download_data_boundary_trace_summary_from_descriptor(boundary)
    workflow_summary = download_data_workflow_trace_summary_from_descriptor(workflow)

    assert boundary_ref.object_id == "download_data_boundary"
    assert boundary_ref.object_kind == DOWNLOAD_DATA_BOUNDARY_OBJECT_KIND
    assert boundary_summary.metadata["workflow_ids"] == ("download_data",)
    assert workflow_ref.object_id == "download_data"
    assert workflow_ref.object_kind == DOWNLOAD_DATA_WORKFLOW_OBJECT_KIND
    assert workflow_summary.metadata["provider_capability_refs"] == (
        "bybit.historical_ohlcv",
    )
    assert workflow_summary.metadata["storage_policy_refs"] == (
        "old_leonardo_ohlcv_v1",
    )
    assert workflow_summary.permission_refs == ("download:submit",)


def test_selection_trace_summaries_preserve_selection_fields() -> None:
    draft = _selection_draft()

    ref = download_data_selection_trace_ref_from_draft(draft)
    summary = download_data_selection_trace_summary_from_draft(draft)

    assert ref.object_kind == DOWNLOAD_DATA_SELECTION_OBJECT_KIND
    assert summary.metadata["exchange_id"] == "bybit"
    assert summary.metadata["market_type"] == "linear"
    assert summary.metadata["symbol"] == "BTCUSDT"
    assert summary.metadata["selected_timeframes"] == ("1m", "5m")
    assert summary.metadata["workflow_id"] == "download_data"
    assert summary.lifecycle_status == "complete"


def test_preflight_summary_exposes_mode_counts() -> None:
    preflight = _preflight_summary()

    ref = download_data_preflight_trace_ref_from_summary(preflight)
    summary = download_data_preflight_trace_summary_from_summary(preflight)

    assert ref.object_kind == DOWNLOAD_DATA_PREFLIGHT_OBJECT_KIND
    assert summary.metadata["total_items"] == 5
    assert summary.metadata["new_file_items"] == 1
    assert summary.metadata["update_items"] == 1
    assert summary.metadata["already_current_items"] == 1
    assert summary.metadata["blocked_mode_items"] == 1
    assert summary.metadata["unknown_mode_items"] == 1
    assert summary.metadata["expected_total_bars"] == 30
    assert summary.metadata["expected_total_steps"] == 5


def test_progress_summary_exposes_counts_without_execution_behavior() -> None:
    progress = _progress_summary()

    ref = download_data_progress_trace_ref_from_summary(progress)
    summary = download_data_progress_trace_summary_from_summary(progress)

    assert ref.object_kind == DOWNLOAD_DATA_PROGRESS_OBJECT_KIND
    assert summary.metadata["total_items"] == 3
    assert summary.metadata["completed_items"] == 1
    assert summary.metadata["failed_items"] == 1
    assert summary.metadata["cancelled_items"] == 1
    assert summary.metadata["total_steps"] == 5
    assert summary.metadata["completed_steps"] == 2
    assert summary.operation_refs == ("operation-download-1",)
    assert summary.task_refs == ("task-download-1",)
    assert summary.extra["execution"] == "not_implemented"
    assert not hasattr(summary, "execute")
    assert not hasattr(summary, "cancel")


def test_completion_summary_exposes_output_refs_and_recap_counts() -> None:
    completion = _completion_summary()

    ref = download_data_completion_trace_ref_from_summary(completion)
    summary = download_data_completion_trace_summary_from_summary(completion)

    assert ref.object_kind == DOWNLOAD_DATA_COMPLETION_OBJECT_KIND
    assert summary.metadata["output_ref_count"] == 2
    assert summary.metadata["total_items"] == 2
    assert summary.metadata["completed_items"] == 1
    assert summary.metadata["partial_items"] == 1
    assert summary.extra["execution"] == "not_implemented"


def test_storage_target_and_output_preserve_legacy_naming_policy() -> None:
    target = _storage_target()
    output = _output_ref(
        persistence_status=DownloadDataPersistenceStatus.COMPLETE,
        validation_status=DownloadDataValidationStatus.VALID,
        loadable=True,
        accepted=True,
    )

    target_ref = download_data_storage_target_trace_ref(target)
    target_summary = download_data_storage_target_trace_summary(target)
    output_ref = download_data_output_trace_ref(output)
    output_summary = download_data_output_trace_summary(output)

    expected_csv = "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.csv"
    expected_metadata = (
        "data/historical/bybit/linear/BTCUSDT/1m/ohlcv/candles.meta.json"
    )
    assert target_ref.object_kind == DOWNLOAD_DATA_STORAGE_TARGET_OBJECT_KIND
    assert output_ref.object_kind == DOWNLOAD_DATA_OUTPUT_OBJECT_KIND
    assert target_summary.metadata["artifact_id"] == DOWNLOAD_DATA_ARTIFACT_ID
    assert output_summary.metadata["artifact_id"] == "ohlcv__candles"
    assert target_summary.metadata["csv_path"] == expected_csv
    assert target_summary.metadata["metadata_path"] == expected_metadata
    assert output_summary.metadata["csv_path"] == expected_csv
    assert output_summary.metadata["metadata_path"] == expected_metadata


def test_partial_persistence_trace_does_not_imply_acceptance_or_loadability() -> None:
    partial = _partial_summary()

    ref = download_data_partial_persistence_trace_ref(partial)
    summary = download_data_partial_persistence_trace_summary(partial)

    assert ref.object_kind == DOWNLOAD_DATA_PARTIAL_PERSISTENCE_OBJECT_KIND
    assert summary.metadata["partial"] is True
    assert summary.metadata["accepted"] is False
    assert summary.metadata["loadable"] is False
    assert summary.metadata["validated"] is False
    assert summary.extra["accepted"] is False
    assert summary.extra["loadable"] is False
    assert summary.extra["validated"] is False


def test_relationships_include_boundary_to_workflow_links() -> None:
    pairs = _relationship_pairs(_relationships())

    assert (
        "references",
        "download_data_boundary",
        "download_data_boundary",
        "download_data_workflow",
        "download_data",
    ) in pairs


def test_relationships_include_workflow_dependencies_and_permission_refs() -> None:
    pairs = _relationship_pairs(_relationships())

    assert (
        "references",
        "download_data_workflow",
        "download_data",
        "provider_capability",
        "bybit.historical_ohlcv",
    ) in pairs
    assert (
        "references",
        "download_data_workflow",
        "download_data",
        "storage_policy",
        "old_leonardo_ohlcv_v1",
    ) in pairs
    assert (
        "has_permission",
        "download_data_workflow",
        "download_data",
        "permission",
        "download:submit",
    ) in pairs


def test_operation_and_task_relationships_are_reference_only() -> None:
    relationships = _relationships()
    operation_links = [
        relationship
        for relationship in relationships
        if relationship.target_ref.object_kind == "operation"
    ]
    task_links = [
        relationship
        for relationship in relationships
        if relationship.target_ref.object_kind == "task"
    ]
    source = _TRACE_HELPER.read_text(encoding="utf-8")

    assert operation_links
    assert task_links
    assert operation_links[0].target_ref.metadata["ownership"] == "reference_only"
    assert task_links[0].target_ref.metadata["ownership"] == "reference_only"
    assert "Task" + "Manager" not in source
    assert "Operation" + "Registry" not in source


def test_missing_optional_ids_do_not_create_fake_descriptor_relationships() -> None:
    draft_without_workflow = DownloadDataSelectionDraft(
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        selected_timeframes=("1m",),
    )
    selection = DownloadDataSelectionSummary(
        exchange_id="bybit",
        market_type="linear",
        symbol="ETHUSDT",
        selected_timeframes=("1m",),
    )

    relationships = download_data_boundary_relationships_from_descriptors(
        selection_drafts=(draft_without_workflow,),
        selection_summaries=(selection,),
    )

    assert all(
        relationship.target_ref.object_id not in {"download_data", "ETHUSDT"}
        for relationship in relationships
    )


def test_relationships_are_deterministic_and_deduplicated() -> None:
    relationships = download_data_boundary_relationships_from_descriptors(
        boundary_descriptors=(_boundary(), _boundary()),
        workflow_descriptors=(_workflow(), _workflow()),
        selection_drafts=(_selection_draft(), _selection_draft()),
        selection_summaries=(_selection_summary(),),
        preflight_summaries=(_preflight_summary(),),
        progress_summaries=(_progress_summary(),),
        completion_summaries=(_completion_summary(),),
        storage_targets=(_storage_target(),),
        output_refs=(_output_ref(),),
        partial_persistence_summaries=(_partial_summary(),),
    )
    ids = tuple(relationship.relationship_id for relationship in relationships)

    assert ids == tuple(sorted(ids))
    assert len(ids) == len(set(ids))


def test_section_aggregates_explicit_inputs_only() -> None:
    section = _section()

    assert isinstance(section, ObjectMapSection)
    assert section.section_id == "core.download_data_boundary"
    assert section.provider_id == DOWNLOAD_DATA_BOUNDARY_TRACE_PROVIDER_ID
    assert section.owner_domain == "core"
    assert section.metadata["boundary_count"] == 1
    assert section.metadata["workflow_count"] == 1
    assert section.metadata["selection_draft_count"] == 1
    assert section.metadata["selection_summary_count"] == 1
    assert section.metadata["preflight_summary_count"] == 1
    assert section.metadata["progress_summary_count"] == 1
    assert section.metadata["completion_summary_count"] == 1
    assert section.metadata["storage_target_count"] == 1
    assert section.metadata["output_ref_count"] == 1
    assert section.metadata["partial_persistence_count"] == 1
    assert any(
        summary.object_ref.object_kind == "download_data_preflight_item"
        for summary in section.summaries
    )
    assert any(
        summary.object_ref.object_kind == "download_data_completion_item"
        for summary in section.summaries
    )


def test_section_warnings_blockers_and_errors_derive_from_inputs() -> None:
    boundary = _boundary(warnings=("metadata only",), blockers=("not executable",))
    progress = _progress_summary(warnings=("slow",), errors=("row failed",))

    section = build_download_data_boundary_trace_section(
        boundary_descriptors=(boundary,),
        progress_summaries=(progress,),
    )

    assert (
        "download_data_boundary download_data_boundary: metadata only"
        in section.warnings
    )
    assert (
        "download_data_progress download_data_progress:operation-download-1: slow"
        in section.warnings
    )
    assert (
        "download_data_boundary download_data_boundary: not executable"
        in section.blockers
    )
    assert (
        "download_data_progress download_data_progress:operation-download-1: row failed"
        in section.errors
    )


def test_outputs_are_frozen_and_read_only_through_existing_contracts() -> None:
    section = _section()
    summary = next(
        item
        for item in section.summaries
        if item.object_ref.object_kind == DOWNLOAD_DATA_OUTPUT_OBJECT_KIND
    )

    assert section.extra["mutation_forbidden"] is True
    assert summary.metadata["read_only"] is True
    assert summary.extra["mutation_forbidden"] is True
    with pytest.raises(FrozenInstanceError):
        section.title = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        summary.metadata["read_only"] = False  # type: ignore[index]


def test_no_object_map_service_change_is_required_for_helper() -> None:
    source = _TRACE_HELPER.read_text(encoding="utf-8")
    service_source = _OBJECT_MAP_SERVICE.read_text(encoding="utf-8")

    assert "ReadOnlyObject" + "MapService" not in source
    assert "download_data_boundary" not in service_source


def test_no_registry_discovery_network_or_storage_writer_behavior_exists() -> None:
    source = _TRACE_HELPER.read_text(encoding="utf-8")
    blocked_tokens = (
        "Provider" + "Registry",
        "register" + "_provider",
        "dis" + "cover",
        "pkg" + "util",
        "import" + "lib",
        "os." + "walk",
        "Path." + "rglob",
        "glo" + "bals" + "()",
        "re" + "quests",
        "http" + "x",
        "aio" + "http",
        "web" + "socket",
        "cc" + "xt",
        "by" + "bit",
        "bin" + "ance",
        "sub" + "process",
        "shell" + "=True",
        "soc" + "ket",
        "storage" + "_writer",
    )

    for token in blocked_tokens:
        assert token not in source


def test_source_does_not_import_forbidden_owners_or_gui_modules() -> None:
    source = _TRACE_HELPER.read_text(encoding="utf-8")
    blocked_tokens = (
        "from leonardo." + "gui",
        "import leonardo." + "gui",
        "from leonardo." + "data",
        "from leonardo." + "storage",
        "PySide6",
        "Runtime" + "Manager",
        "Runtime" + "ManagerBackend",
        "ReadOnlyObject" + "MapService",
        "Task" + "Manager",
        "Operation" + "Registry",
        "State" + "Store",
        "Audit" + "Log",
        "CoreRuntime" + "Bridge",
        "Core" + "Runner",
        "Connection" + "Registry",
    )

    for token in blocked_tokens:
        assert token not in source


def test_read_only_object_map_service_can_consume_explicit_provider_entry() -> None:
    provider_descriptor = build_download_data_boundary_trace_provider_descriptor()
    service = ReadOnlyObjectMapService(
        (
            ObjectMapProviderEntry(
                descriptor=provider_descriptor,
                build_section=_section,
            ),
        )
    )

    snapshot = service.build_snapshot(generated_at_utc="2026-01-01T00:00:00+00:00")
    report = service.query()

    assert snapshot.provider_descriptors == (provider_descriptor,)
    assert snapshot.sections[0].provider_id == provider_descriptor.provider_id
    assert snapshot.metadata["section_count"] == 1
    assert report.metadata["summary_count"] == len(snapshot.sections[0].summaries)
    assert any(
        summary.object_ref.object_kind == "download_data_partial_persistence"
        for summary in report.summaries
    )


def _relationships():
    return download_data_boundary_relationships_from_descriptors(
        boundary_descriptors=(_boundary(),),
        workflow_descriptors=(_workflow(),),
        selection_drafts=(_selection_draft(),),
        selection_summaries=(_selection_summary(),),
        preflight_summaries=(_preflight_summary(),),
        progress_summaries=(_progress_summary(),),
        completion_summaries=(_completion_summary(),),
        storage_targets=(_storage_target(),),
        output_refs=(_output_ref(),),
        partial_persistence_summaries=(_partial_summary(),),
    )


def _relationship_pairs(relationships):
    return {
        (
            relationship.relationship_type,
            relationship.source_ref.object_kind,
            relationship.source_ref.object_id,
            relationship.target_ref.object_kind,
            relationship.target_ref.object_id,
        )
        for relationship in relationships
    }


def _section() -> ObjectMapSection:
    return build_download_data_boundary_trace_section(
        boundary_descriptors=(_boundary(),),
        workflow_descriptors=(_workflow(),),
        selection_drafts=(_selection_draft(),),
        selection_summaries=(_selection_summary(),),
        preflight_summaries=(_preflight_summary(),),
        progress_summaries=(_progress_summary(),),
        completion_summaries=(_completion_summary(),),
        storage_targets=(_storage_target(),),
        output_refs=(_output_ref(),),
        partial_persistence_summaries=(_partial_summary(),),
    )


def _boundary(
    *,
    warnings: tuple[str, ...] = (),
    blockers: tuple[str, ...] = (),
) -> DownloadDataBoundaryDescriptor:
    return DownloadDataBoundaryDescriptor(
        boundary_id="download_data_boundary",
        display_name="Download Data Boundary",
        workflow_ids=("download_data",),
        docs_refs=("docs/contracts_docs/DOWNLOAD_DATA_BOUNDARY.md",),
        test_refs=("tests/contracts_test/test_download_data_boundary_contracts.py",),
        warnings=warnings,
        blockers=blockers,
    )


def _workflow() -> DownloadDataWorkflowDescriptor:
    return DownloadDataWorkflowDescriptor(
        workflow_id="download_data",
        display_name="Download Data",
        status=DownloadDataWorkflowStatus.PREFLIGHT_READY,
        required_permission="download:submit",
        provider_capability_refs=("bybit.historical_ohlcv",),
        storage_policy_refs=("old_leonardo_ohlcv_v1",),
        docs_refs=("docs/contracts_docs/DOWNLOAD_DATA_BOUNDARY.md",),
    )


def _selection_draft() -> DownloadDataSelectionDraft:
    return DownloadDataSelectionDraft(
        exchange_id="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        selected_timeframes=("1m", "5m"),
        metadata={"workflow_id": "download_data"},
    )


def _selection_summary(
    *,
    symbol: str = "BTCUSDT",
    selected_timeframes: tuple[str, ...] = ("1m", "5m"),
) -> DownloadDataSelectionSummary:
    return DownloadDataSelectionSummary(
        exchange_id="bybit",
        market_type="linear",
        symbol=symbol,
        selected_timeframes=selected_timeframes,
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
        "persistence_status": DownloadDataPersistenceStatus.NOT_STARTED,
        "validation_status": DownloadDataValidationStatus.UNKNOWN,
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
        "mode": DownloadDataPreflightMode.NEW_FILE,
        "status": DownloadDataItemStatus.READY,
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


def _preflight_summary() -> DownloadDataPreflightSummary:
    items = (
        _preflight_item(
            mode=DownloadDataPreflightMode.NEW_FILE,
            status=DownloadDataItemStatus.READY,
            expected_bars=10,
            expected_steps=2,
        ),
        _preflight_item(
            timeframe="5m",
            mode=DownloadDataPreflightMode.UPDATE_EXISTING,
            status=DownloadDataItemStatus.READY,
            expected_bars=20,
            expected_steps=3,
        ),
        _preflight_item(
            timeframe="15m",
            mode=DownloadDataPreflightMode.ALREADY_CURRENT,
            status=DownloadDataItemStatus.SKIPPED,
            expected_bars=0,
            expected_steps=0,
        ),
        _preflight_item(
            timeframe="1h",
            mode=DownloadDataPreflightMode.BLOCKED,
            status=DownloadDataItemStatus.BLOCKED,
            expected_bars=0,
            expected_steps=0,
        ),
        _preflight_item(
            timeframe="1d",
            mode=DownloadDataPreflightMode.UNKNOWN,
            status=DownloadDataItemStatus.PENDING,
            expected_bars=0,
            expected_steps=0,
        ),
    )
    return DownloadDataPreflightSummary(
        workflow_id="download_data",
        selection_summary=DownloadDataSelectionSummary(
            exchange_id="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            selected_timeframes=("1m", "5m", "15m", "1h", "1d"),
        ),
        items=items,
    )


def _progress_item(**overrides: object) -> DownloadDataProgressItem:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": DownloadDataItemStatus.RUNNING,
        "mode": DownloadDataPreflightMode.NEW_FILE,
        "completed_steps": 1,
        "total_steps": 2,
        "downloaded_bars": 5,
    }
    values.update(overrides)
    return DownloadDataProgressItem(**values)


def _progress_summary(
    *,
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> DownloadDataProgressSummary:
    return DownloadDataProgressSummary(
        workflow_id="download_data",
        operation_id="operation-download-1",
        task_id="task-download-1",
        status=DownloadDataWorkflowStatus.RUNNING,
        items=(
            _progress_item(
                status=DownloadDataItemStatus.COMPLETED,
                completed_steps=2,
                total_steps=2,
            ),
            _progress_item(
                timeframe="5m",
                status=DownloadDataItemStatus.FAILED,
                completed_steps=0,
                total_steps=2,
            ),
            _progress_item(
                timeframe="15m",
                status=DownloadDataItemStatus.CANCELLED,
                completed_steps=0,
                total_steps=1,
            ),
        ),
        warnings=warnings,
        errors=errors,
    )


def _output_ref(**overrides: object) -> DownloadDataOutputRef:
    values = {
        "exchange_id": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "bars_written": 10,
        "persistence_status": DownloadDataPersistenceStatus.NEW_FILE,
        "validation_status": DownloadDataValidationStatus.UNKNOWN,
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
        "mode": DownloadDataPreflightMode.NEW_FILE,
        "status": DownloadDataItemStatus.COMPLETED,
        "output_ref": output_ref,
        "bars_downloaded": output_ref.bars_written,
    }
    values.update(overrides)
    return DownloadDataCompletionItem(**values)


def _completion_summary() -> DownloadDataCompletionSummary:
    complete_output = _output_ref(
        persistence_status=DownloadDataPersistenceStatus.COMPLETE,
        validation_status=DownloadDataValidationStatus.VALID,
        loadable=True,
        accepted=True,
    )
    partial_output = _output_ref(
        timeframe="5m",
        persistence_status=DownloadDataPersistenceStatus.PARTIAL_UPDATE,
        validation_status=DownloadDataValidationStatus.NOT_VALIDATED,
        loadable=False,
        accepted=False,
    )
    return DownloadDataCompletionSummary(
        workflow_id="download_data",
        status=DownloadDataWorkflowStatus.PARTIAL,
        output_refs=(complete_output, partial_output),
        items=(
            _completion_item(output_ref=complete_output),
            _completion_item(
                output_ref=partial_output,
                status=DownloadDataItemStatus.PARTIAL,
            ),
        ),
    )


def _partial_summary() -> DownloadDataPartialPersistenceSummary:
    output_ref = _output_ref(
        timeframe="5m",
        persistence_status=DownloadDataPersistenceStatus.PARTIAL_UPDATE,
        validation_status=DownloadDataValidationStatus.NOT_VALIDATED,
    )
    return DownloadDataPartialPersistenceSummary(
        exchange_id=output_ref.exchange_id,
        market_type=output_ref.market_type,
        symbol=output_ref.symbol,
        timeframe=output_ref.timeframe,
        csv_path=str(output_ref.csv_path),
        metadata_path=str(output_ref.metadata_path),
        partial=True,
        persistence_status=DownloadDataPersistenceStatus.PARTIAL_UPDATE,
        bars_persisted=5,
        resumable=True,
        maintenance_required=True,
    )
