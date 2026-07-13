"""Connection Area application service for provider capabilities and sessions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from threading import RLock
from typing import AsyncIterator

from leonardo.connection.provider import HistoricalOHLCVProvider
from leonardo.connection.registry import ProviderRegistry
from leonardo.core.connection_registry import ConnectionRegistry


class ConnectionApplicationService:
    def __init__(self, providers: ProviderRegistry, runtime: ConnectionRegistry) -> None:
        self._providers = providers
        self._runtime = runtime
        self._session_lock = RLock()
        self._active_sessions: dict[str, int] = {}

    def provider_names(self) -> tuple[str, ...]:
        return self._providers.names()

    def supported_markets(self, provider_name: str) -> tuple[str, ...]:
        provider = self._providers.create(provider_name)
        return tuple(sorted(provider.supported_markets()))

    def supported_timeframes(self, provider_name: str, market: str) -> tuple[str, ...]:
        provider = self._providers.create(provider_name)
        return tuple(sorted(provider.supported_timeframes(market), key=_timeframe_sort_key))

    @asynccontextmanager
    async def provider_session(self, provider_name: str) -> AsyncIterator[HistoricalOHLCVProvider]:
        provider = self._providers.create(provider_name)
        connection_id = self._ensure_registered(provider_name)
        self._begin_session(connection_id)
        failed_error: Exception | None = None
        try:
            await provider.open()
            self._runtime.mark_connected(connection_id)
            yield provider
        except BaseException as error:
            if isinstance(error, Exception):
                failed_error = error
                self._mark_session_failure(connection_id, error)
            raise
        finally:
            close_error: Exception | None = None
            try:
                await provider.close()
            except Exception as error:
                close_error = error
                self._mark_session_failure(connection_id, error)
                if failed_error is None:
                    raise
            finally:
                remaining = self._end_session(connection_id)
                if remaining == 0:
                    if failed_error is None and close_error is None:
                        self._runtime.mark_disconnected(connection_id)
                elif failed_error is None and close_error is None:
                    self._runtime.mark_connected(connection_id)

    def _begin_session(self, connection_id: str) -> None:
        with self._session_lock:
            active = self._active_sessions.get(connection_id, 0)
            self._active_sessions[connection_id] = active + 1
        if active == 0:
            self._runtime.mark_connecting(connection_id)

    def _end_session(self, connection_id: str) -> int:
        with self._session_lock:
            active = self._active_sessions.get(connection_id, 0)
            remaining = max(0, active - 1)
            if remaining:
                self._active_sessions[connection_id] = remaining
            else:
                self._active_sessions.pop(connection_id, None)
            return remaining

    def _mark_session_failure(self, connection_id: str, error: Exception) -> None:
        with self._session_lock:
            active = self._active_sessions.get(connection_id, 0)
        if active > 1:
            self._runtime.mark_degraded(connection_id, error=str(error))
        else:
            self._runtime.mark_failed(connection_id, error=str(error))

    def _ensure_registered(self, provider_name: str) -> str:
        connection_id = self._connection_id(provider_name)
        with self._session_lock:
            existing = {item.connection_id for item in self._runtime.connection_states()}
            if connection_id not in existing:
                self._runtime.register_connection(
                    connection_id,
                    label=f"{str(provider_name).title()} Historical REST",
                    protocol="https",
                    metadata={
                        "provider": str(provider_name).strip().lower(),
                        "capability": "historical_ohlcv",
                    },
                )
                self._runtime.mark_disconnected(connection_id)
        return connection_id

    @staticmethod
    def _connection_id(provider_name: str) -> str:
        return f"connection.{str(provider_name).strip().lower()}.historical_rest"


def _timeframe_sort_key(value: str) -> tuple[int, int]:
    unit_order = {"m": 0, "h": 1, "d": 2, "w": 3, "M": 4}
    text = str(value)
    return unit_order.get(text[-1], 99), int(text[:-1]) if text[:-1].isdigit() else 0
