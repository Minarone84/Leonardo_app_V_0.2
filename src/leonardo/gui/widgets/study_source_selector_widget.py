"""Signal-only source selection form for Research Study Setup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from leonardo.research import (
    StudySetupCatalog,
    StudySetupSourceSelection,
    StudySourceOption,
)


@dataclass(slots=True)
class _SourceRow:
    role: str
    optional: bool
    container: QWidget
    kind: QComboBox
    item: QComboBox
    output: QComboBox
    remove: QPushButton


class StudySourceSelectorWidget(QWidget):
    """Render frozen source roles and expose only immutable form intent."""

    intent_changed = Signal()

    def __init__(
        self,
        catalog: StudySetupCatalog,
        schema: tuple[str, ...] = (),
        parent: QWidget | None = None,
        *,
        role_labels: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be StudySetupCatalog")
        self.setObjectName("research.study_source_selector")
        self._catalog = catalog
        self._role_labels = dict(role_labels or {})
        if any(
            not isinstance(role, str)
            or not role
            or not isinstance(label, str)
            or not label
            for role, label in self._role_labels.items()
        ):
            raise ValueError("role_labels must contain non-empty text pairs")
        self._schema: tuple[str, ...] = ()
        self._rows: list[_SourceRow] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._add = QPushButton("Add Source", self)
        self._add.setObjectName("research.study_source_selector.button.add")
        self._add.clicked.connect(self._add_dynamic_row)
        self._layout.addWidget(self._add)
        self.set_schema(schema)

    @property
    def schema(self) -> tuple[str, ...]:
        return self._schema

    def set_catalog(self, catalog: StudySetupCatalog) -> None:
        if not isinstance(catalog, StudySetupCatalog):
            raise TypeError("catalog must be StudySetupCatalog")
        self._catalog = catalog
        for row in self._rows:
            self._populate_items(row, emit=False)

    def set_schema(self, schema: tuple[str, ...]) -> None:
        resolved = tuple(schema)
        self._clear_rows()
        self._schema = resolved
        if resolved == ("source_1", "..."):
            self._append_row("source_1", optional=False, removable=False)
            self._add.setVisible(True)
        elif resolved == ("peak+trough?",):
            self._add.setText("Add Peak / Trough")
            self._add.setVisible(True)
        elif resolved == ("fast", "mid?", "slow"):
            self._append_row("fast", optional=False, removable=False)
            self._append_row("slow", optional=False, removable=False)
            self._add.setText("Add Mid")
            self._add.setVisible(True)
        else:
            self._add.setVisible(False)
            for item in resolved:
                optional = item.endswith("?")
                role = item.removesuffix("?")
                if optional:
                    continue
                self._append_row(role, optional=False, removable=False)
        self.intent_changed.emit()

    def selections(self) -> tuple[StudySetupSourceSelection, ...]:
        values: list[StudySetupSourceSelection] = []
        for row in self._rows:
            option = row.item.currentData()
            if not isinstance(option, StudySourceOption):
                continue
            values.append(
                StudySetupSourceSelection(
                    role=row.role,
                    source_kind=option.source_kind,
                    column_name=option.column_name,
                    study_id=option.study_id,
                    artifact_kind=option.artifact_kind,
                    artifact_tool_key=option.artifact_tool_key,
                    artifact_id=option.artifact_id,
                    output_name=option.output_name,
                )
            )
        if self._schema == ("fast", "mid?", "slow"):
            order = {"fast": 0, "mid": 1, "slow": 2}
            values.sort(key=lambda item: order[item.role])
        return tuple(values)

    def select_option(self, role: str, option: StudySourceOption) -> None:
        row = next((candidate for candidate in self._rows if candidate.role == role), None)
        if row is None:
            raise KeyError(role)
        kind_index = row.kind.findData(option.source_kind)
        if kind_index < 0:
            raise ValueError("source kind is unavailable")
        row.kind.setCurrentIndex(kind_index)
        for index in range(row.item.count()):
            if row.item.itemData(index) == option:
                row.item.setCurrentIndex(index)
                return
        raise ValueError("source option is unavailable")

    def _add_dynamic_row(self) -> None:
        if self._schema == ("peak+trough?",):
            if self._rows:
                return
            self._append_row("peak", optional=True, removable=True)
            self._append_row("trough", optional=True, removable=True)
        elif self._schema == ("fast", "mid?", "slow"):
            if any(row.role == "mid" for row in self._rows):
                return
            self._append_row("mid", optional=True, removable=True)
        elif self._schema == ("source_1", "..."):
            self._append_row(
                f"source_{len(self._rows) + 1}", optional=False, removable=True
            )
        self.intent_changed.emit()

    def _append_row(self, role: str, *, optional: bool, removable: bool) -> None:
        container = QWidget(self)
        index = len(self._rows) + 1
        container.setObjectName(f"research.study_source_selector.row.{index}")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(
            self._role_labels.get(role, role.replace("_", " ").title()),
            container,
        )
        label.setObjectName(f"research.study_source_selector.row.{index}.role")
        kind = QComboBox(container)
        kind.setObjectName(f"research.study_source_selector.row.{index}.kind")
        for source_kind, title in (
            ("ohlcv", "OHLCV"),
            ("study", "Current Study"),
            ("artifact", "Saved Artifact"),
        ):
            kind.addItem(title, source_kind)
        item = QComboBox(container)
        item.setObjectName(f"research.study_source_selector.row.{index}.item")
        output = QComboBox(container)
        output.setObjectName(f"research.study_source_selector.row.{index}.output")
        output.setEnabled(False)
        remove = QPushButton("Remove", container)
        remove.setObjectName(f"research.study_source_selector.row.{index}.remove")
        remove.setVisible(removable)
        layout.addWidget(label)
        layout.addWidget(kind)
        layout.addWidget(item, 1)
        layout.addWidget(output)
        layout.addWidget(remove)
        row = _SourceRow(role, optional, container, kind, item, output, remove)
        self._rows.append(row)
        self._layout.insertWidget(self._layout.count() - 1, container)
        kind.currentIndexChanged.connect(lambda _index, current=row: self._kind_changed(current))
        item.currentIndexChanged.connect(lambda _index, current=row: self._item_changed(current))
        remove.clicked.connect(lambda _checked=False, current=row: self._remove_row(current))
        self._populate_items(row, emit=False)

    def _kind_changed(self, row: _SourceRow) -> None:
        self._populate_items(row, emit=True)

    def _populate_items(self, row: _SourceRow, *, emit: bool) -> None:
        source_kind = row.kind.currentData()
        row.item.blockSignals(True)
        row.item.clear()
        for option in self._catalog.source_options:
            if option.source_kind == source_kind:
                row.item.addItem(option.label, option)
        if source_kind == "artifact":
            for artifact in self._catalog.artifact_options:
                for output in artifact.output_names:
                    if output not in artifact.analysis_usable_output_names:
                        self._add_disabled_item(
                            row.item,
                            f"{artifact.display_name}: {output} - not analysis-usable",
                        )
            for rejection in self._catalog.artifact_rejections:
                self._add_disabled_item(
                    row.item,
                    f"{rejection.tool_key}: {rejection.artifact_id} - {rejection.reason}",
                )
        row.item.setCurrentIndex(-1)
        row.item.blockSignals(False)
        row.output.clear()
        if emit:
            self.intent_changed.emit()

    @staticmethod
    def _add_disabled_item(combo: QComboBox, label: str) -> None:
        combo.addItem(label)
        item = combo.model().item(combo.count() - 1)
        if item is not None:
            item.setEnabled(False)

    def _item_changed(self, row: _SourceRow) -> None:
        option = row.item.currentData()
        row.output.clear()
        if isinstance(option, StudySourceOption) and option.output_name is not None:
            row.output.addItem(option.output_name, option.output_name)
        self.intent_changed.emit()

    def _remove_row(self, row: _SourceRow) -> None:
        if row not in self._rows:
            return
        if self._schema == ("peak+trough?",):
            targets = tuple(self._rows)
        else:
            targets = (row,)
        for target in targets:
            self._rows.remove(target)
            self._layout.removeWidget(target.container)
            target.container.deleteLater()
        if self._schema == ("source_1", "..."):
            for index, target in enumerate(self._rows, start=1):
                target.role = f"source_{index}"
        self.intent_changed.emit()

    def _clear_rows(self) -> None:
        for row in self._rows:
            self._layout.removeWidget(row.container)
            row.container.deleteLater()
        self._rows.clear()
        self._add.setText("Add Source")
