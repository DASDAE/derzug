"""
Widget for converting DataFrame rows into an AnnotationSet.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from AnyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg
from pydantic import Field

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    PointGeometry,
    SpanGeometry,
)
from derzug.orange import Setting
from derzug.utils.annotation_metadata import LABEL_SLOTS, optional_text
from derzug.workflow import Task

_GEOM_DOT = 0
_GEOM_LINE = 1

_LABEL_MODE_FIXED = 0
_LABEL_MODE_COLUMN = 1

_NO_COLUMN = ""


def _parse_dims(text: str) -> tuple[str, ...]:
    """Split comma-separated dim text into a tuple of stripped non-empty names."""
    return tuple(d.strip() for d in text.split(",") if d.strip())


def _is_missing(value: Any) -> bool:
    """Return True when a cell value should be treated as missing."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _make_table_geometry(
    *,
    row: pd.Series,
    dims: tuple[str, ...],
    geometry_type: int,
    line_axis_dim: str,
    col_map: dict,
):
    """Return one geometry for a DataFrame row."""
    if geometry_type == _GEOM_DOT:
        coords = {}
        for dim in dims:
            col = col_map[dim]
            val = row[col]
            if _is_missing(val):
                raise ValueError(f"NaN in column '{col}'")
            coords[dim] = val
        return PointGeometry(coords=coords)

    dim = line_axis_dim
    col = col_map[dim]
    val = row[col]
    if _is_missing(val):
        raise ValueError(f"NaN in column '{col}'")
    return SpanGeometry(dim=dim, start=val, end=val)


def _table_notes(row: pd.Series, notes_col: str) -> str | None:
    """Return Annotation.notes from one configured column."""
    if not notes_col or notes_col not in row.index:
        return None
    val = row[notes_col]
    if _is_missing(val):
        return None
    return optional_text(val)


def _table_label(
    row: pd.Series,
    label_mode: int,
    label_col: str,
    fixed_label: str,
) -> str | None:
    """Return Annotation.label from fixed setting or per-row column."""
    if label_mode == _LABEL_MODE_COLUMN:
        if label_col and label_col in row.index:
            val = row[label_col]
            if not _is_missing(val):
                return optional_text(val)
        return None
    return optional_text(fixed_label)


def _table_tags(row: pd.Series, tags_col: str) -> tuple[str, ...]:
    """Return comma-separated tags from one row."""
    if not tags_col or tags_col not in row.index:
        return ()
    val = row[tags_col]
    if _is_missing(val):
        return ()
    return tuple(t.strip() for t in str(val).split(",") if t.strip())


class TableToAnnotationTask(Task):
    """Convert DataFrame rows into annotations."""

    geometry_type: int = _GEOM_DOT
    line_axis_dim: str = ""
    dims_text: str = ""
    col_map: dict = Field(default_factory=dict)
    semantic_type_text: str = "generic"
    notes_col: str = _NO_COLUMN
    label_mode: int = _LABEL_MODE_FIXED
    fixed_label: str = ""
    label_col: str = _NO_COLUMN
    tags_col: str = _NO_COLUMN
    input_variables: ClassVar[dict[str, object]] = {"data": object}
    output_variables: ClassVar[dict[str, object]] = {"annotation_set": object}

    def run(self, data):
        """Convert each DataFrame row into one annotation when valid."""
        dims = _parse_dims(self.dims_text)
        annotations = []
        for i, row in data.iterrows():
            try:
                geometry = _make_table_geometry(
                    row=row,
                    dims=dims,
                    geometry_type=self.geometry_type,
                    line_axis_dim=self.line_axis_dim,
                    col_map=self.col_map,
                )
            except (KeyError, TypeError, ValueError):
                continue
            annotations.append(
                Annotation(
                    id=f"t2a-{i}",
                    geometry=geometry,
                    semantic_type=self.semantic_type_text.strip() or "generic",
                    notes=_table_notes(row, self.notes_col),
                    label=_table_label(
                        row,
                        self.label_mode,
                        self.label_col,
                        self.fixed_label,
                    ),
                    tags=_table_tags(row, self.tags_col),
                )
            )
        return AnnotationSet(dims=dims, annotations=tuple(annotations))


