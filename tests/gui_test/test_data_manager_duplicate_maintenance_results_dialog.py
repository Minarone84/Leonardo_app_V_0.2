from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from leonardo.data_manager.models import (
    DUPLICATE_MAINTENANCE_DOMAINS,
    DuplicateMaintenanceCandidate,
    DuplicateMaintenanceGroup,
    DuplicateMaintenancePreflight,
    DuplicateMaintenancePurgeDetail,
    DuplicateMaintenancePurgeResult,
    DuplicateMaintenanceScanResult,
)
from leonardo.gui.windows.data_manager_duplicate_maintenance_results_dialog import (
    DataManagerDuplicateMaintenanceResultsDialog,
)


_QAPP = QApplication.instance() or QApplication([])
SCANNED_AT = datetime(2026, 8, 20, 10, 30, tzinfo=UTC)


def _result_with_classifications() -> DuplicateMaintenanceScanResult:
    domain = DUPLICATE_MAINTENANCE_DOMAINS["recipe_collections"]
    return DuplicateMaintenanceScanResult(
        DuplicateMaintenancePreflight(domain, 5),
        SCANNED_AT,
        5,
        (
            DuplicateMaintenanceGroup(
                domain,
                "prc_11111111111111111111111111111111",
                (
                    DuplicateMaintenanceCandidate(
                        "prc_22222222222222222222222222222222",
                        "SAFE",
                        "younger equivalent",
                    ),
                    DuplicateMaintenanceCandidate(
                        "prc_33333333333333333333333333333333",
                        "BLOCKED",
                        "dependency exists",
                        ("Database db_1",),
                    ),
                    DuplicateMaintenanceCandidate(
                        "prc_44444444444444444444444444444444",
                        "REVIEW REQUIRED",
                        "legacy identity",
                    ),
                ),
                "Equivalent semantics",
            ),
        ),
        (
            DuplicateMaintenanceCandidate(
                "prc_55555555555555555555555555555555",
                "INVALID / SKIPPED",
                "invalid persisted Collection",
            ),
        ),
    )


def test_zero_duplicate_result_has_explicit_empty_state_and_close_only() -> None:
    domain = DUPLICATE_MAINTENANCE_DOMAINS["recipes"]
    result = DuplicateMaintenanceScanResult(
        DuplicateMaintenancePreflight(domain, 0),
        SCANNED_AT,
        0,
        (),
    )
    dialog = DataManagerDuplicateMaintenanceResultsDialog(result)
    try:
        assert dialog.windowTitle() == "Duplicate Maintenance Results"
        assert dialog.empty_label.text() == "No semantic duplicates found."
        assert dialog.empty_label.isVisibleTo(dialog)
        assert dialog.table.rowCount() == 0
        assert dialog.close_button.text() == "Close"
        assert dialog.purge_button.text() == "Purge Safe Duplicates..."
        assert not dialog.purge_button.isEnabled()
    finally:
        dialog.close()


def test_result_projects_safe_blocked_review_invalid_and_summary_counts() -> None:
    result = _result_with_classifications()
    dialog = DataManagerDuplicateMaintenanceResultsDialog(result)
    try:
        assert dialog.label_text("domain") == "Recipe Collections"
        assert dialog.label_text("scope") == "Global"
        assert dialog.label_text("objects") == "5"
        assert dialog.label_text("groups") == "1"
        assert dialog.label_text("duplicates") == "3"
        assert dialog.label_text("safe") == "1"
        assert dialog.label_text("blocked") == "1"
        assert dialog.label_text("invalid") == "1"
        assert dialog.label_text("review") == "1"
        assert not dialog._labels["historical"].isVisible()
        assert dialog.table.rowCount() == 4
        assert tuple(
            dialog.table.item(row, 0).text()
            for row in range(dialog.table.rowCount())
        ) == ("SAFE", "BLOCKED", "REVIEW REQUIRED", "INVALID / SKIPPED")
        assert dialog.table.item(1, 4).text() == "Database db_1"
        assert dialog.purge_button.isEnabled()
    finally:
        dialog.close()


