"""Utility helpers used across DerZug."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from importlib.metadata import entry_points
from inspect import isclass

import derzug.constants as constants

_EXAMPLE_WORKFLOWS_ENTRY = "orange.widgets.tutorials"


def _parse_csv_env(name: str, *, lower: bool = False) -> set[str]:
    """Return a normalized set from a comma-separated env var."""
    value = os.getenv(name, "")
    values = {item.strip() for item in value.split(",") if item.strip()}
    if lower:
        return {item.lower() for item in values}
    return values


@dataclass(frozen=True)
class _LoaderEntryPoint:
    """Proxy an entry point while overriding ``load`` for Orange discovery."""

    entry_point: object
    loader: object

    def load(self):
        """Return the wrapped discovery-compatible loader."""
        return self.loader

    def __getattr__(self, name: str):
        """Delegate metadata fields to the original entry point."""
        return getattr(self.entry_point, name)


def _widget_loader_from_class(widget_class, dist_name: str | None):
    """Build an Orange discovery loader for class-based widget entry points."""

    def _loader(discovery):
        from orangecanvas.registry import WidgetDescription

        description = widget_class.get_widget_description()
        if description is None:
            return
        desc = WidgetDescription(**description)
        desc.package = widget_class.__module__.rsplit(".", 1)[0]
        desc.category = getattr(widget_class, "category", desc.category)
        if dist_name:
            desc.project_name = dist_name
        discovery.handle_widget(desc)

    return _loader


def _normalize_widget_entrypoint(entry_point):
    """Adapt widget-class entry points to Orange's discovery protocol."""
    try:
        point = entry_point.load()
    except Exception:
        return entry_point
    if isclass(point) and hasattr(point, "get_widget_description"):
        dist = getattr(entry_point, "dist", None)
        dist_name = getattr(dist, "name", None)
        return _LoaderEntryPoint(
            entry_point, _widget_loader_from_class(point, dist_name)
        )
    return entry_point


@cache
def load_widget_entrypoints():
    """
    Load DerZug widget entry points only.
    """
    return tuple(
        sorted(
            (
                _normalize_widget_entrypoint(entry_point)
                for entry_point in entry_points(group=constants.WIDGETS_ENTRY)
            ),
            key=lambda ep: 0 if ep.dist.name.lower() == constants.PKG_NAME else 1,
        )
    )


@cache
def load_example_workflow_entrypoints():
    """
    Load DerZug example workflow entry points only.
    """
    return tuple(
        sorted(
            (
                ep
                for ep in entry_points(group=_EXAMPLE_WORKFLOWS_ENTRY)
                if ep.dist.name.lower() == constants.PKG_NAME
            ),
            key=lambda ep: ep.name,
        )
    )
