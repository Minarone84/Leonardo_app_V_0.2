from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.artifacts import (
    ArtifactMetadataV1,
    ArtifactLineageError,
    ArtifactSummary,
    ArtifactVersionRecordV1,
    ArtifactValidationError,
    ManagedArtifactSummary,
    ManagedArtifactVersionKey,
    OHLCVSourceFingerprintV1,
    RecipeInUseError,
    RecipeSummary,
    compute_logical_artifact_id,
)
from leonardo.data import MarketId
from leonardo.data_manager import (
    ArtifactCollectionMemberV1,
    ArtifactCollectionOutputV1,
    ArtifactCollectionRevisionV1,
    DataManagerCatalogSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerOperationError,
    DataManagerPortableRecipeCatalog,
    DataManagerRecipeCollectionCatalog,
    DataManagerReconciliationSnapshot,
    DataManagerService,
    DataManagerStudyEnvironmentCatalog,
)
from leonardo.data_manager.creation_models import deterministic_hash
from leonardo.data_manager.models import (
    DataManagerDeletionResult,
    DuplicateMaintenanceCandidate,
    DuplicateMaintenanceGroup,
    DuplicateMaintenancePreflight,
    DuplicateMaintenanceScanResult,
)
from leonardo.data_manager.service import DataManagerMarketUnavailableError
from leonardo.recipes import (
    PortableRecipeCollectionRevisionV1,
    PortableRecipeCollectionSummary,
    PortableRecipeDependencyV1,
    PortableRecipeGraphPlanner,
    PortableRecipeOHLCVInputV1,
    PortableRecipeProvenanceV1,
    PortableRecipeStore,
    PortableRecipeSummary,
    build_portable_recipe,
)
from leonardo.recipes.models import (
    PortableRecipePersistenceMetadataV1,
    canonical_json_bytes,
)
from leonardo.research import (
    AcceptedDatasetSummary,
    DatasetCatalogReport,
    DatasetRejection,
    HistoricalDataset,
    StudyEnvironmentStore,
)


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")


def _accepted(market: MarketId = MARKET) -> AcceptedDatasetSummary:
    return AcceptedDatasetSummary(
        market,
        Path("candles.csv"),
        Path("candles.meta.json"),
        "a" * 64,
        6,
        1,
        6,
        "bybit",
        "committed",
        "ok",
        (),
    )


