"""Immutable chart-local Study state and ordered registry ownership."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from leonardo.artifacts import ArtifactSourceRefV1
from leonardo.data import MarketId, canonicalize_market_id
from leonardo.financial_tools import (
    FinancialToolCalculationResult,
    canonicalize_tool_key,
    get_financial_tool_spec,
    resolve_output_signals,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})
_SOURCE_KINDS = frozenset({"ohlcv", "study", "artifact"})
_STUDY_SOURCE_KINDS = frozenset({"calculation", "artifact"})
STUDY_DATASET_ROLES = (
    "unspecified",
    "core_geography",
    "volume",
    "braid",
    "peaks_troughs",
    "utc",
    "supporting_indicator",
    "supporting_oscillator",
    "supporting_construct",
    "helper_dependency",
    "experimental",
    "visual_only",
)
_PRIVATE_SOURCE_ALIASES = {
    "source": "__research_source",
    "fast": "__research_fast",
    "mid": "__research_mid",
    "slow": "__research_slow",
    "peak": "__research_peak",
    "trough": "__research_trough",
    "trend_peak": "__research_trend_peak",
    "trend_trough": "__research_trend_trough",
    "range_peak": "__research_range_peak",
    "range_trough": "__research_range_trough",
}


class StudyError(Exception):
    """Base error for Research Study operations."""


class StudyValidationError(StudyError, ValueError):
    """Raised when Study input or state violates the frozen contract."""


class StudyNotFoundError(StudyError, KeyError):
    """Raised when a chart-local Study does not exist."""


class StudyDependencyError(StudyError):
    """Raised when a Study operation would break a live dependency."""

    def __init__(self, message: str, *, blockers: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.blockers = tuple(blockers)


class StudySaveBlockedError(StudyDependencyError):
    """Raised when transient Study lineage is not durably saveable."""


class StudyOperationCancelled(StudyError):
    """Raised when a Core-supervised Study operation is cancelled."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StudyValidationError(f"{field_name} must be canonical non-empty text")
    return value


