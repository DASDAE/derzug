"""Registry filtering and category styling for DerZug's Orange integration."""

from __future__ import annotations

import types
from pathlib import Path

from orangecanvas.registry import WidgetRegistry
from orangecanvas.registry.description import CategoryDescription

import derzug.constants as constants
from derzug.utils.misc import load_widget_entrypoints

_CATEGORY_STYLES = {
    "IO": {"icon": "Category-Data.svg", "background": "#DCEEFF", "priority": 10},
    "Table": {"icon": "Table.svg", "background": "#EAF3FF", "priority": 15},
    "Processing": {"icon": "Transform.svg", "background": "#FFE8CC", "priority": 20},
    "Transform": {"icon": "Fourier.svg", "background": "#FFF3D6", "priority": 21},
    "Visualize": {"icon": "Colors.svg", "background": "#E6F7E6", "priority": 30},
}


def _entrypoint_qualified_names() -> set[str]:
    """Return normalized qualified names registered under ``derzug.widgets``."""
    from orangewidget.workflow.discovery import widget_desc_from_module

    qualified_names = set()
    for entry_point in load_widget_entrypoints():
        module = getattr(entry_point, "module", "")
        attr = getattr(entry_point, "attr", "")
        if module and attr:
            qualified_names.add(f"{module}.{attr}")
            continue
        try:
            point = entry_point.load()
        except Exception:
            continue
        if isinstance(point, types.ModuleType):
            try:
                qualified_names.add(widget_desc_from_module(point).qualified_name)
            except Exception:
                continue
    return qualified_names


def _register_category(
    output: WidgetRegistry, icons_dir: Path, category_name: str, priority: int
) -> None:
    """Register a category, styling known DerZug categories when possible."""
    style = _CATEGORY_STYLES.get(category_name)
    kwargs = {"name": category_name}
    if style is not None:
        kwargs["icon"] = str(icons_dir / style["icon"])
        kwargs["background"] = style["background"]
        kwargs["priority"] = style["priority"]
    else:
        kwargs["priority"] = priority
    output.register_category(CategoryDescription(**kwargs))


def filter_registry_for_das(registry: WidgetRegistry) -> WidgetRegistry:
    """
    Return a DAS-focused widget registry.

    This keeps all widgets exposed via the ``derzug.widgets`` entry-point group
    and any explicitly allowed Orange widgets.
    """
    output = WidgetRegistry()
    icons_dir = Path(__file__).parent.parent / "widgets" / "icons"
    registered_widget_qnames = _entrypoint_qualified_names()
    kept_widgets = []
    for widget in registry.widgets():
        qualified_name = getattr(widget, "qualified_name", "") or getattr(
            widget, "id", ""
        )
        name = widget.name
        is_registered_widget = qualified_name in registered_widget_qnames
        if not is_registered_widget and name not in constants.ORANGE_WIDGETS_TO_LOAD:
            continue
        if "obsolete" in widget.id:
            continue
        kept_widgets.append(widget)

    known_categories = [
        category_name
        for category_name in _CATEGORY_STYLES
        if any(widget.category == category_name for widget in kept_widgets)
    ]
    extra_categories = sorted(
        {
            widget.category
            for widget in kept_widgets
            if widget.category and widget.category not in _CATEGORY_STYLES
        }
    )
    for priority, category_name in enumerate(
        [*known_categories, *extra_categories], start=10
    ):
        _register_category(output, icons_dir, category_name, priority)

    for widget in kept_widgets:
        output.register_widget(widget)
    return output
