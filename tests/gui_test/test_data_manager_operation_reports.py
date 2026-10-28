from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
)

from leonardo.data import MarketId
from leonardo.gui.data_manager import operations as operation_module
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot


def test_dataset_evidence_attention_preserves_report_and_uses_one_smooth_pulse():
    from PySide6.QtCore import QAbstractAnimation, QVariantAnimation
    from PySide6.QtGui import QPalette

    app = QApplication.instance() or QApplication([])
    surface = operation_module.DataManagerOperationSurface()
    try:
        surface.begin("Existing operation")
        surface.set_task_id("existing-task")
        surface.append("Existing history")
        history = surface.notes_text()
        normal = surface.styleSheet()
        surface._status.setStyleSheet("QLabel { border: 1px solid #123456; }")
        normal_status = surface._status.styleSheet()
        surface.show()
        QApplication.processEvents()
        normal_palette = surface._status.palette()
        normal_font = surface._status.font()
        group_pixel = surface.grab().toImage().pixelColor(surface.width() - 15, surface.height() - 15)
        surface.set_dataset_evidence_attention(True, message="OHLCV evidence changed")
        assert surface._status.palette().color(QPalette.ColorRole.WindowText).name() == "#ff3b4d"
        assert surface._status.font().bold()
        assert "border: 2px solid #FF3B4D" in surface._status.styleSheet()
        animation = surface._attention_animation
        assert animation.duration() == 4000
        assert animation.loopCount() == -1
        assert [(key, color.name()) for key, color in animation.keyValues()] == [
            (0.0, "#142b45"), (0.5, "#315f8a"), (1.0, "#142b45")
        ]
        assert animation.state() == QAbstractAnimation.State.Running
        animation.pause()
        animation.setCurrentTime(2000)
        assert surface.grab().toImage().pixelColor(surface.width() - 15, surface.height() - 15) == group_pixel
        assert "#315f8a" in surface._status.styleSheet()
        assert surface._status.objectName() == "data_manager.operation.status"
        assert surface.styleSheet() == normal
        animation.setCurrentTime(0)
        assert "#142b45" in surface._status.styleSheet()
        assert surface.styleSheet() == normal
        animation.setCurrentTime(2000)
        animation.resume()
        surface.set_dataset_evidence_attention(True, message="Repeated evidence")
        assert surface.findChildren(QVariantAnimation) == [animation]
        assert animation.currentTime() == 2000
        assert surface.status_text() == "Repeated evidence"
        assert surface._name.text() == "Existing operation"
        assert surface._task_id.text() == "existing-task"
        assert surface.notes_text() == history
        surface.set_dataset_evidence_attention(False)
        surface.set_dataset_evidence_attention(False)
        assert animation.state() == QAbstractAnimation.State.Stopped
        assert surface.styleSheet() == normal
        assert surface._status.styleSheet() == normal_status
        assert surface._status.palette() == normal_palette
        assert surface._status.font() == normal_font
        surface.clear()
        surface.set_dataset_evidence_attention(True, message="Idle attention")
        assert surface._name.text() == "None"
        assert surface._task_id.text() == ""
    finally:
        surface.set_dataset_evidence_attention(False)
        surface.close()
        del app


