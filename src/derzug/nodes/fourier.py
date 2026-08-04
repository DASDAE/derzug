"""The Fourier node: forward and inverse discrete Fourier transforms.

The forward transform takes a *set* of dimensions and the inverse takes one,
and each prefers a different default — ``dft`` wants a time-domain axis while
``idft`` wants a Fourier one. Both resolve that choice against the patch they
actually receive, so a saved node runs headlessly on a patch whose dimensions
differ from the one it was configured against.
"""

from __future__ import annotations

from typing import ClassVar, Literal

import dascore as dc
from pydantic import BaseModel, Field

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.dims import PREFERRED_DIM
from derzug.workflow.task import Task

TRANSFORMS: tuple[str, ...] = ("dft", "idft")
REAL_OPTIONS: tuple[tuple[str, str | bool | None], ...] = (
    ("Auto", None),
    ("Real", True),
    ("Complex", False),
)
REAL_OPTION_MAP: dict[str, bool | None] = dict(REAL_OPTIONS)
_FOURIER_PREFIX = "ft_"


class FourierParams(BaseModel):
    """Parameters for the Fourier node."""

    transform: Literal["dft", "idft"] = "dft"
    selected_dim: str = ""
    selected_dims: list[str] = Field(default_factory=list)
    real_mode: Literal["Auto", "Real", "Complex"] = "Auto"
    pad: bool = True


def default_dft_dim(dims: tuple[str, ...]) -> str | None:
    """Return the dimension a forward transform defaults to.

    A time axis wins, then any Fourier axis, then whatever comes first.
    """
    if not dims:
        return None
    if PREFERRED_DIM in dims:
        return PREFERRED_DIM
    fourier = [dim for dim in dims if dim.startswith(_FOURIER_PREFIX)]
    return fourier[0] if fourier else dims[0]


def default_idft_dim(dims: tuple[str, ...]) -> str | None:
    """Return the dimension an inverse transform defaults to.

    Inverting is only meaningful on a Fourier axis, so those are preferred
    over the forward default.
    """
    fourier = tuple(dim for dim in dims if dim.startswith(_FOURIER_PREFIX))
    return default_dft_dim(fourier or dims)


class FourierTask(Task):
    """Run a forward or inverse discrete Fourier transform on one patch."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    transform: Literal["dft", "idft"] = "dft"
    dims: tuple[str, ...] = ()
    dim: str = ""
    real: bool | None = None
    pad: bool = True

    def run(self, patch):
        """Apply the configured transform, resolving dimensions on the patch."""
        available = tuple(patch.dims)
        if self.transform == "idft":
            dim = self.dim if self.dim in available else default_idft_dim(available)
            if dim is None:
                raise ValueError("idft needs a dimension but the patch has none")
            return patch.idft(dim)
        dims = tuple(dim for dim in self.dims if dim in available)
        if not dims:
            fallback = default_dft_dim(available)
            if fallback is None:
                raise ValueError("dft needs a dimension but the patch has none")
            dims = (fallback,)
        return patch.dft(dims, real=self.real, pad=self.pad)


def fourier_task_from_params(params: FourierParams | None = None) -> FourierTask:
    """Build the configured Fourier task."""
    params = FourierParams() if params is None else params
    transform = params.transform if params.transform in TRANSFORMS else TRANSFORMS[0]
    real_mode = params.real_mode if params.real_mode in REAL_OPTION_MAP else "Auto"
    return FourierTask(
        transform=transform,
        dims=tuple(params.selected_dims),
        dim=params.selected_dim,
        real=REAL_OPTION_MAP[real_mode],
        pad=bool(params.pad),
    )


NODE_SPEC = NodeSpec(
    name="Fourier",
    widget_qualified_name="derzug.widgets.fourier.Fourier",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=FourierParams,
    task_factory=fourier_task_from_params,
    category="Transform",
    description="Apply DASCore Fourier transforms to a patch",
    keywords=("transform", "fourier", "fft", "dft", "idft"),
    icon="icons/Fourier.svg",
    priority=21.1,
)