class Table2Annotation(ZugWidget):
    """Orange widget that converts each DataFrame row into an Annotation."""

    name = "Table to Annotations"
    description = (
        "Convert rows of a DataFrame into an AnnotationSet. "
        "Each row becomes one annotation (dot or line)."
    )
    icon = "icons/DataFrame2Annotation.svg"
    category = "Table"
    keywords = ("annotation", "table", "dataframe", "convert", "label")
    priority = 25

    # --- settings ---
    geometry_type: int = Setting(_GEOM_DOT)  # 0=dot, 1=line
    line_axis_dim: str = Setting("")  # which dim the line is pinned to
    dims_text: str = Setting("")  # comma-separated dims
    col_map: dict = Setting({})  # {dim_name: col_name}
    semantic_type_text: str = Setting("generic")
    notes_col: str = Setting(_NO_COLUMN)
    label_mode: int = Setting(_LABEL_MODE_FIXED)  # 0=fixed, 1=column
    fixed_label: str = Setting("")
    label_col: str = Setting(_NO_COLUMN)
    tags_col: str = Setting(_NO_COLUMN)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        no_dims = Msg("No dimensions declared. Enter at least one dim name.")
        no_col_mapped = Msg("Dimension '{}' has no column selected.")
        line_axis_missing = Msg("No line axis dimension selected.")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

        rows_skipped = Msg("{} row(s) skipped due to missing or invalid values.")
        no_data = Msg("No input data.")

    class Inputs:
        """Widget input signals."""

        data = Input("Data", pd.DataFrame, auto_summary=False)

    class Outputs:
        """Widget output signals."""

        annotation_set = Output("Annotations", AnnotationSet)

    def __init__(self) -> None:
        super().__init__()
        self._df: pd.DataFrame | None = None
        # Parallel lists — one entry per active mapping row
        self._mapping_labels: list[QLabel] = []
        self._mapping_combos: list[QComboBox] = []

        # ── Geometry box ──────────────────────────────────────────
        geom_box = gui.widgetBox(self.controlArea, "Geometry")
        gui.radioButtons(
            geom_box,
            self,
            "geometry_type",
            btnLabels=["Dot", "Line"],
            orientation=gui.Qt.Horizontal,
            callback=self._on_geometry_changed,
        )
        # Line axis row (shown only in line mode)
        self._line_axis_row = QWidget(geom_box)
        line_axis_layout = QHBoxLayout(self._line_axis_row)
        line_axis_layout.setContentsMargins(0, 4, 0, 0)
        line_axis_layout.setSpacing(4)
        line_axis_layout.addWidget(QLabel("Line axis:", self._line_axis_row))
        self._line_axis_combo = QComboBox(self._line_axis_row)
        self._line_axis_combo.currentTextChanged.connect(self._on_line_axis_changed)
        line_axis_layout.addWidget(self._line_axis_combo, 1)
        geom_box.layout().addWidget(self._line_axis_row)

        # ── Dimensions box ────────────────────────────────────────
        dims_box = gui.widgetBox(self.controlArea, "Dimensions")
        self._dims_edit = gui.lineEdit(
            dims_box,
            self,
            "dims_text",
            label="Dims (comma-separated):",
            orientation=gui.Qt.Horizontal,
            callback=self._on_dims_changed,
        )

        # ── Column mapping box ────────────────────────────────────
        self._mapping_box = gui.widgetBox(self.controlArea, "Column Mapping")
        self._mapping_container = QWidget(self._mapping_box)
        self._mapping_container.setLayout(QVBoxLayout())
        self._mapping_container.layout().setContentsMargins(0, 0, 0, 0)
        self._mapping_container.layout().setSpacing(2)
        self._mapping_box.layout().addWidget(self._mapping_container)

        # ── Annotation fields box ─────────────────────────────────
        fields_box = gui.widgetBox(self.controlArea, "Annotation Fields")

        gui.lineEdit(
            fields_box,
            self,
            "semantic_type_text",
            label="Semantic type:",
            orientation=gui.Qt.Horizontal,
            callback=self.run,
        )

        # Notes column
        notes_col_row = QWidget(fields_box)
        notes_col_layout = QHBoxLayout(notes_col_row)
        notes_col_layout.setContentsMargins(0, 0, 0, 0)
        notes_col_layout.setSpacing(4)
        notes_col_layout.addWidget(QLabel("Notes column:", notes_col_row))
        self._notes_col_combo = QComboBox(notes_col_row)
        self._notes_col_combo.currentTextChanged.connect(self._on_notes_col_changed)
        notes_col_layout.addWidget(self._notes_col_combo, 1)
        fields_box.layout().addWidget(notes_col_row)

        # Label
        gui.radioButtons(
            fields_box,
            self,
            "label_mode",
            btnLabels=["Fixed label:", "Label column:"],
            orientation=gui.Qt.Horizontal,
            callback=self._on_label_mode_changed,
        )
        label_row = QWidget(fields_box)
        label_row_layout = QHBoxLayout(label_row)
        label_row_layout.setContentsMargins(0, 0, 0, 0)
        label_row_layout.setSpacing(4)
        self._fixed_label_combo = QComboBox(label_row)
        self._fixed_label_combo.addItems(["(none)", *LABEL_SLOTS])
        if self.fixed_label in LABEL_SLOTS:
            self._fixed_label_combo.setCurrentText(self.fixed_label)
        self._fixed_label_combo.currentTextChanged.connect(self._on_fixed_label_changed)
        self._label_col_combo = QComboBox(label_row)
        self._label_col_combo.currentTextChanged.connect(self._on_label_col_changed)
        label_row_layout.addWidget(self._fixed_label_combo, 1)
        label_row_layout.addWidget(self._label_col_combo, 1)
        fields_box.layout().addWidget(label_row)

        # Tags column
        tags_col_row = QWidget(fields_box)
        tags_col_layout = QHBoxLayout(tags_col_row)
        tags_col_layout.setContentsMargins(0, 0, 0, 0)
        tags_col_layout.setSpacing(4)
        tags_col_layout.addWidget(QLabel("Tags column:", tags_col_row))
        self._tags_col_combo = QComboBox(tags_col_row)
        self._tags_col_combo.currentTextChanged.connect(self._on_tags_col_changed)
        tags_col_layout.addWidget(self._tags_col_combo, 1)
        fields_box.layout().addWidget(tags_col_row)

        # ── Status ────────────────────────────────────────────────
        self._status_label = gui.widgetLabel(self.controlArea, "")

        # Restore persisted state
        self._rebuild_mapping_rows()
        self._update_line_axis_visibility()
        self._update_label_controls()

    # ── Input handler ─────────────────────────────────────────────

    @Inputs.data
    def set_data(self, df: pd.DataFrame | None) -> None:
        """Receive a new DataFrame and rebuild column dropdowns."""
        self._df = df
        self._update_column_combos()
        self.run()

    def _supports_async_execution(self) -> bool:
        """Run table conversion off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one table-to-annotation execution request."""
        validated = self._validated_task()
        if validated is None:
            return None
        task, df = validated
        return self._build_task_execution_request(
            task,
            input_values={"data": df},
            output_names=("annotation_set",),
        )

    # ── ZugWidget lifecycle ───────────────────────────────────────

    def _run(self) -> AnnotationSet | None:
        """Build and return an AnnotationSet from the current DataFrame."""
        validated = self._validated_task()
        if validated is None:
            return None
        task, df = validated
        return self._execute_workflow_object(
            task,
            input_values={"data": df},
            output_names=("annotation_set",),
        )

    def get_task(self) -> Task:
        """Return the configured table-to-annotation task."""
        return TableToAnnotationTask(
            geometry_type=self.geometry_type,
            line_axis_dim=self.line_axis_dim,
            dims_text=self.dims_text,
            col_map=self.col_map,
            semantic_type_text=self.semantic_type_text,
            notes_col=self.notes_col,
            label_mode=self.label_mode,
            fixed_label=self.fixed_label,
            label_col=self.label_col,
            tags_col=self.tags_col,
        )

    def _validated_task(self) -> tuple[TableToAnnotationTask, pd.DataFrame] | None:
        """Return the current validated task and dataframe, or None on UI error."""
        df = self._df
        if df is None or df.empty:
            self.Warning.no_data()
            return None
        dims = _parse_dims(self.dims_text)
        if not dims:
            self.Error.no_dims()
            return None
        active_dims = self._active_dims(dims)
        for dim in active_dims:
            col = self.col_map.get(dim, _NO_COLUMN)
            if not col or col not in df.columns:
                self.Error.no_col_mapped(dim)
                return None
        if self.geometry_type == _GEOM_LINE and not self.line_axis_dim:
            self.Error.line_axis_missing()
            return None
        skipped = 0
        for _, row in df.iterrows():
            try:
                self._make_geometry(row, dims)
            except (KeyError, TypeError, ValueError):
                skipped += 1
        if skipped:
            self.Warning.rows_skipped(skipped)
        return self.get_task(), df

    def _on_result(self, result: AnnotationSet | None) -> None:
        """Emit the result and update the status label."""
        self.Outputs.annotation_set.send(result)
        if result is None:
            self._status_label.setText("")
        else:
            n = len(result.annotations)
            self._status_label.setText(f"{n:,} annotation{'s' if n != 1 else ''}")

    # ── Geometry helpers ──────────────────────────────────────────

    def _make_geometry(self, row: pd.Series, dims: tuple[str, ...]):
        """Return a PointGeometry or SpanGeometry for one DataFrame row."""
        return _make_table_geometry(
            row=row,
            dims=dims,
            geometry_type=self.geometry_type,
            line_axis_dim=self.line_axis_dim,
            col_map=self.col_map,
        )

    def _get_notes(self, row: pd.Series) -> str | None:
        """Return Annotation.notes from the configured column, or None."""
        return _table_notes(row, self.notes_col)

    def _get_label(self, row: pd.Series) -> str | None:
        """Return Annotation.label from fixed setting or per-row column."""
        return _table_label(row, self.label_mode, self.label_col, self.fixed_label)

    def _get_tags(self, row: pd.Series) -> tuple[str, ...]:
        """Return Annotation.tags split from a comma-separated column value."""
        return _table_tags(row, self.tags_col)

    # ── Active dim logic ──────────────────────────────────────────

    def _active_dims(self, dims: tuple[str, ...]) -> tuple[str, ...]:
        """Return only the dims that need a column mapping for the current mode."""
        if self.geometry_type == _GEOM_LINE:
            return (self.line_axis_dim,) if self.line_axis_dim in dims else ()
        return dims

    # ── UI rebuild ────────────────────────────────────────────────

    def _rebuild_mapping_rows(self) -> None:
        """Rebuild the dim → column mapping rows to match the current dims and mode."""
        dims = _parse_dims(self.dims_text)
        active = self._active_dims(dims)

        # Resize the row list (add or remove rows)
        target = len(active)
        while len(self._mapping_labels) < target:
            label = QLabel(self._mapping_container)
            combo = QComboBox(self._mapping_container)
            combo.currentTextChanged.connect(self._on_mapping_combo_changed)
            row_widget = QWidget(self._mapping_container)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(label)
            row_layout.addWidget(combo, 1)
            self._mapping_container.layout().addWidget(row_widget)
            self._mapping_labels.append(label)
            self._mapping_combos.append(combo)

        while len(self._mapping_labels) > target:
            label = self._mapping_labels.pop()
            combo = self._mapping_combos.pop()
            # Remove the row_widget (combo's parent)
            row_widget = combo.parentWidget()
            self._mapping_container.layout().removeWidget(row_widget)
            row_widget.deleteLater()

        # Populate labels and column choices
        cols = [""] + (list(self._df.columns) if self._df is not None else [])
        for i, dim in enumerate(active):
            self._mapping_labels[i].setText(f"{dim}:")
            combo = self._mapping_combos[i]
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(cols)
            saved = self.col_map.get(dim, _NO_COLUMN)
            if saved in cols:
                combo.setCurrentText(saved)
            combo.blockSignals(False)

        # Update line axis combo choices
        self._line_axis_combo.blockSignals(True)
        self._line_axis_combo.clear()
        self._line_axis_combo.addItems(list(dims))
        if self.line_axis_dim in dims:
            self._line_axis_combo.setCurrentText(self.line_axis_dim)
        elif dims:
            self.line_axis_dim = dims[0]
            self._line_axis_combo.setCurrentIndex(0)
        self._line_axis_combo.blockSignals(False)

    def _update_column_combos(self) -> None:
        """Refresh all column-picking dropdowns after a new DataFrame arrives."""
        cols = [""] + (list(self._df.columns) if self._df is not None else [])

        # Mapping rows
        dims = _parse_dims(self.dims_text)
        active = self._active_dims(dims)
        for i, dim in enumerate(active):
            if i >= len(self._mapping_combos):
                break
            combo = self._mapping_combos[i]
            saved = self.col_map.get(dim, _NO_COLUMN)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(cols)
            if saved in cols:
                combo.setCurrentText(saved)
            combo.blockSignals(False)

        # Auxiliary combos
        for combo, attr in [
            (self._notes_col_combo, "notes_col"),
            (self._label_col_combo, "label_col"),
            (self._tags_col_combo, "tags_col"),
        ]:
            saved = getattr(self, attr)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(cols)
            if saved in cols:
                combo.setCurrentText(saved)
            combo.blockSignals(False)

    def _update_line_axis_visibility(self) -> None:
        """Show the line-axis row only in line mode."""
        self._line_axis_row.setVisible(self.geometry_type == _GEOM_LINE)

    def _update_label_controls(self) -> None:
        """Enable the appropriate label sub-control for the current mode."""
        fixed = self.label_mode == _LABEL_MODE_FIXED
        self._fixed_label_combo.setEnabled(fixed)
        self._label_col_combo.setEnabled(not fixed)

    # ── Callbacks ─────────────────────────────────────────────────

    def _on_geometry_changed(self) -> None:
        self._update_line_axis_visibility()
        self._rebuild_mapping_rows()
        self.run()

    def _on_dims_changed(self) -> None:
        self._rebuild_mapping_rows()
        self.run()

    def _on_line_axis_changed(self, text: str) -> None:
        self.line_axis_dim = text
        self._rebuild_mapping_rows()
        self.run()

    def _on_mapping_combo_changed(self) -> None:
        """Sync col_map from the current mapping combo selections."""
        dims = _parse_dims(self.dims_text)
        active = self._active_dims(dims)
        updated = dict(self.col_map)
        for i, dim in enumerate(active):
            if i < len(self._mapping_combos):
                updated[dim] = self._mapping_combos[i].currentText()
        self.col_map = updated
        self.run()

    def _on_notes_col_changed(self, text: str) -> None:
        self.notes_col = text
        self.run()

    def _on_label_mode_changed(self) -> None:
        self._update_label_controls()
        self.run()

    def _on_fixed_label_changed(self, text: str) -> None:
        self.fixed_label = "" if text == "(none)" else text
        self.run()

    def _on_label_col_changed(self, text: str) -> None:
        self.label_col = text
        self.run()

    def _on_tags_col_changed(self, text: str) -> None:
        self.tags_col = text
        self.run()


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Table2Annotation).run()
