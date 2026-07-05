"""GUI-only Download Request Builder shell."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


DOWNLOAD_DATA_WORKFLOW_MODE = "download_data"
OHLCV_MAINTENANCE_WORKFLOW_MODE = "ohlcv_maintenance"
SUPPORTED_WORKFLOW_MODES = (
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
)
OHLCV_POLICY_DEFERRED_MESSAGE = (
    "OHLCV naming/storage policy is not defined yet. "
    "Submission is intentionally disabled/deferred."
)


@dataclass(frozen=True)
class _FieldSpec:
    field_id: str
    label: str
    widget_kind: str
    options: tuple[str, ...] = ()
    placeholder: str = ""


_FIELD_SPECS = (
    _FieldSpec(
        "source_provider",
        "Source / Provider",
        "combo",
        options=("Select provider (catalog pending)",),
    ),
    _FieldSpec(
        "market",
        "Market",
        "combo",
        options=("Select market (catalog pending)",),
    ),
    _FieldSpec("symbols", "Symbols", "line", placeholder="BTCUSDT, ETHUSDT"),
    _FieldSpec(
        "timeframe_mode",
        "Timeframe Mode",
        "combo",
        options=("explicit", "all", "default", "supported"),
    ),
    _FieldSpec("timeframes", "Timeframes", "line", placeholder="1m, 5m, 1h"),
    _FieldSpec(
        "range_mode",
        "Range Mode",
        "combo",
        options=("explicit", "latest", "missing_only", "full_history"),
    ),
    _FieldSpec("start", "Start", "line", placeholder="YYYY-MM-DD or timestamp"),
    _FieldSpec("end", "End", "line", placeholder="YYYY-MM-DD or timestamp"),
    _FieldSpec(
        "conflict_policy",
        "Conflict Policy",
        "combo",
        options=("skip_existing", "overwrite", "append", "merge", "repair_gaps"),
    ),
    _FieldSpec(
        "priority",
        "Priority",
        "combo",
        options=("low", "normal", "high"),
    ),
    _FieldSpec(
        "connection_ref",
        "Connection Ref",
        "combo",
        options=("No connection selected (catalog pending)",),
    ),
    _FieldSpec("websocket_required", "WebSocket Required", "checkbox"),
    _FieldSpec("tags", "Tags", "line", placeholder="comma-separated tags"),
    _FieldSpec("metadata", "Metadata", "text", placeholder="draft metadata"),
)


class DownloadRequestBuilderWindow(QWidget):
    """
    Shared GUI-only shell for future Download Manager request drafting.

    The shell displays draft fields and workflow-specific messaging only. It
    does not create request contracts, call Core services, submit preflight, or
    execute download behavior.
    """

    def __init__(
        self,
        workflow_mode: str = DOWNLOAD_DATA_WORKFLOW_MODE,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._workflow_mode = ""
        self._field_widgets: dict[str, QWidget] = {}
        self._title_label: QLabel | None = None
        self._workflow_mode_label: QLabel | None = None
        self._ohlcv_policy_note: QLabel | None = None

        self.setObjectName("download_request_builder_window")
        self.resize(720, 640)
        self._build_window()
        self.set_workflow_mode(workflow_mode)

    @property
    def workflow_mode(self) -> str:
        """Return the current GUI-local workflow mode string."""

        return self._workflow_mode

    @property
    def workflow_label(self) -> str:
        """Return the current user-facing workflow label."""

        return _workflow_label(self._workflow_mode)

    def field_labels(self) -> tuple[str, ...]:
        """Return visible request-builder field labels in display order."""

        return tuple(spec.label for spec in _FIELD_SPECS)

    def field_widget_for_id(self, field_id: str) -> QWidget:
        """Return a draft field widget by stable GUI field identifier."""

        try:
            return self._field_widgets[field_id]
        except KeyError as error:
            raise KeyError(f"Unknown Download Request Builder field: {field_id}") from error

    def option_values_for_id(self, field_id: str) -> tuple[str, ...]:
        """Return combo-box option values for a draft field."""

        widget = self.field_widget_for_id(field_id)
        if not isinstance(widget, QComboBox):
            return ()
        return tuple(widget.itemText(index) for index in range(widget.count()))

    def set_workflow_mode(self, workflow_mode: str) -> None:
        """Switch the shell between supported GUI-local workflow modes."""

        _validate_workflow_mode(workflow_mode)
        self._workflow_mode = workflow_mode
        workflow_label = _workflow_label(workflow_mode)
        self.setWindowTitle(f"{workflow_label} Request Builder")
        if self._title_label is not None:
            self._title_label.setText(f"{workflow_label} Request Builder")
        if self._workflow_mode_label is not None:
            self._workflow_mode_label.setText(f"Workflow mode: {workflow_mode}")
        if self._ohlcv_policy_note is not None:
            self._ohlcv_policy_note.setVisible(
                workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE
            )

    def _build_window(self) -> None:
        root = QVBoxLayout(self)

        title_label = QLabel("")
        title_label.setObjectName("download_request_builder.title_label")
        self._title_label = title_label

        workflow_mode_label = QLabel("")
        workflow_mode_label.setObjectName("download_request_builder.workflow_mode_label")
        self._workflow_mode_label = workflow_mode_label

        ohlcv_note = QLabel(OHLCV_POLICY_DEFERRED_MESSAGE)
        ohlcv_note.setObjectName("download_request_builder.ohlcv_policy_note")
        ohlcv_note.setWordWrap(True)
        self._ohlcv_policy_note = ohlcv_note

        form = QFormLayout()
        form.setObjectName("download_request_builder.form")
        for spec in _FIELD_SPECS:
            label = QLabel(spec.label)
            label.setObjectName(f"download_request_builder.{spec.field_id}.label")
            widget = _build_field_widget(spec)
            self._field_widgets[spec.field_id] = widget
            form.addRow(label, widget)

        close_button = QPushButton("Close")
        close_button.setObjectName("download_request_builder.close")
        close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        root.addWidget(title_label)
        root.addWidget(workflow_mode_label)
        root.addWidget(ohlcv_note)
        root.addLayout(form)
        root.addLayout(buttons)


def _build_field_widget(spec: _FieldSpec) -> QWidget:
    object_name = f"download_request_builder.{spec.field_id}"
    if spec.widget_kind == "combo":
        widget = QComboBox()
        widget.addItems(spec.options)
    elif spec.widget_kind == "checkbox":
        widget = QCheckBox("Require WebSocket-capable connection")
    elif spec.widget_kind == "text":
        widget = QTextEdit()
        widget.setPlaceholderText(spec.placeholder)
        widget.setFixedHeight(72)
    else:
        widget = QLineEdit()
        widget.setPlaceholderText(spec.placeholder)
    widget.setObjectName(object_name)
    return widget


def _validate_workflow_mode(workflow_mode: str) -> None:
    if workflow_mode not in SUPPORTED_WORKFLOW_MODES:
        supported = ", ".join(SUPPORTED_WORKFLOW_MODES)
        raise ValueError(
            "Unsupported Download Request Builder workflow mode: "
            f"{workflow_mode}. Supported modes: {supported}"
        )


def _workflow_label(workflow_mode: str) -> str:
    if workflow_mode == DOWNLOAD_DATA_WORKFLOW_MODE:
        return "Download Data"
    if workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE:
        return "OHLCV Maintenance"
    _validate_workflow_mode(workflow_mode)
    return workflow_mode
