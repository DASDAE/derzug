"""The Normalize node: DASCore normalize or standardize along one dimension."""

from __future__ import annotations

from typing import Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask

OPERATIONS: tuple[str, ...] = ("normalize", "standardize")
NORMS: tuple[str, ...] = ("l1", "l2", "max", "bit")


class NormalizeParams(BaseModel):
    """Parameters for the Normalize node."""

    operation: Literal["normalize", "standardize"] = "normalize"
    selected_dim: str = ""
    norm: Literal["l1", "l2", "max", "bit"] = "l2"


def normalize_task_from_params(params: NormalizeParams | None = None):
    """Build the configured normalize/standardize task."""
    params = NormalizeParams() if params is None else params
    operation = params.operation if params.operation in OPERATIONS else OPERATIONS[0]
    norm = params.norm if params.norm in NORMS else NORMS[1]
    return PatchConfiguredMethodTask(
        method_name=operation,
        call_style="positional_dim",
        dim=params.selected_dim,
        method_kwargs={"norm": norm} if operation == "normalize" else {},
    )


NODE_SPEC = NodeSpec(
    name="Normalize",
    widget_qualified_name="derzug.widgets.normalize.Normalize",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=NormalizeParams,
    task_factory=normalize_task_from_params,
    category="Processing",
    description="Apply DASCore normalize or standardize to a patch",
    keywords=("normalize", "standardize", "scale", "amplitude"),
    icon="icons/Normalize.svg",
    priority=21.5,
)
