"""The Rolling node: a moving-window aggregation along one dimension."""

from __future__ import annotations

from typing import Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow.widget_tasks import PatchRollingTask

AGGREGATIONS: tuple[str, ...] = ("mean", "median", "sum", "min", "max", "std")


class RollingParams(BaseModel):
    """Parameters for the Rolling node."""

    selected_dim: str = ""
    rolling_window: str = "0.01"
    step: str = ""
    center: bool = False
    dropna: bool = False
    aggregation: Literal["mean", "median", "sum", "min", "max", "std"] = "mean"


def rolling_task_from_params(params: RollingParams | None = None):
    """Build the configured rolling-aggregation task.

    The window and step arrive as free text because they may name a coordinate
    step (``"0.01"``) or a time span (``"2s"``); parsing them is what turns the
    persisted strings into the values DASCore expects.
    """
    params = RollingParams() if params is None else params
    aggregation = (
        params.aggregation if params.aggregation in AGGREGATIONS else AGGREGATIONS[0]
    )
    return PatchRollingTask(
        dim=params.selected_dim,
        window=parse_patch_text_value(params.rolling_window, required=True),
        step=parse_patch_text_value(params.step, allow_none=True),
        center=bool(params.center),
        dropna=bool(params.dropna),
        aggregation=aggregation,
    )


NODE_SPEC = NodeSpec(
    name="Rolling",
    widget_qualified_name="derzug.widgets.rolling.Rolling",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=RollingParams,
    task_factory=rolling_task_from_params,
    category="Processing",
    description="Apply DASCore rolling aggregation to a patch",
    keywords=("rolling", "aggregate", "smooth", "moving"),
    icon="icons/Rolling.svg",
    priority=24,
)
