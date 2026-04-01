"""
Task definitions for the streaming workflow engine.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import textwrap
from collections.abc import Callable
from functools import cached_property
from typing import Any, ClassVar, Self, get_args, get_origin, get_type_hints

from .model import WorkflowFrozenModel


def _get_callable_source_hash(target: Any) -> str:
    """Return a stable hash for a class or function body."""
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        source = (
            f"{getattr(target, '__module__', '')}:"
            f"{getattr(target, '__qualname__', '')}"
        )
    source = textwrap.dedent(source)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _get_code_path(target: Any) -> str:
    """Return a stable import path for a function or class."""
    return f"{target.__module__}:{target.__qualname__}"


def _extract_return_names(func: Callable) -> tuple[str, ...] | None:
    """Infer output names from a simple return statement."""
    try:
        source = textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None
    try:
        module_ast = ast.parse(source)
    except SyntaxError:
        return None
    func_nodes = [
        node
        for node in ast.walk(module_ast)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if not func_nodes:
        return None
    return_nodes = [
        node for node in ast.walk(func_nodes[0]) if isinstance(node, ast.Return)
    ]
    if len(return_nodes) != 1:
        return None
    expr = return_nodes[0].value
    if expr is None:
        return ("output",)
    if isinstance(expr, ast.Name):
        return (expr.id,)
    if isinstance(expr, ast.Tuple) and all(isinstance(x, ast.Name) for x in expr.elts):
        return tuple(x.id for x in expr.elts)
    return None


def _annotation_to_mapping(
    annotation: Any, names: tuple[str, ...] | None, default_single: str = "output"
) -> dict[str, Any]:
    """Convert a return annotation into named outputs."""
    if annotation in (inspect.Signature.empty, Any):
        if names:
            return {name: Any for name in names}
        return {default_single: Any}

    origin = get_origin(annotation)
    if origin is tuple:
        args = get_args(annotation)
        if len(args) == 2 and args[-1] is Ellipsis:
            if names and len(names) == 1:
                return {names[0]: annotation}
            return {default_single: annotation}
        if names and len(names) == len(args):
            return dict(zip(names, args, strict=True))
        return {f"output_{index}": arg for index, arg in enumerate(args)}

    if names and len(names) == 1:
        return {names[0]: annotation}
    return {default_single: annotation}


def _unwrap_generator_types(annotation: Any) -> tuple[Any | None, Any | None]:
    """Return (yield_type, return_type) for a generator annotation."""
    origin = get_origin(annotation)
    if origin is None:
        return (None, None)
    origin_name = getattr(origin, "__qualname__", str(origin))
    if "Generator" not in origin_name:
        return (None, None)
    args = get_args(annotation)
    if len(args) != 3:
        return (Any, Any)
    return (args[0], args[2])


class Task(WorkflowFrozenModel):
    """
    Base class for workflow tasks.

    Tasks are immutable workflow specifications. Runtime state belongs to the
    execution engine, not the task instance itself.
    """

    __version__: ClassVar[str] = "1.0"
    input_variables: ClassVar[dict[str, Any] | None] = None
    output_variables: ClassVar[dict[str, Any] | None] = None
    stream_inputs: ClassVar[dict[str, Any] | None] = None
    stream_outputs: ClassVar[dict[str, Any] | None] = None
    final_output: ClassVar[str | None] = None
    _original_function: ClassVar[Callable | None] = None
    _registered_tasks: ClassVar[list[type[Task]]] = []
    __task_code_path__: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs):
        """Register concrete subclasses."""
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            Task._registered_tasks.append(cls)

    @classmethod
    def code_path(cls) -> str:
        """Return the import path used for serialization."""
        if cls.__task_code_path__ is not None:
            return cls.__task_code_path__
        target = cls._original_function or cls
        return _get_code_path(target)

    @classmethod
    def _run_target(cls) -> Callable:
        """Return the callable to use for static run introspection."""
        return cls._original_function or cls.run

    @classmethod
    def scalar_input_variables(cls) -> dict[str, Any]:
        """Return scalar input ports for this task."""
        if cls.input_variables is not None:
            return dict(cls.input_variables)
        target = cls._run_target()
        sig = inspect.signature(target)
        stream_names = set((cls.stream_inputs or {}).keys())
        hints = get_type_hints(target)
        out = {}
        for name, param in sig.parameters.items():
            if name == "self" or name in stream_names:
                continue
            annotation = hints.get(name, param.annotation)
            out[name] = Any if annotation is inspect.Signature.empty else annotation
        return out

    @classmethod
    def stream_input_variables(cls) -> dict[str, Any]:
        """Return stream input ports for this task."""
        return dict(cls.stream_inputs or {})

    @classmethod
    def required_scalar_inputs(cls) -> tuple[str, ...]:
        """Return scalar inputs that must be bound before activation."""
        sig = inspect.signature(cls._run_target())
        scalar_names = set(cls.scalar_input_variables())
        required = []
        for name, param in sig.parameters.items():
            if name == "self" or name not in scalar_names:
                continue
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return tuple(required)

    @classmethod
    def stream_output_variables(cls) -> dict[str, Any]:
        """Return stream output ports for this task."""
        return dict(cls.stream_outputs or {})

    @classmethod
    def scalar_output_variables(cls) -> dict[str, Any]:
        """Return scalar output ports for this task."""
        if cls.output_variables is not None:
            return dict(cls.output_variables)

        target = cls._original_function or cls.run
        hints = get_type_hints(target)
        annotation = hints.get("return", inspect.signature(target).return_annotation)
        _, return_type = _unwrap_generator_types(annotation)
        names = _extract_return_names(target)
        if cls.stream_outputs:
            stream_names = tuple(cls.stream_outputs.keys())
            scalar_names = tuple(
                name for name in (names or ()) if name not in stream_names
            )
            if cls.final_output is not None:
                final_type = Any if return_type is None else return_type
                return {cls.final_output: final_type}
            if scalar_names and return_type is not None:
                return _annotation_to_mapping(return_type, scalar_names)
            return {}
        return _annotation_to_mapping(annotation, names)

    @classmethod
    def validate_ports(cls) -> None:
        """Validate the declared or inferred task interface."""
        if len(cls.stream_input_variables()) > 1:
            raise ValueError(
                f"{cls.__name__} may not declare more than one stream input"
            )
        if len(cls.stream_output_variables()) > 1:
            raise ValueError(
                f"{cls.__name__} may not declare more than one stream output"
            )
        if (
            cls.final_output is not None
            and cls.final_output not in cls.scalar_output_variables()
        ):
            raise ValueError(
                f"{cls.__name__}.final_output={cls.final_output!r} "
                "is not declared in output_variables"
            )
        if cls.stream_output_variables() and not inspect.isgeneratorfunction(
            cls._run_target()
        ):
            raise ValueError(
                f"{cls.__name__} declares stream_outputs but run() "
                "is not a generator"
            )

    def resolved_scalar_input_variables(self) -> dict[str, Any]:
        """Return scalar input ports for this task instance."""
        return type(self).scalar_input_variables()

    def resolved_stream_input_variables(self) -> dict[str, Any]:
        """Return stream input ports for this task instance."""
        return type(self).stream_input_variables()

    def resolved_required_scalar_inputs(self) -> tuple[str, ...]:
        """Return required scalar input ports for this task instance."""
        return type(self).required_scalar_inputs()

    def resolved_scalar_output_variables(self) -> dict[str, Any]:
        """Return scalar output ports for this task instance."""
        return type(self).scalar_output_variables()

    def resolved_stream_output_variables(self) -> dict[str, Any]:
        """Return stream output ports for this task instance."""
        return type(self).stream_output_variables()

    def validate_instance_ports(self) -> None:
        """Validate the effective instance-level task interface."""
        if len(self.resolved_stream_input_variables()) > 1:
            raise ValueError(
                f"{type(self).__name__} may not declare more than one stream input"
            )
        if len(self.resolved_stream_output_variables()) > 1:
            raise ValueError(
                f"{type(self).__name__} may not declare more than one stream output"
            )
        if (
            self.final_output is not None
            and self.final_output not in self.resolved_scalar_output_variables()
        ):
            raise ValueError(
                f"{type(self).__name__}.final_output={self.final_output!r} "
                "is not declared in output_variables"
            )
        if self.resolved_stream_output_variables() and not inspect.isgeneratorfunction(
            type(self)._run_target()
        ):
            raise ValueError(
                f"{type(self).__name__} declares stream_outputs but run() "
                "is not a generator"
            )

    @classmethod
    def is_stream_producer(cls) -> bool:
        """Return True when the task yields streamed outputs."""
        return bool(cls.stream_output_variables())

    @classmethod
    def is_stream_consumer(cls) -> bool:
        """Return True when the task accepts a streamed input."""
        return bool(cls.stream_input_variables())

    @classmethod
    def uses_generator_runtime(cls) -> bool:
        """Return True when the task runtime is generator-backed."""
        return inspect.isgeneratorfunction(cls._run_target())

    @cached_property
    def fingerprint(self) -> str:
        """Return a stable task fingerprint."""
        payload = {
            "code_path": self.code_path(),
            "code_hash": _get_callable_source_hash(
                self._original_function or self.__class__
            ),
            "version": self.__version__,
            "parameters": self.model_dump(mode="json"),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

    def run(self, *args, **kwargs) -> Any:
        """Execute the task."""
        raise NotImplementedError("Subclasses must implement run")

    def update(self, **kwargs) -> Self:
        """Return a modified copy of the task."""
        return self.model_copy(update=kwargs)

    def __or__(self, other):
        """Support task | task syntax."""
        from .graph import PipeBuilder

        builder = PipeBuilder()
        left = builder.add(self)
        right = builder.add(other)
        builder.connect(left, right)
        return builder.build()

    def __ror__(self, other):
        return NotImplemented


class RunMethodDescriptor:
    """Descriptor for dynamically created function-based task run methods."""

    def __init__(
        self,
        func: Callable,
        field_names: list[str],
        param_defaults: dict[str, Any],
    ):
        self.func = func
        self.field_names = field_names
        self.param_defaults = param_defaults

    def __get__(self, instance, owner):
        if instance is None:
            return self

        sig = inspect.signature(self.func)

        def run_method_impl(*args, **kwargs):
            combined_kwargs = _resolve_task_parameters(
                instance, self.field_names, self.param_defaults, sig, args, kwargs
            )
            return self.func(**combined_kwargs)

        run_method_impl.__signature__ = sig
        return run_method_impl


def _resolve_task_parameters(
    task: Task,
    field_names: list[str],
    param_defaults: dict[str, Any],
    sig: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Resolve fields and call-time arguments for a function task."""
    combined_kwargs = dict(param_defaults)
    task_data = task.model_dump()
    for field_name in field_names:
        if field_name in task_data:
            combined_kwargs[field_name] = task_data[field_name]
    sig_params = list(sig.parameters.keys())
    for index, arg in enumerate(args):
        if index < len(sig_params):
            combined_kwargs[sig_params[index]] = arg
    combined_kwargs.update(kwargs)
    return combined_kwargs


