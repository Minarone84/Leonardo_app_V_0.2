from __future__ import annotations

import hashlib
import json
from pathlib import Path

from leonardo.artifacts.identity import (
    artifact_identity_payload,
    canonical_json_identity_bytes,
    recipe_identity_payload,
)
from leonardo.artifacts.models import OHLCVSourceFingerprintV1


FIXTURES = Path(__file__).with_name("fixtures")


def test_frozen_recipe_values_and_artifact_identities() -> None:
    fixture = json.loads((FIXTURES / "task_1016_identity_fixtures.json").read_text(encoding="utf-8"))
    recipe_payload = fixture["recipe_identity_payload"]
    recipe_id = hashlib.sha256(canonical_json_identity_bytes(recipe_payload)).hexdigest()
    assert recipe_id == fixture["expected_recipe_id"]
    values = (FIXTURES / "task_1016_canonical_values.csv").read_bytes()
    values_hash = hashlib.sha256(values).hexdigest()
    assert values_hash == fixture["expected_values_sha256"]
    artifact_id = hashlib.sha256(
        canonical_json_identity_bytes(fixture["artifact_identity_payload"])
    ).hexdigest()
    assert artifact_id == fixture["expected_artifact_id"]


def test_mapping_order_and_descriptive_fields_do_not_change_identity() -> None:
    fixture = json.loads((FIXTURES / "task_1016_identity_fixtures.json").read_text(encoding="utf-8"))
    original = fixture["recipe_identity_payload"]
    reordered = {key: original[key] for key in reversed(tuple(original))}
    assert canonical_json_identity_bytes(original) == canonical_json_identity_bytes(reordered)
    descriptive_a = dict(original, display_name="A", description="first")
    descriptive_b = dict(original, display_name="B", description="second")
    for value in (descriptive_a, descriptive_b):
        value.pop("display_name")
        value.pop("description")
    assert canonical_json_identity_bytes(descriptive_a) == canonical_json_identity_bytes(descriptive_b)


def test_semantic_changes_change_identity() -> None:
    fixture = json.loads((FIXTURES / "task_1016_identity_fixtures.json").read_text(encoding="utf-8"))
    original = fixture["recipe_identity_payload"]
    changed = json.loads(json.dumps(original))
    changed["parameters"]["period"] = 4
    assert hashlib.sha256(canonical_json_identity_bytes(original)).hexdigest() != hashlib.sha256(
        canonical_json_identity_bytes(changed)
    ).hexdigest()


def test_identity_payload_builders_match_frozen_payloads() -> None:
    fixture = json.loads((FIXTURES / "task_1016_identity_fixtures.json").read_text(encoding="utf-8"))
    source = OHLCVSourceFingerprintV1.from_dict(fixture["source_ohlcv"])
    recipe = recipe_identity_payload(
        market_id=source.market_id,
        tool_key="sma",
        kind="indicator",
        parameters={"period": 3},
        bindings={},
        output_names=("sma_3",),
        source_artifacts=(),
    )
    assert recipe == fixture["recipe_identity_payload"]
    artifact = artifact_identity_payload(
        recipe_id=fixture["expected_recipe_id"],
        source_ohlcv=source.to_dict(),
        source_artifacts=(),
        row_count=4,
        first_timestamp_ms=1_700_000_000_000,
        last_timestamp_ms=1_700_000_180_000,
        values_sha256=fixture["expected_values_sha256"],
        analysis_sha256=None,
    )
    assert artifact == fixture["artifact_identity_payload"]