def _sha256(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _SHA256_RE.fullmatch(text) is None:
        raise StudyValidationError(f"{field_name} must be a lowercase SHA-256 value")
    return text


def _role(value: object) -> str:
    text = _text(value, "role")
    if _ROLE_RE.fullmatch(text) is None:
        raise StudyValidationError("role must be a canonical source identifier")
    return text


def _market(value: object) -> MarketId:
    if not isinstance(value, MarketId):
        raise StudyValidationError("market_id must be a MarketId")
    canonical = canonicalize_market_id(
        value.exchange, value.market_type, value.symbol, value.timeframe
    )
    if canonical != value:
        raise StudyValidationError("market_id must already be canonical")
    return value


def _canonical_tool(value: object, field_name: str):
    key = _text(value, field_name)
    try:
        canonical = canonicalize_tool_key(key)
        spec = get_financial_tool_spec(canonical)
    except (KeyError, TypeError, ValueError) as exc:
        raise StudyValidationError(f"{field_name} is not a known Financial Tool") from exc
    if canonical != key:
        raise StudyValidationError(f"{field_name} must already be canonical")
    return key, spec


def _result_copy(result: object) -> FinancialToolCalculationResult:
    if not isinstance(result, FinancialToolCalculationResult):
        raise StudyValidationError("result must be a FinancialToolCalculationResult")
    return FinancialToolCalculationResult(
        tool_key=result.tool_key,
        kind=result.kind,
        parameters=result.parameters,
        bindings=result.bindings,
        output_names=result.output_names,
        frame=result.to_frame(),
        analysis=result.analysis,
    )


def _frozen_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StudyValidationError(f"{field_name} must be a mapping")
    copied = deepcopy(dict(value))
    if not all(isinstance(key, str) for key in copied):
        raise StudyValidationError(f"{field_name} keys must be strings")
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class StudyUserMetadata:
    """Semantic user metadata that does not alter Study calculation or identity."""

    important: bool = False
    dataset_role: str = "unspecified"
    description: str = ""

    def __post_init__(self) -> None:
        if type(self.important) is not bool:
            raise StudyValidationError("important must be a boolean")
        if self.dataset_role not in STUDY_DATASET_ROLES:
            raise StudyValidationError("dataset_role is not supported")
        if not isinstance(self.description, str):
            raise StudyValidationError("description must be a string")


@dataclass(frozen=True, slots=True)
class _CanonicalSelectorLineage:
    external_roles: tuple[str, ...]
    exact_outputs: tuple[tuple[str, str], ...]
    implicit_ohlcv: tuple[tuple[str, str], ...]


def _validate_study_source_lineage(
    result: FinancialToolCalculationResult,
    source_studies: Sequence["StudyDependencyRef"],
    source_artifacts: Sequence[ArtifactSourceRefV1],
    *,
    study_id: str | None,
) -> tuple[str, ...]:
    """Require declared Study lineage to match canonical Task 1015 selectors."""

    if not isinstance(result, FinancialToolCalculationResult):
        raise StudyValidationError("result must be a FinancialToolCalculationResult")
    studies = tuple(source_studies)
    artifacts = tuple(source_artifacts)
    if not all(isinstance(item, StudyDependencyRef) for item in studies):
        raise StudyValidationError("source_studies must contain StudyDependencyRef values")
    if not all(isinstance(item, ArtifactSourceRefV1) for item in artifacts):
        raise StudyValidationError("source_artifacts must contain ArtifactSourceRefV1 values")
    references = (*studies, *artifacts)
    roles = tuple(item.role for item in references)
    if len(roles) != len(set(roles)):
        raise StudyValidationError("Study source roles must be unique")
    if study_id is not None and any(
        item.study_id == study_id for item in studies
    ):
        raise StudyValidationError("a Study may not depend on itself")

    selectors = _canonical_selector_lineage(result)
    expected_roles = selectors.external_roles
    utc_roles_valid = roles == expected_roles or (
        not studies and roles == tuple(sorted(expected_roles))
    )
    if (
        result.tool_key == "universal_trend_classifier"
        and not utc_roles_valid
    ) or (
        result.tool_key != "universal_trend_classifier"
        and (set(roles) != set(expected_roles) or len(roles) != len(expected_roles))
    ):
        raise StudyValidationError(
            f"Study lineage roles {tuple(sorted(roles))!r} do not match selectors "
            f"{tuple(sorted(expected_roles))!r}"
        )
    by_role = {item.role: item for item in references}
    for role, output_name in selectors.exact_outputs:
        if by_role[role].output_name != output_name:
            raise StudyValidationError(
                f"Study lineage output for {role!r} must be {output_name!r}"
            )
    if result.tool_key == "universal_trend_classifier" and references:
        owners = {
            (
                "study",
                item.study_id,
            )
            if isinstance(item, StudyDependencyRef)
            else (
                "artifact",
                item.artifact_id,
            )
            for item in references
        }
        if len(owners) != 1:
            raise StudyValidationError(
                "UTC sources must come from one Peaks & Troughs owner"
            )
    _validate_implicit_ohlcv_families(result, selectors)
    return expected_roles


def _canonical_selector_lineage(
    result: FinancialToolCalculationResult,
) -> _CanonicalSelectorLineage:
    key = result.tool_key
    parameters = dict(result.parameters)
    bindings = dict(result.bindings)
    if key in {"derivative", "angle"}:
        selector = bindings.get("source")
        if selector in _OHLCV_COLUMNS:
            return _CanonicalSelectorLineage((), (), (("source", selector),))
        if selector == _PRIVATE_SOURCE_ALIASES["source"]:
            return _CanonicalSelectorLineage(("source",), (), ())
        raise StudyValidationError(f"invalid canonical {key} source selector")
    if key in {"delta", "braids", "braid_instability", "trap_area"}:
        roles = ("fast", "slow") if key == "delta" else ("fast", "mid", "slow")
        external: list[str] = []
        implicit: list[tuple[str, str]] = []
        for role in roles:
            selector = parameters.get(role)
            if role == "mid" and key == "trap_area" and selector == "":
                continue
            if selector in _OHLCV_COLUMNS:
                implicit.append((role, selector))
                continue
            if selector == _PRIVATE_SOURCE_ALIASES[role]:
                external.append(role)
                continue
            raise StudyValidationError(
                f"invalid canonical {key} selector for role {role!r}"
            )
        return _CanonicalSelectorLineage(tuple(external), (), tuple(implicit))
    if key in {"dynamic_binning", "percent_span_angle", "angle_momentum"}:
        raw = parameters.get("source_columns")
        if not isinstance(raw, str) or not raw:
            raise StudyValidationError(f"{key}.source_columns must be canonical text")
        selectors = tuple(item.strip() for item in raw.split(","))
        if not selectors or any(not item for item in selectors):
            raise StudyValidationError(f"{key}.source_columns is invalid")
        external = []
        implicit = []
        for index, selector in enumerate(selectors, start=1):
            role = f"source_{index}"
            if selector in _OHLCV_COLUMNS:
                implicit.append((role, selector))
                continue
            expected = f"__research_source_{index}"
            if selector != expected:
                raise StudyValidationError(
                    f"invalid canonical {key} selector at position {index}"
                )
            external.append(role)
        return _CanonicalSelectorLineage(tuple(external), (), tuple(implicit))
    if key == "universal_trend_classifier":
        peak = parameters.get("peak_column")
        trough = parameters.get("trough_column")
        if peak is None and trough is None:
            return _CanonicalSelectorLineage((), (), ())
        trend_window = parameters.get("trend_fractal_window")
        range_window = parameters.get("range_fractal_window")
        if (
            type(trend_window) is not int
            or trend_window <= 0
            or type(range_window) is not int
            or range_window <= 0
        ):
            raise StudyValidationError("UTC fractal windows must be positive integers")
        if (
            peak != f"peak_fractal_{trend_window}"
            or trough != f"trough_fractal_{trend_window}"
        ):
            raise StudyValidationError(
                "UTC trend peak and trough selectors must form an exact pair"
            )
        return _CanonicalSelectorLineage(
            ("trend_peak", "trend_trough", "range_peak", "range_trough"),
            (
                ("trend_peak", f"peak_fractal_{trend_window}"),
                ("trend_trough", f"trough_fractal_{trend_window}"),
                ("range_peak", f"peak_fractal_{range_window}"),
                ("range_trough", f"trough_fractal_{range_window}"),
            ),
            (),
        )
    return _CanonicalSelectorLineage((), (), ())


def _validate_implicit_ohlcv_families(
    result: FinancialToolCalculationResult,
    selectors: _CanonicalSelectorLineage,
) -> None:
    if not selectors.implicit_ohlcv:
        return
    construct = get_financial_tool_spec(result.tool_key).construct_io
    if construct is not None and "ohlc" not in construct.allowed_source_families:
        families = tuple("ohlc" for _item in selectors.implicit_ohlcv)
        raise StudyValidationError(f"source families are not allowed: {families!r}")


@dataclass(frozen=True, slots=True)
class StudyInputSource:
    role: str
    source_kind: str
    column_name: str | None = None
    study_id: str | None = None
    artifact_kind: str | None = None
    artifact_tool_key: str | None = None
    artifact_id: str | None = None
    output_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _role(self.role))
        source_kind = _text(self.source_kind, "source_kind")
        if source_kind not in _SOURCE_KINDS:
            raise StudyValidationError(f"unsupported source_kind: {source_kind!r}")
        object.__setattr__(self, "source_kind", source_kind)
        supplied = {
            "column_name": self.column_name,
            "study_id": self.study_id,
            "artifact_kind": self.artifact_kind,
            "artifact_tool_key": self.artifact_tool_key,
            "artifact_id": self.artifact_id,
            "output_name": self.output_name,
        }
        if source_kind == "ohlcv":
            if set(key for key, value in supplied.items() if value is not None) != {
                "column_name"
            }:
                raise StudyValidationError("OHLCV sources require only column_name")
            column = _text(self.column_name, "column_name")
            if column not in _OHLCV_COLUMNS:
                raise StudyValidationError("column_name must be canonical OHLCV")
            object.__setattr__(self, "column_name", column)
        elif source_kind == "study":
            if set(key for key, value in supplied.items() if value is not None) != {
                "study_id",
                "output_name",
            }:
                raise StudyValidationError("Study sources require study_id and output_name")
            object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
            object.__setattr__(self, "output_name", _text(self.output_name, "output_name"))
        else:
            if set(key for key, value in supplied.items() if value is not None) != {
                "artifact_kind",
                "artifact_tool_key",
                "artifact_id",
                "output_name",
            }:
                raise StudyValidationError(
                    "artifact sources require kind, tool key, artifact ID, and output name"
                )
            key, spec = _canonical_tool(self.artifact_tool_key, "artifact_tool_key")
            kind = _text(self.artifact_kind, "artifact_kind")
            if spec.kind != kind:
                raise StudyValidationError("artifact_kind must match artifact_tool_key")
            object.__setattr__(self, "artifact_kind", kind)
            object.__setattr__(self, "artifact_tool_key", key)
            object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))
            object.__setattr__(self, "output_name", _text(self.output_name, "output_name"))


