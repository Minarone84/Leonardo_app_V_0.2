"""Provider capability contracts for future Download Data execution.

This module defines pure read-model contracts for provider, market, timeframe,
transport, rate-limit, and timeframe-expansion facts. The contracts do not
implement adapters, discover live capabilities, open network connections, read
or write catalogs, write storage artifacts, import Core or GUI modules, or
execute downloads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from types import MappingProxyType

from leonardo.contracts.ohlcv_storage import normalize_market, normalize_provider


class ProviderCapabilityStatus(str, Enum):
    """Support state for a provider capability fact."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    DEPRECATED = "deprecated"


class ProviderTransportKind(str, Enum):
    """Transport category declared by a provider capability fact."""

    REST = "rest"
    WEBSOCKET = "websocket"
    FILE = "file"
    MOCK = "mock"


class ProviderDataKind(str, Enum):
    """Data kind declared by a provider capability fact."""

    OHLCV = "ohlcv"


class ProviderMarketKind(str, Enum):
    """Canonical market category for provider capability facts."""

    SPOT = "spot"
    FUTURES = "futures"
    PERP = "perp"
    MARGIN = "margin"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderTimeframeCapability:
    """
    Timeframe support fact for one provider market.

    The canonical timeframe is Leonardo-facing. The provider interval is the
    provider-native interval token that a future adapter may use. This contract
    does not call an adapter or verify the interval remotely.
    """

    canonical_timeframe: str
    provider_interval: str
    status: ProviderCapabilityStatus
    min_since_utc: str | None = None
    max_until_utc: str | None = None
    default_limit: int | None = None
    max_limit: int | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_timeframe",
            _normalize_timeframe(self.canonical_timeframe),
        )
        object.__setattr__(
            self,
            "provider_interval",
            _normalize_provider_interval(
                self.provider_interval,
                self.status,
            ),
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProviderCapabilityStatus, "status"),
        )
        _validate_optional_string(self.min_since_utc, "min_since_utc")
        _validate_optional_string(self.max_until_utc, "max_until_utc")
        _validate_optional_non_negative_int(self.default_limit, "default_limit")
        _validate_optional_non_negative_int(self.max_limit, "max_limit")
        _validate_limit_order(self.default_limit, self.max_limit)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ProviderMarketCapability:
    """
    Market-level capability facts for one provider.

    The market groups data kinds, canonical timeframe support, transports, and
    optional default expansion policy. It does not own live discovery,
    connection readiness, or execution behavior.
    """

    market: str
    status: ProviderCapabilityStatus
    data_kinds: tuple[ProviderDataKind | str, ...] = ()
    timeframes: tuple[ProviderTimeframeCapability, ...] = ()
    transports: tuple[ProviderTransportKind | str, ...] = ()
    default_transport: ProviderTransportKind | str | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", normalize_market(self.market))
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProviderCapabilityStatus, "status"),
        )
        object.__setattr__(
            self,
            "data_kinds",
            _normalize_enum_value_tuple(
                self.data_kinds,
                ProviderDataKind,
                "data_kinds",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "timeframes",
            _normalize_timeframe_capabilities(self.timeframes),
        )
        transports = _normalize_enum_value_tuple(
            self.transports,
            ProviderTransportKind,
            "transports",
            allow_empty=True,
        )
        object.__setattr__(self, "transports", transports)
        default_transport = _normalize_optional_enum_value(
            self.default_transport,
            ProviderTransportKind,
            "default_transport",
        )
        if default_transport is not None and default_transport not in transports:
            raise ValueError("default_transport must be declared in transports")
        object.__setattr__(self, "default_transport", default_transport)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ProviderSymbolPolicy:
    """Provider symbol-format facts for future adapter validation."""

    canonical_symbol_example: str | None = None
    native_symbol_example: str | None = None
    case_sensitive: bool = False
    separator_policy: str = "unknown"
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_optional_string(
            self.canonical_symbol_example,
            "canonical_symbol_example",
        )
        _validate_optional_string(self.native_symbol_example, "native_symbol_example")
        if type(self.case_sensitive) is not bool:
            raise TypeError("case_sensitive must be a bool")
        _validate_non_empty_string(self.separator_policy, "separator_policy")
        object.__setattr__(
            self,
            "separator_policy",
            self.separator_policy.strip(),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class ProviderRateLimitPolicy:
    """Provider rate and page-limit facts for future execution estimates."""

    requests_per_minute: int | None = None
    weight_per_minute: int | None = None
    page_limit_default: int | None = None
    page_limit_max: int | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_optional_non_negative_int(
            self.requests_per_minute,
            "requests_per_minute",
        )
        _validate_optional_non_negative_int(
            self.weight_per_minute,
            "weight_per_minute",
        )
        _validate_optional_non_negative_int(
            self.page_limit_default,
            "page_limit_default",
        )
        _validate_optional_non_negative_int(self.page_limit_max, "page_limit_max")
        _validate_limit_order(self.page_limit_default, self.page_limit_max)
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class DownloadProviderCapability:
    """
    Provider-level capability facts for future Download Data preflight.

    The provider capability is a read model. It does not perform live provider
    discovery, own an adapter, create connections, or write storage artifacts.
    """

    provider: str
    display_name: str
    status: ProviderCapabilityStatus
    markets: tuple[ProviderMarketCapability, ...] = ()
    symbol_policy: ProviderSymbolPolicy | None = None
    rate_limit_policy: ProviderRateLimitPolicy | None = None
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_provider(self.provider))
        _validate_non_empty_string(self.display_name, "display_name")
        object.__setattr__(self, "display_name", self.display_name.strip())
        object.__setattr__(
            self,
            "status",
            _coerce_enum(self.status, ProviderCapabilityStatus, "status"),
        )
        object.__setattr__(self, "markets", _normalize_markets(self.markets))
        if self.symbol_policy is not None and not isinstance(
            self.symbol_policy,
            ProviderSymbolPolicy,
        ):
            raise TypeError("symbol_policy must be a ProviderSymbolPolicy or None")
        if self.rate_limit_policy is not None and not isinstance(
            self.rate_limit_policy,
            ProviderRateLimitPolicy,
        ):
            raise TypeError(
                "rate_limit_policy must be a ProviderRateLimitPolicy or None"
            )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


@dataclass(frozen=True)
class TimeframeExpansionResult:
    """Result of non-executing timeframe expansion from capability facts."""

    provider: str
    market: str
    mode: str
    timeframes: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    metadata: Mapping[str, object] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_provider(self.provider))
        object.__setattr__(self, "market", normalize_market(self.market))
        object.__setattr__(self, "mode", _normalize_mode(self.mode))
        object.__setattr__(
            self,
            "timeframes",
            tuple(_normalize_timeframe(value) for value in self.timeframes),
        )
        object.__setattr__(
            self,
            "issues",
            _normalize_string_tuple(self.issues, "issues", allow_empty=True),
        )
        object.__setattr__(self, "metadata", _readonly_mapping(self.metadata))


