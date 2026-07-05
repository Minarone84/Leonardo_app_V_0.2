import ast
from pathlib import Path

import pytest

from leonardo.contracts.download_provider_capabilities import (
    DownloadProviderCapability,
    ProviderCapabilityStatus,
    ProviderDataKind,
    ProviderMarketCapability,
    ProviderTimeframeCapability,
    ProviderTransportKind,
    TimeframeExpansionResult,
)
from leonardo.connection.exchange.metadata_loader import load_default_exchange_capabilities
from leonardo.core.download_capability_catalog import DownloadCapabilityCatalog


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_SOURCE = (
    _REPO_ROOT / "src" / "leonardo" / "core" / "download_capability_catalog.py"
)


def test_empty_catalog_construction() -> None:
    catalog = DownloadCapabilityCatalog()

    assert catalog.list_providers() == ()
    assert catalog.list_markets("binance") == ()


def test_catalog_construction_with_one_provider() -> None:
    provider = _provider()

    catalog = DownloadCapabilityCatalog((provider,))

    assert catalog.list_providers() == (provider,)


def test_duplicate_provider_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate provider capability"):
        DownloadCapabilityCatalog((_provider("Binance"), _provider("binance")))


def test_list_providers_returns_tuple_snapshot() -> None:
    provider = _provider()
    catalog = DownloadCapabilityCatalog((provider,))
    listed = catalog.list_providers()

    assert listed == (provider,)
    assert isinstance(listed, tuple)


def test_get_provider_returns_provider() -> None:
    provider = _provider()
    catalog = DownloadCapabilityCatalog((provider,))

    assert catalog.get_provider("BINANCE") is provider


def test_get_provider_returns_none_for_unknown_provider() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.get_provider("kraken") is None


def test_require_provider_raises_key_error_for_unknown_provider() -> None:
    catalog = DownloadCapabilityCatalog()

    with pytest.raises(KeyError, match="binance"):
        catalog.require_provider("Binance")


def test_has_provider() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.has_provider("BINANCE") is True
    assert catalog.has_provider("kraken") is False


def test_list_markets() -> None:
    market = _market("spot")
    catalog = DownloadCapabilityCatalog((_provider(markets=(market,)),))

    assert catalog.list_markets("binance") == (market,)


def test_get_market_returns_market() -> None:
    market = _market("spot")
    catalog = DownloadCapabilityCatalog((_provider(markets=(market,)),))

    assert catalog.get_market("BINANCE", "SPOT") is market


def test_get_market_returns_none_for_unknown_market_or_provider() -> None:
    catalog = DownloadCapabilityCatalog((_provider(markets=(_market("spot"),)),))

    assert catalog.get_market("binance", "margin") is None
    assert catalog.get_market("kraken", "spot") is None


def test_supported_timeframes_for_known_provider_market() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.supported_timeframes("binance", "spot") == ("1m", "5m", "1h")


def test_supported_timeframes_returns_empty_tuple_for_unknown_provider_or_market() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.supported_timeframes("kraken", "spot") == ()
    assert catalog.supported_timeframes("binance", "margin") == ()


def test_provider_interval_for_timeframe_returns_native_interval() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.provider_interval_for_timeframe("binance", "spot", "1H") == "1h"


def test_provider_interval_for_timeframe_returns_none_for_unsupported_or_missing() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    assert catalog.provider_interval_for_timeframe("binance", "spot", "1d") is None
    assert catalog.provider_interval_for_timeframe("binance", "margin", "1m") is None
    assert catalog.provider_interval_for_timeframe("kraken", "spot", "1m") is None


def test_default_exchange_capabilities_catalog_contains_bybit_only() -> None:
    catalog = DownloadCapabilityCatalog(load_default_exchange_capabilities())

    assert tuple(provider.provider for provider in catalog.list_providers()) == (
        "bybit",
    )


def test_default_exchange_capabilities_catalog_exposes_bybit_timeframes() -> None:
    catalog = DownloadCapabilityCatalog(load_default_exchange_capabilities())

    assert catalog.supported_timeframes("bybit", "spot") == (
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "12h",
        "1d",
        "1w",
    )


