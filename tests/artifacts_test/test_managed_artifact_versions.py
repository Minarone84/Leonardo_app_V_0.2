from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from leonardo.artifacts import (
    ArtifactHeadV1,
    ManagedArtifactGraphPublicationResult,
    ManagedArtifactVersionKey,
    ArtifactIdentityCollisionError,
    ArtifactLineageError,
    ArtifactNotFoundError,
    ArtifactService,
    ArtifactSourceRefV1,
    ArtifactValidationError,
    ArtifactVersionRecordV1,
    compute_logical_artifact_id,
)
from leonardo.artifacts.serialization import encode_canonical_json
from leonardo.data import MarketId
from leonardo.financial_tools import calculate_financial_tool

from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.artifacts_test.test_artifact_catalog_and_delete import _make_link


MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")
OTHER_MARKET = MarketId("bybit", "linear", "ETHUSDT", "1m")
PORTABLE_ID = "a" * 64
OTHER_PORTABLE_ID = "b" * 64
CREATED = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def test_logical_identity_and_strict_managed_schemas() -> None:
    logical_id = compute_logical_artifact_id(MARKET, PORTABLE_ID)
    assert logical_id == compute_logical_artifact_id(MARKET, PORTABLE_ID)
    assert logical_id != compute_logical_artifact_id(OTHER_MARKET, PORTABLE_ID)
    assert logical_id != compute_logical_artifact_id(MARKET, OTHER_PORTABLE_ID)

    record = ArtifactVersionRecordV1(
        logical_id,
        "c" * 64,
        PORTABLE_ID,
        MARKET,
        None,
        CREATED,
    )
    head = ArtifactHeadV1(logical_id, "c" * 64, CREATED)
    assert ArtifactVersionRecordV1.from_dict(record.to_dict()) == record
    assert ArtifactHeadV1.from_dict(head.to_dict()) == head
    assert record.canonical_json_bytes().endswith(b"\n")
    assert head.canonical_json_bytes().endswith(b"\n")

    with pytest.raises(ArtifactValidationError):
        replace(record, logical_artifact_id="d" * 64)
    with pytest.raises(ArtifactValidationError):
        replace(record, previous_artifact_id=record.artifact_id)
    with pytest.raises(ArtifactValidationError):
        replace(record, created_at_utc=CREATED.replace(tzinfo=None))
    with pytest.raises(ArtifactValidationError):
        ArtifactVersionRecordV1.from_dict({**record.to_dict(), "extra": True})
    incomplete = record.to_dict()
    incomplete.pop("artifact_id")
    with pytest.raises(ArtifactValidationError):
        ArtifactVersionRecordV1.from_dict(incomplete)


def test_managed_publication_round_trip_and_exact_reuse(tmp_path: Path) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    result = calculate_financial_tool("sma", frame, {"period": 3})
    candidate = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        result,
        expected_source=source,
        created_at_utc=CREATED,
    )

    published = service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )
    assert published.created_artifact_ids == (candidate.metadata.artifact_id,)
    version_key = ManagedArtifactVersionKey(
        candidate.logical_artifact_id, candidate.metadata.artifact_id
    )
    assert published.created_version_keys == (version_key,)
    assert published.reused_version_keys == ()
    assert published.advanced_logical_artifact_ids == (
        candidate.logical_artifact_id,
    )
    assert service.load_artifact_head(market, candidate.logical_artifact_id) == candidate.head
    assert service.load_artifact_version(
        market, candidate.logical_artifact_id, candidate.metadata.artifact_id
    ) == candidate.version_record
    assert service.list_artifact_versions(market, candidate.logical_artifact_id) == (
        candidate.version_record,
    )
    loaded = service.load_artifact_by_id(market, candidate.metadata.artifact_id)
    assert loaded.metadata == candidate.metadata

    repeated = service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )
    assert repeated.created_artifact_ids == ()
    assert repeated.created_version_keys == ()
    assert repeated.reused_version_keys == (version_key,)
    assert repeated.reused_artifact_ids == (candidate.metadata.artifact_id,)
    assert repeated.advanced_logical_artifact_ids == ()
    assert len(service.list_managed_artifacts(market)) == 1


