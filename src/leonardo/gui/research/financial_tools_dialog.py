"""Chart-local Financial Tools intent dialog for the restored Research GUI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from types import MappingProxyType

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.financial_tools import (
    FinancialToolSpec,
    ParameterSpec,
    get_financial_tool_spec,
)
from leonardo.gui.table_sizing import resize_table_columns_to_contents
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.widgets.study_source_selector_widget import (
    StudySourceSelectorWidget,
)
from leonardo.research import (
    StudyArtifactOption,
    StudyArtifactRequest,
    StudyExecutionRequest,
    StudyGuideStyle,
    StudyPresentation,
    StudySetupCatalog,
    StudySetupDraft,
    StudySetupSourceSelection,
    StudySourceOption,
    StudyUserMetadata,
    build_study_request,
    source_role_schema,
)


_SELECTOR_PARAMETERS = {
    "derivative": {"source"},
    "angle": {"source"},
    "delta": {"fast", "slow"},
    "braids": {"fast", "mid", "slow"},
    "braid_instability": {"fast", "mid", "slow"},
    "trap_area": {"fast", "mid", "slow"},
    "dynamic_binning": {"source_columns"},
    "percent_span_angle": {"source_columns"},
    "angle_momentum": {"source_columns"},
    "universal_trend_classifier": {
        "fractal_window",
        "peak_column",
        "trough_column",
    },
}
_UTC_SOURCE_ROLES = (
    "trend_peak",
    "trend_trough",
    "range_peak",
    "range_trough",
)
_UTC_PEAKS_TROUGHS_OUTPUTS = tuple(
    output_name
    for window in (3, 5, 7, 9, 11)
    for output_name in (f"peak_fractal_{window}", f"trough_fractal_{window}")
)


def _float_control_decimals(parameter: ParameterSpec) -> int:
    decimals = 8
    for value in (
        parameter.default,
        parameter.min_value,
        parameter.max_value,
    ):
        if value is None:
            continue
        exponent = Decimal(str(value)).normalize().as_tuple().exponent
        if exponent < 0:
            decimals = max(decimals, -exponent)
    return decimals


def _validate_guide_values(
    spec: FinancialToolSpec,
    guide_values: Mapping[str, float],
) -> Mapping[str, float]:
    if not isinstance(guide_values, Mapping):
        raise TypeError("guide_values must be a mapping")
    visual = spec.oscillator_visual
    expected = (
        ()
        if visual is None
        else tuple(guide.kind for guide in visual.guide_levels)
    )
    if tuple(guide_values) != expected:
        raise ValueError(
            "guide IDs must exactly match the canonical guide order"
        )
    values: dict[str, float] = {}
    for guide_id, value in guide_values.items():
        if not isinstance(guide_id, str) or not guide_id:
            raise ValueError("guide IDs must be non-empty strings")
        if type(value) not in {int, float}:
            raise TypeError("guide values must be numeric")
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("guide values must be finite")
        values[guide_id] = numeric
    if visual is not None and visual.range_mode == "fixed_bounds":
        if any(value < 0.0 or value > 100.0 for value in values.values()):
            raise ValueError("fixed oscillator guides must be within 0 and 100")
    if {"oversold", "center", "overbought"}.issubset(values):
        if not (
            values["oversold"]
            < values["center"]
            < values["overbought"]
        ):
            raise ValueError(
                "oscillator guides require oversold < center < overbought"
            )
    return MappingProxyType(values)


@dataclass(frozen=True, slots=True)
class ResearchStudyApplyIntent:
    request: StudyExecutionRequest
    guide_values: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        spec = get_financial_tool_spec(self.request.tool_key)
        object.__setattr__(
            self,
            "guide_values",
            _validate_guide_values(spec, self.guide_values),
        )


@dataclass(frozen=True, slots=True)
class _StudyEditorDraft:
    parameters: Mapping[str, object]
    source_selections: tuple[StudySetupSourceSelection, ...]
    source_roles: tuple[str, ...]
    guide_values: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a mapping")
        if not isinstance(self.source_selections, tuple) or not all(
            isinstance(item, StudySetupSourceSelection)
            for item in self.source_selections
        ):
            raise TypeError(
                "source_selections must contain StudySetupSourceSelection values"
            )
        if not isinstance(self.source_roles, tuple):
            raise TypeError("source_roles must be a tuple")
        if any(
            not isinstance(role, str)
            or not role
            or role != role.strip()
            for role in self.source_roles
        ):
            raise ValueError("source_roles must contain canonical non-empty text")
        if len(set(self.source_roles)) != len(self.source_roles):
            raise ValueError("source_roles must not contain duplicates")
        if not isinstance(self.guide_values, Mapping):
            raise TypeError("guide_values must be a mapping")
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters))
        )
        object.__setattr__(
            self, "source_selections", tuple(self.source_selections)
        )
        object.__setattr__(self, "source_roles", tuple(self.source_roles))
        object.__setattr__(
            self, "guide_values", MappingProxyType(dict(self.guide_values))
        )


@dataclass(frozen=True, slots=True)
class ResearchSavedArtifactBatchIntent:
    requests: tuple[StudyArtifactRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.requests, tuple) or not self.requests:
            raise ValueError("requests must be a non-empty tuple")
        if not all(
            isinstance(request, StudyArtifactRequest)
            for request in self.requests
        ):
            raise TypeError("requests must contain StudyArtifactRequest values")
        artifact_ids = tuple(request.artifact_id for request in self.requests)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("saved Artifact requests must have unique IDs")


@dataclass(frozen=True, slots=True)
class _UtcPeaksTroughsOwner:
    source_kind: str
    identity: str
    label: str
    options: tuple[StudySourceOption, ...]


def _utc_peaks_troughs_owners(
    catalog: StudySetupCatalog,
) -> tuple[_UtcPeaksTroughsOwner, ...]:
    grouped: dict[tuple[str, str], dict[str, StudySourceOption]] = {}
    labels: dict[tuple[str, str], str] = {}
    for option in catalog.study_sources:
        if (
            option.source_kind != "study"
            or option.family != "indicator"
            or option.study_id is None
            or option.output_name not in _UTC_PEAKS_TROUGHS_OUTPUTS
        ):
            continue
        key = ("study", option.study_id)
        grouped.setdefault(key, {})[option.output_name] = option
        labels.setdefault(key, f"{option.label.split(':', 1)[0]} [{option.study_id}]")
    for artifact in catalog.artifact_options:
        if (
            artifact.kind != "indicator"
            or artifact.tool_key != "peaks_troughs"
            or not set(_UTC_PEAKS_TROUGHS_OUTPUTS).issubset(
                artifact.analysis_usable_output_names
            )
        ):
            continue
        key = ("artifact", artifact.artifact_id)
        options = {
            option.output_name: option
            for option in catalog.source_options
            if option.source_kind == "artifact"
            and option.artifact_id == artifact.artifact_id
            and option.output_name in _UTC_PEAKS_TROUGHS_OUTPUTS
        }
        grouped[key] = options
        labels[key] = f"{artifact.display_name} [{artifact.artifact_id}]"
    required = set(_UTC_PEAKS_TROUGHS_OUTPUTS)
    owners = (
        _UtcPeaksTroughsOwner(
            source_kind=key[0],
            identity=key[1],
            label=labels[key],
            options=tuple(grouped[key][name] for name in _UTC_PEAKS_TROUGHS_OUTPUTS),
        )
        for key in grouped
        if set(grouped[key]) == required
    )
    return tuple(
        sorted(
            owners,
            key=lambda owner: (owner.source_kind, owner.label, owner.identity),
        )
    )


def _utc_selection_owner_key(selection) -> tuple[str, str] | None:
    if selection.source_kind == "study" and selection.study_id is not None:
        return "study", selection.study_id
    if selection.source_kind == "artifact" and selection.artifact_id is not None:
        return "artifact", selection.artifact_id
    return None


class _UtcPeaksTroughsOwnerSelector(QWidget):
    """Select one complete Peaks & Troughs owner for UTC dependencies."""

    intent_changed = Signal()

    def __init__(
        self,
        catalog: StudySetupCatalog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._owners = _utc_peaks_troughs_owners(catalog)
        self._trend_window = 5
        self._range_window = 3
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.owner_combo = QComboBox(self)
        self.owner_combo.setObjectName(
            "research.utc_peaks_troughs_owner_selector.owner"
        )
        if len(self._owners) != 1:
            self.owner_combo.addItem("Select Peaks & Troughs Source", None)
        for owner in self._owners:
            self.owner_combo.addItem(owner.label, owner)
        if len(self._owners) == 1:
            self.owner_combo.setCurrentIndex(0)
        else:
            self.owner_combo.setCurrentIndex(0)
        self.owner_combo.setEnabled(bool(self._owners))
        self.owner_combo.currentIndexChanged.connect(
            lambda _index: self.intent_changed.emit()
        )
        layout.addRow("Peaks & Troughs Source", self.owner_combo)

    @property
    def schema(self) -> tuple[str, ...]:
        return _UTC_SOURCE_ROLES

    @property
    def owner_count(self) -> int:
        return len(self._owners)

    @property
    def selected_owner_key(self) -> tuple[str, str] | None:
        owner = self.owner_combo.currentData()
        if not isinstance(owner, _UtcPeaksTroughsOwner):
            return None
        return owner.source_kind, owner.identity

    def set_windows(self, trend_window: int, range_window: int) -> None:
        self._trend_window = int(trend_window)
        self._range_window = int(range_window)

    def select_owner(self, source_kind: str, identity: str) -> None:
        key = (source_kind, identity)
        for index in range(self.owner_combo.count()):
            owner = self.owner_combo.itemData(index)
            if isinstance(owner, _UtcPeaksTroughsOwner) and (
                owner.source_kind,
                owner.identity,
            ) == key:
                self.owner_combo.setCurrentIndex(index)
                return
        raise ValueError("Peaks & Troughs owner is unavailable")

    def restore(self, request: StudyExecutionRequest) -> None:
        self.restore_selections(
            tuple(
                StudySetupSourceSelection(
                    role=source.role,
                    source_kind=source.source_kind,
                    column_name=source.column_name,
                    study_id=source.study_id,
                    artifact_kind=source.artifact_kind,
                    artifact_tool_key=source.artifact_tool_key,
                    artifact_id=source.artifact_id,
                    output_name=source.output_name,
                )
                for source in request.input_sources
            )
        )

    def restore_selections(
        self, selections: tuple[StudySetupSourceSelection, ...]
    ) -> None:
        if tuple(source.role for source in selections) != _UTC_SOURCE_ROLES:
            raise ValueError("UTC requires four ordered Peaks & Troughs sources")
        keys = {_utc_selection_owner_key(source) for source in selections}
        if None in keys or len(keys) != 1:
            raise ValueError("UTC sources must come from one Peaks & Troughs owner")
        key = next(iter(keys))
        expected_outputs = self._output_names()
        if tuple(source.output_name for source in selections) != expected_outputs:
            raise ValueError("UTC source outputs do not match the selected fractal windows")
        self.select_owner(*key)

    def selections(self) -> tuple[StudySetupSourceSelection, ...]:
        owner = self.owner_combo.currentData()
        if not isinstance(owner, _UtcPeaksTroughsOwner):
            if not self._owners:
                raise ValueError(
                    "UTC requires a compatible Peaks & Troughs Study or Artifact."
                )
            raise ValueError("Select a Peaks & Troughs Source for UTC.")
        options = {option.output_name: option for option in owner.options}
        return tuple(
            StudySetupSourceSelection(
                role=role,
                source_kind=option.source_kind,
                column_name=option.column_name,
                study_id=option.study_id,
                artifact_kind=option.artifact_kind,
                artifact_tool_key=option.artifact_tool_key,
                artifact_id=option.artifact_id,
                output_name=option.output_name,
            )
            for role, output_name in zip(
                _UTC_SOURCE_ROLES, self._output_names(), strict=True
            )
            for option in (options[output_name],)
        )

    def _output_names(self) -> tuple[str, ...]:
        return (
            f"peak_fractal_{self._trend_window}",
            f"trough_fractal_{self._trend_window}",
            f"peak_fractal_{self._range_window}",
            f"trough_fractal_{self._range_window}",
        )


class _StudyParameterEditor(QWidget):
    """Own the shared calculation, source, and guide editing surface."""

    def __init__(
        self,
        catalog: StudySetupCatalog,
        spec: FinancialToolSpec,
        object_name_prefix: str,
        *,
        request: StudyExecutionRequest | None = None,
        current_guide_values: Mapping[str, float] | None = None,
        draft: _StudyEditorDraft | None = None,
        validation_changed=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be a StudySetupCatalog")
        if not isinstance(spec, FinancialToolSpec):
            raise TypeError("spec must be a FinancialToolSpec")
        if not isinstance(object_name_prefix, str) or not object_name_prefix:
            raise ValueError("object_name_prefix must be non-empty text")
        if request is not None and (
            not isinstance(request, StudyExecutionRequest)
            or request.tool_key != spec.key
        ):
            raise ValueError("request must match the fixed Financial Tool")
        if draft is not None and not isinstance(draft, _StudyEditorDraft):
            raise TypeError("draft must be a _StudyEditorDraft or None")
        if request is not None and draft is not None:
            raise ValueError("request and draft cannot both be supplied")
        if validation_changed is not None and not callable(validation_changed):
            raise TypeError("validation_changed must be callable or None")

        self._catalog = catalog
        self._spec = spec
        self._validation_changed = validation_changed
        self._initializing = True
        self._parameter_controls: dict[str, QWidget] = {}
        self._guide_controls: dict[str, QDoubleSpinBox] = {}
        self.setObjectName(f"{object_name_prefix}.editor")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        parameter_scroll = QScrollArea(self)
        parameter_scroll.setWidgetResizable(True)
        self.parameter_host = QWidget(parameter_scroll)
        self.parameter_host.setObjectName(f"{object_name_prefix}.parameters")
        self.parameter_form = QFormLayout(self.parameter_host)
        parameter_scroll.setWidget(self.parameter_host)
        root.addWidget(parameter_scroll, 1)

        for parameter in _visible_parameters(spec):
            control = _parameter_control(
                parameter,
                self.parameter_host,
                self._changed,
                f"{object_name_prefix}.parameter",
            )
            self._parameter_controls[parameter.name] = control
            self.parameter_form.addRow(
                parameter.label or parameter.name,
                control,
            )
            if request is not None and parameter.name in request.parameters:
                _set_control_value(control, request.parameters[parameter.name])
            elif draft is not None and parameter.name in draft.parameters:
                _set_control_value(control, draft.parameters[parameter.name])

        if spec.key == "universal_trend_classifier":
            self.source_selector = _UtcPeaksTroughsOwnerSelector(
                catalog, parent=self
            )
            self.source_selector.set_windows(
                self._utc_window("trend_fractal_window"),
                self._utc_window("range_fractal_window"),
            )
        else:
            self.source_selector = StudySourceSelectorWidget(catalog, parent=self)
            self.source_selector.set_schema(source_role_schema(spec.key))
        self.source_selector.setObjectName(f"{object_name_prefix}.sources")
        self.source_selector.intent_changed.connect(self._changed)
        root.addWidget(self.source_selector)
        if request is not None:
            if isinstance(
                self.source_selector, _UtcPeaksTroughsOwnerSelector
            ):
                self.source_selector.restore(request)
            else:
                _restore_sources(self.source_selector, catalog, request)
        elif draft is not None:
            if isinstance(
                self.source_selector, _UtcPeaksTroughsOwnerSelector
            ):
                if draft.source_selections:
                    try:
                        self.source_selector.restore_selections(
                            draft.source_selections
                        )
                    except ValueError:
                        pass
            else:
                _restore_source_role_layout(
                    self.source_selector,
                    draft.source_roles,
                )
                if draft.source_selections:
                    _restore_source_selections(
                        self.source_selector,
                        catalog,
                        draft.source_selections,
                        require_available=False,
                    )

        visual = spec.oscillator_visual
        guide_specs = () if visual is None else visual.guide_levels
        default_values = {
            guide.kind: guide.value for guide in guide_specs
        }
        values = _validate_guide_values(
            spec,
            default_values
            if current_guide_values is None
            else current_guide_values,
        )
        if guide_specs:
            guide_group = QGroupBox("Oscillator Thresholds", self)
            guide_group.setObjectName(f"{object_name_prefix}.thresholds")
            guide_form = QFormLayout(guide_group)
            fixed_bounds = visual.range_mode == "fixed_bounds"
            for guide in guide_specs:
                control = QDoubleSpinBox(guide_group)
                control.setObjectName(
                    f"{object_name_prefix}.guide.{guide.kind}"
                )
                control.setDecimals(8)
                if fixed_bounds:
                    control.setRange(0.0, 100.0)
                else:
                    control.setRange(-1e12, 1e12)
                control.setValue(values[guide.kind])
                control.valueChanged.connect(self._changed)
                self._guide_controls[guide.kind] = control
                guide_form.addRow(
                    guide.label or _guide_label(guide.kind),
                    control,
                )
            if draft is not None:
                for guide_id, value in draft.guide_values.items():
                    control = self._guide_controls.get(guide_id)
                    if control is not None:
                        control.setValue(float(value))
            root.addWidget(guide_group)
        self._initializing = False

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return dict(self._parameter_controls)

    @property
    def guide_controls(self) -> dict[str, QDoubleSpinBox]:
        return dict(self._guide_controls)

    def build_request(
        self,
        *,
        display_name: str,
        user_metadata: StudyUserMetadata,
    ) -> StudyExecutionRequest:
        draft = StudySetupDraft(
            mode="calculation",
            tool_key=self._spec.key,
            parameters={
                name: _control_value(control)
                for name, control in self._parameter_controls.items()
            },
            sources=self.source_selector.selections(),
            display_name=display_name,
            user_metadata=user_metadata,
        )
        request = build_study_request(draft, self._catalog)
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("calculation request must be StudyExecutionRequest")
        return request

    def guide_values(self) -> Mapping[str, float]:
        return _validate_guide_values(
            self._spec,
            {
                guide_id: control.value()
                for guide_id, control in self._guide_controls.items()
            },
        )

    def _capture_draft(self) -> _StudyEditorDraft:
        try:
            selections = self.source_selector.selections()
        except ValueError:
            selections = ()
        if isinstance(self.source_selector, StudySourceSelectorWidget):
            source_roles = tuple(
                row.role for row in self.source_selector._rows
            )
        else:
            source_roles = tuple(selection.role for selection in selections)
        return _StudyEditorDraft(
            parameters={
                name: _control_value(control)
                for name, control in self._parameter_controls.items()
            },
            source_selections=selections,
            source_roles=source_roles,
            guide_values={
                guide_id: control.value()
                for guide_id, control in self._guide_controls.items()
            },
        )

    def _changed(self, *_args) -> None:
        if hasattr(self, "source_selector") and isinstance(
            self.source_selector, _UtcPeaksTroughsOwnerSelector
        ):
            self.source_selector.set_windows(
                self._utc_window("trend_fractal_window"),
                self._utc_window("range_fractal_window"),
            )
        elif hasattr(self, "source_selector") and isinstance(
            self.source_selector, StudySourceSelectorWidget
        ):
            roles = tuple(row.role for row in self.source_selector._rows)
            if (
                self.source_selector.schema == ("fast", "mid?", "slow")
                and roles == ("fast", "slow", "mid")
            ):
                _restore_source_role_layout(
                    self.source_selector,
                    ("fast", "mid", "slow"),
                )
        if not self._initializing and self._validation_changed is not None:
            self._validation_changed()

    def _utc_window(self, name: str) -> int:
        return int(_control_value(self._parameter_controls[name]))


class ResearchFinancialToolsDialog(QDialog):
    """Collect one canonical Financial Tool or saved Artifact intent."""

    apply_requested = Signal(object)
    save_requested = Signal(object)
    edit_requested = Signal(str, object)
    apply_saved_artifact_requested = Signal(object)

    def __init__(
        self,
        market_id: MarketId,
        catalog: StudySetupCatalog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be a StudySetupCatalog")
        if catalog.market_id != market_id:
            raise ValueError("catalog MarketId must match market_id")

        self._market_id = market_id
        self._catalog = catalog
        self._current_spec: FinancialToolSpec | None = None
        self._editor: _StudyParameterEditor | None = None
        self._parameter_controls: dict[str, QWidget] = {}
        self._guide_controls: dict[str, QDoubleSpinBox] = {}
        self.source_selector: (
            StudySourceSelectorWidget | _UtcPeaksTroughsOwnerSelector | None
        ) = None
        self._busy = False
        self._mode = "ordinary"
        self._edit_study_id: str | None = None
        self._edit_template: StudyExecutionRequest | None = None
        self._tool_drafts: dict[str, _StudyEditorDraft] = {}
        self._ordinary_family: str | None = None
        self._ordinary_tool_key: str | None = None
        self._checked_artifact_ids: set[str] = set()
        self._idle_status_message = ""

        self.setObjectName("research_restoration.financial_tools")
        self.setWindowTitle(
            f"Financial Tools — {market_id.symbol} · {market_id.timeframe}"
        )
        self.setModal(False)

        root = QVBoxLayout(self)
        self.context_label = QLabel(_context_text(market_id), self)
        self.context_label.setObjectName(
            "research_restoration.financial_tools.context"
        )
        root.addWidget(self.context_label)

        body = QHBoxLayout()
        root.addLayout(body, 1)
        left = QVBoxLayout()
        right = QVBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)

        self.family_combo = QComboBox(self)
        self.family_combo.setObjectName(
            "research_restoration.financial_tools.family"
        )
        for label, value in (
            ("All", None),
            ("Indicator", "indicator"),
            ("Oscillator", "oscillator"),
            ("Construct", "construct"),
        ):
            self.family_combo.addItem(label, value)
        left.addWidget(self.family_combo)

        self.tool_list = QListWidget(self)
        self.tool_list.setObjectName("research_restoration.financial_tools.tools")
        left.addWidget(self.tool_list, 1)

        self.description_label = QLabel("Select a Financial Tool.", self)
        self.description_label.setObjectName(
            "research_restoration.financial_tools.description"
        )
        self.description_label.setWordWrap(True)
        left.addWidget(self.description_label)

        self._editor_host = QWidget(self)
        self._editor_layout = QVBoxLayout(self._editor_host)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self._editor_host, 1)

        self.status_label = QLabel("Select a Financial Tool.", self)
        self.status_label.setObjectName(
            "research_restoration.financial_tools.status"
        )
        self.status_label.setWordWrap(True)
        left.addWidget(self.status_label)

        calculation_actions = QHBoxLayout()
        calculation_actions.addStretch(1)
        self.apply_button = QPushButton("Apply", self)
        self.apply_button.setObjectName(
            "research_restoration.financial_tools.apply"
        )
        calculation_actions.addWidget(self.apply_button)
        self.save_button = QPushButton("Save", self)
        self.save_button.setObjectName(
            "research_restoration.financial_tools.save"
        )
        calculation_actions.addWidget(self.save_button)
        left.addLayout(calculation_actions)

        saved_group = QGroupBox("Saved Artifacts", self)
        saved_layout = QVBoxLayout(saved_group)
        self.saved_artifact_table = QTableWidget(0, 4, saved_group)
        self.saved_artifact_table.setObjectName(
            "research_restoration.financial_tools.saved_artifacts"
        )
        self.saved_artifact_table.setHorizontalHeaderLabels(
            ("Apply", "Artifact", "Parameters", "Outputs")
        )
        self.saved_artifact_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.saved_artifact_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.saved_artifact_table.setSortingEnabled(False)
        self.saved_artifact_table.verticalHeader().setVisible(False)
        self.saved_artifact_table.horizontalHeader().setVisible(True)
        self.saved_artifact_table.setWordWrap(False)
        saved_layout.addWidget(self.saved_artifact_table, 1)
        self.apply_saved_artifact_button = QPushButton(
            "Apply Checked Artifacts", saved_group
        )
        self.apply_saved_artifact_button.setObjectName(
            "research_restoration.financial_tools.apply_saved_artifact"
        )
        saved_layout.addWidget(self.apply_saved_artifact_button)
        right.addWidget(saved_group, 1)

        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "research_restoration.financial_tools.close"
        )
        right.addWidget(self.close_button)

        self.family_combo.currentIndexChanged.connect(self._family_changed)
        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.saved_artifact_table.itemChanged.connect(
            self._saved_artifact_check_changed
        )
        self.apply_button.clicked.connect(self._request_apply)
        self.save_button.clicked.connect(self._request_save)
        self.apply_saved_artifact_button.clicked.connect(
            self._request_apply_saved_artifact
        )
        self.close_button.clicked.connect(self.close)

        self._populate_tools()
        self._populate_saved_artifacts()
        self._set_calculation_actions_enabled(False)
        self.apply_saved_artifact_button.setEnabled(False)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=1 / 2,
            height_fraction=2 / 3,
        )

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return dict(self._parameter_controls)

    @property
    def guide_controls(self) -> dict[str, QDoubleSpinBox]:
        return dict(self._guide_controls)

    def set_catalog(self, catalog: StudySetupCatalog) -> None:
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be a StudySetupCatalog")
        if catalog.market_id != self._market_id:
            raise ValueError("catalog MarketId must match the dialog MarketId")
        self._capture_current_draft()
        family = self._ordinary_family
        selected_key = self._ordinary_tool_key
        self._catalog = catalog
        available_artifact_ids = {
            option.artifact_id for option in catalog.artifact_options
        }
        self._checked_artifact_ids.intersection_update(
            available_artifact_ids
        )
        if self._mode == "ordinary":
            self._restore_ordinary_state(family, selected_key)
        else:
            self._populate_saved_artifacts()

    def prepare_for_open(self) -> None:
        self._capture_current_draft()
        self._mode = "ordinary"
        self._edit_study_id = None
        self._edit_template = None
        self.family_combo.setEnabled(True)
        self.tool_list.setEnabled(True)
        self.saved_artifact_table.setEnabled(True)
        self.apply_button.setText("Apply")
        self.save_button.setVisible(True)
        self._restore_ordinary_state(
            self._ordinary_family, self._ordinary_tool_key
        )

    def prepare_for_edit(
        self, study_id: str, request: StudyExecutionRequest
    ) -> None:
        if not isinstance(study_id, str) or not study_id.strip():
            raise ValueError("study_id must be a non-empty string")
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        self.prepare_for_open()
        self._mode = "edit"
        self._edit_study_id = study_id
        self._edit_template = request
        spec = next(
            (item for item in self._catalog.tools if item.key == request.tool_key),
            None,
        )
        if spec is None:
            raise ValueError(f"Financial Tool is not available: {request.tool_key}")
        family_index = self.family_combo.findData(spec.kind)
        if family_index < 0:
            raise ValueError(f"Financial Tool family is not available: {spec.kind}")
        self.family_combo.setCurrentIndex(family_index)
        tool_row = next(
            (
                row
                for row in range(self.tool_list.count())
                if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole).key
                == request.tool_key
            ),
            -1,
        )
        if tool_row < 0:
            raise ValueError(f"Financial Tool is not available: {request.tool_key}")
        self.tool_list.setCurrentRow(tool_row)
        rebuilt = self._build_calculation_request()
        if (
            rebuilt.tool_key != request.tool_key
            or dict(rebuilt.parameters) != dict(request.parameters)
            or rebuilt.input_sources != request.input_sources
        ):
            raise ValueError("Edit form does not reproduce the canonical Study request")
        self.family_combo.setEnabled(False)
        self.tool_list.setEnabled(False)
        self.saved_artifact_table.setEnabled(False)
        self.apply_saved_artifact_button.setEnabled(False)
        self.save_button.setVisible(False)
        self.save_button.setEnabled(False)
        self.apply_button.setText("Apply Edit")
        self.status_label.setText(f"Ready to edit {request.display_name}.")

    def set_busy(self, busy: bool, message: str = "") -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._busy = busy
        self.saved_artifact_table.setEnabled(
            not busy and self._mode == "ordinary"
        )
        if busy:
            self.apply_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.apply_saved_artifact_button.setEnabled(False)
            self.status_label.setText(message or "Working...")
            return
        if message:
            self._idle_status_message = message
        self._validate_request(_preserve_idle_message=True)
        self._update_saved_artifact_action()
        if self._idle_status_message:
            self.status_label.setText(self._idle_status_message)

    def _family_changed(self) -> None:
        self._idle_status_message = ""
        self._capture_current_draft()
        if self._mode == "ordinary":
            self._ordinary_family = self.family_combo.currentData()
            self._ordinary_tool_key = None
        self._current_spec = None
        self._clear_parameter_form()
        self.description_label.setText("Select a Financial Tool.")
        self.status_label.setText("Select a Financial Tool.")
        self._set_calculation_actions_enabled(False)
        self._populate_tools()
        self._populate_saved_artifacts()

    def _populate_tools(self) -> None:
        family = self.family_combo.currentData()
        self.tool_list.blockSignals(True)
        self.tool_list.clear()
        for spec in self._catalog.tools:
            if family is not None and spec.kind != family:
                continue
            item = QListWidgetItem(spec.title)
            item.setData(Qt.ItemDataRole.UserRole, spec)
            self.tool_list.addItem(item)
        self.tool_list.setCurrentRow(-1)
        self.tool_list.blockSignals(False)

    def _tool_changed(self, current: QListWidgetItem | None, _previous) -> None:
        self._capture_current_draft()
        value = None if current is None else current.data(Qt.ItemDataRole.UserRole)
        self._current_spec = value if isinstance(value, FinancialToolSpec) else None
        if self._mode == "ordinary":
            self._ordinary_tool_key = (
                None if self._current_spec is None else self._current_spec.key
            )
        self._clear_parameter_form()
        if self._current_spec is None:
            self.description_label.setText("Select a Financial Tool.")
            self.status_label.setText("Select a Financial Tool.")
            self._set_calculation_actions_enabled(False)
        else:
            self.description_label.setText(self._current_spec.description)
            request = (
                self._edit_template
                if (
                    self._edit_template is not None
                    and self._edit_template.tool_key == self._current_spec.key
                )
                else None
            )
            self._editor = _StudyParameterEditor(
                self._catalog,
                self._current_spec,
                "research_restoration.financial_tools",
                request=request,
                draft=(
                    None
                    if request is not None
                    else self._tool_drafts.get(self._current_spec.key)
                ),
                validation_changed=self._validate_request,
                parent=self._editor_host,
            )
            self._editor_layout.addWidget(self._editor)
            self.parameter_host = self._editor.parameter_host
            self._parameter_form = self._editor.parameter_form
            self._parameter_controls = self._editor.parameter_controls
            self._guide_controls = self._editor.guide_controls
            self.source_selector = self._editor.source_selector
            self._validate_request()
        self._populate_saved_artifacts()

    def _build_calculation_request(self) -> StudyExecutionRequest:
        if self._current_spec is None or self._editor is None:
            raise ValueError("select a valid Financial Tool")
        return self._editor.build_request(
            display_name=(
                self._current_spec.title
                if self._edit_template is None
                else self._edit_template.display_name
            ),
            user_metadata=(
                StudyUserMetadata()
                if self._edit_template is None
                else self._edit_template.user_metadata
            ),
        )

    def _build_apply_intent(self) -> ResearchStudyApplyIntent:
        if self._editor is None:
            raise ValueError("select a valid Financial Tool")
        return ResearchStudyApplyIntent(
            self._build_calculation_request(),
            self._editor.guide_values(),
        )

    def _validate_request(
        self, *_args, _preserve_idle_message: bool = False
    ) -> None:
        if not _preserve_idle_message:
            self._idle_status_message = ""
        if self._current_spec is None:
            self.status_label.setText("Select a Financial Tool.")
            self._set_calculation_actions_enabled(False)
            return
        try:
            self._build_apply_intent()
        except (TypeError, ValueError) as error:
            self.status_label.setText(str(error))
            self._set_calculation_actions_enabled(False)
        else:
            self.status_label.setText("Ready")
            self._set_calculation_actions_enabled(True)

    def _set_calculation_actions_enabled(self, enabled: bool) -> None:
        self.apply_button.setEnabled(enabled and not self._busy)
        self.save_button.setEnabled(
            enabled
            and not self._busy
            and self._mode == "ordinary"
        )

    def _request_apply(self) -> None:
        if self._busy:
            return
        try:
            intent = self._build_apply_intent()
        except (TypeError, ValueError):
            self._validate_request()
            return
        if self._mode == "edit":
            if self._edit_study_id is None:
                raise RuntimeError("Edit target Study is missing")
            self.edit_requested.emit(self._edit_study_id, intent.request)
            self.status_label.setText("Edit requested.")
        else:
            self.apply_requested.emit(intent)
            self.status_label.setText("Apply requested.")

    def _request_save(self) -> None:
        if self._busy or self._mode != "ordinary":
            return
        try:
            intent = self._build_apply_intent()
        except (TypeError, ValueError):
            self._validate_request()
            return
        self.save_requested.emit(intent)
        self.status_label.setText("Save requested.")

    def _populate_saved_artifacts(self) -> None:
        family = self.family_combo.currentData()
        selected_key = (
            None if self._current_spec is None else self._current_spec.key
        )
        self.saved_artifact_table.blockSignals(True)
        self.saved_artifact_table.setRowCount(0)
        for option in self._catalog.artifact_options:
            if family is not None and option.kind != family:
                continue
            if selected_key is not None and option.tool_key != selected_key:
                continue
            row = self.saved_artifact_table.rowCount()
            self.saved_artifact_table.insertRow(row)
            parameter_entries = _artifact_parameter_entries(option)
            full_parameters = _joined_or_none(parameter_entries, "; ")
            full_outputs = _joined_or_none(option.output_names, ", ")
            tooltip = (
                f"Artifact: {option.display_name}\n"
                f"Artifact ID: {option.artifact_id}\n"
                f"Tool: {option.tool_key}\n"
                f"Kind: {option.kind}\n"
                f"Parameters: {full_parameters}\n"
                f"Outputs: {full_outputs}"
            )
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            check_item.setCheckState(
                Qt.CheckState.Checked
                if option.artifact_id in self._checked_artifact_ids
                else Qt.CheckState.Unchecked
            )
            check_item.setData(Qt.ItemDataRole.UserRole, option)
            check_item.setToolTip(tooltip)
            self.saved_artifact_table.setItem(row, 0, check_item)
            values = (
                option.display_name,
                _compact_entries(parameter_entries, 4, "; "),
                _compact_entries(option.output_names, 3, ", "),
            )
            for column, text in enumerate(values, start=1):
                item = QTableWidgetItem(text)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                )
                item.setToolTip(tooltip)
                self.saved_artifact_table.setItem(row, column, item)
        self.saved_artifact_table.blockSignals(False)
        resize_table_columns_to_contents(self.saved_artifact_table)
        self._update_saved_artifact_action()

    def _saved_artifact_check_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        option = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(option, StudyArtifactOption):
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_artifact_ids.add(option.artifact_id)
        else:
            self._checked_artifact_ids.discard(option.artifact_id)
        self._update_saved_artifact_action()

    def _visible_checked_artifact_options(
        self,
    ) -> tuple[StudyArtifactOption, ...]:
        values: list[StudyArtifactOption] = []
        for row in range(self.saved_artifact_table.rowCount()):
            item = self.saved_artifact_table.item(row, 0)
            option = None if item is None else item.data(
                Qt.ItemDataRole.UserRole
            )
            if (
                isinstance(option, StudyArtifactOption)
                and item.checkState() == Qt.CheckState.Checked
            ):
                values.append(option)
        return tuple(values)

    def _update_saved_artifact_action(self) -> None:
        self.apply_saved_artifact_button.setEnabled(
            self._mode == "ordinary"
            and not self._busy
            and bool(self._visible_checked_artifact_options())
        )

    def _request_apply_saved_artifact(self) -> None:
        if self._busy:
            return
        options = self._visible_checked_artifact_options()
        if not options:
            self.apply_saved_artifact_button.setEnabled(False)
            return
        requests = tuple(
            self._build_saved_artifact_request(option)
            for option in options
        )
        self.apply_saved_artifact_requested.emit(
            ResearchSavedArtifactBatchIntent(requests)
        )
        self.status_label.setText("Saved Artifact batch requested.")

    def settle_saved_artifact_success(self, artifact_id: str) -> None:
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact_id must be non-empty text")
        self._checked_artifact_ids.discard(artifact_id)
        for row in range(self.saved_artifact_table.rowCount()):
            item = self.saved_artifact_table.item(row, 0)
            option = None if item is None else item.data(
                Qt.ItemDataRole.UserRole
            )
            if (
                isinstance(option, StudyArtifactOption)
                and option.artifact_id == artifact_id
            ):
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_saved_artifact_action()

    def _build_saved_artifact_request(
        self, option: StudyArtifactOption
    ) -> StudyArtifactRequest:
        request = build_study_request(
            StudySetupDraft(
                mode="artifact",
                tool_key=option.tool_key,
                artifact_id=option.artifact_id,
                display_name=option.display_name,
                user_metadata=StudyUserMetadata(),
            ),
            self._catalog,
        )
        if not isinstance(request, StudyArtifactRequest):
            raise TypeError("artifact request must be StudyArtifactRequest")
        return request

    def _capture_current_draft(self) -> None:
        if (
            self._mode == "ordinary"
            and self._current_spec is not None
            and self._editor is not None
        ):
            self._tool_drafts[self._current_spec.key] = (
                self._editor._capture_draft()
            )

    def _restore_ordinary_state(
        self, family: str | None, selected_key: str | None
    ) -> None:
        family_index = self.family_combo.findData(family)
        if family_index < 0:
            family_index = 0
            family = None
        self._ordinary_family = family
        self.family_combo.blockSignals(True)
        self.family_combo.setCurrentIndex(family_index)
        self.family_combo.blockSignals(False)
        self._current_spec = None
        self._clear_parameter_form()
        self._populate_tools()
        tool_row = next(
            (
                row
                for row in range(self.tool_list.count())
                if self.tool_list.item(row).data(
                    Qt.ItemDataRole.UserRole
                ).key == selected_key
            ),
            -1,
        )
        self.tool_list.setCurrentRow(tool_row)
        if tool_row < 0:
            self._ordinary_tool_key = None
            self.description_label.setText("Select a Financial Tool.")
            self.status_label.setText("Select a Financial Tool.")
            self._set_calculation_actions_enabled(False)
            self._populate_saved_artifacts()


    def _clear_parameter_form(self) -> None:
        if self._editor is not None:
            self._editor_layout.removeWidget(self._editor)
            self._editor.deleteLater()
        self._editor = None
        self._parameter_controls.clear()
        self._guide_controls.clear()
        self.source_selector = None


@dataclass(frozen=True, slots=True)
class ResearchStudyEditIntent:
    study_id: str
    request: StudyExecutionRequest
    guide_values: Mapping[str, float]
    calculation_changed: bool
    guide_changed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.study_id, str) or not self.study_id.strip():
            raise ValueError("study_id must be a non-empty string")
        if not isinstance(self.request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        values = _validate_guide_values(
            get_financial_tool_spec(self.request.tool_key),
            self.guide_values,
        )
        if type(self.calculation_changed) is not bool:
            raise TypeError("calculation_changed must be a boolean")
        if type(self.guide_changed) is not bool:
            raise TypeError("guide_changed must be a boolean")
        if not self.calculation_changed and not self.guide_changed:
            raise ValueError("edit intent must contain a change")
        object.__setattr__(self, "guide_values", values)


class ResearchStudyEditDialog(QDialog):
    """Edit one fixed Study's calculation intent and oscillator guides."""

    edit_requested = Signal(object)

    def __init__(
        self,
        market_id: MarketId,
        catalog: StudySetupCatalog,
        study_id: str,
        request: StudyExecutionRequest,
        presentation: StudyPresentation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId")
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be a StudySetupCatalog")
        if catalog.market_id != market_id:
            raise ValueError("catalog MarketId must match market_id")
        if not isinstance(study_id, str) or not study_id.strip():
            raise ValueError("study_id must be a non-empty string")
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        if not isinstance(presentation, StudyPresentation):
            raise TypeError("presentation must be a StudyPresentation")
        if presentation.study_id != study_id:
            raise ValueError("presentation Study ID must match study_id")
        if presentation.tool_key != request.tool_key:
            raise ValueError("presentation tool key must match request")
        spec = next(
            (item for item in catalog.tools if item.key == request.tool_key),
            None,
        )
        if spec is None:
            raise ValueError(
                f"Financial Tool is not available: {request.tool_key}"
            )

        self._market_id = market_id
        self._catalog = catalog
        self._study_id = study_id
        self._spec = spec
        self._baseline_request = request
        self._presentation = presentation
        self._baseline_guide_values = tuple(
            (guide.guide_id, guide.value)
            for guide in presentation.guide_styles.values()
        )
        self._busy = False

        self.setObjectName(
            f"research_restoration.study_edit.{study_id}"
        )
        self.setWindowTitle(f"Edit Study - {request.display_name}")
        self.setModal(False)
        root = QVBoxLayout(self)

        self.context_label = QLabel(_context_text(market_id), self)
        self.context_label.setObjectName(
            "research_restoration.study_edit.context"
        )
        root.addWidget(self.context_label)
        self.tool_title_label = QLabel(spec.title, self)
        self.tool_title_label.setObjectName(
            "research_restoration.study_edit.tool_title"
        )
        root.addWidget(self.tool_title_label)
        self.description_label = QLabel(spec.description, self)
        self.description_label.setObjectName(
            "research_restoration.study_edit.description"
        )
        self.description_label.setWordWrap(True)
        root.addWidget(self.description_label)

        self.status_label = QLabel("No changes.", self)
        self.status_label.setObjectName(
            "research_restoration.study_edit.status"
        )
        self.status_label.setWordWrap(True)
        current_guides = MappingProxyType(
            {
                guide.guide_id: guide.value
                for guide in presentation.guide_styles.values()
            }
        )
        self._editor = _StudyParameterEditor(
            catalog,
            spec,
            "research_restoration.study_edit",
            request=request,
            current_guide_values=current_guides,
            validation_changed=self._validate_edit,
            parent=self,
        )
        root.addWidget(self._editor, 1)
        self.parameter_host = self._editor.parameter_host
        self._parameter_form = self._editor.parameter_form
        self.source_selector = self._editor.source_selector
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.apply_edit_button = QPushButton("Apply Edit", self)
        self.apply_edit_button.setObjectName(
            "research_restoration.study_edit.apply"
        )
        self.apply_edit_button.setEnabled(False)
        actions.addWidget(self.apply_edit_button)
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "research_restoration.study_edit.close"
        )
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        self.apply_edit_button.clicked.connect(self._request_edit)
        self.close_button.clicked.connect(self.close)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=1 / 2,
            height_fraction=1 / 2,
        )
        self._validate_edit()

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return self._editor.parameter_controls

    @property
    def guide_controls(self) -> dict[str, QDoubleSpinBox]:
        return self._editor.guide_controls

    def set_busy(self, busy: bool, message: str = "") -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._busy = busy
        if busy:
            self.apply_edit_button.setEnabled(False)
            self.status_label.setText(message or "Working...")
        else:
            self._validate_edit()

    def set_operation_failure(self, message: str) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("message must be non-empty text")
        self._busy = False
        self.apply_edit_button.setEnabled(False)
        self.status_label.setText(f"Operation failure: {message}")

    def accept_applied_state(
        self,
        request: StudyExecutionRequest,
        presentation: StudyPresentation,
    ) -> None:
        if not isinstance(request, StudyExecutionRequest):
            raise TypeError("request must be a StudyExecutionRequest")
        if not isinstance(presentation, StudyPresentation):
            raise TypeError("presentation must be a StudyPresentation")
        self._baseline_request = request
        self._presentation = presentation
        self._baseline_guide_values = tuple(
            (guide.guide_id, guide.value)
            for guide in presentation.guide_styles.values()
        )
        self._busy = False
        self._validate_edit()

    def _build_request(self) -> StudyExecutionRequest:
        return self._editor.build_request(
            display_name=self._baseline_request.display_name,
            user_metadata=self._baseline_request.user_metadata,
        )

    def _guide_values(self) -> Mapping[str, float]:
        return self._editor.guide_values()

    def _validated_state(
        self,
    ) -> tuple[
        StudyExecutionRequest,
        Mapping[str, float],
        bool,
        bool,
    ]:
        request = self._build_request()
        values = self._guide_values()
        calculation_changed = (
            request.tool_key != self._baseline_request.tool_key
            or dict(request.parameters)
            != dict(self._baseline_request.parameters)
            or request.input_sources
            != self._baseline_request.input_sources
        )
        guide_changed = tuple(values.items()) != self._baseline_guide_values
        return request, values, calculation_changed, guide_changed

    def _validate_edit(self, *_args) -> None:
        if not hasattr(self, "_editor"):
            return
        try:
            _, _, calculation_changed, guide_changed = (
                self._validated_state()
            )
        except (TypeError, ValueError) as error:
            self.status_label.setText(f"Invalid input: {error}")
            self.apply_edit_button.setEnabled(False)
            return
        if not calculation_changed and not guide_changed:
            self.status_label.setText("No changes.")
            self.apply_edit_button.setEnabled(False)
            return
        self.status_label.setText("Ready to apply edit.")
        self.apply_edit_button.setEnabled(not self._busy)

    def _request_edit(self) -> None:
        if self._busy:
            return
        try:
            request, values, calculation_changed, guide_changed = (
                self._validated_state()
            )
            intent = ResearchStudyEditIntent(
                self._study_id,
                request,
                values,
                calculation_changed,
                guide_changed,
            )
        except (TypeError, ValueError):
            self._validate_edit()
            return
        self.edit_requested.emit(intent)
        self.apply_edit_button.setEnabled(False)
        self.status_label.setText("Edit submitted.")