def test_default_exchange_capabilities_catalog_maps_bybit_intervals() -> None:
    catalog = DownloadCapabilityCatalog(load_default_exchange_capabilities())

    assert catalog.provider_interval_for_timeframe("bybit", "spot", "1h") == "60"
    assert catalog.provider_interval_for_timeframe("bybit", "spot", "1w") == "W"
    assert "1M" not in catalog.supported_timeframes("bybit", "spot")


def test_expand_timeframes_explicit_supported_values() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    result = catalog.expand_timeframes("BINANCE", "SPOT", "explicit", ("5M", "1m"))

    assert isinstance(result, TimeframeExpansionResult)
    assert result.provider == "binance"
    assert result.market == "spot"
    assert result.mode == "explicit"
    assert result.timeframes == ("5m", "1m")
    assert result.issues == ()


def test_expand_timeframes_explicit_unsupported_values_reports_issues() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    result = catalog.expand_timeframes("binance", "spot", "explicit", ("1m", "1d"))

    assert result.timeframes == ("1m",)
    assert result.issues == ("Unsupported timeframe: 1d",)


@pytest.mark.parametrize("mode", ("all", "supported"))
def test_expand_timeframes_all_and_supported_return_supported_timeframes(
    mode: str,
) -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    result = catalog.expand_timeframes("binance", "spot", mode)

    assert result.timeframes == ("1m", "5m", "1h")
    assert result.issues == ()


def test_expand_timeframes_default_is_deterministic() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    result = catalog.expand_timeframes("binance", "spot", "default")

    assert result.timeframes == ("5m", "1h")
    assert result.issues == ()


def test_expand_timeframes_unknown_provider_or_market_reports_issues() -> None:
    catalog = DownloadCapabilityCatalog((_provider(),))

    unknown_provider = catalog.expand_timeframes("kraken", "spot", "default")
    unknown_market = catalog.expand_timeframes("binance", "margin", "default")

    assert unknown_provider.timeframes == ()
    assert unknown_provider.issues == ("Unknown provider: kraken",)
    assert unknown_market.timeframes == ()
    assert unknown_market.issues == ("Unknown provider market: margin",)


def test_catalog_imports_no_gui() -> None:
    source = _CATALOG_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imported_modules(tree)

    assert all("leonardo.gui" not in module for module in imported_modules)


def test_catalog_performs_no_runtime_io_or_external_dependency_imports() -> None:
    source = _CATALOG_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imported_modules(tree)
    forbidden_imports = (
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket",
        "sub" + "process",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
    )
    forbidden_tokens = (
        "shell" + "=True",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "to" + "_csv",
        "to" + "_parquet",
    )

    assert all(
        forbidden not in module
        for forbidden in forbidden_imports
        for module in imported_modules
    )
    for token in forbidden_tokens:
        assert token not in source


def _provider(
    provider: str = "Binance",
    *,
    markets: tuple[ProviderMarketCapability, ...] | None = None,
) -> DownloadProviderCapability:
    return DownloadProviderCapability(
        provider=provider,
        display_name=provider.strip(),
        status=ProviderCapabilityStatus.SUPPORTED,
        markets=markets or (_market(),),
    )


def _market(market: str = "spot") -> ProviderMarketCapability:
    return ProviderMarketCapability(
        market=market,
        status=ProviderCapabilityStatus.SUPPORTED,
        data_kinds=(ProviderDataKind.OHLCV,),
        timeframes=(
            _timeframe("1m"),
            _timeframe("5m"),
            _timeframe("1h"),
            _timeframe("1d", status=ProviderCapabilityStatus.UNSUPPORTED),
        ),
        transports=(ProviderTransportKind.REST, ProviderTransportKind.WEBSOCKET),
        default_transport=ProviderTransportKind.REST,
        metadata={"default_timeframes": ("5m", "1h")},
    )


def _timeframe(
    canonical_timeframe: str,
    *,
    status: ProviderCapabilityStatus = ProviderCapabilityStatus.SUPPORTED,
) -> ProviderTimeframeCapability:
    return ProviderTimeframeCapability(
        canonical_timeframe=canonical_timeframe,
        provider_interval=(
            canonical_timeframe.lower()
            if status is ProviderCapabilityStatus.SUPPORTED
            else ""
        ),
        status=status,
    )


def _imported_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return tuple(modules)
