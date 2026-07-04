"""Guard that every bundled example workflow loads and uses the current format.

Bundled ``.ows`` files ship with the package (Help -> Load Example Workflow). If
one is saved in the old flat-``Setting`` layout, it still *loads* fine but
silently restores default parameters under authoritative storage. These tests
fail if a bundled workflow stops loading, or still stores parameters as flat
settings instead of the ``_state`` blob — so the migration can't silently rot.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from xml.etree import ElementTree

import derzug
import pytest
from derzug.core import ZugWidget
from derzug.utils.testing import widget_context

_WORKFLOWS_DIR = Path(derzug.__file__).parent / "workflows"
_BUNDLED = sorted(_WORKFLOWS_DIR.glob("*.ows"))
_IDS = [p.name for p in _BUNDLED]


def _load_widget_class(qualified_name: str) -> type:
    module_name, class_name = qualified_name.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), class_name)


def _node_properties(path: Path):
    """Yield ``(qualified_name, properties_dict)`` for each node in an .ows file."""
    root = ElementTree.parse(path).getroot()
    nid_qn = {n.get("id"): n.get("qualified_name") for n in root.iter("node")}
    for props in root.iter("properties"):
        yield nid_qn[props.get("node_id")], ast.literal_eval(props.text)


def test_bundled_workflows_exist():
    """There is at least one bundled example workflow to check."""
    assert _BUNDLED, f"no .ows files found under {_WORKFLOWS_DIR}"


@pytest.mark.parametrize("path", _BUNDLED, ids=_IDS)
def test_bundled_workflow_loads(path, make_window, qtbot):
    """Every bundled workflow loads headlessly and its widgets restore params."""
    window = make_window()
    # Skip the arbitrary-Python confirmation dialog (a Code widget would block).
    window.maybe_confirm_code_widget_load = lambda: True
    window.load_scheme(str(path))

    scheme = window.current_document().scheme()
    assert scheme.nodes, f"{path.name} loaded no nodes"
    for node in scheme.nodes:
        widget = scheme.widget_for_node(node)
        assert widget is not None, f"{path.name}: no widget for node {node.title!r}"
        if getattr(widget, "authoritative_state", False):
            widget.get_params()  # typed params restore without error


@pytest.mark.parametrize("path", _BUNDLED, ids=_IDS)
def test_bundled_workflow_uses_state_blob(path):
    """Bundled workflows store parameters in the ``_state`` blob, not flat settings.

    Catches a workflow saved before the authoritative-storage migration, which
    would otherwise load silently with default parameters.
    """
    for qualified_name, props in _node_properties(path):
        cls = _load_widget_class(qualified_name)
        if not (
            issubclass(cls, ZugWidget) and getattr(cls, "authoritative_state", False)
        ):
            continue
        with widget_context(cls) as widget:
            model_backed = widget._model_backed_attrs()
        stale = model_backed & set(props)
        assert not stale, (
            f"{path.name}: node {qualified_name} stores stale flat params "
            f"{sorted(stale)} at top level; re-save the workflow to migrate it"
        )
        assert (
            "_state" in props
        ), f"{path.name}: node {qualified_name} has no _state blob; re-save it"
