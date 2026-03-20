"""
Task definitions and task-related functionality for the workflow engine.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from functools import cached_property
from typing import Any, ClassVar, Self

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from pydantic import ConfigDict

from ..core import SlanRodBaseModel
from ..utils.misc import get_class_ast_hash


class Task(SlanRodBaseModel):
    """
    Base class for workflow tasks.

    Tasks are immutable, validated operations that can be uniquely identified
    by their parameters through fingerprinting.
    """

    model_config = ConfigDict(extra="forbid")

    __version__: str = "1.0"
    _registered_tasks: ClassVar[list[type[Task]]] = []

    def __init_subclass__(cls, **kwargs):
        """Register new subclasses."""
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            Task._registered_tasks.append(cls)
        return cls

    @cached_property
    def fingerprint(self) -> str:
        """
        Return a unique ID based on the task's class code, version, and input
        parameters.

        Combines AST hash of the class (ignoring comments/docstrings) with
        task version and serialized model parameters for consistent identification
        across runs.
        """
        # Get model phase_shift_validator as dict, excluding any cached properties
        param_data = self.model_dump(mode="json")

        # Get class AST hash
        class_hash = get_class_ast_hash(self.__class__)

        # Combine class, version, and parameter phase_shift_validator
        combined_data = {
            "class_hash": class_hash,
            "version": self.__version__,
            "parameters": param_data,
        }

        # Sort keys for consistent ordering and generate hash
        json_str = json.dumps(combined_data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()[
            :16
        ]  # First 16 chars for brevity

    def run(self, *args, **kwargs) -> Any:
        """
        Execute the task. Override this method in subclasses.

        Parameters
        ----------
        **kwargs
            Input parameters for the task execution.

        Returns
        -------
        Any
            Task output.
        """
        raise NotImplementedError("Subclasses must implement the run method")

    def is_streaming(self) -> bool:
        """
        Check if this task generates streaming results.

        Returns True if the run method is a generator function,
        False for regular tasks that return single results.
        """
        # For function-based tasks, check the original function
        if hasattr(self, "_original_function"):
            return inspect.isgeneratorfunction(self._original_function)
        # For class-based tasks, check the run method directly
        return inspect.isgeneratorfunction(self.run)

    def plot(self, *args, **kwargs) -> Figure:
        """
        Function to perform standard processing but plot for debugging.

        This is mainly useful for debugging during pipeline development.
        The default implementation just calls run() and returns an empty figure.

        Parameters
        ----------
        **kwargs
            Input parameters for the task execution.

        Returns
        -------
        Figure
            Matplotlib figure for debugging.
        """
        self.run(*args, **kwargs)
        return plt.figure()

    # Pipe operator support
    def __or__(self, other):
        """Support task | other_task syntax."""
        from .pipe import Pipe

        return Pipe._create_pipe_from_single_task(self, other)

    def __ror__(self, other):
        """Support other | task syntax."""
        from .pipe import Pipe

        if isinstance(other, dict | tuple | list):
            return Pipe._create_multi_input_pipe(other, self)
        else:
            return NotImplemented

    def update(self, **kwargs) -> Self:
        """Update some part of the task and return new task."""
        contents = self.model_dump()
        contents.update(kwargs)
        return self.__class__(**contents)


class RunMethodDescriptor:
    """Descriptor for dynamically created run methods in function tasks."""

    def __init__(self, func: Callable, param_names: list[str], param_defaults: dict):
        self.func = func
        self.param_names = param_names
        self.param_defaults = param_defaults

    def __get__(self, instance, owner):
        """Return bound method for the instance."""
        if instance is None:
            return self

        sig = inspect.signature(self.func)

        def run_method_impl(*args, **kwargs):
            combined_kwargs = _resolve_task_parameters(
                instance, self.param_names, self.param_defaults, sig, args, kwargs
            )
            return self.func(**combined_kwargs)

        # Preserve the original function signature on the bound method
        run_method_impl.__signature__ = sig
        return run_method_impl


def _resolve_task_parameters(
    task: Task,
    param_names: list[str],
    param_defaults: dict,
    sig: inspect.Signature,
    args: tuple,
    kwargs: dict,
) -> dict:
    """
    Resolve parameters for function-based tasks.

    Combines task field values, positional args, keyword args, and defaults
    into a single kwargs dict for function execution.
    """
    # Start with task field values and defaults
    combined_kwargs = dict(param_defaults)

    # Add task field values (these override defaults)
    task_data = task.model_dump()
    for param_name in param_names:
        if param_name in task_data:
            combined_kwargs[param_name] = task_data[param_name]

    # Add positional arguments
    sig_params = list(sig.parameters.keys())
    for i, arg in enumerate(args):
        if i < len(sig_params):
            param_name = sig_params[i]
            combined_kwargs[param_name] = arg

    # Add keyword arguments (these have highest priority)
    combined_kwargs.update(kwargs)

    return combined_kwargs


def _create_function_task_class(
    func: Callable, sig: inspect.Signature, version: str, run_descriptor
) -> type[Task]:
    """Create a dynamic Task subclass from a function."""
    # Build class attributes dict
    class_attrs = {
        "__version__": version,
        "_original_function": func,
        "__doc__": func.__doc__,
        "run": run_descriptor,
    }

    # Create annotations dict for Pydantic
    annotations = {
        "__version__": str,
        "_original_function": ClassVar[Callable],
        "run": ClassVar[RunMethodDescriptor],
    }

    # Add function parameters as Pydantic fields
    for param_name, param in sig.parameters.items():
        if param.annotation != inspect.Parameter.empty:
            # Use type annotation if available, make optional
            try:
                annotations[param_name] = param.annotation | type(None)
            except TypeError:
                # Handle string annotations or other types that don't support |
                annotations[param_name] = Any | type(None)
            if param.default != inspect.Parameter.empty:
                class_attrs[param_name] = param.default
            else:
                # Required parameter - will be set via pydantic
                class_attrs[param_name] = None  # Will be validated by pydantic
        else:
            # No annotation, use Any and make optional
            annotations[param_name] = Any | type(None)
            if param.default != inspect.Parameter.empty:
                class_attrs[param_name] = param.default
            else:
                class_attrs[param_name] = None

    class_attrs["__annotations__"] = annotations

    # Create dynamic class
    class_name = f"{func.__name__.title().replace('_', '')}Task"
    return type(class_name, (Task,), class_attrs)


def task(func: Callable | None = None, *, version: str = "1.0") -> Task | Callable:
    """
    Decorator to convert a function into a Task class.

    Parameters
    ----------
    func : Callable, optional
        Function to convert to a task.
    version : str, default "1.0"
        Version string for the task.

    Returns
    -------
    Task or Callable
        Task instance if used as @task, decorator function if used as @task().

    Examples
    --------
    >>> @task
    >>> def add_numbers(a: int, b: int) -> int:
    ...     return a + b

    >>> @task(version="2.0")
    >>> def multiply(x: float, y: float = 2.0) -> float:
    ...     return x * y
    """

    def decorator(f: Callable) -> type[Task]:
        sig = inspect.signature(f)

        # Extract parameter info
        param_names = list(sig.parameters.keys())
        param_defaults = {
            name: param.default
            for name, param in sig.parameters.items()
            if param.default != inspect.Parameter.empty
        }

        # Create run method descriptor
        run_descriptor = RunMethodDescriptor(f, param_names, param_defaults)

        # Create the task class
        task_class = _create_function_task_class(f, sig, version, run_descriptor)

        return task_class

    if func is None:
        # Called as @task(version="...")
        return decorator
    else:
        # Called as @task
        return decorator(func)