def find_market_capability(
    provider_capability: DownloadProviderCapability,
    market: str,
) -> ProviderMarketCapability | None:
    """Return a provider market capability by normalized market identifier."""

    _validate_provider_capability(provider_capability)
    normalized = normalize_market(market)
    for candidate in provider_capability.markets:
        if candidate.market == normalized:
            return candidate
    return None


def find_timeframe_capability(
    market_capability: ProviderMarketCapability,
    canonical_timeframe: str,
) -> ProviderTimeframeCapability | None:
    """Return a timeframe capability by normalized canonical timeframe."""

    _validate_market_capability(market_capability)
    normalized = _normalize_timeframe(canonical_timeframe)
    for candidate in market_capability.timeframes:
        if candidate.canonical_timeframe == normalized:
            return candidate
    return None


def supported_timeframes(
    market_capability: ProviderMarketCapability,
) -> tuple[str, ...]:
    """Return supported canonical timeframes in declaration order."""

    _validate_market_capability(market_capability)
    return tuple(
        timeframe.canonical_timeframe
        for timeframe in market_capability.timeframes
        if timeframe.status is ProviderCapabilityStatus.SUPPORTED
    )


def expand_timeframes(
    market_capability: ProviderMarketCapability,
    mode: str,
    explicit_timeframes: tuple[str, ...] = (),
    *,
    provider: str = "provider",
) -> TimeframeExpansionResult:
    """
    Expand requested timeframe mode using declared capability facts only.

    The function never invents provider support, fetches live metadata, or calls
    adapters. Unsupported explicit values are reported as issues and omitted
    from the returned timeframe tuple.
    """

    _validate_market_capability(market_capability)
    normalized_mode = _normalize_mode(mode)
    supported = supported_timeframes(market_capability)
    issues: list[str] = []

    if normalized_mode == "explicit":
        expanded: list[str] = []
        for value in explicit_timeframes:
            normalized = _normalize_timeframe(value)
            if normalized in supported:
                if normalized not in expanded:
                    expanded.append(normalized)
            else:
                issues.append(f"Unsupported timeframe: {normalized}")
        return TimeframeExpansionResult(
            provider=provider,
            market=market_capability.market,
            mode=normalized_mode,
            timeframes=tuple(expanded),
            issues=tuple(issues),
        )

    if normalized_mode in {"all", "supported"}:
        return TimeframeExpansionResult(
            provider=provider,
            market=market_capability.market,
            mode=normalized_mode,
            timeframes=supported,
        )

    defaults = _default_timeframes(market_capability, supported)
    return TimeframeExpansionResult(
        provider=provider,
        market=market_capability.market,
        mode=normalized_mode,
        timeframes=defaults,
        issues=() if defaults else ("No supported default timeframe is declared.",),
    )


