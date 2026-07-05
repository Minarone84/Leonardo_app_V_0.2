"""Core application runtime skeleton for Leonardo V2."""

from __future__ import annotations

from dataclasses import dataclass

from leonardo.contracts.kernel import (
    ContractDescriptor,
    ContractOwner,
    ContractSchemaKind,
    ContractStatus,
)
from leonardo.contracts.runtime import AppLifecycleStatus
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
from leonardo.core.download_capability_catalog import DownloadCapabilityCatalog
from leonardo.core.download_execution_manager import DownloadExecutionManager
from leonardo.core.download_manager import DownloadManager
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
    process_manager: ProcessManager
    connection_registry: ConnectionRegistry
    window_registry: WindowRegistry
    action_registry: ActionRegistry
    operation_registry: OperationRegistry
    download_capability_catalog: DownloadCapabilityCatalog
    download_manager: DownloadManager
    download_execution_manager: DownloadExecutionManager
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
        self.process_manager = ProcessManager(
            self.state_store,
            self.audit_log,
            error_router=self.error_router,
        )
        self.connection_registry = ConnectionRegistry(self.state_store)
        self.window_registry = WindowRegistry(self.state_store)
        self.action_registry = ActionRegistry(self.state_store)
        self.operation_registry = OperationRegistry(self.state_store)
        self.download_capability_catalog = DownloadCapabilityCatalog()
        self.download_manager = DownloadManager(self.audit_log)
        self.download_execution_manager = DownloadExecutionManager(
            self.download_manager,
            self.audit_log,
            self.download_capability_catalog,
        )
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
            download_manager=self.download_manager,
            download_execution_manager=self.download_execution_manager,
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
            process_manager=self.process_manager,
            connection_registry=self.connection_registry,
            window_registry=self.window_registry,
            action_registry=self.action_registry,
            operation_registry=self.operation_registry,
            download_capability_catalog=self.download_capability_catalog,
            download_manager=self.download_manager,
            download_execution_manager=self.download_execution_manager,
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

    def shutdown(self) -> None:
        """Stop the Core runtime foundation. Shutdown is idempotent."""

        status = self.state_store.get_app_status()
        if status is AppLifecycleStatus.STOPPED:
            return
        self.state_store.set_app_lifecycle_status(AppLifecycleStatus.STOPPING)
        self.state_store.set_app_lifecycle_status(AppLifecycleStatus.STOPPED)
        self.audit_log.close()

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
