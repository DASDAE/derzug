"""
DERZUG utility module.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "INPUTS_NOT_READY": ("derzug.utils.code2widget", "INPUTS_NOT_READY"),
    "format_display": ("derzug.utils.display", "format_display"),
    "function_to_widget": ("derzug.utils.code2widget", "function_to_widget"),
    "parse_patch_text_value": (
        "derzug.utils.parsing",
        "parse_patch_text_value",
    ),
    "parse_text_value": ("derzug.utils.parsing", "parse_text_value"),
    "task_from_callable": ("derzug.utils.code2widget", "task_from_callable"),
    "widget_class_from_callable": (
        "derzug.utils.code2widget",
        "widget_class_from_callable",
    ),
}

__all__ = [
    "INPUTS_NOT_READY",
    "format_display",
    "function_to_widget",
    "parse_patch_text_value",
    "parse_text_value",
    "task_from_callable",
    "widget_class_from_callable",
]


def __getattr__(name: str):
    """Load public utility exports only when callers request them."""
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to interactive discovery."""
    return sorted(set(globals()) | set(__all__))
