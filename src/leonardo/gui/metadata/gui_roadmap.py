"""Read-only access to the canonical Leonardo V2 GUI roadmap metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType


GUI_ROADMAP_METADATA_PATH = Path(__file__).with_name("gui_roadmap.json")
GUI_ROADMAP_SCHEMA_PATH = Path(__file__).with_name("gui_roadmap.schema.json")


@dataclass(frozen=True)
class GuiRoadmap:
    """
    Immutable view of the GUI roadmap metadata.

    The roadmap is static source metadata. It is not a runtime registry, widget
    factory, Object Map provider, or action executor.
    """

    data: Mapping[str, object]

    @property
    def roadmap_id(self) -> str:
        """Return the stable roadmap identifier."""

        return _string_at(self.data, "roadmap_id")

    @property
    def schema_version(self) -> str:
        """Return the roadmap schema version."""

        return _string_at(self.data, "schema_version")

    @property
    def windows(self) -> tuple[Mapping[str, object], ...]:
        """Return roadmap window records."""

        return _sequence_of_mappings(self.data, "windows")

    @property
    def actions(self) -> tuple[Mapping[str, object], ...]:
        """Return roadmap action records."""

        return _sequence_of_mappings(self.data, "actions")

    @property
    def objects(self) -> tuple[Mapping[str, object], ...]:
        """Return roadmap GUI object records."""

        return _sequence_of_mappings(self.data, "objects")

    def window_by_id(self, window_id: str) -> Mapping[str, object]:
        """Return a window record by stable window identifier."""

        return _lookup(self.windows, "window_id", window_id, "window")

    def action_by_id(self, action_id: str) -> Mapping[str, object]:
        """Return an action record by stable action identifier."""

        return _lookup(self.actions, "action_id", action_id, "action")

    def object_by_id(self, object_id: str) -> Mapping[str, object]:
        """Return a GUI object record by stable object identifier."""

        return _lookup(self.objects, "object_id", object_id, "object")

    def suite_by_id(self, suite_id: str) -> Mapping[str, object]:
        """Return a suite record by stable suite identifier."""

        return _lookup(
            _sequence_of_mappings(self.data, "suites"),
            "suite_id",
            suite_id,
            "suite",
        )


def load_gui_roadmap(path: str | Path = GUI_ROADMAP_METADATA_PATH) -> GuiRoadmap:
    """
    Load and validate the bundled GUI roadmap metadata.

    The loader reads static JSON only. It does not construct GUI widgets,
    resolve Core services, mutate Object Map state, or call domain services.
    """

    source_path = Path(path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    errors = validate_gui_roadmap(data)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"Invalid GUI roadmap metadata: {joined}")
    return GuiRoadmap(_freeze(data))


def load_gui_roadmap_schema(
    path: str | Path = GUI_ROADMAP_SCHEMA_PATH,
) -> Mapping[str, object]:
    """Load the static GUI roadmap JSON schema as an immutable mapping."""

    source_path = Path(path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("GUI roadmap schema root must be a mapping")
    return _freeze(data)


def validate_gui_roadmap(data: object) -> tuple[str, ...]:
    """Return structural validation errors for GUI roadmap metadata."""

    if not isinstance(data, Mapping):
        return ("roadmap root must be a mapping",)

    errors: list[str] = []
    required_top_level = (
        "roadmap_id",
        "schema_version",
        "status",
        "nsrr_policy",
        "status_taxonomy",
        "ownership_policy",
        "id_conventions",
        "areas",
        "suites",
        "windows",
        "objects",
        "actions",
        "ai_agent_usage",
    )
    for key in required_top_level:
        if key not in data:
            errors.append(f"missing top-level field: {key}")

    for key in ("areas", "suites", "windows", "objects", "actions"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} must be a list")

    _collect_required_item_fields(
        data,
        "areas",
        ("area_id", "display_name", "gui_role", "domain_role", "owner_scope"),
        errors,
    )
    _collect_required_item_fields(
        data,
        "suites",
        (
            "suite_id",
            "display_name",
            "target_area_id",
            "gui_status",
            "domain_status",
            "owned_domain_modules",
            "planned_gui_surfaces",
        ),
        errors,
    )
    _collect_required_item_fields(
        data,
        "windows",
        (
            "window_id",
            "object_id",
            "display_name",
            "owner_area",
            "status",
            "lifecycle_owner",
            "parent_object_id",
            "child_object_ids",
            "action_ids",
            "ai_agent",
            "forbidden_behaviors",
        ),
        errors,
    )
    _collect_required_item_fields(
        data,
        "actions",
        (
            "action_id",
            "display_label",
            "kind",
            "owner_area",
            "status",
            "source_object_id",
            "window_id",
            "runtime_observed",
            "requires_human_confirmation",
            "ai_agent",
            "forbidden_behaviors",
        ),
        errors,
    )
    _collect_required_item_fields(
        data,
        "objects",
        (
            "object_id",
            "object_type",
            "window_id",
            "parent_object_id",
            "status",
            "owner_area",
            "target_area_id",
            "target_suite_id",
            "target_module_id",
            "ai_agent",
        ),
        errors,
    )
    _collect_duplicate_ids(data, "areas", "area_id", errors)
    _collect_duplicate_ids(data, "suites", "suite_id", errors)
    _collect_duplicate_ids(data, "windows", "window_id", errors)
    _collect_duplicate_ids(data, "objects", "object_id", errors)
    _collect_duplicate_ids(data, "actions", "action_id", errors)
    _collect_graph_reference_errors(data, errors)
    return tuple(errors)


def _collect_graph_reference_errors(
    data: Mapping[str, object],
    errors: list[str],
) -> None:
    windows = data.get("windows", ())
    actions = data.get("actions", ())
    objects = data.get("objects", ())
    if not isinstance(windows, list) or not isinstance(actions, list) or not isinstance(objects, list):
        return

    action_ids = {
        action.get("action_id")
        for action in actions
        if isinstance(action, Mapping) and isinstance(action.get("action_id"), str)
    }
    object_ids = {
        window.get("object_id")
        for window in windows
        if isinstance(window, Mapping) and isinstance(window.get("object_id"), str)
    }
    object_ids.update(
        item.get("object_id")
        for item in objects
        if isinstance(item, Mapping) and isinstance(item.get("object_id"), str)
    )

    for window in windows:
        if not isinstance(window, Mapping):
            continue
        window_id = window.get("window_id", "<unknown>")
        action_values = window.get("action_ids", ())
        if isinstance(action_values, list):
            for action_id in action_values:
                if action_id not in action_ids:
                    errors.append(f"window {window_id} references unknown action: {action_id}")
        child_values = window.get("child_object_ids", ())
        if isinstance(child_values, list):
            for object_id in child_values:
                if object_id not in object_ids:
                    errors.append(f"window {window_id} references unknown child object: {object_id}")

    for action in actions:
        if not isinstance(action, Mapping):
            continue
        source_object_id = action.get("source_object_id")
        if source_object_id not in object_ids:
            errors.append(f"action {action.get('action_id', '<unknown>')} references unknown source object: {source_object_id}")

    for item in objects:
        if not isinstance(item, Mapping):
            continue
        parent_object_id = item.get("parent_object_id")
        if parent_object_id is not None and parent_object_id not in object_ids:
            errors.append(f"object {item.get('object_id', '<unknown>')} references unknown parent object: {parent_object_id}")


def _collect_required_item_fields(
    data: Mapping[str, object],
    section: str,
    required_fields: tuple[str, ...],
    errors: list[str],
) -> None:
    values = data.get(section, ())
    if not isinstance(values, list):
        return
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            errors.append(f"{section}.{index} must be a mapping")
            continue
        for field_name in required_fields:
            if field_name not in item:
                errors.append(f"{section}.{index} missing field: {field_name}")


def _collect_duplicate_ids(
    data: Mapping[str, object],
    section: str,
    id_field: str,
    errors: list[str],
) -> None:
    values = data.get(section, ())
    if not isinstance(values, list):
        return
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        value = item.get(id_field)
        if not isinstance(value, str) or not value:
            errors.append(f"{section} entry has invalid {id_field}")
            continue
        if value in seen:
            errors.append(f"duplicate {section}.{id_field}: {value}")
        seen.add(value)


def _lookup(
    values: tuple[Mapping[str, object], ...],
    key: str,
    value: str,
    label: str,
) -> Mapping[str, object]:
    for item in values:
        if item.get(key) == value:
            return item
    raise KeyError(f"Unknown GUI roadmap {label}: {value}")


def _sequence_of_mappings(
    data: Mapping[str, object],
    key: str,
) -> tuple[Mapping[str, object], ...]:
    value = data.get(key, ())
    if not isinstance(value, tuple):
        raise TypeError(f"{key} must be an immutable sequence")
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{key} entries must be mappings")
    return value


def _string_at(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
