"""The Wiggle node: a trace-oriented viewer that passes its patch through."""

from __future__ import annotations

from typing import Any, Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.widget_tasks import PatchPassThroughTask


class WiggleParams(BaseModel):
    """Parameters for the Wiggle node.

    Wiggle passes the patch through unchanged, so it has no output-affecting
    parameters; its display state belongs to the view model.
    """


class WiggleView(BaseModel):
    """Presentation-only state for Wiggle (a passthrough viewer)."""

    mode: Literal["offset", "time series"] = "offset"
    selected_trace_dim: str = ""
    selected_x_dim: str = ""
    stride: int = 8
    gain: int = 150
    colormap: str = "viridis"
    series_color_limits: Any = None
    percentiles: bool = False


def wiggle_task_from_params(
    params: WiggleParams | None = None,
) -> PatchPassThroughTask:
    """Build the pass-through task the viewer contributes to a workflow."""
    return PatchPassThroughTask()


NODE_SPEC = NodeSpec(
    name="Wiggle",
    widget_qualified_name="derzug.widgets.wiggle.Wiggle",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=WiggleParams,
    view_model=WiggleView,
    task_factory=wiggle_task_from_params,
    category="Visualize",
    description="Interactive pyqtgraph wiggle view for DAS patches",
    keywords=("wiggle", "patch", "pyqtgraph", "dascore"),
    icon="icons/Wiggle.svg",
    priority=21,
)
