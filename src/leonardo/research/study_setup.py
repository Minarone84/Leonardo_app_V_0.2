"""Pure immutable Study Setup catalog and request construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

from leonardo.data import MarketId
from leonardo.financial_tools import (
    ALL_FINANCIAL_TOOL_SPECS,
    FinancialToolSpec,
    get_financial_tool_spec,
    resolve_parameters,
)
from leonardo.research.studies import (
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyInputSource,
    StudyUserMetadata,
)


_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
_KINDS = frozenset({"ohlcv", "study", "artifact"})
_MODES = frozenset({"calculation", "artifact"})
_MULTI_SOURCE_TOOLS = frozenset(
    {"dynamic_binning", "percent_span_angle", "angle_momentum"}
)


def _owned_selector_names(tool_key: str) -> frozenset[str]:
    if tool_key in {"derivative", "angle"}:
        return frozenset({"source"})
    if tool_key == "delta":
        return frozenset({"fast", "slow"})
    if tool_key in {"braids", "braid_instability", "trap_area"}:
        return frozenset({"fast", "mid", "slow"})
    if tool_key in _MULTI_SOURCE_TOOLS:
        return frozenset({"source_columns"})
    if tool_key == "universal_trend_classifier":
        return frozenset({"peak_column", "trough_column"})
    return frozenset()


class StudySetupValidationError(ValueError):
    """Raised when a Study Setup draft violates canonical setup policy."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StudySetupValidationError(f"{name} must be canonical non-empty text")
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StudySetupValidationError(f"{name} must be a mapping")
    copied = deepcopy(dict(value))
    if not all(isinstance(key, str) for key in copied):
        raise StudySetupValidationError(f"{name} keys must be strings")
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class StudySourceOption:
    source_kind: str
    label: str
    family: str
    column_name: str | None = None
    study_id: str | None = None
    artifact_kind: str | None = None
    artifact_tool_key: str | None = None
    artifact_id: str | None = None
    output_name: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in _KINDS:
            raise StudySetupValidationError("unsupported source option kind")
        _text(self.label, "label")
        _text(self.family, "family")
        supplied = {
            "column_name": self.column_name,
            "study_id": self.study_id,
            "artifact_kind": self.artifact_kind,
            "artifact_tool_key": self.artifact_tool_key,
            "artifact_id": self.artifact_id,
            "output_name": self.output_name,
        }
        present = {name for name, value in supplied.items() if value is not None}
        required = {
            "ohlcv": {"column_name"},
            "study": {"study_id", "output_name"},
            "artifact": {
                "artifact_kind",
                "artifact_tool_key",
                "artifact_id",
                "output_name",
            },
        }[self.source_kind]
        if present != required:
            raise StudySetupValidationError("source option fields do not match kind")
        if self.source_kind == "ohlcv" and self.column_name not in _OHLCV_COLUMNS:
            raise StudySetupValidationError("OHLCV source option is not canonical")


@dataclass(frozen=True, slots=True)
class StudyArtifactOption:
    market_id: MarketId
    artifact_id: str
    kind: str
    tool_key: str
    display_name: str
    output_names: tuple[str, ...]
    analysis_usable_output_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, MarketId):
            raise StudySetupValidationError("market_id must be a MarketId")
        _text(self.artifact_id, "artifact_id")
        spec = get_financial_tool_spec(_text(self.tool_key, "tool_key"))
        if self.kind != spec.kind:
            raise StudySetupValidationError("artifact option kind does not match tool")
        _text(self.display_name, "display_name")
        outputs = tuple(self.output_names)
        if not outputs or any(not isinstance(item, str) or not item for item in outputs):
            raise StudySetupValidationError("artifact option outputs are invalid")
        object.__setattr__(self, "output_names", outputs)
        analysis = (
            outputs
            if self.analysis_usable_output_names is None
            else tuple(self.analysis_usable_output_names)
        )
        if any(item not in outputs for item in analysis):
            raise StudySetupValidationError(
                "analysis-usable artifact outputs must exist in output_names"
            )
        object.__setattr__(self, "analysis_usable_output_names", analysis)


@dataclass(frozen=True, slots=True)
class StudySetupCatalogRejection:
    artifact_id: str
    kind: str
    tool_key: str
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.kind, "kind"),
            (self.tool_key, "tool_key"),
            (self.reason, "reason"),
        ):
            _text(value, name)


