"""GUI composition root for Core-aware Leonardo windows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from leonardo.gui.action_observer import (
    GuiActionObserver,
    build_gui_action_observer,
)
from leonardo.gui.download_request_mapper import (
    DownloadPreflightPreviewView,
    DownloadSubmitResultView,
    build_download_request_for_submit,
    build_download_request_from_draft,
    build_preflight_preview_view,
    build_submit_error_view,
    build_submit_result_view,
)
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataOverrideStore,
    GuiMetadataOverrideStoreResult,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.settings_profiles import (
    GuiSettingsProfileProvider,
    MAIN_WINDOW_SETTINGS_PROFILE_ID,
)
from leonardo.gui.settings_inspector import GuiSettingsInspectorViewModel
from leonardo.gui.window_tracking import GuiWindowTracker, identity_from_profile
from leonardo.gui.windows.download_request_builder_window import (
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
    DownloadRequestBuilderOptions,
    DownloadRequestDraft,
    DownloadRequestBuilderWindow,
)
from leonardo.gui.windows.main_window import (
    LeonardoMainWindow,
    _MAIN_WINDOW_METADATA_PATH,
    load_main_window_profile,
)
from leonardo.gui.windows.runtime_manager_window import (
    RuntimeManagerWindow,
    _RUNTIME_MANAGER_METADATA_PATH,
    load_runtime_manager_profile,
)
from leonardo.gui.windows.settings_inspector_window import SettingsInspectorWindow


_DOWNLOAD_REQUEST_BUILDER_METADATA_PATH = (
    Path(__file__).resolve().parent
    / "metadata"
    / "windows"
    / "download_request_builder.window.toml"
)


class RuntimeSnapshotBackend(Protocol):
    """Read-only runtime snapshot provider boundary."""

    def snapshot(self) -> object:
        """Return the current runtime snapshot."""


class GuiCoreContext(Protocol):
    """Core context boundary consumed by GUI composition."""

    runtime_manager: RuntimeSnapshotBackend
    window_registry: object
    action_registry: object
    session_manager: object
    user_policy: object
    audit_log: object
    download_capability_catalog: object
    download_manager: object
    download_execution_manager: object


@dataclass(frozen=True)
class _ExecutionPlanSubmitState:
    plan_id: str | None
    created: bool
    message: str
    phase: str | None = None
    ready: bool = False
    blocked: bool = False


@dataclass(frozen=True)
class _SandboxExecutionSubmitState:
    status: str | None
    completed: bool
    message: str
    sandbox_root: str | None = None
    csv_paths: tuple[str, ...] = ()
    metadata_paths: tuple[str, ...] = ()
    bars_written: int = 0
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None
    timeframes_completed: tuple[str, ...] = ()


class GuiCompositionRoot:
    """
    Compose GUI-owned windows from an existing Core context.

    The composition root receives Core services but does not own application
    lifecycle, create the Qt application object, or construct Core services. It injects
    read-only runtime snapshot access into Runtime Manager windows and installs
    GUI-side window tracking when enabled.
    """

    def __init__(
        self,
        context: GuiCoreContext,
        *,
        track_windows: bool = True,
        override_store: GuiMetadataOverrideStore | None = None,
        settings_profile_provider: GuiSettingsProfileProvider | None = None,
        download_smoke_sandbox_root: str | Path | None = None,
    ) -> None:
        snapshot = getattr(getattr(context, "runtime_manager", None), "snapshot", None)
        if not callable(snapshot):
            raise TypeError("context.runtime_manager must expose callable snapshot")
        if override_store is not None and not isinstance(
            override_store,
            GuiMetadataOverrideStore,
        ):
            raise TypeError("override_store must be a GuiMetadataOverrideStore or None")
        if settings_profile_provider is not None and not isinstance(
            settings_profile_provider,
            GuiSettingsProfileProvider,
        ):
            raise TypeError(
                "settings_profile_provider must be a GuiSettingsProfileProvider or None"
            )
        self._context = context
        self._snapshot_provider = snapshot
        self._track_windows = track_windows
        self._override_store = override_store
        self._settings_profile_provider = (
            settings_profile_provider
            if settings_profile_provider is not None
            else GuiSettingsProfileProvider()
        )
        self._override_load_results: dict[str, GuiMetadataOverrideStoreResult] = {}
        self._window_registry = getattr(context, "window_registry", None)
        if self._track_windows and self._window_registry is None:
            raise TypeError("context.window_registry is required when tracking windows")
        self._trackers: dict[str, GuiWindowTracker] = {}
        self._action_observer: GuiActionObserver | None = build_gui_action_observer(
            context
        )
        self._download_request_builder_window: DownloadRequestBuilderWindow | None = None
        self._download_manager = getattr(context, "download_manager", None)
        self._download_execution_manager = getattr(
            context,
            "download_execution_manager",
            None,
        )
        self._download_capability_catalog = getattr(
            context,
            "download_capability_catalog",
            None,
        )
        self._download_smoke_sandbox_root = (
            Path(download_smoke_sandbox_root)
            if download_smoke_sandbox_root is not None
            else None
        )

    @property
    def window_trackers(self) -> Mapping[str, GuiWindowTracker]:
        """Return installed GUI window trackers by Core window identifier."""

        return dict(self._trackers)

    def tracker_for(self, window_id: str) -> GuiWindowTracker | None:
        """Return the installed tracker for a Core window identifier."""

        return self._trackers.get(window_id)

    @property
    def override_load_results(self) -> Mapping[str, GuiMetadataOverrideStoreResult]:
        """Return retained override load results by metadata identifier."""

        return dict(self._override_load_results)

    @property
    def download_request_builder_window(self) -> DownloadRequestBuilderWindow | None:
        """Return the retained Download Request Builder shell, if created."""

        return self._download_request_builder_window

    def create_main_window(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
    ) -> LeonardoMainWindow:
        """
        Create the metadata-driven Main Window for the existing Core context.

        Runtime Manager construction remains lazy. The snapshot provider is not
        called during Main Window creation.
        """

        main_profile = profile if profile is not None else self._load_main_window_profile()
        main_window: LeonardoMainWindow | None = None

        def settings_inspector_factory() -> SettingsInspectorWindow:
            if main_window is None:
                raise RuntimeError("Main Window is not available for settings apply")
            return self._create_settings_inspector_window(main_window)

        def download_data_requested(action_id: str) -> str:
            if action_id != "main_window.download_data":
                raise ValueError("Download Data callback received unexpected action ID")
            if main_window is None:
                raise RuntimeError("Main Window is not available for download builder")
            return self._open_download_request_builder(
                main_window,
                DOWNLOAD_DATA_WORKFLOW_MODE,
            )

        def ohlcv_maintenance_requested(action_id: str) -> str:
            if action_id != "main_window.ohlcv_maintenance":
                raise ValueError(
                    "OHLCV Maintenance callback received unexpected action ID"
                )
            if main_window is None:
                raise RuntimeError("Main Window is not available for download builder")
            return self._open_download_request_builder(
                main_window,
                OHLCV_MAINTENANCE_WORKFLOW_MODE,
            )

        window = LeonardoMainWindow(
            main_profile,
            runtime_manager_window_factory=self._create_runtime_manager_window,
            settings_inspector_factory=(
                settings_inspector_factory if self._override_store is not None else None
            ),
            action_observer=self._action_observer,
            on_download_data_requested=download_data_requested,
            on_ohlcv_maintenance_requested=ohlcv_maintenance_requested,
        )
        main_window = window
        self._install_tracker(
            window,
            main_profile,
            fallback_window_type="main_window",
        )
        return window

    def _open_download_request_builder(
        self,
        parent: LeonardoMainWindow,
        workflow_mode: str,
    ) -> str:
        if self._download_request_builder_window is None:
            self._download_request_builder_window = DownloadRequestBuilderWindow(
                workflow_mode,
                parent=parent,
                on_preview_requested=(
                    self._preview_download_request
                    if self._download_preview_available()
                    else None
                ),
                on_submit_intent=(
                    self._submit_download_request
                    if self._download_submit_available()
                    else None
                ),
                action_observer=self._action_observer,
                options=self._download_request_builder_options(),
            )
            if self._track_windows:
                self._install_tracker(
                    self._download_request_builder_window,
                    self._load_download_request_builder_profile(),
                    fallback_window_type="download_request_builder",
                )
        else:
            self._download_request_builder_window.set_workflow_mode(workflow_mode)

        self._download_request_builder_window.show()
        self._download_request_builder_window.raise_()
        self._download_request_builder_window.activateWindow()
        return f"{self._download_request_builder_window.workflow_label} request builder opened."

    def _download_preview_available(self) -> bool:
        preview = getattr(self._download_manager, "preview_request", None)
        return callable(preview)

    def _download_submit_available(self) -> bool:
        submit = getattr(self._download_manager, "submit_request", None)
        return callable(submit)

    def _download_request_builder_options(self) -> DownloadRequestBuilderOptions:
        catalog = self._download_capability_catalog
        list_providers = getattr(catalog, "list_providers", None)
        list_markets = getattr(catalog, "list_markets", None)
        supported_timeframes = getattr(catalog, "supported_timeframes", None)
        if not (
            callable(list_providers)
            and callable(list_markets)
            and callable(supported_timeframes)
        ):
            return DownloadRequestBuilderOptions()

        providers = tuple(list_providers())
        if not providers:
            return DownloadRequestBuilderOptions()

        provider = providers[0]
        provider_id = str(getattr(provider, "provider", "")).strip()
        display_name = str(getattr(provider, "display_name", "")).strip()
        exchange = display_name if display_name else provider_id

        markets = tuple(
            str(getattr(market, "market", "")).strip()
            for market in list_markets(provider_id)
            if _is_download_data_market(market)
        )
        default_market = markets[0] if markets else ""
        timeframes = (
            tuple(supported_timeframes(provider_id, default_market))
            if default_market
            else ()
        )

        rate_limit_policy = getattr(provider, "rate_limit_policy", None)
        default_limit = getattr(rate_limit_policy, "page_limit_default", None)
        max_limit = getattr(rate_limit_policy, "page_limit_max", None)
        return DownloadRequestBuilderOptions(
            exchanges=(exchange,) if exchange else (),
            markets=markets,
            timeframes=timeframes,
            default_limit=default_limit if isinstance(default_limit, int) else 200,
            max_limit=max_limit if isinstance(max_limit, int) else 1000,
        )

    def _preview_download_request(
        self,
        draft: DownloadRequestDraft,
    ) -> DownloadPreflightPreviewView:
        preview = getattr(self._download_manager, "preview_request", None)
        if not callable(preview):
            raise RuntimeError("Download Manager preview is unavailable")
        request = build_download_request_from_draft(draft)
        preflight = preview(request)
        return build_preflight_preview_view(preflight)

    def _submit_download_request(
        self,
        draft: DownloadRequestDraft,
    ) -> DownloadSubmitResultView:
        if draft.workflow_mode != DOWNLOAD_DATA_WORKFLOW_MODE:
            return build_submit_error_view(
                "",
                (
                    "OHLCV Maintenance submit is deferred until storage execution "
                    "and maintenance policy are implemented."
                ),
                (),
            )

        try:
            request = build_download_request_for_submit(draft)
        except Exception as error:
            return build_submit_error_view(
                "",
                "Download request submit rejected.",
                (f"{type(error).__name__}: {error}",),
            )

        submit = getattr(self._download_manager, "submit_request", None)
        if not callable(submit):
            return build_submit_error_view(
                request.request_id,
                "Download Manager submit is unavailable.",
                (),
            )

        try:
            preflight = submit(request)
            item_count = _submitted_item_count(
                self._download_manager,
                request.request_id,
            )
        except Exception as error:
            return build_submit_error_view(
                request.request_id,
                "Download request submit rejected.",
                (f"{type(error).__name__}: {error}",),
            )
        execution_plan = _create_execution_plan(
            self._download_execution_manager,
            request.request_id,
        )
        sandbox_execution = _run_sandbox_smoke_execution(
            self._download_execution_manager,
            request.request_id,
            self._download_smoke_sandbox_root,
            execution_plan,
        )
        return build_submit_result_view(
            request,
            preflight,
            item_count=item_count,
            execution_plan_id=execution_plan.plan_id,
            execution_plan_created=execution_plan.created,
            execution_plan_message=execution_plan.message,
            execution_plan_phase=execution_plan.phase,
            execution_plan_ready=execution_plan.ready,
            execution_plan_blocked=execution_plan.blocked,
            sandbox_execution_status=sandbox_execution.status,
            sandbox_execution_completed=sandbox_execution.completed,
            sandbox_execution_message=sandbox_execution.message,
            sandbox_root=sandbox_execution.sandbox_root,
            sandbox_csv_paths=sandbox_execution.csv_paths,
            sandbox_metadata_paths=sandbox_execution.metadata_paths,
            sandbox_bars_written=sandbox_execution.bars_written,
            sandbox_first_timestamp_ms=sandbox_execution.first_timestamp_ms,
            sandbox_last_timestamp_ms=sandbox_execution.last_timestamp_ms,
            sandbox_timeframes_completed=sandbox_execution.timeframes_completed,
        )

    def _create_runtime_manager_window(self) -> RuntimeManagerWindow:
        profile = self._load_runtime_manager_profile()
        window = RuntimeManagerWindow(
            profile,
            snapshot_provider=self._snapshot_provider,
            action_observer=self._action_observer,
        )
        self._install_tracker(
            window,
            profile,
            fallback_window_type="runtime_manager",
        )
        return window

    def _create_settings_inspector_window(
        self,
        target_window: LeonardoMainWindow,
    ) -> SettingsInspectorWindow:
        if self._override_store is None:
            raise RuntimeError("override_store is required for settings inspector wiring")
        profile_ref = self._settings_profile_provider.get_profile(
            MAIN_WINDOW_SETTINGS_PROFILE_ID,
        )
        result = load_metadata_document(profile_ref.metadata_path)
        if result.document is None or result.report.has_errors:
            messages = "; ".join(issue.message for issue in result.report.issues)
            raise ValueError(f"Invalid GUI metadata profile: {messages}")
        viewmodel = GuiSettingsInspectorViewModel(result.document, self._override_store)
        return SettingsInspectorWindow(
            viewmodel,
            on_apply=lambda metadata_id, effective_profile: (
                _apply_main_window_settings(
                    target_window,
                    metadata_id,
                    effective_profile,
                )
            ),
            action_observer=self._action_observer,
        )

    def _install_tracker(
        self,
        window: (
            RuntimeManagerWindow
            | LeonardoMainWindow
            | DownloadRequestBuilderWindow
        ),
        profile: EffectiveGuiMetadataProfile,
        *,
        fallback_window_type: str,
    ) -> GuiWindowTracker | None:
        if not self._track_windows:
            return None
        identity = identity_from_profile(
            profile,
            fallback_window_type=fallback_window_type,
        )
        tracker = GuiWindowTracker(self._window_registry, identity)
        tracker.track(window)
        self._trackers[identity.window_id] = tracker
        return tracker

    def _load_main_window_profile(self) -> EffectiveGuiMetadataProfile:
        if self._override_store is None:
            return load_main_window_profile()
        return self._load_profile_with_overrides(_MAIN_WINDOW_METADATA_PATH)

    def _load_runtime_manager_profile(self) -> EffectiveGuiMetadataProfile:
        if self._override_store is None:
            return load_runtime_manager_profile()
        return self._load_profile_with_overrides(_RUNTIME_MANAGER_METADATA_PATH)

    def _load_download_request_builder_profile(self) -> EffectiveGuiMetadataProfile:
        if self._override_store is None:
            result = load_metadata_document(_DOWNLOAD_REQUEST_BUILDER_METADATA_PATH)
            if result.document is None or result.report.has_errors:
                messages = "; ".join(issue.message for issue in result.report.issues)
                raise ValueError(f"Invalid GUI metadata profile: {messages}")
            return GuiMetadataResolver().resolve(result.document)
        return self._load_profile_with_overrides(_DOWNLOAD_REQUEST_BUILDER_METADATA_PATH)

    def _load_profile_with_overrides(
        self,
        metadata_path: Path,
    ) -> EffectiveGuiMetadataProfile:
        result = load_metadata_document(metadata_path)
        if result.document is None or result.report.has_errors:
            messages = "; ".join(issue.message for issue in result.report.issues)
            raise ValueError(f"Invalid GUI metadata profile: {messages}")

        override_result = self._override_store.load(result.document.metadata_id)
        self._override_load_results[result.document.metadata_id] = override_result
        return GuiMetadataResolver().resolve(result.document, override_result.document)


def _submitted_item_count(download_manager: object, request_id: str) -> int:
    list_items = getattr(download_manager, "list_items", None)
    if not callable(list_items):
        return 0
    return len(tuple(list_items(request_id)))


def _is_download_data_market(market: object) -> bool:
    status = getattr(market, "status", None)
    status_value = getattr(status, "value", status)
    timeframes = getattr(market, "timeframes", ())
    data_kinds = tuple(
        str(getattr(kind, "value", kind))
        for kind in getattr(market, "data_kinds", ())
    )
    return (
        status_value == "supported"
        and bool(tuple(timeframes))
        and "ohlcv" in data_kinds
        and bool(str(getattr(market, "market", "")).strip())
    )


def _create_execution_plan(
    download_execution_manager: object,
    request_id: str,
) -> _ExecutionPlanSubmitState:
    create_plan = getattr(download_execution_manager, "create_plan", None)
    if not callable(create_plan):
        return _ExecutionPlanSubmitState(
            None,
            False,
            "Download Execution Manager is unavailable.",
        )

    try:
        snapshot = create_plan(request_id)
    except Exception as error:
        return _ExecutionPlanSubmitState(
            None,
            False,
            "Download execution plan creation failed: "
            f"{type(error).__name__}: {error}",
        )

    plan = getattr(snapshot, "plan", None)
    plan_id = getattr(plan, "plan_id", None)
    if isinstance(plan_id, str) and plan_id:
        return _classify_execution_plan(download_execution_manager, snapshot, plan_id)
    return _ExecutionPlanSubmitState(
        None,
        False,
        "Download execution plan was created without a plan ID.",
    )


def _classify_execution_plan(
    download_execution_manager: object,
    snapshot: object,
    plan_id: str,
) -> _ExecutionPlanSubmitState:
    classify_readiness = getattr(download_execution_manager, "classify_readiness", None)
    if not callable(classify_readiness):
        return _ExecutionPlanSubmitState(
            plan_id,
            True,
            "Download execution plan created. Readiness classification is unavailable.",
            _snapshot_plan_phase(snapshot),
        )

    try:
        classified_snapshot = classify_readiness(plan_id)
    except Exception as error:
        return _ExecutionPlanSubmitState(
            plan_id,
            True,
            "Download execution readiness classification failed: "
            f"{type(error).__name__}: {error}",
            _snapshot_plan_phase(snapshot),
        )

    phase = _snapshot_plan_phase(classified_snapshot)
    if phase == "ready":
        message = "Download execution plan classified as ready."
    elif phase == "blocked":
        detail = _snapshot_progress_message(classified_snapshot)
        message = (
            f"Download execution plan classified as blocked: {detail}"
            if detail
            else "Download execution plan classified as blocked."
        )
    else:
        message = (
            f"Download execution plan classified as {phase}."
            if phase is not None
            else "Download execution plan classification completed."
        )

    return _ExecutionPlanSubmitState(
        plan_id,
        True,
        message,
        phase,
        ready=phase == "ready",
        blocked=phase == "blocked",
    )


def _run_sandbox_smoke_execution(
    download_execution_manager: object,
    request_id: str,
    sandbox_root: Path | None,
    execution_plan: _ExecutionPlanSubmitState,
) -> _SandboxExecutionSubmitState:
    if sandbox_root is None:
        return _SandboxExecutionSubmitState(
            None,
            False,
            "Sandbox execution root is not configured.",
        )
    if not execution_plan.ready:
        return _SandboxExecutionSubmitState(
            "blocked",
            False,
            "Sandbox execution was not run because the execution plan is not ready.",
            str(sandbox_root.resolve(strict=False)),
        )

    run_sandbox_smoke = getattr(download_execution_manager, "run_sandbox_smoke", None)
    if not callable(run_sandbox_smoke):
        return _SandboxExecutionSubmitState(
            "unavailable",
            False,
            "Sandbox smoke execution is unavailable.",
            str(sandbox_root.resolve(strict=False)),
        )

    try:
        result = run_sandbox_smoke(
            request_id,
            sandbox_root=sandbox_root,
        )
    except Exception as error:
        return _SandboxExecutionSubmitState(
            "failed",
            False,
            f"Sandbox smoke execution failed: {type(error).__name__}: {error}",
            str(sandbox_root.resolve(strict=False)),
        )

    storage_results = tuple(getattr(result, "storage_results", ()))
    csv_paths = tuple(
        str(sandbox_root / path)
        for path in (
            getattr(storage_result, "csv_path", "")
            for storage_result in storage_results
        )
        if path
    )
    metadata_paths = tuple(
        str(sandbox_root / path)
        for path in (
            getattr(storage_result, "metadata_path", "")
            for storage_result in storage_results
        )
        if path
    )
    first_timestamps = tuple(
        timestamp
        for timestamp in (
            getattr(storage_result, "first_timestamp_ms", None)
            for storage_result in storage_results
        )
        if isinstance(timestamp, int)
    )
    last_timestamps = tuple(
        timestamp
        for timestamp in (
            getattr(storage_result, "last_timestamp_ms", None)
            for storage_result in storage_results
        )
        if isinstance(timestamp, int)
    )
    timeframes_completed = tuple(
        timeframe
        for timeframe in (
            getattr(getattr(storage_result, "target", None), "timeframe", None)
            for storage_result in storage_results
        )
        if isinstance(timeframe, str) and timeframe
    )
    status = getattr(getattr(result, "status", None), "value", None)
    if not isinstance(status, str):
        status = str(getattr(result, "status", "completed"))
    return _SandboxExecutionSubmitState(
        status,
        status == "completed",
        "Sandbox smoke execution completed.",
        str(sandbox_root.resolve(strict=False)),
        csv_paths,
        metadata_paths,
        sum(
            getattr(storage_result, "bars_written", 0)
            for storage_result in storage_results
        ),
        min(first_timestamps) if first_timestamps else None,
        max(last_timestamps) if last_timestamps else None,
        timeframes_completed,
    )


def _snapshot_plan_phase(snapshot: object) -> str | None:
    plan = getattr(snapshot, "plan", None)
    phase = getattr(plan, "phase", None)
    value = getattr(phase, "value", phase)
    if isinstance(value, str) and value:
        return value
    return None


def _snapshot_progress_message(snapshot: object) -> str:
    progress = getattr(snapshot, "progress", None)
    message = getattr(progress, "message", "")
    return message if isinstance(message, str) else ""


def create_main_window_for_context(context: GuiCoreContext) -> LeonardoMainWindow:
    """Create a Core-aware Main Window using the default GUI composition root."""

    return GuiCompositionRoot(context).create_main_window()


def _apply_main_window_settings(
    target_window: LeonardoMainWindow,
    metadata_id: str,
    effective_profile: EffectiveGuiMetadataProfile,
) -> None:
    if metadata_id != MAIN_WINDOW_SETTINGS_PROFILE_ID:
        raise ValueError("Settings apply callback only supports main_window.window")
    target_window.apply_effective_profile(effective_profile)
