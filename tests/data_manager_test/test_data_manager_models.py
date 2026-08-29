from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from leonardo.artifacts.models import LoadedArtifact
from leonardo.core.core_runner import TaskResult
from leonardo.data import MarketId
from leonardo.data_manager import (
    DataManagerArtifactEntry,
    DataManagerCatalogSnapshot,
    DataManagerDatasetEntry,
    DataManagerMarketSnapshot,
    DataManagerPreview,
    DataManagerRecipeEntry,
)
from leonardo.data_manager.models import DataManagerDeletionResult
from leonardo.data_manager.models import DataManagerRecipeCollectionEntry
from leonardo.data_manager.service import format_created_at
from leonardo.research.dataset import HistoricalDataset
from leonardo.research.session import ChartSessionState


INPUT = Path("tests/gui_test/fixtures/task_1024_data_manager_handoff_input.json")
EXPECTED = Path("tests/gui_test/fixtures/task_1024_data_manager_handoff_expected.json")


def _market(payload: dict[str, str]) -> MarketId:
    return MarketId(**payload)


def test_frozen_fixture_projects_exact_canonical_orders() -> None:
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    report = source["catalog_report"]
    datasets = [
        DataManagerDatasetEntry(
            market_id=_market(item["market_id"]),
            accepted=True,
            row_count=item["row_count"],
            first_timestamp_ms=item["first_timestamp_ms"],
            last_timestamp_ms=item["last_timestamp_ms"],
            source=item["source"],
            persistence_status=item["persistence_status"],
            validation_status=item["validation_status"],
            warnings=tuple(item["warnings"]),
        )
        for item in report["accepted"]
    ]
    datasets.extend(
        DataManagerDatasetEntry(
            market_id=None if item["market_id"] is None else _market(item["market_id"]),
            accepted=False,
            rejection_code=item["code"],
            rejection_reason=item["reason"],
        )
        for item in report["rejected"]
    )
    catalog = DataManagerCatalogSnapshot(tuple(reversed(datasets)))
    dataset_keys = [
        (
            f"{item.market_id.exchange}|{item.market_id.market_type}|"
            f"{item.market_id.symbol}|{item.market_id.timeframe}|"
            f"{'accepted' if item.accepted else 'rejected'}"
            if item.market_id is not None
            else "<unknown>|rejected"
        )
        for item in catalog.datasets
    ]
    assert dataset_keys == expected["canonical_dataset_order"]

    market = _market(source["selected_market"])
    dataset = catalog.accepted_market(market)
    recipes = tuple(
        DataManagerRecipeEntry(
            market_id=_market(item["market_id"]),
            recipe_id=item["recipe_id"],
            tool_key=item["tool_key"],
            kind=item["kind"],
            output_names=tuple(item["output_names"]),
            display_name=item["display_name"],
            created_at_utc=None,
            valid=item["valid"],
            rejection_reason=item["rejection_reason"],
        )
        for item in reversed(source["recipes"])
    )
    artifacts = tuple(
        DataManagerArtifactEntry(
            market_id=_market(item["market_id"]),
            artifact_id=item["artifact_id"],
            recipe_id=item["recipe_id"],
            tool_key=item["tool_key"],
            kind=item["kind"],
            output_names=tuple(item["output_names"]),
            row_count=item["row_count"],
            first_timestamp_ms=item["first_timestamp_ms"],
            last_timestamp_ms=item["last_timestamp_ms"],
            created_at_utc=None,
            valid=item["valid"],
            rejection_reason=item["rejection_reason"],
            current_status="unknown" if item["valid"] else "invalid",
        )
        for item in reversed(source["artifacts"])
    )
    snapshot = DataManagerMarketSnapshot(market, dataset, recipes, artifacts)
    assert [item.recipe_id for item in snapshot.recipes] == expected["canonical_recipe_order"]
    assert [item.artifact_id for item in snapshot.artifacts] == expected["canonical_artifact_order"]


def test_models_are_immutable_and_preview_contains_only_display_values() -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    preview = DataManagerPreview(
        "Preview",
        market,
        "dataset",
        None,
        ("ts_ms", "close"),
        (("0", "1.5"),),
        1,
        False,
        {"market_id": market.as_key()},
    )
    with pytest.raises(FrozenInstanceError):
        preview.title = "changed"
    with pytest.raises(TypeError):
        preview.metadata["path"] = "forbidden"
    assert all(isinstance(value, str) for row in preview.rows for value in row)
    assert "path" not in preview.metadata


@pytest.mark.parametrize("limit", (0, 501, True))
def test_preview_contract_rejects_incoherent_shapes(limit) -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    with pytest.raises((TypeError, ValueError)):
        DataManagerPreview(
            "Preview",
            market,
            "dataset",
            None,
            ("ts_ms",),
            (("0",),),
            limit,
            False,
            {},
        )


