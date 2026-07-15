"""Preliminary and canonical OHLCV validation authorities.

The preliminary validator supports defensive post-download feedback only. The
canonical validator owns final OHLCV quality truth for Maintenance. Neither
validator mutates CSV data or durable sidecar evidence.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from leonardo.data import MarketId, canonicalize_market_id, timeframe_duration_ms
from leonardo.ohlcv.store import Candle, OHLCVStore

_CSV_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")
_FINAL_PERSISTENCE_STATUSES = frozenset({"committed", "repaired"})
_SEVERITY_ORDER = {"error": 0, "warning": 1}
_DEFAULT_PROGRESS_INTERVAL_ROWS = 8192


class ValidationCancelled(RuntimeError):
    """Raised when a cooperative canonical validation cancellation is requested."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    row_number: int | None = None
    column: str | None = None
    timestamp_ms: int | None = None

    def __post_init__(self) -> None:
        if self.severity not in _SEVERITY_ORDER:
            raise ValueError("severity must be 'error' or 'warning'")
        if not self.code.strip():
            raise ValueError("code must be non-empty")
        if not self.message.strip():
            raise ValueError("message must be non-empty")
        if self.row_number is not None and self.row_number < 1:
            raise ValueError("row_number must be positive when provided")


@dataclass(frozen=True, slots=True)
class PreliminaryValidationReport:
    status: str
    row_count: int
    issues: tuple[ValidationIssue, ...]

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(f"{item.severity}:{item.code}:{item.message}" for item in self.issues)


@dataclass(frozen=True, slots=True)
class FileEvidence:
    """Stable evidence captured for one file during validation."""

    path: Path
    size_bytes: int
    modified_time_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CanonicalValidationReport:
    """Deterministic final-quality result for one canonical OHLCV dataset."""

    market_id: MarketId
    csv_path: Path
    sidecar_path: Path
    status: str
    row_count: int
    first_timestamp_ms: int | None
    last_timestamp_ms: int | None
    issues: tuple[ValidationIssue, ...]
    csv_evidence: FileEvidence | None
    sidecar_evidence: FileEvidence | None
    publication_allowed: bool
    publication_blockers: tuple[str, ...]

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.issues)

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.issues)

    @property
    def warning_messages(self) -> tuple[str, ...]:
        return tuple(
            f"{item.code}:{item.message}"
            for item in self.issues
            if item.severity == "warning"
        )

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(f"{item.severity}:{item.code}:{item.message}" for item in self.issues)


