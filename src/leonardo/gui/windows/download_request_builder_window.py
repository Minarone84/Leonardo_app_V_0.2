"""GUI-only Download Request Builder shell."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

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
OHLCV_DRAFT_SUMMARY_WARNING = (
    "OHLCV naming/storage/maintenance policy is not implemented here. "
    "This is a local draft only."
)


@dataclass(frozen=True)
class _FieldSpec:
    field_id: str
    label: str
    widget_kind: str
    options: tuple[str, ...] = ()
    placeholder: str = ""


@dataclass(frozen=True)
class DownloadRequestDraft:
    """
    GUI-local draft assembled from visible request-builder fields.

    The draft is a presentation-layer structure only. It is not a Core request
    contract and is not submitted or preflighted by this window.
    """

    workflow_mode: str
    source_provider: str
    market: str
    symbols: tuple[str, ...]
    timeframe_mode: str
    timeframes: tuple[str, ...]
    range_mode: str
    start: str
    end: str
    conflict_policy: str
    priority: str
    connection_ref: str
    websocket_required: bool
    tags: tuple[str, ...]
    metadata: Mapping[str, object]
    metadata_parse_error: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "timeframes", tuple(self.timeframes))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True)
class DownloadDraftIssue:
    """
    GUI-local validation issue for the local draft summary.

    Issues reported here are non-authoritative and do not replace Core
    validation or future preflight behavior.
    """

    field_id: str
    severity: str
    message: str


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
        on_preview_requested: Callable[[DownloadRequestDraft], object] | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._workflow_mode = ""
        self._field_widgets: dict[str, QWidget] = {}
        self._title_label: QLabel | None = None
        self._workflow_mode_label: QLabel | None = None
        self._ohlcv_policy_note: QLabel | None = None
        self._summary_text: QTextEdit | None = None
        self._preview_result_text: QTextEdit | None = None
        self._on_preview_requested = on_preview_requested

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

    def current_draft(self) -> DownloadRequestDraft:
        """Return the current parsed GUI-local draft."""

        return _draft_from_widgets(self._workflow_mode, self._field_widgets)

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
        if self._summary_text is not None:
            self._summary_text.clear()
        if self._preview_result_text is not None:
            self._preview_result_text.clear()

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

        draft_summary_button = QPushButton("Draft Summary")
        draft_summary_button.setObjectName(
            "download_request_builder.draft_summary_button"
        )
        draft_summary_button.clicked.connect(self._show_draft_summary)

        preview_preflight_button = QPushButton("Preview Preflight")
        preview_preflight_button.setObjectName(
            "download_request_builder.preview_preflight_button"
        )
        preview_preflight_button.clicked.connect(self._show_preflight_preview)

        close_button = QPushButton("Close")
        close_button.setObjectName("download_request_builder.close")
        close_button.clicked.connect(self.close)

        summary_text = QTextEdit()
        summary_text.setObjectName("download_request_builder.summary_text")
        summary_text.setReadOnly(True)
        summary_text.setFixedHeight(190)
        self._summary_text = summary_text

        preview_result_text = QTextEdit()
        preview_result_text.setObjectName("download_request_builder.preview_result_text")
        preview_result_text.setReadOnly(True)
        preview_result_text.setFixedHeight(140)
        self._preview_result_text = preview_result_text

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(draft_summary_button)
        buttons.addWidget(preview_preflight_button)
        buttons.addWidget(close_button)

        root.addWidget(title_label)
        root.addWidget(workflow_mode_label)
        root.addWidget(ohlcv_note)
        root.addLayout(form)
        root.addWidget(summary_text)
        root.addWidget(preview_result_text)
        root.addLayout(buttons)

    def _show_draft_summary(self) -> None:
        if self._summary_text is None:
            return
        draft = self.current_draft()
        issues = _validate_draft(draft)
        self._summary_text.setPlainText(_format_draft_summary(draft, issues))

    def _show_preflight_preview(self) -> None:
        if self._preview_result_text is None:
            return

        draft = self.current_draft()
        issues = _validate_draft(draft)
        if issues:
            self._preview_result_text.setPlainText(
                _format_local_preview_blocked(issues)
            )
            return

        if self._on_preview_requested is None:
            self._preview_result_text.setPlainText(
                "Preflight preview is unavailable."
            )
            return

        try:
            preview = self._on_preview_requested(draft)
        except Exception as error:
            self._preview_result_text.setPlainText(
                "Preflight preview failed: "
                f"{type(error).__name__}: {error}"
            )
            return
        self._preview_result_text.setPlainText(_format_preflight_preview(preview))


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


def _draft_from_widgets(
    workflow_mode: str,
    field_widgets: Mapping[str, QWidget],
) -> DownloadRequestDraft:
    timeframe_mode = _text_field_value(field_widgets["timeframe_mode"])
    metadata, metadata_parse_error = _parse_metadata(
        _text_field_value(field_widgets["metadata"])
    )
    return DownloadRequestDraft(
        workflow_mode=workflow_mode,
        source_provider=_text_field_value(field_widgets["source_provider"]),
        market=_text_field_value(field_widgets["market"]),
        symbols=_split_csv_lines(_text_field_value(field_widgets["symbols"])),
        timeframe_mode=timeframe_mode,
        timeframes=(
            _split_csv_lines(_text_field_value(field_widgets["timeframes"]))
            if timeframe_mode == "explicit"
            else ()
        ),
        range_mode=_text_field_value(field_widgets["range_mode"]),
        start=_text_field_value(field_widgets["start"]),
        end=_text_field_value(field_widgets["end"]),
        conflict_policy=_text_field_value(field_widgets["conflict_policy"]),
        priority=_text_field_value(field_widgets["priority"]),
        connection_ref=_text_field_value(field_widgets["connection_ref"]),
        websocket_required=_checked_field_value(field_widgets["websocket_required"]),
        tags=_split_csv_lines(_text_field_value(field_widgets["tags"])),
        metadata=metadata,
        metadata_parse_error=metadata_parse_error,
    )


def _validate_draft(draft: DownloadRequestDraft) -> tuple[DownloadDraftIssue, ...]:
    issues: list[DownloadDraftIssue] = []
    if not draft.symbols:
        issues.append(
            DownloadDraftIssue(
                field_id="symbols",
                severity="error",
                message="At least one symbol is required.",
            )
        )
    if draft.timeframe_mode == "explicit" and not draft.timeframes:
        issues.append(
            DownloadDraftIssue(
                field_id="timeframes",
                severity="error",
                message="Explicit timeframe mode requires at least one timeframe.",
            )
        )
    if draft.metadata_parse_error is not None:
        issues.append(
            DownloadDraftIssue(
                field_id="metadata",
                severity="error",
                message=draft.metadata_parse_error,
            )
        )

    start_value, start_error = _parse_iso_like_datetime(draft.start)
    end_value, end_error = _parse_iso_like_datetime(draft.end)
    if start_error is not None:
        issues.append(
            DownloadDraftIssue(
                field_id="start",
                severity="error",
                message=start_error,
            )
        )
    if end_error is not None:
        issues.append(
            DownloadDraftIssue(
                field_id="end",
                severity="error",
                message=end_error,
            )
        )
    if start_value is not None and end_value is not None:
        try:
            if start_value > end_value:
                issues.append(
                    DownloadDraftIssue(
                        field_id="end",
                        severity="error",
                        message="End must be greater than or equal to start.",
                    )
                )
        except TypeError:
            issues.append(
                DownloadDraftIssue(
                    field_id="end",
                    severity="error",
                    message="Start and end must use comparable timezone formats.",
                )
            )

    return tuple(issues)


def _format_draft_summary(
    draft: DownloadRequestDraft,
    issues: tuple[DownloadDraftIssue, ...],
) -> str:
    metadata_display = (
        f"invalid ({draft.metadata_parse_error})"
        if draft.metadata_parse_error is not None
        else f"valid JSON object {json.dumps(dict(draft.metadata), sort_keys=True)}"
    )
    lines = [
        f"Workflow mode: {draft.workflow_mode}",
        f"Source / Provider: {_display_value(draft.source_provider)}",
        f"Market: {_display_value(draft.market)}",
        f"Symbols: {len(draft.symbols)} ({_format_sequence(draft.symbols)})",
        f"Timeframe mode: {draft.timeframe_mode}",
        f"Explicit timeframes: {len(draft.timeframes)} ({_format_sequence(draft.timeframes)})",
        f"Range mode: {draft.range_mode}",
        f"Start: {_display_value(draft.start)}",
        f"End: {_display_value(draft.end)}",
        f"Conflict policy: {draft.conflict_policy}",
        f"Priority: {draft.priority}",
        f"Connection ref: {_display_value(draft.connection_ref)}",
        f"WebSocket required: {draft.websocket_required}",
        f"Tags: {len(draft.tags)} ({_format_sequence(draft.tags)})",
        f"Metadata: {metadata_display}",
    ]
    if draft.workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE:
        lines.extend(("", f"Warning: {OHLCV_DRAFT_SUMMARY_WARNING}"))

    lines.extend(("", "Local validation issues:"))
    if not issues:
        lines.append("- none")
    else:
        for issue in issues:
            lines.append(
                f"- {issue.severity.upper()} {issue.field_id}: {issue.message}"
            )
    return "\n".join(lines)


def _format_local_preview_blocked(
    issues: tuple[DownloadDraftIssue, ...],
) -> str:
    lines = ["Preflight preview blocked by local validation issues:"]
    for issue in issues:
        lines.append(f"- {issue.severity.upper()} {issue.field_id}: {issue.message}")
    return "\n".join(lines)


def _format_preflight_preview(preview: object) -> str:
    issues = tuple(getattr(preview, "issues", ()))
    lines = [
        "Preflight preview result:",
        f"Message: {getattr(preview, 'message', '')}",
        f"Request ID: {getattr(preview, 'request_id', '')}",
        f"Status: {getattr(preview, 'status', '')}",
        f"Can run: {getattr(preview, 'can_run', False)}",
        f"Estimated symbols: {_display_optional(getattr(preview, 'estimated_symbols', None))}",
        f"Estimated timeframes: {_display_optional(getattr(preview, 'estimated_timeframes', None))}",
        f"Estimated items: {_display_optional(getattr(preview, 'estimated_items', None))}",
        (
            "Required connections: "
            f"{_format_sequence(tuple(getattr(preview, 'required_connections', ())))}"
        ),
        f"WebSocket required: {getattr(preview, 'websocket_required', False)}",
        "Core preview issues:",
    ]
    if not issues:
        lines.append("- none")
    else:
        for issue in issues:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def _text_field_value(widget: QWidget) -> str:
    if isinstance(widget, QComboBox):
        return widget.currentText().strip()
    if isinstance(widget, QTextEdit):
        return widget.toPlainText().strip()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    return ""


def _checked_field_value(widget: QWidget) -> bool:
    return isinstance(widget, QCheckBox) and widget.isChecked()


def _split_csv_lines(value: str) -> tuple[str, ...]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return tuple(
        part.strip()
        for part in normalized.replace("\n", ",").split(",")
        if part.strip()
    )


def _parse_metadata(raw_value: str) -> tuple[Mapping[str, object], str | None]:
    if not raw_value:
        return {}, None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as error:
        return {}, f"Invalid metadata JSON: {error.msg}"
    if not isinstance(parsed, dict):
        return {}, "Metadata must be a JSON object."
    return parsed, None


def _parse_iso_like_datetime(value: str) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized), None
    except ValueError:
        return None, "Value must be an ISO-like date or datetime."


def _display_value(value: str) -> str:
    return value if value else "none"


def _display_optional(value: object) -> str:
    return "unresolved" if value is None else str(value)


def _format_sequence(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    return ", ".join(values)
