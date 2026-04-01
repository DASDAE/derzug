"""
Compile Orange widget graphs into portable workflow artifacts.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .graph import Edge
from .pipe import Pipe
from .task import Task
from .widget_tasks import MultiPassThroughTask


@dataclass(frozen=True)
class CompiledWorkflow:
    """A compiled Orange workflow with an optional default mapped source."""

    pipe: Pipe
    mapped_source: Iterable[object] | None = None
    mapped_input_names: tuple[str, ...] = ()

    def run(self, *args, **kwargs):
        """Execute the compiled workflow once."""
        return self.pipe.run(*args, **kwargs)

    def map(
        self,
        source: Iterable[object] | None = None,
        *,
        output_keys: list[str] | tuple[str, ...] | None = None,
        strict: bool = True,
        provenance=None,
    ) -> Iterator[object]:
        """Map one iterable over the compiled workflow."""
        runtime_source = source if source is not None else self.mapped_source
        if runtime_source is None:
            raise ValueError(
                "no mapped source configured; pass one explicitly to map(source=...)"
            )
        if not self.mapped_input_names:
            raise ValueError(
                "mapped source is ambiguous for this workflow; pass explicit "
                "inputs to run(...) instead"
            )
        if len(self.mapped_input_names) == 1:
            input_name = self.mapped_input_names[0]
            for item in runtime_source:
                yield self.pipe.run(
                    **{input_name: item},
                    output_keys=output_keys,
                    strict=strict,
                    provenance=provenance,
                )
            return
        for item in runtime_source:
            if not isinstance(item, Mapping):
                raise TypeError(
                    "mapped items for multi-port workflows must be mappings "
                    "keyed by input port name"
                )
            kwargs = {name: item[name] for name in self.mapped_input_names}
            yield self.pipe.run(
                **kwargs,
                output_keys=output_keys,
                strict=strict,
                provenance=provenance,
            )


def widget_signal_name_map(widget, container_name: str) -> dict[str, str]:
    """Return a mapping of display signal names to widget attribute names."""
    container = getattr(type(widget), container_name, None)
    if container is None:
        container = getattr(widget, container_name, None)
    if container is None:
        return {}
    out: dict[str, str] = {}
    for attr_name, value in vars(container).items():
        display_name = getattr(value, "name", None)
        if isinstance(display_name, str):
            out[display_name] = attr_name
    return out


def compile_workflow(orange_workflow) -> CompiledWorkflow:
    """Compile one Orange workflow into a compiled workflow artifact."""
    tasks: dict[str, Task] = {}
    edges: list[Edge] = []
    node_names: dict[str, str] = {}
    widget_handles: dict[Any, dict[str, str]] = {}
    external_source_ports: dict[Any, tuple[str, ...]] = {}
    active_source_widget = _active_source_widget(orange_workflow)

    for node in orange_workflow.nodes:
        widget = orange_workflow.widget_for_node(node)
        node_key = _node_key(node)
        if _is_external_source_widget(widget, active_source_widget):
            ports = _widget_output_ports(widget)
            workflow_obj: Task | Pipe = MultiPassThroughTask.from_names(ports)
            external_source_ports[widget] = ports
        else:
            if not hasattr(widget, "get_task"):
                raise TypeError(
                    f"widget {type(widget).__name__} does not implement get_task()"
                )
            workflow_obj = widget.get_task()
        handles = _inline_workflow_object(
            workflow_obj,
            node_key=node_key,
            tasks=tasks,
            edges=edges,
            node_names=node_names,
        )
        widget_handles[node] = handles

    for link in orange_workflow.links:
        source_widget = orange_workflow.widget_for_node(link.source_node)
        sink_widget = orange_workflow.widget_for_node(link.sink_node)
        source_map = widget_signal_name_map(source_widget, "Outputs")
        sink_map = widget_signal_name_map(sink_widget, "Inputs")
        from_port = source_map.get(link.source_channel.name, link.source_channel.name)
        to_port = sink_map.get(link.sink_channel.name, link.sink_channel.name)
        source_handles = widget_handles[link.source_node]
        sink_handles = widget_handles[link.sink_node]
        from_node = source_handles.get(from_port) or _require_named_handle(
            source_handles, from_port, source_widget, "output"
        )
        to_node = sink_handles.get(to_port) or _require_named_handle(
            sink_handles, to_port, sink_widget, "input"
        )
        edges.append(
            Edge(
                from_node=from_node,
                from_port=from_port,
                to_node=to_node,
                to_port=to_port,
            )
        )

    pipe = Pipe(tasks=tasks, edges=tuple(edges), node_names=node_names)
    pipe.validate()
    mapped_input_names, mapped_source = _mapped_source_details(
        active_source_widget,
        external_source_ports,
    )
    return CompiledWorkflow(
        pipe=pipe,
        mapped_source=mapped_source,
        mapped_input_names=mapped_input_names,
    )


def _mapped_source_details(
    active_source_widget: object | None,
    external_source_ports: Mapping[object, tuple[str, ...]],
) -> tuple[tuple[str, ...], Iterable[object] | None]:
    """Return the mapped input names and default mapped iterable, if any."""
    if (
        active_source_widget is not None
        and active_source_widget in external_source_ports
    ):
        mapped_source = _resolve_mapped_source(active_source_widget)
        return external_source_ports[active_source_widget], mapped_source
    if len(external_source_ports) == 1:
        return next(iter(external_source_ports.values())), None
    return (), None


def _resolve_mapped_source(widget: object) -> Iterable[object] | None:
    """Resolve the default mapped iterable from one active source widget."""
    getter = getattr(widget, "get_mapped_source", None)
    if getter is None:
        return None
    source = getter()
    if source is None:
        return None
    if not isinstance(source, Iterable):
        raise TypeError(
            f"mapped source for widget {type(widget).__name__} is not iterable"
        )
    return source


def _active_source_widget(orange_workflow) -> object | None:
    """Return the currently active source widget, when available."""
    direct = getattr(orange_workflow, "active_source_widget", None)
    if direct is not None:
        return direct
    manager = getattr(orange_workflow, "active_source_manager", None)
    if manager is not None:
        return getattr(manager, "_active_widget", None)
    main_window = getattr(orange_workflow, "main_window", None)
    manager = getattr(main_window, "active_source_manager", None)
    if manager is not None:
        return getattr(manager, "_active_widget", None)
    return None


def _is_external_source_widget(
    widget: object, active_source_widget: object | None
) -> bool:
    """Return True when a source widget should compile as an external input."""
    if not bool(getattr(widget, "is_source", False)):
        return False
    return (
        widget is active_source_widget
        or not hasattr(widget, "get_task")
        or _uses_default_get_task(widget)
    )


def _uses_default_get_task(widget: object) -> bool:
    """Return True when the widget still relies on `ZugWidget`'s fallback contract."""
    try:
        from derzug.core.zugwidget import ZugWidget
    except Exception:
        return False
    return getattr(type(widget), "get_task", None) is ZugWidget.get_task