class PreliminaryOHLCVValidator:
    """Run defensive post-download checks without publishing acceptance truth."""

    def validate(self, store: OHLCVStore, market: MarketId) -> PreliminaryValidationReport:
        path: Path = store.csv_path(market)
        if not path.is_file():
            return PreliminaryValidationReport(
                status="error",
                row_count=0,
                issues=(ValidationIssue("error", "file_missing", "OHLCV CSV does not exist"),),
            )
        try:
            candles = store.read(market)
        except Exception as error:
            return PreliminaryValidationReport(
                status="error",
                row_count=0,
                issues=(
                    ValidationIssue(
                        "error",
                        "csv_invalid",
                        f"OHLCV CSV could not be parsed: {error}",
                    ),
                ),
            )
        issues: list[ValidationIssue] = []
        if not candles:
            issues.append(ValidationIssue("error", "empty", "OHLCV CSV contains no rows"))
        previous_timestamp: int | None = None
        step = timeframe_duration_ms(market.timeframe)
        for row_no, candle in enumerate(candles, start=2):
            self._validate_candle(candle, row_no, issues)
            if previous_timestamp is not None:
                delta = candle.ts_ms - previous_timestamp
                if delta <= 0:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "timestamp_order",
                            f"timestamp is not strictly increasing at row {row_no}",
                            row_number=row_no,
                            column="ts_ms",
                            timestamp_ms=candle.ts_ms,
                        )
                    )
                elif step is not None and delta != step:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "time_gap",
                            f"expected {step} ms but found {delta} ms before row {row_no}",
                            row_number=row_no,
                            column="ts_ms",
                            timestamp_ms=candle.ts_ms,
                        )
                    )
            previous_timestamp = candle.ts_ms
        if step is None and market.timeframe.endswith("M"):
            issues.append(
                ValidationIssue(
                    "warning",
                    "variable_month",
                    "month candles use variable calendar duration; fixed-step continuity was not checked",
                )
            )
        status = _status_from_issues(issues)
        return PreliminaryValidationReport(status=status, row_count=len(candles), issues=tuple(issues))

    @staticmethod
    def _validate_candle(
        candle: Candle,
        row_no: int,
        issues: list[ValidationIssue],
    ) -> None:
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        if not all(math.isfinite(value) for value in values):
            issues.append(
                ValidationIssue(
                    "error",
                    "non_finite",
                    f"non-finite OHLCV value at row {row_no}",
                    row_number=row_no,
                )
            )
            return
        if candle.low > candle.high:
            issues.append(
                ValidationIssue(
                    "error",
                    "low_above_high",
                    f"low > high at row {row_no}",
                    row_number=row_no,
                    timestamp_ms=candle.ts_ms,
                )
            )
        if not candle.low <= candle.open <= candle.high:
            issues.append(
                ValidationIssue(
                    "error",
                    "open_outside_range",
                    f"open outside low/high at row {row_no}",
                    row_number=row_no,
                    column="open",
                    timestamp_ms=candle.ts_ms,
                )
            )
        if not candle.low <= candle.close <= candle.high:
            issues.append(
                ValidationIssue(
                    "error",
                    "close_outside_range",
                    f"close outside low/high at row {row_no}",
                    row_number=row_no,
                    column="close",
                    timestamp_ms=candle.ts_ms,
                )
            )
        if candle.volume < 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "negative_volume",
                    f"negative volume at row {row_no}",
                    row_number=row_no,
                    column="volume",
                    timestamp_ms=candle.ts_ms,
                )
            )


