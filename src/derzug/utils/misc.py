"""Utility helpers used across DerZug."""

from __future__ import annotations

from functools import cache
from importlib.metadata import entry_points
from typing import Any

import derzug.constants as constants

_EXAMPLE_WORKFLOWS_ENTRY = "orange.widgets.tutorials"


def ordered_pair(first: Any, second: Any) -> tuple[Any, Any]:
    """Return the pair ordered low-to-high, unchanged when not comparable.

    Callers that need type normalization (e.g. numpy to pandas scalars) should
    apply it before calling this; the shared kernel only handles ordering.
    """
    try:
        return (first, second) if first <= second else (second, first)
    except Exception:
        return first, second


@cache
def load_entrypoints(group: str):
    """
    Load one entry-point group, DerZug's own entries first.

    The entry point group is the whole contract.  Do not also filter by
    distribution name, or external providers such as SlanRod's `derzug.widgets`
    entry point disappear from discovery.
    """
    return tuple(
        sorted(
            entry_points(group=group),
            key=lambda ep: 0 if ep.dist.name.lower() == constants.PKG_NAME else 1,
        )
    )


def load_widget_entrypoints():
    """
    Load DerZug widget entry points, including external providers.
    """
    return load_entrypoints(constants.WIDGETS_ENTRY)


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
