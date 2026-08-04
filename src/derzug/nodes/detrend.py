"""The Detrend node: remove a linear or constant trend along one dimension."""

from __future__ import annotations

from functools import partial

import dascore as dc

from derzug.nodes._options import (
    ComboOption,
    OptionSpec,
    build_params_model,
    options_task_factory,
)
from derzug.nodes.spec import NodeSpec, PortSpec

_OPTIONS: tuple[OptionSpec, ...] = (
    ComboOption(
        "detrend_type",
        ("linear", "constant"),
        role="arg",
        label="Type:",
        combo_attr="_type_combo",
    ),
)

DetrendParams = build_params_model("DetrendParams", _OPTIONS, uses_dim=True)

detrend_task_from_params = partial(
    options_task_factory,
    method_name="detrend",
    call_style="positional_dim",
    uses_dim=True,
    options=_OPTIONS,
)

NODE_SPEC = NodeSpec(
    name="Detrend",
    widget_qualified_name="derzug.widgets.detrend.Detrend",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=DetrendParams,
    task_factory=detrend_task_from_params,
    category="Processing",
    description="Apply DASCore detrending to a patch",
    keywords=("detrend", "trend", "linear", "constant"),
    icon="icons/Detrend.svg",
    priority=21,
)
