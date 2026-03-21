"""Derzug workflow package.

This package is currently exposed lazily so ``import derzug.workflow`` stays
importable even while the workflow internals are mid-refactor.
"""

from __future__ import annotations

from importlib import import_module

__all__ = (
    "ExecutionContext",
    "FileSystemSink",
    "FileSystemSource",
    "Pipe",
    "Provenance",
    "Sink",
    "Source",
    "Task",
    "task",
)

_EXPORTS = {
    "ExecutionContext": (".context", "ExecutionContext"),
    "FileSystemSink": (".sink", "FileSystemSink"),
    "FileSystemSource": (".source", "FileSystemSource"),
    "Pipe": (".pipe", "Pipe"),
    "Provenance": (".provenance", "Provenance"),
    "Sink": (".sink", "Sink"),
    "Source": (".source", "Source"),
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
