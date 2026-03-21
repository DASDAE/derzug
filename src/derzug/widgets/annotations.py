"""Widget for storing and persisting annotation sets."""

from __future__ import annotations

from pathlib import Path

from AnyQt.QtCore import QAbstractTableModel, QModelIndex, Qt
from AnyQt.QtGui import QKeySequence, QShortcut
from AnyQt.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.models.annotations import AnnotationSet
from derzug.orange import Setting
from derzug.utils.annotations import (
    AnnotationStoreSummary,
    build_state,
    delete_entry,
    import_annotation_set,
    load_store,
    normalize_selected_id,
    rename_entry,
    selected_annotation_set,
    state_to_dict,
    summarize_entries,
    sync_directory_state,
)

_TABLE_COLUMNS = (
    ("name", "Name"),
    ("dims_text", "Dims"),
    ("point_count", "Points"),
    ("span_count", "Spans"),
    ("box_count", "Boxes"),
    ("path_count", "Paths"),
    ("polygon_count", "Polygons"),
    ("size_text", "Size"),
)


class _AnnotationsTableModel(QAbstractTableModel):
    """Lightweight table model for stored annotation sets."""

    def __init__(
        self,
        rows: tuple[AnnotationStoreSummary, ...],
        on_rename,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows = rows
        self._on_rename = on_rename

    def set_rows(self, rows: tuple[AnnotationStoreSummary, ...]) -> None:
        """Replace the model rows in one reset."""
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(_TABLE_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._rows) or col < 0 or col >= len(_TABLE_COLUMNS):
            return None
        summary = self._rows[row]
        field = _TABLE_COLUMNS[col][0]
        value = getattr(summary, field)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return value
        if role == Qt.ItemDataRole.UserRole:
            if field == "size_text":
                return summary.size_bytes if summary.size_bytes is not None else -1
            return value
        if (
            role == Qt.ItemDataRole.TextAlignmentRole
            and field != "name"
            and field != "dims_text"
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(
            _TABLE_COLUMNS
        ):
            return _TABLE_COLUMNS[section][1]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = super().flags(index)
        if _TABLE_COLUMNS[index.column()][0] == "name":
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def row_id(self, row: int) -> str | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row].id

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        if _TABLE_COLUMNS[index.column()][0] != "name":
            return False
        renamed = self._on_rename(index.row(), str(value))
        if renamed:
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        return renamed


class Annotations(ZugWidget):
    """Store multiple annotation sets in memory or on disk."""

    name = "Annotations"
    description = "Store and persist annotation sets"
    icon = "icons/Annotations.svg"
    category = "IO"
    keywords = ("annotations", "store", "persist", "table")
    priority = 27
    is_source = True

    store_directory: str = Setting("")
    stored_entries: list = Setting([])
    selected_entry_id: str = Setting("")

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        general = Msg("Annotation store error: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        no_directory = Msg("Directory does not exist: {}")

    class Inputs:
        """Input signal definitions."""

        annotation_set = Input("Annotations", AnnotationSet)

    class Outputs:
        """Output signal definitions."""

        annotation_set = Output("Annotations", AnnotationSet)

    def __init__(self) -> None:
        super().__init__()
        self._entries = ()
        self._table_model: _AnnotationsTableModel | None = None
        self._build_controls()
        self._build_table()
        self._selection_connected = False
        self._restore_store()
        self._emit_selected_output()
        self._request_ui_refresh()

    def _build_controls(self) -> None:
        store_box = gui.widgetBox(self.controlArea, "Store")
        self._in_memory_checkbox = QCheckBox("In Memory", store_box)
        self._in_memory_checkbox.toggled.connect(self._on_in_memory_toggled)
        store_box.layout().addWidget(self._in_memory_checkbox)

        directory_row = QWidget(store_box)
        row_layout = QHBoxLayout(directory_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        self._choose_button = QPushButton("Choose Path", directory_row)
        self._choose_button.clicked.connect(self._choose_directory)
        row_layout.addWidget(self._choose_button)
        row_layout.addStretch(1)
        store_box.layout().addWidget(directory_row)

        action_row = QWidget(store_box)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(4)
        self._delete_button = QPushButton("Delete", action_row)
        self._delete_button.clicked.connect(self._delete_selected)
        action_layout.addWidget(self._delete_button)
        store_box.layout().addWidget(action_row)

        self._status_label = gui.widgetLabel(self.controlArea, "")

    def _build_table(self) -> None:
        container = QWidget(self.mainArea)
        container.setLayout(QVBoxLayout())
        container.layout().setContentsMargins(0, 0, 0, 0)
        self.mainArea.layout().addWidget(container)
        self._table = QTableView(container)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._table.setStyleSheet(
            "QTableView { alternate-background-color: rgba(0, 0, 0, 0.035); }"
            "QHeaderView::section { padding: 6px 8px; font-weight: 600; }"
        )
        self._delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._table)
        self._delete_shortcut.activated.connect(self._delete_selected)
        container.layout().addWidget(self._table)

    def _restore_store(self) -> None:
        directory = self.store_directory.strip()
        if directory and not Path(directory).exists():
            self.Warning.no_directory(directory)
            directory = ""
            self.store_directory = ""
        self._entries = load_store(
            directory=directory, state_entries=self.stored_entries
        )
        selected = self.selected_entry_id.strip() or None
        self.selected_entry_id = normalize_selected_id(self._entries, selected) or ""

    @Inputs.annotation_set
    def set_annotation_set(self, annotation_set: AnnotationSet | None) -> None:
        """Receive an annotation set and import it into the store."""
        if annotation_set is None:
            return
        self.Error.clear()
        try:
            result = import_annotation_set(
                self._entries,
                annotation_set,
                selected_id=self.selected_entry_id.strip() or None,
                directory=self.store_directory.strip(),
            )
            self._entries = sync_directory_state(
                result.entries,
                self.store_directory.strip(),
            )
            self.selected_entry_id = result.selected_id or ""
            self._persist_settings()
            self._emit_selected_output()
            self._request_ui_refresh()
        except Exception as exc:
            self._show_exception("general", exc)

    def _refresh_ui(self) -> None:
        in_memory = not self.store_directory.strip()
        self._in_memory_checkbox.blockSignals(True)
        self._in_memory_checkbox.setChecked(in_memory)
        self._in_memory_checkbox.setEnabled(not in_memory)
        self._in_memory_checkbox.blockSignals(False)
        summaries = summarize_entries(self._entries)
        if self._table_model is None:
            self._table_model = _AnnotationsTableModel(
                summaries,
                self._set_name_for_row,
                self._table,
            )
            self._table.setModel(self._table_model)
        else:
            self._table_model.set_rows(summaries)
        self._table.resizeColumnsToContents()
        selection_model = self._table.selectionModel()
        if selection_model is not None and not self._selection_connected:
            selection_model.selectionChanged.connect(self._on_selection_changed)
            self._selection_connected = True
        self._restore_selected_row()
        self._update_status_label()
        self._delete_button.setEnabled(bool(self._entries))

    def _restore_selected_row(self) -> None:
        model = self._table_model
        if model is None:
            return
        wanted_id = self.selected_entry_id.strip() or None
        if not wanted_id:
            return
        for row in range(model.rowCount()):
            if model.row_id(row) == wanted_id:
                self._table.selectRow(row)
                return

    def _on_selection_changed(self, *_args) -> None:
        model = self._table_model
        selection_model = self._table.selectionModel()
        if model is None or selection_model is None:
            return
        rows = selection_model.selectedRows()
        selected_id = model.row_id(rows[0].row()) if rows else None
        self.selected_entry_id = selected_id or ""
        self._persist_settings()
        self._emit_selected_output()
        self._update_status_label()

    def _emit_selected_output(self) -> None:
        annotation_set = selected_annotation_set(
            self._entries,
            self.selected_entry_id.strip() or None,
        )
        self.Outputs.annotation_set.send(annotation_set)

    def _persist_settings(self) -> None:
        state = build_state(
            self._entries,
            directory=self.store_directory.strip(),
            selected_id=self.selected_entry_id.strip() or None,
        )
        payload = state_to_dict(state)
        self.stored_entries = list(payload["entries"])
        self.selected_entry_id = payload["selected_id"]
        self.store_directory = payload["directory"]

    def _update_status_label(self) -> None:
        count = len(self._entries)
        selected = selected_annotation_set(
            self._entries,
            self.selected_entry_id.strip() or None,
        )
        selected_count = 0 if selected is None else len(selected.annotations)
        self._status_label.setText(
            f"{count} set(s), {selected_count} annotation(s) selected"
        )

    def _choose_directory(self) -> None:
        start_dir = self.store_directory.strip() or str(Path.cwd())
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Annotations Directory",
            start_dir,
        )
        if not directory:
            return
        self.Error.clear()
        self.Warning.clear()
        self.store_directory = directory
        try:
            if Path(directory).exists() and any(Path(directory).glob("*.json")):
                self._entries = load_store(directory=directory, state_entries=[])
            else:
                self._entries = sync_directory_state(self._entries, directory)
            self.selected_entry_id = (
                normalize_selected_id(
                    self._entries, self.selected_entry_id.strip() or None
                )
                or ""
            )
            self._persist_settings()
            self._emit_selected_output()
            self._request_ui_refresh()
        except Exception as exc:
            self._show_exception("general", exc)

    def _on_in_memory_toggled(self, checked: bool) -> None:
        if not checked:
            self._request_ui_refresh()
            return
        self._clear_directory()

    def _clear_directory(self) -> None:
        self.store_directory = ""
        self._entries = sync_directory_state(self._entries, "")
        self._persist_settings()
        self._emit_selected_output()
        self._request_ui_refresh()

    def _delete_selected(self) -> None:
        selected_id = self.selected_entry_id.strip() or None
        if not selected_id:
            return
        try:
            self._entries, next_selected = delete_entry(
                self._entries,
                selected_id,
                selected_id=selected_id,
            )
            self._entries = sync_directory_state(
                self._entries, self.store_directory.strip()
            )
            self.selected_entry_id = next_selected or ""
            self._persist_settings()
            self._emit_selected_output()
            self._request_ui_refresh()
        except Exception as exc:
            self._show_exception("general", exc)

    def _set_name_for_row(self, row: int, value: str) -> bool:
        model = self._table_model
        if model is None:
            return False
        entry_id = model.row_id(row)
        if not entry_id:
            return False
        self._entries = rename_entry(self._entries, entry_id, value)
        self._entries = sync_directory_state(
            self._entries, self.store_directory.strip()
        )
        self._persist_settings()
        self._emit_selected_output()
        self._update_status_label()
        self._request_ui_refresh()
        return True
