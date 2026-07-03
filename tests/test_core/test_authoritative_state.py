"""Authoritative-state widgets persist their models via the ``_state`` blob.

For widgets that set ``authoritative_state = True`` the pydantic models are the
sole persisted state: the per-param flat ``Setting``s are gone and the serialized
models round-trip through ``.ows`` in a single ``_state`` blob.
"""

from __future__ import annotations

import importlib
import inspect
import os
import tempfile

import pytest
from derzug.core import ZugWidget
from derzug.utils.misc import load_widget_entrypoints


def _authoritative_widget_classes() -> list:
    found = []
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
                and getattr(obj, "authoritative_state", False)
            ):
                found.append(pytest.param(obj, id=obj.__name__))
    return found


_AUTHORITATIVE = _authoritative_widget_classes()


@pytest.mark.parametrize("widget_cls", _AUTHORITATIVE)
def test_params_are_not_flat_settings(widget_cls, qtbot):
    """Authoritative widgets back params with the blob, not flat Settings."""
    from derzug.utils.testing import widget_context

    with widget_context(widget_cls) as widget:
        assert widget._is_setting("_state")
        for attr in widget._model_backed_attrs():
            assert not widget._is_setting(attr), f"{widget_cls.__name__}.{attr}"


@pytest.mark.parametrize("widget_cls", _AUTHORITATIVE)
def test_state_survives_ows_roundtrip(widget_cls, qtbot):
    """Applied params round-trip through a save/reload of the scheme."""
    from derzug.dascore import namespace as ns

    qualified = f"{widget_cls.__module__}.{widget_cls.__name__}"

    def _desc(window):
        for desc in window.widget_registry.widgets():
            if desc.qualified_name == qualified:
                return desc
        raise LookupError(qualified)

    window = ns._create_main_window()
    scheme = window.current_document().scheme()
    node = scheme.new_node(_desc(window), title="w", position=(0.0, 0.0))
    widget = scheme.widget_for_node(node)

    # Re-apply the current params so the widget is in a settled, known state.
    widget.apply_params(widget.get_params(), run=False)

    path = os.path.join(tempfile.mkdtemp(), "state_roundtrip.ows")
    window.save_scheme_to(scheme, path)
    # Capture after save: saving syncs controls and may normalize state (e.g.
    # Waterfall's unset ROI flag -> False), and that persisted form is what a
    # reload must reproduce.
    expected = widget.get_params()

    reloaded = ns._create_main_window()
    # Auto-accept the arbitrary-Python confirmation dialog (Code widget) that
    # would otherwise block a headless scheme load.
    reloaded.maybe_confirm_code_widget_load = lambda: True
    reloaded.load_scheme(path)
    reloaded_scheme = reloaded.current_document().scheme()
    restored = next(
        reloaded_scheme.widget_for_node(n)
        for n in reloaded_scheme.nodes
        if isinstance(reloaded_scheme.widget_for_node(n), widget_cls)
    )
    assert restored.get_params() == expected
