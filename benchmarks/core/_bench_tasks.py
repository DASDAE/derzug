"""Workflow tasks and pipe builders shared by the Qt-free benchmarks.

These live in a real module rather than a ``conftest.py`` because
:meth:`derzug.workflow.graph.PipeGraph.validate` re-imports every task's
``code_path``, so the defining module must be importable by name.
"""

from __future__ import annotations

from typing import ClassVar

from derzug.workflow import STREAM_END, PipeBuilder, Task


class AddOne(Task):
    """Add one to a scalar input."""

    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"y": int}

    def run(self, x):
        """Return the input incremented by one."""
        return x + 1


class SumTwo(Task):
    """Sum two scalar inputs."""

    input_variables: ClassVar[dict[str, type[int]]] = {"left": int, "right": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"total": int}

    def run(self, left, right):
        """Return the sum of both inputs."""
        return left + right


class Split(Task):
    """Split a scalar input into two scalar outputs."""

    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"left": int, "right": int}

    def run(self, x):
        """Return the input and its successor."""
        return (x, x + 1)


class DetectEven(Task):
    """Stream the even items of a list input."""

    input_variables: ClassVar[dict[str, type[list]]] = {"items": list}
    stream_outputs: ClassVar[dict[str, type[int]]] = {"event": int}

    def run(self, items):
        """Yield each even item in turn."""
        for item in items:
            if item % 2 == 0:
                yield item


class CollectEvents(Task):
    """Collect a stream of events into a list."""

    stream_inputs: ClassVar[dict[str, type[int]]] = {"event": int}
    output_variables: ClassVar[dict[str, object]] = {"events": list[int]}
    final_output = "events"

    def run(self):
        """Accumulate streamed events until the end-of-stream sentinel."""
        items = []
        event = yield None
        while event is not STREAM_END:
            items.append(event)
            event = yield None
        return items


def plain_add_two(x: int) -> int:
    """Return the input plus two.

    Used as the source callable for the ``@task`` class-synthesis benchmark;
    it is deliberately *not* decorated, so each benchmark round builds a task
    class from scratch.
    """
    return x + 2


def build_chain(length: int):
    """Return a linear ``length``-node pipe of :class:`AddOne` tasks."""
    builder = PipeBuilder()
    previous = builder.add(AddOne(), name="node_0")
    for index in range(1, length):
        current = builder.add(AddOne(), name=f"node_{index}")
        builder.connect(previous, current)
        previous = current
    return builder.build()


def build_diamond(width: int):
    """Return a fan-out/fan-in pipe with two branches of ``width`` nodes."""
    builder = PipeBuilder()
    source = builder.add(Split(), name="source")
    left = builder.add(AddOne(), name="left_0")
    right = builder.add(AddOne(), name="right_0")
    builder.connect(source, left, from_output="left")
    builder.connect(source, right, from_output="right")
    for index in range(1, width):
        new_left = builder.add(AddOne(), name=f"left_{index}")
        new_right = builder.add(AddOne(), name=f"right_{index}")
        builder.connect(left, new_left)
        builder.connect(right, new_right)
        left, right = new_left, new_right
    join = builder.add(SumTwo(), name="join")
    builder.connect(left, join, to_input="left")
    builder.connect(right, join, to_input="right")
    return builder.build()


def build_stream_pipe():
    """Return a producer/consumer pipe exercising the generator runtime."""
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    collect = builder.add(CollectEvents(), name="collect")
    builder.connect(detect, collect, from_output="event", to_input="event")
    return builder.build()
