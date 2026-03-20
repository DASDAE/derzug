"""
Qt UI building and runtime dispatch for DerZug widgets.

This module contains all PyQt/Orange-specific logic that runs at widget
instantiation and execution time.  It is intentionally separated from the
metaclass injection code in ``core/zugwidget.py`` (which runs once at
class-definition time and has no Qt state) so that:

- The UI builder is independently importable and testable without a running
  Orange application.
- The Qt dependency boundary is explicit: everything in this file may import
  from AnyQt or Orange; nothing outside this file needs to.
"""

from __future__ import annotations

import enum as _enum
import typing
import warnings as _warnings
from collections.abc import Callable

from AnyQt.QtWidgets import QComboBox
from Orange.widgets import gui
from Orange.widgets.widget import OWWidget

from derzug.core.abstractcontrols import (
    AbstractControl,
    CheckboxControl,
    ComboControl,
    DoubleSpinControl,
    HiddenControl,
    LineEditControl,
    SkipControl,
    SpinControl,
    get_control,
)
from derzug.core.zugmodel import DerZugModel
from derzug.exceptions import DerZugError, DerZugWarning

# ---------------------------------------------------------------------------
# Field metadata helpers
# ---------------------------------------------------------------------------


def _get_field_label(field_name: str, field_info) -> str:
    """Return an auto-generated display label by converting snake_case to Title Case."""
    return field_name.replace("_", " ").title()


def _get_numeric_bounds(field_info) -> tuple[float, float]:
    """Extract ge/le bounds from pydantic field metadata for spin controls."""
    # Default to wide bounds; most DAS parameters won't need exact limits.
    min_val: float = -(2**31)
    max_val: float = 2**31 - 1
    for constraint in getattr(field_info, "metadata", []):
        if hasattr(constraint, "ge"):
            min_val = constraint.ge
        elif hasattr(constraint, "gt"):
            min_val = constraint.gt + 1
        if hasattr(constraint, "le"):
            max_val = constraint.le
        elif hasattr(constraint, "lt"):
            max_val = constraint.lt - 1
    return min_val, max_val


# ---------------------------------------------------------------------------
# Annotation helpers
# ---------------------------------------------------------------------------


def _unwrap_optional(annotation: type) -> type:
    """Strip Optional / X | None wrappers, returning the inner type."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        # Keep only non-None args; unwrap if exactly one remains.
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _get_literal_choices(annotation) -> list | None:
    """Return choices list if annotation is Literal[...], else None."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return list(typing.get_args(annotation))
    return None


def _get_enum_choices(annotation) -> list | None:
    """Return enum values if annotation is an Enum subclass, else None."""
    if isinstance(annotation, type) and issubclass(annotation, _enum.Enum):
        return [e.value for e in annotation]
    return None


# ---------------------------------------------------------------------------
# Layout helper
# ---------------------------------------------------------------------------


def _get_or_create_box(widget: OWWidget, group_name: str, boxes: dict):
    """Return an existing group box widget or create a new one in controlArea."""
    if group_name not in boxes:
        boxes[group_name] = gui.widgetBox(widget.controlArea, group_name)
    return boxes[group_name]


# ---------------------------------------------------------------------------
# Scalar control dispatch table
# ---------------------------------------------------------------------------

# Each builder receives (widget, field_name, field_info, label, box).
# bool must be registered before int because bool is a subclass of int, but
# dict lookup by type identity (not isinstance) means order doesn't matter here.
_SCALAR_BUILDERS: dict[type, Callable] = {}


def _register_scalar(t: type):
    """Decorator to register a scalar control builder for a given type."""

    def decorator(fn: Callable) -> Callable:
        _SCALAR_BUILDERS[t] = fn
        return fn

    return decorator


@_register_scalar(bool)
def _bool_control(widget, field_name, field_info, label, box):
    """Build a checkbox for a bool field."""
    gui.checkBox(box, widget, field_name, label, callback=widget.run)


@_register_scalar(int)
def _int_control(widget, field_name, field_info, label, box):
    """Build an integer spin box, respecting ge/le bounds."""
    min_val, max_val = _get_numeric_bounds(field_info)
    gui.spin(
        box,
        widget,
        field_name,
        int(min_val),
        int(max_val),
        label=label,
        callback=widget.run,
    )


@_register_scalar(float)
def _float_control(widget, field_name, field_info, label, box):
    """Build a float double-spin box, respecting ge/le bounds."""
    min_val, max_val = _get_numeric_bounds(field_info)
    gui.doubleSpin(
        box,
        widget,
        field_name,
        float(min_val),
        float(max_val),
        label=label,
        callback=widget.run,
    )


@_register_scalar(str)
def _str_control(widget, field_name, field_info, label, box):
    """Build a line-edit for a str field."""
    gui.lineEdit(box, widget, field_name, label=label, callback=widget.run)


# ---------------------------------------------------------------------------
# Control builders
# ---------------------------------------------------------------------------


