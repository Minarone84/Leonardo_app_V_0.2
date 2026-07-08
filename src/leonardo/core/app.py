"""Core application runtime skeleton for Leonardo V2."""

from __future__ import annotations

from dataclasses import dataclass

from leonardo.contracts.kernel import (
    ContractDescriptor,
    ContractOwner,
    ContractSchemaKind,
    ContractStatus,
)
from leonardo.contracts.runtime import AppLifecycleStatus, ServiceLifecycleStatus
from leonardo.contracts.services import ServiceKind
from leonardo.core.audit_log import (
    AuditLog,
    CompositeAuditSink,
    InMemoryAuditSink,
    JsonlAuditSink,
)
from leonardo.core.action_registry import ActionRegistry
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.config import AppConfig, AuditConfig, load_default_config
from leonardo.core.contract_registry import ContractRegistry
from leonardo.core.core_runner import CoreRunner
from leonardo.core.core_runtime_bridge import CoreRuntimeBridge
from leonardo.core.error_router import ErrorRouter
from leonardo.core.operation_registry import OperationRegistry
from leonardo.core.process_manager import ProcessManager
from leonardo.core.runtime_manager import RuntimeManagerBackend
from leonardo.core.service_registry import ServiceRegistry
from leonardo.core.session_manager import SessionManager
from leonardo.core.state_store import StateStore
from leonardo.core.task_manager import TaskManager
from leonardo.core.user_policy import UserPolicy
from leonardo.core.window_registry import WindowRegistry


@dataclass(frozen=True)
class CoreContext:
    """Container for Core components constructed by ``LeonardoApp``."""

    config: AppConfig
    audit_log: AuditLog
    contract_registry: ContractRegistry
    state_store: StateStore
    session_manager: SessionManager
    user_policy: UserPolicy
    service_registry: ServiceRegistry
    error_router: ErrorRouter
    task_manager: TaskManager
    core_runner: CoreRunner
    core_runtime_bridge: CoreRuntimeBridge
    process_manager: ProcessManager
    connection_registry: ConnectionRegistry
    window_registry: WindowRegistry
    action_registry: ActionRegistry
    operation_registry: OperationRegistry
    runtime_manager: RuntimeManagerBackend