def _dataset() -> HistoricalDataset:
    return HistoricalDataset(
        MARKET,
        Path("candles.csv"),
        "a" * 64,
        6,
        1,
        6,
        (1, 2, 3, 4, 5, 6),
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        (2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
        (0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
        (1.5, 2.5, 3.5, 4.5, 5.5, 6.5),
        (10.0, 11.0, 12.0, 13.0, 14.0, 15.0),
    )


class _Catalog:
    def __init__(self, report=None) -> None:
        self.report = report or DatasetCatalogReport((_accepted(),), ())
        self.calls = 0

    def scan(self):
        self.calls += 1
        return self.report


class _Loader:
    def __init__(self) -> None:
        self.dataset = _dataset()

    def load(self, market_id, *, progress=None, cancellation_requested=None):
        if progress is not None:
            progress(6, 6)
        return self.dataset


class _Artifacts:
    def __init__(self) -> None:
        self.deleted = []
        self.calls = []
        self.validation_error = None
        self.recipe_error = None
        self.frame = pd.DataFrame({"ts_ms": range(1, 7), "rsi": [45, 48, 52, 57, 61, 64]})
        self.managed_markets = ()
        self.managed_artifacts = {}
        self.managed_versions = {}
        self.managed_deleted = []
        self.artifacts_by_id = {}
        self.source = OHLCVSourceFingerprintV1(
            MARKET,
            "1" * 64,
            "2" * 64,
            6,
            1,
            6,
            "committed",
            "ok",
            "1.0",
        )

    def list_recipes(self, market_id):
        self.calls.append(("list_recipes", market_id))
        return (self._recipe_summary(market_id),)

    def list_artifacts(self, market_id):
        self.calls.append(("list_artifacts", market_id))
        return (self._artifact_summary(market_id),)

    @staticmethod
    def _recipe_summary(market_id):
        return RecipeSummary(
            market_id,
            "2" * 64,
            "rsi",
            "oscillator",
            ("rsi",),
            "RSI 14",
            datetime(2026, 7, 18, tzinfo=UTC),
        )

    @staticmethod
    def _artifact_summary(market_id):
        return ArtifactSummary(
            market_id,
            "4" * 64,
            "2" * 64,
            "rsi",
            "oscillator",
            ("rsi",),
            6,
            1,
            6,
            datetime(2026, 7, 18, tzinfo=UTC),
        )

    def load_artifact(self, market_id, kind, tool_key, artifact_id):
        self.calls.append(("load_artifact", market_id, kind, tool_key, artifact_id))
        recipe = SimpleNamespace(
            output_names=("rsi",), recipe_id="2" * 64, tool_key="rsi", kind="oscillator"
        )
        metadata = SimpleNamespace(
            recipe=recipe, row_count=len(self.frame), first_timestamp_ms=1, last_timestamp_ms=len(self.frame)
        )
        return SimpleNamespace(metadata=metadata, frame=self.frame.copy(deep=True))

    def load_artifact_by_id(self, market_id, artifact_id):
        self.calls.append(("load_artifact_by_id", market_id, artifact_id))
        return SimpleNamespace(metadata=self.artifacts_by_id[artifact_id])

    def validate_artifact_current(self, market_id, kind, tool_key, artifact_id):
        self.calls.append(
            ("validate_artifact", market_id, kind, tool_key, artifact_id)
        )
        if self.validation_error is not None:
            raise self.validation_error
        return self._artifact_summary(market_id)

    def delete_artifact(self, market_id, kind, tool_key, artifact_id):
        self.calls.append(
            ("delete_artifact", market_id, kind, tool_key, artifact_id)
        )
        self.deleted.append(("artifact", market_id, kind, tool_key, artifact_id))
        return self._artifact_summary(market_id)

    def delete_recipe(self, market_id, kind, tool_key, recipe_id):
        self.calls.append(("delete_recipe", market_id, kind, tool_key, recipe_id))
        if self.recipe_error is not None:
            raise self.recipe_error
        self.deleted.append(("recipe", market_id, kind, tool_key, recipe_id))
        return self._recipe_summary(market_id)

    def list_managed_markets(self):
        return self.managed_markets

    def list_managed_artifacts(self, market_id):
        return self.managed_artifacts.get(market_id, ())

    def list_artifact_versions(self, market_id, logical_artifact_id):
        return self.managed_versions.get((market_id, logical_artifact_id), ())

    def capture_accepted_source(self, market_id):
        assert market_id == self.source.market_id
        return self.source

    def delete_managed_artifact(
        self, market_id, logical_artifact_id, *, before_delete=None
    ):
        if before_delete is not None:
            before_delete()
        self.managed_deleted.append((market_id, logical_artifact_id))
        return SimpleNamespace(
            market_id=market_id, logical_artifact_id=logical_artifact_id
        )


def _service(catalog=None, loader=None, artifacts=None, *, root=None):
    recipes = PortableRecipeStore(
        Path("__unused_data_manager_recipes_test__") if root is None else root
    )
    return DataManagerService(
        catalog or _Catalog(),
        loader or _Loader(),
        artifacts or _Artifacts(),
        StudyEnvironmentStore(Path("__unused_study_environments_test__")),
        recipes,
        PortableRecipeGraphPlanner(recipes),
    )


def _publish_legacy_recipe(
    store: PortableRecipeStore,
    recipe,
    legacy_recipe_id: str,
    *,
    first_persisted_at_utc: datetime | None = None,
) -> Path:
    payload = recipe.to_dict()
    payload["recipe_id"] = legacy_recipe_id
    path = store.root_dir / "recipes" / f"{legacy_recipe_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))
    if first_persisted_at_utc is not None:
        _publish_recipe_metadata(
            store, legacy_recipe_id, first_persisted_at_utc
        )
    return path


def _publish_recipe_metadata(
    store: PortableRecipeStore,
    recipe_id: str,
    first_persisted_at_utc: datetime,
) -> Path:
    metadata = PortableRecipePersistenceMetadataV1(
        recipe_id, first_persisted_at_utc, ()
    )
    path = (
        store.root_dir
        / "recipe_provenance"
        / recipe_id
        / "metadata.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(metadata.canonical_json_bytes())
    return path


def _artifact_collection_revision(
    *,
    collection_id: str,
    display_name: str,
    created_at_utc: datetime,
    source: OHLCVSourceFingerprintV1,
    portable_recipe_id: str = "3" * 64,
    artifact_id: str = "4" * 64,
    output_name: str = "sma_20",
) -> ArtifactCollectionRevisionV1:
    logical_artifact_id = compute_logical_artifact_id(MARKET, portable_recipe_id)
    member = ArtifactCollectionMemberV1(
        ManagedArtifactVersionKey(logical_artifact_id, artifact_id),
        portable_recipe_id,
        "sma",
        "indicator",
        (output_name,),
        "5" * 64,
    )
    output = ArtifactCollectionOutputV1(
        logical_artifact_id,
        output_name,
        output_name,
    )
    payload = {
        "schema_version": "1.0",
        "object_type": "artifact_collection_revision",
        "collection_id": collection_id,
        "display_name": display_name,
        "description": f"Description for {display_name}",
        "market_id": {
            "exchange": MARKET.exchange,
            "market_type": MARKET.market_type,
            "symbol": MARKET.symbol,
            "timeframe": MARKET.timeframe,
        },
        "root_logical_artifact_ids": [logical_artifact_id],
        "support_logical_artifact_ids": [],
        "members": [member.to_dict()],
        "dependency_edges": [],
        "selected_outputs": [output.to_dict()],
        "presentation_order": [output.column_name],
        "source_portable_recipe_ids": [portable_recipe_id],
        "source_recipe_collection_id": None,
        "source_recipe_collection_revision_id": None,
        "source_ohlcv": source.to_dict(),
        "first_timestamp_ms": 1,
        "last_timestamp_ms": 6,
        "validation_state": "valid",
        "database_ready": True,
        "previous_revision_id": None,
        "created_at_utc": created_at_utc.isoformat().replace("+00:00", "Z"),
        "revised_at_utc": created_at_utc.isoformat().replace("+00:00", "Z"),
    }
    payload["revision_id"] = deterministic_hash(payload)
    return ArtifactCollectionRevisionV1.from_dict(payload)


def _install_artifact_collection_member_metadata(
    artifacts: _Artifacts,
    *,
    artifact_id: str = "4" * 64,
    period: int = 20,
    column_name: str = "close",
) -> None:
    artifacts.artifacts_by_id[artifact_id] = SimpleNamespace(
        artifact_id=artifact_id,
        recipe=SimpleNamespace(
            market_id=MARKET,
            tool_key="sma",
            parameters={"period": period},
            bindings={"close": f"OHLCV.{column_name}"},
            source_artifacts=(),
        ),
        source_ohlcv=artifacts.source,
    )


def _install_managed_artifact(
    artifacts: _Artifacts,
    *,
    portable_recipe_id: str,
    artifact_id: str,
    created_at_utc: datetime,
    column_name: str = "close",
    market: MarketId = MARKET,
    source: OHLCVSourceFingerprintV1 | None = None,
) -> ManagedArtifactSummary:
    resolved_source = artifacts.source if source is None else source
    logical_id = compute_logical_artifact_id(market, portable_recipe_id)
    summary = ManagedArtifactSummary(
        logical_id,
        portable_recipe_id,
        market,
        artifact_id,
        None,
        "sma",
        "indicator",
        ("sma_20",),
        6,
        1,
        6,
        created_at_utc,
    )
    artifacts.managed_artifacts[market] = (
        *artifacts.managed_artifacts.get(market, ()),
        summary,
    )
    artifacts.artifacts_by_id[artifact_id] = SimpleNamespace(
        artifact_id=artifact_id,
        recipe=SimpleNamespace(
            market_id=market,
            tool_key="sma",
            parameters={"period": 20},
            bindings={"close": f"OHLCV.{column_name}"},
            source_artifacts=(),
        ),
        source_ohlcv=resolved_source,
    )
    artifacts.managed_versions[(market, logical_id)] = (
        ArtifactVersionRecordV1(
            logical_id,
            artifact_id,
            portable_recipe_id,
            market,
            None,
            created_at_utc,
        ),
    )
    return summary


def _publish_recipe_collection_duplicates(
    service: DataManagerService,
    collection_ids: tuple[str, ...],
) -> tuple[PortableRecipeV1, tuple[PortableRecipeCollectionRevisionV1, ...]]:
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    service._portable_recipes.save_recipe(recipe)
    revisions = tuple(
        PortableRecipeCollectionRevisionV1.build(
            collection_id=collection_id,
            display_name=f"Collection {index}",
            description=f"Duplicate fixture {index}",
            root_recipe_ids=(recipe.recipe_id,),
            member_recipe_ids=(recipe.recipe_id,),
            previous_revision_id=None,
            created_at_utc=datetime(2026, 8, index, tzinfo=UTC),
        )
        for index, collection_id in enumerate(collection_ids, start=1)
    )
    for revision in revisions:
        service._portable_recipes._publish_revision(
            revision, updated_at_utc=revision.created_at_utc
        )
    return recipe, revisions


def test_product_catalog_scan_aggregates_each_family_once(monkeypatch) -> None:
    service = _service()
    reconciliation = DataManagerReconciliationSnapshot(
        datetime(2026, 8, 4, tzinfo=UTC), (), (), (), (), (), "0" * 64
    )
    service._updates._snapshot = reconciliation
    calls: list[str] = []

    def value(name, result):
        def read(*_args, **_kwargs):
            calls.append(name)
            return result

        return read

    def forbidden_reconciliation(*_args, **_kwargs):
        pytest.fail("product catalog scan must not invoke reconciliation")

    monkeypatch.setattr(service, "latest_update_status", forbidden_reconciliation)
    monkeypatch.setattr(service, "reconcile_update_status", forbidden_reconciliation)
    monkeypatch.setattr(service._updates, "reconcile_all", forbidden_reconciliation)
    monkeypatch.setattr(service, "list_database_ids", value("database_ids", ()))
    monkeypatch.setattr(service, "scan_catalog", value("ohlcv", DataManagerCatalogSnapshot(())))
    monkeypatch.setattr(
        service,
        "scan_study_environments",
        value("environments", DataManagerStudyEnvironmentCatalog(())),
    )
    monkeypatch.setattr(
        service,
        "scan_portable_recipes",
        value("recipes", DataManagerPortableRecipeCatalog(())),
    )
    monkeypatch.setattr(
        service,
        "list_recipe_collections",
        value("recipe_collections", DataManagerRecipeCollectionCatalog(())),
    )
    monkeypatch.setattr(
        service,
        "scan_managed_artifacts",
        value("managed_artifacts", DataManagerManagedArtifactCatalog(())),
    )
    monkeypatch.setattr(service, "list_artifact_collections", value("collections", ()))
    monkeypatch.setattr(service, "list_database_seeds", value("seeds", ()))

    snapshot = service.scan_product_catalogs()

    assert snapshot.latest_reconciliation is reconciliation
    assert service._updates.cached_snapshot() is reconciliation
    assert calls == [
        "database_ids",
        "ohlcv",
        "environments",
        "recipes",
        "recipe_collections",
        "managed_artifacts",
        "collections",
        "seeds",
    ]


def test_recipe_collection_catalog_projects_exact_current_member_ids(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipes = (
        build_portable_recipe(
            tool_key="sma",
            kind="indicator",
            parameters={"period": 10},
            output_names=("sma_10",),
        ),
        build_portable_recipe(
            tool_key="sma",
            kind="indicator",
            parameters={"period": 20},
            output_names=("sma_20",),
        ),
    )
    for recipe in recipes:
        service._portable_recipes.save_recipe(recipe)
    roots = tuple(recipe.recipe_id for recipe in recipes)
    plan = PortableRecipeGraphPlanner(service._portable_recipes).plan(roots)
    service._portable_recipes.create_collection(
        "Collection",
        "",
        plan.root_recipe_ids,
        plan.member_recipe_ids,
    )

    entry = service.list_recipe_collections().collections[0]
    assert entry.valid
    assert entry.member_recipe_ids == plan.member_recipe_ids
    assert entry.member_count == len(plan.member_recipe_ids)


def test_recipe_collection_create_propagates_existing_semantic_winner(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 10},
        output_names=("sma_10",),
    )
    service._portable_recipes.save_recipe(recipe)
    first = service.create_recipe_collection(
        "Original", "old", (recipe.recipe_id,)
    )

    reused = service.create_recipe_collection(
        "Requested", "new", (recipe.recipe_id,)
    )

    assert reused.collection.collection_id == first.collection.collection_id
    assert reused.collection.revision_id == first.collection.revision_id
    assert reused.collection.display_name == "Original"
    assert reused.collection.description == "old"


def test_recipe_collection_update_propagates_equivalent_peer_winner(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    fast = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 10},
        output_names=("sma_10",),
    )
    slow = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    for recipe in (fast, slow):
        service._portable_recipes.save_recipe(recipe)
    older = service.create_recipe_collection("Older", "", (fast.recipe_id,))
    selected = service.create_recipe_collection("Selected", "", (slow.recipe_id,))

    reused = service.update_recipe_collection(
        selected.collection.collection_id,
        "Requested",
        "requested",
        (fast.recipe_id,),
        expected_revision_id=selected.collection.revision_id,
    )

    assert reused.collection.collection_id == older.collection.collection_id
    assert reused.collection.revision_id == older.collection.revision_id
    assert reused.collection.display_name == "Older"
    assert service.inspect_recipe_collection(
        selected.collection.collection_id
    ) == selected


def _collection_detail_fixture():
    from leonardo.data_manager import (
        ArtifactCollectionRevisionV1,
        ArtifactCollectionValidation,
    )

    artifact_id = "7" * 64
    portable_recipe_id = "8" * 64
    artifact_recipe_id = "a" * 64
    values_sha256 = "9" * 64
    member = SimpleNamespace(
        version_key=SimpleNamespace(
            logical_artifact_id="6" * 64,
            artifact_id=artifact_id,
        ),
        portable_recipe_id=portable_recipe_id,
        tool_key="sma",
        kind="indicator",
        output_names=("sma_20",),
        values_sha256=values_sha256,
    )
    revision = object.__new__(ArtifactCollectionRevisionV1)
    for name, value in {
        "collection_id": "collection_1",
        "revision_id": "5" * 64,
        "market_id": MARKET,
        "members": (member,),
    }.items():
        object.__setattr__(revision, name, value)
    validation = ArtifactCollectionValidation(
        revision.collection_id,
        revision.revision_id,
        True,
        True,
        (),
        1,
        6,
        6,
        1,
    )
    metadata = object.__new__(ArtifactMetadataV1)
    recipe = SimpleNamespace(
        market_id=MARKET,
        recipe_id=artifact_recipe_id,
        tool_key="sma",
        kind="indicator",
        output_names=("sma_20",),
        parameters={"period": 20},
        bindings={"source": "OHLCV.close"},
        source_artifacts=(),
    )
    for name, value in {
        "artifact_id": artifact_id,
        "recipe": recipe,
        "values_sha256": values_sha256,
        "row_count": 6,
        "first_timestamp_ms": 1,
        "last_timestamp_ms": 6,
    }.items():
        object.__setattr__(metadata, name, value)
    return revision, validation, metadata


def test_artifact_collection_create_propagates_exact_semantic_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    winner, _validation, _metadata = _collection_detail_fixture()
    materialization = object()
    calls: list[tuple[object, str, dict[str, object]]] = []
    invalidations: list[bool] = []
    monkeypatch.setattr(
        service._creation,
        "create_artifact_collection",
        lambda value, display_name, **options: (
            calls.append((value, display_name, options)),
            winner,
        )[-1],
    )
    monkeypatch.setattr(
        service._updates,
        "invalidate",
        lambda: invalidations.append(True),
    )

    returned = service.create_artifact_collection(
        materialization,
        "Requested",
        description="requested metadata",
    )

    assert returned is winner
    assert calls == [
        (
            materialization,
            "Requested",
            {
                "description": "requested metadata",
                "source_recipe_collection_id": None,
                "source_recipe_collection_revision_id": None,
                "selected_outputs": None,
            },
        )
    ]
    assert invalidations == [True]


def test_artifact_collection_detail_inspection_uses_embedded_metadata_only(
    monkeypatch,
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts)
    revision, validation, metadata = _collection_detail_fixture()
    artifacts.artifacts_by_id[metadata.artifact_id] = metadata
    monkeypatch.setattr(
        service._creation,
        "inspect_artifact_collection",
        lambda collection_id, revision_id: (revision, validation),
    )
    monkeypatch.setattr(
        service._portable_recipes,
        "load_recipe",
        lambda _recipe_id: pytest.fail("portable Recipe lookup is forbidden"),
    )
    monkeypatch.setattr(
        service._updates,
        "invalidate",
        lambda: pytest.fail("inspection must not invalidate update state"),
    )

    result = service.inspect_artifact_collection_details(
        revision.collection_id, revision.revision_id
    )

    assert revision.members[0].portable_recipe_id != metadata.recipe.recipe_id
    assert result == (revision, validation, (metadata,))
    assert result[2][0].recipe.parameters == {"period": 20}
    assert artifacts.calls == [
        ("load_artifact_by_id", MARKET, metadata.artifact_id)
    ]


@pytest.mark.parametrize(
    ("target", "replacement"),
    (
        ("artifact_id", "4" * 64),
        ("market_id", MarketId("bybit", "linear", "ETHUSDT", "1h")),
        ("tool_key", "ema"),
        ("kind", "oscillator"),
        ("output_names", ("other",)),
        ("values_sha256", "2" * 64),
    ),
)
def test_artifact_collection_detail_inspection_rejects_member_mismatch(
    monkeypatch,
    target: str,
    replacement: object,
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts)
    revision, validation, metadata = _collection_detail_fixture()
    if target in {
        "market_id", "recipe_id", "tool_key", "kind", "output_names"
    }:
        setattr(metadata.recipe, target, replacement)
    else:
        object.__setattr__(metadata, target, replacement)
    artifacts.artifacts_by_id[revision.members[0].version_key.artifact_id] = metadata
    monkeypatch.setattr(
        service._creation,
        "inspect_artifact_collection",
        lambda collection_id, revision_id: (revision, validation),
    )

    with pytest.raises(
        DataManagerOperationError,
        match="does not match Collection truth",
    ):
        service.inspect_artifact_collection_details(
            revision.collection_id, revision.revision_id
        )


def test_catalog_projects_accepted_and_rejected_without_paths() -> None:
    rejected_market = MarketId("bybit", "linear", "SOLUSDT", "1h")
    report = DatasetCatalogReport(
        (_accepted(),),
        (
            DatasetRejection(Path("private"), "hash", "changed", rejected_market),
            DatasetRejection(Path("private2"), "identity", "unknown"),
        ),
    )
    snapshot = _service(catalog=_Catalog(report)).scan_catalog()
    assert [(item.accepted, item.market_id) for item in snapshot.datasets] == [
        (True, MARKET),
        (False, rejected_market),
        (False, None),
    ]
    assert all(not hasattr(item, "dataset_dir") for item in snapshot.datasets)


def test_market_inspection_delegates_and_orders_canonical_summaries() -> None:
    snapshot = _service().inspect_market(MARKET)
    assert snapshot.market_id == MARKET
    assert snapshot.dataset.accepted
    assert snapshot.recipes[0].recipe_id == "2" * 64
    assert snapshot.artifacts[0].current_status == "unknown"


def test_dataset_preview_is_bounded_head_then_tail_and_reports_progress() -> None:
    service = _service()
    events = []
    preview = service._preview_dataset(
        MARKET,
        limit=5,
        progress=lambda current, total: events.append((current, total)),
        cancellation_requested=lambda: False,
    )
    assert preview.columns == ("ts_ms", "open", "high", "low", "close", "volume")
    assert [row[0] for row in preview.rows] == ["1", "2", "3", "5", "6"]
    assert preview.total_rows == 6
    assert preview.truncated
    assert events == [(6, 6)]
    assert "path" not in preview.metadata


def test_artifact_preview_formats_nan_boolean_and_string_and_rejects_infinity() -> None:
    artifacts = _Artifacts()
    artifacts.frame = pd.DataFrame(
        {"ts_ms": [0, 1, 2], "rsi": [float("nan"), True, "exact"]}
    )
    preview = _service(artifacts=artifacts).preview_artifact(
        MARKET, "oscillator", "rsi", "4" * 64
    )
    assert preview.rows == (("0", ""), ("1", "true"), ("2", "exact"))
    artifacts.frame = pd.DataFrame({"ts_ms": [0], "rsi": [float("inf")]})
    with pytest.raises(DataManagerOperationError, match="infinity") as captured:
        _service(artifacts=artifacts).preview_artifact(
            MARKET, "oscillator", "rsi", "4" * 64
        )
    assert type(captured.value) is DataManagerOperationError


def test_validation_distinguishes_current_stale_and_invalid() -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts)
    assert service.validate_artifact_current(MARKET, "oscillator", "rsi", "4" * 64).status == "current"
    artifacts.validation_error = ArtifactLineageError("source changed")
    assert service.validate_artifact_current(MARKET, "oscillator", "rsi", "4" * 64).status == "stale"
    artifacts.validation_error = ArtifactValidationError("invalid bytes")
    assert service.validate_artifact_current(MARKET, "oscillator", "rsi", "4" * 64).status == "invalid"


def test_deletion_delegates_exact_identity_and_preserves_recipe_refusal() -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts)
    result = service.delete_artifact(MARKET, "oscillator", "rsi", "4" * 64)
    assert result == DataManagerDeletionResult(
        MARKET, "artifact", "oscillator", "rsi", "4" * 64
    )
    assert artifacts.deleted == [("artifact", MARKET, "oscillator", "rsi", "4" * 64)]
    assert artifacts.calls == [
        ("delete_artifact", MARKET, "oscillator", "rsi", "4" * 64)
    ]
    artifacts.recipe_error = RecipeInUseError("recipe is referenced")
    with pytest.raises(RecipeInUseError, match="referenced"):
        service.delete_recipe(MARKET, "oscillator", "rsi", "2" * 64)


