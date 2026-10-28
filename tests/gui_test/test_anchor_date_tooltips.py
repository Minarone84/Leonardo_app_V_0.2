"""1083-R4-F1: exact draft hover values without analytical side effects."""
from dataclasses import replace
import json
import pytest
from PySide6.QtCore import QDateTime, QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QToolTip
from PySide6.QtTest import QTest
from leonardo.analysis.refinement_models import AnchorDateRange as Range, GranularRefinement as D
from leonardo.gui.analysis.refinement_filter_editor import GranularFilterEditor
from leonardo.gui.display_time import DISPLAY_TIME_ZONE_PROPERTY
from tests.gui_test.test_trend_start_patterns_tab import qapp
from tests.gui_test.test_anchor_date_refinement_workflow import root_context, definition_for, wait_operation
from tests.gui_test.test_family_scope_workflow import family_gui, _gr05_pin_gui
from tests.gui_test.test_refinement_filter_editor import installed_theme_font, activate
from tests.gui_test.test_pre_event_pattern_controls import dispose

START = 1700000000000
END = 1700027540000


@pytest.fixture(autouse=True)
def utc_session(qapp):
    previous = qapp.property(DISPLAY_TIME_ZONE_PROPERTY)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, 'UTC')
    yield
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, previous)


@pytest.fixture
def editor(root_context):
    widget = GranularFilterEditor()
    widget.set_context(root_context)
    assert root_context['original_request'].start_ms == START
    assert root_context['original_request'].end_ms == END
    widget.set_value(D(anchor_range=Range(START, END)))
    yield widget
    dispose(widget)


def set_ms(widget, value):
    widget.setDateTime(QDateTime.fromMSecsSinceEpoch(value, widget.timeZone()))


def hover_tip(widget):
    point = QPoint(1, 1)
    QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, point, widget.mapToGlobal(point)))
    tip = widget.toolTip()
    QToolTip.hideText()
    return tip


def assert_hover(widget, expected):
    assert hover_tip(widget) == expected
    assert hover_tip(widget.lineEdit()) == expected
    assert widget.toolTip() == expected
    # The line edit is the actual hovered child, not a detached display model.
    assert widget.lineEdit().toolTip() == expected


@pytest.mark.parametrize('endpoint,changed', (('start', 1700000000123), ('end', 1700027539877)))
def test_original_endpoint_reproduction(editor, endpoint, changed, tmp_path):
    control = editor.anchor_range
    widget = getattr(control, endpoint)
    opposite = control.end if endpoint == 'start' else control.start
    old = widget.dateTime().toMSecsSinceEpoch()
    opposite_ms = opposite.dateTime().toMSecsSinceEpoch()
    set_ms(widget, changed)
    assert getattr(editor.value().anchor_range, endpoint+'_ms') == changed
    receipt = dict(endpoint=endpoint, old_ms=old, new_ms=changed,
                   returned_ms=getattr(editor.value().anchor_range, endpoint+'_ms'),
                   tooltip=widget.toolTip(), child_tooltip=widget.lineEdit().toolTip())
    (tmp_path/'tooltip_receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    assert widget.toolTip() == f'Exact UTC milliseconds: {changed}'
    assert_hover(widget, f'Exact UTC milliseconds: {changed}')
    assert_hover(opposite, f'Exact UTC milliseconds: {opposite_ms}')


@pytest.mark.parametrize('endpoint', ('start', 'end'))
@pytest.mark.parametrize('edit', ('clear', 'keyboard'))
def test_native_incomplete_input_is_unavailable_without_extra_signals(editor, qapp, endpoint, edit):
    control = editor.anchor_range
    widget = getattr(control, endpoint)
    signals = []
    editor.changed.connect(lambda: signals.append(1))
    old = widget.dateTime().toMSecsSinceEpoch()
    text = widget.lineEdit().text()
    if edit == 'clear':
        widget.clear()
    else:
        widget.lineEdit().setSelection(3, 1)
        QTest.keyClick(widget, Qt.Key.Key_Backspace)
        assert widget.lineEdit().text() == text[:3]+text[4:]
    assert not widget.hasAcceptableInput()
    assert widget.dateTime().toMSecsSinceEpoch() == old
    assert signals == ([] if edit == 'clear' else [1])
    with pytest.raises(ValueError, match='complete valid anchor date'):
        editor.value()
    for tip in (hover_tip(widget), hover_tip(widget.lineEdit())):
        assert 'unavailable' in tip.lower() and 'complete valid anchor date' in tip
        assert str(old) not in tip and 'Exact UTC milliseconds:' not in tip
    raw = widget.lineEdit().text()
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, 'Europe/Rome')
    editor.refresh_display_time()
    assert widget.lineEdit().text() == raw and not widget.hasAcceptableInput()
    assert signals == ([] if edit == 'clear' else [1])
    editor.set_value(D(anchor_range=Range(START+123, END-123)))
    assert editor.value().anchor_range == Range(START+123, END-123)
    assert_hover(widget, f'Exact UTC milliseconds: {START+123 if endpoint == "start" else END-123}')


