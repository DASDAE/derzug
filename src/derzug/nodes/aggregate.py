"""The Aggregate node: reduce a patch along one dimension (or all of them)."""

from __future__ import annotations

from typing import ClassVar, Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.dims import PREFERRED_DIM
from derzug.workflow.task import Task

METHODS: tuple[str, ...] = (
    "first",
    "last",
    "max",
    "mean",
    "median",
    "min",
    "phase_weighted_stack",
    "std",
    "sum",
)
DIM_REDUCES: tuple[str, ...] = (
    "empty",
    "squeeze",
    "mean",
    "min",
    "max",
    "first",
    "last",
)


def default_phase_weighted_stack_dim(dims: tuple[str, ...]) -> str | None:
    """Return the stack dimension phase-weighted stacking defaults to.

    Stacking is usually across receivers, so ``distance`` wins, then whatever
    comes first. Shared by the widget's method switch and ``AggregateTask.run``
    so canvas and headless resolve the same dimension.
    """
    if not dims:
        return None
    return "distance" if "distance" in dims else dims[0]


def infer_phase_weighted_stack_transform_dim(patch: dc.Patch, stack_dim: str) -> str:
    """Pick a deterministic transform axis for phase-weighted stacking."""
    candidates = tuple(dim for dim in patch.dims if dim != stack_dim)
    if not candidates:
        msg = "Phase-weighted stack requires at least two patch dimensions."
        raise ValueError(msg)
    if PREFERRED_DIM in candidates:
        return PREFERRED_DIM
    sized_candidates = tuple(
        dim for dim in candidates if patch.shape[patch.dims.index(dim)] > 1
    )
    if len(sized_candidates) == 1:
        return sized_candidates[0]
    if len(candidates) == 1:
        return candidates[0]
    msg = (
        "Phase-weighted stack could not infer the transform dimension from "
        f"{candidates}. Add a 'time' dimension or reduce the patch to one "
        "non-stack dimension before stacking."
    )
    raise ValueError(msg)


class AggregateTask(Task):
    """Task wrapper around DASCore aggregate reduction."""

    selected_dim: str = ""
    transform_dim: str = ""
    method: str = "mean"
    dim_reduce: str = "empty"
    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    def run(self, patch):
        """Apply the configured aggregate reduction to one patch."""
        dim = None if self.selected_dim in ("", "All") else self.selected_dim
        if dim is not None and dim not in patch.dims:
            # The widget's dim chooser resets a stale dim to "All"; match it.
            dim = None
        if self.method == "phase_weighted_stack":
            if dim is None:
                # A headless caller may leave the stack dim unset; resolve it
                # the same way the widget's method switch would.
                dim = default_phase_weighted_stack_dim(tuple(patch.dims))
            if dim is None:
                msg = "Phase-weighted stack requires a patch with dimensions."
                raise ValueError(msg)
            # A transform dim that is missing or equals the resolved stack dim
            # is re-inferred, mirroring the widget's transform chooser.
            transform_dim = (
                self.transform_dim
                if self.transform_dim
                and self.transform_dim in patch.dims
                and self.transform_dim != dim
                else infer_phase_weighted_stack_transform_dim(patch, dim)
            )
            return patch.phase_weighted_stack(
                stack_dim=dim,
                transform_dim=transform_dim,
                dim_reduce=self.dim_reduce,
            )
        return patch.aggregate(dim=dim, method=self.method, dim_reduce=self.dim_reduce)


class AggregateParams(BaseModel):
    """Parameters for the Aggregate node."""

    selected_dim: str = ""
    transform_dim: str = ""
    method: Literal[
        "first",
        "last",
        "max",
        "mean",
        "median",
        "min",
        "phase_weighted_stack",
        "std",
        "sum",
    ] = "mean"
    dim_reduce: Literal["empty", "squeeze", "mean", "min", "max", "first", "last"] = (
        "empty"
    )


def aggregate_task_from_params(params: AggregateParams | None = None) -> AggregateTask:
    """Build the configured aggregate task."""
    params = AggregateParams() if params is None else params
    return AggregateTask(
        selected_dim=params.selected_dim,
        transform_dim=params.transform_dim,
        method=params.method if params.method in METHODS else METHODS[0],
        dim_reduce=(
            params.dim_reduce if params.dim_reduce in DIM_REDUCES else DIM_REDUCES[0]
        ),
    )


NODE_SPEC = NodeSpec(
    name="Aggregate",
    widget_qualified_name="derzug.widgets.aggregate.Aggregate",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=AggregateParams,
    task_factory=aggregate_task_from_params,
    category="Processing",
    description="Apply DASCore aggregate reduction to a patch",
    keywords=("aggregate", "reduce", "mean", "sum", "statistics"),
    icon="icons/AggregateColumns.svg",
    priority=25,
)
