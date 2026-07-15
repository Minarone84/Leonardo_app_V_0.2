"""Owner-local provider boundary for historical OHLCV access."""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ProviderCandle:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


class HistoricalProviderRequestError(RuntimeError):
    """Typed provider failure used to make retry decisions explicit.

    Provider adapters own wire-level classification. Callers may retry only when
    ``retryable`` is true and the provider has not already exhausted its own
    bounded retry policy.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        operation: str,
        retryable: bool,
        attempts_exhausted: bool = False,
        status: int | None = None,
        code: int | str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = str(provider)
        self.operation = str(operation)
        self.retryable = bool(retryable)
        self.attempts_exhausted = bool(attempts_exhausted)
        self.status = status
        self.code = code


@runtime_checkable
class HistoricalOHLCVProvider(Protocol):
    @property
    def name(self) -> str: ...

    def supported_markets(self) -> Set[str]: ...

    def supported_timeframes(self, market: str) -> Set[str]: ...

    def max_historical_ohlcv_limit(self, market: str) -> int | None: ...

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def get_server_time_ms(self) -> int: ...

    async def oldest_historical_ohlcv_ts_ms(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int | None = None,
    ) -> int | None: ...

    async def fetch_ohlcv_historical(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> Sequence[ProviderCandle]: ...
