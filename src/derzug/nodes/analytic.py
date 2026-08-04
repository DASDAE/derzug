"""The Analytic node: Hilbert-derived transforms along one dimension.

The transform dropdown carries ``role="method"``, so the chosen value *is* the
patch method invoked — the node declares no ``method_name`` of its own.
"""

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
        "transform",
        ("hilbert", "envelope"),
        role="method",
        label="Transform:",
        combo_attr="_transform_combo",
    ),
)

AnalyticParams = build_params_model("AnalyticParams", _OPTIONS, uses_dim=True)

analytic_task_from_params = partial(
    options_task_factory,
    call_style="positional_dim",
    uses_dim=True,
    options=_OPTIONS,
)

NODE_SPEC = NodeSpec(
    name="Analytic",
    widget_qualified_name="derzug.widgets.analytic.Analytic",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=AnalyticParams,
    task_factory=analytic_task_from_params,
    category="Transform",
    description="Apply Hilbert-derived transforms to a patch",
    keywords=("transform", "hilbert", "envelope", "analytic"),
    icon="icons/Analytic.svg",
    priority=21.2,
)