def _build_combo_choices_control(
    widget: OWWidget,
    field_name: str,
    field_info,
    ctrl: ComboControl,
    model: DerZugModel,
    box,
) -> None:
    """
    Build a QComboBox for a dynamic-choices field.

    Uses ``ctrl.binds_to`` to find the widget attribute (an Orange Setting)
    that stores the currently selected value.  On selection change, updates
    that attribute and triggers widget.run().

    Parameters
    ----------
    widget : OWWidget
        The widget instance being built.
    field_name : str
        Name of the field providing the list of choices on the model.
    field_info
        Pydantic FieldInfo for the choices field.
    ctrl : ComboControl
        The abstract control descriptor for this field.
    model : DerZugModel
        The model instance (used to read the runtime choices list).
    box
        The parent container widget to add the combo into.
    """
    if not ctrl.binds_to:
        return

    # Read the runtime choices from the already-instantiated model.
    choices = list(getattr(model, field_name, []))
    label = ctrl.label or _get_field_label(field_name, field_info)

    gui.widgetLabel(box, label + ":")
    combo = QComboBox()
    combo.addItems(choices)
    box.layout().addWidget(combo)

    # Restore the previously persisted selection (from Orange Setting).
    current = getattr(widget, ctrl.binds_to, None)
    if current in choices:
        combo.setCurrentIndex(choices.index(current))
    elif choices:
        # No persisted selection; default to the first item.
        combo.setCurrentIndex(0)
        setattr(widget, ctrl.binds_to, choices[0])

    def _on_change(index: int) -> None:
        """Sync the bound attribute and trigger model execution."""
        value = choices[index] if 0 <= index < len(choices) else None
        setattr(widget, ctrl.binds_to, value)
        widget.run()

    combo.currentIndexChanged.connect(_on_change)


def _build_scalar_control(
    widget: OWWidget,
    field_name: str,
    annotation: type,
    field_info,
    ctrl: AbstractControl | None,
    box,
) -> None:
    """
    Build a scalar Qt control for a field based on its annotation.

    Dispatches to a registered builder via ``_SCALAR_BUILDERS``.  Literal and
    Enum annotations fall back to a combo box.  Unsupported annotations are
    skipped silently; developers can override ``__init__`` for custom controls.

    An explicit ``ctrl`` descriptor (e.g. ``SpinControl``) overrides the
    auto-detected widget type and can supply bounds directly via its attributes.

    Parameters
    ----------
    widget : OWWidget
        The widget instance being built.
    field_name : str
        Pydantic field name (also the Orange Setting attribute name).
    annotation : type
        The field's resolved annotation (may be Optional/Union).
    field_info
        Pydantic FieldInfo for the field.
    ctrl : AbstractControl or None
        Abstract control descriptor for this field, or None for auto-detection.
    box
        The parent container widget to add the control into.
    """
    # Strip Optional so int | None → int, str | None → str, etc.
    inner = _unwrap_optional(annotation)
    label = (
        ctrl.label if ctrl and ctrl.label else _get_field_label(field_name, field_info)
    )

    # Explicit control descriptors take precedence over type-based auto-detection.
    if isinstance(ctrl, SpinControl):
        gui.spin(
            box,
            widget,
            field_name,
            ctrl.min,
            ctrl.max,
            label=label,
            callback=widget.run,
        )
        return
    if isinstance(ctrl, DoubleSpinControl):
        gui.doubleSpin(
            box,
            widget,
            field_name,
            ctrl.min,
            ctrl.max,
            label=label,
            callback=widget.run,
        )
        return
    if isinstance(ctrl, CheckboxControl):
        gui.checkBox(box, widget, field_name, label, callback=widget.run)
        return
    if isinstance(ctrl, LineEditControl):
        gui.lineEdit(box, widget, field_name, label=label, callback=widget.run)
        return

    # Auto-detect from type annotation via the dispatch table.
    # Dict lookup is by type identity, so bool and int are distinct keys even
    # though bool is a subclass of int.
    builder = _SCALAR_BUILDERS.get(inner)
    if builder is not None:
        builder(widget, field_name, field_info, label, box)
        return

    # Literal[a, b, c] and Enum subclasses both render as combo boxes.
    choices = _get_literal_choices(inner) or _get_enum_choices(inner)
    if choices is not None:
        _build_static_combo_control(widget, field_name, choices, label, box)


def _build_static_combo_control(
    widget: OWWidget,
    field_name: str,
    choices: list,
    label: str,
    box,
) -> None:
    """
    Build a QComboBox for a static Literal or Enum field.

    Keeps original typed values in a closure so the widget Setting always
    stores the typed value (e.g. int, Enum member) rather than its string
    representation.  Mirrors the approach used by _build_combo_choices_control
    for dynamic choices.

    Parameters
    ----------
    widget : OWWidget
        The widget instance being built.
    field_name : str
        Pydantic field name (also the Orange Setting attribute name).
    choices : list
        The original typed choice values (from Literal args or Enum members).
    label : str
        Display label for the control.
    box
        The parent container widget to add the control into.
    """
    gui.widgetLabel(box, label + ":")
    combo = QComboBox()
    # Display strings; typed originals are kept in the closure.
    combo.addItems([str(c) for c in choices])
    box.layout().addWidget(combo)

    # Restore the previously persisted selection.
    current = getattr(widget, field_name, None)
    if current in choices:
        combo.setCurrentIndex(choices.index(current))
    elif choices:
        # No persisted value; default to the first typed choice.
        combo.setCurrentIndex(0)
        setattr(widget, field_name, choices[0])

    def _on_change(index: int) -> None:
        """Store the typed value (not the display string) and trigger run."""
        value = choices[index] if 0 <= index < len(choices) else None
        setattr(widget, field_name, value)
        widget.run()

    combo.currentIndexChanged.connect(_on_change)


