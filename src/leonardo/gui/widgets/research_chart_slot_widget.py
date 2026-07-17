"""One visual Research chart slot without domain or service ownership."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.gui.chart import CandlestickInteractionState
from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget
from leonardo.research import ResidentStudyProjection, ResidentVolumeProjection
from leonardo.research.study_presentation import StudyPresentation


class ResearchChartSlotWidget(QWidget):
    """Display one slot-local Task 1018 chart workspace."""

    activated = Signal(int)
    position_change_requested = Signal(int, int)
    go_to_requested = Signal(int)
    detach_requested = Signal(int)
    dock_requested = Signal(int)

    def __init__(self, slot_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if type(slot_id) is not int or not 1 <= slot_id <= 8:
            raise ValueError("slot_id must be an integer from 1 through 8")
        self._slot_id = slot_id
        self._market_id: MarketId | None = None
        self._activation_targets: set[QWidget] = set()
        self._activation_press_key: int | None = None
        prefix = f"research.chart_slot.{slot_id}"
        self.setObjectName(prefix)
        self.setProperty("active", False)
        self._header = QWidget(self)
        self._header.setObjectName(f"{prefix}.header")
        self._position = QLabel(f"Chart {slot_id}", self._header)
        self._position.setObjectName(f"{prefix}.label.workspace_position")
        self._legacy_position = QLabel("", self._header)
        self._legacy_position.setObjectName(f"{prefix}.label.position")
        self._legacy_position.setVisible(False)
        self._position_combo = QComboBox(self._header)
        self._position_combo.setObjectName(f"{prefix}.combo.workspace_position")
        for workspace_position in range(1, 9):
            self._position_combo.addItem(str(workspace_position), workspace_position)
        self._position_combo.setCurrentIndex(slot_id - 1)
        self._position_combo.currentIndexChanged.connect(
            self._on_workspace_position_changed
        )
        self._go_to = QPushButton("Go to Date", self._header)
        self._go_to.setObjectName(f"{prefix}.button.go_to")
        self._go_to.setEnabled(False)
        self._go_to.clicked.connect(lambda: self.go_to_requested.emit(self._slot_id))
        self._detach = QPushButton("Detach", self._header)
        self._detach.setObjectName(f"{prefix}.button.detach")
        self._detach.clicked.connect(self._on_detach_clicked)
        self._detached = False
        self._dataset = QLabel("No dataset", self._header)
        self._dataset.setObjectName(f"{prefix}.label.dataset")
        self._status = QLabel("Empty", self._header)
        self._status.setObjectName(f"{prefix}.label.status")
        self._progress = QProgressBar(self._header)
        self._progress.setObjectName(f"{prefix}.progress")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.setSpacing(6)
        header_layout.addWidget(self._position)
        header_layout.addWidget(self._position_combo)
        header_layout.addWidget(self._dataset, stretch=1)
        header_layout.addWidget(self._status)
        header_layout.addWidget(self._progress)
        header_layout.addWidget(self._go_to)
        header_layout.addWidget(self._detach)
        self._workspace = ChartPaneWorkspaceWidget(self)
        self._workspace.setObjectName(f"{prefix}.chart")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._header)
        layout.addWidget(self._workspace, stretch=1)
        self._install_activation_filter(self)

    @property
    def slot_id(self) -> int:
        return self._slot_id

    @property
    def market_id(self) -> MarketId | None:
        return self._market_id

    @property
    def chart_workspace(self) -> ChartPaneWorkspaceWidget:
        return self._workspace

    @property
    def chart_widget(self):
        return self._workspace.price_chart

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def dataset_text(self) -> str:
        return self._dataset.text()

    def set_active(self, active: bool) -> None:
        if type(active) is not bool:
            raise TypeError("active must be a boolean")
        if self.property("active") == active:
            return
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_dataset(self, market_id: MarketId | None) -> None:
        if market_id is not None and not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        self._market_id = market_id
        self._dataset.setText("No dataset" if market_id is None else market_id.as_key())

    def set_go_to_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        self._go_to.setEnabled(enabled)

    def set_workspace_position(self, workspace_position: int) -> None:
        if type(workspace_position) is not int or not 1 <= workspace_position <= 8:
            raise ValueError("workspace_position must be an integer from 1 through 8")
        self._position_combo.blockSignals(True)
        self._position_combo.setCurrentIndex(workspace_position - 1)
        self._position_combo.blockSignals(False)

    def set_detached(self, detached: bool) -> None:
        if type(detached) is not bool:
            raise TypeError("detached must be a boolean")
        self._detached = detached
        self._position_combo.setEnabled(not detached)
        self._detach.setText("Dock" if detached else "Detach")

    def set_status(self, message: str) -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self._status.setText(message)

    def set_progress(self, current: int | None, total: int | None) -> None:
        if current is None or total is None or total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(max(0, min(current, total)))

    def set_busy(self, busy: bool) -> None:
        if type(busy) is not bool:
            raise TypeError("busy must be a boolean")
        self._progress.setVisible(busy)
        if not busy:
            self._progress.setRange(0, 1)
            self._progress.setValue(0)

    def show_interaction_state(
        self,
        state: CandlestickInteractionState,
        volume_projection: ResidentVolumeProjection | None,
    ) -> None:
        self._workspace.apply_chart_state(state, volume_projection)

    def set_study_state(
        self,
        projections: tuple[ResidentStudyProjection, ...],
        presentations: tuple[StudyPresentation, ...],
    ) -> None:
        self._workspace.apply_study_state(projections, presentations)
        self._workspace.refresh_from_shared_state()
        self._workspace.price_chart.repaint()

    def clear_chart_state(self) -> None:
        self._workspace.clear()
        self._workspace.set_volume_visible(False)
        self.set_dataset(None)
        self.set_go_to_enabled(False)
        self.set_busy(False)
        self.set_status("Empty")

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._install_activation_filter(child)
        elif (
            event.type()
            in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if event.type() == QEvent.Type.MouseButtonPress:
                press_key = event.timestamp()
                if press_key != self._activation_press_key:
                    self._activation_press_key = press_key
                    self.activated.emit(self._slot_id)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._activation_press_key = None
        return super().eventFilter(watched, event)

    def _install_activation_filter(self, widget: QWidget) -> None:
        targets = (widget, *widget.findChildren(QWidget))
        for target in targets:
            if target not in self._activation_targets:
                target.installEventFilter(self)
                self._activation_targets.add(target)

    def _on_workspace_position_changed(self, _index: int) -> None:
        position = self._position_combo.currentData()
        if type(position) is int:
            self.position_change_requested.emit(self._slot_id, position)

    def _on_detach_clicked(self) -> None:
        if self._detached:
            self.dock_requested.emit(self._slot_id)
        else:
            self.detach_requested.emit(self._slot_id)
