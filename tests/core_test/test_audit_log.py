from leonardo.contracts.audit import AuditCategory, AuditEvent, AuditSeverity
from leonardo.core.audit_log import AuditLog, InMemoryAuditSink


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
