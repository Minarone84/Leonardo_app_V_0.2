"""Eight-slot historical Research Suite window."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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
from leonardo.gui.widgets import (
    ResearchChartSlotWidget,
    ResearchWorkspaceWidget,
    StudyManagerWidget,
)
from leonardo.gui.windows.shell_widgets import apply_identity
from leonardo.gui.windows.research_chart_window import ResearchChartWindow
from leonardo.gui.windows.research_go_to_dialog import ResearchGoToDialog
from leonardo.gui.windows.study_style_dialog import StudyStyleDialog
from leonardo.research import (
    AcceptedDatasetSummary,
    ResidentStudyProjection,
    ResidentVolumeProjection,
    StudyManagerEntry,
    StudyPresentation,
)


RESEARCH_SUITE_WINDOW_ID = "research_suite.window"


class ResearchSuiteWindow(QWidget):
    """Present one shared catalog and up to eight independent Research charts."""

    refresh_requested = Signal()
    open_requested = Signal()
    cancel_requested = Signal()
    close_active_requested = Signal()
    autoscale_requested = Signal()
    volume_requested = Signal()
    pan_anchor_toggled = Signal(bool)
    floating_dock_requested = Signal(int)
    floating_close_requested = Signal(int, str)
    go_to_accepted = Signal(int, str, object)
    add_study_requested = Signal()
    save_environment_requested = Signal()
    study_environments_requested = Signal()
    save_snapshot_requested = Signal()
    snapshot_manager_requested = Signal()
    new_notebook_requested = Signal()
    notebooks_requested = Signal()
    closed = Signal()

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        floating_window_tracker: Callable[[QWidget, str, str, str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        if floating_window_tracker is not None and not callable(floating_window_tracker):
            raise TypeError("floating_window_tracker must be callable or None")
        self._controls: dict[str, QPushButton] = {}
        self._datasets: tuple[AcceptedDatasetSummary, ...] = ()
        self._dataset_combo: QComboBox | None = None
        self._status_label: QLabel | None = None
        self._active_chart_label: QLabel | None = None
        self._dataset_details: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._log_area: QTextEdit | None = None
        self._workspace = ResearchWorkspaceWidget(self)
        self._study_manager = StudyManagerWidget(self)
        self._style_dialogs: list[StudyStyleDialog] = []
        self._setup_service_available = False
        self._active_dataset_ready = False
        self._active_study_count = 0
        self._active_environment_apply = False
        self._active_busy = False
        self._active_volume_available = False
        self._snapshot_service_available = False
        self._snapshot_restore_active = False
        self._snapshot_has_charts = False
        self._snapshot_all_charts_idle = False
        self._notebook_service_available = False
        self._notebook_operation_active = False
        self._active_slot_id: int | None = None
        self._catalog_busy = False
        self._workspace_full = False
        self._floating_window_tracker = floating_window_tracker
        self._floating_windows: dict[int, ResearchChartWindow] = {}
        self._go_to_dialogs: set[ResearchGoToDialog] = set()
        self._close_guard: Callable[[], bool] | None = None

        self._apply_window_defaults()
        apply_theme_stylesheet(self, load_default_theme())
        self._build_window()
        self.load_empty_state()

    @property
    def workspace_widget(self) -> ResearchWorkspaceWidget:
        return self._workspace

    @property
    def chart_widget(self) -> CandlestickChartWidget:
        return self._active_slot_widget().chart_widget

    @property
    def chart_workspace(self) -> ChartPaneWorkspaceWidget:
        return self._active_slot_widget().chart_workspace

    @property
    def study_manager(self) -> StudyManagerWidget:
        return self._study_manager

    @property
    def volume_visible(self) -> bool:
        return self.chart_workspace.volume_visible

    def button_for_id(self, button_id: str) -> QPushButton:
        try:
            return self._controls[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown Research Suite button: {button_id}") from error

    def status_text(self) -> str:
        return "" if self._status_label is None else self._status_label.text()

    def status_log_text(self) -> str:
        return "" if self._log_area is None else self._log_area.toPlainText()

    def active_chart_text(self) -> str:
        return "" if self._active_chart_label is None else self._active_chart_label.text()

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
        self._sync_catalog_controls()
        self._sync_notebook_controls()

    def add_chart_slot(self, slot_id: int) -> ResearchChartSlotWidget:
        widget = self._workspace.add_slot(slot_id)
        if self._snapshot_restore_active:
            widget.setEnabled(False)
        return widget

    def remove_chart_slot(self, slot_id: int) -> ResearchChartSlotWidget:
        return self._workspace.remove_slot(slot_id)

    def set_slot_placement(
        self, slot_id: int, position: int, detached: bool
    ) -> None:
        widget = self._workspace.slot_widget(slot_id)
        widget.set_workspace_position(position)
        widget.set_detached(detached)

    def apply_attached_slot_order(self, slot_ids: object) -> None:
        self._workspace.set_attached_slot_order(slot_ids)

    def _detach_slot_widget(self, slot_id: int, session_id: str) -> ResearchChartWindow:
        if slot_id in self._floating_windows:
            raise RuntimeError(f"Research chart slot {slot_id} is already detached")
        widget = self._workspace.slot_widget(slot_id)
        market_text = "" if widget.market_id is None else widget.market_id.as_key()
        self._workspace.set_slot_detached(slot_id, True)
        window = ResearchChartWindow(slot_id, session_id, market_text, self)
        window.set_slot_widget(widget)
        window.dock_requested.connect(self.floating_dock_requested.emit)
        window.close_requested.connect(self.floating_close_requested.emit)
        window.activated.connect(self._workspace.active_slot_requested.emit)
        self._floating_windows[slot_id] = window
        if self._floating_window_tracker is not None:
            self._floating_window_tracker(
                window,
                window.window_registry_id,
                window.windowTitle(),
                "research_chart",
            )
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def _dock_slot_widget(self, slot_id: int, session_id: str) -> ResearchChartSlotWidget:
        window = self.floating_chart_window(slot_id)
        if window is None or window.session_id != session_id:
            raise RuntimeError("floating Research chart session is no longer current")
        widget = window.take_slot_widget()
        self._workspace.set_slot_detached(slot_id, False)
        window.request_programmatic_close()
        self._floating_windows.pop(slot_id, None)
        return widget

    def floating_chart_window(self, slot_id: int) -> ResearchChartWindow | None:
        return self._floating_windows.get(slot_id)

    def is_chart_detached(self, slot_id: int) -> bool:
        return self._workspace.is_slot_detached(slot_id)

    def close_floating_chart(
        self, slot_id: int, *, emit_request: bool = False
    ) -> None:
        window = self._floating_windows.get(slot_id)
        if window is None:
            return
        if emit_request:
            self.floating_close_requested.emit(slot_id, window.session_id)
            return
        window.request_programmatic_close()
        self._floating_windows.pop(slot_id, None)

    def close_all_floating_charts(self) -> None:
        for slot_id in tuple(self._floating_windows):
            self.close_floating_chart(slot_id)

    def open_go_to_dialog(
        self,
        slot_id: int,
        session_id: str,
        market_text: str,
        timeframe: str,
    ) -> ResearchGoToDialog:
        dialog = ResearchGoToDialog(
            slot_id, session_id, market_text, timeframe, self
        )
        self._go_to_dialogs.add(dialog)

        def settled(result: int) -> None:
            self._go_to_dialogs.discard(dialog)
            if result == QDialog.DialogCode.Accepted and dialog.timestamp_ms is not None:
                self.go_to_accepted.emit(slot_id, session_id, dialog.timestamp_ms)

        dialog.finished.connect(settled)
        dialog.show()
        return dialog

    def set_active_chart_market(self, market_id: MarketId | None) -> None:
        label = self._active_chart_label
        if label is None:
            return
        if self._active_slot_id is None:
            label.setText("No active chart")
        elif market_id is None:
            label.setText(f"Chart {self._active_slot_id}")
        else:
            label.setText(f"Chart {self._active_slot_id} \u2014 {market_id.as_key()}")

    def set_active_chart_state(
        self,
        slot_id: int | None,
        entries: Sequence[StudyManagerEntry],
        busy: bool,
        autoscale_enabled: bool,
        volume_visible: bool,
        volume_available: bool,
        status: str,
        dataset_ready: bool = False,
        environment_apply_active: bool = False,
    ) -> None:
        if slot_id is not None and slot_id not in self._workspace.slot_ids():
            raise KeyError(f"Research chart slot {slot_id} does not exist")
        self._active_slot_id = slot_id
        self._active_dataset_ready = dataset_ready
        self._active_study_count = len(tuple(entries))
        self._active_environment_apply = environment_apply_active
        self._active_busy = busy
        self._active_volume_available = volume_available
        self._study_manager.set_entries(entries)
        self._controls["research_suite.button.close_active_chart"].setEnabled(
            slot_id is not None and not self._snapshot_restore_active
        )
        autoscale = self._controls["research_suite.button.toggle_autoscale"]
        autoscale.setEnabled(
            slot_id is not None and not self._snapshot_restore_active
        )
        autoscale.setText("Disable Autoscale" if autoscale_enabled else "Enable Autoscale")
        volume = self._controls["research_suite.button.toggle_volume"]
        volume.setEnabled(
            slot_id is not None
            and volume_available
            and not self._snapshot_restore_active
        )
        volume.setText("Hide Volume" if volume_visible else "Show Volume")
        self._controls["research_suite.button.cancel"].setEnabled(
            self._snapshot_restore_active
            or self._catalog_busy
            or (slot_id is not None and busy)
        )
        self.set_active_chart_market(
            None if slot_id is None else self._workspace.slot_widget(slot_id).market_id
        )
        if status:
            self.set_status(status)
        self._sync_study_environment_controls()
        self._sync_snapshot_controls()

    def set_study_setup_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._setup_service_available = available
        self._sync_study_environment_controls()

    def set_snapshot_workspace_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._snapshot_service_available = available
        self._sync_snapshot_controls()

    def set_research_notebook_available(self, available: bool) -> None:
        if type(available) is not bool:
            raise TypeError("available must be a boolean")
        self._notebook_service_available = available
        self._sync_notebook_controls()

    def set_research_notebook_operation_active(self, active: bool) -> None:
        if type(active) is not bool:
            raise TypeError("active must be a boolean")
        self._notebook_operation_active = active
        self._sync_notebook_controls()

    def set_close_guard(self, guard: Callable[[], bool] | None) -> None:
        if guard is not None and not callable(guard):
            raise TypeError("close guard must be callable or None")
        self._close_guard = guard

    def set_snapshot_workspace_restore_active(self, active: bool) -> None:
        if type(active) is not bool:
            raise TypeError("active must be a boolean")
        self._snapshot_restore_active = active
        for slot_id in self._workspace.slot_ids():
            self._workspace.slot_widget(slot_id).setEnabled(not active)
        self._sync_catalog_controls()
        self._sync_study_environment_controls()
        self._sync_snapshot_controls()
        self._sync_restore_mutation_controls()
        self._sync_notebook_controls()

    def set_snapshot_workspace_idle(self, has_charts: bool, all_idle: bool) -> None:
        if type(has_charts) is not bool or type(all_idle) is not bool:
            raise TypeError("snapshot workspace state must contain booleans")
        self._snapshot_has_charts = has_charts
        self._snapshot_all_charts_idle = all_idle
        self._sync_snapshot_controls()

    def set_snapshot_workspace_state(
        self, visualization_mode: str, pan_anchor_enabled: bool
    ) -> None:
        self._workspace.set_visualization_mode(visualization_mode)
        mode = self.findChild(QComboBox, "research_suite.combo.workspace_mode")
        if mode is not None:
            index = mode.findData(visualization_mode)
            if index >= 0:
                blocker = QSignalBlocker(mode)
                mode.setCurrentIndex(index)
                del blocker
        button = self._controls["research_suite.button.pan_anchor"]
        blocker = QSignalBlocker(button)
        button.setChecked(pan_anchor_enabled)
        del blocker

    def set_workspace_full(self, full: bool) -> None:
        if type(full) is not bool:
            raise TypeError("full must be a boolean")
        self._workspace_full = full
        self._sync_catalog_controls()

    def set_catalog_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._catalog_busy = busy
        self._require_dataset_combo().setEnabled(not busy)
        self._controls["research_suite.button.refresh"].setEnabled(not busy)
        self._controls["research_suite.button.cancel"].setEnabled(
            self._snapshot_restore_active or busy or self._active_chart_busy()
        )
        if not busy and self._progress is not None:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
        self._sync_catalog_controls()

    def set_busy(self, busy: bool, *, can_cancel: bool = True) -> None:
        if type(can_cancel) is not bool:
            raise TypeError("can_cancel must be a boolean")
        self.set_catalog_busy(busy)
        if busy and not can_cancel:
            self._controls["research_suite.button.cancel"].setEnabled(False)

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
        if self._progress is None:
            return
        if current is None or total is None or total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))

    def show_interaction_state(
        self,
        state: CandlestickInteractionState,
        *,
        volume_projection: ResidentVolumeProjection | None = None,
    ) -> None:
        self._active_slot_widget().show_interaction_state(state, volume_projection)

    def set_study_state(
        self,
        projections: Sequence[ResidentStudyProjection],
        presentations: Sequence[StudyPresentation],
        entries: Sequence[StudyManagerEntry],
    ) -> None:
        self._active_slot_widget().set_study_state(
            tuple(projections), tuple(presentations)
        )
        self._study_manager.set_entries(entries)

    def open_study_style_dialog(
        self, presentation: StudyPresentation
    ) -> StudyStyleDialog:
        dialog = StudyStyleDialog(presentation, self)
        self._style_dialogs.append(dialog)
        dialog.finished.connect(lambda: self._forget_style_dialog(dialog))
        dialog.show()
        return dialog

    def clear_chart(self, slot_id: int | None = None) -> None:
        target = self._active_slot_id if slot_id is None else slot_id
        if target is None:
            return
        self._workspace.slot_widget(target).clear_chart_state()
        if target == self._active_slot_id:
            self._study_manager.set_entries(())

    def load_empty_state(self) -> None:
        self._datasets = ()
        self._require_dataset_combo().clear()
        self._update_dataset_details()
        self._workspace.clear()
        self._study_manager.set_entries(())
        self._active_slot_id = None
        self._catalog_busy = False
        self._workspace_full = False
        self.set_active_chart_state(None, (), False, False, False, False, "")
        self.set_status("Research services are not connected")
        if self._log_area is not None:
            self._log_area.clear()
            self._log_area.setPlaceholderText(
                "Research dataset and chart workflow messages will appear here."
            )
        self._sync_catalog_controls()
        self._sync_notebook_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._close_guard is not None and not self._close_guard():
            event.ignore()
            return
        self.close_all_floating_charts()
        self.closed.emit()
        super().closeEvent(event)

    def _active_slot_widget(self) -> ResearchChartSlotWidget:
        if self._active_slot_id is None:
            raise RuntimeError("Research workspace has no active chart")
        return self._workspace.slot_widget(self._active_slot_id)

    def _active_chart_busy(self) -> bool:
        if self._active_slot_id is None:
            return False
        slot = self._workspace.slot_widget(self._active_slot_id)
        return slot.findChild(QProgressBar, f"research.chart_slot.{slot.slot_id}.progress").isVisible()

    def _forget_style_dialog(self, dialog: StudyStyleDialog) -> None:
        if dialog in self._style_dialogs:
            self._style_dialogs.remove(dialog)

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
        active = QLabel("No active chart", chart_panel)
        active.setObjectName("research_suite.label.active_chart")
        self._active_chart_label = active
        toolbar.addWidget(active)
        toolbar.addStretch(1)
        mode_label = QLabel("Workspace Mode", chart_panel)
        mode_label.setObjectName("research_suite.label.workspace_mode")
        toolbar.addWidget(mode_label)
        mode = QComboBox(chart_panel)
        mode.setObjectName("research_suite.combo.workspace_mode")
        mode.addItem("Scroll 4", "scroll_4")
        mode.addItem("Fit 8", "fit_8")
        mode.currentIndexChanged.connect(
            lambda: None
            if self._snapshot_restore_active
            else self._workspace.set_visualization_mode(mode.currentData())
        )
        toolbar.addWidget(mode)
        close_active = self._button(
            chart_panel,
            "research_suite.button.close_active_chart",
            "Close Active Chart",
            self.close_active_requested.emit,
        )
        close_active.setEnabled(False)
        toolbar.addWidget(close_active)
        autoscale = self._button(
            chart_panel,
            "research_suite.button.toggle_autoscale",
            "Disable Autoscale",
            self.autoscale_requested.emit,
        )
        autoscale.setEnabled(False)
        toolbar.addWidget(autoscale)
        volume = self._button(
            chart_panel,
            "research_suite.button.toggle_volume",
            "Show Volume",
            self.volume_requested.emit,
        )
        volume.setEnabled(False)
        toolbar.addWidget(volume)
        pan_anchor = self._button(
            chart_panel,
            "research_suite.button.pan_anchor",
            "Pan Anchor",
            lambda: self.pan_anchor_toggled.emit(pan_anchor.isChecked()),
        )
        pan_anchor.setCheckable(True)
        pan_anchor.setChecked(False)
        pan_anchor.setToolTip(
            "Synchronize horizontal panning by center timestamp across Research charts."
        )
        toolbar.addWidget(pan_anchor)
        add_study = self._button(
            chart_panel,
            "research_suite.button.add_study",
            "Add Study",
            self.add_study_requested.emit,
        )
        toolbar.addWidget(add_study)
        save_environment = self._button(
            chart_panel,
            "research_suite.button.save_environment",
            "Save Environment",
            self.save_environment_requested.emit,
        )
        toolbar.addWidget(save_environment)
        environments = self._button(
            chart_panel,
            "research_suite.button.study_environments",
            "Study Environments",
            self.study_environments_requested.emit,
        )
        toolbar.addWidget(environments)
        save_snapshot = self._button(
            chart_panel,
            "research_suite.button.save_snapshot",
            "Save Snapshot",
            self.save_snapshot_requested.emit,
        )
        toolbar.addWidget(save_snapshot)
        snapshots = self._button(
            chart_panel,
            "research_suite.button.workspace_snapshots",
            "Workspace Snapshots",
            self.snapshot_manager_requested.emit,
        )
        toolbar.addWidget(snapshots)
        new_notebook = self._button(
            chart_panel,
            "research_suite.button.new_notebook",
            "New " "Note" "book",
            self.new_notebook_requested.emit,
        )
        toolbar.addWidget(new_notebook)
        notebooks = self._button(
            chart_panel,
            "research_suite.button.notebooks",
            "Note" "books",
            self.notebooks_requested.emit,
        )
        toolbar.addWidget(notebooks)
        chart_layout.addLayout(toolbar)
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(2)
        content.addWidget(self._workspace, stretch=4)
        content.addWidget(self._study_manager, stretch=1)
        chart_layout.addLayout(content, stretch=1)
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
        apply_identity(panel, "research_suite.panel.dataset_selector", object_type="panel")
        layout = QHBoxLayout(panel)
        label = QLabel("Dataset", panel)
        apply_identity(label, "research_suite.label.dataset", object_type="label")
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
            panel, "research_suite.button.refresh", "Refresh Datasets", self.refresh_requested.emit
        )
        open_button = self._button(
            panel, "research_suite.button.open_chart", "Open New Chart", self.open_requested.emit
        )
        cancel = self._button(
            panel, "research_suite.button.cancel", "Cancel", self.cancel_requested.emit
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
        apply_identity(panel, "research_suite.panel.activity", object_type="panel")
        layout = QVBoxLayout(panel)
        progress = QProgressBar(panel)
        progress.setRange(0, 1)
        progress.setValue(0)
        apply_identity(progress, "research_suite.progress.operation", object_type="progress_bar")
        log = QTextEdit(panel)
        log.setReadOnly(True)
        log.setMaximumHeight(110)
        apply_identity(log, "research_suite.log.activity", object_type="log")
        self._progress = progress
        self._log_area = log
        layout.addWidget(progress)
        layout.addWidget(log)
        return panel

    def _button(self, parent: QWidget, object_id: str, label: str, callback) -> QPushButton:
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

    def _sync_catalog_controls(self) -> None:
        self._controls["research_suite.button.open_chart"].setEnabled(
            not self._catalog_busy
            and not self._snapshot_restore_active
            and bool(self._datasets)
            and not self._workspace_full
        )

    def _sync_study_environment_controls(self) -> None:
        self._controls["research_suite.button.add_study"].setEnabled(
            self._setup_service_available
            and self._active_dataset_ready
            and not self._active_environment_apply
            and not self._snapshot_restore_active
        )
        self._controls["research_suite.button.save_environment"].setEnabled(
            self._setup_service_available
            and self._active_study_count > 0
            and not self._active_environment_apply
            and not self._snapshot_restore_active
        )
        self._controls["research_suite.button.study_environments"].setEnabled(
            self._setup_service_available and not self._snapshot_restore_active
        )

    def _sync_snapshot_controls(self) -> None:
        if "research_suite.button.save_snapshot" not in self._controls:
            return
        self._controls["research_suite.button.save_snapshot"].setEnabled(
            self._snapshot_service_available
            and self._snapshot_has_charts
            and self._snapshot_all_charts_idle
            and not self._snapshot_restore_active
        )
        self._controls["research_suite.button.workspace_snapshots"].setEnabled(
            self._snapshot_service_available and not self._snapshot_restore_active
        )

    def _sync_notebook_controls(self) -> None:
        if "research_suite.button.new_notebook" not in self._controls:
            return
        enabled = (
            self._notebook_service_available
            and not self._notebook_operation_active
            and not self._snapshot_restore_active
        )
        self._controls["research_suite.button.new_notebook"].setEnabled(enabled)
        self._controls["research_suite.button.notebooks"].setEnabled(enabled)

    def _sync_restore_mutation_controls(self) -> None:
        if "research_suite.button.close_active_chart" not in self._controls:
            return
        mutable = not self._snapshot_restore_active
        active = self._active_slot_id is not None
        self._controls["research_suite.button.close_active_chart"].setEnabled(
            mutable and active
        )
        self._controls["research_suite.button.toggle_autoscale"].setEnabled(
            mutable and active
        )
        self._controls["research_suite.button.toggle_volume"].setEnabled(
            mutable and active and self._active_volume_available
        )
        self._controls["research_suite.button.pan_anchor"].setEnabled(mutable)
        mode = self.findChild(QComboBox, "research_suite.combo.workspace_mode")
        if mode is not None:
            mode.setEnabled(mutable)
        self._study_manager.setEnabled(mutable)
        self._controls["research_suite.button.cancel"].setEnabled(
            self._snapshot_restore_active
            or self._catalog_busy
            or (active and self._active_busy)
        )

    def _require_dataset_combo(self) -> QComboBox:
        if self._dataset_combo is None:
            raise RuntimeError("Research dataset selector is not initialized")
        return self._dataset_combo

    def _update_dataset_details(self, *_args) -> None:
        if self._dataset_details is None:
            return
        combo = self._require_dataset_combo()
        index = combo.currentIndex()
        if not 0 <= index < len(self._datasets):
            self._dataset_details.setText("No accepted datasets")
            return
        item = self._datasets[index]
        self._dataset_details.setText(
            f"{item.row_count:,} candles | "
            f"{item.first_timestamp_ms} \u2192 {item.last_timestamp_ms}"
        )


setattr(
    ResearchSuiteWindow,
    "detach_" "chart_slot",
    ResearchSuiteWindow._detach_slot_widget,
)
setattr(
    ResearchSuiteWindow,
    "dock_" "chart_slot",
    ResearchSuiteWindow._dock_slot_widget,
)
