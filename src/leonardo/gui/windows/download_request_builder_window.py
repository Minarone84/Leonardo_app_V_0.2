"""GUI-only Download Request Builder shell."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.download_request_mapper import (
    download_data_selection_drafts_from_request_draft,
    download_data_selection_summary_from_selection_draft,
)


DOWNLOAD_DATA_WORKFLOW_MODE = "download_data"
OHLCV_MAINTENANCE_WORKFLOW_MODE = "ohlcv_maintenance"
SUPPORTED_WORKFLOW_MODES = (
    DOWNLOAD_DATA_WORKFLOW_MODE,
    OHLCV_MAINTENANCE_WORKFLOW_MODE,
)
DOWNLOAD_REQUEST_BUILDER_METADATA_ID = "download_request_builder.window"
DOWNLOAD_REQUEST_BUILDER_DRAFT_SUMMARY_ACTION_ID = (
    "download_request_builder.draft_summary"
)
DOWNLOAD_REQUEST_BUILDER_PREVIEW_PREFLIGHT_ACTION_ID = (
    "download_request_builder.preview_preflight"
)
DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID = "download_request_builder.submit"
DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID = "download_request_builder.close"
OHLCV_POLICY_DEFERRED_MESSAGE = (
    "OHLCV naming/storage policy is not defined yet. "
    "Submission is intentionally disabled/deferred."
)
OHLCV_DRAFT_SUMMARY_WARNING = (
    "OHLCV naming/storage/maintenance policy is not implemented here. "
    "This is a local draft only."
)
OHLCV_SUBMIT_DEFERRED_MESSAGE = (
    "OHLCV Maintenance submit is deferred until storage execution and "
    "maintenance policy are implemented."
)


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


@dataclass(frozen=True)
class DownloadRequestBuilderOptions:
    """
    GUI-safe catalog facts used to populate the Download Data layout.

    Composition supplies these plain values from Core/catalog state. The widget
    does not import Core services, exchange metadata loaders, or contracts.
    """

    exchanges: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    default_limit: int = 200
    max_limit: int | None = 1000

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchanges", _normalize_option_tuple(self.exchanges))
        object.__setattr__(self, "markets", _normalize_option_tuple(self.markets))
        object.__setattr__(self, "timeframes", _normalize_option_tuple(self.timeframes))
        if type(self.default_limit) is not int or self.default_limit < 1:
            raise ValueError("default_limit must be a positive integer")
        if self.max_limit is not None and (
            type(self.max_limit) is not int or self.max_limit < self.default_limit
        ):
            raise ValueError("max_limit must be None or greater than default_limit")


_VISIBLE_FIELD_LABELS = (
    "Exchange",
    "Market Type",
    "Symbol",
    "Timeframes",
    "Start",
    "End",
    "Limit",
)


class DownloadRequestBuilderWindow(QWidget):
    """
    Shared GUI-only shell for future Download Manager request drafting.

    The shell displays draft fields and locally formatted result messages. It
    does not create request contracts, import Core services, or execute download
    behavior. Core-aware preview and submit behavior is injected through
    callbacks owned by composition.
    """

    def __init__(
        self,
        workflow_mode: str = DOWNLOAD_DATA_WORKFLOW_MODE,
        *,
        parent: QWidget | None = None,
        on_preview_requested: Callable[[DownloadRequestDraft], object] | None = None,
        on_submit_intent: Callable[[DownloadRequestDraft], object] | None = None,
        action_observer: GuiActionObserver | None = None,
        options: DownloadRequestBuilderOptions | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._workflow_mode = ""
        self._field_widgets: dict[str, QWidget] = {}
        self._timeframe_checkboxes: dict[str, QCheckBox] = {}
        self._options = options if options is not None else DownloadRequestBuilderOptions()
        self._title_label: QLabel | None = None
        self._ohlcv_policy_note: QLabel | None = None
        self._selection_recap_value_labels: dict[str, QLabel] = {}
        self._progress_timeframes_layout: QVBoxLayout | None = None
        self._progress_timeframe_bars: dict[str, QProgressBar] = {}
        self._progress_total_bar: QProgressBar | None = None
        self._progress_messages: QTextEdit | None = None
        self._summary_text: QTextEdit | None = None
        self._on_preview_requested = on_preview_requested
        self._on_submit_intent = on_submit_intent
        self._action_observer = action_observer

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

        return _VISIBLE_FIELD_LABELS

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

    def selected_timeframes(self) -> tuple[str, ...]:
        """Return selected explicit timeframe values in display order."""

        return tuple(
            timeframe
            for timeframe, checkbox in self._timeframe_checkboxes.items()
            if checkbox.isChecked()
        )

    def timeframe_checkbox_for_value(self, timeframe: str) -> QCheckBox:
        """Return a timeframe checkbox by canonical display value."""

        try:
            return self._timeframe_checkboxes[timeframe]
        except KeyError as error:
            raise KeyError(f"Unknown Download Data timeframe: {timeframe}") from error

    def current_draft(self) -> DownloadRequestDraft:
        """Return the current parsed GUI-local draft."""

        return _draft_from_widgets(self._workflow_mode, self._field_widgets)

    def set_workflow_mode(self, workflow_mode: str) -> None:
        """Switch the shell between supported GUI-local workflow modes."""

        _validate_workflow_mode(workflow_mode)
        self._workflow_mode = workflow_mode
        workflow_label = _workflow_label(workflow_mode)
        self.setWindowTitle(workflow_label)
        if self._title_label is not None:
            self._title_label.setText(workflow_label)
        if self._ohlcv_policy_note is not None:
            self._ohlcv_policy_note.setVisible(
                workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE
            )
        if self._summary_text is not None:
            self._summary_text.clear()
        self._refresh_selection_recap()

    def _build_window(self) -> None:
        root = QVBoxLayout(self)

        title_label = QLabel("")
        title_label.setObjectName("download_request_builder.title_label")
        self._title_label = title_label

        ohlcv_note = QLabel(OHLCV_POLICY_DEFERRED_MESSAGE)
        ohlcv_note.setObjectName("download_request_builder.ohlcv_policy_note")
        ohlcv_note.setWordWrap(True)
        self._ohlcv_policy_note = ohlcv_note

        form = QFormLayout()
        form.setObjectName("download_request_builder.form")

        exchange = QComboBox()
        exchange.setObjectName("download_request_builder.exchange")
        exchange.addItems(self._options.exchanges)
        exchange.setCurrentIndex(-1)
        exchange.currentTextChanged.connect(self._refresh_selection_recap)
        self._field_widgets["exchange"] = exchange
        self._field_widgets["source_provider"] = exchange
        form.addRow(_field_label("exchange", "Exchange"), exchange)

        market = QComboBox()
        market.setObjectName("download_request_builder.market")
        market.addItems(self._options.markets)
        market.setCurrentIndex(-1)
        market.currentTextChanged.connect(self._refresh_selection_recap)
        self._field_widgets["market"] = market
        form.addRow(_field_label("market", "Market Type"), market)

        symbol = QLineEdit()
        symbol.setObjectName("download_request_builder.symbol")
        symbol.setPlaceholderText("BTCUSDT")
        symbol.textChanged.connect(self._refresh_selection_recap)
        self._field_widgets["symbol"] = symbol
        self._field_widgets["symbols"] = symbol
        form.addRow(_field_label("symbol", "Symbol"), symbol)

        timeframe_grid = QWidget()
        timeframe_grid.setObjectName("download_request_builder.timeframes")
        grid = QGridLayout(timeframe_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for index, timeframe in enumerate(self._options.timeframes):
            checkbox = QCheckBox(timeframe)
            checkbox.setObjectName(f"download_request_builder.timeframe.{timeframe}")
            checkbox.toggled.connect(self._refresh_selection_recap)
            self._timeframe_checkboxes[timeframe] = checkbox
            grid.addWidget(checkbox, index // 3, index % 3)
        self._field_widgets["timeframes"] = timeframe_grid
        form.addRow(_field_label("timeframes", "Timeframes"), timeframe_grid)

        start = QLineEdit()
        start.setObjectName("download_request_builder.start")
        start.setPlaceholderText("YYYY-MM-DD or timestamp")
        self._field_widgets["start"] = start
        form.addRow(_field_label("start", "Start"), start)

        end = QLineEdit()
        end.setObjectName("download_request_builder.end")
        end.setPlaceholderText("YYYY-MM-DD or timestamp")
        self._field_widgets["end"] = end
        form.addRow(_field_label("end", "End"), end)

        limit = QLineEdit(str(self._options.default_limit))
        limit.setObjectName("download_request_builder.limit")
        limit.setProperty("download_request_builder.limit_max", self._options.max_limit)
        max_label = (
            f"1-{self._options.max_limit}"
            if self._options.max_limit is not None
            else "positive integer"
        )
        limit.setPlaceholderText(f"Page limit ({max_label})")
        limit.textChanged.connect(self._refresh_selection_recap)
        self._field_widgets["limit"] = limit
        form.addRow(_field_label("limit", "Limit"), limit)

        selection_recap = self._build_selection_recap()
        progress_shell = self._build_progress_shell()

        preview_button = QPushButton("Preview Preflight")
        preview_button.setObjectName(
            "download_request_builder.preview_preflight_button"
        )
        preview_button.clicked.connect(self._show_preflight_preview)

        submit_button = QPushButton("Start")
        submit_button.setObjectName("download_request_builder.submit_button")
        submit_button.clicked.connect(self._show_submit_result)

        close_button = QPushButton("Close")
        close_button.setObjectName("download_request_builder.close")
        close_button.clicked.connect(self._close_requested)

        summary_text = QTextEdit()
        summary_text.setObjectName("download_request_builder.status_summary")
        summary_text.setReadOnly(True)
        summary_text.setFixedHeight(190)
        self._summary_text = summary_text

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(preview_button)
        buttons.addWidget(submit_button)
        buttons.addWidget(close_button)

        root.addWidget(title_label)
        root.addWidget(ohlcv_note)
        root.addLayout(form)
        root.addWidget(selection_recap)
        root.addWidget(summary_text)
        root.addWidget(progress_shell)
        root.addLayout(buttons)
        self._refresh_selection_recap()

    def _build_selection_recap(self) -> QWidget:
        recap = QWidget()
        recap.setObjectName("download_request_builder.selection_recap")
        grid = QGridLayout(recap)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        title = QLabel("Selection Recap")
        title.setObjectName("download_request_builder.selection_recap.title")
        grid.addWidget(title, 0, 0, 1, 2)

        fields = (
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("symbols", "Asset / Symbol"),
            ("timeframes", "Selected Timeframes"),
            ("limit", "Limit"),
            ("state", "State"),
            ("warnings", "Warnings"),
            ("blockers", "Blockers"),
        )
        for row_index, (field_id, label_text) in enumerate(fields, start=1):
            label = QLabel(label_text)
            label.setObjectName(
                f"download_request_builder.selection_recap.{field_id}.label"
            )
            value = QLabel("")
            value.setObjectName(
                f"download_request_builder.selection_recap.{field_id}.value"
            )
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._selection_recap_value_labels[field_id] = value
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)
        return recap

    def _build_progress_shell(self) -> QWidget:
        progress = QWidget()
        progress.setObjectName("download_request_builder.progress_shell")
        layout = QVBoxLayout(progress)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)

        title = QLabel("Progress")
        title.setObjectName("download_request_builder.progress.title")
        layout.addWidget(title)

        total_label = QLabel("Total Progress")
        total_label.setObjectName("download_request_builder.progress.total.label")
        layout.addWidget(total_label)

        total = QProgressBar()
        total.setObjectName("download_request_builder.progress.total")
        total.setRange(0, 100)
        total.setValue(0)
        self._progress_total_bar = total
        layout.addWidget(total)

        timeframe_container = QWidget()
        timeframe_container.setObjectName("download_request_builder.progress.timeframes")
        timeframe_layout = QVBoxLayout(timeframe_container)
        timeframe_layout.setContentsMargins(0, 0, 0, 0)
        timeframe_layout.setSpacing(4)
        self._progress_timeframes_layout = timeframe_layout
        layout.addWidget(timeframe_container)

        messages = QTextEdit()
        messages.setObjectName("download_request_builder.progress.messages")
        messages.setReadOnly(True)
        messages.setFixedHeight(64)
        messages.setPlainText("No download running.\nExecution is not implemented yet.")
        self._progress_messages = messages
        layout.addWidget(messages)

        return progress

    def _refresh_selection_recap(self) -> None:
        if not self._selection_recap_value_labels:
            return

        values = _selection_recap_values(self.current_draft())
        for field_id, value in values.items():
            label = self._selection_recap_value_labels.get(field_id)
            if label is not None:
                label.setText(value)
        self._refresh_progress_shell()

    def _refresh_progress_shell(self) -> None:
        if self._progress_timeframes_layout is None:
            return

        while self._progress_timeframes_layout.count():
            item = self._progress_timeframes_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._progress_timeframe_bars.clear()

        timeframes = self.selected_timeframes()
        if not timeframes:
            empty = QLabel("No timeframes selected.")
            empty.setObjectName("download_request_builder.progress.timeframes.empty")
            self._progress_timeframes_layout.addWidget(empty)
            return

        for timeframe in timeframes:
            row = QWidget()
            row.setObjectName(f"download_request_builder.progress.row.{timeframe}")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(timeframe)
            label.setObjectName(f"download_request_builder.progress.label.{timeframe}")
            row_layout.addWidget(label)

            bar = QProgressBar()
            bar.setObjectName(f"download_request_builder.progress.timeframe.{timeframe}")
            bar.setRange(0, 100)
            bar.setValue(0)
            row_layout.addWidget(bar)
            self._progress_timeframe_bars[timeframe] = bar

            self._progress_timeframes_layout.addWidget(row)

    def _show_draft_summary(self) -> None:
        if not self._record_action(DOWNLOAD_REQUEST_BUILDER_DRAFT_SUMMARY_ACTION_ID):
            return
        if self._summary_text is None:
            return
        draft = self.current_draft()
        issues = _validate_draft(draft)
        self._summary_text.setPlainText(_format_draft_summary(draft, issues))

    def _show_preflight_preview(self) -> None:
        if not self._record_action(DOWNLOAD_REQUEST_BUILDER_PREVIEW_PREFLIGHT_ACTION_ID):
            return
        if self._summary_text is None:
            return

        draft = self.current_draft()
        issues = _validate_draft(draft)
        if issues:
            self._summary_text.setPlainText(
                _format_local_preview_blocked(issues)
            )
            return

        if self._on_preview_requested is None:
            self._summary_text.setPlainText(
                "Preflight preview is unavailable."
            )
            return

        try:
            preview = self._on_preview_requested(draft)
        except Exception as error:
            self._summary_text.setPlainText(
                "Preflight preview failed: "
                f"{type(error).__name__}: {error}"
            )
            return
        self._summary_text.setPlainText(_format_preflight_preview(preview))

    def _show_submit_result(self) -> None:
        if not self._record_action(DOWNLOAD_REQUEST_BUILDER_SUBMIT_ACTION_ID):
            return
        if self._summary_text is None:
            return

        draft = self.current_draft()
        issues = _validate_draft(draft)
        if issues:
            self._summary_text.setPlainText(_format_local_submit_blocked(issues))
            return

        if draft.workflow_mode == OHLCV_MAINTENANCE_WORKFLOW_MODE:
            self._summary_text.setPlainText(OHLCV_SUBMIT_DEFERRED_MESSAGE)
            return

        if self._on_submit_intent is None:
            self._summary_text.setPlainText("Download start is unavailable.")
            return

        try:
            result = self._on_submit_intent(draft)
        except Exception as error:
            self._summary_text.setPlainText(
                "Download start failed: " f"{type(error).__name__}: {error}"
            )
            self._set_progress_message(
                f"Download start failed: {type(error).__name__}: {error}"
            )
            return
        self._summary_text.setPlainText(_format_submit_result(result))
        self._apply_submit_progress(result)

    def _close_requested(self) -> None:
        if not self._record_action(DOWNLOAD_REQUEST_BUILDER_CLOSE_ACTION_ID):
            return
        self.close()

    def _record_action(self, action_id: str) -> bool:
        if self._action_observer is None:
            return True

        decision = self._action_observer.record_action(
            action_id,
            window_id=DOWNLOAD_REQUEST_BUILDER_METADATA_ID,
            metadata={"workflow_mode": self._workflow_mode},
        )
        return decision.allowed

    def _apply_submit_progress(self, result: object) -> None:
        status = getattr(result, "sandbox_execution_status", None)
        if status is None:
            return

        if getattr(result, "sandbox_execution_completed", False) is True:
            if self._progress_total_bar is not None:
                self._progress_total_bar.setValue(100)
            for timeframe in tuple(
                getattr(result, "sandbox_timeframes_completed", ())
            ):
                bar = self._progress_timeframe_bars.get(timeframe)
                if bar is not None:
                    bar.setValue(100)
            self._set_progress_message(_format_sandbox_progress_message(result))
            return

        if self._progress_total_bar is not None:
            self._progress_total_bar.setValue(0)
        self._set_progress_message(str(getattr(result, "sandbox_execution_message", "")))

    def _set_progress_message(self, message: str) -> None:
        if self._progress_messages is not None:
            self._progress_messages.setPlainText(message)


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
    timeframes = _selected_timeframes(field_widgets["timeframes"])
    limit_widget = field_widgets["limit"]
    limit_value, limit_error = _parse_limit(
        _text_field_value(limit_widget),
        max_limit=_limit_max(limit_widget),
    )
    metadata = {"limit": limit_value} if limit_value is not None else {}
    range_mode = "explicit"
    return DownloadRequestDraft(
        workflow_mode=workflow_mode,
        source_provider=_text_field_value(field_widgets["source_provider"]),
        market=_text_field_value(field_widgets["market"]),
        symbols=_single_symbol_tuple(_text_field_value(field_widgets["symbols"])),
        timeframe_mode="explicit",
        timeframes=timeframes,
        range_mode=range_mode,
        start=_text_field_value(field_widgets["start"]),
        end=_text_field_value(field_widgets["end"]),
        conflict_policy="skip_existing",
        priority="normal",
        connection_ref="",
        websocket_required=False,
        tags=(),
        metadata=metadata,
        metadata_parse_error=limit_error,
    )


def _field_label(field_id: str, label_text: str) -> QLabel:
    label = QLabel(label_text)
    label.setObjectName(f"download_request_builder.{field_id}.label")
    return label


def _normalize_option_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError("option values must be strings")
        candidate = value.strip()
        if candidate and candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)
    return tuple(normalized)


def _selected_timeframes(widget: QWidget) -> tuple[str, ...]:
    return tuple(
        checkbox.text().strip()
        for checkbox in widget.findChildren(QCheckBox)
        if checkbox.isChecked() and checkbox.text().strip()
    )


def _parse_limit(value: str, *, max_limit: int | None) -> tuple[int | None, str | None]:
    if not value:
        return None, "Limit is required."
    try:
        parsed = int(value)
    except ValueError:
        return None, "Limit must be a positive integer."
    if parsed < 1:
        return None, "Limit must be a positive integer."
    if max_limit is not None and parsed > max_limit:
        return None, f"Limit must be less than or equal to {max_limit}."
    return parsed, None


def _limit_max(widget: QWidget) -> int | None:
    value = widget.property("download_request_builder.limit_max")
    return value if isinstance(value, int) else None


def _validate_draft(draft: DownloadRequestDraft) -> tuple[DownloadDraftIssue, ...]:
    issues: list[DownloadDraftIssue] = []
    if not draft.source_provider:
        issues.append(
            DownloadDraftIssue(
                field_id="source_provider",
                severity="error",
                message="Exchange is required.",
            )
        )
    if not draft.market:
        issues.append(
            DownloadDraftIssue(
                field_id="market",
                severity="error",
                message="Market Type is required.",
            )
        )
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
                field_id="limit",
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


def _selection_recap_values(draft: DownloadRequestDraft) -> dict[str, str]:
    selection_drafts = download_data_selection_drafts_from_request_draft(draft)
    warnings = _unique_strings(
        warning
        for selection in selection_drafts
        for warning in selection.warnings
    )
    blockers = list(
        _unique_strings(
            blocker
            for selection in selection_drafts
            for blocker in selection.blockers
        )
    )
    if draft.metadata_parse_error is not None:
        blockers.append(draft.metadata_parse_error)

    item_count = 0
    complete_selection = bool(selection_drafts) and not blockers
    for selection in selection_drafts:
        if not selection.selection_complete:
            complete_selection = False
            continue
        summary = download_data_selection_summary_from_selection_draft(selection)
        item_count += summary.item_count

    state = (
        f"Selection complete - ready for preflight ({item_count} items)"
        if complete_selection
        else "Selection incomplete"
    )
    return {
        "exchange": _format_optional_sequence(
            tuple(selection.exchange_id for selection in selection_drafts)
        ),
        "market_type": _format_optional_sequence(
            tuple(selection.market_type for selection in selection_drafts)
        ),
        "symbols": _format_optional_sequence(
            tuple(selection.symbol for selection in selection_drafts)
        ),
        "timeframes": _format_selected_timeframes(selection_drafts),
        "limit": _display_optional(dict(draft.metadata).get("limit")),
        "state": state,
        "warnings": _format_sequence(warnings),
        "blockers": _format_sequence(tuple(blockers)),
    }


def _format_draft_summary(
    draft: DownloadRequestDraft,
    issues: tuple[DownloadDraftIssue, ...],
) -> str:
    limit_display = _display_optional(dict(draft.metadata).get("limit"))
    lines = [
        f"Exchange: {_display_value(draft.source_provider)}",
        f"Market Type: {_display_value(draft.market)}",
        f"Symbol: {_format_sequence(draft.symbols)}",
        f"Timeframes: {len(draft.timeframes)} ({_format_sequence(draft.timeframes)})",
        f"Start: {_display_value(draft.start)}",
        f"End: {_display_value(draft.end)}",
        f"Limit: {limit_display}",
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


def _format_local_submit_blocked(
    issues: tuple[DownloadDraftIssue, ...],
) -> str:
    lines = ["Download start blocked by local validation issues:"]
    for issue in issues:
        lines.append(f"- {issue.severity.upper()} {issue.field_id}: {issue.message}")
    return "\n".join(lines)


def _format_preflight_preview(preview: object) -> str:
    issues = tuple(getattr(preview, "issues", ()))
    lines = [
        "Preflight preview result:",
        (
            "Structural preflight preview only. Provider range checks, storage "
            "checks, update/new-file detection, and execution are not performed "
            "in this shell yet."
        ),
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


def _format_submit_result(result: object) -> str:
    issues = tuple(getattr(result, "issues", ()))
    lines = [
        "Download start result:",
        f"Message: {getattr(result, 'message', '')}",
        f"Accepted: {getattr(result, 'accepted', False)}",
        f"Request ID: {getattr(result, 'request_id', '')}",
        f"Status: {getattr(result, 'status', '')}",
        f"Can run: {getattr(result, 'can_run', False)}",
        f"Item count: {getattr(result, 'item_count', 0)}",
        f"Estimated items: {_display_optional(getattr(result, 'estimated_items', None))}",
        f"Runtime visible: {getattr(result, 'runtime_visible', False)}",
        (
            "Execution plan created: "
            f"{_display_yes_no(getattr(result, 'execution_plan_created', False))}"
        ),
        (
            "Execution plan ID: "
            f"{_display_optional(getattr(result, 'execution_plan_id', None))}"
        ),
        (
            "Execution plan message: "
            f"{getattr(result, 'execution_plan_message', '')}"
        ),
        (
            "Execution plan phase: "
            f"{_display_optional(getattr(result, 'execution_plan_phase', None))}"
        ),
        (
            "Execution plan ready: "
            f"{_display_yes_no(getattr(result, 'execution_plan_ready', False))}"
        ),
        (
            "Execution plan blocked: "
            f"{_display_yes_no(getattr(result, 'execution_plan_blocked', False))}"
        ),
    ]
    sandbox_status = getattr(result, "sandbox_execution_status", None)
    if sandbox_status is not None:
        lines.extend(
            (
                "",
                "Sandbox execution:",
                f"Status: {sandbox_status}",
                (
                    "Completed: "
                    f"{_display_yes_no(getattr(result, 'sandbox_execution_completed', False))}"
                ),
                f"Message: {getattr(result, 'sandbox_execution_message', '')}",
                (
                    "Sandbox root: "
                    f"{_display_optional(getattr(result, 'sandbox_root', None))}"
                ),
                (
                    "Bars written: "
                    f"{getattr(result, 'sandbox_bars_written', 0)}"
                ),
                (
                    "CSV path: "
                    f"{_format_sequence(tuple(getattr(result, 'sandbox_csv_paths', ())))}"
                ),
                (
                    "Metadata path: "
                    f"{_format_sequence(tuple(getattr(result, 'sandbox_metadata_paths', ())))}"
                ),
                (
                    "First timestamp: "
                    f"{_display_optional(getattr(result, 'sandbox_first_timestamp_ms', None))}"
                ),
                (
                    "Last timestamp: "
                    f"{_display_optional(getattr(result, 'sandbox_last_timestamp_ms', None))}"
                ),
                "Sandbox root notice: output is confined to the configured sandbox root.",
            )
        )
    lines.append("Submit issues:")
    if not issues:
        lines.append("- none")
    else:
        for issue in issues:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def _format_sandbox_progress_message(result: object) -> str:
    lines = [
        str(getattr(result, "sandbox_execution_message", "")),
        f"Bars written: {getattr(result, 'sandbox_bars_written', 0)}",
    ]
    csv_paths = tuple(getattr(result, "sandbox_csv_paths", ()))
    metadata_paths = tuple(getattr(result, "sandbox_metadata_paths", ()))
    if csv_paths:
        lines.append(f"CSV: {_format_sequence(csv_paths)}")
    if metadata_paths:
        lines.append(f"Metadata: {_format_sequence(metadata_paths)}")
    return "\n".join(line for line in lines if line)


def _text_field_value(widget: QWidget) -> str:
    if isinstance(widget, QComboBox):
        return widget.currentText().strip()
    if isinstance(widget, QTextEdit):
        return widget.toPlainText().strip()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    return ""


def _single_symbol_tuple(value: str) -> tuple[str, ...]:
    return (value,) if value else ()


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


def _display_yes_no(value: object) -> str:
    return "yes" if value is True else "no"


def _format_sequence(values: tuple[str, ...]) -> str:
    if not values:
        return "none"
    return ", ".join(values)


def _format_optional_sequence(values: tuple[str | None, ...]) -> str:
    normalized = _unique_strings(value for value in values if value)
    return _format_sequence(normalized) if normalized else "missing"


def _format_selected_timeframes(selection_drafts: tuple[object, ...]) -> str:
    timeframes = _unique_strings(
        timeframe
        for selection in selection_drafts
        for timeframe in getattr(selection, "selected_timeframes", ())
    )
    if not timeframes:
        return "none selected"
    return f"{len(timeframes)} ({_format_sequence(timeframes)})"


def _unique_strings(values: Iterable[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if candidate and candidate not in seen:
            normalized.append(candidate)
            seen.add(candidate)
    return tuple(normalized)