def test_recipe_deletion_returns_committed_identity_after_one_exact_delete() -> None:
    artifacts = _Artifacts()
    result = _service(artifacts=artifacts).delete_recipe(
        MARKET, "oscillator", "rsi", "2" * 64
    )
    assert result == DataManagerDeletionResult(
        MARKET, "recipe", "oscillator", "rsi", "2" * 64
    )
    assert artifacts.deleted == [
        ("recipe", MARKET, "oscillator", "rsi", "2" * 64)
    ]
    assert artifacts.calls == [
        ("delete_recipe", MARKET, "oscillator", "rsi", "2" * 64)
    ]


@pytest.mark.parametrize(
    "operation",
    ("preview_artifact", "validate_artifact", "delete_artifact", "delete_recipe"),
)
@pytest.mark.parametrize("revoked_state", ("rejected", "missing"))
def test_revoked_acceptance_blocks_artifact_service_calls(
    operation, revoked_state
) -> None:
    catalog = _Catalog()
    artifacts = _Artifacts()
    service = _service(catalog=catalog, artifacts=artifacts)
    assert service.scan_catalog().accepted_market(MARKET) is not None
    catalog.report = DatasetCatalogReport(
        (),
        (
            (DatasetRejection(Path("private"), "hash", "source changed", MARKET),)
            if revoked_state == "rejected"
            else ()
        ),
    )
    actions = {
        "preview_artifact": lambda: service.preview_artifact(
            MARKET, "oscillator", "rsi", "4" * 64
        ),
        "validate_artifact": lambda: service.validate_artifact_current(
            MARKET, "oscillator", "rsi", "4" * 64
        ),
        "delete_artifact": lambda: service.delete_artifact(
            MARKET, "oscillator", "rsi", "4" * 64
        ),
        "delete_recipe": lambda: service.delete_recipe(
            MARKET, "oscillator", "rsi", "2" * 64
        ),
    }
    expected = (
        "hash: source changed"
        if revoked_state == "rejected"
        else "missing from canonical persistence"
    )
    with pytest.raises(DataManagerOperationError, match=expected):
        actions[operation]()
    assert artifacts.calls == []
    assert artifacts.deleted == []