class CanonicalOHLCVValidator:
    """Own final read-only OHLCV quality truth for Maintenance."""

    validator_id = "canonical_ohlcv_v1"

    def validate(
        self,
        store: OHLCVStore,
        market: MarketId,
        *,
        cancel_requested: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None,
        progress_interval_rows: int = _DEFAULT_PROGRESS_INTERVAL_ROWS,
    ) -> CanonicalValidationReport:
        if not isinstance(store, OHLCVStore):
            raise TypeError("store must be an OHLCVStore")
        _require_canonical_market(market)
        if type(progress_interval_rows) is not int or progress_interval_rows <= 0:
            raise ValueError("progress_interval_rows must be a positive integer")
        _raise_if_cancelled(cancel_requested)

        csv_path = store.csv_path(market)
        sidecar_path = store.sidecar_path(market)
        issues: list[ValidationIssue] = []
        blockers: set[str] = set()
        csv_start: FileEvidence | None = None
        sidecar_start: FileEvidence | None = None
        sidecar_end: FileEvidence | None = None
        sidecar = None

        if not csv_path.is_file():
            issues.append(ValidationIssue("error", "csv_missing", "candles.csv is missing"))
            blockers.add("csv_missing")
        else:
            csv_start = self._capture_evidence(
                csv_path,
                issues=issues,
                blockers=blockers,
                unstable_code="csv_changed_during_validation",
                unreadable_code="csv_unreadable",
                cancel_requested=cancel_requested,
            )

        if not sidecar_path.is_file():
            issues.append(
                ValidationIssue(
                    "error",
                    "sidecar_missing",
                    "candles.meta.json is missing; canonical validation evidence cannot be published",
                )
            )
            blockers.add("sidecar_missing")
        else:
            sidecar_start = self._capture_evidence(
                sidecar_path,
                issues=issues,
                blockers=blockers,
                unstable_code="sidecar_changed_during_validation",
                unreadable_code="sidecar_unreadable",
            )
            try:
                sidecar = store.read_sidecar(market)
            except (OSError, TypeError, ValueError) as error:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_invalid",
                        f"OHLCV sidecar is unreadable or unsupported: {type(error).__name__}: {error}",
                    )
                )
                blockers.add("sidecar_invalid")

        if sidecar is not None:
            if sidecar.market_id != market:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_market_mismatch",
                        f"sidecar MarketId {sidecar.market_id!r} does not match {market!r}",
                    )
                )
                blockers.add("sidecar_market_mismatch")
            if sidecar.persistence_status not in _FINAL_PERSISTENCE_STATUSES:
                issues.append(
                    ValidationIssue(
                        "error",
                        "persistence_not_final",
                        "canonical validation requires persistence_status 'committed' or 'repaired'",
                    )
                )
                blockers.add("persistence_not_final")

        row_count = 0
        first_timestamp_ms: int | None = None
        last_timestamp_ms: int | None = None
        if csv_start is not None:
            expected_rows = sidecar.row_count if sidecar is not None else None
            row_count, first_timestamp_ms, last_timestamp_ms = self._scan_csv(
                csv_path,
                market,
                issues,
                cancel_requested=cancel_requested,
                progress_callback=progress_callback,
                progress_interval_rows=progress_interval_rows,
                expected_rows=expected_rows,
            )
            try:
                csv_after = csv_path.stat()
            except OSError as error:
                issues.append(
                    ValidationIssue(
                        "error",
                        "csv_unreadable",
                        f"candles.csv could not be inspected after validation: {error}",
                    )
                )
                blockers.add("csv_unreadable")
            else:
                if (
                    csv_after.st_size != csv_start.size_bytes
                    or csv_after.st_mtime_ns != csv_start.modified_time_ns
                ):
                    _append_unique_issue(
                        issues,
                        ValidationIssue(
                            "error",
                            "csv_changed_during_validation",
                            "candles.csv changed while canonical validation was running",
                        ),
                    )
                    blockers.add("csv_changed_during_validation")

        if sidecar_start is not None:
            sidecar_end = self._capture_evidence(
                sidecar_path,
                issues=issues,
                blockers=blockers,
                unstable_code="sidecar_changed_during_validation",
                unreadable_code="sidecar_unreadable",
            )
            if sidecar_end is not None and sidecar_end != sidecar_start:
                _append_unique_issue(
                    issues,
                    ValidationIssue(
                        "error",
                        "sidecar_changed_during_validation",
                        "candles.meta.json changed while canonical validation was running",
                    ),
                )
                blockers.add("sidecar_changed_during_validation")

        _raise_if_cancelled(cancel_requested)
        stable_csv_evidence = (
            csv_start if "csv_changed_during_validation" not in blockers else None
        )
        stable_sidecar_evidence = (
            sidecar_start if sidecar_start is not None and sidecar_start == sidecar_end else None
        )

        if sidecar is not None and stable_csv_evidence is not None:
            if sidecar.file_sha256 != stable_csv_evidence.sha256:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_hash_stale",
                        "sidecar SHA-256 does not match the current candles.csv bytes",
                    )
                )
                blockers.add("sidecar_hash_stale")
            lineage_size = sidecar.lineage.get("file_size")
            lineage_mtime = sidecar.lineage.get("file_mtime_ns")
            if (
                lineage_size != stable_csv_evidence.size_bytes
                or lineage_mtime != stable_csv_evidence.modified_time_ns
            ):
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_fingerprint_stale",
                        "sidecar file size or modification-time evidence is stale",
                    )
                )
                blockers.add("sidecar_fingerprint_stale")
            if sidecar.row_count != row_count:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_row_count_mismatch",
                        f"sidecar row_count={sidecar.row_count} but CSV contains {row_count} rows",
                    )
                )
                blockers.add("sidecar_row_count_mismatch")
            if sidecar.first_timestamp_ms != first_timestamp_ms:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_first_timestamp_mismatch",
                        "sidecar first timestamp does not match candles.csv",
                    )
                )
                blockers.add("sidecar_first_timestamp_mismatch")
            if sidecar.last_timestamp_ms != last_timestamp_ms:
                issues.append(
                    ValidationIssue(
                        "error",
                        "sidecar_last_timestamp_mismatch",
                        "sidecar last timestamp does not match candles.csv",
                    )
                )
                blockers.add("sidecar_last_timestamp_mismatch")

        ordered_issues = tuple(sorted(issues, key=_issue_sort_key))
        status = _status_from_issues(ordered_issues)
        publication_allowed = (
            stable_csv_evidence is not None
            and stable_sidecar_evidence is not None
            and sidecar is not None
            and not blockers
        )
        return CanonicalValidationReport(
            market_id=market,
            csv_path=csv_path,
            sidecar_path=sidecar_path,
            status=status,
            row_count=row_count,
            first_timestamp_ms=first_timestamp_ms,
            last_timestamp_ms=last_timestamp_ms,
            issues=ordered_issues,
            csv_evidence=stable_csv_evidence,
            sidecar_evidence=stable_sidecar_evidence,
            publication_allowed=publication_allowed,
            publication_blockers=tuple(sorted(blockers)),
        )

    @staticmethod
    def _capture_evidence(
        path: Path,
        *,
        issues: list[ValidationIssue],
        blockers: set[str],
        unstable_code: str,
        unreadable_code: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> FileEvidence | None:
        try:
            before = path.stat()
            sha256 = _sha256(path, cancel_requested=cancel_requested)
            after = path.stat()
        except OSError as error:
            _append_unique_issue(
                issues,
                ValidationIssue(
                    "error",
                    unreadable_code,
                    f"{path.name} could not be inspected: {type(error).__name__}: {error}",
                ),
            )
            blockers.add(unreadable_code)
            return None
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            _append_unique_issue(
                issues,
                ValidationIssue(
                    "error",
                    unstable_code,
                    f"{path.name} changed while its fingerprint was being captured",
                ),
            )
            blockers.add(unstable_code)
            return None
        return FileEvidence(
            path=path,
            size_bytes=after.st_size,
            modified_time_ns=after.st_mtime_ns,
            sha256=sha256,
        )

    @staticmethod
    def _scan_csv(
        path: Path,
        market: MarketId,
        issues: list[ValidationIssue],
        *,
        cancel_requested: Callable[[], bool] | None,
        progress_callback: Callable[[int, int | None], None] | None,
        progress_interval_rows: int,
        expected_rows: int | None,
    ) -> tuple[int, int | None, int | None]:
        row_count = 0
        first_timestamp: int | None = None
        last_timestamp: int | None = None
        previous_timestamp: int | None = None
        last_reported_row = 0
        fixed_step = timeframe_duration_ms(market.timeframe)
        month_step = int(market.timeframe[:-1]) if market.timeframe.endswith("M") else None

        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if header is None:
                    issues.append(
                        ValidationIssue("error", "csv_header_missing", "candles.csv has no header")
                    )
                    return 0, None, None

                columns = tuple(header)
                duplicates = tuple(
                    column for column in dict.fromkeys(columns) if columns.count(column) > 1
                )
                for column in duplicates:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "duplicate_column",
                            f"CSV header contains duplicate column {column!r}",
                            column=column,
                        )
                    )
                for column in _CSV_COLUMNS:
                    if column not in columns:
                        issues.append(
                            ValidationIssue(
                                "error",
                                "missing_column",
                                f"CSV header is missing required column {column!r}",
                                column=column,
                            )
                        )
                for column in columns:
                    if column not in _CSV_COLUMNS:
                        issues.append(
                            ValidationIssue(
                                "error",
                                "unexpected_column",
                                f"CSV header contains unsupported column {column!r}",
                                column=column,
                            )
                        )
                if columns != _CSV_COLUMNS:
                    issues.append(
                        ValidationIssue(
                            "error",
                            "column_order_invalid",
                            f"CSV columns must be exactly {_CSV_COLUMNS!r}; found {columns!r}",
                        )
                    )

                indexes = {
                    column: columns.index(column)
                    for column in _CSV_COLUMNS
                    if columns.count(column) == 1
                }
                for row_number, row in enumerate(reader, start=2):
                    row_count += 1
                    if row_count % progress_interval_rows == 0:
                        _raise_if_cancelled(cancel_requested)
                        if progress_callback is not None:
                            progress_callback(row_count, expected_rows)
                            last_reported_row = row_count
                    if len(row) != len(columns):
                        issues.append(
                            ValidationIssue(
                                "error",
                                "row_width_invalid",
                                f"row has {len(row)} values but header declares {len(columns)} columns",
                                row_number=row_number,
                            )
                        )
                        continue

                    timestamp = (
                        _parse_timestamp(row[indexes["ts_ms"]], row_number, issues)
                        if "ts_ms" in indexes
                        else None
                    )
                    numeric: dict[str, float] = {}
                    for column in _CSV_COLUMNS[1:]:
                        if column not in indexes:
                            continue
                        value = _parse_number(row[indexes[column]], row_number, column, issues)
                        if value is not None:
                            numeric[column] = value

                    if timestamp is not None:
                        if first_timestamp is None:
                            first_timestamp = timestamp
                        last_timestamp = timestamp
                        if timestamp < 0:
                            issues.append(
                                ValidationIssue(
                                    "error",
                                    "negative_timestamp",
                                    "timestamp must be non-negative",
                                    row_number=row_number,
                                    column="ts_ms",
                                    timestamp_ms=timestamp,
                                )
                            )
                        if previous_timestamp is not None:
                            if timestamp == previous_timestamp:
                                issues.append(
                                    ValidationIssue(
                                        "error",
                                        "duplicate_timestamp",
                                        "timestamp duplicates the previous row",
                                        row_number=row_number,
                                        column="ts_ms",
                                        timestamp_ms=timestamp,
                                    )
                                )
                            elif timestamp < previous_timestamp:
                                issues.append(
                                    ValidationIssue(
                                        "error",
                                        "timestamp_out_of_order",
                                        "timestamp is earlier than the previous row",
                                        row_number=row_number,
                                        column="ts_ms",
                                        timestamp_ms=timestamp,
                                    )
                                )
                            elif fixed_step is not None and timestamp - previous_timestamp != fixed_step:
                                issues.append(
                                    ValidationIssue(
                                        "warning",
                                        "timeframe_gap",
                                        (
                                            f"expected {fixed_step} ms after {previous_timestamp} but "
                                            f"found {timestamp - previous_timestamp} ms"
                                        ),
                                        row_number=row_number,
                                        column="ts_ms",
                                        timestamp_ms=timestamp,
                                    )
                                )
                            elif month_step is not None:
                                expected = _add_calendar_months(previous_timestamp, month_step)
                                if timestamp != expected:
                                    issues.append(
                                        ValidationIssue(
                                            "warning",
                                            "timeframe_gap",
                                            (
                                                f"expected calendar-month timestamp {expected} after "
                                                f"{previous_timestamp} but found {timestamp}"
                                            ),
                                            row_number=row_number,
                                            column="ts_ms",
                                            timestamp_ms=timestamp,
                                        )
                                    )
                        previous_timestamp = timestamp

                    if numeric:
                        _validate_numeric_row(
                            numeric,
                            row_number=row_number,
                            timestamp_ms=timestamp,
                            issues=issues,
                        )
                _raise_if_cancelled(cancel_requested)
                if progress_callback is not None and row_count != last_reported_row:
                    progress_callback(row_count, expected_rows)
        except ValidationCancelled:
            raise
        except (OSError, UnicodeError, csv.Error) as error:
            issues.append(
                ValidationIssue(
                    "error",
                    "csv_parse_failed",
                    f"candles.csv could not be parsed: {type(error).__name__}: {error}",
                )
            )

        if row_count == 0:
            issues.append(ValidationIssue("error", "dataset_empty", "candles.csv contains no rows"))
        return row_count, first_timestamp, last_timestamp


