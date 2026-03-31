"""Tests for compiling widget graphs into workflow pipes."""

# ruff: noqa: D101, D102, D103, D106

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import ClassVar

import pytest

import derzug
from derzug.workflow import CompiledWorkflow, PipeBuilder, Task, compile_workflow


class AddOneTask(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {"value": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"result": int}

    def run(self, value):
        return value + 1


class DoubleTask(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {"value": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"result": int}

    def run(self, value):
        return value * 2


class SumTask(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {
        "left": int,
        "right": int,
    }
    output_variables: ClassVar[dict[str, type[int]]] = {"total": int}

    def run(self, left, right):
        return left + right


class ConstantTwoTask(Task):
    output_variables: ClassVar[dict[str, type[int]]] = {"result": int}

    def run(self):
        return 2


class _Signal:
    def __init__(self, name: str):
        self.name = name


class ProducerWidget:
    class Inputs:
        value = _Signal("Value")

    class Outputs:
        result = _Signal("Result")

    def get_task(self):
        return AddOneTask()


class ConsumerWidget:
    class Inputs:
        value = _Signal("Value")

    class Outputs:
        result = _Signal("Result")

    def get_task(self):
        return DoubleTask()


class SubPipeWidget:
    class Inputs:
        value = _Signal("Value")

    class Outputs:
        result = _Signal("Result")

    def get_task(self):
        builder = PipeBuilder()
        left = builder.add(AddOneTask(), name="increment")
        right = builder.add(DoubleTask(), name="result")
        builder.connect(left, right, from_output="result", to_input="value")
        return builder.build()


class ConstantWidget:
    class Outputs:
        result = _Signal("Result")

    def get_task(self):
        return ConstantTwoTask()


class MergeWidget:
    class Inputs:
        left = _Signal("Left")
        right = _Signal("Right")

    class Outputs:
        total = _Signal("Total")

    def get_task(self):
        return SumTask()


class SourceWidget:
    is_source = True

    class Outputs:
        value = _Signal("Value")

    def __init__(self, source=None):
        self._source = source

    def get_mapped_source(self):
        return self._source


def test_top_level_workflow_import_is_not_cyclic():
    """`from derzug.workflow import Pipe, Task` succeeds in a fresh interpreter."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from derzug.workflow import Pipe, Task; "
                "print(Pipe.__name__, Task.__name__)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "Pipe Task"


class BoundSourceWidget:
    is_source = True

    class Outputs:
        result = _Signal("Result")

    def get_task(self):
        return ConstantTwoTask()


@dataclass
class _Channel:
    name: str


@dataclass
class _Link:
    source_node: object
    source_channel: _Channel
    sink_node: object
    sink_channel: _Channel


@dataclass(eq=False)
class _Node:
    id: str
    widget: object


class _Workflow:
    def __init__(self, nodes, links, *, active_source_widget=None):
        self.nodes = nodes
        self.links = links
        self.active_source_widget = active_source_widget

    @staticmethod
    def widget_for_node(node):
        return node.widget


def test_compile_workflow_links_task_backed_widgets():
    source = _Node("source", ProducerWidget())
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, sink],
        [
            _Link(
                source_node=source,
                source_channel=_Channel("Result"),
                sink_node=sink,
                sink_channel=_Channel("Value"),
            )
        ],
    )

    compiled = compile_workflow(workflow)
    result = compiled.run(3)

    assert isinstance(compiled, CompiledWorkflow)
    assert result["sink"] == 8


def test_compile_workflow_inlines_subpipe_outputs_at_widget_boundary():
    source = _Node("source", ProducerWidget())
    middle = _Node("middle", SubPipeWidget())
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, middle, sink],
        [
            _Link(source, _Channel("Result"), middle, _Channel("Value")),
            _Link(middle, _Channel("Result"), sink, _Channel("Value")),
        ],
    )

    compiled = compile_workflow(workflow)
    result = compiled.run(2)

    assert result["sink"] == 16
    assert "middle.result" in compiled.pipe.node_names
    assert "middle.increment" not in compiled.pipe.node_names


def test_compile_workflow_maps_display_signal_names_to_task_ports():
    left = _Node("left", ConstantWidget())
    right = _Node("right", ConstantWidget())
    sink = _Node("sum", MergeWidget())
    workflow = _Workflow(
        [left, right, sink],
        [
            _Link(left, _Channel("Result"), sink, _Channel("Left")),
            _Link(right, _Channel("Result"), sink, _Channel("Right")),
        ],
    )

    compiled = compile_workflow(workflow)
    result = compiled.run()

    assert result["sum"] == 4


def test_compile_workflow_without_active_source_allows_manual_run_inputs():
    source = _Node("source", SourceWidget())
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, sink],
        [_Link(source, _Channel("Value"), sink, _Channel("Value"))],
    )

    compiled = compile_workflow(workflow)
    result = compiled.run(value=7)

    assert compiled.mapped_source is None
    assert compiled.mapped_input_names == ("value",)
    assert result["sink"] == 14


def test_compile_workflow_uses_active_source_as_default_map_input():
    source_widget = SourceWidget(source=[3, 4, 5])
    source = _Node("source", source_widget)
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, sink],
        [_Link(source, _Channel("Value"), sink, _Channel("Value"))],
        active_source_widget=source_widget,
    )

    compiled = compile_workflow(workflow)
    results = list(compiled.map())

    assert [result["sink"] for result in results] == [6, 8, 10]


def test_map_explicit_source_overrides_default_active_source():
    source_widget = SourceWidget(source=[3, 4, 5])
    source = _Node("source", source_widget)
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, sink],
        [_Link(source, _Channel("Value"), sink, _Channel("Value"))],
        active_source_widget=source_widget,
    )

    compiled = compile_workflow(workflow)
    results = list(compiled.map([8, 9]))

    assert [result["sink"] for result in results] == [16, 18]


def test_non_active_source_widgets_with_tasks_compile_inside_main_pipe():
    bound = _Node("bound", BoundSourceWidget())
    source = _Node("source", SourceWidget())
    sink = _Node("sum", MergeWidget())
    workflow = _Workflow(
        [bound, source, sink],
        [
            _Link(bound, _Channel("Result"), sink, _Channel("Left")),
            _Link(source, _Channel("Value"), sink, _Channel("Right")),
        ],
    )

    compiled = compile_workflow(workflow)
    result = compiled.run(value=5)

    assert result["sum"] == 7


def test_map_without_mapped_ports_raises_clear_error():
    left = _Node("left", ConstantWidget())
    right = _Node("right", ConstantWidget())
    sink = _Node("sum", MergeWidget())
    workflow = _Workflow(
        [left, right, sink],
        [
            _Link(left, _Channel("Result"), sink, _Channel("Left")),
            _Link(right, _Channel("Result"), sink, _Channel("Right")),
        ],
    )

    compiled = compile_workflow(workflow)

    with pytest.raises(ValueError, match="no mapped source configured"):
        list(compiled.map())


def test_compiled_source_workflow_pipe_round_trips_without_dynamic_class_in_globals(
    tmp_path,
):
    source_widget = SourceWidget()
    source = _Node("source", source_widget)
    sink = _Node("sink", ConsumerWidget())
    workflow = _Workflow(
        [source, sink],
        [_Link(source, _Channel("Value"), sink, _Channel("Value"))],
    )
    compiled = compile_workflow(workflow)
    path = tmp_path / "compiled_source_pipe.yaml"

    compiled.pipe.to_yaml(path)
    source_task = compiled.pipe.tasks[compiled.pipe.get_handle("source")]
    restored = type(compiled.pipe).from_yaml(path)

    assert source_task.__class__.__name__ == "MultiPassThroughTask"
    assert restored.run(value=4, output_keys=["sink"])["sink"] == 8


def test_derzug_top_level_exports_compile_workflow():
    assert derzug.compile_workflow is compile_workflow
