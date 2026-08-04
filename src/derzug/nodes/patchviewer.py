"""The PatchViewer node: inspect a patch and pass it through unchanged."""

from __future__ import annotations

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.widget_tasks import PatchPassThroughTask


class PatchViewerParams(BaseModel):
    """Parameters for the PatchViewer node.

    PatchViewer is a pure viewer with no persisted state; it passes the patch
    through unchanged and has no output-affecting parameters.
    """


def patchviewer_task_from_params(
    params: PatchViewerParams | None = None,
) -> PatchPassThroughTask:
    """Build the pass-through task the viewer contributes to a workflow."""
    return PatchPassThroughTask()


NODE_SPEC = NodeSpec(
    name="PatchViewer",
    widget_qualified_name="derzug.widgets.patchviewer.PatchViewer",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=PatchViewerParams,
    task_factory=patchviewer_task_from_params,
    category="Visualize",
    description="Inspect a DAS patch and preview its arrays",
    keywords=("patch", "viewer", "inspect", "coords", "attrs"),
    icon="icons/PatchViewer.svg",
    priority=22,
)