@pytest.mark.parametrize("state", ("rejected", "missing"))
def test_rejected_or_missing_market_uses_exact_unavailable_subtype(state) -> None:
    report = DatasetCatalogReport(
        (),
        (
            (DatasetRejection(Path("private"), "hash", "changed", MARKET),)
            if state == "rejected"
            else ()
        ),
    )
    expected = (
        f"Dataset {MARKET.as_key()} is unavailable: hash: changed"
        if state == "rejected"
        else f"Dataset {MARKET.as_key()} is missing from canonical persistence"
    )
    with pytest.raises(DataManagerMarketUnavailableError) as captured:
        _service(catalog=_Catalog(report)).inspect_market(MARKET)
    assert str(captured.value) == expected


def test_global_recipe_deletion_ignores_external_provenance_and_invalidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    service._portable_recipes.save_recipe(recipe)
    provenance = PortableRecipeProvenanceV1.build(
        recipe_id=recipe.recipe_id,
        origin_market_id=MARKET,
        study_environment_id="env_recipe_delete",
        study_environment_content_hash="b" * 64,
        study_environment_updated_at_utc=datetime(2026, 8, 17, tzinfo=UTC),
        study_environment_display_name="Recipe deletion",
        study_entry_id="entry_sma",
        study_display_name="SMA",
        study_description="",
    )
    service._portable_recipes.save_provenance(provenance)
    managed_summary = SimpleNamespace(valid=True, logical_artifact_id="a" * 64)
    managed_version = SimpleNamespace(portable_recipe_id=recipe.recipe_id)
    artifacts.managed_markets = (MARKET,)
    artifacts.managed_artifacts[MARKET] = (managed_summary,)
    artifacts.managed_versions[(MARKET, managed_summary.logical_artifact_id)] = (
        managed_version,
    )
    artifact_collection = SimpleNamespace(
        source_portable_recipe_ids=(recipe.recipe_id,),
    )
    database = SimpleNamespace(portable_recipe_ids=(recipe.recipe_id,))
    monkeypatch.setattr(
        service,
        "_artifact_collection_revisions_for_deletion_proof",
        lambda: (artifact_collection,),
    )
    monkeypatch.setattr(
        service, "_database_revisions_for_deletion_proof", lambda: (database,)
    )
    invalidations: list[bool] = []
    monkeypatch.setattr(service._updates, "invalidate", lambda: invalidations.append(True))

    assert service.delete_portable_recipe(recipe.recipe_id) == recipe
    assert invalidations == [True]
    with pytest.raises(FileNotFoundError):
        service._portable_recipes.load_recipe(recipe.recipe_id)
    assert service._portable_recipes.list_provenance(recipe.recipe_id) == ()
    assert artifacts.managed_markets == (MARKET,)
    assert artifacts.managed_artifacts[MARKET] == (managed_summary,)
    assert artifacts.managed_versions[
        (MARKET, managed_summary.logical_artifact_id)
    ] == (managed_version,)
    assert artifact_collection.source_portable_recipe_ids == (recipe.recipe_id,)
    assert database.portable_recipe_ids == (recipe.recipe_id,)


def test_global_recipe_deletion_does_not_read_artifact_domain_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma", kind="indicator", parameters={"period": 20},
        output_names=("sma_20",),
    )
    service._portable_recipes.save_recipe(recipe)

    def unexpected_evidence_read(*_args, **_kwargs):
        raise AssertionError("Artifact-domain evidence must not be read")

    monkeypatch.setattr(
        service,
        "_managed_markets_for_deletion_proof",
        unexpected_evidence_read,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_managed_artifacts_for_deletion_proof",
        unexpected_evidence_read,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_artifact_collection_revisions_for_deletion_proof",
        unexpected_evidence_read,
    )
    monkeypatch.setattr(
        service, "_database_revisions_for_deletion_proof", unexpected_evidence_read
    )
    monkeypatch.setattr(artifacts, "list_managed_markets", unexpected_evidence_read)
    monkeypatch.setattr(artifacts, "list_managed_artifacts", unexpected_evidence_read)
    monkeypatch.setattr(artifacts, "list_artifact_versions", unexpected_evidence_read)

    assert service.delete_portable_recipe(recipe.recipe_id) == recipe
    with pytest.raises(FileNotFoundError):
        service._portable_recipes.load_recipe(recipe.recipe_id)


def test_recipe_collection_deletion_ignores_artifact_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma", kind="indicator", parameters={"period": 10},
        output_names=("sma_10",),
    )
    service._portable_recipes.save_recipe(recipe)
    provenance = PortableRecipeProvenanceV1.build(
        recipe_id=recipe.recipe_id,
        origin_market_id=MARKET,
        study_environment_id="env_collection_delete",
        study_environment_content_hash="c" * 64,
        study_environment_updated_at_utc=datetime(2026, 8, 17, tzinfo=UTC),
        study_environment_display_name="Collection deletion",
        study_entry_id="entry_sma",
        study_display_name="SMA",
        study_description="",
    )
    service._portable_recipes.save_provenance(provenance)
    collection = service._portable_recipes.create_collection(
        "Collection", "", (recipe.recipe_id,), (recipe.recipe_id,)
    )
    artifact_collection = SimpleNamespace(
        source_recipe_collection_id=collection.collection_id,
        source_recipe_collection_revision_id=collection.revision_id,
    )
    monkeypatch.setattr(
        service,
        "_artifact_collection_revisions_for_deletion_proof",
        lambda: (artifact_collection,),
    )
    invalidations: list[bool] = []
    monkeypatch.setattr(service._updates, "invalidate", lambda: invalidations.append(True))

    assert service.delete_recipe_collection(collection.collection_id) == collection
    assert invalidations == [True]
    with pytest.raises(FileNotFoundError):
        service._portable_recipes.load_collection(collection.collection_id)
    assert service._portable_recipes.load_recipe(recipe.recipe_id) == recipe
    assert service._portable_recipes.list_provenance(recipe.recipe_id) == (provenance,)
    assert artifact_collection.source_recipe_collection_id == collection.collection_id
    assert artifact_collection.source_recipe_collection_revision_id == collection.revision_id


def test_managed_artifact_and_artifact_collection_deletion_are_dependency_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    logical_id = "c" * 64
    member = SimpleNamespace(
        version_key=SimpleNamespace(logical_artifact_id=logical_id)
    )
    collection = SimpleNamespace(
        market_id=MARKET,
        members=(member,),
        source_recipe_collection_id=None,
        source_portable_recipe_ids=(),
    )
    monkeypatch.setattr(
        service,
        "_artifact_collection_revisions_for_deletion_proof",
        lambda: (collection,),
    )
    monkeypatch.setattr(service, "_database_revisions_for_deletion_proof", lambda: ())
    with pytest.raises(DataManagerOperationError, match="Artifact Collection"):
        service.delete_managed_artifact(MARKET, logical_id)
    assert artifacts.managed_deleted == []

    monkeypatch.setattr(
        service, "_artifact_collection_revisions_for_deletion_proof", lambda: ()
    )
    monkeypatch.setattr(
        service,
        "_database_revisions_for_deletion_proof",
        lambda: (SimpleNamespace(
            artifact_version_keys=(SimpleNamespace(logical_artifact_id=logical_id),),
        ),),
    )
    with pytest.raises(DataManagerOperationError, match="Database"):
        service.delete_managed_artifact(MARKET, logical_id)
    assert artifacts.managed_deleted == []

    monkeypatch.setattr(service, "_database_revisions_for_deletion_proof", lambda: ())
    deleted = service.delete_managed_artifact(MARKET, logical_id)
    assert deleted.logical_artifact_id == logical_id
    assert artifacts.managed_deleted == [(MARKET, logical_id)]

    expected_collection = SimpleNamespace(collection_id="ac_" + "d" * 32)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        service.creation_store,
        "delete_collection",
        lambda collection_id, before_delete=None: (
            before_delete() if before_delete is not None else None,
            calls.append((collection_id, before_delete is not None)),
            expected_collection,
        )[-1],
    )
    assert service.delete_artifact_collection(expected_collection.collection_id) is expected_collection
    assert calls == [(expected_collection.collection_id, False)]