def provider_interval_for_timeframe(
    market_capability: ProviderMarketCapability,
    canonical_timeframe: str,
) -> str | None:
    """Return provider-native interval for a supported canonical timeframe."""

    capability = find_timeframe_capability(market_capability, canonical_timeframe)
    if capability is None:
        return None
    if capability.status is not ProviderCapabilityStatus.SUPPORTED:
        return None
    return capability.provider_interval


def is_market_supported(
    provider_capability: DownloadProviderCapability,
    market: str,
) -> bool:
    """Return whether a provider market is declared as supported."""

    market_capability = find_market_capability(provider_capability, market)
    return (
        market_capability is not None
        and market_capability.status is ProviderCapabilityStatus.SUPPORTED
    )


def is_timeframe_supported(
    market_capability: ProviderMarketCapability,
    canonical_timeframe: str,
) -> bool:
    """Return whether a canonical timeframe is declared as supported."""

    capability = find_timeframe_capability(market_capability, canonical_timeframe)
    return (
        capability is not None
        and capability.status is ProviderCapabilityStatus.SUPPORTED
    )


def _validate_provider_capability(value: DownloadProviderCapability) -> None:
    if not isinstance(value, DownloadProviderCapability):
        raise TypeError("provider_capability must be a DownloadProviderCapability")


def _validate_market_capability(value: ProviderMarketCapability) -> None:
    if not isinstance(value, ProviderMarketCapability):
        raise TypeError("market_capability must be a ProviderMarketCapability")


def _normalize_markets(
    values: tuple[ProviderMarketCapability, ...],
) -> tuple[ProviderMarketCapability, ...]:
    normalized = _normalize_tuple(values, ProviderMarketCapability, "markets")
    seen: set[str] = set()
    for market in normalized:
        if market.market in seen:
            raise ValueError(f"Duplicate provider market: {market.market}")
        seen.add(market.market)
    return normalized


def _normalize_timeframe_capabilities(
    values: tuple[ProviderTimeframeCapability, ...],
) -> tuple[ProviderTimeframeCapability, ...]:
    normalized = _normalize_tuple(
        values,
        ProviderTimeframeCapability,
        "timeframes",
    )
    seen: set[str] = set()
    for timeframe in normalized:
        if timeframe.canonical_timeframe in seen:
            raise ValueError(
                f"Duplicate provider timeframe: {timeframe.canonical_timeframe}"
            )
        seen.add(timeframe.canonical_timeframe)
    return normalized


