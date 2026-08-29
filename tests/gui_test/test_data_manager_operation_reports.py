from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextEdit

from leonardo.data import MarketId
from leonardo.gui.windows.data_manager_suite_window import DataManagerSuiteWindow
from tests.gui_test.test_data_manager_catalogs import empty_product_snapshot


def test_operation_surface_owns_context_status_message_and_conditional_notes() -> None:
    app = QApplication.instance() or QApplication([])
    del app
    window = DataManagerSuiteWindow()
    try:
        surface = window._operation_surface
        assert surface is not None
        assert {
            label.text() for label in surface.findChildren(QLabel)
        }.issuperset({"Operation", "Task ID", "State", "Context", "Status", "Message"})
        assert surface.findChild(QLabel, "data_manager.operation.context") is not None
        assert surface.findChild(QLabel, "data_manager.operation.status") is not None
        assert surface.findChild(QLabel, "data_manager.operation.message") is not None

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
        notes = surface.findChild(QLabel, "data_manager.operation.notes")
        assert notes is not None and not notes.isHidden()
        window.append_status("diagnostic two")
        assert surface.notes_text() == "diagnostic one\ndiagnostic two"
        assert window.status_log_text() == "diagnostic one\ndiagnostic two"

        surface.settle("failed", "diagnostic failure", (("Published", "no"),))
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
        assert notes.isHidden()
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
        revision = SimpleNamespace(
            collection_id="ac_123",
            revision_id="c" * 64,
            validation_state="valid",
            root_logical_artifact_ids=("a" * 64,),
            support_logical_artifact_ids=("b" * 64,),
            selected_outputs=(SimpleNamespace(
                logical_artifact_id="a" * 64,
                output_name="sma_20",
                column_name="signal",
            ),),
            first_timestamp_ms=1000,
            last_timestamp_ms=2000,
            database_ready=True,
        )
        window.set_artifact_update_result(
            SimpleNamespace(collection_revision=revision)
        )
        table = window._update_workspace.collection_validation_table
        assert table.item(0, 7).text() == "c" * 64
        assert table.item(0, 8).text() == "a" * 64
        assert table.item(0, 1).text().endswith("sma_20->signal")
        assert table.item(0, 2).text() == "1970-01-01 00:00:01 UTC"
        assert table.item(0, 3).text() == "1970-01-01 00:00:02 UTC"
        window.set_product_catalogs(empty_product_snapshot())
        assert table.item(0, 7).text() == "c" * 64

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
        values = {
            report.item(row, 0).text(): report.item(row, 1).text()
            for row in range(report.rowCount())
        }
        assert values == {
            "mode": "APPEND",
            "database_id": "db_123",
            "new_revision_id": "d" * 64,
            "previous_revision_id": "e" * 64,
            "collection_revision_id": "c" * 64,
            "rows": "100",
            "columns": "3",
            "First TS": "1970-01-01 00:00:01 UTC",
            "Last TS": "1970-01-01 00:00:02 UTC",
            "values_hash": "f" * 64,
        }
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

        accepted = window.confirm_database_rebuild(SimpleNamespace(
            database_id="db_123",
            database_revision_id="d" * 64,
            status="SCHEMA_CHANGED",
            source_change=SimpleNamespace(
                status="APPEND_ONLY",
                reason="column mapping changed",
            ),
            collection_revision_id="c" * 64,
        ))
        assert not accepted
        assert all(
            value in messages[-1]
            for value in (
                "db_123",
                "d" * 64,
                "SCHEMA_CHANGED",
                "APPEND_ONLY",
                "column mapping changed",
                "Target Artifact Collection revision",
                "new immutable Database revision",
                "Previous revisions remain unchanged",
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
