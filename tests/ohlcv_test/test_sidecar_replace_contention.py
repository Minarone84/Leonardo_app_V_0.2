from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from leonardo.data import canonicalize_market_id
from leonardo.ohlcv import store as store_module
from leonardo.ohlcv.store import Candle, OHLCVStore


@pytest.fixture
def sidecar_case(tmp_path: Path):
    store = OHLCVStore(tmp_path)
    market = canonicalize_market_id("bybit", "linear", "BTCUSDT", "1m")
    original = store.write(
        market,
        (Candle(60_000, 1, 2, 0.5, 1.5, 10),),
        source="test",
        persistence_status="partial",
    )
    updated = replace(original, persistence_status="committed")
    path = store.sidecar_path(market)
    csv_path = store.csv_path(market)
    return SimpleNamespace(
        store=store,
        path=path,
        sidecar=updated,
        old_bytes=path.read_bytes(),
        expected_bytes=(json.dumps(updated.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
        csv_path=csv_path,
        csv_before=(csv_path.read_bytes(), csv_path.stat().st_mtime_ns),
    )


def _assert_preserved(case, *, success: bool) -> None:
    assert case.path.read_bytes() == (case.expected_bytes if success else case.old_bytes)
    assert (case.csv_path.read_bytes(), case.csv_path.stat().st_mtime_ns) == case.csv_before
    assert not list(case.path.parent.glob(".candles-*.json.tmp"))


def _observe_temp(attempts, source, destination, case) -> None:
    assert destination == case.path
    assert source.read_bytes() == case.expected_bytes
    attempts.append((source, destination, source.stat().st_mtime_ns))
    assert all(item == attempts[0] for item in attempts)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows read-handle replacement contention")
def test_real_reader_released_after_first_failure_allows_replace(sidecar_case, monkeypatch) -> None:
    case = sidecar_case
    ready, release, closed = Event(), Event(), Event()
    reader_errors = []
    attempts, failures = [], []
    real_replace = store_module.os.replace

    def reader() -> None:
        try:
            with case.path.open("rb") as handle:
                assert handle.read() == case.old_bytes
                ready.set()
                assert release.wait(5), "Writer did not release the reader"
        except BaseException as error:
            reader_errors.append(error)
        finally:
            closed.set()

    def observed_replace(source, destination) -> None:
        _observe_temp(attempts, source, destination, case)
        try:
            real_replace(source, destination)
        except OSError as error:
            failures.append(error)
            assert len(attempts) == 1
            assert error.winerror in (5, 32)
            release.set()
            assert closed.wait(5), "Reader did not close after the real failure"
            raise

    worker = Thread(target=reader, name="sidecar-contention-reader")
    worker.start()
    try:
        assert ready.wait(5), "Reader did not acquire its handle"
        monkeypatch.setattr(store_module.os, "replace", observed_replace)
        case.store._write_sidecar_atomic(case.path, case.sidecar)
    finally:
        release.set()
        worker.join(5)
        assert not worker.is_alive(), "Owned reader thread did not stop"
    assert not reader_errors
    assert len(failures) == 1
    assert len(attempts) == 2
    _assert_preserved(case, success=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows read-handle replacement contention")
def test_real_reader_held_through_all_attempts_preserves_old_sidecar(sidecar_case, monkeypatch) -> None:
    case = sidecar_case
    attempts, failures, waits = [], [], []
    real_replace, real_sleep = store_module.os.replace, store_module.time.sleep

    def observed_replace(source, destination) -> None:
        _observe_temp(attempts, source, destination, case)
        try:
            real_replace(source, destination)
        except OSError as error:
            failures.append(error)
            raise

    def observed_sleep(delay) -> None:
        waits.append(delay)
        real_sleep(delay)

    monkeypatch.setattr(store_module.os, "replace", observed_replace)
    monkeypatch.setattr(store_module, "time", SimpleNamespace(sleep=observed_sleep))
    with case.path.open("rb") as reader:
        assert reader.read() == case.old_bytes
        with pytest.raises(OSError) as caught:
            case.store._write_sidecar_atomic(case.path, case.sidecar)
        assert len(attempts) == len(failures) == 5
        assert all(error.winerror in (5, 32) for error in failures)
        assert caught.value is failures[-1]
        assert waits == [0.05] * 4
        _assert_preserved(case, success=False)


def _error(code):
    error = OSError("controlled replacement failure")
    if code is not None:
        error.winerror = code
    return error


def _policy(monkeypatch, platform="win32"):
    waits = []
    monkeypatch.setattr(store_module, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(store_module, "time", SimpleNamespace(sleep=waits.append))
    return waits


@pytest.mark.parametrize("code", [5, 32])
def test_eligible_errors_exhaust_exact_bound(sidecar_case, monkeypatch, code) -> None:
    case = sidecar_case
    attempts = []
    waits = _policy(monkeypatch)
    error = _error(code)

    def denied(source, destination):
        _observe_temp(attempts, source, destination, case)
        raise error

    monkeypatch.setattr(store_module.os, "replace", denied)
    with pytest.raises(OSError) as caught:
        case.store._write_sidecar_atomic(case.path, case.sidecar)
    assert caught.value is error
    assert len(attempts) == 5
    assert waits == [0.05] * 4
    _assert_preserved(case, success=False)


@pytest.mark.parametrize("code", [5, 32])
@pytest.mark.parametrize("failures_before_success", [0, 1, 4])
def test_success_stops_replacements(sidecar_case, monkeypatch, code, failures_before_success) -> None:
    case = sidecar_case
    attempts = []
    waits = _policy(monkeypatch)
    real_replace = store_module.os.replace

    def eventually_replace(source, destination):
        _observe_temp(attempts, source, destination, case)
        if len(attempts) <= failures_before_success:
            raise _error(code)
        real_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", eventually_replace)
    case.store._write_sidecar_atomic(case.path, case.sidecar)
    assert len(attempts) == failures_before_success + 1
    assert waits == [0.05] * failures_before_success
    _assert_preserved(case, success=True)


@pytest.mark.parametrize("platform,code", [("win32", None), ("win32", 2), ("win32", 33), ("linux", 5), ("linux", 32)])
def test_ineligible_errors_propagate_without_retry(sidecar_case, monkeypatch, platform, code) -> None:
    case = sidecar_case
    attempts = []
    waits = _policy(monkeypatch, platform)
    error = _error(code)

    def denied(source, destination):
        _observe_temp(attempts, source, destination, case)
        raise error

    monkeypatch.setattr(store_module.os, "replace", denied)
    with pytest.raises(OSError) as caught:
        case.store._write_sidecar_atomic(case.path, case.sidecar)
    assert caught.value is error
    assert len(attempts) == 1
    assert waits == []
    _assert_preserved(case, success=False)


@pytest.mark.parametrize("stage", ["serialization", "flush", "fsync"])
def test_pre_replace_errors_are_not_retried(sidecar_case, monkeypatch, stage) -> None:
    case = sidecar_case
    waits = _policy(monkeypatch)
    error = _error(5)
    stage_calls, replace_calls = [], []

    def fail(*args, **kwargs):
        stage_calls.append(stage)
        raise error

    def unexpected_replace(*args):
        replace_calls.append(args)
        raise AssertionError("Replacement must not run after a serialization/flush failure")

    monkeypatch.setattr(store_module.os, "replace", unexpected_replace)
    if stage == "serialization":
        monkeypatch.setattr(store_module.json, "dump", fail)
    elif stage == "fsync":
        monkeypatch.setattr(store_module.os, "fsync", fail)
    else:
        real_fdopen = store_module.os.fdopen

        class FailingFlush:
            def __init__(self, *args, **kwargs):
                self.handle = real_fdopen(*args, **kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, text):
                return self.handle.write(text)

            def flush(self):
                fail()

        monkeypatch.setattr(store_module.os, "fdopen", FailingFlush)
    with pytest.raises(OSError) as caught:
        case.store._write_sidecar_atomic(case.path, case.sidecar)
    assert caught.value is error
    assert stage_calls == [stage]
    assert replace_calls == waits == []
    _assert_preserved(case, success=False)
