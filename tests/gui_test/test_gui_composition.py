import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from leonardo.contracts.downloads import (  # noqa: E402
    DownloadPreflight,
    DownloadRequest,
    DownloadStatus,
    DownloadTimeframeMode,
)
from leonardo.contracts.gui import WindowDefinition  # noqa: E402
from leonardo.core.app import LeonardoApp  # noqa: E402
from leonardo.gui.composition import (  # noqa: E402
    GuiCompositionRoot,
    create_main_window_for_context,
)
from leonardo.gui.windows.download_request_builder_window import (  # noqa: E402
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    DownloadRequestBuilderWindow,
)
from leonardo.gui.windows.main_window import LeonardoMainWindow  # noqa: E402
from leonardo.gui.windows.runtime_manager_window import RuntimeManagerWindow  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSITION_SOURCE = _REPO_ROOT / "src" / "leonardo" / "gui" / "composition.py"


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "health": "ok",
            "sections": (
                {
                    "section_id": "services",
                    "status": "ok",
                    "count": 1,
                    "message": "1 service visible",
                    "metadata": {"service_ids": ("runtime-service",)},
                },
                {
                    "section_id": "downloads",
                    "status": "ok",
                    "count": 0,
                    "message": "0 download requests, 0 items",
                    "metadata": {
                        "total_requests": 0,
                        "total_items": 0,
                    },
                },
            ),
            "recent_audit_events": (),
        }


