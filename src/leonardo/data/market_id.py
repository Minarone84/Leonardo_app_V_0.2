"""Canonical market-series identity shared across Leonardo Areas."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketId:
    """Identify one exchange market series without embedding storage policy."""

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
