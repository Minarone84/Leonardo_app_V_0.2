"""Real canonical Artifact reads, with ordinary long paths and exact safety.

Optional runner parameters: R02_FIXTURE_ROOT is a disposable short root,
R02_OBSERVATIONS receives JSON receipts, and R02_JUNCTIONS names an outer-
controller-created junction manifest. No subprocess or fake link is used here.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from leonardo.artifacts import ArtifactNotFoundError, ArtifactService, ArtifactValidationError
from leonardo.artifacts._stores import _io_path
from leonardo.artifacts.serialization import encode_canonical_json
from leonardo.data import MarketId
from leonardo.financial_tools import calculate_financial_tool
from leonardo.ohlcv.store import Candle, OHLCVStore

MARKET = MarketId("bybit", "linear", "BTCUSDT", "1m")
CREATED = datetime(2026, 1, 1, tzinfo=UTC)


def ordinary(path):
    return Path(str(path).removeprefix("\\\\?\\"))


def io(path):
    path = Path(path).absolute()
    return Path("\\\\?\\" + str(path)) if os.name == "nt" and not str(path).startswith("\\\\?\\") else path


def receipt(node, stage, value):
    configured = os.environ.get("R02_OBSERVATIONS")
    if configured:
        folder = Path(configured)
        folder.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(node.encode()).hexdigest()[:16] + "_" + stage + ".json"
        with (folder / name).open("x", encoding="utf-8") as handle:
            json.dump({"node": node, "stage": stage, **value}, handle, indent=2, default=str)


def case_root(tmp_path, request):
    configured = os.environ.get("R02_FIXTURE_ROOT")
    root = ordinary(Path(configured)) / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:8] if configured else ordinary(tmp_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


def deep_root(base, payload_length=270):
    suffix = Path("bybit/linear/BTCUSDT/1m/artifacts/indicator/sma") / ("a" * 64) / "artifact.meta.json"
    needed = payload_length - len(str(base / suffix)) - 1
    assert 1 <= needed < 240
    return base / ("d" * needed)


def disk(root, *, mtimes=True):
    root = io(root)
    result = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(current, d).is_symlink() and not Path(current, d).is_junction())
        for name in sorted(files):
            path = Path(current, name)
            assert not path.is_symlink()
            data = path.read_bytes()
            value = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if mtimes:
                value["mtime_ns"] = path.stat().st_mtime_ns
            result[path.relative_to(root).as_posix()] = value
    return result


def accepted(root, rows=12):
    values = [100.0 + i for i in range(rows)]
    candles = [Candle(1_700_000_040_000 + i * 60_000, v - .2, v + 1, v - 1, v, 1000.0 + i) for i, v in enumerate(values)]
    store = OHLCVStore(root)
    store.write(MARKET, candles, source="R02 synthetic", persistence_status="committed")
    csv, meta = store.csv_path(MARKET), store.sidecar_path(MARKET)
    a, b = csv.stat(), meta.stat()
    store.publish_validation(
        MARKET, expected_csv_size=a.st_size, expected_csv_mtime_ns=a.st_mtime_ns,
        expected_csv_sha256=hashlib.sha256(csv.read_bytes()).hexdigest(),
        expected_sidecar_size=b.st_size, expected_sidecar_mtime_ns=b.st_mtime_ns,
        expected_sidecar_sha256=hashlib.sha256(meta.read_bytes()).hexdigest(),
        status="ok", row_count=rows, first_timestamp_ms=candles[0].ts_ms,
        last_timestamp_ms=candles[-1].ts_ms, warnings=(), issue_codes=(),
        error_count=0, warning_count=0, validator="R02 synthetic",
    )
    return pd.DataFrame([dict(ts_ms=c.ts_ms, open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume) for c in candles])


def canonical_tree(base, depth, tools=("sma",)):
    short = base / "s"
    frame = accepted(short)
    service = ArtifactService(short)
    source = service.capture_accepted_source(MARKET)
    saved = []
    for index, tool in enumerate(tools):
        result = calculate_financial_tool(tool, frame, {"period": 3} if tool == "sma" else {"window": 3})
        prepared = service.prepare_managed_calculation(
            MARKET, str(index + 1) * 64, result, expected_source=source,
            created_at_utc=CREATED + timedelta(days=index),
        )
        published = service.publish_managed_artifact_graph((prepared,), expected_source=source)
        assert published.created_artifact_ids == (prepared.metadata.artifact_id,)
        saved.append((prepared, result))
    root = short if depth == "short" else deep_root(base, 270 if depth == "payload" else 400)
    if root != short:
        shutil.copytree(io(short), io(root), copy_function=shutil.copy2)
        assert disk(root) == disk(short)
    return root, frame, saved


@pytest.mark.parametrize("depth", ("short", "payload", "root"))
@pytest.mark.parametrize("tool", ("sma", "dynamic_binning"))
@pytest.mark.parametrize("mode", ("full", "metadata"))
def test_reads_match_extended_spelling_and_preserve_bytes(tmp_path, request, depth, tool, mode):
    root, _, saved = canonical_tree(case_root(tmp_path, request), depth, (tool,))
    prepared, calculation = saved[0]
    meta = prepared.metadata
    directory = root / "bybit/linear/BTCUSDT/1m/artifacts" / meta.recipe.kind / tool / meta.artifact_id
    before = disk(root)
    control = ArtifactService(io(root))
    control_full = control.load_artifact_by_id(MARKET, meta.artifact_id)
    assert control.load_artifact_metadata(MARKET, meta.artifact_id) == meta
    pd.testing.assert_frame_equal(control_full.frame, calculation.to_frame().reset_index(drop=True))
    observed = {"root": str(root), "root_length": len(str(root)), "directory_length": len(str(directory)), "payload_length": len(str(directory / "artifact.meta.json")), "copy_preparation": depth != "short", "before": before, "extended_control_validated": True, "ordinary_is_file": (directory / "artifact.meta.json").is_file(), "extended_is_file": io(directory / "artifact.meta.json").is_file()}
    if depth != "short":
        assert observed["payload_length"] >= 270
    service = ArtifactService(root)
    try:
        if mode == "metadata":
            assert service.load_artifact_metadata(MARKET, meta.artifact_id) == meta
        else:
            loaded = service.load_artifact(MARKET, meta.recipe.kind, tool, meta.artifact_id)
            pd.testing.assert_frame_equal(loaded.frame, control_full.frame)
            assert loaded.metadata == control_full.metadata == meta
            assert loaded.analysis == control_full.analysis == calculation.analysis
            raw = service._store.read_artifact_bytes(directory)
            assert raw == control._store.read_artifact_bytes(io(directory))
            assert (raw[1] is None) == (tool == "sma")
        observed["ordinary_success"] = True
    except Exception as exc:
        observed.update(ordinary_success=False, error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        observed["after"] = disk(root)
        receipt(request.node.nodeid, "reads", observed)
        assert observed["after"] == before


@pytest.mark.parametrize("depth", ("short", "payload", "root"))
def test_catalogues_recipes_versions_and_canonical_paths_agree(tmp_path, request, depth):
    root, _, saved = canonical_tree(case_root(tmp_path, request), depth, ("sma", "dynamic_binning"))
    service, control = ArtifactService(root), ArtifactService(io(root))
    before = disk(root)
    expected = tuple(item.metadata.artifact_id for item, _ in saved)
    assert tuple(item.artifact_id for item in service.list_artifacts(MARKET)) == expected
    assert tuple(item.artifact_id for item in service.list_artifacts_metadata(MARKET)) == expected
    for kind, tool in ((None, None), ("indicator", None), (None, "sma"), ("indicator", "sma"), ("construct", "dynamic_binning"), ("oscillator", None), ("indicator", "dynamic_binning")):
        filters = dict(kind=kind, tool_key=tool)
        assert service.list_artifacts(MARKET, **filters) == control.list_artifacts(MARKET, **filters)
        assert service.list_artifacts_metadata(MARKET, **filters) == control.list_artifacts_metadata(MARKET, **filters)
        assert service.list_recipes(MARKET, **filters) == control.list_recipes(MARKET, **filters)
        for iterator in ("iter_artifact_dirs", "iter_recipe_paths"):
            normal = tuple(getattr(service._store, iterator)(MARKET, **filters))
            extended = tuple(getattr(control._store, iterator)(MARKET, **filters))
            assert normal == tuple(sorted(normal))
            assert normal == tuple(ordinary(p) for p in extended)
            assert all(not str(p).startswith("\\\\?\\") and p.is_relative_to(root) for p in normal)
    assert all(x.valid and x.artifact_id for x in service.list_managed_artifacts_metadata(MARKET))
    assert service.list_managed_artifacts(MARKET) == control.list_managed_artifacts(MARKET)
    assert service.list_managed_artifacts_metadata(MARKET) == control.list_managed_artifacts_metadata(MARKET)
    for prepared, calculation in saved:
        meta = prepared.metadata
        assert service.load_recipe(MARKET, meta.recipe.kind, meta.recipe.tool_key, meta.recipe.recipe_id) == meta.recipe
        assert service.load_artifact_head(MARKET, prepared.logical_artifact_id) == prepared.head
        assert service.list_artifact_versions(MARKET, prepared.logical_artifact_id) == (prepared.version_record,)
        assert service.load_artifact_version(MARKET, prepared.logical_artifact_id, meta.artifact_id) == prepared.version_record
        pd.testing.assert_frame_equal(service.load_artifact_by_id(MARKET, meta.artifact_id).frame, calculation.to_frame().reset_index(drop=True))
    assert disk(root) == before
    receipt(request.node.nodeid, "catalogue", {"root":str(root), "files":before, "artifact_ids":expected, "ordinary_prefix_preserved":True})


@pytest.mark.parametrize("damage", ("missing", "extra", "directory", "bad_json", "bad_schema", "identity", "checksum", "missing_analysis"))
@pytest.mark.parametrize("depth", ("short", "payload"))
def test_invalid_payloads_remain_rejected(tmp_path, request, damage, depth):
    tool = "dynamic_binning" if damage == "missing_analysis" else "sma"
    root, _, saved = canonical_tree(case_root(tmp_path, request), depth, (tool,))
    meta = saved[0][0].metadata
    service = ArtifactService(root)
    directory = service._store.artifact_dir(MARKET, meta.recipe.kind, tool, meta.artifact_id)
    values, metadata = io(directory / "values.csv"), io(directory / "artifact.meta.json")
    if damage == "missing":
        values.unlink()
    elif damage == "extra":
        io(directory / "extra.txt").write_bytes(b"unrelated")
    elif damage == "directory":
        values.unlink(); values.mkdir()
    elif damage == "bad_json":
        metadata.write_bytes(b"not json\n")
    elif damage in ("bad_schema", "identity"):
        payload = json.loads(metadata.read_bytes())
        payload["schema_version" if damage == "bad_schema" else "artifact_id"] = 999 if damage == "bad_schema" else "f" * 64
        metadata.write_bytes(encode_canonical_json(payload))
    elif damage == "checksum":
        values.write_bytes(values.read_bytes().replace(b"101", b"901", 1))
    else:
        io(directory / "analysis.json").unlink()
    before = disk(root)
    with pytest.raises(ArtifactValidationError):
        service.load_artifact(MARKET, meta.recipe.kind, tool, meta.artifact_id)
    if damage not in ("checksum", "missing_analysis"):
        with pytest.raises(ArtifactValidationError):
            service.load_artifact_metadata(MARKET, meta.artifact_id)
    assert disk(root) == before
    receipt(request.node.nodeid, "refusal", {"damage":damage, "root":str(root), "unchanged":before})


def test_missing_objects_empty_catalogues_and_unsafe_filters(tmp_path, request):
    root = deep_root(case_root(tmp_path, request), 400)
    service = ArtifactService(root)
    for filters in ({}, {"kind":"indicator"}, {"tool_key":"sma"}, {"kind":"indicator", "tool_key":"sma"}):
        assert service.list_artifacts(MARKET, **filters) == ()
        assert service.list_recipes(MARKET, **filters) == ()
    for operation in (lambda: service.load_recipe(MARKET,"indicator","sma","a"*64), lambda: service.load_artifact(MARKET,"indicator","sma","a"*64)):
        with pytest.raises(ArtifactNotFoundError): operation()
    for filters in ({"kind":"../indicator"}, {"tool_key":"../sma"}, {"tool_key":"SMA"}, {"kind":"indicator/../construct"}):
        for operation in (service.list_artifacts, service.list_artifacts_metadata, service.list_recipes):
            with pytest.raises(ArtifactValidationError): operation(MARKET, **filters)
    with pytest.raises(ArtifactValidationError, match="escapes"):
        service._store.read_recipe_bytes(root / ".." / "outside.json")
    assert not io(root).exists()


@pytest.mark.parametrize("placement", ("root", "artifact_kind", "artifact_tool", "artifact", "payload", "recipe_kind", "recipe_tool", "recipe_file"))
def test_actual_junction_refusal_preserves_external_target(request, placement):
    manifest = Path(os.environ["R02_JUNCTIONS"])
    fixture = json.loads(manifest.read_text())[placement]
    root, link, target = (Path(fixture[k]) for k in ("root", "link", "target"))
    assert link.is_junction() and not link.is_symlink()
    before = disk(target)
    assert before == fixture["target_before"]
    with pytest.raises(ArtifactValidationError, match="link|junction"):
        if placement == "root":
            ArtifactService(root)
        else:
            service = ArtifactService(root)
            if placement == "payload":
                service.load_artifact(MARKET, "indicator", "sma", "a" * 64)
            elif placement == "recipe_file":
                service.load_recipe(MARKET, "indicator", "sma", "a" * 64)
            elif placement.startswith("recipe"):
                service.list_recipes(MARKET)
            else:
                service.list_artifacts_metadata(MARKET)
    assert disk(target) == before
    receipt(request.node.nodeid, "junction", {"placement":placement, "link":str(link), "target":str(target), "target_unchanged":before, "real_junction":True})


def test_io_mapping_preserves_explicit_prefix_and_unc_without_access():
    assert os.name == "nt", "R02 mapping control is explicitly Windows"
    normal = Path(r"C:\synthetic\file")
    assert str(_io_path(normal)) == "\\\\?\\" + str(normal)
    extended = Path(r"\\?\C:\synthetic\file")
    assert _io_path(extended) == extended
    unc = Path(r"\\synthetic-host\share\file")
    assert str(_io_path(unc)) == r"\\?\UNC\synthetic-host\share\file"


def _e2_cleanup_fixture(tmp_path, request, depth, tool="sma"):
    root, _, saved = canonical_tree(case_root(tmp_path, request), depth, (tool,))
    meta = saved[0][0].metadata
    store = ArtifactService(root)._store
    directory = store.artifact_dir(MARKET, meta.recipe.kind, tool, meta.artifact_id)
    sibling = directory.parent / "unrelated-sibling"
    io(sibling).mkdir()
    io(sibling / "sentinel.bin").write_bytes(b"E2 unrelated sibling")
    io(root / "sentinel.bin").write_bytes(b"E2 root sentinel")
    return root, store, directory


def _e2_cleanup_call(request, root, store, directory, **details):
    before = disk(root)
    error = None
    try:
        store.delete_artifact_dir(directory)
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt(request.node.nodeid, "e2_cleanup", {
            "root": str(root), "directory": str(directory),
            "metadata_length": len(str(directory / "artifact.meta.json")),
            "before": before, "after": disk(root), "error": error, **details,
        })
    return before


@pytest.mark.parametrize("depth", ("short", "payload"))
@pytest.mark.parametrize("tool", ("sma", "dynamic_binning"))
def test_e2_cleanup_legal_complete_inventory(tmp_path, request, depth, tool):
    root, store, directory = _e2_cleanup_fixture(tmp_path, request, depth, tool)
    names = {p.name for p in io(directory).iterdir()}
    assert names == ({"values.csv", "artifact.meta.json"} | ({"analysis.json"} if tool == "dynamic_binning" else set()))
    before = _e2_cleanup_call(request, root, store, directory, copied_fixture=depth != "short", tool=tool)
    prefix = directory.relative_to(root).as_posix() + "/"
    assert disk(root) == {k: v for k, v in before.items() if not k.startswith(prefix)}
    assert not io(directory).exists()


@pytest.mark.parametrize("depth", ("short", "payload"))
@pytest.mark.parametrize("mask", range(8))
def test_e2_cleanup_all_allowed_subsets(tmp_path, request, depth, mask):
    root, store, directory = _e2_cleanup_fixture(tmp_path, request, depth, "dynamic_binning")
    names = ("values.csv", "analysis.json", "artifact.meta.json")
    for bit, name in enumerate(names):
        if not mask & (1 << bit):
            io(directory / name).unlink()
    before = _e2_cleanup_call(request, root, store, directory, mask=mask, copied_fixture=depth != "short")
    prefix = directory.relative_to(root).as_posix() + "/"
    assert disk(root) == {k: v for k, v in before.items() if not k.startswith(prefix)}
    assert not io(directory).exists()


@pytest.mark.parametrize("depth", ("short", "payload"))
def test_e2_cleanup_missing_directory_keeps_error(tmp_path, request, depth):
    root, store, directory = _e2_cleanup_fixture(tmp_path, request, depth)
    missing = directory.parent / ("f" * 64)
    before = disk(root)
    with pytest.raises(ArtifactNotFoundError, match="artifact not found: " + "f" * 64):
        _e2_cleanup_call(request, root, store, missing)
    assert disk(root) == before


@pytest.mark.parametrize("depth", ("short", "payload"))
@pytest.mark.parametrize("damage", ("extra", "directory"))
def test_e2_cleanup_rejects_whole_inventory_before_unlink(tmp_path, request, depth, damage):
    root, store, directory = _e2_cleanup_fixture(tmp_path, request, depth, "dynamic_binning")
    if damage == "extra":
        io(directory / "unowned.bin").write_bytes(b"must not delete")
    else:
        io(directory / "artifact.meta.json").unlink()
        io(directory / "artifact.meta.json").mkdir()
        io(directory / "artifact.meta.json" / "sentinel.bin").write_bytes(b"must not recurse")
    before = disk(root)
    with pytest.raises(ArtifactValidationError, match="artifact directory contains unexpected entries"):
        _e2_cleanup_call(request, root, store, directory, damage=damage)
    assert disk(root) == before
    assert io(directory).is_dir()


@pytest.mark.parametrize("placement", ("e2_artifact", "e2_payload"))
def test_e2_cleanup_real_junction_refusal(request, placement):
    fixture = json.loads(Path(os.environ["R02_JUNCTIONS"]).read_text())[placement]
    root, directory, link, target = (Path(fixture[k]) for k in ("root", "directory", "link", "target"))
    assert link.is_junction() and not link.is_symlink()
    target_before, root_before = disk(target), disk(root)
    assert target_before == fixture["target_before"]
    with pytest.raises(ArtifactValidationError, match="link|junction"):
        _e2_cleanup_call(request, root, ArtifactService(root)._store, directory, real_junction=str(link), target_before=target_before)
    assert disk(target) == target_before
    assert disk(root) == root_before
    receipt(request.node.nodeid, "e2_junction_target", {"target_after": disk(target), "target_before": target_before, "link": str(link)})


@pytest.mark.parametrize("depth", ("short", "payload"))
def test_e2_cleanup_propagates_post_first_unlink_io_error(tmp_path, request, monkeypatch, depth):
    root, store, directory = _e2_cleanup_fixture(tmp_path, request, depth)
    before = disk(root)
    original = Path.unlink
    calls = []

    def unlink(path, missing_ok=False):
        canonical = ordinary(path)
        if canonical.parent == directory:
            calls.append({"name": canonical.name, "missing_ok": missing_ok})
            if canonical.name == "artifact.meta.json":
                raise OSError(5, "E2 injected post-first-unlink I/O refusal")
        return original(path, missing_ok=missing_ok)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", unlink)
        with pytest.raises(OSError, match="E2 injected post-first-unlink"):
            _e2_cleanup_call(request, root, store, directory, injected_error=True, calls=calls)
    removed = (directory / "values.csv").relative_to(root).as_posix()
    assert disk(root) == {k: v for k, v in before.items() if k != removed}
    assert io(directory).is_dir() and not io(directory / "values.csv").exists()
    assert calls == [{"name": n, "missing_ok": True} for n in ("values.csv", "analysis.json", "artifact.meta.json")]
