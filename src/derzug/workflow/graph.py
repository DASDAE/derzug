"""
Workflow graph definitions and validation helpers.
"""

# ruff: noqa: D102

from __future__ import annotations

import importlib
import inspect
import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from .model import WorkflowFrozenModel
from .task import Task
from .widget_tasks import CallableTaskAdapter, MultiPassThroughTask


def resolve_symbol(code_path: str) -> Any:
    """Import a symbol from module:qualname form."""
    module_name, qualname = code_path.split(":", maxsplit=1)
    try:
        obj = importlib.import_module(module_name)
    except Exception as exc:
        raise ImportError(
            f"could not import module {module_name!r} for workflow task {code_path!r}"
        ) from exc
    try:
        for attr in qualname.split("."):
            obj = getattr(obj, attr)
    except AttributeError as exc:
        raise ImportError(
            "could not resolve qualname "
            f"{qualname!r} in module {module_name!r} "
            f"for workflow task {code_path!r}"
        ) from exc
    return obj


def ensure_task_class(symbol: Any) -> type[Task]:
    """Resolve an imported symbol into a Task subclass."""
    if inspect.isclass(symbol) and issubclass(symbol, Task):
        return symbol
    raise TypeError(f"{symbol!r} is not a Task subclass")


def ensure_code_path_is_portable(code_path: str) -> None:
    """Validate that a task code path can be re-imported."""
    if "<locals>" in code_path:
        raise ValueError(f"task code path {code_path!r} is not portable")
    if "<lambda>" in code_path:
        raise ValueError(f"task code path {code_path!r} is not portable")
    try:
        ensure_task_class(resolve_symbol(code_path))
    except (ImportError, TypeError) as exc:
        raise ValueError(f"task code path {code_path!r} is not portable") from exc


def hash_payload(payload: dict[str, Any]) -> str:
    """Return a stable short hash."""
    return (
        __import__("hashlib")
        .sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))
        .hexdigest()[:16]
    )


def _portable_task_payload(task: Task) -> dict[str, Any]:
    """Return the stable serialized representation for one task instance."""
    task_cls = task.__class__
    code_path = f"{task_cls.__module__}:{task_cls.__qualname__}"
    parameters = task.model_dump(mode="json")
    metadata: dict[str, Any] = {}
    if getattr(task_cls, "__portable_adapter_factory__", None) == "callable_task":
        code_path = (
            f"{CallableTaskAdapter.__module__}:" f"{CallableTaskAdapter.__qualname__}"
        )
        parameters = {
            "function_code_path": task.code_path(),
            "output_names": tuple(task.resolved_scalar_output_variables()),
        }
        metadata["legacy_factory"] = "callable_task"
    elif isinstance(task, MultiPassThroughTask):
        code_path = (
            f"{MultiPassThroughTask.__module__}:{MultiPassThroughTask.__qualname__}"
        )
        parameters = task.model_dump(mode="json")
        metadata["legacy_factory"] = "multi_pass_through"
    return {
        "code_path": code_path,
        "version": task.__version__,
        "parameters": parameters,
        "metadata": metadata,
    }


def _rebuild_legacy_dynamic_task(task_data: dict[str, Any]) -> Task | None:
    """Rebuild supported legacy dynamic task payloads from older serialized data."""
    metadata = task_data.get("metadata") or {}
    factory = metadata.get("factory")
    parameters = task_data.get("parameters", {})
    if factory == "callable_task":
        return CallableTaskAdapter(
            function_code_path=metadata["function_code_path"],
            output_names=tuple(metadata.get("output_names") or ()),
        )
    if factory == "multi_pass_through":
        names = tuple(metadata.get("port_names") or ())
        return MultiPassThroughTask.from_names(names).model_copy(update=parameters)
    return None


@dataclass(frozen=True)
class Edge:
    """A port-to-port connection between nodes."""

    from_node: str
    from_port: str
    to_node: str
    to_port: str


