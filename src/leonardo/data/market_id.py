"""Canonical market-series identity and normalization policy."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ALLOWED_MARKET_TYPES = frozenset({"spot", "linear", "inverse", "options"})
_EXCHANGE_RE = re.compile(r"^[a-z0-9_]+$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9.]+$")
_TIMEFRAME_RE = re.compile(r"^(\d+)\s*([A-Za-z]+)$")
_TIMEFRAME_UNIT_ALIASES = {
    "m": "m",
    "min": "m",
    "mins": "m",
    "minute": "m",
    "minutes": "m",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "d": "d",
    "day": "d",
    "days": "d",
    "w": "w",
    "wk": "w",
    "wks": "w",
    "week": "w",
    "weeks": "w",
    "mo": "M",
    "mon": "M",
    "month": "M",
    "months": "M",
    "mth": "M",
    "mths": "M",
}


@dataclass(frozen=True, slots=True)
class MarketId:
    """Identify one canonical exchange market series without storage policy."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        for name in ("exchange", "market_type", "symbol", "timeframe"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())

    def as_key(self) -> str:
        return ":".join((self.exchange, self.market_type, self.symbol, self.timeframe))


def normalize_exchange(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or _EXCHANGE_RE.fullmatch(normalized) is None:
        raise ValueError(f"invalid exchange: {value!r}")
    return normalized


def normalize_market_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ALLOWED_MARKET_TYPES:
        raise ValueError(
            f"invalid market_type: {value!r} (allowed: {sorted(_ALLOWED_MARKET_TYPES)})"
        )
    return normalized


def normalize_symbol(value: str) -> str:
    normalized = str(value or "").strip().upper()
    for separator in ("/", "-", "_", ":", " "):
        normalized = normalized.replace(separator, "")
    if not normalized or _SYMBOL_RE.fullmatch(normalized) is None:
        raise ValueError(f"invalid symbol: {value!r}")
    return normalized


def normalize_timeframe(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("timeframe required")
    if raw.isdigit():
        amount = int(raw)
        if amount <= 0:
            raise ValueError("timeframe amount must be greater than zero")
        return f"{amount}m"
    if re.fullmatch(r"\d+M", raw):
        amount = int(raw[:-1])
        if amount <= 0:
            raise ValueError("timeframe amount must be greater than zero")
        return f"{amount}M"
    match = _TIMEFRAME_RE.fullmatch(raw)
    if match is None:
        raise ValueError(f"invalid timeframe: {value!r}")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("timeframe amount must be greater than zero")
    unit_raw = match.group(2)
    unit = _TIMEFRAME_UNIT_ALIASES.get(unit_raw.lower())
    if unit is None:
        raise ValueError(f"invalid timeframe unit: {unit_raw!r}")
    return f"{amount}{unit}"


def canonicalize_market_id(
    exchange: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> MarketId:
    """Normalize raw identity components into Leonardo's shared ``MarketId``."""

    return MarketId(
        exchange=normalize_exchange(exchange),
        market_type=normalize_market_type(market_type),
        symbol=normalize_symbol(symbol),
        timeframe=normalize_timeframe(timeframe),
    )


def timeframe_duration_ms(timeframe: str) -> int | None:
    """Return fixed duration in milliseconds, or ``None`` for month candles."""

    canonical = normalize_timeframe(timeframe)
    if canonical.endswith("M"):
        return None
    amount = int(canonical[:-1])
    unit = canonical[-1]
    multipliers = {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
        "w": 7 * 86_400_000,
    }
    return amount * multipliers[unit]


def timeframe_to_storage_segment(timeframe: str) -> str:
    """Return a case-insensitive-filesystem-safe timeframe directory segment."""

    canonical = normalize_timeframe(timeframe)
    return f"{canonical[:-1]}mo" if canonical.endswith("M") else canonical


def storage_segment_to_timeframe(segment: str) -> str:
    raw = str(segment or "").strip()
    if raw.lower().endswith("mo") and raw[:-2].isdigit():
        return f"{int(raw[:-2])}M"
    return normalize_timeframe(raw)