@pytest.mark.parametrize('endpoint', ('start', 'end'))
@pytest.mark.parametrize('fault', ('outside', 'reversed'))
def test_invalid_range_tooltips_and_valid_recovery(editor, endpoint, fault):
    control = editor.anchor_range
    widget = getattr(control, endpoint)
    bad = (START-1 if endpoint == 'start' else END+1) if fault == 'outside' else (END+1 if endpoint == 'start' else START-1)
    set_ms(widget, bad)
    assert widget.dateTime().toMSecsSinceEpoch() == bad
    with pytest.raises(ValueError):
        editor.value()
    reason = control.status.text().split('\n')[0]
    assert reason.startswith('Invalid date draft:')
    for hovered in (widget, widget.lineEdit()):
        tip = hovered.toolTip()
        assert str(bad) in tip and 'draft' in tip.lower()
        assert reason in tip and not tip.startswith('Exact UTC milliseconds:')
    set_ms(widget, START+123 if endpoint == 'start' else END-123)
    assert getattr(editor.value().anchor_range, endpoint+'_ms') == (START+123 if endpoint == 'start' else END-123)
    assert_hover(widget, f'Exact UTC milliseconds: {START+123 if endpoint == "start" else END-123}')


def test_unrepresentable_load_retains_input_and_diagnostic(editor):
    control = editor.anchor_range
    editor.set_value(D(anchor_range=Range(2**63-2, 2**63-1)))
    retained = dict(control._unavailable)
    assert retained == {'start': 2**63-2, 'end': 2**63-1}
    with pytest.raises(ValueError, match='unavailable in the GUI calendar'):
        editor.value()
    for name in ('start', 'end'):
        widget = getattr(control, name)
        assert str(retained[name]) in widget.toolTip()
        assert 'unavailable' in widget.toolTip().lower()
        assert not widget.toolTip().startswith('Exact UTC milliseconds:')
        assert widget.lineEdit().toolTip() == widget.toolTip()
    editor.refresh_display_time()
    assert control._unavailable == retained
    editor.set_value(D(anchor_range=Range(START+123, END-123)))
    assert not control._unavailable
    assert_hover(control.start, 'Exact UTC milliseconds: 1700000000123')
    assert_hover(control.end, 'Exact UTC milliseconds: 1700027539877')


