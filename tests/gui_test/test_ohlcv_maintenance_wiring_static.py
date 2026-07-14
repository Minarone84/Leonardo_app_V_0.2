from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ohlcv_maintenance_gui_wiring_is_explicit_and_shell_only() -> None:
    paths = {
        "window": ROOT / "src/leonardo/gui/windows/ohlcv_maintenance_window.py",
        "presenter": ROOT / "src/leonardo/gui/presenters/ohlcv_maintenance_presenter.py",
        "composition": ROOT / "src/leonardo/gui/composition.py",
        "download_presenter": ROOT
        / "src/leonardo/gui/presenters/historical_download_presenter.py",
    }
    for path in paths.values():
        ast.parse(path.read_text(encoding="utf-8"))

    window = paths["window"].read_text(encoding="utf-8")
    presenter = paths["presenter"].read_text(encoding="utf-8")
    composition = paths["composition"].read_text(encoding="utf-8")
    download_presenter = paths["download_presenter"].read_text(encoding="utf-8")

    assert "ohlcv_maintenance.window" in window
    assert "ohlcv_maintenance.table.datasets" in window
    assert "ohlcv_maintenance.table.evidence" in window
    assert "ohlcv_maintenance.table.issues" in window
    assert "ohlcv_maintenance.table.repair" in window
    assert "refresh_requested = Signal()" in window
    assert "validate_requested = Signal()" in window
    assert "plan_repair_requested = Signal()" in window
    assert "execute_repair_requested = Signal()" in window
    assert "reconstruct_sidecar_requested = Signal()" in window
    assert "delete_requested = Signal()" in window
    assert "cancel_requested = Signal()" in window
    assert "Plan Repair" in window
    assert "Execute Repair" in window
    assert "Confirm OHLCV Repair" in window
    assert "Rebuild Sidecar" in window
    assert "Confirm OHLCV Sidecar Reconstruction" in window
    assert "Delete Selected" in window
    assert "Confirm OHLCV Dataset Deletion" in window

    assert "OhlcvMaintenancePresenter" in composition
    assert "ohlcv_maintenance_service" in composition
    assert "_open_ohlcv_maintenance" in composition
    assert "window.maintenance_requested.connect" in composition
    assert "submit_validation" in presenter
    assert "submit_repair_plan" in presenter
    assert "submit_repair" in presenter
    assert "submit_sidecar_reconstruction_plan" in presenter
    assert "submit_sidecar_reconstruction" in presenter
    assert "submit_deletion_plan" in presenter
    assert "submit_deletion" in presenter
    assert "callback_dispatcher=self._dispatcher.dispatch" in presenter
    assert "self._maintenance.discover()" in presenter
    assert "OHLCV Maintenance is not implemented yet" not in download_presenter

    for forbidden in (
        "OHLCVStore",
        "CanonicalOHLCVValidator",
        "csv.",
        "read_text(",
        "write_text(",
        "historical_data",
        "QApplication.processEvents",
        "CoreBridge",
        "leonardo.contracts",
    ):
        assert forbidden not in window


def test_existing_main_action_routes_to_dedicated_maintenance_window() -> None:
    composition = (ROOT / "src/leonardo/gui/composition.py").read_text(encoding="utf-8")
    expected = "return self._open_ohlcv_maintenance(main_window)"
    assert expected in composition
    assert "def _open_historical_download_manager" in composition
