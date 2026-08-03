"""The Taper node: a windowed taper along one patch dimension.

Reference implementation of an option-driven node module. Everything the node
is — its controls, its derived params model, and the configured patch-method
task they build — is declared here; ``derzug.widgets.taper`` only renders it.
"""

from __future__ import annotations

from functools import partial

import dascore as dc

from derzug.nodes._options import (
    ComboOption,
    OptionSpec,
    SpinOption,
    build_params_model,
    options_task_factory,
)
from derzug.nodes.spec import NodeSpec, PortSpec

_OPTIONS: tuple[OptionSpec, ...] = (
    SpinOption(
        "p",
        minimum=0.0,
        maximum=0.4,
        step=0.01,
        decimals=3,
        role="dim_value",
        label="Taper fraction (p):",
        spin_attr="_p_spin",
        default=0.05,
    ),
    ComboOption(
        "window_type",
        ("hann", "hamming", "blackman", "nuttall"),
        role="kwarg",
        label="Window type:",
        combo_attr="_window_combo",
    ),
)

TaperParams = build_params_model("TaperParams", _OPTIONS, uses_dim=True)

taper_task_from_params = partial(
    options_task_factory,
    method_name="taper",
    call_style="keyword_dim",
    uses_dim=True,
    options=_OPTIONS,
)

NODE_SPEC = NodeSpec(
    name="Taper",
    widget_qualified_name="derzug.widgets.taper.Taper",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=TaperParams,
    task_factory=taper_task_from_params,
    category="Processing",
    description="Apply a taper window to a patch along a selected dimension",
    keywords=("taper", "window", "hann", "pre-fft", "cosine"),
    icon="icons/Taper.svg",
    priority=21.4,
)
