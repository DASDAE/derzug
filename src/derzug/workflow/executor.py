"""
Streaming workflow execution runtime.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Generator
from typing import Any

import derzug

from .results import Results

STREAM_END = object()


class StreamingExecutor:
    """Execute one Pipe invocation."""

    def __init__(
        self,
        pipe,
        requested_outputs: list[str] | None = None,
        *,
        strict: bool = True,
        source_provenance=(),
    ):
        self.pipe = pipe
        self.requested_outputs = list(requested_outputs or [])
        self.strict = strict
        self.source_provenance = tuple(source_provenance)
        self.scalar_inputs = defaultdict(dict)
        self.adjacency = self._adjacency()
        self.started_scalars: set[str] = set()
        self.active_coroutines: dict[str, Generator[Any, Any, Any]] = {}
        self.node_outputs: dict[str, dict[str, Any]] = defaultdict(dict)
        self.retained_outputs = self._retained_outputs()
        self.errors: dict[str, Any] = {}
        self.skipped_nodes: dict[str, str] = {}
        self.queued = deque()
        self.failed_nodes: set[str] = set()

    def _adjacency(self) -> dict[tuple[str, str], list[Any]]:
        out: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for edge in self.pipe.edges:
            out[(edge.from_node, edge.from_port)].append(edge)
        return out

    def _retained_outputs(self) -> dict[str, set[str] | None]:
        """Return the scalar outputs that should be kept in `node_outputs`."""
        requested = self.requested_outputs or self.default_requested_outputs()
        retained: dict[str, set[str] | None] = {}
        for key in requested:
            handle = self._resolve_requested_handle(key)
            task = self.pipe.tasks.get(handle)
            if task is None:
                continue
            retained_port = self._retained_port_for_key(key, handle, task)
            if retained_port is None:
                retained[handle] = None
                continue
            existing = retained.get(handle)
            if existing is None and handle in retained:
                continue
            if existing is None:
                retained[handle] = {retained_port}
            else:
                existing.add(retained_port)
        return retained

    def _resolve_requested_handle(self, key: str) -> str:
        """Resolve an output request key to the owning node handle."""
        handle = self.pipe.node_names.get(key)
        if handle is not None:
            return handle
        prefix, _, _suffix = key.rpartition(".")
        if prefix:
            handle = self.pipe.node_names.get(prefix)
            if handle is not None:
                return handle
        return key

    def _retained_port_for_key(self, key: str, handle: str, task) -> str | None:
        """Return one specifically requested output port, or None for all ports."""
        outputs = task.resolved_scalar_output_variables()
        if key == handle:
            return None
        prefix, _, suffix = key.rpartition(".")
        if not prefix or suffix not in outputs:
            return None
        if self.pipe.node_names.get(key) == handle:
            return suffix
        if self.pipe.node_names.get(prefix) != handle:
            return None
        return suffix

    def bind_initial_inputs(self, *args, **kwargs) -> None:
        """Bind runtime inputs onto the root tasks that accept them."""
        roots = self.pipe._root_nodes()
        if not roots:
            return
        bindable_roots = [
            handle
            for handle in roots
            if self.pipe.tasks[handle].resolved_scalar_input_variables()
        ]
        if not bindable_roots:
            return
        if len(args) and len(bindable_roots) != 1:
            raise ValueError(
                "positional inputs are supported only when exactly one root "
                "accepts explicit inputs"
            )
        if len(args):
            handle = bindable_roots[0]
            task = self.pipe.tasks[handle]
            scalar_ports = list(task.resolved_scalar_input_variables())
        else:
            handle = None
            scalar_ports = []
        for index, arg in enumerate(args):
            if index >= len(scalar_ports):
                raise ValueError("too many positional inputs for root task")
            if isinstance(arg, derzug.Source):
                arg = arg.get_single_data()
            self.scalar_inputs[handle][scalar_ports[index]] = arg
        if not kwargs:
            return
        port_to_handle: dict[str, str] = {}
        for root_handle in bindable_roots:
            for port_name in self.pipe.tasks[
                root_handle
            ].resolved_scalar_input_variables():
                existing = port_to_handle.get(port_name)
                if existing is not None and existing != root_handle:
                    raise ValueError(
                        f"input port {port_name!r} is ambiguous across root tasks"
                    )
                port_to_handle[port_name] = root_handle
        for key, value in kwargs.items():
            if isinstance(value, derzug.Source):
                value = value.get_single_data()
            target = port_to_handle.get(key)
            if target is None:
                raise ValueError(f"unknown root input {key!r}")
            self.scalar_inputs[target][key] = value

    def execute(self, *args, **kwargs) -> Results:
        """Run the pipe once."""
        self.pipe.validate()
        self.bind_initial_inputs(*args, **kwargs)

        for handle in self.pipe._root_nodes():
            self.schedule_if_ready(handle)

        while self.queued:
            handle = self.queued.popleft()
            if handle in self.started_scalars:
                continue
            self.started_scalars.add(handle)
            task = self.pipe.tasks[handle]
            try:
                if task.__class__.is_stream_producer():
                    self._execute_stream_producer(handle, task)
                else:
                    raw = task.run(**self.scalar_inputs[handle])
                    for port, value in self.normalize_scalar_outputs(task, raw).items():
                        self.emit_scalar(handle, port, value)
            except Exception as exc:  # pragma: no cover
                self.record_error(handle, exc)

        for handle in self.pipe.tasks:
            if handle in self.started_scalars or handle in self.failed_nodes:
                continue
            if self.dependencies_failed(handle):
                self.skipped_nodes.setdefault(handle, "upstream dependency failed")

        result_outputs = {}
        for handle in self.retained_outputs:
            outputs = self.node_outputs.get(handle, {})
            if outputs:
                result_outputs[handle] = outputs
        return Results(
            node_outputs=result_outputs,
            error_map=self.errors,
            skipped_map=self.skipped_nodes,
            provenance=self.pipe.get_provenance(
                source_provenance=self.source_provenance
            ),
            node_names=self.pipe.node_names,
        )

    def record_error(self, handle: str, exc: Exception) -> None:
        """Record one node failure, optionally aborting execution."""
        self.errors[handle] = exc
        self.failed_nodes.add(handle)
        self.active_coroutines.pop(handle, None)
        if self.strict:
            raise exc

    def required_ready(self, handle: str) -> bool:
        """Return True when all required scalar inputs have been supplied."""
        task = self.pipe.tasks[handle]
        return set(task.resolved_required_scalar_inputs()).issubset(
            self.scalar_inputs[handle]
        )

    def dependencies_failed(self, handle: str) -> bool:
        """Return True when any upstream dependency failed."""
        for edge in self.pipe.edges:
            if edge.to_node == handle and edge.from_node in self.failed_nodes:
                return True
        return False

    def schedule_if_ready(self, handle: str) -> None:
        """Queue a scalar task once its dependencies and inputs are satisfied."""
        task = self.pipe.tasks[handle]
        if task.__class__.is_stream_consumer():
            return
        if handle in self.started_scalars:
            return
        if self.dependencies_failed(handle):
            self.skipped_nodes.setdefault(handle, "upstream dependency failed")
            return
        if self.required_ready(handle):
            self.queued.append(handle)

    def normalize_scalar_outputs(self, task, raw: Any) -> dict[str, Any]:
        """Convert one task return value into its named scalar outputs."""
        mapping = task.resolved_scalar_output_variables()
        if not mapping:
            return {}
        if len(mapping) == 1:
            return {next(iter(mapping)): raw}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, tuple) and len(raw) == len(mapping):
            return dict(zip(mapping.keys(), raw, strict=True))
        raise ValueError(
            f"task {task.__class__.__name__} returned {raw!r} "
            f"but outputs are {tuple(mapping)}"
        )

    def emit_scalar(self, handle: str, port: str, value: Any) -> None:
        """Store and forward a scalar output value."""
        if self._should_retain_output(handle, port):
            self.node_outputs[handle][port] = value
        for edge in self.adjacency.get((handle, port), []):
            self.scalar_inputs[edge.to_node][edge.to_port] = value
            self.schedule_if_ready(edge.to_node)

    def _should_retain_output(self, handle: str, port: str) -> bool:
        """Return True when one emitted scalar output should stay in memory."""
        retained = self.retained_outputs.get(handle)
        if retained is None:
            return handle in self.retained_outputs
        return port in retained

    def start_coroutine(self, handle: str) -> Generator[Any, Any, Any]:
        """Prime one generator-backed downstream task."""
        gen = self.pipe.tasks[handle].run(**self.scalar_inputs[handle])
        try:
            first = next(gen)
        except StopIteration as stop:
            if (
                self.pipe.tasks[handle].final_output is not None
                and stop.value is not None
            ):
                self.emit_scalar(
                    handle,
                    self.pipe.tasks[handle].final_output,
                    stop.value,
                )
            raise ValueError(
                f"stream consumer {handle} terminated before accepting input"
            )
        if first is not None:
            raise ValueError(f"stream consumer {handle} must yield None when primed")
        return gen

    def drain_generator_yields(
        self, gen: Generator[Any, Any, Any], yielded: Any
    ) -> tuple[list[Any], Any | None]:
        """Collect yielded stream values until suspension or completion."""
        emitted: list[Any] = []
        current = yielded
        while True:
            if current is None:
                return emitted, None
            emitted.append(current)
            try:
                current = next(gen)
            except StopIteration as stop:
                return emitted, stop.value

    def close_coroutine(self, handle: str) -> None:
        """Flush and close one active downstream consumer coroutine."""
        gen = self.active_coroutines.pop(handle, None)
        if gen is None:
            return
        try:
            yielded = gen.send(STREAM_END)
        except StopIteration as stop:
            final = stop.value
            if self.pipe.tasks[handle].final_output is not None and final is not None:
                self.emit_scalar(handle, self.pipe.tasks[handle].final_output, final)
            for port in self.pipe.tasks[handle].resolved_stream_output_variables():
                self.finalize_stream(handle, port)
            return
        emitted, final = self.drain_generator_yields(gen, yielded)
        stream_port = next(
            iter(self.pipe.tasks[handle].resolved_stream_output_variables()),
            None,
        )
        if stream_port is not None:
            for item in emitted:
                self.emit_stream(handle, stream_port, item)
            self.finalize_stream(handle, stream_port)
        if self.pipe.tasks[handle].final_output is not None and final is not None:
            self.emit_scalar(handle, self.pipe.tasks[handle].final_output, final)

    def emit_stream(self, handle: str, port: str, value: Any) -> None:
        """Deliver one streamed value to each connected downstream node."""
        for edge in self.adjacency.get((handle, port), []):
            downstream = self.pipe.tasks[edge.to_node]
            if edge.to_node in self.failed_nodes:
                continue
            if not self.required_ready(edge.to_node):
                raise ValueError(
                    f"scalar inputs for node {edge.to_node} "
                    "must be ready before stream delivery"
                )
            if downstream.__class__.uses_generator_runtime():
                gen = self.active_coroutines.get(edge.to_node)
                if gen is None:
                    try:
                        gen = self.start_coroutine(edge.to_node)
                    except Exception as exc:  # pragma: no cover
                        self.record_error(edge.to_node, exc)
                        continue
                    self.active_coroutines[edge.to_node] = gen
                try:
                    yielded = gen.send(value)
                except StopIteration as stop:
                    self.active_coroutines.pop(edge.to_node, None)
                    if downstream.final_output is not None and stop.value is not None:
                        self.emit_scalar(
                            edge.to_node,
                            downstream.final_output,
                            stop.value,
                        )
                    continue
                except Exception as exc:  # pragma: no cover
                    self.record_error(edge.to_node, exc)
                    continue
                emitted, final = self.drain_generator_yields(gen, yielded)
                stream_port = next(
                    iter(downstream.resolved_stream_output_variables()),
                    None,
                )
                if stream_port is not None:
                    for item in emitted:
                        self.emit_stream(edge.to_node, stream_port, item)
                if downstream.final_output is not None and final is not None:
                    self.emit_scalar(edge.to_node, downstream.final_output, final)
                    self.active_coroutines.pop(edge.to_node, None)
            else:
                try:
                    raw = downstream.run(
                        **self.scalar_inputs[edge.to_node],
                        **{edge.to_port: value},
                    )
                except Exception as exc:  # pragma: no cover
                    self.record_error(edge.to_node, exc)
                    continue
                for out_port, out_value in self.normalize_scalar_outputs(
                    downstream,
                    raw,
                ).items():
                    self.emit_scalar(edge.to_node, out_port, out_value)

    def finalize_stream(self, handle: str, port: str) -> None:
        """Finalize delivery for one exhausted stream output port."""
        for edge in self.adjacency.get((handle, port), []):
            downstream = self.pipe.tasks[edge.to_node]
            if edge.to_node in self.failed_nodes:
                continue
            if downstream.__class__.uses_generator_runtime():
                self.close_coroutine(edge.to_node)

    def _execute_stream_producer(self, handle: str, task) -> None:
        """Run one generator-backed producer and emit all yielded values."""
        gen = task.run(**self.scalar_inputs[handle])
        stream_port = next(iter(task.resolved_stream_output_variables()))
        while True:
            try:
                item = next(gen)
            except StopIteration as stop:
                if task.final_output is not None and stop.value is not None:
                    self.emit_scalar(handle, task.final_output, stop.value)
                self.finalize_stream(handle, stream_port)
                break
            self.emit_stream(handle, stream_port, item)

    def default_requested_outputs(self) -> list[str]:
        """Return terminal node names used when callers omit output_keys."""
        requested = []
        reverse_names = self.pipe._reverse_names()
        downstream_nodes = {edge.from_node for edge in self.pipe.edges}
        for handle, task in self.pipe.tasks.items():
            if (
                handle not in downstream_nodes
                and task.resolved_scalar_output_variables()
            ):
                requested.append(reverse_names.get(handle, handle))
        return requested
