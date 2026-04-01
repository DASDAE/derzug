"""Helpers for turning Python callables into task-backed DerZug widgets."""

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

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.workflow import Task

_EMPTY = inspect.Signature.empty
_UNSET = object()
INPUTS_NOT_READY = _UNSET
_IDENT_RE = re.compile(r"\W+")


@dataclass(frozen=True)
class _WidgetInputSpec:
    """Internal metadata for one generated input signal."""

    name: str
    signal_name: str
    signal_type: type
    has_default: bool


@dataclass(frozen=True)
class _WidgetOutputSpec:
    """Internal metadata for one generated output signal."""

    name: str
    signal_name: str
    signal_type: type


@dataclass(frozen=True)
class _WidgetTaskSpec:
    """Internal callable metadata used to generate widget/task wrappers."""

    function_name: str
    inputs: tuple[_WidgetInputSpec, ...]
    outputs: tuple[_WidgetOutputSpec, ...]
    returns_dict: bool


def task_from_callable(
    fn,
    *,
    output_names: tuple[str, ...] | None = None,
) -> type[Task]:
    """Return a dynamic workflow task subclass for one callable."""
    if not callable(fn):
        raise TypeError("fn must be callable")
    spec = _spec_from_callable(fn, output_names=output_names)

    input_variables = {
        input_spec.signal_name: input_spec.signal_type for input_spec in spec.inputs
    }
    output_variables = {
        output_spec.signal_name: output_spec.signal_type for output_spec in spec.outputs
    }

    def run(self, **kwargs):
        values = _invoke_spec_function(spec, fn, kwargs)
        if values is INPUTS_NOT_READY:
            return INPUTS_NOT_READY
        if spec.returns_dict:
            return {
                output_spec.signal_name: values.get(output_spec.name)
                for output_spec in spec.outputs
            }
        if len(spec.outputs) == 1:
            return values
        if isinstance(values, tuple):
            return dict(
                zip(
                    (output_spec.signal_name for output_spec in spec.outputs),
                    values,
                    strict=True,
                )
            )
        return values

    class_namespace = {
        "__doc__": f"Generated task for {spec.function_name}.",
        "_original_function": fn,
        "__portable_adapter_factory__": "callable_task",
        "__task_code_path__": (
            f"{getattr(fn, '__module__', '__main__')}:"
            f"{getattr(fn, '__qualname__', spec.function_name)}"
        ),
        "input_variables": input_variables,
        "output_variables": output_variables,
        "run": run,
    }
    task_name = f"{_normalize_class_name(spec.function_name)}GeneratedTask"
    task_cls = type(task_name, (Task,), class_namespace)
    task_cls.__module__ = getattr(fn, "__module__", __name__)
    return task_cls


def widget_class_from_callable(
    *,
    fn,
    name: str,
    description: str,
    icon: str,
    category: str,
    priority: float | int,
    keywords: tuple[str, ...] = (),
    output_names: tuple[str, ...] | None = None,
) -> type[ZugWidget]:
    """Create a DerZug widget subclass from one callable."""
    if not callable(fn):
        raise TypeError("fn must be callable")
    spec = _spec_from_callable(fn, output_names=output_names)

    inputs_namespace: dict[str, object] = {"__doc__": "Input signal definitions."}
    outputs_namespace: dict[str, object] = {"__doc__": "Output signal definitions."}
    class_namespace: dict[str, object] = {
        "__doc__": f"Generated widget for {spec.function_name}.",
        "name": name,
        "description": description,
        "icon": icon,
        "category": category,
        "keywords": keywords,
        "priority": priority,
        "want_main_area": False,
        "_generated_function": staticmethod(fn),
        "_generated_spec": spec,
        "_generated_task_cls": task_from_callable(fn, output_names=output_names),
    }

    for input_spec in spec.inputs:
        signal = Input(input_spec.name, input_spec.signal_type, auto_summary=False)
        inputs_namespace[input_spec.signal_name] = signal

        def _make_handler(spec_name: str):
            def _handler(self, value):
                self._input_values[spec_name] = value
                self.run()

            return _handler

        class_namespace[f"set_{input_spec.signal_name}"] = signal(
            _make_handler(input_spec.signal_name)
        )

    for output_spec in spec.outputs:
        outputs_namespace[output_spec.signal_name] = Output(
            output_spec.name,
            output_spec.signal_type,
            auto_summary=False,
        )

    class Error(ZugWidget.Error):
        general = Msg("Generated widget failed: {}")

    class_namespace["Error"] = Error
    class_namespace["Inputs"] = type("Inputs", (), inputs_namespace)
    class_namespace["Outputs"] = type("Outputs", (), outputs_namespace)

    def _generated_init(self) -> None:
        super(generated_cls, self).__init__()
        self._input_values = {
            input_spec.signal_name: _UNSET for input_spec in self._generated_spec.inputs
        }

    def _supports_async_execution(self) -> bool:
        return True

    def _build_execution_request(self):
        ready_kwargs = _kwargs_from_input_values(
            self._generated_spec,
            self._input_values,
        )
        if ready_kwargs is INPUTS_NOT_READY:
            return None
        return WidgetExecutionRequest(
            workflow_obj=self.get_task(),
            input_values=ready_kwargs,
            output_names=tuple(
                output_spec.signal_name for output_spec in self._generated_spec.outputs
            ),
        )

    def get_task(self):
        return self._generated_task_cls()

    def _on_result(self, result) -> None:
        if result is _UNSET or result is None:
            for output_spec in self._generated_spec.outputs:
                getattr(self.Outputs, output_spec.signal_name).send(None)
            return
        if self._generated_spec.returns_dict or len(self._generated_spec.outputs) > 1:
            if not isinstance(result, dict):
                self._show_error_message("general", "expected mapping result")
                for output_spec in self._generated_spec.outputs:
                    getattr(self.Outputs, output_spec.signal_name).send(None)
                return
            for output_spec in self._generated_spec.outputs:
                getattr(self.Outputs, output_spec.signal_name).send(
                    result.get(output_spec.signal_name)
                )
            return
        output_spec = self._generated_spec.outputs[0]
        getattr(self.Outputs, output_spec.signal_name).send(result)

    class_namespace["__init__"] = _generated_init
    class_namespace["_supports_async_execution"] = _supports_async_execution
    class_namespace["_build_execution_request"] = _build_execution_request
    class_namespace["_on_result"] = _on_result
    class_namespace["get_task"] = get_task

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
    """Convenience wrapper that returns a task-backed widget class."""
    return widget_class_from_callable(
        fn=fn,
        name=name,
        description=description,
        icon=icon,
        category=category,
        priority=priority,
        keywords=keywords,
        output_names=output_names,
    )


