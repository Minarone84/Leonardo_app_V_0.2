"""Canonical OHLCV CSV and sidecar persistence."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Iterable
from uuid import uuid4

from leonardo.data import MarketId, timeframe_to_storage_segment
from leonardo.storage import OHLCVSidecarV1

_CSV_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class Candle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class DatasetInspection:
    csv_path: Path
    sidecar_path: Path
    csv_exists: bool
    metadata_exists: bool
    metadata_valid: bool
    first_ts_ms: int | None
    last_ts_ms: int | None
    row_count: int
    source: str
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationPublicationResult:
    """Result of one controlled canonical validation-evidence publication."""

    sidecar: OHLCVSidecarV1
    changed: bool


@dataclass(frozen=True, slots=True)
class StoredFileEvidence:
    """Stable fingerprint for one canonical persisted dataset file."""

    path: Path
    size_bytes: int
    modified_time_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DatasetDeletionEvidence:
    """Read-only exact file evidence reviewed before destructive deletion."""

    market_id: MarketId
    dataset_dir: Path
    csv: StoredFileEvidence
    sidecar: StoredFileEvidence | None


@dataclass(frozen=True, slots=True)
class DatasetDeletionResult:
    """Physical deletion outcome from the canonical OHLCV Store."""

    market_id: MarketId
    dataset_dir: Path
    csv_path: Path
    sidecar_path: Path
    csv_deleted: bool
    sidecar_deleted: bool
    removed_directories: tuple[Path, ...]
    cleanup_warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SidecarReconstructionResult:
    """Controlled sidecar reconstruction outcome for one canonical CSV."""

    market_id: MarketId
    sidecar: OHLCVSidecarV1
    replaced_existing: bool


class OHLCVStore:
    """Own the only physical write path for historical OHLCV datasets."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._write_lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def dataset_dir(self, market: MarketId) -> Path:
        return (
            self._root
            / market.exchange
            / market.market_type
            / market.symbol
            / timeframe_to_storage_segment(market.timeframe)
            / "ohlcv"
        )

    def csv_path(self, market: MarketId) -> Path:
        return self.dataset_dir(market) / "candles.csv"

    def sidecar_path(self, market: MarketId) -> Path:
        return self.dataset_dir(market) / "candles.meta.json"

    def inspect(self, market: MarketId) -> DatasetInspection:
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        if not csv_path.is_file():
            return DatasetInspection(
                csv_path=csv_path,
                sidecar_path=sidecar_path,
                csv_exists=False,
                metadata_exists=sidecar_path.is_file(),
                metadata_valid=False,
                first_ts_ms=None,
                last_ts_ms=None,
                row_count=0,
                source="missing",
                issues=("csv_missing",) if sidecar_path.is_file() else (),
            )

        issues: list[str] = []
        metadata_exists = sidecar_path.is_file()
        if metadata_exists:
            try:
                sidecar = self.read_sidecar(market)
                stat = csv_path.stat()
                lineage = sidecar.lineage
                fingerprint_matches = (
                    lineage.get("file_size") == stat.st_size
                    and lineage.get("file_mtime_ns") == stat.st_mtime_ns
                )
                if sidecar.market_id != market:
                    issues.append("metadata_market_mismatch")
                elif not fingerprint_matches:
                    issues.append("metadata_fingerprint_stale")
                else:
                    return DatasetInspection(
                        csv_path=csv_path,
                        sidecar_path=sidecar_path,
                        csv_exists=True,
                        metadata_exists=True,
                        metadata_valid=True,
                        first_ts_ms=sidecar.first_timestamp_ms,
                        last_ts_ms=sidecar.last_timestamp_ms,
                        row_count=sidecar.row_count,
                        source="sidecar",
                        issues=(),
                    )
            except Exception as error:
                issues.append(f"metadata_invalid:{type(error).__name__}")
        first_ts, last_ts, row_count, scan_issues = self._scan_csv_identity(csv_path)
        issues.extend(scan_issues)
        return DatasetInspection(
            csv_path=csv_path,
            sidecar_path=sidecar_path,
            csv_exists=True,
            metadata_exists=metadata_exists,
            metadata_valid=False,
            first_ts_ms=first_ts,
            last_ts_ms=last_ts,
            row_count=row_count,
            source="csv_scan",
            issues=tuple(issues),
        )

    def read(self, market: MarketId) -> list[Candle]:
        path = self.csv_path(market)
        if not path.is_file():
            return []
        candles: list[Candle] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
                raise ValueError(f"invalid OHLCV CSV columns: {reader.fieldnames!r}")
            for line_no, row in enumerate(reader, start=2):
                try:
                    candles.append(
                        Candle(
                            ts_ms=int(row["ts_ms"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                    )
                except (TypeError, ValueError, KeyError) as error:
                    raise ValueError(f"invalid OHLCV row at line {line_no}") from error
        return candles

    def write(
        self,
        market: MarketId,
        candles: Iterable[Candle],
        *,
        source: str,
        persistence_status: str,
        warnings: Iterable[str] = (),
        lineage: dict[str, object] | None = None,
    ) -> OHLCVSidecarV1:
        normalized = merge_idempotent((), candles)
        if not normalized:
            raise ValueError("cannot persist an empty OHLCV dataset")
        with self._write_lock:
            directory = self.dataset_dir(market)
            directory.mkdir(parents=True, exist_ok=True)
            csv_path = self.csv_path(market)
            self._write_csv_atomic(csv_path, normalized)
            return self._write_sidecar_for_existing_csv(
                market,
                normalized,
                source=source,
                persistence_status=persistence_status,
                warnings=warnings,
                lineage=lineage,
            )

    def finalize(
        self,
        market: MarketId,
        *,
        source: str,
        warnings: Iterable[str] = (),
        lineage: dict[str, object] | None = None,
    ) -> OHLCVSidecarV1:
        with self._write_lock:
            candles = self.read(market)
            if not candles:
                raise ValueError("cannot finalize an empty or missing OHLCV dataset")
            return self._write_sidecar_for_existing_csv(
                market,
                candles,
                source=source,
                persistence_status="committed",
                warnings=warnings,
                lineage=lineage,
            )

    def mark_repaired(
        self,
        market: MarketId,
        *,
        repair_record: dict[str, object],
    ) -> OHLCVSidecarV1:
        """Finalize provider-backed repair provenance for a stable current CSV.

        Repair execution may rewrite CSV data through the historical downloader.
        This method owns the controlled transition to ``persistence_status="repaired"``
        and resets final validation truth to ``unknown`` until Maintenance validates
        the repaired bytes canonically.
        """

        if not isinstance(repair_record, dict) or not repair_record:
            raise ValueError("repair_record must be a non-empty dictionary")
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        with self._write_lock:
            before = _stable_file_state(csv_path)
            candles = self.read(market)
            after = _stable_file_state(csv_path)
            if before != after:
                raise RuntimeError("candles.csv changed while repair provenance was finalized")
            if not candles:
                raise ValueError("cannot finalize repair for an empty OHLCV dataset")
            previous = self.read_sidecar(market)
            if previous.market_id != market:
                raise ValueError("sidecar MarketId does not match the repair target")
            if previous.file_sha256 != before[2]:
                raise ValueError("sidecar SHA-256 is stale after repair download")
            lineage = dict(previous.lineage)
            history_value = lineage.get("repair_history", [])
            if not isinstance(history_value, list):
                raise ValueError("existing repair_history lineage must be a list")
            history = list(history_value)
            history.append(dict(repair_record))
            lineage["repair_history"] = history
            lineage["repair_count"] = len(history)
            return self._write_sidecar_for_existing_csv(
                market,
                candles,
                source=previous.source,
                persistence_status="repaired",
                warnings=(),
                lineage=lineage,
            )

    def capture_deletion_evidence(self, market: MarketId) -> DatasetDeletionEvidence:
        """Capture stable canonical file evidence for explicit user review."""

        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        with self._write_lock:
            if not csv_path.is_file():
                raise FileNotFoundError(f"OHLCV CSV not found: {csv_path}")
            csv_state = _stored_file_evidence(csv_path)
            sidecar_state = _stored_file_evidence(sidecar_path) if sidecar_path.is_file() else None
            return DatasetDeletionEvidence(
                market_id=market,
                dataset_dir=self.dataset_dir(market),
                csv=csv_state,
                sidecar=sidecar_state,
            )

    def delete_dataset(
        self,
        evidence: DatasetDeletionEvidence,
    ) -> DatasetDeletionResult:
        """Delete the exact reviewed CSV and optional adjacent sidecar.

        Both canonical files are first renamed to hidden staging names while the
        Store write lock is held. If staging the second file fails, already staged
        files are restored. The reviewed evidence must still match exactly.
        """

        if not isinstance(evidence, DatasetDeletionEvidence):
            raise TypeError("evidence must be DatasetDeletionEvidence")
        market = evidence.market_id
        dataset_dir = self.dataset_dir(market)
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        if evidence.dataset_dir != dataset_dir:
            raise ValueError("deletion evidence dataset directory is not canonical")
        if evidence.csv.path != csv_path:
            raise ValueError("deletion evidence CSV path is not canonical")
        if evidence.sidecar is not None and evidence.sidecar.path != sidecar_path:
            raise ValueError("deletion evidence sidecar path is not canonical")

        with self._write_lock:
            current_csv = _stored_file_evidence(csv_path) if csv_path.is_file() else None
            current_sidecar = (
                _stored_file_evidence(sidecar_path) if sidecar_path.is_file() else None
            )
            if current_csv != evidence.csv:
                raise ValueError("deletion plan is stale because candles.csv changed")
            if current_sidecar != evidence.sidecar:
                raise ValueError("deletion plan is stale because candles.meta.json changed")

            staged: list[tuple[Path, Path]] = []
            token = uuid4().hex
            try:
                for original in (csv_path, sidecar_path):
                    expected = evidence.csv if original == csv_path else evidence.sidecar
                    if expected is None:
                        continue
                    staged_path = original.with_name(f".{original.name}.deleting-{token}")
                    os.replace(original, staged_path)
                    staged.append((original, staged_path))
            except Exception:
                for original, staged_path in reversed(staged):
                    if staged_path.exists() and not original.exists():
                        os.replace(staged_path, original)
                raise

            cleanup_warnings: list[str] = []
            for _original, staged_path in staged:
                try:
                    staged_path.unlink()
                except OSError as error:
                    cleanup_warnings.append(
                        f"staged deletion cleanup failed for {staged_path}: "
                        f"{type(error).__name__}: {error}"
                    )
            removed_directories = _remove_empty_canonical_directories(dataset_dir, self._root)
            return DatasetDeletionResult(
                market_id=market,
                dataset_dir=dataset_dir,
                csv_path=csv_path,
                sidecar_path=sidecar_path,
                csv_deleted=not csv_path.exists(),
                sidecar_deleted=evidence.sidecar is None or not sidecar_path.exists(),
                removed_directories=removed_directories,
                cleanup_warnings=tuple(cleanup_warnings),
            )

    def reconstruct_sidecar(
        self,
        market: MarketId,
        *,
        expected_csv_size: int,
        expected_csv_mtime_ns: int,
        expected_csv_sha256: str,
        expected_sidecar_size: int | None,
        expected_sidecar_mtime_ns: int | None,
        expected_sidecar_sha256: str | None,
        reconstruction_reason: str,
    ) -> SidecarReconstructionResult:
        """Replace missing or defective sidecar evidence for an unchanged CSV.

        Reconstruction never changes candle bytes and never claims provider
        provenance. The new sidecar is deliberately ``committed/unknown`` so
        canonical validation remains the only authority that may accept it.
        """

        if not isinstance(reconstruction_reason, str) or not reconstruction_reason.strip():
            raise ValueError("reconstruction_reason must be a non-empty string")
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)
        expected_csv = (
            expected_csv_size,
            expected_csv_mtime_ns,
            expected_csv_sha256,
        )
        expected_sidecar = None
        if expected_sidecar_size is not None:
            if expected_sidecar_mtime_ns is None or expected_sidecar_sha256 is None:
                raise ValueError("complete expected sidecar evidence is required")
            expected_sidecar = (
                expected_sidecar_size,
                expected_sidecar_mtime_ns,
                expected_sidecar_sha256,
            )
        elif expected_sidecar_mtime_ns is not None or expected_sidecar_sha256 is not None:
            raise ValueError("partial expected sidecar evidence is not allowed")

        with self._write_lock:
            current_csv = _stable_file_state(csv_path)
            if current_csv != expected_csv:
                raise ValueError("reconstruction plan is stale because candles.csv changed")
            current_sidecar = _stable_file_state(sidecar_path) if sidecar_path.is_file() else None
            if current_sidecar != expected_sidecar:
                raise ValueError(
                    "reconstruction plan is stale because candles.meta.json changed"
                )

            candles = self.read(market)
            if not candles:
                raise ValueError("cannot reconstruct a sidecar for an empty OHLCV dataset")
            after_read = _stable_file_state(csv_path)
            if after_read != expected_csv:
                raise RuntimeError("candles.csv changed while sidecar reconstruction was running")

            now = datetime.now(UTC)
            lineage = {
                "file_size": expected_csv_size,
                "file_mtime_ns": expected_csv_mtime_ns,
                "sidecar_reconstruction": {
                    "reconstructed_at_utc": now.isoformat(),
                    "reason": reconstruction_reason.strip(),
                    "replaced_existing": expected_sidecar is not None,
                    "replaced_sidecar_sha256": (
                        expected_sidecar_sha256 if expected_sidecar is not None else None
                    ),
                },
            }
            sidecar = OHLCVSidecarV1(
                market_id=market,
                file_sha256=expected_csv_sha256,
                row_count=len(candles),
                first_timestamp_ms=candles[0].ts_ms,
                last_timestamp_ms=candles[-1].ts_ms,
                source="maintenance_reconstruction",
                persistence_status="committed",
                validation_status="unknown",
                warnings=(
                    "Sidecar reconstructed by Maintenance; canonical validation is required.",
                ),
                lineage=lineage,
                created_at_utc=now,
                updated_at_utc=now,
            )
            self._write_sidecar_atomic(sidecar_path, sidecar)
            return SidecarReconstructionResult(
                market_id=market,
                sidecar=sidecar,
                replaced_existing=expected_sidecar is not None,
            )

    def publish_validation(
        self,
        market: MarketId,
        *,
        expected_csv_size: int,
        expected_csv_mtime_ns: int,
        expected_csv_sha256: str,
        expected_sidecar_size: int,
        expected_sidecar_mtime_ns: int,
        expected_sidecar_sha256: str,
        status: str,
        row_count: int,
        first_timestamp_ms: int | None,
        last_timestamp_ms: int | None,
        warnings: Iterable[str],
        issue_codes: Iterable[str],
        error_count: int,
        warning_count: int,
        validator: str,
    ) -> ValidationPublicationResult:
        """Atomically publish final validation truth for an unchanged dataset.

        The expected CSV and sidecar fingerprints provide optimistic concurrency.
        Any change after validation aborts publication instead of blessing stale or
        contradictory evidence. Repeating the same publication is a no-op.
        """

        if status not in {"ok", "warning", "error"}:
            raise ValueError("status must be 'ok', 'warning', or 'error'")
        if type(row_count) is not int or row_count < 0:
            raise ValueError("row_count must be a non-negative integer")
        if type(error_count) is not int or error_count < 0:
            raise ValueError("error_count must be a non-negative integer")
        if type(warning_count) is not int or warning_count < 0:
            raise ValueError("warning_count must be a non-negative integer")
        if not isinstance(validator, str) or not validator.strip():
            raise ValueError("validator must be a non-empty string")

        normalized_warnings = tuple(str(item).strip() for item in warnings if str(item).strip())
        normalized_codes = tuple(str(item).strip() for item in issue_codes if str(item).strip())
        csv_path = self.csv_path(market)
        sidecar_path = self.sidecar_path(market)

        with self._write_lock:
            current_csv = _stable_file_state(csv_path)
            expected_csv = (expected_csv_size, expected_csv_mtime_ns, expected_csv_sha256)
            if current_csv != expected_csv:
                raise RuntimeError("candles.csv changed after canonical validation")
            current_sidecar = _stable_file_state(sidecar_path)
            expected_sidecar = (
                expected_sidecar_size,
                expected_sidecar_mtime_ns,
                expected_sidecar_sha256,
            )
            if current_sidecar != expected_sidecar:
                raise RuntimeError("candles.meta.json changed after canonical validation")

            previous = self.read_sidecar(market)
            if previous.market_id != market:
                raise ValueError("sidecar MarketId does not match the publication target")
            if previous.persistence_status not in {"committed", "repaired"}:
                raise ValueError("canonical validation may only publish final persisted datasets")
            if previous.file_sha256 != expected_csv_sha256:
                raise ValueError("sidecar SHA-256 is stale; validation publication is forbidden")

            validation_summary = {
                "validator": validator.strip(),
                "status": status,
                "issue_codes": list(normalized_codes),
                "error_count": error_count,
                "warning_count": warning_count,
            }
            lineage = dict(previous.lineage)
            prior_summary = lineage.get("canonical_validation")
            unchanged = (
                previous.validation_status == status
                and previous.row_count == row_count
                and previous.first_timestamp_ms == first_timestamp_ms
                and previous.last_timestamp_ms == last_timestamp_ms
                and previous.warnings == normalized_warnings
                and prior_summary == validation_summary
            )
            if unchanged:
                return ValidationPublicationResult(sidecar=previous, changed=False)

            lineage["file_size"] = expected_csv_size
            lineage["file_mtime_ns"] = expected_csv_mtime_ns
            lineage["canonical_validation"] = validation_summary
            sidecar = OHLCVSidecarV1(
                market_id=market,
                file_sha256=expected_csv_sha256,
                row_count=row_count,
                first_timestamp_ms=first_timestamp_ms,
                last_timestamp_ms=last_timestamp_ms,
                source=previous.source,
                persistence_status=previous.persistence_status,
                validation_status=status,
                warnings=normalized_warnings,
                lineage=lineage,
                created_at_utc=previous.created_at_utc,
                updated_at_utc=datetime.now(UTC),
            )
            self._write_sidecar_atomic(sidecar_path, sidecar)
            return ValidationPublicationResult(sidecar=sidecar, changed=True)

    def _write_sidecar_for_existing_csv(
        self,
        market: MarketId,
        candles: list[Candle],
        *,
        source: str,
        persistence_status: str,
        warnings: Iterable[str],
        lineage: dict[str, object] | None,
    ) -> OHLCVSidecarV1:
        csv_path = self.csv_path(market)
        stat = csv_path.stat()
        previous = self._try_read_sidecar(market)
        created_at = previous.created_at_utc if previous is not None else datetime.now(UTC)
        merged_lineage = dict(lineage or {})
        merged_lineage.update(
            {
                "file_size": stat.st_size,
                "file_mtime_ns": stat.st_mtime_ns,
            }
        )
        sidecar = OHLCVSidecarV1(
            market_id=market,
            file_sha256=_sha256(csv_path),
            row_count=len(candles),
            first_timestamp_ms=candles[0].ts_ms,
            last_timestamp_ms=candles[-1].ts_ms,
            source=source,
            persistence_status=persistence_status,
            validation_status="unknown",
            warnings=tuple(warnings),
            lineage=merged_lineage,
            created_at_utc=created_at,
            updated_at_utc=datetime.now(UTC),
        )
        self._write_sidecar_atomic(self.sidecar_path(market), sidecar)
        return sidecar

    def read_sidecar(self, market: MarketId) -> OHLCVSidecarV1:
        path = self.sidecar_path(market)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("OHLCV sidecar root must be an object")
        return OHLCVSidecarV1.from_dict(payload)

    def _try_read_sidecar(self, market: MarketId) -> OHLCVSidecarV1 | None:
        try:
            return self.read_sidecar(market)
        except Exception:
            return None

    @staticmethod
    def _write_csv_atomic(path: Path, candles: list[Candle]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".candles-", suffix=".csv.tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(_CSV_COLUMNS)
                for candle in candles:
                    writer.writerow(
                        (
                            candle.ts_ms,
                            candle.open,
                            candle.high,
                            candle.low,
                            candle.close,
                            candle.volume,
                        )
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_sidecar_atomic(path: Path, sidecar: OHLCVSidecarV1) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".candles-", suffix=".json.tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(sidecar.to_dict(), handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _scan_csv_identity(path: Path) -> tuple[int | None, int | None, int, tuple[str, ...]]:
        first: int | None = None
        last: int | None = None
        count = 0
        issues: list[str] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != _CSV_COLUMNS:
                    return None, None, 0, ("csv_columns_invalid",)
                for row in reader:
                    timestamp = int(row["ts_ms"])
                    if first is None:
                        first = timestamp
                    last = timestamp
                    count += 1
        except Exception as error:
            issues.append(f"csv_scan_failed:{type(error).__name__}")
        return first, last, count, tuple(issues)


def _stable_file_state(path: Path) -> tuple[int, int, str]:
    before = path.stat()
    sha256 = _sha256(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"{path.name} changed while its fingerprint was captured")
    return after.st_size, after.st_mtime_ns, sha256


def _stored_file_evidence(path: Path) -> StoredFileEvidence:
    size, modified_time_ns, sha256 = _stable_file_state(path)
    return StoredFileEvidence(
        path=path,
        size_bytes=size,
        modified_time_ns=modified_time_ns,
        sha256=sha256,
    )


def _remove_empty_canonical_directories(dataset_dir: Path, root: Path) -> tuple[Path, ...]:
    removed: list[Path] = []
    current = dataset_dir
    canonical_root = root.resolve()
    while current != root:
        try:
            if current.resolve().is_relative_to(canonical_root) is False:
                break
            current.rmdir()
        except OSError:
            break
        removed.append(current)
        current = current.parent
    return tuple(removed)


def merge_idempotent(existing: Iterable[Candle], incoming: Iterable[Candle]) -> list[Candle]:
    """Merge candles by open timestamp; incoming values win on overlap."""

    by_timestamp = {int(item.ts_ms): item for item in existing}
    for item in incoming:
        by_timestamp[int(item.ts_ms)] = Candle(
            ts_ms=int(item.ts_ms),
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=float(item.volume),
        )
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
