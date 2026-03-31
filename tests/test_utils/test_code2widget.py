# ruff: noqa: D103

"""Tests for task-backed code-to-widget helpers."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.code2widget import (
    _validate_unique_signal_names,
    function_to_widget,
    task_from_callable,
    widget_class_from_callable,
)
from derzug.utils.testing import wait_for_widget_idle, widget_context
from derzug.workflow import PipeBuilder
from derzug.workflow.widget_tasks import CallableTaskAdapter


def module_level_transform(patch: dc.Patch) -> dc.Patch:
    return patch


def module_level_dict_transform(patch: dc.Patch) -> dict[str, dc.Patch]:
    return {"first": patch, "second": patch}


def test_task_from_callable_single_patch_round_trip():
    def transform(patch: dc.Patch) -> dc.Patch:
        return patch

    task_type = task_from_callable(transform)
    task = task_type()
    patch = dc.get_example_patch("example_event_1")

    assert task_type.scalar_input_variables()["patch"] is dc.Patch
    assert tuple(task_type.scalar_output_variables()) == ("result",)
    assert task.run(patch=patch) is patch


def test_task_from_callable_preserves_required_inputs_and_defaults():
    def transform(scale: float = 1.0, patch: dc.Patch | None = None) -> object:
        return patch

    task_type = task_from_callable(transform)

    assert tuple(task_type.scalar_input_variables()) == ("scale", "patch")
    assert task_type.required_scalar_inputs() == ()
    assert task_type().run(scale=1.0, patch=None) is None


def test_unresolved_type_hints_fall_back_to_object():
    def transform(arg):
        return arg

    transform.__annotations__ = {"arg": "MissingType", "return": "OtherMissing"}
    task_type = task_from_callable(transform)

    assert task_type.scalar_input_variables()["arg"] is object
    assert task_type.scalar_output_variables()["result"] is object


def test_dict_return_requires_explicit_output_names():
    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"x": patch}

    with pytest.raises(ValueError, match="output_names"):
        task_from_callable(transform)


def test_dict_return_with_output_names_uses_named_outputs():
    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch, "second": patch}

    task_type = task_from_callable(transform, output_names=("first", "second"))

    assert tuple(task_type.scalar_output_variables()) == ("first", "second")


def test_input_name_collisions_after_normalization_are_rejected():
    with pytest.raises(ValueError, match="normalize to the same signal name"):
        _validate_unique_signal_names(
            (("a-b", "a_b"), ("a b", "a_b")),
            kind="input",
        )


def test_output_name_collisions_after_normalization_are_rejected():
    def transform(value: int) -> dict[str, int]:
        return {"a-b": value, "a b": value}

    with pytest.raises(ValueError, match="normalize to the same signal name"):
        task_from_callable(transform, output_names=("a-b", "a b"))


def test_varargs_are_rejected():
    def transform(*patches: dc.Patch) -> object:
        return None

    with pytest.raises(ValueError, match="not supported"):
        task_from_callable(transform)


def test_widget_class_from_callable_emits_single_result(monkeypatch):
    def transform(patch: dc.Patch) -> dc.Patch:
        return patch

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated",
        description="Generated widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        patch = dc.get_example_patch("example_event_1")
        widget.set_patch(patch)
        wait_for_widget_idle(widget)
        assert received[-1] is patch


def test_widget_uses_callable_defaults_for_unset_optional_inputs(monkeypatch):
    captured: list[tuple[int, int]] = []

    def transform(value: int, scale: int = 3) -> int:
        captured.append((value, scale))
        return value * scale

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated",
        description="Generated widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        widget.set_value(2)
        wait_for_widget_idle(widget)

        assert captured == [(2, 3)]
        assert received[-1] == 6


def test_widget_explicit_none_overrides_optional_default(monkeypatch):
    captured: list[tuple[int, object]] = []

    def transform(value: int, patch: dc.Patch | None = None) -> object:
        captured.append((value, patch))
        return patch

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated",
        description="Generated widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        widget.set_patch(None)
        widget.set_value(4)
        wait_for_widget_idle(widget)

        assert captured == [(4, None)]
        assert received[-1] is None


def test_widget_does_not_run_until_all_required_inputs_are_present(monkeypatch):
    call_count = 0

    def transform(left: int, right: int) -> int:
        nonlocal call_count
        call_count += 1
        return left + right

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated",
        description="Generated widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        widget.set_left(2)

        assert call_count == 0
        assert received[-1] is None

        widget.set_right(5)
        wait_for_widget_idle(widget)

        assert call_count == 1
        assert received[-1] == 7


def test_widget_uses_defaults_and_waits_only_for_required_inputs(monkeypatch):
    captured: list[tuple[int, int, int]] = []

    def transform(left: int, right: int, scale: int = 10) -> int:
        captured.append((left, right, scale))
        return (left + right) * scale

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated",
        description="Generated widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        widget.set_left(1)

        assert captured == []
        assert received[-1] is None

        widget.set_right(2)
        wait_for_widget_idle(widget)

        assert captured == [(1, 2, 10)]
        assert received[-1] == 30


def test_widget_class_from_callable_emits_named_dict_outputs(monkeypatch):
    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch, "second": patch}

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated Dict",
        description="Generated dict widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
        output_names=("first", "second"),
    )

    with widget_context(widget_cls) as widget:
        first_received: list = []
        second_received: list = []
        monkeypatch.setattr(widget.Outputs.first, "send", first_received.append)
        monkeypatch.setattr(widget.Outputs.second, "send", second_received.append)
        patch = dc.get_example_patch("example_event_1")
        widget.set_patch(patch)
        wait_for_widget_idle(widget)
        assert first_received[-1] is patch
        assert second_received[-1] is patch


def test_widget_class_from_callable_missing_dict_keys_emit_none(monkeypatch):
    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch}

    widget_cls = widget_class_from_callable(
        fn=transform,
        name="Generated Dict",
        description="Generated dict widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
        output_names=("first", "second"),
    )

    with widget_context(widget_cls) as widget:
        first_received: list = []
        second_received: list = []
        monkeypatch.setattr(widget.Outputs.first, "send", first_received.append)
        monkeypatch.setattr(widget.Outputs.second, "send", second_received.append)
        patch = dc.get_example_patch("example_event_1")
        widget.set_patch(patch)
        wait_for_widget_idle(widget)
        assert first_received[-1] is patch
        assert second_received[-1] is None


def test_function_to_widget_wraps_callable_generation(monkeypatch):
    def transform(value: int) -> int:
        return value + 1

    widget_cls = function_to_widget(
        transform,
        name="Adder",
        description="Adds one",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        received: list = []
        monkeypatch.setattr(widget.Outputs.result, "send", received.append)
        widget.set_value(2)
        wait_for_widget_idle(widget)
        assert received[-1] == 3


def test_task_from_callable_plain_function_builds_and_round_trips(tmp_path):
    task_type = task_from_callable(module_level_transform)
    builder = PipeBuilder()
    builder.add(task_type(), name="transform")
    pipe = builder.build()
    path = tmp_path / "callable_task.yaml"

    pipe.to_yaml(path)
    restored = type(pipe).from_yaml(path)
    patch = dc.get_example_patch("example_event_1")

    assert isinstance(
        restored.tasks[restored.get_handle("transform")],
        CallableTaskAdapter,
    )
    assert restored.run(patch=patch, output_keys=["transform"])["transform"] is patch


def test_task_from_callable_dict_output_round_trips(tmp_path):
    task_type = task_from_callable(
        module_level_dict_transform, output_names=("first", "second")
    )
    builder = PipeBuilder()
    builder.add(task_type(), name="transform")
    pipe = builder.build()
    path = tmp_path / "dict_callable_task.yaml"

    pipe.to_yaml(path)
    restored = type(pipe).from_yaml(path)
    patch = dc.get_example_patch("example_event_1")
    result = restored.run(patch=patch, output_keys=["transform"])

    assert isinstance(
        restored.tasks[restored.get_handle("transform")],
        CallableTaskAdapter,
    )
    assert result["transform", "first"] is patch
    assert result["transform", "second"] is patch