def _context_text(market_id: MarketId) -> str:
    exchange = market_id.exchange[:1].upper() + market_id.exchange[1:]
    return (
        "Historical Chart: "
        f"{exchange}_{market_id.market_type}_{market_id.symbol}_{market_id.timeframe}"
    )


def _artifact_parameter_entries(
    option: StudyArtifactOption,
) -> tuple[str, ...]:
    return tuple(
        f"{name}={_format_artifact_value(value)}"
        for name, value in option.parameters.items()
    ) + tuple(
        f"{role}={value}" for role, value in option.source_bindings
    )


def _format_artifact_value(value: object) -> str:
    if value is None:
        return "none"
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return str(value)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return "[" + ", ".join(_format_artifact_value(item) for item in value) + "]"
    return str(value)


def _joined_or_none(values: Sequence[str], separator: str) -> str:
    return separator.join(values) if values else "none"


def _compact_entries(
    values: Sequence[str],
    limit: int,
    separator: str,
) -> str:
    snapshot = tuple(values)
    if not snapshot:
        return "none"
    visible = separator.join(snapshot[:limit])
    omitted = len(snapshot) - limit
    if omitted > 0:
        return f"{visible}{separator}... (+{omitted})"
    return visible


def _visible_parameters(spec: FinancialToolSpec) -> tuple[ParameterSpec, ...]:
    owned = _SELECTOR_PARAMETERS.get(spec.key, set())
    return tuple(
        parameter for parameter in spec.parameters if parameter.name not in owned
    )


