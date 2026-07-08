"""GUI-only Analysis Suite shell with deterministic dummy data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.dummy_data import analysis_feature_rows, analysis_readiness_rows
from leonardo.gui.metadata import (
    EffectiveGuiMetadataProfile,
    GuiMetadataResolver,
    load_metadata_document,
)
from leonardo.gui.windows.traceable_shell_widgets import (
    apply_trace,
    configure_table,
    populate_table,
)


ANALYSIS_SUITE_METADATA_ID = "analysis_suite.window"
_ANALYSIS_SUITE_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "metadata"
    / "windows"
    / "analysis_suite.window.toml"
)
_READINESS_COLUMNS = ("item", "state", "details")
_FEATURE_COLUMNS = ("feature_set", "status", "notes")


def load_analysis_suite_profile() -> EffectiveGuiMetadataProfile:
    """Load and resolve the Analysis Suite shell metadata profile."""

    result = load_metadata_document(_ANALYSIS_SUITE_METADATA_PATH)
    if result.document is None or result.report.has_errors:
        messages = "; ".join(issue.message for issue in result.report.issues)
        raise ValueError(f"Invalid Analysis Suite metadata profile: {messages}")
    return GuiMetadataResolver().resolve(result.document)


class AnalysisSuiteWindow(QWidget):
    """Shell-only Analysis Suite window using local dummy display data."""

    def __init__(
        self,
        profile: EffectiveGuiMetadataProfile | None = None,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._profile = profile if profile is not None else load_analysis_suite_profile()
        if self._profile.metadata_id != ANALYSIS_SUITE_METADATA_ID:
            raise ValueError("profile must describe analysis_suite.window")
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._buttons: dict[str, QPushButton] = {}
        self._tables: dict[str, QTableWidget] = {}
        self._status_label: QLabel | None = None
        self._report_area: QTextEdit | None = None
        self._log_area: QTextEdit | None = None

        self._apply_profile_metadata()
        self._build_shell()
        self.load_dummy_analysis_state()

    @property
    def profile(self) -> EffectiveGuiMetadataProfile:
        """Return the effective metadata profile consumed by the shell."""

        return self._profile

    def button_for_id(self, button_id: str) -> QPushButton:
        """Return a stable button by identifier."""

        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Analysis Suite button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        """Return a stable table by identifier."""

        try:
            return self._tables[table_id]
        except KeyError as error:
            raise KeyError(f"Unknown Analysis Suite table: {table_id}") from error

    def load_dummy_analysis_state(self) -> None:
        """Render deterministic dummy Analysis Suite state."""

        populate_table(
            self._tables["analysis_suite.table.readiness_dummy"],
            _READINESS_COLUMNS,
            analysis_readiness_rows(),
        )
        populate_table(
            self._tables["analysis_suite.table.feature_plan_dummy"],
            _FEATURE_COLUMNS,
            analysis_feature_rows(),
        )
        if self._report_area is not None:
            self._report_area.setPlainText(
                "DUMMY diagnostics report placeholder. No analysis engine ran."
            )
        self._set_status("DUMMY analysis shell loaded: diagnostics disabled.")
        self._append_log("Loaded dummy Analysis Suite shell state.")

    def _apply_profile_metadata(self) -> None:
        values = self._profile.values
        identity = _mapping_at(values, "identity")
        metadata = _mapping_at(values, "metadata")
        geometry = _mapping_at(values, "geometry")
        style = _mapping_at(values, "style")
        self.setWindowTitle(_string_value(identity, "title", "Analysis Suite"))
        self.setObjectName(_string_value(metadata, "object_name", "analysis_suite_window"))
        self.setProperty(
            "object_id",
            _string_value(metadata, "window_id", ANALYSIS_SUITE_METADATA_ID),
        )
        self.resize(_int_value(geometry, "width", 1280), _int_value(geometry, "height", 820))
        font = self.font()
        font.setPointSize(_int_value(style, "font_size", 14))
        self.setFont(font)

    def _build_shell(self) -> None:
        root = QVBoxLayout(self)
        apply_trace(
            root,
            "analysis_suite.layout.root",
            object_type="layout",
            parent_object_id=ANALYSIS_SUITE_METADATA_ID,
        )
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_status_log())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Analysis Suite Shell", self)
        apply_trace(
            header,
            "analysis_suite.panel.header",
            object_type="panel",
            parent_object_id=ANALYSIS_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(header)
        apply_trace(
            layout,
            "analysis_suite.layout.header",
            object_type="layout",
            parent_object_id="analysis_suite.panel.header",
        )
        title = QLabel("Analysis Suite", header)
        apply_trace(
            title,
            "analysis_suite.label.title",
            object_type="label",
            parent_object_id="analysis_suite.panel.header",
        )
        status = QLabel("DUMMY shell only", header)
        apply_trace(
            status,
            "analysis_suite.label.status",
            object_type="status_label",
            parent_object_id="analysis_suite.panel.header",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QGroupBox("Toolbar", self)
        apply_trace(
            toolbar,
            "analysis_suite.toolbar.main",
            object_type="toolbar",
            parent_object_id=ANALYSIS_SUITE_METADATA_ID,
        )
        layout = QHBoxLayout(toolbar)
        apply_trace(
            layout,
            "analysis_suite.layout.toolbar",
            object_type="layout",
            parent_object_id="analysis_suite.toolbar.main",
        )
        for button_id, label, action_id, action in (
            (
                "analysis_suite.button.load_dummy_state",
                "Load Dummy State",
                "analysis_suite.action.load_dummy_state",
                self.load_dummy_analysis_state,
            ),
            (
                "analysis_suite.button.preview_target_plan",
                "Preview Target Plan",
                "analysis_suite.action.preview_target_plan",
                partial(self._local_action, "analysis_suite.action.preview_target_plan"),
            ),
            (
                "analysis_suite.button.preview_diagnostics",
                "Preview Diagnostics",
                "analysis_suite.action.preview_diagnostics",
                partial(self._local_action, "analysis_suite.action.preview_diagnostics"),
            ),
            (
                "analysis_suite.button.reset_dummy_plan",
                "Reset Dummy Plan",
                "analysis_suite.action.reset_dummy_plan",
                self.reset_dummy_plan,
            ),
        ):
            button = QPushButton(label, toolbar)
            apply_trace(
                button,
                button_id,
                object_type="button",
                display_label=label,
                parent_object_id="analysis_suite.toolbar.main",
                action_id=action_id,
                tooltip="GUI shell action only. No analysis engine.",
            )
            button.clicked.connect(partial(self._handle_shell_action, action_id, action))
            self._buttons[button_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return toolbar

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        apply_trace(
            splitter,
            "analysis_suite.splitter.workspace",
            object_type="splitter",
            parent_object_id=ANALYSIS_SUITE_METADATA_ID,
        )
        splitter.addWidget(self._build_readiness_panel())
        splitter.addWidget(self._build_planning_panel())
        splitter.addWidget(self._build_report_panel())
        return splitter

    def _build_readiness_panel(self) -> QWidget:
        panel = QGroupBox("Readiness Dummy", self)
        apply_trace(
            panel,
            "analysis_suite.panel.readiness_dummy",
            object_type="panel",
            parent_object_id="analysis_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "analysis_suite.layout.readiness_dummy",
            object_type="layout",
            parent_object_id="analysis_suite.panel.readiness_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.readiness_dummy",
            columns=_READINESS_COLUMNS,
            labels=("Item", "State", "Details"),
            parent_object_id="analysis_suite.panel.readiness_dummy",
        )
        self._tables["analysis_suite.table.readiness_dummy"] = table
        layout.addWidget(table)
        return panel

    def _build_planning_panel(self) -> QWidget:
        panel = QGroupBox("Target / Feature Planning Dummy", self)
        apply_trace(
            panel,
            "analysis_suite.panel.target_feature_dummy",
            object_type="panel",
            parent_object_id="analysis_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "analysis_suite.layout.target_feature_dummy",
            object_type="layout",
            parent_object_id="analysis_suite.panel.target_feature_dummy",
        )
        target = QLabel("Target plan placeholder: no labels generated.", panel)
        apply_trace(
            target,
            "analysis_suite.label.target_plan_dummy",
            object_type="label",
            parent_object_id="analysis_suite.panel.target_feature_dummy",
        )
        table = configure_table(
            QTableWidget(panel),
            object_id="analysis_suite.table.feature_plan_dummy",
            columns=_FEATURE_COLUMNS,
            labels=("Feature Set", "Status", "Notes"),
            parent_object_id="analysis_suite.panel.target_feature_dummy",
        )
        self._tables["analysis_suite.table.feature_plan_dummy"] = table
        layout.addWidget(target)
        layout.addWidget(table)
        return panel

    def _build_report_panel(self) -> QWidget:
        panel = QGroupBox("Diagnostics Report Dummy", self)
        apply_trace(
            panel,
            "analysis_suite.panel.diagnostics_report_dummy",
            object_type="panel",
            parent_object_id="analysis_suite.splitter.workspace",
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "analysis_suite.layout.diagnostics_report_dummy",
            object_type="layout",
            parent_object_id="analysis_suite.panel.diagnostics_report_dummy",
        )
        report = QTextEdit(panel)
        apply_trace(
            report,
            "analysis_suite.text.diagnostics_report_dummy",
            object_type="text_area",
            parent_object_id="analysis_suite.panel.diagnostics_report_dummy",
        )
        report.setReadOnly(True)
        self._report_area = report
        layout.addWidget(report)
        return panel

    def _build_status_log(self) -> QWidget:
        panel = QGroupBox("Status / Log", self)
        apply_trace(
            panel,
            "analysis_suite.panel.status_log",
            object_type="panel",
            parent_object_id=ANALYSIS_SUITE_METADATA_ID,
        )
        layout = QVBoxLayout(panel)
        apply_trace(
            layout,
            "analysis_suite.layout.status_log",
            object_type="layout",
            parent_object_id="analysis_suite.panel.status_log",
        )
        log = QTextEdit(panel)
        apply_trace(
            log,
            "analysis_suite.text.status_log",
            object_type="text_area",
            parent_object_id="analysis_suite.panel.status_log",
        )
        log.setReadOnly(True)
        self._log_area = log
        layout.addWidget(log)
        return panel

    def reset_dummy_plan(self) -> None:
        """Reset local Analysis Suite dummy plan display state."""

        self._tables["analysis_suite.table.feature_plan_dummy"].setRowCount(0)
        if self._report_area is not None:
            self._report_area.setPlainText(
                "DUMMY analysis plan reset. No analysis engine ran."
            )
        self._set_status("DUMMY analysis plan reset: shell remains inert.")
        self._append_log("Reset dummy Analysis Suite plan display.")

    def _local_action(self, action_id: str) -> None:
        self._set_status(f"{action_id} is GUI shell-only dummy behavior.")
        self._append_log(f"{action_id}: no Analysis Suite engine ran.")

    def _handle_shell_action(
        self,
        action_id: str,
        handler: Callable[[], None],
    ) -> None:
        if not self._record_action(action_id):
            return
        handler()

    def _record_action(self, action_id: str) -> bool:
        if self._action_observer is None:
            return True
        decision = self._action_observer.record_action(
            action_id,
            window_id=ANALYSIS_SUITE_METADATA_ID,
        )
        return decision.allowed

    def _set_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _append_log(self, message: str) -> None:
        if self._log_area is not None:
            self._log_area.append(message)


def _mapping_at(values: object, key: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        return {}
    value = values.get(key, {})
    if isinstance(value, Mapping):
        return value
    return {}


def _string_value(values: object, key: str, fallback: str) -> str:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, str) and value else fallback


def _int_value(values: object, key: str, fallback: int) -> int:
    value = values.get(key) if hasattr(values, "get") else None
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback
