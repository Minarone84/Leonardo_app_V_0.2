"""Single-chart historical Research Suite window."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.chart.candlestick_widget import CandlestickChartWidget
from leonardo.gui.chart.interaction import CandlestickInteractionState
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.windows.shell_widgets import apply_identity
from leonardo.research import AcceptedDatasetSummary, ResidentVolumeProjection

RESEARCH_SUITE_WINDOW_ID = "research_suite.window"


class ResearchSuiteWindow(QWidget):
    """Present one accepted historical dataset through the Research chart."""

    refresh_requested = Signal()
    open_requested = Signal()
    cancel_requested = Signal()
    closed = Signal()

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._controls: dict[str, QPushButton] = {}
        self._datasets: tuple[AcceptedDatasetSummary, ...] = ()
        self._dataset_combo: QComboBox | None = None
        self._status_label: QLabel | None = None
        self._dataset_details: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._log_area: QTextEdit | None = None
        self._chart_workspace = ChartPaneWorkspaceWidget(self)
        self._chart = self._chart_workspace.price_chart

        self._apply_window_defaults()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_window()
        self.load_empty_state()

    @property
    def chart_widget(self) -> CandlestickChartWidget:
        return self._chart

    @property
    def chart_workspace(self) -> ChartPaneWorkspaceWidget:
        return self._chart_workspace

    @property
    def volume_visible(self) -> bool:
        return self._chart_workspace.volume_visible

    def button_for_id(self, button_id: str) -> QPushButton:
        try:
            return self._controls[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Research Suite button: {button_id}") from error

    def status_text(self) -> str:
        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        return "" if self._log_area is None else self._log_area.toPlainText()

    def selected_market_id(self) -> MarketId | None:
        combo = self._require_dataset_combo()
        index = combo.currentIndex()
        if not 0 <= index < len(self._datasets):
            return None
        return self._datasets[index].market_id

    def set_catalog(self, datasets: Sequence[AcceptedDatasetSummary]) -> None:
        normalized = tuple(datasets)
        if any(not isinstance(item, AcceptedDatasetSummary) for item in normalized):
            raise TypeError("datasets must contain AcceptedDatasetSummary values")
        previous = self.selected_market_id()
        self._datasets = normalized
        combo = self._require_dataset_combo()
        combo.blockSignals(True)
        combo.clear()
        for item in normalized:
            market = item.market_id
            combo.addItem(
                f"{market.exchange} | {market.market_type} | "
                f"{market.symbol} | {market.timeframe}"
            )
        if previous is not None:
            for index, item in enumerate(normalized):
                if item.market_id == previous:
                    combo.setCurrentIndex(index)
                    break
        combo.blockSignals(False)
        if normalized and combo.currentIndex() < 0:
            combo.setCurrentIndex(0)
        self._update_dataset_details()
        self._set_open_enabled(bool(normalized))

    def set_status(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if self._status_label is not None:
            self._status_label.setText(message)

    def append_status(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if self._log_area is not None:
            self._log_area.append(message)

    def set_progress(self, current: int | None, total: int | None) -> None:
        progress = self._progress
        if progress is None:
            return
        if current is None or total is None or total <= 0:
            progress.setRange(0, 0)
            return
        progress.setRange(0, total)
        progress.setValue(max(0, min(current, total)))

    def set_busy(self, busy: bool, *, can_cancel: bool = True) -> None:
        if type(busy) is not bool or type(can_cancel) is not bool:
            raise TypeError("busy and can_cancel must be booleans")
        self._require_dataset_combo().setEnabled(not busy)
        self._controls["research_suite.button.refresh"].setEnabled(not busy)
        self._set_open_enabled(not busy and bool(self._datasets))
        self._controls["research_suite.button.cancel"].setEnabled(busy and can_cancel)
        if not busy and self._progress is not None:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)

    def show_interaction_state(
        self,
        state: CandlestickInteractionState,
        *,
        volume_projection: ResidentVolumeProjection | None = None,
    ) -> None:
        self._chart_workspace.apply_chart_state(state, volume_projection)
        autoscale = self._controls["research_suite.button.toggle_autoscale"]
        autoscale.setEnabled(True)
        self._sync_autoscale_button()
        self._controls["research_suite.button.toggle_volume"].setEnabled(
            volume_projection is not None
        )

    def clear_chart(self) -> None:
        self._chart_workspace.clear()
        self._chart_workspace.set_volume_visible(False)
        autoscale = self._controls.get("research_suite.button.toggle_autoscale")
        if autoscale is not None:
            autoscale.setText("Disable Autoscale")
            autoscale.setEnabled(False)
        toggle = self._controls.get("research_suite.button.toggle_volume")
        if toggle is not None:
            toggle.setText("Show Volume")
            toggle.setEnabled(False)

    def load_empty_state(self) -> None:
        self._datasets = ()
        combo = self._require_dataset_combo()
        combo.clear()
        self._update_dataset_details()
        self.clear_chart()
        self.set_busy(False)
        self.set_status("Research services are not connected")
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText(
                "Research dataset and chart workflow messages will appear here."
            )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closed.emit()
        super().closeEvent(event)

    def _apply_window_defaults(self) -> None:
        self.setWindowTitle("Research Suite")
        self.setObjectName("research_suite_window")
        self.setProperty("object_id", RESEARCH_SUITE_WINDOW_ID)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1320, 860)
        font = self.font()
        font.setPointSize(12)
        self.setFont(font)

    def _build_window(self) -> None:
        root = QVBoxLayout(self)
        apply_identity(root, "research_suite.layout.root", object_type="layout")
        root.addWidget(self._build_header())
        root.addWidget(self._build_dataset_controls())
        chart_panel = QGroupBox("Historical Chart Workspace", self)
        apply_identity(
            chart_panel,
            "research_suite.panel.chart",
            object_type="panel",
            appearance_role="chart_panel",
        )
        chart_layout = QVBoxLayout(chart_panel)
        apply_identity(
            chart_layout,
            "research_suite.layout.chart",
            object_type="layout",
        )
        toolbar = QHBoxLayout()
        apply_identity(
            toolbar,
            "research_suite.layout.chart_toolbar",
            object_type="layout",
        )
        toolbar.addStretch(1)
        autoscale_toggle = self._button(
            chart_panel,
            "research_suite.button.toggle_autoscale",
            "Disable Autoscale",
            self._toggle_autoscale,
        )
        autoscale_toggle.setEnabled(False)
        toolbar.addWidget(autoscale_toggle)
        volume_toggle = self._button(
            chart_panel,
            "research_suite.button.toggle_volume",
            "Show Volume",
            self._toggle_volume,
        )
        volume_toggle.setEnabled(False)
        toolbar.addWidget(volume_toggle)
        chart_layout.addLayout(toolbar)
        chart_layout.addWidget(self._chart_workspace, stretch=1)
        root.addWidget(chart_panel, stretch=1)
        root.addWidget(self._build_status_panel())

    def _build_header(self) -> QWidget:
        header = QGroupBox("Research Suite", self)
        apply_identity(header, "research_suite.panel.header", object_type="panel")
        layout = QHBoxLayout(header)
        title = QLabel("Historical Research", header)
        apply_identity(
            title,
            "research_suite.label.title",
            object_type="label",
            display_label="Historical Research",
        )
        status = QLabel("Research services are not connected", header)
        apply_identity(
            status,
            "research_suite.label.status",
            object_type="status_label",
            display_label="Status",
        )
        self._status_label = status
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(status)
        return header

    def _build_dataset_controls(self) -> QWidget:
        panel = QGroupBox("Accepted OHLCV Dataset", self)
        apply_identity(
            panel,
            "research_suite.panel.dataset_selector",
            object_type="panel",
        )
        layout = QHBoxLayout(panel)
        label = QLabel("Dataset", panel)
        apply_identity(
            label,
            "research_suite.label.dataset",
            object_type="label",
        )
        combo = QComboBox(panel)
        apply_identity(
            combo,
            "research_suite.combo.accepted_dataset",
            object_type="combo_box",
            display_label="Accepted Dataset",
            tooltip="Only canonically accepted OHLCV datasets are listed.",
        )
        combo.currentIndexChanged.connect(self._update_dataset_details)
        self._dataset_combo = combo
        details = QLabel("No accepted datasets", panel)
        details.setWordWrap(True)
        apply_identity(
            details,
            "research_suite.label.dataset_details",
            object_type="label",
            display_label="Dataset Details",
        )
        self._dataset_details = details

        refresh = self._button(
            panel,
            "research_suite.button.refresh",
            "Refresh Datasets",
            self._emit_refresh,
        )
        open_button = self._button(
            panel,
            "research_suite.button.open_chart",
            "Open Chart",
            self._emit_open,
        )
        cancel = self._button(
            panel,
            "research_suite.button.cancel",
            "Cancel",
            self._emit_cancel,
        )
        cancel.setEnabled(False)
        layout.addWidget(label)
        layout.addWidget(combo, stretch=1)
        layout.addWidget(details, stretch=2)
        layout.addWidget(refresh)
        layout.addWidget(open_button)
        layout.addWidget(cancel)
        return panel

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("Research Activity", self)
        apply_identity(
            panel,
            "research_suite.panel.activity",
            object_type="panel",
        )
        layout = QVBoxLayout(panel)
        progress = QProgressBar(panel)
        progress.setRange(0, 1)
        progress.setValue(0)
        apply_identity(
            progress,
            "research_suite.progress.operation",
            object_type="progress_bar",
        )
        log = QTextEdit(panel)
        log.setReadOnly(True)
        log.setMaximumHeight(110)
        apply_identity(
            log,
            "research_suite.log.activity",
            object_type="log",
        )
        self._progress = progress
        self._log_area = log
        layout.addWidget(progress)
        layout.addWidget(log)
        return panel

    def _button(
        self,
        parent: QWidget,
        object_id: str,
        label: str,
        callback,
    ) -> QPushButton:
        button = QPushButton(label, parent)
        apply_identity(
            button,
            object_id,
            object_type="button",
            display_label=label,
            tooltip="Local Research workflow control.",
        )
        button.clicked.connect(callback)
        self._controls[object_id] = button
        return button

    def _toggle_autoscale(self) -> None:
        enabled = not self._chart.autoscale_enabled
        self._chart.set_autoscale_enabled(enabled)
        self._sync_autoscale_button()

    def _sync_autoscale_button(self) -> None:
        button = self._controls["research_suite.button.toggle_autoscale"]
        button.setText(
            "Disable Autoscale"
            if self._chart.autoscale_enabled
            else "Enable Autoscale"
        )

    def _toggle_volume(self) -> None:
        visible = not self._chart_workspace.volume_visible
        self._chart_workspace.set_volume_visible(visible)
        self._controls["research_suite.button.toggle_volume"].setText(
            "Hide Volume" if visible else "Show Volume"
        )

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit()

    def _emit_open(self) -> None:
        self.open_requested.emit()

    def _emit_cancel(self) -> None:
        self.cancel_requested.emit()

    def _set_open_enabled(self, enabled: bool) -> None:
        self._controls["research_suite.button.open_chart"].setEnabled(enabled)

    def _require_dataset_combo(self) -> QComboBox:
        if self._dataset_combo is None:
            raise RuntimeError("Research dataset selector is not initialized")
        return self._dataset_combo

    def _update_dataset_details(self, *_args) -> None:
        details = self._dataset_details
        if details is None:
            return
        combo = self._require_dataset_combo()
        index = combo.currentIndex()
        if not 0 <= index < len(self._datasets):
            details.setText("No accepted datasets")
            return
        item = self._datasets[index]
        details.setText(
            f"{item.row_count:,} candles | "
            f"{item.first_timestamp_ms} → {item.last_timestamp_ms}"
        )
