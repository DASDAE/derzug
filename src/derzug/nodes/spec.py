"""Qt-free node identity: ports, parameter models, and task factories.

A :class:`NodeSpec` is everything DerZug needs to know about a node type
*without* importing Qt: what it is called, what flows in and out, the pydantic
models describing its parameters and presentation state, and how to turn a
parameter model into a runnable :class:`~derzug.workflow.task.Task`.

The Qt widget for a node consumes the same spec (see ``ZugWidget.node_spec``),
so a headless host can introspect and execute a node while the canvas keeps
rendering it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from derzug.workflow import Pipe, Task


@dataclass(frozen=True)
class PortSpec:
    """One input or output port of a node.

    Parameters
    ----------
    name
        The port name used by the workflow compiler; also the widget attribute
        holding the Orange ``Input``/``Output`` descriptor.
    display_name
        The Orange signal name shown on the canvas (e.g. ``"Patch"``).
    type
        The value type carried by the port.
    context_only
        True for ports that configure the widget but take no part in the
        compiled workflow graph (e.g. an annotation set feeding a viewer).
    """

    name: str
    display_name: str
    type: Any = object
    context_only: bool = False


@dataclass(frozen=True)
class NodeSpec:
    """Qt-free description of one DerZug node type.

    ``task_factory`` maps a ``params_model`` instance (or ``None``, meaning
    "use the node's defaults") onto the workflow object the node executes.
    Nodes with no workflow semantics — pure viewers — leave it ``None``.
    """

    name: str
    widget_qualified_name: str
    inputs: tuple[PortSpec, ...] = ()
    outputs: tuple[PortSpec, ...] = ()
    params_model: Any = None
    view_model: Any = None
    task_factory: Callable[[Any], Task | Pipe] | None = None
    is_source: bool = False
    category: str = ""
    description: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    icon: str = ""
    priority: float = 0.0
    executes_arbitrary_code: bool = False

    @property
    def module_name(self) -> str:
        """Return the module part of :attr:`widget_qualified_name`."""
        return self.widget_qualified_name.rpartition(".")[0]

    def workflow_inputs(self) -> tuple[PortSpec, ...]:
        """Return input ports that participate in the compiled graph."""
        return tuple(port for port in self.inputs if not port.context_only)

    def workflow_outputs(self) -> tuple[PortSpec, ...]:
        """Return output ports that participate in the compiled graph."""
        return tuple(port for port in self.outputs if not port.context_only)

    def params_schema(self) -> dict[str, object] | None:
        """Return the JSON schema of :attr:`params_model`, or ``None``."""
        return _json_schema(self.params_model)

    def view_schema(self) -> dict[str, object] | None:
        """Return the JSON schema of :attr:`view_model`, or ``None``."""
        return _json_schema(self.view_model)

    def build_task(self, params: Any = None) -> Task | Pipe:
        """Return the workflow object for ``params`` (defaults when ``None``).

        Each node's factory owns its own default handling, because a
        discriminated union (Filter's ``kind``) has no single default member
        that a generic helper could construct.
        """
        if self.task_factory is None:
            raise TypeError(f"node {self.name!r} does not build a workflow task")
        return self.task_factory(params)


def _json_schema(model: Any) -> dict[str, object] | None:
    """Return a JSON schema for a model or discriminated union, or ``None``."""
    return None if model is None else TypeAdapter(model).json_schema()


__all__ = ("NodeSpec", "PortSpec")
