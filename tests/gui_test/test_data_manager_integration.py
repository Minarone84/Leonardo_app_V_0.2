from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data_manager import DataManagerApplicationService
from leonardo.gui.composition import GuiCompositionRoot


def test_app_composes_one_functional_data_manager_service_and_window(tmp_path) -> None:
    qapp = QApplication.instance() or QApplication([])
    del qapp
    config = replace(load_default_config(tmp_path), audit=AuditConfig(enabled=False))
    app = LeonardoApp(config)
    app.startup()
    composition = GuiCompositionRoot(app.context)
    main = composition.create_main_window()
    try:
        assert isinstance(app.context.data_manager_service, DataManagerApplicationService)
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        QCoreApplication.processEvents()
        assert composition.data_manager_suite_window is not None
        assert composition.data_manager_suite_presenter is not None
        assert composition.data_manager_suite_window.isVisible()
    finally:
        main.close()
        QCoreApplication.processEvents()
        app.shutdown()
