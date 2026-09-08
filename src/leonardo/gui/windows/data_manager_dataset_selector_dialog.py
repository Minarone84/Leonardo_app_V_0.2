"""Dedicated OHLCV dataset selector for the Data Manager Suite."""

from __future__ import annotations

import math
from html import escape

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.data_manager import DataManagerCatalogSnapshot, DataManagerDatasetEntry
from leonardo.gui.action_observer import GuiActionObserver
from leonardo.gui.data_manager.table_presentation import (
    DATA_MANAGER_DATASET_COLUMNS,
    DataManagerSortKind,
    data_manager_dataset_details,
    data_manager_dataset_row,
    resize_data_manager_table,
    sort_data_manager_rows,
)
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID = "data_manager.dataset_selector.window"
DATA_MANAGER_DATASET_SEARCH_HELP_WINDOW_ID = (
    "data_manager.dataset_selector.search_help.window"
)

_FILTER_ORDER = ("exchange", "market_type", "symbol", "timeframe")
_FILTER_LABELS = {
    "exchange": "Exchange",
    "market_type": "Market Type",
    "symbol": "Symbol",
    "timeframe": "Timeframe",
}
_FILTER_TEXT_SCALE = 1.5
_COMBO_CHROME_WIDTH = 44
_DATASET_NUMBER_COLUMNS = {"Rows"}
_DATASET_UTC_COLUMNS = {"First Data", "Last Data"}

def _search_help_html(snapshot: DataManagerCatalogSnapshot) -> str:
    entries = snapshot.datasets
    states = _catalog_terms(
        "accepted" if entry.accepted else "rejected" for entry in entries
    )
    persistence = _catalog_terms(entry.persistence_status for entry in entries)
    validation = _catalog_terms(entry.validation_status for entry in entries)
    sources = _catalog_terms(entry.source for entry in entries)
    warnings = _catalog_terms(
        warning
        for entry in entries
        for warning in entry.warnings
    )
    rejection_codes = _catalog_terms(entry.rejection_code for entry in entries)
    rejection_reasons = _catalog_terms(entry.rejection_reason for entry in entries)

    return f"""
    <html>
      <body style="font-family: sans-serif; font-size: 10pt;">
        <h2 style="margin-bottom: 4px;">Dataset Search Help</h2>
        <p style="margin-top: 0;">
          Both fields are case-insensitive, accept partial text, combine with
          the dropdown filters, and combine with each other using
          <b>AND</b>. They only filter the visible catalog. They never create,
          modify, or delete dataset data.
        </p>

        <h3>Dataset ID / State</h3>
        <p>
          Searches the complete or partial canonical MarketId, the
          accepted/rejected state, the Persistence column, and the Validation
          column.
        </p>
        <p>
          <b>Example:</b> <code>BTCUSDT</code><br/>
          Shows datasets whose canonical MarketId contains
          <code>BTCUSDT</code>.
        </p>
        {_help_terms_table((
            ("States", states),
            ("Persistence", persistence),
            ("Validation", validation),
        ))}

        <h3>Source / Warning / Reason</h3>
        <p>
          Searches dataset source metadata, warning text, rejection codes,
          and rejection reasons.
        </p>
        <p>
          <b>Example:</b> <code>timestamp gap</code><br/>
          Shows datasets whose source, warning, rejection code, or rejection
          reason contains <code>timestamp gap</code>.
        </p>
        {_help_terms_table((
            ("Sources", sources),
            ("Warnings", warnings),
            ("Rejection codes", rejection_codes),
            ("Rejection reasons", rejection_reasons),
        ))}
      </body>
    </html>
    """


def _catalog_terms(values) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value).strip()
                for value in values
                if value is not None and str(value).strip()
            },
            key=str.casefold,
        )
    )


