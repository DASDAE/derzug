"""The Table2Annotation node: one DataFrame row becomes one annotation."""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel, Field

from derzug.models.annotations import (
    Annotation,
    AnnotationSet,
    PointGeometry,
    SpanGeometry,
)
from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.annotation_metadata import LABEL_SLOTS, optional_text
from derzug.workflow.task import Task

GEOM_DOT = 0
GEOM_LINE = 1

LABEL_MODE_FIXED = 0
LABEL_MODE_COLUMN = 1

NO_COLUMN = ""


def parse_dims(text: str) -> tuple[str, ...]:
    """Split comma-separated dim text into a tuple of stripped non-empty names."""
    return tuple(d.strip() for d in text.split(",") if d.strip())


def is_missing(value: Any) -> bool:
    """Return True when a cell value should be treated as missing."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def make_table_geometry(
    *,
    row: tuple[Any, ...],
    column_positions: dict[str, int],
    dims: tuple[str, ...],
    geometry_type: int,
    line_axis_dim: str,
    col_map: dict,
):
    """Return one geometry for a DataFrame row."""
    if geometry_type == GEOM_DOT:
        coords = {}
        for dim in dims:
            col = col_map[dim]
            val = row[column_positions[col]]
            if is_missing(val):
                raise ValueError(f"NaN in column '{col}'")
            coords[dim] = val
        return PointGeometry(coords=coords)

    dim = line_axis_dim
    col = col_map[dim]
    val = row[column_positions[col]]
    if is_missing(val):
        raise ValueError(f"NaN in column '{col}'")
    return SpanGeometry(dim=dim, start=val, end=val)


def table_notes(
    row: tuple[Any, ...],
    column_positions: dict[str, int],
    notes_col: str,
) -> str | None:
    """Return Annotation.notes from one configured column."""
    if not notes_col or notes_col not in column_positions:
        return None
    val = row[column_positions[notes_col]]
    if is_missing(val):
        return None
    return optional_text(val)


def table_label(
    row: tuple[Any, ...],
    column_positions: dict[str, int],
    label_mode: int,
    label_col: str,
    fixed_label: str,
) -> str | None:
    """Return Annotation.label from fixed setting or per-row column."""
    if label_mode == LABEL_MODE_COLUMN:
        if label_col and label_col in column_positions:
            val = row[column_positions[label_col]]
            if not is_missing(val):
                return optional_text(val)
        return None
    return optional_text(fixed_label)


def table_tags(
    row: tuple[Any, ...],
    column_positions: dict[str, int],
    tags_col: str,
) -> tuple[str, ...]:
    """Return comma-separated tags from one row."""
    if not tags_col or tags_col not in column_positions:
        return ()
    val = row[column_positions[tags_col]]
    if is_missing(val):
        return ()
    return tuple(t.strip() for t in str(val).split(",") if t.strip())


class TableToAnnotationTask(Task):
    """Convert DataFrame rows into annotations."""

    geometry_type: int = GEOM_DOT
    line_axis_dim: str = ""
    dims_text: str = ""
    col_map: dict = Field(default_factory=dict)
    semantic_type_text: str = "generic"
    notes_col: str = NO_COLUMN
    label_mode: int = LABEL_MODE_FIXED
    fixed_label: str = ""
    label_col: str = NO_COLUMN
    tags_col: str = NO_COLUMN
    input_variables: ClassVar[dict[str, object]] = {"data": object}
    output_variables: ClassVar[dict[str, object]] = {"annotation_set": object}

    def run(self, data):
        """Convert each DataFrame row into one annotation when valid."""
        dims = parse_dims(self.dims_text)
        annotations = []
        column_positions = {
            str(column): position for position, column in enumerate(data.columns)
        }
        rows = data.itertuples(index=False, name=None)
        for i, row in zip(data.index, rows, strict=True):
            try:
                geometry = make_table_geometry(
                    row=row,
                    column_positions=column_positions,
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
                    notes=table_notes(row, column_positions, self.notes_col),
                    label=table_label(
                        row,
                        column_positions,
                        self.label_mode,
                        self.label_col,
                        self.fixed_label,
                    ),
                    tags=table_tags(row, column_positions, self.tags_col),
                )
            )
        return AnnotationSet(dims=dims, annotations=tuple(annotations))


class Table2AnnotationParams(BaseModel):
    """Parameters for the Table to Annotations widget."""

    geometry_type: int = 0
    line_axis_dim: str = ""
    dims_text: str = ""
    col_map: dict = Field(default_factory=dict)
    semantic_type_text: str = "generic"
    notes_col: str = ""
    label_mode: int = 0
    fixed_label: str = ""
    label_col: str = ""
    tags_col: str = ""


def table2annotation_task_from_params(
    params: Table2AnnotationParams | None = None,
) -> TableToAnnotationTask:
    """Build the configured table-to-annotation task."""
    params = Table2AnnotationParams() if params is None else params
    return TableToAnnotationTask(
        geometry_type=params.geometry_type,
        line_axis_dim=params.line_axis_dim,
        dims_text=params.dims_text,
        col_map=params.col_map,
        semantic_type_text=params.semantic_type_text,
        notes_col=params.notes_col,
        label_mode=params.label_mode,
        fixed_label=params.fixed_label,
        label_col=params.label_col,
        tags_col=params.tags_col,
    )


NODE_SPEC = NodeSpec(
    name="Table to Annotations",
    widget_qualified_name="derzug.widgets.table2annotation.Table2Annotation",
    inputs=(PortSpec(name="data", display_name="Data", type=pd.DataFrame),),
    outputs=(
        PortSpec(
            name="annotation_set", display_name="Annotations", type=AnnotationSet
        ),
    ),
    params_model=Table2AnnotationParams,
    task_factory=table2annotation_task_from_params,
    category="Table",
    description=(
        "Convert rows of a DataFrame into an AnnotationSet. "
        "Each row becomes one annotation (dot or line)."
    ),
    keywords=("annotation", "table", "dataframe", "convert", "label"),
    icon="icons/DataFrame2Annotation.svg",
    priority=25,
)