def test_invalid_artifact_reference_evidence_refuses_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    monkeypatch.setattr(
        service,
        "_artifact_collection_revisions_for_deletion_proof",
        lambda: (_ for _ in ()).throw(ValueError("invalid historical revision")),
    )
    with pytest.raises(DataManagerOperationError, match="could not prove"):
        service.delete_managed_artifact(MARKET, "c" * 64)
    assert artifacts.managed_deleted == []


def test_duplicate_maintenance_recipes_zero_result_and_invalid_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(root=tmp_path / "data_manager")
    preflight = service.prepare_duplicate_maintenance("recipes")
    zero = service.scan_duplicate_maintenance(preflight)
    assert preflight.scope_label == "Global"
    assert zero.objects_scanned == 0
    assert zero.groups == ()
    assert zero.duplicate_objects == 0
    assert zero.safe_to_purge == 0
    assert zero.blocked == 0
    assert zero.invalid_skipped == 0
    assert zero.review_required == 0

    invalid = PortableRecipeSummary(
        "f" * 64,
        "",
        "",
        "",
        (),
        0,
        0,
        False,
        "invalid persisted Recipe",
    )
    monkeypatch.setattr(
        service._portable_recipes,
        "list_recipe_summaries",
        lambda: (invalid,),
    )
    preflight = service.prepare_duplicate_maintenance("recipes")
    result = service.scan_duplicate_maintenance(preflight)
    assert result.objects_scanned == 1
    assert result.groups == ()
    assert result.invalid_skipped == 1
    assert result.invalid_candidates[0].classification == "INVALID / SKIPPED"


def test_duplicate_maintenance_recipe_uses_oldest_authoritative_timestamp(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    first_recipe_id = "f" * 64
    last_recipe_id = "a" * 64
    second_at = datetime(2026, 9, 4, 11, 0, tzinfo=UTC)
    service._portable_recipes._clock = lambda: second_at
    service._portable_recipes.save_recipe(recipe)
    _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        first_recipe_id,
        first_persisted_at_utc=second_at - timedelta(hours=1),
    )
    _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        last_recipe_id,
        first_persisted_at_utc=second_at + timedelta(hours=1),
    )

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    assert result.objects_scanned == 3
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.canonical_id == first_recipe_id
    assert group.tool_key == "sma"
    assert group.parameters_label == '{"period": 20}'
    assert tuple(item.object_id for item in group.duplicates) == tuple(
        sorted((last_recipe_id, recipe.recipe_id))
    )
    assert all(item.classification == "SAFE" for item in group.duplicates)
    assert result.duplicate_objects == 2
    assert result.safe_to_purge == 2


def test_duplicate_maintenance_recipe_equal_timestamp_uses_recipe_id_tie_break(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    persisted_at = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    service._portable_recipes._clock = lambda: persisted_at
    service._portable_recipes.save_recipe(recipe)
    legacy_recipe_id = "f" * 64
    _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=persisted_at,
    )

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    expected_winner = min(recipe.recipe_id, legacy_recipe_id)
    assert result.groups[0].canonical_id == expected_winner
    assert result.groups[0].duplicates[0].object_id == max(
        recipe.recipe_id, legacy_recipe_id
    )


def test_duplicate_maintenance_uses_only_tool_parameters_and_actual_inputs(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="angle_momentum",
        kind="construct",
        parameters={"n": 3},
        output_names=("angle_momentum_close",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("source_1", "close"),),
    )
    service._portable_recipes.save_recipe(recipe)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    for index, character in enumerate("abcdef", start=1):
        _publish_legacy_recipe(
            service._portable_recipes,
            recipe,
            character * 64,
            first_persisted_at_utc=(
                metadata.first_persisted_at_utc + timedelta(minutes=index)
            ),
        )
    for variant in (
        build_portable_recipe(
            tool_key="angle_momentum",
            kind="construct",
            parameters={"n": 4},
            output_names=("angle_momentum_close",),
            ohlcv_inputs=(PortableRecipeOHLCVInputV1("source_1", "close"),),
        ),
        build_portable_recipe(
            tool_key="angle_momentum",
            kind="construct",
            parameters={"n": 3},
            output_names=("angle_momentum_open",),
            ohlcv_inputs=(PortableRecipeOHLCVInputV1("source_1", "open"),),
        ),
        build_portable_recipe(
            tool_key="derivative",
            kind="construct",
            parameters={"n": 3},
            output_names=("derivative_close",),
            ohlcv_inputs=(PortableRecipeOHLCVInputV1("source_1", "close"),),
        ),
    ):
        service._portable_recipes.save_recipe(variant)

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    assert result.objects_scanned == 10
    assert len(result.groups) == 1
    assert result.groups[0].canonical_id == recipe.recipe_id
    assert len(result.groups[0].duplicates) == 6
    assert result.duplicate_objects == 6


def test_recipe_and_collection_semantics_resolve_dependency_recipe_ids(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    implicit = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    explicit = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    derivatives = tuple(
        build_portable_recipe(
            tool_key="derivative",
            kind="construct",
            parameters={"order": 1},
            output_names=("derivative_sma",),
            dependencies=(
                PortableRecipeDependencyV1(
                    "source", source.recipe_id, "sma_20"
                ),
            ),
        )
        for source in (implicit, explicit)
    )
    different_derivative = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"order": 2},
        output_names=("derivative_sma",),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", explicit.recipe_id, "sma_20"
            ),
        ),
    )
    for item in (implicit, explicit, *derivatives, different_derivative):
        service._portable_recipes.save_recipe(item)

    recipe_scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )
    derivative_group = next(
        item for item in recipe_scan.groups if item.tool_key == "derivative"
    )
    assert len(derivative_group.duplicates) == 1

    collections = tuple(
        PortableRecipeCollectionRevisionV1.build(
            collection_id=f"prc_{index * 32}",
            display_name=f"Collection {index}",
            description="",
            root_recipe_ids=(derivative.recipe_id,),
            member_recipe_ids=(source.recipe_id, derivative.recipe_id),
            previous_revision_id=None,
            created_at_utc=datetime(2026, 8, position, tzinfo=UTC),
        )
        for position, (index, source, derivative) in enumerate(
            zip(("1", "2"), (implicit, explicit), derivatives, strict=True),
            start=1,
        )
    )
    different_collection = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_33333333333333333333333333333333",
        display_name="Different Collection",
        description="",
        root_recipe_ids=(different_derivative.recipe_id,),
        member_recipe_ids=(explicit.recipe_id, different_derivative.recipe_id),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 3, tzinfo=UTC),
    )
    for revision in (*collections, different_collection):
        service._portable_recipes._publish_revision(
            revision, updated_at_utc=revision.created_at_utc
        )
    collection_scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipe_collections")
    )
    assert collection_scan.objects_scanned == 3
    assert len(collection_scan.groups) == 1
    assert collection_scan.duplicate_objects == 1
    assert different_collection.collection_id not in {
        collection_scan.groups[0].canonical_id,
        *(
            item.object_id
            for item in collection_scan.groups[0].duplicates
        ),
    }


def test_recipe_collection_creation_reuses_semantically_equivalent_graph(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    implicit = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    explicit = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
        ohlcv_inputs=(PortableRecipeOHLCVInputV1("close", "close"),),
    )
    derivatives = tuple(
        build_portable_recipe(
            tool_key="derivative",
            kind="construct",
            parameters={"order": order},
            output_names=("derivative_sma",),
            dependencies=(
                PortableRecipeDependencyV1(
                    "source", source.recipe_id, "sma_20"
                ),
            ),
        )
        for source, order in ((implicit, 1), (explicit, 1), (explicit, 2))
    )
    for recipe in (implicit, explicit, *derivatives):
        service._portable_recipes.save_recipe(recipe)

    original = service.create_recipe_collection(
        "Original", "", (derivatives[0].recipe_id,)
    )
    reused = service.create_recipe_collection(
        "Equivalent", "different metadata", (derivatives[1].recipe_id,)
    )
    different = service.create_recipe_collection(
        "Different", "", (derivatives[2].recipe_id,)
    )

    assert reused.collection.collection_id == original.collection.collection_id
    assert reused.collection.revision_id == original.collection.revision_id
    assert different.collection.collection_id != original.collection.collection_id
    assert len(service._portable_recipes.list_collection_summaries()) == 2