def topological_sort(tasks: dict[str, Task], edges: tuple[Edge, ...]) -> list[str]:
    """Return node handles in topological order."""
    incoming: dict[str, int] = {handle: 0 for handle in tasks}
    outgoing: dict[str, list[str]] = {handle: [] for handle in tasks}
    for edge in edges:
        incoming[edge.to_node] += 1
        outgoing[edge.from_node].append(edge.to_node)
    queue = deque(sorted(handle for handle, count in incoming.items() if count == 0))
    out: list[str] = []
    while queue:
        handle = queue.popleft()
        out.append(handle)
        for downstream in outgoing[handle]:
            incoming[downstream] -= 1
            if incoming[downstream] == 0:
                queue.append(downstream)
    if len(out) != len(tasks):
        raise ValueError("workflow graph contains a cycle")
    return out


class PipeBuilder:
    """Mutable workflow graph builder."""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.edges: list[Edge] = []
        self.node_names: dict[str, str] = {}

    def add(self, task: Task, name: str | None = None) -> str:
        """Insert a task and return its node handle."""
        handle = uuid.uuid4().hex
        self.tasks[handle] = task.model_copy(deep=True)
        if name is not None:
            if name in self.node_names:
                raise ValueError(f"duplicate node name {name!r}")
            self.node_names[name] = handle
        return handle

    def connect(
        self,
        from_node: str,
        to_node: str,
        *,
        from_output: str | None = None,
        to_input: str | None = None,
    ) -> None:
        """Connect one node port to another."""
        upstream = self.tasks[from_node]
        downstream = self.tasks[to_node]
        from_output = from_output or self._infer_from_output(upstream)
        is_stream = from_output in upstream.resolved_stream_output_variables()
        to_input = to_input or self._infer_to_input(downstream, is_stream=is_stream)
        self.edges.append(
            Edge(
                from_node=from_node,
                from_port=from_output,
                to_node=to_node,
                to_port=to_input,
            )
        )

    def _infer_from_output(self, task: Task) -> str:
        outputs = {
            **task.resolved_scalar_output_variables(),
            **task.resolved_stream_output_variables(),
        }
        if len(outputs) != 1:
            raise ValueError(
                "from_output is required when the upstream task has multiple outputs"
            )
        return next(iter(outputs))

    def _infer_to_input(self, task: Task, *, is_stream: bool) -> str:
        stream_inputs = task.resolved_stream_input_variables()
        scalar_inputs = task.resolved_scalar_input_variables()
        if is_stream:
            if len(stream_inputs) == 1:
                return next(iter(stream_inputs))
            if not stream_inputs:
                raise ValueError(
                    "to_input is required when connecting a stream to a non-stream task"
                )
            raise ValueError(
                "to_input is required when the downstream task has multiple "
                "stream inputs"
            )
        if len(scalar_inputs) == 1:
            return next(iter(scalar_inputs))
        required = list(task.resolved_required_scalar_inputs())
        if len(required) == 1:
            return required[0]
        candidates = [name for name in scalar_inputs if name not in stream_inputs]
        if len(candidates) == 1:
            return candidates[0]
        raise ValueError(
            "to_input is required when the downstream task has multiple "
            "candidate inputs"
        )

    def build(self):
        """Return an immutable validated pipe."""
        from .pipe import Pipe

        pipe = Pipe(
            tasks=self.tasks,
            edges=tuple(self.edges),
            node_names=self.node_names,
        )
        pipe.validate()
        return pipe


