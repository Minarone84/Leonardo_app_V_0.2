"""Read-only catalog of OHLCV datasets accepted for Research use.

The OHLCV Area remains authoritative for physical persistence and validation.
This module only discovers persisted datasets and verifies that their current
CSV bytes still match accepted ``OHLCVSidecarV1`` evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from leonardo.data import (
    MarketId,
    canonicalize_market_id,
    storage_segment_to_timeframe,
    timeframe_to_storage_segment,
)
from leonardo.ohlcv.store import OHLCVStore

_ACCEPTED_PERSISTENCE_STATUSES = frozenset({"committed", "repaired"})
_ACCEPTED_VALIDATION_STATUS = "ok"


@dataclass(frozen=True, slots=True)
class AcceptedDatasetSummary:
    """Immutable Research-facing summary of one accepted OHLCV dataset."""

    market_id: MarketId
    csv_path: Path
    sidecar_path: Path
    file_sha256: str
    row_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    source: str
    persistence_status: str
    validation_status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetRejection:
    """Structured reason why a physical dataset is unavailable to Research."""

    dataset_dir: Path
    code: str
    reason: str
    market_id: MarketId | None = None


@dataclass(frozen=True, slots=True)
class DatasetCatalogReport:
    """Deterministic catalog result containing accepted and refused datasets."""

    accepted: tuple[AcceptedDatasetSummary, ...]
    rejected: tuple[DatasetRejection, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class AcceptedDatasetCatalog:
    """Discover OHLCV datasets without changing persistence or validation truth."""

    def __init__(self, historical_root: Path) -> None:
        self._root = Path(historical_root)
        self._store = OHLCVStore(self._root)

    @property
    def historical_root(self) -> Path:
        return self._root

    def scan(self) -> DatasetCatalogReport:
        accepted: list[AcceptedDatasetSummary] = []
        rejected: list[DatasetRejection] = []
        for candidate in self._candidate_directories():
            result = self._inspect_candidate(candidate)
            if isinstance(result, AcceptedDatasetSummary):
                accepted.append(result)
            else:
                rejected.append(result)
        accepted.sort(key=lambda item: _market_sort_key(item.market_id))
        rejected.sort(
            key=lambda item: (
                _market_sort_key(item.market_id) if item.market_id is not None else ("", "", "", ""),
                str(item.dataset_dir),
                item.code,
            )
        )
        return DatasetCatalogReport(tuple(accepted), tuple(rejected))

    def list_accepted(self) -> tuple[AcceptedDatasetSummary, ...]:
        """Return only datasets whose persisted evidence is accepted and current."""

        return self.scan().accepted

    def inspect_market(
        self,
        market_id: MarketId,
    ) -> AcceptedDatasetSummary | DatasetRejection:
        """Inspect one canonical MarketId without scanning unrelated datasets."""

        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        canonical = canonicalize_market_id(
            market_id.exchange,
            market_id.market_type,
            market_id.symbol,
            market_id.timeframe,
        )
        if canonical != market_id:
            raise ValueError(f"market_id must already be canonical: {canonical!r}")
        return self._inspect_candidate(self._store.dataset_dir(market_id))

    def _candidate_directories(self) -> tuple[Path, ...]:
        if not self._root.exists():
            return ()
        if not self._root.is_dir():
            raise NotADirectoryError(f"historical root is not a directory: {self._root}")

        candidates: list[Path] = []
        for exchange_dir in _child_directories(self._root):
            for market_type_dir in _child_directories(exchange_dir):
                for symbol_dir in _child_directories(market_type_dir):
                    for timeframe_dir in _child_directories(symbol_dir):
                        dataset_dir = timeframe_dir / "ohlcv"
                        if dataset_dir.is_dir():
                            candidates.append(dataset_dir)
        return tuple(sorted(candidates, key=str))

    def _inspect_candidate(
        self,
        dataset_dir: Path,
    ) -> AcceptedDatasetSummary | DatasetRejection:
        identity_result = _market_from_dataset_dir(self._root, dataset_dir)
        if isinstance(identity_result, DatasetRejection):
            return identity_result
        market = identity_result

        expected_dir = self._store.dataset_dir(market)
        if dataset_dir != expected_dir:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="noncanonical_storage_identity",
                reason=(
                    "Dataset directory does not use the canonical MarketId storage segments; "
                    f"expected {expected_dir}."
                ),
            )

        csv_path = dataset_dir / "candles.csv"
        sidecar_path = dataset_dir / "candles.meta.json"
        if not csv_path.is_file():
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="csv_missing",
                reason="candles.csv is missing.",
            )
        if not sidecar_path.is_file():
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="sidecar_missing",
                reason="candles.meta.json is missing; Research requires durable validation evidence.",
            )

        try:
            sidecar = self._store.read_sidecar(market)
        except (OSError, TypeError, ValueError) as error:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="sidecar_invalid",
                reason=f"OHLCV sidecar is unreadable or invalid: {type(error).__name__}: {error}",
            )

        if sidecar.market_id != market:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="sidecar_market_mismatch",
                reason=(
                    "OHLCV sidecar MarketId does not match the canonical storage path: "
                    f"{sidecar.market_id!r}."
                ),
            )
        if sidecar.persistence_status not in _ACCEPTED_PERSISTENCE_STATUSES:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="persistence_not_final",
                reason=(
                    f"Persistence status is {sidecar.persistence_status!r}; Research accepts only "
                    f"{sorted(_ACCEPTED_PERSISTENCE_STATUSES)}."
                ),
            )
        if sidecar.validation_status != _ACCEPTED_VALIDATION_STATUS:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="validation_not_accepted",
                reason=(
                    f"Validation status is {sidecar.validation_status!r}; Research accepts only "
                    f"{_ACCEPTED_VALIDATION_STATUS!r}."
                ),
            )
        if sidecar.row_count <= 0:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="dataset_empty",
                reason="Accepted Research datasets must contain at least one candle.",
            )

        try:
            before = csv_path.stat()
            current_sha256 = _sha256(csv_path)
            after = csv_path.stat()
        except OSError as error:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="csv_unreadable",
                reason=f"candles.csv could not be inspected: {type(error).__name__}: {error}",
            )
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="csv_changed_during_scan",
                reason="candles.csv changed while Research was verifying it; retry after the writer settles.",
            )
        if current_sha256 != sidecar.file_sha256:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="csv_hash_mismatch",
                reason="candles.csv bytes no longer match the accepted OHLCV sidecar SHA-256.",
            )

        if sidecar.first_timestamp_ms is None or sidecar.last_timestamp_ms is None:
            return DatasetRejection(
                dataset_dir=dataset_dir,
                market_id=market,
                code="sidecar_time_range_missing",
                reason="A non-empty accepted dataset must declare first and last timestamps.",
            )
        return AcceptedDatasetSummary(
            market_id=market,
            csv_path=csv_path,
            sidecar_path=sidecar_path,
            file_sha256=current_sha256,
            row_count=sidecar.row_count,
            first_timestamp_ms=sidecar.first_timestamp_ms,
            last_timestamp_ms=sidecar.last_timestamp_ms,
            source=sidecar.source,
            persistence_status=sidecar.persistence_status,
            validation_status=sidecar.validation_status,
            warnings=sidecar.warnings,
        )


def _child_directories(path: Path) -> tuple[Path, ...]:
    return tuple(sorted((item for item in path.iterdir() if item.is_dir()), key=lambda item: item.name))


def _market_from_dataset_dir(
    root: Path,
    dataset_dir: Path,
) -> MarketId | DatasetRejection:
    try:
        relative = dataset_dir.relative_to(root)
    except ValueError:
        return DatasetRejection(
            dataset_dir=dataset_dir,
            code="dataset_outside_root",
            reason="Dataset directory is outside the configured historical root.",
        )
    if len(relative.parts) != 5 or relative.parts[-1] != "ohlcv":
        return DatasetRejection(
            dataset_dir=dataset_dir,
            code="storage_layout_invalid",
            reason=(
                "Expected storage layout "
                "<exchange>/<market_type>/<symbol>/<timeframe>/ohlcv."
            ),
        )

    exchange, market_type, symbol, timeframe_segment, _ = relative.parts
    try:
        timeframe = storage_segment_to_timeframe(timeframe_segment)
        market = canonicalize_market_id(exchange, market_type, symbol, timeframe)
    except ValueError as error:
        return DatasetRejection(
            dataset_dir=dataset_dir,
            code="storage_identity_invalid",
            reason=f"Storage path does not define a valid MarketId: {error}",
        )

    canonical_parts = (
        market.exchange,
        market.market_type,
        market.symbol,
        timeframe_to_storage_segment(market.timeframe),
        "ohlcv",
    )
    if relative.parts != canonical_parts:
        return DatasetRejection(
            dataset_dir=dataset_dir,
            market_id=market,
            code="noncanonical_storage_identity",
            reason=(
                "Storage path normalizes to a different canonical MarketId path: "
                f"{'/'.join(canonical_parts)}."
            ),
        )
    return market


def _market_sort_key(market: MarketId) -> tuple[str, str, str, str]:
    return market.exchange, market.market_type, market.symbol, market.timeframe


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