@dataclass(frozen=True, slots=True)
class StudySetupCatalog:
    market_id: MarketId
    tools: tuple[FinancialToolSpec, ...]
    ohlcv_sources: tuple[StudySourceOption, ...]
    study_sources: tuple[StudySourceOption, ...]
    artifact_options: tuple[StudyArtifactOption, ...]
    artifact_rejections: tuple[StudySetupCatalogRejection, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, MarketId):
            raise StudySetupValidationError("market_id must be a MarketId")
        tools = tuple(self.tools)
        if not all(isinstance(item, FinancialToolSpec) for item in tools):
            raise StudySetupValidationError("tools must contain FinancialToolSpec values")
        if len({item.key for item in tools}) != len(tools):
            raise StudySetupValidationError("catalog tool keys must be unique")
        if tuple(item.key for item in tools) != tuple(ALL_FINANCIAL_TOOL_SPECS):
            raise StudySetupValidationError("catalog must contain all canonical tools in order")
        for values, cls, name in (
            (self.ohlcv_sources, StudySourceOption, "ohlcv_sources"),
            (self.study_sources, StudySourceOption, "study_sources"),
            (self.artifact_options, StudyArtifactOption, "artifact_options"),
            (self.artifact_rejections, StudySetupCatalogRejection, "artifact_rejections"),
        ):
            normalized = tuple(values)
            if not all(isinstance(item, cls) for item in normalized):
                raise StudySetupValidationError(f"{name} contains invalid values")
            object.__setattr__(self, name, normalized)

    @property
    def source_options(self) -> tuple[StudySourceOption, ...]:
        artifact_sources = tuple(
            StudySourceOption(
                source_kind="artifact",
                label=f"{item.display_name}: {output}",
                family=item.kind,
                artifact_kind=item.kind,
                artifact_tool_key=item.tool_key,
                artifact_id=item.artifact_id,
                output_name=output,
            )
            for item in self.artifact_options
            for output in item.analysis_usable_output_names
        )
        return (*self.ohlcv_sources, *self.study_sources, *artifact_sources)


@dataclass(frozen=True, slots=True)
class StudySetupSourceSelection:
    role: str
    source_kind: str
    column_name: str | None = None
    study_id: str | None = None
    artifact_kind: str | None = None
    artifact_tool_key: str | None = None
    artifact_id: str | None = None
    output_name: str | None = None

    def __post_init__(self) -> None:
        _text(self.role, "role")
        if self.source_kind not in _KINDS:
            raise StudySetupValidationError("unsupported source selection kind")


@dataclass(frozen=True, slots=True)
class StudySetupDraft:
    mode: str
    tool_key: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    sources: tuple[StudySetupSourceSelection, ...] = ()
    artifact_id: str | None = None
    display_name: str | None = None
    user_metadata: StudyUserMetadata = StudyUserMetadata()

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise StudySetupValidationError("unsupported Study Setup mode")
        _text(self.tool_key, "tool_key")
        object.__setattr__(self, "parameters", _mapping(self.parameters, "parameters"))
        sources = tuple(self.sources)
        if not all(isinstance(item, StudySetupSourceSelection) for item in sources):
            raise StudySetupValidationError("sources contain invalid selections")
        object.__setattr__(self, "sources", sources)
        if self.display_name is not None:
            _text(self.display_name, "display_name")
        if not isinstance(self.user_metadata, StudyUserMetadata):
            raise StudySetupValidationError("user_metadata must be StudyUserMetadata")


def source_role_schema(tool_key: str) -> tuple[str, ...]:
    """Return the exact frozen source-role schema for one canonical tool."""

    key = get_financial_tool_spec(tool_key).key
    if key in {"derivative", "angle"}:
        return ("source",)
    if key == "delta":
        return ("fast", "slow")
    if key in {"braids", "braid_instability", "trap_area"}:
        return ("fast", "mid?", "slow")
    if key in _MULTI_SOURCE_TOOLS:
        return ("source_1", "...")
    if key == "universal_trend_classifier":
        return ("peak+trough?",)
    return ()


