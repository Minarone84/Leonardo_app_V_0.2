"""Variation interaction and presentation; execution belongs to its presenter."""
from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from leonardo.financial_tools.variation_models import BinningPolicy
from leonardo.financial_tools.directional_variation_models import DirectionalBinningPolicy
from leonardo.gui.analysis.database_presentation import display_catalog
from leonardo.gui.analysis.binning_results import BinningResults
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


@dataclass(frozen=True)
class DatabaseColumnDisplayEntry:
    """Disposable injected column metadata, bound to exactly one database ID."""
    database_id: str
    name: str
    unit: str = ""
    definition: str = ""
    numeric: bool = True


class BinningSettingsEditor(QWidget):
    changed = Signal()

    def __init__(self, object_id: str, parent=None) -> None:
        super().__init__(parent)
        apply_identity(self, object_id, object_type="widget")
        policy = BinningPolicy()
        directional_policy = DirectionalBinningPolicy()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.measurement = QComboBox(self)
        self.measurement.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.measurement.setMinimumContentsLength(18)
        self.measurement.addItem("Directional intensity", "directional_intensity")
        self.measurement.addItem("Signed value (full reference)", "value")
        self.measurement.addItem("Absolute magnitude (full reference)", "magnitude")
        apply_identity(self.measurement, object_id + ".measurement", object_type="combo_box")
        self.measurement.setToolTip("Directional intensity compares each sign with its own history. Full-reference modes combine both signs. The supplied column is analyzed without calculating a change or derivative.")
        form.addRow("Measurement", self.measurement)
        self.minimum_count = QSpinBox(self)
        self.minimum_count.setRange(1, 2_147_483_647)
        self.minimum_count.setValue(policy.min_reference_count)
        apply_identity(self.minimum_count, object_id + ".minimum_count", object_type="spin_box")
        self.count_label = QLabel(self)
        self.count_label.setWordWrap(True)
        form.addRow(self.count_label, self.minimum_count)
        layout.addLayout(form)
        self.directional_controls = QWidget(self)
        directional_form = QFormLayout(self.directional_controls)
        directional_form.setContentsMargins(0, 0, 0, 0)
        directional_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.positive_bins = QSpinBox(self.directional_controls)
        self.negative_bins = QSpinBox(self.directional_controls)
        for name, control, title in (("positive_bins", self.positive_bins, "Positive bins"),
                                     ("negative_bins", self.negative_bins, "Negative bins")):
            control.setRange(1, 1000)
            control.setValue(getattr(directional_policy, name))
            apply_identity(control, object_id + "." + name, object_type="spin_box")
            control.setToolTip("Equally spaced percentile bins within this direction; ties may leave bins empty.")
            directional_form.addRow(title, control)
            control.valueChanged.connect(lambda _value: self.changed.emit())
        help_text = QLabel("Each sign uses its own history; symmetry around zero is never forced. "
                           "Positive-only and negative-only columns are supported. An absent sign remains uncalibrated. "
                           "Zero and missing values have no directional bin. Bin count and rarity are separate.", self.directional_controls)
        help_text.setWordWrap(True)
        directional_form.addRow(help_text)
        layout.addWidget(self.directional_controls)
        self.legacy_controls = QWidget(self)
        legacy_layout = QVBoxLayout(self.legacy_controls)
        legacy_layout.setContentsMargins(0, 0, 0, 0)
        boundary_label = QLabel("Six percentile boundaries define seven bands:", self.legacy_controls)
        boundary_label.setWordWrap(True)
        legacy_layout.addWidget(boundary_label)
        boundaries = QGridLayout()
        self.cutoffs = []
        band_edges = ("Very Low / Low", "Low / Below Typical", "Below Typical / Typical",
                      "Typical / Above Typical", "Above Typical / High", "High / Very High")
        for index, value in enumerate(policy.cutoffs):
            control = QDoubleSpinBox(self.legacy_controls)
            control.setDecimals(4)
            control.setRange(0.0001, 99.9999)
            control.setSingleStep(1)
            control.setValue(value)
            control.setSuffix(" %")
            apply_identity(control, f"{object_id}.cutoff.{index + 1}", object_type="spin_box")
            edge_label = QLabel(band_edges[index], self.legacy_controls)
            edge_label.setWordWrap(True)
            boundaries.addWidget(edge_label, index // 2 * 2, index % 2)
            boundaries.addWidget(control, index // 2 * 2 + 1, index % 2)
            self.cutoffs.append(control)
            control.valueChanged.connect(lambda _value: self.changed.emit())
        legacy_layout.addLayout(boundaries)
        layout.addWidget(self.legacy_controls)
        layout.addStretch(1)
        self.measurement.currentIndexChanged.connect(self._mode_changed)
        self.minimum_count.valueChanged.connect(lambda _value: self.changed.emit())
        self._sync_mode()

    def _sync_mode(self) -> None:
        directional = self.measurement.currentData() == "directional_intensity"
        self.directional_controls.setVisible(directional)
        self.legacy_controls.setVisible(not directional)
        self.count_label.setText("Minimum observations per populated direction" if directional else "Minimum reference observations")

    def _mode_changed(self, *_args) -> None:
        self._sync_mode()
        self.changed.emit()

    def values(self) -> dict:
        values = {"measurement": self.measurement.currentData(), "min_reference_count": self.minimum_count.value()}
        if values["measurement"] == "directional_intensity":
            values.update(positive_bins=self.positive_bins.value(), negative_bins=self.negative_bins.value())
        else:
            values["cutoffs"] = tuple(control.value() for control in self.cutoffs)
        return values

    def set_values(self, values: dict) -> None:
        index = self.measurement.findData(values["measurement"])
        if index < 0:
            raise ValueError("unknown binning measurement")
        blockers = [QSignalBlocker(control) for control in (self.measurement, self.minimum_count, self.positive_bins, self.negative_bins, *self.cutoffs)]
        self.measurement.setCurrentIndex(index)
        self.minimum_count.setValue(values["min_reference_count"])
        if values["measurement"] == "directional_intensity":
            self.positive_bins.setValue(values["positive_bins"])
            self.negative_bins.setValue(values["negative_bins"])
        else:
            for control, value in zip(self.cutoffs, values["cutoffs"], strict=True):
                control.setValue(value)
        del blockers
        self._sync_mode()

class ColumnOverrideEditor(QWidget):
    changed = Signal()

    def __init__(self, database_id: str, name: str, defaults: BinningSettingsEditor, parent=None) -> None:
        super().__init__(parent)
        object_id = f"analysis_suite.binning.column.{database_id.encode('utf-8').hex()}.{name.encode('utf-8').hex()}"
        apply_identity(self, object_id, object_type="widget")
        self.setProperty("database_id", database_id)
        self.setProperty("column_name", name)
        self.defaults = defaults
        layout = QVBoxLayout(self)
        self.override = QCheckBox("Override shared defaults", self)
        self.override.setToolTip("Apply these settings only to the column selected above.")
        apply_identity(self.override, object_id + ".override", object_type="check_box")
        self.override.setProperty("column_name", name)
        layout.addWidget(self.override)
        self.editor = BinningSettingsEditor(object_id + ".settings", self)
        self.editor.setProperty("column_name", name)
        self.editor.set_values(defaults.values())
        self.editor.setEnabled(False)
        layout.addWidget(self.editor)
        self.override.toggled.connect(self._toggle_override)
        self.editor.changed.connect(self.changed)

    def _toggle_override(self, enabled: bool) -> None:
        if not enabled:
            self.editor.set_values(self.defaults.values())
        self.editor.setEnabled(enabled)
        self.changed.emit()

    def follow_defaults(self) -> None:
        if not self.override.isChecked():
            self.editor.set_values(self.defaults.values())

    def values(self) -> dict:
        return self.editor.values() if self.override.isChecked() else self.defaults.values()


class VariationBinningTab(QWidget):
    """Local input state only: one database, independent selected columns."""
    source_changed = Signal(object)
    configuration_changed = Signal()
    run_requested = Signal()
    reload_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        apply_identity(self, "analysis_suite.tab.variation_binning", object_type="widget")
        self._databases = ()
        self._column_catalogs: dict[str, tuple[DatabaseColumnDisplayEntry, ...]] = {}
        self._column_labels: dict[str, str] = {}
        self._overrides: dict[str, ColumnOverrideEditor] = {}
        self._populating = False
        self._connected = False
        self._busy = False
        self._source_ready = False
        self._last_configuration = None
        self._execution_message = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        apply_identity(scroll, "analysis_suite.binning.controls_scroll", object_type="scroll_area")
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        controls = QVBoxLayout(content)
        source = QGroupBox("Active database", content)
        source_layout = QVBoxLayout(source)
        source_layout.setContentsMargins(10, 26, 10, 10)
        self.database_choice = QComboBox(source)
        self.database_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.database_choice.setMinimumContentsLength(20)
        apply_identity(self.database_choice, "analysis_suite.binning.database", object_type="combo_box")
        self.database_choice.addItem("Choose one checked database…", None)
        source_layout.addWidget(self.database_choice)
        self.database_details = QLabel("All selected columns must come from this one database.", source)
        self.database_details.setWordWrap(True)
        source_layout.addWidget(self.database_details)
        self.reload_button = QPushButton("Reload Database", source)
        apply_identity(self.reload_button, "analysis_suite.binning.reload", object_type="button", action_id="analysis_suite.action.reload_database")
        self.reload_button.setEnabled(False)
        self.reload_button.clicked.connect(self.reload_requested)
        source_layout.addWidget(self.reload_button)
        controls.addWidget(source)
        columns = QGroupBox("Columns", content)
        columns_layout = QVBoxLayout(columns)
        columns_layout.setContentsMargins(10, 26, 10, 10)
        self.column_source = QLabel("No database selected.", columns)
        self.column_source.setWordWrap(True)
        columns_layout.addWidget(self.column_source)
        self.column_issues = QLabel(columns)
        self.column_issues.setWordWrap(True)
        self.column_issues.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        columns_layout.addWidget(self.column_issues)
        self.columns = configure_table(QTableWidget(columns), object_id="analysis_suite.binning.columns", columns=("Select", "Column", "Unit", "Definition"))
        self.columns.setMinimumWidth(0)
        self.columns.setMinimumHeight(140)
        self.columns.setMaximumHeight(200)
        self.columns.setWordWrap(False)
        columns_layout.addWidget(self.columns)
        self.column_count = QLabel("0 columns selected", columns)
        self.column_count.setWordWrap(True)
        columns_layout.addWidget(self.column_count)
        controls.addWidget(columns)
        self.settings_tabs = QTabWidget(content)
        apply_identity(self.settings_tabs, "analysis_suite.binning.settings_tabs", object_type="tab_widget")
        defaults_page = QWidget(self.settings_tabs)
        defaults_layout = QVBoxLayout(defaults_page)
        self.defaults = BinningSettingsEditor("analysis_suite.binning.defaults", defaults_page)
        defaults_layout.addWidget(self.defaults)
        self.settings_tabs.addTab(defaults_page, "Shared Defaults")
        overrides_page = QWidget(self.settings_tabs)
        overrides_layout = QVBoxLayout(overrides_page)
        self.override_column = QComboBox(overrides_page)
        apply_identity(self.override_column, "analysis_suite.binning.override_column", object_type="combo_box")
        overrides_layout.addWidget(self.override_column)
        self.override_stack = QStackedWidget(overrides_page)
        self.override_empty = QLabel("Select columns above to review or override their settings.", self.override_stack)
        self.override_empty.setWordWrap(True)
        self.override_stack.addWidget(self.override_empty)
        overrides_layout.addWidget(self.override_stack)
        self.settings_tabs.addTab(overrides_page, "Column Overrides")
        controls.addWidget(self.settings_tabs)
        self.reference_label = QLabel("Reference: entire history of the active database for retrospective analysis.\nRarity thresholds remain fixed at 1% and 5%, independently of the bin count. Each column has its own reference.", content)
        self.reference_label.setWordWrap(True)
        controls.addWidget(self.reference_label)
        self.configuration_status = QLabel(content)
        self.configuration_status.setWordWrap(True)
        apply_identity(self.configuration_status, "analysis_suite.binning.configuration_status", object_type="label")
        controls.addWidget(self.configuration_status)
        self.run_button = QPushButton("Analyze && Bin", content)
        apply_identity(self.run_button, "analysis_suite.binning.run", object_type="button", action_id="analysis_suite.action.run_binning")
        self.run_button.setEnabled(False)
        self.run_button.setToolTip("GUI preview: calculations are not connected yet.")
        self.run_button.clicked.connect(self.run_requested)
        controls.addWidget(self.run_button)
        self.results = BinningResults(content)
        self.views = self.results.views
        controls.addWidget(self.results)
        controls.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.database_choice.currentIndexChanged.connect(self._source_selected)
        self.columns.itemChanged.connect(self._columns_changed)
        self.defaults.changed.connect(self._defaults_changed)
        self.override_column.currentIndexChanged.connect(self._show_override)
        self._sync_status()

    def set_execution_state(self, *, connected, busy, source_ready, message=""):
        self._connected, self._busy, self._source_ready = connected, busy, source_ready
        self._execution_message = message
        for control in (self.database_choice, self.columns, self.settings_tabs):
            control.setEnabled(not busy)
        self._sync_status()

    def clear_source_columns(self, database_id):
        self._column_catalogs.pop(database_id, None)
        self._column_labels.pop(database_id, None)
        if self.active_database_id() == database_id:
            self._source_ready = False
            self.column_issues.clear()
            self._activate_database()

    def _source_selected(self, *_args):
        self._source_ready = False
        self._execution_message = ""
        self.column_issues.clear()
        self._activate_database()
        self.source_changed.emit(self.active_database_id())

    def active_database_id(self) -> str | None:
        return self.database_choice.currentData()

    def set_databases(self, entries) -> None:
        entries = display_catalog(entries)
        previous = self.active_database_id()
        self._databases = entries
        blocker = QSignalBlocker(self.database_choice)
        self.database_choice.clear()
        self.database_choice.addItem("Choose one checked database…", None)
        for entry in entries:
            self.database_choice.addItem(f"{entry.name} · {entry.asset} · {entry.timeframe} [{entry.database_id}]", entry.database_id)
        index = self.database_choice.findData(previous)
        self.database_choice.setCurrentIndex(max(index, 0))
        del blocker
        if self.active_database_id() != previous:
            self._source_selected()
        else:
            self.refresh_database_details()
            self._sync_status()

    def refresh_database_details(self):
        entry = next((value for value in self._databases if value.database_id == self.active_database_id()), None)
        if entry is None:
            self.database_details.setText("All selected columns must come from this one database.")
        else:
            first, last = entry.display_values()[-2:]
            self.database_details.setText(f"{entry.exchange} · {entry.market_type} · {entry.asset} · {entry.timeframe}\nEntire history: {first or 'unknown'} → {last or 'unknown'}")

    def set_database_columns(self, database_id: str, entries, *, source_label: str = "Injected column display metadata.") -> None:
        entries = tuple(entries)
        if any(not isinstance(entry, DatabaseColumnDisplayEntry) for entry in entries):
            raise TypeError("column entries must be DatabaseColumnDisplayEntry values")
        if any(entry.database_id != database_id for entry in entries):
            raise ValueError("all columns must belong to the supplied database ID")
        names = [entry.name for entry in entries]
        if any(not isinstance(name, str) or not name.strip() for name in names) or len(names) != len(set(names)):
            raise ValueError("column names must be non-empty and unique within one database")
        if any(not isinstance(entry.numeric, bool) for entry in entries):
            raise TypeError("numeric eligibility must be a boolean display flag")
        self._column_catalogs[database_id] = entries
        self._column_labels[database_id] = source_label
        if self.active_database_id() == database_id:
            self._activate_database()

    def selected_column_names(self) -> tuple[str, ...]:
        return tuple(self.columns.item(row, 0).data(Qt.ItemDataRole.UserRole)
                     for row in range(self.columns.rowCount())
                     if self.columns.item(row, 0).checkState() == Qt.CheckState.Checked)

    def column_override(self, name: str) -> ColumnOverrideEditor:
        return self._overrides[name]

    def configuration(self) -> dict | None:
        """Disposable GUI projection, not a validated execution request or profile."""
        names = self.selected_column_names()
        if self.active_database_id() is None or not names:
            return None
        values = []
        for name in names:
            page = self._overrides[name]
            settings = page.values()
            if settings["measurement"] != "directional_intensity":
                bounds = settings["cutoffs"]
                if not all(left < right for left, right in zip(bounds, bounds[1:])):
                    return None
            values.append({"source": name, "override": page.override.isChecked(), **settings})
        return {"database_id": self.active_database_id(), "reference": "full_history", "columns": tuple(values)}

    def _activate_database(self, *_args) -> None:
        self._populating = True
        self.columns.setRowCount(0)
        self.override_column.clear()
        for page in self._overrides.values():
            self.override_stack.removeWidget(page)
            page.hide()
            page.setParent(None)
            page.deleteLater()
        self._overrides.clear()
        self.override_stack.setCurrentWidget(self.override_empty)
        identity = self.active_database_id()
        entry = next((value for value in self._databases if value.database_id == identity), None)
        self.refresh_database_details()
        if entry is None:
            self.column_source.setText("No database selected.")
        else:
            supplied = identity in self._column_catalogs
            entries = tuple(value for value in self._column_catalogs.get(identity, ()) if value.numeric)
            self.column_source.setText(self._column_labels.get(identity, "Column catalogue is not connected.") if not supplied or entries else "No numeric parameter columns available.")
            self.columns.setRowCount(len(entries))
            for row, column in enumerate(entries):
                check = QTableWidgetItem()
                check.setData(Qt.ItemDataRole.UserRole, column.name)
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Unchecked)
                self.columns.setItem(row, 0, check)
                for index, text in enumerate((column.name, column.unit, column.definition), 1):
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    self.columns.setItem(row, index, item)
                page = ColumnOverrideEditor(identity, column.name, self.defaults, self.override_stack)
                page.changed.connect(self._sync_status)
                self._overrides[column.name] = page
                self.override_stack.addWidget(page)
            resize_data_manager_table(self.columns)
            self.columns.setColumnWidth(0, 60)
        self._populating = False
        self._sync_status()

    def _columns_changed(self, item) -> None:
        if self._populating or item.column() != 0:
            return
        previous = self.override_column.currentData()
        blocker = QSignalBlocker(self.override_column)
        self.override_column.clear()
        for name in self.selected_column_names():
            self.override_column.addItem(name, name)
        self.override_column.setCurrentIndex(max(self.override_column.findData(previous), 0) if self.override_column.count() else -1)
        del blocker
        self._show_override()
        self._sync_status()

    def _show_override(self, *_args) -> None:
        self.override_stack.setCurrentWidget(self._overrides.get(self.override_column.currentData(), self.override_empty))

    def _defaults_changed(self) -> None:
        for page in self._overrides.values():
            page.follow_defaults()
        self._sync_status()

    def _sync_status(self) -> None:
        names = self.selected_column_names()
        self.column_count.setText(f"{len(names)} columns selected · one profile per column")
        if self.active_database_id() is None:
            text = "Choose one checked database to configure variation and binning."
        elif not names:
            text = "Select one or more columns from the active database."
        elif self.configuration() is None:
            text = "Percentile boundaries must be strictly increasing. Review the selected columns' effective settings."
        else:
            text = "Ready to analyze each column independently." if self._connected and self._source_ready else "Configuration ready for review. Calculations are not connected yet."
        if self._connected and self._execution_message:
            text = self._execution_message
        self.configuration_status.setText(text)
        ready = self._connected and self._source_ready and not self._busy and self.configuration() is not None
        self.run_button.setEnabled(ready)
        self.run_button.setToolTip("Run full-history retrospective analysis." if ready else text)
        self.reload_button.setEnabled(self._connected and not self._busy and self.active_database_id() is not None)
        configuration = self.configuration()
        if configuration != self._last_configuration:
            self._last_configuration = configuration
            self.configuration_changed.emit()
