"""The Calculus node: differentiate or integrate along one dimension."""

from __future__ import annotations

from typing import Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask

TRANSFORMS: tuple[str, ...] = ("differentiate", "integrate")


class CalculusParams(BaseModel):
    """Parameters for the Calculus node."""

    transform: Literal["differentiate", "integrate"] = "differentiate"
    selected_dim: str = ""
    order: int = 2
    step: int = 1
    definite: bool = False


def calculus_task_from_params(params: CalculusParams | None = None):
    """Build the configured differentiate/integrate task."""
    params = CalculusParams() if params is None else params
    transform = params.transform if params.transform in TRANSFORMS else TRANSFORMS[0]
    kwargs = (
        {"order": int(params.order), "step": int(params.step)}
        if transform == "differentiate"
        else {"definite": bool(params.definite)}
    )
    return PatchConfiguredMethodTask(
        method_name=transform,
        call_style="positional_dim",
        dim=params.selected_dim,
        method_kwargs=kwargs,
    )


NODE_SPEC = NodeSpec(
    name="Calculus",
    widget_qualified_name="derzug.widgets.calculus.Calculus",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=CalculusParams,
    task_factory=calculus_task_from_params,
    category="Transform",
    description="Apply differentiation and integration transforms to a patch",
    keywords=("transform", "differentiate", "integrate", "derivative", "integral"),
    icon="icons/Calculus.svg",
    priority=21.3,
)
