"""Preliminary post-download OHLCV checks.

This report is informational. It never changes canonical OHLCV acceptance truth;
OHLCV Maintenance will own accepted validation state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from leonardo.data import timeframe_duration_ms
from leonardo.ohlcv.store import Candle, OHLCVStore


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class PreliminaryValidationReport:
    status: str
    row_count: int
    issues: tuple[ValidationIssue, ...]

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(f"{item.severity}:{item.code}:{item.message}" for item in self.issues)


class PreliminaryOHLCVValidator:
    def validate(self, store: OHLCVStore, market) -> PreliminaryValidationReport:
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
                        )
                    )
                elif step is not None and delta != step:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "time_gap",
                            f"expected {step} ms but found {delta} ms before row {row_no}",
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
        status = "error" if any(item.severity == "error" for item in issues) else (
            "warning" if issues else "ok"
        )
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
                ValidationIssue("error", "non_finite", f"non-finite OHLCV value at row {row_no}")
            )
            return
        if candle.low > candle.high:
            issues.append(ValidationIssue("error", "low_above_high", f"low > high at row {row_no}"))
        if not candle.low <= candle.open <= candle.high:
            issues.append(
                ValidationIssue("error", "open_outside_range", f"open outside low/high at row {row_no}")
            )
        if not candle.low <= candle.close <= candle.high:
            issues.append(
                ValidationIssue("error", "close_outside_range", f"close outside low/high at row {row_no}")
            )
        if candle.volume < 0:
            issues.append(ValidationIssue("error", "negative_volume", f"negative volume at row {row_no}"))
