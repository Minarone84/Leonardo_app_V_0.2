"""Copy and validate UTC evidence owned by physical Artifact providers."""
from __future__ import annotations

from hashlib import sha256
import json

from leonardo.artifacts.serialization import encode_analysis_json
from leonardo.financial_tools import UtcClassificationResult
from leonardo.financial_tools.utc_classification import _validate_utc_analysis
from .creation_models import (
    DataManagerCreationError, canonical_json_bytes, database_revision_from_dict, deterministic_hash,
)


def _utc_segments(manifest):
    provenance = manifest.to_dict().get("value_provenance", {})
    members = {m["artifact_id"]: m for m in provenance.get("members", ())}
    return tuple((segment, members[segment["artifact_id"]])
                 for segment in provenance.get("outputs", ())
                 if "artifact_id" in segment
                 and members[segment["artifact_id"]]["tool_key"] == "universal_trend_classifier")


def _decode_snapshot(data, manifest):
    descriptor = getattr(manifest, "utc_classification", None)
    if descriptor is None:
        if data is not None:
            raise DataManagerCreationError("unexpected UTC classification payload")
        return {"schema_version": "1.0", "reports": {}, "associations": []}
    if not isinstance(data, bytes) or sha256(data).hexdigest() != descriptor["sha256"]:
        raise DataManagerCreationError("UTC classification hash mismatch or missing payload")
    try:
        payload = json.loads(data)
        if canonical_json_bytes(payload) != data:
            raise ValueError("noncanonical")
        if set(payload) != {"schema_version", "reports", "associations"} or payload["schema_version"] != "1.0":
            raise ValueError("unsupported schema")
        if not isinstance(payload["reports"], dict) or not isinstance(payload["associations"], list):
            raise ValueError("invalid sections")
        for digest, analysis in payload["reports"].items():
            if sha256(encode_analysis_json(analysis)).hexdigest() != digest:
                raise ValueError("report hash mismatch")
            if analysis:
                report = _validate_utc_analysis(analysis)
                if report.status == "legacy_unavailable":
                    raise ValueError("synthetic legacy report")
        expected = [dict(segment) for segment, _member in _utc_segments(manifest)]
        actual = []
        used = set()
        provider_reports = {}
        for association in payload["associations"]:
            required = {"artifact_id", "logical_artifact_id", "column_name", "output_name",
                        "first_timestamp_ms", "last_timestamp_ms", "report_sha256"}
            if set(association) != required:
                raise ValueError("invalid UTC association")
            digest = association["report_sha256"]
            if digest not in payload["reports"]:
                raise ValueError("missing report")
            provider = association["artifact_id"]
            if provider in provider_reports and provider_reports[provider] != digest:
                raise ValueError("physical UTC provider has conflicting reports")
            provider_reports[provider] = digest
            used.add(digest)
            actual.append({k: v for k, v in association.items() if k != "report_sha256"})
            analysis = payload["reports"][digest]
            if analysis:
                axis = analysis["utc_classification"]["timestamps_ms"]
                if (association["first_timestamp_ms"] not in axis
                        or association["last_timestamp_ms"] not in axis):
                    raise ValueError("classification does not cover provider segment")
        if (sorted(actual, key=canonical_json_bytes) != sorted(expected, key=canonical_json_bytes)
                or used != set(payload["reports"])):
            raise ValueError("UTC associations disagree with value provenance")
        return payload
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise DataManagerCreationError(f"invalid UTC classification payload: {exc}") from exc


def _confirmed_facts(analysis):
    if not analysis:
        return {}
    return {
        (e["direction"], e["segment_start_ms"], e["formation"][0]["ts_ms"]):
        {k: v for k, v in e.items() if k not in ("episode_id", "predecessor_episode_id", "status")}
        for e in analysis["utc_classification"]["episodes"]
    }


def _capture_snapshot(manifest, artifacts, previous=None):
    segments = _utc_segments(manifest)
    if not segments:
        return manifest, None
    saved = _decode_snapshot(previous.utc_classification, previous.manifest) if previous else {
        "reports": {}, "associations": []
    }
    saved_by_artifact = {}
    # Old revisions did not copy classification. Retaining their values must not
    # acquire new claims from a live source or require that source to survive.
    if previous and getattr(previous.manifest, "utc_classification", None) is None:
        saved_by_artifact.update((member["artifact_id"], {})
                                 for _, member in _utc_segments(previous.manifest))
    for association in saved["associations"]:
        saved_by_artifact[association["artifact_id"]] = saved["reports"][association["report_sha256"]]
    reports, associations, captured = {}, [], {}
    for segment, member in segments:
        identity = member["artifact_id"]
        if identity not in captured:
            if identity in saved_by_artifact:
                analysis = saved_by_artifact[identity]
            else:
                loaded = artifacts.load_artifact_by_id(manifest.market_id, identity)
                if (loaded.metadata.recipe.tool_key != "universal_trend_classifier"
                        or loaded.metadata.values_sha256 != member["values_sha256"]
                        or loaded.metadata.recipe.output_names != tuple(member["output_names"])):
                    raise DataManagerCreationError("UTC provider evidence changed")
                analysis = loaded.analysis
                if analysis:
                    _validate_utc_analysis(analysis)
            digest = sha256(encode_analysis_json(analysis)).hexdigest()
            captured[identity] = digest, analysis
        digest, analysis = captured[identity]
        reports[digest] = analysis
        associations.append({**segment, "report_sha256": digest})
    # A new suffix provider must preserve already confirmed facts in shared history.
    if previous:
        for new in associations:
            if new["first_timestamp_ms"] <= previous.manifest.last_timestamp_ms:
                continue
            new_analysis = reports[new["report_sha256"]]
            for old in saved["associations"]:
                if old["logical_artifact_id"] != new["logical_artifact_id"]:
                    continue
                old_analysis = saved["reports"][old["report_sha256"]]
                if not old_analysis or not new_analysis:
                    continue
                old_report = old_analysis["utc_classification"]
                new_report = new_analysis["utc_classification"]
                if old_report["parameters"] != new_report["parameters"]:
                    raise DataManagerCreationError("UTC configuration changed; rebuild required")
                old_facts, new_facts = _confirmed_facts(old_analysis), _confirmed_facts(new_analysis)
                if any(new_facts.get(key) != facts for key, facts in old_facts.items()):
                    raise DataManagerCreationError("confirmed UTC formation changed; rebuild required")
    payload = {"schema_version": "1.0", "reports": reports, "associations": associations}
    data = canonical_json_bytes(payload)
    value = manifest.to_dict(include_revision_id=False)
    value["schema_version"] = "6.0"
    value["utc_classification"] = {
        "schema_version": "1.0", "filename": "utc_classification.json",
        "sha256": sha256(data).hexdigest(),
    }
    value["revision_id"] = deterministic_hash(value)
    updated = database_revision_from_dict(value)
    _decode_snapshot(data, updated)
    return updated, data

