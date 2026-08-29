from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSize
from PySide6.QtWidgets import QApplication

from leonardo.core.app import LeonardoApp
from leonardo.core.config import AuditConfig, load_default_config
from leonardo.data_manager import DataManagerApplicationService
from leonardo.gui.composition import GuiCompositionRoot
from leonardo.gui.windows.data_manager_dataset_selector_dialog import (
    DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
)


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
        assert app.data_manager_creation_store is app.data_manager_domain.creation_store
        assert app.data_manager_creation_store.root_dir == config.paths.data_manager_dir
        assert not config.paths.data_manager_dir.exists()
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        QCoreApplication.processEvents()
        window = composition.data_manager_suite_window
        assert window is not None
        assert composition.data_manager_suite_presenter is not None
        assert window.isVisible()
        assert window.isMaximized()
        assert not window.isFullScreen()

        window.showNormal()
        window.resize(QSize(1110, 740))
        QCoreApplication.processEvents()
        assert not window.isMaximized()
        restored_size = window.size()
        main.action_for_id("main_window.open_data_manager_suite").trigger()
        QCoreApplication.processEvents()
        assert composition.data_manager_suite_window is window
        assert not window.isMaximized()
        assert not window.isFullScreen()
        assert window.size() == restored_size

        select_button = window.button_for_id("data_manager.button.select_dataset")
        select_button.click()
        QCoreApplication.processEvents()
        first = window.dataset_selector_dialog()
        assert first is not None
        assert first.isVisible()
        assert composition.tracker_for(DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID) is not None
        matching = tuple(
            item
            for item in app.context.window_registry.list_windows()
            if item.window_id == DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID
        )
        assert len(matching) == 1
        assert matching[0].status == "open"

        select_button.click()
        QCoreApplication.processEvents()
        assert window.dataset_selector_dialog() is first
        assert len(
            tuple(
                item
                for item in app.context.window_registry.list_windows()
                if item.window_id == DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID
            )
        ) == 1
    finally:
        main.close()
        QCoreApplication.processEvents()
        matching = tuple(
            item
            for item in app.context.window_registry.list_windows()
            if item.window_id == DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID
        )
        if matching:
            assert matching[0].status == "closed"
        app.shutdown()