@dataclass(frozen=True, slots=True)
class StudyExecutionRequest:
    tool_key: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    input_sources: tuple[StudyInputSource, ...] = ()
    display_name: str | None = None
    user_metadata: StudyUserMetadata = StudyUserMetadata()

    def __post_init__(self) -> None:
        key, spec = _canonical_tool(self.tool_key, "tool_key")
        parameters = _frozen_mapping(self.parameters, "parameters")
        if not isinstance(self.input_sources, Sequence) or isinstance(
            self.input_sources, (str, bytes, bytearray)
        ):
            raise StudyValidationError("input_sources must be a sequence")
        sources = tuple(self.input_sources)
        if not all(isinstance(source, StudyInputSource) for source in sources):
            raise StudyValidationError("input_sources must contain StudyInputSource values")
        if len({source.role for source in sources}) != len(sources):
            raise StudyValidationError("input source roles must be unique")
        display = spec.title if self.display_name is None else _text(
            self.display_name, "display_name"
        )
        object.__setattr__(self, "tool_key", key)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "input_sources", sources)
        object.__setattr__(self, "display_name", display)
        if not isinstance(self.user_metadata, StudyUserMetadata):
            raise StudyValidationError("user_metadata must be StudyUserMetadata")


@dataclass(frozen=True, slots=True)
class StudyArtifactRequest:
    kind: str
    tool_key: str
    artifact_id: str
    display_name: str | None = None
    user_metadata: StudyUserMetadata = StudyUserMetadata()

    def __post_init__(self) -> None:
        key, spec = _canonical_tool(self.tool_key, "tool_key")
        kind = _text(self.kind, "kind")
        if kind != spec.kind:
            raise StudyValidationError("kind must match tool_key")
        display = None if self.display_name is None else _text(
            self.display_name, "display_name"
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "tool_key", key)
        object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "display_name", display)
        if not isinstance(self.user_metadata, StudyUserMetadata):
            raise StudyValidationError("user_metadata must be StudyUserMetadata")


