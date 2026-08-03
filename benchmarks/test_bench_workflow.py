"""Benchmarks for the DerZug workflow engine.

Every widget execution in the canvas goes through this engine, so graph
construction, validation, serialization and execution overhead directly bound
how responsive a workflow feels.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from derzug.workflow import STREAM_END, PipeBuilder, Task
from derzug.workflow.task import task

# Depth/width of the synthetic graphs. Chosen to stay representative of real
# canvases (tens of widgets) while keeping each benchmark in the millisecond
# range.
CHAIN_DEPTH = 24
WIDE_WIDTH = 32
STREAM_ITEMS = 128
MAP_ITEMS = 32


class AddOne(Task):
    """Add one to a scalar input."""

    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"y": int}

    def run(self, x):
        """Return the incremented input."""
        return x + 1


class Split(Task):
    """Split one scalar into two scalars."""

    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"left": int, "right": int}

    def run(self, x):
        """Return the input duplicated with an offset."""
        return (x, x + 1)


class SumTwo(Task):
    """Add two scalar inputs."""

    input_variables: ClassVar[dict[str, type[int]]] = {"left": int, "right": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"total": int}

    def run(self, left, right):
        """Return the sum of both inputs."""
        return left + right


class DetectEven(Task):
    """Stream the even values of an input sequence."""

    input_variables: ClassVar[dict[str, type[list]]] = {"values": list}
    stream_outputs: ClassVar[dict[str, type[int]]] = {"event": int}

    def run(self, values):
        """Yield each even value in the input sequence."""
        for value in values:
            if value % 2 == 0:
                yield value


class DoubleEvent(Task):
    """Double one streamed event."""

    stream_inputs: ClassVar[dict[str, type[int]]] = {"event": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"value": int}

    def run(self, event):
        """Return the doubled event."""
        return event * 2


class CollectEvents(Task):
    """Aggregate a stream of events into a list."""

    stream_inputs: ClassVar[dict[str, type[int]]] = {"event": int}
    output_variables: ClassVar[dict[str, object]] = {"events": list[int]}
    final_output = "events"

    def run(self):
        """Collect every streamed event until the stream ends."""
        items = []
        event = yield None
        while event is not STREAM_END:
            items.append(event)
            event = yield None
        return items


def build_chain_pipe(depth: int = CHAIN_DEPTH):
    """Return a validated linear pipe of ``depth`` scalar tasks."""
    builder = PipeBuilder()
    previous = None
    for index in range(depth):
        handle = builder.add(AddOne(), name=f"add_{index}")
        if previous is not None:
            builder.connect(previous, handle, from_output="y", to_input="x")
        previous = handle
    return builder.build()


def build_fan_out_pipe(width: int = WIDE_WIDTH):
    """Return a validated fan-out/fan-in pipe with ``width`` parallel branches."""
    builder = PipeBuilder()
    source = builder.add(Split(), name="split")
    for index in range(width):
        left = builder.add(AddOne(), name=f"left_{index}")
        right = builder.add(AddOne(), name=f"right_{index}")
        join = builder.add(SumTwo(), name=f"join_{index}")
        builder.connect(source, left, from_output="left", to_input="x")
        builder.connect(source, right, from_output="right", to_input="x")
        builder.connect(left, join, from_output="y", to_input="left")
        builder.connect(right, join, from_output="y", to_input="right")
    return builder.build()


def build_stream_pipe():
    """Return a validated streaming pipe with a consumer and an aggregator."""
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    collect = builder.add(CollectEvents(), name="collect")
    builder.connect(detect, collect, from_output="event", to_input="event")
    return builder.build()


@pytest.fixture(scope="module")
def chain_pipe():
    """Return a reusable linear pipe."""
    return build_chain_pipe()


@pytest.fixture(scope="module")
def fan_out_pipe():
    """Return a reusable fan-out/fan-in pipe."""
    return build_fan_out_pipe()


@pytest.fixture(scope="module")
def stream_pipe():
    """Return a reusable streaming pipe."""
    return build_stream_pipe()


@pytest.fixture(scope="module")
def chain_pipe_json(tmp_path_factory, chain_pipe):
    """Return the path of a serialized linear pipe."""
    path = tmp_path_factory.mktemp("workflow") / "chain.json"
    chain_pipe.to_json(path)
    return path


def test_build_chain_pipe(benchmark):
    """Build and validate a deep linear workflow graph."""
    pipe = benchmark(build_chain_pipe)
    assert len(pipe.tasks) == CHAIN_DEPTH


def test_build_fan_out_pipe(benchmark):
    """Build and validate a wide fan-out/fan-in workflow graph."""
    pipe = benchmark(build_fan_out_pipe)
    assert len(pipe.tasks) == WIDE_WIDTH * 3 + 1


def test_validate_fan_out_pipe(benchmark, fan_out_pipe):
    """Re-validate an existing wide graph (done on every derived copy)."""
    benchmark(fan_out_pipe.validate)


def test_topological_sort(benchmark, fan_out_pipe):
    """Order the nodes of a wide graph."""
    handles = benchmark(fan_out_pipe.sorted_tasks)
    assert len(handles) == len(fan_out_pipe.tasks)


def test_pipe_fingerprint(benchmark, fan_out_pipe):
    """Hash a wide graph into its stable fingerprint."""
    assert len(benchmark(lambda: fan_out_pipe.fingerprint)) == 16


def test_run_chain_pipe(benchmark, chain_pipe):
    """Execute a deep linear workflow once."""
    results = benchmark(chain_pipe.run, 0, output_keys=[f"add_{CHAIN_DEPTH - 1}"])
    assert results[f"add_{CHAIN_DEPTH - 1}"] == CHAIN_DEPTH


def test_run_fan_out_pipe(benchmark, fan_out_pipe):
    """Execute a wide fan-out/fan-in workflow once."""
    results = benchmark(fan_out_pipe.run, 1, output_keys=["join_0"])
    assert results["join_0"] == 5


def test_run_stream_pipe(benchmark, stream_pipe):
    """Execute a streaming workflow that aggregates every emitted event."""
    values = list(range(STREAM_ITEMS))
    results = benchmark(stream_pipe.run, values, output_keys=["collect"])
    assert len(results["collect"]) == STREAM_ITEMS // 2


def test_map_chain_pipe(benchmark, chain_pipe):
    """Map a linear workflow over a source of scalars."""
    key = f"add_{CHAIN_DEPTH - 1}"

    def run_map():
        """Consume the full map generator."""
        return [result[key] for result in chain_pipe.map(range(MAP_ITEMS))]

    assert len(benchmark(run_map)) == MAP_ITEMS


def test_pipe_to_dict(benchmark, fan_out_pipe):
    """Serialize a wide graph into its portable mapping."""
    payload = benchmark(fan_out_pipe._to_dict)
    assert len(payload["tasks"]) == len(fan_out_pipe.tasks)


def test_pipe_from_json(benchmark, chain_pipe, chain_pipe_json):
    """Rebuild a linear graph from its serialized form."""
    pipe = benchmark(type(chain_pipe).from_json, chain_pipe_json)
    assert len(pipe.tasks) == CHAIN_DEPTH


def test_pipe_provenance(benchmark, chain_pipe):
    """Build the provenance record attached to workflow outputs."""
    provenance = benchmark(chain_pipe.get_provenance)
    assert provenance.fingerprint


def test_function_task_creation(benchmark):
    """Turn a plain function into a task class and resolve its ports."""

    def make_task():
        """Create one function-backed task class and inspect its ports."""

        @task
        def scale_value(x: int, factor: int = 2) -> int:
            """Scale one value by a factor."""
            scaled = x * factor
            return scaled

        return scale_value.port_spec()

    spec = benchmark(make_task)
    assert spec.scalar_outputs == (("scaled", int),)
