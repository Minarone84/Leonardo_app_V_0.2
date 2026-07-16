"""Universal Trend Classifier indicator runtime.

This module is intentionally compute-only.  It does not import GUI code, does not
own rendering policy, and does not persist artifacts.  Historical computation
requires controller-injected Peaks & Troughs columns while preserving sequential
swing-state trend logic.

Design notes
------------
* Historical mode consumes controller-injected Peaks & Troughs event columns,
  while keeping trend detection as a forward swing-state scan.
* Directional trends and horizontal range discovery may consume different
  confirmed Peaks & Troughs streams. UTC does not infer its own internal
  fractals; realtime integration must feed the same confirmed events that
  historical mode consumes.
* Fractals define horizontal range zones; after a range is active, continuation
  is governed by price acceptance, the configured break mode, and pending
  breakout/reclaim state rather than by requiring more fractals.
* Horizontal ranges and trend intervals may backfill start rows when a pattern is
  confirmed.  The incremental update object reports the affected position span so
  a realtime chart can refresh only the revised rows if desired.
* Invalid bars break active intervals.  No calculation bridges NaN or malformed
  OHLC/source gaps.

The runtime output keys are deliberately stable so Leonardo's contract/naming
layer can describe renderability without the renderer inventing semantics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite, nan
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd


_ANALYSIS_OUTPUT_COLUMNS: Tuple[str, ...] = (
    "horizontal_range",
    "hr_start",
    "hr_end",
    "uptrend",
    "uptrend_start",
    "uptrend_end",
    "downtrend",
    "downtrend_start",
    "downtrend_end",
    "hr_uptrend",
    "hr_downtrend",
    "hr_breakout_attempt",
    "hr_pending_breakout",
    "hr_breakout_confirmed",
    "hr_false_breakout",
    "hr_reclaim",
    "hr_break_direction",
    "hr_break_extreme",
    "hr_reclaim_marker",
)

_RENDERABLE_OUTPUT_COLUMNS: Tuple[str, ...] = (
    "hor_upper",
    "hor_lower",
    "hr_start_marker",
    "hr_end_marker",
    "uptrend_start_marker",
    "uptrend_end_marker",
    "downtrend_start_marker",
    "downtrend_end_marker",
)

_OUTPUT_COLUMNS: Tuple[str, ...] = (
    "horizontal_range",
    "hr_start",
    "hr_end",
    "hor_upper",
    "hor_lower",
    "uptrend",
    "uptrend_start",
    "uptrend_end",
    "downtrend",
    "downtrend_start",
    "downtrend_end",
    "hr_uptrend",
    "hr_downtrend",
    "hr_start_marker",
    "hr_end_marker",
    "uptrend_start_marker",
    "uptrend_end_marker",
    "downtrend_start_marker",
    "downtrend_end_marker",
    "hr_breakout_attempt",
    "hr_pending_breakout",
    "hr_breakout_confirmed",
    "hr_false_breakout",
    "hr_reclaim",
    "hr_break_direction",
    "hr_break_extreme",
    "hr_reclaim_marker",
)

_BOOLEAN_COLUMNS = {
    "horizontal_range",
    "hr_start",
    "hr_end",
    "uptrend",
    "uptrend_start",
    "uptrend_end",
    "downtrend",
    "downtrend_start",
    "downtrend_end",
    "hr_uptrend",
    "hr_downtrend",
    "hr_breakout_attempt",
    "hr_pending_breakout",
    "hr_breakout_confirmed",
    "hr_false_breakout",
    "hr_reclaim",
}

_FLOAT_COLUMNS = set(_OUTPUT_COLUMNS) - _BOOLEAN_COLUMNS


def _default_output_row() -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for name in _OUTPUT_COLUMNS:
        row[name] = False if name in _BOOLEAN_COLUMNS else nan
    return row


def _as_float(value: Any, *, name: str) -> float:
    """Convert a dataframe/bar value to float without accepting bools as numbers."""
    if value is None:
        return nan
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric, got bool")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric, got {value!r}") from exc


def _finite(value: float) -> bool:
    return isinstance(value, (int, float)) and isfinite(float(value))


_HR_BREAK_MODES = {"wick", "close", "hybrid"}


def _normalize_hr_break_mode(value: Any) -> str:
    mode = str(value or "close").strip().lower()
    if mode not in _HR_BREAK_MODES:
        raise ValueError("hr_break_mode must be one of: close, hybrid, wick")
    return mode


def _default_peak_column(fractal_window: int) -> str:
    return f"peak_fractal_{int(fractal_window)}"


def _default_trough_column(fractal_window: int) -> str:
    return f"trough_fractal_{int(fractal_window)}"


def _private_range_dependency_columns(
    columns: Iterable[object],
    range_peak_column: str,
    range_trough_column: str,
) -> Tuple[str, str]:
    used = set(columns)

    def available_name(source_name: str) -> str:
        base = f"__utc_internal_range_{source_name}"
        candidate = base
        suffix = 1
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    return available_name(range_peak_column), available_name(range_trough_column)


@dataclass(frozen=True)
class _Config:
    """Runtime configuration for the Universal Trend Classifier.

    ``fractal_window`` / ``peak_column`` / ``trough_column`` are kept as
    compatibility aliases for the directional trend swing stream. Horizontal
    range discovery can use a faster independent Peaks & Troughs stream.
    """

    source: str = "close"
    high: str = "high"
    low: str = "low"
    close: str = "close"
    fractal_window: int = 5
    trend_fractal_window: int = 5
    range_fractal_window: int = 3
    peak_column: Optional[str] = None
    trough_column: Optional[str] = None
    trend_peak_column: Optional[str] = None
    trend_trough_column: Optional[str] = None
    range_peak_column: Optional[str] = None
    range_trough_column: Optional[str] = None
    min_hr_band_perc: float = 0.005
    hr_trend_length: int = 20
    hr_trend_atr_mult: float = 1.0
    hr_trend_atr_len: int = 500
    hr_trend_tol_mult: float = 0.3
    hr_trend_max_gap: int = 20
    hr_min_inside_ratio: float = 0.8
    min_range_swings: int = 4
    hr_break_mode: str = "close"

    def validate(self) -> None:
        if not self.source:
            raise ValueError("source column name must be non-empty")
        for attr_name in ("high", "low", "close"):
            if not getattr(self, attr_name):
                raise ValueError(f"{attr_name} column name must be non-empty")
        for attr_name in ("min_hr_band_perc", "hr_trend_atr_mult", "hr_trend_tol_mult", "hr_min_inside_ratio"):
            if not _finite(getattr(self, attr_name)):
                raise ValueError(f"{attr_name} must be finite")
        for attr_name in ("fractal_window", "trend_fractal_window", "range_fractal_window"):
            value = int(getattr(self, attr_name))
            if value < 3 or value % 2 != 1:
                raise ValueError(f"{attr_name} must be an odd integer >= 3")
        for attr_name in (
            "peak_column",
            "trough_column",
            "trend_peak_column",
            "trend_trough_column",
            "range_peak_column",
            "range_trough_column",
        ):
            value = getattr(self, attr_name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{attr_name} must be non-empty when provided")
        if self.hr_trend_length < self.range_fractal_window:
            raise ValueError("hr_trend_length must be >= range_fractal_window")
        if self.hr_trend_atr_len < 1:
            raise ValueError("hr_trend_atr_len must be >= 1")
        if self.hr_trend_atr_mult < 0:
            raise ValueError("hr_trend_atr_mult must be >= 0")
        if self.min_hr_band_perc < 0:
            raise ValueError("min_hr_band_perc must be >= 0")
        if self.hr_trend_tol_mult < 0:
            raise ValueError("hr_trend_tol_mult must be >= 0")
        if self.hr_trend_max_gap < 1:
            raise ValueError("hr_trend_max_gap must be >= 1")
        if not (0.0 < self.hr_min_inside_ratio <= 1.0):
            raise ValueError("hr_min_inside_ratio must be within (0, 1]")
        if self.min_range_swings < 4:
            raise ValueError("min_range_swings must be >= 4")
        _normalize_hr_break_mode(self.hr_break_mode)

    @classmethod
    def from_params(
        cls,
        *,
        source: str = "close",
        col: Optional[str] = None,
        high: str = "high",
        low: str = "low",
        close: str = "close",
        fractal_window: int = 5,
        trend_fractal_window: Optional[int] = None,
        range_fractal_window: Optional[int] = None,
        peak_column: Optional[str] = None,
        trough_column: Optional[str] = None,
        trend_peak_column: Optional[str] = None,
        trend_trough_column: Optional[str] = None,
        range_peak_column: Optional[str] = None,
        range_trough_column: Optional[str] = None,
        min_hr_band_perc: float = 0.005,
        hr_trend_length: int = 20,
        hr_trend_atr_mult: float = 1.0,
        hr_trend_atr_len: int = 500,
        hr_trend_tol_mult: float = 0.3,
        hr_trend_max_gap: int = 20,
        hr_min_inside_ratio: float = 0.8,
        min_range_swings: int = 4,
        hr_break_mode: str = "close",
    ) -> "_Config":
        # ``col`` is accepted as a compatibility alias for the pasted prototype.
        trend_window = int(trend_fractal_window if trend_fractal_window is not None else fractal_window)
        range_window = int(range_fractal_window if range_fractal_window is not None else 3)
        cfg = cls(
            source=col or source,
            high=high,
            low=low,
            close=close,
            fractal_window=trend_window,
            trend_fractal_window=trend_window,
            range_fractal_window=range_window,
            peak_column=peak_column,
            trough_column=trough_column,
            trend_peak_column=trend_peak_column,
            trend_trough_column=trend_trough_column,
            range_peak_column=range_peak_column,
            range_trough_column=range_trough_column,
            min_hr_band_perc=float(min_hr_band_perc),
            hr_trend_length=int(hr_trend_length),
            hr_trend_atr_mult=float(hr_trend_atr_mult),
            hr_trend_atr_len=int(hr_trend_atr_len),
            hr_trend_tol_mult=float(hr_trend_tol_mult),
            hr_trend_max_gap=int(hr_trend_max_gap),
            hr_min_inside_ratio=float(hr_min_inside_ratio),
            min_range_swings=int(min_range_swings),
            hr_break_mode=_normalize_hr_break_mode(hr_break_mode),
        )
        cfg.validate()
        return cfg

@dataclass(frozen=True)
class _SwingPoint:
    """A confirmed Peaks & Troughs swing."""

    position: int
    index: Any
    value: float
    kind: str  # "peak" or "trough"
    atr: float


@dataclass(frozen=True)
class _Update:
    """Result of one realtime update.

    ``changed_start`` and ``changed_end`` are inclusive local positions in the
    engine's internal history.  They may point to earlier rows when an external
    swing confirms a past pivot or when a trend/range is backfilled.
    """

    position: int
    index: Any
    changed_start: int
    changed_end: int
    confirmed_swing: Optional[_SwingPoint]
    row: Mapping[str, Any]


@dataclass
class _Bar:
    position: int
    index: Any
    source: float
    high: float
    low: float
    close: float
    atr: float = nan

    @property
    def valid(self) -> bool:
        return _finite(self.source) and _finite(self.high) and _finite(self.low) and _finite(self.close)


@dataclass
class _HorizontalRangeState:
    start_pos: int
    upper: float
    lower: float
    start_value: float = nan
    active_from_pos: Optional[int] = None
    break_seen: bool = False
    break_direction: int = 0


@dataclass
class _PendingHorizontalRangeBreakout:
    start_pos: int
    upper: float
    lower: float
    start_value: float
    break_pos: int
    break_direction: int
    expires_pos: int
    break_extreme: float = nan
    active_from_pos: Optional[int] = None


@dataclass
class _TrendState:
    kind: str  # "uptrend" or "downtrend"
    start_pos: int
    last_peak: Optional[float] = None
    last_trough: Optional[float] = None
    last_swing_pos: int = 0


class _RollingAverage:
    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._values: Deque[float] = deque()
        self._total: float = 0.0

    def push(self, value: float) -> float:
        if not _finite(value):
            return self.value
        self._values.append(float(value))
        self._total += float(value)
        while len(self._values) > self.window:
            self._total -= self._values.popleft()
        return self.value

    @property
    def value(self) -> float:
        if not self._values:
            return nan
        return self._total / len(self._values)

    def clear(self) -> None:
        self._values.clear()
        self._total = 0.0


@dataclass(frozen=True)
class _TrendInterval:
    kind: str  # "uptrend" or "downtrend"
    start_pos: int
    end_pos: int
    start_value: float
    end_value: float


@dataclass(frozen=True)
class _HorizontalRangeInterval:
    start_pos: int
    end_pos: int
    upper: float
    lower: float
    start_value: float
    end_value: float
    closed: bool
    break_direction: int = 0


def _bar_wick_midpoint(bar: _Bar) -> float:
    if not (_finite(bar.high) and _finite(bar.low)):
        return nan
    return (bar.high + bar.low) / 2.0


def _bar_wick_inside(bar: _Bar, lower: float, upper: float) -> bool:
    return _finite(bar.high) and _finite(bar.low) and lower <= bar.low and bar.high <= upper


def _bar_source_inside(bar: _Bar, lower: float, upper: float) -> bool:
    value = bar.source if _finite(bar.source) else bar.close
    return _finite(value) and lower <= value <= upper


def _direction_from_break_flags(above: bool, below: bool, bar: _Bar, lower: float, upper: float) -> int:
    if above and below:
        midpoint = (upper + lower) / 2.0
        value = bar.source if _finite(bar.source) else bar.close
        if _finite(value):
            if value > midpoint:
                return 1
            if value < midpoint:
                return -1
        return 0
    if above:
        return 1
    if below:
        return -1
    return 0


def _bar_wick_outside(bar: _Bar, lower: float, upper: float) -> bool:
    return (_finite(bar.high) and bar.high > upper) or (_finite(bar.low) and bar.low < lower)


def _bar_wick_break_direction(bar: _Bar, lower: float, upper: float) -> int:
    above = _finite(bar.high) and bar.high > upper
    below = _finite(bar.low) and bar.low < lower
    return _direction_from_break_flags(above, below, bar, lower, upper)


def _bar_close_break_direction(bar: _Bar, lower: float, upper: float) -> int:
    value = bar.source if _finite(bar.source) else bar.close
    if not _finite(value):
        return 0
    return _direction_from_break_flags(value > upper, value < lower, bar, lower, upper)


def _bar_breaks_horizontal_range(
    bar: _Bar,
    state: _HorizontalRangeState,
    config: _Config,
    *,
    mutate_state: bool = True,
) -> Tuple[bool, int]:
    if not bar.valid:
        return True, 0

    mode = _normalize_hr_break_mode(config.hr_break_mode)
    if mode == "wick":
        breaks = _bar_wick_outside(bar, state.lower, state.upper)
        direction = _bar_wick_break_direction(bar, state.lower, state.upper) if breaks else 0
        if mutate_state:
            state.break_seen = breaks
            state.break_direction = direction
        return breaks, direction

    close_direction = _bar_close_break_direction(bar, state.lower, state.upper)
    if mode == "close":
        if mutate_state:
            state.break_seen = bool(close_direction)
            state.break_direction = close_direction
        return close_direction != 0, close_direction

    # Hybrid mode treats highs/lows as pressure, not as a one-tick kill switch.
    # One same-side wick probe is tolerated while source remains accepted inside
    # the zone; a repeated probe or a close outside confirms the breakout.
    if close_direction != 0:
        if mutate_state:
            state.break_seen = True
            state.break_direction = close_direction
        return True, close_direction

    wick_breaks = _bar_wick_outside(bar, state.lower, state.upper)
    wick_direction = _bar_wick_break_direction(bar, state.lower, state.upper) if wick_breaks else 0
    if wick_breaks:
        if mutate_state:
            if state.break_seen and state.break_direction == wick_direction:
                return True, wick_direction
            state.break_seen = True
            state.break_direction = wick_direction
        return False, wick_direction

    if mutate_state:
        state.break_seen = False
        state.break_direction = 0
    return False, 0


def _bar_reclaims_pending_breakout(bar: _Bar, pending: _PendingHorizontalRangeBreakout) -> bool:
    return bar.valid and _bar_source_inside(bar, pending.lower, pending.upper)


def _breakout_extreme_for_bar(bar: _Bar, direction: int) -> float:
    if direction > 0:
        return bar.high
    if direction < 0:
        return bar.low
    return bar.source


def _update_pending_breakout_extreme(pending: _PendingHorizontalRangeBreakout, bar: _Bar) -> None:
    value = _breakout_extreme_for_bar(bar, pending.break_direction)
    if not _finite(value):
        return
    if not _finite(pending.break_extreme):
        pending.break_extreme = value
    elif pending.break_direction > 0:
        pending.break_extreme = max(pending.break_extreme, value)
    elif pending.break_direction < 0:
        pending.break_extreme = min(pending.break_extreme, value)
    else:
        pending.break_extreme = value


def _range_mark_start(state: _HorizontalRangeState) -> int:
    return state.active_from_pos if state.active_from_pos is not None else state.start_pos


def _pending_breakout_state(
    pending: _PendingHorizontalRangeBreakout,
    *,
    active_from_pos: Optional[int] = None,
) -> _HorizontalRangeState:
    return _HorizontalRangeState(
        start_pos=pending.start_pos,
        upper=pending.upper,
        lower=pending.lower,
        start_value=pending.start_value,
        active_from_pos=active_from_pos if active_from_pos is not None else pending.active_from_pos,
    )


def _source_compression_gate_passes(
    window_bars: Sequence[_Bar],
    config: _Config,
    atr: float,
) -> bool:
    if not window_bars:
        return False
    source_values = [bar.source for bar in window_bars]
    if any(not _finite(value) for value in source_values):
        return False

    center = sum(source_values) / len(source_values)
    atr_component = atr * config.hr_trend_atr_mult if _finite(atr) else 0.0
    min_band = abs(center) * config.min_hr_band_perc
    band = max(atr_component, min_band)
    if not _finite(band):
        return False

    lower = center - band
    upper = center + band
    inside_count = sum(1 for value in source_values if lower <= value <= upper)
    return inside_count / len(source_values) >= config.hr_min_inside_ratio


def _is_alternating_swings(swings: Sequence[_SwingPoint]) -> bool:
    if len(swings) < 2:
        return False
    for left, right in zip(swings, swings[1:]):
        if left.kind == right.kind:
            return False
    return True


def _swing_gaps_are_acceptable_for_config(
    swings: Sequence[_SwingPoint],
    config: _Config,
) -> bool:
    for left, right in zip(swings, swings[1:]):
        if right.position - left.position > config.hr_trend_max_gap:
            return False
    return True


def _resolved_trend_peak_trough_columns(config: _Config) -> Tuple[str, str]:
    peak_column = config.trend_peak_column or config.peak_column or _default_peak_column(config.trend_fractal_window)
    trough_column = config.trend_trough_column or config.trough_column or _default_trough_column(config.trend_fractal_window)
    return peak_column, trough_column


def _resolved_range_peak_trough_columns(config: _Config) -> Tuple[str, str]:
    peak_column = config.range_peak_column or _default_peak_column(config.range_fractal_window)
    trough_column = config.range_trough_column or _default_trough_column(config.range_fractal_window)
    return peak_column, trough_column


def _resolved_peak_trough_columns(config: _Config) -> Tuple[str, str]:
    """Compatibility resolver for the directional trend swing stream."""
    return _resolved_trend_peak_trough_columns(config)


def _resolved_peak_trough_columns_for_purpose(
    config: _Config,
    *,
    purpose: str,
) -> Tuple[str, str]:
    if purpose == "trend":
        return _resolved_trend_peak_trough_columns(config)
    if purpose == "range":
        return _resolved_range_peak_trough_columns(config)
    raise ValueError("purpose must be 'trend' or 'range'")


def _required_peak_trough_pairs(config: _Config) -> Tuple[Tuple[str, str], ...]:
    pairs: List[Tuple[str, str]] = []
    for pair in (_resolved_trend_peak_trough_columns(config), _resolved_range_peak_trough_columns(config)):
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)


def _required_peak_trough_columns_for_purpose(
    config: _Config,
    *,
    purpose: str,
) -> Tuple[str, str]:
    """Return the exact Peaks & Troughs pair required by one UTC detector."""
    return _resolved_peak_trough_columns_for_purpose(config, purpose=purpose)


def _required_peak_trough_columns(config: _Config) -> Tuple[str, ...]:
    """Return all unique Peaks & Troughs columns required by UTC.

    Trend and range dependency intent stays separate, but the combined list is
    useful for validation and for controller-side artifact loading optimization.
    """

    columns: List[str] = []
    for pair in _required_peak_trough_pairs(config):
        for column in pair:
            if column not in columns:
                columns.append(column)
    return tuple(columns)


def _require_peak_trough_columns_for_purpose(
    df: pd.DataFrame,
    config: _Config,
    *,
    purpose: str,
) -> Tuple[str, str]:
    """Validate one detector's injected Peaks & Troughs dependency.

    UTC is a consumer of saved/controller-injected Peaks & Troughs artifacts.
    The trend classifier and horizontal-range detector may require different
    fractal pairs, so each dependency is validated independently. The controller
    may still load the saved Peaks & Troughs artifact once and inject the union
    of both requested pairs as an optimization.
    """

    peak_column, trough_column = _required_peak_trough_columns_for_purpose(config, purpose=purpose)
    required_columns = (peak_column, trough_column)
    missing = [name for name in required_columns if name not in df.columns]
    if missing:
        raise ValueError(
            "Universal Trend Classifier requires saved/controller-injected "
            f"Peaks & Troughs indicators for the selected {purpose} fractal; "
            f"missing column(s): {missing}"
        )

    duplicates = [
        name
        for name in required_columns
        if sum(1 for column in df.columns if column == name) > 1
    ]
    if duplicates:
        raise ValueError(f"Peaks & Troughs dependency columns must be unique; duplicates: {duplicates}")

    return peak_column, trough_column


def _require_peak_trough_columns(df: pd.DataFrame, config: _Config) -> Tuple[str, str]:
    """Validate all UTC Peaks & Troughs dependencies and return trend columns.

    This compatibility helper keeps the older all-at-once validation contract,
    while the purpose-specific helper above is the preferred two-injection path.
    """

    _require_peak_trough_columns_for_purpose(df, config, purpose="trend")
    _require_peak_trough_columns_for_purpose(df, config, purpose="range")
    return _resolved_trend_peak_trough_columns(config)


def _resolve_peak_trough_dependency_columns(
    params: Optional[Mapping[str, Any]] = None,
    *,
    purpose: str,
) -> Tuple[str, str]:
    """Public helper for controller-side UTC dependency resolution.

    ``purpose="trend"`` returns the Up/Down trend fractal pair.
    ``purpose="range"`` returns the horizontal-range fractal pair.
    UTC does not load these columns; callers use this helper to inject them.
    """

    config = _Config.from_params(**dict(params or {}))
    return _required_peak_trough_columns_for_purpose(config, purpose=purpose)


def _resolve_all_peak_trough_dependency_columns(params: Optional[Mapping[str, Any]] = None) -> Tuple[str, ...]:
    """Public helper returning all unique UTC Peaks & Troughs dependency columns."""

    config = _Config.from_params(**dict(params or {}))
    return _required_peak_trough_columns(config)


def _build_swings_from_peak_trough_columns(
    df: pd.DataFrame,
    config: _Config,
    atr_values: Sequence[float],
    *,
    purpose: str = "trend",
) -> List[_SwingPoint]:
    """Build ordered swings from one Peaks & Troughs sparse event stream.

    Directional trends consume the trend fractal pair. Horizontal range
    discovery consumes the range fractal pair. A missing or partial dependency
    is rejected because mixing external swings with internally inferred swings
    would corrupt deterministic structure.
    """

    peak_column, trough_column = _require_peak_trough_columns_for_purpose(df, config, purpose=purpose)

    swings: List[_SwingPoint] = []
    peak_values = df[peak_column]
    trough_values = df[trough_column]
    for pos, (index, peak_value, trough_value) in enumerate(zip(df.index, peak_values, trough_values)):
        peak = _as_float(peak_value, name=peak_column)
        trough = _as_float(trough_value, name=trough_column)
        has_peak_value = _finite(peak)
        has_trough_value = _finite(trough)
        if has_peak_value and has_trough_value:
            # Same-row peak+trough is a valid market bar but ambiguous swing
            # evidence. UTC preserves bar continuity and skips this directional
            # event instead of forcing an arbitrary peak/trough ordering.
            continue
        atr = atr_values[pos] if pos < len(atr_values) else nan
        if has_peak_value:
            swings.append(_SwingPoint(position=pos, index=index, value=peak, kind="peak", atr=atr))
        elif has_trough_value:
            swings.append(_SwingPoint(position=pos, index=index, value=trough, kind="trough", atr=atr))
    return swings

def _detect_trend_intervals_from_swings(swings: Sequence[_SwingPoint]) -> Tuple[List[_TrendInterval], List[_TrendInterval]]:
    """Directional swing-state scan over confirmed swings.

    The scanner is intentionally sequential. It accepts same-kind swings while a
    trend candidate is forming, and active trends continue until their current
    structural floor/ceiling is broken unless a complete opposite trend is
    confirmed from the active trend endpoint.

    Directional invariants:
    - uptrends start at troughs and end at peaks;
    - downtrends start at peaks and end at troughs;
    - opposite trends may share one boundary swing but must not overlap beyond
      that boundary;
    - ``hr_trend_max_gap`` is not used here. It belongs to horizontal-range
      continuity, not directional trend detection.
    """

    uptrends: List[_TrendInterval] = []
    downtrends: List[_TrendInterval] = []
    swing_tuples = list(swings)
    count = len(swing_tuples)
    tol = 0.0

    mode: Optional[str] = None
    start_swing: Optional[_SwingPoint] = None
    start_i = 0
    first_peak: Optional[_SwingPoint] = None
    first_trough: Optional[_SwingPoint] = None
    last_peak: Optional[_SwingPoint] = None
    last_trough: Optional[_SwingPoint] = None
    first_peak_i = 0
    first_trough_i = 0
    last_peak_i = 0
    last_trough_i = 0

    reversal_kind: Optional[str] = None  # "down" while active_up, "up" while active_down
    reversal_start: Optional[_SwingPoint] = None
    reversal_start_i = 0
    reversal_first_peak: Optional[_SwingPoint] = None
    reversal_first_trough: Optional[_SwingPoint] = None
    reversal_last_peak: Optional[_SwingPoint] = None
    reversal_last_trough: Optional[_SwingPoint] = None
    reversal_first_peak_i = 0
    reversal_first_trough_i = 0
    reversal_last_peak_i = 0
    reversal_last_trough_i = 0

    def reset_reversal() -> None:
        nonlocal reversal_kind, reversal_start, reversal_start_i
        nonlocal reversal_first_peak, reversal_first_trough, reversal_last_peak, reversal_last_trough
        nonlocal reversal_first_peak_i, reversal_first_trough_i, reversal_last_peak_i, reversal_last_trough_i
        reversal_kind = None
        reversal_start = None
        reversal_start_i = 0
        reversal_first_peak = None
        reversal_first_trough = None
        reversal_last_peak = None
        reversal_last_trough = None
        reversal_first_peak_i = 0
        reversal_first_trough_i = 0
        reversal_last_peak_i = 0
        reversal_last_trough_i = 0

    def reset() -> None:
        nonlocal mode, start_swing, start_i
        nonlocal first_peak, first_trough, last_peak, last_trough
        nonlocal first_peak_i, first_trough_i, last_peak_i, last_trough_i
        mode = None
        start_swing = None
        start_i = 0
        first_peak = None
        first_trough = None
        last_peak = None
        last_trough = None
        first_peak_i = 0
        first_trough_i = 0
        last_peak_i = 0
        last_trough_i = 0
        reset_reversal()

    def start_up_candidate(swing: _SwingPoint, idx: int) -> None:
        nonlocal mode, start_swing, start_i, first_trough, last_trough
        nonlocal first_peak, last_peak
        nonlocal first_trough_i, last_trough_i, first_peak_i, last_peak_i
        reset_reversal()
        mode = "candidate_up"
        start_swing = swing
        start_i = idx
        first_trough = swing
        first_trough_i = idx
        last_trough = swing
        last_trough_i = idx
        first_peak = None
        last_peak = None
        first_peak_i = 0
        last_peak_i = 0

    def start_down_candidate(swing: _SwingPoint, idx: int) -> None:
        nonlocal mode, start_swing, start_i, first_peak, last_peak
        nonlocal first_trough, last_trough
        nonlocal first_peak_i, last_peak_i, first_trough_i, last_trough_i
        reset_reversal()
        mode = "candidate_down"
        start_swing = swing
        start_i = idx
        first_peak = swing
        first_peak_i = idx
        last_peak = swing
        last_peak_i = idx
        first_trough = None
        last_trough = None
        first_trough_i = 0
        last_trough_i = 0

    def start_down_reversal(anchor_peak: _SwingPoint, idx: int) -> None:
        nonlocal reversal_kind, reversal_start, reversal_start_i
        nonlocal reversal_first_peak, reversal_last_peak, reversal_first_peak_i, reversal_last_peak_i
        nonlocal reversal_first_trough, reversal_last_trough, reversal_first_trough_i, reversal_last_trough_i
        reversal_kind = "down"
        reversal_start = anchor_peak
        reversal_start_i = idx
        reversal_first_peak = anchor_peak
        reversal_first_peak_i = idx
        reversal_last_peak = anchor_peak
        reversal_last_peak_i = idx
        reversal_first_trough = None
        reversal_last_trough = None
        reversal_first_trough_i = 0
        reversal_last_trough_i = 0

    def start_up_reversal(anchor_trough: _SwingPoint, idx: int) -> None:
        nonlocal reversal_kind, reversal_start, reversal_start_i
        nonlocal reversal_first_trough, reversal_last_trough, reversal_first_trough_i, reversal_last_trough_i
        nonlocal reversal_first_peak, reversal_last_peak, reversal_first_peak_i, reversal_last_peak_i
        reversal_kind = "up"
        reversal_start = anchor_trough
        reversal_start_i = idx
        reversal_first_trough = anchor_trough
        reversal_first_trough_i = idx
        reversal_last_trough = anchor_trough
        reversal_last_trough_i = idx
        reversal_first_peak = None
        reversal_last_peak = None
        reversal_first_peak_i = 0
        reversal_last_peak_i = 0

    def append_uptrend_at(end_peak: Optional[_SwingPoint]) -> None:
        if start_swing is None or end_peak is None:
            return
        if start_swing.kind != "trough" or end_peak.kind != "peak":
            return
        if end_peak.position < start_swing.position:
            return
        uptrends.append(
            _TrendInterval(
                kind="uptrend",
                start_pos=start_swing.position,
                end_pos=end_peak.position,
                start_value=start_swing.value,
                end_value=end_peak.value,
            )
        )

    def append_downtrend_at(end_trough: Optional[_SwingPoint]) -> None:
        if start_swing is None or end_trough is None:
            return
        if start_swing.kind != "peak" or end_trough.kind != "trough":
            return
        if end_trough.position < start_swing.position:
            return
        downtrends.append(
            _TrendInterval(
                kind="downtrend",
                start_pos=start_swing.position,
                end_pos=end_trough.position,
                start_value=start_swing.value,
                end_value=end_trough.value,
            )
        )

    def activate_down_from_reversal(end_trough: _SwingPoint, idx: int) -> None:
        """Close active uptrend at its endpoint peak and start downtrend there."""
        nonlocal mode, start_swing, start_i
        nonlocal first_peak, first_trough, last_peak, last_trough
        nonlocal first_peak_i, first_trough_i, last_peak_i, last_trough_i

        anchor = reversal_start
        if anchor is None or anchor.kind != "peak":
            return
        first_rev_trough = reversal_first_trough or end_trough
        ceiling_peak = reversal_last_peak or anchor
        append_uptrend_at(anchor)

        mode = "active_down"
        start_swing = anchor
        start_i = reversal_start_i
        first_peak = anchor
        first_peak_i = reversal_start_i
        last_peak = ceiling_peak
        last_peak_i = reversal_last_peak_i if reversal_last_peak is not None else reversal_start_i
        first_trough = first_rev_trough
        first_trough_i = reversal_first_trough_i if reversal_first_trough is not None else idx
        last_trough = end_trough
        last_trough_i = idx
        reset_reversal()
        start_up_reversal(last_trough, last_trough_i)

    def activate_up_from_reversal(end_peak: _SwingPoint, idx: int) -> None:
        """Close active downtrend at its endpoint trough and start uptrend there."""
        nonlocal mode, start_swing, start_i
        nonlocal first_peak, first_trough, last_peak, last_trough
        nonlocal first_peak_i, first_trough_i, last_peak_i, last_trough_i

        anchor = reversal_start
        if anchor is None or anchor.kind != "trough":
            return
        first_rev_peak = reversal_first_peak or end_peak
        floor_trough = reversal_last_trough or anchor
        append_downtrend_at(anchor)

        mode = "active_up"
        start_swing = anchor
        start_i = reversal_start_i
        first_trough = anchor
        first_trough_i = reversal_start_i
        last_trough = floor_trough
        last_trough_i = reversal_last_trough_i if reversal_last_trough is not None else reversal_start_i
        first_peak = first_rev_peak
        first_peak_i = reversal_first_peak_i if reversal_first_peak is not None else idx
        last_peak = end_peak
        last_peak_i = idx
        reset_reversal()
        start_down_reversal(last_peak, last_peak_i)

    i = 0
    while i < count:
        swing = swing_tuples[i]

        if mode is None:
            if swing.kind == "trough":
                start_up_candidate(swing, i)
            elif swing.kind == "peak":
                start_down_candidate(swing, i)
            i += 1
            continue

        if mode == "candidate_up":
            if swing.kind == "trough":
                if first_peak is None:
                    # Before the first peak, keep the lowest available trough
                    # as the uptrend anchor.
                    if start_swing is not None and swing.value < start_swing.value:
                        start_up_candidate(swing, i)
                    i += 1
                    continue

                # Once a peak exists, the candidate's structural floor may only
                # stay flat or move higher. A lower trough breaks the candidate
                # and lets the previous peak seed a possible downtrend.
                if last_trough is None or swing.value >= last_trough.value - tol:
                    if last_trough is None or swing.value > last_trough.value:
                        last_trough = swing
                        last_trough_i = i
                    i += 1
                    continue

                restart_i = last_peak_i if last_peak is not None else i
                reset()
                i = restart_i
                continue

            if swing.kind == "peak":
                if first_peak is None:
                    first_peak = swing
                    first_peak_i = i
                    last_peak = swing
                    last_peak_i = i
                    i += 1
                    continue

                structural_floor = (
                    last_trough.value
                    if last_trough is not None
                    else start_swing.value
                    if start_swing is not None
                    else -float("inf")
                )
                if swing.value > last_peak.value:
                    last_peak = swing
                    last_peak_i = i
                    mode = "active_up"
                    start_down_reversal(last_peak, last_peak_i)
                    i += 1
                    continue

                if swing.value >= structural_floor - tol:
                    # Non-improving peaks above the structural floor do not
                    # confirm the trend, but they also do not invalidate the
                    # candidate.
                    i += 1
                    continue

                restart_i = last_peak_i if last_peak is not None else i
                reset()
                i = restart_i
                continue

        if mode == "active_up":
            structural_floor = (
                last_trough.value
                if last_trough is not None
                else start_swing.value
                if start_swing is not None
                else -float("inf")
            )

            if swing.kind == "trough":
                if swing.value < structural_floor - tol:
                    if (
                        reversal_kind == "down"
                        and reversal_first_trough is not None
                        and reversal_last_trough is not None
                        and swing.value < reversal_last_trough.value - tol
                    ):
                        activate_down_from_reversal(swing, i)
                        i += 1
                        continue

                    append_uptrend_at(last_peak)
                    restart_i = last_peak_i if last_peak is not None else i
                    reset()
                    i = restart_i
                    continue

                if reversal_kind != "down" or reversal_start is None:
                    if last_peak is not None:
                        start_down_reversal(last_peak, last_peak_i)

                if reversal_kind == "down":
                    if reversal_first_trough is None:
                        reversal_first_trough = swing
                        reversal_first_trough_i = i
                        reversal_last_trough = swing
                        reversal_last_trough_i = i
                    elif reversal_last_trough is not None and swing.value < reversal_last_trough.value - tol:
                        activate_down_from_reversal(swing, i)
                        i += 1
                        continue

                # The uptrend floor can only stay flat or move higher.
                if last_trough is None or swing.value > last_trough.value:
                    last_trough = swing
                    last_trough_i = i
                i += 1
                continue

            if swing.kind == "peak":
                if swing.value < structural_floor - tol:
                    append_uptrend_at(last_peak)
                    restart_i = last_peak_i if last_peak is not None else i
                    reset()
                    i = restart_i
                    continue

                if reversal_kind != "down" or reversal_start is None:
                    if last_peak is not None:
                        start_down_reversal(last_peak, last_peak_i)

                if reversal_kind == "down" and reversal_first_trough is not None:
                    candidate_ceiling = (
                        reversal_last_peak.value
                        if reversal_last_peak is not None
                        else reversal_start.value
                        if reversal_start is not None
                        else float("inf")
                    )
                    if swing.value <= candidate_ceiling + tol:
                        if reversal_last_peak is None or swing.value < reversal_last_peak.value:
                            reversal_last_peak = swing
                            reversal_last_peak_i = i
                        # Do not accept this lower/equal peak as the uptrend
                        # endpoint until the reversal candidate fails.
                        i += 1
                        continue

                    # A peak above the pending downtrend ceiling invalidates the
                    # reversal attempt and becomes the new uptrend endpoint.
                    last_peak = swing
                    last_peak_i = i
                    start_down_reversal(last_peak, last_peak_i)
                    i += 1
                    continue

                # No trough after the current endpoint yet: same-kind peak
                # continuation can safely become the latest uptrend endpoint.
                last_peak = swing
                last_peak_i = i
                start_down_reversal(last_peak, last_peak_i)
                i += 1
                continue

        if mode == "candidate_down":
            if swing.kind == "peak":
                if first_trough is None:
                    # Before the first trough, keep the highest available peak
                    # as the downtrend anchor.
                    if start_swing is not None and swing.value > start_swing.value:
                        start_down_candidate(swing, i)
                    i += 1
                    continue

                # Once a trough exists, the candidate's structural ceiling may
                # only stay flat or move lower. A higher peak breaks the
                # candidate and lets the previous trough seed a possible uptrend.
                if last_peak is None or swing.value <= last_peak.value + tol:
                    if last_peak is None or swing.value < last_peak.value:
                        last_peak = swing
                        last_peak_i = i
                    i += 1
                    continue

                restart_i = last_trough_i if last_trough is not None else i
                reset()
                i = restart_i
                continue

            if swing.kind == "trough":
                if first_trough is None:
                    first_trough = swing
                    first_trough_i = i
                    last_trough = swing
                    last_trough_i = i
                    i += 1
                    continue

                structural_ceiling = (
                    last_peak.value
                    if last_peak is not None
                    else start_swing.value
                    if start_swing is not None
                    else float("inf")
                )
                if swing.value < last_trough.value:
                    last_trough = swing
                    last_trough_i = i
                    mode = "active_down"
                    start_up_reversal(last_trough, last_trough_i)
                    i += 1
                    continue

                if swing.value <= structural_ceiling + tol:
                    # Non-improving troughs below the structural ceiling do not
                    # confirm the trend, but they also do not invalidate the
                    # candidate.
                    i += 1
                    continue

                restart_i = last_trough_i if last_trough is not None else i
                reset()
                i = restart_i
                continue

        if mode == "active_down":
            structural_ceiling = (
                last_peak.value
                if last_peak is not None
                else start_swing.value
                if start_swing is not None
                else float("inf")
            )

            if swing.kind == "peak":
                if swing.value > structural_ceiling + tol:
                    if (
                        reversal_kind == "up"
                        and reversal_first_peak is not None
                        and reversal_last_peak is not None
                        and swing.value > reversal_last_peak.value + tol
                    ):
                        activate_up_from_reversal(swing, i)
                        i += 1
                        continue

                    append_downtrend_at(last_trough)
                    restart_i = last_trough_i if last_trough is not None else i
                    reset()
                    i = restart_i
                    continue

                if reversal_kind != "up" or reversal_start is None:
                    if last_trough is not None:
                        start_up_reversal(last_trough, last_trough_i)

                if reversal_kind == "up":
                    if reversal_first_peak is None:
                        reversal_first_peak = swing
                        reversal_first_peak_i = i
                        reversal_last_peak = swing
                        reversal_last_peak_i = i
                    elif reversal_last_peak is not None and swing.value > reversal_last_peak.value + tol:
                        activate_up_from_reversal(swing, i)
                        i += 1
                        continue

                # The downtrend ceiling can only stay flat or move lower.
                if last_peak is None or swing.value < last_peak.value:
                    last_peak = swing
                    last_peak_i = i
                i += 1
                continue

            if swing.kind == "trough":
                if swing.value > structural_ceiling + tol:
                    append_downtrend_at(last_trough)
                    restart_i = last_trough_i if last_trough is not None else i
                    reset()
                    i = restart_i
                    continue

                if reversal_kind != "up" or reversal_start is None:
                    if last_trough is not None:
                        start_up_reversal(last_trough, last_trough_i)

                if reversal_kind == "up" and reversal_first_peak is not None:
                    candidate_floor = (
                        reversal_last_trough.value
                        if reversal_last_trough is not None
                        else reversal_start.value
                        if reversal_start is not None
                        else -float("inf")
                    )
                    if swing.value >= candidate_floor - tol:
                        if reversal_last_trough is None or swing.value > reversal_last_trough.value:
                            reversal_last_trough = swing
                            reversal_last_trough_i = i
                        # Do not accept this higher/equal trough as the
                        # downtrend endpoint until the reversal candidate fails.
                        i += 1
                        continue

                    # A trough below the pending uptrend floor invalidates the
                    # reversal attempt and becomes the new downtrend endpoint.
                    last_trough = swing
                    last_trough_i = i
                    start_up_reversal(last_trough, last_trough_i)
                    i += 1
                    continue

                # No peak after the current endpoint yet: same-kind trough
                # continuation can safely become the latest downtrend endpoint.
                last_trough = swing
                last_trough_i = i
                start_up_reversal(last_trough, last_trough_i)
                i += 1
                continue

        # Defensive forward progress for any unexpected branch.
        i += 1

    if mode == "active_up":
        append_uptrend_at(last_peak)
    elif mode == "active_down":
        append_downtrend_at(last_trough)

    return uptrends, downtrends


def _valid_bar_segments(bars: Sequence[_Bar]) -> List[Tuple[int, int]]:
    """Return inclusive valid-data spans that must not bridge invalid bars."""
    segments: List[Tuple[int, int]] = []
    start: Optional[int] = None

    for pos, bar in enumerate(bars):
        if bar.valid:
            if start is None:
                start = pos
            continue

        if start is not None:
            segments.append((start, pos - 1))
            start = None

    if start is not None:
        segments.append((start, len(bars) - 1))

    return segments


def _detect_trend_intervals_from_swings_by_valid_segments(
    bars: Sequence[_Bar],
    swings: Sequence[_SwingPoint],
) -> Tuple[List[_TrendInterval], List[_TrendInterval]]:
    """Detect directional trends without bridging invalid OHLC/source gaps."""
    uptrends: List[_TrendInterval] = []
    downtrends: List[_TrendInterval] = []

    for start_pos, end_pos in _valid_bar_segments(bars):
        segment_swings = [
            swing
            for swing in swings
            if start_pos <= swing.position <= end_pos
        ]
        if not segment_swings:
            continue

        segment_uptrends, segment_downtrends = _detect_trend_intervals_from_swings(segment_swings)
        uptrends.extend(segment_uptrends)
        downtrends.extend(segment_downtrends)

    return uptrends, downtrends


def _build_horizontal_range_state(
    bars: Sequence[_Bar],
    confirmed_swings: Sequence[_SwingPoint],
    config: _Config,
    current_pos: int,
    min_range_start_pos: int,
) -> Optional[_HorizontalRangeState]:
    """Return a new horizontal-range state from confirmed Peaks & Troughs swings.

    The detector uses a wick-based recent-window gate and then validates a
    complete alternating swing pattern inside that gate.  ``current_pos`` is the
    bar where the newest swing is knowable, not necessarily the pivot bar.  That
    keeps the historical path compatible with a future realtime path that feeds
    the same confirmed swing events as they become available.
    """

    cfg = config
    if current_pos < 0 or current_pos >= len(bars):
        return None
    if len(bars) < cfg.hr_trend_length:
        return None

    window_start = max(min_range_start_pos, current_pos - cfg.hr_trend_length + 1)
    window_bars = list(bars[window_start : current_pos + 1])
    if len(window_bars) < cfg.hr_trend_length:
        return None
    if any(not bar.valid for bar in window_bars):
        return None

    midpoints = [_bar_wick_midpoint(bar) for bar in window_bars]
    if any(not _finite(value) for value in midpoints):
        return None
    mean_wick = sum(midpoints) / len(midpoints)

    current_bar = bars[current_pos]
    atr = current_bar.atr if _finite(current_bar.atr) else 0.0
    if not _source_compression_gate_passes(window_bars, cfg, atr):
        return None
    min_band = abs(mean_wick) * cfg.min_hr_band_perc
    band = max(atr * cfg.hr_trend_atr_mult, min_band)
    if not _finite(band):
        return None

    range_top = mean_wick + band
    range_bottom = mean_wick - band
    inside_count = sum(1 for bar in window_bars if _bar_wick_inside(bar, range_bottom, range_top))
    inside_ratio = inside_count / len(window_bars)
    if inside_ratio < cfg.hr_min_inside_ratio:
        return None

    eligible = [
        swing
        for swing in confirmed_swings
        if window_start <= swing.position <= current_pos and range_bottom <= swing.value <= range_top
    ]
    if len(eligible) < cfg.min_range_swings:
        return None

    # Prefer the most recent complete alternating pattern.  This mirrors the
    # previous range-start policy while using the externally confirmed swing
    # stream instead of UTC-internal source fractals.
    pattern: Optional[List[_SwingPoint]] = None
    for end in range(len(eligible), cfg.min_range_swings - 1, -1):
        candidate = eligible[end - cfg.min_range_swings : end]
        if _is_alternating_swings(candidate) and _swing_gaps_are_acceptable_for_config(candidate, cfg):
            pattern = candidate
            break
    if pattern is None:
        return None

    peaks = [s for s in pattern if s.kind == "peak"]
    troughs = [s for s in pattern if s.kind == "trough"]
    if not peaks or not troughs:
        return None

    peak = max(peaks, key=lambda s: s.value)
    trough = min(troughs, key=lambda s: s.value)
    peak_atr = peak.atr if _finite(peak.atr) else atr
    trough_atr = trough.atr if _finite(trough.atr) else atr
    upper = peak.value + peak_atr * cfg.hr_trend_atr_mult
    lower = trough.value - trough_atr * cfg.hr_trend_atr_mult
    if not (_finite(upper) and _finite(lower)) or lower > upper:
        return None
    probe_state = _HorizontalRangeState(start_pos=pattern[0].position, upper=upper, lower=lower, start_value=pattern[0].value)
    breaks_current_bar, _direction = _bar_breaks_horizontal_range(current_bar, probe_state, cfg, mutate_state=False)
    if breaks_current_bar:
        return None

    start_swing = pattern[0]
    return _HorizontalRangeState(
        start_pos=start_swing.position,
        upper=upper,
        lower=lower,
        start_value=start_swing.value,
    )


def _detect_horizontal_range_intervals_from_swings(
    bars: Sequence[_Bar],
    swings: Sequence[_SwingPoint],
    config: _Config,
) -> List[_HorizontalRangeInterval]:
    """Sequential horizontal-range scan using confirmed range-fractal swings."""

    if not bars:
        return []

    half_window = config.range_fractal_window // 2
    swings_by_confirmation_pos: Dict[int, List[_SwingPoint]] = {}
    for swing in swings:
        confirmation_pos = swing.position + half_window
        if 0 <= confirmation_pos < len(bars):
            swings_by_confirmation_pos.setdefault(confirmation_pos, []).append(swing)

    intervals: List[_HorizontalRangeInterval] = []
    confirmed_swings: List[_SwingPoint] = []
    active_range: Optional[_HorizontalRangeState] = None
    pending_breakout: Optional[_PendingHorizontalRangeBreakout] = None
    min_range_start_pos = 0

    def finalize_pending_breakout(pending: _PendingHorizontalRangeBreakout, *, closed: bool = True) -> None:
        nonlocal min_range_start_pos
        end_pos = min(max(pending.break_pos - 1, pending.start_pos), len(bars) - 1)
        end_bar = bars[end_pos]
        intervals.append(
            _HorizontalRangeInterval(
                start_pos=pending.start_pos,
                end_pos=end_pos,
                upper=pending.upper,
                lower=pending.lower,
                start_value=pending.start_value,
                end_value=end_bar.source,
                closed=closed,
                break_direction=pending.break_direction,
            )
        )
        min_range_start_pos = max(min_range_start_pos, end_pos + 1)

    for pos, bar in enumerate(bars):
        if active_range is not None:
            breaks, direction = _bar_breaks_horizontal_range(bar, active_range, config)
            if breaks:
                extreme = bar.high if direction > 0 else bar.low if direction < 0 else bar.source
                pending_breakout = _PendingHorizontalRangeBreakout(
                    start_pos=active_range.start_pos,
                    upper=active_range.upper,
                    lower=active_range.lower,
                    start_value=active_range.start_value,
                    break_pos=pos,
                    break_direction=direction,
                    expires_pos=pos + config.hr_trend_max_gap,
                    break_extreme=extreme,
                )
                active_range = None

        elif pending_breakout is not None:
            if not bar.valid:
                finalize_pending_breakout(pending_breakout)
                pending_breakout = None
                min_range_start_pos = pos + 1
                continue
            if pos <= pending_breakout.expires_pos and _bar_reclaims_pending_breakout(bar, pending_breakout):
                # False breakout: reactivate the same range zone.  Bars between
                # break and reclaim remain outside the range; no output column is
                # added in this contract-stable phase.
                active_range = _pending_breakout_state(pending_breakout)
                pending_breakout = None
            elif pos > pending_breakout.expires_pos:
                finalize_pending_breakout(pending_breakout)
                pending_breakout = None

        if not bar.valid:
            if active_range is not None:
                end_pos = max(active_range.start_pos, pos - 1)
                end_bar = bars[end_pos]
                intervals.append(
                    _HorizontalRangeInterval(
                        start_pos=active_range.start_pos,
                        end_pos=end_pos,
                        upper=active_range.upper,
                        lower=active_range.lower,
                        start_value=active_range.start_value,
                        end_value=end_bar.source,
                        closed=True,
                    )
                )
                active_range = None
            if pending_breakout is not None:
                finalize_pending_breakout(pending_breakout)
                pending_breakout = None
            min_range_start_pos = pos + 1
            continue

        new_swing_seen = False
        for swing in swings_by_confirmation_pos.get(pos, []):
            confirmed_swings.append(swing)
            new_swing_seen = True

        if active_range is None and pending_breakout is None and new_swing_seen:
            active_range = _build_horizontal_range_state(
                bars,
                confirmed_swings,
                config,
                pos,
                min_range_start_pos,
            )

    if active_range is not None:
        end_pos = len(bars) - 1
        intervals.append(
            _HorizontalRangeInterval(
                start_pos=active_range.start_pos,
                end_pos=end_pos,
                upper=active_range.upper,
                lower=active_range.lower,
                start_value=active_range.start_value,
                end_value=bars[end_pos].source,
                closed=False,
            )
        )
    if pending_breakout is not None:
        finalize_pending_breakout(pending_breakout)

    return intervals


def _apply_external_horizontal_range_intervals(
    result: pd.DataFrame,
    intervals: Sequence[_HorizontalRangeInterval],
) -> None:
    for name in ("horizontal_range", "hr_start", "hr_end"):
        result[name] = False
    for name in ("hor_upper", "hor_lower", "hr_start_marker", "hr_end_marker"):
        result[name] = nan

    for interval in intervals:
        if len(result) == 0:
            continue
        start = max(0, min(interval.start_pos, len(result) - 1))
        end = max(start, min(interval.end_pos, len(result) - 1))
        start_index = result.index[start]
        end_index = result.index[end]
        result.loc[result.index[start : end + 1], "horizontal_range"] = True
        result.loc[result.index[start : end + 1], "hor_upper"] = interval.upper
        result.loc[result.index[start : end + 1], "hor_lower"] = interval.lower
        result.at[start_index, "hr_start"] = True
        result.at[start_index, "hr_start_marker"] = interval.start_value
        if interval.closed:
            result.at[end_index, "hr_end"] = True
            result.at[end_index, "hr_end_marker"] = interval.end_value

    result["hr_uptrend"] = result["horizontal_range"].astype(bool) & result["uptrend"].astype(bool)
    result["hr_downtrend"] = result["horizontal_range"].astype(bool) & result["downtrend"].astype(bool)


def _apply_external_trend_intervals(
    result: pd.DataFrame,
    uptrends: Sequence[_TrendInterval],
    downtrends: Sequence[_TrendInterval],
) -> None:
    for name in (
        "uptrend",
        "uptrend_start",
        "uptrend_end",
        "downtrend",
        "downtrend_start",
        "downtrend_end",
    ):
        result[name] = False
    for name in (
        "uptrend_start_marker",
        "uptrend_end_marker",
        "downtrend_start_marker",
        "downtrend_end_marker",
    ):
        result[name] = nan

    for interval in uptrends:
        start = max(0, min(interval.start_pos, len(result) - 1))
        end = max(start, min(interval.end_pos, len(result) - 1))
        start_index = result.index[start]
        end_index = result.index[end]
        result.loc[result.index[start : end + 1], "uptrend"] = True
        result.at[start_index, "uptrend_start"] = True
        result.at[end_index, "uptrend_end"] = True
        result.at[start_index, "uptrend_start_marker"] = interval.start_value
        result.at[end_index, "uptrend_end_marker"] = interval.end_value

    for interval in downtrends:
        start = max(0, min(interval.start_pos, len(result) - 1))
        end = max(start, min(interval.end_pos, len(result) - 1))
        start_index = result.index[start]
        end_index = result.index[end]
        result.loc[result.index[start : end + 1], "downtrend"] = True
        result.at[start_index, "downtrend_start"] = True
        result.at[end_index, "downtrend_end"] = True
        result.at[start_index, "downtrend_start_marker"] = interval.start_value
        result.at[end_index, "downtrend_end_marker"] = interval.end_value

    result["hr_uptrend"] = result["horizontal_range"].astype(bool) & result["uptrend"].astype(bool)
    result["hr_downtrend"] = result["horizontal_range"].astype(bool) & result["downtrend"].astype(bool)


class _HistoricalReplay:
    """Realtime state machine for the Universal Trend Classifier.

    This class records bars without inferring internal fractals. Realtime
    integration must feed the same confirmed Peaks & Troughs swing stream used
    by historical computation; the normalized bridge remains disabled until that
    dependency-aware feed path is wired.
    """

    def __init__(self, config: Optional[_Config] = None, **params: Any) -> None:
        if config is None:
            config = _Config.from_params(**params)
        else:
            config.validate()
        self.config = config
        self._bars: List[_Bar] = []
        self._outputs: List[Dict[str, Any]] = []
        self._atr_average = _RollingAverage(config.hr_trend_atr_len)
        self._prev_close: float = nan
        self._swings: List[_SwingPoint] = []  # Compatibility alias for trend swings.
        self._range_swings: List[_SwingPoint] = []
        self._active_range: Optional[_HorizontalRangeState] = None
        self._pending_range_breakout: Optional[_PendingHorizontalRangeBreakout] = None
        self._active_trend: Optional[_TrendState] = None
        self._min_range_start_pos = 0
        self._min_trend_start_pos = 0

    @property
    def bars_seen(self) -> int:
        return len(self._bars)

    @property
    def confirmed_swings(self) -> Tuple[_SwingPoint, ...]:
        return tuple(self._swings)

    def confirm_swing(
        self,
        swing: _SwingPoint,
        *,
        current_pos: Optional[int] = None,
        purpose: str = "trend",
    ) -> _Update:
        """Feed an externally confirmed Peaks & Troughs event into the engine.

        UTC never calculates fractals. Historical replay and future realtime
        integration must feed already-confirmed events from Peaks & Troughs.
        """
        if not self._bars:
            raise ValueError("cannot confirm a swing before any bars have been recorded")
        if purpose not in {"trend", "range", "both"}:
            raise ValueError("purpose must be one of: trend, range, both")
        pos = len(self._bars) - 1 if current_pos is None else int(current_pos)
        if pos < 0 or pos >= len(self._bars):
            raise ValueError("current_pos is outside the recorded bar history")

        changed_start = min(max(swing.position, 0), pos)
        changed_end = pos
        if purpose in {"trend", "both"}:
            self._swings.append(swing)
            changed_start, changed_end = self._update_trend_with_swing(swing, pos, changed_start, changed_end)
        if purpose in {"range", "both"}:
            self._range_swings.append(swing)
            if self._active_range is None and self._pending_range_breakout is None:
                changed_start, changed_end = self._try_start_horizontal_range(pos, changed_start, changed_end)

        self._refresh_composite_flags(changed_start, changed_end)
        return _Update(pos, self._bars[pos].index, changed_start, changed_end, swing, dict(self._outputs[pos]))

    def confirm_range_swing(self, swing: _SwingPoint, *, current_pos: Optional[int] = None) -> _Update:
        return self.confirm_swing(swing, current_pos=current_pos, purpose="range")

    def confirm_trend_swing(self, swing: _SwingPoint, *, current_pos: Optional[int] = None) -> _Update:
        return self.confirm_swing(swing, current_pos=current_pos, purpose="trend")

    def update_from_mapping(self, index: Any, row: Mapping[str, Any]) -> _Update:
        required_names = tuple(dict.fromkeys((self.config.source, self.config.high, self.config.low, self.config.close)))
        missing = [name for name in required_names if name not in row]
        if missing:
            raise ValueError(f"missing required column(s): {missing}")
        return self.update_bar(
            index=index,
            source=row[self.config.source],
            high=row[self.config.high],
            low=row[self.config.low],
            close=row[self.config.close],
        )

    def update_bar(self, *, index: Any, source: Any, high: Any, low: Any, close: Any) -> _Update:
        pos = len(self._bars)
        source_f = _as_float(source, name=self.config.source)
        high_f = _as_float(high, name=self.config.high)
        low_f = _as_float(low, name=self.config.low)
        close_f = _as_float(close, name=self.config.close)
        if _finite(high_f) and _finite(low_f) and high_f < low_f:
            raise ValueError(f"{self.config.high} must be >= {self.config.low} for finite OHLC rows")
        tr = self._true_range(high_f, low_f, self._prev_close)
        atr = self._atr_average.push(tr)
        bar = _Bar(pos, index, source_f, high_f, low_f, close_f, atr)

        self._bars.append(bar)
        self._outputs.append(_default_output_row())
        changed_start = pos
        changed_end = pos
        confirmed_swing: Optional[_SwingPoint] = None

        if not bar.valid:
            changed_start, changed_end = self._handle_invalid_bar(pos, changed_start, changed_end)
            # Invalid bars are hard continuity breaks.  Do not let a finite close
            # on an otherwise-invalid row feed the next bar's true-range path.
            self._prev_close = nan
            return _Update(pos, index, changed_start, changed_end, confirmed_swing, dict(self._outputs[pos]))

        # Active range/trend markers are assigned for the current row. External
        # swing events, when available, may revise earlier rows afterward.
        changed_start, changed_end = self._update_active_range_with_bar(bar, changed_start, changed_end)
        changed_start, changed_end = self._update_pending_range_breakout_with_bar(bar, changed_start, changed_end)
        changed_start, changed_end = self._mark_active_trend_current(bar.position, changed_start, changed_end)

        self._refresh_composite_flags(changed_start, changed_end)
        self._prev_close = close_f
        return _Update(pos, index, changed_start, changed_end, confirmed_swing, dict(self._outputs[pos]))

    def to_output_frame(self) -> pd.DataFrame:
        """Return a dataframe containing only indicator outputs."""
        index = [bar.index for bar in self._bars]
        # List-of-dicts construction is used only for materialization.  All
        # computation paths above are sequential and realtime-compatible.
        return pd.DataFrame(self._outputs, index=index, columns=list(_OUTPUT_COLUMNS))

    def to_records(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self._outputs]

    def _true_range(self, high: float, low: float, prev_close: float) -> float:
        if not (_finite(high) and _finite(low)):
            return nan
        base = high - low
        if _finite(prev_close):
            return max(base, abs(high - prev_close), abs(low - prev_close))
        return base

    def _handle_invalid_bar(self, pos: int, changed_start: int, changed_end: int) -> Tuple[int, int]:
        prev_pos = pos - 1
        if self._active_range is not None and prev_pos >= _range_mark_start(self._active_range):
            changed_start, changed_end = self._close_horizontal_range(prev_pos, changed_start, changed_end)
        if self._pending_range_breakout is not None:
            changed_start, changed_end = self._finalize_pending_range_breakout(changed_start, changed_end)
        if self._active_trend is not None and prev_pos >= self._active_trend.start_pos:
            changed_start, changed_end = self._close_trend(prev_pos, changed_start, changed_end)
        self._active_range = None
        self._pending_range_breakout = None
        self._active_trend = None
        self._min_range_start_pos = pos + 1
        self._min_trend_start_pos = pos + 1
        self._atr_average.clear()
        return min(changed_start, max(prev_pos, 0)), changed_end

    def _on_swing_confirmed(
        self,
        swing: _SwingPoint,
        current_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        self._swings.append(swing)
        self._range_swings.append(swing)
        changed_start, changed_end = self._update_trend_with_swing(swing, current_pos, changed_start, changed_end)
        if self._active_range is None and self._pending_range_breakout is None:
            changed_start, changed_end = self._try_start_horizontal_range(current_pos, changed_start, changed_end)
        return changed_start, changed_end

    def _update_active_range_with_bar(
        self,
        bar: _Bar,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = self._active_range
        if state is None:
            return changed_start, changed_end

        breaks, direction = _bar_breaks_horizontal_range(bar, state, self.config)
        if not breaks:
            self._outputs[bar.position]["horizontal_range"] = True
            self._outputs[bar.position]["hor_upper"] = state.upper
            self._outputs[bar.position]["hor_lower"] = state.lower
            return changed_start, max(changed_end, bar.position)

        mark_start = _range_mark_start(state)
        extreme = _breakout_extreme_for_bar(bar, direction)
        self._pending_range_breakout = _PendingHorizontalRangeBreakout(
            start_pos=state.start_pos,
            upper=state.upper,
            lower=state.lower,
            start_value=state.start_value,
            break_pos=bar.position,
            break_direction=direction,
            expires_pos=bar.position + self.config.hr_trend_max_gap,
            break_extreme=extreme,
            active_from_pos=mark_start,
        )
        self._mark_breakout_lifecycle_row(bar.position, self._pending_range_breakout, attempt=True, pending_state=True)
        self._active_range = None
        return min(changed_start, mark_start), max(changed_end, bar.position)

    def _update_pending_range_breakout_with_bar(
        self,
        bar: _Bar,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        pending = self._pending_range_breakout
        if pending is None:
            return changed_start, changed_end
        if bar.position == pending.break_pos:
            return changed_start, changed_end

        if bar.position > pending.expires_pos:
            return self._finalize_pending_range_breakout(
                changed_start,
                changed_end,
                confirmation_pos=bar.position,
            )

        _update_pending_breakout_extreme(pending, bar)

        if _bar_reclaims_pending_breakout(bar, pending):
            self._active_range = _pending_breakout_state(pending, active_from_pos=bar.position)
            self._pending_range_breakout = None
            self._outputs[bar.position]["horizontal_range"] = True
            self._outputs[bar.position]["hor_upper"] = self._active_range.upper
            self._outputs[bar.position]["hor_lower"] = self._active_range.lower
            self._mark_breakout_lifecycle_row(bar.position, pending, false_breakout=True, reclaim=True)
            self._outputs[bar.position]["hr_reclaim_marker"] = bar.source
            return min(changed_start, pending.start_pos), max(changed_end, bar.position)

        self._mark_breakout_lifecycle_row(bar.position, pending, pending_state=True)
        return changed_start, max(changed_end, bar.position)

    def _finalize_pending_range_breakout(
        self,
        changed_start: int,
        changed_end: int,
        *,
        confirmation_pos: Optional[int] = None,
    ) -> Tuple[int, int]:
        pending = self._pending_range_breakout
        if pending is None:
            return changed_start, changed_end
        self._active_range = _pending_breakout_state(pending)
        end_pos = max(pending.start_pos, pending.break_pos - 1)
        changed_start, changed_end = self._close_horizontal_range(end_pos, changed_start, changed_end)
        if confirmation_pos is not None:
            self._mark_breakout_lifecycle_row(confirmation_pos, pending, confirmed=True)
            changed_end = max(changed_end, confirmation_pos)
        self._active_range = None
        self._pending_range_breakout = None
        return changed_start, changed_end

    def _mark_breakout_lifecycle_row(
        self,
        pos: int,
        pending: _PendingHorizontalRangeBreakout,
        *,
        attempt: bool = False,
        pending_state: bool = False,
        confirmed: bool = False,
        false_breakout: bool = False,
        reclaim: bool = False,
    ) -> None:
        if pos < 0 or pos >= len(self._outputs):
            return
        row = self._outputs[pos]
        if attempt:
            row["hr_breakout_attempt"] = True
        if pending_state:
            row["hr_pending_breakout"] = True
        if confirmed:
            row["hr_breakout_confirmed"] = True
        if false_breakout:
            row["hr_false_breakout"] = True
        if reclaim:
            row["hr_reclaim"] = True
        row["hr_break_direction"] = float(pending.break_direction)
        row["hr_break_extreme"] = pending.break_extreme

    def _try_start_horizontal_range(
        self,
        current_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = _build_horizontal_range_state(
            self._bars,
            self._range_swings,
            self.config,
            current_pos,
            self._min_range_start_pos,
        )
        if state is None:
            return changed_start, changed_end

        start_pos = state.start_pos
        mark_start = _range_mark_start(state)
        self._active_range = state
        self._outputs[start_pos]["hr_start"] = True
        self._outputs[start_pos]["hr_start_marker"] = state.start_value
        for pos in range(mark_start, current_pos + 1):
            self._outputs[pos]["horizontal_range"] = True
            self._outputs[pos]["hor_upper"] = state.upper
            self._outputs[pos]["hor_lower"] = state.lower
        return min(changed_start, mark_start), max(changed_end, current_pos)

    def _close_horizontal_range(
        self,
        end_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = self._active_range
        if state is None:
            return changed_start, changed_end
        mark_start = _range_mark_start(state)
        end_pos = min(max(end_pos, mark_start), len(self._bars) - 1)
        self._outputs[end_pos]["hr_end"] = True
        self._outputs[end_pos]["hr_end_marker"] = self._bars[end_pos].source
        self._min_range_start_pos = max(self._min_range_start_pos, end_pos + 1)
        for pos in range(mark_start, end_pos + 1):
            self._outputs[pos]["horizontal_range"] = True
            self._outputs[pos]["hor_upper"] = state.upper
            self._outputs[pos]["hor_lower"] = state.lower
        for pos in range(end_pos + 1, len(self._bars)):
            self._outputs[pos]["horizontal_range"] = False
            self._outputs[pos]["hor_upper"] = nan
            self._outputs[pos]["hor_lower"] = nan
        return min(changed_start, mark_start), max(changed_end, len(self._bars) - 1)

    def _is_alternating(self, swings: Sequence[_SwingPoint]) -> bool:
        return _is_alternating_swings(swings)

    def _swing_gaps_are_acceptable(self, swings: Sequence[_SwingPoint]) -> bool:
        return _swing_gaps_are_acceptable_for_config(swings, self.config)

    def _restart_anchor_after_failed_trend_swing(self, swing: _SwingPoint) -> int:
        """Return the earliest swing position that may seed an immediate reversal.

        The failing swing is already part of self._swings when this method is
        called. Keeping the immediately preceding confirmed swing eligible lets
        the realtime state machine recognize reversal structures such as
        peak -> trough -> lower peak -> lower trough after an uptrend fails,
        without reopening stale trend anchors from much earlier history.
        """

        if len(self._swings) >= 2 and self._swings[-1].position == swing.position:
            return self._swings[-2].position
        return swing.position

    def _update_trend_with_swing(
        self,
        swing: _SwingPoint,
        current_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        if self._active_trend is None:
            return self._try_start_trend_from_tail(current_pos, changed_start, changed_end)

        state = self._active_trend
        tol = self._current_tolerance(swing)
        extended = False
        if state.kind == "uptrend":
            if swing.kind == "peak" and state.last_peak is not None and swing.value >= state.last_peak - tol:
                state.last_peak = swing.value
                state.last_swing_pos = swing.position
                extended = True
            elif swing.kind == "trough" and state.last_trough is not None and swing.value >= state.last_trough - tol:
                state.last_trough = swing.value
                state.last_swing_pos = swing.position
                extended = True
        elif state.kind == "downtrend":
            if swing.kind == "trough" and state.last_trough is not None and swing.value <= state.last_trough + tol:
                state.last_trough = swing.value
                state.last_swing_pos = swing.position
                extended = True
            elif swing.kind == "peak" and state.last_peak is not None and swing.value <= state.last_peak + tol:
                state.last_peak = swing.value
                state.last_swing_pos = swing.position
                extended = True

        if extended:
            changed_start, changed_end = self._mark_active_trend_span(current_pos, changed_start, changed_end)
            return changed_start, changed_end

        close_pos = max(state.start_pos, swing.position - 1)
        changed_start, changed_end = self._close_trend(close_pos, changed_start, changed_end)
        restart_anchor = self._restart_anchor_after_failed_trend_swing(swing)
        self._min_trend_start_pos = max(self._min_trend_start_pos, restart_anchor)
        self._active_trend = None
        return self._try_start_trend_from_tail(current_pos, changed_start, changed_end)

    def _try_start_trend_from_tail(
        self,
        current_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        eligible = [s for s in self._swings if s.position >= self._min_trend_start_pos]
        if len(eligible) < 4:
            return changed_start, changed_end

        # Search from the most recent complete four-swing window backwards. This
        # keeps realtime semantics intact because every candidate is already a
        # confirmed swing, while avoiding a false negative when the latest four
        # swings are not the newest valid trend-start pattern.
        for end in range(len(eligible), 3, -1):
            s0, s1, s2, s3 = eligible[end - 4], eligible[end - 3], eligible[end - 2], eligible[end - 1]
            candidate = (s0, s1, s2, s3)
            if not self._is_alternating(candidate) or not self._swing_gaps_are_acceptable(candidate):
                continue

            if (
                s0.kind == "trough"
                and s1.kind == "peak"
                and s2.kind == "trough"
                and s3.kind == "peak"
                and s3.value > s1.value
                and s2.value > s0.value
            ):
                self._active_trend = _TrendState(
                    kind="uptrend",
                    start_pos=s0.position,
                    last_peak=s3.value,
                    last_trough=s2.value,
                    last_swing_pos=s3.position,
                )
                self._outputs[s0.position]["uptrend_start"] = True
                self._outputs[s0.position]["uptrend_start_marker"] = self._bars[s0.position].source
                return self._mark_active_trend_span(current_pos, min(changed_start, s0.position), changed_end)

            if (
                s0.kind == "peak"
                and s1.kind == "trough"
                and s2.kind == "peak"
                and s3.kind == "trough"
                and s3.value < s1.value
                and s2.value < s0.value
            ):
                self._active_trend = _TrendState(
                    kind="downtrend",
                    start_pos=s0.position,
                    last_peak=s2.value,
                    last_trough=s3.value,
                    last_swing_pos=s3.position,
                )
                self._outputs[s0.position]["downtrend_start"] = True
                self._outputs[s0.position]["downtrend_start_marker"] = self._bars[s0.position].source
                return self._mark_active_trend_span(current_pos, min(changed_start, s0.position), changed_end)

        return changed_start, changed_end

    def _current_tolerance(self, swing: _SwingPoint) -> float:
        atr = swing.atr
        if not _finite(atr) and self._bars:
            atr = self._bars[-1].atr
        if not _finite(atr):
            return 0.0
        return max(0.0, atr * self.config.hr_trend_tol_mult)

    def _mark_active_trend_span(
        self,
        current_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = self._active_trend
        if state is None:
            return changed_start, changed_end
        column = state.kind
        for pos in range(state.start_pos, current_pos + 1):
            self._outputs[pos][column] = True
        return min(changed_start, state.start_pos), max(changed_end, current_pos)

    def _mark_active_trend_current(
        self,
        pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = self._active_trend
        if state is None:
            return changed_start, changed_end
        self._outputs[pos][state.kind] = True
        return changed_start, max(changed_end, pos)

    def _close_trend(
        self,
        end_pos: int,
        changed_start: int,
        changed_end: int,
    ) -> Tuple[int, int]:
        state = self._active_trend
        if state is None:
            return changed_start, changed_end
        end_pos = min(max(end_pos, state.start_pos), len(self._bars) - 1)
        column = state.kind
        start_col = f"{column}_start"
        end_col = f"{column}_end"
        end_marker_col = f"{column}_end_marker"
        self._outputs[state.start_pos][start_col] = True
        self._outputs[end_pos][end_col] = True
        self._outputs[end_pos][end_marker_col] = self._bars[end_pos].source
        for pos in range(state.start_pos, end_pos + 1):
            self._outputs[pos][column] = True
        for pos in range(end_pos + 1, len(self._bars)):
            self._outputs[pos][column] = False
        return min(changed_start, state.start_pos), max(changed_end, len(self._bars) - 1)

    def _refresh_composite_flags(self, start: int, end: int) -> None:
        start = max(0, start)
        end = min(end, len(self._outputs) - 1)
        for pos in range(start, end + 1):
            row = self._outputs[pos]
            row["hr_uptrend"] = bool(row["horizontal_range"] and row["uptrend"])
            row["hr_downtrend"] = bool(row["horizontal_range"] and row["downtrend"])


# Public historical compute entrypoint -------------------------------------------------


def _validate_input_dataframe(df: pd.DataFrame, config: _Config) -> None:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas.DataFrame")
    if df.empty:
        # Empty dataframes are allowed; they return empty output columns.
        return
    required = tuple(dict.fromkeys((config.source, config.high, config.low, config.close)))
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}; available columns: {list(df.columns)}")
    duplicate_required = sorted(
        name for name in required if sum(1 for column in df.columns if column == name) > 1
    )
    if duplicate_required:
        raise ValueError(f"df required columns must be unique; duplicates: {duplicate_required}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("df index must be monotonic increasing")
    if df.index.has_duplicates:
        raise ValueError("df index must not contain duplicates")
    for index, high_value, low_value in zip(df.index, df[config.high], df[config.low]):
        try:
            high_f = _as_float(high_value, name=config.high)
            low_f = _as_float(low_value, name=config.low)
        except ValueError:
            continue
        if _finite(high_f) and _finite(low_f) and high_f < low_f:
            raise ValueError(
                f"finite OHLC rows must satisfy {config.high} >= {config.low}; "
                f"first malformed index: {index!r}"
            )


def _compute_historical(
    df: pd.DataFrame,
    *,
    source: str = "close",
    col: Optional[str] = None,
    high: str = "high",
    low: str = "low",
    close: str = "close",
    fractal_window: int = 5,
    trend_fractal_window: Optional[int] = None,
    range_fractal_window: Optional[int] = None,
    peak_column: Optional[str] = None,
    trough_column: Optional[str] = None,
    trend_peak_column: Optional[str] = None,
    trend_trough_column: Optional[str] = None,
    range_peak_column: Optional[str] = None,
    range_trough_column: Optional[str] = None,
    min_hr_band_perc: float = 0.005,
    hr_trend_length: int = 20,
    hr_trend_atr_mult: float = 1.0,
    hr_trend_atr_len: int = 500,
    hr_trend_tol_mult: float = 0.3,
    hr_trend_max_gap: int = 20,
    hr_min_inside_ratio: float = 0.8,
    min_range_swings: int = 4,
    hr_break_mode: str = "close",
) -> pd.DataFrame:
    """Compute Universal Trend Classifier outputs for a full dataframe.

    Historical compute records OHLC bars sequentially for ATR/continuity truth,
    then consumes controller-injected Peaks & Troughs event columns selected by
    ``trend_fractal_window`` and ``range_fractal_window``. It returns a copy of
    ``df`` with all indicator output columns appended.
    """

    config = _Config.from_params(
        source=source,
        col=col,
        high=high,
        low=low,
        close=close,
        fractal_window=fractal_window,
        trend_fractal_window=trend_fractal_window,
        range_fractal_window=range_fractal_window,
        peak_column=peak_column,
        trough_column=trough_column,
        trend_peak_column=trend_peak_column,
        trend_trough_column=trend_trough_column,
        range_peak_column=range_peak_column,
        range_trough_column=range_trough_column,
        min_hr_band_perc=min_hr_band_perc,
        hr_trend_length=hr_trend_length,
        hr_trend_atr_mult=hr_trend_atr_mult,
        hr_trend_atr_len=hr_trend_atr_len,
        hr_trend_tol_mult=hr_trend_tol_mult,
        hr_trend_max_gap=hr_trend_max_gap,
        hr_min_inside_ratio=hr_min_inside_ratio,
        min_range_swings=min_range_swings,
        hr_break_mode=hr_break_mode,
    )
    _validate_input_dataframe(df, config)
    if df.empty:
        result = df.copy()
        for name in _OUTPUT_COLUMNS:
            dtype = "bool" if name in _BOOLEAN_COLUMNS else "float64"
            result[name] = pd.Series(index=result.index, dtype=dtype)
        return result

    # Fail before replay if the controller did not inject the selected saved
    # Peaks & Troughs dependencies.  Trend and range are validated separately so
    # controller/source-resolution code can treat them as two independent
    # injection requests, then deduplicate if both resolve to the same pair.
    _require_peak_trough_columns_for_purpose(df, config, purpose="trend")
    _require_peak_trough_columns_for_purpose(df, config, purpose="range")

    # itertuples is used only as a row transport.  Calculation remains one bar at
    # a time and does not depend on vectorized rolling/window operations.
    required = (config.source, config.high, config.low, config.close)
    required_positions = tuple(df.columns.get_loc(name) for name in required)
    if any(not isinstance(pos, int) for pos in required_positions):
        raise ValueError("df required columns must be unique")
    source_pos, high_pos, low_pos, close_pos = required_positions
    records = list(df.itertuples(index=True, name=None))

    # First pass: build bar/ATR truth so Peaks & Troughs swing events can carry
    # the same pivot ATR that realtime would have known by confirmation time.
    atr_engine = _HistoricalReplay(config)
    for record in records:
        atr_engine.update_bar(
            index=record[0],
            source=record[source_pos + 1],
            high=record[high_pos + 1],
            low=record[low_pos + 1],
            close=record[close_pos + 1],
        )

    atr_values = [bar.atr for bar in atr_engine._bars]
    range_swings = _build_swings_from_peak_trough_columns(df, config, atr_values, purpose="range")
    trend_swings = _build_swings_from_peak_trough_columns(df, config, atr_values, purpose="trend")

    range_swings_by_confirmation_pos: Dict[int, List[_SwingPoint]] = {}
    range_half_window = config.range_fractal_window // 2
    for swing in range_swings:
        confirmation_pos = swing.position + range_half_window
        if 0 <= confirmation_pos < len(records):
            range_swings_by_confirmation_pos.setdefault(confirmation_pos, []).append(swing)

    # Second pass: replay bars and confirm range swings in the same chronological
    # order realtime will use. This lets an active range continue through bars
    # after its confirmation point instead of only backfilling up to that point.
    engine = _HistoricalReplay(config)
    for current_pos, record in enumerate(records):
        engine.update_bar(
            index=record[0],
            source=record[source_pos + 1],
            high=record[high_pos + 1],
            low=record[low_pos + 1],
            close=record[close_pos + 1],
        )
        for swing in range_swings_by_confirmation_pos.get(current_pos, []):
            engine.confirm_range_swing(swing, current_pos=current_pos)

    outputs = engine.to_output_frame()
    result = df.copy()
    for name in _OUTPUT_COLUMNS:
        result[name] = outputs[name].tolist()

    uptrends, downtrends = _detect_trend_intervals_from_swings_by_valid_segments(
        engine._bars,
        trend_swings,
    )
    _apply_external_trend_intervals(result, uptrends, downtrends)

    return result


def _calculate_universal_trend_classifier(
    data: pd.DataFrame,
    parameters: Mapping[str, object],
    bindings: Mapping[str, object],
) -> tuple[tuple[pd.Series, ...], Mapping[str, object]]:
    from .common import _fractal_extrema, _numeric_series

    fractal_window = int(parameters["fractal_window"])
    trend_window = int(parameters["trend_fractal_window"])
    range_window = int(parameters["range_fractal_window"])
    if fractal_window != trend_window:
        raise ValueError("fractal_window and trend_fractal_window must be equal")

    peak_column = parameters["peak_column"]
    trough_column = parameters["trough_column"]
    if (peak_column is None) != (trough_column is None):
        raise ValueError("peak_column and trough_column must be provided together")

    working = data.copy(deep=True)
    high = _numeric_series(working, "high", context="universal_trend_classifier")
    low = _numeric_series(working, "low", context="universal_trend_classifier")
    if peak_column is None:
        trend_peak = _default_peak_column(trend_window)
        trend_trough = _default_trough_column(trend_window)
        working[trend_peak] = _fractal_extrema(high, window=trend_window, peak=True)
        working[trend_trough] = _fractal_extrema(low, window=trend_window, peak=False)
    else:
        if not isinstance(peak_column, str) or not isinstance(trough_column, str):
            raise ValueError("custom peak_column and trough_column must be strings")
        if peak_column not in working.columns or trough_column not in working.columns:
            raise ValueError("custom peak_column and trough_column must exist")
        _numeric_series(working, peak_column, context="universal_trend_classifier")
        _numeric_series(working, trough_column, context="universal_trend_classifier")

    range_peak = _default_peak_column(range_window)
    range_trough = _default_trough_column(range_window)
    historical_parameters = dict(parameters)
    if peak_column is not None and {peak_column, trough_column}.intersection({range_peak, range_trough}):
        range_peak, range_trough = _private_range_dependency_columns(
            working.columns,
            range_peak,
            range_trough,
        )
        historical_parameters["range_peak_column"] = range_peak
        historical_parameters["range_trough_column"] = range_trough
    working[range_peak] = _fractal_extrema(high, window=range_window, peak=True)
    working[range_trough] = _fractal_extrema(low, window=range_window, peak=False)

    result = _compute_historical(working, **historical_parameters)
    return tuple(pd.Series(result[name], index=data.index) for name in _OUTPUT_COLUMNS), {}