def test_recipe_result_projects_semantic_tool_and_parameter_evidence() -> None:
    domain = DUPLICATE_MAINTENANCE_DOMAINS["recipes"]
    result = DuplicateMaintenanceScanResult(
        DuplicateMaintenancePreflight(domain, 2),
        SCANNED_AT,
        2,
        (
            DuplicateMaintenanceGroup(
                domain,
                "a" * 64,
                (
                    DuplicateMaintenanceCandidate(
                        "b" * 64,
                        "SAFE",
                        "historical Recipe matches canonical-current Recipe",
                    ),
                ),
                "Equivalent executable Recipe semantics",
                "sma",
                '{"period": 20}',
            ),
        ),
    )

    dialog = DataManagerDuplicateMaintenanceResultsDialog(result)
    try:
        assert dialog.table.columnCount() == 7
        assert tuple(
            dialog.table.horizontalHeaderItem(column).text()
            for column in range(dialog.table.columnCount())
        ) == (
            "Status",
            "Canonical Recipe ID",
            "Duplicate Recipe ID",
            "Tool",
            "Parameters",
            "Reason",
            "Dependency / Blocker",
        )
        assert dialog.table.item(0, 3).text() == "sma"
        assert dialog.table.item(0, 4).text() == '{"period": 20}'
    finally:
        dialog.close()


def test_safe_purge_action_emits_exact_scan_once() -> None:
    result = _result_with_classifications()
    dialog = DataManagerDuplicateMaintenanceResultsDialog(result)
    emitted: list[object] = []
    dialog.purge_requested.connect(emitted.append)
    try:
        dialog.purge_button.click()
        assert emitted == [result]
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("execution_results", "expected_title", "expected_empty"),
    (
        (("PURGED",), "Duplicate Maintenance Complete", False),
        (("PURGED", "BLOCKED"), "Duplicate Maintenance Complete", False),
        (("BLOCKED",), "Duplicate Maintenance Complete", True),
    ),
)
def test_purge_result_projects_one_summary_for_success_partial_and_no_deletion(
    execution_results: tuple[str, ...],
    expected_title: str,
    expected_empty: bool,
) -> None:
    domain = DUPLICATE_MAINTENANCE_DOMAINS["recipe_collections"]
    candidates = tuple(
        DuplicateMaintenanceCandidate(
            f"prc_{index:032x}", "SAFE", "younger equivalent"
        )
        for index in range(2, 2 + len(execution_results))
    )
    scan = DuplicateMaintenanceScanResult(
        DuplicateMaintenancePreflight(domain, len(candidates) + 1),
        SCANNED_AT,
        len(candidates) + 1,
        (
            DuplicateMaintenanceGroup(
                domain,
                "prc_11111111111111111111111111111111",
                candidates,
                "Equivalent semantics",
            ),
        ),
    )
    purge = DuplicateMaintenancePurgeResult(
        scan,
        SCANNED_AT,
        tuple(
            DuplicateMaintenancePurgeDetail(
                domain,
                candidate.object_id,
                scan.groups[0].canonical_id,
                status,
                "result reason",
            )
            for candidate, status in zip(candidates, execution_results, strict=True)
        ),
    )
    dialog = DataManagerDuplicateMaintenanceResultsDialog(purge)
    try:
        assert dialog.windowTitle() == expected_title
        assert dialog.label_text("candidates") == str(len(candidates))
        assert dialog.label_text("purged") == str(execution_results.count("PURGED"))
        assert dialog.label_text("blocked") == str(execution_results.count("BLOCKED"))
        assert dialog.label_text("winners") == "1"
        assert dialog.table.rowCount() == len(candidates)
        assert dialog.empty_label.isVisibleTo(dialog) is expected_empty
        assert not dialog.purge_button.isVisible()
    finally:
        dialog.close()
