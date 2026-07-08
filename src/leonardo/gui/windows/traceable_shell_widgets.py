"""Small GUI-only helpers for assigning stable shell object identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QWidget


def apply_trace(
    obj: object,
    object_id: str,
    *,
    object_type: str = "",
    display_label: str = "",
    parent_object_id: str = "",
    action_id: str = "",
    tooltip: str = "",
) -> object:
    """Attach stable GUI trace fields to a Qt object and return it."""

    _validate_object_id(object_id)
    set_object_name = getattr(obj, "setObjectName", None)
    set_property = getattr(obj, "setProperty", None)
    if not callable(set_object_name) or not callable(set_property):
        raise TypeError("obj must expose Qt object identity methods")

    set_object_name(object_id)
    set_property("object_id", object_id)
    if object_type:
        set_property("object_type", object_type)
    if display_label:
        set_property("display_label", display_label)
    if parent_object_id:
        set_property("parent_object_id", parent_object_id)
    if action_id:
        set_property("action_id", action_id)
    if tooltip and isinstance(obj, QWidget):
        obj.setToolTip(tooltip)
    return obj


def configure_table(
    table: QTableWidget,
    *,
    object_id: str,
    columns: Sequence[str],
    labels: Sequence[str] | None = None,
    parent_object_id: str = "",
) -> QTableWidget:
    """Configure a read-only table with stable identity and headers."""

    apply_trace(
        table,
        object_id,
        object_type="table",
        parent_object_id=parent_object_id,
    )
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(tuple(labels or columns))
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return table


def populate_table(
    table: QTableWidget,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Populate a read-only table from deterministic display rows."""

    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, column_id in enumerate(columns):
            item = QTableWidgetItem(str(row.get(column_id, "")))
            table.setItem(row_index, column_index, item)
    table.resizeColumnsToContents()


def _validate_object_id(object_id: str) -> None:
    if not isinstance(object_id, str) or not object_id.strip():
        raise ValueError("object_id must be a non-empty string")