# ---------------------------------------------------------------------------
# Full UI builder
# ---------------------------------------------------------------------------


def _build_ui(model: DerZugModel, widget: OWWidget) -> None:
    """
    Build Qt controls in widget.controlArea for each pydantic instance field.

    Groups fields by their control descriptor's ``group`` attribute (default:
    ``"Parameters"``). Fields annotated with ``HiddenControl`` or ``SkipControl``
    are omitted. Fields annotated with ``ComboControl`` render as a managed
    QComboBox linked to a companion selection Setting.

    Parameters
    ----------
    model : DerZugModel
        The widget's model instance (already copied for this widget).
    widget : OWWidget
        The widget being initialized.
    """
    # include_extras=True preserves Annotated wrappers so get_control can
    # extract AbstractControl descriptors from field annotations.
    hints = typing.get_type_hints(type(model), include_extras=True)
    # Group boxes created lazily, keyed by group name.
    boxes: dict[str, object] = {}

    for field_name, field_info in type(model).model_fields.items():
        annotation = hints.get(field_name)
        if annotation is None:
            continue

        ctrl = get_control(annotation)

        # Hidden and skip fields have no visible control.
        if isinstance(ctrl, HiddenControl | SkipControl):
            continue

        group = ctrl.group if ctrl else "Parameters"
        box = _get_or_create_box(widget, group, boxes)

        if isinstance(ctrl, ComboControl):
            # Combo box populated from the runtime field value.
            _build_combo_choices_control(
                widget, field_name, field_info, ctrl, model, box
            )
        else:
            _build_scalar_control(widget, field_name, annotation, field_info, ctrl, box)


# ---------------------------------------------------------------------------
# Settings sync
# ---------------------------------------------------------------------------


def _sync_settings_to_model(widget: OWWidget) -> None:
    """
    Copy Orange Setting values from the widget instance into its model.

    Called before each run() so pydantic stays the source of truth for
    validation while Orange owns persistence across sessions.
    """
    model = widget.model
    hints = typing.get_type_hints(type(model), include_extras=True)
    for field_name in type(model).model_fields:
        # Combo choices lists are recomputed at runtime; never overwrite them.
        if isinstance(get_control(hints.get(field_name)), ComboControl):
            continue
        if hasattr(widget, field_name):
            setattr(model, field_name, getattr(widget, field_name))


# ---------------------------------------------------------------------------
# Error / warning routing
# ---------------------------------------------------------------------------


def _route_error(widget: OWWidget, exc: DerZugError) -> None:
    """Activate the named Orange Error slot that matches the exception key."""
    # Fall back to 'general' if the key isn't a known slot on this widget.
    slot = getattr(widget.Error, exc.key, widget.Error.general)
    slot(*exc.fmt_args)


def _route_warnings(widget: OWWidget, issued: list) -> None:
    """Activate Orange Warning slots for all DerZugWarning instances collected."""
    for w in issued:
        if not issubclass(w.category, DerZugWarning):
            continue
        warn_obj = w.message
        slot = getattr(widget.Warning, warn_obj.key, None)
        if slot is not None:
            slot(*warn_obj.fmt_args)


# ---------------------------------------------------------------------------
# Output dispatch
# ---------------------------------------------------------------------------


def _send_outputs(widget: OWWidget, result) -> None:
    """
    Dispatch a model result to the widget's declared output signals.

    For a single-output model the result is sent directly. For multiple
    outputs the result must be a dict keyed by output name.  If a multi-output
    model returns a non-dict value, a ``RuntimeWarning`` is issued and all
    outputs receive ``None``.

    Parameters
    ----------
    widget : OWWidget
        The widget whose Outputs signals should be sent.
    result
        The value(s) returned by model.__call__(), or None on error.
    """
    outputs = widget.model.outputs
    if not outputs:
        return

    output_names = list(outputs.keys())
    if len(output_names) == 1:
        # Single output: send the value directly.
        getattr(widget.Outputs, output_names[0]).send(result)
        return

    # Multiple outputs: result must be a dict keyed by output name.
    if result is not None and not isinstance(result, dict):
        _warnings.warn(
            f"Multi-output model returned {type(result).__name__!r} instead of a "
            f"dict keyed by output name. All outputs will be sent as None.",
            RuntimeWarning,
            stacklevel=2,
        )
        result = None

    result_dict = result or {}
    for name in output_names:
        getattr(widget.Outputs, name).send(result_dict.get(name))
