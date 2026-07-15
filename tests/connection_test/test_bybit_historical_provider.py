from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp
import pytest

from leonardo.connection import HistoricalProviderRequestError
from leonardo.connection import bybit
from leonardo.connection.bybit import BybitHistoricalProvider


class _FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, object] | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {}
        self._json_error = json_error

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def json(self, *, content_type: object = None) -> object:
        _ = content_type
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeSession:
    closed = False

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, *, params: object = None) -> object:
        self.requests.append((url, dict(params or {})))
        if not self._responses:
            raise AssertionError("unexpected Bybit request")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response



def _provider_with_session(responses: list[object]) -> tuple[BybitHistoricalProvider, _FakeSession]:
    provider = BybitHistoricalProvider()
    session = _FakeSession(responses)
    provider._session = session  # type: ignore[assignment]
    return provider, session


def test_bybit_historical_response_is_normalized_and_sorted(monkeypatch) -> None:
    provider = BybitHistoricalProvider()
    captured = {}

    async def fake_get(path, *, params=None):
        captured["path"] = path
        captured["params"] = dict(params or {})
        return {
            "retCode": 0,
            "result": {
                "list": [
                    ["120000", "2", "3", "1", "2.5", "20", "0"],
                    ["60000", "1", "2", "0.5", "1.5", "10", "0"],
                ]
            },
        }

    monkeypatch.setattr(provider, "_public_get_json", fake_get)
    candles = asyncio.run(
        provider.fetch_ohlcv_historical(
            market="linear",
            symbol="btc-usdt",
            timeframe="60m",
            start_ms=1,
            end_ms=2,
            limit=5000,
        )
    )

    assert captured["path"] == "/v5/market/kline"
    assert captured["params"]["category"] == "linear"
    assert captured["params"]["symbol"] == "BTCUSDT"
    assert captured["params"]["interval"] == "60"
    assert captured["params"]["limit"] == 1000
    assert [item.ts_ms for item in candles] == [60_000, 120_000]


def test_bybit_standard_kline_rejects_options_market() -> None:
    provider = BybitHistoricalProvider()

    with pytest.raises(ValueError, match="spot, linear, and inverse"):
        provider.supported_timeframes("options")


def test_bybit_marks_current_month_candle_open(monkeypatch) -> None:
    from datetime import UTC, datetime

    provider = BybitHistoricalProvider()
    month_open = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp() * 1000)
    mid_month = int(datetime(2026, 7, 13, tzinfo=UTC).timestamp() * 1000)

    async def fake_get(_path, *, params=None):
        return {
            "retCode": 0,
            "time": mid_month,
            "result": {"list": [[str(month_open), "1", "2", "0.5", "1.5", "10"]]},
        }

    monkeypatch.setattr(provider, "_public_get_json", fake_get)
    candles = asyncio.run(
        provider.fetch_ohlcv_historical(
            market="linear",
            symbol="BTCUSDT",
            timeframe="1M",
        )
    )

    assert candles[0].is_closed is False


def test_bybit_permanent_api_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_MIN_INTERVAL_SECONDS", 0.0)
    provider, session = _provider_with_session(
        [_FakeResponse({"retCode": 10001, "retMsg": "params error: Symbol Is Invalid"})]
    )

    with pytest.raises(HistoricalProviderRequestError) as captured:
        asyncio.run(
            provider.fetch_ohlcv_historical(
                market="linear",
                symbol="SOLDUSDT",
                timeframe="1m",
                limit=1,
            )
        )

    error = captured.value
    assert error.retryable is False
    assert error.attempts_exhausted is False
    assert error.code == 10001
    assert error.operation == "historical_ohlcv"
    assert len(session.requests) == 1


def test_bybit_rate_limit_retries_use_reset_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_MIN_INTERVAL_SECONDS", 0.0)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    reset_ms = int(time.time() * 1000) + 250
    provider, session = _provider_with_session(
        [
            _FakeResponse(
                {"retCode": 10006, "retMsg": "Too many visits"},
                headers={"X-Bapi-Limit-Reset-Timestamp": str(reset_ms)},
            ),
            _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 1234}),
        ]
    )

    assert asyncio.run(provider.get_server_time_ms()) == 1234
    assert len(session.requests) == 2
    assert sleeps and sleeps[0] > 0


def test_bybit_exhausted_transient_retries_are_marked_for_no_outer_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bybit, "_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(bybit, "_MAX_ATTEMPTS", 3)

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    provider, session = _provider_with_session(
        [
            _FakeResponse({"retCode": 0}, status=503),
            _FakeResponse({"retCode": 0}, status=503),
            _FakeResponse({"retCode": 0}, status=503),
        ]
    )

    with pytest.raises(HistoricalProviderRequestError) as captured:
        asyncio.run(provider.get_server_time_ms())

    error = captured.value
    assert error.retryable is True
    assert error.attempts_exhausted is True
    assert error.status == 503
    assert len(session.requests) == 3


def test_bybit_cancellation_during_retry_sleep_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bybit, "_MIN_INTERVAL_SECONDS", 0.0)
    sleep_started = asyncio.Event()

    async def blocking_sleep(_delay: float) -> None:
        sleep_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bybit.asyncio, "sleep", blocking_sleep)
    provider, session = _provider_with_session(
        [
            _FakeResponse({"retCode": 10006, "retMsg": "Too many visits"}),
            _FakeResponse({"retCode": 0, "time": 1234}),
        ]
    )

    async def scenario() -> None:
        task = asyncio.create_task(provider.get_server_time_ms())
        await asyncio.wait_for(sleep_started.wait(), 1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(session.requests) == 1


def test_bybit_transport_failure_is_bounded_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bybit, "_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(bybit, "_MAX_ATTEMPTS", 2)

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    provider, session = _provider_with_session(
        [aiohttp.ClientConnectionError("offline"), aiohttp.ClientConnectionError("offline")]
    )

    with pytest.raises(HistoricalProviderRequestError) as captured:
        asyncio.run(provider.get_server_time_ms())

    error = captured.value
    assert error.retryable is True
    assert error.attempts_exhausted is True
    assert error.operation == "server_time"
    assert len(session.requests) == 2
