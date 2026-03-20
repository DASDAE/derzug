"""
Abstract UI control descriptors for DerZug models.

Each subclass of ``AbstractControl`` represents a specific kind of UI widget
(checkbox, spin box, combo box, …) with typed, IDE-discoverable parameters.
Controls are attached to pydantic fields via ``Annotated`` metadata::

    from typing import Annotated
    from derzug.core.abstractcontrols import ComboControl, HiddenControl

    class MyModel(DerZugModel):
        choices: Annotated[list[str], ComboControl(binds_to="selection")] = Field(...)
        selection: Annotated[str | None, HiddenControl()] = None

The mapping from abstract controls to Qt widgets lives entirely in
``derzug.utils.pyqt_ui_builder``, keeping this module free of Qt imports.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass
class AbstractControl:
    """
    Base class for all abstract UI control descriptors.

    Parameters
    ----------
    label : str or None
        Override the auto-generated label (default: snake_case → Title Case).
    group : str
        Name of the ``gui.widgetBox`` section to place the control in.
    """

    label: str | None = None
    group: str = "Parameters"


# ---------------------------------------------------------------------------
# Concrete control types
# ---------------------------------------------------------------------------


@dataclass
class HiddenControl(AbstractControl):
    """Persist as an Orange Setting but render no visible widget."""


@dataclass
class SkipControl(AbstractControl):
    """Neither persisted nor displayed — completely ignored by the UI builder."""


@dataclass
class ComboControl(AbstractControl):
    """
    Dynamic-choices combo box.

    The field holding this control provides the list of choices at runtime.
    ``binds_to`` names the companion Setting field that stores the selection.

    Parameters
    ----------
    binds_to : str
        Name of the sibling field (and Orange Setting) that holds the
        currently selected value.
    """

    binds_to: str = ""


@dataclass
class CheckboxControl(AbstractControl):
    """Boolean checkbox."""


@dataclass
class SpinControl(AbstractControl):
    """
    Integer spin box.

    Parameters
    ----------
    min : int
        Minimum allowed value.
    max : int
        Maximum allowed value.
    """

    min: int = -(2**31)
    max: int = 2**31 - 1


@dataclass
class DoubleSpinControl(AbstractControl):
    """
    Floating-point double-spin box.

    Parameters
    ----------
    min : float
        Minimum allowed value.
    max : float
        Maximum allowed value.
    """

    min: float = float(-(2**31))
    max: float = float(2**31 - 1)


@dataclass
class LineEditControl(AbstractControl):
    """Single-line text entry."""


# ---------------------------------------------------------------------------
# Extraction helper
# ---------------------------------------------------------------------------


def get_control(annotation) -> AbstractControl | None:
    """
    Extract the first ``AbstractControl`` from an ``Annotated`` annotation.

    Returns ``None`` if the annotation carries no control descriptor, or if
    the annotation is not an ``Annotated`` type.

    Parameters
    ----------
    annotation
        A type annotation, possibly ``Annotated[T, ..., AbstractControl, ...]``.

    Examples
    --------
    >>> from typing import Annotated
    >>> get_control(Annotated[int, SpinControl(min=0, max=100)])
    SpinControl(label=None, group='Parameters', min=0, max=100)
    >>> get_control(int) is None
    True
    """
    for meta in typing.get_args(annotation):
        if isinstance(meta, AbstractControl):
            return meta
    return None
