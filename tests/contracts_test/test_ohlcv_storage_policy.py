from pathlib import Path, PurePosixPath

import pytest

from leonardo.contracts.ohlcv_storage import (
    OHLCVDatasetIdentity,
    OHLCVDataType,
    OHLCVPartition,
    OHLCVPathPolicy,
    OHLCVPriceBasis,
    OHLCVQualityValidationStatus,
    OHLCVSchemaVersion,
    OHLCVStorageFormat,
    OHLCVValidationStatus,
    default_download_quality_validation_status,
    default_download_validation_status,
    is_accepted_validation_status,
    is_blocked_validation_status,
    normalize_market,
    normalize_provider,
    normalize_symbol_for_path,
    normalize_timeframe,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OHLCV_STORAGE_CONTRACT = (
    _REPO_ROOT / "src" / "leonardo" / "contracts" / "ohlcv_storage.py"
)


def test_valid_dataset_identity_construction_defaults() -> None:
    identity = OHLCVDatasetIdentity(
        provider="Binance",
        market="Spot",
        symbol="BTCUSDT",
        timeframe="1M",
    )

    assert identity.provider == "binance"
    assert identity.market == "spot"
    assert identity.symbol == "BTCUSDT"
    assert identity.timeframe == "1m"
    assert identity.schema_version == OHLCVSchemaVersion.V1.value
    assert identity.price_basis == OHLCVPriceBasis.RAW.value
    assert identity.data_type == OHLCVDataType.OHLCV.value
    assert identity.storage_format == OHLCVStorageFormat.CSV.value


@pytest.mark.parametrize("field_name", ("provider", "market", "symbol", "timeframe"))
def test_empty_identity_fields_are_rejected(field_name: str) -> None:
    values = {
        "provider": "binance",
        "market": "spot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        OHLCVDatasetIdentity(**values)


def test_provider_and_market_normalization() -> None:
    assert normalize_provider(" Binance US ") == "binance~20us"
    assert normalize_market(" SPOT/USDT ") == "spot~2fusdt"


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("1M", "1m"),
        ("5m", "5m"),
        ("1H", "1h"),
        ("1D", "1d"),
    ),
)
def test_timeframe_normalization(raw: str, expected: str) -> None:
    assert normalize_timeframe(raw) == expected


@pytest.mark.parametrize("raw", ("0m", "m1", "1mo", "1/minute", ""))
def test_invalid_timeframe_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="timeframe"):
        normalize_timeframe(raw)


def test_symbol_path_normalization_preserves_collision_sensitive_differences() -> None:
    slugs = {
        "BTCUSDT": normalize_symbol_for_path("BTCUSDT"),
        "BTC/USDT": normalize_symbol_for_path("BTC/USDT"),
        "BTC:USDT": normalize_symbol_for_path("BTC:USDT"),
        "BTC USDT": normalize_symbol_for_path("BTC USDT"),
    }

    assert slugs["BTCUSDT"] == "btcusdt"
    assert slugs["BTC/USDT"] == "btc~2fusdt"
    assert slugs["BTC:USDT"] == "btc~3ausdt"
    assert slugs["BTC USDT"] == "btc~20usdt"
    assert len(set(slugs.values())) == len(slugs)


def test_generated_dataset_relative_directory() -> None:
    policy = OHLCVPathPolicy()

    assert policy.dataset_relative_dir(_identity()) == PurePosixPath(
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m"
    )


def test_generated_value_and_metadata_paths() -> None:
    policy = OHLCVPathPolicy()
    identity = _identity()

    assert policy.value_file_relative_path(identity) == PurePosixPath(
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/candles.csv"
    )
    assert policy.metadata_relative_path(identity) == PurePosixPath(
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/candles.meta.json"
    )


def test_parquet_storage_format_is_declared_for_future_value_paths() -> None:
    policy = OHLCVPathPolicy()
    identity = OHLCVDatasetIdentity(
        provider="binance",
        market="spot",
        symbol="BTCUSDT",
        timeframe="1m",
        storage_format=OHLCVStorageFormat.PARQUET.value,
    )

    assert identity.storage_format == OHLCVStorageFormat.PARQUET.value
    assert policy.value_file_relative_path(identity).name == "candles.parquet"
    assert policy.metadata_relative_path(identity).name == "candles.meta.json"


