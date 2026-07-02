import pytest

from leonardo.contracts.processes import (
    ProcessKind,
    ProcessLaunchRequest,
    ProcessLifecycleStatus,
)
from leonardo.core.audit_log import AuditLog
from leonardo.core.error_router import ErrorRouter
from leonardo.core.process_manager import ProcessManager
from leonardo.core.state_store import StateStore


class FakeHandle:
    def __init__(self, pid: int = 1001, exit_code: int | None = None) -> None:
        self.pid = pid
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        return 0 if self.exit_code is None else self.exit_code


class FakeLauncher:
    def __init__(self, handle: FakeHandle | None = None) -> None:
        self.handle = handle if handle is not None else FakeHandle()
        self.requests: list[ProcessLaunchRequest] = []

    def start(self, request: ProcessLaunchRequest) -> FakeHandle:
        self.requests.append(request)
        return self.handle


def _manager(
    handle: FakeHandle | None = None,
) -> tuple[ProcessManager, StateStore, AuditLog, FakeLauncher]:
    audit_log = AuditLog()
    state_store = StateStore(audit_log)
    launcher = FakeLauncher(handle)
    return (
        ProcessManager(
            state_store,
            audit_log,
            launcher=launcher,
            error_router=ErrorRouter(audit_log),
        ),
        state_store,
        audit_log,
        launcher,
    )


def _request(process_id: str = "process-1") -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        process_id=process_id,
        label="Inspect runtime",
        command=("python", "-c", "print('ok')"),
        kind=ProcessKind.UTILITY,
        correlation_id="corr-1",
    )


def test_process_manager_starts_fake_process_and_records_active_state() -> None:
    manager, state_store, audit_log, launcher = _manager()

    state = manager.launch_process(_request())

    assert launcher.requests[0].process_id == "process-1"
    assert state.status is ProcessLifecycleStatus.RUNNING
    assert state.pid == 1001
    assert state_store.processes_state() == (state,)
    assert [event.event_type for event in audit_log.snapshot()] == [
        "process.lifecycle.starting",
        "process.lifecycle.running",
    ]


def test_process_manager_rejects_duplicate_active_process_id() -> None:
    manager, _state_store, _audit_log, _launcher = _manager()
    manager.launch_process(_request())

    with pytest.raises(ValueError, match="already active"):
        manager.launch_process(_request())


def test_poll_process_moves_completed_process_out_of_active_state() -> None:
    handle = FakeHandle(exit_code=0)
    manager, state_store, audit_log, _launcher = _manager(handle)
    manager.launch_process(_request())

    terminal = manager.poll_process("process-1")

    assert terminal.status is ProcessLifecycleStatus.STOPPED
    assert terminal.exit_code == 0
    assert state_store.processes_state() == ()
    assert audit_log.snapshot()[-1].event_type == "process.lifecycle.stopped"


def test_failed_process_emits_audit_event_and_is_removed() -> None:
    handle = FakeHandle(exit_code=2)
    manager, state_store, audit_log, _launcher = _manager(handle)
    manager.launch_process(_request())

    terminal = manager.refresh_process("process-1")

    assert terminal.status is ProcessLifecycleStatus.FAILED
    assert terminal.exit_code == 2
    assert state_store.processes_state() == ()
    assert audit_log.snapshot()[-1].event_type == "process.lifecycle.failed"


def test_kill_process_emits_audit_event_and_removes_active_state() -> None:
    handle = FakeHandle()
    manager, state_store, audit_log, _launcher = _manager(handle)
    manager.launch_process(_request())

    terminal = manager.kill_process("process-1")

    assert handle.killed is True
    assert terminal.status is ProcessLifecycleStatus.KILLED
    assert terminal.exit_code == -9
    assert state_store.processes_state() == ()
    assert audit_log.snapshot()[-1].event_type == "process.lifecycle.killed"


def test_missing_process_operations_raise_structured_key_errors() -> None:
    manager, _state_store, _audit_log, _launcher = _manager()

    with pytest.raises(KeyError, match="not active"):
        manager.poll_process("missing")
    with pytest.raises(KeyError, match="not active"):
        manager.stop_process("missing")
    with pytest.raises(KeyError, match="not active"):
        manager.kill_process("missing")


def test_stop_all_requests_termination_for_active_fake_handles() -> None:
    handle = FakeHandle()
    manager, state_store, audit_log, _launcher = _manager(handle)
    manager.launch_process(_request())

    stopped = manager.stop_all()

    assert handle.terminated is True
    assert stopped[0].status is ProcessLifecycleStatus.STOP_REQUESTED
    assert state_store.processes_state()[0].status is ProcessLifecycleStatus.STOP_REQUESTED
    assert audit_log.snapshot()[-1].event_type == "process.lifecycle.stop_requested"