def build_study_request(
    draft: StudySetupDraft,
    catalog: StudySetupCatalog,
) -> StudyExecutionRequest | StudyArtifactRequest:
    """Validate one immutable draft and build an existing Task 1017 request."""

    if not isinstance(draft, StudySetupDraft):
        raise StudySetupValidationError("draft must be StudySetupDraft")
    if not isinstance(catalog, StudySetupCatalog):
        raise StudySetupValidationError("catalog must be StudySetupCatalog")
    specs = {item.key: item for item in catalog.tools}
    if draft.tool_key not in specs:
        raise StudySetupValidationError("tool is not present in the canonical catalog")
    spec = specs[draft.tool_key]
    if draft.mode == "artifact":
        if draft.sources or draft.parameters:
            raise StudySetupValidationError("direct artifact Apply has no form sources or parameters")
        option = next(
            (
                item
                for item in catalog.artifact_options
                if item.artifact_id == draft.artifact_id
                and item.tool_key == draft.tool_key
                and item.kind == spec.kind
            ),
            None,
        )
        if option is None:
            raise StudySetupValidationError("artifact is not a current selectable option")
        return StudyArtifactRequest(
            option.kind,
            option.tool_key,
            option.artifact_id,
            display_name=draft.display_name or option.display_name,
            user_metadata=draft.user_metadata,
        )

    if draft.artifact_id is not None:
        raise StudySetupValidationError("calculation drafts may not contain artifact_id")
    selectors = _owned_selector_names(draft.tool_key)
    supplied_selectors = tuple(sorted(selectors.intersection(draft.parameters)))
    if supplied_selectors:
        raise StudySetupValidationError(
            f"service-owned source selectors were supplied: {supplied_selectors!r}"
        )
    try:
        parameters = {
            name: value
            for name, value in resolve_parameters(draft.tool_key, draft.parameters).items()
            if name not in selectors
        }
    except (TypeError, ValueError) as exc:
        raise StudySetupValidationError(str(exc)) from exc
    roles = tuple(item.role for item in draft.sources)
    _validate_roles(draft.tool_key, roles)
    options = catalog.source_options
    input_sources: list[StudyInputSource] = []
    families: list[str] = []
    for selection in draft.sources:
        option = _match_source_option(selection, options)
        if option is None:
            raise StudySetupValidationError(
                f"source selection for role {selection.role!r} is not in the catalog"
            )
        families.append(option.family)
        input_sources.append(
            StudyInputSource(
                role=selection.role,
                source_kind=selection.source_kind,
                column_name=selection.column_name,
                study_id=selection.study_id,
                artifact_kind=selection.artifact_kind,
                artifact_tool_key=selection.artifact_tool_key,
                artifact_id=selection.artifact_id,
                output_name=selection.output_name,
            )
        )
    construct = spec.construct_io
    if construct is not None and any(
        family not in construct.allowed_source_families for family in families
    ):
        raise StudySetupValidationError("selected source family is not allowed")
    if (
        construct is not None
        and construct.source_compatibility == "same_family"
        and len(set(families)) > 1
    ):
        raise StudySetupValidationError("selected sources must use one family")
    return StudyExecutionRequest(
        draft.tool_key,
        parameters,
        tuple(input_sources),
        display_name=draft.display_name or spec.title,
        user_metadata=draft.user_metadata,
    )


def _validate_roles(tool_key: str, roles: tuple[str, ...]) -> None:
    schema = source_role_schema(tool_key)
    if schema == ("source_1", "..."):
        expected = tuple(f"source_{index}" for index in range(1, len(roles) + 1))
        if not roles or roles != expected:
            raise StudySetupValidationError("multi-source roles must be contiguous and ordered")
        return
    if schema == ("peak+trough?",):
        if roles not in ((), ("peak", "trough")):
            raise StudySetupValidationError("UTC sources must be absent or an exact peak/trough pair")
        return
    if schema == ("fast", "mid?", "slow"):
        if roles not in (("fast", "slow"), ("fast", "mid", "slow")):
            raise StudySetupValidationError("source roles must be fast, optional mid, slow")
        return
    if roles != schema:
        raise StudySetupValidationError(f"source roles must be {schema!r}")


def _match_source_option(
    selection: StudySetupSourceSelection,
    options: Sequence[StudySourceOption],
) -> StudySourceOption | None:
    fields = (
        "source_kind",
        "column_name",
        "study_id",
        "artifact_kind",
        "artifact_tool_key",
        "artifact_id",
        "output_name",
    )
    return next(
        (
            option
            for option in options
            if all(getattr(option, name) == getattr(selection, name) for name in fields)
        ),
        None,
    )
