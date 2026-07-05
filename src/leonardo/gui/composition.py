"""GUI composition root for Core-aware Leonardo windows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from leonardo.gui.action_observer import (
    GuiActionObserver,
    build_gui_action_observer,
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

        window = LeonardoMainWindow(
            main_profile,
            runtime_manager_window_factory=self._create_runtime_manager_window,
            settings_inspector_factory=(
                settings_inspector_factory if self._override_store is not None else None
            ),
            action_observer=self._action_observer,
            on_download_data_requested=_download_data_placeholder_message,
            on_ohlcv_maintenance_requested=_ohlcv_maintenance_placeholder_message,
        )
        main_window = window
        self._install_tracker(
            window,
            main_profile,
            fallback_window_type="main_window",
        )
        return window

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
        window: RuntimeManagerWindow | LeonardoMainWindow,
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


def _download_data_placeholder_message(action_id: str) -> str:
    if action_id != "main_window.download_data":
        raise ValueError("Download Data callback received unexpected action ID")
    return "Download Data placeholder selected."


def _ohlcv_maintenance_placeholder_message(action_id: str) -> str:
    if action_id != "main_window.ohlcv_maintenance":
        raise ValueError("OHLCV Maintenance callback received unexpected action ID")
    return "OHLCV Maintenance placeholder selected."
