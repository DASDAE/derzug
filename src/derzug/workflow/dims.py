"""The shared convention for choosing a patch dimension.

Both a widget's dimension chooser and a task running headlessly have to answer
"which dimension did the user mean?" when the stored choice is blank or absent
from the incoming patch. They must answer it the same way, or the same node
produces different results on the canvas and off it — so both go through here.
"""

from __future__ import annotations

#: Preferred dimension when a node has no valid stored choice.
PREFERRED_DIM = "time"


def default_patch_dim(dims: tuple[str, ...]) -> str | None:
    """Return the fallback dimension for ``dims``, or ``None`` when empty."""
    if not dims:
        return None
    return PREFERRED_DIM if PREFERRED_DIM in dims else dims[0]


def resolve_patch_dim(requested: str | None, dims: tuple[str, ...]) -> str | None:
    """Return ``requested`` when it is one of ``dims``, else the fallback."""
    if requested and requested in dims:
        return requested
    return default_patch_dim(dims)


__all__ = ("PREFERRED_DIM", "default_patch_dim", "resolve_patch_dim")
