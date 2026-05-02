"""Registry filtering and category styling for DerZug's Orange integration."""

from __future__ import annotations

from pathlib import Path

from orangecanvas.registry import WidgetRegistry
from orangecanvas.registry.description import CategoryDescription

import derzug.constants as constants

_CATEGORY_STYLES = {
    "IO": {"icon": "Category-Data.svg", "background": "#DCEEFF", "priority": 10},
    "Table": {"icon": "Table.svg", "background": "#EAF3FF", "priority": 15},
    "Processing": {"icon": "Transform.svg", "background": "#FFE8CC", "priority": 20},
    "Transform": {"icon": "Fourier.svg", "background": "#FFF3D6", "priority": 21},
    "Visualize": {"icon": "Colors.svg", "background": "#E6F7E6", "priority": 30},
}


def filter_registry_for_das(registry: WidgetRegistry) -> WidgetRegistry:
    """
    Return a DAS-focused widget registry.

    This keeps all DerZug widgets and the Orange ones explicitly named.
    """
    output = WidgetRegistry()
    icons_dir = Path(__file__).parent.parent / "widgets" / "icons"
    for category_name, style in _CATEGORY_STYLES.items():
        icon_path = icons_dir / style["icon"]
        output.register_category(
            CategoryDescription(
                name=category_name,
                icon=str(icon_path),
                background=style["background"],
                priority=style["priority"],
            )
        )
    for widget in registry.widgets():
        package = (getattr(widget, "package", "") or "").lower()
        name = widget.name
        is_derzug_widget = package == constants.PKG_NAME or package.startswith(
            f"{constants.PKG_NAME}."
        )
        if not is_derzug_widget and name not in constants.ORANGE_WIDGETS_TO_LOAD:
            continue
        if "obsolete" in widget.id:
            continue
        output.register_widget(widget)
    return output
