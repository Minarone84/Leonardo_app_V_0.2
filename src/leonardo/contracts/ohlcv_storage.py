"""OHLCV storage identity and naming policy contracts.

This module defines pure path and identity helpers for future OHLCV storage.
The helpers return relative POSIX paths and logical dataset references only.
They do not read files, write files, create directories, execute downloads,
or import Core or GUI modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re


class OHLCVDataType(str, Enum):
    """Supported market-data dataset type for this policy layer."""

    OHLCV = "ohlcv"


class OHLCVSchemaVersion(str, Enum):
    """Supported OHLCV storage schema versions."""

    V1 = "v1"


class OHLCVPriceBasis(str, Enum):
    """Supported OHLCV price-basis variants."""

    RAW = "raw"


class OHLCVStorageFormat(str, Enum):
    """Declared OHLCV value artifact formats."""

    CSV = "csv"
    PARQUET = "parquet"


class OHLCVValidationStatus(str, Enum):
    """Metadata validation states for OHLCV loadability decisions."""

    UNKNOWN = "unknown"
    OK = "ok"
    MODIFIED = "modified"
    WARNING = "warning"
    ERROR = "error"


class OHLCVQualityValidationStatus(str, Enum):
    """Quality validation states for OHLCV sidecar metadata."""

    NOT_VALIDATED = "not_validated"
    OK = "ok"
    MODIFIED = "modified"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class OHLCVDatasetIdentity:
    """
    Stable identity for one OHLCV dataset.

    Date coverage is intentionally excluded from identity. Coverage belongs in
    metadata and future partition inventory, while provider, market, symbol,
    timeframe, schema version, price basis, and data type define the dataset.
    """

    provider: str
    market: str
    symbol: str
    timeframe: str
    schema_version: str = OHLCVSchemaVersion.V1.value
    price_basis: str = OHLCVPriceBasis.RAW.value
    data_type: str = OHLCVDataType.OHLCV.value
    storage_format: str = OHLCVStorageFormat.CSV.value
    source_symbol: str | None = None
    base_asset: str | None = None
    quote_asset: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_provider(self.provider))
        object.__setattr__(self, "market", normalize_market(self.market))
        _validate_non_empty_string(self.symbol, "symbol")
        object.__setattr__(self, "symbol", self.symbol.strip())
        object.__setattr__(self, "timeframe", normalize_timeframe(self.timeframe))
        object.__setattr__(
            self,
            "schema_version",
            _coerce_enum_value(
                self.schema_version,
                OHLCVSchemaVersion,
                "schema_version",
            ),
        )
        object.__setattr__(
            self,
            "price_basis",
            _coerce_enum_value(self.price_basis, OHLCVPriceBasis, "price_basis"),
        )
        object.__setattr__(
            self,
            "data_type",
            _coerce_enum_value(self.data_type, OHLCVDataType, "data_type"),
        )
        object.__setattr__(
            self,
            "storage_format",
            _coerce_enum_value(
                self.storage_format,
                OHLCVStorageFormat,
                "storage_format",
            ),
        )
        for field_name in ("source_symbol", "base_asset", "quote_asset"):
            _validate_optional_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class OHLCVPartition:
    """Calendar partition identity for future chunked OHLCV storage."""

    year: int
    month: int
    day: int | None = None

    def __post_init__(self) -> None:
        if type(self.year) is not int or self.year < 1 or self.year > 9999:
            raise ValueError("year must be between 1 and 9999")
        if type(self.month) is not int or self.month < 1 or self.month > 12:
            raise ValueError("month must be between 1 and 12")
        if self.day is not None and (
            type(self.day) is not int or self.day < 1 or self.day > 31
        ):
            raise ValueError("day must be between 1 and 31 when provided")


@dataclass(frozen=True)
class OHLCVPathPolicy:
    """Resolve deterministic relative paths and refs for OHLCV datasets."""

    def dataset_relative_dir(self, identity: OHLCVDatasetIdentity) -> PurePosixPath:
        """Return the legacy-compatible relative dataset directory."""

        _validate_identity(identity)
        path = (
            PurePosixPath(identity.data_type)
            / identity.price_basis
            / identity.schema_version
            / f"provider={identity.provider}"
            / f"market={identity.market}"
            / f"symbol={normalize_symbol_for_path(identity.symbol)}"
            / f"timeframe={identity.timeframe}"
        )
        return _checked_relative_path(path)

    def value_file_relative_path(
        self,
        identity: OHLCVDatasetIdentity,
    ) -> PurePosixPath:
        """Return the relative value artifact path for an OHLCV dataset."""

        return _checked_relative_path(
            self.dataset_relative_dir(identity)
            / f"candles.{_value_file_extension(identity)}"
        )

    def metadata_relative_path(
        self,
        identity: OHLCVDatasetIdentity,
    ) -> PurePosixPath:
        """Return the relative metadata sidecar path for an OHLCV dataset."""

        return _checked_relative_path(
            self.dataset_relative_dir(identity) / "candles.meta.json"
        )

    def data_partition_relative_dir(
        self,
        identity: OHLCVDatasetIdentity,
        partition: OHLCVPartition,
    ) -> PurePosixPath:
        """Return the future partition-aware relative data directory."""

        _validate_identity(identity)
        _validate_partition(partition)
        path = (
            self.dataset_relative_dir(identity)
            / "data"
            / f"year={partition.year:04d}"
            / f"month={partition.month:02d}"
        )
        if partition.day is not None:
            path = path / f"day={partition.day:02d}"
        return _checked_relative_path(path)

    def partition_value_file_relative_path(
        self,
        identity: OHLCVDatasetIdentity,
        partition: OHLCVPartition,
    ) -> PurePosixPath:
        """Return the future partition-aware value artifact path."""

        return _checked_relative_path(
            self.data_partition_relative_dir(identity, partition)
            / f"candles.{_value_file_extension(identity)}"
        )

    def partition_metadata_relative_path(
        self,
        identity: OHLCVDatasetIdentity,
        partition: OHLCVPartition,
    ) -> PurePosixPath:
        """Return the future partition-aware metadata sidecar path."""

        return _checked_relative_path(
            self.data_partition_relative_dir(identity, partition)
            / "candles.meta.json"
        )

    def dataset_ref(self, identity: OHLCVDatasetIdentity) -> str:
        """Return the stable logical dataset reference for an OHLCV dataset."""

        _validate_identity(identity)
        return (
            f"dataset://{identity.data_type}/{identity.schema_version}"
            f"/provider={identity.provider}"
            f"/market={identity.market}"
            f"/symbol={normalize_symbol_for_path(identity.symbol)}"
            f"/timeframe={identity.timeframe}"
            f"/basis={identity.price_basis}"
        )


def normalize_provider(value: str) -> str:
    """Normalize a provider name to a lowercase path-safe slug."""

    return _encode_path_segment(value, field_name="provider", lowercase=True)


def normalize_market(value: str) -> str:
    """Normalize a market name to a lowercase path-safe slug."""

    return _encode_path_segment(value, field_name="market", lowercase=True)


def normalize_timeframe(value: str) -> str:
    """Normalize and validate an OHLCV timeframe token."""

    _validate_non_empty_string(value, "timeframe")
    normalized = value.strip().lower()
    if not re.fullmatch(r"[1-9][0-9]*(m|h|d|w)", normalized):
        raise ValueError(
            "timeframe must use a canonical interval such as 1m, 5m, 1h, or 1d"
        )
    return normalized


def normalize_symbol_for_path(value: str) -> str:
    """Return a filesystem-safe symbol segment while preserving collisions."""

    return _encode_path_segment(value, field_name="symbol", lowercase=True)


def is_accepted_validation_status(status: str) -> bool:
    """Return whether a validation status is accepted for loading."""

    return _status_value(status) in {
        OHLCVValidationStatus.OK.value,
        OHLCVValidationStatus.MODIFIED.value,
    }


def is_blocked_validation_status(status: str) -> bool:
    """Return whether a validation or quality status blocks loading."""

    return _status_value(status) in {
        OHLCVValidationStatus.UNKNOWN.value,
        OHLCVQualityValidationStatus.NOT_VALIDATED.value,
        OHLCVValidationStatus.WARNING.value,
        OHLCVValidationStatus.ERROR.value,
    }


def default_download_validation_status() -> str:
    """Return the initial validation status for newly downloaded OHLCV."""

    return OHLCVValidationStatus.UNKNOWN.value


def default_download_quality_validation_status() -> str:
    """Return the initial quality validation status for downloaded OHLCV."""

    return OHLCVQualityValidationStatus.NOT_VALIDATED.value


def _validate_identity(identity: OHLCVDatasetIdentity) -> None:
    if not isinstance(identity, OHLCVDatasetIdentity):
        raise TypeError("identity must be an OHLCVDatasetIdentity")


def _validate_partition(partition: OHLCVPartition) -> None:
    if not isinstance(partition, OHLCVPartition):
        raise TypeError("partition must be an OHLCVPartition")


def _validate_non_empty_string(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: str | None, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _coerce_enum_value(
    value: str,
    enum_type: type[Enum],
    field_name: str,
) -> str:
    raw = value.value if isinstance(value, enum_type) else value
    _validate_non_empty_string(raw, field_name)
    allowed = {item.value for item in enum_type}
    if raw not in allowed:
        values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {values}")
    return raw


def _status_value(status: str) -> str:
    raw = status.value if isinstance(status, Enum) else status
    _validate_non_empty_string(raw, "status")
    return raw.strip().lower()


def _encode_path_segment(
    value: str,
    *,
    field_name: str,
    lowercase: bool,
) -> str:
    _validate_non_empty_string(value, field_name)
    source = value.strip()
    if lowercase:
        source = source.lower()
    encoded = "".join(_encode_character(character) for character in source)
    if not encoded:
        raise ValueError(f"{field_name} must produce a non-empty path segment")
    if ".." in encoded:
        raise ValueError(f"{field_name} must not produce a parent path segment")
    return encoded


def _encode_character(character: str) -> str:
    if character.isascii() and (
        character.isalnum() or character in {"_", "-"}
    ):
        return character
    return "".join(f"~{byte:02x}" for byte in character.encode("utf-8"))


def _value_file_extension(identity: OHLCVDatasetIdentity) -> str:
    if identity.storage_format == OHLCVStorageFormat.CSV.value:
        return "csv"
    if identity.storage_format == OHLCVStorageFormat.PARQUET.value:
        return "parquet"
    raise ValueError("storage_format must be a supported OHLCVStorageFormat")


def _checked_relative_path(path: PurePosixPath) -> PurePosixPath:
    if path.is_absolute():
        raise ValueError("OHLCV storage paths must be relative")
    path_text = path.as_posix()
    if "\\" in path_text:
        raise ValueError("OHLCV storage paths must be POSIX-style paths")
    if ".." in path_text:
        raise ValueError("OHLCV storage paths must not contain parent segments")
    return path
