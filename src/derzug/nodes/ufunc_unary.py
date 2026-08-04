"""The UFuncUnary node: one element-wise NumPy transform over a whole patch.

Unlike most option-driven nodes this one takes no dimension — the operations
are element-wise — so it uses the ``plain`` call style.
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

OPS: tuple[str, ...] = (
    "abs",
    "real",
    "imag",
    "conj",
    "angle",
    "exp",
    "log",
    "log10",
    "log2",
)

_OPTIONS: tuple[OptionSpec, ...] = (
    ComboOption(
        "selected_op",
        OPS,
        role="method",
        label="Operation:",
        combo_attr="_op_combo",
    ),
)

UFuncUnaryParams = build_params_model("UFuncUnaryParams", _OPTIONS, uses_dim=False)

ufunc_unary_task_from_params = partial(
    options_task_factory,
    call_style="plain",
    uses_dim=False,
    options=_OPTIONS,
)

NODE_SPEC = NodeSpec(
    name="UFuncUnary",
    widget_qualified_name="derzug.widgets.ufunc_unary.UFuncUnary",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=UFuncUnaryParams,
    task_factory=ufunc_unary_task_from_params,
    category="Processing",
    description="Apply a unary element-wise transform to a patch",
    keywords=("ufunc", "math", "unary", "abs", "log", "exp", "transform"),
    icon="icons/UFunc.svg",
    priority=22,
)
