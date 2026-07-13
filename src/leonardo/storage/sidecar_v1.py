"""Versioned OHLCV sidecar evidence schema."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from leonardo.data import MarketId


@dataclass(frozen=True)
class OHLCVSidecarV1:
    """Durable evidence describing one persisted OHLCV dataset."""

    market_id: MarketId
    file_sha256: str
    row_count: int
    first_timestamp_ms: int | None
    last_timestamp_ms: int | None
    source: str
    persistence_status: str
    validation_status: str = "unknown"
    warnings: tuple[str, ...] = ()
    lineage: Mapping[str, object] = field(default_factory=dict)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        for name in ("file_sha256", "source", "persistence_status", "validation_status", "schema_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("row_count must be a non-negative integer")
        for name in ("first_timestamp_ms", "last_timestamp_ms"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise TypeError(f"{name} must be an integer or None")
        if (
            self.first_timestamp_ms is not None
            and self.last_timestamp_ms is not None
            and self.first_timestamp_ms > self.last_timestamp_ms
        ):
            raise ValueError("first_timestamp_ms cannot be greater than last_timestamp_ms")
        for name in ("created_at_utc", "updated_at_utc"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be a timezone-aware datetime")
            object.__setattr__(self, name, value.astimezone(UTC))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "lineage", dict(self.lineage))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "market_id": {
                "exchange": self.market_id.exchange,
                "market_type": self.market_id.market_type,
                "symbol": self.market_id.symbol,
                "timeframe": self.market_id.timeframe,
            },
            "file_sha256": self.file_sha256,
            "row_count": self.row_count,
            "first_timestamp_ms": self.first_timestamp_ms,
            "last_timestamp_ms": self.last_timestamp_ms,
            "source": self.source,
            "persistence_status": self.persistence_status,
            "validation_status": self.validation_status,
            "warnings": list(self.warnings),
            "lineage": dict(self.lineage),
            "created_at_utc": self.created_at_utc.isoformat(),
            "updated_at_utc": self.updated_at_utc.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "OHLCVSidecarV1":
        market = data.get("market_id")
        if not isinstance(market, Mapping):
            raise TypeError("market_id must be a mapping")
        warnings = data.get("warnings", ())
        if not isinstance(warnings, Sequence) or isinstance(warnings, (str, bytes, bytearray)):
            raise TypeError("warnings must be a sequence")
        lineage = data.get("lineage", {})
        if not isinstance(lineage, Mapping):
            raise TypeError("lineage must be a mapping")
        return cls(
            schema_version=_text(data, "schema_version"),
            market_id=MarketId(
                exchange=_text(market, "exchange"),
                market_type=_text(market, "market_type"),
                symbol=_text(market, "symbol"),
                timeframe=_text(market, "timeframe"),
            ),
            file_sha256=_text(data, "file_sha256"),
            row_count=_integer(data, "row_count"),
            first_timestamp_ms=_optional_integer(data.get("first_timestamp_ms")),
            last_timestamp_ms=_optional_integer(data.get("last_timestamp_ms")),
            source=_text(data, "source"),
            persistence_status=_text(data, "persistence_status"),
            validation_status=_text(data, "validation_status"),
            warnings=tuple(str(item) for item in warnings),
            lineage=lineage,
            created_at_utc=_datetime(data, "created_at_utc"),
            updated_at_utc=_datetime(data, "updated_at_utc"),
        )


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise TypeError(f"{key} must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError("optional timestamp fields must be integers or None")
    return value


def _datetime(data: Mapping[str, object], key: str) -> datetime:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be an ISO-8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
