"""Tests for code-to-widget helpers."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.code2widget import (
    WidgetFunctionSchema,
    _validate_unique_signal_names,
    function_to_widget,
    schema_from_function,
    widget_class_from_schema,
)
from derzug.utils.testing import widget_context


def test_schema_from_function_single_patch_round_trip():
    """A simple patch function becomes a one-input/one-output schema."""

    def transform(patch: dc.Patch) -> dc.Patch:
        return patch

    schema = schema_from_function(transform)

    assert isinstance(schema, WidgetFunctionSchema)
    assert schema.function_name == "transform"
    assert len(schema.inputs) == 1
    assert schema.inputs[0].name == "patch"
    assert schema.inputs[0].signal_type is dc.Patch
    assert len(schema.outputs) == 1
    assert schema.outputs[0].name == "result"
    assert schema.outputs[0].signal_type is dc.Patch
    assert schema.returns_dict is False


def test_schema_preserves_input_order_and_defaults():
    """Parameter order and defaults are reflected in the schema."""

    def transform(scale: float = 1.0, patch: dc.Patch | None = None) -> object:
        return patch

    schema = schema_from_function(transform)

    assert [item.name for item in schema.inputs] == ["scale", "patch"]
    assert schema.inputs[0].signal_type is float
    assert schema.inputs[0].has_default is True
    assert schema.inputs[0].default == 1.0
    assert schema.inputs[1].signal_type is dc.Patch


def test_unresolved_type_hints_fall_back_to_object():
    """Unknown annotations degrade safely to object ports."""

    def transform(arg):
        return arg

    transform.__annotations__ = {"arg": "MissingType", "return": "OtherMissing"}
    schema = schema_from_function(transform)

    assert schema.inputs[0].signal_type is object
    assert schema.outputs[0].signal_type is object


def test_dict_return_requires_explicit_output_names():
    """Dict-like return annotations need explicit output names."""

    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"x": patch}

    with pytest.raises(ValueError, match="output_names"):
        schema_from_function(transform)


def test_dict_return_with_output_names_uses_value_type():
    """Dict-like returns generate one output spec per configured name."""

    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch, "second": patch}

    schema = schema_from_function(transform, output_names=("first", "second"))

    assert schema.returns_dict is True
    assert [item.name for item in schema.outputs] == ["first", "second"]
    assert all(item.signal_type is dc.Patch for item in schema.outputs)


def test_input_name_collisions_after_normalization_are_rejected():
    """Distinct input names that normalize identically should fail schema creation."""
    with pytest.raises(ValueError, match="normalize to the same signal name"):
        _validate_unique_signal_names(
            (("a-b", "a_b"), ("a b", "a_b")),
            kind="input",
        )


def test_output_name_collisions_after_normalization_are_rejected():
    """Distinct output names that normalize identically should fail schema creation."""

    def transform(value: int) -> dict[str, int]:
        return {"a-b": value, "a b": value}

    with pytest.raises(ValueError, match="normalize to the same signal name"):
        schema_from_function(transform, output_names=("a-b", "a b"))


def test_varargs_are_rejected():
    """Dynamic widget generation does not support varargs in v1."""

    def transform(*patches: dc.Patch) -> object:
        return None

    with pytest.raises(ValueError, match="not supported"):
        schema_from_function(transform)


def test_widget_class_from_schema_emits_single_result(monkeypatch):
    """Generated widgets can receive inputs and emit a single output."""

    def transform(patch: dc.Patch) -> dc.Patch:
        return patch

    schema = schema_from_function(transform)
    widget_cls = widget_class_from_schema(
        schema,
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
        assert received[-1] is patch


def test_widget_uses_callable_defaults_for_unset_optional_inputs(monkeypatch):
    """Unset optional inputs should use the wrapped function's Python defaults."""
    captured: list[tuple[int, int]] = []

    def transform(value: int, scale: int = 3) -> int:
        captured.append((value, scale))
        return value * scale

    schema = schema_from_function(transform)
    widget_cls = widget_class_from_schema(
        schema,
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

        assert captured == [(2, 3)]
        assert received[-1] == 6


def test_widget_explicit_none_overrides_optional_default(monkeypatch):
    """Explicit None should be passed through instead of using the default."""
    captured: list[tuple[int, object]] = []

    def transform(value: int, patch: dc.Patch | None = None) -> object:
        captured.append((value, patch))
        return patch

    schema = schema_from_function(transform)
    widget_cls = widget_class_from_schema(
        schema,
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

        assert captured == [(4, None)]
        assert received[-1] is None


def test_widget_does_not_run_until_all_required_inputs_are_present(monkeypatch):
    """Generated widgets should stay idle until every required input is set."""
    call_count = 0

    def transform(left: int, right: int) -> int:
        nonlocal call_count
        call_count += 1
        return left + right

    schema = schema_from_function(transform)
    widget_cls = widget_class_from_schema(
        schema,
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

        assert call_count == 1
        assert received[-1] == 7


def test_widget_uses_defaults_and_waits_only_for_required_inputs(monkeypatch):
    """Only unset required inputs should block execution."""
    captured: list[tuple[int, int, int]] = []

    def transform(left: int, right: int, scale: int = 10) -> int:
        captured.append((left, right, scale))
        return (left + right) * scale

    schema = schema_from_function(transform)
    widget_cls = widget_class_from_schema(
        schema,
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

        assert captured == [(1, 2, 10)]
        assert received[-1] == 30


def test_widget_class_from_schema_emits_named_dict_outputs(monkeypatch):
    """Generated dict-output widgets dispatch one signal per configured key."""

    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch, "second": patch}

    schema = schema_from_function(transform, output_names=("first", "second"))
    widget_cls = widget_class_from_schema(
        schema,
        fn=transform,
        name="Generated Dict",
        description="Generated dict widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        first_received: list = []
        second_received: list = []
        monkeypatch.setattr(widget.Outputs.first, "send", first_received.append)
        monkeypatch.setattr(widget.Outputs.second, "send", second_received.append)
        patch = dc.get_example_patch("example_event_1")
        widget.set_patch(patch)
        assert first_received[-1] is patch
        assert second_received[-1] is patch


def test_widget_class_from_schema_missing_dict_keys_emit_none(monkeypatch):
    """Missing dict keys are emitted as None on the configured outputs."""

    def transform(patch: dc.Patch) -> dict[str, dc.Patch]:
        return {"first": patch}

    schema = schema_from_function(transform, output_names=("first", "second"))
    widget_cls = widget_class_from_schema(
        schema,
        fn=transform,
        name="Generated Dict",
        description="Generated dict widget",
        icon="icons/PythonScript.svg",
        category="Processing",
        priority=1,
    )

    with widget_context(widget_cls) as widget:
        first_received: list = []
        second_received: list = []
        monkeypatch.setattr(widget.Outputs.first, "send", first_received.append)
        monkeypatch.setattr(widget.Outputs.second, "send", second_received.append)
        patch = dc.get_example_patch("example_event_1")
        widget.set_patch(patch)
        assert first_received[-1] is patch
        assert second_received[-1] is None


def test_function_to_widget_wraps_schema_and_widget_generation(monkeypatch):
    """Convenience helper returns a usable widget class."""

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
        assert received[-1] == 3
