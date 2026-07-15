"""Bybit v5 historical OHLCV provider adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence, Set
from datetime import UTC, datetime
from typing import Any

import aiohttp

from leonardo.connection.provider import (
    HistoricalProviderRequestError,
    ProviderCandle,
)
from leonardo.data import (
    normalize_market_type,
    normalize_symbol,
    normalize_timeframe,
    timeframe_duration_ms,
)

_BYBIT_REST_MAINNET = "https://api.bybit.com"
_BYBIT_REST_TESTNET = "https://api-testnet.bybit.com"
_BYBIT_CANONICAL_MARKETS = ("spot", "linear", "inverse")
_BYBIT_TIMEFRAMES = (
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h",
    "1d", "1w", "1M",
)
_BYBIT_TIMEFRAME_ALIASES = {"60m": "1h"}
_BYBIT_INTERVALS = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "1w": "W", "1M": "M",
}
_MAX_LIMIT = 1000
_MAX_ATTEMPTS = 4
_MIN_INTERVAL_SECONDS = 0.20
_RATE_LIMIT_CODE = 10006
_RATE_LIMIT_FALLBACK_SECONDS = 1.0
_MAX_RATE_LIMIT_SLEEP_SECONDS = 10.0
_RESET_CUSHION_SECONDS = 0.05
_MONTH_DISCOVERY_STEP_MS = 31 * 86_400_000


class BybitHistoricalProvider:
    """Async historical-only Bybit adapter. It owns Bybit wire semantics."""

    def __init__(self, *, testnet: bool = False, request_timeout_seconds: float = 30.0) -> None:
        self._base_url = _BYBIT_REST_TESTNET if testnet else _BYBIT_REST_MAINNET
        self._timeout_seconds = float(request_timeout_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    @property
    def name(self) -> str:
        return "bybit"

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()

    def supported_markets(self) -> Set[str]:
        return set(_BYBIT_CANONICAL_MARKETS)

    def supported_timeframes(self, market: str) -> Set[str]:
        self._normalize_market(market)
        return set(_BYBIT_TIMEFRAMES)

    def max_historical_ohlcv_limit(self, market: str) -> int:
        self._normalize_market(market)
        return _MAX_LIMIT

    async def get_server_time_ms(self) -> int:
        data = await self._public_get_json("/v5/market/time")
        value = data.get("time")
        if value is None:
            raise self._response_error(
                "Bybit server time response did not include 'time'",
                operation="server_time",
            )
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise self._response_error(
                f"Bybit server time is invalid: {value!r}",
                operation="server_time",
            ) from error

    async def fetch_ohlcv_historical(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> Sequence[ProviderCandle]:
        category = self._normalize_market(market)
        canonical_timeframe = self._normalize_timeframe(timeframe)
        page_limit = _MAX_LIMIT if limit in (None, 0) else min(_MAX_LIMIT, max(1, int(limit)))
        params: dict[str, str | int] = {
            "category": category,
            "symbol": normalize_symbol(symbol),
            "interval": _BYBIT_INTERVALS[canonical_timeframe],
            "limit": page_limit,
        }
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)
        data = await self._public_get_json("/v5/market/kline", params=params)
        result = data.get("result")
        if not isinstance(result, Mapping):
            raise self._response_error(
                "Bybit kline response did not include a result mapping",
                operation="historical_ohlcv",
            )
        rows = result.get("list", ())
        if not isinstance(rows, list):
            raise self._response_error(
                "Bybit kline response list is invalid",
                operation="historical_ohlcv",
            )
        candles: list[ProviderCandle] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise self._response_error(
                    f"Bybit returned an invalid kline row: {row!r}",
                    operation="historical_ohlcv",
                )
            try:
                candle = ProviderCandle(
                    ts_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    is_closed=True,
                )
            except (TypeError, ValueError, OverflowError) as error:
                raise self._response_error(
                    f"Bybit returned a non-numeric kline row: {row!r}",
                    operation="historical_ohlcv",
                ) from error
            candles.append(candle)
        candles.sort(key=lambda candle: candle.ts_ms)
        try:
            server_time_ms = int(data.get("time") or 0)
        except (TypeError, ValueError) as error:
            raise self._response_error(
                f"Bybit response time is invalid: {data.get('time')!r}",
                operation="historical_ohlcv",
            ) from error
        if server_time_ms and candles:
            newest = candles[-1]
            if _candle_close_ms(newest.ts_ms, canonical_timeframe) > server_time_ms:
                candles[-1] = ProviderCandle(
                    ts_ms=newest.ts_ms,
                    open=newest.open,
                    high=newest.high,
                    low=newest.low,
                    close=newest.close,
                    volume=newest.volume,
                    is_closed=False,
                )
        return tuple(candles)

    async def oldest_historical_ohlcv_ts_ms(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int | None = None,
    ) -> int | None:
        category = self._normalize_market(market)
        canonical_timeframe = self._normalize_timeframe(timeframe)
        step_ms = timeframe_duration_ms(canonical_timeframe) or _MONTH_DISCOVERY_STEP_MS
        server_time_ms = await self.get_server_time_ms()
        if server_time_ms <= 0:
            return None

        async def has_candle_through(end_ms: int) -> bool:
            rows = await self.fetch_ohlcv_historical(
                market=category,
                symbol=symbol,
                timeframe=canonical_timeframe,
                start_ms=0,
                end_ms=max(0, int(end_ms)),
                limit=1,
            )
            return bool(rows)

        if not await has_candle_through(server_time_ms):
            return None
        low = 0
        high = int(server_time_ms)
        while high - low > step_ms:
            midpoint = low + ((high - low) // 2)
            if await has_candle_through(midpoint):
                high = midpoint
            else:
                low = midpoint + 1
        final_limit = _MAX_LIMIT if limit in (None, 0) else min(_MAX_LIMIT, max(1, int(limit)))
        rows = await self.fetch_ohlcv_historical(
            market=category,
            symbol=symbol,
            timeframe=canonical_timeframe,
            start_ms=max(0, high - step_ms),
            end_ms=min(server_time_ms, high + step_ms),
            limit=final_limit,
        )
        return rows[0].ts_ms if rows else None

    async def _public_get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Mapping[str, Any]:
        await self.open()
        assert self._session is not None
        last_error: HistoricalProviderRequestError | None = None
        operation = _operation_for_path(path)
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            retry_delay: float | None = None
            try:
                async with self._request_lock:
                    await self._pace_locked()
                    async with self._session.get(
                        f"{self._base_url}{path}", params=params
                    ) as response:
                        status = int(getattr(response, "status", 200) or 200)
                        headers = getattr(response, "headers", {}) or {}
                        try:
                            payload = await response.json(content_type=None)
                        except asyncio.CancelledError:
                            raise
                        except Exception as error:
                            if status == 429:
                                last_error = HistoricalProviderRequestError(
                                    f"Bybit rate limit response for {operation}: HTTP 429",
                                    provider=self.name,
                                    operation=operation,
                                    retryable=True,
                                    status=status,
                                    code=_RATE_LIMIT_CODE,
                                )
                                retry_delay = self._rate_limit_delay(headers, attempt)
                            else:
                                last_error = HistoricalProviderRequestError(
                                    f"Bybit JSON response could not be decoded for {operation}: {error}",
                                    provider=self.name,
                                    operation=operation,
                                    retryable=(
                                        status < 400
                                        or self._is_retryable_http_status(status)
                                    ),
                                    status=status,
                                )
                        else:
                            if not isinstance(payload, Mapping):
                                last_error = HistoricalProviderRequestError(
                                    f"Bybit returned a non-mapping JSON response for {operation}",
                                    provider=self.name,
                                    operation=operation,
                                    retryable=True,
                                    status=status,
                                )
                            else:
                                self._update_pacing_from_headers(headers)
                                ret_code = self._ret_code(payload)
                                if self._is_rate_limited(status, payload):
                                    last_error = HistoricalProviderRequestError(
                                        f"Bybit rate limit response for {operation}: "
                                        f"{payload.get('retMsg') or 'rate limited'}",
                                        provider=self.name,
                                        operation=operation,
                                        retryable=True,
                                        status=status,
                                        code=ret_code,
                                    )
                                    retry_delay = self._rate_limit_delay(headers, attempt)
                                elif status >= 400:
                                    retryable = self._is_retryable_http_status(status)
                                    failure = HistoricalProviderRequestError(
                                        f"Bybit HTTP {status} for {operation}: {payload!r}",
                                        provider=self.name,
                                        operation=operation,
                                        retryable=retryable,
                                        status=status,
                                        code=ret_code,
                                    )
                                    if not retryable:
                                        raise failure
                                    last_error = failure
                                elif ret_code not in (None, 0):
                                    raise HistoricalProviderRequestError(
                                        f"Bybit API error {payload.get('retCode')} for {operation}: "
                                        f"{payload.get('retMsg')}",
                                        provider=self.name,
                                        operation=operation,
                                        retryable=False,
                                        status=status,
                                        code=ret_code,
                                    )
                                else:
                                    return payload
                        if last_error is not None and not last_error.retryable:
                            raise last_error
            except asyncio.CancelledError:
                raise
            except HistoricalProviderRequestError as error:
                if not error.retryable:
                    raise
                last_error = error
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
                last_error = HistoricalProviderRequestError(
                    f"Bybit transport failure for {operation}: "
                    f"{type(error).__name__}: {error}",
                    provider=self.name,
                    operation=operation,
                    retryable=True,
                )
            if attempt >= _MAX_ATTEMPTS:
                break
            await asyncio.sleep(
                retry_delay
                if retry_delay is not None
                else min(float(attempt), _MAX_RATE_LIMIT_SLEEP_SECONDS)
            )
        assert last_error is not None
        raise HistoricalProviderRequestError(
            f"Bybit request failed after {_MAX_ATTEMPTS} attempts for {operation}: "
            f"{last_error}",
            provider=self.name,
            operation=operation,
            retryable=True,
            attempts_exhausted=True,
            status=last_error.status,
            code=last_error.code,
        ) from last_error

    async def _pace_locked(self) -> None:
        delay = self._next_request_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._next_request_at = time.monotonic() + _MIN_INTERVAL_SECONDS

    def _update_pacing_from_headers(self, headers: object) -> None:
        remaining = self._header_int(headers, "X-Bapi-Limit-Status")
        if remaining is None or remaining > 0:
            return
        delay = self._reset_delay(headers)
        if delay is not None:
            self._next_request_at = max(self._next_request_at, time.monotonic() + delay)

    def _rate_limit_delay(self, headers: object, attempt: int) -> float:
        reset = self._reset_delay(headers)
        if reset is not None:
            return reset
        return min(_RATE_LIMIT_FALLBACK_SECONDS * max(1, attempt), _MAX_RATE_LIMIT_SLEEP_SECONDS)

    def _reset_delay(self, headers: object) -> float | None:
        reset_ms = self._header_int(headers, "X-Bapi-Limit-Reset-Timestamp")
        if reset_ms is None:
            return None
        delay = (reset_ms / 1000.0) - time.time() + _RESET_CUSHION_SECONDS
        if delay <= 0:
            return None
        return min(delay, _MAX_RATE_LIMIT_SLEEP_SECONDS)

    @staticmethod
    def _is_rate_limited(status: int, payload: Mapping[str, Any]) -> bool:
        return status == 429 or BybitHistoricalProvider._ret_code(payload) == _RATE_LIMIT_CODE

    @staticmethod
    def _is_retryable_http_status(status: int) -> bool:
        return status in {408, 425} or status >= 500

    @staticmethod
    def _ret_code(payload: Mapping[str, Any]) -> int | None:
        raw = payload.get("retCode")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _header_int(headers: object, name: str) -> int | None:
        getter = getattr(headers, "get", None)
        raw = getter(name) if callable(getter) else None
        if raw is None:
            return None
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_market(market: str) -> str:
        canonical = normalize_market_type(market)
        if canonical not in _BYBIT_CANONICAL_MARKETS:
            raise ValueError(
                "Bybit historical kline supports only spot, linear, and inverse markets"
            )
        return canonical

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        canonical = normalize_timeframe(timeframe)
        canonical = _BYBIT_TIMEFRAME_ALIASES.get(canonical, canonical)
        if canonical not in _BYBIT_INTERVALS:
            raise ValueError(f"Bybit does not support timeframe: {timeframe!r}")
        return canonical

    def _response_error(
        self,
        message: str,
        *,
        operation: str,
    ) -> HistoricalProviderRequestError:
        return HistoricalProviderRequestError(
            message,
            provider=self.name,
            operation=operation,
            retryable=False,
        )


def _operation_for_path(path: str) -> str:
    if path.endswith("/time"):
        return "server_time"
    if path.endswith("/kline"):
        return "historical_ohlcv"
    return str(path)


def _candle_close_ms(open_ts_ms: int, timeframe: str) -> int:
    duration_ms = timeframe_duration_ms(timeframe)
    if duration_ms is not None:
        return int(open_ts_ms) + duration_ms
    canonical = normalize_timeframe(timeframe)
    if canonical != "1M":
        raise ValueError(f"unsupported variable-duration timeframe: {timeframe!r}")
    opened = datetime.fromtimestamp(int(open_ts_ms) / 1000.0, tz=UTC)
    year = opened.year + (1 if opened.month == 12 else 0)
    month = 1 if opened.month == 12 else opened.month + 1
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)
