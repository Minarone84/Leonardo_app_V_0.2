"""Small reusable Qt helpers for Leonardo Light V2 shells."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


def apply_identity(
    obj: object,
    object_id: str,
    *,
    object_type: str,
    display_label: str | None = None,
    action_id: str | None = None,
    tooltip: str | None = None,
    appearance_role: str | None = None,
    editable_properties: Sequence[str] = (),
) -> object:
    """Assign one stable runtime identity and useful dynamic properties."""
    if not isinstance(object_id, str) or not object_id.strip():
        raise ValueError("object_id must be a non-empty string")
    set_name = getattr(obj, "setObjectName", None)
    set_property = getattr(obj, "setProperty", None)
    if callable(set_name):
        set_name(object_id)
    if callable(set_property):
        set_property("object_id", object_id)
        set_property("object_type", object_type)
        if display_label is not None:
            set_property("display_label", display_label)
        if action_id is not None:
            set_property("action_id", action_id)
        if appearance_role is not None:
            set_property("appearance_role", appearance_role)
        if editable_properties:
            set_property("editable_properties", tuple(editable_properties))
    set_tooltip = getattr(obj, "setToolTip", None)
    if tooltip and callable(set_tooltip):
        set_tooltip(tooltip)
    return obj


def configure_table(
    table: QTableWidget,
    columns: Sequence[tuple[str, str]] | Sequence[str] | None = None,
    *,
    object_id: str | None = None,
    labels: Sequence[str] | None = None,
) -> QTableWidget:
    """Configure deterministic columns and common table presentation.

    The keyword form used by the donor shells and the compact positional form
    used by the lean Runtime Manager are both supported during the reset.
    """
    if columns is None:
        raise ValueError("columns are required")
    normalized_columns: tuple[tuple[str, str], ...]
    raw = tuple(columns)
    if raw and isinstance(raw[0], tuple):
        normalized_columns = tuple((str(item[0]), str(item[1])) for item in raw)  # type: ignore[index]
    else:
        ids = tuple(str(item) for item in raw)
        display_labels = tuple(labels or ids)
        if len(display_labels) != len(ids):
            raise ValueError("labels must have the same length as columns")
        normalized_columns = tuple(zip(ids, display_labels, strict=True))

    if object_id:
        apply_identity(table, object_id, object_type="table")
    table.setColumnCount(len(normalized_columns))
    table.setHorizontalHeaderLabels([label for _, label in normalized_columns])
    table.setProperty(
        "column_ids",
        tuple(column_id for column_id, _ in normalized_columns),
    )
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(24)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
    table.setAlternatingRowColors(True)
    return table


def populate_table(
    table: QTableWidget,
    column_ids: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Populate a table without applying global content-width policy."""

    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, column_id in enumerate(column_ids):
            value = row.get(column_id, "")
            item = QTableWidgetItem("" if value is None else str(value))
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            )
            table.setItem(row_index, column_index, item)
