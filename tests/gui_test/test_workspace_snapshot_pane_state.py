import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from leonardo.gui.chart.pane_workspace import ChartPaneWorkspaceWidget


def test_pane_snapshot_retains_hidden_volume_and_restore_rejects_unknown():
    QApplication.instance() or QApplication([])
    widget = ChartPaneWorkspaceWidget()
    widget.restore_pane_sizes({"price": 620, "volume": 180})
    assert widget.snapshot_pane_sizes() == {"price": 620, "volume": 180}
    with pytest.raises(ValueError, match="unknown pane"):
        widget.restore_pane_sizes({"unknown": 100})


def _boundaries(widget: ChartPaneWorkspaceWidget) -> tuple[int, ...]:
    sizes = tuple(
        size
        for index, size in enumerate(widget._splitter.sizes())
        if not widget._splitter.widget(index).isHidden()
    )
    total = sum(sizes)
    cumulative = 0
    output: list[int] = []
    for size in sizes[:-1]:
        cumulative += size
        output.append(round(cumulative * 1000 / total))
    return tuple(output)


def _on_anchor(boundary: int) -> bool:
    return abs(boundary - round(boundary / 10) * 10) <= 1


def test_legacy_pixel_snapshot_normalizes_only_when_visible_and_stays_integer_based():
    app = QApplication.instance() or QApplication([])
    widget = ChartPaneWorkspaceWidget()
    widget.set_volume_visible(True)
    widget.restore_pane_sizes({"price": 617, "volume": 183})
    assert widget.snapshot_pane_sizes() == {"price": 617, "volume": 183}

    widget.resize(800, 700)
    widget.show()
    app.processEvents()
    try:
        assert all(_on_anchor(boundary) for boundary in _boundaries(widget))
        snapshot = widget.snapshot_pane_sizes()
        assert snapshot.keys() == {"price", "volume"}
        assert all(type(value) is int and value > 0 for value in snapshot.values())
        assert not hasattr(widget, "pane_anchor_positions")
        assert not hasattr(widget, "pane_percentages")
    finally:
        widget.close()
        app.processEvents()


def test_hidden_volume_memory_normalizes_on_show_without_material_restore_drift():
    app = QApplication.instance() or QApplication([])
    widget = ChartPaneWorkspaceWidget()
    widget.resize(800, 720)
    widget.show()
    app.processEvents()
    try:
        widget.restore_pane_sizes({"price": 623, "volume": 177})
        hidden = widget.snapshot_pane_sizes()
        assert hidden["volume"] == 177
        widget.set_volume_visible(True)
        app.processEvents()
        first = _boundaries(widget)
        assert all(_on_anchor(boundary) for boundary in first)

        for _iteration in range(3):
            snapshot = widget.snapshot_pane_sizes()
            widget.restore_pane_sizes(snapshot)
            app.processEvents()
        assert _boundaries(widget) == first
        assert all(
            type(value) is int for value in widget.snapshot_pane_sizes().values()
        )
    finally:
        widget.close()
        app.processEvents()
