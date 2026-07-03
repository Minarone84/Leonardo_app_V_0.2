"""GUI composition root for Core-aware Leonardo windows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from leonardo.gui.metadata import EffectiveGuiMetadataProfile
from leonardo.gui.window_tracking import GuiWindowTracker, identity_from_profile
from leonardo.gui.windows.main_window import (
    LeonardoMainWindow,
    load_main_window_profile,
)
from leonardo.gui.windows.runtime_manager_window import (
    RuntimeManagerWindow,
    load_runtime_manager_profile,
)


class RuntimeSnapshotBackend(Protocol):
    """Read-only runtime snapshot provider boundary."""

    def snapshot(self) -> object:
        """Return the current runtime snapshot."""


class GuiCoreContext(Protocol):
    """Core context boundary consumed by GUI composition."""

    runtime_manager: RuntimeSnapshotBackend
    window_registry: object


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
    ) -> None:
        snapshot = getattr(getattr(context, "runtime_manager", None), "snapshot", None)
        if not callable(snapshot):
            raise TypeError("context.runtime_manager must expose callable snapshot")
        self._context = context
        self._snapshot_provider = snapshot
        self._track_windows = track_windows
        self._window_registry = getattr(context, "window_registry", None)
        if self._track_windows and self._window_registry is None:
            raise TypeError("context.window_registry is required when tracking windows")
        self._trackers: dict[str, GuiWindowTracker] = {}

    @property
    def window_trackers(self) -> Mapping[str, GuiWindowTracker]:
        """Return installed GUI window trackers by Core window identifier."""

        return dict(self._trackers)

    def tracker_for(self, window_id: str) -> GuiWindowTracker | None:
        """Return the installed tracker for a Core window identifier."""

        return self._trackers.get(window_id)

    def create_main_window(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
    ) -> LeonardoMainWindow:
        """
        Create the metadata-driven Main Window for the existing Core context.

        Runtime Manager construction remains lazy. The snapshot provider is not
        called during Main Window creation.
        """

        main_profile = profile if profile is not None else load_main_window_profile()
        window = LeonardoMainWindow(
            main_profile,
            runtime_manager_window_factory=self._create_runtime_manager_window,
        )
        self._install_tracker(
            window,
            main_profile,
            fallback_window_type="main_window",
        )
        return window

    def _create_runtime_manager_window(self) -> RuntimeManagerWindow:
        profile = load_runtime_manager_profile()
        window = RuntimeManagerWindow(
            profile,
            snapshot_provider=self._snapshot_provider,
        )
        self._install_tracker(
            window,
            profile,
            fallback_window_type="runtime_manager",
        )
        return window

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


def create_main_window_for_context(context: GuiCoreContext) -> LeonardoMainWindow:
    """Create a Core-aware Main Window using the default GUI composition root."""

    return GuiCompositionRoot(context).create_main_window()
