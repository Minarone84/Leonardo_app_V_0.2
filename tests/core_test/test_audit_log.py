import json

from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.core.audit_log import (
    AuditLog,
    CompositeAuditSink,
    InMemoryAuditSink,
    JsonlAuditSink,
)


def _event(index: int) -> AuditEvent:
    return AuditEvent(
        event_type=f"runtime.event.{index}",
        message=f"Runtime event {index}",
        severity=AuditSeverity.INFO,
        category=AuditCategory.RUNTIME,
    )


def test_in_memory_audit_sink_enforces_bounded_retention() -> None:
    audit_log = AuditLog(InMemoryAuditSink(max_events=2))

    audit_log.emit(_event(1))
    audit_log.emit(_event(2))
    audit_log.emit(_event(3))

    snapshot = audit_log.snapshot()
    assert [event.event_type for event in snapshot] == [
        "runtime.event.2",
        "runtime.event.3",
    ]


def test_audit_snapshot_is_immutable_tuple() -> None:
    audit_log = AuditLog()
    event = _event(1)

    audit_log.emit(event)

    snapshot = audit_log.snapshot()
    assert snapshot == (event,)
    assert isinstance(snapshot, tuple)


def test_jsonl_audit_sink_writes_valid_jsonl_and_creates_parent_on_write(tmp_path) -> None:
    audit_path = tmp_path / "audit" / "events.jsonl"
    sink = JsonlAuditSink(audit_path)
    event = _event(1)

    assert not audit_path.parent.exists()

    sink.emit(event)
    sink.close()

    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_id"] == event.event_id
    assert payload["event_type"] == event.event_type


def test_jsonl_audit_sink_flush_and_close_are_idempotent(tmp_path) -> None:
    sink = JsonlAuditSink(tmp_path / "audit.jsonl")

    sink.flush()
    sink.close()
    sink.emit(_event(1))
    sink.flush()
    sink.close()
    sink.close()

    assert (tmp_path / "audit.jsonl").exists()


def test_composite_audit_sink_fans_out_to_memory_and_jsonl(tmp_path) -> None:
    memory_sink = InMemoryAuditSink()
    jsonl_sink = JsonlAuditSink(tmp_path / "audit.jsonl")
    audit_log = AuditLog(CompositeAuditSink((memory_sink, jsonl_sink)))
    event = _event(1)

    audit_log.emit(event)
    audit_log.close()

    assert audit_log.snapshot() == (event,)
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["event_id"] == event.event_id


def test_sink_failure_does_not_prevent_other_sinks_from_receiving_event() -> None:
    class FailingSink:
        def emit(self, event: AuditEvent) -> AuditEvent:
            raise OSError("sink unavailable")

    memory_sink = InMemoryAuditSink()
    audit_log = AuditLog(CompositeAuditSink((FailingSink(), memory_sink)))
    event = _event(1)

    audit_log.emit(event)

    assert audit_log.snapshot() == (event,)
    failures = audit_log.sink_failures()
    assert len(failures) == 1
    assert failures[0].operation == "emit"
    assert failures[0].event_id == event.event_id