class LeonardoApp:
    """
    Composition root for the initial Leonardo V2 Core runtime foundation.

    The skeleton owns construction of Core services and lifecycle state
    transitions. It does not start an async runtime, GUI, process, connection,
    or domain workflow.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config if config is not None else load_default_config()
        self.audit_log = _build_audit_log(self.config.audit)
        self.contract_registry = ContractRegistry()
        self.state_store = StateStore(self.audit_log)
        self.session_manager = SessionManager(audit_log=self.audit_log)
        self.user_policy = UserPolicy()
        self.service_registry = ServiceRegistry()
        self.error_router = ErrorRouter(
            self.audit_log,
            session_context_provider=lambda: self.session_manager.current_session,
        )
        self.task_manager = TaskManager(
            self.state_store,
            error_router=self.error_router,
        )
        self.operation_registry = OperationRegistry(self.state_store)
        self.core_runner = CoreRunner(
            self.task_manager,
            error_router=self.error_router,
        )
        self.core_runtime_bridge = CoreRuntimeBridge(
            self.core_runner,
            operation_registry=self.operation_registry,
            session_provider=self.session_manager,
            user_policy=self.user_policy,
            audit_log=self.audit_log,
        )
        self.process_manager = ProcessManager(
            self.state_store,
            self.audit_log,
            error_router=self.error_router,
        )
        self.connection_registry = ConnectionRegistry(self.state_store)
        self.window_registry = WindowRegistry(self.state_store)
        self.action_registry = ActionRegistry(self.state_store)
        self.runtime_manager = RuntimeManagerBackend(
            state_store=self.state_store,
            session_manager=self.session_manager,
            service_registry=self.service_registry,
            task_manager=self.task_manager,
            process_manager=self.process_manager,
            connection_registry=self.connection_registry,
            window_registry=self.window_registry,
            action_registry=self.action_registry,
            operation_registry=self.operation_registry,
            audit_log=self.audit_log,
            contract_registry=self.contract_registry,
        )
        self._context = CoreContext(
            config=self.config,
            audit_log=self.audit_log,
            contract_registry=self.contract_registry,
            state_store=self.state_store,
            session_manager=self.session_manager,
            user_policy=self.user_policy,
            service_registry=self.service_registry,
            error_router=self.error_router,
            task_manager=self.task_manager,
            core_runner=self.core_runner,
            core_runtime_bridge=self.core_runtime_bridge,
            process_manager=self.process_manager,
            connection_registry=self.connection_registry,
            window_registry=self.window_registry,
            action_registry=self.action_registry,
            operation_registry=self.operation_registry,
            runtime_manager=self.runtime_manager,
        )

    @property
    def context(self) -> CoreContext:
        """Return Core components constructed by the application root."""

        return self._context

    def startup(self) -> CoreContext:
        """
        Start the Core runtime foundation.

        Startup failures are routed through ``ErrorRouter`` and then re-raised so
        callers can handle the failed startup explicitly.
        """

        if self.state_store.get_app_status() is AppLifecycleStatus.RUNNING:
            return self._context

        try:
            self.state_store.set_app_lifecycle_status(AppLifecycleStatus.STARTING)
            self._register_runtime_contracts()
            self.state_store.set_app_lifecycle_status(AppLifecycleStatus.RUNNING)
            return self._context
        except Exception as exc:
            self.state_store.set_app_lifecycle_status(
                AppLifecycleStatus.FAILED,
                message="Application startup failed",
            )
            self.error_router.route_exception(
                exc,
                message="Application startup failed",
                context={"phase": "startup"},
            )
            raise

    def start_core_runtime(self) -> CoreContext:
        """
        Start the explicit Core async runtime boundary.

        `LeonardoApp.startup()` prepares Core state and contract registration.
        The persistent async runner starts only through this explicit app-level
        boundary, or through direct bridge use in focused Core tests.

        Raises
        ------
        RuntimeError
            Raised when application startup has not completed.
        """

        if self.state_store.get_app_status() is not AppLifecycleStatus.RUNNING:
            raise RuntimeError(
                "Application startup must complete before Core runtime start"
            )
        self.core_runtime_bridge.start()
        return self._context

    def stop_core_runtime(self, *, timeout: float = 5.0) -> None:
        """
        Stop the explicit Core async runtime boundary.

        The stop operation is idempotent and remains safe when the async runner
        was never started.
        """

        if type(timeout) not in (float, int) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.core_runtime_bridge.shutdown(timeout=float(timeout))

    def shutdown(
        self,
        *,
        timeout: float = 5.0,
        reason: str = "Application shutdown requested",
    ) -> None:
        """Stop the Core runtime foundation. Shutdown is idempotent."""

        if type(timeout) not in (float, int) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if not isinstance(reason, str):
            raise TypeError("reason must be a string")

        status = self.state_store.get_app_status()
        if status is AppLifecycleStatus.STOPPED:
            self.stop_core_runtime(timeout=float(timeout))
            return

        preserve_failed_state = status is AppLifecycleStatus.FAILED
        if not preserve_failed_state:
            self.state_store.set_app_lifecycle_status(
                AppLifecycleStatus.STOPPING,
                message=reason,
            )

        try:
            self._shutdown_runtime_resources(
                timeout=float(timeout),
                reason=reason,
            )
        except Exception as exc:
            self.state_store.set_app_lifecycle_status(
                AppLifecycleStatus.FAILED,
                message="Application shutdown failed",
            )
            self.error_router.route_exception(
                exc,
                message="Application shutdown failed",
                context={
                    "phase": "shutdown",
                    "timeout_s": float(timeout),
                    "reason": reason,
                },
            )
            raise
        else:
            if not preserve_failed_state:
                self.state_store.set_app_lifecycle_status(
                    AppLifecycleStatus.STOPPED,
                    message="Application stopped",
                )
        finally:
            self.audit_log.close()

    def _shutdown_runtime_resources(
        self,
        *,
        timeout: float,
        reason: str,
    ) -> None:
        errors: list[tuple[str, Exception]] = []

        shutdown_steps = (
            (
                "core_runtime",
                lambda: self.stop_core_runtime(timeout=timeout),
            ),
            ("processes", self.process_manager.stop_all),
            (
                "connections",
                lambda: self.connection_registry.shutdown_tracking(reason=reason),
            ),
            ("services", lambda: self._shutdown_lifecycle_services(reason=reason)),
        )
        for step_name, shutdown_step in shutdown_steps:
            try:
                shutdown_step()
            except Exception as exc:
                self.error_router.route_exception(
                    exc,
                    message=f"Application shutdown step failed: {step_name}",
                    context={
                        "phase": "shutdown",
                        "step": step_name,
                        "timeout_s": timeout,
                        "reason": reason,
                    },
                )
                errors.append((step_name, exc))

        if errors:
            failed_steps = ", ".join(step_name for step_name, _exc in errors)
            raise RuntimeError(f"Application shutdown failed: {failed_steps}")

    def _shutdown_lifecycle_services(self, *, reason: str) -> None:
        service_states = {
            state.service_id: state
            for state in self.state_store.runtime_snapshot().service_states
        }
        lifecycle_services = self.service_registry.list_services(
            kind=ServiceKind.LIFECYCLE,
        )
        for registered in reversed(lifecycle_services):
            service_id = registered.descriptor.service_id
            state = service_states.get(service_id)
            if state is None:
                continue
            if state.status in {
                ServiceLifecycleStatus.STOPPED,
                ServiceLifecycleStatus.FAILED,
            }:
                continue
            self.state_store.set_service_lifecycle_status(
                service_id,
                ServiceLifecycleStatus.STOPPING,
                message=f"Service stopping during shutdown: {service_id}",
            )
            self.state_store.set_service_lifecycle_status(
                service_id,
                ServiceLifecycleStatus.STOPPED,
                message=f"Service stopped during shutdown: {service_id}. {reason}",
            )

    def _register_runtime_contracts(self) -> None:
        for descriptor in _runtime_contract_descriptors():
            if self.contract_registry.get_contract(
                descriptor.contract_id,
                descriptor.version,
            ) is None:
                self.contract_registry.register_contract(descriptor)


def _runtime_contract_descriptors() -> tuple[ContractDescriptor, ...]:
    return (
        _descriptor(
            "leonardo.identity.user_ref",
            required_fields=("user_id", "username", "roles", "permissions", "is_active"),
        ),
        _descriptor(
            "leonardo.identity.session_context",
            required_fields=("session_id", "actor", "origin", "started_at_utc"),
        ),
        _descriptor(
            "leonardo.audit.event",
            required_fields=(
                "event_id",
                "schema_version",
                "timestamp_utc",
                "severity",
                "category",
                "event_type",
                "message",
            ),
        ),
        _descriptor(
            "leonardo.runtime.app_state",
            required_fields=("status", "last_updated_utc"),
        ),
        _descriptor(
            "leonardo.runtime.service_state",
            required_fields=("service_id", "status", "last_updated_utc"),
        ),
        _descriptor(
            "leonardo.runtime.task_state",
            required_fields=(
                "task_id",
                "task_name",
                "status",
                "started_at_utc",
                "updated_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.core_runtime.metadata",
            required_fields=("schema_version",),
        ),
        _descriptor(
            "leonardo.core_runtime.command",
            required_fields=("command_id", "command_type", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.query",
            required_fields=("query_id", "query_type", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.progress",
            required_fields=("command_id", "task_id", "message", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.result",
            required_fields=("command_id", "task_id", "status", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.cancellation_request",
            required_fields=("task_id", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.cancellation_result",
            required_fields=("task_id", "requested", "message", "metadata"),
        ),
        _descriptor(
            "leonardo.core_runtime.error",
            required_fields=("error_type", "message"),
        ),
        _descriptor(
            "leonardo.processes.launch_request",
            required_fields=("process_id", "label", "command", "kind"),
        ),
        _descriptor(
            "leonardo.processes.runtime_state",
            required_fields=(
                "process_id",
                "label",
                "kind",
                "status",
                "command",
                "updated_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.processes.exit_record",
            required_fields=(
                "process_id",
                "exit_code",
                "status",
                "completed_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.connections.endpoint",
            required_fields=("label", "protocol"),
        ),
        _descriptor(
            "leonardo.connections.definition",
            required_fields=(
                "connection_id",
                "label",
                "kind",
                "protocol",
                "direction",
            ),
        ),
        _descriptor(
            "leonardo.connections.runtime_state",
            required_fields=(
                "connection_id",
                "label",
                "kind",
                "protocol",
                "direction",
                "status",
                "registered_at_utc",
                "updated_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.connections.websocket_channel_definition",
            required_fields=("channel_id", "connection_id", "label"),
        ),
        _descriptor(
            "leonardo.connections.websocket_channel_runtime_state",
            required_fields=(
                "channel_id",
                "connection_id",
                "label",
                "status",
                "registered_at_utc",
                "updated_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.connections.event_record",
            required_fields=(
                "event_type",
                "connection_id",
                "status",
                "timestamp_utc",
            ),
        ),
        _descriptor(
            "leonardo.gui.window_definition",
            required_fields=("window_id", "title", "window_type"),
        ),
        _descriptor(
            "leonardo.gui.action_definition",
            required_fields=("action_id", "label", "kind"),
        ),
        _descriptor(
            "leonardo.operations.operation_state",
            required_fields=(
                "operation_id",
                "operation_kind",
                "status",
                "label",
                "requested_at_utc",
                "updated_at_utc",
            ),
        ),
        _descriptor(
            "leonardo.services.service_descriptor",
            required_fields=("service_id", "kind"),
        ),
        _descriptor(
            "leonardo.errors.error_report",
            required_fields=("error_id", "timestamp_utc", "severity", "message"),
        ),
    )


def _descriptor(
    contract_id: str,
    *,
    required_fields: tuple[str, ...],
) -> ContractDescriptor:
    return ContractDescriptor(
        contract_id=contract_id,
        version="1.0",
        owner=ContractOwner.CORE,
        status=ContractStatus.ACTIVE,
        schema_kind=ContractSchemaKind.FIELD_SET,
        required_fields=required_fields,
    )


def _build_audit_log(config: AuditConfig) -> AuditLog:
    memory_sink = InMemoryAuditSink(max_events=config.memory_max_events)
    if not config.enabled or not config.jsonl_enabled:
        return AuditLog(memory_sink)

    if config.jsonl_path is None:
        raise ValueError("audit.jsonl_path must be configured when JSONL audit is enabled")
    return AuditLog(
        CompositeAuditSink(
            (
                memory_sink,
                JsonlAuditSink(config.jsonl_path),
            )
        )
    )
