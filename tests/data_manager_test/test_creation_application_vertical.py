from __future__ import annotations

from dataclasses import replace
from threading import Event

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.core.core_runner import TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    BatchArtifactBranchRequest,
    BatchArtifactRequest,
    DataManagerArtifactMaterializationRequest,
)
from leonardo.financial_tools import resolve_output_names
from leonardo.research import StudyEnvironmentDraft

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.research_test.test_study_environment_models import fixture_environment


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1h")


def _completed(submit, *args, **kwargs):
    settled = Event()
    received: list[TaskResult] = []

    def receive(result: TaskResult) -> None:
        received.append(result)
        settled.set()

    submit(*args, **kwargs, result_callback=receive)
    assert settled.wait(10.0), f"Data Manager operation did not settle: {submit.__name__}"
    assert received[0].status == "completed", received[0]
    return received[0].value


def _save_upstream_environment(app: LeonardoApp) -> str:
    source = fixture_environment()
    saved = app.study_environment_store.create(
        StudyEnvironmentDraft(
            source.display_name,
            source.description,
            source.created_from,
            source.entries,
            source.environment_id,
        )
    )
    return saved.environment_id


def test_headless_creation_application_workflow_survives_restart(tmp_path) -> None:
    _market, source_frame = _accepted_dataset(
        tmp_path / "historical_data", market=MARKET
    )
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    environment_id = _save_upstream_environment(app)
    app.startup()
    app.start_core_runtime()
    application = app.data_manager_service
    try:
        environments = _completed(application.submit_scan_study_environments)
        assert tuple(item.environment_id for item in environments.environments) == (
            environment_id,
        )
        derivation_plan = _completed(
            application.submit_plan_recipe_derivation,
            environment_id,
            ("entry_003",),
        )
        assert not derivation_plan.blocked
        assert derivation_plan.support_entry_ids == ("entry_001", "entry_002")
        recipes = _completed(
            application.submit_persist_recipe_derivation,
            environment_id,
            ("entry_003",),
            create_collection=True,
            collection_display_name="Momentum Recipes",
            collection_description="Portable dependency graph",
        )
        assert recipes.collection_id is not None
        assert recipes.revision_id is not None
        recipe_collection = _completed(
            application.submit_inspect_recipe_collection, recipes.collection_id
        )
        assert recipe_collection.collection.revision_id == recipes.revision_id

        artifact_request = DataManagerArtifactMaterializationRequest(
            MARKET,
            recipe_collection_id=recipes.collection_id,
            recipe_collection_revision_id=recipes.revision_id,
        )
        artifact_plan = _completed(
            application.submit_plan_artifact_materialization, artifact_request
        )
        assert not artifact_plan.blocked
        materialization = _completed(
            application.submit_execute_artifact_materialization, artifact_plan
        )
        assert len(materialization.root_logical_artifact_ids) == 1
        assert len(materialization.support_logical_artifact_ids) == 2

        range_start = int(source_frame.ts_ms.iloc[5])
        range_end = int(source_frame.ts_ms.iloc[-5])
        seed = _completed(
            application.submit_create_database_seed,
            MARKET,
            "Momentum Database",
            description="Headless vertical Seed",
            selected_ohlcv_columns=("open", "close", "volume"),
            selected_range_start_ms=range_start,
            selected_range_end_ms=range_end,
        )
        assert _completed(application.submit_load_database_seed, seed.seed_id) == seed
        assert _completed(application.submit_inspect_database_seed, seed.seed_id) == seed
        assert _completed(application.submit_validate_database_seed, seed.seed_id) == (
            True,
            (),
        )
        collection = _completed(
            application.submit_create_artifact_collection,
            materialization,
            "Momentum Features",
            description="Base root and support Artifacts",
            source_recipe_collection_id=recipes.collection_id,
            source_recipe_collection_revision_id=recipes.revision_id,
        )
        assert collection.source_recipe_collection_id == recipes.collection_id
        assert collection.source_recipe_collection_revision_id == recipes.revision_id

        root = next(
            item
            for item in materialization.managed_artifacts
            if item.logical_artifact_id == materialization.root_logical_artifact_ids[0]
        )
        source_output = root.output_names[0]
        batch_request = BatchArtifactRequest(
            MARKET,
            (BatchArtifactBranchRequest(
                root.logical_artifact_id,
                source_output,
                "derivative",
                {"order": 1},
                resolve_output_names(
                    "derivative", {"order": 1, "source": source_output}
                ),
            ),),
            "collection_revision",
            collection.collection_id,
        )
        batch_plan = _completed(
            application.submit_plan_batch_artifacts, batch_request
        )
        assert not batch_plan.blocked
        batch_materialization, batch_collection = _completed(
            application.submit_execute_batch_artifacts, batch_plan
        )
        assert batch_collection is not None
        assert batch_collection.previous_revision_id == collection.revision_id
        assert batch_materialization.root_logical_artifact_ids

        inspected, validation = _completed(
            application.submit_inspect_artifact_collection,
            collection.collection_id,
        )
        assert inspected == batch_collection
        assert validation.valid and validation.database_ready
        assert _completed(
            application.submit_validate_artifact_collection,
            collection.collection_id,
        ) == validation
        reviewed_collection = _completed(
            application.submit_revise_artifact_collection,
            collection.collection_id,
            description="Reviewed before first Database revision",
            selected_outputs=inspected.selected_outputs,
            presentation_order=inspected.presentation_order,
        )
        assert reviewed_collection.previous_revision_id == batch_collection.revision_id

        readiness = _completed(
            application.submit_assess_database_readiness,
            seed.seed_id,
            collection.collection_id,
            reviewed_collection.revision_id,
        )
        assert readiness.ready
        first_manifest = _completed(
            application.submit_build_database_revision,
            seed.seed_id,
            collection.collection_id,
            collection_revision_id=reviewed_collection.revision_id,
            display_name="Momentum Database",
            description="Immutable feature snapshots",
        )
        first_loaded = _completed(
            application.submit_load_database_revision,
            first_manifest.database_id,
            first_manifest.revision_id,
        )

        current_collection = _completed(
            application.submit_revise_artifact_collection,
            collection.collection_id,
            display_name="Momentum Features Accepted",
        )
        assert current_collection.collection_id == collection.collection_id
        assert current_collection.previous_revision_id == reviewed_collection.revision_id
        second_manifest = _completed(
            application.submit_build_database_revision,
            seed.seed_id,
            collection.collection_id,
            collection_revision_id=current_collection.revision_id,
            database_id=first_manifest.database_id,
        )
        assert second_manifest.database_id == first_manifest.database_id
        assert second_manifest.previous_revision_id == first_manifest.revision_id
        second_loaded = _completed(
            application.submit_load_database_revision,
            second_manifest.database_id,
            second_manifest.revision_id,
        )
        assert first_loaded.values_csv == second_loaded.values_csv
        collection_history = _completed(
            application.submit_list_artifact_collection_revisions,
            collection.collection_id,
        )
        assert tuple(item.revision_id for item in collection_history) == (
            collection.revision_id,
            batch_collection.revision_id,
            reviewed_collection.revision_id,
            current_collection.revision_id,
        )
        database_history = _completed(
            application.submit_list_database_revisions, first_manifest.database_id
        )
        assert database_history == (first_manifest, second_manifest)
    finally:
        app.shutdown()

    restarted = LeonardoApp(config)
    restarted.startup()
    restarted.start_core_runtime()
    application = restarted.data_manager_service
    try:
        assert _completed(application.submit_load_database_seed, seed.seed_id) == seed
        assert _completed(
            application.submit_load_artifact_collection, collection.collection_id
        ) == current_collection
        assert _completed(
            application.submit_load_artifact_collection,
            collection.collection_id,
            reviewed_collection.revision_id,
        ) == reviewed_collection
        assert _completed(
            application.submit_list_artifact_collection_revisions,
            collection.collection_id,
        ) == collection_history
        definition = _completed(
            application.submit_load_database_definition, first_manifest.database_id
        )
        assert definition.database_id == first_manifest.database_id
        assert definition.seed_id == seed.seed_id
        assert _completed(
            application.submit_list_database_revisions, first_manifest.database_id
        ) == database_history
        assert _completed(
            application.submit_load_database_revision,
            first_manifest.database_id,
        ) == second_loaded
        assert _completed(
            application.submit_load_database_revision,
            first_manifest.database_id,
            first_manifest.revision_id,
        ) == first_loaded
        assert _completed(
            application.submit_load_database_revision,
            first_manifest.database_id,
            second_manifest.revision_id,
        ) == second_loaded
        assert first_loaded.manifest.artifact_payload_hashes
        assert second_loaded.manifest.collection_revision_id == (
            current_collection.revision_id
        )
        assert first_loaded.values_csv == second_loaded.values_csv
    finally:
        restarted.shutdown()
