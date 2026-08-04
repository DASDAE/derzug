"""The Resample node: decimate or resample a patch along one dimension."""

from __future__ import annotations

from typing import Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.parsing import parse_patch_text_value, parse_text_value
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask

MODE_NAMES: tuple[str, ...] = ("decimate", "resample")
DECIMATE_FILTER_TYPES: tuple[str, ...] = ("iir", "fir", "none")
INTERP_KINDS: tuple[str, ...] = (
    "linear",
    "nearest",
    "zero",
    "slinear",
    "quadratic",
    "cubic",
)


class ResampleParams(BaseModel):
    """Parameters for the Resample node."""

    mode: Literal["decimate", "resample"] = "decimate"
    selected_dim: str = ""
    decimate_factor: str = "2"
    decimate_filter_type: Literal["iir", "fir", "none"] = "iir"
    resample_target: str = "10 ms"
    resample_samples: bool = False
    resample_interp_kind: Literal[
        "linear", "nearest", "zero", "slinear", "quadratic", "cubic"
    ] = "linear"


def parse_decimate_factor(text: str) -> int:
    """Return the positive integer decimation factor named by ``text``."""
    parsed = parse_text_value(text)
    if not isinstance(parsed, int):
        raise ValueError("factor must be an integer")
    if parsed <= 0:
        raise ValueError("factor must be positive")
    return parsed


def parse_resample_target(text: str, *, samples: bool):
    """Return the resample target: a sample count, or a coordinate step."""
    if not samples:
        return parse_patch_text_value(text, required=True)
    parsed = parse_text_value(text)
    if not isinstance(parsed, int):
        raise ValueError("sample target must be an integer")
    if parsed <= 0:
        raise ValueError("sample target must be positive")
    return parsed


def resample_task_from_params(params: ResampleParams | None = None):
    """Build the configured decimate/resample task."""
    params = ResampleParams() if params is None else params
    if params.mode == "resample":
        return PatchConfiguredMethodTask(
            method_name="resample",
            call_style="keyword_dim",
            dim=params.selected_dim,
            dim_value=parse_resample_target(
                params.resample_target, samples=bool(params.resample_samples)
            ),
            method_kwargs={
                "samples": bool(params.resample_samples),
                "interp_kind": params.resample_interp_kind,
            },
        )
    filter_type = (
        None if params.decimate_filter_type == "none" else params.decimate_filter_type
    )
    return PatchConfiguredMethodTask(
        method_name="decimate",
        call_style="keyword_dim",
        dim=params.selected_dim,
        dim_value=parse_decimate_factor(params.decimate_factor),
        method_kwargs={"filter_type": filter_type},
    )


NODE_SPEC = NodeSpec(
    name="Resample",
    widget_qualified_name="derzug.widgets.resample.Resample",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=ResampleParams,
    task_factory=resample_task_from_params,
    category="Processing",
    description="Decimate or resample a patch along a dimension",
    keywords=("resample", "decimate", "downsample", "upsample", "interpolate"),
    icon="icons/Resample.svg",
    priority=24,
)
