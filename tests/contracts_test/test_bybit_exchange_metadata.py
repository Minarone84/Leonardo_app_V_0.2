import ast
import json
from pathlib import Path

import pytest

from leonardo.contracts.download_provider_capabilities import (
    DownloadProviderCapability,
    ProviderCapabilityStatus,
    ProviderDataKind,
    ProviderTransportKind,
    provider_interval_for_timeframe,
    supported_timeframes,
)
from leonardo.connection.exchange.metadata_loader import (
    bybit_metadata_to_provider_capability,
    load_bybit_exchange_metadata,
    load_default_exchange_capabilities,
    load_exchange_metadata,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_METADATA_PATH = (
    _REPO_ROOT
    / "src"
    / "leonardo"
    / "connection"
    / "exchange"
    / "metadata"
    / "bybit.exchange.json"
)
_DOC_PATH = _REPO_ROOT / "docs" / "contracts_docs" / "BYBIT_EXCHANGE_METADATA.md"
_LOADER_PATH = (
    _REPO_ROOT / "src" / "leonardo" / "connection" / "exchange" / "metadata_loader.py"
)

_EXPECTED_TOP_LEVEL_KEYS = {
    "schema_version",
    "exchange_id",
    "display_name",
    "provider",
    "status",
    "default_environment",
    "environments",
    "markets",
    "timeframes",
    "timeframe_aliases",
    "kline",
    "websocket",
    "symbol_policy",
    "rate_limit_policy",
    "historical_download_policy",
    "metadata",
}
_EXPECTED_TIMEFRAMES = (
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
    "1M",
)
_EXPECTED_INTERVALS = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}
_EXPECTED_CAPABILITY_TIMEFRAMES = tuple(
    timeframe for timeframe in _EXPECTED_TIMEFRAMES if timeframe != "1M"
)
_EXPECTED_CAPABILITY_INTERVALS = {
    timeframe: interval
    for timeframe, interval in _EXPECTED_INTERVALS.items()
    if timeframe != "1M"
}


def test_bybit_metadata_json_loads() -> None:
    metadata = _load_metadata()

    assert metadata["exchange_id"] == "bybit"


def test_bybit_metadata_remains_under_connection_exchange_metadata() -> None:
    assert _METADATA_PATH.exists()
    assert _METADATA_PATH.parts[-5:] == (
        "leonardo",
        "connection",
        "exchange",
        "metadata",
        "bybit.exchange.json",
    )


def test_bybit_metadata_loads_through_loader() -> None:
    metadata = load_bybit_exchange_metadata()

    assert metadata["exchange_id"] == "bybit"
    assert metadata["provider"] == "bybit"


def test_exchange_metadata_loader_rejects_unknown_exchange_id() -> None:
    with pytest.raises(KeyError, match="kraken"):
        load_exchange_metadata("kraken")


def test_default_exchange_capabilities_contain_exactly_bybit_for_now() -> None:
    capabilities = load_default_exchange_capabilities()

    assert len(capabilities) == 1
    assert capabilities[0].provider == "bybit"


def test_bybit_metadata_converts_to_provider_capability() -> None:
    capability = bybit_metadata_to_provider_capability(load_bybit_exchange_metadata())

    assert isinstance(capability, DownloadProviderCapability)
    assert capability.provider == "bybit"
    assert capability.display_name == "Bybit"
    assert capability.status is ProviderCapabilityStatus.SUPPORTED


def test_metadata_required_top_level_keys() -> None:
    metadata = _load_metadata()

    assert set(metadata) == _EXPECTED_TOP_LEVEL_KEYS


def test_exchange_identity_fields() -> None:
    metadata = _load_metadata()

    assert metadata["schema_version"] == "v1"
    assert metadata["exchange_id"] == "bybit"
    assert metadata["display_name"] == "Bybit"
    assert metadata["provider"] == "bybit"
    assert metadata["status"] == ProviderCapabilityStatus.SUPPORTED.value
    assert metadata["default_environment"] == "mainnet"


def test_environment_endpoints() -> None:
    environments = _load_metadata()["environments"]

    assert environments["mainnet"]["rest_base"] == "https://api.bybit.com"
    assert environments["mainnet"]["rest_alternate_base"] == "https://api.bytick.com"
    assert (
        environments["mainnet"]["public_websocket_base"]
        == "wss://stream.bybit.com/v5/public"
    )
    assert environments["testnet"]["rest_base"] == "https://api-testnet.bybit.com"
    assert (
        environments["testnet"]["public_websocket_base"]
        == "wss://stream-testnet.bybit.com/v5/public"
    )


