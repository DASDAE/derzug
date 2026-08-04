"""The Code node: run a user-supplied ``transform(patch)`` script.

This node executes arbitrary Python by design, which is what
``executes_arbitrary_code`` on its spec announces to anything (the Conductor,
a future server) that needs to decide whether running it is acceptable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

import dascore as dc
import numpy as np
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.callable_spec import task_from_callable
from derzug.workflow.task import Task

DEFAULT_SCRIPT = """def transform(patch):
    \"\"\"Return the value to emit from this widget.\"\"\"
    return patch
"""

_COMPILE_CACHE_SIZE = 64


@lru_cache(maxsize=_COMPILE_CACHE_SIZE)
def compile_script(script_text: str):
    """Compile and cache immutable user script bytecode by source text."""
    return compile(script_text, "<derzug-code>", "exec")


def has_unsupported_required_inputs(task_type: type[Task]) -> bool:
    """Return True when required inputs other than patch are declared."""
    for name in task_type.required_scalar_inputs():
        if name == "patch":
            continue
        return True
    return False


class CodeTransformTask(Task):
    """Task that compiles widget script text and invokes `transform`."""

    script_text: str
    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"result": object}

    def run(self, patch):
        """Compile the saved script and execute its `transform` callable."""
        namespace: dict[str, object] = {
            "__builtins__": __builtins__,
            "__name__": "__main__",
            "dc": dc,
            "np": np,
        }
        code = compile_script(self.script_text)
        exec(code, namespace, namespace)
        transform = namespace.get("transform")
        if not callable(transform):
            raise ValueError("script must define a callable `transform(patch)`")
        task_type = task_from_callable(transform)
        if has_unsupported_required_inputs(task_type):
            raise ValueError(
                "script transform has unsupported required inputs; only "
                "`patch` may be required"
            )
        task = task_type()
        return task.run(patch=patch)


class CodeParams(BaseModel):
    """Parameters for the Code node."""

    script_text: str = DEFAULT_SCRIPT


def code_task_from_params(params: CodeParams | None = None) -> CodeTransformTask:
    """Build the configured script-execution task."""
    params = CodeParams() if params is None else params
    return CodeTransformTask(script_text=params.script_text)


NODE_SPEC = NodeSpec(
    name="Code",
    widget_qualified_name="derzug.widgets.code.Code",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="result", display_name="Result"),),
    params_model=CodeParams,
    task_factory=code_task_from_params,
    executes_arbitrary_code=True,
    category="Processing",
    description="Run custom Python code on a patch",
    keywords=("code", "python", "script", "custom"),
    icon="icons/PythonScript.svg",
    priority=21.7,
)
