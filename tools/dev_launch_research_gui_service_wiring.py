"""Launch the restored Research shell with real catalog and chart services."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.gui.research.composition import create_restored_research_suite
from leonardo.gui.style import apply_theme_stylesheet, load_default_theme
from leonardo.gui.window_tracking import GuiWindowTracker


def main() -> int:
    from PySide6.QtWidgets import QApplication

    config = replace(
        load_default_config(Path.cwd()),
        audit=AuditConfig(enabled=False),
    )
    app = LeonardoApp(config)
    context = app.startup()
    app.start_core_runtime()
    application = QApplication.instance() or QApplication([])
    apply_theme_stylesheet(application, load_default_theme())
    trackers: dict[str, GuiWindowTracker] = {}

    def track_window(widget, window_id, title, window_type) -> None:
        tracker = GuiWindowTracker(
            widget,
            window_id=window_id,
            title=title,
            window_type=window_type,
            registry=context.window_registry,
        )
        trackers[window_id] = tracker

    window, presenter = create_restored_research_suite(
        context.research_dataset_service,
        context.research_study_service,
        context.research_study_setup_service,
        context.research_workspace_snapshot_service,
        context.research_notebook_service,
        track_window,
    )
    window.show()
    try:
        return int(application.exec())
    finally:
        presenter.dispose()
        window.close()
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