def _parameter_control(
    parameter: ParameterSpec,
    parent: QWidget,
    changed,
    object_name_prefix: str,
) -> QWidget:
    if parameter.choices:
        control = QComboBox(parent)
        for choice in parameter.choices:
            control.addItem(str(choice), choice)
        control.setCurrentIndex(max(0, control.findData(parameter.default)))
        control.currentIndexChanged.connect(changed)
    elif parameter.dtype == "int":
        control = QSpinBox(parent)
        control.setRange(
            int(
                parameter.min_value
                if parameter.min_value is not None
                else -2147483647
            ),
            int(
                parameter.max_value
                if parameter.max_value is not None
                else 2147483647
            ),
        )
        control.setValue(int(parameter.default or 0))
        control.valueChanged.connect(changed)
    elif parameter.dtype == "float":
        control = QDoubleSpinBox(parent)
        control.setDecimals(_float_control_decimals(parameter))
        control.setRange(
            float(
                parameter.min_value
                if parameter.min_value is not None
                else -1e12
            ),
            float(
                parameter.max_value
                if parameter.max_value is not None
                else 1e12
            ),
        )
        control.setValue(float(parameter.default or 0.0))
        control.valueChanged.connect(changed)
    elif parameter.dtype == "bool":
        control = QCheckBox(parent)
        control.setChecked(bool(parameter.default))
        control.toggled.connect(changed)
    else:
        control = QLineEdit(parent)
        control.setText(
            "" if parameter.default is None else str(parameter.default)
        )
        control.textChanged.connect(changed)
    control.setObjectName(f"{object_name_prefix}.{parameter.name}")
    if parameter.description:
        control.setToolTip(parameter.description)
    return control


