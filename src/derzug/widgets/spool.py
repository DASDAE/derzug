"""
Pure Orange widget for loading DASCore example spools.
"""

from __future__ import annotations

import ast
import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any

import dascore as dc
import numpy as np
import pandas as pd
from AnyQt.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QTimer
from AnyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from dascore.clients.dirspool import DirectorySpool
from dascore.clients.filespool import FileSpool
from dascore.utils.patch import get_patch_names
from Orange.widgets import gui
from Orange.widgets.utils.concurrent import ConcurrentWidgetMixin, TaskState
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg
from rich.progress import Progress as RichProgress

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting
from derzug.utils.display import format_display
from derzug.utils.dynamic_rows import DynamicRowManager
from derzug.utils.example_parameters import (
    ExampleParametersDialog,
    build_example_call_kwargs,
    filter_example_overrides,
    get_example_parameter_specs,
)
from derzug.utils.qt import FileOrDirDialog
from derzug.utils.spool import (
    extract_single_patch,
    normalize_dims_value,
)

_PATCH_EMOJI = "⚡"

# Curated subset of spool.get_contents() columns for the table view.
# Columns absent from a given DataFrame are silently skipped.
_DISPLAY_COLUMNS = (
    "network",
    "station",
    "tag",
    "instrument_id",
    "dims",
    "data_units",
    "time_min",
    "time_max",
    "duration",
    "time_step",
    "distance_min",
    "distance_max",
    "distance_step",
)
_DEFAULT_EXAMPLE = "example_event_2"

# Examples that aren't terribly interesting so we dont include them in the
# the drop down menu.
_IGNORE_EXAMPLES = (
    "diverse_das",
    "random_directory_das",
    "patch_with_null",
    "wacky_dim_coords_patch",
)


def _collapsible_section(parent: QWidget, title: str, expanded: bool = True) -> QWidget:
    """Add a collapsible QGroupBox to parent; return the body widget to populate."""
    group = QGroupBox(title, parent)
    group.setCheckable(True)
    group.setChecked(expanded)

    outer = QVBoxLayout(group)
    outer.setContentsMargins(4, 8, 4, 4)
    outer.setSpacing(4)

    body = QWidget(group)
    body.setLayout(QVBoxLayout())
    body.layout().setContentsMargins(0, 0, 0, 0)
    body.layout().setSpacing(4)
    outer.addWidget(body)

    group.toggled.connect(body.setVisible)
    parent.layout().addWidget(group)
    return body


def _all_examples(ignore=()) -> dict[str, object]:
    """Return a single dict of all registered example callables, spools first."""
    examples = {**dc.examples.EXAMPLE_SPOOLS, **dc.examples.EXAMPLE_PATCHES}
    out = {i: v for i, v in examples.items() if i not in ignore}
    return out


def _format_table_header(name: str) -> str:
    """Return a readable table header label."""
    return name.replace("_", " ").title()


def _format_table_value(value: Any) -> str:
    """Return the display text for one table cell."""
    return format_display(value)