def test_supported_ohlcv_markets() -> None:
    markets = _load_metadata()["markets"]

    assert tuple(markets) == ("spot", "linear", "inverse", "options")
    for market_id in ("spot", "linear", "inverse"):
        market = markets[market_id]
        assert market["canonical_market"] == market_id
        assert market["bybit_category"] == market_id
        assert market["status"] == ProviderCapabilityStatus.SUPPORTED.value
        assert market["data_kinds"] == [ProviderDataKind.OHLCV.value]
        assert market["default_transport"] == ProviderTransportKind.REST.value
        assert market["transports"] == [
            ProviderTransportKind.REST.value,
            ProviderTransportKind.WEBSOCKET.value,
        ]
        assert market["historical_download"]["supported"] is True
        assert market["historical_download"]["endpoint"] == "/v5/market/kline"
        assert market["historical_download"]["requires_auth"] is False
        assert market["historical_download"]["default_limit"] == 200
        assert market["historical_download"]["max_limit"] == 1000
        assert (
            market["historical_download"]["response_order"]
            == "reverse_chronological"
        )


def test_options_market_is_known_but_not_regular_ohlcv_supported() -> None:
    options = _load_metadata()["markets"]["options"]

    assert options["canonical_market"] == "options"
    assert options["bybit_category"] == "option"
    assert options["status"] == ProviderCapabilityStatus.UNSUPPORTED.value
    assert options["data_kinds"] == []
    assert options["historical_download"]["supported"] is False
    assert "spot, linear, and inverse only" in options["historical_download"]["reason"]
    assert options["aliases"] == ["option"]


def test_timeframes_exactly_match_bybit_policy() -> None:
    metadata = _load_metadata()

    assert tuple(item["canonical"] for item in metadata["timeframes"]) == (
        _EXPECTED_TIMEFRAMES
    )


def test_provider_interval_mappings() -> None:
    metadata = _load_metadata()

    intervals = {
        item["canonical"]: item["provider_interval"]
        for item in metadata["timeframes"]
    }

    assert intervals == _EXPECTED_INTERVALS


def test_timeframe_aliases() -> None:
    metadata = _load_metadata()

    assert metadata["timeframe_aliases"] == {"60m": "1h"}


def test_converted_markets_include_supported_regular_ohlcv_markets() -> None:
    capability = bybit_metadata_to_provider_capability(load_bybit_exchange_metadata())
    markets = {market.market: market for market in capability.markets}

    assert {"spot", "linear", "inverse"}.issubset(markets)
    for market_id in ("spot", "linear", "inverse"):
        market = markets[market_id]
        assert market.status is ProviderCapabilityStatus.SUPPORTED
        assert market.data_kinds == (ProviderDataKind.OHLCV.value,)
        assert market.default_transport == ProviderTransportKind.REST.value
        assert market.transports == (
            ProviderTransportKind.REST.value,
            ProviderTransportKind.WEBSOCKET.value,
        )


def test_converted_options_market_is_not_regular_ohlcv_supported() -> None:
    capability = bybit_metadata_to_provider_capability(load_bybit_exchange_metadata())
    markets = {market.market: market for market in capability.markets}

    assert markets["options"].status is ProviderCapabilityStatus.UNSUPPORTED
    assert markets["options"].data_kinds == ()
    assert supported_timeframes(markets["options"]) == ()


def test_converted_supported_timeframes_match_contract_compatible_metadata() -> None:
    capability = bybit_metadata_to_provider_capability(load_bybit_exchange_metadata())
    markets = {market.market: market for market in capability.markets}

    for market_id in ("spot", "linear", "inverse"):
        assert supported_timeframes(markets[market_id]) == (
            _EXPECTED_CAPABILITY_TIMEFRAMES
        )
    assert capability.metadata["deferred_timeframes"] == ("1M",)


def test_converted_interval_mappings_match_contract_compatible_metadata() -> None:
    capability = bybit_metadata_to_provider_capability(load_bybit_exchange_metadata())
    spot = {market.market: market for market in capability.markets}["spot"]

    assert {
        timeframe: provider_interval_for_timeframe(spot, timeframe)
        for timeframe in _EXPECTED_CAPABILITY_TIMEFRAMES
    } == _EXPECTED_CAPABILITY_INTERVALS


def test_kline_endpoint_limits_and_response_order() -> None:
    kline = _load_metadata()["kline"]

    assert kline["method"] == "GET"
    assert kline["endpoint"] == "/v5/market/kline"
    assert kline["category_parameter_required"] is True
    assert kline["category_values"] == ["spot", "linear", "inverse"]
    assert kline["symbol_policy"] == "uppercase"
    assert kline["interval_parameter"] == "provider_interval"
    assert kline["interval_values"] == list(_EXPECTED_INTERVALS.values())
    assert kline["start_timestamp_unit"] == "ms"
    assert kline["end_timestamp_unit"] == "ms"
    assert kline["default_limit"] == 200
    assert kline["max_limit"] == 1000
    assert kline["response_list_order"] == "reverse_by_startTime"
    assert (
        kline["expected_normalization"]
        == "adapter_sorts_ascending_by_candle_open_time_before_storage"
    )