def _widget_output_ports(widget: object) -> tuple[str, ...]:
    """Return the output port names exposed by one widget."""
    outputs = tuple(widget_signal_name_map(widget, "Outputs").values())
    if not outputs:
        raise ValueError(
            f"source widget {type(widget).__name__} does not expose output ports"
        )
    return outputs


def _require_named_handle(
    handles: Mapping[str, str],
    port_name: str,
    widget: object,
    port_kind: str,
) -> str:
    """Resolve one exported per-port handle or raise a clear error."""
    handle = handles.get(port_name)
    if handle is not None:
        return handle
    raise ValueError(
        "compiled widget "
        f"{type(widget).__name__} does not expose a {port_kind} node "
        f"for port {port_name!r}"
    )


def _node_key(node: Any) -> str:
    """Return a stable string key for one Orange node."""
    node_id = getattr(node, "id", None)
    if node_id is not None:
        return str(node_id)
    return str(id(node))


def _inline_workflow_object(
    workflow_obj: Task | Pipe,
    *,
    node_key: str,
    tasks: dict[str, Task],
    edges: list[Edge],
    node_names: dict[str, str],
) -> dict[str, str]:
    """Inline a widget-provided Task or Pipe into the compiled graph."""
    if isinstance(workflow_obj, Task):
        handle = node_key
        tasks[handle] = workflow_obj.model_copy(deep=True)
        outputs = tuple(workflow_obj.resolved_scalar_output_variables())
        inputs = tuple(workflow_obj.resolved_scalar_input_variables())
        out: dict[str, str] = {}
        for name in outputs:
            out[name] = handle
            node_names[f"{node_key}.{name}"] = handle
        if len(outputs) == 1:
            node_names[node_key] = handle
        for name in inputs:
            out.setdefault(name, handle)
        return out

    if isinstance(workflow_obj, Pipe):
        output_handles: dict[str, str] = {}
        input_handles: dict[str, str] = {}
        downstream = {edge.from_node for edge in workflow_obj.edges}
        for subhandle, task in workflow_obj.tasks.items():
            compiled_handle = f"{node_key}:{subhandle}"
            tasks[compiled_handle] = task.model_copy(deep=True)
        for edge in workflow_obj.edges:
            edges.append(
                Edge(
                    from_node=f"{node_key}:{edge.from_node}",
                    from_port=edge.from_port,
                    to_node=f"{node_key}:{edge.to_node}",
                    to_port=edge.to_port,
                )
            )
        for subhandle, task in workflow_obj.tasks.items():
            compiled_handle = f"{node_key}:{subhandle}"
            if subhandle in workflow_obj._root_nodes():
                for port_name in task.resolved_scalar_input_variables():
                    input_handles.setdefault(port_name, compiled_handle)
            if subhandle not in downstream:
                for port_name in task.resolved_scalar_output_variables():
                    output_handles.setdefault(port_name, compiled_handle)
        for port_name, handle in output_handles.items():
            node_names[f"{node_key}.{port_name}"] = handle
        if len(output_handles) == 1:
            node_names[node_key] = next(iter(output_handles.values()))
        output_handles.update(
            {
                name: handle
                for name, handle in input_handles.items()
                if name not in output_handles
            }
        )
        return {**input_handles, **output_handles}

    raise TypeError(f"unsupported workflow object {workflow_obj!r}")


__all__ = ("CompiledWorkflow", "compile_workflow", "widget_signal_name_map")
