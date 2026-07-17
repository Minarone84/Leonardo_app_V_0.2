"""Service-free Research Notebook editor window."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data import MarketId
from leonardo.research.notebook import (
    ResearchNotebookAnnotationSettingsV1,
    ResearchNotebookDraft,
    ResearchNotebookNoteV1,
    ResearchNotebookPageV1,
    ResearchNotebookPointOfInterestV1,
    ResearchNotebookPotentialTradeV1,
    ResearchNotebookValidationError,
    ResearchNotebookV1,
)


@dataclass(frozen=True, slots=True)
class ResearchNotebookSaveIntent:
    draft: ResearchNotebookDraft
    save_as: bool


class ResearchNotebookWindow(QDialog):
    """Edit one immutable Research Notebook draft without service access."""

    draft_changed = Signal(object)
    save_requested = Signal(object)
    close_requested = Signal()
    add_current_chart_requested = Signal()
    go_to_requested = Signal(object, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("research.notebook_window")
        self.setWindowTitle("Research Notebook")
        self.resize(980, 720)
        self._notebook_id: str | None = None
        self._pages: list[ResearchNotebookPageV1] = []
        self._last_valid_draft: ResearchNotebookDraft | None = None
        self._dirty = False
        self._loading = False
        self._current_valid = False
        self._save_pending = False

        self._name = QLineEdit(self)
        self._name.setObjectName("research.notebook_window.edit.name")
        self._description = QLineEdit(self)
        self._description.setObjectName(
            "research.notebook_window.edit.description"
        )
        self._show_poi = QCheckBox("Show points of interest", self)
        self._show_poi.setObjectName(
            "research.notebook_window.check.show_poi"
        )
        self._show_trades = QCheckBox("Show potential trades", self)
        self._show_trades.setObjectName(
            "research.notebook_window.check.show_trades"
        )
        self._poi_offset = self._offset_spin(
            "research.notebook_window.spin.poi_offset"
        )
        self._long_offset = self._offset_spin(
            "research.notebook_window.spin.long_offset"
        )
        self._short_offset = self._offset_spin(
            "research.notebook_window.spin.short_offset"
        )
        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("research.notebook_window.tabs.pages")

        self._add_current = QPushButton("Add Current Chart", self)
        self._add_current.setObjectName(
            "research.notebook_window.button.add_current_chart"
        )
        self._remove_page = QPushButton("Remove Page", self)
        self._remove_page.setObjectName(
            "research.notebook_window.button.remove_page"
        )
        self._add_note = QPushButton("Add Note", self)
        self._add_note.setObjectName("research.notebook_window.button.add_note")
        self._add_trade = QPushButton("Add Trade", self)
        self._add_trade.setObjectName(
            "research.notebook_window.button.add_trade"
        )
        self._add_poi = QPushButton("Add POI", self)
        self._add_poi.setObjectName("research.notebook_window.button.add_poi")
        self._save = QPushButton("Save", self)
        self._save.setObjectName("research.notebook_window.button.save")
        self._save_as = QPushButton("Save As", self)
        self._save_as.setObjectName("research.notebook_window.button.save_as")
        self._close = QPushButton("Close", self)
        self._close.setObjectName("research.notebook_window.button.close")
        self._validation = QLabel("", self)
        self._validation.setObjectName(
            "research.notebook_window.label.validation"
        )
        self._dirty_label = QLabel("", self)
        self._dirty_label.setObjectName("research.notebook_window.label.dirty")
        self._status = QLabel("", self)
        self._status.setObjectName("research.notebook_window.label.status")

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        settings = QHBoxLayout()
        settings.addWidget(self._show_poi)
        settings.addWidget(self._show_trades)
        settings.addWidget(QLabel("POI offset", self))
        settings.addWidget(self._poi_offset)
        settings.addWidget(QLabel("Long offset", self))
        settings.addWidget(self._long_offset)
        settings.addWidget(QLabel("Short offset", self))
        settings.addWidget(self._short_offset)
        page_actions = QHBoxLayout()
        page_actions.addWidget(self._add_current)
        page_actions.addWidget(self._remove_page)
        page_actions.addStretch(1)
        row_actions = QHBoxLayout()
        row_actions.addWidget(self._add_note)
        row_actions.addWidget(self._add_trade)
        row_actions.addWidget(self._add_poi)
        row_actions.addStretch(1)
        actions = QHBoxLayout()
        actions.addWidget(self._validation, stretch=1)
        actions.addWidget(self._dirty_label)
        actions.addWidget(self._status)
        actions.addWidget(self._save)
        actions.addWidget(self._save_as)
        actions.addWidget(self._close)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(settings)
        layout.addLayout(page_actions)
        layout.addWidget(self._tabs, stretch=1)
        layout.addLayout(row_actions)
        layout.addLayout(actions)

        self._name.textChanged.connect(self._editor_changed)
        self._description.textChanged.connect(self._editor_changed)
        self._show_poi.toggled.connect(self._editor_changed)
        self._show_trades.toggled.connect(self._editor_changed)
        self._poi_offset.valueChanged.connect(self._editor_changed)
        self._long_offset.valueChanged.connect(self._editor_changed)
        self._short_offset.valueChanged.connect(self._editor_changed)
        self._add_current.clicked.connect(self.add_current_chart_requested.emit)
        self._remove_page.clicked.connect(self._remove_selected_page)
        self._save.clicked.connect(lambda: self._emit_save(False))
        self._save_as.clicked.connect(lambda: self._emit_save(True))
        self._close.clicked.connect(self.close_requested.emit)
        self._add_note.clicked.connect(lambda: self._add_row("note"))
        self._add_trade.clicked.connect(lambda: self._add_row("trade"))
        self._add_poi.clicked.connect(lambda: self._add_row("poi"))
        self.set_draft(
            ResearchNotebookDraft(
                "Untitled Notebook",
                "",
                ResearchNotebookAnnotationSettingsV1(),
                (),
            ),
            dirty=False,
        )

    @property
    def notebook_id(self) -> str | None:
        return self._notebook_id

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def is_current_valid(self) -> bool:
        return self._current_valid

    @property
    def last_valid_draft(self) -> ResearchNotebookDraft | None:
        return self._last_valid_draft

    def set_notebook(self, notebook: ResearchNotebookV1) -> None:
        if not isinstance(notebook, ResearchNotebookV1):
            raise TypeError("notebook must be ResearchNotebookV1")
        self._notebook_id = notebook.notebook_id
        self.set_draft(
            ResearchNotebookDraft(
                notebook.display_name,
                notebook.description,
                notebook.annotation_settings,
                notebook.pages,
                notebook.notebook_id,
            ),
            dirty=False,
        )

    def set_draft(self, draft: ResearchNotebookDraft, *, dirty: bool) -> None:
        if not isinstance(draft, ResearchNotebookDraft):
            raise TypeError("draft must be ResearchNotebookDraft")
        if type(dirty) is not bool:
            raise TypeError("dirty must be boolean")
        self._loading = True
        try:
            self._notebook_id = draft.notebook_id
            self._name.setText(draft.display_name)
            self._description.setText(draft.description)
            settings = draft.annotation_settings
            self._show_poi.setChecked(settings.show_points_of_interest)
            self._show_trades.setChecked(settings.show_potential_trades)
            self._poi_offset.setValue(settings.poi_offset_px)
            self._long_offset.setValue(settings.long_offset_px)
            self._short_offset.setValue(settings.short_offset_px)
            self._pages = list(draft.pages)
            self._rebuild_pages()
            self._last_valid_draft = draft
            self._current_valid = True
            self.set_dirty(dirty)
            self._validation.clear()
        finally:
            self._loading = False
            self._sync_mutation_controls()

    def current_draft(self) -> ResearchNotebookDraft:
        pages = tuple(
            self._page_from_tab(index) for index in range(self._tabs.count())
        )
        return ResearchNotebookDraft(
            display_name=self._name.text(),
            description=self._description.text(),
            annotation_settings=ResearchNotebookAnnotationSettingsV1(
                self._show_poi.isChecked(),
                self._show_trades.isChecked(),
                self._poi_offset.value(),
                self._long_offset.value(),
                self._short_offset.value(),
            ),
            pages=pages,
            notebook_id=self._notebook_id,
        )

    def add_page(self, page: ResearchNotebookPageV1) -> None:
        if not isinstance(page, ResearchNotebookPageV1):
            raise TypeError("page must be ResearchNotebookPageV1")
        for index in range(self._tabs.count()):
            if self._tabs.widget(index).property("market_id") == page.market_id:
                self._tabs.setCurrentIndex(index)
                return
        try:
            draft = self.current_draft()
        except (ResearchNotebookValidationError, ValueError) as error:
            self._status.setText(f"Cannot add page: {error}")
            return
        self._pages = list(draft.pages)
        self._pages.append(page)
        self._pages.sort(key=lambda item: item.market_id.as_key())
        self._rebuild_pages()
        self._tabs.setCurrentIndex(self._pages.index(page))
        self._editor_changed()

    def set_status(self, message: str) -> None:
        self._status.setText(str(message))

    def set_save_pending(self, pending: bool) -> None:
        self._save_pending = bool(pending)
        self._sync_mutation_controls()
        self._status.setText("Saving..." if pending else "")

    def _sync_mutation_controls(self) -> None:
        enabled = not self._save_pending
        for control in (
            self._name,
            self._description,
            self._show_poi,
            self._show_trades,
            self._poi_offset,
            self._long_offset,
            self._short_offset,
            self._tabs,
            self._add_current,
            self._remove_page,
            self._add_note,
            self._add_trade,
            self._add_poi,
        ):
            control.setEnabled(enabled)
        save_enabled = enabled and self._current_valid
        self._save.setEnabled(save_enabled)
        self._save_as.setEnabled(save_enabled)

    def set_dirty(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        self._dirty_label.setText("Unsaved changes" if self._dirty else "Saved")

    def dirty_decision(self) -> str:
        result = QMessageBox.question(
            self,
            "Unsaved Research Notebook",
            "Save changes before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return {
            QMessageBox.Save: "save",
            QMessageBox.Discard: "discard",
        }.get(result, "cancel")

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.close_requested.emit()

    def _offset_spin(self, object_name: str) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setObjectName(object_name)
        spin.setRange(-200, 200)
        return spin

    def _editor_changed(self, *_args) -> None:
        if self._loading:
            return
        try:
            draft = self.current_draft()
        except (ResearchNotebookValidationError, ValueError) as error:
            self._current_valid = False
            self._validation.setText(str(error))
            self._sync_mutation_controls()
            self.set_dirty(True)
            return
        self._last_valid_draft = draft
        self._pages = list(draft.pages)
        self._current_valid = True
        self._validation.clear()
        self._sync_mutation_controls()
        self.set_dirty(True)
        self.draft_changed.emit(draft)

    def _emit_save(self, save_as: bool) -> None:
        if not self._current_valid or self._save_pending:
            return
        try:
            draft = self.current_draft()
        except (ResearchNotebookValidationError, ValueError) as error:
            self._current_valid = False
            self._validation.setText(str(error))
            self._sync_mutation_controls()
            return
        self._last_valid_draft = draft
        self.save_requested.emit(ResearchNotebookSaveIntent(draft, save_as))

    def _remove_selected_page(self) -> None:
        index = self._tabs.currentIndex()
        if not 0 <= index < self._tabs.count():
            return
        container = self._tabs.widget(index)
        tables = container.findChildren(QTableWidget)
        if any(table.rowCount() for table in tables) and QMessageBox.question(
            self,
            "Remove Page",
            "Remove this non-empty notebook page?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._tabs.removeTab(index)
        container.deleteLater()
        self._editor_changed()

    def _rebuild_pages(self) -> None:
        self._tabs.clear()
        for page in self._pages:
            container = QWidget(self._tabs)
            notes = self._table(
                "research.notebook_window.table.notes",
                ("Go", "Delete", "UTC Date / Time", "Note"),
                len(page.notes),
            )
            trades = self._table(
                "research.notebook_window.table.trades",
                (
                    "Go",
                    "Delete",
                    "UTC Date / Time",
                    "Direction",
                    "Entry",
                    "Target",
                    "Stop",
                    "Status",
                    "Outcome",
                    "Note",
                ),
                len(page.potential_trades),
            )
            points = self._table(
                "research.notebook_window.table.poi",
                (
                    "Go",
                    "Delete",
                    "UTC Date / Time",
                    "Price",
                    "Title",
                    "Description",
                ),
                len(page.points_of_interest),
            )
            for row, item in enumerate(page.notes):
                self._set_row(
                    notes,
                    row,
                    item.row_id,
                    page.market_id,
                    ("", "", item.timestamp_ms, item.text),
                )
            for row, item in enumerate(page.potential_trades):
                self._set_row(
                    trades,
                    row,
                    item.row_id,
                    page.market_id,
                    (
                        "",
                        "",
                        item.timestamp_ms,
                        item.direction,
                        item.entry_price,
                        item.target_price,
                        item.stop_price,
                        item.status,
                        item.outcome,
                        item.note,
                    ),
                )
            for row, item in enumerate(page.points_of_interest):
                self._set_row(
                    points,
                    row,
                    item.row_id,
                    page.market_id,
                    (
                        "",
                        "",
                        item.timestamp_ms,
                        item.price,
                        item.title,
                        item.description,
                    ),
                )
            page_layout = QVBoxLayout(container)
            page_layout.addWidget(QLabel("Notes", container))
            page_layout.addWidget(notes)
            page_layout.addWidget(QLabel("Potential Trades", container))
            page_layout.addWidget(trades)
            page_layout.addWidget(QLabel("Points of Interest", container))
            page_layout.addWidget(points)
            container.setProperty("market_id", page.market_id)
            for table in (notes, trades, points):
                table.itemChanged.connect(self._editor_changed)
            self._tabs.addTab(container, page.market_id.as_key())

    @staticmethod
    def _table(name: str, columns: tuple[str, ...], rows: int) -> QTableWidget:
        table = QTableWidget(rows, len(columns))
        table.setObjectName(name)
        table.setHorizontalHeaderLabels(columns)
        return table

    def _set_row(
        self,
        table: QTableWidget,
        row: int,
        row_id: str,
        market_id: MarketId,
        values: tuple[object, ...],
    ) -> None:
        go = QPushButton("Go", table)
        go.setProperty("row_id", row_id)
        go.clicked.connect(
            lambda: self._emit_row_go(table, row_id, market_id)
        )
        delete = QPushButton("Delete", table)
        delete.setProperty("row_id", row_id)
        delete.clicked.connect(lambda: self._delete_row(table, row_id))
        table.setCellWidget(row, 0, go)
        table.setCellWidget(row, 1, delete)
        for column, value in enumerate(values[2:], start=2):
            item = QTableWidgetItem("" if value is None else str(value))
            item.setData(256, row_id)
            table.setItem(row, column, item)

    def _add_row(self, kind: str) -> None:
        index = self._tabs.currentIndex()
        if index < 0:
            self._status.setText("Add a notebook page first")
            return
        container = self._tabs.widget(index)
        market_id = container.property("market_id")
        table_name, prefix, values = {
            "note": (
                "research.notebook_window.table.notes",
                "note",
                ("", "", None, ""),
            ),
            "trade": (
                "research.notebook_window.table.trades",
                "trade",
                (
                    "",
                    "",
                    None,
                    "long",
                    None,
                    None,
                    None,
                    "planned",
                    "pending",
                    "",
                ),
            ),
            "poi": (
                "research.notebook_window.table.poi",
                "poi",
                ("", "", None, None, "", ""),
            ),
        }[kind]
        table = container.findChild(QTableWidget, table_name)
        row = table.rowCount()
        table.insertRow(row)
        self._set_row(
            table,
            row,
            f"{prefix}_{uuid4().hex}",
            market_id,
            values,
        )
        self._editor_changed()

    def _page_from_tab(self, index: int) -> ResearchNotebookPageV1:
        container = self._tabs.widget(index)
        market_id = container.property("market_id")
        notes_table = container.findChild(
            QTableWidget, "research.notebook_window.table.notes"
        )
        trades_table = container.findChild(
            QTableWidget, "research.notebook_window.table.trades"
        )
        points_table = container.findChild(
            QTableWidget, "research.notebook_window.table.poi"
        )
        notes = tuple(
            ResearchNotebookNoteV1(
                self._row_id(notes_table, row),
                self._optional_integer(notes_table.item(row, 2).text()),
                notes_table.item(row, 3).text(),
            )
            for row in range(notes_table.rowCount())
        )
        trades = tuple(
            ResearchNotebookPotentialTradeV1(
                self._row_id(trades_table, row),
                self._required_integer(trades_table.item(row, 2).text()),
                trades_table.item(row, 3).text(),
                self._optional_float(trades_table.item(row, 4).text()),
                self._optional_float(trades_table.item(row, 5).text()),
                self._optional_float(trades_table.item(row, 6).text()),
                trades_table.item(row, 7).text(),
                trades_table.item(row, 8).text(),
                trades_table.item(row, 9).text(),
            )
            for row in range(trades_table.rowCount())
        )
        points = tuple(
            ResearchNotebookPointOfInterestV1(
                self._row_id(points_table, row),
                self._required_integer(points_table.item(row, 2).text()),
                self._optional_float(points_table.item(row, 3).text()),
                points_table.item(row, 4).text(),
                points_table.item(row, 5).text(),
            )
            for row in range(points_table.rowCount())
        )
        return ResearchNotebookPageV1(market_id, notes, trades, points)

    @staticmethod
    def _row_id(table: QTableWidget, row: int) -> str:
        return str(table.cellWidget(row, 0).property("row_id"))

    @staticmethod
    def _optional_integer(value: str) -> int | None:
        return None if not value.strip() else int(value)

    @classmethod
    def _required_integer(cls, value: str) -> int:
        resolved = cls._optional_integer(value)
        if resolved is None:
            raise ResearchNotebookValidationError(
                "timestamp_ms must be an integer"
            )
        return resolved

    @staticmethod
    def _optional_float(value: str) -> float | None:
        return None if not value.strip() else float(value)

    def _emit_row_go(
        self,
        table: QTableWidget,
        row_id: str,
        market_id: MarketId,
    ) -> None:
        for row in range(table.rowCount()):
            if self._row_id(table, row) != row_id:
                continue
            try:
                timestamp = self._optional_integer(table.item(row, 2).text())
            except ValueError:
                self._status.setText("Go To requires an integer timestamp")
                return
            if timestamp is None:
                self._status.setText("Go To requires a timestamp")
                return
            if timestamp < 0:
                self._status.setText("Go To requires a non-negative timestamp")
                return
            self.go_to_requested.emit(market_id, timestamp)
            return

    def _delete_row(self, table: QTableWidget, row_id: str) -> None:
        if QMessageBox.question(
            self,
            "Delete Notebook Row",
            "Delete this notebook row?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        for row in range(table.rowCount()):
            if self._row_id(table, row) == row_id:
                table.removeRow(row)
                self._editor_changed()
                return