def test_managed_market_discovery_is_canonical_without_ohlcv_sidecars(
    tmp_path: Path,
) -> None:
    service = ArtifactService(tmp_path)
    for market, portable_id in (
        (OTHER_MARKET, OTHER_PORTABLE_ID),
        (MARKET, PORTABLE_ID),
    ):
        _, frame = _accepted_dataset(tmp_path, market=market)
        source = service.capture_accepted_source(market)
        candidate = service.prepare_managed_calculation(
            market,
            portable_id,
            calculate_financial_tool("sma", frame, {"period": 3}),
            expected_source=source,
            created_at_utc=CREATED,
        )
        service.publish_managed_artifact_graph(
            (candidate,), expected_source=source
        )

    assert service.list_managed_markets() == (MARKET, OTHER_MARKET)
    service._ohlcv_store.sidecar_path(MARKET).unlink()
    service._ohlcv_store.sidecar_path(OTHER_MARKET).unlink()
    assert service.list_managed_markets() == (MARKET, OTHER_MARKET)


def test_duplicate_artifact_candidates_must_be_semantically_equivalent(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    result = calculate_financial_tool("sma", frame, {"period": 3})
    first = service.prepare_managed_calculation(
        market, PORTABLE_ID, result, expected_source=source, created_at_utc=CREATED
    )
    second = service.prepare_managed_calculation(
        market,
        OTHER_PORTABLE_ID,
        result,
        expected_source=source,
        created_at_utc=CREATED,
    )
    different_recipe = replace(
        second.metadata.recipe, description="different description"
    )
    different_metadata = replace(second.metadata, recipe=different_recipe)
    conflicting = replace(
        second,
        metadata=different_metadata,
        recipe_bytes=encode_canonical_json(different_recipe.to_dict()),
        metadata_bytes=encode_canonical_json(different_metadata.to_dict()),
    )

    with pytest.raises(ArtifactIdentityCollisionError):
        service.publish_managed_artifact_graph(
            (first, conflicting), expected_source=source
        )
    assert service.list_artifacts(market) == ()
    assert service.list_managed_artifacts(market) == ()


def test_result_models_reject_ambiguous_publication_evidence() -> None:
    logical_id = compute_logical_artifact_id(MARKET, PORTABLE_ID)
    key = ManagedArtifactVersionKey(logical_id, "c" * 64)
    with pytest.raises(ArtifactValidationError):
        ManagedArtifactVersionKey("C" * 64, "c" * 64)
    with pytest.raises(ArtifactValidationError):
        ManagedArtifactVersionKey(logical_id, "invalid")
    with pytest.raises(ArtifactValidationError, match="created_artifact_ids"):
        ManagedArtifactGraphPublicationResult(
            (), ("c" * 64, "c" * 64), (), (), (), ()
        )
    with pytest.raises(ArtifactValidationError, match="reused_artifact_ids"):
        ManagedArtifactGraphPublicationResult(
            (), (), ("c" * 64, "c" * 64), (), (), ()
        )
    with pytest.raises(ArtifactValidationError, match="disjoint"):
        ManagedArtifactGraphPublicationResult(
            (), ("c" * 64,), ("c" * 64,), (), (), ()
        )
    with pytest.raises(ArtifactValidationError, match="created_version_keys"):
        ManagedArtifactGraphPublicationResult(
            (), (), (), (key, key), (), ()
        )
    with pytest.raises(ArtifactValidationError, match="disjoint"):
        ManagedArtifactGraphPublicationResult(
            (), (), (), (key,), (key,), ()
        )


def test_publication_result_evidence_must_exactly_match_managed_entries(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    candidate = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", frame, {"period": 3}),
        expected_source=source,
        created_at_utc=CREATED,
    )
    published = service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )
    artifact_id = candidate.metadata.artifact_id
    logical_id = candidate.logical_artifact_id
    unrelated_artifact_id = "d" * 64
    unrelated_logical_id = "e" * 64

    with pytest.raises(ArtifactValidationError, match="Artifact evidence"):
        replace(published, created_artifact_ids=(unrelated_artifact_id,))
    with pytest.raises(ArtifactValidationError, match="Artifact evidence"):
        replace(
            published,
            created_artifact_ids=(),
            reused_artifact_ids=(unrelated_artifact_id,),
        )
    with pytest.raises(ArtifactValidationError, match="Artifact evidence"):
        replace(published, created_artifact_ids=())
    with pytest.raises(ArtifactValidationError, match="version-key evidence"):
        replace(
            published,
            created_version_keys=(
                ManagedArtifactVersionKey(unrelated_logical_id, artifact_id),
            ),
        )
    with pytest.raises(ArtifactValidationError, match="version-key evidence"):
        replace(
            published,
            created_version_keys=(
                ManagedArtifactVersionKey(logical_id, unrelated_artifact_id),
            ),
        )
    with pytest.raises(ArtifactValidationError, match="advanced logical"):
        replace(
            published,
            advanced_logical_artifact_ids=(unrelated_logical_id,),
        )
    with pytest.raises(ArtifactValidationError, match="Artifact evidence"):
        replace(published, managed_artifacts=())
    extra = replace(
        published.managed_artifacts[0],
        logical_artifact_id=unrelated_logical_id,
    )
    with pytest.raises(ArtifactValidationError, match="version-key evidence"):
        replace(published, managed_artifacts=(*published.managed_artifacts, extra))


