"""R04 metadata uses real Core writes and complete disposable disk inventories."""
from dataclasses import replace

import pytest

from leonardo.gui.windows.workspace_snapshot_manager_dialog import WorkspaceSnapshotMetadataIntent
from leonardo.gui.windows.workspace_snapshot_save_dialog import WorkspaceSnapshotSaveIntent
from tests.gui_test.test_xrepair_r04_snapshot_review_identity import system, _disk, _wait


def _edit(h, key):
    h.select(key)
    before = _disk(h.root)
    snapshot = h.store.load(key)
    charts = h.p._capture_snapshot_workspace()
    h.d.name_edit.setText(key + ' renamed')
    h.d.description_edit.setText('R04 metadata only')
    assert h.d.metadata_button.isEnabled()
    h.d.metadata_button.click()
    entry = h.api.last('metadata')
    _wait(lambda: entry.result is not None)
    stored = h.store.load(key)
    after = _disk(h.root)
    changed = [p for p in before if before[p] != after.get(p)]
    h.receipts.append({'before': before, 'after': after, 'changed': changed,
                       'before_snapshot': snapshot.to_dict(), 'after_snapshot': stored.to_dict(),
                       'charts_before': repr(charts)})
    assert set(before) == set(after)
    assert changed == ['snapshots/' + key + '.json']
    assert stored.display_name == key + ' renamed'
    assert stored.description == 'R04 metadata only'
    assert stored.charts == snapshot.charts and stored.workspace == snapshot.workspace
    assert stored.notebook_id == snapshot.notebook_id
    assert stored.content_hash != snapshot.content_hash
    assert stored.updated_at_utc != snapshot.updated_at_utc
    return entry, charts


def test_noncurrent_metadata_does_not_adopt_workspace_or_next_targets(system):
    h = system
    entry, charts = _edit(h, 'b')
    h.api.deliver(entry)
    h.receipts.append({'after_completion_snapshot': h.p._current_workspace_snapshot_id,
                       'after_completion_notebook': h.p._assigned_notebook_id})
    assert h.p._current_workspace_snapshot_id == 'a'
    assert h.p._assigned_notebook_id == 'notebook_a'
    assert h.p._capture_snapshot_workspace() == charts
    # Exercise the existing assigned-Notebook route and observe its actual target.
    h.p._open_assigned_notebook()
    _wait(lambda: h.p._active_notebook is not None)
    assert h.p._active_notebook.notebook_id == 'notebook_a'
    assert h.p._notebook_editor.notebook_id == 'notebook_a'
    h.p._close_notebook_editor()
    # Explicit next Save target still belongs to A; capture the real update request.
    h.p._save_snapshot_intent(charts, WorkspaceSnapshotSaveIntent(
        'update', h.p._current_workspace_snapshot_id, 'A next save', ''))
    save = h.api.last('metadata')
    assert save.args[0] == 'a'
    h.api.deliver(save)
    assert h.store.load('a').display_name == 'A next save'
    assert h.store.load('b').display_name == 'b renamed'


def test_current_metadata_preserves_chart_link_and_refreshes_real_review(system):
    h = system
    entry, charts = _edit(h, 'a')
    old_review = h.d.compatibility_report
    h.api.deliver(entry)
    assert h.p._current_workspace_snapshot_id == 'a'
    assert h.p._assigned_notebook_id == 'notebook_a'
    assert h.p._capture_snapshot_workspace() == charts
    assert h.d.snapshot == h.store.load('a')
    assert h.d.compatibility_report is None
    h.api.deliver(h.api.last('review'))
    assert h.d.compatibility_report is not old_review
    assert h.d.load_button.isEnabled()


@pytest.mark.parametrize('change', ['selection', 'live_workspace', 'new_assignment', 'closed', 'reload'])
def test_late_metadata_preserves_newer_selection_and_live_association(system, change):
    h = system
    key = 'a' if change == 'new_assignment' else 'b'
    entry, charts = _edit(h, key)
    if change == 'selection':
        h.select('a')
    elif change == 'live_workspace':
        # Controlled user transition after the real write, before its delivery.
        h.p._current_workspace_snapshot_id = 'b'
        h.p._assigned_notebook_id = 'notebook_a'
    elif change == 'new_assignment':
        # Durable canonical assignment races with an older metadata response.
        h.link.assign_notebook('a', 'notebook_b')
        h.p._assigned_notebook_id = 'notebook_b'
    elif change == 'closed':
        h.d.close()
    else:
        h.p._load_snapshot_manager_selection(h.d, key)
        h.api.deliver(h.api.last('load'))
        h.api.deliver(h.api.last('review'))
    expected = (h.p._current_workspace_snapshot_id, h.p._assigned_notebook_id)
    recap = h.d.snapshot
    h.api.deliver(entry)
    assert (h.p._current_workspace_snapshot_id, h.p._assigned_notebook_id) == expected
    assert h.p._capture_snapshot_workspace() == charts
    if change in ('selection', 'closed', 'reload'):
        assert h.d.snapshot is recap
    if change == 'new_assignment':
        assert h.store.load('a').notebook_id == 'notebook_b'


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'foreign', 'duplicate'])
def test_metadata_settlement_identity_and_status_guards(system, status):
    h = system
    entry, charts = _edit(h, 'b')
    before = h.d.snapshot
    if status == 'foreign':
        h.api.deliver(entry, value=h.A)
    elif status == 'duplicate':
        h.api.deliver(entry)
        h.api.deliver(h.api.last('review'))
        reviewed = h.d.reviewed_context
        h.api.deliver(entry)
        assert h.d.reviewed_context == reviewed
    else:
        h.api.deliver(entry, status=status)
    if status != 'duplicate':
        assert h.d.snapshot is before
    assert h.p._current_workspace_snapshot_id == 'a'
    assert h.p._assigned_notebook_id == 'notebook_a'
    assert h.p._capture_snapshot_workspace() == charts


def test_metadata_foreign_or_empty_intent_never_submits_write(system):
    h = system
    h.select('a')
    before = _disk(h.root)
    count = len(h.api.pending)
    h.p._save_snapshot_manager_metadata(h.d, WorkspaceSnapshotMetadataIntent('b', 'wrong', ''))
    h.d.snapshot_list.setCurrentRow(-1)
    h.d._emit_metadata()
    assert len(h.api.pending) == count
    assert _disk(h.root) == before
