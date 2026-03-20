"""
Base model for derzug.
"""

from __future__ import annotations

import warnings as _warnings
from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Widget metadata
# ---------------------------------------------------------------------------


class Meta(BaseModel):
    """
    Metadata about the model.

    Parameters
    ----------
    name : str
        Name of the model.
    description : str
        Description of the model.
    icon : str or None
        The name (or path) of the icon for the model.
    category : str
        Category of the model.
    keywords : tuple[str, ...]
        Keywords associated with the model.
    """

    name: str = ""
    description: str = ""
    icon: str | None = None
    category: str = "Misc"
    keywords: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class DerZugModel(BaseModel):
    """
    Base model for derzug.

    This is a stateful model for working with basic visualization and managing
    other source data. It also makes generating Orange widgets automatic.

    Pydantic instance fields declared on subclasses become UI controls.
    ClassVar fields (``meta``, ``errors``, ``warnings``, ``inputs``,
    ``outputs``) configure the widget's Orange metadata and signal contracts.
    """

    # Allow non-pydantic types (e.g. dascore objects) in ClassVar fields.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    meta: ClassVar[Meta] = Meta()

    # 'general' is a required fallback; subclasses that override these dicts
    # should include it so ZugWidget.run() always has a slot to fall back to.
    errors: ClassVar[Mapping[str, str]] = {
        "general": "An unexpected error occurred: {}",
    }
    warnings: ClassVar[Mapping[str, str]] = {
        "general": "An unexpected warning: {}",
    }

    # These define input/outputs for the widget dataflow (not user input).
    outputs: ClassVar[Mapping[str, type] | None] = None
    inputs: ClassVar[Mapping[str, type] | None] = None

    def __init_subclass__(cls, **kwargs):
        """Validate that custom errors/warnings dicts include the 'general' fallback."""
        super().__init_subclass__(**kwargs)
        # Only check dicts explicitly defined on this subclass, not inherited ones.
        for attr in ("errors", "warnings"):
            mapping = cls.__dict__.get(attr)
            if mapping is not None and "general" not in mapping:
                _warnings.warn(
                    f"{cls.__name__}.{attr} is missing the required 'general' "
                    f"fallback key. ZugWidget.run() uses it when an unrecognised "
                    f"key is raised.",
                    UserWarning,
                    stacklevel=2,
                )