def _restore_sources(
    selector: StudySourceSelectorWidget,
    catalog: StudySetupCatalog,
    request: StudyExecutionRequest,
) -> None:
    selections = tuple(
        StudySetupSourceSelection(
            role=source.role,
            source_kind=source.source_kind,
            column_name=source.column_name,
            study_id=source.study_id,
            artifact_kind=source.artifact_kind,
            artifact_tool_key=source.artifact_tool_key,
            artifact_id=source.artifact_id,
            output_name=source.output_name,
        )
        for source in request.input_sources
    )
    _restore_source_selections(
        selector,
        catalog,
        selections,
        require_available=True,
    )


def _restore_source_selections(
    selector: StudySourceSelectorWidget,
    catalog: StudySetupCatalog,
    selections: tuple[StudySetupSourceSelection, ...],
    *,
    require_available: bool,
) -> None:
    for selection in selections:
        option = next(
            (
                item
                for item in catalog.source_options
                if item.source_kind == selection.source_kind
                and item.column_name == selection.column_name
                and item.study_id == selection.study_id
                and item.artifact_kind == selection.artifact_kind
                and item.artifact_tool_key == selection.artifact_tool_key
                and item.artifact_id == selection.artifact_id
                and item.output_name == selection.output_name
            ),
            None,
        )
        if option is None:
            if require_available:
                raise ValueError(
                    f"Required source is not available for role {selection.role}"
                )
            _ensure_source_role(selector, selection.role, len(selections))
            continue
        restored = False
        for _attempt in range(len(selections) + 1):
            try:
                selector.select_option(selection.role, option)
            except KeyError:
                selector._add.click()
            else:
                restored = True
                break
        if not restored:
            raise ValueError(
                f"Required source role cannot be restored: {selection.role}"
            )


