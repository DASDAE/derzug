"""The Waterfall node: an interactive view that also exports its selection.

Waterfall's compiled contribution is the selection the user dragged out on the
image — everything about how the image is *coloured* is view state and stays in
the widget. The annotation ports are widget-local context for the same reason:
annotations ride alongside the plot rather than through the graph.
"""

from __future__ import annotations

from typing import Any

import dascore as dc
from pydantic import BaseModel, Field

from derzug.models.annotations import AnnotationSet
from derzug.models.selection import SelectParams
from derzug.nodes.selection import (
    PatchSelectionWithParamsTask,
    selection_payload_from_settings,
)
from derzug.nodes.spec import NodeSpec, PortSpec


class WaterfallParams(BaseModel):
    """Output-affecting parameters for Waterfall: selection and annotations.

    Presentation state (colormap, colour limits, view range, plot dims) is the
    view model, not params — Waterfall emits selection and annotations as
    downstream outputs, but its colouring never leaves the widget.
    """

    saved_selection_basis: str = ""
    saved_selection_ranges: list = Field(default_factory=list)
    saved_selection_has_roi: bool | None = None
    saved_annotation_set: Any = None


class WaterfallView(BaseModel):
    """Presentation-only state for Waterfall (never leaves the widget)."""

    colormap: str = "CET-D1"
    color_limits: Any = None
    reset_on_new: bool = True
    saved_view_range: Any = None
    saved_plot_y_dim: str = ""
    saved_plot_x_dim: str = ""


def waterfall_task_from_params(
    params: WaterfallParams | None = None,
) -> PatchSelectionWithParamsTask:
    """Build the selection task Waterfall contributes to a workflow."""
    params = WaterfallParams() if params is None else params
    return PatchSelectionWithParamsTask(
        selection_payload=selection_payload_from_settings(
            params.saved_selection_basis, params.saved_selection_ranges
        )
    )


NODE_SPEC = NodeSpec(
    name="Waterfall",
    widget_qualified_name="derzug.widgets.waterfall.Waterfall",
    inputs=(
        PortSpec(name="patch", display_name="Patch", type=dc.Patch),
        PortSpec(
            name="annotation_set",
            display_name="Annotations",
            type=AnnotationSet,
            context_only=True,
        ),
    ),
    outputs=(
        PortSpec(name="patch", display_name="Patch", type=dc.Patch),
        PortSpec(
            name="select_params", display_name="Select Params", type=SelectParams
        ),
        PortSpec(
            name="annotation_set",
            display_name="Annotations",
            type=AnnotationSet,
            context_only=True,
        ),
    ),
    params_model=WaterfallParams,
    view_model=WaterfallView,
    task_factory=waterfall_task_from_params,
    category="Visualize",
    description="Interactive pyqtgraph waterfall view for DAS patches",
    keywords=("waterfall", "patch", "pyqtgraph", "dascore"),
    icon="icons/Waterfall.svg",
    priority=20,
)
