"""Leonardo GUI presentation settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.gui.display_time import (
    available_display_time_zones,
    current_display_time_zone_name,
    set_display_time_zone,
)
from leonardo.gui.windows.shell_widgets import apply_identity


class LeonardoSettingsDialog(QDialog):
    """Edit GUI-only Leonardo presentation settings."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings=None,
        application=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._application = application
        self._display_time_zone_changed = False
        self.setWindowTitle("Settings")
        self.setModal(True)
        apply_identity(self, "settings.dialog", object_type="dialog")

        layout = QVBoxLayout(self)
        presentation = QGroupBox("Presentation")
        apply_identity(
            presentation,
            "settings.group.presentation",
            object_type="group_box",
        )
        presentation_layout = QVBoxLayout(presentation)

        zone_label = QLabel("Display Time Zone")
        apply_identity(
            zone_label,
            "settings.label.display_time_zone",
            object_type="label",
        )
        presentation_layout.addWidget(zone_label)

        self.display_time_zone_combo = QComboBox()
        apply_identity(
            self.display_time_zone_combo,
            "settings.combo.display_time_zone",
            object_type="combo_box",
        )
        self.display_time_zone_combo.addItems(available_display_time_zones())
        current_zone = current_display_time_zone_name(
            application=self._application,
            settings=self._settings,
        )
        self.display_time_zone_combo.setCurrentIndex(
            self.display_time_zone_combo.findText(current_zone)
        )
        presentation_layout.addWidget(self.display_time_zone_combo)

        note = QLabel("Stored timestamps remain UTC. This setting changes display only.")
        apply_identity(
            note,
            "settings.label.display_time_note",
            object_type="label",
        )
        presentation_layout.addWidget(note)
        layout.addWidget(presentation)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_button = QPushButton("Save")
        apply_identity(save_button, "settings.button.save", object_type="button")
        save_button.clicked.connect(self._save)
        buttons.addWidget(save_button)
        cancel_button = QPushButton("Cancel")
        apply_identity(cancel_button, "settings.button.cancel", object_type="button")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

    @property
    def display_time_zone_changed(self) -> bool:
        """Return whether Save changed the active display time zone."""
        return self._display_time_zone_changed

    def _save(self) -> None:
        self._display_time_zone_changed = set_display_time_zone(
            self.display_time_zone_combo.currentText(),
            application=self._application,
            settings=self._settings,
        )
        self.accept()
