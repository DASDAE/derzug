"""
Widget for loading a pandas DataFrame from a file on disk.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from AnyQt.QtCore import QAbstractTableModel, QModelIndex, Qt
from AnyQt.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.concurrent import ConcurrentWidgetMixin, TaskState
from Orange.widgets.utils.signals import Output
from Orange.widgets.utils.tableview import TableView
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.orange import Setting

# Display name → (reader callable, accepted extensions)
_FORMATS: dict[str, tuple[object, tuple[str, ...]]] = {
    "CSV": (pd.read_csv, (".csv", ".tsv", ".txt")),
    "Excel": (pd.read_excel, (".xlsx", ".xls", ".xlsm", ".xlsb", ".ods")),
    "Feather": (pd.read_feather, (".feather",)),
    "HDF5": (pd.read_hdf, (".h5", ".hdf5", ".hdf")),
    "JSON": (pd.read_json, (".json",)),
    "ORC": (pd.read_orc, (".orc",)),
    "Parquet": (pd.read_parquet, (".parquet", ".pq")),
    "Pickle": (pd.read_pickle, (".pkl", ".pickle")),
    "SPSS": (pd.read_spss, (".sav", ".zsav")),
    "Stata": (pd.read_stata, (".dta",)),
}

_AUTO = "Auto"
_FORMAT_NAMES = [_AUTO, *sorted(_FORMATS)]

# Extension → format name, for auto-detection
_EXT_TO_FORMAT: dict[str, str] = {
    ext: name for name, (_, exts) in _FORMATS.items() for ext in exts
}

# File picker filter string
_ALL_EXTENSIONS = " ".join(
    f"*{ext}" for _, (_, exts) in _FORMATS.items() for ext in exts
)
_FILE_FILTER = f"Tabular files ({_ALL_EXTENSIONS});;All files (*)"

# Cap the preview at this many rows to keep the table responsive
_MAX_PREVIEW_ROWS = 10_000


def _detect_format(path: str) -> str | None:
    """Return the format name matching the file extension, or None."""
    return _EXT_TO_FORMAT.get(Path(path).suffix.lower())


def _load_dataframe(path: str, format_name: str, state: TaskState) -> pd.DataFrame:
    """Load a DataFrame from disk; auto-detect format when format_name is 'Auto'."""
    state.set_progress_value(10)
    if format_name == _AUTO:
        detected = _detect_format(path)
        if detected is None:
            suffix = Path(path).suffix or "(no extension)"
            raise ValueError(
                f"Cannot auto-detect format for '{suffix}'. "
                "Select a format explicitly from the dropdown."
            )
        format_name = detected
    reader, _ = _FORMATS[format_name]
    state.set_progress_value(30)
    df = reader(path)
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Reader returned {type(df).__name__}, expected DataFrame.")
    state.set_progress_value(100)
    return df


class _DataFrameModel(QAbstractTableModel):
    """Minimal Qt item model backed by a pandas DataFrame."""

    def __init__(self, df: pd.DataFrame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Cap preview rows; the full DataFrame is still emitted on the output signal
        self._df = df.iloc[:_MAX_PREVIEW_ROWS].reset_index(drop=True)
        self._truncated = len(df) > _MAX_PREVIEW_ROWS

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of display rows."""
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of columns."""
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        """Return cell data for display and alignment roles."""
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._df) or col < 0 or col >= len(self._df.columns):
            return None
        value = self._df.iat[row, col]
        if role == Qt.DisplayRole:
            return _format_cell(value)
        if role == Qt.TextAlignmentRole:
            return int(_cell_alignment(value))
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ):
        """Return column names as horizontal headers; row numbers vertically."""
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._df.columns):
                return str(self._df.columns[section])
            return None
        # Vertical header: original row number
        return str(section)

    @property
    def truncated(self) -> bool:
        """True when the source DataFrame exceeded the preview row cap."""
        return self._truncated


def _format_cell(value) -> str:
    """Return a readable string for one DataFrame cell value."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, float):
        # Use up to 6 significant figures, strip trailing zeros
        return f"{value:.6g}"
    return str(value)


def _cell_alignment(value) -> Qt.AlignmentFlag:
    """Return a sensible alignment for one DataFrame cell value."""
    if isinstance(value, int | float | np.integer | np.floating):
        return Qt.AlignRight | Qt.AlignVCenter
    return Qt.AlignLeft | Qt.AlignVCenter


