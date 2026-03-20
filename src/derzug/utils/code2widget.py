"""Helpers for turning Python callables into DerZug widget classes."""

from __future__ import annotations

import inspect
import keyword
import re
import typing
from dataclasses import dataclass
from types import UnionType

import dascore as dc
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget

_EMPTY = inspect.Signature.empty
_UNSET = object()
INPUTS_NOT_READY = _UNSET
_IDENT_RE = re.compile(r"\W+")


@dataclass(frozen=True)
class WidgetInputSpec:
    """Normalized schema for one generated input signal."""

    name: str
    signal_name: str
    annotation: object
    signal_type: type
    has_default: bool
    default: object = _EMPTY


@dataclass(frozen=True)
class WidgetOutputSpec:
    """Normalized schema for one generated output signal."""

    name: str
    signal_name: str
    annotation: object
    signal_type: type


@dataclass(frozen=True)
class WidgetFunctionSchema:
    """Normalized callable schema used to generate a widget class."""

    function_name: str
    inputs: tuple[WidgetInputSpec, ...]
    outputs: tuple[WidgetOutputSpec, ...]
    returns_dict: bool


def invoke_schema_function(
    schema: WidgetFunctionSchema,
    fn,
    input_values: dict[str, object],
):
    """
    Invoke a callable using schema-defined input names and readiness rules.

    Unset required inputs return ``INPUTS_NOT_READY`` without calling the function.
    Unset optional inputs are omitted so Python defaults apply.
    """
    kwargs = _kwargs_from_input_values(schema, input_values)
    if kwargs is INPUTS_NOT_READY:
        return INPUTS_NOT_READY
    return fn(**kwargs)


def schema_from_function(
    fn,
    *,
    output_names: tuple[str, ...] | None = None,
) -> WidgetFunctionSchema:
    """Return a normalized widget schema for a callable."""
    if not callable(fn):
        raise TypeError("fn must be callable")

    signature = inspect.signature(fn)
    type_hints = _safe_get_type_hints(fn)
    inputs: list[WidgetInputSpec] = []

    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise ValueError("*args and **kwargs are not supported")
        if parameter.name == "self":
            continue

        annotation = type_hints.get(parameter.name, parameter.annotation)
        inputs.append(
            WidgetInputSpec(
                name=parameter.name,
                signal_name=_normalize_signal_name(parameter.name),
                annotation=annotation,
                signal_type=_resolve_signal_type(annotation),
                has_default=parameter.default is not _EMPTY,
                default=parameter.default,
            )
        )
    _validate_unique_signal_names(
        ((item.name, item.signal_name) for item in inputs),
        kind="input",
    )

    return_annotation = type_hints.get("return", signature.return_annotation)
    returns_dict, dict_value_annotation = _return_is_dict_like(return_annotation)

    if returns_dict:
        if not output_names:
            raise ValueError(
                "dict-like return annotations require explicit output_names"
            )
        value_type = _resolve_signal_type(dict_value_annotation)
        outputs = tuple(
            WidgetOutputSpec(
                name=name,
                signal_name=_normalize_signal_name(name),
                annotation=dict_value_annotation,
                signal_type=value_type,
            )
            for name in output_names
        )
        _validate_unique_signal_names(
            ((item.name, item.signal_name) for item in outputs),
            kind="output",
        )
    else:
        outputs = (
            WidgetOutputSpec(
                name="result",
                signal_name="result",
                annotation=return_annotation,
                signal_type=_resolve_signal_type(return_annotation),
            ),
        )

    return WidgetFunctionSchema(
        function_name=getattr(fn, "__name__", "callable"),
        inputs=tuple(inputs),
        outputs=outputs,
        returns_dict=returns_dict,
    )