def test_duplicate_maintenance_recipe_without_canonical_winner_requires_review(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    legacy_ids = ("e" * 64, "f" * 64)
    for legacy_recipe_id in legacy_ids:
        _publish_legacy_recipe(
            service._portable_recipes, recipe, legacy_recipe_id
        )

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    assert len(result.groups) == 1
    assert result.groups[0].canonical_id == ""
    assert tuple(
        item.object_id for item in result.groups[0].duplicates
    ) == legacy_ids
    assert all(
        item.classification == "REVIEW REQUIRED"
        for item in result.groups[0].duplicates
    )
    assert result.duplicate_objects == 2
    assert result.safe_to_purge == 0
    assert result.review_required == 2


def test_duplicate_maintenance_recipe_dependency_reference_blocks_candidate(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    legacy_recipe_id = "f" * 64
    service._portable_recipes.save_recipe(recipe)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=(
            metadata.first_persisted_at_utc + timedelta(minutes=1)
        ),
    )
    dependent = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"order": 1},
        output_names=("legacy_d1",),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", legacy_recipe_id, recipe.output_names[0]
            ),
        ),
    )
    service._portable_recipes.save_recipe(dependent)

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    candidate = result.groups[0].duplicates[0]
    assert candidate.classification == "BLOCKED"
    assert candidate.blockers == (f"Recipe {dependent.recipe_id}",)


def test_duplicate_maintenance_recipe_collection_reference_blocks_candidate(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    legacy_recipe_id = "f" * 64
    service._portable_recipes.save_recipe(recipe)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=(
            metadata.first_persisted_at_utc + timedelta(minutes=1)
        ),
    )
    revision = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_11111111111111111111111111111111",
        display_name="Legacy membership",
        description="",
        root_recipe_ids=(legacy_recipe_id,),
        member_recipe_ids=(legacy_recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    service._portable_recipes._publish_revision(
        revision, updated_at_utc=revision.created_at_utc
    )

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    candidate = result.groups[0].duplicates[0]
    assert candidate.classification == "BLOCKED"
    assert candidate.blockers == (
        f"Recipe Collection {revision.collection_id} revision "
        f"{revision.revision_id}",
    )


def test_duplicate_maintenance_recipe_safe_purge_removes_only_legacy_candidate(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    unrelated = build_portable_recipe(
        tool_key="rsi",
        kind="oscillator",
        parameters={"period": 14},
        output_names=("rsi_14",),
    )
    legacy_recipe_id = "f" * 64
    service._portable_recipes.save_recipe(recipe)
    service._portable_recipes.save_recipe(unrelated)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    legacy_path = _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=(
            metadata.first_persisted_at_utc + timedelta(minutes=1)
        ),
    )
    provenance = PortableRecipeProvenanceV1.build(
        recipe_id=legacy_recipe_id,
        origin_market_id=MARKET,
        study_environment_id="env_legacy",
        study_environment_content_hash="a" * 64,
        study_environment_updated_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
        study_environment_display_name="Legacy",
        study_entry_id="entry_legacy",
        study_display_name="Legacy SMA",
        study_description="",
    )
    provenance_path = (
        service._portable_recipes.root_dir
        / "recipe_provenance"
        / legacy_recipe_id
        / f"{provenance.provenance_id}.json"
    )
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_bytes(provenance.canonical_json_bytes())
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )

    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 1
    assert result.details[0].candidate_id == legacy_recipe_id
    assert result.details[0].winner_id == recipe.recipe_id
    assert not legacy_path.exists()
    assert not provenance_path.parent.exists()
    assert service._portable_recipes.load_recipe(recipe.recipe_id) == recipe
    assert service._portable_recipes.load_recipe(unrelated.recipe_id) == unrelated


def test_duplicate_purge_revalidates_authoritative_recipe_timestamps(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    canonical_at = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    service._portable_recipes._clock = lambda: canonical_at
    service._portable_recipes.save_recipe(recipe)
    legacy_recipe_id = "f" * 64
    legacy_path = _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=canonical_at + timedelta(hours=1),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )
    assert scan.groups[0].canonical_id == recipe.recipe_id
    assert scan.groups[0].duplicates[0].object_id == legacy_recipe_id

    _publish_recipe_metadata(
        service._portable_recipes,
        legacy_recipe_id,
        canonical_at - timedelta(hours=1),
    )
    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 0
    assert result.skipped_stale == 1
    assert legacy_path.exists()
    assert service._portable_recipes.load_recipe(recipe.recipe_id) == recipe


def test_duplicate_purge_recipe_revalidates_new_recipe_dependency_blocker(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    legacy_recipe_id = "f" * 64
    service._portable_recipes.save_recipe(recipe)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    legacy_path = _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=(
            metadata.first_persisted_at_utc + timedelta(minutes=1)
        ),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )
    dependent = build_portable_recipe(
        tool_key="derivative",
        kind="construct",
        parameters={"order": 1},
        output_names=("legacy_d1",),
        dependencies=(
            PortableRecipeDependencyV1(
                "source", legacy_recipe_id, recipe.output_names[0]
            ),
        ),
    )
    service._portable_recipes.save_recipe(dependent)

    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 0
    assert result.blocked_during_revalidation == 1
    assert legacy_path.exists()