def test_operation_surface_owns_current_report_history_and_readable_layout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        operation_module,
        "_operation_history_timestamp",
        lambda: "2026-09-05 18:12:04",
    )
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        window.show()
        QApplication.processEvents()
        surface = window._operation_surface
        assert surface is not None
        assert surface.layout().contentsMargins().top() >= 18
        assert surface.details.maximumHeight() > 130
        assert (
            surface.details.sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Expanding
        )
        assert {
            label.text() for label in surface.findChildren(QLabel)
        }.issuperset({"Operation", "Task ID", "State", "Context", "Status", "Message"})
        assert surface.findChild(QLabel, "data_manager.operation.context") is not None
        assert surface.findChild(QLabel, "data_manager.operation.status") is not None
        assert surface.findChild(QLabel, "data_manager.operation.message") is not None
        notes = surface.findChild(QLabel, "data_manager.operation.notes")
        assert notes is not None
        notes_scroll = next(
            scroll
            for scroll in surface.findChildren(QScrollArea)
            if scroll.widget() is notes
        )
        assert notes_scroll.minimumHeight() == 160
        assert notes_scroll.maximumHeight() == 200
        assert notes_scroll.isVisible()
        assert not notes.isHidden()
        assert surface.notes_text() == ""
        value_labels = tuple(
            surface.findChild(QLabel, object_id)
            for object_id in (
                "data_manager.operation.name",
                "data_manager.operation.task_id",
                "data_manager.operation.state",
                "data_manager.operation.context",
                "data_manager.operation.status",
                "data_manager.operation.message",
            )
        )
        assert all(label is not None for label in value_labels)
        assert all(label.minimumHeight() >= 30 for label in value_labels)
        assert all(label.margin() >= 5 for label in value_labels)
        form = surface.findChild(QFormLayout)
        assert form is not None
        form_labels = tuple(form.labelForField(label) for label in value_labels)
        assert all(isinstance(label, QLabel) for label in form_labels)
        assert all(label.minimumHeight() >= 30 for label in form_labels)
        assert all(label.margin() >= 5 for label in form_labels)
        assert surface.details.verticalHeader().minimumSectionSize() >= 32
        assert surface.details.verticalHeader().defaultSectionSize() >= 32

        window._set_selection_details("Loading accepted dataset...")
        window.set_status("Market inspection ready")
        window.set_busy(True, "preview_dataset")
        window.set_operation_task("task-preview")
        window.set_progress(1, 2, "Reading canonical values")
        assert surface.context_text() == "Loading accepted dataset..."
        assert surface.status_text() == "Operation in progress: preview_dataset"
        assert surface.findChild(
            QLabel, "data_manager.operation.message"
        ).text() == "Reading canonical values"

        window.set_status("Market inspection ready")
        window.append_status("diagnostic one")
        assert notes is not None and not notes.isHidden()
        assert (
            notes_scroll.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert not notes_scroll.isHidden()
        assert surface.notes_text() == (
            "[2026-09-05 18:12:04] INFO | diagnostic one"
        )
        window.append_status("diagnostic two")
        assert surface.notes_text() == (
            "[2026-09-05 18:12:04] INFO | diagnostic one\n"
            "[2026-09-05 18:12:04] INFO | diagnostic two"
        )
        assert window.status_log_text() == surface.notes_text()
        long_note = "\n".join(f"diagnostic line {index}" for index in range(40))
        window.append_status(long_note)
        QApplication.processEvents()
        assert surface.notes_text().endswith(long_note)
        assert notes_scroll.widget() is notes
        assert notes_scroll.verticalScrollBar().maximum() > 0

        surface.begin("create_direct_artifact")
        surface.settle("completed", "completed")
        completed_line = (
            "[2026-09-05 18:12:04] OK | create_direct_artifact | completed"
        )
        assert surface.notes_text().splitlines().count(completed_line) == 1

        surface.begin("delete_portable_recipe")
        surface.settle(
            "failed",
            "Portable Recipe is referenced by a Recipe Collection",
            (("Published", "no"),),
        )
        failure_line = (
            "[2026-09-05 18:12:04] ERROR | delete_portable_recipe | "
            "Portable Recipe is referenced by a Recipe Collection"
        )
        assert surface.notes_text().splitlines().count(failure_line) == 1
        assert surface.state == "failed"
        assert surface.details.item(0, 1).text() == "no"
        surface.clear()
        assert surface.state == "idle"
        assert surface.findChild(QLabel, "data_manager.operation.name").text() == "None"
        assert surface.findChild(QLabel, "data_manager.operation.task_id").text() == ""
        assert surface.findChild(QLabel, "data_manager.operation.message").text() == ""
        assert surface.details.rowCount() == 0
        assert surface.progress.minimum() == 0
        assert surface.progress.maximum() == 1
        assert surface.progress.value() == 0
        assert surface.notes_text() == ""
        assert not notes.isHidden()
        assert notes_scroll.isVisible()
        assert surface.context_text() == "Loading accepted dataset..."
        assert surface.status_text() == "Market inspection ready"
        assert surface.findChild(QTextEdit) is None
        assert surface.findChild(QTextEdit, "data_manager.operation.log") is None
    finally:
        window.close()


def test_terminal_report_survives_automatic_catalog_maintenance() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        window.set_busy(True, "build_database_revision")
        window.set_operation_task("task-build")
        window.set_progress(4, 10, "Publishing values")
        window.set_busy(False)
        window.settle_operation(
            "completed",
            "Database revision published",
            (("Database", "db_123"), ("Published", "yes")),
        )
        surface = window._operation_surface
        assert surface.state == "completed"
        assert surface.details.rowCount() == 2

        window.set_busy(
            True, "reconcile_status", preserve_operation=True
        )
        window.set_busy(False)
        assert surface.state == "completed"
        assert surface.details.item(1, 1).text() == "yes"
    finally:
        window.close()


def test_structured_update_results_populate_and_survive_catalog_refresh() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        window.set_artifact_update_result(
            SimpleNamespace(
                updated_logical_artifact_ids=("a" * 64, "b" * 64),
                recovered_logical_artifact_ids=("b" * 64,),
                reused_logical_artifact_ids=("c" * 64,),
                materialization=SimpleNamespace(
                    advanced_logical_artifact_ids=("a" * 64, "b" * 64),
                ),
            )
        )

        def fields(table):
            return {table.item(row, 0).text(): table.item(row, 1).text()
                    for row in range(table.rowCount())}

        table = window._update_workspace.artifact_report
        expected_artifact_report = {
            "Updated": "2",
            "Recovered managed heads (RECREATE)": "1",
            "Reused": "1",
            "Failed": "0",
            "Advanced logical Artifact IDs": ", ".join(("a" * 64, "b" * 64)),
        }
        assert fields(table) == expected_artifact_report
        window.set_product_catalogs(empty_product_snapshot())
        assert fields(table) == expected_artifact_report

        database = SimpleNamespace(
            database_id="db_123",
            revision_id="d" * 64,
            previous_revision_id="e" * 64,
            collection_revision_id="c" * 64,
            row_count=100,
            column_count=3,
            first_timestamp_ms=1000,
            last_timestamp_ms=2000,
            values_sha256="f" * 64,
        )
        window.set_database_update_result(
            SimpleNamespace(mode="APPEND", database_revision=database)
        )
        report = window._update_workspace.commit_report
        expected_database_report = {
            "Mode": "APPEND",
            "Database": "db_123",
            "New Revision": "d" * 64,
            "Previous Revision": "e" * 64,
            "Rows": "100",
            "Columns": "3",
            "Through": "1970-01-01 01:00:02 CET (+01:00)",
        }
        assert fields(report) == expected_database_report
        window.set_product_catalogs(empty_product_snapshot())
        assert fields(report) == expected_database_report
        assert fields(table) == expected_artifact_report
    finally:
        window.close()


def test_database_confirmations_present_immutable_publication_evidence(
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    messages: list[str] = []

    def answer(_parent, _title, message):
        messages.append(message)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    try:
        accepted = window.confirm_database_publication(
            database_identity="Research DB",
            market_id=MarketId("bybit", "linear", "BTCUSDT", "1m"),
            seed_id="seed_123",
            collection_id="ac_123",
            collection_revision_id="c" * 64,
            row_count=100,
            column_count=3,
            coverage="1000 - 2000",
            selected_columns=("close", "sma_20", "rsi_14"),
        )
        assert not accepted
        assert all(
            value in messages[-1]
            for value in (
                "Research DB",
                "bybit:linear:BTCUSDT:1m",
                "seed_123",
                "ac_123",
                "Rows: 100",
                "Columns: 3",
                "new immutable Database revision",
            )
        )

    finally:
        window.close()


def test_failed_operation_report_shows_error_and_publication_state() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        window.set_busy(True, "execute_database_append")
        window.settle_operation(
            "failed",
            "ValueError: incompatible revision",
            (("Error type", "ValueError"), ("Published", "no")),
        )
        assert window._operation_surface.state == "failed"
        assert window._operation_surface.details.item(1, 1).text() == "no"
    finally:
        window.close()
