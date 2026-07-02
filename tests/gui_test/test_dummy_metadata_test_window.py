import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTextEdit,
)

from leonardo.gui.windows.dummy_metadata_test_window import (  # noqa: E402
    DummyMetadataTestWindow,
    load_dummy_metadata_profile,
)


def test_dummy_metadata_effective_profile_loads() -> None:
    profile = load_dummy_metadata_profile()

    assert profile.metadata_id == "dummy_metadata_test.window"
    assert profile.values["identity"]["title"] == "Dummy Metadata Test Window"
    assert profile.report.has_errors is False


def test_dummy_window_constructs_without_core_services(qapplication: QApplication) -> None:
    profile = load_dummy_metadata_profile()
    window = DummyMetadataTestWindow(profile)

    assert window.profile is profile
    assert window.windowTitle() == "Dummy Metadata Test Window"
    assert window.objectName() == "dummy_metadata_test_window"

    window.close()
    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_action_buttons_come_from_metadata(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())

    expected_labels = {
        "dummy_metadata_test.refresh": "Refresh",
        "dummy_metadata_test.apply_mock": "Apply Mock",
        "dummy_metadata_test.reset_mock": "Reset Mock",
        "dummy_metadata_test.open_settings": "Open Settings",
        "dummy_metadata_test.close": "Close",
    }
    for action_id, label in expected_labels.items():
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.text() == label

    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_table_headers_come_from_metadata(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    table = window.findChild(QTableWidget, "dummy_metadata_test.results_table")

    assert table is not None
    assert table.columnCount() == 4
    assert [
        table.horizontalHeaderItem(index).text()
        for index in range(table.columnCount())
    ] == ["Item", "Status", "Value", "Details"]
    assert table.item(0, 0).text() == "alpha"

    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_representative_widgets_exist(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())

    assert window.findChild(QLabel, "dummy_metadata_test.title_label") is not None
    assert window.findChild(QLabel, "dummy_metadata_test.status_label") is not None
    assert window.findChild(QCheckBox, "dummy_metadata_test.enabled_checkbox") is not None
    assert window.findChild(QLineEdit, "dummy_metadata_test.name_input") is not None
    assert window.findChild(QComboBox, "dummy_metadata_test.mode_combo") is not None
    assert window.findChild(QTextEdit, "dummy_metadata_test.notes_text") is not None
    assert window.findChild(QTextEdit, "dummy_metadata_test.report_view") is not None
    assert window.findChild(QTextEdit, "dummy_metadata_test.diagnostics_view") is not None

    window.deleteLater()
    qapplication.processEvents()


def test_dummy_button_behavior_is_local_not_metadata_sourced(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    status = window.findChild(QLabel, "dummy_metadata_test.status_label")
    refresh = window.findChild(QPushButton, "dummy_metadata_test.refresh")

    assert status is not None
    assert refresh is not None
    refresh.click()
    qapplication.processEvents()

    assert status.text() == "Dummy refresh complete."
    assert "callback" not in window.profile.values["actions"]["dummy_metadata_test.refresh"]
    assert "handler" not in window.profile.values["actions"]["dummy_metadata_test.refresh"]

    window.deleteLater()
    qapplication.processEvents()


def test_dummy_close_action_closes_locally(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    close_button = window.findChild(QPushButton, "dummy_metadata_test.close")
    window.show()
    qapplication.processEvents()

    assert close_button is not None
    assert window.isVisible() is True
    close_button.click()
    qapplication.processEvents()

    assert window.close_requested_locally is True
    assert window.isVisible() is False
    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_can_be_destroyed_cleanly(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())
    window.show()
    qapplication.processEvents()

    window.close()
    window.deleteLater()
    qapplication.processEvents()

    assert window.close_requested_locally is True


def test_dummy_window_can_load_profile_by_default(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow()

    assert window.profile.metadata_id == "dummy_metadata_test.window"
    assert window.windowTitle() == "Dummy Metadata Test Window"

    window.deleteLater()
    qapplication.processEvents()


def test_dummy_window_has_expected_table_property(qapplication: QApplication) -> None:
    window = DummyMetadataTestWindow(load_dummy_metadata_profile())

    assert window.results_table.objectName() == "dummy_metadata_test.results_table"

    window.deleteLater()
    qapplication.processEvents()


def _qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qapplication() -> QApplication:
    return _qapplication()