def _invoke_spec_function(
    spec: _WidgetTaskSpec,
    fn,
    input_values: dict[str, object],
):
    """Invoke a callable using spec-defined readiness rules."""
    kwargs = _kwargs_from_input_values(spec, input_values)
    if kwargs is INPUTS_NOT_READY:
        return INPUTS_NOT_READY
    return fn(**kwargs)


def _spec_from_callable(
    fn,
    *,
    output_names: tuple[str, ...] | None = None,
) -> _WidgetTaskSpec:
    """Return internal widget/task metadata for one callable."""
    signature = inspect.signature(fn)
    type_hints = _safe_get_type_hints(fn)
    inputs: list[_WidgetInputSpec] = []

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
            _WidgetInputSpec(
                name=parameter.name,
                signal_name=_normalize_signal_name(parameter.name),
                signal_type=_resolve_signal_type(annotation),
                has_default=parameter.default is not _EMPTY,
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
            _WidgetOutputSpec(
                name=output_name,
                signal_name=_normalize_signal_name(output_name),
                signal_type=value_type,
            )
            for output_name in output_names
        )
        _validate_unique_signal_names(
            ((item.name, item.signal_name) for item in outputs),
            kind="output",
        )
    else:
        outputs = (
            _WidgetOutputSpec(
                name="result",
                signal_name="result",
                signal_type=_resolve_signal_type(return_annotation),
            ),
        )
    return _WidgetTaskSpec(
        function_name=getattr(fn, "__name__", "callable"),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        returns_dict=returns_dict,
    )


def _safe_get_type_hints(fn) -> dict[str, object]:
    try:
        return typing.get_type_hints(fn, globalns=getattr(fn, "__globals__", {}))
    except Exception:
        return dict(getattr(fn, "__annotations__", {}))


def _normalize_signal_name(name: str) -> str:
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
    spec: _WidgetTaskSpec,
    input_values: dict[str, object],
):
    kwargs: dict[str, object] = {}
    for input_spec in spec.inputs:
        value = input_values.get(input_spec.signal_name, _UNSET)
        if value is _UNSET:
            if input_spec.has_default:
                continue
            return INPUTS_NOT_READY
        kwargs[input_spec.name] = value
    return kwargs


def _normalize_class_name(name: str) -> str:
    parts = [part for part in _IDENT_RE.split(name.title()) if part]
    output = "".join(parts) or "GeneratedWidget"
    if output[0].isdigit():
        output = f"Widget{output}"
    return output


def _unwrap_optional(annotation: object) -> object:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, UnionType):
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _return_is_dict_like(annotation: object) -> tuple[bool, object]:
    annotation = _unwrap_optional(annotation)
    origin = typing.get_origin(annotation)
    if annotation is dict or origin is dict:
        args = typing.get_args(annotation)
        value_annotation = args[1] if len(args) == 2 else object
        return True, value_annotation
    return False, annotation


def _resolve_signal_type(annotation: object) -> type:
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


__all__ = [
    "INPUTS_NOT_READY",
    "function_to_widget",
    "task_from_callable",
    "widget_class_from_callable",
]
