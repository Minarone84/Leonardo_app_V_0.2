"""R05: complete row insertion and deferred ownership of replaced pages."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QTabWidget, QTableWidget
from shiboken6 import isValid

from leonardo.data import MarketId
from leonardo.gui.windows.research_notebook_window import ResearchNotebookWindow
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1, ResearchNotebookDraft,
    ResearchNotebookNoteV1, ResearchNotebookPageV1,
)
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_store import ResearchNotebookStore


def _receipt(request, value):
    root = os.environ.get("R02_OBSERVATIONS")
    if root:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
        (path / (key + ".json")).write_text(
            json.dumps({"node": request.node.nodeid, **value}, indent=2) + "\n", encoding="utf-8")


def _page(symbol="BTCUSDT"):
    return ResearchNotebookPageV1(MarketId("bybit", "linear", symbol, "1h"),
        notes=(ResearchNotebookNoteV1("note_existing", 1000, "Retained note"),))


def _draft(pages=None):
    return ResearchNotebookDraft("R05 Notebook", "Disposable editor proof",
        ResearchNotebookAnnotationSettingsV1(), (_page(),) if pages is None else tuple(pages))


def _drain(app):
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    window = ResearchNotebookWindow()
    window.set_draft(_draft(), dirty=False)
    window.show()
    app.processEvents()
    yield app, window
    if isValid(window):
        window.deleteLater()
        _drain(app)


def _controls(window, kind, index=None):
    if index is not None:
        window._tabs.setCurrentIndex(index)
    container = window._tabs.currentWidget()
    names = {"note": (0, "notes"), "trade": (1, "trades"), "poi": (2, "poi")}
    category, table_name = names[kind]
    container.findChild(QTabWidget, "research.notebook_window.tabs.categories").setCurrentIndex(category)
    return (container.findChild(QTableWidget, "research.notebook_window.table." + table_name),
        container.findChild(QPushButton, "research.notebook_window.button.add_" + kind))


def _rows(table):
    return [{"id": table.cellWidget(row, 0).property("row_id"),
             "delete_id": table.cellWidget(row, 1).property("row_id"),
             "cells": [None if table.item(row, column) is None else table.item(row, column).text()
                       for column in range(2, table.columnCount())]}
            for row in range(table.rowCount())]


def test_actual_add_note_callback(editor, request):
    """PRE lane: old partial-row AttributeError must escape into the unchanged guard."""
    app, window = editor
    old = window.last_valid_draft
    changed = []
    window.draft_changed.connect(changed.append)
    table, button = _controls(window, "note")
    button.click()
    app.processEvents()
    _receipt(request, {"rows": _rows(table), "valid": window._current_valid,
        "dirty": window._dirty, "validation": window._validation.text(),
        "draft_signals": len(changed), "last_valid_preserved": window.last_valid_draft == old})
    assert table.rowCount() == 2
    assert all(table.item(1, col) is not None for col in range(2, 4))
    assert not window._current_valid and window._dirty and window._validation.text()
    assert not window._save.isEnabled() and not window._save_as.isEnabled()
    assert changed == [] and window.last_valid_draft == old


@pytest.mark.parametrize("pages", [1, 2])
@pytest.mark.parametrize("kind", ["note", "trade", "poi"])
def test_actual_add_complete_correct_save_go_delete(editor, request, tmp_path, monkeypatch, pages, kind):
    app, window = editor
    if pages == 2:
        window.add_page(ResearchNotebookPageV1(
            MarketId("bybit", "linear", "ETHUSDT", "1h"),
            notes=(ResearchNotebookNoteV1("note_eth", 1000, "Retained ETH note"),)))
        _drain(app)
    table, button = _controls(window, kind, pages - 1)
    original = window.current_draft()
    old_valid = window.last_valid_draft
    changed, saves, locations = [], [], []
    window.draft_changed.connect(changed.append)
    window.save_requested.connect(saves.append)
    window.go_to_requested.connect(lambda market, timestamp: locations.append((market, timestamp)))
    observations = []
    strict = window.current_draft
    def complete_draft():
        for current in window._tabs.currentWidget().findChildren(QTableWidget):
            for row in range(current.rowCount()):
                assert current.cellWidget(row, 0) is not None
                assert current.cellWidget(row, 1) is not None
                assert all(current.item(row, col) is not None for col in range(2, current.columnCount()))
        observations.append(_rows(table))
        return strict()
    monkeypatch.setattr(window, "current_draft", complete_draft)
    before_rows = table.rowCount()
    button.click()
    app.processEvents()
    assert len(observations) == 1
    assert table.rowCount() == before_rows + 1 and not table.signalsBlocked()
    assert window._dirty and not window._current_valid
    assert window._validation.text() and changed == []
    assert window.last_valid_draft == old_valid
    assert not window._save.isEnabled() and not window._save_as.isEnabled()
    row = before_rows
    new_id = table.cellWidget(row, 0).property("row_id")
    assert new_id.startswith(kind + "_")
    assert all(table.item(row, col).data(256) == new_id for col in range(2, table.columnCount()))
    table.item(row, 2).setText("1700000000000")
    if kind == "note":
        assert not window._current_valid
        table.item(row, 3).setText("New note")
    elif kind == "poi":
        assert not window._current_valid
        table.item(row, 4).setText("New point")
    assert window._current_valid and window._validation.text() == ""
    assert window._save.isEnabled() and window._save_as.isEnabled()
    assert len(changed) == 1 and changed[-1] == window.current_draft()
    valid = changed[-1]
    for prior_page in original.pages:
        current_page = next(page for page in valid.pages if page.market_id == prior_page.market_id)
        assert all(note in current_page.notes for note in prior_page.notes)
    if pages == 2:
        assert valid.pages[0] == original.pages[0]
    window._save.click()
    window._save_as.click()
    assert len(saves) == 2 and saves[0].draft == valid and saves[1].draft == valid
    assert saves[0].save_as is False and saves[1].save_as is True
    store = ResearchNotebookStore(tmp_path / "notebooks")
    service = ResearchNotebookService(store)
    stored = service.create_notebook(saves[0].draft)
    loaded = service.load_notebook(stored.notebook_id)
    assert loaded == stored and loaded.pages == valid.pages
    assert loaded.display_name == valid.display_name and loaded.description == valid.description
    assert loaded.annotation_settings == valid.annotation_settings
    disk = {str(p.relative_to(tmp_path)): {"bytes": p.stat().st_size,
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in tmp_path.rglob("*") if p.is_file()}
    assert disk
    table.cellWidget(row, 0).click()
    assert locations == [(valid.pages[-1].market_id, 1700000000000)]
    window.set_save_pending(True)
    button.click()
    assert table.rowCount() == before_rows + 1 and not button.isEnabled()
    assert not window._save.isEnabled() and not window._save_as.isEnabled()
    window.set_save_pending(False)
    assert button.isEnabled() and window._save.isEnabled()
    second_before = window.last_valid_draft
    button.click()
    assert table.rowCount() == before_rows + 2 and not window._current_valid
    assert window.last_valid_draft == second_before
    second_id = table.cellWidget(before_rows + 1, 0).property("row_id")
    assert second_id != new_id
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)
    table.cellWidget(before_rows + 1, 1).click()
    assert window._current_valid and table.rowCount() == before_rows + 1
    assert table.cellWidget(row, 0).property("row_id") == new_id
    table.cellWidget(row, 1).click()
    assert table.rowCount() == before_rows and window.current_draft() == original
    _receipt(request, {"kind": kind, "pages": pages, "first_complete_validation": observations[0],
        "new_ids": [new_id, second_id], "save_intents": [repr(s) for s in saves],
        "draft_signals": len(changed), "go": [repr(x) for x in locations],
        "roundtrip": stored.to_dict(), "disk": disk, "final_draft": repr(window.current_draft())})


def test_preserves_preblocked_table_state(editor):
    _, window = editor
    table, button = _controls(window, "note")
    table.blockSignals(True)
    try:
        button.click()
        assert table.signalsBlocked() and table.rowCount() == 2
        assert not window._current_valid
    finally:
        table.blockSignals(False)
    table.item(1, 3).setText("Signals restored")
    new_id = table.cellWidget(1, 0).property("row_id")
    assert window._current_valid
    assert next(note for note in window.current_draft().pages[0].notes if note.row_id == new_id).text == "Signals restored"


def test_replaced_pages_retired_after_deferred_delete(editor, request):
    app, window = editor
    old = [window._tabs.widget(0)]
    old_tables = old[0].findChildren(QTableWidget)
    destroyed = []
    old[0].destroyed.connect(lambda: destroyed.append("page0"))
    expected = _draft()
    for dirty in (True, False, True):
        window.set_draft(expected, dirty=dirty)
        assert window.current_draft() == expected and window.last_valid_draft == expected
        assert window._dirty is dirty
        _drain(app)
    receipt = {"old_page_valid": isValid(old[0]), "old_tables_valid": [isValid(t) for t in old_tables],
        "destroyed": destroyed, "current_pages": window._tabs.count(),
        "descendant_tables": len(window.findChildren(QTableWidget))}
    _receipt(request, receipt)
    assert not isValid(old[0]) and not any(isValid(t) for t in old_tables)
    assert destroyed == ["page0"]
    assert window._tabs.count() == 1 and len(window.findChildren(QTableWidget)) == 3


def test_set_notebook_empty_populated_current_signals_and_owner_destruction(editor, request, tmp_path):
    app, window = editor
    service = ResearchNotebookService(ResearchNotebookStore(tmp_path / "notebooks"))
    stored = service.create_notebook(_draft())
    changed = []
    window.draft_changed.connect(changed.append)
    retired = []
    for _ in range(3):
        retired.extend(window._tabs.widget(i) for i in range(window._tabs.count()))
        window.set_notebook(stored)
        _drain(app)
        assert not window._dirty and window.current_draft().notebook_id == stored.notebook_id
        assert window.current_draft() == window.last_valid_draft
        assert len(window.findChildren(QTableWidget)) == 3 and changed == []
    window.add_page(ResearchNotebookPageV1(
            MarketId("bybit", "linear", "ETHUSDT", "1h"),
            notes=(ResearchNotebookNoteV1("note_eth", 1000, "Retained ETH note"),)))
    _drain(app)
    assert len(window.findChildren(QTableWidget)) == 6 and len(changed) == 1
    assert window._dirty and window.current_draft() == window.last_valid_draft
    table, _ = _controls(window, "note", 1)
    changed.clear()
    table.item(0, 3).setText("Current-page change")
    assert len(changed) == 1 and changed[0] == window.current_draft()
    retired.extend(window._tabs.widget(i) for i in range(window._tabs.count()))
    window.set_draft(_draft([]), dirty=False)
    _drain(app)
    assert window._tabs.count() == 0 and window.findChildren(QTableWidget) == []
    assert all(not isValid(page) for page in retired)
    window.set_draft(_draft(), dirty=True)
    _drain(app)
    current = window._tabs.widget(0)
    current_tables = current.findChildren(QTableWidget)
    close_requests = []
    window.close_requested.connect(lambda: close_requests.append(True))
    window.close()
    _drain(app)
    assert close_requests == [True] and isValid(window) and isValid(current)
    assert all(isValid(t) for t in current_tables)
    window.deleteLater()
    _drain(app)
    assert not isValid(window) and not isValid(current)
    assert not any(isValid(t) for t in current_tables)
    _receipt(request, {"retired_count": len(retired), "retired_valid": [isValid(p) for p in retired],
        "close_requests": len(close_requests), "close_is_not_destruction": True,
        "owner_destroyed": not isValid(window), "current_tables_destroyed": [not isValid(t) for t in current_tables]})


# Task1100-E1: append-only integer transport and real receiver regressions.
from types import SimpleNamespace as _E1Namespace
from PySide6.QtCore import QObject as _E1QObject, Slot as _E1Slot, Qt as _E1Qt
from leonardo.research.notebook import (
    ResearchNotebookPotentialTradeV1 as _E1Trade,
    ResearchNotebookPointOfInterestV1 as _E1Point,
)
from tests.gui_test.test_xrepair_r04_snapshot_review_identity import (
    system as r05_e1_system, _wait as _e1_wait,
)


_E1_MODERN = 1765432100987
_E1_MARKET = MarketId("bybit", "linear", "ETHUSDT", "1h")


@pytest.fixture
def r05_e1_app():
    app = QApplication.instance() or QApplication([])
    yield app
    _drain(app)


def _e1_transport_editor(app, kind, timestamp):
    rows = {}
    if kind == "note":
        rows["notes"] = (ResearchNotebookNoteV1("e1_note", timestamp, "Transport note"),)
    elif kind == "trade":
        rows["potential_trades"] = (_E1Trade("e1_trade", timestamp, "long", 100.0, 110.0,
                                             90.0, "planned", "pending", ""),)
    else:
        rows["points_of_interest"] = (_E1Point("e1_poi", timestamp, 100.0, "Transport point", ""),)
    draft = ResearchNotebookDraft("R05 E1 transport", "Disposable transport-only fixture",
        ResearchNotebookAnnotationSettingsV1(), (ResearchNotebookPageV1(_E1_MARKET, **rows),))
    window = ResearchNotebookWindow()
    window.set_draft(draft, dirty=False)
    window.show()
    app.processEvents()
    table, _button = _controls(window, kind)
    assert window.current_draft() == draft and window.is_current_valid
    return window, table, draft


class _E1Receiver(_E1QObject):
    def __init__(self):
        super().__init__()
        self.received = []

    @_E1Slot(object, object)
    def receive(self, market, timestamp):
        self.received.append((market, timestamp, type(timestamp)))


@pytest.mark.parametrize("kind", ["note", "trade", "poi"])
@pytest.mark.parametrize("queued", [False, True], ids=["direct", "queued"])
@pytest.mark.parametrize("timestamp", [0, 2**31-1, 2**31, _E1_MODERN, 2**63+17],
                         ids=["zero", "int32_max", "above_int32", "modern_ms", "above_int64_transport_only"])
def test_e1_exact_python_integer_transport(r05_e1_app, request, kind, queued, timestamp):
    app = r05_e1_app
    window, table, draft = _e1_transport_editor(app, kind, timestamp)
    receiver = _E1Receiver()
    window.go_to_requested.connect(receiver.receive,
        _E1Qt.ConnectionType.QueuedConnection if queued else _E1Qt.ConnectionType.DirectConnection)
    try:
        table.cellWidget(0, 0).click()
        if queued:
            assert receiver.received == []
        else:
            assert receiver.received == [(_E1_MARKET, timestamp, int)]
        app.processEvents()
        assert receiver.received == [(_E1_MARKET, timestamp, int)]
        assert type(receiver.received[0][1]) is int
        assert window.current_draft() == draft and not window.is_dirty
        _receipt(request, {"kind": kind, "queued": queued, "timestamp": timestamp,
            "python_type": type(receiver.received[0][1]).__name__, "delivery_count": len(receiver.received),
            "market": receiver.received[0][0].as_key(), "exact": True,
            "transport_only_not_calendar_claim": timestamp > 2**63-1})
    finally:
        window.deleteLater()
        receiver.deleteLater()
        _drain(app)


@pytest.mark.parametrize("kind", ["note", "trade", "poi"])
@pytest.mark.parametrize("text", ["", "-1", "not-an-integer"], ids=["blank", "negative", "malformed"])
def test_e1_invalid_go_preserves_controlled_refusal(r05_e1_app, request, kind, text):
    app = r05_e1_app
    window, table, _draft_value = _e1_transport_editor(app, kind, _E1_MODERN)
    received = []
    window.go_to_requested.connect(lambda market, timestamp: received.append((market, timestamp)))
    try:
        table.item(0, 2).setText(text)
        table.cellWidget(0, 0).click()
        app.processEvents()
        assert received == []
        expected = {"": "Go To requires a timestamp", "-1": "Go To requires a non-negative timestamp",
                    "not-an-integer": "Go To requires an integer timestamp"}[text]
        assert window._status.text() == expected
        _receipt(request, {"kind": kind, "input": text, "received": received,
                           "status": window._status.text()})
    finally:
        window.deleteLater()
        _drain(app)


@pytest.mark.parametrize("route", ["current", "legacy"])
@pytest.mark.parametrize("state", ["active", "fallback", "restoring", "no_match"])
def test_e1_receivers_preserve_selection_and_refusal(r05_e1_app, request, route, state):
    # Real unchanged receiver methods with labelled minimal collaborators.
    # Actual composed navigation is independently tested below.
    from leonardo.gui.research.lifecycle_presenter import RestoredResearchLifecyclePresenter
    from leonardo.gui.presenters.research_presenter import ResearchSuitePresenter
    app = r05_e1_app
    window, table, _draft_value = _e1_transport_editor(app, "note", _E1_MODERN)
    calls, activated, messages = [], [], []
    def target(slot, market):
        return _E1Namespace(slot_id=slot, session=_E1Namespace(dataset=_E1Namespace(market_id=market)),
            go_to_timestamp_ms=lambda value: calls.append((slot, value, type(value))))
    first = target(7, _E1_MARKET)
    second = target(9, _E1_MARKET)
    wrong = target(11, MarketId("bybit", "linear", "BTCUSDT", "1h"))
    positions = {7: 1, 9: 2, 11: 0}
    shell = _E1Namespace(placement_for=lambda slot: _E1Namespace(workspace_position=positions[slot]))
    presenters = {11: wrong} if state == "no_match" else {9: second, 11: wrong, 7: first}
    owner = _E1Namespace(_snapshot_restore=object() if state == "restoring" else None,
        _chart_presenters=presenters, _active_presenter=lambda: second if state == "active" else wrong,
        _view=_E1Namespace(workspace=_E1Namespace(shell_state=shell, set_active_slot=activated.append),
                           set_status=messages.append),
        _workspace_state=_E1Namespace(set_active=activated.append), _shell_state=shell,
        _set_active_slot_internal=activated.append, _refresh_active_view=lambda: None,
        _refresh_command_actions=lambda: None, _append_activity=messages.append)
    method = (RestoredResearchLifecyclePresenter._notebook_go_to if route == "current"
              else ResearchSuitePresenter._notebook_go_to)
    window.go_to_requested.connect(lambda market, timestamp: method(owner, market, timestamp))
    try:
        table.cellWidget(0, 0).click()
        app.processEvents()
        if state in ("restoring", "no_match"):
            assert calls == [] and activated == []
        else:
            selected = 9 if state == "active" else 7
            assert calls == [(selected, _E1_MODERN, int)]
            assert activated == ([selected, selected] if route == "current" else [selected])
        if state == "no_match":
            expected = f"No open Research chart for {_E1_MARKET.as_key()}" + ("." if route == "current" else "")
            assert messages == [expected]
        else:
            assert messages == []
        assert len(presenters) == (1 if state == "no_match" else 3)
        _receipt(request, {"route": route, "state": state, "minimal_routing_control": True,
            "calls": [(slot, stamp, kind.__name__) for slot, stamp, kind in calls],
            "activated": activated, "messages": messages, "no_extra_chart": True})
    finally:
        window.deleteLater()
        _drain(app)


def _e1_install_navigation(editor, chart, monkeypatch):
    resident = chart.session.resident
    timestamp = int(resident.ts_ms[len(resident.ts_ms) // 2])
    assert timestamp > 2**31-1
    market = chart.session.dataset.market_id
    draft = ResearchNotebookDraft("Real navigation", "Modern accepted dataset",
        ResearchNotebookAnnotationSettingsV1(),
        (ResearchNotebookPageV1(market, notes=(ResearchNotebookNoteV1("e1_navigation", timestamp, "Exact navigation"),)),),
        editor.notebook_id)
    editor.set_draft(draft, dirty=False)
    table, _button = _controls(editor, "note")
    # Establish a different legitimate camera location through the real owner,
    # so the later actual Go action must move the chart rather than be a no-op.
    first_timestamp = int(chart.session.dataset.ts_ms[0])
    assert first_timestamp != timestamp
    chart.center_on_timestamp_ms(first_timestamp)
    calls = []
    original = chart.go_to_timestamp_ms
    def forward(value):
        result = original(value)
        calls.append((value, type(value), result))
        return result
    monkeypatch.setattr(chart, "go_to_timestamp_ms", forward)
    return timestamp, calls, table


def test_e1_current_composed_modern_navigation(r05_e1_system, request, monkeypatch):
    h = r05_e1_system
    presenter = h.p
    chart = presenter._active_presenter()
    assert chart is not None
    presenter._open_assigned_notebook()
    _e1_wait(lambda: presenter._notebook_editor is not None and presenter._notebook_task_id is None)
    editor = presenter._notebook_editor
    timestamp, calls, table = _e1_install_navigation(editor, chart, monkeypatch)
    slots = h.window.workspace.slot_ids()
    table.cellWidget(0, 0).click()
    QApplication.processEvents()
    assert calls == [(timestamp, int, True)]
    assert h.window.workspace.slot_ids() == slots
    assert presenter._current_workspace_snapshot_id == "a"
    assert presenter._assigned_notebook_id == "notebook_a"
    _receipt(request, {"route": "current", "actual_production_editor_connection": True,
        "real_chart_navigation": True, "timestamp": timestamp, "calls": [(t, k.__name__, ok) for t,k,ok in calls],
        "slots_before": list(slots), "slots_after": list(h.window.workspace.slot_ids()),
        "dataset_range": [int(chart.session.dataset.ts_ms[0]), int(chart.session.dataset.ts_ms[-1])],
        "native_acceptance": False})


def test_e1_legacy_composed_modern_navigation(tmp_path, request, monkeypatch, r05_e1_app):
    from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
    from tests.gui_test import test_research_notebook_presenter as fixture_module
    from tests.gui_test.test_research_single_chart_integration import _wait_until
    # Replace only the legacy fixture's 1970 seed writer with the existing
    # canonical modern accepted OHLCV fixture. Production acceptance stays real.
    monkeypatch.setattr(fixture_module, "_write_accepted_dataset", _accepted_dataset)
    app, main, window, presenter = fixture_module._open_legacy_notebook_suite(tmp_path)
    try:
        chart = presenter._active_presenter()
        assert chart is not None
        _wait_until(lambda: chart.session.resident is not None and not chart.is_busy)
        presenter.new_notebook()
        editor = window.findChild(ResearchNotebookWindow)
        assert editor is not None
        timestamp, calls, table = _e1_install_navigation(editor, chart, monkeypatch)
        slots = presenter.slot_ids()
        table.cellWidget(0, 0).click()
        r05_e1_app.processEvents()
        assert calls == [(timestamp, int, True)]
        assert presenter.slot_ids() == slots
        _receipt(request, {"route": "legacy", "actual_production_editor_connection": True,
            "real_chart_navigation": True, "timestamp": timestamp, "calls": [(t,k.__name__,ok) for t,k,ok in calls],
            "slots_before": list(slots), "slots_after": list(presenter.slot_ids()),
            "dataset_range": [int(chart.session.dataset.ts_ms[0]), int(chart.session.dataset.ts_ms[-1])],
            "native_acceptance": False})
    finally:
        presenter._close_notebook_editor()
        presenter.dispose()
        window.close()
        main.close()
        r05_e1_app.processEvents()
        app.shutdown()