class PipeGraph(WorkflowFrozenModel):
    """Graph storage and serialization mixin for Pipe."""

    tasks: dict[str, Task] = Field(default_factory=dict)
    edges: tuple[Edge, ...] = Field(default_factory=tuple)
    node_names: dict[str, str] = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = {
            "tasks": {
                handle: {
                    "task_fingerprint": task.fingerprint,
                    "code_path": _portable_task_payload(task)["code_path"],
                }
                for handle, task in sorted(self.tasks.items())
            },
            "edges": [edge.__dict__ for edge in self.edges],
            "node_names": self.node_names,
        }
        return hash_payload(payload)

    def __hash__(self) -> int:
        """Hash the graph using its stable fingerprint."""
        return hash(self.fingerprint)

    def get_handle(self, name: str) -> str:
        """Return the node handle for a stable node name."""
        return self.node_names[name]

    def _reverse_names(self) -> dict[str, str]:
        """Return the inverse mapping from handle to stable node name."""
        return {handle: name for name, handle in self.node_names.items()}

    def _to_dict(self) -> dict[str, Any]:
        """Serialize the graph into a plain mapping."""
        return {
            "tasks": [
                {"handle": handle, **_portable_task_payload(task)}
                for handle, task in self.tasks.items()
            ],
            "edges": [edge.__dict__ for edge in self.edges],
            "node_names": self.node_names,
        }

    @classmethod
    def _from_dict(cls, data: dict[str, Any]):
        """Rebuild a graph instance from serialized data."""
        tasks: dict[str, Task] = {}
        for task_data in data.get("tasks", []):
            rebuilt = _rebuild_legacy_dynamic_task(task_data)
            if rebuilt is not None:
                tasks[task_data["handle"]] = rebuilt
                continue
            task_cls = ensure_task_class(resolve_symbol(task_data["code_path"]))
            tasks[task_data["handle"]] = task_cls(**task_data.get("parameters", {}))
        edges = tuple(Edge(**edge_data) for edge_data in data.get("edges", []))
        return cls(tasks=tasks, edges=edges, node_names=data.get("node_names", {}))

    def to_json(self, path: str | Path, *, indent: int = 2) -> None:
        """Write the serialized graph to a JSON file."""
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(
            json.dumps(self._to_dict(), indent=indent, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def from_json(cls, path: str | Path):
        """Load a graph from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls._from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        """Write the serialized graph to a YAML file."""
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(
            yaml.safe_dump(self._to_dict(), sort_keys=False),
            encoding="utf-8",
        )

    @classmethod
    def from_yaml(cls, path: str | Path):
        """Load a graph from a YAML file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls._from_dict(data)

    def sorted_tasks(self) -> list[str]:
        """Return task handles in topological order."""
        return topological_sort(self.tasks, self.edges)

    def _root_nodes(self) -> list[str]:
        """Return task handles with no incoming edges."""
        downstream = {edge.to_node for edge in self.edges}
        return [handle for handle in self.tasks if handle not in downstream]

    def validate(self) -> None:
        """Validate task interfaces and graph topology."""
        for task in self.tasks.values():
            task.validate_instance_ports()
            ensure_code_path_is_portable(_portable_task_payload(task)["code_path"])

        for name, handle in self.node_names.items():
            if handle not in self.tasks:
                raise ValueError(
                    f"node name {name!r} references unknown handle {handle!r}"
                )

        topological_sort(self.tasks, self.edges)
        stream_input_counts: dict[str, int] = defaultdict(int)
        stream_consumers: dict[tuple[str, str], int] = defaultdict(int)
        for edge in self.edges:
            if edge.from_node not in self.tasks or edge.to_node not in self.tasks:
                raise ValueError(f"edge references unknown node: {edge}")

            upstream = self.tasks[edge.from_node]
            downstream = self.tasks[edge.to_node]
            scalar_outputs = upstream.resolved_scalar_output_variables()
            stream_outputs = upstream.resolved_stream_output_variables()
            scalar_inputs = downstream.resolved_scalar_input_variables()
            stream_inputs = downstream.resolved_stream_input_variables()

            if edge.from_port in scalar_outputs:
                if edge.to_port not in scalar_inputs:
                    raise ValueError(
                        f"scalar port {edge.from_port!r} "
                        "must connect to a scalar input"
                    )
            elif edge.from_port in stream_outputs:
                if edge.to_port not in stream_inputs:
                    raise ValueError(
                        f"stream port {edge.from_port!r} "
                        "must connect to a stream input"
                    )
                stream_input_counts[edge.to_node] += 1
                stream_consumers[(edge.from_node, edge.from_port)] += 1
            else:
                raise ValueError(f"unknown upstream output port {edge.from_port!r}")

        for handle, count in stream_input_counts.items():
            if count > 1:
                raise ValueError(
                    f"node {handle} may not have more than one streaming input"
                )
        for (handle, port), count in stream_consumers.items():
            if count > 1:
                raise ValueError(
                    f"stream output {handle}:{port} has multiple consumers"
                )