def test_generated_paths_are_relative_posix_and_contain_no_parent_segments() -> None:
    policy = OHLCVPathPolicy()
    identity = OHLCVDatasetIdentity(
        provider="Vendor.Name",
        market="Spot",
        symbol="BTC/USDT",
        timeframe="1m",
    )
    paths = (
        policy.dataset_relative_dir(identity),
        policy.value_file_relative_path(identity),
        policy.metadata_relative_path(identity),
        policy.data_partition_relative_dir(identity, OHLCVPartition(2026, 1)),
        policy.partition_value_file_relative_path(identity, OHLCVPartition(2026, 1)),
        policy.partition_metadata_relative_path(identity, OHLCVPartition(2026, 1)),
    )

    for path in paths:
        assert not path.is_absolute()
        assert "\\" not in path.as_posix()
        assert ".." not in path.as_posix()


def test_logical_dataset_ref_generation() -> None:
    policy = OHLCVPathPolicy()

    ref = policy.dataset_ref(_identity())

    assert ref == (
        "dataset://ohlcv/v1/provider=binance/market=spot/"
        "symbol=btcusdt/timeframe=1m/basis=raw"
    )
    assert "2026" not in ref
    assert ":/" in ref
    assert "C:" not in ref
    assert "\\" not in ref


def test_logical_ref_uses_normalized_identity_segments() -> None:
    policy = OHLCVPathPolicy()
    identity = OHLCVDatasetIdentity(
        provider="Binance US",
        market="SPOT/USDT",
        symbol="BTC:USDT",
        timeframe="1H",
    )

    assert policy.dataset_ref(identity) == (
        "dataset://ohlcv/v1/provider=binance~20us/market=spot~2fusdt/"
        "symbol=btc~3ausdt/timeframe=1h/basis=raw"
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("schema_version", "v2"),
        ("price_basis", "adjusted"),
        ("data_type", "trades"),
        ("storage_format", "jsonl"),
    ),
)
def test_identity_policy_fields_are_validated(field_name: str, value: str) -> None:
    values = {
        "provider": "binance",
        "market": "spot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        field_name: value,
    }

    with pytest.raises(ValueError, match=field_name):
        OHLCVDatasetIdentity(**values)


def test_downloaded_status_defaults() -> None:
    assert default_download_validation_status() == OHLCVValidationStatus.UNKNOWN.value
    assert (
        default_download_quality_validation_status()
        == OHLCVQualityValidationStatus.NOT_VALIDATED.value
    )


@pytest.mark.parametrize(
    "status",
    (
        OHLCVValidationStatus.OK.value,
        OHLCVValidationStatus.MODIFIED.value,
        OHLCVValidationStatus.OK,
        OHLCVQualityValidationStatus.MODIFIED,
    ),
)
def test_accepted_loadable_statuses(status: str) -> None:
    assert is_accepted_validation_status(status) is True
    assert is_blocked_validation_status(status) is False


@pytest.mark.parametrize(
    "status",
    (
        OHLCVValidationStatus.UNKNOWN.value,
        OHLCVQualityValidationStatus.NOT_VALIDATED.value,
        OHLCVValidationStatus.WARNING.value,
        OHLCVValidationStatus.ERROR.value,
        OHLCVValidationStatus.UNKNOWN,
        OHLCVQualityValidationStatus.NOT_VALIDATED,
    ),
)
def test_blocked_statuses(status: str) -> None:
    assert is_blocked_validation_status(status) is True
    assert is_accepted_validation_status(status) is False


def test_partition_month_formatting() -> None:
    policy = OHLCVPathPolicy()
    partition = OHLCVPartition(year=2026, month=1)

    assert policy.partition_value_file_relative_path(_identity(), partition) == PurePosixPath(
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/"
        "data/year=2026/month=01/candles.csv"
    )
    assert policy.partition_metadata_relative_path(
        _identity(),
        partition,
    ) == PurePosixPath(
        "ohlcv/raw/v1/provider=binance/market=spot/symbol=btcusdt/timeframe=1m/"
        "data/year=2026/month=01/candles.meta.json"
    )


@pytest.mark.parametrize("month", (0, 13))
def test_invalid_partition_month_rejected(month: int) -> None:
    with pytest.raises(ValueError, match="month"):
        OHLCVPartition(year=2026, month=month)


def test_contract_module_imports_no_core_or_gui() -> None:
    source = _OHLCV_STORAGE_CONTRACT.read_text(encoding="utf-8")

    assert "leonardo.core" not in source
    assert "leonardo.gui" not in source


def test_contract_module_exposes_no_storage_side_effect_helpers() -> None:
    source = _OHLCV_STORAGE_CONTRACT.read_text(encoding="utf-8")
    forbidden_tokens = (
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


def _identity() -> OHLCVDatasetIdentity:
    return OHLCVDatasetIdentity(
        provider="binance",
        market="spot",
        symbol="BTCUSDT",
        timeframe="1m",
    )
