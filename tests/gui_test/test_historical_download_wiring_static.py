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
    assert "HistoricalDownloadService" not in manager
    assert 'limit.setText("0")' in manager
    assert "validation_checklist_table" in Path(
        "src/leonardo/gui/windows/ohlcv_download_preflight_window.py"
    ).read_text(encoding="utf-8")
    assert "output_summary_table" in Path(
        "src/leonardo/gui/windows/ohlcv_download_task_window.py"
    ).read_text(encoding="utf-8")
