"""Local exchange metadata loading for Download Data capability facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from leonardo.contracts.download_provider_capabilities import (
    DownloadProviderCapability,
    ProviderCapabilityStatus,
    ProviderDataKind,
    ProviderMarketCapability,
    ProviderRateLimitPolicy,
    ProviderSymbolPolicy,
    ProviderTimeframeCapability,
    ProviderTransportKind,
)


_BYBIT_EXCHANGE_ID = "bybit"
_METADATA_DIR = Path(__file__).resolve().parent / "metadata"


def load_exchange_metadata(exchange_id: str) -> Mapping[str, Any]:
    """
    Load static exchange metadata from the packaged repository metadata folder.

    Only explicitly known local metadata files are resolved. The function does
    not perform discovery, read environment variables, create clients, open
    network transports, or write files.
    """

    normalized = _normalize_exchange_id(exchange_id)
    if normalized != _BYBIT_EXCHANGE_ID:
        raise KeyError(f"Exchange metadata is not available: {normalized}")

    path = _METADATA_DIR / "bybit.exchange.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Exchange metadata is malformed JSON: {normalized}") from exc

    if not isinstance(payload, Mapping):
        raise ValueError(f"Exchange metadata root must be an object: {normalized}")
    return _readonly_mapping(payload)


def load_bybit_exchange_metadata() -> Mapping[str, Any]:
    """Load the static Bybit exchange metadata mapping."""

    return load_exchange_metadata(_BYBIT_EXCHANGE_ID)


def bybit_metadata_to_provider_capability(
    metadata: Mapping[str, Any],
) -> DownloadProviderCapability:
    """
    Convert static Bybit metadata into a provider capability contract.

    Monthly `1M` metadata is preserved as deferred metadata because the current
    provider capability contract normalizes timeframe units to `m`, `h`, `d`,
    and `w`; converting `1M` directly would collide with minute-based `1m`.
    """

    _validate_bybit_metadata_identity(metadata)
    kline = _required_mapping(metadata, "kline")
    timeframes, deferred_timeframes = _timeframe_capabilities(
        _required_sequence(metadata, "timeframes"),
        default_limit=_required_int(kline, "default_limit"),
        max_limit=_required_int(kline, "max_limit"),
    )
    markets = _market_capabilities(
        metadata,
        timeframes=timeframes,
        deferred_timeframes=deferred_timeframes,
    )

    return DownloadProviderCapability(
        provider=_required_string(metadata, "provider"),
        display_name=_required_string(metadata, "display_name"),
        status=_status(metadata, "status"),
        markets=markets,
        symbol_policy=_symbol_policy(_required_mapping(metadata, "symbol_policy")),
        rate_limit_policy=_rate_limit_policy(
            _required_mapping(metadata, "rate_limit_policy")
        ),
        metadata={
            "schema_version": _required_string(metadata, "schema_version"),
            "exchange_id": _required_string(metadata, "exchange_id"),
            "default_environment": _required_string(
                metadata,
                "default_environment",
            ),
            "environments": _required_mapping(metadata, "environments"),
            "kline": kline,
            "websocket": _required_mapping(metadata, "websocket"),
            "timeframe_aliases": _required_mapping(metadata, "timeframe_aliases"),
            "historical_download_policy": _required_mapping(
                metadata,
                "historical_download_policy",
            ),
            "deferred_timeframes": deferred_timeframes,
            "source": "exchange_metadata_loader",
        },
    )


def load_default_exchange_capabilities() -> tuple[DownloadProviderCapability, ...]:
    """Return the deterministic default exchange capabilities for the app root."""

    return (bybit_metadata_to_provider_capability(load_bybit_exchange_metadata()),)


def _market_capabilities(
    metadata: Mapping[str, Any],
    *,
    timeframes: tuple[ProviderTimeframeCapability, ...],
    deferred_timeframes: tuple[str, ...],
) -> tuple[ProviderMarketCapability, ...]:
    markets = _required_mapping(metadata, "markets")
    websocket = _required_mapping(metadata, "websocket")
    policy = _required_mapping(metadata, "historical_download_policy")
    supported_markets = frozenset(
        _string_tuple(policy, "regular_ohlcv_supported_markets")
    )
    deferred_markets = frozenset(_string_tuple(policy, "deferred_markets"))

    capabilities: list[ProviderMarketCapability] = []
    for market_id, raw_market in markets.items():
        if not isinstance(market_id, str):
            raise ValueError("market identifiers must be strings")
        market = _as_mapping(raw_market, f"markets.{market_id}")
        status = _status(market, "status")
        historical = _required_mapping(market, "historical_download")
        canonical = _required_string(market, "canonical_market")
        data_kinds = _string_tuple(market, "data_kinds")
        transports = _string_tuple(market, "transports")
        is_regular_ohlcv = (
            market_id in supported_markets
            and status is ProviderCapabilityStatus.SUPPORTED
            and _required_bool(historical, "supported") is True
            and ProviderDataKind.OHLCV.value in data_kinds
        )

        if is_regular_ohlcv:
            capabilities.append(
                ProviderMarketCapability(
                    market=canonical,
                    status=status,
                    data_kinds=data_kinds,
                    timeframes=timeframes,
                    transports=transports,
                    default_transport=_optional_string(market, "default_transport"),
                    metadata={
                        "bybit_category": _required_string(
                            market,
                            "bybit_category",
                        ),
                        "historical_download": historical,
                        "deferred_timeframes": deferred_timeframes,
                        "websocket_available": (
                            ProviderTransportKind.WEBSOCKET.value in transports
                        ),
                        "websocket_required_for_historical_download": _required_bool(
                            websocket,
                            "historical_download_requires_websocket",
                        ),
                    },
                )
            )
            continue

        if market_id in deferred_markets or status is not ProviderCapabilityStatus.SUPPORTED:
            capabilities.append(
                ProviderMarketCapability(
                    market=canonical,
                    status=status,
                    data_kinds=data_kinds,
                    timeframes=(),
                    transports=transports,
                    default_transport=_optional_string(market, "default_transport"),
                    metadata={
                        "bybit_category": _required_string(
                            market,
                            "bybit_category",
                        ),
                        "historical_download": historical,
                    },
                )
            )

    return tuple(capabilities)


def _timeframe_capabilities(
    values: Sequence[Any],
    *,
    default_limit: int,
    max_limit: int,
) -> tuple[tuple[ProviderTimeframeCapability, ...], tuple[str, ...]]:
    timeframes: list[ProviderTimeframeCapability] = []
    deferred: list[str] = []
    for index, raw_item in enumerate(values):
        item = _as_mapping(raw_item, f"timeframes[{index}]")
        canonical = _required_string(item, "canonical")
        provider_interval = _required_string(item, "provider_interval")
        status = _status(item, "status")
        if _is_deferred_monthly_timeframe(canonical, provider_interval):
            deferred.append(canonical)
            continue
        if not _is_contract_timeframe(canonical):
            raise ValueError(
                f"Exchange timeframe cannot be represented by the capability "
                f"contract: {canonical}"
            )
        timeframes.append(
            ProviderTimeframeCapability(
                canonical_timeframe=canonical,
                provider_interval=provider_interval,
                status=status,
                default_limit=default_limit if status is ProviderCapabilityStatus.SUPPORTED else None,
                max_limit=max_limit if status is ProviderCapabilityStatus.SUPPORTED else None,
                metadata={"source": "bybit.exchange.json"},
            )
        )
    return tuple(timeframes), tuple(deferred)


def _symbol_policy(payload: Mapping[str, Any]) -> ProviderSymbolPolicy:
    return ProviderSymbolPolicy(
        canonical_symbol_example=_optional_string(payload, "canonical_symbol_example"),
        native_symbol_example=_optional_string(payload, "native_symbol_example"),
        case_sensitive=_required_bool(payload, "uppercase_required"),
        separator_policy=_required_string(payload, "separator_policy"),
        metadata={
            "uppercase_required": _required_bool(payload, "uppercase_required"),
            "normalization_implemented": _required_bool(
                payload,
                "normalization_implemented",
            ),
        },
    )


def _rate_limit_policy(payload: Mapping[str, Any]) -> ProviderRateLimitPolicy:
    return ProviderRateLimitPolicy(
        page_limit_default=_required_int(payload, "kline_default_page_limit"),
        page_limit_max=_required_int(payload, "kline_max_page_limit"),
        metadata={
            "adapter_rate_limit_handling": _required_string(
                payload,
                "adapter_rate_limit_handling",
            ),
        },
    )


def _validate_bybit_metadata_identity(metadata: Mapping[str, Any]) -> None:
    if not isinstance(metadata, Mapping):
        raise TypeError("metadata must be a mapping")
    if _required_string(metadata, "exchange_id") != _BYBIT_EXCHANGE_ID:
        raise ValueError("Bybit metadata must declare exchange_id bybit")
    if _required_string(metadata, "provider") != _BYBIT_EXCHANGE_ID:
        raise ValueError("Bybit metadata must declare provider bybit")


def _normalize_exchange_id(exchange_id: str) -> str:
    if not isinstance(exchange_id, str) or not exchange_id.strip():
        raise ValueError("exchange_id must be a non-empty string")
    return exchange_id.strip().lower()


def _status(
    payload: Mapping[str, Any],
    key: str,
) -> ProviderCapabilityStatus:
    try:
        return ProviderCapabilityStatus(_required_string(payload, key))
    except ValueError as exc:
        raise ValueError(f"{key} must be a provider capability status") from exc


def _required_mapping(
    payload: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any]:
    if key not in payload:
        raise ValueError(f"Missing exchange metadata field: {key}")
    return _as_mapping(payload[key], key)


def _as_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_sequence(
    payload: Mapping[str, Any],
    key: str,
) -> Sequence[Any]:
    if key not in payload:
        raise ValueError(f"Missing exchange metadata field: {key}")
    value = payload[key]
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{key} must be a sequence")
    return value


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"Missing exchange metadata field: {key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    return _required_string(payload, key)


def _required_bool(payload: Mapping[str, Any], key: str) -> bool:
    if key not in payload or type(payload[key]) is not bool:
        raise ValueError(f"{key} must be a bool")
    return payload[key]


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    if key not in payload or type(payload[key]) is not int:
        raise ValueError(f"{key} must be an integer")
    return payload[key]


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _required_sequence(payload, key)
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key}[{index}] must be a non-empty string")
        normalized.append(value.strip())
    return tuple(normalized)


def _is_deferred_monthly_timeframe(
    canonical: str,
    provider_interval: str,
) -> bool:
    return canonical == "1M" and provider_interval == "M"


def _is_contract_timeframe(canonical: str) -> bool:
    if canonical != canonical.lower() or len(canonical) < 2:
        return False
    amount = canonical[:-1]
    unit = canonical[-1]
    return unit in {"m", "h", "d", "w"} and amount.isdecimal() and int(amount) > 0


def _readonly_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("exchange metadata keys must be strings")
        normalized[key] = _readonly_value(item)
    return MappingProxyType(normalized)


def _readonly_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_readonly_value(item) for item in value)
    return value
