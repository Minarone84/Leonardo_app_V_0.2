"""Explicit nine-stage Data Manager database-creation workspace."""

from __future__ import annotations

import json
from functools import partial

from PySide6.QtCore import QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.financial_tools import CONSTRUCT_SPECS
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


CREATION_STAGES = (
    "1. Target OHLCV",
    "2. Database Seed",
    "3. Study Environments",
    "4. Recipes",
    "5. Base Artifacts",
    "6. Batch Artifacts",
    "7. Artifact Collection",
    "8. Database Review",
    "9. Build Database",
)


class DataManagerCreationWorkspace(QWidget):
    """Capture explicit creation intent without owning domain behavior."""

    action_requested = Signal(str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        apply_identity(self, "data_manager.creation.workspace", object_type="workspace")
        self.buttons: dict[str, QPushButton] = {}
        self.controls: dict[str, QWidget] = {}
        self._busy = False
        self._base_plan_ready = False
        self._batch_plan_ready = False
        self._database_readiness_ready = False
        self.stage_list = QListWidget(self)
        apply_identity(
            self.stage_list,
            "data_manager.creation.list.stages",
            object_type="list",
        )
        self.stage_list.addItems(CREATION_STAGES)
        self.stage_list.setFixedWidth(220)
        self.stack = QStackedWidget(self)
        apply_identity(
            self.stack,
            "data_manager.creation.stack.stages",
            object_type="stack",
        )
        self.stage_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        for page in (
            self._target_page(),
            self._seed_page(),
            self._environment_page(),
            self._recipe_page(),
            self._base_artifact_page(),
            self._batch_page(),
            self._artifact_collection_page(),
            self._review_page(),
            self._build_page(),
        ):
            self.stack.addWidget(page)
        self.summary = QLabel("Select an accepted Target OHLCV to begin.", self)
        self.summary.setWordWrap(True)
        apply_identity(
            self.summary,
            "data_manager.creation.summary",
            object_type="status_label",
        )
        right = QVBoxLayout()
        right.addWidget(self.stack, 1)
        right.addWidget(self.summary)
        layout = QHBoxLayout(self)
        layout.addWidget(self.stage_list)
        layout.addLayout(right, 1)
        self.stage_list.setCurrentRow(0)
        self._wire_context_changes()
        self._sync_gating()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.stage_list.setEnabled(not self._busy)
        self._sync_gating()

    def set_base_plan_ready(self, ready: bool) -> None:
        self._base_plan_ready = bool(ready)
        self._sync_gating()

    def set_batch_plan_ready(self, ready: bool) -> None:
        self._batch_plan_ready = bool(ready)
        self._sync_gating()

    def set_database_readiness_ready(self, ready: bool) -> None:
        self._database_readiness_ready = bool(ready)
        self._sync_gating()

    def invalidate_all_plans(self) -> None:
        self._base_plan_ready = False
        self._batch_plan_ready = False
        self._database_readiness_ready = False
        self._sync_gating()

    def select_stage(self, index: int) -> None:
        if not 0 <= index < len(CREATION_STAGES):
            raise ValueError("creation stage index is invalid")
        self.stage_list.setCurrentRow(index)

    def value(self, object_id: str) -> str:
        control = self.controls.get(object_id)
        if isinstance(control, QLineEdit):
            return control.text().strip()
        if isinstance(control, QComboBox):
            value = control.currentData()
            return "" if value is None else str(value)
        raise KeyError(f"Unknown Data Manager creation control: {object_id}")

    def set_catalogs(
        self,
        *,
        portable_recipes: tuple[tuple[str, str], ...],
        seeds: tuple[tuple[str, str], ...],
        collections: tuple[tuple[str, str], ...],
        databases: tuple[tuple[str, str], ...],
        environments: tuple[tuple[str, str], ...] = (),
        recipe_collections: tuple[tuple[str, str], ...] = (),
    ) -> None:
        values = {
            "data_manager.combo.portable_recipe": portable_recipes,
            "data_manager.combo.seed": seeds,
            "data_manager.combo.artifact_collection": collections,
            "data_manager.combo.database": databases,
            "data_manager.creation.combo.environment": environments,
            "data_manager.creation.combo.recipe_collection": recipe_collections,
        }
        for object_id, entries in values.items():
            combo = self.controls.get(object_id)
            if not isinstance(combo, QComboBox):
                continue
            current = combo.currentData()
            blocker = QSignalBlocker(combo)
            combo.clear()
            combo.addItem("Select explicitly", None)
            for identity, label in entries:
                combo.addItem(label, identity)
            if current is not None:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            del blocker

    def set_plan_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.plan_table, rows)

    def set_environment_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.environment_table, rows)

    def set_recipe_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.recipe_table, rows)

    def set_readiness_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.readiness_table, rows)

    def set_build_report(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.build_report, rows)

    def set_collection_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        _set_rows(self.collection_table, rows)

    def _target_page(self) -> QWidget:
        return self._simple_page(
            "Target OHLCV",
            "Choose one accepted OHLCV market from Catalogs. Selection is never inferred.",
            (("data_manager.button.creation.use_target", "Use Selected Dataset", "use_target"),),
        )

    def _seed_page(self) -> QWidget:
        page, layout = self._page("Database Seed")
        form = QFormLayout()
        existing = self._combo("data_manager.combo.seed", page)
        name = self._line("data_manager.input.seed_name", page, "Database name")
        description = self._line(
            "data_manager.input.seed_description", page, "Description"
        )
        form.addRow("Existing Seed", existing)
        form.addRow("Name", name)
        form.addRow("Description", description)
        columns = QWidget(page)
        columns_layout = QHBoxLayout(columns)
        for column in ("open", "high", "low", "close", "volume"):
            check = QCheckBox(column, columns)
            check.setChecked(True)
            object_id = f"data_manager.creation.check.seed_{column}"
            apply_identity(check, object_id, object_type="check_box")
            self.controls[object_id] = check
            columns_layout.addWidget(check)
        form.addRow("OHLCV Columns", columns)
        range_mode = self._combo("data_manager.creation.combo.seed_range", page)
        range_mode.addItem("Full accepted range", "full")
        range_mode.addItem("Custom range", "custom")
        start = self._line("data_manager.creation.input.range_start", page, "Start timestamp ms")
        end = self._line("data_manager.creation.input.range_end", page, "End timestamp ms")
        form.addRow("Range", range_mode)
        form.addRow("Custom start", start)
        form.addRow("Custom end", end)
        layout.addLayout(form)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.create_seed", "Create Seed", "create_seed"),
            ("data_manager.creation.button.load_seed", "Load", "load_seed"),
            ("data_manager.creation.button.validate_seed", "Validate", "validate_seed"),
            ("data_manager.creation.button.delete_seed", "Delete", "delete_seed"),
        )))
        layout.addStretch(1)
        return page

    def _environment_page(self) -> QWidget:
        page, layout = self._page("Study Environments")
        environment = self._combo("data_manager.creation.combo.environment", page)
        roots = self._line(
            "data_manager.creation.input.environment_roots",
            page,
            "Comma-separated explicit root entry IDs",
        )
        form = QFormLayout()
        form.addRow("Environment", environment)
        form.addRow("Root entries", roots)
        layout.addLayout(form)
        self.environment_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.environment_portability",
            columns=("Entry", "Tool", "Mode", "Status", "Dependencies", "Reason"),
            labels=("Entry", "Tool", "Mode", "Status", "Dependencies", "Reason"),
        )
        layout.addWidget(self.environment_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.refresh_foundations", "Refresh Foundations", "refresh_foundations"),
            ("data_manager.creation.button.inspect_environment", "Inspect", "inspect_environment"),
            ("data_manager.creation.button.plan_derivation", "Plan Recipe Derivation", "plan_recipe_derivation"),
        )))
        return page

    def _recipe_page(self) -> QWidget:
        page, layout = self._page("Recipes")
        mode = self._combo("data_manager.creation.combo.recipe_mode", page)
        mode.addItem("Direct portable Recipe", "direct")
        mode.addItem("Recipe Collection revision", "collection")
        recipe = self._combo("data_manager.combo.portable_recipe", page)
        recipe_roots = self._line(
            "data_manager.creation.input.recipe_root_ids",
            page,
            "Comma-separated portable Recipe IDs",
        )
        collection = self._combo("data_manager.creation.combo.recipe_collection", page)
        collection_name = self._line(
            "data_manager.creation.input.recipe_collection_name",
            page,
            "Recipe Collection name",
        )
        collection_description = self._line(
            "data_manager.creation.input.recipe_collection_description",
            page,
            "Recipe Collection description",
        )
        form = QFormLayout()
        form.addRow("Source mode", mode)
        form.addRow("Portable Recipe", recipe)
        form.addRow("Portable Recipe roots", recipe_roots)
        form.addRow("Recipe Collection", collection)
        form.addRow("Collection name", collection_name)
        form.addRow("Collection description", collection_description)
        layout.addLayout(form)
        self.recipe_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.recipes",
            columns=("Recipe", "Tool", "Kind", "Outputs", "Dependencies", "State"),
            labels=("Recipe", "Tool", "Kind", "Outputs", "Dependencies", "State"),
        )
        layout.addWidget(self.recipe_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.plan_base", "Plan Selected Recipe", "plan_base"),
            ("data_manager.creation.button.persist_derivation", "Persist Derivation", "persist_recipe_derivation"),
            ("data_manager.creation.button.create_recipe_collection", "Create Collection", "create_recipe_collection"),
            ("data_manager.creation.button.update_recipe_collection", "Update Collection", "update_recipe_collection"),
        )))
        return page

    def _base_artifact_page(self) -> QWidget:
        page, layout = self._page("Base Artifacts")
        self.plan_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.materialization_plan",
            columns=("Recipe", "Logical Artifact", "Tool", "Role", "Status", "Blockers"),
            labels=("Recipe", "Logical Artifact", "Tool", "Role", "Status", "Blockers"),
        )
        layout.addWidget(self.plan_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.materialize_base", "Materialize Base Artifacts", "materialize_base"),
        )))
        return page

    def _batch_page(self) -> QWidget:
        page, layout = self._page("Batch Artifacts")
        destination = self._combo("data_manager.creation.combo.batch_destination", page)
        destination.addItem("Individual managed Artifacts", "individual")
        destination.addItem("New Artifact Collection", "new_collection")
        destination.addItem("Existing Artifact Collection", "existing_collection")
        tool = self._combo("data_manager.combo.batch_tool", page)
        for key, specification in CONSTRUCT_SPECS.items():
            tool.addItem(specification.title, key)
        form = QFormLayout()
        form.addRow("Default Construct", tool)
        form.addRow("Destination", destination)
        layout.addLayout(form)
        self.batch_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.batch_branches",
            columns=("Source Logical ID", "Source Output", "Tool", "Parameters", "Requested Outputs"),
            labels=("Source Logical ID", "Source Output", "Tool", "Parameters", "Requested Outputs"),
        )
        self.batch_table.setRowCount(1)
        layout.addWidget(self.batch_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.creation.button.add_batch_branch", "Add Branch", "add_batch_branch"),
            ("data_manager.creation.button.remove_batch_branch", "Remove Branch", "remove_batch_branch"),
            ("data_manager.button.creation.plan_batch", "Plan Batch", "plan_batch"),
            ("data_manager.button.creation.execute_batch", "Execute Batch", "execute_batch"),
        )))
        return page

    def _artifact_collection_page(self) -> QWidget:
        page, layout = self._page("Artifact Collection")
        collection = self._combo("data_manager.combo.artifact_collection", page)
        name = self._line("data_manager.creation.input.collection_name", page, "Collection name")
        description = self._line("data_manager.creation.input.collection_description", page, "Description")
        revision = self._line(
            "data_manager.creation.input.collection_revision",
            page,
            "Exact historical revision ID (optional)",
        )
        remove_roots = self._line(
            "data_manager.creation.input.collection_remove_roots",
            page,
            "Comma-separated optional root logical Artifact IDs",
        )
        form = QFormLayout()
        form.addRow("Collection", collection)
        form.addRow("Name", name)
        form.addRow("Description", description)
        form.addRow("Exact revision", revision)
        form.addRow("Remove optional roots", remove_roots)
        layout.addLayout(form)
        self.collection_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.collection_members",
            columns=(
                "Logical Artifact", "Output", "Database Column", "Order", "Role", "Locked"
            ),
            labels=(
                "Logical Artifact", "Output", "Database Column", "Order", "Role", "Locked"
            ),
        )
        layout.addWidget(self.collection_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.create_collection", "Create", "create_collection"),
            ("data_manager.creation.button.load_collection", "Load History", "load_collection"),
            ("data_manager.creation.button.validate_collection", "Validate", "validate_collection"),
            ("data_manager.creation.button.revise_collection", "Revise", "revise_collection"),
            ("data_manager.creation.button.add_collection_branches", "Add Branches", "add_collection_branches"),
            ("data_manager.creation.button.remove_collection_branches", "Remove Branches", "remove_collection_branches"),
        )))
        return page

    def _review_page(self) -> QWidget:
        page, layout = self._page("Database Review")
        self.readiness_table = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.readiness",
            columns=("Check", "Result", "Details"),
            labels=("Check", "Result", "Details"),
        )
        layout.addWidget(self.readiness_table, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.review", "Validate Readiness", "review"),
        )))
        return page

    def _build_page(self) -> QWidget:
        page, layout = self._page("Build Database")
        database = self._combo("data_manager.combo.database", page)
        name = self._line("data_manager.creation.input.database_name", page, "Database name")
        description = self._line("data_manager.creation.input.database_description", page, "Description")
        confirm = QCheckBox("I confirm immutable Database publication", page)
        apply_identity(confirm, "data_manager.creation.check.build_confirmed", object_type="check_box")
        self.controls["data_manager.creation.check.build_confirmed"] = confirm
        form = QFormLayout()
        form.addRow("Existing Database", database)
        form.addRow("Name", name)
        form.addRow("Description", description)
        form.addRow("Confirmation", confirm)
        layout.addLayout(form)
        self.build_report = configure_table(
            QTableWidget(page),
            object_id="data_manager.creation.table.build_report",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        layout.addWidget(self.build_report, 1)
        layout.addLayout(self._button_row(page, (
            ("data_manager.button.creation.build", "Build Database Revision", "build"),
            ("data_manager.button.creation.reload", "Reload Durable Creation State", "reload_creation"),
        )))
        return page

    def _simple_page(self, title: str, detail: str, actions) -> QWidget:
        page, layout = self._page(title)
        label = QLabel(detail, page)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addLayout(self._button_row(page, actions))
        layout.addStretch(1)
        return page

    def _page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        heading = QLabel(title, page)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        return page, layout

    def _combo(self, object_id: str, parent: QWidget) -> QComboBox:
        combo = QComboBox(parent)
        apply_identity(combo, object_id, object_type="combo_box")
        self.controls[object_id] = combo
        return combo

    def _line(self, object_id: str, parent: QWidget, placeholder: str) -> QLineEdit:
        line = QLineEdit(parent)
        line.setPlaceholderText(placeholder)
        apply_identity(line, object_id, object_type="line_edit")
        self.controls[object_id] = line
        return line

    def _button_row(self, parent: QWidget, actions) -> QHBoxLayout:
        layout = QHBoxLayout()
        for object_id, label, action in actions:
            button = QPushButton(label, parent)
            apply_identity(
                button,
                object_id,
                object_type="button",
                display_label=label,
                action_id=object_id,
            )
            button.clicked.connect(partial(self._emit, action))
            self.buttons[object_id] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return layout

    def _emit(self, action: str) -> None:
        if action == "add_batch_branch":
            self.batch_table.insertRow(self.batch_table.rowCount())
            return
        if action == "remove_batch_branch":
            row = self.batch_table.currentRow()
            if row >= 0:
                self.batch_table.removeRow(row)
            return
        payload = {
            "seed_name": self.value("data_manager.input.seed_name"),
            "seed_description": self.value("data_manager.input.seed_description"),
            "seed_id": self.value("data_manager.combo.seed"),
            "seed_columns": tuple(
                column
                for column in ("open", "high", "low", "close", "volume")
                if self.controls[f"data_manager.creation.check.seed_{column}"].isChecked()
            ),
            "range_mode": self.value("data_manager.creation.combo.seed_range"),
            "range_start": self.value("data_manager.creation.input.range_start"),
            "range_end": self.value("data_manager.creation.input.range_end"),
            "environment_id": self.value("data_manager.creation.combo.environment"),
            "environment_root_entry_ids": _csv(self.value("data_manager.creation.input.environment_roots")),
            "recipe_mode": self.value("data_manager.creation.combo.recipe_mode"),
            "portable_recipe_id": self.value("data_manager.combo.portable_recipe"),
            "portable_recipe_ids": _csv(
                self.value("data_manager.creation.input.recipe_root_ids")
            ),
            "recipe_collection_id": self.value("data_manager.creation.combo.recipe_collection"),
            "recipe_collection_name": self.value("data_manager.creation.input.recipe_collection_name"),
            "recipe_collection_description": self.value("data_manager.creation.input.recipe_collection_description"),
            "batch_tool": self.value("data_manager.combo.batch_tool"),
            "batch_destination": self.value("data_manager.creation.combo.batch_destination"),
            "batch_branches": _table_payload(self.batch_table),
            "collection_id": self.value("data_manager.combo.artifact_collection"),
            "collection_name": self.value("data_manager.creation.input.collection_name"),
            "collection_description": self.value("data_manager.creation.input.collection_description"),
            "collection_revision_id": self.value("data_manager.creation.input.collection_revision"),
            "collection_remove_roots": _csv(
                self.value("data_manager.creation.input.collection_remove_roots")
            ),
            "collection_selected_outputs": _collection_output_payload(
                self.collection_table
            ),
            "database_id": self.value("data_manager.combo.database"),
            "database_name": self.value("data_manager.creation.input.database_name"),
            "database_description": self.value("data_manager.creation.input.database_description"),
            "build_confirmed": self.controls["data_manager.creation.check.build_confirmed"].isChecked(),
        }
        self.action_requested.emit(action, payload)

    def _wire_context_changes(self) -> None:
        base_ids = (
            "data_manager.creation.combo.recipe_mode",
            "data_manager.combo.portable_recipe",
            "data_manager.creation.input.recipe_root_ids",
            "data_manager.creation.combo.recipe_collection",
        )
        batch_ids = (
            "data_manager.creation.combo.batch_destination",
            "data_manager.combo.artifact_collection",
        )
        readiness_ids = (
            "data_manager.combo.seed",
            "data_manager.combo.artifact_collection",
            "data_manager.creation.input.collection_revision",
        )
        for object_id in base_ids:
            self._connect_context_control(object_id, "base")
        for object_id in batch_ids:
            self._connect_context_control(object_id, "batch")
        for object_id in readiness_ids:
            self._connect_context_control(object_id, "readiness")
        self.batch_table.itemChanged.connect(
            lambda _item: self._context_changed("batch")
        )
        self.controls[
            "data_manager.creation.check.build_confirmed"
        ].toggled.connect(self._sync_gating)

    def _connect_context_control(self, object_id: str, scope: str) -> None:
        control = self.controls[object_id]
        if isinstance(control, QComboBox):
            control.currentIndexChanged.connect(
                lambda _index, value=scope: self._context_changed(value)
            )
        elif isinstance(control, QLineEdit):
            control.textChanged.connect(
                lambda _text, value=scope: self._context_changed(value)
            )

    def _context_changed(self, scope: str) -> None:
        if scope == "base":
            self._base_plan_ready = False
        elif scope == "batch":
            self._batch_plan_ready = False
        elif scope == "readiness":
            self._database_readiness_ready = False
        self._sync_gating()
        self.action_requested.emit("context_changed", {"scope": scope})

    def _sync_gating(self) -> None:
        for button in self.buttons.values():
            button.setEnabled(not self._busy)
        gated = {
            "data_manager.button.creation.materialize_base": self._base_plan_ready,
            "data_manager.button.creation.execute_batch": self._batch_plan_ready,
            "data_manager.button.creation.build": (
                self._database_readiness_ready
                and self.controls[
                    "data_manager.creation.check.build_confirmed"
                ].isChecked()
            ),
        }
        for object_id, ready in gated.items():
            self.buttons[object_id].setEnabled(not self._busy and ready)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _table_payload(table: QTableWidget) -> tuple[dict[str, object], ...]:
    keys = ("source_logical_artifact_id", "source_output", "tool_key", "parameters", "requested_outputs")
    values: list[dict[str, object]] = []
    for row in range(table.rowCount()):
        raw = tuple(
            "" if table.item(row, column) is None else table.item(row, column).text().strip()
            for column in range(table.columnCount())
        )
        if not any(raw):
            continue
        parameters: object = {}
        if raw[3]:
            try:
                parameters = json.loads(raw[3])
            except json.JSONDecodeError:
                parameters = raw[3]
        values.append(dict(zip(keys, (*raw[:3], parameters, _csv(raw[4])), strict=True)))
    return tuple(values)


def _collection_output_payload(
    table: QTableWidget,
) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    keys = ("logical_artifact_id", "output_name", "column_name", "order")
    for row in range(table.rowCount()):
        raw = tuple(
            "" if table.item(row, column) is None else table.item(row, column).text().strip()
            for column in range(4)
        )
        if any(raw):
            values.append(dict(zip(keys, raw, strict=True)))
    return tuple(values)


def _set_rows(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setRowCount(len(rows))
    for row_index, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if table.objectName() == "data_manager.creation.table.collection_members" and (
                column in {0, 4, 5} or (len(values) > 5 and values[5] == "yes")
            ):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_index, column, item)