def _restore_source_role_layout(
    selector: StudySourceSelectorWidget,
    source_roles: tuple[str, ...],
) -> None:
    schema = selector.schema
    if schema == ("source_1", "..."):
        expected = tuple(
            f"source_{index}" for index in range(1, len(source_roles) + 1)
        )
        if not source_roles or source_roles != expected:
            raise ValueError("invalid dynamic source role layout")
        while len(selector._rows) < len(source_roles):
            selector._add.click()
    elif schema == ("fast", "mid?", "slow"):
        if source_roles not in (
            ("fast", "slow"),
            ("fast", "mid", "slow"),
        ):
            raise ValueError("invalid fast/mid/slow source role layout")
        if source_roles == ("fast", "mid", "slow") and not any(
            row.role == "mid" for row in selector._rows
        ):
            selector._add.click()
        current_roles = tuple(row.role for row in selector._rows)
        if current_roles == ("fast", "slow", "mid"):
            mid = selector._rows.pop()
            selector._rows.insert(1, mid)
            selector._layout.removeWidget(mid.container)
            selector._layout.insertWidget(1, mid.container)
    elif schema == ("peak+trough?",):
        if source_roles not in ((), ("peak", "trough")):
            raise ValueError("invalid peak/trough source role layout")
        if source_roles and not selector._rows:
            selector._add.click()
    else:
        canonical_roles = tuple(
            role.removesuffix("?")
            for role in schema
            if not role.endswith("?")
        )
        if source_roles != canonical_roles:
            raise ValueError("invalid fixed source role layout")

    if tuple(row.role for row in selector._rows) != source_roles:
        raise ValueError("source role layout could not be restored")