def _validate_numeric_row(
    values: dict[str, float],
    *,
    row_number: int,
    timestamp_ms: int | None,
    issues: list[ValidationIssue],
) -> None:
    non_finite = [column for column, value in values.items() if not math.isfinite(value)]
    for column in non_finite:
        issues.append(
            ValidationIssue(
                "error",
                "non_finite_value",
                f"{column} is not finite",
                row_number=row_number,
                column=column,
                timestamp_ms=timestamp_ms,
            )
        )
    if non_finite:
        return

    price_columns = {"open", "high", "low", "close"}
    if price_columns <= values.keys():
        open_value = values["open"]
        high = values["high"]
        low = values["low"]
        close = values["close"]
        if low > high:
            issues.append(
                ValidationIssue(
                    "error",
                    "low_above_high",
                    "low is greater than high",
                    row_number=row_number,
                    timestamp_ms=timestamp_ms,
                )
            )
        if not low <= open_value <= high:
            issues.append(
                ValidationIssue(
                    "error",
                    "open_outside_range",
                    "open is outside the low/high range",
                    row_number=row_number,
                    column="open",
                    timestamp_ms=timestamp_ms,
                )
            )
        if not low <= close <= high:
            issues.append(
                ValidationIssue(
                    "error",
                    "close_outside_range",
                    "close is outside the low/high range",
                    row_number=row_number,
                    column="close",
                    timestamp_ms=timestamp_ms,
                )
            )
    if "volume" in values and values["volume"] < 0:
        issues.append(
            ValidationIssue(
                "error",
                "negative_volume",
                "volume is negative",
                row_number=row_number,
                column="volume",
                timestamp_ms=timestamp_ms,
            )
        )


