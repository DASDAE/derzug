"""The FBE node: frequency-band energy via STFT power reduction."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.nodes.stft import parse_overlap
from derzug.utils.parsing import parse_patch_text_value
from derzug.workflow.dims import PREFERRED_DIM
from derzug.workflow.task import Task

WINDOW_TYPES: tuple[str, ...] = ("hann", "hamming", "blackman", "nuttall")


def parse_fbe_bound(text: str) -> Any | None:
    """Parse one optional FBE frequency-band endpoint; blank means "no bound"."""
    if not text.strip():
        return None
    return parse_patch_text_value(text, allow_none=True)


class FBETask(Task):
    """Portable FBE task mirroring the widget's persisted settings.

    The bounds and window arrive as text and are parsed at run time, because
    a bound may be a bare number or a unit-bearing quantity and only the
    incoming patch settles what a blank bound means.
    """

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    selected_dim: str = PREFERRED_DIM
    window_length: str = "0.01"
    overlap: str = "50 %"
    taper_window: str = "hann"
    samples: bool = False
    detrend: bool = False
    fbe_lower: str = ""
    fbe_upper: str = ""

    def run(self, patch):
        """Apply FBE reduction to one patch using persisted settings."""
        if PREFERRED_DIM not in patch.dims:
            return None
        dim = self.selected_dim if self.selected_dim in patch.dims else PREFERRED_DIM
        window_length = parse_patch_text_value(self.window_length, required=True)
        stft_patch = patch.stft(
            overlap=parse_overlap(self.overlap),
            taper_window=self.taper_window,
            samples=bool(self.samples),
            detrend=bool(self.detrend),
            **{dim: window_length},
        )
        ft_values = stft_patch.get_array("ft_time")
        low = parse_fbe_bound(self.fbe_lower)
        high = parse_fbe_bound(self.fbe_upper)
        low = ft_values[0] if low is None else low
        high = ft_values[-1] if high is None else high
        if low > high:
            raise ValueError("lower must be less than or equal to upper")
        return (
            (stft_patch * stft_patch.conj())
            .select(ft_time=(low, high))
            .sum("ft_time")
            .squeeze()
        )


class FBEParams(BaseModel):
    """Parameters for the FBE node."""

    selected_dim: str = ""
    window_length: str = "0.01"
    overlap: str = "50 %"
    taper_window: Literal["hann", "hamming", "blackman", "nuttall"] = "hann"
    samples: bool = False
    detrend: bool = False
    fbe_lower: str = ""
    fbe_upper: str = ""


def fbe_task_from_params(params: FBEParams | None = None) -> FBETask:
    """Build the configured frequency-band energy task."""
    params = FBEParams() if params is None else params
    taper = (
        params.taper_window if params.taper_window in WINDOW_TYPES else WINDOW_TYPES[0]
    )
    return FBETask(
        selected_dim=str(params.selected_dim or PREFERRED_DIM),
        window_length=str(params.window_length or ""),
        overlap=str(params.overlap or ""),
        taper_window=str(taper),
        samples=bool(params.samples),
        detrend=bool(params.detrend),
        fbe_lower=str(params.fbe_lower or ""),
        fbe_upper=str(params.fbe_upper or ""),
    )


NODE_SPEC = NodeSpec(
    name="FBE",
    widget_qualified_name="derzug.widgets.fbe.FBE",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=FBEParams,
    task_factory=fbe_task_from_params,
    category="Transform",
    description="Extract one frequency band energy feature from a patch",
    keywords=("fbe", "stft", "frequency", "band", "energy"),
    icon="icons/FBE.svg",
    priority=21.14,
)
