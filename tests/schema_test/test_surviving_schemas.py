from datetime import UTC, datetime

import pytest

from leonardo.audit import AuditEventV1
from leonardo.data import MarketId
from leonardo.storage import OHLCVSidecarV1


def test_market_id_preserves_month_case() -> None:
    identity = MarketId("bybit", "linear", "BTCUSDT", "1M")
    assert identity.timeframe == "1M"
    assert identity.as_key() == "bybit:linear:BTCUSDT:1M"


def test_sidecar_round_trip() -> None:
    sidecar = OHLCVSidecarV1(
        market_id=MarketId("bybit", "linear", "BTCUSDT", "1M"),
        file_sha256="a" * 64,
        row_count=12,
        first_timestamp_ms=1,
        last_timestamp_ms=12,
        source="bybit",
        persistence_status="committed",
        validation_status="unknown",
        warnings=("not validated",),
        lineage={"request_id": "r1"},
        created_at_utc=datetime.now(UTC),
        updated_at_utc=datetime.now(UTC),
    )
    assert OHLCVSidecarV1.from_dict(sidecar.to_dict()) == sidecar


def test_sidecar_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="cannot be greater"):
        OHLCVSidecarV1(
            market_id=MarketId("bybit", "linear", "BTCUSDT", "1h"),
            file_sha256="a" * 64,
            row_count=1,
            first_timestamp_ms=2,
            last_timestamp_ms=1,
            source="bybit",
            persistence_status="committed",
        )


def test_audit_event_is_versioned() -> None:
    event = AuditEventV1(event_type="test", message="Test")
    assert event.schema_version == "1.0"