def _parse_timestamp(
    value: str,
    row_number: int,
    issues: list[ValidationIssue],
) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "error",
                "timestamp_invalid",
                f"timestamp {value!r} is not an integer",
                row_number=row_number,
                column="ts_ms",
            )
        )
        return None


def _parse_number(
    value: str,
    row_number: int,
    column: str,
    issues: list[ValidationIssue],
) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "error",
                "numeric_value_invalid",
                f"{column} value {value!r} is not numeric",
                row_number=row_number,
                column=column,
            )
        )
        return None


def _add_calendar_months(timestamp_ms: int, months: int) -> int:
    current = datetime.fromtimestamp(timestamp_ms / 1000, UTC)
    month_index = current.year * 12 + (current.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    current_last_day = calendar.monthrange(current.year, current.month)[1]
    target_last_day = calendar.monthrange(year, month)[1]
    day = target_last_day if current.day == current_last_day else min(current.day, target_last_day)
    expected = current.replace(year=year, month=month, day=day)
    return int(expected.timestamp() * 1000)


def _require_canonical_market(market: MarketId) -> None:
    if not isinstance(market, MarketId):
        raise TypeError("market must be a MarketId")
    canonical = canonicalize_market_id(
        market.exchange,
        market.market_type,
        market.symbol,
        market.timeframe,
    )
    if canonical != market:
        raise ValueError(f"market must already be canonical: {canonical!r}")


def _append_unique_issue(issues: list[ValidationIssue], issue: ValidationIssue) -> None:
    if not any(existing.code == issue.code and existing.message == issue.message for existing in issues):
        issues.append(issue)


def _issue_sort_key(issue: ValidationIssue) -> tuple[int, int, str, str, int]:
    return (
        _SEVERITY_ORDER[issue.severity],
        issue.row_number if issue.row_number is not None else 2**31,
        issue.code,
        issue.column or "",
        issue.timestamp_ms if issue.timestamp_ms is not None else -1,
    )


def _status_from_issues(issues) -> str:
    if any(item.severity == "error" for item in issues):
        return "error"
    if any(item.severity == "warning" for item in issues):
        return "warning"
    return "ok"


def _sha256(
    path: Path,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk_number, chunk in enumerate(
            iter(lambda: handle.read(1024 * 1024), b""),
            start=1,
        ):
            digest.update(chunk)
            if chunk_number % 4 == 0:
                _raise_if_cancelled(cancel_requested)
    return digest.hexdigest()


def _raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None and cancel_requested():
        raise ValidationCancelled("canonical OHLCV validation cancelled")