def test_equivalent_same_logical_publications_reuse_canonical_bytes(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    result = calculate_financial_tool("sma", frame, {"period": 3})
    first = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        result,
        expected_source=source,
        created_at_utc=CREATED,
    )
    second = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        result,
        expected_source=source,
        created_at_utc=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    )
    service.publish_managed_artifact_graph((first,), expected_source=source)
    recipe_path = service._store.recipe_path(
        market,
        first.metadata.recipe.kind,
        first.metadata.recipe.tool_key,
        first.metadata.recipe.recipe_id,
    )
    artifact_dir = service._store.artifact_dir(
        market,
        first.metadata.recipe.kind,
        first.metadata.recipe.tool_key,
        first.metadata.artifact_id,
    )
    version_path = service._store.version_record_path(
        market, first.logical_artifact_id, first.metadata.artifact_id
    )
    head_path = service._store.head_path(market, first.logical_artifact_id)
    before = (
        service._store.read_optional_bytes(recipe_path),
        service._store.read_artifact_bytes(artifact_dir),
        service._store.read_optional_bytes(version_path),
        service._store.read_optional_bytes(head_path),
    )

    repeated = service.publish_managed_artifact_graph(
        (second,), expected_source=source
    )
    key = ManagedArtifactVersionKey(
        first.logical_artifact_id, first.metadata.artifact_id
    )
    assert repeated.created_artifact_ids == ()
    assert repeated.reused_artifact_ids == (first.metadata.artifact_id,)
    assert repeated.created_version_keys == ()
    assert repeated.reused_version_keys == (key,)
    assert repeated.advanced_logical_artifact_ids == ()
    assert (
        service._store.read_optional_bytes(recipe_path),
        service._store.read_artifact_bytes(artifact_dir),
        service._store.read_optional_bytes(version_path),
        service._store.read_optional_bytes(head_path),
    ) == before


def test_research_save_is_reconciled_before_managed_publication(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    result = calculate_financial_tool("sma", frame, {"period": 3})
    candidate = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        result,
        expected_source=source,
        display_name="Shared SMA",
        description="shared",
        created_at_utc=CREATED,
    )
    saved = service.save_calculation(
        market,
        result,
        display_name="Shared SMA",
        description="shared",
        created_at_utc=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    )
    before = service._store.read_artifact_bytes(saved.path)

    publication = service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )
    key = ManagedArtifactVersionKey(
        candidate.logical_artifact_id, candidate.metadata.artifact_id
    )
    assert publication.created_artifact_ids == ()
    assert publication.reused_artifact_ids == (candidate.metadata.artifact_id,)
    assert publication.created_version_keys == (key,)
    assert publication.reused_version_keys == ()
    assert service._store.read_artifact_bytes(saved.path) == before
    assert service.load_artifact_version(
        market, candidate.logical_artifact_id, candidate.metadata.artifact_id
    ).artifact_id == candidate.metadata.artifact_id
    assert service.load_artifact_head(
        market, candidate.logical_artifact_id
    ).artifact_id == candidate.metadata.artifact_id


def test_stale_prepared_head_cannot_overwrite_newer_publication(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    first = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", frame, {"period": 3}),
        expected_source=source,
        created_at_utc=CREATED,
    )
    service.publish_managed_artifact_graph((first,), expected_source=source)
    stale = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", frame, {"period": 4}),
        expected_source=source,
        previous_artifact_id=first.metadata.artifact_id,
        created_at_utc=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    )
    newer = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("ema", frame, {"period": 3}),
        expected_source=source,
        previous_artifact_id=first.metadata.artifact_id,
        created_at_utc=datetime(2026, 8, 3, 12, 2, tzinfo=UTC),
    )
    service.publish_managed_artifact_graph((newer,), expected_source=source)
    head_before = service._store.read_optional_bytes(
        service._store.head_path(market, first.logical_artifact_id)
    )
    versions_before = service.list_artifact_versions(
        market, first.logical_artifact_id
    )

    with pytest.raises(
        ArtifactLineageError,
        match="logical Artifact head changed after preparation",
    ):
        service.publish_managed_artifact_graph((stale,), expected_source=source)

    assert service._store.read_optional_bytes(
        service._store.head_path(market, first.logical_artifact_id)
    ) == head_before
    assert service.list_artifact_versions(
        market, first.logical_artifact_id
    ) == versions_before
    assert not service._store.artifact_dir(
        market,
        stale.metadata.recipe.kind,
        stale.metadata.recipe.tool_key,
        stale.metadata.artifact_id,
    ).exists()