def _table_sort_value(value: Any) -> Any:
    """Return a stable sort value separate from the display string."""
    if value is None:
        return ""
    # pd.Timedelta is a datetime.timedelta subclass but np.asarray gives object dtype.
    if isinstance(value, datetime.timedelta):
        return int(value.total_seconds() * 1e9)
    arr = np.asarray(value)
    if np.issubdtype(arr.dtype, np.datetime64):
        return int(arr.astype("datetime64[ns]").astype(np.int64))
    if np.issubdtype(arr.dtype, np.timedelta64):
        return int(arr.astype("timedelta64[ns]").astype(np.int64))
    if np.issubdtype(arr.dtype, np.number):
        return value.item() if isinstance(value, np.generic) else value
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def _table_alignment(value: Any) -> Qt.AlignmentFlag:
    """Return a sensible cell alignment for one table value."""
    if isinstance(value, datetime.timedelta):
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    arr = np.asarray(value)
    if np.issubdtype(arr.dtype, np.number):
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    if np.issubdtype(arr.dtype, np.datetime64):
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    if np.issubdtype(arr.dtype, np.timedelta64):
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class _SpoolContentsTableModel(QAbstractTableModel):
    """Lightweight dataframe-backed model for spool contents."""

    def __init__(self, df, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._headers = [_format_table_header(col) for col in self._columns]
        self._display_df = df[self._columns].reset_index(drop=True)
        self._row_order = list(range(len(self._display_df)))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the current row count."""
        if parent.isValid():
            return 0
        return len(self._row_order)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the current column count."""
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return display, sort, and alignment data for one cell."""
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if (
            row < 0
            or row >= len(self._row_order)
            or col < 0
            or col >= len(self._columns)
        ):
            return None
        source_row = self._row_order[row]
        value = self._display_df.iat[source_row, col]
        if role == Qt.ItemDataRole.DisplayRole:
            return _format_table_value(value)
        if role == Qt.ItemDataRole.UserRole:
            return _table_sort_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_table_alignment(value))
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        """Return header labels for the visible columns."""
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
            return None
        return None

    def sort(
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Sort rows by the requested visible column."""
        if column < 0 or column >= len(self._columns):
            return
        self.layoutAboutToBeChanged.emit()
        reverse = order == Qt.SortOrder.DescendingOrder
        self._row_order.sort(
            key=lambda row: _table_sort_value(self._display_df.iat[row, column]),
            reverse=reverse,
        )
        self.layoutChanged.emit()

    def source_row_for_view_row(self, row: int) -> int:
        """Return the original spool row index for one visible table row."""
        if row < 0 or row >= len(self._row_order):
            raise IndexError(row)
        return self._row_order[row]

    def view_row_for_source_row(self, row: int) -> int:
        """Return the visible row index for one original spool row."""
        if row < 0:
            raise IndexError(row)
        return self._row_order.index(row)


_TASK_LOAD = "load"
_TASK_EMIT = "emit"


class _TaskStateProgress(RichProgress):
    """Bridge DasCore Rich progress reporting to an Orange TaskState."""

    def __init__(self, state: TaskState, start_pct: int, end_pct: int) -> None:
        super().__init__(disable=True)  # suppress terminal rendering
        self._state = state
        self._start_pct = start_pct
        self._end_pct = end_pct

    def advance(self, task_id, advance: float = 1) -> None:
        super().advance(task_id, advance)
        try:
            task = self._tasks[task_id]
            if task.total:
                frac = min(task.completed / task.total, 1.0)
                pct = int(self._start_pct + frac * (self._end_pct - self._start_pct))
                self._state.set_progress_value(pct)
        except Exception:
            pass


def _load_spool_task(loader, state: TaskState) -> dc.BaseSpool:
    """Run loader() then update() in a worker thread, reporting progress."""
    state.set_progress_value(5)
    spool = loader()
    state.set_progress_value(30)
    state.set_status("Updating spool index…")
    progress = _TaskStateProgress(state, start_pct=30, end_pct=95)
    spool = spool.update(progress=progress)
    state.set_progress_value(100)
    return spool


def _emit_task(
    display_spool: dc.BaseSpool,
    selected_source_rows: frozenset[int],
    unpack_single: bool,
    visible_row_count: int | None,
    state: TaskState,
) -> tuple[dc.BaseSpool | None, dc.Patch | None]:
    """Read selected patch data off the main thread and return (spool, patch)."""
    if not selected_source_rows:
        output_spool = display_spool
        if unpack_single and visible_row_count == 1:
            output_patch = extract_single_patch(output_spool)
        else:
            output_patch = None
    else:
        patches = _spool_rows_to_patches(display_spool, selected_source_rows)
        output_spool = dc.spool(patches)
        if unpack_single and len(selected_source_rows) == 1:
            output_patch = extract_single_patch(output_spool)
        else:
            output_patch = None
    return output_spool, output_patch


def _ordered_contents_df_with_source_rows(spool: dc.BaseSpool) -> pd.DataFrame:
    """Return spool contents in display order with source-row mapping preserved."""
    df = spool.get_contents()
    if df.empty:
        ordered = df.copy()
        ordered["_source_row"] = pd.Series(dtype=np.int64)
        return ordered
    ordered = df.copy()
    ordered["_source_row"] = np.arange(len(ordered), dtype=np.int64)
    if not isinstance(spool, DirectorySpool):
        return ordered
    sort_cols = [
        column
        for column in ("path", "tag", "station", "network", "time_min", "time_max")
        if column in ordered.columns
    ]
    sort_cols.append("_source_row")
    return ordered.sort_values(
        by=sort_cols,
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def _spool_indices_for_rows(
    spool: dc.BaseSpool,
    selected_rows: set[int] | frozenset[int],
) -> list[int]:
    """Map visible row indices onto spool indices without loading patch payloads."""
    if not selected_rows:
        return []
    if not hasattr(spool, "get_contents"):
        return sorted(int(row) for row in selected_rows)
    ordered_df = _ordered_contents_df_with_source_rows(spool)
    indices = []
    for row in sorted(selected_rows):
        if row < 0 or row >= len(ordered_df):
            raise IndexError(row)
        indices.append(int(ordered_df.iloc[row]["_source_row"]))
    return indices


def _spool_rows_to_patches(
    spool: dc.BaseSpool,
    selected_rows: set[int] | frozenset[int],
) -> list[dc.Patch]:
    """Return selected patches without materializing the entire spool."""
    return [spool[index] for index in _spool_indices_for_rows(spool, selected_rows)]


def _serialize_identity_value(value: Any) -> str:
    """Return one spool-contents value as a stable identity string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str | int | float | bool | Path)):
        return str(value)
    if isinstance(value, datetime.timedelta):
        return str(int(value.total_seconds() * 1e9))
    arr = np.asarray(value)
    if arr.ndim == 0:
        item = arr.item()
        return _serialize_identity_value(item)
    return repr(value)


def _contents_identity_token(df: pd.DataFrame, row: int) -> str:
    """Return a stable row token from spool contents without loading patches."""
    if row < 0 or row >= len(df):
        raise IndexError(row)
    if "path" in df.columns:
        value = df.iloc[row]["path"]
        text = _serialize_identity_value(value).strip()
        if text:
            return f"path:{Path(text).stem}"
    parts = []
    for column in df.columns:
        parts.append(f"{column}={_serialize_identity_value(df.iloc[row][column])}")
    return "row:" + "|".join(parts)


class Spool(ConcurrentWidgetMixin, ZugWidget):
    """Orange widget for loading DASCore example spools."""

    name = "Spool"
    description = "Interact with DASCore Spools"
    icon = "icons/Spool.svg"
    category = "IO"
    keywords = ("dascore", "examples", "spool", "patch")
    priority = 15
    is_source = True

    spool_input = Setting(None)
    # These overrides must round-trip through saved workflows because example
    # functions are now configurable from a generated dialog.
    example_parameters = Setting({})
    file_input = Setting("")
    raw_input = Setting("")
    chunk_dim = Setting("")
    chunk_value = Setting("")
    chunk_overlap = Setting("")
    chunk_keep_partial = Setting(False)
    chunk_snap_coords = Setting(True)
    chunk_tolerance = Setting(1.5)
    chunk_conflict = Setting("raise")
    select_filters = Setting([])
    select_col = Setting("")
    select_val = Setting("")
    selected_source_row = Setting(None)
    selected_source_patch_name = Setting("")
    unpack_single_patch = Setting(True)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        load_failed = Msg("Could not load example '{}': {}")
        general = Msg("An unexpected error occurred: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        no_examples = Msg("No DASCore examples were discovered")
        general = Msg("An unexpected warning: {}")

    class Outputs:
        """Widget output signals."""

        spool = Output("Spool", dc.BaseSpool, doc="The loaded or filtered spool")
        patch = Output(
            "Patch",
            dc.Patch,
            doc=(
                "Single patch unpacked from the spool when exactly one patch is "
                f"selected or available. The {_PATCH_EMOJI} indicator in the widget "
                f"title shows when this output is active"
            ),
        )

    class Inputs:
        """Widget input signals."""

        patch = Input("Patch", dc.Patch, doc="Patch to append to the current spool")
        spool = Input(
            "Spool",
            dc.BaseSpool,
            doc=(
                "Spool whose patches are merged into the current spool. The widget "
                "marked with ★ in its title is the active source — the one that "
                "responds to keyboard step commands"
            ),
        )

    def __init__(self) -> None:
        ZugWidget.__init__(self)
        ConcurrentWidgetMixin.__init__(self)
        self._base_caption = self.name
        self._examples: list[str] = sorted(
            _all_examples(ignore=_IGNORE_EXAMPLES), key=str.casefold
        )
        self._source_spool: dc.BaseSpool | None = None
        self._display_spool: dc.BaseSpool | None = None
        self._pending_source_name: str | None = None
        self._pending_task_type: str | None = None
        self._pending_restore_emit: bool = False
        self._shutting_down: bool = False
        self._table_selection_model = None
        self._select_options: tuple[str, ...] = ()
        self._migrate_select_filters()

        params_box = gui.widgetBox(self.controlArea, "Parameters")
        self.update_button = QPushButton("Update", params_box)
        self.update_button.setToolTip("Refresh the current underlying spool")
        params_box.layout().addWidget(self.update_button)
        self._build_inputs_section(params_box)
        self._build_chunk_section(params_box)
        self._build_select_section(params_box)
        self._restore_initial_source_state()
        self._connect_control_signals()
        self._build_table_view()
        # Load and display the persisted/default source immediately.
        self.run()
        self._migrate_select_filters()
        self._refresh_select_rows()
        self._initialize_active_source_selection()

    def _build_inputs_section(self, parent: QWidget) -> None:
        """Build the source-input controls."""
        box = _collapsible_section(parent, "Inputs")
        self._inputs_group = box.parent()
        gui.widgetLabel(box, "Example:")
        self.example_combo = QComboBox(box)
        self.example_combo.addItems(self._examples)
        self.example_combo.setToolTip(
            "Select an example. Right-click to configure example parameters."
        )
        self.example_combo.installEventFilter(self)
        box.layout().addWidget(self.example_combo)
        gui.widgetLabel(box, "File / Directory:")
        file_row = QWidget(box)
        file_row_layout = QHBoxLayout(file_row)
        file_row_layout.setContentsMargins(0, 0, 0, 0)
        file_row_layout.setSpacing(4)
        self.file_path_edit = QLineEdit(file_row)
        self.file_path_edit.setReadOnly(True)
        self.open_button = QPushButton("Open...", file_row)
        file_row_layout.addWidget(self.file_path_edit, 1)
        file_row_layout.addWidget(self.open_button)
        box.layout().addWidget(file_row)
        self.raw_edit = gui.lineEdit(
            box,
            self,
            "raw_input",
            label="Raw Input",
        )

    def _set_source_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the source-entry controls."""
        self.example_combo.setEnabled(enabled)
        self.file_path_edit.setEnabled(enabled)
        self.open_button.setEnabled(enabled)
        self.raw_edit.setEnabled(enabled)

    def set_canvas_source(self, value: dc.Patch | dc.BaseSpool) -> None:
        """
        Replace the current source with fixed canvas input and lock source controls.
        """
        self.cancel()
        self._pending_task_type = None
        self._pending_source_name = None
        self.Error.clear()
        self.Warning.clear()
        self._clear_other_inputs("canvas")
        self._set_source_controls_enabled(False)
        self._inputs_group.setChecked(False)
        spool = dc.spool([value]) if isinstance(value, dc.Patch) else value
        self._set_source_spool(spool)
        self._schedule_emit()

    def _build_chunk_section(self, parent: QWidget) -> None:
        """Build the chunking controls."""
        chunk_box = _collapsible_section(parent, "Chunk")
        chunk_row = QWidget(chunk_box)
        chunk_row_layout = QHBoxLayout(chunk_row)
        chunk_row_layout.setContentsMargins(0, 0, 0, 0)
        chunk_row_layout.setSpacing(4)
        self.chunk_dim_combo = QComboBox(chunk_row)
        self.chunk_dim_combo.setEnabled(False)
        self.chunk_value_edit = QLineEdit(chunk_row)
        self.chunk_value_edit.setPlaceholderText("Chunk Value")
        self.chunk_value_edit.setEnabled(False)
        chunk_row_layout.addWidget(self.chunk_dim_combo, 1)
        chunk_row_layout.addWidget(self.chunk_value_edit, 1)
        chunk_box.layout().addWidget(chunk_row)
        self.chunk_overlap_edit = gui.lineEdit(
            chunk_box,
            self,
            "chunk_overlap",
            label="Overlap",
        )
        self.chunk_overlap_edit.setEnabled(False)
        self.chunk_keep_partial_cb = gui.checkBox(
            chunk_box, self, "chunk_keep_partial", "Keep Partial"
        )
        self.chunk_keep_partial_cb.setEnabled(False)
        self.chunk_snap_coords_cb = gui.checkBox(
            chunk_box, self, "chunk_snap_coords", "Snap Coords"
        )
        self.chunk_snap_coords_cb.setEnabled(False)
        self.chunk_tolerance_spin = gui.doubleSpin(
            chunk_box,
            self,
            "chunk_tolerance",
            0.0,
            1_000_000.0,
            step=0.1,
            label="Tolerance",
        )
        self.chunk_tolerance_spin.setEnabled(False)
        self.chunk_conflict_combo = gui.comboBox(
            chunk_box,
            self,
            "chunk_conflict",
            label="Conflict",
            items=["drop", "raise", "keep_first"],
            sendSelectedValue=True,
        )
        self.chunk_conflict_combo.setEnabled(False)

    def _build_select_section(self, parent: QWidget) -> None:
        """Build the select controls."""
        select_box = _collapsible_section(parent, "Select")
        controls_row = QWidget(select_box)
        controls_layout = QHBoxLayout(controls_row)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(4)
        controls_layout.addStretch(1)
        self.select_add_button = QPushButton("+", controls_row)
        self.select_add_button.setFixedWidth(24)
        self.select_add_button.setToolTip("Add another select filter")
        controls_layout.addWidget(self.select_add_button)
        select_box.layout().addWidget(controls_row)
        self._select_rows_container = QWidget(select_box)
        self._select_rows_container.setLayout(QVBoxLayout())
        self._select_rows_container.layout().setContentsMargins(0, 0, 0, 0)
        self._select_rows_container.layout().setSpacing(4)
        select_box.layout().addWidget(self._select_rows_container)
        self._select_row_manager = DynamicRowManager(
            blank_state_factory=self._blank_select_filter,
            create_row=self._create_select_row,
            apply_row_state=self._set_select_row_state,
            serialize_row=self._serialize_select_row,
            delete_row_widget=lambda row: row["widget"].deleteLater(),
            set_row_remove_enabled=lambda row, enabled: row["remove"].setEnabled(
                enabled
            ),
            on_rows_changed=self._on_select_changed,
        )
        self._select_rows = self._select_row_manager.rows
        self._refresh_select_rows()
        self._refresh_primary_select_aliases()
        self.unpack_checkbox = gui.checkBox(
            select_box,
            self,
            "unpack_single_patch",
            "Unpack len1 spool",
        )

    def _restore_initial_source_state(self) -> None:
        """Restore the persisted active source selection."""
        if self.file_input:
            self._clear_other_inputs("file")
            self.file_path_edit.setText(self.file_input)
        elif self.raw_input:
            self._clear_other_inputs("raw")
        else:
            if self.spool_input not in self._examples:
                if _DEFAULT_EXAMPLE in self._examples:
                    self.spool_input = _DEFAULT_EXAMPLE
                else:
                    self.spool_input = self._examples[0] if self._examples else None
            if self._examples and self.spool_input is not None:
                self.example_combo.setCurrentText(self.spool_input)
            elif self._examples:
                self.example_combo.setCurrentIndex(-1)

    def _connect_control_signals(self) -> None:
        """Connect widget signals to their handlers."""
        self.example_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.open_button.clicked.connect(self._select_path_input)
        self.raw_edit.textEdited.connect(self._on_raw_text_edited)
        self.raw_edit.editingFinished.connect(self._on_raw_edit_finished)
        self.chunk_dim_combo.currentIndexChanged.connect(self._on_chunk_dim_changed)
        self.chunk_value_edit.editingFinished.connect(self._on_chunk_param_changed)
        self.chunk_overlap_edit.editingFinished.connect(self._on_chunk_param_changed)
        self.chunk_keep_partial_cb.toggled.connect(self._on_chunk_param_changed)
        self.chunk_snap_coords_cb.toggled.connect(self._on_chunk_param_changed)
        self.chunk_tolerance_spin.valueChanged.connect(self._on_chunk_param_changed)
        self.chunk_conflict_combo.currentIndexChanged.connect(
            self._on_chunk_param_changed
        )
        self.select_add_button.clicked.connect(self._on_add_select_row_clicked)
        self.unpack_checkbox.toggled.connect(lambda *_args: self._schedule_emit())
        self.update_button.clicked.connect(self._on_update_clicked)

    def eventFilter(self, watched: QWidget, event: QEvent) -> bool:
        """Open example parameters when the example combo is right-clicked."""
        if (
            watched is self.example_combo
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.RightButton
        ):
            self._open_example_parameters_dialog()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _build_table_view(self) -> None:
        """Build the main table view."""
        self._table = QTableView(self.mainArea)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setCornerButtonEnabled(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultSectionSize(132)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._table.setStyleSheet(
            "QTableView { alternate-background-color: rgba(0, 0, 0, 0.035); }"
            "QHeaderView::section { padding: 6px 8px; font-weight: 600; }"
        )
        self.mainArea.layout().addWidget(self._table)

    @property
    def _current_spool(self) -> dc.BaseSpool | None:
        """Backward-compatible alias for the base source spool."""
        return self._source_spool

    @_current_spool.setter
    def _current_spool(self, value: dc.BaseSpool | None) -> None:
        """Set the base source spool and reset derived state for compatibility."""
        self._source_spool = value
        self._display_spool = value

    def run(self) -> None:
        """Load selected example and emit spool output."""
        self.Error.clear()
        self.Warning.clear()
        self.cancel()
        self._pending_task_type = None

        source_name, loader_fn = self._snapshot_loader()
        if source_name is None or loader_fn is None:
            self._set_source_spool(None)
            self._schedule_emit()
            return

        self._pending_source_name = source_name
        self._pending_task_type = _TASK_LOAD
        self.start(_load_spool_task, loader_fn)

    def _on_update_clicked(self) -> None:
        """Refresh the currently configured spool source."""
        if self.example_combo.isEnabled():
            self.run()
            return
        if self._source_spool is None:
            self._emit_current_output()
            return
        self.Error.clear()
        self.Warning.clear()
        self.cancel()
        self._pending_task_type = None
        try:
            updated = self._source_spool.update()
        except Exception as exc:
            self._show_exception("general", exc)
            return
        self._set_source_spool(updated)
        self._schedule_emit()

    def _snapshot_loader(self) -> tuple[str | None, Callable | None]:
        """Capture current source state and return (source_name, pure_callable).

        All widget-state reads happen here on the main thread.  The returned
        callable captures only immutable data so it is safe to run in a worker.
        """
        if self.file_input:
            path = self.file_input
            return path, lambda: dc.spool(path)

        if self.raw_input:
            raw = self.raw_input
            return raw, lambda: dc.spool(raw)

        if not self._examples:
            self.Warning.no_examples()
            return None, None
        example_name = self.spool_input
        if not example_name:
            return None, None
        fn = self._selected_example_callable(example_name)
        kwargs = build_example_call_kwargs(
            fn, self.example_parameters_for(example_name)
        )

        def _load() -> dc.BaseSpool:
            result = fn(**kwargs)
            if isinstance(result, dc.Patch):
                return dc.spool([result])
            return result

        return example_name, _load

    def on_done(self, result) -> None:
        """Dispatch the background-task result based on which task just finished."""
        task_type = self._pending_task_type
        self._pending_task_type = None
        if task_type == _TASK_LOAD:
            self._set_source_spool(result)
            # Cannot call self.start() from on_done; defer to next event-loop tick.
            QTimer.singleShot(0, self._schedule_emit)
        else:
            output_spool, output_patch = result
            self._update_caption_for_outputs(output_patch)
            self.Outputs.spool.send(output_spool)
            self.Outputs.patch.send(output_patch)

    def on_exception(self, ex: Exception) -> None:
        """Handle a failure from whichever background task just ran."""
        task_type = self._pending_task_type
        self._pending_task_type = None
        if task_type == _TASK_LOAD:
            self._set_source_spool(None)
            self._show_exception("load_failed", ex, self._pending_source_name or "")
            self._emit_current_output()
        else:
            self._show_exception("general", ex)

    def onDeleteWidget(self) -> None:
        """Shut down the background thread pool when the widget is closed."""
        self._shutting_down = True
        self.shutdown()
        super().onDeleteWidget()

    def _schedule_emit(self) -> None:
        """Snapshot UI state and dispatch patch extraction to the worker thread.

        If a spool load is still in progress the call is silently dropped; the
        deferred _schedule_emit fired from on_done will pick up the latest
        selection state instead.  If there is no loaded spool, None outputs are
        sent synchronously (no I/O involved).
        """
        if self._shutting_down:
            return
        if self._pending_task_type == _TASK_LOAD:
            return
        if self._display_spool is None:
            self._emit_current_output()
            return
        display_spool = self._display_spool
        selected_source_rows = self._snapshot_selected_source_rows()
        unpack = bool(self.unpack_single_patch)
        visible_row_count = self._visible_spool_row_count(display_spool)
        self._pending_task_type = _TASK_EMIT
        self.start(
            _emit_task, display_spool, selected_source_rows, unpack, visible_row_count
        )

    def _snapshot_selected_source_rows(self) -> frozenset[int]:
        """Capture the currently selected source-row indices (main thread only)."""
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return self._restored_selected_source_rows()
        model = self._table.model()
        selected = {idx.row() for idx in selection_model.selectedRows()}
        if not selected and self._pending_restore_emit:
            return self._restored_selected_source_rows()
        if isinstance(model, _SpoolContentsTableModel):
            return frozenset(model.source_row_for_view_row(r) for r in selected)
        return frozenset(selected)

    def _restored_selected_source_rows(self) -> frozenset[int]:
        """Return the persisted row selection while a hidden restore is pending."""
        source_row = self._resolved_selected_source_row()
        if source_row is None:
            return frozenset()
        return frozenset({source_row})

    def _on_combo_changed(self, index: int) -> None:
        """Sync selected combo entry to Setting and run the widget."""
        self._clear_other_inputs("example")
        if index < 0 or index >= len(self._examples):
            self.spool_input = None
        else:
            self.spool_input = self._examples[index]
        self.run()

    def _set_file_input(self, path: str, *, trigger_run: bool) -> None:
        """Set file input path, clear other inputs, and optionally run."""
        cleaned = path.strip()
        if not cleaned:
            return
        self.file_input = cleaned
        self.file_path_edit.setText(cleaned)
        self._clear_other_inputs("file")
        if trigger_run:
            self.run()

    def _select_path_input(self) -> None:
        """Open a picker that accepts either a file or a directory path."""
        selected = self._open_path_dialog()
        self._set_file_input(selected, trigger_run=True)

    def _open_path_dialog(self) -> str:
        """Return a selected file or directory path from one picker dialog."""
        dialog = FileOrDirDialog(self, "Open DAS File Or Directory")
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        # Use Qt's non-native dialog so folder selection semantics are consistent.
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)

        if self.file_input:
            existing = Path(self.file_input)
            if existing.exists():
                dialog.setDirectory(
                    str(existing if existing.is_dir() else existing.parent)
                )

        if dialog.exec():
            return dialog.chosen_path()
        return ""

    def _on_raw_text_edited(self, text: str) -> None:
        """Use raw input as active source while typing and clear other inputs."""
        self.raw_input = text.strip()
        self._clear_other_inputs("raw")

    def _on_raw_edit_finished(self) -> None:
        """Run after raw input editing loses focus."""
        self.raw_input = self.raw_edit.text().strip()
        self.run()

    def _clear_other_inputs(self, active: str) -> None:
        """Keep only one active input source and clear the others."""
        if active != "example":
            self.spool_input = None
            self.example_combo.blockSignals(True)
            self.example_combo.setCurrentIndex(-1)
            self.example_combo.blockSignals(False)

        if active != "file":
            self.file_input = ""
            self.file_path_edit.clear()
        if active != "raw":
            self.raw_input = ""
            self.raw_edit.blockSignals(True)
            self.raw_edit.clear()
            self.raw_edit.blockSignals(False)

    def _load_from_example(self) -> dc.BaseSpool:
        """Load spool from the selected example key."""
        if not self._examples:
            self.Warning.no_examples()
            raise ValueError("No examples available")
        example_name = self._selected_example_name()
        if example_name is None:
            raise ValueError("No example selected")
        fn = self._selected_example_callable(example_name)
        kwargs = build_example_call_kwargs(
            fn,
            self.example_parameters_for(example_name),
        )
        result = fn(**kwargs)
        if isinstance(result, dc.Patch):
            return dc.spool([result])
        return result

    def _selected_example_name(self) -> str | None:
        """Return the currently selected example name, if any."""
        return self.spool_input

    def _example_registry(self) -> dict[str, object]:
        """Return the current example registry used by the widget."""
        return _all_examples()

    def _selected_example_callable(self, example_name: str):
        """Return the callable registered for one example name."""
        return self._example_registry()[example_name]

    def example_parameters_for(self, example_name: str | None) -> dict[str, object]:
        """Return the persisted parameter overrides for one example."""
        if not example_name:
            return {}
        values = (self.example_parameters or {}).get(example_name, {})
        return dict(values) if isinstance(values, dict) else {}

    def _open_example_parameters_dialog(self) -> None:
        """Open the autogenerated parameter dialog for the selected example."""
        example_name = (
            self._selected_example_name() or self.example_combo.currentText().strip()
        )
        if not example_name:
            return
        fn = self._example_registry().get(example_name)
        if fn is None:
            return
        specs = get_example_parameter_specs(fn)
        dialog = ExampleParametersDialog(
            example_name=example_name,
            specs=specs,
            saved_values=self.example_parameters_for(example_name),
            parent=self,
        )
        if dialog.exec():
            self._save_example_parameter_overrides(
                example_name,
                specs,
                dialog.parsed_values,
            )
            if (
                self.spool_input == example_name
                and not self.file_input
                and not self.raw_input
            ):
                self.run()

    def _save_example_parameter_overrides(
        self,
        example_name: str,
        specs,
        values: dict[str, object],
    ) -> None:
        """Persist one example's non-default parameter overrides."""
        current = dict(self.example_parameters or {})
        overrides = filter_example_overrides(specs, values)
        if overrides:
            current[example_name] = overrides
        else:
            current.pop(example_name, None)
        self.example_parameters = current

    def _load_from_file_input(self) -> dc.BaseSpool:
        """Load spool from a file path or directory path string."""
        if not self.file_input:
            raise ValueError("No file input provided")
        return dc.spool(self.file_input)

    def _load_from_raw_input(self) -> dc.BaseSpool:
        """Load spool from raw input string passed directly to DASCore."""
        if not self.raw_input:
            raise ValueError("No raw input provided")
        return dc.spool(self.raw_input)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Append an incoming patch to the current spool."""
        if patch is None:
            return
        self._ingest_input(dc.spool([patch]))

    @Inputs.spool
    def set_spool(self, spool: dc.BaseSpool | None) -> None:
        """Append an incoming spool to the current spool."""
        if spool is None:
            return
        self._ingest_input(spool)

    def _ingest_input(self, incoming: dc.BaseSpool) -> None:
        """Merge incoming spool data into the current spool and emit it."""
        self.Error.general.clear()
        try:
            updated = self._merge_incoming_spool(incoming)
        except Exception as exc:
            self._show_exception("general", exc)
            return
        self._set_source_spool(updated)
        self._schedule_emit()

    def _merge_incoming_spool(self, incoming: dc.BaseSpool) -> dc.BaseSpool:
        """Return an updated spool after appending incoming data."""
        current = self._source_spool
        if current is None:
            return incoming

        put_method = getattr(current, "put", None)
        if callable(put_method):
            result = put_method(incoming)
            if isinstance(result, dc.BaseSpool):
                return result
            return current

        if isinstance(current, DirectorySpool):
            return self._append_to_directory_spool(current, incoming)

        if isinstance(current, FileSpool):
            raise ValueError("Cannot append input to a file-backed spool.")

        return self._append_to_memory_spool(current, incoming)

    def _append_to_directory_spool(
        self, current: DirectorySpool, incoming: dc.BaseSpool
    ) -> dc.BaseSpool:
        """Write incoming patches into a directory-backed spool and reload it."""
        directory = Path(current.spool_path)
        self._write_spool_to_directory(incoming, directory)
        return dc.spool(directory)

    def _append_to_memory_spool(
        self, current: dc.BaseSpool, incoming: dc.BaseSpool
    ) -> dc.BaseSpool:
        """Append incoming spool data in memory and rebuild the spool."""
        return dc.spool([*current, *incoming])

    def _write_spool_to_directory(
        self,
        spool: dc.BaseSpool,
        directory: Path,
        *,
        file_format: str = "DASDAE",
        extension: str = "hdf5",
    ) -> None:
        """Persist each patch in a spool to a target directory."""
        directory.mkdir(parents=True, exist_ok=True)
        for patch in spool:
            patch_name = str(get_patch_names(patch).iloc[0])
            out_path = directory / f"{patch_name}.{extension}"
            patch.io.write(out_path, file_format=file_format)

    def _reset_chunk_controls(self) -> None:
        """Disable and clear chunk and select controls when no spool is available."""
        self.chunk_dim = ""
        self.chunk_value = ""
        self.chunk_overlap = ""
        self.select_filters = [self._blank_select_filter()]
        self.select_col = ""
        self.select_val = ""
        self._select_options = ()
        self.chunk_dim_combo.blockSignals(True)
        self.chunk_dim_combo.clear()
        self.chunk_dim_combo.setEnabled(False)
        self.chunk_dim_combo.blockSignals(False)
        self.chunk_value_edit.blockSignals(True)
        self.chunk_value_edit.clear()
        self.chunk_value_edit.setEnabled(False)
        self.chunk_value_edit.blockSignals(False)
        self.chunk_overlap_edit.blockSignals(True)
        self.chunk_overlap_edit.clear()
        self.chunk_overlap_edit.setEnabled(False)
        self.chunk_overlap_edit.blockSignals(False)
        self.chunk_keep_partial_cb.setEnabled(False)
        self.chunk_snap_coords_cb.setEnabled(False)
        self.chunk_tolerance_spin.setEnabled(False)
        self.chunk_conflict_combo.setEnabled(False)
        self._refresh_select_rows()

    def _set_chunk_dims_from_contents(self, df) -> None:
        """Populate chunk dimension choices from the contents DataFrame."""
        if "dims" not in df.columns:
            self._reset_chunk_controls()
            return
        options: list[str] = []
        seen: set[str] = set()
        for value in df["dims"]:
            for dim in normalize_dims_value(value):
                if dim not in seen:
                    seen.add(dim)
                    options.append(dim)

        self.chunk_dim_combo.blockSignals(True)
        self.chunk_dim_combo.clear()
        if not options:
            self.chunk_dim = ""
            self.chunk_dim_combo.setEnabled(False)
            self.chunk_value_edit.setEnabled(False)
            self.chunk_dim_combo.blockSignals(False)
            return
        options = sorted(options, key=str.casefold)
        self.chunk_dim_combo.addItems(options)
        self.chunk_dim_combo.setEnabled(True)
        self.chunk_value_edit.setEnabled(True)
        self.chunk_overlap_edit.setEnabled(True)
        self.chunk_keep_partial_cb.setEnabled(True)
        self.chunk_snap_coords_cb.setEnabled(True)
        self.chunk_tolerance_spin.setEnabled(True)
        self.chunk_conflict_combo.setEnabled(True)
        if self.chunk_dim in options:
            self.chunk_dim_combo.setCurrentText(self.chunk_dim)
        else:
            self.chunk_dim = ""
            self.chunk_dim_combo.setCurrentIndex(-1)
        self.chunk_dim_combo.blockSignals(False)

    def _set_select_cols_from_contents(self, df) -> None:
        """Populate select column choices from the contents DataFrame."""
        visible_cols = self._visible_contents_columns(df)
        dims: list[str] = []
        if "dims" in df.columns:
            seen: set[str] = set(visible_cols)
            for value in df["dims"]:
                for dim in normalize_dims_value(value):
                    if dim not in seen:
                        seen.add(dim)
                        dims.append(dim)
        self._select_options = tuple(sorted(visible_cols + dims, key=str.casefold))
        self._refresh_select_rows()

    def _on_select_changed(self, *_args) -> None:
        """Apply select filter and emit filtered spool."""
        self._sync_select_filters_from_ui()
        if self._source_spool is None:
            return
        self._recompute_display_spool()
        self._schedule_emit()

    def _on_chunk_dim_changed(self, index: int) -> None:
        """Handle dimension changes and apply chunk if all inputs are present."""
        if index < 0:
            self.chunk_dim = ""
            return
        dim = self.chunk_dim_combo.itemText(index).strip()
        self.chunk_dim = dim
        self._on_chunk_param_changed()

    def _parse_chunk_scalar(self, text: str) -> Any:
        """Parse text for chunk kwargs, supporting literals and ellipsis."""
        t = text.strip()
        if not t:
            return None
        if t == "...":
            return ...
        try:
            return ast.literal_eval(t)
        except Exception:
            return t

    def _on_chunk_param_changed(self, *_args) -> None:
        """Apply chunk with selected parameters and emit chunked spool."""
        if self._source_spool is None:
            return
        self.chunk_value = self.chunk_value_edit.text().strip()
        self.chunk_overlap = self.chunk_overlap_edit.text().strip()
        self._recompute_display_spool()
        self._schedule_emit()

    def _set_source_spool(self, spool: dc.BaseSpool | None) -> None:
        """Store the source spool and refresh derived display state."""
        self._source_spool = spool
        self._pending_restore_emit = (
            spool is not None
            and self.selected_source_row is not None
            and not self._is_ui_visible()
        )
        self._recompute_display_spool()

    def _recompute_display_spool(self) -> None:
        """Rebuild the displayed spool from the base source spool and transforms."""
        source = self._source_spool
        if source is None:
            self._display_spool = None
            self._request_ui_refresh()
            return
        try:
            # Narrow the spool before any downstream patch materialization so
            # chunking and row extraction work on the smallest candidate set.
            display = self._apply_select_transform(source)
            display = self._apply_chunk_transform(display)
        except Exception as exc:
            self._display_spool = source
            self._show_exception("general", exc)
            return
        self._display_spool = display
        self._request_ui_refresh()

    def _refresh_ui(self) -> None:
        """Refresh the visible table and transform controls."""
        self._render_spool(self._display_spool)

    def _apply_chunk_transform(self, spool: dc.BaseSpool) -> dc.BaseSpool:
        """Return the source spool or a chunked derivative based on current controls."""
        dim = (self.chunk_dim or "").strip()
        value = self._parse_chunk_scalar(self.chunk_value_edit.text())
        if not dim or value is None:
            return spool

        overlap = self._parse_chunk_scalar(self.chunk_overlap_edit.text())
        kwargs = {
            dim: value,
            "overlap": overlap,
            "keep_partial": bool(self.chunk_keep_partial),
            "snap_coords": bool(self.chunk_snap_coords),
            "tolerance": float(self.chunk_tolerance),
            "conflict": self.chunk_conflict,
        }
        return spool.chunk(**kwargs)

    def _apply_select_transform(self, spool: dc.BaseSpool) -> dc.BaseSpool:
        """Return the input spool or a selection-filtered derivative."""
        kwargs = {}
        for filter_data in self._iter_active_select_filters():
            value = self._parse_chunk_scalar(filter_data["raw"])
            if value is None:
                continue
            kwargs[filter_data["key"]] = value
        if not kwargs:
            return spool
        return spool.select(**kwargs)

    @staticmethod
    def _blank_select_filter() -> dict[str, str]:
        """Return one empty select-filter entry."""
        return {"key": "", "raw": ""}

    def _migrate_select_filters(self) -> None:
        """Migrate legacy single-select settings into the row-based filter list."""
        filters = [
            {
                "key": str(item.get("key", "")).strip(),
                "raw": str(item.get("raw", "")).strip(),
            }
            for item in (self.select_filters or [])
            if isinstance(item, dict)
        ]
        if not filters and (self.select_col or self.select_val):
            filters = [
                {
                    "key": str(self.select_col or "").strip(),
                    "raw": str(self.select_val or "").strip(),
                }
            ]
        self.select_filters = filters or [self._blank_select_filter()]

    def _create_select_row(
        self,
        on_change,
        on_remove,
    ) -> dict[str, QWidget]:
        """Create and return one select-filter row."""
        row_widget = QWidget(self._select_rows_container)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        combo = QComboBox(row_widget)
        value_edit = QLineEdit(row_widget)
        value_edit.setPlaceholderText("Value")
        remove_button = QPushButton("-", row_widget)
        remove_button.setFixedWidth(24)
        remove_button.setToolTip("Remove this select filter")
        row_layout.addWidget(combo, 1)
        row_layout.addWidget(value_edit, 1)
        row_layout.addWidget(remove_button)
        combo.currentIndexChanged.connect(on_change)
        value_edit.editingFinished.connect(on_change)
        row = {
            "widget": row_widget,
            "combo": combo,
            "edit": value_edit,
            "remove": remove_button,
        }
        remove_button.clicked.connect(lambda *_args, current=row: on_remove(current))
        self._select_rows_container.layout().addWidget(row_widget)
        return row

    def _set_select_row_state(
        self, row: dict[str, QWidget], filter_data: dict[str, str]
    ) -> None:
        """Apply options and values to one select-filter row."""
        combo = row["combo"]
        edit = row["edit"]
        key = str(filter_data.get("key", "")).strip()
        raw = str(filter_data.get("raw", "")).strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(self._select_options)
        combo.setEnabled(bool(self._select_options))
        if key and key not in self._select_options:
            combo.addItem(key)
            combo.setCurrentText(key)
        elif key in self._select_options:
            combo.setCurrentText(key)
        else:
            combo.setCurrentIndex(-1)
        combo.blockSignals(False)
        edit.blockSignals(True)
        edit.setText(raw)
        edit.setEnabled(bool(self._select_options))
        edit.blockSignals(False)

    def _refresh_select_rows(self) -> None:
        """Refresh all select-filter rows from the persisted filter state."""
        filters = self.select_filters or [self._blank_select_filter()]
        self._select_row_manager.refresh(filters)
        self.select_add_button.setEnabled(bool(self._select_options))
        self._refresh_primary_select_aliases()

    def _refresh_primary_select_aliases(self) -> None:
        """Expose the first select row through the legacy widget attributes."""
        first = self._select_rows[0]
        self.select_col_combo = first["combo"]
        self.select_val_edit = first["edit"]

    def _sync_select_filters_from_ui(self) -> None:
        """Persist the current UI select rows into widget settings."""
        self.select_filters = self._select_row_manager.sync_from_ui()
        first = self.select_filters[0]
        self.select_col = first["key"]
        self.select_val = first["raw"]

    def _serialize_select_row(self, row: dict[str, QWidget]) -> dict[str, str]:
        """Serialize one select row from the current UI."""
        return {
            "key": row["combo"].currentText().strip(),
            "raw": row["edit"].text().strip(),
        }

    def _iter_active_select_filters(self) -> list[dict[str, str]]:
        """Return non-empty select filters from the current widget state."""
        self._sync_select_filters_from_ui()
        return [
            item
            for item in self.select_filters
            if item["key"].strip() and item["raw"].strip()
        ]

    def _on_add_select_row_clicked(self) -> None:
        """Append a blank select row and re-run selection."""
        self._select_row_manager.add_blank_row()

    def _remove_select_row(self, row: dict[str, QWidget]) -> None:
        """Remove one select row, keeping at least one row available."""
        self._select_row_manager.remove_row(row)

    def _render_spool(self, spool: dc.BaseSpool | None) -> None:
        """Refresh the table and control state for the displayed spool."""
        if spool is None:
            self._disconnect_table_selection_model()
            self._table.setModel(None)
            self.selected_source_row = None
            self.selected_source_patch_name = ""
            self._reset_chunk_controls()
            return
        try:
            df = self._ordered_contents_df(spool)
            self._set_chunk_dims_from_contents(df)
            select_df = (
                self._ordered_contents_df(self._source_spool)
                if self._source_spool is not None
                else df
            )
            self._set_select_cols_from_contents(select_df)
            table_model = self._build_table_model(df)
            self._disconnect_table_selection_model()
            self._table.setModel(table_model)
            self._connect_table_selection_model()
            self._restore_saved_row_selection(table_model)
        except Exception as exc:
            self._disconnect_table_selection_model()
            self._table.setModel(None)
            self.selected_source_row = None
            self.selected_source_patch_name = ""
            self.Warning.general(str(exc))

    def _build_table_model(self, df) -> _SpoolContentsTableModel:
        """Return a Qt item model for the visible spool contents columns."""
        # Compute duration from time bounds when both are present.
        if "time_min" in df.columns and "time_max" in df.columns:
            df = df.copy()
            df["duration"] = pd.to_timedelta(df["time_max"] - df["time_min"], unit="s")
        cols = self._visible_contents_columns(df)
        return _SpoolContentsTableModel(df, cols, self._table)

    def _visible_contents_columns(self, df) -> list[str]:
        """Return the configured table columns that contain visible values."""
        return [
            c
            for c in _DISPLAY_COLUMNS
            if c in df.columns and df[c].astype(str).str.strip().ne("").any()
        ]

    def _get_selected_output_spool(self) -> dc.BaseSpool | None:
        """Return the display spool filtered to selected rows, if any."""
        if self._display_spool is None:
            return None
        selection_model = self._table.selectionModel()
        if selection_model is None:
            restored_rows = self._restored_selected_source_rows()
            if restored_rows:
                return self._spool_rows_to_output(
                    self._display_spool, set(restored_rows)
                )
            return self._display_spool
        selected_rows = {idx.row() for idx in selection_model.selectedRows()}
        if not selected_rows:
            restored_rows = self._restored_selected_source_rows()
            if restored_rows:
                return self._spool_rows_to_output(
                    self._display_spool, set(restored_rows)
                )
            return self._display_spool
        model = self._table.model()
        if not isinstance(model, _SpoolContentsTableModel):
            return self._spool_rows_to_output(self._display_spool, selected_rows)
        selected_source_rows = {
            model.source_row_for_view_row(row) for row in selected_rows
        }
        return self._spool_rows_to_output(self._display_spool, selected_source_rows)

    @staticmethod
    def _spool_rows_to_output(
        spool: dc.BaseSpool,
        selected_rows: set[int],
    ) -> dc.BaseSpool:
        """Return a spool containing only the requested source rows."""
        indices = _spool_indices_for_rows(spool, selected_rows)
        if not indices:
            return spool
        if not hasattr(spool, "get_contents"):
            if len(indices) == 1:
                index = int(indices[0])
                return spool[index : index + 1]
            return dc.spool([spool[int(index)] for index in indices])
        return spool[np.asarray(indices, dtype=np.int64)]

    def _emit_current_output(self) -> None:
        """Emit the current output spool and optional unpacked patch."""
        restored_rows = self._restored_selected_source_rows()
        selection_model = self._table.selectionModel()
        if (
            self._display_spool is not None
            and selection_model is None
            and restored_rows
        ):
            spool = self._spool_rows_to_output(self._display_spool, set(restored_rows))
            patch = extract_single_patch(spool) if self.unpack_single_patch else None
        else:
            spool = self._get_selected_output_spool()
            patch = self._extract_output_patch(spool)
        self._update_caption_for_outputs(patch)
        self.Outputs.spool.send(spool)
        self.Outputs.patch.send(patch)

    def _extract_output_patch(self, spool: dc.BaseSpool | None) -> dc.Patch | None:
        """Return the patch output when the current visible selection has one row."""
        if not self.unpack_single_patch or spool is None:
            return None
        selected_rows = self._selected_table_rows()
        if len(selected_rows) == 1:
            return extract_single_patch(spool)
        if selected_rows:
            return None
        row_count = self._visible_spool_row_count(spool)
        if row_count != 1:
            return None
        return extract_single_patch(spool)

    def _selected_table_rows(self) -> set[int]:
        """Return the currently selected visible table rows."""
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return set(self._restored_selected_source_rows())
        selected = {idx.row() for idx in selection_model.selectedRows()}
        if selected:
            return selected
        if self._pending_restore_emit:
            return set(self._restored_selected_source_rows())
        return set()

    def _visible_spool_row_count(self, spool: dc.BaseSpool) -> int | None:
        """Return the visible spool row count without loading patch payloads."""
        model = self._table.model()
        if model is not None:
            return model.rowCount()
        try:
            return len(spool.get_contents())
        except Exception:
            return None

    def _update_caption_for_outputs(self, patch: dc.Patch | None) -> None:
        """Decorate the live caption when Patch output is currently active."""
        previous_caption = self.captionTitle
        previous_node_title = self._current_node_title()
        caption = self._base_caption
        if patch is not None:
            caption = f"{caption} {_PATCH_EMOJI}"
        if self.captionTitle != caption:
            self.captionTitle = caption
            self.setWindowTitle(caption)
            self._sync_node_title(previous_caption, previous_node_title, caption)

    def _current_node_title(self) -> str | None:
        """Return the current scheme node title, if this widget is on a canvas."""
        signal_manager = getattr(self, "signalManager", None)
        if signal_manager is None:
            return None
        scheme_getter = getattr(signal_manager, "scheme", None)
        if scheme_getter is None:
            return None
        scheme = scheme_getter()
        if scheme is None:
            return None
        node = scheme.node_for_widget(self)
        if node is None:
            return None
        return getattr(node, "title", "")

    def _sync_node_title(
        self,
        previous_caption: str,
        previous_node_title: str | None,
        new_caption: str,
    ) -> None:
        """Keep default-titled nodes in sync while preserving custom node titles."""
        signal_manager = getattr(self, "signalManager", None)
        if signal_manager is None:
            return
        scheme_getter = getattr(signal_manager, "scheme", None)
        if scheme_getter is None:
            return
        scheme = scheme_getter()
        if scheme is None:
            return
        node = scheme.node_for_widget(self)
        if node is None:
            return
        if previous_node_title is None:
            return

        managed_titles = {
            self._base_caption,
            f"{self._base_caption} {_PATCH_EMOJI}",
        }
        desired_title = (
            new_caption
            if previous_node_title in managed_titles
            else previous_node_title
        )
        node.title = desired_title
        QTimer.singleShot(
            0,
            lambda n=node, t=desired_title: setattr(n, "title", t),
        )
        from derzug.views import orange as orange_view

        manager = orange_view._APP_ACTIVE_SOURCE_MANAGER
        main_window = orange_view._APP_ACTIVE_SOURCE_MAIN_WINDOW
        if manager is not None and main_window is not None:
            manager.refresh_active_marker(main_window)

    def _connect_table_selection_model(self) -> None:
        """Connect selection changes for the current table model exactly once."""
        selection_model = self._table.selectionModel()
        if selection_model is None:
            self._table_selection_model = None
            return
        selection_model.selectionChanged.connect(self._on_table_selection_changed)
        self._table_selection_model = selection_model

    def _disconnect_table_selection_model(self) -> None:
        """Disconnect selection callback from the previously active model."""
        if self._table_selection_model is None:
            return
        try:
            self._table_selection_model.selectionChanged.disconnect(
                self._on_table_selection_changed
            )
        except (TypeError, RuntimeError):
            pass
        self._table_selection_model = None

    def _on_table_selection_changed(self, *_args) -> None:
        """Re-emit spool filtered to selected rows, or full spool if none."""
        self._persist_selected_row()
        self._schedule_emit()

    def _persist_selected_row(self) -> None:
        """Persist the currently selected source row for workflow round-tripping."""
        selected_source_rows = self._snapshot_selected_source_rows()
        if not selected_source_rows:
            self.selected_source_row = None
            self.selected_source_patch_name = ""
            return
        source_row = min(selected_source_rows)
        self.selected_source_row = source_row
        self.selected_source_patch_name = self._patch_name_for_source_row(source_row)

    def _restore_saved_row_selection(self, model: _SpoolContentsTableModel) -> None:
        """Restore the persisted source-row selection when it is still visible."""
        source_row = self._resolved_selected_source_row()
        if source_row is None:
            self._pending_restore_emit = False
            return
        try:
            view_row = model.view_row_for_source_row(int(source_row))
        except (IndexError, TypeError, ValueError):
            self.selected_source_row = None
            self.selected_source_patch_name = ""
            self._pending_restore_emit = False
            return
        selection_model = self._table.selectionModel()
        if selection_model is None:
            self.selected_source_row = None
            self.selected_source_patch_name = ""
            self._pending_restore_emit = False
            return
        selection_model.blockSignals(True)
        self._table.selectRow(view_row)
        self._table.scrollTo(model.index(view_row, 0))
        selection_model.blockSignals(False)
        if self._pending_restore_emit:
            self._pending_restore_emit = False
            QTimer.singleShot(0, self._schedule_emit)

    def _resolved_selected_source_row(self) -> int | None:
        """Return the persisted source row, remapped by patch name when possible."""
        patch_name = str(self.selected_source_patch_name or "").strip()
        if patch_name and self._source_spool is not None:
            source_row = self._source_row_for_patch_name(patch_name)
            if source_row is not None:
                self.selected_source_row = source_row
                return source_row
        if self.selected_source_row is None:
            return None
        try:
            return int(self.selected_source_row)
        except (TypeError, ValueError):
            return None

    def _patch_name_for_source_row(self, source_row: int) -> str:
        """Return a persisted row token for one source-spool row."""
        if self._source_spool is None:
            return ""
        try:
            df = self._ordered_contents_df(self._source_spool)
        except Exception:
            return ""
        try:
            return _contents_identity_token(df, source_row)
        except Exception:
            return ""

    def _source_row_for_patch_name(self, patch_name: str) -> int | None:
        """Return the current source-spool row for a persisted row token."""
        token = str(patch_name or "").strip()
        if self._source_spool is None or not token:
            return None
        try:
            df = self._ordered_contents_df(self._source_spool)
        except Exception:
            return None
        for index in range(len(df)):
            try:
                candidate = _contents_identity_token(df, index)
            except Exception:
                continue
            if candidate == token:
                return index
        return None

    @staticmethod
    def _ordered_contents_df(spool: dc.BaseSpool):
        """Return spool contents in the widget's deterministic default order."""
        ordered = _ordered_contents_df_with_source_rows(spool)
        return ordered.drop(columns="_source_row")

    def _initialize_active_source_selection(self) -> None:
        """Best-effort active-source registration for the first source widget."""
        from derzug.views import orange as orange_view

        app = QApplication.instance()
        manager = orange_view._APP_ACTIVE_SOURCE_MANAGER
        main_window = orange_view._APP_ACTIVE_SOURCE_MAIN_WINDOW
        if manager is None and app is not None:
            manager = getattr(app, "active_source_manager", None)
            main_window = getattr(app, "active_source_main_window", None)
        if (
            manager is not None
            and main_window is not None
            and manager._active_widget is None
        ):
            try:
                manager._set_active_widget(main_window, self)
            except Exception:
                pass
        self._ensure_active_source_selection()
        QTimer.singleShot(0, self._ensure_active_source_selection)

    def step_next_item(self) -> bool:
        """Advance row selection to the next patch, wrapping at the end."""
        return self._step_table_row(1)

    def step_previous_item(self) -> bool:
        """Move row selection to the previous patch, wrapping at the start."""
        return self._step_table_row(-1)

    def _step_table_row(self, delta: int) -> bool:
        """Move table row selection by ``delta`` and emit the corresponding spool."""
        model = self._table.model()
        if model is None:
            return False
        row_count = model.rowCount()
        if row_count <= 0:
            return False

        selected_rows = self._table.selectionModel().selectedRows()
        current_row = selected_rows[0].row() if selected_rows else -1
        if current_row < 0:
            target = 0 if delta >= 0 else row_count - 1
        else:
            target = (current_row + delta) % row_count

        self._table.selectRow(target)
        self._table.scrollTo(model.index(target, 0))
        return True


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Spool).run()
