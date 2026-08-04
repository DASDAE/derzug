"""Qt-free callable introspection shared by generated widgets and tasks.

Turning a plain Python function into a DerZug node needs two things: a
normalized description of its signature (:func:`_spec_from_callable`) and a
task that calls it (:func:`task_from_callable`). Both are pure Python, so they
live here rather than in :mod:`derzug.utils.code2widget`, which builds the Qt
widget around them.
"""

from __future__ import annotations

import inspect
import keyword
import re
import typing
from dataclasses import dataclass
from types import UnionType

import dascore as dc

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


__all__ = ("INPUTS_NOT_READY", "task_from_callable")
