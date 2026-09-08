from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from leonardo.artifacts import OHLCVSourceFingerprintV1
from leonardo.data import MarketId
from leonardo.data_manager.models import (
    DUPLICATE_MAINTENANCE_DOMAINS,
    DuplicateMaintenancePreflight,
)
from leonardo.gui.windows.data_manager_duplicate_maintenance_preflight_dialog import (
    DataManagerDuplicateMaintenancePreflightDialog,
)


_QAPP = QApplication.instance() or QApplication([])
MARKET = MarketId("bybit", "linear", "ADAUSDT", "4h")
SOURCE = OHLCVSourceFingerprintV1(
    MARKET,
    "1" * 64,
    "2" * 64,
    10,
    1,
    10,
    "committed",
    "ok",
    "1.0",
)


@pytest.mark.parametrize(
    ("domain_key", "display_name", "count"),
    (
        ("recipes", "Recipes", 25),
        ("recipe_collections", "Recipe Collections", 4),
    ),
)
def test_global_preflight_shows_domain_scope_and_count(
    domain_key: str, display_name: str, count: int
) -> None:
    preflight = DuplicateMaintenancePreflight(
        DUPLICATE_MAINTENANCE_DOMAINS[domain_key], count
    )
    dialog = DataManagerDuplicateMaintenancePreflightDialog(preflight)
    try:
        assert dialog.windowTitle() == "Duplicate Maintenance"
        assert dialog.label_text("domain") == display_name
        assert dialog.label_text("scope") == "Global"
        assert dialog.label_text("objects") == str(count)
        assert not dialog._labels["exchange"].isVisible()
        assert dialog.scan_button.text() == "Scan"
        assert dialog.cancel_button.text() == "Cancel"
    finally:
        dialog.close()


@pytest.mark.parametrize(
    ("domain_key", "display_name", "count"),
    (
        ("artifacts", "Artifacts", 2),
        ("artifact_collections", "Artifact Collections", 3),
    ),
)
def test_selected_ohlcv_preflight_shows_market_fingerprint_and_emits_only_on_scan(
    domain_key: str, display_name: str, count: int
) -> None:
    preflight = DuplicateMaintenancePreflight(
        DUPLICATE_MAINTENANCE_DOMAINS[domain_key],
        count,
        MARKET,
        SOURCE,
    )
    dialog = DataManagerDuplicateMaintenancePreflightDialog(preflight)
    emitted: list[object] = []
    dialog.scan_requested.connect(emitted.append)
    try:
        assert emitted == []
        assert dialog.label_text("domain") == display_name
        assert dialog.label_text("scope") == MARKET.as_key()
        assert dialog.label_text("exchange") == "bybit"
        assert dialog.label_text("market_type") == "linear"
        assert dialog.label_text("asset") == "ADAUSDT"
        assert dialog.label_text("timeframe") == "4h"
        assert SOURCE.csv_sha256 in dialog.label_text("fingerprint")
        assert SOURCE.sidecar_sha256 in dialog.label_text("fingerprint")
        dialog.scan_button.click()
        assert emitted == [preflight]
    finally:
        dialog.close()


def test_cancel_closes_without_starting_scan() -> None:
    preflight = DuplicateMaintenancePreflight(
        DUPLICATE_MAINTENANCE_DOMAINS["recipes"], 0
    )
    dialog = DataManagerDuplicateMaintenancePreflightDialog(preflight)
    emitted: list[object] = []
    dialog.scan_requested.connect(emitted.append)
    dialog.show()
    dialog.cancel_button.click()
    _QAPP.processEvents()
    assert emitted == []
    assert not isValid(dialog)