@pytest.mark.parametrize('state', ('valid', 'incomplete', 'unrepresentable'))
def test_disabled_retained_draft_and_clear_load(editor, state):
    control = editor.anchor_range
    signals = []
    editor.changed.connect(lambda: signals.append(1))
    if state == 'incomplete':
        control.start.clear()
        assert not control.start.hasAcceptableInput()
    elif state == 'unrepresentable':
        editor.set_value(D(anchor_range=Range(2**63-2, 2**63-1)))
    control.enabled.click()
    assert editor.value().anchor_range is None and signals == [1]
    tip = control.start.toolTip()
    assert 'not applied' in tip.lower() and 'draft' in tip.lower()
    if state != 'valid':
        assert 'unavailable' in tip.lower() and 'Exact UTC milliseconds:' not in tip
    control.enabled.click()
    assert signals == [1, 1]
    if state != 'valid':
        with pytest.raises(ValueError):
            editor.value()
    editor.set_value(D())
    assert signals == [1, 1] and editor.value().anchor_range is None
    assert control.start.dateTime().toMSecsSinceEpoch() == START
    assert 'not applied' in control.start.toolTip().lower()
    editor.set_value(D(anchor_range=Range(START+123, END-123)))
    assert signals == [1, 1]
    assert_hover(control.start, 'Exact UTC milliseconds: 1700000000123')
    assert_hover(control.end, 'Exact UTC milliseconds: 1700027539877')


@pytest.mark.parametrize('zone', ('UTC', 'Europe/Rome'))
def test_programmatic_restore_and_display_timezone_keep_exact_instants(editor, qapp, root_context, zone):
    signals = []
    editor.changed.connect(lambda: signals.append(1))
    context = dict(root_context)
    context['original_request'] = replace(context['original_request'], start_ms=1711836000123, end_ms=1711846800789)
    definition = D(anchor_range=Range(1711845000123, 1711846800789))
    editor.set_context(context)
    editor.set_value(definition)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, zone)
    editor.refresh_display_time()
    editor.set_context(context)
    editor.set_value(definition)
    assert editor.value() == definition and not signals
    control = editor.anchor_range
    for widget, timestamp in ((control.start, 1711845000123), (control.end, 1711846800789)):
        assert widget.dateTime().toMSecsSinceEpoch() == timestamp
        assert widget.timeZone().id().data().decode() == zone
        assert_hover(widget, f'Exact UTC milliseconds: {timestamp}')
    assert control.start.dateTime().time().msec() == 123


def semantic_sequence(editor, qapp, root_context):
    """Identical actions captured on PRE and POST by the external evidence test."""
    signals = []
    editor.changed.connect(lambda: signals.append(1))
    records = []
    def capture(action):
        control = editor.anchor_range
        try:
            definition = editor.value().to_dict()
            error = None
        except (TypeError, ValueError) as exc:
            definition = None
            error = (type(exc).__name__, str(exc))
        records.append(dict(action=action, definition=definition, error=error,
            signals=len(signals), enabled=control.enabled.isChecked(),
            texts=[w.lineEdit().text() for w in (control.start, control.end)],
            acceptable=[w.hasAcceptableInput() for w in (control.start, control.end)],
            utc=[w.dateTime().toMSecsSinceEpoch() for w in (control.start, control.end)],
            unavailable=dict(control._unavailable), status=control.status.text(), editor_status=editor.status.text()))
        before = records[-1]
        for widget in (control.start, control.end):
            hover_tip(widget)
            hover_tip(widget.lineEdit())
        assert len(signals) == before['signals']
        assert control.status.text() == before['status']
        assert editor.status.text() == before['editor_status']
        assert [w.lineEdit().text() for w in (control.start, control.end)] == before['texts']
        assert [w.dateTime().toMSecsSinceEpoch() for w in (control.start, control.end)] == before['utc']
        assert control._unavailable == before['unavailable']

    capture('loaded')
    set_ms(editor.anchor_range.start, START+123); capture('start edit')
    set_ms(editor.anchor_range.end, END-123); capture('end edit')
    editor.anchor_range.start.clear(); capture('native clear')
    editor.anchor_range.enabled.click(); capture('disabled incomplete')
    editor.anchor_range.enabled.click(); capture('reenabled incomplete')
    definition = D(anchor_range=Range(START+123, END-123))
    editor.set_value(definition); capture('restore')
    set_ms(editor.anchor_range.start, START-1); capture('outside')
    editor.set_value(definition)
    set_ms(editor.anchor_range.end, START); capture('reversed')
    editor.set_value(D(anchor_range=Range(2**63-2, 2**63-1))); capture('unrepresentable')
    editor.set_value(D()); capture('clear selection')
    editor.set_value(definition)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, 'Europe/Rome')
    editor.refresh_display_time(); capture('timezone')
    raw = editor.anchor_range.start.lineEdit().text()
    editor.anchor_range.start.lineEdit().setSelection(3, 1)
    QTest.keyClick(editor.anchor_range.start, Qt.Key.Key_Backspace)
    assert editor.anchor_range.start.lineEdit().text() == raw[:3]+raw[4:]
    capture('keyboard incomplete')
    editor.set_context(root_context); capture('context invalid')
    editor.set_value(definition); capture('final restore')
    return records