@dataclass(frozen=True, slots=True)
class StudyDependencyRef:
    role: str
    study_id: str
    output_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _role(self.role))
        object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
        object.__setattr__(self, "output_name", _text(self.output_name, "output_name"))


@dataclass(frozen=True, slots=True)
class StudySavedLink:
    kind: str
    tool_key: str
    recipe_id: str
    artifact_id: str

    def __post_init__(self) -> None:
        key, spec = _canonical_tool(self.tool_key, "tool_key")
        kind = _text(self.kind, "kind")
        if spec.kind != kind:
            raise StudyValidationError("kind must match tool_key")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "tool_key", key)
        object.__setattr__(self, "recipe_id", _sha256(self.recipe_id, "recipe_id"))
        object.__setattr__(self, "artifact_id", _sha256(self.artifact_id, "artifact_id"))


@dataclass(frozen=True, slots=True)
class StudyApplyAttempt:
    session_id: str
    generation: int
    request_id: str
    study_id: str
    market_id: MarketId
    dataset_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _text(self.session_id, "session_id"))
        if type(self.generation) is not int or self.generation <= 0:
            raise StudyValidationError("generation must be a positive integer")
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
        object.__setattr__(self, "market_id", _market(self.market_id))
        object.__setattr__(
            self, "dataset_fingerprint", _sha256(self.dataset_fingerprint, "dataset_fingerprint")
        )


