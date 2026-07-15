"""Canonical OHLCV Maintenance discovery, validation, repair, deletion, and evidence recovery."""

from __future__ import annotations

import calendar
import csv
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import AuditLog
from leonardo.data import (
    MarketId,
    canonicalize_market_id,
    storage_segment_to_timeframe,
    timeframe_duration_ms,
    timeframe_to_storage_segment,
)
from leonardo.ohlcv.models import DownloadItemResult
from leonardo.ohlcv.store import (
    DatasetDeletionEvidence,
    DatasetDeletionResult,
    OHLCVStore,
    SidecarReconstructionResult,
)
from leonardo.ohlcv.validation import (
    CanonicalOHLCVValidator,
    CanonicalValidationReport,
    FileEvidence,
    ValidationCancelled,
    ValidationIssue,
)
from leonardo.storage import OHLCVSidecarV1

_REDOWNLOAD_ANCHOR_CODES = frozenset(
    {
        "duplicate_timestamp",
        "timestamp_out_of_order",
        "low_above_high",
        "open_outside_range",
        "close_outside_range",
        "negative_volume",
        "non_finite_value",
    }
)

_RECONSTRUCTABLE_SIDECAR_CODES = frozenset(
    {
        "sidecar_missing",
        "sidecar_invalid",
        "sidecar_market_mismatch",
        "sidecar_hash_stale",
        "sidecar_fingerprint_stale",
        "sidecar_row_count_mismatch",
        "sidecar_first_timestamp_mismatch",
        "sidecar_last_timestamp_mismatch",
    }
)
_CSV_RECONSTRUCTION_BLOCKERS = frozenset(
    {
        "csv_missing",
        "csv_unreadable",
        "csv_changed_during_validation",
        "csv_header_missing",
        "duplicate_column",
        "missing_column",
        "unexpected_column",
        "column_order_invalid",
        "row_width_invalid",
        "csv_parse_failed",
        "dataset_empty",
        "timestamp_invalid",
        "numeric_value_invalid",
    }
)


@dataclass(frozen=True, slots=True)
class MaintenanceDatasetSummary:
    """Read-only Maintenance summary for one canonical storage location."""

    market_id: MarketId
    csv_path: Path
    sidecar_path: Path
    csv_exists: bool
    sidecar_exists: bool
    persistence_status: str
    validation_status: str
    row_count: int
    source: str
    evidence_state: str
    issues: tuple[str, ...]
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    csv_size_bytes: int | None = None
    csv_modified_time_ns: int | None = None
    file_sha256: str = ""
    sidecar_schema_version: str = ""
    sidecar_created_at_utc: datetime | None = None
    sidecar_updated_at_utc: datetime | None = None
    sidecar_warnings: tuple[str, ...] = ()
    validator_id: str = ""
    validation_error_count: int | None = None
    validation_warning_count: int | None = None


@dataclass(frozen=True, slots=True)
class MaintenanceDiscoveryRejection:
    dataset_dir: Path
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class MaintenanceDiscoveryReport:
    datasets: tuple[MaintenanceDatasetSummary, ...]
    rejected: tuple[MaintenanceDiscoveryRejection, ...]


@dataclass(frozen=True, slots=True)
class MaintenanceValidationResult:
    """Validation report plus the durable publication outcome."""

    report: CanonicalValidationReport
    sidecar: OHLCVSidecarV1 | None
    sidecar_published: bool
    publication_changed: bool
    publication_error: str | None = None

    @property
    def accepted(self) -> bool:
        return bool(
            self.sidecar_published
            and self.sidecar is not None
            and self.sidecar.validation_status == "ok"
        )


@dataclass(frozen=True, slots=True)
class MaintenanceDeletionPlan:
    """Exact reviewed deletion target tied to stable canonical file evidence."""

    market_id: MarketId
    evidence: DatasetDeletionEvidence
    message: str


@dataclass(frozen=True, slots=True)
class MaintenanceDeletionResult:
    """Structured result for one confirmed controlled dataset deletion."""

    plan: MaintenanceDeletionPlan
    store_result: DatasetDeletionResult
    cache_invalidated: bool = False

    @property
    def completed(self) -> bool:
        return self.store_result.csv_deleted and self.store_result.sidecar_deleted


@dataclass(frozen=True, slots=True)
class MaintenanceSidecarReconstructionPlan:
    """Read-only sidecar recovery proposal tied to exact current file evidence."""

    market_id: MarketId
    validation_report: CanonicalValidationReport
    evidence_state: str
    actionable: bool
    message: str
    warnings: tuple[str, ...]
    csv_evidence: FileEvidence | None
    sidecar_evidence: FileEvidence | None
    proposed_source: str = "maintenance_reconstruction"
    proposed_persistence_status: str = "committed"
    proposed_validation_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class MaintenanceSidecarReconstructionResult:
    """Controlled reconstruction plus mandatory canonical post-validation."""

    plan: MaintenanceSidecarReconstructionPlan
    store_result: SidecarReconstructionResult
    validation: MaintenanceValidationResult
    cache_invalidated: bool = False

    @property
    def accepted(self) -> bool:
        return self.validation.accepted


@dataclass(frozen=True, slots=True)
class MaintenanceRepairRange:
    """One reviewed provider-redownload range derived from validation evidence."""

    start_ts_ms: int
    end_ts_ms: int
    reason: str
    issue_codes: tuple[str, ...]
    coverage_anchor_ts_ms: tuple[int, ...]
    estimated_bars: int | None


