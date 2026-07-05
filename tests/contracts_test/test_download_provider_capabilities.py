from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from leonardo.contracts.download_provider_capabilities import (
    DownloadProviderCapability,
    ProviderCapabilityStatus,
    ProviderDataKind,
    ProviderMarketCapability,
    ProviderRateLimitPolicy,
    ProviderSymbolPolicy,
    ProviderTimeframeCapability,
    ProviderTransportKind,
    TimeframeExpansionResult,
    expand_timeframes,
    find_market_capability,
    find_timeframe_capability,
    is_market_supported,
    is_timeframe_supported,
    provider_interval_for_timeframe,
    supported_timeframes,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY_CONTRACT = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "contracts"
    / "download_provider_capabilities.py"
)


def test_valid_provider_capability_construction() -> None:
    provider = _provider()

    assert provider.provider == "binance"
    assert provider.display_name == "Binance"
    assert provider.status is ProviderCapabilityStatus.SUPPORTED
    assert provider.markets[0].market == "spot"
    assert provider.symbol_policy is not None
    assert provider.rate_limit_policy is not None
    assert provider.metadata["owner"] == "contracts"


def test_empty_provider_rejected() -> None:
    with pytest.raises(ValueError, match="provider"):
        DownloadProviderCapability(
            provider=" ",
            display_name="Blank",
            status=ProviderCapabilityStatus.SUPPORTED,
        )


def test_market_capability_construction() -> None:
    market = _market()

    assert market.market == "spot"
    assert market.status is ProviderCapabilityStatus.SUPPORTED
    assert market.data_kinds == ("ohlcv",)
    assert market.transports == ("rest", "websocket")
    assert market.default_transport == "rest"


def test_duplicate_markets_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate provider market"):
        DownloadProviderCapability(
            provider="binance",
            display_name="Binance",
            status=ProviderCapabilityStatus.SUPPORTED,
            markets=(_market("spot"), _market("Spot")),
        )


def test_timeframe_capability_construction() -> None:
    timeframe = ProviderTimeframeCapability(
        canonical_timeframe="1M",
        provider_interval="1m",
        status=ProviderCapabilityStatus.SUPPORTED,
        min_since_utc="2017-01-01T00:00:00Z",
        default_limit=500,
        max_limit=1000,
        metadata={"weight": 1},
    )

    assert timeframe.canonical_timeframe == "1m"
    assert timeframe.provider_interval == "1m"
    assert timeframe.status is ProviderCapabilityStatus.SUPPORTED
    assert timeframe.default_limit == 500
    assert timeframe.max_limit == 1000
    assert timeframe.metadata["weight"] == 1


def test_duplicate_timeframes_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate provider timeframe"):
        ProviderMarketCapability(
            market="spot",
            status=ProviderCapabilityStatus.SUPPORTED,
            timeframes=(_timeframe("1m"), _timeframe("1M")),
        )


def test_supported_timeframes_helper() -> None:
    assert supported_timeframes(_market()) == ("1m", "5m", "1h")


def test_non_supported_timeframes_excluded_from_supported_helper() -> None:
    market = ProviderMarketCapability(
        market="spot",
        status=ProviderCapabilityStatus.SUPPORTED,
        timeframes=(
            _timeframe("1m", status=ProviderCapabilityStatus.SUPPORTED),
            _timeframe("3m", status=ProviderCapabilityStatus.UNSUPPORTED),
            _timeframe("15m", status=ProviderCapabilityStatus.UNKNOWN),
            _timeframe("30m", status=ProviderCapabilityStatus.DEPRECATED),
        ),
    )

    assert supported_timeframes(market) == ("1m",)


def test_provider_interval_mapping() -> None:
    market = _market()

    assert provider_interval_for_timeframe(market, "1M") == "1m"
    assert provider_interval_for_timeframe(market, "1d") is None


def test_market_lookup() -> None:
    provider = _provider()

    market = find_market_capability(provider, "SPOT")

    assert market is not None
    assert market.market == "spot"


def test_missing_market_lookup_returns_none() -> None:
    assert find_market_capability(_provider(), "margin") is None


def test_is_market_supported() -> None:
    provider = DownloadProviderCapability(
        provider="binance",
        display_name="Binance",
        status=ProviderCapabilityStatus.SUPPORTED,
        markets=(
            _market("spot", status=ProviderCapabilityStatus.SUPPORTED),
            _market("margin", status=ProviderCapabilityStatus.UNSUPPORTED),
        ),
    )

    assert is_market_supported(provider, "spot") is True
    assert is_market_supported(provider, "margin") is False
    assert is_market_supported(provider, "futures") is False


def test_is_timeframe_supported() -> None:
    market = _market()

    assert is_timeframe_supported(market, "5M") is True
    assert is_timeframe_supported(market, "1d") is False


def test_explicit_timeframe_expansion_returns_requested_supported_values() -> None:
    result = expand_timeframes(
        _market(),
        "explicit",
        ("5M", "1m", "5m"),
        provider="Binance",
    )

    assert isinstance(result, TimeframeExpansionResult)
    assert result.provider == "binance"
    assert result.market == "spot"
    assert result.mode == "explicit"
    assert result.timeframes == ("5m", "1m")
    assert result.issues == ()


def test_explicit_timeframe_expansion_reports_unsupported_values() -> None:
    result = expand_timeframes(
        _market(),
        "explicit",
        ("1m", "1d"),
        provider="binance",
    )

    assert result.timeframes == ("1m",)
    assert result.issues == ("Unsupported timeframe: 1d",)


