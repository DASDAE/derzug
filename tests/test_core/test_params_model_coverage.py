"""Track the pydantic params-model rollout across every ZugWidget.

Each widget should declare a ``params_model`` (the authoritative typed schema
for ``get_params``/``apply_params``). This test enforces that the only widgets
without one are the explicitly tracked pending ones — so converting a widget
forces it out of ``_PENDING``, and a new widget without a model is flagged.
``_PENDING`` shrinks to empty as the rollout completes.
"""

from __future__ import annotations

import importlib
import inspect

import pytest
from derzug.core import ZugWidget
from derzug.utils.misc import load_widget_entrypoints
from derzug.utils.testing import widget_context

# Widgets not yet migrated to a pydantic params model. Remove each as it lands.
_PENDING = {
    "Aggregate",
    "Annotation2DataFrame",
    "Annotations",
    "Calculus",
    "Code",
    "Coords",
    "DataFrameLoader",
    "FBE",
    "Fourier",
    "Normalize",
    "PatchViewer",
    "PlayAudio",
    "Resample",
    "Rolling",
    "Select",
    "Spool",
    "Stft",
    "Table2Annotation",
    "UFuncBinary",
    "Waterfall",
    "Wiggle",
}


# Widgets with presentation state that must declare a ``view_model``.
_VISUAL_WIDGETS = {"Waterfall", "Wiggle", "PatchViewer", "Spool"}

# Visual widgets not yet given a view model. Remove each as it lands.
_VIEW_PENDING = {"Waterfall", "Wiggle", "PatchViewer", "Spool"}


def _all_widget_classes() -> dict[str, type]:
    """Return every registered concrete ZugWidget class by name."""
    found: dict[str, type] = {}
    for entry_point in load_widget_entrypoints():
        try:
            module = importlib.import_module(entry_point.value)
        except Exception:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, ZugWidget)
                and obj.__module__ == entry_point.value
                and getattr(obj, "name", "")
            ):
                found[obj.__name__] = obj
    return found


def test_params_model_rollout_coverage():
    """Only the tracked pending widgets may lack a params model."""
    classes = _all_widget_classes()
    missing = {
        name
        for name, cls in classes.items()
        if getattr(cls, "params_model", None) is None
    }

    newly_missing = missing - _PENDING
    assert not newly_missing, (
        f"these widgets lack a params_model and are not tracked: "
        f"{sorted(newly_missing)} — declare a model or add to _PENDING"
    )

    now_covered = _PENDING - missing
    assert not now_covered, (
        f"these widgets now have a params_model: {sorted(now_covered)} — "
        f"remove them from _PENDING"
    )


def test_filter_is_covered():
    """Filter is the reference implementation and must stay covered."""
    classes = _all_widget_classes()
    assert getattr(classes["Filter"], "params_model", None) is not None


_MODELED = [
    pytest.param(cls, id=name)
    for name, cls in sorted(_all_widget_classes().items())
    if getattr(cls, "params_model", None) is not None
]


@pytest.mark.parametrize("widget_cls", _MODELED)
def test_params_roundtrip(widget_cls, qtbot):
    """Reading params and applying them back is a stable no-op for every model."""
    with widget_context(widget_cls) as widget:
        params = widget.get_params()
        widget.apply_params(params)
        assert widget.get_params() == params


def test_view_model_coverage():
    """Visual widgets declare a view_model; processing widgets do not."""
    classes = _all_widget_classes()
    has_view = {
        name
        for name, cls in classes.items()
        if getattr(cls, "view_model", None) is not None
    }

    # Non-visual widgets must not carry a view model.
    stray = has_view - _VISUAL_WIDGETS
    assert not stray, f"non-visual widgets declare a view_model: {sorted(stray)}"

    # Visual widgets either have a view model or are tracked as pending.
    missing = _VISUAL_WIDGETS - has_view
    assert missing == _VIEW_PENDING, (
        f"view-model coverage changed. covered: {sorted(_VIEW_PENDING - missing)}; "
        f"still missing: {sorted(missing)}. Update _VIEW_PENDING."
    )