def _help_terms_table(
    rows: tuple[tuple[str, tuple[str, ...]], ...],
) -> str:
    rendered_rows = []
    for label, values in rows:
        rendered_values = (
            ", ".join(f"<code>{escape(value)}</code>" for value in values)
            if values
            else "<i>None present in the current catalog</i>"
        )
        rendered_rows.append(
            "<tr>"
            f"<td style='vertical-align: top; padding: 2px 12px 2px 0;'>"
            f"<b>{escape(label)}</b></td>"
            f"<td style='padding: 2px 0;'>{rendered_values}</td>"
            "</tr>"
        )
    return (
        "<table cellspacing='0' cellpadding='0' style='margin-bottom: 12px;'>"
        + "".join(rendered_rows)
        + "</table>"
    )


class _DataManagerDatasetSearchHelpDialog(QDialog):
    """Reusable catalog-aware help window for the two dataset search fields."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Dialog)
        self.setWindowTitle("Dataset Search Help")
        self.setObjectName("data_manager_dataset_selector_search_help_dialog")
        self.setProperty(
            "object_id",
            DATA_MANAGER_DATASET_SEARCH_HELP_WINDOW_ID,
        )
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(520, 380)
        self.resize(640, 500)

        root = QVBoxLayout(self)

        content = QTextBrowser(self)
        content.setOpenExternalLinks(False)
        content.setReadOnly(True)
        apply_identity(
            content,
            "data_manager.dataset_selector.search_help.content",
            object_type="text_browser",
        )
        self._content = content
        root.addWidget(content, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close", self)
        apply_identity(
            close_button,
            "data_manager.dataset_selector.search_help.button.close",
            object_type="button",
            display_label="Close",
            action_id="data_manager.dataset_selector.search_help.button.close",
        )
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        root.addLayout(button_row)

        self.set_catalog(DataManagerCatalogSnapshot(()))

    def set_catalog(self, snapshot: DataManagerCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerCatalogSnapshot")
        self._content.setHtml(_search_help_html(snapshot))
        self._content.verticalScrollBar().setValue(0)



class DataManagerDatasetSelectorDialog(QDialog):
    """Filter the complete OHLCV catalog and emit one accepted MarketId."""

    refresh_requested = Signal()
    market_selected = Signal(object)

    def __init__(
        self,
        *,
        action_observer: GuiActionObserver | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Dialog)
        if action_observer is not None and not callable(
            getattr(action_observer, "record_action", None)
        ):
            raise TypeError("action_observer must expose callable record_action")
        self._action_observer = action_observer
        self._catalog = DataManagerCatalogSnapshot(())
        self._visible_entries: tuple[DataManagerDatasetEntry, ...] = ()
        self._current_market: MarketId | None = None
        self._checked_markets: set[MarketId] = set()
        self._populating = False
        self._sort_state: tuple[int, bool] | None = None
        self._busy = False
        self._filters: dict[str, QComboBox] = {}
        self._filter_labels: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._search_inputs: dict[str, QLineEdit] = {}
        self._filter_layout: QGridLayout | None = None
        self._active_label: QLabel | None = None
        self._active_table: QTableWidget | None = None
        self._table: QTableWidget | None = None
        self._search_help_dialog: _DataManagerDatasetSearchHelpDialog | None = None
        self._build_dialog()

    def button_for_id(self, button_id: str) -> QPushButton:
        try:
            return self._buttons[button_id]
        except KeyError as error:
            raise KeyError(f"Unknown dataset selector button: {button_id}") from error

    def table_for_id(self, table_id: str) -> QTableWidget:
        tables = {
            "data_manager.dataset_selector.table.active_dataset": self._active_table,
            "data_manager.table.datasets": self._table,
        }
        table = tables.get(table_id)
        if table is None:
            raise KeyError(f"Unknown dataset selector table: {table_id}")
        return table

    def filter_for_id(self, filter_id: str) -> QComboBox | QLineEdit:
        prefix = "data_manager.dataset_selector.filter."
        if not filter_id.startswith(prefix):
            raise KeyError(f"Unknown dataset selector filter: {filter_id}")
        key = filter_id[len(prefix) :]
        if key in self._search_inputs:
            return self._search_inputs[key]
        try:
            return self._filters[key]
        except KeyError as error:
            raise KeyError(f"Unknown dataset selector filter: {filter_id}") from error

    def set_catalog(self, snapshot: DataManagerCatalogSnapshot) -> None:
        if not isinstance(snapshot, DataManagerCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerCatalogSnapshot")
        pending_checks = set(self._checked_markets)
        self._catalog = snapshot
        self._checked_markets = pending_checks
        if self._search_help_dialog is not None:
            self._search_help_dialog.set_catalog(snapshot)
        self._rebuild_filter_values()
        self._populate_active_dataset()
        self._populate()

    def set_current_market(self, market_id: MarketId | None) -> None:
        if market_id is not None and not isinstance(market_id, MarketId):
            raise TypeError("market_id must be a MarketId or None")
        self._current_market = market_id
        self._checked_markets = set() if market_id is None else {market_id}
        self._populate_active_dataset()
        self._populate(preferred_market=market_id)

    def selected_market_id(self) -> MarketId | None:
        if len(self._checked_markets) != 1:
            return None
        checked_market = next(iter(self._checked_markets))
        entry = next(
            (
                item
                for item in self._visible_entries
                if item.market_id == checked_market
            ),
            None,
        )
        if entry is None or not entry.accepted:
            return None
        return entry.market_id

    def clear_selection(self) -> None:
        self._checked_markets.clear()
        if self._table is not None:
            self._populate()
        self._sync_actions()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        controls = (
            *self._filters.values(),
            *self._search_inputs.values(),
            self._table,
        )
        for control in controls:
            if control is not None:
                control.setEnabled(not self._busy)
        self._sync_actions()

    def prepare_for_market(self, market_id: MarketId | None) -> None:
        """Synchronize the active identity immediately before the dialog is shown."""

        self.set_current_market(market_id)

    def _build_dialog(self) -> None:
        self.setWindowTitle("Select OHLCV Dataset")
        self.setObjectName("data_manager_dataset_selector_dialog")
        self.setProperty("object_id", DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1240, 680)

        root = QVBoxLayout(self)

        filter_panel = QWidget(self)
        filter_layout = QGridLayout(filter_panel)
        self._filter_layout = filter_layout
        for column, key in enumerate(_FILTER_ORDER):
            caption = QLabel(_FILTER_LABELS[key], filter_panel)
            apply_identity(
                caption,
                f"data_manager.dataset_selector.label.{key}",
                object_type="label",
            )
            combo = QComboBox(filter_panel)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            combo.addItem("All", "")
            apply_identity(
                combo,
                f"data_manager.dataset_selector.filter.{key}",
                object_type="combo_box",
            )
            combo.currentIndexChanged.connect(self._on_dropdown_changed)
            self._filter_labels[key] = caption
            self._filters[key] = combo
            filter_layout.addWidget(caption, 0, column)
            filter_layout.addWidget(combo, 1, column)

        search_row = QHBoxLayout()
        show_all = QPushButton("All", filter_panel)
        apply_identity(
            show_all,
            "data_manager.dataset_selector.button.show_all",
            object_type="button",
            display_label="Show all datasets",
            action_id="data_manager.dataset_selector.button.show_all",
            tooltip="Reset every filter to All and show the complete catalog.",
        )
        show_all.clicked.connect(
            lambda: self._invoke_action(
                "data_manager.dataset_selector.button.show_all",
                self._show_all_datasets,
            )
        )
        self._buttons["data_manager.dataset_selector.button.show_all"] = show_all
        search_row.addWidget(show_all)
        search_row.addSpacing(8)

        help_button = QPushButton("?", filter_panel)
        help_button.setFixedWidth(28)
        help_button.setToolTip("Open dataset search help.")
        apply_identity(
            help_button,
            "data_manager.dataset_selector.button.filter_help",
            object_type="button",
            display_label="Dataset search help",
            action_id="data_manager.dataset_selector.button.filter_help",
        )
        help_button.clicked.connect(
            lambda: self._invoke_action(
                "data_manager.dataset_selector.button.filter_help",
                self._show_search_help,
            )
        )
        self._buttons[
            "data_manager.dataset_selector.button.filter_help"
        ] = help_button
        search_row.addWidget(help_button)

        id_state_label = QLabel("Dataset ID / State", filter_panel)
        apply_identity(
            id_state_label,
            "data_manager.dataset_selector.label.text",
            object_type="label",
        )
        id_state_search = QLineEdit(filter_panel)
        id_state_search.setClearButtonEnabled(True)
        id_state_search.setPlaceholderText("Example: BTCUSDT, accepted, invalid…")
        id_state_search.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        apply_identity(
            id_state_search,
            "data_manager.dataset_selector.filter.text",
            object_type="line_edit",
        )
        id_state_search.textChanged.connect(self._on_text_filter_changed)
        self._search_inputs["text"] = id_state_search
        search_row.addWidget(id_state_label)
        search_row.addWidget(id_state_search, 1)

        source_reason_label = QLabel("Source / Warning / Reason", filter_panel)
        apply_identity(
            source_reason_label,
            "data_manager.dataset_selector.label.source_reason",
            object_type="label",
        )
        source_reason_search = QLineEdit(filter_panel)
        source_reason_search.setClearButtonEnabled(True)
        source_reason_search.setPlaceholderText(
            "Example: legacy import, timestamp gap…"
        )
        source_reason_search.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        apply_identity(
            source_reason_search,
            "data_manager.dataset_selector.filter.source_reason",
            object_type="line_edit",
        )
        source_reason_search.textChanged.connect(self._on_text_filter_changed)
        self._search_inputs["source_reason"] = source_reason_search
        search_row.addWidget(source_reason_label)
        search_row.addWidget(source_reason_search, 1)
        filter_layout.addLayout(search_row, 2, 0, 1, len(_FILTER_ORDER))
        root.addWidget(filter_panel)

        active_label = QLabel("Active Dataset", self)
        apply_identity(
            active_label,
            "data_manager.dataset_selector.label.active_dataset",
            object_type="label",
        )
        active_label.hide()
        self._active_label = active_label
        root.addWidget(active_label)

        active_table = self._create_dataset_table(
            "data_manager.dataset_selector.table.active_dataset",
            selectable=False,
        )
        active_table.hide()
        self._active_table = active_table
        root.addWidget(active_table)

        table = self._create_dataset_table(
            "data_manager.table.datasets",
            selectable=True,
        )
        table.horizontalHeader().setSectionsClickable(True)
        table.horizontalHeader().setSortIndicatorShown(False)
        table.horizontalHeader().sectionClicked.connect(self._on_sort_column)
        table.itemSelectionChanged.connect(self._sync_actions)
        table.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        self._table = table
        root.addWidget(table, 1)

        button_row = QHBoxLayout()
        refresh = self._button(
            "data_manager.dataset_selector.button.refresh",
            "Refresh",
            self.refresh_requested.emit,
        )
        select = self._button(
            "data_manager.dataset_selector.button.select",
            "Select",
            self._accept_selection,
        )
        cancel = self._button(
            "data_manager.dataset_selector.button.cancel",
            "Cancel",
            self.reject,
        )
        select.setDefault(True)
        button_row.addWidget(refresh)
        button_row.addStretch(1)
        button_row.addWidget(select)
        button_row.addWidget(cancel)
        root.addLayout(button_row)

        self._search_help_dialog = _DataManagerDatasetSearchHelpDialog(self)
        self.finished.connect(self._close_search_help_dialog)

        self._update_filter_widths()
        self._sync_actions()

    def _create_dataset_table(
        self,
        object_id: str,
        *,
        selectable: bool,
    ) -> QTableWidget:
        columns = (
            ("Select", *DATA_MANAGER_DATASET_COLUMNS)
            if selectable
            else DATA_MANAGER_DATASET_COLUMNS
        )
        table = configure_table(
            QTableWidget(self),
            object_id=object_id,
            columns=columns,
            labels=columns,
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        if selectable:
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
        else:
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return table

    def _button(self, object_id: str, label: str, callback) -> QPushButton:
        button = QPushButton(label, self)
        apply_identity(
            button,
            object_id,
            object_type="button",
            display_label=label,
            action_id=object_id,
        )
        button.clicked.connect(
            lambda _checked=False, current=object_id, action=callback: (
                self._invoke_action(current, action)
            )
        )
        self._buttons[object_id] = button
        return button

    def _on_dropdown_changed(self, _index: int) -> None:
        self._rebuild_filter_values()
        self._populate()

    def _on_text_filter_changed(self, _text: str) -> None:
        self._populate()

    def _on_sort_column(self, column: int) -> None:
        if column == 0:
            return
        previous = self._sort_state
        descending = previous is not None and previous == (column, False)
        self._sort_state = (column, descending)
        header = self.table_for_id("data_manager.table.datasets").horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(
            column,
            Qt.SortOrder.DescendingOrder
            if descending
            else Qt.SortOrder.AscendingOrder,
        )
        self._populate()

    def _sort_kind(self, column: int) -> DataManagerSortKind:
        label = DATA_MANAGER_DATASET_COLUMNS[column - 1]
        if label in _DATASET_NUMBER_COLUMNS:
            return "number"
        if label in _DATASET_UTC_COLUMNS:
            return "utc"
        return "text"

    def _rebuild_filter_values(self) -> None:
        previous = {
            key: str(combo.currentData() or "")
            for key, combo in self._filters.items()
        }
        resolved: dict[str, str] = {}
        for key in _FILTER_ORDER:
            options = sorted(
                {
                    str(getattr(entry.market_id, key))
                    for entry in self._catalog.datasets
                    if entry.market_id is not None
                    and _matches_selected_prefix(entry, resolved)
                },
                key=str.casefold,
            )
            selected = previous.get(key, "")
            if selected not in options:
                selected = ""
            combo = self._filters[key]
            blocker = QSignalBlocker(combo)
            combo.clear()
            combo.addItem("All", "")
            for value in options:
                combo.addItem(value, value)
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            del blocker
            resolved[key] = selected
        self._update_filter_widths()

    def _update_filter_widths(self) -> None:
        layout = self._filter_layout
        if layout is None:
            return
        for column, key in enumerate(_FILTER_ORDER):
            combo = self._filters[key]
            label = self._filter_labels[key]
            metrics = combo.fontMetrics()
            widest_item = max(
                (metrics.horizontalAdvance(combo.itemText(index))
                 for index in range(combo.count())),
                default=0,
            )
            label_width = label.fontMetrics().horizontalAdvance(label.text())
            text_width = max(widest_item, label_width)
            minimum_width = (
                math.ceil(text_width * _FILTER_TEXT_SCALE) + _COMBO_CHROME_WIDTH
            )
            combo.setMinimumWidth(minimum_width)
            layout.setColumnMinimumWidth(column, minimum_width)
            layout.setColumnStretch(column, max(1, minimum_width))

    def _show_all_datasets(self) -> None:
        for combo in self._filters.values():
            blocker = QSignalBlocker(combo)
            combo.setCurrentIndex(0)
            del blocker
        for search in self._search_inputs.values():
            blocker = QSignalBlocker(search)
            search.clear()
            del blocker
        self._rebuild_filter_values()
        self._populate()

    def _populate_active_dataset(self) -> None:
        table = self._active_table
        label = self._active_label
        if table is None or label is None:
            return
        entry = next(
            (
                item
                for item in self._catalog.datasets
                if item.market_id == self._current_market
            ),
            None,
        )
        blocker = QSignalBlocker(table)
        table.setRowCount(0 if entry is None else 1)
        if entry is not None:
            self._write_dataset_row(table, 0, entry)
        del blocker
        visible = entry is not None
        label.setVisible(visible)
        table.setVisible(visible)
        self._resize_dataset_tables()

    def _populate(self, preferred_market: MarketId | None = None) -> None:
        table = self._table
        if table is None:
            return
        checked_before = (
            {preferred_market}
            if preferred_market is not None
            else set(self._checked_markets)
        )
        selected_filters = {
            key: str(combo.currentData() or "").casefold()
            for key, combo in self._filters.items()
        }
        id_state_text = self._search_inputs["text"].text().strip().casefold()
        source_reason_text = (
            self._search_inputs["source_reason"].text().strip().casefold()
        )

        filtered = tuple(
            entry
            for entry in self._catalog.datasets
            if _matches_dropdowns(entry, selected_filters)
            and _matches_id_state_search(entry, id_state_text)
            and _matches_source_reason_search(entry, source_reason_text)
        )
        visible = filtered
        if self._sort_state is not None:
            column, descending = self._sort_state
            projected = sort_data_manager_rows(
                tuple((data_manager_dataset_row(entry), entry) for entry in filtered),
                column=column - 1,
                kind=self._sort_kind(column),
                descending=descending,
            )
            visible = tuple(entry for _values, entry in projected)
        visible_accepted = {
            entry.market_id
            for entry in visible
            if entry.accepted and entry.market_id is not None
        }
        checked_before &= visible_accepted
        self._checked_markets = checked_before
        blocker = QSignalBlocker(table)
        self._populating = True
        try:
            table.setRowCount(len(visible))
            table.clearSelection()
            self._visible_entries = visible
            for row, entry in enumerate(visible):
                self._write_dataset_row(table, row, entry)
            if len(checked_before) == 1:
                selected_before = next(iter(checked_before))
                for row, entry in enumerate(visible):
                    if entry.accepted and entry.market_id == selected_before:
                        table.selectRow(row)
                        break
        finally:
            self._populating = False
            del blocker
        self._resize_dataset_tables()
        self._sync_actions()

    def _write_dataset_row(
        self,
        table: QTableWidget,
        row: int,
        entry: DataManagerDatasetEntry,
    ) -> None:
        details = data_manager_dataset_details(entry)
        offset = 0
        if table is self._table:
            offset = 1
            checkbox = QCheckBox(table)
            checkbox.setChecked(
                entry.accepted and entry.market_id in self._checked_markets
            )
            checkbox.setEnabled(entry.accepted and entry.market_id is not None)
            checkbox.setToolTip(details)
            checkbox.setStyleSheet(
                "QCheckBox::indicator { width: 16px; height: 16px; }"
                "QCheckBox::indicator:unchecked {"
                " border: 1px solid #8C98A8; background: #20252D; }"
                "QCheckBox::indicator:checked {"
                " border: 1px solid #59A6FF; background: #2D78C4; }"
            )
            checkbox.toggled.connect(
                lambda checked, market=entry.market_id: self._dataset_toggled(
                    market, checked
                )
            )
            holder = QWidget(table)
            layout = QHBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(checkbox)
            table.setCellWidget(row, 0, holder)
        for column, value in enumerate(data_manager_dataset_row(entry), start=offset):
            item = QTableWidgetItem(value)
            item.setToolTip(details)
            table.setItem(row, column, item)

    def _dataset_toggled(
        self,
        market_id: MarketId | None,
        checked: bool,
    ) -> None:
        if self._populating or market_id is None:
            return
        if checked:
            self._checked_markets.add(market_id)
        else:
            self._checked_markets.discard(market_id)
        self._populate()

    def _resize_dataset_tables(self) -> None:
        tables = tuple(
            table
            for table in (self._active_table, self._table)
            if table is not None
        )
        if not tables:
            return
        for table in tables:
            resize_data_manager_table(table)
        active = self._active_table
        selectable = self._table
        if active is not None and selectable is not None:
            selectable.setColumnWidth(0, 58)
            for column in range(len(DATA_MANAGER_DATASET_COLUMNS)):
                width = max(
                    active.columnWidth(column),
                    selectable.columnWidth(column + 1),
                )
                active.setColumnWidth(column, width)
                selectable.setColumnWidth(column + 1, width)
        self._fit_active_table_height()

    def _fit_active_table_height(self) -> None:
        table = self._active_table
        if table is None or table.rowCount() == 0:
            return
        height = (
            table.horizontalHeader().height()
            + table.rowHeight(0)
            + table.horizontalScrollBar().sizeHint().height()
            + (table.frameWidth() * 2)
            + 4
        )
        table.setFixedHeight(height)

    def _selected_entry(self) -> DataManagerDatasetEntry | None:
        return next(
            (
                entry
                for entry in self._visible_entries
                if len(self._checked_markets) == 1
                and entry.market_id in self._checked_markets
            ),
            None,
        )

    def _sync_actions(self) -> None:
        selected = self._selected_entry()
        refresh = self._buttons.get("data_manager.dataset_selector.button.refresh")
        select = self._buttons.get("data_manager.dataset_selector.button.select")
        cancel = self._buttons.get("data_manager.dataset_selector.button.cancel")
        show_all = self._buttons.get("data_manager.dataset_selector.button.show_all")
        help_button = self._buttons.get(
            "data_manager.dataset_selector.button.filter_help"
        )
        if refresh is not None:
            refresh.setEnabled(not self._busy)
        if select is not None:
            select.setEnabled(
                not self._busy
                and selected is not None
                and selected.accepted
                and selected.market_id is not None
            )
        if cancel is not None:
            cancel.setEnabled(True)
        if show_all is not None:
            show_all.setEnabled(not self._busy)
        if help_button is not None:
            help_button.setEnabled(not self._busy)

    def _accept_selection(self) -> None:
        market_id = self.selected_market_id()
        if self._busy or market_id is None:
            return
        self.market_selected.emit(market_id)
        self.accept()

    def _show_search_help(self) -> None:
        dialog = self._search_help_dialog
        if dialog is None:
            return
        dialog.set_catalog(self._catalog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_search_help_dialog(self, _result: int) -> None:
        dialog = self._search_help_dialog
        if dialog is not None and dialog.isVisible():
            dialog.reject()

    def _invoke_action(self, action_id: str, callback) -> None:
        if self._action_observer is not None:
            decision = self._action_observer.record_action(
                action_id,
                window_id=DATA_MANAGER_DATASET_SELECTOR_WINDOW_ID,
            )
            if not decision.allowed:
                return
        callback()


def _matches_selected_prefix(
    entry: DataManagerDatasetEntry,
    selected: dict[str, str],
) -> bool:
    market = entry.market_id
    if market is None:
        return False
    return all(
        not value or str(getattr(market, key)) == value
        for key, value in selected.items()
    )


def _matches_dropdowns(
    entry: DataManagerDatasetEntry,
    selected: dict[str, str],
) -> bool:
    market = entry.market_id
    if market is None:
        return not any(selected.values())
    return all(
        not selected[key] or selected[key] == str(getattr(market, key)).casefold()
        for key in _FILTER_ORDER
    )


def _matches_id_state_search(entry: DataManagerDatasetEntry, token: str) -> bool:
    if not token:
        return True
    market = entry.market_id
    values = (
        "" if market is None else market.as_key(),
        "accepted" if entry.accepted else "rejected",
        entry.persistence_status,
        entry.validation_status,
    )
    return token in " | ".join(values).casefold()

def _matches_source_reason_search(
    entry: DataManagerDatasetEntry,
    token: str,
) -> bool:
    if not token:
        return True
    values = (
        entry.source,
        entry.rejection_code,
        entry.rejection_reason,
        *entry.warnings,
    )
    return token in " | ".join(values).casefold()
