from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from leonardo.data import MarketId
from leonardo.gui.presenters.research_presenter import ResearchSuitePresenter


def test_research_handoff_publishes_only_active_canonical_market_id() -> None:
    market = MarketId("bybit", "linear", "ETHUSDT", "15m")
    received = []
    fake = SimpleNamespace(
        _disposed=False,
        _snapshot_restore=None,
        _active_presenter=lambda: SimpleNamespace(
            session=SimpleNamespace(dataset=SimpleNamespace(market_id=market))
        ),
        _view=SimpleNamespace(append_status=lambda _message: None),
        _open_data_manager=received.append,
    )
    ResearchSuitePresenter._request_data_manager(fake)
    assert received == [market]
    assert isinstance(received[0], MarketId)


def test_research_handoff_without_dataset_changes_no_data_manager_state() -> None:
    messages = []
    received = []
    fake = SimpleNamespace(
        _disposed=False,
        _snapshot_restore=None,
        _active_presenter=lambda: None,
        _view=SimpleNamespace(append_status=messages.append),
        _open_data_manager=received.append,
    )
    ResearchSuitePresenter._request_data_manager(fake)
    assert received == []
    assert "active accepted dataset" in messages[0]