def test_models_expose_no_filesystem_or_runtime_object_fields() -> None:
    import inspect
    import leonardo.data_manager.models as models

    source = inspect.getsource(models)
    assert "from pathlib" not in source
    assert "DataFrame" not in source
    assert "TaskResult" not in source
    assert "LoadedArtifact" not in source


def test_presentation_models_reject_forbidden_runtime_values() -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    forbidden = (
        Path("candles.csv"),
        pd.DataFrame({"value": [1]}),
        np.array([1]),
        object.__new__(HistoricalDataset),
        object.__new__(LoadedArtifact),
        TaskResult("task", "completed"),
        object.__new__(ChartSessionState),
    )
    for value in forbidden:
        with pytest.raises(TypeError, match="source must be a string"):
            DataManagerDatasetEntry(market, True, 1, 0, 0, source=value)
    with pytest.raises(TypeError, match="persistence_status must be a string"):
        DataManagerDatasetEntry(
            market, True, 1, 0, 0, persistence_status=object()
        )
    for created_at in (Path("recipe"), datetime(2026, 7, 18)):
        with pytest.raises((TypeError, ValueError), match="created_at_utc|timezone-aware"):
            DataManagerRecipeEntry(
                market,
                "r",
                "rsi",
                "oscillator",
                ("rsi",),
                "RSI",
                created_at,
            )
        with pytest.raises((TypeError, ValueError), match="created_at_utc|timezone-aware"):
            DataManagerArtifactEntry(
                market,
                "a",
                "r",
                "rsi",
                "oscillator",
                ("rsi",),
                1,
                0,
                0,
                created_at,
            )
    with pytest.raises((TypeError, ValueError)):
        DataManagerPreview(
            "Preview",
            market,
            "dataset",
            None,
            ("ts_ms",),
            ((pd.DataFrame({"value": [1]}),),),
            1,
            False,
            {},
        )
    with pytest.raises((TypeError, ValueError)):
        DataManagerPreview(
            "Preview",
            market,
            "dataset",
            None,
            ("ts_ms",),
            ((np.array([1]),),),
            1,
            False,
            {},
        )


def test_presentation_models_reject_boolean_integer_fields() -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    with pytest.raises(TypeError, match="row_count"):
        DataManagerDatasetEntry(market, True, True, 0, 0)
    with pytest.raises(ValueError, match="row_count"):
        DataManagerArtifactEntry(
            market,
            "a",
            "r",
            "rsi",
            "oscillator",
            ("rsi",),
            True,
            0,
            0,
            None,
        )


def test_aware_timestamps_are_normalized_and_displayed_stably() -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    local = datetime(2026, 7, 18, 14, 30, tzinfo=timezone(timedelta(hours=2)))
    recipe = DataManagerRecipeEntry(
        market, "r", "rsi", "oscillator", ("rsi",), "RSI", local
    )
    assert recipe.created_at_utc == datetime(2026, 7, 18, 12, 30, tzinfo=UTC)
    assert format_created_at(local) == "2026-07-18T12:30:00Z"
    with pytest.raises(ValueError, match="timezone-aware"):
        format_created_at(datetime(2026, 7, 18, 12, 30))
def test_deletion_result_is_frozen_and_contains_only_exact_identity() -> None:
    market = MarketId("bybit", "linear", "BTCUSDT", "1h")
    result = DataManagerDeletionResult(market, "artifact", "oscillator", "rsi", "a")
    assert result.object_id == "a"
    with pytest.raises(FrozenInstanceError):
        result.object_id = "changed"


def test_recipe_collection_catalog_members_are_exact_immutable_recipe_ids() -> None:
    members = ["a" * 64, "b" * 64]
    entry = DataManagerRecipeCollectionEntry(
        "collection_1",
        "c" * 64,
        "Collection",
        "",
        1,
        2,
        members,
        1,
        2,
        datetime(2026, 8, 9, tzinfo=UTC),
        datetime(2026, 8, 9, tzinfo=UTC),
    )
    members.append("d" * 64)
    assert entry.member_recipe_ids == ("a" * 64, "b" * 64)
    assert isinstance(entry.member_recipe_ids, tuple)

    with pytest.raises(ValueError, match="unique"):
        DataManagerRecipeCollectionEntry(
            "collection_1", "c" * 64, "Collection", "", 1, 2,
            ("a" * 64, "a" * 64), 1, 2, None, None,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        DataManagerRecipeCollectionEntry(
            "collection_1", "c" * 64, "Collection", "", 1, 1,
            ("not-a-sha",), 0, 1, None, None,
        )
    with pytest.raises(ValueError, match="member_count"):
        DataManagerRecipeCollectionEntry(
            "collection_1", "c" * 64, "Collection", "", 1, 2,
            ("a" * 64,), 0, 1, None, None,
        )

    invalid = DataManagerRecipeCollectionEntry(
        "broken", "", "Broken", "", 0, 3, (), 0, 0,
        None, None, False, "unreadable",
    )
    assert invalid.member_recipe_ids == ()
