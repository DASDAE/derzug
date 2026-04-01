"""Derzug workflow package.

This package is currently exposed lazily so ``import derzug.workflow`` stays
importable even while the workflow internals are mid-refactor.
"""

from __future__ import annotations

from importlib import import_module

__all__ = (
    "CompiledWorkflow",
    "compile_workflow",
    "FileSystemSource",
    "Pipe",
    "PipeBuilder",
    "Provenance",
    "Results",
    "Source",
    "STREAM_END",
    "Task",
    "task",
)

_EXPORTS = {
    "CompiledWorkflow": (".compiler", "CompiledWorkflow"),
    "compile_workflow": (".compiler", "compile_workflow"),
    "FileSystemSource": (".source", "FileSystemSource"),
    "Pipe": (".pipe", "Pipe"),
    "PipeBuilder": (".graph", "PipeBuilder"),
    "Provenance": (".provenance", "Provenance"),
    "Results": (".results", "Results"),
    "Source": (".source", "Source"),
    "STREAM_END": (".executor", "STREAM_END"),
    "Task": (".task", "Task"),
    "task": (".task", "task"),
}


def __getattr__(name: str):
    """Load workflow symbols lazily."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
