from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QLabel,
    QLineEdit,
    QTimeEdit,
)

from leonardo.data import canonicalize_market_id
from leonardo.research import DatasetCatalogReport, HistoricalDataset
from tests.gui_test.test_research_gui_service_catalog import (
    _ControlledDatasetService,
    _complete_catalog,
    _dataset_bundle,
    _presenter,
    _select_complete_summary,
    _settle_qt,
)
from tests.gui_test.test_research_gui_service_chart_lifecycle import _open_pending


def _ready_chart(presenter, service) -> int:
    slot_id, load_id = _open_pending(presenter, service)
    service.complete(load_id)
    service.complete(service.pending_ids("resident")[-1])
    _settle_qt()
    return slot_id


def _submit_go_to(presenter, slot_id: int, timestamp_ms: int):
    presenter._open_go_to(slot_id)
    dialog = presenter._go_to_dialogs[slot_id]
    selected = datetime.fromtimestamp(timestamp_ms / 1_000, UTC)
    field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
    button = dialog.findChild(object, "research.go_to_dialog.button.go")
    field.setText(selected.strftime("%Y-%m-%d %H:%M"))
    button.click()
    _settle_qt()
    return dialog


def _large_bundle(row_count: int = 6_000):
    market = canonicalize_market_id("bybit", "linear", "BTCUSD", "1m")
    timestamps = tuple((index + 1) * 60_000 for index in range(row_count))
    values = tuple(float(100 + index) for index in range(row_count))
    dataset = HistoricalDataset(
        market_id=market,
        csv_path=_dataset_bundle()[0].csv_path,
        file_sha256="b" * 64,
        row_count=row_count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
        ts_ms=timestamps,
        open=values,
        high=tuple(value + 2 for value in values),
        low=tuple(value - 2 for value in values),
        close=tuple(value + 1 for value in values),
        volume=tuple(1_000.0 + index for index in range(row_count)),
    )
    summary = replace(
        _dataset_bundle()[1],
        market_id=market,
        file_sha256=dataset.file_sha256,
        row_count=row_count,
        first_timestamp_ms=timestamps[0],
        last_timestamp_ms=timestamps[-1],
    )
    return dataset, summary


