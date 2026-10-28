"""Canonical Data Manager creation workflows over accepted service authorities."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO, BytesIO
import csv
from leonardo.ohlcv.store import OHLCVStore

import pandas as pd

from leonardo.artifacts import (
    ArtifactError,
    ArtifactService,
    ManagedArtifactVersionKey,
    compute_logical_artifact_id,
)
from leonardo.data import MarketId, timeframe_duration_ms
from leonardo.ohlcv.validation import _add_calendar_months
from leonardo.financial_tools import get_financial_tool_spec, resolve_output_names, resolve_parameters
from leonardo.recipes import (
    PortableRecipeDependencyV1,
    PortableRecipeOHLCVInputV1,
    PortableRecipeV1,
    build_portable_recipe,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader

from .creation_models import (
    ArtifactCollectionDependencyV1,
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    ArtifactCollectionRevisionV2,
    ArtifactCollectionSelectionPlan,
    ArtifactCollectionValidation,
    BatchArtifactBranchRequest,
    BatchArtifactPlan,
    BatchArtifactRequest,
    DatabaseDefinitionV1,
    DatabaseCollectionReferenceV2,
    DatabaseContentEditPlan,
    DatabaseContentOutputPreview,
    DatabaseReadiness,
    DatabaseRevisionManifest,
    DatabaseRevisionManifestV1,
    DatabaseRevisionManifestV2,
    DatabaseSeedV1,
    DatabaseSeedV2,
    DatabaseRevisionManifestV3,
    DatabaseRevisionManifestV4,
    DatabaseLegacyOutputV1,
    database_revision_from_dict,
    DatabaseSeedCreationPlan,
    DatabaseSeedAppendPlan,
    DataManagerCreationError,
    SeedOnlyDatabaseCreationPlan,
    deterministic_hash,
)
from .construct_batch import visible_output_names
from .construct_sources import list_construct_source_signals
from .direct_artifact import (
    DataManagerDirectArtifactSource,
    DataManagerDirectArtifactRequest,
    _build_direct_portable_recipe,
    _validate_source_roles,
)
from .creation_store import DataManagerCreationStore, DataManagerCreationStoreError, _database_nullable_columns, _snapshot_rows
from .models import (
    DataManagerArtifactMaterializationPlan,
    DataManagerArtifactMaterializationResult,
)


class DataManagerCreationWorkflow:
    """Coordinate Data Manager creation while preserving canonical owners."""

    def __init__(
        self,
        *,
        store: DataManagerCreationStore,
        catalog: AcceptedDatasetCatalog | object,
        loader: HistoricalDatasetLoader | object,
        artifacts: ArtifactService | object,
        batch_materialization_planner: Callable[
            [BatchArtifactRequest, tuple[PortableRecipeV1, ...]],
            tuple[DataManagerArtifactMaterializationPlan, object],
        ],
        batch_materialization_executor: Callable[..., DataManagerArtifactMaterializationResult],
        portable_recipe_resolver: Callable[
            [tuple[PortableRecipeV1, ...]], tuple[PortableRecipeV1, ...]
        ],
        portable_recipe_publisher: Callable[
            [tuple[PortableRecipeV1, ...]], None
        ],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._catalog = catalog
        self._loader = loader
        self._artifacts = artifacts
        self._plan_batch_materialization = batch_materialization_planner
        self._execute_batch_materialization = batch_materialization_executor
        self._resolve_portable_recipes = portable_recipe_resolver
        self._publish_portable_recipes = portable_recipe_publisher
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def store(self) -> DataManagerCreationStore:
        return self._store

    def create_database_seed(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: Sequence[str] = ("open", "high", "low", "close", "volume"),
    ) -> DatabaseSeedV2:
        plan = self.plan_database_seed_creation(
            market_id,
            display_name,
            description=description,
            selected_ohlcv_columns=selected_ohlcv_columns,
        )
        return self.execute_database_seed_creation(plan)

    def plan_database_seed_creation(
        self,
        market_id: MarketId,
        display_name: str,
        *,
        description: str = "",
        selected_ohlcv_columns: Sequence[str] = (
            "open", "high", "low", "close", "volume"
        ),
    ) -> DatabaseSeedCreationPlan:
        source = self._artifacts.capture_accepted_source(market_id)
        dataset = self._loader.load(market_id)
        if dataset.file_sha256 != source.csv_sha256 or dataset.row_count != source.row_count:
            raise DataManagerCreationError("loaded OHLCV does not match accepted source evidence")
        columns = tuple(selected_ohlcv_columns)
        if columns not in (
            ("open", "high", "low", "close"),
            ("open", "high", "low", "close", "volume"),
        ):
            raise DataManagerCreationError(
                "selected_ohlcv_columns must be OHLC with optional Volume in canonical order"
            )
        values = self._full_source_seed_values(dataset, source, columns)
        seed = DatabaseSeedV2(
            seed_id=self._store.new_seed_id(), display_name=display_name,
            description=description, market_id=market_id, source_ohlcv=source,
            source_row_count=dataset.row_count,
            first_timestamp_ms=dataset.first_timestamp_ms,
            last_timestamp_ms=dataset.last_timestamp_ms,
            selected_ohlcv_columns=columns,
            selected_range_start_ms=dataset.first_timestamp_ms,
            selected_range_end_ms=dataset.last_timestamp_ms,
            created_at_utc=self._clock(),
            row_count=dataset.row_count, column_count=len(columns) + 1, values_sha256=sha256(values).hexdigest(),
        )
        return DatabaseSeedCreationPlan(
            deterministic_hash(seed.to_dict()), seed, values
        )

    def execute_database_seed_creation(
        self,
        plan: DatabaseSeedCreationPlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseSeedV2:
        if not isinstance(plan, DatabaseSeedCreationPlan):
            raise TypeError("plan must be a DatabaseSeedCreationPlan")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerCreationError("Database Seed creation cancelled")
        self._require_seed_candidate_current(plan.seed, plan.values_csv)

        def publication_gate() -> None:
            if cancelled():
                raise DataManagerCreationError("Database Seed creation cancelled")
            self._require_seed_candidate_current(plan.seed, plan.values_csv)
            if before_publish is not None:
                before_publish()
            if cancelled():
                raise DataManagerCreationError("Database Seed creation cancelled")
            self._require_seed_candidate_current(plan.seed, plan.values_csv)

        return self._store.save_seed(plan.seed, values_csv=plan.values_csv, before_publish=publication_gate)

    def plan_database_seed_append(self, seed_id: str) -> DatabaseSeedAppendPlan:
        seed = self._store.load_seed_metadata(seed_id)
        old_values = self._seed_base_values(seed)
        columns, _old_rows, old_axis = _snapshot_rows(
            old_values, columns=("ts_ms", *seed.selected_ohlcv_columns),
            first=seed.selected_range_start_ms, last=seed.selected_range_end_ms,
        )
        source = self._artifacts.capture_accepted_source(seed.market_id)
        dataset = self._loader.load(seed.market_id)
        if (source.row_count < seed.source_row_count or source.last_timestamp_ms < seed.last_timestamp_ms
                or source.first_timestamp_ms != seed.first_timestamp_ms):
            raise DataManagerCreationError("OHLCV source coverage conflict; repair or revalidate the source; stored Seed remains unchanged")
        if (dataset.file_sha256 != source.csv_sha256 or dataset.row_count != source.row_count
                or dataset.first_timestamp_ms != source.first_timestamp_ms
                or dataset.last_timestamp_ms != source.last_timestamp_ms):
            raise DataManagerCreationError("loaded OHLCV does not match accepted source evidence")
        projected = self._full_source_seed_values(dataset, source, seed.selected_ohlcv_columns)
        _header, rows, axis = _snapshot_rows(projected, columns=columns)
        suffix = tuple(row for row, timestamp in zip(rows, axis, strict=True) if timestamp > old_axis[-1])
        last = old_axis[-1]
        step = timeframe_duration_ms(seed.market_id.timeframe)
        for row in suffix:
            expected = last + step if step is not None else _add_calendar_months(last, int(seed.market_id.timeframe[:-1]))
            last = int(row[0])
            if last != expected:
                raise DataManagerCreationError("Seed append suffix has a boundary or interior gap")
        values = old_values
        candidate = seed
        if suffix:
            buffer = StringIO(newline="")
            csv.writer(buffer, lineterminator="\n").writerows(suffix)
            values = old_values + (b"" if old_values.endswith(b"\n") else b"\n") + buffer.getvalue().encode("utf-8")
            _columns, _rows, combined = _snapshot_rows(values, columns=columns)
            if not values.startswith(old_values) or combined != (*old_axis, *(int(row[0]) for row in suffix)):
                raise DataManagerCreationError("Seed append changed existing rows")
            changes = dict(source_ohlcv=source, source_row_count=source.row_count,
                           first_timestamp_ms=source.first_timestamp_ms, last_timestamp_ms=source.last_timestamp_ms,
                           selected_range_end_ms=last)
            if isinstance(seed, DatabaseSeedV2):
                changes.update(row_count=len(combined), values_sha256=sha256(values).hexdigest())
            candidate = replace(seed, **changes)
        payload = {
            "previous_seed_sha256": sha256(seed.canonical_json_bytes()).hexdigest(),
            "previous_values_sha256": sha256(old_values).hexdigest(),
            "previous_row_count": len(old_axis), "seed": candidate.to_dict(),
            "values_sha256": sha256(values).hexdigest(), "source_ohlcv": source.to_dict(),
            "appended_row_count": len(suffix),
        }
        return DatabaseSeedAppendPlan(
            deterministic_hash(payload), payload["previous_seed_sha256"], payload["previous_values_sha256"],
            len(old_axis), candidate, values, source, len(suffix),
        )

    def execute_database_seed_append(self, plan, *, cancellation_requested=None, before_publish=None):
        if not isinstance(plan, DatabaseSeedAppendPlan):
            raise TypeError("plan must be a DatabaseSeedAppendPlan")
        cancelled = cancellation_requested or (lambda: False)

        def verify():
            if cancelled():
                raise DataManagerCreationError("Database Seed append cancelled")
            if self.plan_database_seed_append(plan.seed.seed_id) != plan:
                raise DataManagerCreationError("Database Seed append plan is stale")

        verify()
        if not plan.appended_row_count:
            return plan.seed
        previous = self._store.load_seed_metadata(plan.seed.seed_id)
        old_values = self._seed_base_values(previous)
        if (sha256(previous.canonical_json_bytes()).hexdigest() != plan.previous_seed_sha256
                or sha256(old_values).hexdigest() != plan.previous_values_sha256):
            raise DataManagerCreationError("Database Seed changed before append")

        def require_reviewed_evidence():
            if cancelled():
                raise DataManagerCreationError("Database Seed append cancelled")
            if (self._store.load_seed_metadata(plan.seed.seed_id) != previous
                    or self._artifacts.capture_accepted_source(previous.market_id) != plan.source_ohlcv):
                raise DataManagerCreationError("Database Seed append plan is stale")

        def publication_gate():
            require_reviewed_evidence()
            if before_publish is not None:
                before_publish()
            require_reviewed_evidence()

        return self._store.append_seed(previous, plan.seed, old_values, plan.values_csv, before_publish=publication_gate)

    def plan_seed_only_database_creation(
        self,
        seed_id: str,
        display_name: str,
        *,
        description: str = "",
    ) -> SeedOnlyDatabaseCreationPlan:
        seed = self._store.load_seed_metadata(seed_id)
        frame = self._seed_base_frame(seed)
        seed_hash = sha256(seed.canonical_json_bytes()).hexdigest()
        payload = {
            "seed_id": seed.seed_id,
            "seed_sha256": seed_hash,
            "source_ohlcv": seed.source_ohlcv.to_dict(),
            "display_name": display_name,
            "description": description,
            "column_names": list(frame.columns),
            "row_count": len(frame),
            "first_timestamp_ms": int(frame["ts_ms"].iloc[0]),
            "last_timestamp_ms": int(frame["ts_ms"].iloc[-1]),
        }
        return SeedOnlyDatabaseCreationPlan(
            plan_id=deterministic_hash(payload),
            seed_id=seed.seed_id,
            seed_sha256=seed_hash,
            source_ohlcv=seed.source_ohlcv,
            display_name=display_name,
            description=description,
            column_names=tuple(frame.columns),
            row_count=len(frame),
            first_timestamp_ms=int(frame["ts_ms"].iloc[0]),
            last_timestamp_ms=int(frame["ts_ms"].iloc[-1]),
        )

    def execute_seed_only_database_creation(
        self,
        plan: SeedOnlyDatabaseCreationPlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifestV3:
        if not isinstance(plan, SeedOnlyDatabaseCreationPlan):
            raise TypeError("plan must be a SeedOnlyDatabaseCreationPlan")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerCreationError("Seed-only Database creation cancelled")
        fresh = self.plan_seed_only_database_creation(
            plan.seed_id, plan.display_name, description=plan.description
        )
        if fresh != plan:
            raise DataManagerCreationError(
                "Seed-only Database creation plan changed before execution"
            )
        seed = self._store.load_seed_metadata(plan.seed_id)
        if sha256(seed.canonical_json_bytes()).hexdigest() != plan.seed_sha256:
            raise DataManagerCreationError("Database Seed bytes changed before execution")
        values = self._seed_base_values(seed)
        if isinstance(seed, DatabaseSeedV2) and sha256(values).hexdigest() != seed.values_sha256:
            raise DataManagerCreationStoreError("Database output values hash disagrees with Seed")
        database_id = self._store.new_database_id()
        now = self._clock()
        definition = DatabaseDefinitionV1(
            database_id,
            plan.display_name,
            plan.description,
            seed.market_id,
            seed.seed_id,
            now,
        )
        mapping = {column: column for column in plan.column_names}
        payload = {
            "schema_version": "4.0",
            "object_type": "database_revision",
            "database_id": database_id,
            "display_name": plan.display_name,
            "description": plan.description,
            "seed_id": seed.seed_id,
            "market_id": {
                "exchange": seed.market_id.exchange,
                "market_type": seed.market_id.market_type,
                "symbol": seed.market_id.symbol,
                "timeframe": seed.market_id.timeframe,
            },
            "source_ohlcv": plan.source_ohlcv.to_dict(),
            "members": [],
            "dependency_edges": [],
            "selected_outputs": [],
            "collection_sources": [],
            "selection_sources": [],
            "value_provenance": {"members": [], "dependency_edges": [], "outputs": []},
            "column_mapping": mapping,
            "first_timestamp_ms": plan.first_timestamp_ms,
            "last_timestamp_ms": plan.last_timestamp_ms,
            "row_count": plan.row_count,
            "column_count": len(plan.column_names),
            "values_sha256": sha256(values).hexdigest(),
            "previous_revision_id": None,
            "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        }
        manifest = DatabaseRevisionManifestV4(
            database_id=database_id,
            revision_id=deterministic_hash(payload),
            display_name=plan.display_name,
            description=plan.description,
            seed_id=seed.seed_id,
            market_id=seed.market_id,
            source_ohlcv=plan.source_ohlcv,
            members=(),
            dependency_edges=(),
            selected_outputs=(),
            collection_sources=(),
            selection_sources=(),
            value_provenance=payload["value_provenance"],
            column_mapping=mapping,
            first_timestamp_ms=plan.first_timestamp_ms,
            last_timestamp_ms=plan.last_timestamp_ms,
            row_count=plan.row_count,
            column_count=len(plan.column_names),
            values_sha256=sha256(values).hexdigest(),
            previous_revision_id=None,
            created_at_utc=now,
        )
        if cancelled():
            raise DataManagerCreationError("Seed-only Database creation cancelled")

        def publication_gate() -> None:
            if cancelled():
                raise DataManagerCreationError("Seed-only Database creation cancelled")
            persisted = self._store.load_seed_metadata(plan.seed_id)
            if sha256(persisted.canonical_json_bytes()).hexdigest() != plan.seed_sha256:
                raise DataManagerCreationError(
                    "Database Seed bytes changed before publication"
                )
            if before_publish is not None:
                before_publish()

        return self._publish_database_revision(
            definition,
            manifest,
            values,
            expected_head_revision_id=None,
            before_publish=publication_gate,
        )

    def list_database_seeds(self) -> tuple[DatabaseSeedV1 | DatabaseSeedV2, ...]:
        return self._store.list_seeds_metadata()

    def load_database_seed(self, seed_id: str) -> DatabaseSeedV1 | DatabaseSeedV2:
        return self._store.load_seed(seed_id)

    def inspect_database_seed(self, seed_id: str) -> DatabaseSeedV1 | DatabaseSeedV2:
        return self._store.load_seed_metadata(seed_id)

    def validate_database_seed(self, seed_id: str) -> tuple[bool, tuple[str, ...]]:
        try:
            self.load_database_seed(seed_id)
        except (DataManagerCreationError, OSError, ValueError) as exc:
            return False, (str(exc),)
        return True, ()

    def database_seed_newer_source_available(self, seed_id: str) -> bool | None:
        """Return advisory newer-source availability without changing Seed integrity."""

        seed = self._store.load_seed_metadata(seed_id)
        try:
            source = self._artifacts.source_metadata(seed.market_id)
        except (ArtifactError, OSError, TypeError, ValueError):
            return None
        if (source.row_count < seed.source_row_count or source.last_timestamp_ms < seed.last_timestamp_ms
                or source.first_timestamp_ms != seed.first_timestamp_ms):
            return None
        return source.last_timestamp_ms > seed.last_timestamp_ms

    def delete_database_seed(self, seed_id: str) -> DatabaseSeedV1 | DatabaseSeedV2:
        return self._store.delete_seed(seed_id)

    def create_artifact_collection(
        self,
        materialization: DataManagerArtifactMaterializationResult,
        display_name: str,
        *,
        description: str = "",
        source_recipe_collection_id: str | None = None,
        source_recipe_collection_revision_id: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(materialization, DataManagerArtifactMaterializationResult):
            raise TypeError("materialization must be a DataManagerArtifactMaterializationResult")
        values = self._collection_values_from_materialization(
            materialization, selected_outputs,
            progress=progress, cancellation_requested=cancellation_requested,
        )
        now = self._clock()
        return self._store.create_collection_revision(
            market_id=values["market_id"],
            source_ohlcv=values["source_ohlcv"],
            root_logical_artifact_ids=values["roots"],
            support_logical_artifact_ids=values["supports"],
            members=values["members"],
            selected_outputs=values["selected_outputs"],
            presentation_order=values["presentation_order"],
            before_publish=self._collection_publication_gate(cancellation_requested, before_publish),
            revision_factory=lambda collection_id: self._build_collection_revision(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                source_recipe_collection_id=source_recipe_collection_id,
                source_recipe_collection_revision_id=(
                    source_recipe_collection_revision_id
                ),
                previous_revision_id=None,
                created_at_utc=now,
                revised_at_utc=now,
                **values,
            ),
        )

    def create_artifact_collection_from_selection(
        self,
        plan: ArtifactCollectionSelectionPlan,
        display_name: str,
        *,
        description: str = "",
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        self._check_collection_inputs(plan, progress=progress, cancellation_requested=cancellation_requested)
        outputs = self._selection_outputs(plan, selected_outputs)
        now = self._clock()
        presentation_order = tuple(item.column_name for item in outputs)
        return self._store.create_collection_revision(
            market_id=plan.market_id,
            source_ohlcv=plan.source_ohlcv,
            root_logical_artifact_ids=plan.root_logical_artifact_ids,
            support_logical_artifact_ids=plan.support_logical_artifact_ids,
            members=plan.members,
            selected_outputs=outputs,
            presentation_order=presentation_order,
            before_publish=self._collection_publication_gate(cancellation_requested, before_publish),
            revision_factory=lambda collection_id: self._build_collection_revision(
                collection_id=collection_id,
                display_name=display_name,
                description=description,
                market_id=plan.market_id,
                roots=plan.root_logical_artifact_ids,
                supports=plan.support_logical_artifact_ids,
                members=plan.members,
                edges=plan.dependency_edges,
                selected_outputs=outputs,
                presentation_order=presentation_order,
                source_recipe_collection_id=None,
                source_recipe_collection_revision_id=None,
                source_ohlcv=plan.source_ohlcv,
                first_timestamp_ms=plan.first_timestamp_ms,
                last_timestamp_ms=plan.last_timestamp_ms,
                previous_revision_id=None,
                created_at_utc=now,
                revised_at_utc=now,
            ),
        )

    def edit_artifact_collection_from_selection(
        self,
        collection_id: str,
        plan: ArtifactCollectionSelectionPlan,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        expected_revision_id: str,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(plan, ArtifactCollectionSelectionPlan):
            raise TypeError("plan must be an ArtifactCollectionSelectionPlan")
        current = self.load_artifact_collection(collection_id)
        if current.revision_id != expected_revision_id:
            raise DataManagerCreationError(
                "Artifact Collection revision changed before Edit"
            )
        if current.market_id != plan.market_id:
            raise DataManagerCreationError(
                "Artifact Collection selection MarketId differs"
            )
        self._check_collection_inputs(
            plan, retained=current.members, progress=progress,
            cancellation_requested=cancellation_requested,
        )
        member_by_id = {
            item.version_key.logical_artifact_id: item for item in plan.members
        }
        if selected_outputs is None:
            output_values = [
                item
                for item in current.selected_outputs
                if item.logical_artifact_id in member_by_id
                and item.output_name
                in member_by_id[item.logical_artifact_id].output_names
            ]
            selected_pairs = {
                (item.logical_artifact_id, item.output_name)
                for item in output_values
            }
            old_roots = set(current.root_logical_artifact_ids)
            for logical_id in plan.root_logical_artifact_ids:
                if logical_id in old_roots:
                    continue
                for output_name in member_by_id[logical_id].output_names:
                    pair = (logical_id, output_name)
                    if pair not in selected_pairs:
                        output_values.append(
                            ArtifactCollectionOutputV1(
                                logical_id, output_name, output_name
                            )
                        )
                        selected_pairs.add(pair)
            outputs = tuple(output_values)
        else:
            outputs = tuple(selected_outputs)
        if presentation_order is None:
            columns = {item.column_name for item in outputs}
            order = tuple(
                item for item in current.presentation_order if item in columns
            )
            order = (*order, *(item.column_name for item in outputs if item.column_name not in order))
        else:
            order = tuple(presentation_order)
        revised = self._build_collection_revision(
            collection_id=current.collection_id,
            display_name=current.display_name if display_name is None else display_name,
            description=current.description if description is None else description,
            market_id=plan.market_id,
            roots=plan.root_logical_artifact_ids,
            supports=plan.support_logical_artifact_ids,
            members=plan.members,
            edges=plan.dependency_edges,
            selected_outputs=outputs,
            presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=(
                current.source_recipe_collection_revision_id
            ),
            source_ohlcv=plan.source_ohlcv,
            first_timestamp_ms=plan.first_timestamp_ms,
            last_timestamp_ms=plan.last_timestamp_ms,
            previous_revision_id=current.revision_id,
            created_at_utc=current.created_at_utc,
            revised_at_utc=self._clock(),
        )
        return self._store.save_collection_revision(
            revised, expected_head_revision_id=current.revision_id,
            before_publish=self._collection_publication_gate(cancellation_requested, before_publish),
        )

    def list_artifact_collections(self) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return tuple(self._store.load_collection(item) for item in self._store.list_collection_ids())

    def list_artifact_collection_revisions(
        self, collection_id: str
    ) -> tuple[ArtifactCollectionRevisionV1, ...]:
        return self._store.list_collection_revisions(collection_id)

    def load_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionRevisionV1:
        return self._store.load_collection(collection_id, revision_id)

    def inspect_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> tuple[ArtifactCollectionRevisionV1, ArtifactCollectionValidation]:
        revision = self.load_artifact_collection(collection_id, revision_id)
        return revision, self.validate_artifact_collection(collection_id, revision.revision_id)

    def revise_artifact_collection(
        self,
        collection_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        presentation_order: Sequence[str] | None = None,
        remove_root_logical_artifact_ids: Sequence[str] = (),
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        current = self.load_artifact_collection(collection_id)
        roots = tuple(item for item in current.root_logical_artifact_ids if item not in set(remove_root_logical_artifact_ids))
        if not roots:
            raise DataManagerCreationError("Artifact Collection must retain at least one root")
        required = self._required_members(roots, current.dependency_edges)
        members = tuple(item for item in current.members if item.version_key.logical_artifact_id in required)
        supports = tuple(item for item in required if item not in roots)
        outputs = tuple(selected_outputs) if selected_outputs is not None else tuple(
            item for item in current.selected_outputs if item.logical_artifact_id in required
        )
        order = tuple(presentation_order) if presentation_order is not None else tuple(
            item for item in current.presentation_order if item in {output.column_name for output in outputs}
        )
        revised = self._build_collection_revision(
            collection_id=current.collection_id,
            display_name=current.display_name if display_name is None else display_name,
            description=current.description if description is None else description,
            market_id=current.market_id, roots=roots, supports=supports, members=members,
            edges=tuple(edge for edge in current.dependency_edges if edge.dependency_logical_artifact_id in required and edge.dependent_logical_artifact_id in required),
            selected_outputs=outputs, presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            source_ohlcv=current.source_ohlcv,
            first_timestamp_ms=current.first_timestamp_ms,
            last_timestamp_ms=current.last_timestamp_ms,
            previous_revision_id=current.revision_id,
            created_at_utc=current.created_at_utc, revised_at_utc=self._clock(),
        )
        return self._store.save_collection_revision(
            revised, expected_head_revision_id=current.revision_id,
            before_publish=self._collection_publication_gate(cancellation_requested, before_publish),
        )

    def add_collection_branches(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
        *,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        current = self.load_artifact_collection(collection_id)
        if current.market_id != materialization.target_market_id or not self._same_coverage(current.source_ohlcv, materialization.source_ohlcv):
            raise DataManagerCreationError("Artifact branches are incompatible with the Collection")
        branch_member_ids = {
            item.logical_artifact_id for item in materialization.managed_artifacts
        }
        branch_outputs = (
            None
            if selected_outputs is None
            else tuple(
                item
                for item in selected_outputs
                if item.logical_artifact_id in branch_member_ids
            )
            or None
        )
        branch = self._collection_revision_from_materialization(
            materialization, collection_id=current.collection_id,
            display_name=current.display_name, description=current.description,
            previous=current.revision_id, created_at=current.created_at_utc,
            revised_at=self._clock(), source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            selected_outputs=branch_outputs,
            progress=progress, cancellation_requested=cancellation_requested,
        )
        member_map = {item.version_key.logical_artifact_id: item for item in current.members}
        member_map.update({item.version_key.logical_artifact_id: item for item in branch.members})
        roots = tuple(dict.fromkeys((*current.root_logical_artifact_ids, *branch.root_logical_artifact_ids)))
        supports = tuple(item for item in dict.fromkeys((*current.support_logical_artifact_ids, *branch.support_logical_artifact_ids)) if item not in roots)
        edges = tuple(dict.fromkeys((*current.dependency_edges, *branch.dependency_edges)))
        if selected_outputs is not None:
            outputs = tuple(selected_outputs)
            order = tuple(item.column_name for item in outputs)
        else:
            outputs = tuple(
                dict.fromkeys((*current.selected_outputs, *branch.selected_outputs))
            )
            order = tuple(
                dict.fromkeys(
                    (*current.presentation_order, *(item.column_name for item in outputs))
                )
            )
        revised = self._build_collection_revision(
            collection_id=current.collection_id, display_name=current.display_name,
            description=current.description, market_id=current.market_id, roots=roots,
            supports=supports, members=tuple(member_map.values()), edges=edges,
            selected_outputs=outputs, presentation_order=order,
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=current.source_recipe_collection_revision_id,
            source_ohlcv=current.source_ohlcv,
            first_timestamp_ms=max(current.first_timestamp_ms, branch.first_timestamp_ms),
            last_timestamp_ms=min(current.last_timestamp_ms, branch.last_timestamp_ms),
            previous_revision_id=current.revision_id, created_at_utc=current.created_at_utc,
            revised_at_utc=self._clock(),
            value_provenance=self._combine_value_provenance((
                self._collection_value_provenance(current),
                self._combine_value_provenance((self._collection_value_provenance(branch),),
                                              tuple(o for o in outputs if o not in current.selected_outputs)),
            ), outputs),
        )
        return self._store.save_collection_revision(
            revised, expected_head_revision_id=current.revision_id,
            before_publish=self._collection_publication_gate(cancellation_requested, before_publish),
        )

    def advance_artifact_collection(
        self,
        collection_id: str,
        materialization: DataManagerArtifactMaterializationResult,
    ) -> ArtifactCollectionRevisionV1:
        if not isinstance(materialization, DataManagerArtifactMaterializationResult):
            raise TypeError(
                "materialization must be a DataManagerArtifactMaterializationResult"
            )
        current = self.load_artifact_collection(collection_id)
        if current.market_id != materialization.target_market_id:
            raise DataManagerCreationError(
                "materialization MarketId does not match Artifact Collection"
            )
        candidate = self._collection_revision_from_materialization(
            materialization,
            collection_id=current.collection_id,
            display_name=current.display_name,
            description=current.description,
            previous=current.revision_id,
            created_at=current.created_at_utc,
            revised_at=self._clock(),
            source_recipe_collection_id=current.source_recipe_collection_id,
            source_recipe_collection_revision_id=(
                current.source_recipe_collection_revision_id
            ),
            selected_outputs=current.selected_outputs,
        )
        if set(candidate.root_logical_artifact_ids) != set(
            current.root_logical_artifact_ids
        ):
            raise DataManagerCreationError("Artifact Collection roots cannot change")
        if set(candidate.support_logical_artifact_ids) != set(
            current.support_logical_artifact_ids
        ):
            raise DataManagerCreationError("Artifact Collection supports cannot change")
        if {item.version_key.logical_artifact_id for item in candidate.members} != {
            item.version_key.logical_artifact_id for item in current.members
        }:
            raise DataManagerCreationError("Artifact Collection member set cannot change")
        if candidate.dependency_edges != current.dependency_edges:
            raise DataManagerCreationError(
                "Artifact Collection dependency edges cannot change"
            )
        if candidate.selected_outputs != current.selected_outputs:
            raise DataManagerCreationError(
                "Artifact Collection selected outputs cannot change"
            )
        if candidate.presentation_order != current.presentation_order:
            raise DataManagerCreationError(
                "Artifact Collection presentation order cannot change"
            )
        if (
            candidate.source_recipe_collection_id
            != current.source_recipe_collection_id
            or candidate.source_recipe_collection_revision_id
            != current.source_recipe_collection_revision_id
        ):
            raise DataManagerCreationError(
                "Artifact Collection Recipe Collection references cannot change"
            )
        return self._store.save_collection_revision(
            candidate,
            expected_head_revision_id=current.revision_id,
        )

    def validate_artifact_collection(
        self, collection_id: str, revision_id: str | None = None
    ) -> ArtifactCollectionValidation:
        revision = self.load_artifact_collection(collection_id, revision_id)
        blockers: list[str] = []
        frames: dict[str, pd.DataFrame] = {}
        if hasattr(revision, "value_provenance"):
            value_provenance = revision.to_dict()["value_provenance"]
        else:
            by_id = {m.version_key.logical_artifact_id: m.version_key.artifact_id for m in revision.members}
            value_provenance = {
                "members": [member.to_dict() for member in revision.members],
                "dependency_edges": [{"dependency_artifact_id": by_id[edge.dependency_logical_artifact_id],
                                      "dependent_artifact_id": by_id[edge.dependent_logical_artifact_id],
                                      "role": edge.role, "output_name": edge.output_name}
                                     for edge in revision.dependency_edges],
            }
        for record in value_provenance["members"]:
            member = ArtifactCollectionMemberV1.from_dict(record)
            try:
                loaded = self._artifacts.load_artifact_by_id(
                    revision.market_id, member.version_key.artifact_id
                )
                metadata = loaded.metadata
                if metadata.values_sha256 != member.values_sha256:
                    blockers.append(f"Artifact payload changed: {member.version_key.logical_artifact_id}")
                if not self._same_coverage(metadata.source_ohlcv, revision.source_ohlcv):
                    blockers.append(f"Artifact source changed: {member.version_key.logical_artifact_id}")
                recorded_inputs = {
                    (edge["dependency_artifact_id"], edge["role"], edge["output_name"])
                    for edge in value_provenance["dependency_edges"]
                    if edge["dependent_artifact_id"] == member.version_key.artifact_id
                }
                if recorded_inputs != {(ref.artifact_id, ref.role, ref.output_name)
                                       for ref in metadata.recipe.source_artifacts}:
                    blockers.append(f"Artifact input provenance changed: {member.version_key.artifact_id}")
                frames[member.version_key.artifact_id] = loaded.frame
                if not hasattr(revision, "value_provenance"):
                    frames[member.version_key.logical_artifact_id] = loaded.frame
            except Exception as exc:
                blockers.append(f"Artifact unavailable {member.version_key.logical_artifact_id}: {exc}")
        first, last, rows = self._usable_coverage(revision, frames, blockers)
        return ArtifactCollectionValidation(
            revision.collection_id, revision.revision_id, not blockers, not blockers and rows > 0,
            tuple(dict.fromkeys(blockers)), first, last, rows,
            len(revision.selected_outputs),
        )

    def plan_batch_artifacts(self, request: BatchArtifactRequest) -> BatchArtifactPlan:
        if not isinstance(request, BatchArtifactRequest):
            raise TypeError("request must be a BatchArtifactRequest")
        if request.destination == "collection_revision":
            collection = self.load_artifact_collection(request.collection_id)
            if (
                collection.market_id != request.market_id
                or not self._same_coverage(collection.source_ohlcv, request.expected_source_ohlcv)
            ):
                raise DataManagerCreationError(
                    "Batch destination is incompatible with the selected MarketId "
                    "or OHLCV row count/timestamp range"
                )
        branch_recipes = self._validated_batch_recipes(request)
        try:
            materialization, _members = self._plan_batch_materialization(
                request, branch_recipes
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        return self._project_batch_plan(request, branch_recipes, materialization)

    def execute_batch_artifacts(
        self,
        plan: BatchArtifactPlan,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        collection_display_name: str = "Batch Artifact Collection",
    ) -> tuple[DataManagerArtifactMaterializationResult, ArtifactCollectionRevisionV1 | None]:
        if not isinstance(plan, BatchArtifactPlan) or plan.blocked:
            raise DataManagerCreationError("blocked batch plan cannot execute")
        cancelled = cancellation_requested or (lambda: False)
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Artifact validation")
        recipes = self._validated_batch_recipes(plan.request)
        try:
            materialization_plan, members = self._plan_batch_materialization(
                plan.request, recipes
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        if self._project_batch_plan(
            plan.request, recipes, materialization_plan
        ) != plan:
            raise DataManagerCreationError("batch Artifact graph changed before execution")
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Artifact publication")
        self._publish_portable_recipes(recipes)
        try:
            result = self._execute_batch_materialization(
                materialization_plan, members, progress=progress,
                cancellation_requested=cancelled, before_publish=None,
            )
        except (ArtifactError, KeyError, TypeError, ValueError) as exc:
            raise DataManagerCreationError(str(exc)) from exc
        if cancelled():
            raise DataManagerCreationError("batch cancelled before Collection mutation")
        collection = None
        selected_outputs = self._batch_collection_outputs(plan, recipes)
        if plan.request.destination == "new_collection":
            collection = self.create_artifact_collection(
                result,
                collection_display_name,
                selected_outputs=selected_outputs,
                progress=progress, cancellation_requested=cancelled,
            )
        elif plan.request.destination == "collection_revision":
            collection = self.add_collection_branches(
                plan.request.collection_id,
                result,
                selected_outputs=selected_outputs,
                progress=progress, cancellation_requested=cancelled,
            )
        return result, collection

    def assess_database_readiness(
        self, seed_id: str, collection_id: str, collection_revision_id: str | None = None
    ) -> DatabaseReadiness:
        seed = self._store.load_seed_metadata(seed_id)
        collection = self.load_artifact_collection(collection_id, collection_revision_id)
        blockers: list[str] = []
        validation = self.validate_artifact_collection(collection_id, collection.revision_id)
        blockers.extend(validation.blockers)
        if seed.market_id != collection.market_id:
            blockers.append("Seed and Artifact Collection MarketId differ")
        columns = ("ts_ms", *seed.selected_ohlcv_columns, *collection.presentation_order)
        if len(columns) != len(set(columns)):
            blockers.append("Database output-column collision")
        first = None
        last = None
        rows = 0
        warmup = 0
        if not blockers:
            try:
                frame, warmup = self._database_frame(seed, collection)
            except DataManagerCreationError as exc:
                blockers.append(str(exc))
            else:
                if frame.empty:
                    blockers.append("Database has no common usable rows")
                else:
                    first = int(frame["ts_ms"].iloc[0])
                    last = int(frame["ts_ms"].iloc[-1])
                    rows = len(frame)
        return DatabaseReadiness(
            seed.seed_id, collection.collection_id, collection.revision_id,
            not blockers, tuple(dict.fromkeys(blockers)), first, last, rows,
            len(columns), tuple(columns), warmup,
        )

    def build_database_revision(
        self,
        seed_id: str,
        collection_id: str,
        *,
        collection_revision_id: str | None = None,
        database_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> DatabaseRevisionManifestV3:
        cancelled = cancellation_requested or (lambda: False)
        seed = self._store.load_seed_metadata(seed_id)
        collection = self.load_artifact_collection(collection_id, collection_revision_id)
        readiness = self.assess_database_readiness(seed_id, collection_id, collection.revision_id)
        if not readiness.ready:
            raise DataManagerCreationError("Database is not ready: " + "; ".join(readiness.blockers))
        if cancelled():
            raise DataManagerCreationError("Database build cancelled before materialization")
        providers = self._collection_output_providers(collection)
        reviewed = {m.version_key.logical_artifact_id: m for m in collection.members}
        reviewed_edges = collection.dependency_edges
        value_provenance = self._collection_value_provenance(collection)
        collection_provenance = value_provenance
        frame, _warmup = self._database_frame(seed, collection, reviewed_members=reviewed)
        values = frame.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
        values_hash = sha256(values).hexdigest()
        exact_database_id = database_id or self._store.new_database_id()
        previous = None
        if database_id is not None:
            retained = self._store.read_trusted_database_revision(database_id)
            previous = retained.manifest.revision_id
            definition = self._store.load_database_definition(database_id)
            if definition.seed_id != seed.seed_id or definition.market_id != seed.market_id:
                raise DataManagerCreationError(
                    "Database definition cannot change Seed or MarketId"
                )
            self._require_database_build_preservation(
                retained, values, collection.selected_outputs
            )
            _old_members, _old_edges, old_outputs = self._database_output_evidence(retained.manifest)
            new_outputs = tuple(o for o in collection.selected_outputs if o not in old_outputs)
            value_provenance = self._combine_value_provenance((
                self._database_value_provenance(retained.manifest),
                self._combine_value_provenance((collection_provenance,), new_outputs),
            ), collection.selected_outputs)
        else:
            definition = DatabaseDefinitionV1(
                exact_database_id,
                seed.display_name if display_name is None else display_name,
                seed.description if description is None else description,
                seed.market_id,
                seed.seed_id,
                self._clock(),
            )
        now = self._clock()
        members = self._ordered_consumed_members(collection.members, reviewed)
        mapping = {item: item for item in readiness.column_names}
        payload = {
            "schema_version": "4.0", "object_type": "database_revision",
            "database_id": exact_database_id, "display_name": definition.display_name,
            "description": definition.description, "seed_id": seed.seed_id,
            "market_id": {"exchange": seed.market_id.exchange, "market_type": seed.market_id.market_type,
                          "symbol": seed.market_id.symbol, "timeframe": seed.market_id.timeframe},
            "source_ohlcv": seed.source_ohlcv.to_dict(),
            "members": [m.to_dict() for m in members],
            "dependency_edges": [e.to_dict() for e in reviewed_edges],
            "selected_outputs": [o.to_dict() for o in collection.selected_outputs],
            "collection_sources": [{"collection_id": collection.collection_id, "revision_id": collection.revision_id}],
            "selection_sources": [{"source_kind": "collection", "source_id": collection.collection_id,
                                   "source_revision_id": collection.revision_id,
                                   "column_names": sorted(o.column_name for o in collection.selected_outputs)}],
            "column_mapping": mapping, "first_timestamp_ms": readiness.first_usable_timestamp_ms,
            "last_timestamp_ms": readiness.last_usable_timestamp_ms,
            "row_count": readiness.row_count, "column_count": readiness.column_count,
            "values_sha256": values_hash, "previous_revision_id": previous,
            "created_at_utc": now.isoformat().replace("+00:00", "Z"),
            "value_provenance": value_provenance,
        }
        payload["revision_id"] = deterministic_hash(payload)
        manifest = DatabaseRevisionManifestV4.from_dict(payload)
        if cancelled():
            raise DataManagerCreationError("Database build cancelled before publication")

        def publication_gate() -> None:
            if cancelled():
                raise DataManagerCreationError("Database build cancelled before publication")
            if before_publish is not None:
                before_publish()
            current_collection = self.load_artifact_collection(collection.collection_id, collection.revision_id)
            if cancelled() or self._collection_value_provenance(current_collection) != collection_provenance:
                raise DataManagerCreationError("Database build cancelled or Artifact evidence changed")
            self._verify_collection_provenance(current_collection)
            for output in collection.selected_outputs:
                self._copy_output_slice(seed.market_id, providers[output.column_name], output, tuple(frame.ts_ms))

        return self._publish_database_revision(
            definition, manifest, values, expected_head_revision_id=previous,
            before_publish=publication_gate,
        )

    def _require_database_build_preservation(self, retained, values, outputs):
        old_columns, old_rows, old_axis = _snapshot_rows(
            retained.values_csv,
            nullable_columns=_database_nullable_columns(retained.manifest),
        )
        new_columns, new_rows, new_axis = _snapshot_rows(
            values, nullable_columns=tuple(output.column_name for output in outputs),
        )
        refusal = (
            "Database build must preserve the existing snapshot and retained content; "
            "use the reviewed Database append or content-edit operation"
        )
        if old_axis != new_axis or not set(old_columns) <= set(new_columns):
            raise DataManagerCreationError(refusal)
        positions = tuple(new_columns.index(column) for column in old_columns)
        if any(
            old != [new[position] for position in positions]
            for old, new in zip(old_rows, new_rows, strict=True)
        ):
            raise DataManagerCreationError(refusal)
        _members, _edges, old_outputs = self._database_output_evidence(retained.manifest)
        by_column = {output.column_name: output for output in outputs}
        if any(by_column.get(output.column_name) != output for output in old_outputs):
            raise DataManagerCreationError(refusal)

    def _review_output_members(self, market, outputs):
        members, _edges = self._review_content_output_evidence(market, outputs)
        return members

    def _ordered_consumed_members(self, previous, reviewed):
        order = dict.fromkeys((
            *(member.version_key.logical_artifact_id for member in previous),
            *reviewed,
        ))
        return tuple(reviewed[key] for key in order if key in reviewed)

    @staticmethod
    def _same_coverage(left, right):
        return (
            left.market_id, left.row_count, left.first_timestamp_ms, left.last_timestamp_ms
        ) == (
            right.market_id, right.row_count, right.first_timestamp_ms, right.last_timestamp_ms
        )

    @staticmethod
    def _require_coverage(market, row_count, first, last, source):
        if source.market_id != market:
            raise DataManagerCreationError("Artifact OHLCV identity differs from target")
        if source.row_count != row_count:
            raise DataManagerCreationError("Artifact row count differs from target; align snapshots and Artifacts before adding")
        if (source.first_timestamp_ms, source.last_timestamp_ms) != (first, last):
            raise DataManagerCreationError("Artifact first/last timestamps differ from target")

    def _capture_value_provenance(self, market, outputs, providers, first, last, *, verified_metadata=()):
        """Capture physical input history without requiring shared dependency versions."""
        if not outputs:
            return {"members": [], "dependency_edges": [], "outputs": []}
        owners = {}
        for summary in self._artifacts.list_managed_artifacts_metadata(market):
            for version in self._artifacts.list_artifact_versions(market, summary.logical_artifact_id):
                owner = owners.setdefault(version.artifact_id, version)
                if owner.logical_artifact_id != version.logical_artifact_id:
                    raise DataManagerCreationError("Artifact version ownership is ambiguous")
        members, edges, visiting, sources = {}, [], set(), {}
        verified = {item.artifact_id: item for item in verified_metadata}

        def collect(artifact_id):
            if artifact_id in visiting:
                raise DataManagerCreationError("Artifact provenance dependency cycle")
            if artifact_id in members:
                return
            record = owners.get(artifact_id)
            if record is None:
                raise DataManagerCreationError("Artifact dependency has no managed owner")
            visiting.add(artifact_id)
            metadata = self._artifacts.load_artifact_metadata(market, artifact_id)
            if verified.get(artifact_id) != metadata:
                metadata = self._artifacts.load_artifact_by_id(market, artifact_id).metadata
            sources[artifact_id] = metadata.source_ohlcv
            member = ArtifactCollectionMemberV1(
                ManagedArtifactVersionKey(record.logical_artifact_id, artifact_id),
                record.portable_recipe_id, metadata.recipe.tool_key, metadata.recipe.kind,
                metadata.recipe.output_names, metadata.values_sha256,
            )
            for ref in metadata.recipe.source_artifacts:
                collect(ref.artifact_id)
                if not self._same_coverage(sources[ref.artifact_id], metadata.source_ohlcv):
                    raise DataManagerCreationError("Artifact dependency coverage differs from its dependent")
                if ref.output_name not in members[ref.artifact_id]["output_names"]:
                    raise DataManagerCreationError("Artifact dependency output is unavailable")
                edges.append({"dependency_artifact_id": ref.artifact_id,
                              "dependent_artifact_id": artifact_id,
                              "role": ref.role, "output_name": ref.output_name})
            members[artifact_id] = member.to_dict()
            visiting.remove(artifact_id)

        bindings = []
        for output in outputs:
            member = providers[output.column_name]
            artifact_id = member.version_key.artifact_id
            collect(artifact_id)
            if members[artifact_id] != member.to_dict():
                raise DataManagerCreationError("Artifact differs from captured value provenance")
            bindings.append({"column_name": output.column_name,
                             "logical_artifact_id": output.logical_artifact_id,
                             "output_name": output.output_name, "artifact_id": artifact_id,
                             "first_timestamp_ms": first, "last_timestamp_ms": last})
        return self._combine_value_provenance(
            ({"members": list(members.values()), "dependency_edges": edges, "outputs": bindings},),
            outputs,
        )

    @staticmethod
    def _combine_value_provenance(parts, outputs, *, selection_sources=()):
        selected = {o.column_name: o for o in outputs}
        members, edges, bindings, legacy_revisions = {}, {}, [], {}
        for part in parts:
            for record in part.get("legacy_revisions", ()):
                previous = legacy_revisions.setdefault(record["revision_id"], dict(record))
                if previous != dict(record):
                    raise DataManagerCreationError("Captured legacy provenance disagrees with itself")
            for member in part["members"]:
                previous = members.setdefault(member["artifact_id"], dict(member))
                if previous != dict(member):
                    raise DataManagerCreationError("Physical Artifact provenance disagrees with itself")
            for edge in part["dependency_edges"]:
                key = (edge["dependency_artifact_id"], edge["dependent_artifact_id"], edge["role"], edge["output_name"])
                edges[key] = dict(edge)
            bindings.extend(dict(b) for b in part["outputs"]
                            if b["column_name"] in selected
                            and b["output_name"] == selected[b["column_name"]].output_name
                            and (isinstance(selected[b["column_name"]], DatabaseLegacyOutputV1)
                                 or b.get("logical_artifact_id") == selected[b["column_name"]].logical_artifact_id))
        needed = {b["artifact_id"] for b in bindings if "artifact_id" in b}
        pending = list(needed)
        while pending:
            dependent = pending.pop()
            for edge in edges.values():
                dependency = edge["dependency_artifact_id"]
                if edge["dependent_artifact_id"] == dependent and dependency not in needed:
                    needed.add(dependency)
                    pending.append(dependency)
        combined = {
            "members": [members[key] for key in sorted(needed)],
            "dependency_edges": [edges[key] for key in sorted(edges) if key[1] in needed],
            "outputs": sorted(bindings, key=lambda b: (b["column_name"], b["first_timestamp_ms"], b["last_timestamp_ms"])),
        }
        needed_legacy = {b["legacy_revision_id"] for b in bindings if "legacy_revision_id" in b}
        needed_legacy.update(source["source_revision_id"] for source in selection_sources
                             if source["source_kind"] == "legacy_snapshot")
        if needed_legacy:
            combined["legacy_revisions"] = [legacy_revisions[key] for key in sorted(needed_legacy)]
        return combined

    def _collection_value_provenance(self, collection):
        if hasattr(collection, "value_provenance"):
            return collection.to_dict()["value_provenance"]
        by_id = {m.version_key.logical_artifact_id: m for m in collection.members}
        providers = {o.column_name: by_id[o.logical_artifact_id] for o in collection.selected_outputs}
        return self._capture_value_provenance(collection.market_id, collection.selected_outputs,
                                              providers, collection.first_timestamp_ms, collection.last_timestamp_ms)

    def _collection_output_providers(self, collection):
        provenance = self._collection_value_provenance(collection)
        members = {m["artifact_id"]: ArtifactCollectionMemberV1.from_dict(m) for m in provenance["members"]}
        return {b["column_name"]: members[b["artifact_id"]] for b in provenance["outputs"]}

    def _verify_collection_provenance(self, collection):
        recorded = self._collection_value_provenance(collection)
        actual = self._capture_value_provenance(
            collection.market_id, collection.selected_outputs, self._collection_output_providers(collection),
            collection.first_timestamp_ms, collection.last_timestamp_ms,
        )
        if actual != recorded:
            raise DataManagerCreationError("Collection physical provenance disagrees with its Artifacts")

    def _database_value_provenance(self, manifest):
        if hasattr(manifest, "value_provenance"):
            return manifest.to_dict()["value_provenance"]
        _members, _edges, outputs = self._database_output_evidence(manifest)
        # A legacy snapshot proves its own saved claims, not exact physical
        # history that it did not capture. Never reload or relabel its providers.
        result = {"members": [], "dependency_edges": [], "outputs": []}
        if outputs:
            result["legacy_revisions"] = [manifest.to_dict()]
            result["outputs"] = [{**output.to_dict(), "legacy_revision_id": manifest.revision_id,
                                  "first_timestamp_ms": manifest.first_timestamp_ms,
                                  "last_timestamp_ms": manifest.last_timestamp_ms}
                                 for output in outputs]
        return result

    def _copy_output_slice(self, market, member, output, timestamps, *, target_coverage=None):
        loaded = self._artifacts.load_artifact_by_id(market, member.version_key.artifact_id)
        if loaded.metadata.values_sha256 != member.values_sha256:
            raise DataManagerCreationError("reviewed Artifact payload hash changed")
        frame = loaded.frame
        expected = (len(timestamps), timestamps[0], timestamps[-1]) if target_coverage is None else target_coverage
        self._require_coverage(market, *expected, loaded.metadata.source_ohlcv)
        if output.output_name not in frame or frame["ts_ms"].duplicated().any():
            raise DataManagerCreationError("Artifact output or unique timestamps unavailable")
        indexed = frame.set_index("ts_ms")
        if any(ts not in indexed.index for ts in timestamps):
            raise DataManagerCreationError("Artifact does not cover every Database timestamp")
        selected = indexed.loc[list(timestamps), output.output_name]
        # Only new values are serialized; retained Database tokens never enter pandas.
        text = selected.to_frame().to_csv(index=False, header=False, lineterminator="\n", float_format="%.17g")
        tokens = [row[0] for row in csv.reader(StringIO(text))]
        if len(tokens) != len(timestamps):
            raise DataManagerCreationError("Artifact slice row count disagrees")
        return tokens

    def _review_content_output_evidence(self, market, outputs):
        roots = tuple(
            dict.fromkeys(output.logical_artifact_id for output in outputs)
        )
        if not roots:
            return {}, ()

        owner_by_artifact = {}
        summaries = {}
        for summary in self._artifacts.list_managed_artifacts_metadata(market):
            previous = summaries.setdefault(summary.logical_artifact_id, summary)
            if previous != summary:
                raise DataManagerCreationError(
                    "managed Artifact logical identity is ambiguous"
                )
            for version in self._artifacts.list_artifact_versions(
                market, summary.logical_artifact_id
            ):
                owner = owner_by_artifact.setdefault(
                    version.artifact_id, summary.logical_artifact_id
                )
                if owner != summary.logical_artifact_id:
                    raise DataManagerCreationError(
                        "Artifact version ownership is ambiguous"
                    )

        members = {}
        selected_versions = {}
        edges = []
        visiting = set()
        root_versions = {logical_id: self._artifacts.load_artifact_head(market, logical_id).artifact_id
                         for logical_id in roots if logical_id in summaries and summaries[logical_id].valid}

        def collect(logical_id, artifact_id):
            artifact_id = root_versions.get(logical_id, artifact_id)
            previous = selected_versions.get(logical_id)
            if previous is not None:
                return
            if logical_id in visiting:
                raise DataManagerCreationError(
                    "content edit Artifact dependency graph contains a cycle"
                )
            if owner_by_artifact.get(artifact_id) != logical_id:
                raise DataManagerCreationError(
                    "content edit Artifact version has no exact managed owner"
                )
            visiting.add(logical_id)
            loaded = self._artifacts.load_artifact_by_id(market, artifact_id)
            record = self._artifacts.load_artifact_version(
                market, logical_id, artifact_id
            )
            metadata = loaded.metadata
            if metadata.artifact_id != artifact_id:
                raise DataManagerCreationError(
                    "content edit Artifact metadata identity disagrees"
                )
            member = ArtifactCollectionMemberV1(
                ManagedArtifactVersionKey(logical_id, artifact_id),
                record.portable_recipe_id,
                metadata.recipe.tool_key,
                metadata.recipe.kind,
                metadata.recipe.output_names,
                metadata.values_sha256,
            )
            selected_versions[logical_id] = artifact_id
            members[logical_id] = member
            for ref in metadata.recipe.source_artifacts:
                dependency_id = owner_by_artifact.get(ref.artifact_id)
                if dependency_id is None:
                    raise DataManagerCreationError(
                        "content edit dependency has no managed owner"
                    )
                collect(dependency_id, ref.artifact_id)
                if ref.output_name not in members[dependency_id].output_names:
                    raise DataManagerCreationError(
                        "content edit dependency output is unavailable"
                    )
                edge = ArtifactCollectionDependencyV1(
                    dependency_id,
                    logical_id,
                    ref.role,
                    ref.output_name,
                )
                if edge not in edges:
                    edges.append(edge)
            visiting.remove(logical_id)

        for logical_id in roots:
            summary = summaries.get(logical_id)
            if summary is None or not summary.valid:
                raise DataManagerCreationError(
                    "content edit root managed Artifact is unavailable"
                )
            head = self._artifacts.load_artifact_head(market, logical_id)
            collect(logical_id, head.artifact_id)

        for output in outputs:
            member = members.get(output.logical_artifact_id)
            if member is None or output.output_name not in member.output_names:
                raise DataManagerCreationError(
                    "reviewed Artifact output is unavailable"
                )
        return members, tuple(edges)

    def _database_output_evidence(self, manifest):
        if not isinstance(manifest, DatabaseRevisionManifestV1):
            return manifest.members, manifest.dependency_edges, manifest.selected_outputs
        derived = {(original, column) for original, column in manifest.column_mapping.items()
                   if column not in {"ts_ms", "open", "high", "low", "close", "volume"}}
        captured = set(zip(manifest.artifact_version_keys, manifest.artifact_payload_hashes, strict=True))
        cursor, seen = manifest, {manifest.revision_id}
        while cursor.previous_revision_id is not None:
            cursor = self._store.load_database_manifest(manifest.database_id, cursor.previous_revision_id)
            if cursor.revision_id in seen:
                raise DataManagerCreationError("Database revision history cycle")
            seen.add(cursor.revision_id)
            if isinstance(cursor, DatabaseRevisionManifestV1):
                continue
            # Reuse only claims already proved by this Database's identical saved
            # payload and captured inputs. No external provider is consulted.
            if (cursor.market_id == manifest.market_id
                    and cursor.values_sha256 == manifest.values_sha256
                    and (cursor.row_count, cursor.first_timestamp_ms, cursor.last_timestamp_ms)
                    == (manifest.row_count, manifest.first_timestamp_ms, manifest.last_timestamp_ms)
                    and {(o.output_name, o.column_name) for o in cursor.selected_outputs} == derived
                    and all(isinstance(o, ArtifactCollectionOutputV1) for o in cursor.selected_outputs)
                    and {(m.version_key, m.values_sha256) for m in cursor.members} == captured
                    and set(cursor.portable_recipe_ids) == set(manifest.portable_recipe_ids)):
                return cursor.members, cursor.dependency_edges, cursor.selected_outputs
        outputs = tuple(
            DatabaseLegacyOutputV1(column, original, manifest.revision_id)
            for original, column in manifest.column_mapping.items()
            if column not in {"ts_ms", "open", "high", "low", "close", "volume"}
        )
        return (), (), outputs

    def _database_append_outputs(self, manifest, outputs):
        """Resolve future providers without changing a snapshot's historical claims."""
        resolved = []
        provenance = self._database_value_provenance(manifest)
        captures = {record["revision_id"]: record for record in provenance.get("legacy_revisions", ())}
        for output in outputs:
            if not isinstance(output, DatabaseLegacyOutputV1):
                resolved.append(output)
                continue
            # Validated exact suffixes agree on one provider for this saved column.
            provider = next((segment["logical_artifact_id"] for segment in provenance["outputs"]
                             if "artifact_id" in segment and segment["column_name"] == output.column_name
                             and segment["output_name"] == output.output_name), None)
            if provider is not None:
                resolved.append(ArtifactCollectionOutputV1(provider, output.output_name, output.column_name))
                continue
            captured = database_revision_from_dict(captures[output.legacy_revision_id])
            candidates = []
            # Every captured candidate must be accounted for: a missing candidate
            # could provide the same output name as the sole surviving Artifact.
            for key in captured.artifact_version_keys:
                try:
                    head = self._artifacts.load_artifact_head(manifest.market_id, key.logical_artifact_id)
                    metadata = self._artifacts.load_artifact_metadata(manifest.market_id, head.artifact_id)
                except ArtifactError as exc:
                    raise DataManagerCreationError(
                        f"Saved column {output.column_name}: original provider is unprovable; "
                        "remove this column or recreate the captured Artifacts and plan again"
                    ) from exc
                if output.output_name in metadata.recipe.output_names:
                    candidates.append(key.logical_artifact_id)
            if len(candidates) != 1:
                raise DataManagerCreationError(
                    f"Saved column {output.column_name}: original provider is ambiguous; "
                    "remove this column or restore provable inputs and plan again"
                )
            resolved.append(ArtifactCollectionOutputV1(candidates[0], output.output_name, output.column_name))
        return tuple(resolved)

    def _database_selection_sources(self, manifest):
        if isinstance(manifest, DatabaseRevisionManifestV3):
            return tuple(dict(item) for item in manifest.selection_sources)
        chain, seen = [], set()
        cursor = manifest
        while True:
            if cursor.revision_id in seen:
                raise DataManagerCreationError("Database revision history cycle")
            seen.add(cursor.revision_id)
            chain.append(cursor)
            if cursor.previous_revision_id is None:
                break
            cursor = self._store.load_database_manifest(cursor.database_id, cursor.previous_revision_id)
        legacy_identities = {
            revision.revision_id: {key.logical_artifact_id for key in revision.artifact_version_keys}
            for revision in chain if isinstance(revision, DatabaseRevisionManifestV1)
        }
        ownership, old_outputs = {}, {}
        old_refs = set()
        for revision in reversed(chain):
            _members, _edges, outputs = self._database_output_evidence(revision)
            by_column = {o.column_name: o for o in outputs}
            if isinstance(revision, DatabaseRevisionManifestV3):
                ownership = {(s["source_kind"], s["source_id"], s["source_revision_id"]): set(s["column_names"])
                             for s in revision.selection_sources}
                refs = {(r.collection_id, r.revision_id) for r in revision.collection_sources}
            elif isinstance(revision, DatabaseRevisionManifestV1):
                refs = {(revision.collection_id, revision.collection_revision_id)}
                ownership = {("collection", revision.collection_id, revision.collection_revision_id): set(by_column)}
            else:
                refs = {(r.collection_id, r.revision_id) for r in revision.collection_sources}
                # Only a saved identical binding preserves a known previous owner.
                for key in ownership:
                    ownership[key].intersection_update(
                        column for column, output in by_column.items()
                        if output == old_outputs.get(column)
                        or (isinstance(old_outputs.get(column), DatabaseLegacyOutputV1)
                            and output.output_name == old_outputs[column].output_name
                            and output.logical_artifact_id in legacy_identities[old_outputs[column].legacy_revision_id])
                    )
                assigned = set().union(*ownership.values()) if ownership else set()
                for column in set(by_column) - assigned:
                    output = by_column[column]
                    if refs - old_refs or any(key[0] == "legacy_snapshot" for key in ownership):
                        key = ("legacy_snapshot", manifest.database_id, manifest.revision_id)
                    else:
                        key = ("artifact", output.logical_artifact_id, None)
                    ownership.setdefault(key, set()).add(column)
            old_outputs, old_refs = by_column, refs
        # Unresolved ownership is captured by the current original snapshot; no
        # live Collection lookup and no guessed relationship to a surviving one.
        unresolved = set()
        for key in tuple(ownership):
            if key[0] == "legacy_snapshot":
                unresolved.update(ownership.pop(key))
        if unresolved:
            ownership[("legacy_snapshot", manifest.database_id, manifest.revision_id)] = unresolved
        return tuple(
            {"source_kind": key[0], "source_id": key[1], "source_revision_id": key[2],
             "column_names": tuple(sorted(names))}
            for key, names in sorted(ownership.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or ""))
            if names
        )

    def _merge_consumed_content_evidence(
        self, members, edges, reviewed_members, reviewed_edges, new_outputs
    ):
        if not new_outputs:
            return members, edges
        required = {output.logical_artifact_id for output in new_outputs}
        pending = list(required)
        while pending:
            dependent = pending.pop()
            for edge in reviewed_edges:
                dependency = edge.dependency_logical_artifact_id
                if edge.dependent_logical_artifact_id == dependent and dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        combined = {member.version_key.logical_artifact_id: member for member in members}
        for logical_id in sorted(required):
            member = reviewed_members[logical_id]
            # New schemas bind physical value providers per column, not through this
            # one-per-logical selection projection. Never relabel retained members.
            combined.setdefault(logical_id, member)
        consumed_edges = tuple(
            edge for edge in reviewed_edges
            if edge.dependent_logical_artifact_id in required
        )
        return tuple(combined.values()), tuple(dict.fromkeys((*edges, *consumed_edges)))

    def plan_database_content_edit(
        self, database_id, *, artifact_additions=(), collection_additions=(),
        remove_sources=(), remove_outputs=(), remove_columns=(),
    ):
        loaded = self._store.read_trusted_database_revision(database_id)
        manifest = loaded.manifest
        columns, rows, timestamps = _snapshot_rows(
            loaded.values_csv, nullable_columns=_database_nullable_columns(manifest)
        )
        members, edges, old_outputs = self._database_output_evidence(manifest)
        old_provenance = self._database_value_provenance(manifest)
        old_sources = self._database_selection_sources(manifest)
        direct = tuple(artifact_additions)
        captures = tuple(collection_additions)
        removals = tuple(tuple(key) for key in remove_sources)
        removed_outputs = tuple(tuple(key) for key in remove_outputs)
        column_removals = tuple(remove_columns)
        if (len(column_removals) != len(set(column_removals))
                or any(column not in {o.column_name for o in old_outputs} for column in column_removals)):
            raise DataManagerCreationError("remove_columns must name unique existing derived columns")

        for key in removals:
            if len(key) != 3:
                raise DataManagerCreationError(
                    "captured source key must have three fields"
                )
        for key in removed_outputs:
            if len(key) != 2:
                raise DataManagerCreationError(
                    "removed output key must have two fields"
                )

        for logical_id, name in removed_outputs:
            if any(isinstance(o, DatabaseLegacyOutputV1) and o.output_name == name for o in old_outputs):
                raise DataManagerCreationError("legacy output binding is unprovable; remove the saved column by name")

        incoming = [
            (output, ("artifact", output.logical_artifact_id, None))
            for output in direct
        ]
        captured = {}
        incoming_providers = {}
        reviewed_members, reviewed_edges = self._review_content_output_evidence(manifest.market_id, direct)
        for output in direct:
            incoming_providers[output.column_name] = reviewed_members[output.logical_artifact_id]
        for reference in captures:
            collection = self.load_artifact_collection(
                reference.collection_id, reference.revision_id
            )
            if collection.market_id != manifest.market_id:
                raise DataManagerCreationError(
                    "Collection MarketId differs from Database"
                )
            self._require_coverage(manifest.market_id, len(timestamps), timestamps[0], timestamps[-1], collection.source_ohlcv)
            self._verify_collection_provenance(collection)
            collection_providers = self._collection_output_providers(collection)
            for output in collection.selected_outputs:
                incoming_providers.setdefault(output.column_name, collection_providers[output.column_name])
            for member in collection.members:
                reviewed_members.setdefault(member.version_key.logical_artifact_id, member)
            reviewed_edges = tuple(dict.fromkeys((*reviewed_edges, *collection.dependency_edges)))
            captured[(reference.collection_id, reference.revision_id)] = collection
            incoming.extend(
                (
                    output,
                    (
                        "collection",
                        reference.collection_id,
                        reference.revision_id,
                    ),
                )
                for output in collection.selected_outputs
            )

        incoming_output_keys = {
            (output.logical_artifact_id, output.output_name)
            for output, _owner in incoming
        }
        if (incoming_output_keys & set(removed_outputs)
                or {output.column_name for output, _owner in incoming} & set(column_removals)):
            raise DataManagerCreationError(
                "contradictory add/remove output intent"
            )
        if {owner for _output, owner in incoming} & set(removals):
            raise DataManagerCreationError(
                "contradictory add/remove source intent"
            )

        owners = {
            (
                source["source_kind"],
                source["source_id"],
                source["source_revision_id"],
            ): set(source["column_names"])
            for source in old_sources
        }
        for key in removals:
            owners.pop(key, None)

        for output in old_outputs:
            if ((output.logical_artifact_id, output.output_name) in removed_outputs
                    or output.column_name in column_removals):
                for names in owners.values():
                    names.discard(output.column_name)

        retained_names = set().union(*owners.values()) if owners else set()
        output_by_key = {
            (output.logical_artifact_id, output.output_name): output
            for output in old_outputs
            if output.column_name in retained_names
        }
        existing_by_key = {
            (output.logical_artifact_id, output.output_name): output
            for output in old_outputs
        }
        new_outputs = []
        blockers = []

        for output, owner in incoming:
            key = (output.logical_artifact_id, output.output_name)
            existing = output_by_key.get(key) or existing_by_key.get(key)
            effective = existing or output
            if existing and output.column_name != existing.column_name:
                blockers.append(
                    f"existing output mapping differs for {output.output_name}"
                )
                continue
            if not existing and (
                output.column_name in columns
                or any(
                    candidate.column_name == output.column_name
                    and (
                        candidate.logical_artifact_id,
                        candidate.output_name,
                    ) != key
                    for candidate in new_outputs
                )
            ):
                blockers.append(
                    f"Database output column collision: {output.column_name}"
                )
                continue
            owners.setdefault(owner, set()).add(effective.column_name)
            output_by_key[key] = effective
            if key not in existing_by_key and effective not in new_outputs:
                new_outputs.append(effective)

        new_outputs.sort(
            key=lambda output: (
                output.logical_artifact_id,
                output.output_name,
                output.column_name,
            )
        )
        final_sources = tuple(
            {
                "source_kind": key[0],
                "source_id": key[1],
                "source_revision_id": key[2],
                "column_names": tuple(sorted(names)),
            }
            for key, names in sorted(
                owners.items(),
                key=lambda item: (
                    item[0][0], item[0][1], item[0][2] or ""
                ),
            )
            if names
        )
        names = {output.column_name for output in output_by_key.values()}
        removed_columns = tuple(
            output.column_name
            for output in old_outputs
            if output.column_name not in names
        )
        retained_columns = tuple(
            column for column in columns if column not in removed_columns
        )
        final_columns = (
            *retained_columns,
            *(output.column_name for output in new_outputs),
        )

        slices = {}
        for output, _owner in incoming:
            try:
                loaded_input = self._artifacts.load_artifact_by_id(manifest.market_id, incoming_providers[output.column_name].version_key.artifact_id)
                self._require_coverage(manifest.market_id, len(timestamps), timestamps[0], timestamps[-1], loaded_input.metadata.source_ohlcv)
            except (ArtifactError, DataManagerCreationError) as exc:
                blockers.append(str(exc))
        if not blockers:
            for output in new_outputs:
                try:
                    slices[output.column_name] = self._copy_output_slice(
                        manifest.market_id,
                        incoming_providers[output.column_name],
                        output,
                        timestamps,
                    )
                except DataManagerCreationError as exc:
                    blockers.append(str(exc))

        if not blockers:
            try:
                final_members, final_edges = self._merge_consumed_content_evidence(
                    members, edges, reviewed_members, reviewed_edges, new_outputs
                )
            except DataManagerCreationError as exc:
                blockers.append(str(exc))

        if blockers:
            final_sources = old_sources
            final_columns = tuple(columns)
            removed_columns = ()
            new_outputs = []
            output_by_key = {
                (output.logical_artifact_id, output.output_name): output
                for output in old_outputs
            }
            values = loaded.values_csv
            ownership_changed = False
            final_members = members
            final_edges = edges
        else:
            result = StringIO(newline="")
            writer = csv.writer(result, lineterminator="\n")
            writer.writerow(final_columns)
            indices = [columns.index(column) for column in retained_columns]
            for index, row in enumerate(rows):
                writer.writerow(
                    [row[position] for position in indices]
                    + [
                        slices[output.column_name][index]
                        for output in new_outputs
                    ]
                )
            values = result.getvalue().encode("utf-8")
            if not new_outputs and not removed_columns:
                values = loaded.values_csv

            ownership_changed = sorted(
                (
                    source["source_kind"],
                    source["source_id"],
                    source["source_revision_id"] or "",
                    tuple(source["column_names"]),
                )
                for source in old_sources
            ) != sorted(
                (
                    source["source_kind"],
                    source["source_id"],
                    source["source_revision_id"] or "",
                    tuple(source["column_names"]),
                )
                for source in final_sources
            )

        final_outputs = tuple(
            sorted(
                output_by_key.values(),
                key=lambda output: final_columns.index(output.column_name),
            )
        )
        new_provenance = self._capture_value_provenance(
            manifest.market_id, tuple(new_outputs), incoming_providers, timestamps[0], timestamps[-1]
        ) if not blockers else {"members": [], "dependency_edges": [], "outputs": []}
        final_provenance = self._combine_value_provenance(
            (old_provenance, new_provenance), final_outputs, selection_sources=final_sources
        )
        if not final_outputs:
            final_members, final_edges = (), ()
        payload = {
            "database": database_id,
            "head": manifest.revision_id,
            "members": [
                member.to_dict()
                for member in sorted(
                    reviewed_members.values(),
                    key=lambda item: item.version_key.logical_artifact_id,
                )
            ],
            "values": sha256(values).hexdigest(),
            "sources": final_sources,
            "outputs": [output.to_dict() for output in final_outputs],
            "intent": {
                "direct": [output.to_dict() for output in direct],
                "collections": [reference.to_dict() for reference in captures],
                "remove_sources": removals,
                "remove_outputs": removed_outputs,
                "remove_columns": column_removals,
            },
            "blockers": blockers,
            "value_provenance": final_provenance,
        }
        return DatabaseContentEditPlan(
            deterministic_hash(payload),
            database_id,
            manifest.revision_id,
            manifest.market_id,
            manifest.source_ohlcv,
            direct,
            captures,
            removals,
            removed_outputs,
            tuple(
                sorted(
                    reviewed_members.values(),
                    key=lambda item: item.version_key.logical_artifact_id,
                )
            ),
            final_members,
            final_edges,
            final_outputs,
            final_sources,
            values,
            tuple(final_columns),
            tuple(output.column_name for output in new_outputs),
            tuple(removed_columns),
            ownership_changed,
            tuple(dict.fromkeys(blockers)),
            value_provenance=final_provenance,
            remove_columns=column_removals,
        )

    def execute_database_content_edit(
        self, plan, *, cancellation_requested=None, before_publish=None
    ):
        if not isinstance(plan, DatabaseContentEditPlan):
            raise TypeError("plan must be a DatabaseContentEditPlan")
        cancelled = cancellation_requested or (lambda: False)

        def verify():
            if cancelled():
                raise DataManagerCreationError(
                    "Database content edit cancelled"
                )
            current = self._store.load_database_manifest(plan.database_id)
            if current.revision_id != plan.starting_revision_id:
                raise DataManagerCreationError(
                    "Database content edit changed after Preview"
                )
            fresh = self.plan_database_content_edit(
                plan.database_id, artifact_additions=plan.artifact_additions,
                collection_additions=plan.collection_additions,
                remove_sources=plan.remove_sources, remove_outputs=plan.remove_outputs,
                remove_columns=plan.remove_columns,
            )
            if fresh != plan:
                raise DataManagerCreationError("Artifact or Database content changed after Preview")

        verify()
        if plan.blocked:
            raise DataManagerCreationError(
                "blocked Database content edit: " + "; ".join(plan.blockers)
            )
        if plan.no_op:
            return None
        current = self._store.load_database_manifest(plan.database_id)
        manifest = self._database_v3_manifest(
            current,
            plan.values_csv,
            plan.members,
            plan.dependency_edges,
            plan.selected_outputs,
            plan.selection_sources,
            value_provenance=plan.value_provenance,
        )

        def publication_gate():
            if before_publish is not None:
                before_publish()
            verify()

        return self._publish_database_revision(
            self.load_database_definition(plan.database_id),
            manifest,
            plan.values_csv,
            expected_head_revision_id=plan.starting_revision_id,
            before_publish=publication_gate,
        )

    def _publish_database_revision(self, definition, manifest, values_csv, *,
                                   expected_head_revision_id, before_publish=None):
        from .utc_classification_snapshot import _capture_snapshot, _utc_segments

        previous = (self._store.load_database_revision(manifest.database_id, manifest.previous_revision_id)
                    if manifest.previous_revision_id is not None and _utc_segments(manifest) else None)
        revised, classification = _capture_snapshot(manifest, self._artifacts, previous)

        def publication_gate():
            if before_publish is not None:
                before_publish()
            checked, checked_payload = _capture_snapshot(manifest, self._artifacts, previous)
            if checked != revised or checked_payload != classification:
                raise DataManagerCreationError("UTC provider evidence changed before publication")

        return self._store.publish_database_revision(
            definition, revised, values_csv, expected_head_revision_id=expected_head_revision_id,
            utc_classification=classification, before_publish=publication_gate,
        )

    def _database_v3_manifest(self, previous, values, members, edges, outputs, sources, *, value_provenance=None):
        columns, rows, timestamps = _snapshot_rows(
            values, nullable_columns=tuple(output.column_name for output in outputs)
        )
        references = sorted({(s["source_id"], s["source_revision_id"]) for s in sources if s["source_kind"] == "collection"})
        legacy_claims = (any(isinstance(o, DatabaseLegacyOutputV1) for o in outputs)
                         or any(s["source_kind"] == "legacy_snapshot" for s in sources))
        payload = {
            "schema_version": "5.0" if legacy_claims else "4.0", "object_type": "database_revision",
            "database_id": previous.database_id, "display_name": previous.display_name,
            "description": previous.description, "seed_id": previous.seed_id,
            "market_id": {"exchange": previous.market_id.exchange, "market_type": previous.market_id.market_type,
                          "symbol": previous.market_id.symbol, "timeframe": previous.market_id.timeframe},
            "source_ohlcv": previous.source_ohlcv.to_dict(),
            "members": [m.to_dict() for m in members], "dependency_edges": [e.to_dict() for e in edges],
            "selected_outputs": [o.to_dict() for o in outputs],
            "selection_sources": [dict(s) for s in sources],
            "collection_sources": [{"collection_id": identity, "revision_id": revision} for identity, revision in references],
            "column_mapping": {c:c for c in columns}, "row_count": len(rows), "column_count": len(columns),
            "first_timestamp_ms": timestamps[0], "last_timestamp_ms": timestamps[-1],
            "values_sha256": sha256(values).hexdigest(), "previous_revision_id": previous.revision_id,
            "created_at_utc": self._clock().isoformat().replace("+00:00", "Z"),
            "value_provenance": value_provenance,
        }
        payload["revision_id"] = deterministic_hash(payload)
        return database_revision_from_dict(payload)

    def plan_database_content_addition(self, database_id, selection, *, selected_outputs, source_kind, source_collection=None):
        if source_kind == "collection":
            return self.plan_database_content_edit(database_id, collection_additions=(source_collection,))
        return self.plan_database_content_edit(database_id, artifact_additions=tuple(selected_outputs))

    def execute_database_content_addition(self, plan, **execution):
        return self.execute_database_content_edit(plan, **execution)

    def _database_v2_content(
        self, manifest: DatabaseRevisionManifest
    ) -> tuple[
        tuple[ArtifactCollectionMemberV1, ...],
        tuple[ArtifactCollectionDependencyV1, ...],
        tuple[ArtifactCollectionOutputV1, ...],
        tuple[DatabaseCollectionReferenceV2, ...],
    ]:
        if isinstance(manifest, (DatabaseRevisionManifestV2, DatabaseRevisionManifestV3)):
            return (
                manifest.members,
                manifest.dependency_edges,
                manifest.selected_outputs,
                manifest.collection_sources,
            )
        collection = self.load_artifact_collection(
            manifest.collection_id, manifest.collection_revision_id
        )
        if (
            tuple(item.version_key for item in collection.members)
            != manifest.artifact_version_keys
            or tuple(item.values_sha256 for item in collection.members)
            != manifest.artifact_payload_hashes
            or collection.source_portable_recipe_ids != manifest.portable_recipe_ids
            or collection.source_ohlcv != manifest.source_ohlcv
        ):
            raise DataManagerCreationError(
                "V1 Database content does not match its exact Artifact Collection"
            )
        return (
            collection.members,
            collection.dependency_edges,
            collection.selected_outputs,
            (DatabaseCollectionReferenceV2(
                collection.collection_id, collection.revision_id
            ),),
        )

    @staticmethod
    def _read_database_values(values_csv: bytes) -> pd.DataFrame:
        try:
            frame = pd.read_csv(StringIO(values_csv.decode("utf-8")))
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise DataManagerCreationError("Database values payload is invalid") from exc
        if frame.empty or "ts_ms" not in frame.columns:
            raise DataManagerCreationError("Database values payload is empty or invalid")
        if frame["ts_ms"].isna().any() or frame["ts_ms"].duplicated().any():
            raise DataManagerCreationError("Database timestamps are invalid")
        return frame

    def _materialize_database_content(
        self,
        frame: pd.DataFrame,
        source_ohlcv,
        additions: tuple[ArtifactCollectionOutputV1, ...],
        member_by_id: Mapping[str, ArtifactCollectionMemberV1],
    ) -> pd.DataFrame:
        result = frame.copy()
        loaded_by_artifact: dict[str, object] = {}
        for output in additions:
            member = member_by_id[output.logical_artifact_id]
            artifact_id = member.version_key.artifact_id
            loaded = loaded_by_artifact.get(artifact_id)
            if loaded is None:
                loaded = self._artifacts.load_artifact_by_id(
                    source_ohlcv.market_id, artifact_id
                )
                if (
                    loaded.metadata.values_sha256 != member.values_sha256
                    or loaded.metadata.source_ohlcv != source_ohlcv
                ):
                    raise DataManagerCreationError(
                        "selected Artifact does not match persisted Database content truth"
                    )
                loaded_by_artifact[artifact_id] = loaded
            if output.output_name not in loaded.frame.columns:
                raise DataManagerCreationError(
                    "selected Artifact output is not persisted"
                )
            values = loaded.frame.loc[:, ["ts_ms", output.output_name]].rename(
                columns={output.output_name: output.column_name}
            )
            result = result.merge(values, on="ts_ms", how="left", validate="one_to_one")
        return result

    def delete_database(self, database_id, *, before_delete=None):
        return self._store.delete_database(database_id, before_delete=before_delete)

    def list_database_ids(self) -> tuple[str, ...]:
        return self._store.list_database_ids()

    def load_database_definition(self, database_id: str) -> DatabaseDefinitionV1:
        return self._store.load_database_definition(database_id)

    def list_database_revisions(self, database_id: str) -> tuple[DatabaseRevisionManifest, ...]:
        return self._store.list_database_revisions(database_id)

    def load_database_revision(self, database_id: str, revision_id: str | None = None):
        loaded = self._store.load_database_revision(database_id, revision_id)
        if sha256(loaded.values_csv).hexdigest() != loaded.manifest.values_sha256:
            raise DataManagerCreationError("Database values payload hash disagrees")
        return loaded

    def _collection_revision_from_materialization(
        self, materialization: DataManagerArtifactMaterializationResult, *,
        collection_id: str, display_name: str, description: str,
        previous: str | None, created_at: datetime, revised_at: datetime,
        source_recipe_collection_id: str | None,
        source_recipe_collection_revision_id: str | None,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
        progress: Callable[[int, int, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        before_publish: Callable[[], None] | None = None,
    ) -> ArtifactCollectionRevisionV1:
        values = self._collection_values_from_materialization(
            materialization, selected_outputs,
            progress=progress, cancellation_requested=cancellation_requested,
        )
        return self._build_collection_revision(
            collection_id=collection_id,
            display_name=display_name,
            description=description,
            previous_revision_id=previous,
            created_at_utc=created_at,
            revised_at_utc=revised_at,
            source_recipe_collection_id=source_recipe_collection_id,
            source_recipe_collection_revision_id=(
                source_recipe_collection_revision_id
            ),
            **values,
        )

    def _collection_values_from_materialization(
        self,
        materialization: DataManagerArtifactMaterializationResult,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
        *, metadata_only: bool = False, progress=None, cancellation_requested=None,
    ) -> dict[str, object]:
        artifact_by_id = {item.artifact_id: item for item in materialization.managed_artifacts}
        logical_by_artifact = {item.artifact_id: item.logical_artifact_id for item in materialization.managed_artifacts}
        members: list[ArtifactCollectionMemberV1] = []
        edges: list[ArtifactCollectionDependencyV1] = []
        verified = {item.artifact_id: item for item in materialization.verified_artifact_metadata}
        total = len(materialization.managed_artifacts)
        for index, entry in enumerate(materialization.managed_artifacts, start=1):
            self._collection_publication_gate(cancellation_requested, None)()
            try:
                metadata = self._artifacts.load_artifact_metadata(
                    materialization.target_market_id, entry.artifact_id
                )
                reused = verified.get(entry.artifact_id) == metadata
                if not metadata_only and not reused:
                    metadata = self._artifacts.load_artifact_by_id(
                        materialization.target_market_id, entry.artifact_id
                    ).metadata
                if (not self._same_coverage(metadata.source_ohlcv, materialization.source_ohlcv)
                        or metadata.recipe.market_id != materialization.target_market_id
                        or metadata.recipe.output_names != entry.output_names):
                    raise DataManagerCreationError("Artifact metadata differs from materialization")
            except (ArtifactError, OSError, ValueError) as exc:
                raise DataManagerCreationError(
                    f"Artifact {entry.artifact_id}: {exc}"
                ) from exc
            if progress is not None and not metadata_only:
                action = "Reusing completed check" if reused else "Checked Artifact"
                progress(index, total, f"{action} {entry.artifact_id}")
            members.append(ArtifactCollectionMemberV1(
                ManagedArtifactVersionKey(entry.logical_artifact_id, entry.artifact_id),
                entry.portable_recipe_id, entry.tool_key, entry.kind, entry.output_names,
                metadata.values_sha256,
            ))
            for ref in metadata.recipe.source_artifacts:
                dependency_id = logical_by_artifact.get(ref.artifact_id)
                if dependency_id is None:
                    raise DataManagerCreationError("materialization result omits a supporting dependency")
                edges.append(ArtifactCollectionDependencyV1(
                    dependency_id, entry.logical_artifact_id, ref.role, ref.output_name
                ))
        if selected_outputs is None:
            outputs: list[ArtifactCollectionOutputV1] = []
            used: set[str] = set()
            for logical_id in materialization.root_logical_artifact_ids:
                entry = next(item for item in materialization.managed_artifacts if item.logical_artifact_id == logical_id)
                for output in entry.output_names:
                    column = output
                    if column in used:
                        raise DataManagerCreationError(
                            f"selected output-column collision requires explicit mapping: {column}"
                        )
                    used.add(column)
                    outputs.append(ArtifactCollectionOutputV1(logical_id, output, column))
        else:
            outputs = list(selected_outputs)
        return {
            "market_id": materialization.target_market_id,
            "verified_artifact_metadata": tuple(verified.values()) if not metadata_only else (),
            "roots": materialization.root_logical_artifact_ids,
            "supports": materialization.support_logical_artifact_ids,
            "members": tuple(members),
            "edges": tuple(edges),
            "selected_outputs": tuple(outputs),
            "presentation_order": tuple(item.column_name for item in outputs),
            "source_ohlcv": materialization.source_ohlcv,
            "first_timestamp_ms": max(
                item.first_timestamp_ms
                for item in materialization.managed_artifacts
            ),
            "last_timestamp_ms": min(
                item.last_timestamp_ms
                for item in materialization.managed_artifacts
            ),
        }

    @staticmethod
    def _collection_publication_gate(cancellation_requested, before_publish):
        def gate():
            if cancellation_requested is not None and cancellation_requested():
                raise DataManagerCreationError("Artifact Collection cancelled before publication")
            if before_publish is not None:
                before_publish()
            if cancellation_requested is not None and cancellation_requested():
                raise DataManagerCreationError("Artifact Collection cancelled before publication")
        return gate

    def _check_collection_inputs(
        self, plan, *, retained=(), progress=None, cancellation_requested=None,
    ):
        retained_by_key = {item.version_key: item for item in retained}
        changed_ids = tuple(
            item.version_key.logical_artifact_id for item in plan.members
            if retained_by_key.get(item.version_key) != item
        )
        required = self._required_members(changed_ids, plan.dependency_edges)
        pending = {
            item.version_key.artifact_id: (item.values_sha256, item.output_names)
            for item in plan.members
            if item.version_key.logical_artifact_id in required
        }
        physical_ids = list(pending)
        for artifact_id in physical_ids:
            self._collection_publication_gate(cancellation_requested, None)()
            metadata = self._artifacts.load_artifact_metadata(plan.market_id, artifact_id)
            for ref in metadata.recipe.source_artifacts:
                if ref.artifact_id not in pending:
                    dependency = self._artifacts.load_artifact_metadata(plan.market_id, ref.artifact_id)
                    pending[ref.artifact_id] = (dependency.values_sha256, dependency.recipe.output_names)
                    physical_ids.append(ref.artifact_id)
        for index, (artifact_id, (expected_hash, output_names)) in enumerate(pending.items(), start=1):
            self._collection_publication_gate(cancellation_requested, None)()
            try:
                metadata = self._artifacts.load_artifact_by_id(
                    plan.market_id, artifact_id
                ).metadata
                if (not self._same_coverage(metadata.source_ohlcv, plan.source_ohlcv)
                        or metadata.values_sha256 != expected_hash
                        or metadata.recipe.output_names != output_names):
                    raise DataManagerCreationError("Artifact differs from selected evidence")
            except (ArtifactError, OSError, ValueError) as exc:
                raise DataManagerCreationError(f"Artifact {artifact_id}: {exc}") from exc
            if progress is not None:
                progress(index, len(pending), f"Checked Artifact {artifact_id}")

    @staticmethod
    def _selection_outputs(
        plan: ArtifactCollectionSelectionPlan,
        selected_outputs: Sequence[ArtifactCollectionOutputV1] | None,
    ) -> tuple[ArtifactCollectionOutputV1, ...]:
        if selected_outputs is not None:
            return tuple(selected_outputs)
        member_by_id = {
            item.version_key.logical_artifact_id: item for item in plan.members
        }
        outputs: list[ArtifactCollectionOutputV1] = []
        used: set[str] = set()
        for logical_id in plan.root_logical_artifact_ids:
            for output_name in member_by_id[logical_id].output_names:
                if output_name in used:
                    raise DataManagerCreationError(
                        "selected output-column collision requires explicit mapping: "
                        f"{output_name}"
                    )
                used.add(output_name)
                outputs.append(
                    ArtifactCollectionOutputV1(
                        logical_id, output_name, output_name
                    )
                )
        return tuple(outputs)

    def _build_collection_revision(self, **values) -> ArtifactCollectionRevisionV1:
        payload = {
            "schema_version": "2.0", "object_type": "artifact_collection_revision",
            "collection_id": values["collection_id"], "display_name": values["display_name"],
            "description": values["description"],
            "market_id": {"exchange": values["market_id"].exchange, "market_type": values["market_id"].market_type,
                          "symbol": values["market_id"].symbol, "timeframe": values["market_id"].timeframe},
            "root_logical_artifact_ids": list(values["roots"]),
            "support_logical_artifact_ids": list(values["supports"]),
            "members": [item.to_dict() for item in values["members"]],
            "dependency_edges": [item.to_dict() for item in values["edges"]],
            "selected_outputs": [item.to_dict() for item in values["selected_outputs"]],
            "presentation_order": list(values["presentation_order"]),
            "source_portable_recipe_ids": sorted({item.portable_recipe_id for item in values["members"]}),
            "source_recipe_collection_id": values["source_recipe_collection_id"],
            "source_recipe_collection_revision_id": values["source_recipe_collection_revision_id"],
            "source_ohlcv": values["source_ohlcv"].to_dict(),
            "first_timestamp_ms": values["first_timestamp_ms"],
            "last_timestamp_ms": values["last_timestamp_ms"],
            "validation_state": "valid", "database_ready": True,
            "previous_revision_id": values["previous_revision_id"],
            "created_at_utc": values["created_at_utc"].isoformat().replace("+00:00", "Z"),
            "revised_at_utc": values["revised_at_utc"].isoformat().replace("+00:00", "Z"),
        }
        outputs = tuple(values["selected_outputs"])
        by_id = {m.version_key.logical_artifact_id: m for m in values["members"]}
        provenance = values.get("value_provenance")
        if provenance is None:
            retained = ()
            old_provenance = {"members": [], "dependency_edges": [], "outputs": []}
            if values["previous_revision_id"] is not None:
                previous = self.load_artifact_collection(values["collection_id"], values["previous_revision_id"])
                old_members = {m.version_key.logical_artifact_id: m for m in previous.members}
                if self._same_coverage(previous.source_ohlcv, values["source_ohlcv"]):
                    retained = tuple(o for o in outputs if o in previous.selected_outputs
                                     and old_members.get(o.logical_artifact_id) == by_id[o.logical_artifact_id])
                    old_provenance = self._combine_value_provenance((self._collection_value_provenance(previous),), retained)
            added = tuple(o for o in outputs if o not in retained)
            captured = self._capture_value_provenance(
                values["market_id"], added, {o.column_name: by_id[o.logical_artifact_id] for o in added},
                values["first_timestamp_ms"], values["last_timestamp_ms"],
                verified_metadata=values.get("verified_artifact_metadata", ()),
            )
            provenance = self._combine_value_provenance((old_provenance, captured), outputs)
        payload["value_provenance"] = provenance
        payload["revision_id"] = deterministic_hash(payload)
        return ArtifactCollectionRevisionV2.from_dict(payload)

    def _validated_batch_recipes(
        self, request: BatchArtifactRequest
    ) -> tuple[PortableRecipeV1, ...]:
        current_source = self._artifacts.capture_accepted_source(request.market_id)
        if current_source != request.expected_source_ohlcv:
            raise DataManagerCreationError(
                "accepted OHLCV source changed after Batch Preview"
            )
        try:
            catalogue = {
                (
                    item.logical_artifact_id,
                    item.artifact_id,
                    item.output_name,
                ): item
                for item in list_construct_source_signals(
                    self._artifacts, request.market_id, metadata_only=True
                )
                if self._same_coverage(item.source_ohlcv, current_source)
            }
        except (ArtifactError, OSError, ValueError) as exc:
            raise DataManagerCreationError(
                f"Construct Source Catalogue is unavailable: {exc}"
            ) from exc
        managed = {
            item.logical_artifact_id: item
            for item in self._artifacts.list_managed_artifacts_metadata(request.market_id)
        }
        recipes: list[PortableRecipeV1] = []
        for index, branch in enumerate(request.branches, start=1):
            source_recipe_ids: dict[str, str] = {}
            for source in branch.sources:
                if source.source_kind == "current_ohlcv":
                    if (
                        source.market_id != request.market_id
                        or source.source_ohlcv != request.expected_source_ohlcv
                    ):
                        raise DataManagerCreationError(
                            f"branch {index}: current OHLCV source identity changed"
                        )
                    continue
                identity = (
                    source.logical_artifact_id,
                    source.artifact_id,
                    source.output_name,
                )
                admitted = catalogue.get(identity)
                if admitted is None:
                    raise DataManagerCreationError(
                        f"branch {index}: frozen source is no longer admitted"
                    )
                if not self._same_coverage(admitted.source_ohlcv, request.expected_source_ohlcv):
                    raise DataManagerCreationError(
                        f"branch {index}: source OHLCV coverage changed"
                    )
                summary = managed.get(source.logical_artifact_id)
                if summary is None or not summary.valid:
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact is unavailable or invalid"
                    )
                if summary.artifact_id != source.artifact_id:
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact head changed"
                    )
                if source.output_name not in summary.output_names:
                    raise DataManagerCreationError(
                        f"branch {index}: selected source output disappeared"
                    )
                loaded = self._artifacts.load_artifact_by_id(
                    request.market_id, source.artifact_id
                )
                if not self._same_coverage(loaded.metadata.source_ohlcv, request.expected_source_ohlcv):
                    raise DataManagerCreationError(
                        f"branch {index}: source Artifact OHLCV changed"
                    )
                if source.output_name not in loaded.metadata.recipe.output_names:
                    raise DataManagerCreationError(
                        f"branch {index}: selected source output disappeared"
                    )
                source_recipe_ids[source.role] = summary.portable_recipe_id
            recipe = self._build_batch_portable_recipe(
                request,
                branch,
                source_recipe_ids,
            )
            if branch.requested_outputs != visible_output_names(
                branch.tool_key, branch.parameters, branch.sources
            ):
                raise DataManagerCreationError(
                    f"branch {index}: requested outputs do not match canonical visible outputs"
                )
            recipes.append(recipe)
        if (
            self._artifacts.capture_accepted_source(request.market_id)
            != request.expected_source_ohlcv
        ):
            raise DataManagerCreationError(
                "accepted OHLCV source changed during batch validation"
            )
        return self._resolve_portable_recipes(tuple(recipes))

    @staticmethod
    def _build_batch_portable_recipe(
        request: BatchArtifactRequest,
        branch: BatchArtifactBranchRequest,
        source_recipe_ids: Mapping[str, str],
    ) -> PortableRecipeV1:
        artifact_sources = tuple(
            source for source in branch.sources if source.source_kind == "artifact"
        )
        raw_sources = tuple(
            source
            for source in branch.sources
            if source.source_kind == "current_ohlcv"
        )
        if not raw_sources:
            direct_sources = tuple(
                DataManagerDirectArtifactSource(
                    source.role,
                    source.logical_artifact_id,
                    source.artifact_id,
                    source.output_name,
                )
                for source in artifact_sources
            )
            direct_request = DataManagerDirectArtifactRequest(
                market_id=request.market_id,
                expected_source_ohlcv=request.expected_source_ohlcv,
                tool_key=branch.tool_key,
                parameters=branch.parameters,
                sources=direct_sources,
            )
            return _build_direct_portable_recipe(
                direct_request, source_recipe_ids
            )

        spec = get_financial_tool_spec(branch.tool_key)
        roles = tuple(source.role for source in branch.sources)
        _validate_source_roles(spec.key, spec.kind, roles)
        resolved = dict(resolve_parameters(spec.key, branch.parameters))
        naming = dict(resolved)
        bound_names = {
            source.role: source.column
            if source.source_kind == "current_ohlcv"
            else f"__research_{source.role}"
            for source in branch.sources
        }
        if spec.key in {"derivative", "angle"}:
            naming["source"] = bound_names["source"]
        elif spec.key == "delta":
            naming.update(fast=bound_names["fast"], slow=bound_names["slow"])
        elif spec.key in {"braids", "braid_instability"}:
            naming.update(
                fast=bound_names["fast"],
                mid=bound_names["mid"],
                slow=bound_names["slow"],
            )
        elif spec.key == "trap_area":
            naming.update(fast=bound_names["fast"], slow=bound_names["slow"])
            if "mid" in roles:
                naming["mid"] = bound_names["mid"]
            else:
                naming.pop("mid", None)
        elif spec.key in {"percent_span_angle", "angle_momentum"}:
            naming["source_columns"] = ",".join(
                bound_names[f"source_{index}"]
                for index in range(1, len(roles) + 1)
            )
        dependencies = tuple(
            PortableRecipeDependencyV1(
                source.role,
                source_recipe_ids[source.role],
                source.output_name,
            )
            for source in artifact_sources
        )
        ohlcv_inputs = tuple(
            PortableRecipeOHLCVInputV1(source.role, source.column)
            for source in raw_sources
        )
        return build_portable_recipe(
            tool_key=spec.key,
            kind=spec.kind,
            parameters=resolved,
            output_names=resolve_output_names(spec.key, naming),
            ohlcv_inputs=ohlcv_inputs,
            dependencies=dependencies,
        )

    def _project_batch_plan(
        self,
        request: BatchArtifactRequest,
        recipes: tuple[PortableRecipeV1, ...],
        materialization: DataManagerArtifactMaterializationPlan,
    ) -> BatchArtifactPlan:
        branch_recipe_ids = tuple(recipe.recipe_id for recipe in recipes)
        recipe_ids = tuple(dict.fromkeys(branch_recipe_ids))
        node_by_recipe = {
            node.portable_recipe_id: node for node in materialization.nodes
        }
        branch_nodes = tuple(node_by_recipe[item] for item in branch_recipe_ids)
        branch_reuse = tuple(
            node.status == "REUSE_CURRENT" for node in branch_nodes
        )
        new_recipe_ids = tuple(
            recipe_id
            for recipe_id in recipe_ids
            if node_by_recipe[recipe_id].status != "REUSE_CURRENT"
        )
        reusable_recipe_ids = tuple(
            recipe_id
            for recipe_id in recipe_ids
            if node_by_recipe[recipe_id].status == "REUSE_CURRENT"
        )
        new_logical_ids = tuple(
            node_by_recipe[item].logical_artifact_id for item in new_recipe_ids
        )
        reusable_logical_ids = tuple(
            node_by_recipe[item].logical_artifact_id
            for item in reusable_recipe_ids
        )
        collisions = self._batch_output_collisions(
            request,
            recipes,
            tuple(node.logical_artifact_id for node in branch_nodes),
        )
        return BatchArtifactPlan(
            request=request,
            branch_recipe_ids=branch_recipe_ids,
            branch_reuse_current=branch_reuse,
            recipe_ids=recipe_ids,
            dependency_edges=tuple(
                (
                    edge.dependency_recipe_id,
                    edge.dependent_recipe_id,
                    edge.role,
                    edge.output_name,
                )
                for edge in materialization.dependency_edges
            ),
            execution_stages=materialization.execution_stages,
            new_recipe_ids=new_recipe_ids,
            reusable_recipe_ids=reusable_recipe_ids,
            new_logical_artifact_ids=new_logical_ids,
            reusable_logical_artifact_ids=reusable_logical_ids,
            naming_collisions=collisions,
            unsupported_combinations=(),
            blockers=(),
        )

    def _batch_output_collisions(
        self,
        request: BatchArtifactRequest,
        recipes: Sequence[PortableRecipeV1],
        logical_ids: Sequence[str],
    ) -> tuple[str, ...]:
        if request.destination == "individual":
            return ()
        owners: dict[str, tuple[str, str]] = {}
        if request.destination == "collection_revision":
            current = self.load_artifact_collection(request.collection_id)
            owners.update(
                {
                    item.column_name: (
                        item.logical_artifact_id,
                        item.output_name,
                    )
                    for item in current.selected_outputs
                }
            )
        collisions: list[str] = []
        for branch, recipe, logical_id in zip(
            request.branches, recipes, logical_ids, strict=True
        ):
            for output, column in zip(
                recipe.output_names, branch.requested_outputs, strict=True
            ):
                owner = (logical_id, output)
                previous = owners.setdefault(column, owner)
                if previous != owner and column not in collisions:
                    collisions.append(column)
        return tuple(collisions)

    def _batch_collection_outputs(
        self,
        plan: BatchArtifactPlan,
        recipes: Sequence[PortableRecipeV1],
    ) -> tuple[ArtifactCollectionOutputV1, ...] | None:
        if plan.request.destination == "individual":
            return None
        outputs: list[ArtifactCollectionOutputV1] = []
        seen: set[tuple[str, str, str]] = set()
        if plan.request.destination == "collection_revision":
            current = self.load_artifact_collection(plan.request.collection_id)
            for item in current.selected_outputs:
                identity = (
                    item.logical_artifact_id,
                    item.output_name,
                    item.column_name,
                )
                if identity not in seen:
                    seen.add(identity)
                    outputs.append(item)
        for branch, recipe in zip(plan.request.branches, recipes, strict=True):
            logical_id = compute_logical_artifact_id(
                plan.request.market_id, recipe.recipe_id
            )
            for output, column in zip(
                recipe.output_names, branch.requested_outputs, strict=True
            ):
                identity = (logical_id, output, column)
                if identity not in seen:
                    seen.add(identity)
                    outputs.append(
                        ArtifactCollectionOutputV1(logical_id, output, column)
                    )
        return tuple(outputs)

    @staticmethod
    def _required_members(
        roots: Sequence[str], edges: Sequence[ArtifactCollectionDependencyV1]
    ) -> set[str]:
        required = set(roots)
        changed = True
        while changed:
            changed = False
            for edge in edges:
                if edge.dependent_logical_artifact_id in required and edge.dependency_logical_artifact_id not in required:
                    required.add(edge.dependency_logical_artifact_id)
                    changed = True
        return required

    @staticmethod
    def _usable_coverage(
        collection: ArtifactCollectionRevisionV1,
        frames: Mapping[str, pd.DataFrame],
        blockers: list[str],
    ) -> tuple[int | None, int | None, int]:
        aligned: pd.DataFrame | None = None
        providers = ({b["column_name"]: b["artifact_id"] for b in collection.value_provenance["outputs"]}
                     if hasattr(collection, "value_provenance") else {})
        for selected in collection.selected_outputs:
            frame = frames.get(providers.get(selected.column_name, selected.logical_artifact_id))
            if frame is None:
                continue
            if "ts_ms" not in frame or selected.output_name not in frame:
                blockers.append(f"selected output unavailable: {selected.column_name}")
                continue
            values = frame[["ts_ms", selected.output_name]].rename(columns={selected.output_name: selected.column_name})
            if values["ts_ms"].duplicated().any() or not values["ts_ms"].is_monotonic_increasing:
                blockers.append(f"Artifact timestamps invalid: {selected.column_name}")
                continue
            aligned = values if aligned is None else aligned.merge(values, on="ts_ms", how="inner", validate="one_to_one")
        if aligned is None or aligned.empty:
            return None, None, 0
        return int(aligned["ts_ms"].iloc[0]), int(aligned["ts_ms"].iloc[-1]), len(aligned)

    @staticmethod
    def _full_source_seed_values(dataset, source, columns: tuple[str, ...]) -> bytes:
        raw = dataset.csv_path.read_bytes()
        if sha256(raw).hexdigest() != source.csv_sha256 or dataset.file_sha256 != source.csv_sha256:
            raise DataManagerCreationError("source CSV does not match accepted source evidence")
        header, rows, timestamps = _snapshot_rows(
            raw,
            columns=("ts_ms", "open", "high", "low", "close", "volume"),
            row_count=dataset.row_count,
            first=dataset.first_timestamp_ms, last=dataset.last_timestamp_ms,
        )
        if timestamps != dataset.ts_ms:
            raise DataManagerCreationError("source CSV timestamps do not match loaded OHLCV")
        selected = ("ts_ms", *columns)
        indices = tuple(header.index(column) for column in selected)
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(selected)
        writer.writerows(tuple(row[index] for index in indices) for row in rows)
        return output.getvalue().encode("utf-8")

    def _require_seed_candidate_current(
        self, seed: DatabaseSeedV1 | DatabaseSeedV2, values_csv: bytes
    ) -> None:
        if not isinstance(seed, DatabaseSeedV2) or seed.selected_ohlcv_columns not in (
            ("open", "high", "low", "close"),
            ("open", "high", "low", "close", "volume"),
        ):
            raise DataManagerCreationError("new Seed must be V2 with OHLC and optional Volume")
        source = self._artifacts.capture_accepted_source(seed.market_id)
        if source != seed.source_ohlcv:
            raise DataManagerCreationError(
                "accepted OHLCV fingerprint changed before Seed publication"
            )
        dataset = self._loader.load(seed.market_id)
        if (
            dataset.file_sha256 != seed.source_ohlcv.csv_sha256
            or dataset.row_count != seed.source_row_count
            or dataset.first_timestamp_ms != seed.first_timestamp_ms
            or dataset.last_timestamp_ms != seed.last_timestamp_ms
        ):
            raise DataManagerCreationError(
                "loaded OHLCV does not match Database Seed source evidence"
            )
        if (
            seed.row_count != dataset.row_count
            or seed.selected_range_start_ms != dataset.first_timestamp_ms
            or seed.selected_range_end_ms != dataset.last_timestamp_ms
        ):
            raise DataManagerCreationError("new Seed must cover the full accepted source")
        if values_csv != self._full_source_seed_values(dataset, source, seed.selected_ohlcv_columns):
            raise DataManagerCreationError("new Seed payload must match the full accepted source projection")

    def _seed_base_frame(self, seed) -> pd.DataFrame:
        return pd.read_csv(BytesIO(self._seed_base_values(seed)), float_precision="round_trip")

    def _seed_base_values(self, seed) -> bytes:
        if isinstance(seed, DatabaseSeedV2):
            return self._store.read_trusted_seed_values(seed.seed_id)
        # Prove original full-source bytes or the exact raw CSV prefix;
        # accepted sidecar evolution is deliberately not reconstruction evidence.
        path = OHLCVStore(self._catalog.historical_root).csv_path(seed.market_id)
        try:
            with path.open("rb") as handle:
                lines = [handle.readline() for _ in range(seed.source_row_count + 1)]
        except OSError as exc:
            raise DataManagerCreationError(
                "legacy Seed source bytes cannot be proven"
            ) from exc
        raw = b"".join(lines)
        if not all(lines) or sha256(raw).hexdigest() != seed.source_ohlcv.csv_sha256:
            raise DataManagerCreationError("legacy Seed source bytes cannot be proven")
        header, rows, timestamps = _snapshot_rows(
            raw,
            columns=("ts_ms", "open", "high", "low", "close", "volume"),
            row_count=seed.source_row_count,
            first=seed.first_timestamp_ms, last=seed.last_timestamp_ms,
        )
        if seed.selected_range_start_ms not in timestamps or seed.selected_range_end_ms not in timestamps:
            raise DataManagerCreationError("legacy Seed selected range cannot be proven")
        columns = ("ts_ms", *seed.selected_ohlcv_columns)
        indices = tuple(header.index(column) for column in columns)
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(
            tuple(row[index] for index in indices)
            for row, timestamp in zip(rows, timestamps, strict=True)
            if seed.selected_range_start_ms <= timestamp <= seed.selected_range_end_ms
        )
        return output.getvalue().encode("utf-8")

    def _database_frame(
        self, seed: DatabaseSeedV1, collection: ArtifactCollectionRevisionV1,
        *, reviewed_members=None,
    ) -> tuple[pd.DataFrame, int]:
        columns, rows, timestamps = _snapshot_rows(self._seed_base_values(seed))
        frame = pd.DataFrame(rows, columns=columns)
        frame["ts_ms"] = list(timestamps)
        self._require_coverage(seed.market_id, len(timestamps), timestamps[0], timestamps[-1], collection.source_ohlcv)
        providers = self._collection_output_providers(collection)
        for output in collection.selected_outputs:
            member = providers[output.column_name]
            frame[output.column_name] = self._copy_output_slice(
                seed.market_id, member, output, timestamps
            )
        frame = frame[["ts_ms", *seed.selected_ohlcv_columns, *collection.presentation_order]]
        if frame["ts_ms"].duplicated().any() or not frame["ts_ms"].is_monotonic_increasing:
            raise DataManagerCreationError("Database timestamps must be monotonic and unique")
        return frame, 0
