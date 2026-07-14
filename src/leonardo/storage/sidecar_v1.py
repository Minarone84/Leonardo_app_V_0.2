"""Versioned OHLCV sidecar evidence schema."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from leonardo.data import MarketId

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PERSISTENCE_STATUSES = frozenset({"partial", "committed", "repaired"})
_VALIDATION_STATUSES = frozenset({"unknown", "ok", "warning", "error"})


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
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported OHLCV sidecar schema_version: {self.schema_version!r}")
        if _SHA256_RE.fullmatch(self.file_sha256) is None:
            raise ValueError("file_sha256 must be a 64-character hexadecimal SHA-256")
        if self.persistence_status not in _PERSISTENCE_STATUSES:
            raise ValueError(
                f"invalid persistence_status: {self.persistence_status!r}; "
                f"allowed={sorted(_PERSISTENCE_STATUSES)}"
            )
        if self.validation_status not in _VALIDATION_STATUSES:
            raise ValueError(
                f"invalid validation_status: {self.validation_status!r}; "
                f"allowed={sorted(_VALIDATION_STATUSES)}"
            )
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
        if self.row_count == 0 and (
            self.first_timestamp_ms is not None or self.last_timestamp_ms is not None
        ):
            raise ValueError("empty datasets cannot declare first or last timestamps")
        if self.row_count > 0 and (
            self.first_timestamp_ms is None or self.last_timestamp_ms is None
        ):
            raise ValueError("non-empty datasets must declare first and last timestamps")
        for name in ("created_at_utc", "updated_at_utc"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"{name} must be a timezone-aware datetime")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.updated_at_utc < self.created_at_utc:
            raise ValueError("updated_at_utc cannot be earlier than created_at_utc")
        normalized_warnings = tuple(str(item).strip() for item in self.warnings if str(item).strip())
        normalized_lineage = dict(self.lineage)
        try:
            json.dumps(normalized_lineage, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("lineage must contain only JSON-safe finite values") from error
        object.__setattr__(self, "file_sha256", self.file_sha256.lower())
        object.__setattr__(self, "warnings", normalized_warnings)
        object.__setattr__(self, "lineage", normalized_lineage)

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
