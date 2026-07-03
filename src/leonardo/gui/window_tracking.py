"""GUI-side window lifecycle tracking adapter for Core window state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from leonardo.contracts.gui import WindowDefinition
from leonardo.gui.metadata import EffectiveGuiMetadataProfile


class WindowTrackingRegistry(Protocol):
    """Public window registry boundary required by the GUI tracker."""

    def get_window_definition(self, window_id: str) -> WindowDefinition | None:
        """Return a registered window definition, if present."""

    def register_window(self, definition: WindowDefinition) -> WindowDefinition:
        """Register a window definition."""

    def open_windows(self) -> tuple[object, ...]:
        """Return open window runtime states."""

    def open_window(
        self,
        window_id: str,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        """Record that a window identity opened."""

    def focus_window(self, window_id: str) -> object:
        """Record that a window identity received focus."""

    def request_window_close(self, window_id: str) -> object:
        """Record that a window close was requested."""

    def close_window(self, window_id: str) -> object:
        """Record that a window identity closed."""


@dataclass(frozen=True)
class GuiWindowIdentity:
    """
    Local GUI metadata identity used to report a window to Core.

    The identity stores stable strings only. Qt widgets remain owned by the GUI
    layer and are never included in registry metadata.
    """

    window_id: str
    metadata_id: str
    title: str
    window_type: str
    object_name: str
    is_singleton: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_non_empty(self.window_id, "window_id")
        _validate_non_empty(self.metadata_id, "metadata_id")
        _validate_non_empty(self.title, "title")
        _validate_non_empty(self.window_type, "window_type")
        _validate_non_empty(self.object_name, "object_name")

    def to_definition(self) -> WindowDefinition:
        """Return the Core window definition for this GUI identity."""

        return WindowDefinition(
            window_id=self.window_id,
            title=self.title,
            window_type=self.window_type,
            is_singleton=self.is_singleton,
            metadata=self.registry_metadata(),
        )

    def registry_metadata(self) -> dict[str, object]:
        """Return registry-safe metadata without Qt objects."""

        metadata = dict(self.metadata)
        metadata["metadata_id"] = self.metadata_id
        metadata["object_name"] = self.object_name
        return metadata


class GuiWindowTracker(QObject):
    """
    Observe one opt-in top-level Qt window identity and report it to Core.

    The tracker is a GUI-layer adapter. It may hold Qt event-filter state, but
    it reports only stable identifiers and metadata through the window registry
    public API.
    """

    def __init__(
        self,
        registry: WindowTrackingRegistry,
        identity: GuiWindowIdentity,
    ) -> None:
        super().__init__()
        self._registry = registry
        self._identity = identity
        self._tracked_widget_ids: set[int] = set()
        self._is_open = False
        self._close_requested = False

    @property
    def identity(self) -> GuiWindowIdentity:
        """Return the local GUI window identity."""

        return self._identity

    @property
    def window_id(self) -> str:
        """Return the Core window identifier tracked by this adapter."""

        return self._identity.window_id

    @property
    def is_open(self) -> bool:
        """Return whether this tracker has reported the window as open."""

        return self._is_open

    def track(self, window: QWidget) -> bool:
        """
        Install tracking on an explicitly provided top-level window.

        Embedded widgets are ignored and return ``False``. Installing tracking
        does not report Core state; lifecycle reports begin when explicit helper
        methods or observed Qt events run.
        """

        if not isinstance(window, QWidget):
            raise TypeError("window must be a QWidget")
        if not window.isWindow():
            return False
        if not window.objectName():
            window.setObjectName(self._identity.object_name)

        widget_id = id(window)
        if widget_id not in self._tracked_widget_ids:
            window.installEventFilter(self)
            self._tracked_widget_ids.add(widget_id)
        return True

    def ensure_registered(self) -> WindowDefinition:
        """Register the Core window definition if needed."""

        existing = self._registry.get_window_definition(self.window_id)
        if existing is not None:
            return existing
        return self._registry.register_window(self._identity.to_definition())

    def mark_opened(
        self,
        *,
        owner_action_id: str | None = None,
        current_operation_id: str | None = None,
    ) -> object | None:
        """Report an open lifecycle transition if not already open."""

        self.ensure_registered()
        if self._is_open or self._registry_reports_open_window():
            self._is_open = True
            self._close_requested = False
            return None

        state = self._registry.open_window(
            self.window_id,
            owner_action_id=owner_action_id,
            current_operation_id=current_operation_id,
            metadata=self._identity.registry_metadata(),
        )
        self._is_open = True
        self._close_requested = False
        return state

    def mark_focused(self) -> object | None:
        """Report a focus lifecycle transition for an open window."""

        if not self._is_open:
            self.mark_opened()
        return self._registry.focus_window(self.window_id)

    def mark_close_requested(self) -> object | None:
        """Report a close-request lifecycle transition once per open window."""

        if not self._is_open or self._close_requested:
            return None
        state = self._registry.request_window_close(self.window_id)
        self._close_requested = True
        return state

    def mark_closed(self) -> object | None:
        """Report a closed lifecycle transition for an open window."""

        if not self._is_open:
            return None
        state = self._registry.close_window(self.window_id)
        self._is_open = False
        self._close_requested = False
        return state

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Translate selected top-level Qt events into registry reports."""

        if isinstance(watched, QWidget) and id(watched) in self._tracked_widget_ids:
            event_type = event.type()
            if event_type == QEvent.Type.Show:
                self.mark_opened()
            elif event_type in {QEvent.Type.WindowActivate, QEvent.Type.FocusIn}:
                self.mark_focused()
            elif event_type == QEvent.Type.Close:
                self.mark_close_requested()
            elif event_type == QEvent.Type.Hide and self._close_requested:
                self.mark_closed()
        return super().eventFilter(watched, event)

    def _registry_reports_open_window(self) -> bool:
        for state in self._registry.open_windows():
            if getattr(state, "window_id", None) == self.window_id:
                return True
        return False


def identity_from_profile(
    profile: EffectiveGuiMetadataProfile,
    *,
    fallback_window_type: str = "window",
) -> GuiWindowIdentity:
    """Build a registry-safe GUI window identity from an effective profile."""

    values = profile.values
    identity = _mapping_at(values, "identity")
    metadata = _mapping_at(values, "metadata")
    metadata_id = profile.metadata_id
    window_id = _string_value(metadata, "window_id", metadata_id)
    object_name = _string_value(metadata, "object_name", metadata_id)
    title = _string_value(identity, "title", metadata_id)
    window_type = _string_value(metadata, "logical_kind", fallback_window_type)
    instance_policy = _string_value(metadata, "instance_policy", "singleton")
    registry_metadata = _registry_metadata(profile.metadata_id, metadata)

    return GuiWindowIdentity(
        window_id=window_id,
        metadata_id=metadata_id,
        title=title,
        window_type=window_type,
        object_name=object_name,
        is_singleton=instance_policy == "singleton",
        metadata=registry_metadata,
    )


def _registry_metadata(
    metadata_id: str,
    source: Mapping[str, object],
) -> dict[str, object]:
    metadata: dict[str, object] = {"metadata_id": metadata_id}
    for key in (
        "contract_id",
        "logical_kind",
        "owner_area",
        "instance_policy",
        "runtime_role",
    ):
        value = source.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata


def _mapping_at(values: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: Mapping[str, object], key: str, fallback: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback


def _validate_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
