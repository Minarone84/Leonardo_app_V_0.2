"""Area and suite boundary descriptor contracts for Leonardo V2.

The contracts in this module describe future areas, suites, modules, commands,
and queries. They are static descriptor models only. They do not register
suites, discover modules, execute commands, query services, mutate runtime
state, or implement domain behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from leonardo.contracts.identity import Permission
from leonardo.contracts.traceable_object import TraceableObjectRef


class AreaKind(str, Enum):
    """Canonical category for an architectural area descriptor."""

    SUITE = "suite"
    INFRASTRUCTURE = "infrastructure"
    WORKFLOW = "workflow"
    MODULE = "module"
    CAPABILITY = "capability"


class SuiteLifecycleStatus(str, Enum):
    """Lifecycle state for area, suite, and module descriptors."""

    PLANNED = "planned"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class SuiteCommandKind(str, Enum):
    """Capability category for a suite command descriptor."""

    INTENT = "intent"
    MUTATION = "mutation"
    LONG_RUNNING = "long_running"
    READ_MODEL_REFRESH = "read_model_refresh"
    MAINTENANCE = "maintenance"


class SuiteQueryKind(str, Enum):
    """Read capability category for a suite query descriptor."""

    LOCAL_READ_MODEL = "local_read_model"
    ASYNC_QUERY = "async_query"
    CROSS_BOUNDARY = "cross_boundary"


class SuiteTaskBehavior(str, Enum):
    """Expected operation and task behavior for a command descriptor."""

    NONE = "none"
    OPERATION_ONLY = "operation_only"
    TASK_EXPECTED = "task_expected"
    TASK_OPTIONAL = "task_optional"


class SuiteAuditPolicy(str, Enum):
    """Audit policy declared by command and query descriptors."""

    NONE = "none"
    SUMMARY = "summary"
    REQUIRED = "required"
    DENIED_ONLY = "denied_only"


class SuiteRuntimePolicy(str, Enum):
    """Runtime routing policy declared by a command descriptor."""

    NONE = "none"
    LOCAL_READ_ONLY = "local_read_only"
    CORE_RUNTIME_REQUIRED = "core_runtime_required"


class SuiteCachePolicy(str, Enum):
    """Cache policy declared by a query descriptor."""

    NONE = "none"
    SNAPSHOT = "snapshot"
    SHORT_LIVED = "short_lived"
    STATIC = "static"


@dataclass(frozen=True)
class AreaDescriptor:
    """
    Static descriptor for a major Leonardo architectural area.

    Areas may describe user-facing suites, shared infrastructure, workflows,
    modules, or capability boundaries. The descriptor is metadata only and has
    no registration or runtime side effects.
    """

    area_id: str
    display_name: str
    description: str
    area_kind: AreaKind | str
    owner_domain: str
    owner_component: str
    lifecycle_status: SuiteLifecycleStatus | str = SuiteLifecycleStatus.PLANNED
    version: str = "1.0"
    suite_id: str | None = None
    module_ids: tuple[str, ...] = ()
    object_family_ids: tuple[str, ...] = ()
    command_ids: tuple[str, ...] = ()
    query_ids: tuple[str, ...] = ()
    required_permissions: tuple[Permission | str, ...] = ()
    audit_categories: tuple[str, ...] = ()
    object_map_provider_id: str | None = None
    runtime_summary_kind: str | None = None
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    metadata_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "area_id",
            "display_name",
            "description",
            "owner_domain",
            "owner_component",
            "version",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "area_kind",
            _coerce_enum(self.area_kind, AreaKind, "area_kind"),
        )
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                self.lifecycle_status,
                SuiteLifecycleStatus,
                "lifecycle_status",
            ),
        )
        _validate_optional_string(self.suite_id, "suite_id")
        for field_name in (
            "object_map_provider_id",
            "runtime_summary_kind",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        _normalize_descriptor_sequences(self)


@dataclass(frozen=True)
class SuiteDescriptor:
    """
    Static descriptor for a large user-facing Leonardo suite.

    Suites own future domain behavior and read models. The descriptor itself is
    read-only vocabulary and does not own runtime startup, task lifecycle,
    operations, audit storage, GUI widgets, or provider transport.
    """

    suite_id: str
    display_name: str
    description: str
    owner_domain: str
    owner_component: str
    lifecycle_status: SuiteLifecycleStatus | str = SuiteLifecycleStatus.PLANNED
    version: str = "1.0"
    area_ids: tuple[str, ...] = ()
    module_ids: tuple[str, ...] = ()
    supported_command_ids: tuple[str, ...] = ()
    supported_query_ids: tuple[str, ...] = ()
    object_family_ids: tuple[str, ...] = ()
    required_permissions: tuple[Permission | str, ...] = ()
    audit_categories: tuple[str, ...] = ()
    object_map_provider_id: str | None = None
    runtime_summary_kind: str | None = None
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    metadata_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "suite_id",
            "display_name",
            "description",
            "owner_domain",
            "owner_component",
            "version",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                self.lifecycle_status,
                SuiteLifecycleStatus,
                "lifecycle_status",
            ),
        )
        for field_name in (
            "object_map_provider_id",
            "runtime_summary_kind",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        _normalize_descriptor_sequences(self)


@dataclass(frozen=True)
class SuiteModuleDescriptor:
    """
    Static descriptor for a coherent suite or area module.

    Modules describe functional slices such as download-data or analysis-run
    surfaces. They do not own GUI widgets, runtime execution, provider
    registration, or domain service construction.
    """

    module_id: str
    display_name: str
    description: str
    owner_domain: str
    owner_component: str
    suite_id: str | None = None
    area_id: str | None = None
    lifecycle_status: SuiteLifecycleStatus | str = SuiteLifecycleStatus.PLANNED
    object_family_ids: tuple[str, ...] = ()
    command_ids: tuple[str, ...] = ()
    query_ids: tuple[str, ...] = ()
    required_permissions: tuple[Permission | str, ...] = ()
    audit_categories: tuple[str, ...] = ()
    object_map_section_id: str | None = None
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    metadata_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "module_id",
            "display_name",
            "description",
            "owner_domain",
            "owner_component",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_optional_string(self.suite_id, "suite_id")
        _validate_optional_string(self.area_id, "area_id")
        if self.suite_id is None and self.area_id is None:
            raise ValueError("suite_id or area_id must identify module ownership")
        object.__setattr__(
            self,
            "lifecycle_status",
            _coerce_enum(
                self.lifecycle_status,
                SuiteLifecycleStatus,
                "lifecycle_status",
            ),
        )
        _validate_optional_string(self.object_map_section_id, "object_map_section_id")
        _normalize_descriptor_sequences(self)


@dataclass(frozen=True)
class SuiteCommandDescriptor:
    """
    Static descriptor for a suite command capability.

    The descriptor describes what a future command means, which permission gates
    it requires, and how it relates to GUI actions and object families. It is
    not a command instance and has no execution behavior.
    """

    command_id: str
    command_kind: SuiteCommandKind | str
    label: str
    description: str
    required_permission: Permission | str
    suite_id: str | None = None
    area_id: str | None = None
    module_id: str | None = None
    creates_operation: bool = False
    expected_task_behavior: SuiteTaskBehavior | str = SuiteTaskBehavior.NONE
    cancellable: bool = False
    audit_category: str = "none"
    runtime_policy: SuiteRuntimePolicy | str = SuiteRuntimePolicy.NONE
    input_schema_ref: str | None = None
    result_schema_ref: str | None = None
    progress_schema_ref: str | None = None
    related_action_ids: tuple[str, ...] = ()
    object_family_ids: tuple[str, ...] = ()
    object_refs: tuple[TraceableObjectRef | Mapping[str, object], ...] = ()
    allowed_callers: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "label",
            "description",
            "audit_category",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_optional_string(self.suite_id, "suite_id")
        _validate_optional_string(self.area_id, "area_id")
        _validate_optional_string(self.module_id, "module_id")
        if self.suite_id is None and self.area_id is None:
            raise ValueError("suite_id or area_id must identify command ownership")
        object.__setattr__(
            self,
            "command_kind",
            _coerce_enum(self.command_kind, SuiteCommandKind, "command_kind"),
        )
        object.__setattr__(
            self,
            "required_permission",
            _normalize_permission_ref(self.required_permission, "required_permission"),
        )
        object.__setattr__(
            self,
            "expected_task_behavior",
            _coerce_enum(
                self.expected_task_behavior,
                SuiteTaskBehavior,
                "expected_task_behavior",
            ),
        )
        object.__setattr__(
            self,
            "runtime_policy",
            _coerce_enum(self.runtime_policy, SuiteRuntimePolicy, "runtime_policy"),
        )
        for field_name in ("creates_operation", "cancellable"):
            _validate_bool(getattr(self, field_name), field_name)
        for field_name in (
            "input_schema_ref",
            "result_schema_ref",
            "progress_schema_ref",
        ):
            _validate_optional_string(getattr(self, field_name), field_name)
        if _command_requires_operation(self) and self.creates_operation is not True:
            raise ValueError(
                "mutating, long-running, or task-backed commands must create operations"
            )
        _normalize_descriptor_sequences(self)
        object.__setattr__(
            self,
            "object_refs",
            _normalize_object_refs(self.object_refs, "object_refs"),
        )


@dataclass(frozen=True)
class SuiteQueryDescriptor:
    """
    Static descriptor for a suite read/query capability.

    Query descriptors describe read-model access. They do not execute queries,
    inspect runtime services, perform authorization, or mutate domain state.
    """

    query_id: str
    query_kind: SuiteQueryKind | str
    label: str
    description: str
    required_permission: Permission | str
    read_model_kind: str
    suite_id: str | None = None
    area_id: str | None = None
    module_id: str | None = None
    input_schema_ref: str | None = None
    result_schema_ref: str | None = None
    object_family_ids: tuple[str, ...] = ()
    object_refs: tuple[TraceableObjectRef | Mapping[str, object], ...] = ()
    cache_policy: SuiteCachePolicy | str = SuiteCachePolicy.NONE
    audit_policy: SuiteAuditPolicy | str = SuiteAuditPolicy.NONE
    allowed_callers: tuple[str, ...] = ()
    docs_refs: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "query_id",
            "label",
            "description",
            "read_model_kind",
        ):
            _validate_non_empty_string(getattr(self, field_name), field_name)
        _validate_optional_string(self.suite_id, "suite_id")
        _validate_optional_string(self.area_id, "area_id")
        _validate_optional_string(self.module_id, "module_id")
        if self.suite_id is None and self.area_id is None:
            raise ValueError("suite_id or area_id must identify query ownership")
        object.__setattr__(
            self,
            "query_kind",
            _coerce_enum(self.query_kind, SuiteQueryKind, "query_kind"),
        )
        object.__setattr__(
            self,
            "required_permission",
            _normalize_permission_ref(self.required_permission, "required_permission"),
        )
        object.__setattr__(
            self,
            "cache_policy",
            _coerce_enum(self.cache_policy, SuiteCachePolicy, "cache_policy"),
        )
        object.__setattr__(
            self,
            "audit_policy",
            _coerce_enum(self.audit_policy, SuiteAuditPolicy, "audit_policy"),
        )
        for field_name in ("input_schema_ref", "result_schema_ref"):
            _validate_optional_string(getattr(self, field_name), field_name)
        _normalize_descriptor_sequences(self)
        object.__setattr__(
            self,
            "object_refs",
            _normalize_object_refs(self.object_refs, "object_refs"),
        )


def _normalize_descriptor_sequences(value: object) -> None:
    permission_fields = {"required_permissions"}
    for field_name in _SEQUENCE_FIELDS:
        if not hasattr(value, field_name):
            continue
        field_value = getattr(value, field_name)
        if field_name in permission_fields:
            normalized = _normalize_permission_tuple(field_value, field_name)
        else:
            normalized = _normalize_string_tuple(field_value, field_name)
        object.__setattr__(value, field_name, normalized)


def _command_requires_operation(value: SuiteCommandDescriptor) -> bool:
    return (
        value.command_kind
        in {
            SuiteCommandKind.MUTATION,
            SuiteCommandKind.LONG_RUNNING,
            SuiteCommandKind.MAINTENANCE,
        }
        or value.expected_task_behavior is not SuiteTaskBehavior.NONE
        or value.runtime_policy is SuiteRuntimePolicy.CORE_RUNTIME_REQUIRED
    )


def _normalize_permission_tuple(
    values: tuple[Permission | str, ...],
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of permissions")
    return tuple(_normalize_permission_ref(value, f"{field_name} entry") for value in values)


def _normalize_permission_ref(value: Permission | str, field_name: str) -> str:
    if isinstance(value, Permission):
        return value.value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty permission string")
    if value.startswith("suite" + ":"):
        raise ValueError(
            f"{field_name} must use an established area permission namespace"
        )
    return value


def _normalize_object_refs(
    values: tuple[TraceableObjectRef | Mapping[str, object], ...],
    field_name: str,
) -> tuple[TraceableObjectRef, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of object references")
    normalized = tuple(values)
    return tuple(_normalize_object_ref(value, field_name) for value in normalized)


def _normalize_object_ref(
    value: TraceableObjectRef | Mapping[str, object],
    field_name: str,
) -> TraceableObjectRef:
    if isinstance(value, TraceableObjectRef):
        return value
    if isinstance(value, Mapping):
        return TraceableObjectRef.from_dict(value)
    raise TypeError(f"{field_name} entries must be TraceableObjectRef or mapping")


def _normalize_string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a tuple of strings")
    normalized = tuple(values)
    for item in normalized:
        _validate_non_empty_string(item, f"{field_name} entry")
    return normalized


def _coerce_enum(
    value: object,
    enum_type: type[Enum],
    field_name: str,
) -> Enum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise ValueError(f"{field_name} must be one of: {allowed}") from error
    raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _validate_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_optional_string(value: object, field_name: str) -> None:
    if value is None:
        return
    _validate_non_empty_string(value, field_name)


def _validate_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")


_SEQUENCE_FIELDS = (
    "module_ids",
    "object_family_ids",
    "command_ids",
    "query_ids",
    "required_permissions",
    "audit_categories",
    "docs_refs",
    "test_refs",
    "metadata_refs",
    "warnings",
    "blockers",
    "area_ids",
    "supported_command_ids",
    "supported_query_ids",
    "related_action_ids",
    "allowed_callers",
)


__all__ = [
    "AreaDescriptor",
    "AreaKind",
    "SuiteAuditPolicy",
    "SuiteCachePolicy",
    "SuiteCommandDescriptor",
    "SuiteCommandKind",
    "SuiteDescriptor",
    "SuiteLifecycleStatus",
    "SuiteModuleDescriptor",
    "SuiteQueryDescriptor",
    "SuiteQueryKind",
    "SuiteRuntimePolicy",
    "SuiteTaskBehavior",
]
