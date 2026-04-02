"""
Widget for converting an AnnotationSet into a tidy pandas DataFrame.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pandas as pd
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.models.annotations import AnnotationSet, PointGeometry
from derzug.orange import Setting
from derzug.utils.annotation_metadata import annotation_metadata_row
from derzug.workflow import Task


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


class Annotation2DataFrame(ZugWidget):
    """Orange widget that extracts point annotations into a DataFrame."""

    name = "Annotations to DataFrame"
    description = "Extract point annotations from an AnnotationSet into a DataFrame."
    icon = "icons/Annotation2DataFrame.svg"
    category = "Table"
    keywords = ("annotation", "table", "dataframe", "convert", "point")
    priority = 26

    include_properties: bool = Setting(False)

    class Warning(ZugWidget.Warning):
        """Warnings shown by this widget."""

        no_data = Msg("No annotation set connected.")
        non_point_skipped = Msg("{} non-point annotation(s) excluded.")

    class Inputs:
        """Widget input signals."""

        annotation_set = Input("Annotations", AnnotationSet)

    class Outputs:
        """Widget output signals."""

        data = Output("Data", pd.DataFrame, auto_summary=False)

    def __init__(self) -> None:
        super().__init__()
        self._ann_set: AnnotationSet | None = None

        output_box = gui.widgetBox(self.controlArea, "Output")
        gui.checkBox(
            output_box,
            self,
            "include_properties",
            "Include properties column",
            callback=self.run,
        )

        self._status_label = gui.widgetLabel(self.controlArea, "")

    @Inputs.annotation_set
    def set_annotation_set(self, ann_set: AnnotationSet | None) -> None:
        """Receive a new AnnotationSet and trigger processing."""
        self._ann_set = ann_set
        self.run()

    def _supports_async_execution(self) -> bool:
        """Run annotation conversion off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one annotation-to-dataframe execution request."""
        ann_set = self._ann_set
        workflow_obj = self._validated_task()
        if ann_set is None:
            return None
        return self._build_task_execution_request(
            workflow_obj,
            input_values={"annotation_set": ann_set},
            output_names=("data",),
        )

    def _validated_task(self) -> Task | None:
        """Return the conversion task after surfacing widget-side warnings."""
        ann_set = self._ann_set
        if ann_set is None:
            self.Warning.no_data()
            return None
        skipped = sum(1 for ann in ann_set.annotations if ann.geometry.type != "point")
        if skipped:
            self.Warning.non_point_skipped(skipped)
        return AnnotationSetToDataFrameTask(include_properties=self.include_properties)

    def _run(self) -> pd.DataFrame | None:
        ann_set = self._ann_set
        workflow_obj = self._validated_task()
        if ann_set is None:
            return None
        return self._execute_workflow_object(
            workflow_obj,
            input_values={"annotation_set": ann_set},
            output_names=("data",),
        )

    def get_task(self) -> Task:
        """Return the configured annotation conversion task."""
        return AnnotationSetToDataFrameTask(include_properties=self.include_properties)

    def _on_result(self, result: pd.DataFrame | None) -> None:
        self.Outputs.data.send(result)
        if result is None or result.empty:
            self._status_label.setText("")
        else:
            self._status_label.setText(f"{len(result):,} point annotation(s)")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Annotation2DataFrame).run()