def test_current_and_historical_managed_artifacts_cannot_be_deleted(
    tmp_path: Path,
) -> None:
    market, first_frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    first_source = service.capture_accepted_source(market)
    first = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", first_frame, {"period": 3}),
        expected_source=first_source,
        created_at_utc=CREATED,
    )
    service.publish_managed_artifact_graph((first,), expected_source=first_source)

    _market, second_frame = _accepted_dataset(tmp_path, market=MARKET, rows=97)
    second_source = service.capture_accepted_source(market)
    second = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", second_frame, {"period": 3}),
        expected_source=second_source,
        previous_artifact_id=first.metadata.artifact_id,
        created_at_utc=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
    )
    service.publish_managed_artifact_graph((second,), expected_source=second_source)
    head_before = service.load_artifact_head(market, first.logical_artifact_id)
    versions_before = service.list_artifact_versions(market, first.logical_artifact_id)
    artifact_bytes = {
        artifact_id: service._store.read_artifact_bytes(
            service._store.find_artifact_dirs(market, artifact_id)[0]
        )
        for artifact_id in (first.metadata.artifact_id, second.metadata.artifact_id)
    }

    for candidate in (first, second):
        with pytest.raises(
            ArtifactLineageError, match="artifact is referenced by managed version"
        ):
            service.delete_artifact(
                market,
                candidate.metadata.recipe.kind,
                candidate.metadata.recipe.tool_key,
                candidate.metadata.artifact_id,
            )

    assert service.load_artifact_head(market, first.logical_artifact_id) == head_before
    assert service.list_artifact_versions(market, first.logical_artifact_id) == versions_before
    assert service.list_managed_artifacts(market)[0].valid
    assert all(
        service._store.read_artifact_bytes(
            service._store.find_artifact_dirs(market, artifact_id)[0]
        ) == payload
        for artifact_id, payload in artifact_bytes.items()
    )

    unmanaged = service.save_calculation(
        market, calculate_financial_tool("ema", second_frame, {"period": 3})
    )
    deleted = service.delete_artifact(
        market, "indicator", "ema", unmanaged.metadata.artifact_id
    )
    assert deleted.artifact_id == unmanaged.metadata.artifact_id


def test_managed_publication_recursively_revalidates_source_lineage(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    first = service.save_calculation(
        market, calculate_financial_tool("sma", frame, {"period": 3})
    )
    first_ref = ArtifactSourceRefV1(
        "first", first.metadata.artifact_id, "sma_3"
    )
    second = service.save_calculation(
        market,
        calculate_financial_tool("ema", frame, {"period": 3}),
        source_artifacts=(first_ref,),
    )
    second_ref = ArtifactSourceRefV1(
        "second", second.metadata.artifact_id, "ema_3"
    )
    candidate = service.prepare_managed_calculation(
        market,
        "d" * 64,
        calculate_financial_tool("rsi", frame, {"period": 3}),
        expected_source=source,
        source_artifacts=(second_ref,),
        source_metadata=(second.metadata,),
        created_at_utc=CREATED,
    )

    published = service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )

    assert published.managed_artifacts[0].artifact_id == candidate.metadata.artifact_id


