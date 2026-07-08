"""Static Connection Suite provider capability catalog for Download Data preflight."""

from __future__ import annotations

from collections.abc import Iterable

from leonardo.contracts.download_provider_capabilities import (
    DownloadProviderCapability,
    ProviderMarketCapability,
    TimeframeExpansionResult,
    expand_timeframes as expand_provider_timeframes,
    find_market_capability,
    provider_interval_for_timeframe as provider_interval_for_market_timeframe,
    supported_timeframes as supported_market_timeframes,
)
from leonardo.contracts.ohlcv_storage import normalize_market, normalize_provider


class DownloadCapabilityCatalog:
    """
    Store static Connection Suite provider capability facts in memory.

    The catalog is a read-only Connection-owned descriptor for future download
    capability preflight. It stores already-constructed
    `DownloadProviderCapability` values and delegates market, timeframe, and
    interval interpretation to the provider capability contract helpers. It
    does not load catalogs, call adapters, create provider clients, check
    connection readiness, write files, or execute downloads.
    """

    def __init__(
        self,
        capabilities: Iterable[DownloadProviderCapability] | None = None,
    ) -> None:
        self._capabilities_by_provider: dict[str, DownloadProviderCapability] = {}
        for capability in tuple(capabilities or ()):
            if not isinstance(capability, DownloadProviderCapability):
                raise TypeError(
                    "capabilities entries must be DownloadProviderCapability"
                )
            if capability.provider in self._capabilities_by_provider:
                raise ValueError(
                    f"Duplicate provider capability: {capability.provider}"
                )
            self._capabilities_by_provider[capability.provider] = capability

    def list_providers(self) -> tuple[DownloadProviderCapability, ...]:
        """Return provider capabilities in deterministic provider order."""

        return tuple(
            self._capabilities_by_provider[provider]
            for provider in sorted(self._capabilities_by_provider)
        )

    def get_provider(self, provider: str) -> DownloadProviderCapability | None:
        """Return a provider capability by normalized provider identifier."""

        return self._capabilities_by_provider.get(normalize_provider(provider))

    def require_provider(self, provider: str) -> DownloadProviderCapability:
        """Return a provider capability or raise when it is not registered."""

        normalized = normalize_provider(provider)
        capability = self._capabilities_by_provider.get(normalized)
        if capability is None:
            raise KeyError(f"Provider capability is not registered: {normalized}")
        return capability

    def has_provider(self, provider: str) -> bool:
        """Return whether a provider capability is registered."""

        return self.get_provider(provider) is not None

    def list_markets(self, provider: str) -> tuple[ProviderMarketCapability, ...]:
        """Return market capabilities for a provider, or an empty tuple."""

        capability = self.get_provider(provider)
        if capability is None:
            return ()
        return capability.markets

    def get_market(
        self,
        provider: str,
        market: str,
    ) -> ProviderMarketCapability | None:
        """Return a provider market capability, if both provider and market exist."""

        capability = self.get_provider(provider)
        if capability is None:
            return None
        return find_market_capability(capability, market)

    def supported_timeframes(self, provider: str, market: str) -> tuple[str, ...]:
        """Return supported canonical timeframes for a provider market."""

        market_capability = self.get_market(provider, market)
        if market_capability is None:
            return ()
        return supported_market_timeframes(market_capability)

    def expand_timeframes(
        self,
        provider: str,
        market: str,
        mode: str,
        explicit_timeframes: tuple[str, ...] = (),
    ) -> TimeframeExpansionResult:
        """
        Expand timeframe mode from stored provider capability facts only.

        Missing providers or markets return a structured expansion result with
        issues rather than creating fallback timeframes. Unsupported explicit
        values are handled by the provider capability contract helper.
        """

        normalized_provider = normalize_provider(provider)
        normalized_market = normalize_market(market)
        market_capability = self.get_market(normalized_provider, normalized_market)
        if market_capability is None:
            issue = (
                f"Unknown provider: {normalized_provider}"
                if self.get_provider(normalized_provider) is None
                else f"Unknown provider market: {normalized_market}"
            )
            return TimeframeExpansionResult(
                provider=normalized_provider,
                market=normalized_market,
                mode=mode,
                issues=(issue,),
            )
        return expand_provider_timeframes(
            market_capability,
            mode,
            explicit_timeframes,
            provider=normalized_provider,
        )

    def provider_interval_for_timeframe(
        self,
        provider: str,
        market: str,
        canonical_timeframe: str,
    ) -> str | None:
        """Return the provider-native interval for a supported timeframe."""

        market_capability = self.get_market(provider, market)
        if market_capability is None:
            return None
        return provider_interval_for_market_timeframe(
            market_capability,
            canonical_timeframe,
        )
