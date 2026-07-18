"""Read/manage orchestration over canonical dataset and artifact authorities."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from numbers import Integral, Real
from typing import Protocol

from leonardo.artifacts import (
    ArtifactError,
    ArtifactLineageError,
    ArtifactService,
    ArtifactSummary,
    RecipeSummary,
)
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.research import (
    AcceptedDatasetCatalog,
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    DatasetRejection,
    HistoricalDataset,
    HistoricalDatasetLoader,
)

from .models import (
    DataManagerArtifactEntry,
    DataManagerArtifactValidation,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerDeletionResult,
    DataManagerMarketSnapshot,
    DataManagerOperationError,
    DataManagerPreview,
    DataManagerRecipeEntry,
)


_DATASET_COLUMNS = ("ts_ms", "open", "high", "low", "close", "volume")


class DataManagerMarketUnavailableError(DataManagerOperationError):
    """Raised when canonical persistence no longer accepts an exact market."""


class _Catalog(Protocol):
    def scan(self) -> DatasetCatalogReport: ...


class _Loader(Protocol):
    def load(
        self,
        market_id: MarketId,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> HistoricalDataset: ...


class _Artifacts(Protocol):
    def list_recipes(self, market_id: MarketId) -> tuple[RecipeSummary, ...]: ...
    def list_artifacts(self, market_id: MarketId) -> tuple[ArtifactSummary, ...]: ...
    def load_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> object: ...
    def validate_artifact_current(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary: ...
    def delete_artifact(
        self, market_id: MarketId, kind: str, tool_key: str, artifact_id: str
    ) -> ArtifactSummary: ...
    def delete_recipe(
        self, market_id: MarketId, kind: str, tool_key: str, recipe_id: str
    ) -> RecipeSummary: ...


class DataManagerService:
    """Project canonical persisted truth into immutable Data Manager values."""

    def __init__(
        self,
        catalog: AcceptedDatasetCatalog | _Catalog,
        loader: HistoricalDatasetLoader | _Loader,
        artifacts: ArtifactService | _Artifacts,
    ) -> None:
        _require_methods(catalog, "catalog", ("scan",))
        _require_methods(loader, "loader", ("load",))
        _require_methods(
            artifacts,
            "artifacts",
            (
                "list_recipes",
                "list_artifacts",
                "load_artifact",
                "validate_artifact_current",
                "delete_artifact",
                "delete_recipe",
            ),
        )
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts

    def scan_catalog(self) -> DataManagerCatalogSnapshot:
        return _project_catalog(self._catalog.scan())

    def inspect_market(self, market_id: MarketId) -> DataManagerMarketSnapshot:
        market = _canonical_market(market_id)
        dataset = self._require_accepted(market)
        recipes = tuple(_project_recipe(item) for item in self._artifacts.list_recipes(market))
        artifacts = tuple(
            _project_artifact(item) for item in self._artifacts.list_artifacts(market)
        )
        return DataManagerMarketSnapshot(market, dataset, recipes, artifacts)

    def preview_dataset(
        self, market_id: MarketId, *, limit: int = 200
    ) -> DataManagerPreview:
        return self._preview_dataset(
            market_id,
            limit=limit,
            progress=None,
            cancellation_requested=None,
        )

    def _preview_dataset(
        self,
        market_id: MarketId,
        *,
        limit: int,
        progress: Callable[[int, int], None] | None,
        cancellation_requested: Callable[[], bool] | None,
    ) -> DataManagerPreview:
        market = _canonical_market(market_id)
        _validate_limit(limit)
        self._require_accepted(market)
        dataset = self._loader.load(
            market,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )
        source_rows = tuple(
            zip(
                dataset.ts_ms,
                dataset.open,
                dataset.high,
                dataset.low,
                dataset.close,
                dataset.volume,
                strict=True,
            )
        )
        rows = _bounded_rows(source_rows, limit)
        display_rows = tuple(
            (_format_timestamp(row[0]), *(_format_cell(value) for value in row[1:]))
            for row in rows
        )
        return DataManagerPreview(
            title=f"OHLCV - {market.as_key()}",
            market_id=market,
            object_kind="dataset",
            object_id=None,
            columns=_DATASET_COLUMNS,
            rows=display_rows,
            total_rows=dataset.row_count,
            truncated=dataset.row_count > len(display_rows),
            metadata={
                "market_id": market.as_key(),
                "row_count": str(dataset.row_count),
                "first_timestamp_ms": str(dataset.first_timestamp_ms),
                "last_timestamp_ms": str(dataset.last_timestamp_ms),
            },
        )

    def preview_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        limit: int = 200,
    ) -> DataManagerPreview:
        market = _canonical_market(market_id)
        _validate_limit(limit)
        self._require_accepted(market)
        loaded = self._artifacts.load_artifact(market, kind, tool_key, artifact_id)
        metadata = loaded.metadata
        output_names = tuple(metadata.recipe.output_names)
        columns = ("ts_ms", *output_names)
        frame = loaded.frame
        source_rows = tuple(
            tuple(frame[column].iloc[index] for column in columns)
            for index in range(len(frame.index))
        )
        rows = _bounded_rows(source_rows, limit)
        display_rows = tuple(
            (_format_timestamp(row[0]), *(_format_cell(value) for value in row[1:]))
            for row in rows
        )
        return DataManagerPreview(
            title=f"Artifact {artifact_id}",
            market_id=market,
            object_kind="artifact",
            object_id=artifact_id,
            columns=columns,
            rows=display_rows,
            total_rows=metadata.row_count,
            truncated=metadata.row_count > len(display_rows),
            metadata={
                "market_id": market.as_key(),
                "artifact_id": artifact_id,
                "recipe_id": metadata.recipe.recipe_id,
                "tool_key": metadata.recipe.tool_key,
                "kind": metadata.recipe.kind,
                "row_count": str(metadata.row_count),
                "first_timestamp_ms": str(metadata.first_timestamp_ms),
                "last_timestamp_ms": str(metadata.last_timestamp_ms),
            },
        )

    def validate_artifact_current(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
    ) -> DataManagerArtifactValidation:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        try:
            self._artifacts.validate_artifact_current(
                market, kind, tool_key, artifact_id
            )
        except ArtifactLineageError as error:
            return DataManagerArtifactValidation(
                market, kind, tool_key, artifact_id, "stale", str(error)
            )
        except ArtifactError as error:
            return DataManagerArtifactValidation(
                market, kind, tool_key, artifact_id, "invalid", str(error)
            )
        return DataManagerArtifactValidation(
            market, kind, tool_key, artifact_id, "current", ""
        )

    def delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
    ) -> DataManagerDeletionResult:
        return self._delete_artifact(
            market_id, kind, tool_key, artifact_id, before_delete=None
        )

    def _delete_artifact(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        artifact_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> DataManagerDeletionResult:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        if before_delete is not None:
            before_delete()
        self._artifacts.delete_artifact(market, kind, tool_key, artifact_id)
        return DataManagerDeletionResult(
            market, "artifact", kind, tool_key, artifact_id
        )

    def delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
    ) -> DataManagerDeletionResult:
        return self._delete_recipe(
            market_id, kind, tool_key, recipe_id, before_delete=None
        )

    def _delete_recipe(
        self,
        market_id: MarketId,
        kind: str,
        tool_key: str,
        recipe_id: str,
        *,
        before_delete: Callable[[], None] | None,
    ) -> DataManagerDeletionResult:
        market = _canonical_market(market_id)
        self._require_accepted(market)
        if before_delete is not None:
            before_delete()
        self._artifacts.delete_recipe(market, kind, tool_key, recipe_id)
        return DataManagerDeletionResult(
            market, "recipe", kind, tool_key, recipe_id
        )

    def _require_accepted(self, market: MarketId) -> DataManagerDatasetEntry:
        snapshot = self.scan_catalog()
        accepted = snapshot.accepted_market(market)
        if accepted is not None:
            return accepted
        rejected = next(
            (item for item in snapshot.datasets if item.market_id == market),
            None,
        )
        if rejected is not None:
            raise DataManagerMarketUnavailableError(
                f"Dataset {market.as_key()} is unavailable: "
                f"{rejected.rejection_code}: {rejected.rejection_reason}"
            )
        raise DataManagerMarketUnavailableError(
            f"Dataset {market.as_key()} is missing from canonical persistence"
        )


def _project_catalog(report: DatasetCatalogReport) -> DataManagerCatalogSnapshot:
    entries = [
        DataManagerDatasetEntry(
            market_id=item.market_id,
            accepted=True,
            row_count=item.row_count,
            first_timestamp_ms=item.first_timestamp_ms,
            last_timestamp_ms=item.last_timestamp_ms,
            source=item.source,
            persistence_status=item.persistence_status,
            validation_status=item.validation_status,
            warnings=tuple(item.warnings),
        )
        for item in report.accepted
    ]
    entries.extend(
        DataManagerDatasetEntry(
            market_id=item.market_id,
            accepted=False,
            rejection_code=item.code,
            rejection_reason=item.reason,
        )
        for item in report.rejected
    )
    return DataManagerCatalogSnapshot(tuple(entries))


def _project_recipe(summary: RecipeSummary) -> DataManagerRecipeEntry:
    return DataManagerRecipeEntry(
        market_id=summary.market_id,
        recipe_id=summary.recipe_id,
        tool_key=summary.tool_key,
        kind=summary.kind,
        output_names=tuple(summary.output_names),
        display_name=summary.display_name,
        created_at_utc=summary.created_at_utc,
        valid=summary.valid,
        rejection_reason=summary.rejection_reason or "",
    )


def _project_artifact(summary: ArtifactSummary) -> DataManagerArtifactEntry:
    return DataManagerArtifactEntry(
        market_id=summary.market_id,
        artifact_id=summary.artifact_id,
        recipe_id=summary.recipe_id,
        tool_key=summary.tool_key,
        kind=summary.kind,
        output_names=tuple(summary.output_names),
        row_count=summary.row_count,
        first_timestamp_ms=summary.first_timestamp_ms,
        last_timestamp_ms=summary.last_timestamp_ms,
        created_at_utc=summary.created_at_utc,
        valid=summary.valid,
        rejection_reason=summary.rejection_reason or "",
        current_status="unknown" if summary.valid else "invalid",
    )


def _bounded_rows(rows: Sequence[tuple[object, ...]], limit: int) -> tuple[tuple[object, ...], ...]:
    total = len(rows)
    if total <= limit:
        return tuple(rows)
    head = (limit + 1) // 2
    tail = limit // 2
    return (*rows[:head], *rows[total - tail :])


def _format_timestamp(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise DataManagerOperationError("timestamp values must be numeric integers")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 0:
        raise DataManagerOperationError("timestamp values must be finite non-negative integers")
    return str(int(numeric))


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        numeric = float(value)
        if math.isnan(numeric):
            return ""
        if not math.isfinite(numeric):
            raise DataManagerOperationError("preview values cannot contain infinity")
        return format(numeric, ".15g")
    raise DataManagerOperationError(
        f"preview values must be strings, booleans, or finite numbers: {type(value).__name__}"
    )


def _validate_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("preview limit must be an integer from 1 through 500")


def _canonical_market(market_id: MarketId) -> MarketId:
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
    return market_id


def _require_methods(value: object, name: str, methods: tuple[str, ...]) -> None:
    missing = [method for method in methods if not callable(getattr(value, method, None))]
    if missing:
        raise TypeError(f"{name} must expose callable methods: {', '.join(missing)}")


def format_created_at(value: datetime | None) -> str:
    """Return one stable display timestamp for GUI projections."""

    if value is None:
        return ""
    if not isinstance(value, datetime):
        raise TypeError("created_at_utc must be a timezone-aware datetime or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at_utc must be timezone-aware")
    resolved = value.astimezone(UTC)
    return resolved.isoformat().replace("+00:00", "Z")
