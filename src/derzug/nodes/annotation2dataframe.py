"""The Annotation2DataFrame node: point annotations as tidy table rows."""

from __future__ import annotations

import json
from typing import ClassVar

import pandas as pd
from pydantic import BaseModel

from derzug.models.annotations import AnnotationSet, PointGeometry
from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.annotation_metadata import annotation_metadata_row
from derzug.workflow.task import Task


class AnnotationSetToDataFrameTask(Task):
    """Convert point annotations into a tidy DataFrame."""

    include_properties: bool = False
    input_variables: ClassVar[dict[str, object]] = {"annotation_set": object}
    output_variables: ClassVar[dict[str, object]] = {"data": object}

    def run(self, annotation_set):
        """Convert point annotations from one set into rows."""
        set_dims = annotation_set.dims
        rows = []
        for ann in annotation_set.annotations:
            if ann.geometry.type != "point":
                continue
            geom = ann.geometry
            if not isinstance(geom, PointGeometry):
                continue
            dim_vals = {d: None for d in set_dims}
            for dim, value in geom.coords.items():
                if dim in dim_vals:
                    dim_vals[dim] = value
            row = {
                **dim_vals,
                "id": ann.id,
                **annotation_metadata_row(ann),
            }
            if self.include_properties:
                row["properties"] = json.dumps(ann.properties)
            rows.append(row)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)


class Annotation2DataFrameParams(BaseModel):
    """Parameters for the Annotations to DataFrame node."""

    include_properties: bool = False


def annotation2dataframe_task_from_params(
    params: Annotation2DataFrameParams | None = None,
) -> AnnotationSetToDataFrameTask:
    """Build the configured annotation-to-table task."""
    params = Annotation2DataFrameParams() if params is None else params
    return AnnotationSetToDataFrameTask(include_properties=params.include_properties)


NODE_SPEC = NodeSpec(
    name="Annotations to DataFrame",
    widget_qualified_name=(
        "derzug.widgets.annotation2dataframe.Annotation2DataFrame"
    ),
    inputs=(
        PortSpec(
            name="annotation_set", display_name="Annotations", type=AnnotationSet
        ),
    ),
    outputs=(PortSpec(name="data", display_name="Data", type=pd.DataFrame),),
    params_model=Annotation2DataFrameParams,
    task_factory=annotation2dataframe_task_from_params,
    category="Table",
    description=(
        "Extract point annotations from an AnnotationSet into a DataFrame."
    ),
    keywords=("annotation", "table", "dataframe", "convert", "point"),
    icon="icons/Annotation2DataFrame.svg",
    priority=26,
)