def test_semantic_action_sequence_has_original_signal_counts(editor, qapp, root_context, tmp_path):
    records = semantic_sequence(editor, qapp, root_context)
    assert [r['signals'] for r in records] == [0, 1, 2, 2, 3, 4, 4, 5, 6, 6, 6, 6, 7, 7, 7]
    assert records[3]['error'][1] == 'Enter a complete valid anchor date including milliseconds'
    assert 'anchor_range' not in records[4]['definition']
    assert records[-1]['definition']['anchor_range'] == {'kind': 'gr-date-anchor-range-v1', 'start_ms': START+123, 'end_ms': END-123}
    (tmp_path/'semantic_sequence.json').write_text(json.dumps(records, indent=2), encoding='utf-8')


def test_real_history_and_hover_do_not_create_analysis_or_generation(family_gui, monkeypatch, qapp):
    from tests.gui_test.test_pattern_refinement_workflow import _r2_history_popup, _r2_spies, _r2_same_saved
    p = family_gui
    page = _gr05_pin_gui(p)
    definition = definition_for(p)
    activate(page, definition)
    page.actions['evaluate'].click()
    wait_operation(p, 'tooltip baseline')
    result = page._result
    frame = page.results.model.frame.copy(deep=True)
    saved = p.service.refinement_snapshot(p.presenter.session)
    control = page.granular_editor.anchor_range
    set_ms(control.start, definition.anchor_range.start_ms+123)
    edited = p.service.refinement_snapshot(p.presenter.session)
    assert edited['generation'] == saved['generation']+1
    calls = _r2_spies(p, page, monkeypatch)
    qapp.setProperty(DISPLAY_TIME_ZONE_PROPERTY, 'Europe/Rome')
    p.presenter.refresh_display_time()
    assert_hover(control.start, f'Exact UTC milliseconds: {definition.anchor_range.start_ms+123}')
    assert p.service.refinement_snapshot(p.presenter.session) == edited
    _r2_history_popup(p, page, saved['active_checkpoint_id'])
    _r2_same_saved(p, page, edited, result, frame)
    assert page.draft() == definition
    assert calls.selection.call_count == 1 and calls.worker.call_count == 0
    assert_hover(control.start, f'Exact UTC milliseconds: {definition.anchor_range.start_ms}')
    assert_hover(control.end, f'Exact UTC milliseconds: {definition.anchor_range.end_ms}')



@pytest.mark.parametrize('endpoint', ('start', 'end'))
def test_native_millisecond_keyboard_commit_uses_current_draft(editor, endpoint):
    control = editor.anchor_range
    editor.set_value(D(anchor_range=Range(START+60000, END-60000)))
    widget = getattr(control, endpoint)
    expected = 1700000060123 if endpoint == 'start' else 1700027480123
    widget.setCurrentSection(widget.Section.MSecSection)
    widget.lineEdit().setSelection(len(widget.lineEdit().text())-3, 3)
    QTest.keyClicks(widget, '123')
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert widget.hasAcceptableInput()
    assert getattr(editor.value().anchor_range, endpoint+'_ms') == expected
    assert_hover(widget, f'Exact UTC milliseconds: {expected}')
