"""
Models for describing reproducible computations and graph connections.
"""

from __future__ import annotations

import importlib
import inspect
import traceback
import types
import typing
from collections.abc import Callable
from types import UnionType
from typing import Any, Literal

from derzug.utils.docstring import ParsedDocEntry, parse_numpy_docstring
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

_EMPTY = inspect.Signature.empty


class DocumentedIssue(BaseModel):
    """One warning/exception documented in a callable docstring."""

    name: str
    description: str = ""


class ParameterSpec(BaseModel):
    """One user-configurable computation parameter."""

    name: str
    annotation: str = "object"
    required: bool = True
    default: Any = None
    description: str = ""


class PortSpec(BaseModel):
    """One named graph input or output port."""

    name: str
    annotation: str = "object"
    required: bool = True
    description: str = ""


class ComputationResult(BaseModel):
    """One runtime result produced by invoking a computation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ok: bool
    value: Any = None
    message: str | None = None
    exception_type: str | None = None
    exception_module: str | None = None
    traceback_text: str | None = None
    error: BaseException | None = Field(default=None, exclude=True)

    @classmethod
    def from_value(cls, value: Any) -> ComputationResult:
        """Build one successful result from a raw callable return value."""
        return cls(ok=True, value=value)

    @classmethod
    def from_exception(cls, exc: BaseException) -> ComputationResult:
        """Build one failed result from an exception raised during invocation."""
        return cls(
            ok=False,
            message=str(exc),
            exception_type=type(exc).__name__,
            exception_module=type(exc).__module__,
            traceback_text="".join(traceback.format_exception(exc)),
            error=exc,
        )

    def is_ok(self) -> bool:
        """Return True when the computation completed successfully."""
        return self.ok

    def is_err(self) -> bool:
        """Return True when the computation failed."""
        return not self.ok

    def unwrap(self) -> Any:
        """Return the value or raise a runtime error describing the failure."""
        if self.ok:
            return self.value
        detail = self.message or "computation failed"
        raise RuntimeError(detail)


class ComputationSpec(BaseModel):
    """
    Immutable description of a callable computation.

    Functions store their runtime parameters and graph inputs on one callable.
    Callable classes split constructor parameters from runtime inputs.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    code_path: str
    kind: Literal["function", "callable_class"]
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    inputs: dict[str, PortSpec] = Field(default_factory=dict)
    outputs: dict[str, PortSpec] = Field(default_factory=dict)
    documented_exceptions: tuple[DocumentedIssue, ...] = ()
    documented_warnings: tuple[DocumentedIssue, ...] = ()
    parameter_order: tuple[str, ...] = ()
    input_order: tuple[str, ...] = ()
    output_order: tuple[str, ...] = ()
    _callable_obj: Callable[..., Any] | type | None = PrivateAttr(default=None)

    @classmethod
    def from_function(
        cls,
        fn,
        *,
        output_names: tuple[str, ...] | None = None,
        input_names: tuple[str, ...] | None = None,
        parameter_names: tuple[str, ...] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> ComputationSpec:
        """Build a computation spec from a Python function."""
        if not callable(fn):
            raise TypeError("fn must be callable")

        overrides = _resolve_function_overrides(
            metadata_overrides=metadata_overrides,
            output_names=output_names,
            input_names=input_names,
            parameter_names=parameter_names,
        )
        signature, type_hints, docs = _inspect_callable(fn)
        parameters, inputs, parameter_order, input_order = _split_function_signature(
            signature=signature,
            type_hints=type_hints,
            parameter_docs=docs.parameters,
            input_names=overrides.input_names,
            parameter_names=overrides.parameter_names,
        )

        outputs, output_order = _outputs_from_return_annotation(
            type_hints.get("return", signature.return_annotation),
            docs.returns,
            output_names=overrides.output_names,
        )

        spec = cls(
            code_path=_code_path_for_object(fn),
            kind="function",
            parameters=parameters,
            inputs=inputs,
            outputs=outputs,
            documented_exceptions=_issues_from_doc_entries(docs.raises),
            documented_warnings=_issues_from_doc_entries(docs.warns),
            parameter_order=tuple(parameter_order),
            input_order=tuple(input_order),
            output_order=tuple(output_order),
        )
        spec._callable_obj = fn
        return spec

    @classmethod
    def from_class(
        cls,
        klass: type,
        *,
        output_names: tuple[str, ...] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> ComputationSpec:
        """Build a computation spec from a callable class definition."""
        if not inspect.isclass(klass):
            raise TypeError("klass must be a class")
        if "__call__" not in klass.__dict__:
            raise TypeError("klass must define __call__")

        resolved_output_names = _resolve_output_names(
            metadata_overrides=metadata_overrides,
            output_names=output_names,
        )

        init_sig, init_hints, init_docs = _inspect_callable(klass.__init__)
        parameters, parameter_order = _parameter_specs_from_signature(
            signature=init_sig,
            type_hints=init_hints,
            parameter_docs=init_docs.parameters,
        )

        call_sig, call_hints, call_docs = _inspect_callable(klass.__call__)
        inputs, input_order = _input_specs_from_signature(
            signature=call_sig,
            type_hints=call_hints,
            parameter_docs=call_docs.parameters,
        )

        outputs, output_order = _outputs_from_return_annotation(
            call_hints.get("return", call_sig.return_annotation),
            call_docs.returns,
            output_names=resolved_output_names,
        )

        spec = cls(
            code_path=_code_path_for_object(klass),
            kind="callable_class",
            parameters=parameters,
            inputs=inputs,
            outputs=outputs,
            documented_exceptions=_issues_from_doc_entries(call_docs.raises),
            documented_warnings=_issues_from_doc_entries(call_docs.warns),
            parameter_order=tuple(parameter_order),
            input_order=tuple(input_order),
            output_order=tuple(output_order),
        )
        spec._callable_obj = klass
        return spec

    def snapshot(self) -> ComputationSpec:
        """Return a deep copy suitable for one isolated run."""
        snap = self.model_copy(deep=True)
        snap._callable_obj = self._callable_obj
        return snap

    def get_callable(self) -> Callable[..., Any] | type:
        """Return the bound runtime object, importing it on demand if needed."""
        if self._callable_obj is not None:
            return self._callable_obj
        obj = _import_from_code_path(self.code_path)
        self._callable_obj = obj
        return obj

    def invoke(
        self,
        *,
        param_values: dict[str, Any] | None = None,
        input_values: dict[str, Any] | None = None,
    ) -> ComputationResult:
        """Invoke the described computation using current parameter/input values."""
        param_values = param_values or {}
        input_values = input_values or {}

        try:
            _validate_required_values(self.parameters, param_values, kind="parameter")
            _validate_required_values(self.inputs, input_values, kind="input")

            if self.kind == "function":
                return _invoke_function_spec(self, param_values, input_values)

            return _invoke_callable_class_spec(self, param_values, input_values)
        except Exception as exc:
            return ComputationResult.from_exception(exc)


class ComputationState(BaseModel):
    """Mutable runtime values for one computation node."""

    param_values: dict[str, Any] = Field(default_factory=dict)
    input_values: dict[str, Any] = Field(default_factory=dict)
    last_invocation: ComputationResult | None = Field(default=None, exclude=True)

    def snapshot(self) -> ComputationState:
        """Return a deep copy suitable for one isolated run."""
        return self.model_copy(deep=True)


class ComputationNode(BaseModel):
    """One graph node storing computation identity and current values."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    node_id: str
    spec: ComputationSpec
    state: ComputationState = Field(default_factory=ComputationState)

    @classmethod
    def from_function(
        cls,
        node_id: str,
        fn,
        *,
        output_names: tuple[str, ...] | None = None,
        input_names: tuple[str, ...] | None = None,
        parameter_names: tuple[str, ...] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> ComputationNode:
        """Convenience constructor from a function."""
        return cls(
            node_id=node_id,
            spec=ComputationSpec.from_function(
                fn,
                output_names=output_names,
                input_names=input_names,
                parameter_names=parameter_names,
                metadata_overrides=metadata_overrides,
            ),
        )

    @classmethod
    def from_class(
        cls,
        node_id: str,
        klass: type,
        *,
        output_names: tuple[str, ...] | None = None,
        metadata_overrides: dict[str, Any] | None = None,
    ) -> ComputationNode:
        """Convenience constructor from a callable class."""
        return cls(
            node_id=node_id,
            spec=ComputationSpec.from_class(
                klass,
                output_names=output_names,
                metadata_overrides=metadata_overrides,
            ),
        )

    def snapshot(self) -> ComputationNode:
        """Return a deep copy suitable for one isolated run."""
        snap = self.model_copy(deep=True)
        snap.spec._callable_obj = self.spec._callable_obj
        return snap

    def invoke(self) -> ComputationResult:
        """Invoke this node and store the latest result/error summary."""
        result = self.spec.invoke(
            param_values=self.state.param_values,
            input_values=self.state.input_values,
        )
        self.state.last_invocation = result
        return result


class Connection(BaseModel):
    """One typed edge between two computation nodes."""

    source_node: str
    source_port: str
    target_node: str
    target_port: str


class _FunctionOverrides(BaseModel):
    """Resolved per-function metadata overrides."""

    output_names: tuple[str, ...] | None = None
    input_names: tuple[str, ...] | None = None
    parameter_names: tuple[str, ...] | None = None


def _resolve_function_overrides(
    *,
    metadata_overrides: dict[str, Any] | None,
    output_names: tuple[str, ...] | None,
    input_names: tuple[str, ...] | None,
    parameter_names: tuple[str, ...] | None,
) -> _FunctionOverrides:
    """Merge direct overrides with metadata overrides for function specs."""
    metadata_overrides = metadata_overrides or {}
    return _FunctionOverrides(
        output_names=output_names or metadata_overrides.get("output_names"),
        input_names=input_names or metadata_overrides.get("input_names"),
        parameter_names=parameter_names or metadata_overrides.get("parameter_names"),
    )


def _resolve_output_names(
    *,
    metadata_overrides: dict[str, Any] | None,
    output_names: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    """Resolve output names, preferring the explicit method argument."""
    metadata_overrides = metadata_overrides or {}
    return output_names or metadata_overrides.get("output_names")


def _inspect_callable(
    fn: Callable[..., Any],
) -> tuple[inspect.Signature, dict[str, object], Any]:
    """Collect signature, resolved type hints, and parsed docs for one callable."""
    signature = inspect.signature(fn)
    type_hints = _safe_get_type_hints(fn)

    # Parsing once keeps the higher-level constructors focused on model assembly.
    docs = parse_numpy_docstring(inspect.getdoc(fn) or "")
    return signature, type_hints, docs


def _split_function_signature(
    *,
    signature: inspect.Signature,
    type_hints: dict[str, object],
    parameter_docs: dict[str, str],
    input_names: tuple[str, ...] | None,
    parameter_names: tuple[str, ...] | None,
) -> tuple[dict[str, ParameterSpec], dict[str, PortSpec], list[str], list[str]]:
    """Split one function signature into runtime parameters and graph inputs."""
    parameters: dict[str, ParameterSpec] = {}
    inputs: dict[str, PortSpec] = {}
    parameter_order: list[str] = []
    input_order: list[str] = []

    # Name-based overrides should be checked against sets once, not per branch.
    input_name_set = set(input_names or ())
    parameter_name_set = set(parameter_names or ())

    for parameter in signature.parameters.values():
        if _skip_parameter(parameter):
            continue

        if _is_function_input(
            parameter=parameter,
            input_names=input_names,
            parameter_names=parameter_names,
            input_name_set=input_name_set,
            parameter_name_set=parameter_name_set,
        ):
            inputs[parameter.name] = _port_spec_from_parameter(
                parameter=parameter,
                type_hints=type_hints,
                parameter_docs=parameter_docs,
            )
            input_order.append(parameter.name)
            continue

        parameters[parameter.name] = _parameter_spec_from_parameter(
            parameter=parameter,
            type_hints=type_hints,
            parameter_docs=parameter_docs,
        )
        parameter_order.append(parameter.name)

    return parameters, inputs, parameter_order, input_order


def _parameter_specs_from_signature(
    *,
    signature: inspect.Signature,
    type_hints: dict[str, object],
    parameter_docs: dict[str, str],
) -> tuple[dict[str, ParameterSpec], list[str]]:
    """Build constructor parameter specs from one signature."""
    parameters: dict[str, ParameterSpec] = {}
    parameter_order: list[str] = []

    for parameter in signature.parameters.values():
        if _skip_parameter(parameter):
            continue

        parameters[parameter.name] = _parameter_spec_from_parameter(
            parameter=parameter,
            type_hints=type_hints,
            parameter_docs=parameter_docs,
        )
        parameter_order.append(parameter.name)

    return parameters, parameter_order


def _input_specs_from_signature(
    *,
    signature: inspect.Signature,
    type_hints: dict[str, object],
    parameter_docs: dict[str, str],
) -> tuple[dict[str, PortSpec], list[str]]:
    """Build runtime input port specs from one signature."""
    inputs: dict[str, PortSpec] = {}
    input_order: list[str] = []

    for parameter in signature.parameters.values():
        if _skip_parameter(parameter):
            continue

        inputs[parameter.name] = _port_spec_from_parameter(
            parameter=parameter,
            type_hints=type_hints,
            parameter_docs=parameter_docs,
        )
        input_order.append(parameter.name)

    return inputs, input_order


def _skip_parameter(parameter: inspect.Parameter) -> bool:
    """Validate one parameter and skip sentinel receiver arguments."""
    _validate_parameter_kind(parameter)
    return parameter.name == "self"


def _is_function_input(
    *,
    parameter: inspect.Parameter,
    input_names: tuple[str, ...] | None,
    parameter_names: tuple[str, ...] | None,
    input_name_set: set[str],
    parameter_name_set: set[str],
) -> bool:
    """Classify one function argument as a graph input or stored parameter."""
    has_default = parameter.default is not _EMPTY

    # Explicit input names take precedence over all other heuristics.
    if input_names is not None:
        return parameter.name in input_name_set

    # Parameter-name overrides invert the default required-vs-defaulted split.
    if parameter_names is not None:
        return parameter.name not in parameter_name_set

    # Without overrides, required args are runtime inputs and defaults are settings.
    return not has_default


def _parameter_spec_from_parameter(
    *,
    parameter: inspect.Parameter,
    type_hints: dict[str, object],
    parameter_docs: dict[str, str],
) -> ParameterSpec:
    """Convert one inspected parameter into a stored parameter spec."""
    annotation = type_hints.get(parameter.name, parameter.annotation)
    has_default = parameter.default is not _EMPTY
    return ParameterSpec(
        name=parameter.name,
        annotation=_annotation_to_string(annotation),
        required=not has_default,
        default=None if not has_default else parameter.default,
        description=parameter_docs.get(parameter.name, ""),
    )


def _port_spec_from_parameter(
    *,
    parameter: inspect.Parameter,
    type_hints: dict[str, object],
    parameter_docs: dict[str, str],
) -> PortSpec:
    """Convert one inspected parameter into an input/output port spec."""
    annotation = type_hints.get(parameter.name, parameter.annotation)
    return PortSpec(
        name=parameter.name,
        annotation=_annotation_to_string(annotation),
        required=parameter.default is _EMPTY,
        description=parameter_docs.get(parameter.name, ""),
    )


def _invoke_function_spec(
    spec: ComputationSpec,
    param_values: dict[str, Any],
    input_values: dict[str, Any],
) -> ComputationResult:
    """Invoke one function-backed computation spec."""
    fn = spec.get_callable()

    # Preserve parameter ordering first, then let runtime inputs fill the rest.
    kwargs = _kwargs_from_named_specs(spec.parameters, param_values)
    kwargs.update(_kwargs_from_named_specs(spec.inputs, input_values))
    return ComputationResult.from_value(fn(**kwargs))


def _invoke_callable_class_spec(
    spec: ComputationSpec,
    param_values: dict[str, Any],
    input_values: dict[str, Any],
) -> ComputationResult:
    """Invoke one callable-class-backed computation spec."""
    klass = spec.get_callable()

    # Constructor parameters are persisted on the node, inputs arrive at call time.
    init_kwargs = _kwargs_from_named_specs(spec.parameters, param_values)
    call_kwargs = _kwargs_from_named_specs(spec.inputs, input_values)
    instance = klass(**init_kwargs)
    return ComputationResult.from_value(instance(**call_kwargs))


def _safe_get_type_hints(obj) -> dict[str, object]:
    """Return resolved type hints when possible, else raw annotations."""
    try:
        globalns = getattr(obj, "__globals__", None)
        return typing.get_type_hints(obj, globalns=globalns)
    except Exception:
        return dict(getattr(obj, "__annotations__", {}))


def _annotation_to_string(annotation: object) -> str:
    """Return a stable string form for one annotation."""
    if annotation in (_EMPTY, inspect._empty, None):
        return "object"
    if isinstance(annotation, str):
        return annotation
    if getattr(annotation, "__module__", "") == "builtins":
        return annotation.__name__
    text = str(annotation)
    return text.replace("typing.", "")


def _code_path_for_object(obj: object) -> str:
    """Return one stable module/qualname string for a runtime object."""
    module = getattr(obj, "__module__", "__main__")
    qualname = getattr(
        obj,
        "__qualname__",
        getattr(obj, "__name__", type(obj).__name__),
    )
    return f"{module}:{qualname}"


def _import_from_code_path(code_path: str) -> object:
    """Resolve one module:qualname path back into a Python object."""
    module_name, _, qualname = code_path.partition(":")
    if not module_name or not qualname:
        raise ValueError(f"invalid code path {code_path!r}")
    module = importlib.import_module(module_name)
    obj: object = module
    for part in qualname.split("."):
        if part == "<locals>":
            raise ValueError(f"cannot import local object from {code_path!r}")
        obj = getattr(obj, part)
    return obj


def _validate_parameter_kind(parameter: inspect.Parameter) -> None:
    """Reject unsupported callable signature features."""
    if parameter.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    ):
        raise ValueError(
            "positional-only parameters, *args, and **kwargs are not supported"
        )


def _outputs_from_return_annotation(
    annotation: object,
    return_entries: tuple[ParsedDocEntry, ...],
    *,
    output_names: tuple[str, ...] | None,
) -> tuple[dict[str, PortSpec], tuple[str, ...]]:
    """Build named output ports from a return annotation and docstring metadata."""
    annotation = _unwrap_optional(annotation)
    doc_names = tuple(entry.name for entry in return_entries if entry.name)
    descriptions_by_name = {
        entry.name: entry.description for entry in return_entries if entry.name
    }

    if _return_is_dict_like(annotation):
        names = output_names or doc_names
        if not names:
            raise ValueError(
                "multi-output dict-like returns require docstring names or output_names"
            )
        value_annotation = _dict_value_annotation(annotation)
        outputs = {
            name: PortSpec(
                name=name,
                annotation=_annotation_to_string(value_annotation),
                required=True,
                description=descriptions_by_name.get(name, ""),
            )
            for name in names
        }
        return outputs, tuple(names)

    tuple_args = _tuple_annotations(annotation)
    if tuple_args is not None:
        names = output_names or doc_names
        if not names:
            raise ValueError(
                "multi-output tuple returns require docstring names or output_names"
            )
        if len(names) != len(tuple_args):
            raise ValueError("output_names must match the number of returned values")
        outputs = {
            name: PortSpec(
                name=name,
                annotation=_annotation_to_string(item_annotation),
                required=True,
                description=descriptions_by_name.get(name, ""),
            )
            for name, item_annotation in zip(names, tuple_args, strict=False)
        }
        return outputs, tuple(names)

    single_name = doc_names[0] if len(doc_names) == 1 else "result"
    description = descriptions_by_name.get(single_name, "")
    if not description and return_entries:
        description = return_entries[0].description
    outputs = {
        single_name: PortSpec(
            name=single_name,
            annotation=_annotation_to_string(annotation),
            required=True,
            description=description,
        )
    }
    return outputs, (single_name,)


def _return_is_dict_like(annotation: object) -> bool:
    """Return True when one return annotation is dict-like."""
    origin = typing.get_origin(annotation)
    return annotation is dict or origin is dict


def _dict_value_annotation(annotation: object) -> object:
    """Return the dict value annotation, defaulting to object."""
    args = typing.get_args(annotation)
    return args[1] if len(args) == 2 else object


def _tuple_annotations(annotation: object) -> tuple[object, ...] | None:
    """Return tuple item annotations for fixed-size tuple returns."""
    origin = typing.get_origin(annotation)
    if annotation is tuple or origin is tuple:
        args = typing.get_args(annotation)
        if not args:
            return None
        if len(args) == 2 and args[1] is Ellipsis:
            return None
        return tuple(args)
    return None


def _unwrap_optional(annotation: object) -> object:
    """Strip Optional / X | None wrappers, returning the inner type."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, UnionType, types.UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _issues_from_doc_entries(
    entries: tuple[ParsedDocEntry, ...],
) -> tuple[DocumentedIssue, ...]:
    """Convert parsed docstring entries into issue models."""
    return tuple(
        DocumentedIssue(name=entry.name, description=entry.description)
        for entry in entries
        if entry.name
    )


def _validate_required_values(
    specs: dict[str, ParameterSpec | PortSpec],
    values: dict[str, Any],
    *,
    kind: str,
) -> None:
    """Raise when one required parameter/input is missing."""
    missing = [
        name for name, spec in specs.items() if spec.required and name not in values
    ]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"missing required {kind}(s): {joined}")


def _kwargs_from_named_specs(
    specs: dict[str, ParameterSpec | PortSpec],
    values: dict[str, Any],
) -> dict[str, Any]:
    """Return callable kwargs from currently provided named values."""
    return {name: values[name] for name in specs if name in values}
