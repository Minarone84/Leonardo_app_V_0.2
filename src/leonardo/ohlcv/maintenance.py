"""Canonical OHLCV Maintenance discovery and validation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from leonardo.audit import AuditEventV1
from leonardo.core.audit_log import AuditLog
from leonardo.data import (
    MarketId,
    canonicalize_market_id,
    storage_segment_to_timeframe,
    timeframe_to_storage_segment,
)
from leonardo.ohlcv.store import OHLCVStore
from leonardo.ohlcv.validation import CanonicalOHLCVValidator, CanonicalValidationReport
from leonardo.storage import OHLCVSidecarV1


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
    issues: tuple[str, ...]


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


class OHLCVMaintenanceService:
    """Discover, validate and publish canonical OHLCV evidence.

    Validation is read-only toward CSV data. Final validation state is written
    only through ``OHLCVStore.publish_validation``.
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
            datasets.append(self._summarize(market_or_rejection))

        datasets.sort(key=lambda item: _market_sort_key(item.market_id))
        rejected.sort(key=lambda item: (str(item.dataset_dir), item.code))
        return MaintenanceDiscoveryReport(tuple(datasets), tuple(rejected))

    def validate(
        self,
        market: MarketId,
        *,
        correlation_id: str | None = None,
    ) -> MaintenanceValidationResult:
        report = self._validator.validate(self._store, market)
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

    def _summarize(self, market: MarketId) -> MaintenanceDatasetSummary:
        inspection = self._store.inspect(market)
        persistence_status = "missing"
        validation_status = "missing"
        source = inspection.source
        issues = list(inspection.issues)
        if inspection.metadata_exists:
            try:
                sidecar = self._store.read_sidecar(market)
            except (OSError, TypeError, ValueError) as error:
                persistence_status = "invalid"
                validation_status = "invalid"
                issues.append(f"sidecar_invalid:{type(error).__name__}")
            else:
                persistence_status = sidecar.persistence_status
                validation_status = sidecar.validation_status
                source = sidecar.source
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
            issues=tuple(dict.fromkeys(issues)),
        )

    @staticmethod
    def _candidate_directories(root: Path) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for exchange_dir in _child_directories(root):
            for market_type_dir in _child_directories(exchange_dir):
                for symbol_dir in _child_directories(market_type_dir):
                    for timeframe_dir in _child_directories(symbol_dir):
                        dataset_dir = timeframe_dir / "ohlcv"
                        if dataset_dir.is_dir():
                            candidates.append(dataset_dir)
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


def _child_directories(path: Path) -> tuple[Path, ...]:
    return tuple(
        sorted((item for item in path.iterdir() if item.is_dir()), key=lambda item: item.name)
    )


def _market_sort_key(market: MarketId) -> tuple[str, str, str, str]:
    return market.exchange, market.market_type, market.symbol, market.timeframe