def _create_function_task_class(func: Callable, version: str) -> type[Task]:
    """Create a dynamic Task subclass from a Python function."""
    sig = inspect.signature(func)
    field_names = [
        name
        for name, param in sig.parameters.items()
        if param.default is not inspect.Parameter.empty
    ]
    param_defaults = {
        name: param.default
        for name, param in sig.parameters.items()
        if param.default is not inspect.Parameter.empty
    }
    descriptor = RunMethodDescriptor(func, field_names, param_defaults)
    annotations: dict[str, Any] = {
        "__version__": ClassVar[str],
        "_original_function": ClassVar[Callable],
        "__task_code_path__": ClassVar[str],
        "run": ClassVar[RunMethodDescriptor],
    }
    attrs: dict[str, Any] = {
        "__version__": version,
        "_original_function": func,
        "__task_code_path__": _get_code_path(func),
        "__doc__": func.__doc__,
        "run": descriptor,
    }
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            continue
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = Any
        annotations[name] = annotation
        attrs[name] = param.default
    attrs["__annotations__"] = annotations
    class_name = f"{func.__name__.title().replace('_', '')}Task"
    task_cls = type(class_name, (Task,), attrs)
    task_cls.__module__ = func.__module__
    if "<locals>" not in getattr(func, "__qualname__", ""):
        try:
            module = importlib.import_module(func.__module__)
        except Exception:
            module = None
        if module is not None:
            setattr(module, class_name, task_cls)
    return task_cls


def task(
    func: Callable | None = None, *, version: str = "1.0"
) -> type[Task] | Callable:
    """Decorator to turn a function into a Task subclass."""

    def decorator(inner: Callable) -> type[Task]:
        return _create_function_task_class(inner, version)

    if func is None:
        return decorator
    return decorator(func)