@pytest.mark.parametrize("mode", ("all", "supported"))
def test_all_and_supported_timeframe_expansion_returns_supported_values(
    mode: str,
) -> None:
    result = expand_timeframes(_market(), mode, provider="binance")

    assert result.mode == mode
    assert result.timeframes == ("1m", "5m", "1h")
    assert result.issues == ()


def test_default_timeframe_expansion_is_deterministic_from_metadata() -> None:
    result = expand_timeframes(_market(), "default", provider="binance")

    assert result.timeframes == ("5m", "1h")
    assert result.issues == ()


def test_default_timeframe_expansion_falls_back_to_first_supported_value() -> None:
    result = expand_timeframes(
        ProviderMarketCapability(
            market="spot",
            status=ProviderCapabilityStatus.SUPPORTED,
            timeframes=(_timeframe("1m"), _timeframe("5m")),
        ),
        "default",
        provider="binance",
    )

    assert result.timeframes == ("1m",)
    assert result.issues == ()


@pytest.mark.parametrize(
    ("field_name", "values"),
    (
        ("default_limit", {"default_limit": -1}),
        ("max_limit", {"max_limit": -1}),
        ("requests_per_minute", {"requests_per_minute": -1}),
        ("weight_per_minute", {"weight_per_minute": -1}),
        ("page_limit_default", {"page_limit_default": -1}),
        ("page_limit_max", {"page_limit_max": -1}),
    ),
)
def test_limits_reject_negative_values(
    field_name: str,
    values: dict[str, int],
) -> None:
    if field_name in {"default_limit", "max_limit"}:
        with pytest.raises(ValueError, match=field_name):
            ProviderTimeframeCapability(
                canonical_timeframe="1m",
                provider_interval="1m",
                status=ProviderCapabilityStatus.SUPPORTED,
                **values,
            )
    else:
        with pytest.raises(ValueError, match=field_name):
            ProviderRateLimitPolicy(**values)


def test_max_limit_lower_than_default_limit_rejected() -> None:
    with pytest.raises(ValueError, match="max_limit"):
        ProviderTimeframeCapability(
            canonical_timeframe="1m",
            provider_interval="1m",
            status=ProviderCapabilityStatus.SUPPORTED,
            default_limit=1000,
            max_limit=500,
        )
    with pytest.raises(ValueError, match="max_limit"):
        ProviderRateLimitPolicy(page_limit_default=1000, page_limit_max=500)


def test_metadata_copied_readonly_and_contracts_are_frozen() -> None:
    metadata = {"defaults": ["1m", "5m"], "nested": {"weight": 1}}
    market = ProviderMarketCapability(
        market="spot",
        status=ProviderCapabilityStatus.SUPPORTED,
        timeframes=(_timeframe("1m"),),
        metadata=metadata,
    )
    metadata["defaults"] = ["changed"]

    assert market.metadata["defaults"] == ("1m", "5m")
    assert market.metadata["nested"]["weight"] == 1
    with pytest.raises(TypeError):
        market.metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        market.market = "margin"  # type: ignore[misc]


def test_supported_timeframe_requires_provider_interval() -> None:
    with pytest.raises(ValueError, match="provider_interval"):
        ProviderTimeframeCapability(
            canonical_timeframe="1m",
            provider_interval=" ",
            status=ProviderCapabilityStatus.SUPPORTED,
        )


def test_contracts_import_no_core_or_gui() -> None:
    source = _CAPABILITY_CONTRACT.read_text(encoding="utf-8")

    assert "leonardo.core" not in source
    assert "leonardo.gui" not in source


def test_contracts_have_no_network_file_process_or_dependency_imports() -> None:
    source = _CAPABILITY_CONTRACT.read_text(encoding="utf-8")
    forbidden_tokens = (
        "import " + "requests",
        "from " + "requests",
        "aio" + "http",
        "web" + "sockets",
        "socket" + ".",
        "sub" + "process",
        "shell" + "=True",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "pa" + "ndas",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    for token in forbidden_tokens:
        assert token not in source


def test_timeframe_lookup() -> None:
    capability = find_timeframe_capability(_market(), "1H")

    assert capability is not None
    assert capability.provider_interval == "1h"


def _provider() -> DownloadProviderCapability:
    return DownloadProviderCapability(
        provider="Binance",
        display_name="Binance",
        status=ProviderCapabilityStatus.SUPPORTED,
        markets=(_market(),),
        symbol_policy=ProviderSymbolPolicy(
            canonical_symbol_example="BTCUSDT",
            native_symbol_example="BTCUSDT",
            separator_policy="none",
        ),
        rate_limit_policy=ProviderRateLimitPolicy(
            requests_per_minute=1200,
            weight_per_minute=6000,
            page_limit_default=500,
            page_limit_max=1000,
        ),
        metadata={"owner": "contracts"},
    )


def _market(
    market: str = "spot",
    *,
    status: ProviderCapabilityStatus = ProviderCapabilityStatus.SUPPORTED,
) -> ProviderMarketCapability:
    return ProviderMarketCapability(
        market=market,
        status=status,
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
        provider_interval=canonical_timeframe.lower() if status is ProviderCapabilityStatus.SUPPORTED else "",
        status=status,
        default_limit=500 if status is ProviderCapabilityStatus.SUPPORTED else None,
        max_limit=1000 if status is ProviderCapabilityStatus.SUPPORTED else None,
    )
