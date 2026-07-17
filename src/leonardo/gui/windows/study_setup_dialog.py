"""GUI-only Financial Tool Study Setup form."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from leonardo.financial_tools import FinancialToolSpec, ParameterSpec
from leonardo.gui.widgets.study_source_selector_widget import StudySourceSelectorWidget
from leonardo.research import (
    STUDY_DATASET_ROLES,
    StudyArtifactOption,
    StudySetupCatalog,
    StudySetupCatalogRejection,
    StudySetupDraft,
    StudyUserMetadata,
    build_study_request,
    source_role_schema,
)


class StudySetupDialog(QDialog):
    """Build one existing Task 1017 request from immutable catalog truth."""

    request_submitted = Signal(object)

    def __init__(
        self,
        catalog: StudySetupCatalog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be StudySetupCatalog")
        self.setObjectName("research.study_setup_dialog")
        self.setWindowTitle("Add Study")
        self._catalog = catalog
        self._request = None
        self._parameter_controls: dict[str, QWidget] = {}

        self._mode = QComboBox(self)
        self._mode.setObjectName("research.study_setup_dialog.combo.mode")
        self._mode.addItem("Calculate Financial Tool", "calculation")
        self._mode.addItem("Apply Saved Artifact", "artifact")
        self._family = QComboBox(self)
        self._family.setObjectName("research.study_setup_dialog.combo.family")
        for label, value in (
            ("All", None),
            ("Indicator", "indicator"),
            ("Oscillator", "oscillator"),
            ("Construct", "construct"),
        ):
            self._family.addItem(label, value)
        self._tools = QListWidget(self)
        self._tools.setObjectName("research.study_setup_dialog.list.tools")
        self._description = QLabel(self)
        self._description.setObjectName("research.study_setup_dialog.label.description")
        self._description.setWordWrap(True)
        self._display_name = QLineEdit(self)
        self._display_name.setObjectName("research.study_setup_dialog.edit.display_name")
        self._parameter_host = QWidget(self)
        self._parameter_host.setObjectName("research.study_setup_dialog.form.parameters")
        self._parameter_form = QFormLayout(self._parameter_host)
        self._sources = StudySourceSelectorWidget(catalog, parent=self)
        self._sources.setObjectName("research.study_setup_dialog.sources")
        self._important = QCheckBox("Important", self)
        self._important.setObjectName("research.study_setup_dialog.check.important")
        self._dataset_role = QComboBox(self)
        self._dataset_role.setObjectName("research.study_setup_dialog.combo.dataset_role")
        for role in STUDY_DATASET_ROLES:
            self._dataset_role.addItem(role.replace("_", " ").title(), role)
        self._metadata_description = QLineEdit(self)
        self._metadata_description.setObjectName(
            "research.study_setup_dialog.edit.metadata_description"
        )
        self._validation = QLabel(self)
        self._validation.setObjectName("research.study_setup_dialog.label.validation")
        self._validation.setWordWrap(True)
        self._apply = QPushButton("Apply", self)
        self._apply.setObjectName("research.study_setup_dialog.button.apply")
        self._cancel = QPushButton("Cancel", self)
        self._cancel.setObjectName("research.study_setup_dialog.button.cancel")

        selectors = QHBoxLayout()
        selectors.addWidget(self._mode)
        selectors.addWidget(self._family)
        metadata = QFormLayout()
        metadata.addRow("Display name", self._display_name)
        metadata.addRow("Dataset role", self._dataset_role)
        metadata.addRow("Description", self._metadata_description)
        metadata.addRow("", self._important)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._apply)
        buttons.addWidget(self._cancel)
        layout = QVBoxLayout(self)
        layout.addLayout(selectors)
        layout.addWidget(self._tools)
        layout.addWidget(self._description)
        layout.addWidget(self._parameter_host)
        layout.addWidget(self._sources)
        layout.addLayout(metadata)
        layout.addWidget(self._validation)
        layout.addLayout(buttons)

        self._mode.currentIndexChanged.connect(self._refresh_tools)
        self._family.currentIndexChanged.connect(self._refresh_tools)
        self._tools.currentItemChanged.connect(self._selection_changed)
        self._display_name.textChanged.connect(self._validate)
        self._important.toggled.connect(self._validate)
        self._dataset_role.currentIndexChanged.connect(self._validate)
        self._metadata_description.textChanged.connect(self._validate)
        self._sources.intent_changed.connect(self._validate)
        self._apply.clicked.connect(self._accept_request)
        self._cancel.clicked.connect(self.reject)
        self._refresh_tools()

    @property
    def result_request(self):
        return self._request

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return dict(self._parameter_controls)

    def current_request(self):
        return self._build_request()

    def _refresh_tools(self) -> None:
        family = self._family.currentData()
        mode = self._mode.currentData()
        self._tools.clear()
        if mode == "calculation":
            for spec in self._catalog.tools:
                if family is not None and spec.kind != family:
                    continue
                item = QListWidgetItem(spec.title)
                item.setData(Qt.ItemDataRole.UserRole, spec)
                self._tools.addItem(item)
        else:
            for option in self._catalog.artifact_options:
                if family is not None and option.kind != family:
                    continue
                item = QListWidgetItem(option.display_name)
                item.setData(Qt.ItemDataRole.UserRole, option)
                self._tools.addItem(item)
            for rejection in self._catalog.artifact_rejections:
                if family is not None and rejection.kind != family:
                    continue
                item = QListWidgetItem(
                    f"{rejection.tool_key}: {rejection.artifact_id} - {rejection.reason}"
                )
                item.setData(Qt.ItemDataRole.UserRole, rejection)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                self._tools.addItem(item)
        if self._tools.count():
            self._tools.setCurrentRow(0)
        else:
            self._selection_changed(None, None)

    def _selection_changed(self, current, _previous) -> None:
        self._clear_parameter_form()
        value = None if current is None else current.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, FinancialToolSpec):
            self._description.setText(value.description)
            self._display_name.setText(value.title)
            for parameter in _visible_parameters(value):
                control = self._parameter_control(parameter)
                self._parameter_controls[parameter.name] = control
                self._parameter_form.addRow(parameter.label or parameter.name, control)
            self._sources.set_schema(source_role_schema(value.key))
        elif isinstance(value, StudyArtifactOption):
            self._description.setText(
                f"Saved {value.kind}: {value.tool_key} ({', '.join(value.output_names)})"
            )
            self._display_name.setText(value.display_name)
            self._sources.set_schema(())
        elif isinstance(value, StudySetupCatalogRejection):
            self._description.setText(value.reason)
            self._display_name.clear()
            self._sources.set_schema(())
        else:
            self._description.clear()
            self._display_name.clear()
            self._sources.set_schema(())
        self._validate()

    def _parameter_control(self, parameter: ParameterSpec) -> QWidget:
        if parameter.choices:
            control = QComboBox(self._parameter_host)
            for choice in parameter.choices:
                control.addItem(str(choice), choice)
            control.setCurrentIndex(max(0, control.findData(parameter.default)))
            control.currentIndexChanged.connect(self._validate)
        elif parameter.dtype == "int":
            control = QSpinBox(self._parameter_host)
            control.setRange(
                int(parameter.min_value if parameter.min_value is not None else -2147483647),
                int(parameter.max_value if parameter.max_value is not None else 2147483647),
            )
            control.setValue(int(parameter.default or 0))
            control.valueChanged.connect(self._validate)
        elif parameter.dtype == "float":
            control = QDoubleSpinBox(self._parameter_host)
            control.setDecimals(8)
            control.setRange(
                float(parameter.min_value if parameter.min_value is not None else -1e12),
                float(parameter.max_value if parameter.max_value is not None else 1e12),
            )
            control.setValue(float(parameter.default or 0.0))
            control.valueChanged.connect(self._validate)
        elif parameter.dtype == "bool":
            control = QCheckBox(self._parameter_host)
            control.setChecked(bool(parameter.default))
            control.toggled.connect(self._validate)
        else:
            control = QLineEdit(self._parameter_host)
            control.setText("" if parameter.default is None else str(parameter.default))
            control.textChanged.connect(self._validate)
        control.setObjectName(f"research.study_setup_dialog.parameter.{parameter.name}")
        if parameter.description:
            control.setToolTip(parameter.description)
        return control

    def _build_request(self):
        item = self._tools.currentItem()
        value = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        metadata = StudyUserMetadata(
            important=self._important.isChecked(),
            dataset_role=self._dataset_role.currentData(),
            description=self._metadata_description.text(),
        )
        if isinstance(value, FinancialToolSpec):
            draft = StudySetupDraft(
                mode="calculation",
                tool_key=value.key,
                parameters={
                    name: _control_value(control)
                    for name, control in self._parameter_controls.items()
                },
                sources=self._sources.selections(),
                display_name=self._display_name.text(),
                user_metadata=metadata,
            )
        elif isinstance(value, StudyArtifactOption):
            draft = StudySetupDraft(
                mode="artifact",
                tool_key=value.tool_key,
                artifact_id=value.artifact_id,
                display_name=self._display_name.text(),
                user_metadata=metadata,
            )
        else:
            raise ValueError("select a valid Financial Tool or saved artifact")
        return build_study_request(draft, self._catalog)

    def _validate(self, *_args) -> None:
        try:
            self._build_request()
        except (TypeError, ValueError) as error:
            self._validation.setText(str(error))
            self._apply.setEnabled(False)
        else:
            self._validation.setText("Ready")
            self._apply.setEnabled(True)

    def _accept_request(self) -> None:
        try:
            request = self._build_request()
        except (TypeError, ValueError):
            self._validate()
            return
        self._request = request
        self.request_submitted.emit(request)
        self.accept()

    def _clear_parameter_form(self) -> None:
        while self._parameter_form.rowCount():
            self._parameter_form.removeRow(0)
        self._parameter_controls.clear()


def _visible_parameters(spec: FinancialToolSpec) -> tuple[ParameterSpec, ...]:
    owned = {
        "derivative": {"source"},
        "angle": {"source"},
        "delta": {"fast", "slow"},
        "braids": {"fast", "mid", "slow"},
        "braid_instability": {"fast", "mid", "slow"},
        "trap_area": {"fast", "mid", "slow"},
        "dynamic_binning": {"source_columns"},
        "percent_span_angle": {"source_columns"},
        "angle_momentum": {"source_columns"},
        "universal_trend_classifier": {"peak_column", "trough_column"},
    }.get(spec.key, set())
    return tuple(item for item in spec.parameters if item.name not in owned)


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
