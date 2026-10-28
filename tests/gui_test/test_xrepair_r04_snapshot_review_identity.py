"""R04: real stored Snapshot reviews, with deliberately ordered callback delivery.

All final-confirmation tests capture the unchanged restore ENTRY only. Existing
restore/rollback/dirty-Notebook integration tests own actual restore evidence.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from leonardo.artifacts import ArtifactService
from leonardo.core.core_runner import CoreRunner, TaskResult
from leonardo.core.task_manager import TaskManager
from leonardo.gui.research import ResearchSuiteWindow, RestoredResearchLifecyclePresenter
from leonardo.gui.windows.workspace_snapshot_manager_dialog import (
    WorkspaceSnapshotManagerDialog, WorkspaceSnapshotLoadIntent,
)
from leonardo.research import AcceptedDatasetCatalog, HistoricalDatasetLoader, ResearchDatasetApplicationService, ResidentSliceService
from leonardo.research.notebook import ResearchNotebookAnnotationSettingsV1
from leonardo.research.notebook_store import ResearchNotebookStore
from leonardo.research.notebook_service import ResearchNotebookService
from leonardo.research.notebook_application import ResearchNotebookApplicationService
from leonardo.research.study_environment_store import StudyEnvironmentStore
from leonardo.research.study_setup_service import ResearchStudySetupService
from leonardo.research.workspace_notebook_link import ResearchWorkspaceNotebookLinkService
from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotDraft
from leonardo.research.workspace_snapshot_store import ResearchWorkspaceSnapshotStore
from leonardo.research.workspace_snapshot_service import ResearchWorkspaceSnapshotService
from leonardo.research.workspace_snapshot_application import ResearchWorkspaceSnapshotApplicationService
from tests.artifacts_test.test_artifact_service_roundtrip import _accepted_dataset
from tests.gui_test.test_research_gui_service_catalog import _ControlledStudyService


def _wait(predicate):
    deadline = time.monotonic() + 3.0
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.002)
    assert predicate(), "Core/Qt did not settle within the bounded fixture wait"


def _disk(root):
    return {p.relative_to(root).as_posix(): {"bytes": len(p.read_bytes()),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.rglob('*')) if p.is_file()}


class _OrderedSnapshots(ResearchWorkspaceSnapshotApplicationService):
    """Delay callback delivery only; real Core/service/storage compute every result."""
    def __init__(self, *args):
        super().__init__(*args)
        self.pending = []
        self.results = {}
        self.deliveries = []

    def _held(self, kind, submit, args, callbacks):
        callback = callbacks.pop('result_callback')
        entry = SimpleNamespace(kind=kind, callback=callback, result=None, args=args)
        self.pending.append(entry)
        def arrived(result):
            entry.result = result
            self.results[result.task_id] = result
        submission = submit(*args, result_callback=arrived, **callbacks)
        entry.task_id = submission.task_id
        return submission

    def submit_load_snapshot(self, *args, **kwargs):
        return self._held('load', super().submit_load_snapshot, args, kwargs)

    def submit_preflight(self, *args, **kwargs):
        return self._held('review', super().submit_preflight, args, kwargs)

    def submit_update_snapshot(self, *args, **kwargs):
        return self._held('metadata', super().submit_update_snapshot, args, kwargs)

    def last(self, kind):
        return next(e for e in reversed(self.pending) if e.kind == kind)

    def deliver(self, entry, *, status=None, value=None):
        _wait(lambda: entry.result is not None)
        result = entry.result
        assert result.status == 'completed', result
        if status is not None:
            result = TaskResult(result.task_id, status)
        elif value is not None:
            result = TaskResult(result.task_id, 'completed', value=value)
        self.deliveries.append({"kind": entry.kind, "task_id": result.task_id,
                               "status": result.status, "value": repr(result.value)})
        entry.callback(result)


@pytest.fixture
def system(tmp_path, request):
    app = QApplication.instance() or QApplication([])
    market, _frame = _accepted_dataset(tmp_path / 'historical')
    catalog = AcceptedDatasetCatalog(tmp_path / 'historical')
    loader = HistoricalDatasetLoader(catalog)
    store = ResearchWorkspaceSnapshotStore(tmp_path / 'snapshots')
    notebooks = ResearchNotebookService(ResearchNotebookStore(tmp_path / 'notebooks'))
    link = ResearchWorkspaceNotebookLinkService(store, notebooks)
    setup = ResearchStudySetupService(ArtifactService(tmp_path / 'historical'),
                                     StudyEnvironmentStore(tmp_path / 'environments'))
    domain = ResearchWorkspaceSnapshotService(catalog, loader, setup, store, link)
    runner = CoreRunner(TaskManager())
    runner.start()
    api = _OrderedSnapshots(runner, domain, link)
    window = ResearchSuiteWindow()
    presenter = RestoredResearchLifecyclePresenter(
        window, ResearchDatasetApplicationService(runner, loader, catalog=catalog, resident_slices=ResidentSliceService()),
        _ControlledStudyService(), snapshot_service=api,
        notebook_service=ResearchNotebookApplicationService(runner, notebooks, link),
    )
    h = SimpleNamespace(app=app, root=tmp_path, window=window, p=presenter,
                        api=api, store=store, domain=domain, link=link,
                        notebooks=notebooks, receipts=[], d=None, entries=[])
    try:
        _wait(lambda: presenter._active_catalog_task_id is None)
        slot, chart = presenter._create_restored_chart(market)
        chart.open_dataset(market)
        _wait(lambda: chart.session.resident is not None and not chart.is_busy)
        h.capture = presenter._capture_snapshot_workspace()
        for key in ('a', 'b'):
            notebooks.create_notebook(notebooks.build_draft(
                notebook_id='notebook_' + key, display_name='Notebook ' + key,
                annotation_settings=ResearchNotebookAnnotationSettingsV1()))
            snap = store.create(domain.build_draft(h.capture, display_name=key, snapshot_id=key))
            setattr(h, key.upper(), link.assign_notebook(snap.snapshot_id, 'notebook_' + key))
        presenter._current_workspace_snapshot_id = 'a'
        presenter._assigned_notebook_id = 'notebook_a'
        presenter._open_snapshot_manager('manage')
        _wait(lambda: presenter._snapshot_manager is not None)
        h.d = presenter._snapshot_manager
        h.entries = []
        # Entry fence observation only; no claim of completed restore.
        presenter._restore_snapshot_workspace = lambda s, r: h.entries.append((s, r))
        def select(key, *, settle=True):
            index = next(i for i in range(h.d.snapshot_list.count())
                         if h.d.snapshot_list.item(i).data(256) == key)
            h.d.snapshot_list.setCurrentRow(index)
            entry = api.last('load')
            if settle:
                api.deliver(entry)
                api.deliver(api.last('review'))
            return entry
        h.select = select
        yield h
    finally:
        # Finish actual jobs before disposing the owner; held callbacks are not jobs.
        for entry in api.pending:
            _wait(lambda entry=entry: entry.result is not None)
        observation = {
            'nodeid': request.node.nodeid, 'entry_fencing_only': True,
            'selected': None if presenter._snapshot_manager is None else h.d.selected_snapshot_id,
            'loaded': None if h.d is None or h.d.snapshot is None else h.d.snapshot.to_dict(),
            'review_context': repr(getattr(h.d, 'reviewed_context', None)),
            'live_snapshot': presenter._current_workspace_snapshot_id,
            'live_notebook': presenter._assigned_notebook_id,
            'load_enabled': None if h.d is None else h.d.load_button.isEnabled(),
            'metadata_enabled': None if h.d is None else h.d.metadata_button.isEnabled(),
            'restore_entries': [(s.snapshot_id, r.mode) for s, r in h.entries],
            'deliveries': api.deliveries, 'receipts': h.receipts, 'disk': _disk(tmp_path),
        }
        if os.environ.get('R02_OBSERVATIONS'):
            root = Path(os.environ['R02_OBSERVATIONS']); root.mkdir(exist_ok=True)
            name = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16] + '.json'
            with (root / name).open('x', encoding='utf-8') as file:
                json.dump(observation, file, indent=2, default=str)
        presenter.dispose()
        window.close()
        runner.shutdown()
        QApplication.processEvents()


def test_late_A_after_B_cannot_load_A(system):
    h = system
    late = h.select('a', settle=False)
    h.select('b')
    h.api.deliver(late)
    if h.api.last('review').result is None:
        h.api.deliver(h.api.last('review'))
    emitted = []
    h.d.load_requested.connect(emitted.append)
    h.d.load_button.click()
    h.receipts.append({'selected': h.d.selected_snapshot_id,
                       'loaded': h.d.snapshot.snapshot_id, 'emitted': repr(emitted)})
    assert h.d.snapshot.snapshot_id == 'b'
    assert emitted == [WorkspaceSnapshotLoadIntent('b', 'append')]


def test_foreign_compatible_report_cannot_enable_load(system):
    h = system
    h.select('b', settle=False)
    h.api.deliver(h.api.last('load'))
    foreign = h.domain.preflight(h.A, 'append', {'occupied_positions': (1,), 'idle': True})
    assert foreign.compatible
    h.d.set_compatibility(foreign)
    emitted = []
    h.d.load_requested.connect(emitted.append)
    h.d.load_button.click()
    h.receipts.append({'button_enabled': h.d.load_button.isEnabled(), 'emitted': repr(emitted)})
    assert not h.d.load_button.isEnabled()
    assert emitted == []
    h.api.deliver(h.api.last('review'))
    h.d.load_button.click()
    assert emitted == [WorkspaceSnapshotLoadIntent('b', 'append')]


@pytest.mark.parametrize('mode', ['append', 'replace'])
def test_current_core_review_actual_buttons_reach_restore_entry(system, mode):
    h = system
    if mode == 'replace':
        h.d.replace_radio.click()
    h.select('b')
    assert h.d.compatibility_report.compatible
    assert h.d.compatibility_report.mode == mode
    h.d.load_button.click()
    preflight = h.p._snapshot_preflight_dialog
    assert preflight is not None and preflight.load_button.isEnabled()
    preflight.load_button.click()
    assert h.entries == [(h.B, h.d.compatibility_report)]
    assert h.entries[0][1].mode == mode


@pytest.mark.parametrize('route', ['ABA', 'same_id', 'duplicate'])
def test_load_generation_consumes_only_current_delivery(system, route):
    h = system
    old = h.select('a', settle=False)
    if route == 'ABA':
        h.select('b', settle=False)
        h.select('a')
    elif route == 'same_id':
        h.p._load_snapshot_manager_selection(h.d, 'a')
        h.api.deliver(h.api.last('load'))
        h.api.deliver(h.api.last('review'))
    else:
        h.api.deliver(old)
        h.api.deliver(h.api.last('review'))
    before = h.d.reviewed_context
    h.api.deliver(old)
    assert before == h.d.reviewed_context and before is not None
    assert h.d.load_button.isEnabled()


@pytest.mark.parametrize('route', ['same_mode', 'append_replace_append', 'changed_content'])
def test_review_generation_rejects_obsolete_compatible_result(system, route):
    h = system
    h.select('a', settle=False)
    h.api.deliver(h.api.last('load'))
    old = h.api.last('review')
    if route == 'append_replace_append':
        h.d.replace_radio.click()
        h.d.append_radio.click()
    elif route == 'changed_content':
        changed = h.store.update('a', replace(h.domain.build_draft(h.capture,
            display_name='Changed A', snapshot_id='a'), description='new content'))
        h.d.set_snapshot(changed)
        h.p._check_snapshot_manager_compatibility(h.d, WorkspaceSnapshotLoadIntent('a', 'append'))
    else:
        h.p._check_snapshot_manager_compatibility(h.d, WorkspaceSnapshotLoadIntent('a', 'append'))
    h.api.deliver(h.api.last('review'))
    current = h.d.reviewed_context
    h.api.deliver(old)
    assert current == h.d.reviewed_context and current is not None
    assert h.d.load_button.isEnabled()


@pytest.mark.parametrize('route', ['clear', 'invalid', 'refresh', 'closed', 'replaced'])
def test_ineligible_manager_or_selection_cannot_receive_pending_load(system, route):
    h = system
    old = h.select('a', settle=False)
    if route == 'clear':
        h.d.snapshot_list.setCurrentRow(-1)
    elif route == 'invalid':
        summaries = h.store.list_summaries()
        h.d.set_summaries((replace(summaries[0], valid=False, rejection_reason='invalid'),))
        h.d.snapshot_list.setCurrentRow(0)
    elif route == 'refresh':
        h.p._refresh_snapshot_manager(h.d)
    elif route == 'closed':
        h.d.close()
    else:
        replacement = WorkspaceSnapshotManagerDialog(h.store.list_summaries(), h.window, mode='manage')
        h.p._snapshot_manager = replacement
        replacement.show()
    h.api.deliver(old)
    assert h.d.snapshot is None
    assert not h.d.metadata_button.isEnabled() and not h.d.load_button.isEnabled()


@pytest.mark.parametrize('kind', ['load', 'review'])
@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_failed_cancelled_settlement_never_authorizes_load(system, kind, status):
    h = system
    h.select('a', settle=False)
    if kind == 'review':
        h.api.deliver(h.api.last('load'))
    h.api.deliver(h.api.last(kind), status=status)
    assert not h.d.load_button.isEnabled()
    emitted = []
    h.d.load_requested.connect(emitted.append)
    h.d._emit_load()
    assert emitted == []


def test_no_selection_recap_is_read_only_and_clears_on_refresh(system):
    h = system
    h.d.snapshot_list.setCurrentRow(-1)
    h.d.set_snapshot(h.A)
    assert h.d.chart_table.rowCount() == len(h.A.charts)
    assert h.d.name_edit.text() == h.A.display_name
    emitted = []
    h.d.metadata_requested.connect(emitted.append)
    h.d.load_requested.connect(emitted.append)
    h.d._emit_metadata(); h.d._emit_load()
    assert emitted == []
    assert h.d.compatibility_context() is None
    h.d.set_summaries(h.store.list_summaries())
    assert h.d.chart_table.rowCount() == 0 and h.d.name_edit.text() == ''


@pytest.mark.parametrize('change', ['selection', 'mode', 'content', 'closed', 'retired', 'foreign_report'])
def test_final_preflight_button_rejects_stale_review(system, change):
    h = system
    h.select('a')
    h.d.load_button.click()
    preflight = h.p._snapshot_preflight_dialog
    if change == 'selection':
        h.select('b')
    elif change == 'mode':
        h.d.replace_radio.click()
    elif change == 'content':
        h.d.set_snapshot(h.store.update('a', h.domain.build_draft(h.capture,
                              display_name='A changed', snapshot_id='a')))
    elif change == 'closed':
        h.d.close()
    elif change == 'retired':
        h.select('b')
        h.d.load_button.click()
        assert h.p._snapshot_preflight_dialog is not preflight
    if change == 'foreign_report':
        preflight.load_requested.emit(h.domain.preflight(h.B, 'append', {}))
    else:
        preflight.load_button.click()
    assert h.entries == []
    assert not preflight.load_button.isEnabled()


def test_sixteen_slot_authority_still_blocks_and_matching_context_is_reviewed(system):
    h = system
    h.select('a')
    report = h.domain.preflight(h.A, 'append', {'occupied_positions': tuple(range(1, 17))})
    assert not report.compatible
    h.d.set_compatibility(report)
    assert h.d.reviewed_context is not None and not h.d.load_button.isEnabled()