def test_websocket_kline_metadata() -> None:
    metadata = _load_metadata()
    websocket = metadata["websocket"]

    assert websocket["public_kline_topic_template"] == "kline.{interval}.{symbol}"
    assert websocket["interval_parameter"] == "provider_interval"
    assert websocket["symbol_policy"] == "uppercase"
    assert websocket["push_frequency"] == "1-60s"
    assert websocket["closed_candle_indicator"] == "confirm=true"
    assert websocket["historical_download_requires_websocket"] is False


def test_symbol_and_limit_policies() -> None:
    metadata = _load_metadata()

    assert metadata["symbol_policy"]["canonical_symbol_example"] == "BTCUSDT"
    assert metadata["symbol_policy"]["native_symbol_example"] == "BTCUSDT"
    assert metadata["symbol_policy"]["uppercase_required"] is True
    assert metadata["symbol_policy"]["normalization_implemented"] is False
    assert metadata["rate_limit_policy"]["kline_default_page_limit"] == 200
    assert metadata["rate_limit_policy"]["kline_max_page_limit"] == 1000
    assert metadata["rate_limit_policy"]["adapter_rate_limit_handling"] == "deferred"


def test_historical_download_policy() -> None:
    policy = _load_metadata()["historical_download_policy"]

    assert policy["regular_ohlcv_supported_markets"] == ["spot", "linear", "inverse"]
    assert policy["deferred_markets"] == ["options"]
    assert policy["default_transport"] == ProviderTransportKind.REST.value
    assert policy["websocket_required_by_default"] is False
    assert policy["requires_auth"] is False
    assert policy["response_order"] == "reverse_chronological"
    assert policy["storage_sort_order"] == "ascending_by_candle_open_time"


def test_metadata_contains_no_sensitive_fields_or_values() -> None:
    metadata = _load_metadata()
    blocked_tokens = (
        "api" + "_key",
        "api" + "se" + "cret",
        "se" + "cret",
        "pa" + "ssword",
        "private" + "_key",
        "x-bapi" + "-api-key",
    )

    for value in _walk_values(metadata):
        if isinstance(value, str):
            lowered = value.lower()
            assert all(token not in lowered for token in blocked_tokens)


def test_metadata_file_is_static_json_only() -> None:
    source = _METADATA_PATH.read_text(encoding="utf-8")
    blocked_tokens = (
        "import ",
        "def ",
        "class ",
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    assert all(token not in source for token in blocked_tokens)


def test_metadata_loader_imports_no_gui_or_runtime_execution_owners() -> None:
    source = _LOADER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imported_modules(tree)

    blocked_tokens = (
        "leonardo.gui",
        "leonardo.core.task_manager",
        "leonardo.core.operation_registry",
        "leonardo.core.process_manager",
        "leonardo.core.connection_registry",
        "adapter",
    )

    for token in blocked_tokens:
        assert all(token not in module for module in imported_modules)


def test_metadata_loader_has_no_network_process_or_file_write_behavior() -> None:
    source = _LOADER_PATH.read_text(encoding="utf-8")
    blocked_tokens = (
        "re" + "quests",
        "aio" + "http",
        "web" + "sockets",
        "soc" + "ket.",
        "sub" + "process",
        "shell" + "=True",
        "op" + "en(",
        "wr" + "ite(",
        "mk" + "dir",
        "un" + "link",
        "re" + "name",
        "re" + "place",
        "pan" + "das",
        "py" + "arrow",
        "fast" + "parquet",
        "to" + "_csv",
        "to" + "_parquet",
    )

    for token in blocked_tokens:
        assert token not in source


def test_docs_file_exists_and_describes_boundaries() -> None:
    source = _DOC_PATH.read_text(encoding="utf-8")

    assert "Bybit Exchange Metadata" in source
    assert "/v5/market/kline" in source
    assert "`options`" in source
    assert "does not implement a REST client" in source
    assert "metadata loader" in source
    assert "DownloadCapabilityCatalog" in source


def _load_metadata() -> dict[str, object]:
    return json.loads(_METADATA_PATH.read_text(encoding="utf-8"))


def _walk_values(value: object) -> tuple[object, ...]:
    values: list[object] = [value]
    if isinstance(value, dict):
        for key, item in value.items():
            values.extend(_walk_values(key))
            values.extend(_walk_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_values(item))
    return tuple(values)


def _imported_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return tuple(modules)
