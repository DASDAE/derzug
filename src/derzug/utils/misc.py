"""Utility helpers used across DerZug."""

from __future__ import annotations

import os
from functools import cache
from importlib.metadata import entry_points

import derzug.constants as constants

_EXAMPLE_WORKFLOWS_ENTRY = "orange.widgets.tutorials"


def _parse_csv_env(name: str, *, lower: bool = False) -> set[str]:
    """Return a normalized set from a comma-separated env var."""
    value = os.getenv(name, "")
    values = {item.strip() for item in value.split(",") if item.strip()}
    if lower:
        return {item.lower() for item in values}
    return values


@cache
def load_widget_entrypoints():
    """
    Load DerZug widget entry points only.
    """
    return tuple(
        sorted(
            (
                ep
                for ep in entry_points(group=constants.WIDGETS_ENTRY)
                if ep.dist.name.lower() == constants.PKG_NAME
            ),
            key=lambda ep: ep.name,
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