def widget_class_from_schema(
    schema: WidgetFunctionSchema,
    *,
    fn,
    name: str,
    description: str,
    icon: str,
    category: str,
    priority: float | int,
    keywords: tuple[str, ...] = (),
) -> type[ZugWidget]:
    """Create a DerZug widget subclass from a callable schema."""
    if not callable(fn):
        raise TypeError("fn must be callable")

    inputs_namespace: dict[str, object] = {"__doc__": "Input signal definitions."}
    outputs_namespace: dict[str, object] = {"__doc__": "Output signal definitions."}
    class_namespace: dict[str, object] = {
        "__doc__": f"Generated widget for {schema.function_name}.",
        "name": name,
        "description": description,
        "icon": icon,
        "category": category,
        "keywords": keywords,
        "priority": priority,
        "want_main_area": False,
        "_generated_function": staticmethod(fn),
        "_generated_schema": schema,
    }

    for input_spec in schema.inputs:
        signal = Input(input_spec.name, input_spec.signal_type, auto_summary=False)
        inputs_namespace[input_spec.signal_name] = signal

        def _make_handler(spec_name: str):
            def _handler(self, value):
                self._input_values[spec_name] = value
                self.run()

            return _handler

        handler_name = f"set_{input_spec.signal_name}"
        class_namespace[handler_name] = signal(_make_handler(input_spec.signal_name))

    for output_spec in schema.outputs:
        outputs_namespace[output_spec.signal_name] = Output(
            output_spec.name,
            output_spec.signal_type,
            auto_summary=False,
        )

    class Error(ZugWidget.Error):
        """Errors shown by generated widget classes."""

        general = Msg("Generated widget failed: {}")

    class_namespace["Error"] = Error
    class_namespace["Inputs"] = type("Inputs", (), inputs_namespace)
    class_namespace["Outputs"] = type("Outputs", (), outputs_namespace)

    def _generated_init(self) -> None:
        super(generated_cls, self).__init__()
        self._input_values = {
            input_spec.signal_name: _UNSET
            for input_spec in self._generated_schema.inputs
        }

    def _run(self):
        return invoke_schema_function(
            self._generated_schema,
            self._generated_function,
            self._input_values,
        )

    def _on_result(self, result) -> None:
        if result is _UNSET:
            for output_spec in self._generated_schema.outputs:
                getattr(self.Outputs, output_spec.signal_name).send(None)
            return
        if self._generated_schema.returns_dict:
            if not isinstance(result, dict):
                self._show_error_message("general", "expected dict result")
                for output_spec in self._generated_schema.outputs:
                    getattr(self.Outputs, output_spec.signal_name).send(None)
                return
            for output_spec in self._generated_schema.outputs:
                value = result.get(output_spec.name)
                getattr(self.Outputs, output_spec.signal_name).send(value)
            return

        output_spec = self._generated_schema.outputs[0]
        getattr(self.Outputs, output_spec.signal_name).send(result)

    class_namespace["__init__"] = _generated_init
    class_namespace["_run"] = _run
    class_namespace["_on_result"] = _on_result

    generated_name = _normalize_class_name(name)
    generated_cls = type(
        generated_name,
        (ZugWidget,),
        class_namespace,
        openclass=True,
    )
    return generated_cls


def function_to_widget(
    fn,
    *,
    name: str,
    description: str,
    icon: str,
    category: str,
    priority: float | int,
    keywords: tuple[str, ...] = (),
    output_names: tuple[str, ...] | None = None,
) -> type[ZugWidget]:
    """Convenience wrapper that builds schema then returns a widget class."""
    schema = schema_from_function(fn, output_names=output_names)
    return widget_class_from_schema(
        schema,
        fn=fn,
        name=name,
        description=description,
        icon=icon,
        category=category,
        priority=priority,
        keywords=keywords,
    )


def _safe_get_type_hints(fn) -> dict[str, object]:
    """Return type hints when resolvable, else a best-effort fallback."""
    try:
        return typing.get_type_hints(fn, globalns=getattr(fn, "__globals__", {}))
    except Exception:
        return dict(getattr(fn, "__annotations__", {}))


def _normalize_signal_name(name: str) -> str:
    """Return a valid Orange signal identifier."""
    normalized = _IDENT_RE.sub("_", name).strip("_")
    if not normalized:
        normalized = "value"
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    if keyword.iskeyword(normalized):
        normalized = f"{normalized}_"
    return normalized


def _validate_unique_signal_names(
    pairs: typing.Iterable[tuple[str, str]],
    *,
    kind: str,
) -> None:
    """Raise when multiple names normalize to the same signal identifier."""
    normalized_to_originals: dict[str, list[str]] = {}
    for original, normalized in pairs:
        normalized_to_originals.setdefault(normalized, []).append(original)

    collisions = {
        normalized: originals
        for normalized, originals in normalized_to_originals.items()
        if len(originals) > 1
    }
    if not collisions:
        return

    normalized, originals = next(iter(collisions.items()))
    joined = ", ".join(repr(value) for value in originals)
    raise ValueError(
        f"{kind} names {joined} normalize to the same signal name {normalized!r}"
    )


def _kwargs_from_input_values(
    schema: WidgetFunctionSchema,
    input_values: dict[str, object],
):
    """
    Return callable kwargs or ``INPUTS_NOT_READY`` when required inputs are missing.
    """
    kwargs: dict[str, object] = {}
    for input_spec in schema.inputs:
        value = input_values.get(input_spec.signal_name, _UNSET)
        if value is _UNSET:
            if input_spec.has_default:
                continue
            return INPUTS_NOT_READY
        kwargs[input_spec.name] = value
    return kwargs


def _normalize_class_name(name: str) -> str:
    """Return a valid Python class name from display text."""
    parts = [part for part in _IDENT_RE.split(name.title()) if part]
    output = "".join(parts) or "GeneratedWidget"
    if output[0].isdigit():
        output = f"Widget{output}"
    return output


def _unwrap_optional(annotation: object) -> object:
    """Strip Optional / X | None wrappers, returning the inner type."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _return_is_dict_like(annotation: object) -> tuple[bool, object]:
    """Return True and the value annotation when the return is dict-like."""
    annotation = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    if annotation is dict or origin is dict:
        args = typing.get_args(annotation)
        value_annotation = args[1] if len(args) == 2 else object
        return True, value_annotation
    return False, annotation


def _resolve_signal_type(annotation: object) -> type:
    """Map a type annotation onto an Orange signal type."""
    annotation = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)

    if annotation in (_EMPTY, inspect._empty, None):
        return object
    if isinstance(annotation, str):
        return object
    if annotation in {dc.Patch, dc.BaseSpool, object, int, float, str, bool, dict}:
        return annotation
    if origin is dict:
        return dict
    if isinstance(annotation, type):
        return annotation
    return object
