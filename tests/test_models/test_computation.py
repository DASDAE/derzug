"""Tests for computation models and introspection helpers."""

from __future__ import annotations

import pytest
from derzug.models.computation import (
    ComputationNode,
    ComputationResult,
    ComputationSpec,
    Connection,
)


def test_function_spec_splits_inputs_parameters_and_docs():
    """Defaulted function arguments become parameters, required ones become inputs."""

    def transform(patch: object, scale: float = 2.0) -> object:
        """
        Scale one patch.

        Parameters
        ----------
        patch : object
            Input patch to scale.
        scale : float
            Scalar multiplier.

        Returns
        -------
        processed : object
            Scaled patch.

        Raises
        ------
        ValueError
            Raised when the patch cannot be scaled.

        Warns
        -----
        RuntimeWarning
            Warns when scaling clips the data.
        """
        return patch

    spec = ComputationSpec.from_function(transform)

    assert spec.kind == "function"
    assert tuple(spec.inputs) == ("patch",)
    assert tuple(spec.parameters) == ("scale",)
    assert spec.inputs["patch"].description == "Input patch to scale."
    assert spec.parameters["scale"].default == 2.0
    assert tuple(spec.outputs) == ("processed",)
    assert spec.outputs["processed"].description == "Scaled patch."
    assert spec.documented_exceptions[0].name == "ValueError"
    assert spec.documented_warnings[0].name == "RuntimeWarning"


def test_multi_output_tuple_uses_docstring_names():
    """Tuple returns derive output names from a NumPy-style Returns section."""

    def transform(value: int) -> tuple[int, int]:
        """
        Duplicate one value.

        Returns
        -------
        left : int
            First output.
        right : int
            Second output.
        """
        return value, value

    spec = ComputationSpec.from_function(transform)

    assert tuple(spec.outputs) == ("left", "right")
    assert spec.outputs["left"].annotation == "int"
    assert spec.outputs["right"].annotation == "int"


def test_multi_output_without_names_requires_override():
    """Unnamed multi-output returns must receive an explicit output_names override."""

    def transform(value: int) -> tuple[int, int]:
        return value, value

    with pytest.raises(ValueError, match="output_names"):
        ComputationSpec.from_function(transform)


def test_multi_output_explicit_names_override_docstring_names():
    """Explicit output names should win over names parsed from the docstring."""

    def transform(value: int) -> tuple[int, int]:
        """
        Duplicate one value.

        Returns
        -------
        left : int
            First output.
        right : int
            Second output.
        """
        return value, value

    spec = ComputationSpec.from_function(transform, output_names=("x", "y"))

    assert tuple(spec.outputs) == ("x", "y")


def test_function_overrides_can_reclassify_inputs_and_parameters():
    """Explicit name overrides should control input vs parameter classification."""

    def transform(scale: float, patch: object | None = None) -> object:
        return patch

    spec = ComputationSpec.from_function(
        transform,
        input_names=("patch",),
        parameter_names=("scale",),
    )

    assert tuple(spec.parameters) == ("scale",)
    assert tuple(spec.inputs) == ("patch",)
    assert spec.parameters["scale"].required is True
    assert spec.inputs["patch"].required is False


def test_class_spec_uses_init_and_call_signatures():
    """Callable classes split constructor parameters from runtime inputs."""

    class OffsetComputation:
        """Callable computation used in tests."""

        def __init__(self, scale: int = 2):
            """
            Initialize the computation.

            Parameters
            ----------
            scale : int
                Scalar multiplier.
            """
            self.scale = scale

        def __call__(self, value: int) -> int:
            """
            Apply the scale.

            Parameters
            ----------
            value : int
                Value to scale.

            Returns
            -------
            result : int
                Scaled result.

            Raises
            ------
            ValueError
                Raised when the value is invalid.
            """
            return value * self.scale

    spec = ComputationSpec.from_class(OffsetComputation)

    assert spec.kind == "callable_class"
    assert tuple(spec.parameters) == ("scale",)
    assert tuple(spec.inputs) == ("value",)
    assert tuple(spec.outputs) == ("result",)
    assert spec.parameters["scale"].description == "Scalar multiplier."
    assert spec.inputs["value"].description == "Value to scale."
    assert spec.documented_exceptions[0].name == "ValueError"


def test_missing_warning_and_exception_docs_are_allowed():
    """Model creation should succeed even when Warns/Raises sections are absent."""

    def transform(value: int) -> int:
        """
        Increment a value.

        Returns
        -------
        result : int
            Incremented value.
        """
        return value + 1

    spec = ComputationSpec.from_function(transform)

    assert spec.documented_exceptions == ()
    assert spec.documented_warnings == ()


def test_node_invoke_uses_defaults_and_serialization_excludes_runtime_state():
    """Node invocation should respect callable defaults and hide transient state."""

    def transform(value: int, scale: int = 3) -> int:
        return value * scale

    node = ComputationNode.from_function("scale-node", transform)
    node.state.input_values["value"] = 4

    result = node.invoke()

    assert isinstance(result, ComputationResult)
    assert result.ok is True
    assert result.value == 12
    assert node.state.last_invocation == result
    dumped = node.model_dump()
    assert dumped["state"]["input_values"] == {"value": 4}
    assert dumped["state"]["param_values"] == {}
    assert "last_invocation" not in dumped["state"]


def test_node_invoke_from_callable_class_uses_constructor_parameters():
    """Callable-class nodes instantiate with stored parameter values first."""

    class OffsetComputation:
        def __init__(self, offset: int = 1):
            self.offset = offset

        def __call__(self, value: int) -> int:
            return value + self.offset

    node = ComputationNode.from_class("offset-node", OffsetComputation)
    node.state.param_values["offset"] = 5
    node.state.input_values["value"] = 8

    result = node.invoke()

    assert result.ok is True
    assert result.value == 13


def test_node_invoke_returns_failed_result_for_callable_errors():
    """Invocation failures should be captured in the returned result object."""

    def transform(value: int) -> int:
        raise ValueError("boom")

    node = ComputationNode.from_function("broken-node", transform)
    node.state.input_values["value"] = 3

    result = node.invoke()

    assert result.ok is False
    assert result.value is None
    assert result.message == "boom"
    assert result.exception_type == "ValueError"
    assert "ValueError: boom" in result.traceback_text
    assert node.state.last_invocation == result


def test_spec_invoke_returns_failed_result_for_missing_required_inputs():
    """Validation failures should use the same result wrapper as callable errors."""

    def transform(value: int) -> int:
        return value

    spec = ComputationSpec.from_function(transform)

    result = spec.invoke()

    assert result.ok is False
    assert result.message == "missing required input(s): value"
    assert result.exception_type == "ValueError"


def test_computation_result_unwrap_raises_on_failed_results():
    """Failed results should raise a deterministic runtime error when unwrapped."""
    result = ComputationResult.from_exception(ValueError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        result.unwrap()


def test_connection_round_trips():
    """Graph connections store only typed source and target endpoints."""
    connection = Connection(
        source_node="left",
        source_port="patch",
        target_node="right",
        target_port="patch",
    )

    assert connection.model_dump() == {
        "source_node": "left",
        "source_port": "patch",
        "target_node": "right",
        "target_port": "patch",
    }


def test_unsupported_signatures_are_rejected():
    """Variadic and positional-only signatures should fail clearly."""

    def variadic(*values: int) -> int:
        return sum(values)

    with pytest.raises(ValueError, match="not supported"):
        ComputationSpec.from_function(variadic)