def test_go_to_exact_nearest_tie_and_dataset_clamps() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        chart = presenter._chart_presenters[slot_id]
        timestamps = chart.session.dataset.ts_ms

        _submit_go_to(presenter, slot_id, timestamps[20])
        assert chart.viewport.center_index == 20

        _submit_go_to(presenter, slot_id, timestamps[20] + 60 * 60_000)
        assert chart.viewport.center_index == 20

        midpoint = timestamps[20] + ((timestamps[21] - timestamps[20]) // 2)
        _submit_go_to(presenter, slot_id, midpoint)
        assert chart.viewport.center_index == 20

        _submit_go_to(presenter, slot_id, 0)
        assert chart.viewport.center_index == 0
        _submit_go_to(
            presenter,
            slot_id,
            int(datetime(2099, 1, 1, tzinfo=UTC).timestamp() * 1_000),
        )
        assert chart.viewport.center_index == len(timestamps) - 1
    finally:
        presenter.dispose()
        window.close()


def test_go_to_dialog_is_reused_resets_to_current_utc_and_stale_is_ignored() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        panel.go_to_button.click()
        first = presenter._go_to_dialogs[slot_id]
        field = first.findChild(QLineEdit, "research.go_to_dialog.input")
        date = first.findChild(QDateEdit, "research.go_to_dialog.input.date")
        time = first.findChild(QTimeEdit, "research.go_to_dialog.input.time")
        error = first.findChild(QLabel, "research.go_to_dialog.label.error")
        calendar = first.findChild(
            QLabel, "research.go_to_dialog.icon.calendar"
        )
        clock = first.findChild(QLabel, "research.go_to_dialog.icon.clock")
        assert field.isVisible()
        assert field is not date.lineEdit()
        assert field.placeholderText() == "YYYY-MM-DD HH:mm"
        assert date.isVisible() and time.isVisible()
        assert calendar.isVisible() and clock.isVisible()
        assert calendar.text() == "📅"
        assert calendar.accessibleName() == "Calendar"
        assert calendar.toolTip() == "Select UTC date"
        assert clock.text() == "🕒"
        assert clock.accessibleName() == "Clock"
        assert clock.toolTip() == "Select UTC time"
        date.setDate(QDate(2001, 1, 1))
        time.setTime(QTime(1, 2))
        assert field.text() == "2001-01-01 01:02"
        field.setText("2025-04-03 07:08")
        field.editingFinished.emit()
        assert date.date() == QDate(2025, 4, 3)
        assert (time.time().hour(), time.time().minute()) == (7, 8)
        date.setDate(QDate(2001, 1, 1))
        time.setTime(QTime(1, 2))
        error.setText("old error")
        first._timestamp_ms = 123

        before = datetime.now(UTC).replace(second=0, microsecond=0)
        presenter._open_go_to(slot_id)
        after = datetime.now(UTC).replace(second=0, microsecond=0)
        assert presenter._go_to_dialogs[slot_id] is first
        reset = datetime(
            date.date().year(),
            date.date().month(),
            date.date().day(),
            time.time().hour(),
            time.time().minute(),
            tzinfo=UTC,
        )
        assert before <= reset <= after
        assert field.text() == reset.strftime("%Y-%m-%d %H:%M")
        assert error.text() == ""
        assert first.timestamp_ms is None

        session = presenter._workspace_state.session_for(slot_id)
        stale_timestamp = session.dataset.ts_ms[0]
        before = presenter._chart_presenters[slot_id].viewport.snapshot()
        panel.close_button.click()
        first._timestamp_ms = stale_timestamp
        first.accepted.emit()
        assert presenter._chart_presenters == {}
        assert before is not None
    finally:
        presenter.dispose()
        window.close()


def test_loading_chart_cannot_open_go_to_and_detached_chart_uses_same_runtime() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id, load_id = _open_pending(presenter, service)
        panel = window.workspace.chart_panel_for_slot(slot_id)
        assert not panel.go_to_button.isEnabled()
        presenter._open_go_to(slot_id)
        assert presenter._go_to_dialogs == {}

        service.complete(load_id)
        service.complete(service.pending_ids("resident")[-1])
        _settle_qt()
        chart = presenter._chart_presenters[slot_id]
        identities = (panel, chart, chart.session, chart.viewport)
        window.workspace.detach_chart(slot_id)
        _submit_go_to(presenter, slot_id, chart.session.dataset.ts_ms[10])
        assert chart.viewport.center_index == 10
        assert (panel, chart, chart.session, chart.viewport) == identities
    finally:
        presenter.dispose()
        window.close()


def test_out_of_resident_go_to_uses_canonical_refill_and_timeframe_hint() -> None:
    _qapp = QApplication.instance() or QApplication([])
    dataset, summary = _large_bundle()
    service = _ControlledDatasetService(dataset)
    from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
    from tests.gui_test.test_research_gui_service_catalog import _ControlledStudyService

    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService()
    )
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        _submit_go_to(presenter, slot_id, dataset.ts_ms[0])
        assert presenter._chart_presenters[slot_id].viewport.center_index == 0
        assert service.pending_ids("resident")
        dialog = presenter._go_to_dialogs[slot_id]
        hint = dialog.findChild(QLabel, "research.go_to_dialog.label.hint")
        assert hint.text() == "UTC date and time"
    finally:
        presenter.dispose()
        window.close()