@dataclass(frozen=True, slots=True)
class MaintenanceRepairPlan:
    """Read-only repair proposal tied to exact CSV and sidecar fingerprints."""

    market_id: MarketId
    validation_report: CanonicalValidationReport
    actionable: bool
    message: str
    ranges: tuple[MaintenanceRepairRange, ...]
    warnings: tuple[str, ...]
    csv_evidence: FileEvidence | None
    sidecar_evidence: FileEvidence | None


@dataclass(frozen=True, slots=True)
class MaintenanceRepairRangeResult:
    repair_range: MaintenanceRepairRange
    fetched_rows: int
    downloaded_first_ts_ms: int | None
    downloaded_last_ts_ms: int | None
    total_rows_after: int
    file_path: Path


@dataclass(frozen=True, slots=True)
class MaintenanceRepairResult:
    """Structured outcome for one explicit reviewed repair execution."""

    plan: MaintenanceRepairPlan
    outcome: str
    range_results: tuple[MaintenanceRepairRangeResult, ...]
    validation: MaintenanceValidationResult
    repaired_sidecar: OHLCVSidecarV1
    warnings: tuple[str, ...]
    source_invalid: bool = False
    source_invalid_anchors: tuple[int, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.outcome == "repaired_ok" and self.validation.accepted


class OHLCVMaintenanceService:
    """Discover, validate, repair, recover evidence, and delete canonical datasets.

    Validation and planning are read-only toward CSV data. Repair mutation is
    executed by the historical downloader and finalized only through
    ``OHLCVStore.mark_repaired`` before canonical post-repair validation.
    Confirmed deletion is executed only through ``OHLCVStore.delete_dataset``.
    Sidecar recovery is executed only through ``OHLCVStore.reconstruct_sidecar``
    and always returns to canonical validation before Research admission.
    """

    def __init__(
        self,
        store: OHLCVStore,
        validator: CanonicalOHLCVValidator,
        *,
        audit_log: AuditLog | None = None,
        actor_id: str | None = None,
    ) -> None:
        if not isinstance(store, OHLCVStore):
            raise TypeError("store must be an OHLCVStore")
        if not isinstance(validator, CanonicalOHLCVValidator):
            raise TypeError("validator must be a CanonicalOHLCVValidator")
        self._store = store
        self._validator = validator
        self._audit_log = audit_log
        self._actor_id = actor_id

    def discover(self) -> MaintenanceDiscoveryReport:
        datasets: list[MaintenanceDatasetSummary] = []
        rejected: list[MaintenanceDiscoveryRejection] = []
        root = self._store.root
        if not root.exists():
            return MaintenanceDiscoveryReport((), ())
        if not root.is_dir():
            raise NotADirectoryError(f"historical root is not a directory: {root}")

        for dataset_dir in self._candidate_directories(root):
            market_or_rejection = self._market_from_dataset_dir(root, dataset_dir)
            if isinstance(market_or_rejection, MaintenanceDiscoveryRejection):
                rejected.append(market_or_rejection)
                continue
            summary = self._summarize(market_or_rejection)
            if not summary.csv_exists and not summary.sidecar_exists:
                rejected.append(
                    MaintenanceDiscoveryRejection(
                        dataset_dir,
                        "empty_dataset_directory",
                        (
                            "canonical dataset directory contains neither candles.csv nor "
                            "candles.meta.json"
                        ),
                    )
                )
                continue
            datasets.append(summary)

        datasets.sort(key=lambda item: _market_sort_key(item.market_id))
        rejected.sort(key=lambda item: (str(item.dataset_dir), item.code))
        return MaintenanceDiscoveryReport(tuple(datasets), tuple(rejected))

    def validate(
        self,
        market: MarketId,
        *,
        correlation_id: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> MaintenanceValidationResult:
        report = self._validator.validate(
            self._store,
            market,
            cancel_requested=cancel_requested,
            progress_callback=progress_callback,
        )
        if cancel_requested is not None and cancel_requested():
            raise ValidationCancelled("canonical OHLCV validation cancelled before publication")
        if not report.publication_allowed:
            self._audit(
                event_type="ohlcv.validation_not_published",
                message=f"Canonical OHLCV validation was not publishable for {market.as_key()}",
                severity="warning" if report.status != "error" else "error",
                correlation_id=correlation_id,
                details={
                    "market_id": market.as_key(),
                    "status": report.status,
                    "issue_codes": report.issue_codes,
                    "publication_blockers": report.publication_blockers,
                },
            )
            return MaintenanceValidationResult(
                report=report,
                sidecar=None,
                sidecar_published=False,
                publication_changed=False,
            )

        csv_evidence = report.csv_evidence
        sidecar_evidence = report.sidecar_evidence
        if csv_evidence is None or sidecar_evidence is None:
            raise RuntimeError("publishable validation report is missing stable file evidence")
        try:
            publication = self._store.publish_validation(
                market,
                expected_csv_size=csv_evidence.size_bytes,
                expected_csv_mtime_ns=csv_evidence.modified_time_ns,
                expected_csv_sha256=csv_evidence.sha256,
                expected_sidecar_size=sidecar_evidence.size_bytes,
                expected_sidecar_mtime_ns=sidecar_evidence.modified_time_ns,
                expected_sidecar_sha256=sidecar_evidence.sha256,
                status=report.status,
                row_count=report.row_count,
                first_timestamp_ms=report.first_timestamp_ms,
                last_timestamp_ms=report.last_timestamp_ms,
                warnings=report.warning_messages,
                issue_codes=report.issue_codes,
                error_count=report.error_count,
                warning_count=report.warning_count,
                validator=self._validator.validator_id,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            message = f"{type(error).__name__}: {error}"
            self._audit(
                event_type="ohlcv.validation_publication_failed",
                message=f"Canonical OHLCV validation publication failed for {market.as_key()}",
                severity="error",
                correlation_id=correlation_id,
                details={
                    "market_id": market.as_key(),
                    "status": report.status,
                    "error": message,
                },
            )
            return MaintenanceValidationResult(
                report=report,
                sidecar=None,
                sidecar_published=False,
                publication_changed=False,
                publication_error=message,
            )

        self._audit(
            event_type="ohlcv.validation_published",
            message=f"Canonical OHLCV validation published for {market.as_key()}",
            severity={"ok": "info", "warning": "warning", "error": "error"}[report.status],
            correlation_id=correlation_id,
            details={
                "market_id": market.as_key(),
                "status": report.status,
                "changed": publication.changed,
                "row_count": report.row_count,
                "issue_codes": report.issue_codes,
            },
        )
        return MaintenanceValidationResult(
            report=report,
            sidecar=publication.sidecar,
            sidecar_published=True,
            publication_changed=publication.changed,
        )

    def plan_deletion(
        self,
        market: MarketId,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceDeletionPlan:
        """Capture the exact canonical files that require explicit confirmation."""

        evidence = self._store.capture_deletion_evidence(market)
        sidecar_text = str(evidence.sidecar.path) if evidence.sidecar is not None else "absent"
        plan = MaintenanceDeletionPlan(
            market_id=market,
            evidence=evidence,
            message=(
                f"Delete {market.as_key()} from canonical OHLCV storage. "
                f"CSV={evidence.csv.path}; sidecar={sidecar_text}."
            ),
        )
        self._audit(
            event_type="ohlcv.deletion_planned",
            message=f"OHLCV dataset deletion prepared for {market.as_key()}",
            severity="warning",
            correlation_id=correlation_id,
            details={
                "market_id": market.as_key(),
                "csv_path": str(evidence.csv.path),
                "csv_sha256": evidence.csv.sha256,
                "sidecar_path": (str(evidence.sidecar.path) if evidence.sidecar else None),
                "sidecar_sha256": (evidence.sidecar.sha256 if evidence.sidecar else None),
            },
        )
        return plan

    def delete_dataset(
        self,
        plan: MaintenanceDeletionPlan,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceDeletionResult:
        """Delete only the exact reviewed canonical files through the Store."""

        if not isinstance(plan, MaintenanceDeletionPlan):
            raise TypeError("plan must be a MaintenanceDeletionPlan")
        store_result = self._store.delete_dataset(plan.evidence)
        result = MaintenanceDeletionResult(plan=plan, store_result=store_result)
        self._audit(
            event_type="ohlcv.dataset_deleted",
            message=f"OHLCV dataset deleted for {plan.market_id.as_key()}",
            severity="warning",
            correlation_id=correlation_id,
            details={
                "market_id": plan.market_id.as_key(),
                "csv_path": str(store_result.csv_path),
                "sidecar_path": str(store_result.sidecar_path),
                "csv_deleted": store_result.csv_deleted,
                "sidecar_deleted": store_result.sidecar_deleted,
                "removed_directories": [str(path) for path in store_result.removed_directories],
                "cleanup_warnings": store_result.cleanup_warnings,
            },
        )
        return result

    def plan_sidecar_reconstruction(
        self,
        market: MarketId,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceSidecarReconstructionPlan:
        """Classify sidecar evidence and prepare a safe explicit recovery plan."""

        report = self._validator.validate(self._store, market)
        codes = set(report.issue_codes)
        evidence_state = _sidecar_evidence_state(self._store, market, report)
        warnings: list[str] = []
        sidecar_problem_codes = codes & _RECONSTRUCTABLE_SIDECAR_CODES
        csv_blockers = codes & _CSV_RECONSTRUCTION_BLOCKERS

        actionable = bool(
            sidecar_problem_codes
            and report.csv_evidence is not None
            and report.row_count > 0
            and not csv_blockers
            and (
                not self._store.sidecar_path(market).exists()
                or report.sidecar_evidence is not None
            )
            and "persistence_not_final" not in codes
            and "sidecar_unreadable" not in codes
            and "sidecar_changed_during_validation" not in codes
            and not (
                report.first_timestamp_ms is not None
                and report.last_timestamp_ms is not None
                and report.first_timestamp_ms > report.last_timestamp_ms
            )
        )
        if csv_blockers:
            warnings.append(
                "CSV structure is not safe for evidence reconstruction: "
                + ", ".join(sorted(csv_blockers))
            )
        if "persistence_not_final" in codes:
            warnings.append(
                "A partial sidecar cannot be promoted to committed by reconstruction."
            )
        if "sidecar_unreadable" in codes:
            warnings.append(
                "The existing sidecar could not be fingerprinted safely and remains inspect-only."
            )
        if "sidecar_changed_during_validation" in codes:
            warnings.append("The sidecar changed during inspection; prepare a new plan later.")
        if (
            report.first_timestamp_ms is not None
            and report.last_timestamp_ms is not None
            and report.first_timestamp_ms > report.last_timestamp_ms
        ):
            warnings.append(
                "The first CSV timestamp is later than the last timestamp; SidecarV1 cannot "
                "represent this evidence safely."
            )

        if actionable:
            message = (
                f"Sidecar reconstruction is available for {market.as_key()}: "
                f"{evidence_state}. The replacement will be committed/unknown and "
                "canonical validation will run immediately afterward."
            )
        elif evidence_state == "complete":
            message = "Current sidecar evidence does not require reconstruction."
        elif evidence_state == "orphan_sidecar":
            message = "Sidecar-only orphan is inspect-only because candles.csv is missing."
        else:
            message = (
                "Sidecar reconstruction is blocked because stable, canonical, parseable "
                "CSV evidence and safely reviewable sidecar state are required."
            )
        plan = MaintenanceSidecarReconstructionPlan(
            market_id=market,
            validation_report=report,
            evidence_state=evidence_state,
            actionable=actionable,
            message=message,
            warnings=tuple(dict.fromkeys(warnings)),
            csv_evidence=report.csv_evidence,
            sidecar_evidence=report.sidecar_evidence,
        )
        self._audit(
            event_type="ohlcv.sidecar_reconstruction_planned",
            message=f"OHLCV sidecar reconstruction reviewed for {market.as_key()}",
            severity="warning" if plan.actionable else "info",
            correlation_id=correlation_id,
            details={
                "market_id": market.as_key(),
                "evidence_state": evidence_state,
                "actionable": actionable,
                "issue_codes": report.issue_codes,
                "warnings": plan.warnings,
            },
        )
        return plan

    def reconstruct_sidecar(
        self,
        plan: MaintenanceSidecarReconstructionPlan,
        *,
        correlation_id: str | None = None,
    ) -> SidecarReconstructionResult:
        """Persist the exact reviewed replacement sidecar through the Store."""

        if not isinstance(plan, MaintenanceSidecarReconstructionPlan):
            raise TypeError("plan must be a MaintenanceSidecarReconstructionPlan")
        if not plan.actionable or plan.csv_evidence is None:
            raise ValueError("sidecar reconstruction plan is not actionable")
        csv_evidence = plan.csv_evidence
        sidecar_evidence = plan.sidecar_evidence
        result = self._store.reconstruct_sidecar(
            plan.market_id,
            expected_csv_size=csv_evidence.size_bytes,
            expected_csv_mtime_ns=csv_evidence.modified_time_ns,
            expected_csv_sha256=csv_evidence.sha256,
            expected_sidecar_size=(sidecar_evidence.size_bytes if sidecar_evidence else None),
            expected_sidecar_mtime_ns=(
                sidecar_evidence.modified_time_ns if sidecar_evidence else None
            ),
            expected_sidecar_sha256=(sidecar_evidence.sha256 if sidecar_evidence else None),
            reconstruction_reason=plan.evidence_state,
        )
        self._audit(
            event_type="ohlcv.sidecar_reconstructed",
            message=f"OHLCV sidecar reconstructed for {plan.market_id.as_key()}",
            severity="warning",
            correlation_id=correlation_id,
            details={
                "market_id": plan.market_id.as_key(),
                "evidence_state": plan.evidence_state,
                "replaced_existing": result.replaced_existing,
                "csv_sha256": result.sidecar.file_sha256,
                "source": result.sidecar.source,
                "persistence_status": result.sidecar.persistence_status,
                "validation_status": result.sidecar.validation_status,
            },
        )
        return result

    def plan_repair(
        self,
        market: MarketId,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceRepairPlan:
        """Build a read-only provider-redownload plan from current validation issues."""

        report = self._validator.validate(self._store, market)
        warnings: list[str] = []
        ranges: tuple[MaintenanceRepairRange, ...] = ()
        if report.csv_evidence is None or report.sidecar_evidence is None:
            warnings.append(
                "Repair planning requires stable readable CSV and sidecar evidence; "
                f"blockers={', '.join(report.publication_blockers) or 'unknown'}."
            )
        else:
            try:
                row_timestamps = _read_row_timestamps(report.csv_path)
            except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as error:
                warnings.append(
                    "Repair planning requires a canonical parseable CSV: "
                    f"{type(error).__name__}: {error}"
                )
            else:
                ranges, range_warnings = _repair_ranges_from_report(
                    report,
                    row_timestamps=row_timestamps,
                )
                warnings.extend(range_warnings)

        if report.status == "ok":
            message = "No validation issues detected; no repair is required."
        elif ranges:
            message = (
                f"{len(ranges)} provider-redownload range(s) are available for explicit repair."
            )
        else:
            message = (
                "No safe provider-redownload range could be derived. "
                "Unsupported structural or unparseable defects remain read-only."
            )
        plan = MaintenanceRepairPlan(
            market_id=market,
            validation_report=report,
            actionable=bool(ranges),
            message=message,
            ranges=ranges,
            warnings=tuple(dict.fromkeys(warnings)),
            csv_evidence=report.csv_evidence,
            sidecar_evidence=report.sidecar_evidence,
        )
        self._audit(
            event_type="ohlcv.repair_planned",
            message=f"OHLCV repair plan prepared for {market.as_key()}",
            severity="info" if plan.actionable else "warning",
            correlation_id=correlation_id,
            details={
                "market_id": market.as_key(),
                "actionable": plan.actionable,
                "range_count": len(plan.ranges),
                "issue_codes": report.issue_codes,
                "warnings": plan.warnings,
            },
        )
        return plan

    def assert_repair_plan_current(self, plan: MaintenanceRepairPlan) -> None:
        if not isinstance(plan, MaintenanceRepairPlan):
            raise TypeError("plan must be a MaintenanceRepairPlan")
        if not plan.actionable or not plan.ranges:
            raise ValueError("repair plan has no actionable ranges")
        current = self._validator.validate(self._store, plan.market_id)
        if plan.csv_evidence is None or plan.sidecar_evidence is None:
            raise ValueError("repair plan is missing stable source evidence")
        if current.csv_evidence != plan.csv_evidence:
            raise ValueError("repair plan is stale because candles.csv changed after planning")
        if current.sidecar_evidence != plan.sidecar_evidence:
            raise ValueError("repair plan is stale because candles.meta.json changed after planning")
        current_codes = set(current.issue_codes)
        planned_codes = {
            code for repair_range in plan.ranges for code in repair_range.issue_codes
        }
        if not planned_codes <= current_codes:
            raise ValueError("repair plan is stale because validation findings changed after planning")

    def mark_repair_completed(
        self,
        plan: MaintenanceRepairPlan,
        range_results: tuple[MaintenanceRepairRangeResult, ...],
        *,
        correlation_id: str | None = None,
    ) -> OHLCVSidecarV1:
        if len(range_results) != len(plan.ranges):
            raise ValueError("all planned repair ranges must complete before repair finalization")
        record = {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "source_csv_sha256": plan.csv_evidence.sha256 if plan.csv_evidence else None,
            "source_csv_size": plan.csv_evidence.size_bytes if plan.csv_evidence else None,
            "ranges": [
                {
                    "start_ts_ms": item.repair_range.start_ts_ms,
                    "end_ts_ms": item.repair_range.end_ts_ms,
                    "issue_codes": list(item.repair_range.issue_codes),
                    "coverage_anchor_ts_ms": list(item.repair_range.coverage_anchor_ts_ms),
                    "fetched_rows": item.fetched_rows,
                    "downloaded_first_ts_ms": item.downloaded_first_ts_ms,
                    "downloaded_last_ts_ms": item.downloaded_last_ts_ms,
                }
                for item in range_results
            ],
        }
        sidecar = self._store.mark_repaired(plan.market_id, repair_record=record)
        self._audit(
            event_type="ohlcv.repair_persisted",
            message=f"OHLCV repair persistence finalized for {plan.market_id.as_key()}",
            severity="info",
            correlation_id=correlation_id,
            details={
                "market_id": plan.market_id.as_key(),
                "range_count": len(range_results),
                "fetched_rows": sum(item.fetched_rows for item in range_results),
                "file_sha256": sidecar.file_sha256,
            },
        )
        return sidecar

    def build_repair_result(
        self,
        plan: MaintenanceRepairPlan,
        range_results: tuple[MaintenanceRepairRangeResult, ...],
        repaired_sidecar: OHLCVSidecarV1,
        validation: MaintenanceValidationResult,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceRepairResult:
        warnings: list[str] = []
        no_replacement_rows = any(item.fetched_rows == 0 for item in range_results)
        coverage_missing = False
        for item in range_results:
            anchors = item.repair_range.coverage_anchor_ts_ms
            if not anchors:
                continue
            first = item.downloaded_first_ts_ms
            last = item.downloaded_last_ts_ms
            missing = (
                first is None
                or last is None
                or any(not first <= anchor <= last for anchor in anchors)
            )
            if missing:
                coverage_missing = True
                warnings.append(
                    "Downloaded coverage did not include all required repair anchors for "
                    f"{item.repair_range.start_ts_ms}..{item.repair_range.end_ts_ms}."
                )
        source_invalid_anchors = _source_invalid_anchors(
            range_results,
            validation.report,
        )
        if source_invalid_anchors:
            issues_by_timestamp = _error_issues_by_timestamp(validation.report)
            for timestamp_ms in source_invalid_anchors:
                issue_text = "; ".join(
                    f"{issue.code}: {issue.message}"
                    for issue in issues_by_timestamp[timestamp_ms]
                )
                warnings.append(
                    f"Source-invalid provider candle detected at ts_ms {timestamp_ms}: "
                    f"{issue_text}. The reviewed range was redownloaded and covered this "
                    "validation anchor, but the replacement candle remains invalid. "
                    "No local correction was applied."
                )

        if validation.accepted:
            outcome = "repaired_ok"
        elif validation.publication_error:
            outcome = "publication_failed"
        elif no_replacement_rows:
            outcome = "no_replacement_rows"
        elif coverage_missing:
            outcome = "coverage_missing_anchor"
        elif source_invalid_anchors:
            outcome = "source_invalid"
        elif validation.report.status == "warning":
            outcome = "repaired_warning"
        else:
            outcome = "validation_failed"
        result = MaintenanceRepairResult(
            plan=plan,
            outcome=outcome,
            range_results=range_results,
            validation=validation,
            repaired_sidecar=repaired_sidecar,
            warnings=tuple(dict.fromkeys(warnings)),
            source_invalid=outcome == "source_invalid",
            source_invalid_anchors=source_invalid_anchors,
        )
        self._audit(
            event_type="ohlcv.repair_completed",
            message=f"OHLCV repair completed for {plan.market_id.as_key()}: {outcome}",
            severity="info" if outcome == "repaired_ok" else "warning",
            correlation_id=correlation_id,
            details={
                "market_id": plan.market_id.as_key(),
                "outcome": outcome,
                "range_count": len(range_results),
                "validation_status": validation.report.status,
                "accepted": validation.accepted,
                "source_invalid": result.source_invalid,
                "source_invalid_anchors": result.source_invalid_anchors,
                "warnings": result.warnings,
            },
        )
        return result

    def _summarize(self, market: MarketId) -> MaintenanceDatasetSummary:
        inspection = self._store.inspect(market)
        persistence_status = "missing"
        validation_status = "missing"
        source = inspection.source
        evidence_state = "complete"
        issues = list(inspection.issues)
        first_timestamp_ms = inspection.first_ts_ms
        last_timestamp_ms = inspection.last_ts_ms
        csv_size_bytes: int | None = None
        csv_modified_time_ns: int | None = None
        file_sha256 = ""
        sidecar_schema_version = ""
        sidecar_created_at_utc: datetime | None = None
        sidecar_updated_at_utc: datetime | None = None
        sidecar_warnings: tuple[str, ...] = ()
        validator_id = ""
        validation_error_count: int | None = None
        validation_warning_count: int | None = None
        if inspection.csv_exists:
            try:
                csv_stat = inspection.csv_path.stat()
            except OSError:
                pass
            else:
                csv_size_bytes = csv_stat.st_size
                csv_modified_time_ns = csv_stat.st_mtime_ns
        if not inspection.csv_exists and inspection.metadata_exists:
            evidence_state = "orphan_sidecar"
        elif inspection.csv_exists and not inspection.metadata_exists:
            evidence_state = "sidecar_missing"
        if inspection.metadata_exists:
            try:
                sidecar = self._store.read_sidecar(market)
            except (OSError, TypeError, ValueError) as error:
                persistence_status = "invalid"
                validation_status = "invalid"
                evidence_state = (
                    "orphan_sidecar" if not inspection.csv_exists else "sidecar_invalid"
                )
                issues.append(f"sidecar_invalid:{type(error).__name__}")
            else:
                persistence_status = sidecar.persistence_status
                validation_status = sidecar.validation_status
                source = sidecar.source
                first_timestamp_ms = sidecar.first_timestamp_ms
                last_timestamp_ms = sidecar.last_timestamp_ms
                file_sha256 = sidecar.file_sha256
                sidecar_schema_version = sidecar.schema_version
                sidecar_created_at_utc = sidecar.created_at_utc
                sidecar_updated_at_utc = sidecar.updated_at_utc
                sidecar_warnings = sidecar.warnings
                validation_summary = sidecar.lineage.get("canonical_validation")
                if isinstance(validation_summary, Mapping):
                    raw_validator = validation_summary.get("validator")
                    if isinstance(raw_validator, str):
                        validator_id = raw_validator.strip()
                    raw_errors = validation_summary.get("error_count")
                    if type(raw_errors) is int:
                        validation_error_count = raw_errors
                    raw_warnings = validation_summary.get("warning_count")
                    if type(raw_warnings) is int:
                        validation_warning_count = raw_warnings
                if not inspection.csv_exists:
                    evidence_state = "orphan_sidecar"
                elif sidecar.persistence_status == "partial":
                    evidence_state = "partial_persistence"
                elif inspection.issues:
                    evidence_state = "sidecar_stale"
        return MaintenanceDatasetSummary(
            market_id=market,
            csv_path=inspection.csv_path,
            sidecar_path=inspection.sidecar_path,
            csv_exists=inspection.csv_exists,
            sidecar_exists=inspection.metadata_exists,
            persistence_status=persistence_status,
            validation_status=validation_status,
            row_count=inspection.row_count,
            source=source,
            evidence_state=evidence_state,
            issues=tuple(dict.fromkeys(issues)),
            first_timestamp_ms=first_timestamp_ms,
            last_timestamp_ms=last_timestamp_ms,
            csv_size_bytes=csv_size_bytes,
            csv_modified_time_ns=csv_modified_time_ns,
            file_sha256=file_sha256,
            sidecar_schema_version=sidecar_schema_version,
            sidecar_created_at_utc=sidecar_created_at_utc,
            sidecar_updated_at_utc=sidecar_updated_at_utc,
            sidecar_warnings=sidecar_warnings,
            validator_id=validator_id,
            validation_error_count=validation_error_count,
            validation_warning_count=validation_warning_count,
        )

    @staticmethod
    def _candidate_directories(root: Path) -> tuple[Path, ...]:
        candidates = {path for path in root.rglob("ohlcv") if path.is_dir()}
        for filename in ("candles.csv", "candles.meta.json"):
            candidates.update(path.parent for path in root.rglob(filename) if path.is_file())
        return tuple(sorted(candidates, key=str))

    def _market_from_dataset_dir(
        self,
        root: Path,
        dataset_dir: Path,
    ) -> MarketId | MaintenanceDiscoveryRejection:
        relative = dataset_dir.relative_to(root)
        if len(relative.parts) != 5 or relative.parts[-1] != "ohlcv":
            return MaintenanceDiscoveryRejection(
                dataset_dir,
                "storage_layout_invalid",
                "expected <exchange>/<market_type>/<symbol>/<timeframe>/ohlcv",
            )
        exchange, market_type, symbol, timeframe_segment, _ = relative.parts
        try:
            timeframe = storage_segment_to_timeframe(timeframe_segment)
            market = canonicalize_market_id(exchange, market_type, symbol, timeframe)
        except ValueError as error:
            return MaintenanceDiscoveryRejection(
                dataset_dir,
                "storage_identity_invalid",
                f"storage path does not define a valid MarketId: {error}",
            )
        canonical_parts = (
            market.exchange,
            market.market_type,
            market.symbol,
            timeframe_to_storage_segment(market.timeframe),
            "ohlcv",
        )
        if relative.parts != canonical_parts or dataset_dir != self._store.dataset_dir(market):
            return MaintenanceDiscoveryRejection(
                dataset_dir,
                "noncanonical_storage_identity",
                f"canonical storage path is {'/'.join(canonical_parts)}",
            )
        return market

    def _audit(
        self,
        *,
        event_type: str,
        message: str,
        severity: str,
        correlation_id: str | None,
        details: dict[str, object],
    ) -> None:
        if self._audit_log is None:
            return
        self._audit_log.emit(
            AuditEventV1(
                event_type=event_type,
                category="ohlcv",
                severity=severity,
                message=message,
                actor_id=self._actor_id,
                correlation_id=correlation_id,
                details=details,
            )
        )


def _error_issues_by_timestamp(
    report: CanonicalValidationReport,
) -> dict[int, tuple[ValidationIssue, ...]]:
    issues_by_timestamp: dict[int, list[ValidationIssue]] = {}
    for issue in report.issues:
        if issue.severity != "error" or issue.timestamp_ms is None:
            continue
        issues_by_timestamp.setdefault(issue.timestamp_ms, []).append(issue)
    return {
        timestamp_ms: tuple(issues)
        for timestamp_ms, issues in issues_by_timestamp.items()
    }


def _source_invalid_anchors(
    range_results: tuple[MaintenanceRepairRangeResult, ...],
    report: CanonicalValidationReport,
) -> tuple[int, ...]:
    """Return reviewed anchors still invalid after covered provider replacement."""

    if report.status != "error":
        return ()
    issues_by_timestamp = _error_issues_by_timestamp(report)
    if not issues_by_timestamp:
        return ()
    anchors: set[int] = set()
    for item in range_results:
        if item.fetched_rows <= 0:
            continue
        first = item.downloaded_first_ts_ms
        last = item.downloaded_last_ts_ms
        if first is None or last is None:
            continue
        for timestamp_ms in item.repair_range.coverage_anchor_ts_ms:
            if first <= timestamp_ms <= last and timestamp_ms in issues_by_timestamp:
                anchors.add(timestamp_ms)
    return tuple(sorted(anchors))


def _repair_ranges_from_report(
    report: CanonicalValidationReport,
    *,
    row_timestamps: tuple[int, ...],
) -> tuple[tuple[MaintenanceRepairRange, ...], tuple[str, ...]]:
    step_ms = timeframe_duration_ms(report.market_id.timeframe)
    month_step = (
        int(report.market_id.timeframe[:-1])
        if report.market_id.timeframe.endswith("M")
        else None
    )
    candidates: list[MaintenanceRepairRange] = []
    warnings: list[str] = []
    for issue in report.issues:
        if issue.code == "timeframe_gap":
            gap_range = _gap_repair_range(
                issue,
                row_timestamps=row_timestamps,
                step_ms=step_ms,
                month_step=month_step,
            )
            if gap_range is None:
                warnings.append(f"Could not derive a gap repair range: {issue.message}")
            else:
                candidates.append(gap_range)
            continue
        if issue.code in _REDOWNLOAD_ANCHOR_CODES and issue.timestamp_ms is not None:
            candidates.append(
                _anchor_repair_range(
                    issue,
                    step_ms=step_ms,
                    month_step=month_step,
                )
            )
            continue
        if issue.severity in {"warning", "error"} and issue.code not in {
            "sidecar_hash_stale",
            "sidecar_fingerprint_stale",
            "sidecar_row_count_mismatch",
            "sidecar_first_timestamp_mismatch",
            "sidecar_last_timestamp_mismatch",
        }:
            warnings.append(f"Unsupported repair issue {issue.code}: {issue.message}")
    return _merge_repair_ranges(candidates, step_ms=step_ms), tuple(dict.fromkeys(warnings))


def _gap_repair_range(
    issue: ValidationIssue,
    *,
    row_timestamps: tuple[int, ...],
    step_ms: int | None,
    month_step: int | None,
) -> MaintenanceRepairRange | None:
    if issue.row_number is None or issue.row_number < 3:
        return None
    data_index = issue.row_number - 2
    previous_index = data_index - 1
    if previous_index < 0 or data_index >= len(row_timestamps):
        return None
    previous = row_timestamps[previous_index]
    current = row_timestamps[data_index]
    if step_ms is not None:
        start = previous + step_ms
        end = current - step_ms
        if start > end:
            return None
        estimated = ((end - start) // step_ms) + 1
    elif month_step is not None:
        start = _add_calendar_months(previous, month_step)
        missing: list[int] = []
        cursor = start
        while cursor < current:
            missing.append(cursor)
            cursor = _add_calendar_months(cursor, month_step)
            if len(missing) > 1200:
                raise ValueError("monthly repair range exceeds 1200 missing intervals")
        if not missing:
            return None
        start, end = missing[0], missing[-1]
        estimated = len(missing)
    else:
        return None
    return MaintenanceRepairRange(
        start_ts_ms=start,
        end_ts_ms=end,
        reason=issue.message,
        issue_codes=(issue.code,),
        coverage_anchor_ts_ms=(start, end) if start != end else (start,),
        estimated_bars=estimated,
    )


def _anchor_repair_range(
    issue: ValidationIssue,
    *,
    step_ms: int | None,
    month_step: int | None,
) -> MaintenanceRepairRange:
    assert issue.timestamp_ms is not None
    anchor = int(issue.timestamp_ms)
    if step_ms is not None:
        start = max(0, anchor - step_ms)
        end = anchor + step_ms
        estimated = ((end - start) // step_ms) + 1
    elif month_step is not None:
        start = _add_calendar_months(anchor, -month_step)
        end = _add_calendar_months(anchor, month_step)
        estimated = 3
    else:
        start = end = anchor
        estimated = 1
    return MaintenanceRepairRange(
        start_ts_ms=start,
        end_ts_ms=end,
        reason=issue.message,
        issue_codes=(issue.code,),
        coverage_anchor_ts_ms=(anchor,),
        estimated_bars=estimated,
    )


def _merge_repair_ranges(
    ranges: list[MaintenanceRepairRange],
    *,
    step_ms: int | None,
) -> tuple[MaintenanceRepairRange, ...]:
    if not ranges:
        return ()
    merged: list[MaintenanceRepairRange] = []
    merge_gap = step_ms or 0
    for item in sorted(ranges, key=lambda value: (value.start_ts_ms, value.end_ts_ms)):
        if not merged or item.start_ts_ms > merged[-1].end_ts_ms + merge_gap:
            merged.append(item)
            continue
        previous = merged[-1]
        start = min(previous.start_ts_ms, item.start_ts_ms)
        end = max(previous.end_ts_ms, item.end_ts_ms)
        estimated = None
        if step_ms is not None:
            estimated = ((end - start) // step_ms) + 1
        merged[-1] = MaintenanceRepairRange(
            start_ts_ms=start,
            end_ts_ms=end,
            reason="; ".join(dict.fromkeys((previous.reason, item.reason))),
            issue_codes=tuple(dict.fromkeys(previous.issue_codes + item.issue_codes)),
            coverage_anchor_ts_ms=tuple(
                sorted(set(previous.coverage_anchor_ts_ms + item.coverage_anchor_ts_ms))
            ),
            estimated_bars=estimated,
        )
    return tuple(merged)


def _read_row_timestamps(path: Path) -> tuple[int, ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ("ts_ms", "open", "high", "low", "close", "volume"):
            raise ValueError("repair planning requires the canonical OHLCV CSV header")
        timestamps: list[int] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                timestamps.append(int(row["ts_ms"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid timestamp at CSV line {line_number}") from error
        return tuple(timestamps)


def _add_calendar_months(timestamp_ms: int, months: int) -> int:
    current = datetime.fromtimestamp(timestamp_ms / 1000, UTC)
    month_index = current.year * 12 + (current.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    current_last_day = calendar.monthrange(current.year, current.month)[1]
    target_last_day = calendar.monthrange(year, month)[1]
    day = target_last_day if current.day == current_last_day else min(current.day, target_last_day)
    return int(current.replace(year=year, month=month, day=day).timestamp() * 1000)


def repair_range_result(
    repair_range: MaintenanceRepairRange,
    download_result: DownloadItemResult,
) -> MaintenanceRepairRangeResult:
    return MaintenanceRepairRangeResult(
        repair_range=repair_range,
        fetched_rows=download_result.fetched_rows,
        downloaded_first_ts_ms=download_result.downloaded_first_ts_ms,
        downloaded_last_ts_ms=download_result.downloaded_last_ts_ms,
        total_rows_after=download_result.total_rows,
        file_path=download_result.file_path,
    )


def _sidecar_evidence_state(
    store: OHLCVStore,
    market: MarketId,
    report: CanonicalValidationReport,
) -> str:
    codes = set(report.issue_codes)
    if "csv_missing" in codes and store.sidecar_path(market).is_file():
        return "orphan_sidecar"
    if "sidecar_missing" in codes:
        return "sidecar_missing"
    if "persistence_not_final" in codes:
        return "partial_persistence"
    if "sidecar_unreadable" in codes:
        return "sidecar_unreadable"
    if "sidecar_changed_during_validation" in codes:
        return "sidecar_unstable"
    if "sidecar_invalid" in codes:
        return "sidecar_invalid"
    if codes & {
        "sidecar_market_mismatch",
        "sidecar_hash_stale",
        "sidecar_fingerprint_stale",
        "sidecar_row_count_mismatch",
        "sidecar_first_timestamp_mismatch",
        "sidecar_last_timestamp_mismatch",
    }:
        return "sidecar_stale"
    return "complete"


def _market_sort_key(market: MarketId) -> tuple[str, str, str, str]:
    return market.exchange, market.market_type, market.symbol, market.timeframe
