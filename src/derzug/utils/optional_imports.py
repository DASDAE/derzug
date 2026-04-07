"""Helpers for optional runtime dependencies."""

from __future__ import annotations

from importlib import import_module


def optional_import(module_name: str):
    """Return an optional module or raise a clear dependency error."""
    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"{module_name} support requires the optional '{module_name}' dependency."
        ) from exc
