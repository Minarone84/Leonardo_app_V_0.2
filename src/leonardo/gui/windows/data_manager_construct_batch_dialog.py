"""Construct Batch intent and reviewed-preview window for Data Manager."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import DataManagerDatasetEntry
from leonardo.data_manager.construct_batch import (
    SUPPORTED_BATCH_CONSTRUCTS,
    ConstructBatchCombination,
    ConstructBatchExpansionRequest,
    ConstructBatchSignal,
    ConstructBatchSourceScope,
    catalog_signals,
    current_ohlcv_signals,
    project_batch_preview,
)
from leonardo.data_manager.creation_models import BatchArtifactPlan
from leonardo.data_manager.direct_artifact import (
    DataManagerDirectArtifactCatalog,
    DataManagerDirectArtifactOption,
)
from leonardo.financial_tools import get_financial_tool_spec
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    data_manager_dataset_details,
    data_manager_dataset_row,
    resize_data_manager_table,
)
from leonardo.gui.research.financial_tools_dialog import _StudyParameterEditor
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import configure_table
from leonardo.research import StudySetupCatalog
from leonardo.research.study_setup import RESEARCH_FINANCIAL_TOOL_SPECS


DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID = "data_manager.construct_batch.window"
_EXECUTION_REPORT_ID = "data_manager.construct_batch.execution_report"


class _BatchExecutionReportDialog(QDialog):
    """Show one terminal Batch execution result without owning live progress."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName(_EXECUTION_REPORT_ID)
        self.setModal(False)

        layout = QVBoxLayout(self)
        self.summary_label = QLabel("", self)
        self.summary_label.setObjectName(f"{_EXECUTION_REPORT_ID}.summary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.new_label = QLabel("", self)
        self.new_label.setObjectName(f"{_EXECUTION_REPORT_ID}.new")
        layout.addWidget(self.new_label)

        self.reused_label = QLabel("", self)
        self.reused_label.setObjectName(f"{_EXECUTION_REPORT_ID}.reuse_current")
        layout.addWidget(self.reused_label)

        self.details_label = QLabel("", self)
        self.details_label.setObjectName(f"{_EXECUTION_REPORT_ID}.details")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.ok_button = QPushButton("OK", self)
        self.ok_button.setObjectName(f"{_EXECUTION_REPORT_ID}.ok")
        self.ok_button.clicked.connect(self.hide)
        actions.addWidget(self.ok_button)
        layout.addLayout(actions)

    def show_success(
        self, *, total_branches: int, new_branches: int, reused_branches: int
    ) -> None:
        self.setWindowTitle("Batch Execution Complete")
        self.summary_label.setText(
            f"{total_branches} / {total_branches} branches completed successfully"
        )
        self.new_label.setText(f"New: {new_branches}")
        self.reused_label.setText(f"Reuse Current: {reused_branches}")
        self.new_label.show()
        self.reused_label.show()
        self.details_label.clear()
        self.details_label.hide()
        self.show()
        self.raise_()

    def show_failure(self, *, status: str, message: str) -> None:
        cancelled = status == "cancelled"
        self.setWindowTitle(
            "Batch Execution Cancelled" if cancelled else "Batch Execution Failed"
        )
        self.summary_label.setText(
            "The batch operation was cancelled." if cancelled else message
        )
        self.new_label.clear()
        self.reused_label.clear()
        self.new_label.hide()
        self.reused_label.hide()
        self.details_label.setText(
            "Detailed task information remains available in the Data Manager "
            "Operation panel."
        )
        self.details_label.show()
        self.show()
        self.raise_()


class DataManagerConstructBatchDialog(QDialog):
    """Collect one explicit Construct batch rule and show its frozen plan."""

    preview_requested = Signal(object)
    execute_requested = Signal()

    def __init__(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        *,
        collections: tuple[tuple[str, str], ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        super().__init__(parent)
        self._catalog = catalog
        self._artifact_signals = catalog_signals(catalog)
        self._current_ohlcv_signals = current_ohlcv_signals(catalog)
        self._signals = (*self._current_ohlcv_signals, *self._artifact_signals)
        self._collections = tuple(collections)
        self._editor: _StudyParameterEditor | None = None
        self._busy = False
        self._reviewed_plan: BatchArtifactPlan | None = None
        self._execution_report: _BatchExecutionReportDialog | None = None
        self._dataset_fields: dict[str, QTableWidgetItem] = {}
        self._updating_source_checks = False
        self._manual_selected_signal_keys: set[tuple[object, ...]] = set()

        self.setObjectName(DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID)
        self.setProperty("object_id", DATA_MANAGER_CONSTRUCT_BATCH_WINDOW_ID)
        self.setWindowTitle("Batch Constructs")
        self.setModal(False)

        root = QVBoxLayout(self)
        root.addWidget(self._build_dataset_context())

        selectors = QHBoxLayout()
        self.construct_combo = QComboBox(self)
        self.construct_combo.setObjectName("data_manager.construct_batch.construct")
        for key in SUPPORTED_BATCH_CONSTRUCTS:
            self.construct_combo.addItem(get_financial_tool_spec(key).title, key)
        selectors.addWidget(QLabel("Construct", self))
        selectors.addWidget(self.construct_combo, 1)
        self.scope_combo = QComboBox(self)
        self.scope_combo.setObjectName("data_manager.construct_batch.scope")
        for scope in ConstructBatchSourceScope:
            self.scope_combo.addItem(scope.value, scope.value)
        selectors.addWidget(QLabel("Source Scope", self))
        selectors.addWidget(self.scope_combo, 1)
        root.addLayout(selectors)

        self._editor_host = QWidget(self)
        self._editor_layout = QVBoxLayout(self._editor_host)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._editor_host, 1)

        self.source_group = QGroupBox("Source Controls", self)
        source_layout = QVBoxLayout(self.source_group)
        self.selected_signals = QTreeWidget(self.source_group)
        self.selected_signals.setObjectName(
            "data_manager.construct_batch.selected_signals"
        )
        self.selected_signals.setHeaderHidden(True)
        source_layout.addWidget(self.selected_signals)
        self.source_empty = QLabel("", self.source_group)
        self.source_empty.setObjectName("data_manager.construct_batch.source_empty")
        self.source_empty.setWordWrap(True)
        source_layout.addWidget(self.source_empty)

        self.delta_controls = QWidget(self.source_group)
        delta_layout = QHBoxLayout(self.delta_controls)
        delta_layout.setContentsMargins(0, 0, 0, 0)
        self.fixed_signal_combo = QComboBox(self.delta_controls)
        self.fixed_signal_combo.setObjectName(
            "data_manager.construct_batch.delta.fixed_signal"
        )
        self.fixed_role_combo = QComboBox(self.delta_controls)
        self.fixed_role_combo.setObjectName(
            "data_manager.construct_batch.delta.fixed_role"
        )
        self.fixed_role_combo.addItem("fast", "fast")
        self.fixed_role_combo.addItem("slow", "slow")
        delta_layout.addWidget(QLabel("Fixed Signal", self.delta_controls))
        delta_layout.addWidget(self.fixed_signal_combo, 1)
        delta_layout.addWidget(QLabel("Fixed Role", self.delta_controls))
        delta_layout.addWidget(self.fixed_role_combo)
        source_layout.addWidget(self.delta_controls)

        self.combination_table = QTableWidget(0, 3, self.source_group)
        self.combination_table.setObjectName(
            "data_manager.construct_batch.combinations"
        )
        self.combination_table.setHorizontalHeaderLabels(("Fast", "Mid", "Slow"))
        self.combination_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        resize_data_manager_table(self.combination_table)
        source_layout.addWidget(self.combination_table)
        combination_actions = QHBoxLayout()
        self.add_combination_button = QPushButton("Add Combination", self.source_group)
        self.add_combination_button.setObjectName(
            "data_manager.construct_batch.add_combination"
        )
        self.remove_combination_button = QPushButton(
            "Remove Combination", self.source_group
        )
        self.remove_combination_button.setObjectName(
            "data_manager.construct_batch.remove_combination"
        )
        combination_actions.addWidget(self.add_combination_button)
        combination_actions.addWidget(self.remove_combination_button)
        combination_actions.addStretch(1)
        source_layout.addLayout(combination_actions)
        self.recap_group = QGroupBox("Recap", self)
        self.recap_group.setObjectName("data_manager.construct_batch.recap")
        recap_layout = QVBoxLayout(self.recap_group)
        self.preview_table = QTableWidget(0, 5, self.recap_group)
        self.preview_table.setObjectName("data_manager.construct_batch.preview")
        self.preview_table.setHorizontalHeaderLabels(
            ("Source(s)", "Construct", "Parameters", "Inputs", "Result")
        )
        self.preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        resize_data_manager_table(self.preview_table)
        recap_layout.addWidget(self.preview_table)

        self.source_recap_layout = QHBoxLayout()
        self.source_recap_layout.addWidget(self.source_group, 1)
        self.source_recap_layout.addWidget(self.recap_group, 1)
        root.addLayout(self.source_recap_layout, 2)

        destination = QHBoxLayout()
        self.destination_combo = QComboBox(self)
        self.destination_combo.setObjectName(
            "data_manager.construct_batch.destination"
        )
        self.destination_combo.addItem("Individual managed Artifacts", "individual")
        self.destination_combo.addItem("New Artifact Collection", "new_collection")
        self.destination_combo.addItem(
            "Existing Artifact Collection revision", "collection_revision"
        )
        self.collection_combo = QComboBox(self)
        self.collection_combo.setObjectName(
            "data_manager.construct_batch.collection"
        )
        destination.addWidget(QLabel("Destination", self))
        destination.addWidget(self.destination_combo, 1)
        destination.addWidget(self.collection_combo, 1)
        root.addLayout(destination)

        self.status_label = QLabel("Configure a Construct batch and select Preview.", self)
        self.status_label.setObjectName("data_manager.construct_batch.status")
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.preview_button = QPushButton("Preview", self)
        self.preview_button.setObjectName("data_manager.construct_batch.preview_action")
        self.execute_button = QPushButton("Execute", self)
        self.execute_button.setObjectName("data_manager.construct_batch.execute")
        self.close_button = QPushButton("Close", self)
        self.close_button.setObjectName("data_manager.construct_batch.close")
        actions.addWidget(self.preview_button)
        actions.addWidget(self.execute_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.construct_combo.currentIndexChanged.connect(self._construct_changed)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self.selected_signals.itemChanged.connect(self._source_item_changed)
        self.fixed_signal_combo.currentIndexChanged.connect(
            self._configuration_changed
        )
        self.fixed_role_combo.currentIndexChanged.connect(
            self._configuration_changed
        )
        self.destination_combo.currentIndexChanged.connect(
            self._destination_changed
        )
        self.collection_combo.currentIndexChanged.connect(
            self._configuration_changed
        )
        self.add_combination_button.clicked.connect(self._add_combination)
        self.remove_combination_button.clicked.connect(self._remove_combination)
        self.preview_button.clicked.connect(self._preview)
        self.execute_button.clicked.connect(self.execute_requested.emit)
        self.close_button.clicked.connect(self.close)

        self._set_context()
        self._set_collections(self._collections)
        self._populate_signals()
        self._construct_changed()
        self.execute_button.setEnabled(False)
        apply_initial_window_size(
            self, parent=parent, width_fraction=2 / 3, height_fraction=3 / 4
        )

    @property
    def market_id(self):
        return None if self._catalog is None else self._catalog.market_id

    @property
    def parameter_controls(self) -> dict[str, QWidget]:
        return {} if self._editor is None else self._editor.parameter_controls

    @property
    def reviewed_plan(self) -> BatchArtifactPlan | None:
        return self._reviewed_plan

    @property
    def execution_report(self) -> QDialog | None:
        return self._execution_report

    def set_catalog(
        self,
        catalog: DataManagerDirectArtifactCatalog,
        *,
        collections: tuple[tuple[str, str], ...] = (),
        preserve_configuration: bool = False,
    ) -> None:
        if not isinstance(catalog, DataManagerDirectArtifactCatalog):
            raise TypeError("catalog must be a DataManagerDirectArtifactCatalog")
        same_market = (
            self._catalog is not None
            and catalog.market_id == self._catalog.market_id
        )
        same_source = (
            same_market
            and catalog.source_ohlcv == self._catalog.source_ohlcv
        )
        if not preserve_configuration or not same_source:
            self._clear_combinations()
            self._reviewed_plan = None
        self._catalog = catalog
        self._artifact_signals = catalog_signals(catalog)
        self._current_ohlcv_signals = current_ohlcv_signals(catalog)
        self._signals = (*self._current_ohlcv_signals, *self._artifact_signals)
        self._set_context()
        self._set_collections(collections)
        self._populate_signals(
            preserve_checks=preserve_configuration and same_source
        )
        self._populate_fixed_signals()
        if not same_market:
            self._construct_changed()
        self._invalidate_preview()

    def invalidate_target(self) -> None:
        self._catalog = None
        self._artifact_signals = ()
        self._current_ohlcv_signals = ()
        self._signals = ()
        self._clear_dataset_table()
        self._populate_signals(preserve_checks=False)
        self._populate_fixed_signals()
        self._clear_combinations()
        self._invalidate_preview("Select an accepted target MarketId.")
        self.preview_button.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._busy = busy
        for widget in (
            self.construct_combo,
            self.scope_combo,
            self._editor_host,
            self.source_group,
            self.destination_combo,
            self.collection_combo,
            self.preview_button,
        ):
            widget.setEnabled(not busy)
        self.execute_button.setEnabled(
            not busy and self._reviewed_plan is not None
        )

    def set_plan(self, plan: BatchArtifactPlan) -> None:
        rows = project_batch_preview(plan)
        self.preview_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, value in enumerate(
                (
                    row.sources,
                    row.construct,
                    row.parameters,
                    row.inputs,
                    row.result,
                )
            ):
                self.preview_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )
        resize_data_manager_table(self.preview_table)
        self._reviewed_plan = plan
        self.execute_button.setEnabled(not self._busy)
        self.status_label.setText(f"Preview ready: {len(rows)} executable branch(es).")

    def settle_success(
        self, *, total_branches: int, new_branches: int, reused_branches: int
    ) -> None:
        for value, label in (
            (total_branches, "total_branches"),
            (new_branches, "new_branches"),
            (reused_branches, "reused_branches"),
        ):
            if type(value) is not int:
                raise TypeError(f"{label} must be an integer")
        if total_branches < 1:
            raise ValueError("total_branches must be at least 1")
        if new_branches < 0 or reused_branches < 0:
            raise ValueError("branch counts cannot be negative")
        if new_branches + reused_branches != total_branches:
            raise ValueError("new and reused branch counts must equal total branches")
        self._invalidate_preview("Batch execution complete. Generate a new Preview to run again.")
        self._report_dialog().show_success(
            total_branches=total_branches,
            new_branches=new_branches,
            reused_branches=reused_branches,
        )

    def settle_failure(self, status: str, message: str) -> None:
        if not isinstance(status, str) or not status:
            raise ValueError("status must be a non-empty string")
        if not isinstance(message, str) or not message:
            raise ValueError("message must be a non-empty string")
        self._report_dialog().show_failure(status=status, message=message)

    def closeEvent(self, event) -> None:
        if self._execution_report is not None:
            self._execution_report.hide()
        super().closeEvent(event)

    def _report_dialog(self) -> _BatchExecutionReportDialog:
        if self._execution_report is None:
            self._execution_report = _BatchExecutionReportDialog(self)
        return self._execution_report

    def _build_dataset_context(self) -> QWidget:
        group = QGroupBox("Selected Dataset", self)
        layout = QVBoxLayout(group)
        self.dataset_table = configure_table(
            QTableWidget(group),
            object_id="data_manager.construct_batch.dataset_table",
            columns=DATA_MANAGER_DATASET_COLUMNS,
            labels=DATA_MANAGER_DATASET_COLUMNS,
        )
        self.dataset_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.dataset_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.dataset_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.dataset_table.setWordWrap(False)
        self.dataset_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        layout.addWidget(self.dataset_table)
        return group

    def _set_context(self) -> None:
        if self._catalog is None:
            self._clear_dataset_table()
            return
        source = self._catalog.source_ohlcv
        entry = DataManagerDatasetEntry(
            market_id=source.market_id,
            accepted=True,
            row_count=source.row_count,
            first_timestamp_ms=source.first_timestamp_ms,
            last_timestamp_ms=source.last_timestamp_ms,
            persistence_status=source.persistence_status,
            validation_status=source.validation_status,
        )
        details = data_manager_dataset_details(entry)
        blocker = QSignalBlocker(self.dataset_table)
        self.dataset_table.setRowCount(1)
        for column, value in enumerate(data_manager_dataset_row(entry)):
            item = QTableWidgetItem(value)
            item.setToolTip(details)
            self.dataset_table.setItem(0, column, item)
            if column < 4:
                key = ("exchange", "market_type", "asset", "timeframe")[column]
                self._dataset_fields[key] = item
        del blocker
        self._resize_dataset_table()

    def _clear_dataset_table(self) -> None:
        self._dataset_fields.clear()
        self.dataset_table.setRowCount(0)
        self._resize_dataset_table()

    def _resize_dataset_table(self) -> None:
        resize_data_manager_table(self.dataset_table)
        row_height = (
            self.dataset_table.rowHeight(0)
            if self.dataset_table.rowCount()
            else self.dataset_table.verticalHeader().defaultSectionSize()
        )
        self.dataset_table.setFixedHeight(
            self.dataset_table.horizontalHeader().height()
            + row_height
            + self.dataset_table.horizontalScrollBar().sizeHint().height()
            + (self.dataset_table.frameWidth() * 2)
            + 4
        )

    def _set_collections(self, values: tuple[tuple[str, str], ...]) -> None:
        current = self.collection_combo.currentData()
        blocker = QSignalBlocker(self.collection_combo)
        self.collection_combo.clear()
        for collection_id, display_name in values:
            self.collection_combo.addItem(display_name, collection_id)
        index = self.collection_combo.findData(current)
        self.collection_combo.setCurrentIndex(index if index >= 0 else 0)
        del blocker
        self._destination_changed()

    def _construct_changed(self, *_args) -> None:
        if self._editor is not None:
            self._editor_layout.removeWidget(self._editor)
            self._editor.deleteLater()
        key = self.construct_combo.currentData()
        spec = get_financial_tool_spec(key)
        setup_catalog = StudySetupCatalog(
            market_id=self._catalog.market_id,
            tools=RESEARCH_FINANCIAL_TOOL_SPECS,
            ohlcv_sources=(),
            study_sources=(),
            artifact_options=(),
        )
        self._editor = _StudyParameterEditor(
            setup_catalog,
            spec,
            "data_manager.construct_batch",
            validation_changed=self._configuration_changed,
            parent=self._editor_host,
        )
        self._editor.source_selector.hide()
        self._editor_layout.addWidget(self._editor)
        explicit = key in {"trap_area", "braids", "braid_instability"}
        self.delta_controls.setVisible(key == "delta")
        self.combination_table.setVisible(explicit)
        self.add_combination_button.setVisible(explicit)
        self.remove_combination_button.setVisible(explicit)
        self.add_combination_button.setText(
            "Add Combination" if key == "trap_area" else "Add Triple"
        )
        self.remove_combination_button.setText(
            "Remove Combination" if key == "trap_area" else "Remove Triple"
        )
        self._clear_combinations()
        self._configuration_changed()

    def _scope_changed(self, *_args) -> None:
        self._update_source_view()
        self._clear_combinations()
        self._configuration_changed()

    def _destination_changed(self, *_args) -> None:
        self.collection_combo.setVisible(
            self.destination_combo.currentData() == "collection_revision"
        )
        self._configuration_changed()

    def _populate_signals(self, *, preserve_checks: bool = True) -> None:
        checked = (
            set(self._manual_selected_signal_keys) if preserve_checks else set()
        )
        signals = {_signal_key(signal): signal for signal in self._signals}
        checked.intersection_update(signals)
        self._manual_selected_signal_keys = checked
        blocker = QSignalBlocker(self.selected_signals)
        self.selected_signals.clear()
        if self._catalog is not None:
            current_parent = QTreeWidgetItem(("Current Dataset",))
            current_parent.setData(
                0, Qt.ItemDataRole.UserRole, "current_ohlcv"
            )
            current_parent.setFlags(
                current_parent.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            self.selected_signals.addTopLevelItem(current_parent)
            for signal in self._current_ohlcv_signals:
                child = QTreeWidgetItem((signal.label,))
                child.setData(0, Qt.ItemDataRole.UserRole, signal)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if _signal_key(signal) in checked
                    else Qt.CheckState.Unchecked,
                )
                current_parent.addChild(child)
            self._update_parent_check_state(current_parent)
            current_parent.setExpanded(True)
            for option in self._catalog.construct_options:
                option_signals = tuple(
                    signals.get(
                        (
                            "artifact",
                            option.logical_artifact_id,
                            option.artifact_id,
                            output_name,
                        )
                    )
                    for output_name in option.output_names
                )
                option_signals = tuple(
                    signal
                    for signal in option_signals
                    if isinstance(signal, ConstructBatchSignal)
                )
                if not option_signals:
                    continue
                parent = QTreeWidgetItem((option.display_name,))
                parent.setData(0, Qt.ItemDataRole.UserRole, option)
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                self.selected_signals.addTopLevelItem(parent)
                for signal in option_signals:
                    child = QTreeWidgetItem((signal.output_name,))
                    child.setData(0, Qt.ItemDataRole.UserRole, signal)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if _signal_key(signal) in checked
                        else Qt.CheckState.Unchecked,
                    )
                    parent.addChild(child)
                self._update_parent_check_state(parent)
                parent.setExpanded(True)
        del blocker
        self._update_source_view()
        self._populate_fixed_signals()

    def _artifact_items(self) -> tuple[QTreeWidgetItem, ...]:
        return tuple(
            self.selected_signals.topLevelItem(index)
            for index in range(self.selected_signals.topLevelItemCount())
            if isinstance(
                self.selected_signals.topLevelItem(index).data(
                    0, Qt.ItemDataRole.UserRole
                ),
                DataManagerDirectArtifactOption,
            )
        )

    def _source_items(self) -> tuple[QTreeWidgetItem, ...]:
        return tuple(
            self.selected_signals.topLevelItem(index)
            for index in range(self.selected_signals.topLevelItemCount())
        )

    def _signal_items(self) -> tuple[QTreeWidgetItem, ...]:
        return tuple(
            parent.child(index)
            for parent in self._source_items()
            for index in range(parent.childCount())
        )

    def _capture_manual_selected_signal_keys(self) -> None:
        self._manual_selected_signal_keys = {
            key
            for item in self._signal_items()
            if item.checkState(0) == Qt.CheckState.Checked
            if (key := _signal_key(
                item.data(0, Qt.ItemDataRole.UserRole)
            )) is not None
        }

    @staticmethod
    def _update_parent_check_state(parent: QTreeWidgetItem) -> None:
        checked_count = sum(
            parent.child(index).checkState(0) == Qt.CheckState.Checked
            for index in range(parent.childCount())
        )
        if checked_count == 0:
            state = Qt.CheckState.Unchecked
        elif checked_count == parent.childCount():
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        parent.setCheckState(0, state)

    def _source_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if (
            self._updating_source_checks
            or self._current_scope()
            is not ConstructBatchSourceScope.SELECTED_SIGNALS
        ):
            return
        self._updating_source_checks = True
        blocker = QSignalBlocker(self.selected_signals)
        try:
            parent = item.parent()
            if parent is None:
                state = (
                    Qt.CheckState.Checked
                    if item.checkState(0) == Qt.CheckState.Checked
                    else Qt.CheckState.Unchecked
                )
                for index in range(item.childCount()):
                    item.child(index).setCheckState(0, state)
                self._update_parent_check_state(item)
            else:
                self._update_parent_check_state(parent)
        finally:
            del blocker
            self._updating_source_checks = False
        self._capture_manual_selected_signal_keys()
        self._configuration_changed()

    def _update_source_view(self) -> None:
        scope = self._current_scope()
        selected = scope is ConstructBatchSourceScope.SELECTED_SIGNALS
        kind = {
            ConstructBatchSourceScope.ALL_INDICATORS: "indicator",
            ConstructBatchSourceScope.ALL_OSCILLATORS: "oscillator",
            ConstructBatchSourceScope.ALL_CONSTRUCTS: "construct",
        }.get(scope)
        visible_count = 0
        blocker = QSignalBlocker(self.selected_signals)
        for parent in self._source_items():
            current_dataset = (
                parent.data(0, Qt.ItemDataRole.UserRole) == "current_ohlcv"
            )
            visible_children = 0
            for index in range(parent.childCount()):
                child = parent.child(index)
                signal = child.data(0, Qt.ItemDataRole.UserRole)
                visible = selected or (
                    not current_dataset and signal.kind == kind
                )
                child.setHidden(not visible)
                flags = child.flags()
                if selected:
                    child.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if _signal_key(signal)
                        in self._manual_selected_signal_keys
                        else Qt.CheckState.Unchecked,
                    )
                else:
                    child.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setData(0, Qt.ItemDataRole.CheckStateRole, None)
                if visible:
                    visible_children += 1
            parent.setHidden(visible_children == 0)
            flags = parent.flags()
            if selected:
                parent.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                self._update_parent_check_state(parent)
            else:
                parent.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                parent.setData(0, Qt.ItemDataRole.CheckStateRole, None)
            visible_count += visible_children
        del blocker
        self.selected_signals.setVisible(True)
        if self._catalog is None:
            message = "Select an accepted dataset to load eligible saved Artifact signals."
        elif selected and visible_count == 0:
            message = (
                "No current-dataset or saved Artifact signals are available."
            )
        elif visible_count == 0:
            label = {
                ConstructBatchSourceScope.ALL_INDICATORS: "Indicator",
                ConstructBatchSourceScope.ALL_OSCILLATORS: "Oscillator",
                ConstructBatchSourceScope.ALL_CONSTRUCTS: "Construct",
            }[scope]
            message = f"No eligible {label} Artifact signals exist for this dataset."
        else:
            message = ""
        self.source_empty.setText(message)
        self.source_empty.setVisible(bool(message))

    def _populate_fixed_signals(self) -> None:
        current = self.fixed_signal_combo.currentData()
        current_key = _signal_key(current) if isinstance(current, ConstructBatchSignal) else None
        blocker = QSignalBlocker(self.fixed_signal_combo)
        self.fixed_signal_combo.clear()
        for signal in self._signals:
            self.fixed_signal_combo.addItem(signal.label, signal)
        index = next(
            (
                index
                for index in range(self.fixed_signal_combo.count())
                if _signal_key(self.fixed_signal_combo.itemData(index)) == current_key
            ),
            -1,
        )
        self.fixed_signal_combo.setCurrentIndex(index if index >= 0 else 0)
        del blocker

    def _resolved_pool(self) -> tuple[ConstructBatchSignal, ...]:
        scope = self._current_scope()
        if scope is ConstructBatchSourceScope.SELECTED_SIGNALS:
            return tuple(
                item.data(0, Qt.ItemDataRole.UserRole)
                for item in self._signal_items()
                if item.checkState(0) == Qt.CheckState.Checked
            )
        kind = {
            ConstructBatchSourceScope.ALL_INDICATORS: "indicator",
            ConstructBatchSourceScope.ALL_OSCILLATORS: "oscillator",
            ConstructBatchSourceScope.ALL_CONSTRUCTS: "construct",
        }.get(scope)
        return tuple(
            signal for signal in self._artifact_signals if signal.kind == kind
        )

    def _add_combination(self) -> None:
        pool = self._resolved_pool()
        if not pool:
            self.status_label.setText("The resolved source scope is empty.")
            return
        row = self.combination_table.rowCount()
        self.combination_table.insertRow(row)
        key = self.construct_combo.currentData()
        for column in range(3):
            combo = QComboBox(self.combination_table)
            if column == 1 and key == "trap_area":
                combo.addItem("None", None)
            for signal in pool:
                combo.addItem(signal.label, signal)
            combo.currentIndexChanged.connect(self._configuration_changed)
            self.combination_table.setCellWidget(row, column, combo)
        resize_data_manager_table(self.combination_table)
        self._configuration_changed()

    def _remove_combination(self) -> None:
        row = self.combination_table.currentRow()
        if row < 0 and self.combination_table.rowCount():
            row = self.combination_table.rowCount() - 1
        if row >= 0:
            self.combination_table.removeRow(row)
            resize_data_manager_table(self.combination_table)
            self._configuration_changed()

    def _clear_combinations(self) -> None:
        self.combination_table.setRowCount(0)
        resize_data_manager_table(self.combination_table)

    def _parameters(self):
        if self._editor is None:
            raise ValueError("Construct parameters are unavailable")
        return self._editor._capture_draft().parameters

    def _build_expansion_request(self) -> ConstructBatchExpansionRequest:
        if self._catalog is None:
            raise ValueError("Select an accepted target MarketId")
        combinations = []
        for row in range(self.combination_table.rowCount()):
            fast = self.combination_table.cellWidget(row, 0).currentData()
            mid = self.combination_table.cellWidget(row, 1).currentData()
            slow = self.combination_table.cellWidget(row, 2).currentData()
            combinations.append(ConstructBatchCombination(fast, slow, mid))
        destination = self.destination_combo.currentData()
        collection_id = (
            self.collection_combo.currentData()
            if destination == "collection_revision"
            else None
        )
        return ConstructBatchExpansionRequest(
            catalog=self._catalog,
            tool_key=self.construct_combo.currentData(),
            parameters=self._parameters(),
            source_scope=self._current_scope(),
            selected_signals=self._resolved_pool()
            if self._current_scope() is ConstructBatchSourceScope.SELECTED_SIGNALS
            else (),
            fixed_signal=self.fixed_signal_combo.currentData(),
            fixed_role=self.fixed_role_combo.currentData(),
            combinations=tuple(combinations),
            destination=destination,
            collection_id=collection_id,
        )

    def _preview(self) -> None:
        if self._busy:
            return
        try:
            request = self._build_expansion_request()
        except (TypeError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        self.preview_requested.emit(request)
        self.status_label.setText("Batch Preview requested.")

    def _configuration_changed(self, *_args) -> None:
        self._invalidate_preview()

    def _current_scope(self) -> ConstructBatchSourceScope:
        return ConstructBatchSourceScope(self.scope_combo.currentData())

    def _invalidate_preview(self, message: str | None = None) -> None:
        self._reviewed_plan = None
        self.preview_table.setRowCount(0)
        resize_data_manager_table(self.preview_table)
        self.execute_button.setEnabled(False)
        if message is not None:
            self.status_label.setText(message)


def _signal_key(value: object) -> tuple[object, ...] | None:
    if not isinstance(value, ConstructBatchSignal):
        return None
    if value.source_kind == "current_ohlcv":
        return (
            value.source_kind,
            value.market_id,
            value.source_ohlcv,
            value.column,
        )
    return (
        value.source_kind,
        value.logical_artifact_id,
        value.artifact_id,
        value.output_name,
    )
