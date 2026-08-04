"""The Stft node: a short-time Fourier transform along one dimension."""

from __future__ import annotations

import ast
from typing import Any

import dascore as dc
from dascore.units import percent
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow.widget_tasks import PatchConfiguredMethodTask


class StftParams(BaseModel):
    """Parameters for the Stft node."""

    selected_dim: str = ""
    window_length: str = "0.01"
    overlap: str = "50 %"
    taper_window: str = "hann"
    samples: bool = False
    detrend: bool = False


def parse_window_length(text: str) -> Any:
    """Parse the required STFT window-length value."""
    return parse_patch_text_value(text, required=True)


def parse_overlap(text: str) -> Any:
    """Parse the optional STFT overlap, honouring a percent suffix."""
    value = text.strip()
    if not value:
        return None
    lowered = value.lower()
    if "%" in value or "percent" in lowered:
        stripped = value.replace("%", "").replace("percent", "").strip()
        return parse_patch_text_value(stripped, required=True) * percent
    return parse_patch_text_value(value, allow_none=True)


def parse_taper_window(text: str) -> str | tuple:
    """Parse the taper-window input.

    Only string names and tuple specs are supported; array-valued windows stay
    out of scope for a text field.
    """
    value = text.strip()
    if not value:
        raise ValueError("value must not be empty")
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        parsed = value
    if isinstance(parsed, str | tuple):
        return parsed
    raise ValueError("expected a string name or tuple specification")


def stft_task_from_params(params: StftParams | None = None):
    """Build the configured short-time Fourier transform task."""
    params = StftParams() if params is None else params
    return PatchConfiguredMethodTask(
        method_name="stft",
        call_style="keyword_dim",
        dim=params.selected_dim,
        dim_value=parse_window_length(params.window_length),
        method_kwargs={
            "overlap": parse_overlap(params.overlap),
            "taper_window": parse_taper_window(params.taper_window),
            "samples": bool(params.samples),
            "detrend": bool(params.detrend),
        },
    )


NODE_SPEC = NodeSpec(
    name="Stft",
    widget_qualified_name="derzug.widgets.stft.Stft",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=StftParams,
    task_factory=stft_task_from_params,
    category="Transform",
    description="Apply a short-time Fourier transform to a patch",
    keywords=("stft", "spectrogram", "fourier", "transform"),
    icon="icons/Stft.svg",
    priority=21.15,
)
