from __future__ import annotations

from leonardo.connection.registry import ProviderRegistry


class _Provider:
    name = "fake"

    def supported_markets(self):
        return {"linear"}

    def supported_timeframes(self, market):
        assert market == "linear"
        return {"1h", "1m", "1M"}

    def max_historical_ohlcv_limit(self, market):
        return 1000

    async def open(self):
        return None

    async def close(self):
        return None

    async def get_server_time_ms(self):
        return 0

    async def oldest_historical_ohlcv_ts_ms(self, **_kwargs):
        return None

    async def fetch_ohlcv_historical(self, **_kwargs):
        return ()


def test_provider_registry_uses_factories_and_rejects_duplicates() -> None:
    registry = ProviderRegistry()
    registry.register("fake", _Provider)
    assert registry.names() == ("fake",)
    assert registry.create("FAKE").name == "fake"


def test_connection_summary_remains_connected_while_another_session_is_active() -> None:
    from leonardo.connection.service import ConnectionApplicationService
    from leonardo.core.connection_registry import ConnectionRegistry

    providers = ProviderRegistry()
    providers.register("fake", _Provider)
    runtime = ConnectionRegistry()
    service = ConnectionApplicationService(providers, runtime)

    async def exercise() -> tuple[str, str, str]:
        async with service.provider_session("fake"):
            first = runtime.connection_states()[0].status
            async with service.provider_session("fake"):
                nested = runtime.connection_states()[0].status
            after_nested = runtime.connection_states()[0].status
        final = runtime.connection_states()[0].status
        return first, nested, after_nested, final

    assert __import__("asyncio").run(exercise()) == (
        "connected",
        "connected",
        "connected",
        "disconnected",
    )