def test_managed_publication_rejects_removed_recursive_source_before_writes(
    tmp_path: Path,
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    first = service.save_calculation(
        market, calculate_financial_tool("sma", frame, {"period": 3})
    )
    first_ref = ArtifactSourceRefV1(
        "first", first.metadata.artifact_id, "sma_3"
    )
    second = service.save_calculation(
        market,
        calculate_financial_tool("ema", frame, {"period": 3}),
        source_artifacts=(first_ref,),
    )
    second_ref = ArtifactSourceRefV1(
        "second", second.metadata.artifact_id, "ema_3"
    )
    candidate = service.prepare_managed_calculation(
        market,
        "d" * 64,
        calculate_financial_tool("rsi", frame, {"period": 3}),
        expected_source=source,
        source_artifacts=(second_ref,),
        source_metadata=(second.metadata,),
        created_at_utc=CREATED,
    )
    recipe_path = service._store.recipe_path(
        market,
        candidate.metadata.recipe.kind,
        candidate.metadata.recipe.tool_key,
        candidate.metadata.recipe.recipe_id,
    )
    artifact_dir = service._store.artifact_dir(
        market,
        candidate.metadata.recipe.kind,
        candidate.metadata.recipe.tool_key,
        candidate.metadata.artifact_id,
    )
    version_path = service._store.version_record_path(
        market, candidate.logical_artifact_id, candidate.metadata.artifact_id
    )
    head_path = service._store.head_path(market, candidate.logical_artifact_id)
    shutil.rmtree(first.path)

    with pytest.raises(ArtifactLineageError, match="source artifact not found"):
        service.publish_managed_artifact_graph((candidate,), expected_source=source)

    assert not recipe_path.exists()
    assert not artifact_dir.exists()
    assert not version_path.exists()
    assert not head_path.exists()


def test_locked_recursive_source_validation_rejects_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, _frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    source = service.capture_accepted_source(market)
    first_ref = ArtifactSourceRefV1("first", "a" * 64, "value")
    second_ref = ArtifactSourceRefV1("second", "b" * 64, "value")
    loaded = {
        first_ref.artifact_id: SimpleNamespace(
            metadata=SimpleNamespace(
                artifact_id=first_ref.artifact_id,
                source_ohlcv=source,
                recipe=SimpleNamespace(
                    market_id=market,
                    output_names=("value",),
                    source_artifacts=(second_ref,),
                ),
            )
        ),
        second_ref.artifact_id: SimpleNamespace(
            metadata=SimpleNamespace(
                artifact_id=second_ref.artifact_id,
                source_ohlcv=source,
                recipe=SimpleNamespace(
                    market_id=market,
                    output_names=("value",),
                    source_artifacts=(first_ref,),
                ),
            )
        ),
    }
    monkeypatch.setattr(
        service,
        "_load_source_artifact",
        lambda _market, artifact_id: loaded[artifact_id],
    )

    with pytest.raises(ArtifactLineageError, match="cycle"):
        service._validate_exact_source_refs_locked(market, (first_ref,), source)


def test_save_calculation_does_not_capture_full_timeline_under_mutation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    original = service._capture_accepted_ohlcv
    lock_states: list[bool] = []

    def tracked_capture(market_id):
        lock_states.append(service._mutation_lock._is_owned())
        return original(market_id)

    monkeypatch.setattr(service, "_capture_accepted_ohlcv", tracked_capture)
    service.save_calculation(
        market, calculate_financial_tool("sma", frame, {"period": 3})
    )

    assert lock_states
    assert not any(lock_states)


def test_managed_publication_does_not_capture_full_timeline_under_mutation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market, frame = _accepted_dataset(tmp_path, market=MARKET)
    service = ArtifactService(tmp_path)
    original = service._capture_accepted_ohlcv
    lock_states: list[bool] = []

    def tracked_capture(market_id):
        lock_states.append(service._mutation_lock._is_owned())
        return original(market_id)

    monkeypatch.setattr(service, "_capture_accepted_ohlcv", tracked_capture)
    source = service.capture_accepted_source(market)
    candidate = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", frame, {"period": 3}),
        expected_source=source,
        created_at_utc=CREATED,
    )
    service.publish_managed_artifact_graph(
        (candidate,), expected_source=source
    )

    assert lock_states
    assert not any(lock_states)


def test_managed_reads_do_not_create_storage(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path)
    logical_id = compute_logical_artifact_id(MARKET, PORTABLE_ID)
    assert service.list_managed_artifacts(MARKET) == ()
    assert service.list_artifact_versions(MARKET, logical_id) == ()
    with pytest.raises(ArtifactNotFoundError):
        service.load_artifact_head(MARKET, logical_id)
    assert tuple(tmp_path.iterdir()) == ()


def test_linked_managed_head_is_rejected_without_external_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "historical"
    market, frame = _accepted_dataset(root, market=MARKET)
    service = ArtifactService(root)
    source = service.capture_accepted_source(market)
    candidate = service.prepare_managed_calculation(
        market,
        PORTABLE_ID,
        calculate_financial_tool("sma", frame, {"period": 3}),
        expected_source=source,
        created_at_utc=CREATED,
    )
    service.publish_managed_artifact_graph((candidate,), expected_source=source)
    head_path = service._store.head_path(market, candidate.logical_artifact_id)
    external = tmp_path / "external_head.json"
    external.write_bytes(head_path.read_bytes())
    before = external.read_bytes()
    head_path.unlink()
    _make_link(head_path, external, directory=False)

    with pytest.raises(ArtifactValidationError, match="links or junctions"):
        service.load_artifact_head(market, candidate.logical_artifact_id)
    summary = service.list_managed_artifacts(market)[0]
    assert not summary.valid
    assert "links or junctions" in summary.rejection_reason
    assert external.read_bytes() == before
