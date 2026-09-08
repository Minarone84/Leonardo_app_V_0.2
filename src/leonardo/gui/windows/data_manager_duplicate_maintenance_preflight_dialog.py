"""Read-only Duplicate Maintenance scan preflight."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager.models import DuplicateMaintenancePreflight
from leonardo.gui.window_geometry import apply_initial_window_size
from leonardo.gui.windows.shell_widgets import apply_identity


DATA_MANAGER_DUPLICATE_MAINTENANCE_PREFLIGHT_WINDOW_ID = (
    "data_manager.duplicate_maintenance.preflight.dialog"
)


class DataManagerDuplicateMaintenancePreflightDialog(QDialog):
    """Show exact scan scope and wait for explicit user authorization."""

    scan_requested = Signal(object)
    closing = Signal()

    def __init__(
        self,
        preflight: DuplicateMaintenancePreflight,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preflight = preflight
        self._closing_emitted = False
        self._labels: dict[str, QLabel] = {}
        apply_identity(
            self,
            DATA_MANAGER_DUPLICATE_MAINTENANCE_PREFLIGHT_WINDOW_ID,
            object_type="dialog",
        )
        self.setWindowTitle("Duplicate Maintenance")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        apply_initial_window_size(
            self,
            parent=parent,
            width_fraction=0.4,
            height_fraction=0.45,
        )

        root = QVBoxLayout(self)
        form = QFormLayout()
        for key, label in (
            ("domain", "Domain"),
            ("scope", "Scope"),
            ("objects", "Objects to check"),
            ("exchange", "Exchange"),
            ("market_type", "Market Type"),
            ("asset", "Asset"),
            ("timeframe", "Timeframe"),
            ("fingerprint", "Current OHLCV fingerprint"),
        ):
            value = QLabel(self)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(key == "fingerprint")
            apply_identity(
                value,
                f"data_manager.duplicate_maintenance.preflight.label.{key}",
                object_type="label",
            )
            self._labels[key] = value
            form.addRow(f"{label}:", value)
        root.addLayout(form)

        notice = QLabel(
            "This scan is read-only.\nNo objects will be modified.", self
        )
        apply_identity(
            notice,
            "data_manager.duplicate_maintenance.preflight.label.notice",
            object_type="label",
        )
        root.addWidget(notice)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.scan_button = QPushButton("Scan", self)
        apply_identity(
            self.scan_button,
            "data_manager.duplicate_maintenance.preflight.button.scan",
            object_type="button",
            display_label="Scan",
            action_id="data_manager.duplicate_maintenance.preflight.button.scan",
        )
        self.scan_button.clicked.connect(self._request_scan)
        actions.addWidget(self.scan_button)
        self.cancel_button = QPushButton("Cancel", self)
        apply_identity(
            self.cancel_button,
            "data_manager.duplicate_maintenance.preflight.button.cancel",
            object_type="button",
            display_label="Cancel",
            action_id="data_manager.duplicate_maintenance.preflight.button.cancel",
        )
        self.cancel_button.clicked.connect(self.close)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)
        self.set_preflight(preflight)

    @property
    def preflight(self) -> DuplicateMaintenancePreflight:
        return self._preflight

    def label_text(self, key: str) -> str:
        return self._labels[key].text()

    def set_preflight(self, preflight: DuplicateMaintenancePreflight) -> None:
        if not isinstance(preflight, DuplicateMaintenancePreflight):
            raise TypeError("preflight must be a DuplicateMaintenancePreflight")
        self._preflight = preflight
        self._labels["domain"].setText(preflight.domain.display_name)
        self._labels["scope"].setText(preflight.scope_label)
        self._labels["objects"].setText(str(preflight.objects_to_check))
        market = preflight.market_id
        source = preflight.source_ohlcv
        market_values = (
            ("", "", "", "")
            if market is None
            else (
                market.exchange,
                market.market_type,
                market.symbol,
                market.timeframe,
            )
        )
        for key, value in zip(
            ("exchange", "market_type", "asset", "timeframe"),
            market_values,
            strict=True,
        ):
            label = self._labels[key]
            label.setText(value)
            form_label = self.layout().itemAt(0).layout().labelForField(label)
            if form_label is not None:
                form_label.setVisible(market is not None)
            label.setVisible(market is not None)
        fingerprint = self._labels["fingerprint"]
        fingerprint.setText(
            ""
            if source is None
            else f"CSV {source.csv_sha256}; sidecar {source.sidecar_sha256}"
        )
        form_label = self.layout().itemAt(0).layout().labelForField(fingerprint)
        if form_label is not None:
            form_label.setVisible(source is not None)
        fingerprint.setVisible(source is not None)

    def _request_scan(self) -> None:
        self.scan_requested.emit(self._preflight)
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._closing_emitted:
            self._closing_emitted = True
            self.closing.emit()
        super().closeEvent(event)
