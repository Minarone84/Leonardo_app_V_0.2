import json
from pathlib import Path
from types import SimpleNamespace

from leonardo.research.workspace_snapshot import ResearchWorkspaceSnapshotV1


def _snapshot():
    payload = json.loads(
        Path("tests/gui_test/fixtures/task_1022_workspace_snapshot_input.json").read_text(
            encoding="utf-8"
        )
    )["snapshot"]
    return ResearchWorkspaceSnapshotV1.from_dict(payload)


def test_frozen_append_position_plan_matches_authority():
    from leonardo.research.workspace_snapshot_service import ResearchWorkspaceSnapshotService

    service = object.__new__(ResearchWorkspaceSnapshotService)
    assert service.plan_append_positions(_snapshot(), (1, 4)) == (
        ("chart_002", 2),
        ("chart_001", 3),
    )


class _Link:
    def __init__(self, blockers=()):
        self.blockers = blockers
        self.references = []

    def validate_notebook_reference(self, notebook_id):
        self.references.append(notebook_id)
        return self.blockers


class _RejectedCatalog:
    def inspect_market(self, _market_id):
        return SimpleNamespace(reason="independent dataset rejection")


def _service_for_preflight(link):
    from leonardo.research.workspace_snapshot_service import (
        ResearchWorkspaceSnapshotService,
    )

    service = object.__new__(ResearchWorkspaceSnapshotService)
    service._notebook_link = link
    service._catalog = _RejectedCatalog()
    service._loader = object()
    service._study_setup = object()
    return service


def _schema_1_1(notebook_id):
    legacy = _snapshot()
    return ResearchWorkspaceSnapshotV1.build(
        snapshot_id=legacy.snapshot_id,
        display_name=legacy.display_name,
        description=legacy.description,
        created_at_utc=legacy.created_at_utc,
        updated_at_utc=legacy.updated_at_utc,
        workspace=legacy.workspace,
        charts=legacy.charts,
        notebook_id=notebook_id,
    )


def test_missing_assigned_notebook_blocks_at_report_level_independently():
    blocker = "assigned notebook is unavailable: notebook_missing"
    link = _Link((blocker,))
    report = _service_for_preflight(link).preflight(
        _schema_1_1("notebook_missing"),
        "replace",
        None,
    )

    assert link.references == ["notebook_missing"]
    assert blocker in report.blockers
    assert all(blocker not in chart.blockers for chart in report.charts)
    assert any(
        "independent dataset rejection" in value for value in report.blockers
    )
    assert not report.compatible


def test_valid_and_legacy_unassigned_notebook_references_do_not_add_blocker():
    valid_link = _Link()
    current_report = _service_for_preflight(valid_link).preflight(
        _schema_1_1("notebook_valid"),
        "append",
        {"occupied_positions": (1, 4), "idle": True},
    )
    legacy_link = _Link()
    legacy_report = _service_for_preflight(legacy_link).preflight(
        _snapshot(),
        "append",
        {"occupied_positions": (1, 4), "idle": True},
    )

    assert valid_link.references == ["notebook_valid"]
    assert legacy_link.references == [None]
    assert not any(
        value.startswith("assigned notebook is unavailable")
        for value in (*current_report.blockers, *legacy_report.blockers)
    )
    assert current_report.append_positions == legacy_report.append_positions
