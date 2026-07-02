from leonardo.contracts.audit import AuditCategory
from leonardo.contracts.errors import ErrorSeverity
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter
from leonardo.core.session_manager import create_development_administrator_session


def test_error_router_converts_exception_to_report_and_audit_event() -> None:
    audit_log = AuditLog()
    session = create_development_administrator_session()
    router = ErrorRouter(audit_log, session_context_provider=lambda: session)

    report = router.route_exception(
        RuntimeError("startup failed"),
        message="Startup failed",
        context={"phase": "startup"},
    )

    event = audit_log.snapshot()[0]
    assert report.exception_type == "RuntimeError"
    assert report.session_id == session.session_id
    assert event.category is AuditCategory.ERROR
    assert event.error is not None
    assert event.payload["context"]["phase"] == "startup"


def test_error_router_converts_explicit_error_to_report() -> None:
    audit_log = AuditLog()
    router = ErrorRouter(audit_log)

    report = router.route_error(
        "Configuration invalid",
        severity=ErrorSeverity.WARNING,
        correlation_id="corr-1",
    )

    assert report.message == "Configuration invalid"
    assert report.correlation_id == "corr-1"
    assert audit_log.snapshot()[0].correlation_id == "corr-1"
