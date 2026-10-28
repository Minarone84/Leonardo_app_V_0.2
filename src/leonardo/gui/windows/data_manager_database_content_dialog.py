"""Database content-edit window for persisted Artifact outputs and captures."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from leonardo.data_manager import (
    ArtifactCollectionOutputV1,
    DataManagerDatabaseCatalogEntry,
    DataManagerProductCatalogSnapshot,
    DatabaseCollectionReferenceV2,
    DatabaseContentEditPlan,
    DatabaseLegacyOutputV1,
)
from leonardo.gui.data_manager.table_presentation import resize_data_manager_table
from leonardo.gui.windows.shell_widgets import apply_identity, configure_table


DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID = "data_manager.database_content.artifacts.window"
DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID = "data_manager.database_content.collections.window"
_CHECKBOX_STYLE = """
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { border: 1px solid #8B949E; background: #0D1117; }
QCheckBox::indicator:checked { border: 1px solid #58A6FF; background: #1F6FEB; }
QCheckBox::indicator:disabled { border: 1px solid #484F58; background: #21262D; }
"""


@dataclass(frozen=True, slots=True)
class _ArtifactOutputChoice:
    output: ArtifactCollectionOutputV1 | DatabaseLegacyOutputV1
    tool_key: str
    was_selected: bool
    selectable: bool
    status: str
    owners: tuple[str, ...]

    @property
    def logical_artifact_id(self) -> str | None:
        return self.output.logical_artifact_id

    @property
    def output_name(self) -> str:
        return self.output.output_name


@dataclass(frozen=True, slots=True)
class _CollectionSourceChoice:
    collection_id: str
    revision_id: str
    column_names: tuple[str, ...]
    was_selected: bool
    selectable: bool
    status: str


class DataManagerDatabaseContentDialog(QDialog):
    """Preview and publish one reviewed immutable Database content edit."""

    preview_requested = Signal(str, str, object)
    apply_requested = Signal(object)
    closing = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._database: DataManagerDatabaseCatalogEntry | None = None
        self._snapshot: DataManagerProductCatalogSnapshot | None = None
        self._mode = "artifacts"
        self._baseline_plan: DatabaseContentEditPlan | None = None
        self._plan: DatabaseContentEditPlan | None = None
        self._busy = False
        self._source_values: list[object] = []
        self._source_checks: list[QCheckBox] = []

        self.setWindowTitle("Edit Database Content")
        self.setObjectName("data_manager_database_content_dialog")
        self.setProperty("object_id", DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID)
        self.setWindowModality(Qt.WindowModality.NonModal)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(
                min(available.width(), max(860, int(available.width() * 0.65))),
                min(available.height(), max(640, int(available.height() * 0.72))),
            )

        root = QVBoxLayout(self)
        self.summary_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.summary",
            columns=("Field", "Value"),
            labels=("Field", "Value"),
        )
        self.summary_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        root.addWidget(self.summary_table)

        self.source_label = QLabel("Artifact Outputs", self)
        apply_identity(
            self.source_label,
            "data_manager.database_content.label.source",
            object_type="label",
        )
        root.addWidget(self.source_label)
        self.source_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.sources",
            columns=(
                "Include",
                "Artifact",
                "Tool",
                "Output",
                "Database Column",
                "Owners",
                "Status",
            ),
            labels=(
                "Include",
                "Artifact",
                "Tool",
                "Output",
                "Database Column",
                "Owners",
                "Status",
            ),
        )
        self.source_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.source_table, 1)

        root.addWidget(QLabel("Preview", self))
        self.preview_table = configure_table(
            QTableWidget(self),
            object_id="data_manager.database_content.table.preview",
            columns=(
                "Action",
                "Artifact",
                "Output",
                "Database Column",
                "Owners Before",
                "Owners After",
            ),
            labels=(
                "Action",
                "Artifact",
                "Output",
                "Database Column",
                "Owners Before",
                "Owners After",
            ),
        )
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        root.addWidget(self.preview_table, 1)

        self.preview_summary = QLabel("Preparing edit context...", self)
        apply_identity(
            self.preview_summary,
            "data_manager.database_content.label.preview_summary",
            object_type="label",
        )
        self.preview_summary.setWordWrap(True)
        root.addWidget(self.preview_summary)

        buttons = QHBoxLayout()
        self.preview_button = self._button("Preview", "preview")
        self.apply_button = self._button("Apply Edit", "apply")
        self.close_button = self._button("Close", "close")
        self.preview_button.clicked.connect(self._emit_preview)
        self.apply_button.clicked.connect(self._emit_apply)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.preview_button)
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)
        self._sync_controls()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def baseline_plan(self) -> DatabaseContentEditPlan | None:
        return self._baseline_plan

    @property
    def reviewed_plan(self) -> DatabaseContentEditPlan | None:
        return self._plan

    @property
    def context_key(self) -> tuple[object, ...]:
        manifest = None if self._database is None else self._database.current_manifest
        intent = self.edit_intent()
        return (
            None if self._database is None else self._database.definition.database_id,
            None if manifest is None else manifest.revision_id,
            self._mode,
            intent["artifact_additions"],
            intent["collection_additions"],
            intent["remove_sources"],
            intent["remove_outputs"],
            intent["remove_columns"],
        )

    def set_context(
        self,
        database: DataManagerDatabaseCatalogEntry,
        snapshot: DataManagerProductCatalogSnapshot,
        *,
        mode: str,
        baseline_plan: DatabaseContentEditPlan | None = None,
    ) -> None:
        if not isinstance(database, DataManagerDatabaseCatalogEntry):
            raise TypeError("database must be a DataManagerDatabaseCatalogEntry")
        if not isinstance(snapshot, DataManagerProductCatalogSnapshot):
            raise TypeError("snapshot must be a DataManagerProductCatalogSnapshot")
        if mode not in {"artifacts", "collections"}:
            raise ValueError("mode must be artifacts or collections")
        self.setProperty(
            "object_id",
            DATA_MANAGER_DATABASE_CONTENT_WINDOW_ID
            if mode == "artifacts"
            else DATA_MANAGER_DATABASE_COLLECTIONS_WINDOW_ID,
        )
        preserved = self._baseline_plan
        self._database = database
        self._snapshot = snapshot
        self._mode = mode
        if baseline_plan is not None:
            if not isinstance(baseline_plan, DatabaseContentEditPlan):
                raise TypeError("baseline_plan must be a DatabaseContentEditPlan")
            if not self._baseline_matches_context(baseline_plan):
                raise ValueError("baseline plan does not match current Database")
            if not baseline_plan.no_op or baseline_plan.blocked:
                raise ValueError("baseline plan must be an unblocked no-op edit plan")
            self._baseline_plan = baseline_plan
        elif preserved is None or not self._baseline_matches_context(preserved):
            self._baseline_plan = None
        else:
            self._baseline_plan = preserved
        self.setWindowTitle(
            "Edit Database Artifacts"
            if mode == "artifacts"
            else "Edit Database Collections"
        )
        self._populate_summary()
        self._populate_sources()
        self.invalidate_preview(
            "Preview required."
            if self._baseline_plan is not None
            else "Preparing edit context..."
        )

    def selected_source_ids(self) -> tuple[str, ...]:
        """Return checked logical IDs for lightweight GUI/test inspection."""
        selected: list[str] = []
        for checkbox, value in zip(
            self._source_checks, self._source_values, strict=True
        ):
            if not checkbox.isChecked():
                continue
            if isinstance(value, _ArtifactOutputChoice):
                if value.logical_artifact_id is not None and value.logical_artifact_id not in selected:
                    selected.append(value.logical_artifact_id)
            elif isinstance(value, _CollectionSourceChoice):
                selected.append(value.collection_id)
        return tuple(selected)

    def edit_intent(self) -> dict[str, tuple[object, ...]]:
        artifact_additions: list[ArtifactCollectionOutputV1] = []
        collection_additions: list[DatabaseCollectionReferenceV2] = []
        remove_sources: list[tuple[str, str, str | None]] = []
        remove_outputs: list[tuple[str, str]] = []
        remove_columns: list[str] = []
        for checkbox, value in zip(
            self._source_checks, self._source_values, strict=True
        ):
            checked = checkbox.isChecked()
            if isinstance(value, _ArtifactOutputChoice):
                if checked and not value.was_selected:
                    artifact_additions.append(value.output)
                elif not checked and value.was_selected:
                    remove_columns.append(value.output.column_name)
            elif isinstance(value, _CollectionSourceChoice):
                if checked and not value.was_selected:
                    collection_additions.append(
                        DatabaseCollectionReferenceV2(
                            value.collection_id, value.revision_id
                        )
                    )
                elif not checked and value.was_selected:
                    remove_sources.append(
                        ("collection", value.collection_id, value.revision_id)
                    )
        return {
            "artifact_additions": tuple(artifact_additions),
            "collection_additions": tuple(collection_additions),
            "remove_sources": tuple(remove_sources),
            "remove_outputs": tuple(remove_outputs),
            "remove_columns": tuple(remove_columns),
        }

    def set_plan(self, plan: DatabaseContentEditPlan) -> None:
        if not isinstance(plan, DatabaseContentEditPlan):
            raise TypeError("plan must be a DatabaseContentEditPlan")
        if not self._plan_matches_context(plan):
            raise ValueError("plan does not match current Database edit context")
        self._plan = plan
        baseline = self._baseline_plan
        if baseline is None:
            raise ValueError("Database edit baseline is unavailable")
        before_outputs = {
            item.column_name: item
            for item in baseline.selected_outputs
        }
        after_outputs = {
            item.column_name: item
            for item in plan.selected_outputs
        }
        before_owners = self._owners_by_column(baseline)
        after_owners = self._owners_by_column(plan)
        keys = sorted(
            set(before_outputs) | set(after_outputs),
            key=lambda column: (
                (after_outputs.get(column) or before_outputs[column]).logical_artifact_id or "",
                (after_outputs.get(column) or before_outputs[column]).output_name,
                column,
            ),
        )
        rows: list[tuple[str, ...]] = []
        for key in keys:
            before = before_outputs.get(key)
            after = after_outputs.get(key)
            output = after or before
            if output is None:
                continue
            old_owners = before_owners.get(output.column_name, ())
            new_owners = after_owners.get(output.column_name, ())
            if before is None:
                action = "ADD"
            elif after is None:
                action = "REMOVE"
            elif old_owners != new_owners:
                action = "OWNERSHIP"
            else:
                action = "KEEP"
            rows.append(
                (
                    action,
                    output.logical_artifact_id or "Not recorded",
                    output.output_name,
                    output.column_name,
                    ", ".join(old_owners) or "-",
                    ", ".join(new_owners) or "-",
                )
            )
        self.preview_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.preview_table.setItem(row, column, QTableWidgetItem(value))
        resize_data_manager_table(self.preview_table)

        summary = "\n".join(
            (
                f"Current schema: {', '.join(baseline.column_names)}",
                f"Proposed schema: {', '.join(plan.column_names)}",
                f"Rows preserved: {plan.row_count}",
                "Added columns: " + (", ".join(plan.added_column_names) or "none"),
                "Removed columns: " + (", ".join(plan.removed_column_names) or "none"),
                f"Selection sources: {len(baseline.selection_sources)} → {len(plan.selection_sources)}",
                f"Ownership changed: {'yes' if plan.ownership_changed else 'no'}",
            )
        )
        manifest = None if self._database is None else self._database.current_manifest
        if manifest is not None and manifest.schema_version == "3.0":
            summary += (
                "\nThis explicit content edit will publish a V4 Database revision "
                "with captured ownership and value provenance. Historical revisions remain unchanged."
            )
        elif manifest is not None and manifest.schema_version in {"1.0", "2.0"}:
            summary += (
                "\nThis explicit content edit will preserve the saved attribution, "
                "including information not recorded by the original snapshot. Historical revisions remain unchanged."
            )
        if plan.no_op and not plan.blocked:
            summary += "\nNo content or ownership change is requested."
        if plan.blockers:
            summary += "\nBlocked: " + "; ".join(plan.blockers)
        self.preview_summary.setText(summary)
        self._sync_controls()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.source_table.setEnabled(not self._busy)
        self._sync_controls()

    def invalidate_preview(self, message: str = "Preview required.") -> None:
        self._plan = None
        self.preview_table.setRowCount(0)
        self.preview_summary.setText(str(message))
        self._sync_controls()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.closing.emit()
        super().closeEvent(event)

    def _populate_summary(self) -> None:
        database = self._database
        manifest = None if database is None else database.current_manifest
        if database is None or manifest is None:
            rows = (("State", "Current Database revision unavailable"),)
        else:
            market = database.definition.market_id
            rows = (
                ("Database Name", database.definition.display_name),
                ("Database ID", database.definition.database_id),
                ("Exchange", market.exchange),
                ("Market Type", market.market_type),
                ("Asset", market.symbol),
                ("Timeframe", market.timeframe),
                ("Current Revision", manifest.revision_id),
                ("Current Rows", str(manifest.row_count)),
                ("Current Columns", str(manifest.column_count)),
                ("Schema", str(manifest.schema_version)),
            )
        self.summary_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.summary_table.setItem(row, column, QTableWidgetItem(value))
        resize_data_manager_table(self.summary_table)

    def _populate_sources(self) -> None:
        self._source_values = []
        self._source_checks = []
        self.source_table.setRowCount(0)
        if self._baseline_plan is None or self._snapshot is None:
            return
        if self._mode == "artifacts":
            self._populate_artifact_outputs()
        else:
            self._populate_collection_sources()
        resize_data_manager_table(self.source_table)

    def _populate_artifact_outputs(self) -> None:
        baseline = self._baseline_plan
        snapshot = self._snapshot
        if baseline is None or snapshot is None:
            return
        live = {
            item.logical_artifact_id: item
            for item in snapshot.managed_artifacts.artifacts
            if item.market_id == baseline.market_id
        }
        owners = self._owners_by_column(baseline)
        existing = {
            (item.logical_artifact_id, item.output_name): item
            for item in baseline.selected_outputs
        }
        keys = set(existing)
        for logical_id, artifact in live.items():
            for output_name in artifact.output_names:
                keys.add((logical_id, output_name))
        choices: list[_ArtifactOutputChoice] = []
        for logical_id, output_name in sorted(keys, key=lambda key: (key[0] or "", key[1])):
            old = existing.get((logical_id, output_name))
            artifact = live.get(logical_id)
            output = old or ArtifactCollectionOutputV1(
                logical_id, output_name, output_name
            )
            if old is not None:
                selectable = True
                if isinstance(old, DatabaseLegacyOutputV1):
                    status = "Saved snapshot; original provider not recorded (removal allowed)"
                elif artifact is None or not artifact.valid:
                    status = "Included; live Artifact unavailable (removal allowed)"
                else:
                    status = "Included"
            else:
                selectable = artifact is not None and artifact.valid
                status = (
                    "Available"
                    if selectable
                    else "Unavailable: "
                    + (
                        "current Artifact not found"
                        if artifact is None
                        else artifact.rejection_reason
                    )
                )
            choices.append(
                _ArtifactOutputChoice(
                    output=output,
                    tool_key="" if artifact is None else artifact.tool_key,
                    was_selected=old is not None,
                    selectable=selectable,
                    status=status,
                    owners=owners.get(output.column_name, ()),
                )
            )
        columns = (
            "Include",
            "Artifact",
            "Tool",
            "Output",
            "Database Column",
            "Owners",
            "Status",
        )
        self.source_label.setText(
            "Artifact Outputs — uncheck an included output to remove it from every owner"
        )
        self.source_table.setColumnCount(len(columns))
        self.source_table.setHorizontalHeaderLabels(columns)
        self.source_table.setRowCount(len(choices))
        self._source_values = list(choices)
        for row, value in enumerate(choices):
            checkbox = self._checkbox(value.selectable, value.was_selected)
            self._source_checks.append(checkbox)
            self.source_table.setCellWidget(row, 0, checkbox)
            texts = (
                value.logical_artifact_id or "Not recorded",
                value.tool_key or "-",
                value.output_name,
                value.output.column_name,
                ", ".join(value.owners) or "-",
                value.status,
            )
            for column, text in enumerate(texts, start=1):
                self.source_table.setItem(row, column, QTableWidgetItem(str(text)))

    def _populate_collection_sources(self) -> None:
        baseline = self._baseline_plan
        snapshot = self._snapshot
        if baseline is None or snapshot is None:
            return
        captured: dict[tuple[str, str], tuple[str, ...]] = {}
        for source in baseline.selection_sources:
            if source["source_kind"] != "collection":
                continue
            revision_id = str(source["source_revision_id"] or "")
            captured[(str(source["source_id"]), revision_id)] = tuple(
                source["column_names"]
            )
        live = {
            (item.collection_id, item.revision_id): item
            for item in snapshot.artifact_collections
            if item.market_id == baseline.market_id
        }
        keys = sorted(set(captured) | set(live))
        choices: list[_CollectionSourceChoice] = []
        for collection_id, revision_id in keys:
            collection = live.get((collection_id, revision_id))
            was_selected = (collection_id, revision_id) in captured
            if was_selected:
                selectable = True
                status = (
                    "Captured"
                    if collection is not None
                    else "Captured; live revision unavailable (removal allowed)"
                )
                column_names = captured[(collection_id, revision_id)]
            else:
                selectable = (
                    collection is not None
                    and collection.validation_state == "valid"
                )
                status = (
                    "Available"
                    if selectable
                    else "Unavailable or invalid"
                )
                column_names = (
                    ()
                    if collection is None
                    else tuple(item.column_name for item in collection.selected_outputs)
                )
            choices.append(
                _CollectionSourceChoice(
                    collection_id=collection_id,
                    revision_id=revision_id,
                    column_names=tuple(column_names),
                    was_selected=was_selected,
                    selectable=selectable,
                    status=status,
                )
            )
        columns = (
            "Include",
            "Collection",
            "Captured Revision",
            "Owned Database Columns",
            "Status",
        )
        self.source_label.setText(
            "Captured Collection Sources — each exact revision is an independent owner"
        )
        self.source_table.setColumnCount(len(columns))
        self.source_table.setHorizontalHeaderLabels(columns)
        self.source_table.setRowCount(len(choices))
        self._source_values = list(choices)
        for row, value in enumerate(choices):
            checkbox = self._checkbox(value.selectable, value.was_selected)
            self._source_checks.append(checkbox)
            self.source_table.setCellWidget(row, 0, checkbox)
            texts = (
                value.collection_id,
                value.revision_id,
                ", ".join(value.column_names) or "-",
                value.status,
            )
            for column, text in enumerate(texts, start=1):
                self.source_table.setItem(row, column, QTableWidgetItem(str(text)))

    def _checkbox(self, enabled: bool, checked: bool) -> QCheckBox:
        checkbox = QCheckBox(self.source_table)
        checkbox.setStyleSheet(_CHECKBOX_STYLE)
        checkbox.setEnabled(enabled)
        checkbox.setChecked(checked)
        checkbox.stateChanged.connect(
            lambda state, current=checkbox: self._source_toggled(current, state)
        )
        return checkbox

    def _source_toggled(self, checkbox: QCheckBox, _state: int) -> None:
        if not checkbox.isEnabled():
            return
        self.invalidate_preview("Selection changed; Preview again.")

    def _emit_preview(self) -> None:
        database = self._database
        if (
            self._busy
            or self._baseline_plan is None
            or database is None
            or database.current_manifest is None
            or not self._has_edit_intent()
        ):
            return
        intent = self.edit_intent()
        self.invalidate_preview("Planning Database content edit...")
        self.preview_requested.emit(
            self._mode, database.definition.database_id, intent
        )

    def _emit_apply(self) -> None:
        if not self._busy and self._plan is not None:
            self.apply_requested.emit(self._plan)

    def _sync_controls(self) -> None:
        can_preview = (
            not self._busy
            and self._baseline_plan is not None
            and self._has_edit_intent()
        )
        self.preview_button.setEnabled(can_preview)
        self.apply_button.setEnabled(
            not self._busy
            and self._plan is not None
            and self._plan_matches_context(self._plan)
            and not self._plan.blocked
            and not self._plan.no_op
        )
        self.close_button.setEnabled(True)

    def _has_edit_intent(self) -> bool:
        intent = self.edit_intent()
        return any(intent.values())

    def _baseline_matches_context(self, plan: DatabaseContentEditPlan) -> bool:
        database = self._database
        manifest = None if database is None else database.current_manifest
        return bool(
            database is not None
            and manifest is not None
            and plan.database_id == database.definition.database_id
            and plan.starting_revision_id == manifest.revision_id
            and plan.market_id == database.definition.market_id
            and plan.source_ohlcv == manifest.source_ohlcv
        )

    def _plan_matches_context(self, plan: DatabaseContentEditPlan) -> bool:
        if not self._baseline_matches_context(plan):
            return False
        intent = self.edit_intent()
        return (
            plan.artifact_additions == intent["artifact_additions"]
            and plan.collection_additions == intent["collection_additions"]
            and plan.remove_sources == intent["remove_sources"]
            and plan.remove_outputs == intent["remove_outputs"]
            and plan.remove_columns == intent["remove_columns"]
        )

    @staticmethod
    def _owners_by_column(plan: DatabaseContentEditPlan) -> dict[str, tuple[str, ...]]:
        owners: dict[str, list[str]] = {}
        for source in plan.selection_sources:
            label = DataManagerDatabaseContentDialog._owner_label(source)
            for column_name in source["column_names"]:
                owners.setdefault(str(column_name), []).append(label)
        return {
            column_name: tuple(sorted(labels))
            for column_name, labels in owners.items()
        }

    @staticmethod
    def _owner_label(source: object) -> str:
        kind = str(source["source_kind"])
        source_id = str(source["source_id"])
        revision_id = source["source_revision_id"]
        if kind == "collection":
            return f"Collection {source_id} @ {revision_id}"
        if kind == "legacy_snapshot":
            return "Saved snapshot; original owner not recorded"
        return f"Artifact {source_id}"

    def _button(self, label: str, suffix: str) -> QPushButton:
        button = QPushButton(label, self)
        apply_identity(
            button,
            f"data_manager.database_content.button.{suffix}",
            object_type="button",
            display_label=label,
            action_id=f"data_manager.database_content.button.{suffix}",
        )
        return button
