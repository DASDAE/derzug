"""The UFuncBinary node: one binary NumPy ufunc over two generic inputs."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.task import Task

OP_LABEL_TO_UFUNC: dict[str, np.ufunc] = {
    "x+y": np.add,
    "x-y": np.subtract,
    "x*y": np.multiply,
    "x/y": np.divide,
    "x**y": np.power,
    "x%y": np.remainder,
    "maximum(x,y)": np.maximum,
    "minimum(x,y)": np.minimum,
    "x>y": np.greater,
    "x<y": np.less,
    "x==y": np.equal,
    "x!=y": np.not_equal,
    "x>=y": np.greater_equal,
    "x<=y": np.less_equal,
}
DEFAULT_OP: str = next(iter(OP_LABEL_TO_UFUNC))


class UFuncBinaryTask(Task):
    """Task wrapper around one selected binary NumPy ufunc."""

    selected_op: str
    input_variables: ClassVar[dict[str, object]] = {"x": object, "y": object}
    output_variables: ClassVar[dict[str, object]] = {"result": object}

    def run(self, x, y):
        """Apply the selected NumPy ufunc to both inputs."""
        ufunc = OP_LABEL_TO_UFUNC.get(self.selected_op, OP_LABEL_TO_UFUNC[DEFAULT_OP])
        return ufunc(x, y)


class UFuncBinaryParams(BaseModel):
    """Parameters for the binary UFunc operator."""

    selected_op: str = "x+y"


def ufunc_binary_task_from_params(
    params: UFuncBinaryParams | None = None,
) -> UFuncBinaryTask:
    """Build the configured binary-ufunc task."""
    params = UFuncBinaryParams() if params is None else params
    return UFuncBinaryTask(selected_op=params.selected_op)


NODE_SPEC = NodeSpec(
    name="UFuncBinary",
    widget_qualified_name="derzug.widgets.ufunc_binary.UFuncBinary",
    inputs=(
        PortSpec(name="x", display_name="x"),
        PortSpec(name="y", display_name="y"),
    ),
    outputs=(PortSpec(name="result", display_name="Result"),),
    params_model=UFuncBinaryParams,
    task_factory=ufunc_binary_task_from_params,
    category="Processing",
    description="Apply selected NumPy ufunc to x and y inputs",
    keywords=("ufunc", "numpy", "binary", "operator", "math"),
    icon="icons/UFunc.svg",
    priority=23,
)
