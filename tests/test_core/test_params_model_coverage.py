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

from derzug.core import ZugWidget
from derzug.utils.misc import load_widget_entrypoints

# Widgets not yet migrated to a pydantic params model. Remove each as it lands.
_PENDING = {
    "Aggregate",
    "Analytic",
    "Annotation2DataFrame",
    "Annotations",
    "Calculus",
    "Code",
    "Coords",
    "DataFrameLoader",
    "Detrend",
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
    "Taper",
    "UFuncBinary",
    "UFuncUnary",
    "Waterfall",
    "Wiggle",
}


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