def _ensure_source_role(
    selector: StudySourceSelectorWidget,
    role: str,
    limit: int,
) -> None:
    for _attempt in range(limit + 1):
        if any(row.role == role for row in selector._rows):
            return
        selector._add.click()


def _guide_label(kind: str) -> str:
    return {
        "oversold": "Oversold",
        "center": "Center",
        "overbought": "Overbought",
        "zero": "Zero",
    }[kind]


def _control_value(control: QWidget):
    if isinstance(control, QComboBox):
        return control.currentData()
    if isinstance(control, QSpinBox):
        return control.value()
    if isinstance(control, QDoubleSpinBox):
        return control.value()
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QLineEdit):
        return control.text()
    raise TypeError("unsupported parameter control")


def _set_control_value(control: QWidget, value: object) -> None:
    if isinstance(control, QComboBox):
        index = control.findData(value)
        if index < 0:
            raise ValueError(f"parameter choice is not available: {value!r}")
        control.setCurrentIndex(index)
    elif isinstance(control, QSpinBox):
        if type(value) is not int:
            raise ValueError("integer parameter value is invalid")
        control.setValue(value)
    elif isinstance(control, QDoubleSpinBox):
        if type(value) not in {int, float}:
            raise ValueError("floating parameter value is invalid")
        control.setValue(float(value))
    elif isinstance(control, QCheckBox):
        if type(value) is not bool:
            raise ValueError("boolean parameter value is invalid")
        control.setChecked(value)
    elif isinstance(control, QLineEdit):
        if not isinstance(value, str):
            raise ValueError("text parameter value is invalid")
        control.setText(value)
    else:
        raise TypeError("unsupported parameter control")