@pytest.mark.parametrize("timeframe", ("1m", "1d", "1w", "1M"))
def test_mixed_timeframes_expose_date_time_controls_and_use_timeline(
    timeframe: str,
) -> None:
    _qapp = QApplication.instance() or QApplication([])
    dataset, summary = _dataset_bundle()
    market = canonicalize_market_id("bybit", "linear", "BTCUSD", timeframe)
    dataset = replace(dataset, market_id=market)
    summary = replace(summary, market_id=market)
    service = _ControlledDatasetService(dataset)
    from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
    from tests.gui_test.test_research_gui_service_catalog import _ControlledStudyService

    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, service, _ControlledStudyService()
    )
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slot_id = _ready_chart(presenter, service)
        presenter._open_go_to(slot_id)
        dialog = presenter._go_to_dialogs[slot_id]
        assert dialog.findChild(
            QLabel, "research.go_to_dialog.label.hint"
        ).text() == "UTC date and time"
        assert dialog.findChild(
            QDateEdit, "research.go_to_dialog.input.date"
        ).isVisible()
        assert dialog.findChild(
            QTimeEdit, "research.go_to_dialog.input.time"
        ).isVisible()
        field = dialog.findChild(QLineEdit, "research.go_to_dialog.input")
        date = dialog.findChild(
            QDateEdit, "research.go_to_dialog.input.date"
        )
        time = dialog.findChild(
            QTimeEdit, "research.go_to_dialog.input.time"
        )
        assert field.isVisible()
        assert field is not date.lineEdit()
        assert field.placeholderText() == "YYYY-MM-DD HH:mm"
        assert date.isVisible() and time.isVisible()
        assert dialog.findChild(
            QLabel, "research.go_to_dialog.icon.calendar"
        ).isVisible()
        assert dialog.findChild(
            QLabel, "research.go_to_dialog.icon.clock"
        ).isVisible()
        target = dataset.ts_ms[30]
        _submit_go_to(presenter, slot_id, target)
        selected = datetime.fromtimestamp(dialog.timestamp_ms / 1_000, UTC)
        expected_selected = datetime.fromtimestamp(target / 1_000, UTC)
        assert (selected.hour, selected.minute) == (
            expected_selected.hour,
            expected_selected.minute,
        )
        if hasattr(dataset, "nearest_global_index_for_timestamp"):
            expected = dataset.nearest_global_index_for_timestamp(
                dialog.timestamp_ms
            )
        else:
            expected = presenter._workspace_state.session_for(
                slot_id
            ).nearest_global_index_for_timestamp(dialog.timestamp_ms)
        assert presenter._chart_presenters[slot_id].viewport.center_index == expected
    finally:
        presenter.dispose()
        window.close()


def test_pan_anchor_off_on_multiple_detached_preserves_zoom_scale_and_no_feedback() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        slots = tuple(_ready_chart(presenter, service) for _ in range(3))
        source = presenter._chart_presenters[slots[0]]
        targets = tuple(presenter._chart_presenters[item] for item in slots[1:])
        window.workspace.detach_chart(slots[2])
        action = window.action_for_text("Pan Anchor")
        assert action.isEnabled() and not action.isChecked()
        before_off = tuple(item.viewport.snapshot() for item in targets)
        source.viewport.pan_left(8)
        source.chart_workspace.viewportChanged.emit(source.viewport.snapshot())
        assert tuple(item.viewport.snapshot() for item in targets) == before_off

        action.setChecked(True)
        target_visible = tuple(item.viewport.visible_count for item in targets)
        target_scales = tuple(item.interaction.price_scale.snapshot() for item in targets)
        source.viewport.pan_left(7)
        source.chart_workspace.viewportChanged.emit(source.viewport.snapshot())
        assert all(
            item.current_center_timestamp_ms() == source.current_center_timestamp_ms()
            for item in targets
        )
        assert tuple(item.viewport.visible_count for item in targets) == target_visible
        assert tuple(item.interaction.price_scale.snapshot() for item in targets) == target_scales
        assert presenter._pan_anchor_in_progress is False

        after_pan = tuple(item.viewport.snapshot() for item in targets)
        source.viewport.zoom_in_at(source.viewport.center_index, 0.5)
        source.chart_workspace.viewportChanged.emit(source.viewport.snapshot())
        assert tuple(item.viewport.snapshot() for item in targets) == after_pan

        source.go_to_timestamp_ms(source.session.dataset.ts_ms[5])
        assert tuple(item.viewport.snapshot() for item in targets) == after_pan
    finally:
        presenter.dispose()
        window.close()


def test_pan_anchor_skips_loading_target_without_changing_task_or_status() -> None:
    _qapp = QApplication.instance() or QApplication([])
    window, presenter, service, summary = _presenter()
    try:
        _complete_catalog(service, DatasetCatalogReport((summary,), ()))
        source_id = _ready_chart(presenter, service)
        target_id, target_load = _open_pending(presenter, service)
        target = presenter._chart_presenters[target_id]
        status = target.status_text
        presenter._set_pan_anchor_enabled(True)
        presenter._on_horizontal_pan(source_id)
        assert target.status_text == status == "Loading historical dataset"
        assert target._active_load_task_id == target_load
        assert target.viewport is None
    finally:
        presenter.dispose()
        window.close()
