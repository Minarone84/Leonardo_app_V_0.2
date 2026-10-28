"""Presentation and collection of one source-bound family selection."""
from copy import deepcopy

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QLabel, QSizePolicy

from leonardo.analysis.pattern_models import FamilyScope, _gr05_resolve_selection
from .trend_start_results import identify


class FamilyScopeControls(QWidget):
    changed = Signal()

    def __init__(self, parent=None, *, identity_prefix, initial=False):
        super().__init__(parent)
        self._initial = initial
        self._context = {}
        self._applying = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.mode = identify(QComboBox(self), identity_prefix + ".mode")
        self.mode.setMinimumContentsLength(12)
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mode.addItem("Use existing family selector (exact / separate overview)" if initial else "Use original request selection", None)
        if not initial:
            self.mode.addItem("One exact family", "exact")
        self.mode.addItem("Selected families (pooled)", "selected")
        self.mode.addItem("All compatible families (pooled)", "all")
        root.addWidget(self.mode)
        self.exact = identify(QComboBox(self), identity_prefix + ".exact")
        self.exact.setMinimumContentsLength(12)
        self.exact.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        root.addWidget(self.exact)
        self.search = identify(QLineEdit(self), identity_prefix + ".search")
        self.search.setPlaceholderText("Find a family (display only)")
        root.addWidget(self.search)
        self.members = identify(QListWidget(self), identity_prefix + ".members")
        self.members.setMaximumHeight(135)
        self.members.setMinimumHeight(80)
        root.addWidget(self.members)
        buttons = QHBoxLayout()
        self.select_all = identify(QPushButton("Select all compatible", self), identity_prefix + ".select_all")
        self.deselect_all = identify(QPushButton("Deselect all", self), identity_prefix + ".deselect_all")
        buttons.addWidget(self.select_all)
        buttons.addWidget(self.deselect_all)
        root.addLayout(buttons)
        self.status = identify(QLabel(self), identity_prefix + ".status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self.status)
        self.mode.currentIndexChanged.connect(self._gr05_changed)
        self.exact.currentIndexChanged.connect(self._gr05_changed)
        self.members.itemChanged.connect(self._gr05_changed)
        self.search.textChanged.connect(self._gr05_filter)
        self.select_all.clicked.connect(lambda: self._gr05_select(True))
        self.deselect_all.clicked.connect(lambda: self._gr05_select(False))
        self._applying = False
        self._gr05_refresh()

    def _gr05_checked(self):
        return tuple(self.members.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.members.count())
                     if self.members.item(i).checkState() == Qt.CheckState.Checked)

    def _gr05_members(self, checked, exact):
        families = tuple(self._context.get("families", ()))
        available = set(families)
        values = sorted(available | set(checked) | ({exact} if exact is not None else set()))
        with QSignalBlocker(self.members), QSignalBlocker(self.exact):
            self.members.clear()
            self.exact.clear()
            for value in values:
                title = value if value in available else value + " · unavailable in this source"
                item = QListWidgetItem(title, self.members)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setToolTip(title)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if value in checked else Qt.CheckState.Unchecked)
                self.exact.addItem(title, value)
                self.exact.setItemData(self.exact.count()-1, title, Qt.ItemDataRole.ToolTipRole)
            if exact is not None:
                self.exact.setCurrentIndex(self.exact.findData(exact))
        self._gr05_filter()

    def set_context(self, context):
        if not isinstance(context, dict):
            raise TypeError("family selector context requires a dictionary")
        checked, exact = self._gr05_checked(), self.exact.currentData()
        self._context = deepcopy(context)
        self._gr05_members(checked, exact)
        self._gr05_refresh()

    def set_value(self, value):
        if value is not None and type(value) is not FamilyScope:
            raise TypeError("family selector requires an exact FamilyScope or None")
        if value is not None and self._initial and value.mode == "exact":
            raise ValueError("Use the existing family selector for an initial exact family")
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(self.mode.findData(None if value is None else value.mode))
        if value is not None:
            self._gr05_members(value.families if value.mode == "selected" else (),
                               value.families[0] if value.mode == "exact" else None)
        elif not self._context:
            self._gr05_members((), None)
        self._gr05_refresh()

    def value(self):
        mode = self.mode.currentData()
        if mode is None and (self._initial or not self._context):
            return None
        value = None if mode is None else FamilyScope(mode,
            (self.exact.currentData(),) if mode == "exact" else self._gr05_checked() if mode == "selected" else ())
        if set(self._context) != {"families", "direction", "comparison", "source_selection"}:
            raise ValueError("family selection needs complete pinned source context")
        source = self._context["source_selection"]
        source = None if source is None else FamilyScope.from_dict(source)
        _gr05_resolve_selection(value, source_selection=source, universe=self._context["families"],
            direction=self._context["direction"], comparison=self._context["comparison"])
        return value

    def _gr05_filter(self, *_):
        query = self.search.text().casefold()
        for i in range(self.members.count()):
            item = self.members.item(i)
            item.setHidden(query not in item.text().casefold())

    def _gr05_select(self, selected):
        with QSignalBlocker(self.members):
            for i in range(self.members.count()):
                item = self.members.item(i)
                if not selected or item.data(Qt.ItemDataRole.UserRole) in self._context.get("families", ()):
                    item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
        self._gr05_changed()

    def _gr05_refresh(self):
        mode = self.mode.currentData()
        self.exact.setVisible(mode == "exact")
        for widget in (self.members, self.search, self.select_all, self.deselect_all):
            widget.setVisible(mode in ("selected", "all"))
        self.members.setEnabled(mode == "selected")
        self.select_all.setEnabled(mode == "selected")
        self.deselect_all.setEnabled(mode == "selected")
        count = len(self._context.get("families", ()))
        try:
            value = self.value()
            description = value.summary() if value is not None else self.mode.currentText()
            message = f"{description}\n{count} compatible families · {count if mode == 'all' else len(self._gr05_checked()) if mode == 'selected' else 1 if mode == 'exact' else 'source'} selected"
        except (ValueError, TypeError) as exc:
            message = "Invalid family selection: " + str(exc)
        question = self._context.get("comparison")
        if question:
            message += "\nRoot comparison: " + question.replace("_", " ")
        if mode == "all":
            message += "\n" + ", ".join(self._context.get("families", ()))
        self.status.setText(message)

    def _gr05_changed(self, *_):
        if not self._applying:
            self._gr05_refresh()
            self.changed.emit()