class FakeWindowRegistry:
    def __init__(self) -> None:
        self.definitions: dict[str, WindowDefinition] = {}
        self.open_ids: set[str] = set()
        self.calls: list[str] = []
        self.widgets_seen = 0

    def get_window_definition(self, window_id: str) -> WindowDefinition | None:
        self._reject_widget(window_id)
        self.calls.append("get_window_definition")
        return self.definitions.get(window_id)

    def register_window(self, definition: WindowDefinition) -> WindowDefinition:
        self._reject_widget(definition)
        self.calls.append("register_window")
        self.definitions[definition.window_id] = definition
        return definition

    def open_windows(self) -> tuple[object, ...]:
        self.calls.append("open_windows")
        return tuple(SimpleNamespace(window_id=window_id) for window_id in self.open_ids)

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        self._reject_widget(window_id, owner_action_id, current_operation_id, metadata)
        self.calls.append("open_window")
        self.open_ids.add(window_id)
        return SimpleNamespace(window_id=window_id)

    def focus_window(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("focus_window")
        return SimpleNamespace(window_id=window_id)

    def request_window_close(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("request_window_close")
        return SimpleNamespace(window_id=window_id)

    def close_window(self, window_id: str) -> object:
        self._reject_widget(window_id)
        self.calls.append("close_window")
        self.open_ids.discard(window_id)
        return SimpleNamespace(window_id=window_id)

    def _reject_widget(self, *values: object) -> None:
        for value in values:
            if isinstance(value, QWidget):
                self.widgets_seen += 1
                raise AssertionError("registry received QWidget")
            if isinstance(value, dict):
                self._reject_widget(*value.values())


class FakeDownloadManager:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.submit_calls = 0
        self.last_preview_request: DownloadRequest | None = None
        self.last_submit_request: DownloadRequest | None = None
        self._submitted_requests: dict[str, DownloadRequest] = {}

    def preview_request(self, request: DownloadRequest) -> DownloadPreflight:
        self.preview_calls += 1
        self.last_preview_request = request
        return DownloadPreflight(
            request_id=request.request_id,
            status=DownloadStatus.VALIDATED,
            can_run=True,
            estimated_symbols=len(request.symbols),
            estimated_timeframes=len(request.timeframes)
            if request.timeframes
            else None,
            estimated_items=(
                len(request.symbols) * len(request.timeframes)
                if request.timeframes
                else None
            ),
            required_connections=(
                (request.connection_ref,) if request.connection_ref is not None else ()
            ),
            websocket_required=request.websocket_required,
        )

    def submit_request(self, request: DownloadRequest) -> DownloadPreflight:
        self.submit_calls += 1
        if request.request_id in self._submitted_requests:
            raise ValueError(f"Download request already submitted: {request.request_id}")
        self.last_submit_request = request
        self._submitted_requests[request.request_id] = request
        return DownloadPreflight(
            request_id=request.request_id,
            status=DownloadStatus.VALIDATED,
            can_run=True,
            estimated_symbols=len(request.symbols),
            estimated_timeframes=len(request.timeframes)
            if request.timeframes
            else None,
            estimated_items=(
                len(request.symbols) * len(request.timeframes)
                if request.timeframes
                else None
            ),
            required_connections=(
                (request.connection_ref,) if request.connection_ref is not None else ()
            ),
            websocket_required=request.websocket_required,
        )

    def list_items(self, request_id: str) -> tuple[object, ...]:
        request = self._submitted_requests.get(request_id)
        if request is None or request.timeframe_mode is not DownloadTimeframeMode.EXPLICIT:
            return ()
        return tuple(
            SimpleNamespace(item_id=f"{request_id}:{symbol}:{timeframe}")
            for symbol in request.symbols
            for timeframe in request.timeframes
        )


class FakeDownloadExecutionManager:
    def __init__(
        self,
        *,
        fail: bool = False,
        classify_fail: bool = False,
        classified_phase: str = "ready",
        classified_message: str = "Download execution plan is ready.",
    ) -> None:
        self.fail = fail
        self.classify_fail = classify_fail
        self.classified_phase = classified_phase
        self.classified_message = classified_message
        self.create_plan_calls = 0
        self.classify_readiness_calls = 0
        self.request_ids: list[str] = []
        self.plan_ids: list[str] = []
        self._snapshots: dict[str, SimpleNamespace] = {}

    def create_plan(self, request_id: str) -> SimpleNamespace:
        self.create_plan_calls += 1
        self.request_ids.append(request_id)
        if self.fail:
            raise RuntimeError("plan failed")
        plan_id = f"execution-plan-{request_id}"
        snapshot = self._snapshots.get(plan_id)
        if snapshot is None:
            snapshot = SimpleNamespace(
                plan=SimpleNamespace(
                    plan_id=plan_id,
                    request_id=request_id,
                    phase="planned",
                )
            )
            self._snapshots[plan_id] = snapshot
        return snapshot

    def classify_readiness(self, plan_id: str) -> SimpleNamespace:
        self.classify_readiness_calls += 1
        self.plan_ids.append(plan_id)
        if self.classify_fail:
            raise RuntimeError("classification failed")
        snapshot = self._snapshots[plan_id]
        classified = SimpleNamespace(
            plan=SimpleNamespace(
                plan_id=snapshot.plan.plan_id,
                request_id=snapshot.plan.request_id,
                phase=self.classified_phase,
            ),
            progress=SimpleNamespace(message=self.classified_message),
        )
        self._snapshots[plan_id] = classified
        return classified

    def list_snapshots(self) -> tuple[SimpleNamespace, ...]:
        return tuple(self._snapshots[plan_id] for plan_id in sorted(self._snapshots))


class FakeDownloadCapabilityCatalog:
    def list_providers(self) -> tuple[SimpleNamespace, ...]:
        return (
            SimpleNamespace(
                provider="bybit",
                display_name="Bybit",
                rate_limit_policy=SimpleNamespace(
                    page_limit_default=200,
                    page_limit_max=1000,
                ),
            ),
        )

    def list_markets(self, provider: str) -> tuple[SimpleNamespace, ...]:
        assert provider == "bybit"
        return (
            _market("spot"),
            _market("linear"),
            _market("inverse"),
            _market("options", status="unsupported", timeframes=()),
        )

    def supported_timeframes(self, provider: str, market: str) -> tuple[str, ...]:
        assert provider == "bybit"
        assert market in {"spot", "linear", "inverse"}
        return (
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "12h",
            "1d",
            "1w",
        )


class FakeCoreContext:
    def __init__(
        self,
        *,
        download_execution_manager: FakeDownloadExecutionManager | None = None,
    ) -> None:
        self.runtime_manager = FakeRuntimeManager()
        self.window_registry = FakeWindowRegistry()
        self.download_capability_catalog = FakeDownloadCapabilityCatalog()
        self.download_manager = FakeDownloadManager()
        self.download_execution_manager = (
            download_execution_manager
            if download_execution_manager is not None
            else FakeDownloadExecutionManager()
        )


def test_composition_creates_main_window_from_context_without_startup(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    app_instance = QApplication.instance()
    root = GuiCompositionRoot(context)

    window = root.create_main_window()

    assert isinstance(window, LeonardoMainWindow)
    assert QApplication.instance() is app_instance
    assert context.runtime_manager.calls == 0
    assert context.window_registry.calls == []
    assert root.tracker_for("main_window.window") is not None

    window.deleteLater()
    qapplication.processEvents()


def test_function_helper_uses_gui_composition_root(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()

    window = create_main_window_for_context(context)

    assert isinstance(window, LeonardoMainWindow)
    assert context.runtime_manager.calls == 0

    window.deleteLater()
    qapplication.processEvents()


def test_runtime_manager_factory_is_injected_and_uses_snapshot_provider_lazily(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert isinstance(runtime_window, RuntimeManagerWindow)
    assert context.runtime_manager.calls == 0
    assert root.tracker_for("runtime_manager.window") is not None

    runtime_window.action_button_for_id("runtime_manager.refresh_snapshot").click()
    qapplication.processEvents()

    assert context.runtime_manager.calls == 1
    assert runtime_window.last_rendered_snapshot_summary["status"] == "rendered"

    runtime_window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()


def test_composition_injects_inert_download_placeholder_callbacks(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window

    assert isinstance(builder, DownloadRequestBuilderWindow)
    assert builder.workflow_mode == DOWNLOAD_DATA_WORKFLOW_MODE
    assert builder.isVisible() is True
    assert root.tracker_for("download_request_builder.window") is not None
    assert "download_request_builder.window" in context.window_registry.definitions
    assert "download_request_builder.window" in context.window_registry.open_ids
    assert window.statusBar().currentMessage() == "Download Data request builder opened."
    assert context.download_manager.submit_calls == 0
    assert context.download_execution_manager.create_plan_calls == 0
    assert context.download_execution_manager.classify_readiness_calls == 0

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()

    assert root.download_request_builder_window is builder
    assert builder.workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE
    assert "download_request_builder.window" in context.window_registry.open_ids
    assert window.statusBar().currentMessage() == (
        "OHLCV Maintenance request builder opened."
    )
    assert context.download_manager.submit_calls == 0
    assert context.download_execution_manager.create_plan_calls == 0
    assert context.download_execution_manager.classify_readiness_calls == 0

    builder.close()
    qapplication.processEvents()
    assert "download_request_builder.window" not in context.window_registry.open_ids

    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_wires_download_preview_without_submit_or_runtime_mutation(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()
    before_snapshot = context.runtime_manager.snapshot()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m", "5m")
    builder._show_preflight_preview()
    after_snapshot = context.runtime_manager.snapshot()
    status_text = _builder_status_text(builder)

    assert context.download_manager.preview_calls == 1
    assert context.download_manager.submit_calls == 0
    assert context.download_execution_manager.create_plan_calls == 0
    assert context.download_execution_manager.classify_readiness_calls == 0
    assert context.download_manager.last_preview_request is not None
    assert context.download_manager.last_preview_request.request_id.startswith(
        "preview-"
    )
    assert context.download_manager.last_preview_request.symbols == ("BTCUSDT",)
    assert context.download_manager.last_preview_request.timeframes == ("1m", "5m")
    assert "Preflight preview passed." in status_text
    assert before_snapshot == after_snapshot

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_wires_download_submit_without_preview_call(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m", "5m")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 1
    assert context.download_manager.preview_calls == 0
    assert context.download_execution_manager.create_plan_calls == 1
    assert context.download_execution_manager.classify_readiness_calls == 1
    assert context.download_manager.last_submit_request is not None
    assert context.download_execution_manager.request_ids == [
        context.download_manager.last_submit_request.request_id,
    ]
    assert context.download_execution_manager.plan_ids == [
        f"execution-plan-{context.download_manager.last_submit_request.request_id}",
    ]
    assert context.download_manager.last_submit_request.request_id.startswith(
        "request-"
    )
    assert not context.download_manager.last_submit_request.request_id.startswith(
        "preview-"
    )
    assert context.download_manager.last_submit_request.symbols == ("BTCUSDT",)
    assert context.download_manager.last_submit_request.timeframes == ("1m", "5m")
    assert "Download request submitted." in submit_text
    assert "Item count: 2" in submit_text
    assert "Runtime visible: True" in submit_text
    assert "Execution plan created: yes" in submit_text
    assert "Execution plan ID: execution-plan-request-" in submit_text
    assert "Execution plan message: Download execution plan classified as ready." in (
        submit_text
    )
    assert "Execution plan phase: ready" in submit_text
    assert "Execution plan ready: yes" in submit_text
    assert "Execution plan blocked: no" in submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_reports_blocked_readiness_for_explicit_download(
    qapplication: QApplication,
) -> None:
    execution_manager = FakeDownloadExecutionManager(
        classified_phase="blocked",
        classified_message="Timeframe expansion is unresolved.",
    )
    context = FakeCoreContext(download_execution_manager=execution_manager)
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 1
    assert execution_manager.create_plan_calls == 1
    assert execution_manager.classify_readiness_calls == 1
    assert context.download_manager.last_submit_request is not None
    assert context.download_manager.last_submit_request.timeframes == ("1m",)
    assert (
        len(
            context.download_manager.list_items(
                context.download_manager.last_submit_request.request_id,
            )
        )
        == 1
    )
    assert "Accepted: True" in submit_text
    assert "Item count: 1" in submit_text
    assert "Execution plan created: yes" in submit_text
    assert "Execution plan phase: blocked" in submit_text
    assert "Execution plan ready: no" in submit_text
    assert "Execution plan blocked: yes" in submit_text
    assert (
        "Execution plan message: Download execution plan classified as blocked: "
        "Timeframe expansion is unresolved."
    ) in submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_handles_duplicate_download_submit_safely(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m")

    _click_builder_button(builder, "download_request_builder.submit_button")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 2
    assert context.download_manager.preview_calls == 0
    assert context.download_execution_manager.create_plan_calls == 1
    assert context.download_execution_manager.classify_readiness_calls == 1
    assert "Download request submit rejected." in submit_text
    assert "Accepted: False" in submit_text
    assert "Runtime visible: False" in submit_text
    assert "Execution plan phase: unresolved" in submit_text
    assert "Execution plan ready: no" in submit_text
    assert "Execution plan blocked: no" in submit_text
    assert "already submitted" in submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_blocks_ohlcv_submit_without_core_call(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.ohlcv_maintenance").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 0
    assert context.download_manager.preview_calls == 0
    assert context.download_execution_manager.create_plan_calls == 0
    assert context.download_execution_manager.classify_readiness_calls == 0
    assert (
        "OHLCV Maintenance submit is deferred until storage execution and "
        "maintenance policy are implemented."
    ) == submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_download_submit_state_is_visible_through_runtime_snapshot(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    context = app.startup()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m", "5m")
    _click_builder_button(builder, "download_request_builder.submit_button")

    summary = app.download_manager.get_summary()
    snapshot = app.runtime_manager.snapshot()
    request = app.download_manager.list_requests()[0]
    plan_id = f"execution-plan-{request.request_id}"

    assert summary.total_requests == 1
    assert summary.total_items == 2
    assert snapshot.downloads_summary.count == 1
    assert snapshot.downloads_summary.metadata["total_requests"] == 1
    assert snapshot.downloads_summary.metadata["total_items"] == 2
    assert snapshot.download_execution_summary.count == 1
    assert snapshot.download_execution_summary.metadata["total_plans"] == 1
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == (
        plan_id,
    )
    assert snapshot.download_execution_summary.metadata["running_plan_ids"] == (
        plan_id,
    )
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["plan_rows"][0]["phase"] == (
        "ready"
    )
    assert any(
        event.event_type == "download.execution.plan.created"
        for event in app.audit_log.snapshot()
    )
    assert any(
        event.event_type == "download.execution.phase.changed"
        and event.payload["new_phase"] == "ready"
        for event in app.audit_log.snapshot()
    )

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()
    app.shutdown()


def test_download_submit_without_timeframe_is_locally_blocked_before_runtime_snapshot(
    qapplication: QApplication,
) -> None:
    app = LeonardoApp()
    context = app.startup()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    snapshot = app.runtime_manager.snapshot()
    assert app.download_manager.list_requests() == ()
    assert app.download_manager.list_items() == ()
    assert "Download start blocked by local validation issues:" in submit_text
    assert "ERROR timeframes: Explicit timeframe mode requires at least one timeframe." in (
        submit_text
    )
    assert snapshot.download_execution_summary.metadata["active_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["running_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["blocked_plan_ids"] == ()
    assert snapshot.download_execution_summary.metadata["plan_rows"] == ()

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()
    app.shutdown()


def test_download_submit_plan_failure_preserves_accepted_submit(
    qapplication: QApplication,
) -> None:
    execution_manager = FakeDownloadExecutionManager(fail=True)
    context = FakeCoreContext(download_execution_manager=execution_manager)
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 1
    assert execution_manager.create_plan_calls == 1
    assert execution_manager.classify_readiness_calls == 0
    assert context.download_manager.last_submit_request is not None
    assert "Accepted: True" in submit_text
    assert "Runtime visible: True" in submit_text
    assert "Execution plan created: no" in submit_text
    assert "Execution plan ID: unresolved" in submit_text
    assert "Execution plan phase: unresolved" in submit_text
    assert "Execution plan ready: no" in submit_text
    assert "Execution plan blocked: no" in submit_text
    assert (
        "Execution plan message: Download execution plan creation failed: "
        "RuntimeError: plan failed"
    ) in submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_download_submit_classification_failure_preserves_created_plan(
    qapplication: QApplication,
) -> None:
    execution_manager = FakeDownloadExecutionManager(classify_fail=True)
    context = FakeCoreContext(download_execution_manager=execution_manager)
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()
    builder = root.download_request_builder_window
    assert builder is not None
    _set_builder_text(builder, "symbol", "BTCUSDT")
    _check_builder_timeframes(builder, "1m")
    _click_builder_button(builder, "download_request_builder.submit_button")
    submit_text = _builder_status_text(builder)

    assert context.download_manager.submit_calls == 1
    assert execution_manager.create_plan_calls == 1
    assert execution_manager.classify_readiness_calls == 1
    assert context.download_manager.last_submit_request is not None
    assert "Accepted: True" in submit_text
    assert "Runtime visible: True" in submit_text
    assert "Execution plan created: yes" in submit_text
    assert "Execution plan ID: execution-plan-request-" in submit_text
    assert "Execution plan phase: planned" in submit_text
    assert "Execution plan ready: no" in submit_text
    assert "Execution plan blocked: no" in submit_text
    assert (
        "Execution plan message: Download execution readiness classification failed: "
        "RuntimeError: classification failed"
    ) in submit_text

    builder.close()
    builder.deleteLater()
    window.deleteLater()
    qapplication.processEvents()


def test_window_tracking_reports_lifecycle_only_after_window_events(
    qapplication: QApplication,
) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context)
    window = root.create_main_window()

    assert context.window_registry.calls == []

    window.show()
    qapplication.processEvents()
    window.close()
    qapplication.processEvents()

    assert "register_window" in context.window_registry.calls
    assert "open_window" in context.window_registry.calls
    assert "request_window_close" in context.window_registry.calls
    assert "close_window" in context.window_registry.calls
    assert context.window_registry.widgets_seen == 0

    window.deleteLater()
    qapplication.processEvents()


def test_composition_can_disable_window_tracking(qapplication: QApplication) -> None:
    context = FakeCoreContext()
    root = GuiCompositionRoot(context, track_windows=False)

    window = root.create_main_window()
    window.show()
    qapplication.processEvents()
    window.action_for_id("main_window.download_data").trigger()
    qapplication.processEvents()

    assert root.window_trackers == {}
    assert context.window_registry.calls == []
    assert root.download_request_builder_window is not None
    assert root.download_request_builder_window.isVisible() is True

    root.download_request_builder_window.close()
    root.download_request_builder_window.deleteLater()
    window.close()
    window.deleteLater()
    qapplication.processEvents()


def test_composition_source_does_not_construct_app_or_qapplication() -> None:
    source = _COMPOSITION_SOURCE.read_text(encoding="utf-8")

    assert "LeonardoApp" not in source
    assert "QApplication" not in source
    assert ".startup(" not in source
    assert ".shutdown(" not in source
    assert "DownloadRequest(" not in source
    assert "leonardo.contracts.downloads" not in source
    assert ".submit_request(" not in source


def test_composed_windows_destroy_cleanly(qapplication: QApplication) -> None:
    context = FakeCoreContext()
    window = GuiCompositionRoot(context).create_main_window()

    window.show()
    window.action_for_id("main_window.open_runtime_manager").trigger()
    qapplication.processEvents()
    runtime_window = window.runtime_manager_window

    assert runtime_window is not None
    window.close()
    window.deleteLater()
    runtime_window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()


def _set_builder_text(
    builder: DownloadRequestBuilderWindow,
    field_id: str,
    value: str,
) -> None:
    widget = builder.field_widget_for_id(field_id)
    assert isinstance(widget, QLineEdit)
    widget.setText(value)


def _check_builder_timeframes(
    builder: DownloadRequestBuilderWindow,
    *timeframes: str,
) -> None:
    for timeframe in timeframes:
        builder.timeframe_checkbox_for_value(timeframe).setChecked(True)


def _builder_status_text(builder: DownloadRequestBuilderWindow) -> str:
    widget = builder.findChild(QTextEdit, "download_request_builder.status_summary")
    assert widget is not None
    return widget.toPlainText()


def _click_builder_button(
    builder: DownloadRequestBuilderWindow,
    object_name: str,
) -> None:
    button = builder.findChild(QPushButton, object_name)
    assert button is not None
    button.click()


def _market(
    market: str,
    *,
    status: str = "supported",
    timeframes: tuple[str, ...] = ("1m",),
) -> SimpleNamespace:
    return SimpleNamespace(
        market=market,
        status=SimpleNamespace(value=status),
        data_kinds=("ohlcv",) if status == "supported" else (),
        timeframes=tuple(
            SimpleNamespace(canonical_timeframe=timeframe)
            for timeframe in timeframes
        ),
    )
