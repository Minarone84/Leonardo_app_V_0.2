"""Shared per-dataset operation locks for mutable OHLCV workflows."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from leonardo.data import MarketId


class OHLCVDatasetOperationLocks:
    """Serialize mutable operations that target the same canonical dataset.

    Downloads, repairs, and destructive Maintenance operations share this
    owner-local authority. Unrelated MarketIds remain independently runnable.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, market: MarketId) -> AsyncIterator[None]:
        if not isinstance(market, MarketId):
            raise TypeError("market must be a MarketId")
        lock = self._locks.setdefault(market.as_key(), asyncio.Lock())
        async with lock:
            yield
