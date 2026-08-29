from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.artifacts import (
    ArtifactLineageError,
    ArtifactSummary,
    ArtifactValidationError,
    RecipeInUseError,
    RecipeSummary,
)
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerCatalogSnapshot,
    DataManagerManagedArtifactCatalog,
    DataManagerOperationError,
    DataManagerPortableRecipeCatalog,
    DataManagerRecipeCollectionCatalog,
    DataManagerReconciliationSnapshot,
    DataManagerService,
    DataManagerStudyEnvironmentCatalog,
)
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.data_manager.service import DataManagerMarketUnavailableError
from leonardo.recipes import (
    PortableRecipeGraphPlanner,
    PortableRecipeProvenanceV1,
    PortableRecipeStore,
    build_portable_recipe,
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


def test_product_catalog_scan_aggregates_each_family_once(monkeypatch) -> None:
    service = _service()
    reconciliation = DataManagerReconciliationSnapshot(
        datetime(2026, 8, 4, tzinfo=UTC), (), (), (), (), (), "0" * 64
    )
    calls: list[str] = []

    def value(name, result):
        def read(*_args, **_kwargs):
            calls.append(name)
            return result

        return read

    monkeypatch.setattr(service, "latest_update_status", value("reconcile", reconciliation))
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
    assert calls == [
        "reconcile",
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
