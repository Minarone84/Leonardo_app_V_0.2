from pathlib import Path


def test_download_wiring_uses_presenter_and_preserves_research_suite_source() -> None:
    composition = Path("src/leonardo/gui/composition.py").read_text(encoding="utf-8")
    presenter = Path(
        "src/leonardo/gui/presenters/historical_download_presenter.py"
    ).read_text(encoding="utf-8")
    manager = Path(
        "src/leonardo/gui/windows/historical_download_manager_window.py"
    ).read_text(encoding="utf-8")

    assert "HistoricalDownloadPresenter" in composition
    assert "submit_preflight" in presenter
    assert "submit_download" in presenter
    assert "callback_dispatcher=self._dispatcher.dispatch" in presenter
    assert "progress_callback=self._on_preflight_progress" in presenter
    assert "self._show_preflight_pending(request)" in presenter
    assert 'exchange.addItem("")' in presenter
    assert "self._view.closed.connect(self._on_manager_closed)" in presenter
    assert "self._preflight_window.closed.connect(self._cancel_active_preflight)" in presenter
    assert "HistoricalDownloadService" not in manager
    assert 'limit.setText("0")' not in manager
    assert 'limit.setPlaceholderText("Blank or 0 = provider default")' in manager
    assert "def reset_form" in manager
    assert "def closeEvent" in manager
    assert "leonardo.connection" not in manager
    assert "leonardo.ohlcv" not in manager
    assert "validation_checklist_table" in Path(
        "src/leonardo/gui/windows/ohlcv_download_preflight_window.py"
    ).read_text(encoding="utf-8")
    assert "output_summary_table" in Path(
        "src/leonardo/gui/windows/ohlcv_download_task_window.py"
    ).read_text(encoding="utf-8")


def test_preflight_shell_exposes_only_presentation_lifecycle_signals() -> None:
    preflight = Path(
        "src/leonardo/gui/windows/ohlcv_download_preflight_window.py"
    ).read_text(encoding="utf-8")

    assert "closed = Signal()" in preflight
    assert "def closeEvent" in preflight
    assert "_normalize_table_rows(rows, _REQUEST_COLUMNS)" in preflight
    assert "_normalize_table_rows(rows, _VALIDATION_COLUMNS)" in preflight
    assert "_normalize_table_rows(rows, _WORKLOAD_COLUMNS)" in preflight
    assert "HistoricalDownloadService" not in preflight
    assert "Bybit" not in preflight
