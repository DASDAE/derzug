"""
Widget for converting an AnnotationSet into a tidy pandas DataFrame.
"""

from __future__ import annotations

import json

import pandas as pd
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.models.annotations import AnnotationSet
from derzug.orange import Setting


class Annotation2DataFrame(ZugWidget):
    """Orange widget that extracts point annotations into a DataFrame."""

    name = "Annotations to DataFrame"
    description = "Extract point annotations from an AnnotationSet into a DataFrame."
    icon = "icons/File.svg"
    category = "IO"
    keywords = ("annotation", "table", "dataframe", "convert", "point")
    priority = 26

    include_properties: bool = Setting(False)

    class Warning(ZugWidget.Warning):
        """Warnings shown by this widget."""

        no_data = Msg("No annotation set connected.")
        non_point_skipped = Msg("{} non-point annotation(s) excluded.")

    class Inputs:
        """Widget input signals."""

        annotation_set = Input("Annotations", AnnotationSet, auto_summary=False)

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

    def _run(self) -> pd.DataFrame | None:
        ann_set = self._ann_set
        if ann_set is None:
            self.Warning.no_data()
            return None

        set_dims = ann_set.dims
        rows = []
        skipped = 0
        for ann in ann_set.annotations:
            if ann.geometry.type != "point":
                skipped += 1
                continue
            geom = ann.geometry
            dim_vals = {d: None for d in set_dims}
            for d, v in zip(geom.dims, geom.values):
                if d in dim_vals:
                    dim_vals[d] = v
            row = {
                **dim_vals,
                "id": ann.id,
                "semantic_type": ann.semantic_type,
                "text": ann.text,
                "group": ann.group,
                "tags": ", ".join(ann.tags),
            }
            if self.include_properties:
                row["properties"] = json.dumps(ann.properties)
            rows.append(row)

        if skipped:
            self.Warning.non_point_skipped(skipped)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _on_result(self, result: pd.DataFrame | None) -> None:
        self.Outputs.data.send(result)
        if result is None or result.empty:
            self._status_label.setText("")
        else:
            self._status_label.setText(f"{len(result):,} point annotation(s)")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Annotation2DataFrame).run()
