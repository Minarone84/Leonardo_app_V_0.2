"""Single composition root for Leonardo Light V2 runtime infrastructure."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock

from leonardo.audit import AuditEventV1
from leonardo.artifacts import ArtifactService
from leonardo.connection import ConnectionApplicationService, build_default_provider_registry
from leonardo.core.action_registry import ActionRegistry
from leonardo.core.audit_log import AuditLog, CompositeAuditSink, InMemoryAuditSink, JsonlAuditSink
from leonardo.core.config import AppConfig, AuditConfig, load_default_config
from leonardo.core.connection_registry import ConnectionRegistry
from leonardo.core.core_runner import CoreRunner
from leonardo.core.error_router import ErrorRouter
from leonardo.core.process_manager import ProcessManager
from leonardo.core.runtime_manager import RuntimeManagerBackend
from leonardo.core.task_manager import TaskManager
from leonardo.core.window_registry import WindowRegistry
from leonardo.ohlcv import (
    CanonicalOHLCVValidator,
    HistoricalDownloadApplicationService,
    HistoricalDownloadService,
    OHLCVDatasetOperationLocks,
    OHLCVMaintenanceApplicationService,
    OHLCVMaintenanceService,
    OHLCVStore,
)
from leonardo.research import (
    AcceptedDatasetCatalog,
    HistoricalDatasetLoader,
    ResearchDatasetApplicationService,
    ResearchStudyApplicationService,
    ResearchStudyService,
    ResidentSliceService,
)


@dataclass(frozen=True)
class CoreContext:
    config: AppConfig
    logger: logging.Logger
    audit_log: AuditLog
    error_router: ErrorRouter
    task_manager: TaskManager
    core_runner: CoreRunner
    process_manager: ProcessManager
    connection_registry: ConnectionRegistry
    window_registry: WindowRegistry
    action_registry: ActionRegistry
    runtime_manager: RuntimeManagerBackend
    connection_service: ConnectionApplicationService
    historical_download_service: HistoricalDownloadApplicationService
    ohlcv_maintenance_service: OHLCVMaintenanceApplicationService
    research_dataset_service: ResearchDatasetApplicationService
    research_study_service: ResearchStudyApplicationService


class LeonardoApp:
    """Own application-wide runtime construction, startup and ordered shutdown."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_default_config()
        self.logger = _build_operational_logger()
        self.audit_log = _build_audit_log(self.config.audit)
        self.error_router = ErrorRouter(self.audit_log, actor_id=self.config.actor_id)
        self.task_manager = TaskManager(
            error_router=self.error_router,
            audit_log=self.audit_log,
            actor_id=self.config.actor_id,
            logger=self.logger,
        )
        self.core_runner = CoreRunner(self.task_manager)
        self.process_manager = ProcessManager(
            self.audit_log,
            error_router=self.error_router,
            logger=self.logger,
        )
        self.connection_registry = ConnectionRegistry()
        self.window_registry = WindowRegistry()
        self.provider_registry = build_default_provider_registry()
        self.connection_service = ConnectionApplicationService(
            self.provider_registry,
            self.connection_registry,
        )
        self.ohlcv_store = OHLCVStore(self.config.paths.historical_data_dir)
        self.ohlcv_operation_locks = OHLCVDatasetOperationLocks()
        self.historical_download_domain = HistoricalDownloadService(
            self.connection_service,
            self.ohlcv_store,
            self.audit_log,
            actor_id=self.config.actor_id,
            operation_locks=self.ohlcv_operation_locks,
        )
        self.historical_download_service = HistoricalDownloadApplicationService(
            self.core_runner,
            self.historical_download_domain,
        )
        self.ohlcv_validator = CanonicalOHLCVValidator()
        self.ohlcv_maintenance_domain = OHLCVMaintenanceService(
            self.ohlcv_store,
            self.ohlcv_validator,
            audit_log=self.audit_log,
            actor_id=self.config.actor_id,
        )
        self.accepted_dataset_catalog = AcceptedDatasetCatalog(
            self.config.paths.historical_data_dir
        )
        self.historical_dataset_loader = HistoricalDatasetLoader(
            self.accepted_dataset_catalog
        )
        self.resident_slice_service = ResidentSliceService()
        self.ohlcv_maintenance_service = OHLCVMaintenanceApplicationService(
            self.core_runner,
            self.ohlcv_maintenance_domain,
            self.historical_download_domain,
            operation_locks=self.ohlcv_operation_locks,
            cache_invalidator=self.historical_dataset_loader.invalidate,
        )
        self.research_dataset_service = ResearchDatasetApplicationService(
            self.core_runner,
            self.historical_dataset_loader,
            catalog=self.accepted_dataset_catalog,
            resident_slices=self.resident_slice_service,
        )
        self.artifact_service = ArtifactService(
            self.config.paths.historical_data_dir
        )
        self.research_study_domain = ResearchStudyService(self.artifact_service)
        self.research_study_service = ResearchStudyApplicationService(
            self.core_runner,
            self.research_study_domain,
        )
        self.action_registry = ActionRegistry(
            self.audit_log,
            actor_id=self.config.actor_id,
        )
        self._status = "created"
        self._lock = RLock()
        self.runtime_manager = RuntimeManagerBackend(
            app_status_provider=lambda: self.status,
            actor_id=self.config.actor_id,
            task_manager=self.task_manager,
            process_manager=self.process_manager,
            connection_registry=self.connection_registry,
            window_registry=self.window_registry,
            action_registry=self.action_registry,
            audit_log=self.audit_log,
        )
        self._context = CoreContext(
            config=self.config,
            logger=self.logger,
            audit_log=self.audit_log,
            error_router=self.error_router,
            task_manager=self.task_manager,
            core_runner=self.core_runner,
            process_manager=self.process_manager,
            connection_registry=self.connection_registry,
            window_registry=self.window_registry,
            action_registry=self.action_registry,
            runtime_manager=self.runtime_manager,
            connection_service=self.connection_service,
            historical_download_service=self.historical_download_service,
            ohlcv_maintenance_service=self.ohlcv_maintenance_service,
            research_dataset_service=self.research_dataset_service,
            research_study_service=self.research_study_service,
        )

    @property
    def context(self) -> CoreContext:
        return self._context

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def startup(self) -> CoreContext:
        with self._lock:
            if self._status == "running":
                return self._context
            if self._status == "stopped":
                raise RuntimeError("A stopped LeonardoApp cannot be restarted")
            self._status = "starting"
        self.logger.info("Application startup requested")
        try:
            self.audit_log.emit(
                AuditEventV1(
                    event_type="application.starting",
                    category="lifecycle",
                    message="Leonardo Light V2 is starting",
                    actor_id=self.config.actor_id,
                )
            )
            with self._lock:
                self._status = "running"
            self.audit_log.emit(
                AuditEventV1(
                    event_type="application.started",
                    category="lifecycle",
                    message="Leonardo Light V2 started",
                    actor_id=self.config.actor_id,
                )
            )
            self.logger.info("Application startup completed")
            return self._context
        except Exception as exc:
            with self._lock:
                self._status = "failed"
            self.logger.exception("Application startup failed")
            self.error_router.route_exception(exc, message="Application startup failed")
            raise

    def start_core_runtime(self) -> CoreContext:
        if self.status != "running":
            raise RuntimeError("Application startup must complete before Core runtime start")
        self.logger.info("Core runtime startup requested")
        self.core_runner.start()
        self.logger.info("Core runtime startup completed")
        return self._context

    def stop_core_runtime(self, *, timeout: float = 5.0) -> None:
        self.logger.info("Core runtime shutdown requested")
        self.core_runner.shutdown(timeout=timeout)
        self.logger.info("Core runtime shutdown completed")

    def shutdown(
        self,
        *,
        timeout: float = 5.0,
        reason: str = "Application shutdown requested",
    ) -> None:
        if type(timeout) not in (int, float) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        with self._lock:
            if self._status == "stopped":
                return
            preserve_failed = self._status == "failed"
            if not preserve_failed:
                self._status = "stopping"
        self.logger.info("Application shutdown requested")
        try:
            self.core_runner.shutdown(timeout=float(timeout))
            self.process_manager.shutdown(timeout=float(timeout))
            self.connection_registry.shutdown_tracking()
            for window in self.window_registry.open_windows():
                self.window_registry.close_window(window.window_id)
            self.audit_log.emit(
                AuditEventV1(
                    event_type="application.stopped",
                    category="lifecycle",
                    message=reason,
                    actor_id=self.config.actor_id,
                )
            )
            if not preserve_failed:
                with self._lock:
                    self._status = "stopped"
            self.logger.info("Application shutdown completed")
        except Exception as exc:
            with self._lock:
                self._status = "failed"
            self.logger.exception("Application shutdown failed")
            self.error_router.route_exception(exc, message="Application shutdown failed")
            raise
        finally:
            self.audit_log.close()


def _build_audit_log(config: AuditConfig) -> AuditLog:
    if not config.enabled:
        return AuditLog(InMemoryAuditSink(max_events=config.memory_max_events))
    memory = InMemoryAuditSink(max_events=config.memory_max_events)
    if not config.jsonl_enabled:
        return AuditLog(memory)
    if config.jsonl_path is None:
        raise ValueError("audit.jsonl_path must be configured when JSONL audit is enabled")
    return AuditLog(CompositeAuditSink((JsonlAuditSink(config.jsonl_path), memory)))


def _build_operational_logger() -> logging.Logger:
    """Return the shared standard-library operational logger."""

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    logger = logging.getLogger("leonardo")
    logger.setLevel(logging.INFO)
    return logger