@dataclass(frozen=True, slots=True)
class StudySaveAttempt:
    session_id: str
    generation: int
    request_id: str
    study_id: str
    market_id: MarketId
    dataset_fingerprint: str

    def __post_init__(self) -> None:
        StudyApplyAttempt(
            session_id=self.session_id,
            generation=self.generation,
            request_id=self.request_id,
            study_id=self.study_id,
            market_id=self.market_id,
            dataset_fingerprint=self.dataset_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class StudyEditAttempt:
    session_id: str
    generation: int
    request_id: str
    study_id: str
    market_id: MarketId
    dataset_fingerprint: str

    def __post_init__(self) -> None:
        StudyApplyAttempt(
            session_id=self.session_id,
            generation=self.generation,
            request_id=self.request_id,
            study_id=self.study_id,
            market_id=self.market_id,
            dataset_fingerprint=self.dataset_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ChartStudy:
    study_id: str
    session_id: str
    generation: int
    market_id: MarketId
    dataset_fingerprint: str
    source_kind: str
    display_name: str
    result: FinancialToolCalculationResult
    setup_request: StudyExecutionRequest | StudyArtifactRequest
    edit_request: StudyExecutionRequest
    user_metadata: StudyUserMetadata = StudyUserMetadata()
    source_studies: tuple[StudyDependencyRef, ...] = ()
    source_artifacts: tuple[ArtifactSourceRefV1, ...] = ()
    saved_link: StudySavedLink | None = None
    pane_role: str | None = None
    renderable_output_names: tuple[str, ...] = ()
    style_driver_output_names: tuple[str, ...] = ()
    analysis_usable_output_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
        object.__setattr__(self, "session_id", _text(self.session_id, "session_id"))
        if type(self.generation) is not int or self.generation <= 0:
            raise StudyValidationError("generation must be a positive integer")
        object.__setattr__(self, "market_id", _market(self.market_id))
        object.__setattr__(
            self, "dataset_fingerprint", _sha256(self.dataset_fingerprint, "dataset_fingerprint")
        )
        source_kind = _text(self.source_kind, "source_kind")
        if source_kind not in _STUDY_SOURCE_KINDS:
            raise StudyValidationError("unsupported Study source_kind")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name"))
        result = _result_copy(self.result)
        object.__setattr__(self, "result", result)
        if not isinstance(self.user_metadata, StudyUserMetadata):
            raise StudyValidationError("user_metadata must be StudyUserMetadata")
        dependencies = tuple(self.source_studies)
        artifacts = tuple(self.source_artifacts)
        if not all(isinstance(item, StudyDependencyRef) for item in dependencies):
            raise StudyValidationError("source_studies must contain StudyDependencyRef values")
        if not all(isinstance(item, ArtifactSourceRefV1) for item in artifacts):
            raise StudyValidationError("source_artifacts must contain ArtifactSourceRefV1 values")
        roles = tuple(item.role for item in dependencies) + tuple(item.role for item in artifacts)
        if len(roles) != len(set(roles)):
            raise StudyValidationError("Study source roles must be unique")
        object.__setattr__(self, "source_studies", dependencies)
        object.__setattr__(self, "source_artifacts", artifacts)
        if source_kind == "artifact":
            if self.saved_link is None:
                raise StudyValidationError("artifact Studies require a saved_link")
            if dependencies:
                raise StudyValidationError(
                    "artifact Studies may not contain transient source_studies"
                )
        _validate_study_source_lineage(
            result,
            dependencies,
            artifacts,
            study_id=self.study_id,
        )
        if self.saved_link is not None:
            if not isinstance(self.saved_link, StudySavedLink):
                raise StudyValidationError("saved_link must be a StudySavedLink")
            if (
                self.saved_link.kind != result.kind
                or self.saved_link.tool_key != result.tool_key
            ):
                raise StudyValidationError("saved_link must match the Study result")
        _validate_setup_request(
            self.setup_request,
            source_kind=source_kind,
            display_name=self.display_name,
            result=result,
            user_metadata=self.user_metadata,
        )
        _validate_edit_request(
            self.edit_request,
            setup_request=self.setup_request,
            source_kind=source_kind,
            display_name=self.display_name,
            result=result,
            user_metadata=self.user_metadata,
            source_artifacts=artifacts,
        )
        signals = resolve_output_signals(
            result.tool_key, {**dict(result.parameters), **dict(result.bindings)}
        )
        renderable = tuple(signal.name for signal in signals if signal.renderable)
        style_drivers = tuple(
            signal.name
            for signal in signals
            if not signal.renderable and signal.can_drive_style_rules
        )
        analysis_usable = tuple(signal.name for signal in signals if signal.analysis_usable)
        spec = get_financial_tool_spec(result.tool_key)
        pane = {
            "overlay": "price",
            "oscillator-pane": "oscillator",
            "non-visual": None,
        }[spec.behavior.output_mode]
        supplied = (
            self.pane_role,
            tuple(self.renderable_output_names),
            tuple(self.style_driver_output_names),
            tuple(self.analysis_usable_output_names),
        )
        canonical = (pane, renderable, style_drivers, analysis_usable)
        if supplied != canonical:
            raise StudyValidationError("Study output metadata must match Task 1014")


@dataclass(frozen=True, slots=True)
class PreparedStudy:
    study: ChartStudy

    def __post_init__(self) -> None:
        if not isinstance(self.study, ChartStudy):
            raise StudyValidationError("study must be a ChartStudy")


@dataclass(frozen=True, slots=True)
class StudySaveOutcome:
    study_id: str
    saved_link: StudySavedLink
    created: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "study_id", _text(self.study_id, "study_id"))
        if not isinstance(self.saved_link, StudySavedLink):
            raise StudyValidationError("saved_link must be a StudySavedLink")
        if type(self.created) is not bool:
            raise StudyValidationError("created must be a boolean")


def build_chart_study(
    *,
    attempt: StudyApplyAttempt | StudyEditAttempt,
    source_kind: str,
    display_name: str,
    result: FinancialToolCalculationResult,
    setup_request: StudyExecutionRequest | StudyArtifactRequest,
    edit_request: StudyExecutionRequest | None = None,
    source_studies: Sequence[StudyDependencyRef] = (),
    source_artifacts: Sequence[ArtifactSourceRefV1] = (),
    saved_link: StudySavedLink | None = None,
) -> ChartStudy:
    """Build one canonical Study from an accepted attempt and full result."""

    if source_kind == "calculation":
        if not isinstance(setup_request, StudyExecutionRequest):
            raise StudyValidationError(
                "calculation Studies require a StudyExecutionRequest setup_request"
            )
        resolved_edit_request = setup_request
        if edit_request is not None and edit_request != resolved_edit_request:
            raise StudyValidationError(
                "calculation Study edit_request must equal setup_request"
            )
    else:
        if not isinstance(edit_request, StudyExecutionRequest):
            raise StudyValidationError(
                "artifact Studies require an explicit edit_request"
            )
        resolved_edit_request = edit_request
    signals = resolve_output_signals(
        result.tool_key, {**dict(result.parameters), **dict(result.bindings)}
    )
    spec = get_financial_tool_spec(result.tool_key)
    return ChartStudy(
        study_id=attempt.study_id,
        session_id=attempt.session_id,
        generation=attempt.generation,
        market_id=attempt.market_id,
        dataset_fingerprint=attempt.dataset_fingerprint,
        source_kind=source_kind,
        display_name=display_name,
        result=result,
        setup_request=setup_request,
        edit_request=resolved_edit_request,
        user_metadata=setup_request.user_metadata,
        source_studies=tuple(source_studies),
        source_artifacts=tuple(source_artifacts),
        saved_link=saved_link,
        pane_role={
            "overlay": "price",
            "oscillator-pane": "oscillator",
            "non-visual": None,
        }[spec.behavior.output_mode],
        renderable_output_names=tuple(signal.name for signal in signals if signal.renderable),
        style_driver_output_names=tuple(
            signal.name
            for signal in signals
            if not signal.renderable and signal.can_drive_style_rules
        ),
        analysis_usable_output_names=tuple(
            signal.name for signal in signals if signal.analysis_usable
        ),
    )


def _validate_setup_request(
    request: object,
    *,
    source_kind: str,
    display_name: str,
    result: FinancialToolCalculationResult,
    user_metadata: StudyUserMetadata,
) -> None:
    if source_kind == "calculation":
        if not isinstance(request, StudyExecutionRequest):
            raise StudyValidationError(
                "calculation Studies require a StudyExecutionRequest setup_request"
            )
        if request.tool_key != result.tool_key:
            raise StudyValidationError("setup_request tool does not match Study result")
    else:
        if not isinstance(request, StudyArtifactRequest):
            raise StudyValidationError(
                "artifact Studies require a StudyArtifactRequest setup_request"
            )
        if request.tool_key != result.tool_key or request.kind != result.kind:
            raise StudyValidationError("setup_request artifact does not match Study result")
    if request.display_name is not None and request.display_name != display_name:
        raise StudyValidationError("setup_request display name does not match Study")
    if request.user_metadata != user_metadata:
        raise StudyValidationError("setup_request metadata does not match Study metadata")


def _validate_edit_request(
    request: object,
    *,
    setup_request: StudyExecutionRequest | StudyArtifactRequest,
    source_kind: str,
    display_name: str,
    result: FinancialToolCalculationResult,
    user_metadata: StudyUserMetadata,
    source_artifacts: tuple[ArtifactSourceRefV1, ...],
) -> None:
    if not isinstance(request, StudyExecutionRequest):
        raise StudyValidationError("edit_request must be a StudyExecutionRequest")
    if request.tool_key != result.tool_key:
        raise StudyValidationError("edit_request tool does not match Study result")
    if request.display_name != display_name:
        raise StudyValidationError("edit_request display name does not match Study")
    if request.user_metadata != user_metadata:
        raise StudyValidationError("edit_request metadata does not match Study metadata")
    if source_kind == "calculation" and request != setup_request:
        raise StudyValidationError(
            "calculation Study edit_request must equal setup_request"
        )
    if source_kind == "artifact" and any(
        source.source_kind == "study" for source in request.input_sources
    ):
        raise StudyValidationError(
            "artifact Study edit_request may not contain transient Study sources"
        )
    if source_kind == "artifact":
        selectors = _canonical_selector_lineage(result)
        expected_roles = {
            role for role, _column in selectors.implicit_ohlcv
        } | {ref.role for ref in source_artifacts}
        by_role = {source.role: source for source in request.input_sources}
        if set(by_role) != expected_roles:
            raise StudyValidationError(
                "artifact Study edit_request lineage does not match result"
            )
        for role, column in selectors.implicit_ohlcv:
            source = by_role[role]
            if source.source_kind != "ohlcv" or source.column_name != column:
                raise StudyValidationError(
                    "artifact Study edit_request OHLCV lineage does not match result"
                )
        for ref in source_artifacts:
            source = by_role[ref.role]
            if (
                source.source_kind != "artifact"
                or source.artifact_id != ref.artifact_id
                or source.output_name != ref.output_name
            ):
                raise StudyValidationError(
                    "artifact Study edit_request artifact lineage does not match result"
                )


class ChartStudyRegistry:
    """Ordered chart-local owner of immutable Studies and resident projections."""

    def __init__(self) -> None:
        self._studies: dict[str, ChartStudy] = {}
        self._projections: dict[str, object] = {}

    def __len__(self) -> int:
        return len(self._studies)

    def snapshot(self) -> tuple[ChartStudy, ...]:
        return tuple(self._studies.values())

    def projection_snapshot(self) -> tuple[object, ...]:
        return tuple(self._projections.values())

    def get(self, study_id: str) -> ChartStudy:
        try:
            return self._studies[study_id]
        except KeyError as exc:
            raise StudyNotFoundError(f"Study not found: {study_id}") from exc

    def get_projection(self, study_id: str) -> object | None:
        if study_id not in self._studies:
            raise StudyNotFoundError(f"Study not found: {study_id}")
        return self._projections.get(study_id)

    def register(self, study: ChartStudy, *, resident: object | None = None) -> object | None:
        if not isinstance(study, ChartStudy):
            raise StudyValidationError("study must be a ChartStudy")
        if study.study_id in self._studies:
            raise StudyValidationError(f"duplicate Study ID: {study.study_id}")
        projection = None
        if resident is not None:
            from leonardo.research.study_projection import project_study

            projection = project_study(study, resident)
        self._studies[study.study_id] = study
        if projection is not None:
            self._projections[study.study_id] = projection
        return projection

    def replace_saved_link(self, study_id: str, saved_link: StudySavedLink) -> ChartStudy:
        study = self.get(study_id)
        if not isinstance(saved_link, StudySavedLink):
            raise StudyValidationError("saved_link must be a StudySavedLink")
        replacement = replace(study, saved_link=saved_link)
        self._studies[study_id] = replacement
        return replacement

    def replace_for_edit(
        self,
        study_id: str,
        replacement: ChartStudy,
        *,
        projection: object | None,
    ) -> ChartStudy:
        current = self.get(study_id)
        if not isinstance(replacement, ChartStudy):
            raise StudyValidationError("replacement must be a ChartStudy")
        if replacement.study_id != current.study_id:
            raise StudyValidationError("edited Study identity must remain unchanged")
        if replacement.result.tool_key != current.result.tool_key:
            raise StudyValidationError("edited Study tool key must remain unchanged")
        if projection is not None and getattr(projection, "study_id", None) != study_id:
            raise StudyValidationError("edited Study projection identity must match")
        self._studies[study_id] = replacement
        if projection is None:
            self._projections.pop(study_id, None)
        else:
            self._projections[study_id] = projection
        return replacement

    def remove(self, study_id: str) -> ChartStudy:
        study = self.get(study_id)
        blockers = tuple(
            candidate.study_id
            for candidate in self._studies.values()
            if any(ref.study_id == study_id for ref in candidate.source_studies)
        )
        if blockers:
            raise StudyDependencyError(
                f"Study {study_id} is required by: {', '.join(blockers)}",
                blockers=blockers,
            )
        self._studies.pop(study_id)
        self._projections.pop(study_id, None)
        return study

    def clear(self) -> int:
        count = len(self._studies)
        self._studies.clear()
        self._projections.clear()
        return count

    def reproject(self, resident: object) -> tuple[object, ...]:
        from leonardo.research.study_projection import project_study

        projections = tuple(project_study(study, resident) for study in self._studies.values())
        self._projections = {projection.study_id: projection for projection in projections}
        return projections