class DataFrameLoader(ConcurrentWidgetMixin, ZugWidget):
    """Orange widget for loading a pandas DataFrame from a file on disk."""

    name = "DataFrame Loader"
    want_control_area = False
    description = (
        "Load a tabular DataFrame from a file. "
        "Format is auto-detected from the file extension or can be set manually."
    )
    icon = "icons/File.svg"
    category = "IO"
    keywords = ("dataframe", "csv", "parquet", "excel", "table", "file", "load")
    priority = 20
    is_source = True

    file_path = Setting("")
    format_name = Setting(_AUTO)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        load_failed = Msg("Could not load file: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        no_file = Msg("No file selected.")
        preview_truncated = Msg(
            f"Preview limited to {_MAX_PREVIEW_ROWS:,} rows. "
            "Full DataFrame is sent on the output."
        )

    class Outputs:
        """Widget output signals."""

        data = Output("Data", pd.DataFrame, auto_summary=False)

    def __init__(self) -> None:
        ZugWidget.__init__(self)
        ConcurrentWidgetMixin.__init__(self)
        self._df: pd.DataFrame | None = None

        content = QWidget(self.mainArea)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        self.mainArea.layout().addWidget(content)

        self._table = TableView(content)
        self._table.setSortingEnabled(False)
        self._table.setSelectionBehavior(TableView.SelectRows)
        self._table.setSelectionMode(TableView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setDefaultSectionSize(120)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._table.setStyleSheet(
            "QTableView { alternate-background-color: rgba(0,0,0,0.035); }"
            "QHeaderView::section { padding: 4px 6px; font-weight: 600; }"
        )
        content_layout.addWidget(self._table, 1)

        self._controls_panel = QWidget(content)
        controls_layout = QVBoxLayout(self._controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)
        content_layout.addWidget(self._controls_panel, 0)

        box = gui.widgetBox(self._controls_panel, "File")
        controls_layout.addWidget(box)

        # File path row: read-only text field + Open button
        file_row = QWidget(box)
        file_row_layout = QHBoxLayout(file_row)
        file_row_layout.setContentsMargins(0, 0, 0, 0)
        file_row_layout.setSpacing(4)
        self.file_path_edit = QLineEdit(file_row)
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("No file selected")
        self.open_button = QPushButton("Open...", file_row)
        file_row_layout.addWidget(self.file_path_edit, 1)
        file_row_layout.addWidget(self.open_button)
        box.layout().addWidget(file_row)

        # Format row: label + combo
        format_row = QWidget(box)
        format_row_layout = QHBoxLayout(format_row)
        format_row_layout.setContentsMargins(0, 0, 0, 0)
        format_row_layout.setSpacing(4)
        format_row_layout.addWidget(QLabel("Format:", format_row))
        self.format_combo = QComboBox(format_row)
        self.format_combo.addItems(_FORMAT_NAMES)
        if self.format_name in _FORMAT_NAMES:
            self.format_combo.setCurrentText(self.format_name)
        format_row_layout.addWidget(self.format_combo, 1)
        box.layout().addWidget(format_row)

        # Shape / detected-format info
        self._info_label = gui.widgetLabel(self._controls_panel, "")
        controls_layout.addWidget(self._info_label)

        self.open_button.clicked.connect(self._on_open_clicked)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)

        # Restore persisted state
        if self.file_path:
            self.file_path_edit.setText(self.file_path)
            self._load()

    def _on_open_clicked(self) -> None:
        """Open a file picker and start loading the selected file."""
        start_dir = ""
        if self.file_path:
            existing = Path(self.file_path)
            start_dir = str(existing.parent if existing.exists() else "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DataFrame File", start_dir, _FILE_FILTER
        )
        if not path:
            return
        self.file_path = path
        self.file_path_edit.setText(path)
        self._load()

    def _on_format_changed(self, text: str) -> None:
        """Re-load when the user picks a different format."""
        self.format_name = text
        if self.file_path:
            self._load()

    def _load(self) -> None:
        """Cancel any running task and start a fresh background load."""
        self.Error.clear()
        self.Warning.clear()
        self._info_label.setText("")
        if not self.file_path:
            self.Warning.no_file()
            self._set_output(None)
            return
        self.cancel()
        self.start(_load_dataframe, self.file_path, self.format_name)

    def on_done(self, result: pd.DataFrame) -> None:
        """Receive the loaded DataFrame from the worker thread."""
        self._set_output(result)

    def on_exception(self, ex: Exception) -> None:
        """Show a load error and clear the output."""
        self.Error.load_failed(str(ex))
        self._set_output(None)

    def onDeleteWidget(self) -> None:
        """Shut down the background thread pool on widget close."""
        self.shutdown()
        super().onDeleteWidget()

    def _set_output(self, df: pd.DataFrame | None) -> None:
        """Store, render, and emit the DataFrame."""
        self._df = df
        self._render_table(df)
        self._update_info(df)
        self.Outputs.data.send(df)

    def _render_table(self, df: pd.DataFrame | None) -> None:
        """Populate the table view with the loaded DataFrame."""
        if df is None:
            self._table.setModel(None)
            return
        model = _DataFrameModel(df, self._table)
        self._table.setModel(model)
        if model.truncated:
            self.Warning.preview_truncated()

    def _update_info(self, df: pd.DataFrame | None) -> None:
        """Show shape and detected format below the controls."""
        if df is None:
            self._info_label.setText("")
            return
        detected = _detect_format(self.file_path) if self.format_name == _AUTO else None
        fmt_tag = f" \u2014 {detected} detected" if detected else ""
        self._info_label.setText(
            f"{len(df):,} rows \u00d7 {len(df.columns):,} columns{fmt_tag}"
        )


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(DataFrameLoader).run()
