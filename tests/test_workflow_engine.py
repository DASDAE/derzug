"""Tests for the workflow execution engine."""

# ruff: noqa: D101, D102, D103

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from derzug.workflow import STREAM_END, Pipe, PipeBuilder, Provenance, Task
from derzug.workflow.task import task


class AddOne(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"y": int}

    def run(self, x):
        return x + 1


class Fail(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"y": int}

    def run(self, x):
        raise RuntimeError(f"bad input: {x}")


class SumTwo(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {
        "left": int,
        "right": int,
    }
    output_variables: ClassVar[dict[str, type[int]]] = {"total": int}

    def run(self, left, right):
        return left + right


class Split(Task):
    input_variables: ClassVar[dict[str, type[int]]] = {"x": int}
    output_variables: ClassVar[dict[str, type[int]]] = {
        "left": int,
        "right": int,
    }

    def run(self, x):
        return (x, x + 1)


class DetectEven(Task):
    input_variables: ClassVar[dict[str, type[list]]] = {"patch": list}
    stream_outputs: ClassVar[dict[str, type[int]]] = {"event": int}

    def run(self, patch):
        for item in patch:
            if item % 2 == 0:
                yield item


class DoubleEvent(Task):
    stream_inputs: ClassVar[dict[str, type[int]]] = {"event": int}
    output_variables: ClassVar[dict[str, type[int]]] = {"value": int}

    def run(self, event):
        return event * 2


class CollectEvents(Task):
    stream_inputs: ClassVar[dict[str, type[int]]] = {"event": int}
    output_variables: ClassVar[dict[str, object]] = {"events": list[int]}
    final_output = "events"

    def run(self):
        items = []
        event = yield None
        while event is not STREAM_END:
            items.append(event)
            event = yield None
        return items


@task
def add_two(x: int) -> int:
    return x + 2


def test_scalar_pipe_run_returns_named_output():
    builder = PipeBuilder()
    builder.add(AddOne(), name="add")
    pipe = builder.build()

    result = pipe.run(2, output_keys=["add"])

    assert result["add"] == 3
    assert result.ok


def test_streaming_pipe_runs_consumer_once_per_emission():
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    double = builder.add(DoubleEvent(), name="double")
    builder.connect(detect, double, from_output="event", to_input="event")
    pipe = builder.build()

    result = next(iter(pipe.map([[1, 2, 3, 4]], output_keys=["double"])))

    assert result["double"] == 8


def test_streaming_pipe_supports_final_output_aggregation():
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    collect = builder.add(CollectEvents(), name="collect")
    builder.connect(detect, collect, from_output="event", to_input="event")
    pipe = builder.build()

    result = pipe.run([1, 2, 3, 4], output_keys=["collect"])

    assert result["collect"] == [2, 4]


def test_stream_outputs_reject_multiple_consumers():
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    left = builder.add(DoubleEvent(), name="left")
    right = builder.add(DoubleEvent(), name="right")
    builder.connect(detect, left, from_output="event", to_input="event")
    builder.connect(detect, right, from_output="event", to_input="event")

    with pytest.raises(ValueError, match="multiple consumers"):
        builder.build()


def test_pipe_json_round_trip(tmp_path):
    builder = PipeBuilder()
    builder.add(AddOne(), name="add")
    pipe = builder.build()
    path = tmp_path / "workflow.json"

    pipe.to_json(path)
    restored = Pipe.from_json(path)
    result = restored.run(5, output_keys=["add"])

    saved = json.loads(path.read_text())
    assert saved["node_names"]["add"] in restored.tasks
    assert result["add"] == 6


def test_run_returns_terminal_outputs_by_default():
    builder = PipeBuilder()
    split = builder.add(Split(), name="split")
    total = builder.add(SumTwo(), name="sum")
    builder.connect(split, total, from_output="left", to_input="left")
    builder.connect(split, total, from_output="right", to_input="right")

    result = builder.build().run(4)

    assert result["sum"] == 9
    with pytest.raises(KeyError):
        _ = result["split"]


def test_results_require_explicit_port_for_multi_output_nodes():
    builder = PipeBuilder()
    builder.add(Split(), name="split")

    result = builder.build().run(3, output_keys=["split"])

    assert result["split", "left"] == 3
    assert result["split", "right"] == 4
    with pytest.raises(ValueError, match="multiple outputs"):
        _ = result["split"]


def test_strict_false_collects_errors_and_skips_dependents():
    builder = PipeBuilder()
    root = builder.add(Fail(), name="fail")
    downstream = builder.add(AddOne(), name="downstream")
    builder.connect(root, downstream, from_output="y", to_input="x")

    result = builder.build().run(2, output_keys=["fail", "downstream"], strict=False)

    assert not result.ok
    assert "fail" in result.errors
    assert result.skipped["downstream"] == "upstream dependency failed"
    assert "downstream" not in result.node_outputs


def test_executor_drops_unrequested_intermediate_outputs():
    builder = PipeBuilder()
    upstream = builder.add(AddOne(), name="upstream")
    downstream = builder.add(AddOne(), name="downstream")
    builder.connect(upstream, downstream, from_output="y", to_input="x")

    result = builder.build().run(2, output_keys=["downstream"])

    assert result["downstream"] == 4
    assert "upstream" not in result.node_outputs


def test_executor_retains_explicitly_requested_intermediate_outputs():
    builder = PipeBuilder()
    upstream = builder.add(AddOne(), name="upstream")
    downstream = builder.add(AddOne(), name="downstream")
    builder.connect(upstream, downstream, from_output="y", to_input="x")

    result = builder.build().run(2, output_keys=["upstream", "downstream"])

    assert result["upstream"] == 3
    assert result["downstream"] == 4
    assert result.node_names["upstream"] in result.node_outputs


def test_executor_retains_only_requested_port_for_multi_output_node():
    builder = PipeBuilder()
    builder.add(Split(), name="split")

    result = builder.build().run(3, output_keys=["split.left"])

    assert result["split", "left"] == 3
    assert result["split.left"] == 3
    assert "right" not in result.node_outputs[result._resolve_handle("split.left")]


def test_strict_true_raises_first_task_error():
    builder = PipeBuilder()
    builder.add(Fail(), name="fail")

    with pytest.raises(RuntimeError, match="bad input: 2"):
        builder.build().run(2, strict=True)


def test_pipe_fingerprint_does_not_depend_on_run_provenance():
    builder = PipeBuilder()
    builder.add(AddOne(), name="add")
    pipe = builder.build()
    original_fingerprint = pipe.fingerprint
    source_provenance = Provenance(
        pipe=pipe,
        derzug_version="test",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        python_version="3.12.0",
        system_info={"platform": "test", "machine": "test", "processor": "test"},
        metadata={"kind": "source"},
        source_provenance=(),
    )

    result = pipe.run(2, output_keys=["add"], provenance=source_provenance)

    assert pipe.fingerprint == original_fingerprint
    assert result.provenance is not None
    assert (
        result.provenance.source_provenance == source_provenance.to_source_provenance()
    )


def test_task_decorator_round_trip(tmp_path):
    builder = PipeBuilder()
    builder.add(add_two(), name="add_two")
    pipe = builder.build()
    path = tmp_path / "task_workflow.yaml"

    pipe.to_yaml(path)
    restored = Pipe.from_yaml(path)
    result = restored.run(5, output_keys=["add_two"])

    assert result["add_two"] == 7


def test_non_portable_task_code_path_fails_validation():
    def local_transform(x: int) -> int:
        return x + 1

    local_task = task(local_transform)
    builder = PipeBuilder()
    builder.add(local_task(), name="local")

    with pytest.raises(ValueError, match="not portable"):
        builder.build()


def test_results_get_and_has_output_helpers():
    builder = PipeBuilder()
    builder.add(Split(), name="split")

    result = builder.build().run(3, output_keys=["split"])

    assert result.has_output("split", "left")
    assert not result.has_output("split")
    assert result.get("split", "left") == 3


def test_executor_retains_requested_stream_final_output_only():
    builder = PipeBuilder()
    detect = builder.add(DetectEven(), name="detect")
    collect = builder.add(CollectEvents(), name="collect")
    builder.connect(detect, collect, from_output="event", to_input="event")

    result = builder.build().run([1, 2, 3, 4], output_keys=["collect"])

    assert result["collect"] == [2, 4]
    assert "detect" not in result.node_outputs
    assert result.get("split") is None
