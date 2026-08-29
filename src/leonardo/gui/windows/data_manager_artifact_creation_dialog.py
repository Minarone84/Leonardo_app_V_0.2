"""Direct managed Artifact creation intent dialog for Data Manager."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
    DataManagerDirectArtifactRequest,
    DataManagerDirectArtifactResult,
    DataManagerDirectArtifactSource,
)
from leonardo.financial_tools import FinancialToolSpec
from leonardo.gui.research.financial_tools_dialog import (
    _StudyEditorDraft,
    _StudyParameterEditor,
)
from leonardo.gui.widgets.study_source_selector_widget import (
    StudySourceSelectorWidget,
)
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.research import (
    StudyArtifactOption,
    StudyExecutionRequest,
    StudySetupCatalog,
    StudyUserMetadata,
)
from leonardo.research.study_setup import RESEARCH_FINANCIAL_TOOL_SPECS


DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID = (
    "data_manager.artifact_creation.window"
)


class DataManagerArtifactCreationDialog(QDialog):
    """Collect one direct managed Artifact creation request."""

    calculate_requested = Signal(object)

    def __init__(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        super().__init__(parent)
        self._catalog = catalog
        self._current_spec: FinancialToolSpec | None = None
        self._editor: _StudyParameterEditor | None = None
        self._tool_drafts: dict[str, _StudyEditorDraft] = {}
        self._busy = False
        self._success_message: str | None = None
        self._restricting_source_kinds = False
        self._dataset_fields: dict[str, QLineEdit] = {}

        self.setObjectName(DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID)
        self.setProperty("object_id", DATA_MANAGER_ARTIFACT_CREATION_WINDOW_ID)
        self.setWindowTitle("Create Artifact")
        self.setModal(False)

        root = QVBoxLayout(self)
        selected_dataset = QGroupBox("Selected Dataset", self)
        selected_dataset.setObjectName(
            "data_manager.artifact_creation.selected_dataset"
        )
        selected_layout = QHBoxLayout(selected_dataset)
        for key, label in (
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("asset", "Asset"),
            ("timeframe", "Timeframe"),
        ):
            field_host = QWidget(selected_dataset)
            field_layout = QVBoxLayout(field_host)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.addWidget(QLabel(label, field_host))
            value = QLineEdit(field_host)
            value.setReadOnly(True)
            value.setObjectName(
                f"data_manager.artifact_creation.dataset.{key}"
            )
            field_layout.addWidget(value)
            selected_layout.addWidget(field_host, 1)
            self._dataset_fields[key] = value
        root.addWidget(selected_dataset)

        self.family_combo = QComboBox(self)
        self.family_combo.setObjectName(
            "data_manager.artifact_creation.family"
        )
        for label, value in (
            ("All", None),
            ("Indicator", "indicator"),
            ("Oscillator", "oscillator"),
            ("Construct", "construct"),
        ):
            self.family_combo.addItem(label, value)
        root.addWidget(self.family_combo)

        self.tool_list = QListWidget(self)
        self.tool_list.setObjectName("data_manager.artifact_creation.tools")
        root.addWidget(self.tool_list, 1)

        self.description_label = QLabel("Select a Financial Tool.", self)
        self.description_label.setObjectName(
            "data_manager.artifact_creation.description"
        )
        self.description_label.setWordWrap(True)
        root.addWidget(self.description_label)

        self._editor_host = QWidget(self)
        self._editor_layout = QVBoxLayout(self._editor_host)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._editor_host, 2)

        self.status_label = QLabel("Select a Financial Tool.", self)
        self.status_label.setObjectName(
            "data_manager.artifact_creation.status"
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.calculate_button = QPushButton("Calculate Artifact", self)
        self.calculate_button.setObjectName(
            "data_manager.artifact_creation.calculate"
        )
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName(
            "data_manager.artifact_creation.close"
        )
        actions.addWidget(self.calculate_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.family_combo.currentIndexChanged.connect(self._family_changed)
        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.calculate_button.clicked.connect(self._calculate)
        self.close_button.clicked.connect(self.close)

        self._set_context()
        self._populate_tools()
        self.calculate_button.setEnabled(False)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=1 / 2,
            height_fraction=2 / 3,
        )

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return {} if self._editor is None else self._editor.parameter_controls

    @property
    def market_id(self):
        return self._catalog.market_id

    @property
    def source_selector(self):
        return None if self._editor is None else self._editor.source_selector

    def set_catalog(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        *,
        preserve_configuration: bool = False,
    ) -> None:
        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        same_market = catalog.market_id == self._catalog.market_id
        selected_key = (
            None if self._current_spec is None else self._current_spec.key
        )
        family = self.family_combo.currentData()
        success_message = self._success_message
        if preserve_configuration and same_market:
            self._capture_current_draft()
        else:
            preserve_configuration = False
            self._success_message = None
            selected_key = None
            family = None
            self._tool_drafts.clear()
        self._catalog = catalog
        self._set_context()
        self._clear_editor()
        family_index = self.family_combo.findData(family)
        self.family_combo.blockSignals(True)
        self.family_combo.setCurrentIndex(max(0, family_index))
        self.family_combo.blockSignals(False)
        self._populate_tools()
        row = next(
            (
                index
                for index in range(self.tool_list.count())
                if self.tool_list.item(index).data(Qt.ItemDataRole.UserRole).key
                == selected_key
            ),
            -1,
        )
        self.tool_list.setCurrentRow(row)
        if preserve_configuration and success_message is not None:
            self._success_message = success_message
            self.status_label.setText(success_message)
        if not preserve_configuration or row < 0:
            self.status_label.setText("Select a Financial Tool.")
            self.calculate_button.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._busy = busy
        self.family_combo.setEnabled(not busy)
        self.tool_list.setEnabled(not busy)
        self._editor_host.setEnabled(not busy)
        if busy:
            self.calculate_button.setEnabled(False)
            if self._success_message is None:
                self.status_label.setText("Creating managed Artifact...")
        else:
            self._validate_request()

    def invalidate_target(self) -> None:
        self._success_message = None
        self._tool_drafts.clear()
        self._clear_editor()
        self.family_combo.blockSignals(True)
        self.family_combo.setCurrentIndex(0)
        self.family_combo.blockSignals(False)
        self._populate_tools()
        self.tool_list.setCurrentRow(-1)
        self._clear_dataset_fields()
        self.status_label.setText("Select an accepted target MarketId.")
        self.calculate_button.setEnabled(False)

    def settle_success(self, result: DataManagerDirectArtifactResult) -> None:
        if not isinstance(result, DataManagerDirectArtifactResult):
            raise TypeError("result must be a DataManagerDirectArtifactResult")
        materialization = result.materialization
        (root_logical_artifact_id,) = materialization.root_logical_artifact_ids
        root_ids = set(materialization.root_logical_artifact_ids)
        root_artifact_ids = {
            item.artifact_id
            for item in materialization.managed_artifacts
            if item.logical_artifact_id in root_ids
        }
        state = (
            "created"
            if root_artifact_ids & set(materialization.created_artifact_ids)
            else "current/reused"
        )
        self._success_message = (
            f"Root Artifact {state}: {root_logical_artifact_id}"
        )
        self.status_label.setText(self._success_message)

    def _set_context(self) -> None:
        market = self._catalog.market_id
        self._dataset_fields["exchange"].setText(market.exchange)
        self._dataset_fields["market_type"].setText(market.market_type)
        self._dataset_fields["asset"].setText(market.symbol)
        self._dataset_fields["timeframe"].setText(market.timeframe)

    def _clear_dataset_fields(self) -> None:
        for field in self._dataset_fields.values():
            field.clear()

    def _family_changed(self) -> None:
        self._success_message = None
        self._capture_current_draft()
        self._clear_editor()
        self._populate_tools()
        self.status_label.setText("Select a Financial Tool.")
        self.calculate_button.setEnabled(False)

    def _populate_tools(self) -> None:
        family = self.family_combo.currentData()
        self.tool_list.blockSignals(True)
        self.tool_list.clear()
        for spec in RESEARCH_FINANCIAL_TOOL_SPECS:
            if family is not None and spec.kind != family:
                continue
            item = QListWidgetItem(spec.title)
            item.setData(Qt.ItemDataRole.UserRole, spec)
            self.tool_list.addItem(item)
        self.tool_list.setCurrentRow(-1)
        self.tool_list.blockSignals(False)

    def _tool_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._success_message = None
        self._capture_current_draft()
        self._clear_editor()
        value = None if current is None else current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, FinancialToolSpec):
            self.description_label.setText("Select a Financial Tool.")
            self.status_label.setText("Select a Financial Tool.")
            self.calculate_button.setEnabled(False)
            return
        self._current_spec = value
        self.description_label.setText(value.description)
        setup_catalog = self._setup_catalog(value)
        self._editor = _StudyParameterEditor(
            setup_catalog,
            value,
            "data_manager.artifact_creation",
            draft=self._tool_drafts.get(value.key),
            validation_changed=self._validate_request,
            parent=self._editor_host,
        )
        self._editor_layout.addWidget(self._editor)
        if (
            value.kind == "construct"
            and isinstance(
                self._editor.source_selector,
                StudySourceSelectorWidget,
            )
        ):
            self._editor.source_selector.intent_changed.connect(
                self._restrict_direct_construct_source_kinds
            )
            self._restrict_direct_construct_source_kinds()
        self._validate_request()

    def _restrict_direct_construct_source_kinds(self) -> None:
        if self._restricting_source_kinds:
            return
        selector = self.source_selector
        if (
            self._current_spec is None
            or self._current_spec.kind != "construct"
            or not isinstance(selector, StudySourceSelectorWidget)
        ):
            return
        self._restricting_source_kinds = True
        try:
            for row in tuple(selector._rows):
                selected_option = row.item.currentData()
                row.kind.blockSignals(True)
                row.kind.clear()
                row.kind.addItem("Saved Artifact", "artifact")
                row.kind.setCurrentIndex(0)
                row.kind.blockSignals(False)
                selector._populate_items(row, emit=False)
                if selected_option is not None:
                    for index in range(row.item.count()):
                        if row.item.itemData(index) == selected_option:
                            row.item.setCurrentIndex(index)
                            break
        finally:
            self._restricting_source_kinds = False

    def _setup_catalog(self, spec: FinancialToolSpec) -> StudySetupCatalog:
        if spec.key == "universal_trend_classifier":
            options = self._catalog.utc_peaks_troughs_options
        elif spec.kind == "construct":
            options = self._catalog.construct_options
        else:
            options = ()
        artifact_options = tuple(
            self._study_artifact_option(option, construct=spec.kind == "construct")
            for option in options
        )
        return StudySetupCatalog(
            market_id=self._catalog.market_id,
            tools=RESEARCH_FINANCIAL_TOOL_SPECS,
            ohlcv_sources=(),
            study_sources=(),
            artifact_options=artifact_options,
        )

    @staticmethod
    def _study_artifact_option(
        option: DataManagerDirectArtifactOption, *, construct: bool
    ) -> StudyArtifactOption:
        return StudyArtifactOption(
            market_id=option.market_id,
            artifact_id=option.artifact_id,
            kind=option.kind,
            tool_key=option.tool_key,
            display_name=option.display_name,
            output_names=option.output_names,
            analysis_usable_output_names=(
                option.output_names if construct else None
            ),
        )

    def _build_request(self) -> DataManagerDirectArtifactRequest:
        if self._current_spec is None or self._editor is None:
            raise ValueError("select a valid Financial Tool")
        transient = self._editor.build_request(
            display_name=self._current_spec.title,
            user_metadata=StudyUserMetadata(),
        )
        if not isinstance(transient, StudyExecutionRequest):
            raise TypeError("editor must build a StudyExecutionRequest")
        available = (
            self._catalog.utc_peaks_troughs_options
            if transient.tool_key == "universal_trend_classifier"
            else self._catalog.construct_options
        )
        sources: list[DataManagerDirectArtifactSource] = []
        for source in transient.input_sources:
            if source.source_kind != "artifact":
                raise ValueError("direct Artifact sources must be saved Artifacts")
            option = next(
                (
                    item
                    for item in available
                    if item.artifact_id == source.artifact_id
                    and item.kind == source.artifact_kind
                    and item.tool_key == source.artifact_tool_key
                    and source.output_name in item.output_names
                ),
                None,
            )
            if option is None or source.output_name is None:
                raise ValueError("selected Artifact source is no longer available")
            sources.append(
                DataManagerDirectArtifactSource(
                    role=source.role,
                    logical_artifact_id=option.logical_artifact_id,
                    artifact_id=option.artifact_id,
                    output_name=source.output_name,
                )
            )
        return DataManagerDirectArtifactRequest(
            market_id=self._catalog.market_id,
            expected_source_ohlcv=self._catalog.source_ohlcv,
            tool_key=transient.tool_key,
            parameters=transient.parameters,
            sources=tuple(sources),
        )

    def _validate_request(self, *_args) -> None:
        if self._busy:
            self.calculate_button.setEnabled(False)
            return
        try:
            self._build_request()
        except (TypeError, ValueError) as exc:
            self.status_label.setText(str(exc))
            self.calculate_button.setEnabled(False)
        else:
            if self._success_message is None:
                self.status_label.setText("Ready")
            self.calculate_button.setEnabled(True)

    def _calculate(self) -> None:
        if self._busy:
            return
        try:
            request = self._build_request()
        except (TypeError, ValueError):
            self._validate_request()
            return
        self._success_message = None
        self.calculate_requested.emit(request)
        self.status_label.setText("Artifact calculation requested.")

    def _capture_current_draft(self) -> None:
        if self._current_spec is not None and self._editor is not None:
            self._tool_drafts[self._current_spec.key] = (
                self._editor._capture_draft()
            )

    def _clear_editor(self) -> None:
        if self._editor is not None:
            self._editor_layout.removeWidget(self._editor)
            self._editor.deleteLater()
        self._editor = None
        self._current_spec = None