def _normalize_tuple(
    values: tuple[object, ...],
    expected_type: type[object],
    field_name: str,
) -> tuple[object, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(values)
    for value in normalized:
        if not isinstance(value, expected_type):
            raise TypeError(f"{field_name} entries must be {expected_type.__name__}")
    return normalized


def _normalize_enum_value_tuple(
    values: tuple[Enum | str, ...],
    enum_type: type[Enum],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _coerce_enum_value(value, enum_type, f"{field_name} entry")
        for value in values
    )
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    return normalized


def _normalize_optional_enum_value(
    value: Enum | str | None,
    enum_type: type[Enum],
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _coerce_enum_value(value, enum_type, field_name)


def _coerce_enum(
    value: object,
    enum_type: type[Enum],
    field_name: str,
) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as error:
            allowed = ", ".join(sorted(item.value for item in enum_type))
            raise ValueError(f"{field_name} must be one of: {allowed}") from error
    raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _coerce_enum_value(
    value: Enum | str,
    enum_type: type[Enum],
    field_name: str,
) -> str:
    coerced = _coerce_enum(value, enum_type, field_name)
    return str(coerced.value)


def _normalize_provider_interval(
    value: str,
    status: ProviderCapabilityStatus,
) -> str:
    if not isinstance(value, str):
        raise TypeError("provider_interval must be a string")
    normalized = value.strip()
    status_value = _coerce_enum(status, ProviderCapabilityStatus, "status")
    if status_value is ProviderCapabilityStatus.SUPPORTED and not normalized:
        raise ValueError("provider_interval must be non-empty for supported timeframes")
    return normalized


def _normalize_timeframe(value: str) -> str:
    _validate_non_empty_string(value, "canonical_timeframe")
    normalized = value.strip().lower()
    if not _is_canonical_timeframe(normalized):
        raise ValueError(
            "canonical_timeframe must use a canonical interval such as 1m, 5m, "
            "1h, or 1d"
        )
    return normalized


def _is_canonical_timeframe(value: str) -> bool:
    if len(value) < 2:
        return False
    unit = value[-1]
    amount = value[:-1]
    return unit in {"m", "h", "d", "w"} and amount.isdecimal() and int(amount) > 0


def _normalize_mode(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("mode must be a string")
    normalized = value.strip().lower()
    if normalized not in {"explicit", "all", "supported", "default"}:
        raise ValueError("mode must be one of: all, default, explicit, supported")
    return normalized


def _default_timeframes(
    market_capability: ProviderMarketCapability,
    supported: tuple[str, ...],
) -> tuple[str, ...]:
    raw_default = market_capability.metadata.get("default_timeframes")
    if raw_default is not None:
        if isinstance(raw_default, str):
            candidates = (raw_default,)
        elif isinstance(raw_default, tuple | list):
            candidates = tuple(raw_default)
        else:
            raise TypeError("metadata default_timeframes must be a string or sequence")

        defaults: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, str):
                raise TypeError("metadata default_timeframes entries must be strings")
            normalized = _normalize_timeframe(candidate)
            if normalized in supported and normalized not in defaults:
                defaults.append(normalized)
        return tuple(defaults)

    return supported[:1]


def _normalize_string_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must contain at least one value")
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _readonly_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("metadata keys must be strings")
        normalized[key] = _readonly_value(item)
    return MappingProxyType(normalized)


def _readonly_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _readonly_mapping(value)
    if isinstance(value, tuple | list):
        return tuple(_readonly_value(item) for item in value)
    return value


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _validate_optional_non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _validate_limit_order(
    default_limit: int | None,
    max_limit: int | None,
) -> None:
    if default_limit is None or max_limit is None:
        return
    if max_limit < default_limit:
        raise ValueError("max_limit must be greater than or equal to default_limit")
