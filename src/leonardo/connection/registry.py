"""Provider factory registry owned by the Connection Area."""

from __future__ import annotations

from collections.abc import Callable

from leonardo.connection.provider import HistoricalOHLCVProvider

ProviderFactory = Callable[[], HistoricalOHLCVProvider]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory) -> None:
        key = str(name or "").strip().lower()
        if not key:
            raise ValueError("provider name must be a non-empty string")
        if not callable(factory):
            raise TypeError("factory must be callable")
        if key in self._factories:
            raise ValueError(f"provider already registered: {key}")
        self._factories[key] = factory

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def create(self, name: str) -> HistoricalOHLCVProvider:
        key = str(name or "").strip().lower()
        try:
            provider = self._factories[key]()
        except KeyError:
            raise KeyError(f"unknown provider: {key}. supported={list(self.names())}") from None
        if not isinstance(provider, HistoricalOHLCVProvider):
            raise TypeError(f"provider factory {key!r} returned an incompatible object")
        return provider


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()

    def build_bybit() -> HistoricalOHLCVProvider:
        from leonardo.connection.bybit import BybitHistoricalProvider

        return BybitHistoricalProvider(testnet=False)

    registry.register("bybit", build_bybit)
    return registry