def test_duplicate_purge_recipe_revalidates_new_collection_membership_blocker(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    legacy_recipe_id = "f" * 64
    service._portable_recipes.save_recipe(recipe)
    metadata = service._portable_recipes.load_persistence_metadata(recipe.recipe_id)
    assert metadata is not None
    assert metadata.first_persisted_at_utc is not None
    legacy_path = _publish_legacy_recipe(
        service._portable_recipes,
        recipe,
        legacy_recipe_id,
        first_persisted_at_utc=(
            metadata.first_persisted_at_utc + timedelta(minutes=1)
        ),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipes")
    )
    revision = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_11111111111111111111111111111111",
        display_name="Late membership",
        description="",
        root_recipe_ids=(legacy_recipe_id,),
        member_recipe_ids=(legacy_recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    service._portable_recipes._publish_revision(
        revision, updated_at_utc=revision.created_at_utc
    )

    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 0
    assert result.blocked_during_revalidation == 1
    assert legacy_path.exists()


def test_portable_recipe_catalog_projects_one_row_for_multiple_provenances(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    service._portable_recipes.save_recipe(recipe)
    for index in (1, 2):
        service._portable_recipes.save_provenance(
            PortableRecipeProvenanceV1.build(
                recipe_id=recipe.recipe_id,
                origin_market_id=MARKET,
                study_environment_id=f"env_{index}",
                study_environment_content_hash=f"{index}" * 64,
                study_environment_updated_at_utc=datetime(
                    2026, 8, index, tzinfo=UTC
                ),
                study_environment_display_name=f"Environment {index}",
                study_entry_id=f"entry_{index}",
                study_display_name="SMA",
                study_description="",
            )
        )

    catalog = service.scan_portable_recipes()

    assert len(catalog.recipes) == 1
    assert catalog.recipes[0].recipe_id == recipe.recipe_id
    assert catalog.recipes[0].provenance_count == 2
    assert catalog.recipes[0].first_persisted_at_utc is not None
    assert catalog.recipes[0].origin_kinds == ("study_environment",)


def test_duplicate_maintenance_recipe_collection_uses_oldest_semantic_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe = build_portable_recipe(
        tool_key="sma",
        kind="indicator",
        parameters={"period": 20},
        output_names=("sma_20",),
    )
    service._portable_recipes.save_recipe(recipe)
    older = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_11111111111111111111111111111111",
        display_name="Original",
        description="Original metadata",
        root_recipe_ids=(recipe.recipe_id,),
        member_recipe_ids=(recipe.recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    younger = PortableRecipeCollectionRevisionV1.build(
        collection_id="prc_22222222222222222222222222222222",
        display_name="Different display name",
        description="Different metadata",
        root_recipe_ids=(recipe.recipe_id,),
        member_recipe_ids=(recipe.recipe_id,),
        previous_revision_id=None,
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
    )
    revisions = {
        older.collection_id: older,
        younger.collection_id: younger,
    }
    summaries = tuple(
        PortableRecipeCollectionSummary(
            item.collection_id,
            item.revision_id,
            item.display_name,
            item.description,
            1,
            1,
            item.created_at_utc,
            item.created_at_utc,
        )
        for item in revisions.values()
    )
    monkeypatch.setattr(
        service._portable_recipes,
        "list_collection_summaries",
        lambda: summaries,
    )
    monkeypatch.setattr(
        service._portable_recipes,
        "load_collection",
        lambda collection_id: revisions[collection_id],
    )

    preflight = service.prepare_duplicate_maintenance("recipe_collections")
    progress: list[tuple[int, int, str]] = []
    result = service.scan_duplicate_maintenance(
        preflight,
        progress=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert preflight.objects_to_check == 2
    assert result.objects_scanned == 2
    assert len(result.groups) == 1
    assert result.groups[0].canonical_id == older.collection_id
    assert result.groups[0].duplicates[0].object_id == younger.collection_id
    assert result.groups[0].duplicates[0].classification == "SAFE"
    assert result.safe_to_purge == 1
    assert progress[-1][:2] == (2, 2)
    assert progress[-1][2] == "Scanning Recipe Collections 2 / 2"


def test_artifact_duplicate_maintenance_uses_selected_dataframe_semantics(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    first = _install_managed_artifact(
        artifacts,
        portable_recipe_id="3" * 64,
        artifact_id="4" * 64,
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    duplicate = _install_managed_artifact(
        artifacts,
        portable_recipe_id="6" * 64,
        artifact_id="7" * 64,
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
    )
    different_input = _install_managed_artifact(
        artifacts,
        portable_recipe_id="8" * 64,
        artifact_id="9" * 64,
        created_at_utc=datetime(2026, 8, 3, tzinfo=UTC),
        column_name="open",
    )
    other_market = MarketId("bybit", "linear", "ETHUSDT", "1h")
    other_source = OHLCVSourceFingerprintV1(
        other_market,
        "a" * 64,
        "b" * 64,
        6,
        1,
        6,
        "committed",
        "ok",
        "1.0",
    )
    _install_managed_artifact(
        artifacts,
        portable_recipe_id="c" * 64,
        artifact_id="d" * 64,
        created_at_utc=datetime(2026, 8, 4, tzinfo=UTC),
        market=other_market,
        source=other_source,
    )
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifacts", MARKET)
    )

    assert result.objects_scanned == 3
    assert len(result.groups) == 1
    assert result.duplicate_objects == 1
    assert result.groups[0].canonical_id == first.logical_artifact_id
    assert result.groups[0].duplicates[0].object_id == duplicate.logical_artifact_id
    assert different_input.logical_artifact_id not in {
        result.groups[0].canonical_id,
        *(item.object_id for item in result.groups[0].duplicates),
    }


def test_artifact_collection_duplicates_use_member_semantics_not_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="4" * 64
    )
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="7" * 64
    )
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="9" * 64, column_name="open"
    )
    revisions = (
        _artifact_collection_revision(
            collection_id="ac_11111111111111111111111111111111",
            display_name="Original",
            created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
            source=artifacts.source,
            portable_recipe_id="3" * 64,
            artifact_id="4" * 64,
        ),
        _artifact_collection_revision(
            collection_id="ac_22222222222222222222222222222222",
            display_name="Different name",
            created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
            source=artifacts.source,
            portable_recipe_id="6" * 64,
            artifact_id="7" * 64,
        ),
        _artifact_collection_revision(
            collection_id="ac_33333333333333333333333333333333",
            display_name="Different input",
            created_at_utc=datetime(2026, 8, 3, tzinfo=UTC),
            source=artifacts.source,
            portable_recipe_id="8" * 64,
            artifact_id="9" * 64,
        ),
    )
    by_id = {item.collection_id: item for item in revisions}
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    monkeypatch.setattr(
        service.creation_store,
        "list_collection_ids",
        lambda: tuple(by_id),
    )
    monkeypatch.setattr(
        service.creation_store,
        "load_collection",
        lambda collection_id: by_id[collection_id],
    )
    monkeypatch.setattr(
        service, "_database_revisions_for_deletion_proof", lambda: ()
    )

    result = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifact_collections", MARKET)
    )

    assert result.objects_scanned == 3
    assert len(result.groups) == 1
    assert result.duplicate_objects == 1
    assert result.groups[0].canonical_id == revisions[0].collection_id
    assert result.groups[0].duplicates[0].object_id == revisions[1].collection_id
    assert revisions[2].collection_id not in {
        result.groups[0].canonical_id,
        *(item.object_id for item in result.groups[0].duplicates),
    }


def test_artifact_collection_creation_reuses_semantic_members_across_ids(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="4" * 64
    )
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="7" * 64
    )
    _install_artifact_collection_member_metadata(
        artifacts, artifact_id="9" * 64, column_name="open"
    )
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")

    def create(
        *,
        portable_recipe_id: str,
        artifact_id: str,
        display_name: str,
        created_at_utc: datetime,
    ) -> ArtifactCollectionRevisionV1:
        logical_id = compute_logical_artifact_id(MARKET, portable_recipe_id)
        member = ArtifactCollectionMemberV1(
            ManagedArtifactVersionKey(logical_id, artifact_id),
            portable_recipe_id,
            "sma",
            "indicator",
            ("sma_20",),
            "5" * 64,
        )
        output = ArtifactCollectionOutputV1(
            logical_id, "sma_20", "sma_20"
        )
        return service.creation_store.create_collection_revision(
            market_id=MARKET,
            source_ohlcv=artifacts.source,
            root_logical_artifact_ids=(logical_id,),
            support_logical_artifact_ids=(),
            members=(member,),
            selected_outputs=(output,),
            presentation_order=(output.column_name,),
            revision_factory=lambda collection_id: _artifact_collection_revision(
                collection_id=collection_id,
                display_name=display_name,
                created_at_utc=created_at_utc,
                source=artifacts.source,
                portable_recipe_id=portable_recipe_id,
                artifact_id=artifact_id,
            ),
        )

    original = create(
        portable_recipe_id="3" * 64,
        artifact_id="4" * 64,
        display_name="Original",
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
    )
    reused = create(
        portable_recipe_id="6" * 64,
        artifact_id="7" * 64,
        display_name="Equivalent",
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
    )
    different = create(
        portable_recipe_id="8" * 64,
        artifact_id="9" * 64,
        display_name="Different",
        created_at_utc=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert reused.collection_id == original.collection_id
    assert reused.revision_id == original.revision_id
    assert different.collection_id != original.collection_id
    assert len(service.creation_store.list_collection_ids()) == 2


def test_duplicate_maintenance_artifact_history_is_excluded(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    portable_recipe_id = "3" * 64
    logical_artifact_id = compute_logical_artifact_id(MARKET, portable_recipe_id)
    older_artifact_id = "4" * 64
    current_artifact_id = "5" * 64
    created = datetime(2026, 8, 1, tzinfo=UTC)
    summary = ManagedArtifactSummary(
        logical_artifact_id,
        portable_recipe_id,
        MARKET,
        current_artifact_id,
        older_artifact_id,
        "sma",
        "indicator",
        ("sma_20",),
        6,
        1,
        6,
        created,
    )
    artifacts.managed_artifacts[MARKET] = (summary,)
    artifacts.artifacts_by_id[current_artifact_id] = SimpleNamespace(
        artifact_id=current_artifact_id,
        recipe=SimpleNamespace(market_id=MARKET),
        source_ohlcv=artifacts.source,
    )
    artifacts.managed_versions[(MARKET, logical_artifact_id)] = (
        ArtifactVersionRecordV1(
            logical_artifact_id,
            older_artifact_id,
            portable_recipe_id,
            MARKET,
            None,
            created,
        ),
        ArtifactVersionRecordV1(
            logical_artifact_id,
            current_artifact_id,
            portable_recipe_id,
            MARKET,
            older_artifact_id,
            datetime(2026, 8, 2, tzinfo=UTC),
        ),
    )
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")

    preflight = service.prepare_duplicate_maintenance("artifacts", MARKET)
    result = service.scan_duplicate_maintenance(preflight)

    assert preflight.objects_to_check == 1
    assert result.objects_scanned == 1
    assert result.groups == ()
    assert result.duplicate_objects == 0
    assert result.historical_versions_excluded == 1


def test_duplicate_maintenance_artifact_collection_safe_and_database_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    _install_artifact_collection_member_metadata(artifacts)
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    older = _artifact_collection_revision(
        collection_id="ac_11111111111111111111111111111111",
        display_name="Original",
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
        source=artifacts.source,
    )
    younger = _artifact_collection_revision(
        collection_id="ac_22222222222222222222222222222222",
        display_name="Equivalent",
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
        source=artifacts.source,
    )
    revisions = {
        older.collection_id: older,
        younger.collection_id: younger,
    }
    monkeypatch.setattr(
        service.creation_store,
        "list_collection_ids",
        lambda: tuple(revisions),
    )
    monkeypatch.setattr(
        service.creation_store,
        "load_collection",
        lambda collection_id: revisions[collection_id],
    )
    monkeypatch.setattr(
        service,
        "_database_revisions_for_deletion_proof",
        lambda: (),
    )

    preflight = service.prepare_duplicate_maintenance(
        "artifact_collections", MARKET
    )
    safe = service.scan_duplicate_maintenance(preflight)
    assert preflight.objects_to_check == 2
    assert len(safe.groups) == 1
    assert safe.groups[0].canonical_id == older.collection_id
    assert safe.groups[0].duplicates[0].object_id == younger.collection_id
    assert safe.groups[0].duplicates[0].classification == "SAFE"
    assert safe.safe_to_purge == 1

    database = SimpleNamespace(
        database_id="db_33333333333333333333333333333333",
        revision_id="6" * 64,
        collection_id=younger.collection_id,
    )
    monkeypatch.setattr(
        service,
        "_database_revisions_for_deletion_proof",
        lambda: (database,),
    )
    blocked = service.scan_duplicate_maintenance(preflight)
    candidate = blocked.groups[0].duplicates[0]
    assert candidate.classification == "BLOCKED"
    assert candidate.blockers == (
        f"Database {database.database_id} revision {database.revision_id}",
    )
    assert blocked.blocked == 1


def test_duplicate_maintenance_refuses_missing_or_stale_artifact_scope(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    with pytest.raises(DataManagerOperationError, match="selected accepted dataset"):
        service.prepare_duplicate_maintenance("artifacts")

    preflight = service.prepare_duplicate_maintenance("artifacts", MARKET)
    artifacts.source = OHLCVSourceFingerprintV1(
        MARKET,
        "7" * 64,
        "2" * 64,
        6,
        1,
        6,
        "committed",
        "ok",
        "1.0",
    )
    with pytest.raises(DataManagerOperationError, match="source changed"):
        service.scan_duplicate_maintenance(preflight)


def test_duplicate_purge_deletes_younger_recipe_collection_and_retains_members(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    recipe, (winner, duplicate) = _publish_recipe_collection_duplicates(
        service,
        (
            "prc_11111111111111111111111111111111",
            "prc_22222222222222222222222222222222",
        ),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipe_collections")
    )
    destructive: list[bool] = []
    progress: list[tuple[int, int, str]] = []

    result = service.purge_duplicate_maintenance(
        scan,
        progress=lambda current, total, message: progress.append(
            (current, total, message)
        ),
        before_delete=lambda: destructive.append(True),
    )

    assert result.candidates_requested == 1
    assert result.purged == 1
    assert result.blocked_during_revalidation == 0
    assert result.skipped_stale == 0
    assert result.failed == 0
    assert result.canonical_winners_retained == 1
    assert result.details[0].result == "PURGED"
    assert destructive == [True]
    assert progress == [
        (1, 1, "Purging Recipe Collections duplicates 1 / 1")
    ]
    assert service._portable_recipes.load_collection(winner.collection_id) == winner
    with pytest.raises(FileNotFoundError):
        service._portable_recipes.load_collection(duplicate.collection_id)
    assert service._portable_recipes.load_recipe(recipe.recipe_id) == recipe


def test_duplicate_purge_skips_recipe_collection_that_disappeared_after_scan(
    tmp_path: Path,
) -> None:
    service = _service(root=tmp_path / "data_manager")
    _recipe, (_winner, duplicate) = _publish_recipe_collection_duplicates(
        service,
        (
            "prc_11111111111111111111111111111111",
            "prc_22222222222222222222222222222222",
        ),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipe_collections")
    )
    service._portable_recipes.delete_collection(duplicate.collection_id)

    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 0
    assert result.skipped_stale == 1
    assert result.details[0].result == "SKIPPED STALE"


def test_duplicate_purge_is_partial_and_continues_after_ordinary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(root=tmp_path / "data_manager")
    _recipe, (_winner, first, second) = _publish_recipe_collection_duplicates(
        service,
        (
            "prc_11111111111111111111111111111111",
            "prc_22222222222222222222222222222222",
            "prc_33333333333333333333333333333333",
        ),
    )
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("recipe_collections")
    )
    original = service._delete_recipe_collection
    attempted: list[str] = []

    def delete(collection_id: str, *, before_delete):
        attempted.append(collection_id)
        if collection_id == first.collection_id:
            raise OSError("ordinary test persistence failure")
        return original(collection_id, before_delete=before_delete)

    monkeypatch.setattr(service, "_delete_recipe_collection", delete)

    result = service.purge_duplicate_maintenance(scan)

    assert attempted == [first.collection_id, second.collection_id]
    assert result.purged == 1
    assert result.failed == 1
    assert service._portable_recipes.load_collection(first.collection_id) == first
    with pytest.raises(FileNotFoundError):
        service._portable_recipes.load_collection(second.collection_id)


def test_duplicate_purge_deletes_artifact_collection_but_revalidates_database_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = _Artifacts()
    _install_artifact_collection_member_metadata(artifacts)
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    winner = _artifact_collection_revision(
        collection_id="ac_11111111111111111111111111111111",
        display_name="Original",
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
        source=artifacts.source,
    )
    duplicate = _artifact_collection_revision(
        collection_id="ac_22222222222222222222222222222222",
        display_name="Duplicate",
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
        source=artifacts.source,
    )
    service.creation_store._publish_collection_revision(winner)
    service.creation_store._publish_collection_revision(duplicate)
    monkeypatch.setattr(service, "_database_revisions_for_deletion_proof", lambda: ())
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifact_collections", MARKET)
    )

    purged = service.purge_duplicate_maintenance(scan)

    assert purged.purged == 1
    assert service.creation_store.load_collection(winner.collection_id) == winner
    with pytest.raises(FileNotFoundError):
        service.creation_store.load_collection(duplicate.collection_id)

    blocked_duplicate = _artifact_collection_revision(
        collection_id="ac_33333333333333333333333333333333",
        display_name="Blocked duplicate",
        created_at_utc=datetime(2026, 8, 3, tzinfo=UTC),
        source=artifacts.source,
    )
    service.creation_store._publish_collection_revision(blocked_duplicate)
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifact_collections", MARKET)
    )
    database = SimpleNamespace(
        database_id="db_44444444444444444444444444444444",
        revision_id="6" * 64,
        collection_id=blocked_duplicate.collection_id,
    )
    monkeypatch.setattr(
        service, "_database_revisions_for_deletion_proof", lambda: (database,)
    )

    blocked = service.purge_duplicate_maintenance(scan)

    assert blocked.purged == 0
    assert blocked.blocked_during_revalidation == 1
    assert service.creation_store.load_collection(blocked_duplicate.collection_id) == blocked_duplicate


def test_duplicate_purge_zero_candidates_preserves_artifact_history(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    portable_recipe_id = "3" * 64
    logical_id = compute_logical_artifact_id(MARKET, portable_recipe_id)
    created = datetime(2026, 8, 1, tzinfo=UTC)
    artifacts.managed_artifacts[MARKET] = (
        ManagedArtifactSummary(
            logical_id,
            portable_recipe_id,
            MARKET,
            "5" * 64,
            "4" * 64,
            "sma",
            "indicator",
            ("sma_20",),
            6,
            1,
            6,
            created,
        ),
    )
    artifacts.artifacts_by_id["5" * 64] = SimpleNamespace(
        artifact_id="5" * 64,
        recipe=SimpleNamespace(market_id=MARKET),
        source_ohlcv=artifacts.source,
    )
    artifacts.managed_versions[(MARKET, logical_id)] = (
        ArtifactVersionRecordV1(
            logical_id, "4" * 64, portable_recipe_id, MARKET, None, created
        ),
        ArtifactVersionRecordV1(
            logical_id,
            "5" * 64,
            portable_recipe_id,
            MARKET,
            "4" * 64,
            datetime(2026, 8, 2, tzinfo=UTC),
        ),
    )
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifacts", MARKET)
    )

    result = service.purge_duplicate_maintenance(scan)

    assert result.candidates_requested == 0
    assert result.details == ()
    assert result.purged == 0
    assert artifacts.managed_deleted == []
    assert len(artifacts.managed_versions[(MARKET, logical_id)]) == 2


def test_duplicate_purge_never_dispatches_candidate_equal_to_canonical_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(root=tmp_path / "data_manager")
    domain = service.prepare_duplicate_maintenance("recipe_collections").domain
    object_id = "prc_11111111111111111111111111111111"
    scan = DuplicateMaintenanceScanResult(
        DuplicateMaintenancePreflight(domain, 1),
        datetime(2026, 8, 20, tzinfo=UTC),
        1,
        (
            DuplicateMaintenanceGroup(
                domain,
                object_id,
                (
                    DuplicateMaintenanceCandidate(
                        object_id, "SAFE", "malformed stale GUI state"
                    ),
                ),
                "Malformed group",
            ),
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        service,
        "_delete_duplicate_candidate",
        lambda _preflight, candidate_id, **_values: dispatched.append(candidate_id),
    )

    result = service.purge_duplicate_maintenance(scan)

    assert dispatched == []
    assert result.failed == 1
    assert result.details[0].reason == "invalid purge candidate equals canonical winner"


def test_duplicate_purge_blocks_changed_artifact_collection_ohlcv_scope(
    tmp_path: Path,
) -> None:
    artifacts = _Artifacts()
    _install_artifact_collection_member_metadata(artifacts)
    service = _service(artifacts=artifacts, root=tmp_path / "data_manager")
    winner = _artifact_collection_revision(
        collection_id="ac_11111111111111111111111111111111",
        display_name="Original",
        created_at_utc=datetime(2026, 8, 1, tzinfo=UTC),
        source=artifacts.source,
    )
    duplicate = _artifact_collection_revision(
        collection_id="ac_22222222222222222222222222222222",
        display_name="Duplicate",
        created_at_utc=datetime(2026, 8, 2, tzinfo=UTC),
        source=artifacts.source,
    )
    service.creation_store._publish_collection_revision(winner)
    service.creation_store._publish_collection_revision(duplicate)
    scan = service.scan_duplicate_maintenance(
        service.prepare_duplicate_maintenance("artifact_collections", MARKET)
    )
    artifacts.source = OHLCVSourceFingerprintV1(
        MARKET,
        "7" * 64,
        "2" * 64,
        6,
        1,
        6,
        "committed",
        "ok",
        "1.0",
    )

    result = service.purge_duplicate_maintenance(scan)

    assert result.purged == 0
    assert result.blocked_during_revalidation == 1
    assert service.creation_store.load_collection(winner.collection_id) == winner
    assert service.creation_store.load_collection(duplicate.collection_id) == duplicate
