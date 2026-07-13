from __future__ import annotations

import asyncio

import pytest

from leonardo.connection.bybit import BybitHistoricalProvider


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
